"""The seekable history of one game: keyframes, time series and events.

A :class:`Timeline` is fed :class:`~vantage.frames.Frame` objects in game
order -- live from the game or from a ``.vrec`` -- and maintains everything the
UI asks about:

* a **keyframe** (a compressed :func:`vantage.world.view`) every
  :data:`KEYFRAME_MS` of game time, so any moment can be shown without
  re-simulating -- this is what makes seek, skip and bookmarks free;
* per-player **time series** every :data:`SERIES_MS` (economy, army, kills,
  exploration, APM ...) for the graphs and the statistics screen;
* a categorised **event log** (kills, research, training, age-ups, chat,
  tribute, market, conversions, wonders/relics, regicide and King of the Hill
  alerts, victory countdowns);
* the static **match info** and **map** layer;
* per-entity logs (activity, damage, kills, conversions) and a per-player log
  of master statistics, for the unit panel at any moment.

The game streams forward patches only, so history is kept as view keyframes
rather than reverse patches.

**APM.** A player's commands are counted over a sliding :data:`APM_WINDOW_MS`
of game time; AI bookkeeping commands (:data:`_NON_ACTIONS`) never count.
*Effective* APM (eAPM, the end screen's geAPM) additionally drops spam: a unit
order (move, work, attack ...) whose kind, units, target and destination tile
equal the same player's previous unit order issued less than
:data:`EAPM_REPEAT_MS` earlier. Production, research, build and economy
commands always count, because repeating them queues more work.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import json
import threading
import time as _time
import zlib
from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from vantage import world as W
from vantage.combat_review import PressureTracker, PressureWorker, military_review
from vantage.frames import Frame
from vantage.gamedata import GameData
from vantage.healing_review import HealingHistory
from vantage.patch import Node, Patcher, PatchError
from vantage.resource_review import ResourceHistory

KEYFRAME_MS = 1000
#: Encoded ``/api/view`` responses kept per timeline (:meth:`Timeline.view_json`):
#: about 300 KB each late in an 8-player game.
VIEW_CACHE_SIZE = 64
#: Decoded keyframes kept for the unit and group panels (:meth:`Timeline.keyframe_at`).
DECODED_CACHE_SIZE = 4
#: How often (game ms) the forest layer is compared and stored when changed: a
#: felled tree stays drawn at most this long.
TREES_MS = 3_000
#: Keyframes between two :func:`settle_heap` calls during ingestion. What the
#: game adds after the snapshot (new units, buildings, logs) piles up in the
#: collector's oldest generation: late in an 8-player game each full collection
#: took ~59 ms, 59 of them in 5 game minutes (16 % of ingestion). Freezing it
#: every 30 keyframes kept them at ~7 ms (0.07 s of settling per 5 minutes).
SETTLE_KEYFRAMES = 30
#: Master statistics the group panel compares per unit type (:meth:`Timeline.group_stats`).
GROUP_STAT_KEYS = (
    "hp",
    "attack",
    "melee_armor",
    "pierce_armor",
    "range",
    "speed",
    "reload",
    "cost",
)
#: Projectiles are sampled at most this often (game ms) between keyframes.
MISSILE_MS = 100
#: Unit movement between keyframes is sampled this often (stream frames allowing).
#: Against the game's own positions on a 100 ms recording, 100 ms against 250 ms:
#: 90th-percentile path error 0.025 against 0.039 tiles (1 s snapshots alone: 0.144),
#: for twice the storage (11 MB for 22 minutes of a 6-player game).
UNIT_TRACK_MS = 100
#: How often (game ms) the live tile terrain is compared and stored when changed.
TERRAIN_MS = 3_000
SERIES_MS = 5000
APM_WINDOW_MS = 60_000
#: The keys of a player's ``collected`` and ``collected_rate`` (per-minute) dicts.
COLLECTED_KEYS = (*W.RESOURCE_NAMES, "total")
#: A repeated identical unit order within this many game-ms is spam (eAPM).
EAPM_REPEAT_MS = 2000
#: One game "year" in game milliseconds (event texts count durations in years).
YEAR_MS = 5000
#: A King status (attacked, refuge attacked, threatened) lapses this long after
#: its last renewal; until then it is re-announced only when the attacking
#: player changes.
KING_STATUS_MS = 15_000
#: A King notification repeating (owner, King, kind) within this window is
#: dropped from the log (an attacker learned later is filled into the first).
KING_MERGE_MS = 20_000
#: King threat search: ranged units within this many tiles (and with the King
#: inside their weapon range), else melee units within the melee radius.
KING_THREAT_RANGED_TILES = 18.0
KING_THREAT_MELEE_TILES = 3.0
#: A refuge below this share of its hit points forces the King out.
KING_FORCED_HP = 0.2
#: Transport ships: a King inside one has *boarded* rather than garrisoned.
TRANSPORT_MASTERS = frozenset({545, 1735})
#: Monastery masters (relic events select the owner's monasteries).
MONASTERY_MASTERS = frozenset({104, 30, 31, 32})
#: Successive market trades of one player and resource merge within this window.
MARKET_MERGE_MS = 2000
#: Treason (game command 10) counts only when the player could pay for it.
TREASON_GOLD = 400
TREASON_COMMAND = 10
#: A diplomacy change after this long in the old stance is high priority and
#: says how long the old stance lasted.
DIPLOMACY_LONG_MS = 100 * YEAR_MS
#: A monument holder this close to victory makes a seizure high priority.
KOTH_CLOSE_MS = 100 * YEAR_MS
#: ``Relation.unitDiplomacy`` -> stance name (other values are not stances).
UNIT_DIPLOMACY = {2: "ally", 3: "neutral", 4: "enemy"}
#: ``Relation.enumValue`` -> ``unitDiplomacy`` code, for streams without it.
_ENUM_TO_UNIT_DIPLOMACY = {0: 2, 1: 3, 2: 3, 3: 4}
_P_RUIN = W._fid("Player", "ruinHeldTime")
_REL_UNIT_DIPLOMACY = W._fid("Relation", "unitDiplomacy")
_GO_TEAMS_LOCKED = W._fid("GameOptions", "teamsLocked")
_VP_ID = W._fid("VictoryPointEntry", "id")
#: ``victoryPointMap`` entry ids behind the score sub-rows (score tooltip).
_VP_EXPLORATION, _VP_RESEARCH, _VP_UNITS_BUILDINGS = 7, 30, 29
_VP_RESOURCES_BANKED = (24, 25, 26, 4)
#: Masters never counted in "most created" (game data: not real units).
MOST_CREATED_EXCLUDED = frozenset({1252, 1253})
#: An Oracle chat and the same chat from the frame stream are one message when
#: they are this close in game time (frames lag by the spectator delay).
CHAT_MATCH_MS = 300_000
#: Victory countdown milestones announced as events (in the countdown's own
#: unit, game years).
COUNTDOWN_MILESTONES = (500, 400, 300, 200, 100, 50, 25, 10)

#: Commands that are bookkeeping rather than player actions (AI scripts emit
#: thousands of these, the game issues the automatic ones); they do not count
#: towards APM.
_NON_ACTIONS = frozenset(
    {
        "game",
        "aiorder",
        "unitaistate",
        "unittypeaistate",
        "raw",
        "giveattributesrge",
        "pseudotech",
        "fillselection",
    }
)
#: Command kinds that move or fight with units; the rest is economy/macro.
_MILITARY_COMMANDS = frozenset(
    {
        "interact",
        "move",
        "attackmove",
        "attackmovetarget",
        "attackground",
        "patrol",
        "guard",
        "follow",
        "formformation",
        "aboutfaceformation",
        "breakformation",
        "lockformation",
        "formationparameters",
        "autoformations",
        "stop",
        "unitorder",
        "scout",
        "stance",
        "groupwaypoint",
        "addwaypoint",
    }
)
#: Commands that are military or economy by the class of the units they name.
_BY_SELECTION = frozenset({"seekshelter", "buildingcommandqueue", "fireactiveability"})
#: Unit orders: repeating one unchanged has no effect (eAPM drops the repeat).
_UNIT_ORDERS = _MILITARY_COMMANDS | frozenset(
    {"work", "repair", "unload", "setgatherpoint", "retreat", "explore", "seekshelter"}
)
#: Command fields that do not change what an order does.
_ORDER_NOISE = frozenset({"commplayerid", "instant", "extend", "humanorder", "controlheld"})

#: Event categories (the UI filters by these).
CATEGORIES = (
    "combat",
    "train_research",
    "age",
    "chat",
    "tribute",
    "market",
    "conversion",
    "victory",
    "diplomacy",
    "status",
    "king",
    "countdown",
)

#: Event kinds the UI shows in its highlighted (high-priority) area. Kinds whose
#: priority depends on the case (a forced ungarrison, a diplomacy change after
#: a long stance, a seizure from a holder close to victory) set ``priority``
#: themselves; King garrisoning and voluntary ungarrisoning are low.
HIGH_PRIORITY = frozenset(
    {
        "king_attacked",
        "king_threatened",
        "king_killed",
        "refuge_attacked",
        "treason",
        "countdown",
        "wonder_started",
        "wonder_completed",
        "wonder_destroyed",
        "relics_held",
        "relics_lost",
        "ruins_held",
        "ruins_lost",
        "resigned",
        "dropped",
        "won",
        "lost",
    }
)

#: Per-player running totals the timeline derives from events.
_TALLY_KEYS = (
    "eco_kills",
    "eco_deaths",
    "tribute_sent",
    "market_bought",
    "market_sold",
    "market_gold_gained",
    "market_gold_spent",
)


@dataclass(slots=True)
class Keyframe:
    time: int
    blob: bytes  # zlib(JSON view)


@dataclass
class Timeline:
    data: GameData
    patcher: Patcher = field(default_factory=Patcher)
    catalog: W.Catalog = field(init=False)
    keyframes: list[Keyframe] = field(default_factory=list)
    series: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    events: list[dict[str, Any]] = field(default_factory=list)
    match: dict[str, Any] = field(default_factory=dict)
    map: dict[str, Any] | None = None
    fog: list[tuple[int, bytes]] = field(default_factory=list)
    trees: list[tuple[int, bytes, list[int]]] = field(default_factory=list)
    #: Live tile terrain (one byte per tile), stored when it changes: the game
    #: repaints tiles under farms, pastures, foundations and buildings.
    terrain: list[tuple[int, bytes]] = field(default_factory=list)
    sprites: dict[int, tuple[str, int, int, float]] = field(default_factory=dict)
    #: Per-entity activity changes: entity id -> [(time, activity code)].
    activity_log: dict[int, list[tuple[int, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    #: Per-entity combat log: entity id -> [(time, kind, amount, other master)].
    #: Kinds: dealt, taken, kill, eco_kill, friendly_kill, died, convert,
    #: convert_eco, heresy. ``other master`` is the target's (dealt) or the
    #: attacker's (taken) master id, else -1.
    unit_log: dict[int, list[tuple[int, str, float, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    #: (owner, master id) -> [(time, master_detail)] whenever the owner's master
    #: statistics change (upgrades, civilisation bonuses).
    master_log: dict[tuple[int, int], list[tuple[int, dict[str, Any]]]] = field(
        default_factory=dict
    )
    #: Per-entity (time, owner, master id, source private/player/missing, private detail).
    #: Removed entities retain their last known stats; reuse/reset appends its current source.
    entity_master_log: dict[int, list[tuple[int, int, int, str, dict[str, Any] | None]]] = field(
        default_factory=dict
    )
    #: Last known (owner, master id) of every entity seen, dead ones included.
    entity_meta: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: Stream discontinuities: ``[from_ms, to_ms]`` where the game skipped timesteps.
    skips: list[list[int]] = field(default_factory=list)
    #: The game reported its end (``World.gameEnded``) at the newest keyframe.
    game_ended: bool = False
    time: int = 0
    frames: int = 0
    errors: int = 0
    complete: bool = False
    #: Bumped on every keyframe so long-poll/SSE clients can wait for change.
    version: int = 0

    def __post_init__(self) -> None:
        self.catalog = W.Catalog(self.data)
        self.resource_history = ResourceHistory(self.data)
        self.healing_history = HealingHistory(self._kill_groups_of)
        self._lock = threading.RLock()
        self._next_key = 0
        #: Game ms between keyframes. A live session widens it while it cannot keep
        #: up with the game's stream (fast replay of a large late game).
        self.keyframe_step_ms = KEYFRAME_MS
        self._next_series = 0
        self._next_fog = 0
        self._next_trees = 0
        self._next_terrain = 0
        self._last_terrain: bytes | None = None
        self._last_trees: tuple[bytes, list[int]] | None = None
        #: Projectile tracks by keyframe time (zlib JSON), and the one being filled.
        self.missiles: dict[int, bytes] = {}
        self._missile_buf: list[Any] = []
        self._last_missile = -1
        self._missile_kf = -1
        self._next_missile = 0
        #: Unit movement tracks by keyframe time (zlib JSON), the one being filled,
        #: and the units followed (id -> last position) since the last keyframe.
        self.unit_tracks: dict[int, bytes] = {}
        self._track_buf: list[Any] = []
        self._track_kf = -1
        self._next_track = 0
        self._track_pos: dict[int, tuple[float, float, int]] = {}
        self._apm: dict[int, deque[tuple[int, bool, bool]]] = defaultdict(deque)
        self._apm_total: dict[int, int] = defaultdict(int)
        self._eapm_total: dict[int, int] = defaultdict(int)
        self._apm_peak: dict[int, int] = defaultdict(int)
        self._last_order: dict[int, tuple[str, int]] = {}
        self._prev_age: dict[int, int] = {}
        self._prev_status: dict[int, str] = {}
        self._prev_dip: dict[int, dict[str, str]] = {}
        self._peak_army: dict[int, float] = defaultdict(float)
        self._ages: dict[int, dict[int, int]] = defaultdict(dict)
        self._last_view: dict[str, Any] | None = None
        self._prev_key_t = -1
        self._prev_frame_t = -1
        self._act_total: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._act_window: dict[str, deque[tuple[int, dict[str, int], float]]] = defaultdict(deque)
        #: player -> (keyframe time, ``collected`` then) over the last APM_WINDOW_MS
        self._col_window: dict[str, deque[tuple[int, dict[str, int]]]] = defaultdict(deque)
        self._tc_idle: dict[str, float] = defaultdict(float)
        self._housed: dict[str, float] = defaultdict(float)
        self._housed_since: dict[str, int] = {}
        self._relics_max: dict[str, int] = defaultdict(int)
        self._tallies: dict[int, dict[str, float]] = defaultdict(
            lambda: dict.fromkeys(_TALLY_KEYS, 0.0)
        )
        #: killer entity id -> times of its kills (for "most kills")
        self._kills_by_unit: dict[int, list[int]] = defaultdict(list)
        #: King id -> (garrisoned, inside); refuge building id -> (King owner, King id)
        self._kings: dict[int, tuple[bool, int]] = {}
        self._refuges: dict[int, tuple[int, int]] = {}
        #: King id -> its last seen ``kings`` row (for a death nobody announced)
        self._king_rows: dict[int, dict[str, Any]] = {}
        #: Kings whose killing blow was seen; owner -> where/when its King died
        self._kings_killed: set[int] = set()
        # (target, monk owner) conversions already shown: repeats are skipped.
        self._conversions_seen: set[tuple[int, int]] = set()
        self._king_deaths: dict[int, dict[str, Any]] = {}
        #: (kind, King id) -> (attacking player, last renewal ms) of a King status
        self._king_status: dict[tuple[str, int], tuple[int | None, int]] = {}
        #: refuge id -> last attacker (unit ref) while a King was inside; hp share
        self._refuge_attacker: dict[int, dict[str, Any] | None] = {}
        self._refuge_hp: dict[int, float] = {}
        self._koth: tuple[int, int] | None = None  # (owner, since ms)
        self._koth_required: int | None = None
        #: The monument holder's time left before victory at the last keyframe.
        self._koth_remaining: int | None = None
        #: player -> ``Player.ruinHeldTime`` at the last keyframe
        self._ruin: dict[int, float] = {}
        #: (author, target) -> ``unitDiplomacy`` code, and when it last changed
        self._stance: dict[tuple[int, int], int] = {}
        self._stance_now: dict[tuple[int, int], int] = {}
        self._stance_since: dict[tuple[int, int], int] = {}
        #: Chats seen on only one path so far (Oracle / frame), to pair them up.
        self._chats_oracle: list[tuple[int, Any, str]] = []
        self._chats_frame: list[tuple[int, Any, str]] = []
        #: master id -> unit-line key (``unitlines.json``), loaded on first use
        self._unit_lines: dict[int, str] | None = None
        #: The running victory countdown: (victory kind, player) and last value
        self._countdown: tuple[str, int] | None = None
        self._countdown_prev: float | None = None
        #: food + wood collected while a truce (treaty / D3 mode) was running
        self._truce: dict[str, float] = {}
        self._had_treaty = False
        #: entity id -> game time of the keyframe it first appeared in (None = unknown)
        self._kill_groups: dict[int, list[int]] = defaultdict(list)
        self._born: dict[int, int | None] = {}
        self._first_key_t = -1
        #: (player, resource, kind) -> the last market row, for the 2 s merge
        self._market_last: dict[tuple[Any, str, str], dict[str, Any]] = {}
        self._pressure = PressureTracker()
        self.changed = threading.Condition(self._lock)
        self.desynced = False
        #: keyframes since the last settle_heap (SETTLE_KEYFRAMES)
        self._unsettled = 0
        #: the tile terrain, kept up to date from the tiles patches reach
        self._terrain_tiles = W.TerrainTiles()
        #: Digest of the last snapshot applied, while no patch has changed the tree
        #: since (see :meth:`repeats_state`).
        self._snapshot_digest: bytes | None = None
        #: Snapshots skipped because they repeated the state already held.
        self.repeated_snapshots = 0
        #: How far :meth:`events_between` has checked that ``events`` is in time
        #: order: (events checked, all in order, time of the last one checked).
        self._events_order: tuple[int, bool, int] = (0, True, -1)
        #: Final encoded views and decoded keyframes by (keyframe index, latest),
        #: most recently used last; the lock guards only these dictionaries.
        self._view_cache: OrderedDict[tuple[int, bool], bytes] = OrderedDict()
        self._decoded_cache: OrderedDict[int, dict[str, Any]] = OrderedDict()
        self._cache_lock = threading.Lock()
        #: :meth:`series_json` at a version: (version, result).
        self._series_cache: tuple[int, dict[str, list[dict[str, Any]]]] | None = None

    # -- ingestion ------------------------------------------------------------

    def repeats_state(self, frame: Frame) -> bool:
        """Whether ``frame`` is a snapshot of exactly the state already held.

        A game that has ended or is paused answers every reconnect with the same
        full snapshot at the same game time: one live session wrote 514 identical
        23 MB snapshots, and re-applying each took 2.6 s of CPU under the GIL. Only
        a byte-identical snapshot at the current time of a healthy tree that no
        patch changed since counts, so a reopened stream with another profile
        (fast replay sends fewer particles) still rebuilds the tree.
        """
        if not frame.is_snapshot or frame.events or frame.commands:
            return False
        digest = self._snapshot_digest
        if digest is None or self.desynced or frame.time != self.time:
            return False
        return _digest(frame.patch) == digest

    def feed(self, frame: Frame) -> bool:
        """Apply one frame. False when it was not applied: ignored while the tree
        is out of sync, failed to apply, or repeated the state (:meth:`repeats_state`)."""
        with self._lock:
            digest: bytes | None = None
            if frame.is_snapshot:
                if self.repeats_state(frame):
                    self.repeated_snapshots += 1
                    return False
                # A full-state frame: (re)build the tree from scratch.
                self.patcher = Patcher(self.patcher.schema)
                self.desynced = False
                digest = _digest(frame.patch)
            elif self.desynced:
                return False
            pre_events = self._resolve_events(frame) if frame.events else []
            commands = [
                _decode_raw_command(c) if c.get("kind") == "raw" else c for c in frame.commands
            ]
            treason = self._treason_gold(commands)
            try:
                self.patcher.apply(frame.patch)
            except PatchError:
                self.errors += 1
                self.desynced = True
                self._snapshot_digest = None
                return False
            if digest is not None or frame.patch:
                self._snapshot_digest = digest
            self.frames += 1
            if frame.skipped and self._prev_frame_t >= 0:
                self.skips.append([self._prev_frame_t, frame.time])
                self._pressure = PressureTracker()
            self._prev_frame_t = frame.time
            self.time = frame.time
            self.resource_history.sample(
                W.world_of(self.patcher.root),
                frame.time,
                pre_events,
                handicaps=W.lobby_handicaps(self.patcher.root),
                raw_events=frame.events,
                commands=commands,
                discontinuity=bool(frame.skipped) or (frame.is_snapshot and self.frames > 1),
            )
            self.healing_history.sample(
                W.world_of(self.patcher.root),
                frame.time,
                frame.events,
                discontinuity=bool(frame.skipped) or (frame.is_snapshot and self.frames > 1),
            )
            self._commands(frame.time, commands)
            for ev in pre_events:
                self.events.append(ev)
            for pid, gold in treason:
                # The game's Treason is a command (id 10, var1 = player); it is
                # real only when the player could afford it beforehand.
                if gold >= TREASON_GOLD:
                    self.events.append(_ev(frame.time, "king", "treason", player=pid))
            if self.map is None:
                self._init_static()
            if frame.time >= self._next_key:
                self._keyframe()
                step = self.keyframe_step_ms
                self._next_key = (frame.time // step + 1) * step
            self._track_missiles(frame.time)
            self._track_units(frame.time)
            return True

    def _start_unit_track(self, t: int, rows: list[list[Any]]) -> None:
        """At a keyframe: store the track since the last one, follow this one's units."""
        if self._track_kf >= 0 and self._track_buf:
            blob = zlib.compress(json.dumps(self._track_buf, separators=(",", ":")).encode(), 3)
            self.unit_tracks[self._track_kf] = blob
        self._track_buf = []
        self._track_kf = t
        self._next_track = t + UNIT_TRACK_MS
        # Units only (buildings stand, projectiles have their own track).
        self._track_pos = {r[0]: (r[3], r[4], r[7]) for r in rows if r[0] >= 0 and not r[6] & 1}

    def _track_units(self, t: int) -> None:
        """Sample unit positions and facing changes between keyframes.

        Each entry is ``[t, [[id, x, y, heading], ...]]``. Keeping turns even
        when a unit stays in place preserves facing changes that would otherwise
        be lost between two identical keyframe headings.
        """
        if self._track_kf < 0 or t < self._next_track or not self._track_pos:
            return
        self._next_track = t + UNIT_TRACK_MS
        world = W.world_of(self.patcher.root)
        if world is None:
            return
        ents = W.entities_of(world)
        moved: list[list[Any]] = []
        pos = self._track_pos
        for eid, (px, py, previous_facet) in pos.items():
            e = ents.get(eid)
            # A patch marks every node it edits: untouched units have not moved.
            if e is None or not e.touched:
                continue
            e.touched = False
            f = e.fields
            x, y = float(f.get(W.E_X, 0.0) or 0.0), float(f.get(W.E_Y, 0.0) or 0.0)
            facet = int(f.get(W.E_FACET, 0) or 0)
            if abs(x - px) + abs(y - py) < 0.01 and facet == previous_facet:
                continue
            pos[eid] = (x, y, facet)
            moved.append([eid, round(x, 2), round(y, 2), facet])
        if moved:
            self._track_buf.append([t, moved])

    def units_after(self, kf_t: int) -> list[Any]:
        """The unit track ``[[t, [[id, x, y, heading], ...]], ...]`` from keyframe
        ``kf_t`` to the next (see :meth:`_track_units`)."""
        loaded: list[Any] = json.loads(self._units_json(kf_t))
        return loaded

    def _track_missiles(self, t: int) -> None:
        """Projectiles per stream frame (at most every MISSILE_MS), kept with the
        keyframe they follow: a shot fired and landed between two keyframes is
        still seen, and flights are drawn from their real positions."""
        world = W.world_of(self.patcher.root)
        if world is None or not self.keyframes or t < self._next_missile:
            return
        self._next_missile = t + MISSILE_MS
        prev, self._last_missile = self._last_missile, t
        kf_t = self.keyframes[-1].time
        if self._missile_kf != kf_t:
            self._flush_missiles()
            self._missile_kf = kf_t
        self.catalog.world_players = W.players_of(world)
        self.catalog.world_sprites = world.fields.get(W.W_SPRITES) or []
        rows = W.missile_rows(world, self.catalog)
        # Ingestion-only Node identity catches even same-model Entity recreation.
        # Only numeric incarnations and complete trail values enter saved samples.
        previous = getattr(self, "_missile_sources", {})
        current = {}
        serial = getattr(self, "_missile_source_serial", 0)
        entities = W.entities_of(world)
        for row in rows:
            entity = entities[row[0]]
            old = previous.get(row[0])
            if old is not None and old[0] is entity:
                incarnation = old[1]
            else:
                serial += 1
                incarnation = serial
            current[row[0]] = (entity, incarnation)
            row[8]["incarnation"] = incarnation
        self._missile_sources = current
        self._missile_source_serial = serial
        # Particles born since the last sample: kept with their birth time, so short
        # ones (impacts, blood, dust) that live and die between two keyframes are
        # still drawn. The first sample takes none (they are in the keyframe).
        births = []
        if prev >= 0:
            births = [[t - round(p[4] * 1000), *p] for p in W.particles(world, (t, prev))]
        if rows or births or self._missile_buf:
            self._missile_buf.append([t, rows, births])

    def _flush_missiles(self) -> None:
        if self._missile_kf >= 0 and self._missile_buf:
            blob = zlib.compress(json.dumps(self._missile_buf, separators=(",", ":")).encode(), 3)
            self.missiles[self._missile_kf] = blob
        self._missile_buf = []

    def missiles_after(self, kf_t: int) -> list[Any]:
        """The projectile track ``[[t, rows, births], ...]`` from keyframe ``kf_t`` to
        the next: projectiles in flight (:func:`world.missile_rows`) and particles
        born since the previous sample (``[birth_t, *particle_row]``)."""
        # The stored track first: read without the lock, a keyframe whose buffer
        # was just flushed is found stored rather than as the next one's buffer.
        loaded: list[Any] = json.loads(self._missiles_json(kf_t))
        return loaded

    def feed_all(self, frames: Iterable[Frame]) -> None:
        for f in frames:
            self.feed(f)
        self.finish()

    def finish(self) -> None:
        with self._lock:
            if self.frames and (not self.keyframes or self.keyframes[-1].time != self.time):
                self._keyframe()
            self.complete = True
            self.version += 1
            self.changed.notify_all()

    # -- derived state --------------------------------------------------------

    def _init_static(self) -> None:
        world = W.world_of(self.patcher.root)
        if world is None:
            return
        self.match = W.match_info(self.patcher.root, self.data)
        opts = self.patcher.root.fields.get(W.ROOT_OPTIONS)
        if isinstance(opts, Node):
            # Zero (false) values are omitted from the stream: absent = unlocked.
            self.match["teams_locked"] = bool(opts.fields.get(_GO_TEAMS_LOCKED, 0))
        self.sprites = W.sprite_table(world)
        layer = W.map_layer(world, self.data)
        self.map = {
            "particle_definitions": list(world.fields.get(W.W_PARTICLE_NAMES) or []),
            **{
                k: v
                for k, v in layer.items()
                if k not in ("terrain", "layers", "elevation", "shapes")
            },
            "shapes": base64.b64encode(layer["shapes"]).decode(),
            "terrain": base64.b64encode(layer["terrain"]).decode(),
            "layers": base64.b64encode(layer["layers"]).decode(),
            "elevation": base64.b64encode(layer["elevation"]).decode(),
        }

    def _keyframe(self) -> None:
        extras = W.ViewExtras()
        v = W.view(self.patcher.root, self.catalog, extras, self._kill_groups_of)
        if v is None:
            return
        world = W.world_of(self.patcher.root)
        t = v["time"]
        for eid in extras.entities:
            if eid not in self.entity_meta:
                # Entities already there at the first keyframe of a game that
                # was joined late have no known birth.
                self._born[eid] = None if (self._first_key_t < 0 and t > 0) else t
        if self._first_key_t < 0:
            self._first_key_t = t
        self.entity_meta.update(extras.entities)
        self._log_masters(t, extras)
        if world is not None:
            self._tree_extras(v, world)
        self._derive_events(v)
        if world is not None and t >= self._next_fog:
            self.fog.append((t, _fog_blob(world)))
            if t >= self._next_trees:
                tiles, kinds = W.tree_tiles(world, self.catalog)
                if (tiles, kinds) != self._last_trees:
                    self._last_trees = (tiles, kinds)
                    self.trees.append((t, zlib.compress(tiles, 6), kinds))
                self._next_trees = (t // TREES_MS + 1) * TREES_MS
            self._next_fog = (t // (KEYFRAME_MS * 2) + 1) * KEYFRAME_MS * 2
        if world is not None and t >= self._next_terrain:
            tiles = self._terrain_tiles(world)
            if tiles != self._last_terrain:
                self._last_terrain = tiles
                self.terrain.append((t, zlib.compress(tiles, 6)))
            self._next_terrain = (t // TERRAIN_MS + 1) * TERRAIN_MS
        v["apm"] = {pid: self._apm_now(int(pid), t) for pid in v["players"]}
        self.resource_history.checkpoint(t)
        for pid, stats in v["players"].items():
            stats["resource_income"] = self.resource_history.player(int(pid), t)
        self._activity(v)
        self._player_extras(v)
        kf = Keyframe(t, zlib.compress(json.dumps(v, separators=(",", ":")).encode(), 3))
        self._start_unit_track(t, v["entities"])
        self.keyframes.append(kf)
        if t >= self._next_series:
            self._sample(v, world)
            self._next_series = (t // SERIES_MS + 1) * SERIES_MS
        self._last_view = v
        self.game_ended = bool(v.get("game_ended"))
        self.version += 1
        self.changed.notify_all()
        self._unsettled += 1
        if self._unsettled >= SETTLE_KEYFRAMES:
            self._unsettled = 0
            settle_heap()

    def _kill_groups_of(self, eid: int) -> list[int]:
        """The objectGroup of every unit this entity has killed so far."""
        return self._kill_groups.get(eid, [])

    def _log_masters(self, t: int, extras: W.ViewExtras) -> None:
        """Append each owner's master statistics when they change."""
        for key, node in extras.master_nodes.items():
            log = self.master_log.get(key)
            if log is not None and not node.touched:
                continue  # no patch reached this master since the last keyframe
            node.touched = False
            detail = W.master_detail(node.fields, key[1])
            if log is None:
                self.master_log[key] = [(t, detail)]
            elif log[-1][1] != detail:
                log.append((t, detail))

        for eid, (owner, mid, private, shared_present) in extras.entity_masters.items():
            elog = self.entity_master_log.get(eid)
            if private is None and shared_present and elog is None:
                continue  # unchanged shared-only units keep the existing shared log path
            shadow = W.master_detail(private.fields, mid) if private is not None else None
            source = "private" if private is not None else "player" if shared_present else "missing"
            state = (owner, mid, source, shadow)
            if elog is None:
                self.entity_master_log[eid] = [(t, *state)]
            elif elog[-1][1:] != state:
                elog.append((t, *state))

    def entity_master_stats(
        self, eid: int, owner: int, mid: int, t: int | None = None
    ) -> dict[str, Any] | None:
        """Effective per-entity shadow at t, falling back only after an explicit reset."""
        with self._lock:
            log = self.entity_master_log.get(eid, ())
            i = len(log) - 1 if t is None else bisect_right(log, t, key=lambda e: e[0]) - 1
            if i >= 0 and log[i][1:3] == (owner, mid):
                if log[i][3] == "private":
                    return log[i][4]
                if log[i][3] == "missing":
                    return None
            return self.master_stats(owner, mid, t) if owner > 0 else None

    def _tree_extras(self, v: dict[str, Any], world: Node) -> None:
        """Per-player numbers read straight from the tree: score sub-rows, the
        housed test, monument timers and diplomacy stances."""
        ents = W.entities_of(world)
        limit = int(self.match.get("pop_limit") or 0) if self.match else 0
        self._ruin = {}
        stances: dict[tuple[int, int], int] = {}
        for pid, p in W.players_of(world).items():
            if pid == 0:
                continue
            rht = p.fields.get(_P_RUIN)
            if rht is not None:
                self._ruin[pid] = float(rht)
            for other, rel in enumerate(p.fields.get(W.P_RELATIONS) or ()):
                if other in (0, pid) or not isinstance(rel, Node):
                    continue
                code = rel.fields.get(_REL_UNIT_DIPLOMACY)
                if code is None:
                    code = _ENUM_TO_UNIT_DIPLOMACY.get(int(rel.fields.get(W.REL_STANCE, 0) or 0))
                stances[(pid, other)] = int(code or 0)
            s = v["players"].get(str(pid))
            if s is None:
                continue
            s["score_sub"] = score_sub(p)
            housed, status = housed_state(p, s.get("production") or (), ents, limit)
            s["housed"] = housed
            s["population_status"] = status
        self._stance_now = stances

    def master_stats(self, owner: int, mid: int, t: int | None = None) -> dict[str, Any] | None:
        """The owner's statistics for one master id as of ``t`` (None = latest)."""
        with self._lock:
            log = self.master_log.get((owner, mid))
            if not log:
                return None
            if t is None:
                return log[-1][1]
            i = bisect_right(log, t, key=lambda e: e[0]) - 1
            return log[max(0, i)][1]

    def _activity(self, v: dict[str, Any]) -> None:
        """Integrate worker activity, idle TCs and housing over the keyframe
        interval, and log per-entity activity changes."""
        t = v["time"]
        dt = max(0, t - self._prev_key_t) / 1000.0 if self._prev_key_t >= 0 else 0.0
        self._prev_key_t = t
        for pid, s in v["players"].items():
            acc = self._act_total[pid]
            window = self._act_window[pid]
            sample = s.get("activity", {})
            for k, n in sample.items():
                acc[k] += n * dt
            window.append((t, dict(sample), dt))
            while window and window[0][0] <= t - APM_WINDOW_MS:
                window.popleft()
            lm: dict[str, float] = defaultdict(float)
            for _, smp, d in window:
                for k, n in smp.items():
                    lm[k] += n * d
            # Time with at least one idle town center (not summed over town centers:
            # five idle TCs for a minute are a minute of idle TC time, not five).
            self._tc_idle[pid] += (1 if s.get("idle_town_centers", 0) else 0) * dt
            if s.get("housed"):
                self._housed[pid] += dt
                s["housed_ms"] = t - self._housed_since.setdefault(pid, t)
            else:
                self._housed_since.pop(pid, None)
                s["housed_ms"] = 0
            s["efficiency"] = {
                "all": {k: round(x) for k, x in acc.items()},
                "last_minute": {k: round(x) for k, x in lm.items()},
                "pct": _efficiency(acc),
                "pct_lm": _efficiency(lm),
            }
            s["efficiency_all"] = _efficiency_groups(acc)
            rate = self._collected_rate(pid, t, s.get("collected"))
            if rate is not None:
                s["collected_rate"] = rate
            s["tc_idle_seconds"] = round(self._tc_idle[pid])
            s["housed_seconds"] = round(self._housed[pid])
            # The "Idle TC / Housed Time" dashboard column: both totals, seconds.
            s["idle_tc_housed"] = [s["tc_idle_seconds"], s["housed_seconds"]]
        for row in v["entities"]:
            if row[1] <= 0 or len(row) < 10:
                continue
            log = self.activity_log[row[0]]
            if not log or log[-1][1] != row[9]:
                log.append((t, row[9]))
        for stats in v["players"].values():
            for units in stats.get("garrison_units", {}).values():
                for eid, *_ in units:
                    log = self.activity_log[eid]
                    if not log or log[-1][1] != W.ACT_GARRISONED:
                        log.append((t, W.ACT_GARRISONED))
        self._sample_pressure(t)

    def _collected_rate(
        self, pid: str, t: int, collected: dict[str, int] | None
    ) -> dict[str, int] | None:
        """Resources collected per game minute over the trailing :data:`APM_WINDOW_MS`.

        The oldest sample kept is the last one at or before the window start, so the
        window spans a full minute once the game has run one; before that the gain is
        divided by the time so far. A step back in time starts the window again.
        None when the view has no ``collected`` (older recordings).
        """
        if collected is None:
            return None
        window = self._col_window[pid]
        if window and t < window[-1][0]:
            window.clear()
        now = {k: collected.get(k, 0) for k in COLLECTED_KEYS}
        window.append((t, now))
        while len(window) >= 2 and window[1][0] <= t - APM_WINDOW_MS:
            window.popleft()
        t0, base = window[0]
        elapsed = t - t0
        if elapsed <= 0:
            return dict.fromkeys(COLLECTED_KEYS, 0)
        return {k: round((now[k] - base[k]) * 60_000 / elapsed) for k in COLLECTED_KEYS}

    def _sample_pressure(self, t: int) -> None:
        """Sample only directly attacked workers, including those now garrisoned."""
        world = W.world_of(self.patcher.root)
        if world is None or not self._pressure.active:
            return
        entities = W.entities_of(world)
        workers: dict[int, PressureWorker] = {}
        attackers: dict[int, tuple[float, float]] = {}
        for worker, credit in self._pressure.active.items():
            entity = entities.get(worker)
            if entity is not None:
                f = entity.fields
                inside = int(f.get(W.E_INSIDE, -1) or -1) > 0
                activity = W.unit_activity(entity, None, inside)
                state = f.get(W.E_STATE)
                workers[worker] = PressureWorker(
                    activity not in (W.ACT_IDLE, W.ACT_MOVING, W.ACT_GARRISONED),
                    state is None or state <= W.ENTITY_ALIVE,
                    float(f.get(W.E_X, 0) or 0),
                    float(f.get(W.E_Y, 0) or 0),
                )
            attacker = entities.get(credit.attacker)
            if attacker is not None:
                f = attacker.fields
                state = f.get(W.E_STATE)
                if state is None or state <= W.ENTITY_ALIVE:
                    attackers[credit.attacker] = (
                        float(f.get(W.E_X, 0) or 0),
                        float(f.get(W.E_Y, 0) or 0),
                    )
        self._log_pressure(self._pressure.sample(t, workers, attackers))

    def _log_pressure(self, intervals: Iterable[tuple[int, int, int, int]]) -> None:
        for attacker, start, end, worker in intervals:
            self.unit_log[attacker].append((end, "forced_idle", (end - start) / 1000, worker))

    def _player_extras(self, v: dict[str, Any]) -> None:
        """Running per-player numbers the view alone cannot know."""
        t = v["time"]
        treaty = v.get("treaty")
        if treaty:
            self._had_treaty = True
        for pid, s in v["players"].items():
            ipid = int(pid)
            self._peak_army[ipid] = max(self._peak_army[ipid], s["army_value"])
            self._relics_max[pid] = max(self._relics_max[pid], s.get("relics", 0))
            s["peak_army_value"] = round(self._peak_army[ipid])
            s["relics_max"] = self._relics_max[pid]
            tallies = self._tallies[ipid]
            for k in _TALLY_KEYS:
                s[k] = round(tallies[k])
            apm = v["apm"].get(pid, {})
            self._apm_peak[ipid] = max(self._apm_peak[ipid], apm.get("total", 0))
            minutes = t / 60_000
            s["apm_peak"] = self._apm_peak[ipid]
            s["apm_avg"] = round(self._apm_total[ipid] / minutes) if minutes >= 1 else 0
            s["eapm"] = apm.get("effective", 0)
            if treaty and treaty.get("active"):
                col = s["collected"]
                self._truce[pid] = float(col["food"] + col["wood"])
            if self._had_treaty:
                # Food and wood gathered during the truce (Return of Rome's D3 mode).
                s["d3_resource_aggregate"] = round(self._truce.get(pid, 0.0))
        self._koth_state(v)

    def _koth_state(self, v: dict[str, Any]) -> None:
        koth = v.get("koth")
        if koth is None:
            return
        t = v["time"]
        owner = int(koth.get("owner", 0) or 0)
        prev = self._koth
        if prev is None or prev[0] != owner:
            if prev is not None:
                ev = _ev(
                    t,
                    "victory",
                    "koth_owner",
                    player=owner,
                    previous=prev[0],
                    x=koth.get("x"),
                    y=koth.get("y"),
                )
                left = self._koth_remaining if prev[0] > 0 else None
                if left is None and prev[0] > 0 and self._koth_required is not None:
                    left = max(0, self._koth_required - (t - prev[1]))
                if left is not None:
                    ev["previous_remaining_ms"] = left
                    ev["previous_remaining_years"] = years(left)
                    if left <= KOTH_CLOSE_MS:
                        ev["priority"] = "high"
                self.events.append(ev)
            self._koth = prev = (owner, t)
            self._koth_required = None
        koth["held_ms"] = t - prev[1] if owner > 0 else 0
        koth["required_ms"] = self._koth_required
        koth["holder"] = owner
        remaining = ruin_remaining_ms(self._ruin.get(owner)) if owner > 0 else None
        if remaining is None and owner > 0 and self._koth_required is not None:
            remaining = max(0, self._koth_required - koth["held_ms"])
        self._koth_remaining = remaining
        if remaining is not None:
            koth["remaining_ms"] = remaining
            koth["remaining_years"] = round(remaining / YEAR_MS, 1)

    def _sample(self, v: dict[str, Any], world: Node | None) -> None:
        explored = _exploration(world) if world is not None else {}
        if world is not None:
            self.series["0"].append({"t": v["time"], **W.resources_left(world, self.catalog)})
        for pid, s in v["players"].items():
            ipid = int(pid)
            tasks = s["tasks"]
            lm = s.get("efficiency", {}).get("last_minute", {})
            rate = s.get("collected_rate") or {}
            self.series[pid].append(
                {
                    "t": v["time"],
                    **{f"res_{k}": s["resources"][k] for k in W.RESOURCE_NAMES},
                    **{f"col_{k}": s["collected"][k] for k in COLLECTED_KEYS},
                    **{f"rate_{k}": rate.get(k, 0) for k in COLLECTED_KEYS},
                    "bonus_total": (s.get("resource_income") or {}).get("total", 0),
                    **{
                        f"bonus_{k}": (s.get("resource_income") or {}).get("bonus", {}).get(k, 0)
                        for k in W.RESOURCE_NAMES
                    },
                    "pop": s["pop"],
                    "pop_cap": s["pop_cap"],
                    "villagers": s["villagers"],
                    "military": s["military"],
                    "eco_units": s["eco_units"],
                    "fishing_ships": s["fishing_ships"],
                    "trade_units": s["trade_units"],
                    "army_value": s["army_value"],
                    "kills": s["kills"],
                    "deaths": s["deaths"],
                    "razings": s["razings"],
                    "idle": s["idle_villagers"],
                    "age": s["age"],
                    "techs": s["techs_researched"],
                    "relics": s["relics"],
                    "score": sum(s["score"].values()),
                    "explored": explored.get(ipid, 0.0),
                    "apm": v["apm"].get(pid, {}).get("total", 0),
                    "eapm": v["apm"].get(pid, {}).get("effective", 0),
                    "actions": self._apm_total[ipid],
                    "actions_effective": self._eapm_total[ipid],
                    "efficiency": s.get("efficiency", {}).get("pct", 0),
                    "efficiency_lm": s.get("efficiency", {}).get("pct_lm", 0),
                    "productive_lm": _productive(lm),
                    "unproductive_lm": _unproductive(lm),
                    "tc_idle": s.get("tc_idle_seconds", 0),
                    "housed": s.get("housed_seconds", 0),
                    "apm_eco": v["apm"].get(pid, {}).get("eco", 0),
                    "apm_mil": v["apm"].get(pid, {}).get("military", 0),
                    "mil_pop": s.get("military_pop", 0),
                    "eco_pop": s.get("civilian_pop", 0),
                    **{
                        f"gather_{k}_lm": round(lm.get(f"gather_{k}", 0))
                        for k in ("food", "wood", "gold", "stone")
                    },
                    **{
                        f"task_{k}": tasks.get(k, 0)
                        for k in ("food", "wood", "gold", "stone", "build", "idle")
                    },
                }
            )

    def _derive_events(self, v: dict[str, Any]) -> None:
        t = v["time"]
        for pid, s in v["players"].items():
            ipid = int(pid)
            age = s["age"]
            prev = self._prev_age.get(ipid)
            if prev is not None and age > prev:
                self._ages[ipid][age] = t
                self.events.append(
                    {"t": t, "cat": "age", "kind": "age_up", "player": ipid, "age": age}
                )
            self._prev_age[ipid] = age
            st = s["status"]
            pst = self._prev_status.get(ipid)
            if pst is not None and st != pst:
                self.events.append(_ev(t, "status", st, player=ipid))
            self._prev_status[ipid] = st
        self._diplomacy_events(t)
        self._king_events(v)
        self._countdown_events(v)

    def _diplomacy_events(self, t: int) -> None:
        """One event per direction when a player's stance towards another
        changes to ally / neutral / enemy; a change after 100 years or more in
        the old stance says so and is high priority."""
        now = self._stance_now
        for pair, code in now.items():
            prev = self._stance.get(pair)
            if prev is None:
                self._stance_since.setdefault(pair, t)
                continue
            if prev == code:
                continue
            held = t - self._stance_since.get(pair, t)
            self._stance_since[pair] = t
            stance = UNIT_DIPLOMACY.get(code)
            if stance is None:
                continue  # not a stance the log can name (self, Gaia)
            ev: dict[str, Any] = {
                "t": t,
                "cat": "diplomacy",
                "kind": "diplomacy",
                "player": pair[0],
                "to": pair[1],
                "stance": stance,
            }
            previous = UNIT_DIPLOMACY.get(prev)
            if previous is not None:
                ev["previous"] = previous
                if held >= DIPLOMACY_LONG_MS:
                    ev["duration_ms"] = held
                    ev["duration_years"] = years(held)
                    ev["priority"] = "high"
            self.events.append(ev)
        self._stance = dict(now)

    def _king_events(self, v: dict[str, Any]) -> None:
        """Regicide: King garrisoned / ungarrisoned (forced or not), refuge hit
        points dropping, threatened, and a King gone without a killing blow."""
        t = v["time"]
        kings = v.get("kings") or []
        if not kings and not self._kings:
            if self._king_deaths:
                v["king_status"] = self._king_status_view(v, kings)
            return
        rows = {int(r[0]): r for r in v.get("entities", ()) if r}
        now: dict[int, tuple[bool, int]] = {}
        refuges: dict[int, tuple[int, int]] = {}
        for k in kings:
            kid, pid = int(k["id"]), int(k["pid"])
            garrisoned = bool(k["garrisoned"])
            state = (garrisoned, int(k.get("inside", -1)) if garrisoned else -1)
            now[kid] = state
            self._king_rows[kid] = k
            pos = {"x": k["x"], "y": k["y"]}
            prev = self._kings.get(kid)
            if state[0]:
                refuges[state[1]] = (pid, kid)
            if prev is not None and prev != state:
                if prev[0]:
                    self._ungarrisoned(t, pid, kid, prev[1], rows, pos)
                if state[0]:
                    self._refuge_attacker[state[1]] = None
                    info = self._refuge_info(state[1], rows)
                    self._king_emit(
                        _ev(t, "king", "king_garrisoned", player=pid, king=kid, **info, **pos)
                    )
            if state[0]:
                self._refuge_hp_drop(t, pid, kid, state[1], rows)
            else:
                threat = self._threat(v, k)
                if threat is not None:
                    self._king_alert(
                        t, "king_threatened", kid, pid, threat["owner"], threat=threat, **pos
                    )
        for kid in self._kings:
            if kid in now:
                continue
            last = self._king_rows.get(kid) or {}
            pid = int(last.get("pid", 0) or 0)
            self._king_deaths[pid] = {"id": kid, "x": last.get("x"), "y": last.get("y"), "t": t}
            if kid not in self._kings_killed:
                self._king_emit(
                    _ev(t, "king", "king_killed", player=pid, king=kid, by=None, attacker=None,
                        mysterious=True, x=last.get("x"), y=last.get("y"))
                )  # fmt: skip
        self._kings = now
        self._refuges = refuges
        v["king_status"] = self._king_status_view(v, kings)

    def _king_status_view(self, v: dict[str, Any], kings: list[dict[str, Any]]) -> dict[str, Any]:
        """Per player: ``alive`` (with the King's id), ``dead`` (where it died),
        or ``none`` (the player never had a King: "No king found")."""
        out: dict[str, Any] = {}
        alive = {int(k["pid"]): k for k in kings}
        for pid in v["players"]:
            ipid = int(pid)
            if ipid in alive:
                k = alive[ipid]
                out[pid] = {"state": "alive", "id": k["id"], "x": k["x"], "y": k["y"]}
            elif ipid in self._king_deaths:
                out[pid] = {"state": "dead", **self._king_deaths[ipid]}
            else:
                out[pid] = {"state": "none"}
        return out

    def _refuge_info(self, refuge: int, rows: dict[int, list[Any]]) -> dict[str, Any]:
        """The building or ship a King is in: id, owner, master, boarded."""
        row = rows.get(refuge)
        meta = self.entity_meta.get(refuge)
        owner = int(row[1]) if row is not None else meta[0] if meta else None
        master = int(row[2]) if row is not None else meta[1] if meta else -1
        return {
            "refuge": {"id": refuge, "owner": owner, "master": master},
            "refuge_owner": owner,
            "refuge_master": master,
            "boarded": master in TRANSPORT_MASTERS,
        }

    def _ungarrisoned(
        self,
        t: int,
        pid: int,
        kid: int,
        refuge: int,
        rows: dict[int, list[Any]],
        pos: dict[str, Any],
    ) -> None:
        """Forced when the refuge is gone or below 20 % hit points (credited
        to its last attacker while the King was inside); else voluntary."""
        row = rows.get(refuge)
        forced = row is None or float(row[5]) < KING_FORCED_HP
        attacker = self._refuge_attacker.pop(refuge, None) if forced else None
        self._refuge_attacker.pop(refuge, None)
        self._refuge_hp.pop(refuge, None)
        ev = _ev(
            t,
            "king",
            "king_ungarrisoned",
            player=pid,
            king=kid,
            forced=forced,
            attacker=attacker,
            by=attacker.get("owner") if attacker else None,
            **self._refuge_info(refuge, rows),
            **pos,
        )
        if forced:
            ev["priority"] = "high"
        self._king_emit(ev)

    def _refuge_hp_drop(
        self, t: int, pid: int, kid: int, refuge: int, rows: dict[int, list[Any]]
    ) -> None:
        """A refuge losing hit points between keyframes is under attack even
        when no Damage event named it (no attacker is known then)."""
        row = rows.get(refuge)
        if row is None:
            return
        hp = float(row[5])
        before = self._refuge_hp.get(refuge)
        self._refuge_hp[refuge] = hp
        if before is not None and hp < before:
            info = self._refuge_info(refuge, rows)
            self._king_alert(
                t, "refuge_attacked", kid, pid, None, building=refuge, hp_drop=True,
                attacker=None, x=row[3], y=row[4], **info,
            )  # fmt: skip

    def _threat(self, v: dict[str, Any], king: dict[str, Any]) -> dict[str, Any] | None:
        """The nearest unit threatening a roaming King: a unit of a player
        neutral or hostile to the King's owner with the King inside its weapon
        range -- ranged units searched within 18 tiles, melee ones within 3
        only when no ranged unit threatens."""
        pid = int(king["pid"])
        kx, ky = float(king["x"]), float(king["y"])
        best: dict[str, tuple[float, list[Any]]] = {}
        for row in v["entities"]:
            owner = int(row[1])
            if owner <= 0 or owner == pid or row[6] & 1:
                continue  # Gaia, own units, buildings
            dip = (v["players"].get(str(owner)) or {}).get("diplomacy", {})
            if dip.get(str(pid)) not in ("neutral", "enemy"):
                continue
            info = self.catalog.masters.get(int(row[2]))
            if info is None or info.kind != "unit" or info.cls == 10:
                continue
            d = ((float(row[3]) - kx) ** 2 + (float(row[4]) - ky) ** 2) ** 0.5
            if d > KING_THREAT_RANGED_TILES:
                continue
            stats = self.entity_master_stats(int(row[0]), owner, int(row[2])) or info.stats
            rng = float(stats.get("range", 0) or 0)
            kind = "ranged" if rng > 1.0 else "melee"
            reach = (
                min(rng, KING_THREAT_RANGED_TILES) if kind == "ranged" else KING_THREAT_MELEE_TILES
            )
            if d <= reach and (kind not in best or d < best[kind][0]):
                best[kind] = (d, row)
        got = best.get("ranged") or best.get("melee")
        if got is None:
            return None
        row = got[1]
        return {"id": int(row[0]), "owner": int(row[1]), "master": int(row[2])}

    def _king_alert(
        self,
        t: int,
        kind: str,
        kid: int,
        owner: int,
        by: int | None,
        out: list[dict[str, Any]] | None = None,
        **fields: Any,
    ) -> None:
        """Announce a King status, or renew it: an active status (renewed in
        the last 15 s) is re-announced only when the attacking player changes.
        ``by`` None (a hit-point drop with no known attacker) renews any."""
        key = (kind, kid)
        st = self._king_status.get(key)
        if st is not None and t - st[1] <= KING_STATUS_MS and (by is None or st[0] == by):
            self._king_status[key] = (st[0], t)
            return
        self._king_status[key] = (by, t)
        self._king_emit(_ev(t, "king", kind, player=owner, king=kid, by=by, **fields), out)

    def _king_emit(self, ev: dict[str, Any], out: list[dict[str, Any]] | None = None) -> None:
        """Log a King notification unless one with the same owner, King and
        kind is in the last 20 s; then only fill in an attacker it lacked."""
        t = ev["t"]
        for log in (out or [], self.events):
            for prev in reversed(log):
                if t - prev["t"] > KING_MERGE_MS:
                    break
                if (
                    prev.get("kind") == ev["kind"]
                    and prev.get("king") == ev.get("king")
                    and prev.get("player") == ev.get("player")
                ):
                    if not prev.get("attacker") and ev.get("attacker"):
                        prev["attacker"] = ev["attacker"]
                        prev["by"] = ev.get("by")
                    return
        (out if out is not None else self.events).append(ev)

    def _countdown_events(self, v: dict[str, Any]) -> None:
        """Milestones of a running wonder / relic / King of the Hill countdown."""
        value = v.get("countdown")
        if value is None or self._countdown is None:
            self._countdown_prev = None
            return
        prev = self._countdown_prev
        self._countdown_prev = float(value)
        if prev is None:
            return
        victory, player = self._countdown
        for mark in COUNTDOWN_MILESTONES:
            if prev > mark >= float(value):
                self.events.append(
                    _ev(v["time"], "countdown", "countdown", victory=victory, player=player,
                        years_left=mark)
                )  # fmt: skip

    def _resolve_events(self, frame: Frame) -> list[dict[str, Any]]:
        """Turn the frame's protocol events into log entries, resolving entity
        ids against the tree *before* the frame's patch removes the dead."""
        world = W.world_of(self.patcher.root)
        ents = W.entities_of(world) if world is not None else {}
        players = W.players_of(world) if world is not None else {}
        t = frame.time
        out: list[dict[str, Any]] = []

        def who(eid: Any) -> dict[str, Any]:
            e = ents.get(int(eid)) if eid is not None else None
            if e is None:
                return {"id": eid}
            f = e.fields
            mid = int(f.get(W.E_MASTER, -1) or -1)
            info = self.catalog.entity_master(e, players)
            cls = info.cls if info else -1
            prototype = W.master_node(e, players)
            return {
                "id": int(eid),
                "owner": int(f.get(W.E_OWNER, 0) or 0),
                "master": mid,
                "x": round(f.get(W.E_X, 0.0) or 0.0, 1),
                "y": round(f.get(W.E_Y, 0.0) or 0.0, 1),
                "kind": info.kind if info else "other",
                "cls": cls,
                "eco": bool(info and info.cls in W._ECO_CLASSES),
                "king": W.is_king(mid, cls),
                "cost": W.master_cost(prototype.fields) if prototype is not None else None,
            }

        def master_of(eid: int) -> int:
            e = ents.get(eid)
            return int(e.fields.get(W.E_MASTER, -1) or -1) if e is not None else -1

        def allied(a: int, b: int) -> bool:
            if a <= 0 or b <= 0:
                return False
            if a == b:
                return True
            p = players.get(a)
            return p is not None and W.diplomacy(p).get(str(b)) == "ally"

        seen: set[Any] = set()

        def kill(victim: dict[str, Any], killer: dict[str, Any], attacker: int) -> None:
            if victim.get("owner", 0) <= 0 or victim.get("cls") in _NOT_KILLS:
                return
            if victim.get("id") in seen:  # a killing blow and EntityKilled for one death
                return
            victim_log = self.unit_log.get(int(victim["id"]), ())
            if any(kind == "died" for _, kind, _, _ in victim_log):
                return
            seen.add(victim.get("id"))
            victim_id = victim.get("id")
            if victim_id is not None:
                self.unit_log[int(victim_id)].append(
                    (t, "died", 1.0, int(killer.get("master", -1)))
                )
            vo, ko = int(victim.get("owner", 0) or 0), int(killer.get("owner", 0) or 0)
            friendly = allied(ko, vo)
            if attacker >= 0:
                kind = "friendly_kill" if friendly else "eco_kill" if victim.get("eco") else "kill"
                self.unit_log[attacker].append((t, kind, 1.0, int(victim.get("master", -1))))
                if not friendly:
                    self._kills_by_unit[attacker].append(t)
                    self._kill_groups[attacker].append(int(victim.get("cls", -1)))
                    cost = victim.get("cost")
                    if cost is None:
                        self.unit_log[attacker].append((t, "destroyed_unknown", 1.0, -1))
                    else:
                        for resource, amount in cost.items():
                            self.unit_log[attacker].append(
                                (
                                    t,
                                    f"destroyed_{resource}",
                                    float(amount),
                                    int(victim.get("master", -1)),
                                )
                            )
            if victim.get("eco") and not friendly:
                if ko > 0:
                    self._tallies[ko]["eco_kills"] += 1
                if vo > 0:
                    self._tallies[vo]["eco_deaths"] += 1
            out.append(
                {
                    "t": t,
                    "cat": "combat",
                    "kind": "kill",
                    "victim": victim,
                    "killer": killer,
                    "player": killer.get("owner"),
                    "friendly": friendly,
                    "x": victim.get("x"),
                    "y": victim.get("y"),
                    **({"priority": "high"} if victim.get("king") else {}),
                }
            )
            if victim.get("king"):
                kid = int(victim["id"])
                self._kings_killed.add(kid)
                ref = unit_ref(killer)
                self._king_emit(
                    _ev(t, "king", "king_killed", player=vo, king=kid,
                        by=ref["owner"] if ref else None, attacker=ref,
                        x=victim.get("x"), y=victim.get("y")),
                    out,
                )  # fmt: skip

        for ev in frame.events:
            k = ev.get("kind")
            if k == "damage":
                dmg = float(ev.get("damage", 0) or 0)
                attacker = int(ev.get("attackerid", -1) or -1)
                target = int(ev.get("entityid", -1) or -1)
                if dmg > 0:
                    tm, am = master_of(target), master_of(attacker)
                    self.unit_log[attacker].append((t, "dealt", dmg, tm))
                    self.unit_log[target].append((t, "taken", dmg, am))
                    self._king_damage(out, t, target, attacker, ents, who)
                    victim, killer = who(target), who(attacker)
                    if (
                        victim.get("cls") == W.CLASS_CIVILIAN
                        and int(victim.get("owner", 0)) > 0
                        and int(killer.get("owner", 0)) > 0
                        and not allied(int(victim["owner"]), int(killer["owner"]))
                    ):
                        entity = ents.get(target)
                        if entity is not None:
                            activity = W.unit_activity(
                                entity, None, int(entity.fields.get(W.E_INSIDE, -1) or -1) > 0
                            )
                            self._log_pressure(
                                self._pressure.hit(
                                    target,
                                    attacker,
                                    t,
                                    working=activity
                                    in (*W.ACT_GATHER.values(), W.ACT_BUILDING, W.ACT_REPAIRING),
                                )
                            )
                if not ev.get("iskillingblow"):
                    continue
                victim = who(ev.get("entityid"))
                killer = who(ev.get("attackerid"))
                if victim.get("owner", 0) == 0 or victim.get("cls") in _NOT_KILLS:
                    continue  # trees, mines, wildlife, livestock being butchered
                kill(victim, killer, attacker)
            elif k == "entitykilled":
                victim = who(ev.get("id"))
                killer = who(ev.get("killerid"))
                kill(victim, killer, int(ev.get("killerid", -1) or -1))
            elif k == "notificationtraindone":
                b = who(ev.get("buildingid"))
                out.append(
                    {
                        "t": t,
                        "cat": "train_research",
                        "kind": "trained",
                        "player": ev.get("ownerid"),
                        "master": ev.get("masterid"),
                        "x": b.get("x"),
                        "y": b.get("y"),
                    }
                )
            elif k == "notificationresearchdone":
                tech = int(ev.get("techid", -1))
                b = who(ev.get("buildingid"))
                cat = "age" if tech in W.AGE_TECHS else "train_research"
                out.append(
                    {
                        "t": t,
                        "cat": cat,
                        "kind": "researched",
                        "player": ev.get("ownerid"),
                        "tech": tech,
                        "x": b.get("x"),
                        "y": b.get("y"),
                    }
                )
            elif k == "playerchat":
                chat = {
                    "t": t,
                    "cat": "chat",
                    "kind": "chat",
                    "player": ev.get("playerid"),
                    "channel": ev.get("channel", 0),
                    "text": ev.get("text", ""),
                    "taunt": ev.get("taunt"),
                    "to": chat_recipients(ev.get("destinationmap")),
                }
                # The game's own "<player_id,3,-1> advanced to the Feudal Age." line
                # repeats the age research event (same moment): not chat.
                announce = str(chat["text"]).startswith("<player_id,") and " advanced to " in str(
                    chat["text"]
                )
                if not announce and not self._chat_seen(
                    self._chats_oracle, self._chats_frame, chat
                ):
                    out.append(chat)
            elif k == "tribute":
                sent = abs(float(ev.get("sendervaluechange", 0) or 0))
                got = abs(float(ev.get("receivervaluechange", 0) or 0))
                sender = int(ev.get("senderid", 0) or 0)
                if sender > 0 and sent > 0:
                    self._tallies[sender]["tribute_sent"] += sent
                if got <= 0:
                    continue  # the game reports nothing received: not a tribute row
                out.append(
                    {
                        "t": t,
                        "cat": "tribute",
                        "kind": "tribute",
                        "player": ev.get("senderid"),
                        "to": ev.get("receiverid"),
                        "resource": _res(ev.get("attributetype")),
                        "amount": round(got),
                        "tax": round(max(0.0, sent - got)),
                        "sent": round(sent),
                    }
                )
            elif k == "markettransaction":
                exch = float(ev.get("attributeexchanged", 0) or 0)
                gold = abs(float(ev.get("goldexchanged", 0) or 0))
                pid = int(ev.get("playerid", 0) or 0)
                if pid > 0:
                    tl = self._tallies[pid]
                    if exch > 0:
                        tl["market_bought"] += exch
                        tl["market_gold_spent"] += gold
                    else:
                        tl["market_sold"] += -exch
                        tl["market_gold_gained"] += gold
                self._market(
                    out,
                    {
                        "t": t,
                        "cat": "market",
                        "kind": "buy" if exch > 0 else "sell",
                        "player": ev.get("playerid"),
                        "resource": _res(ev.get("attributetype")),
                        "amount": abs(exch),
                        "gold": gold,
                    },
                )
            elif k == "monkconversion":
                conv_key = (int(ev.get("targetid", -1) or -1), int(ev.get("monkownerid", 0) or 0))
                if conv_key in self._conversions_seen:
                    continue
                self._conversions_seen.add(conv_key)
                tgt = who(ev.get("targetid"))
                monk = int(ev.get("monkid", -1) or -1)
                target_owner = int(ev.get("targetownerid", 0) or 0)
                heresy = self._has_tech(players.get(target_owner), "heresy")
                if monk >= 0:
                    tm = int(tgt.get("master", -1))
                    self.unit_log[monk].append((t, "convert", 1.0, tm))
                    if tgt.get("eco"):
                        self.unit_log[monk].append((t, "convert_eco", 1.0, tm))
                    if heresy:
                        self.unit_log[monk].append((t, "heresy", 1.0, tm))
                out.append(
                    {
                        "t": t,
                        "cat": "conversion",
                        "kind": "conversion",
                        "player": ev.get("monkownerid"),
                        "from": ev.get("targetownerid"),
                        "target": tgt,
                        "converter": monk,
                        "heresy": heresy,
                        "x": tgt.get("x"),
                        "y": tgt.get("y"),
                    }
                )
            elif k == "notificationwonder":
                o = who(ev.get("objid"))
                kind = _WONDER.get(int(ev.get("type", 0) or 0), "wonder")
                owner = int(ev.get("ownerid", 0) or 0)
                self._wonder_countdown(kind, ev, t)
                extra: dict[str, Any] = {}
                if kind.startswith("wonder_") and ev.get("objid") is not None:
                    extra["wonder"] = int(ev["objid"])
                if kind.startswith("relics_"):
                    # No location: clicking selects the player's monasteries.
                    extra["monasteries"] = self._monasteries(ents, players, owner)
                out.append(
                    {
                        "t": t,
                        "cat": "victory",
                        "kind": kind,
                        "player": owner,
                        "remaining": ev.get("remainingtime"),
                        "x": o.get("x"),
                        "y": o.get("y"),
                        **extra,
                        **({"priority": "high"} if kind in HIGH_PRIORITY else {}),
                    }
                )
            elif k == "combatnotificationsound":
                a = who(ev.get("attackedobjectid"))
                if "owner" not in a:
                    continue  # the attacked object is unknown: no row
                out.append(
                    {
                        "t": t,
                        "cat": "combat",
                        "kind": "under_attack",
                        "player": ev.get("receiverid"),
                        "alert": ev.get("type", 0),
                        "unit": unit_ref(a),
                        "master": a.get("master"),
                        "x": a.get("x"),
                        "y": a.get("y"),
                        # A town centre, castle or king under attack is an alert worth
                        # pinning above the event log.
                        **({"priority": "high"} if a.get("master") in _KEY_TARGETS else {}),
                    }
                )
            elif k == "notificationfarmorfishtrapdied":
                out.append(
                    {
                        "t": t,
                        "cat": "train_research",
                        "kind": "farm_expired" if ev.get("farm") else "trap_expired",
                        "player": ev.get("ownerid"),
                    }
                )
        return out

    def _king_damage(
        self,
        out: list[dict[str, Any]],
        t: int,
        target: int,
        attacker: int,
        ents: dict[int, Node],
        who: Any,
    ) -> None:
        """A King under attack, or the building / ship a King hides in. The
        attacker is remembered so a forced ungarrison can be credited."""
        refuge = self._refuges.get(target)
        e = ents.get(target)
        if e is None:
            return
        mid = int(e.fields.get(W.E_MASTER, -1) or -1)
        info = self.catalog.masters.get(mid)
        is_king = W.is_king(mid, info.cls if info else -1)
        if not is_king and refuge is None:
            return
        victim = who(target)
        ref = unit_ref(who(attacker)) if attacker >= 0 else None
        by = ref["owner"] if ref else None
        if is_king:
            self._king_alert(
                t, "king_attacked", target, int(victim.get("owner", 0) or 0), by, out,
                attacker=ref, x=victim.get("x"), y=victim.get("y"),
            )  # fmt: skip
        elif refuge is not None:
            self._refuge_attacker[target] = ref
            self._king_alert(
                t, "refuge_attacked", refuge[1], refuge[0], by, out, building=target,
                refuge_master=mid, boarded=mid in TRANSPORT_MASTERS, attacker=ref,
                x=victim.get("x"), y=victim.get("y"),
            )  # fmt: skip

    def _monasteries(
        self, ents: dict[int, Node], players: dict[int, Node], owner: int
    ) -> list[int]:
        """Ids of the owner's monasteries (what a relic event selects)."""
        out: list[int] = []
        for eid, e in ents.items():
            f = e.fields
            if int(f.get(W.E_OWNER, 0) or 0) != owner or f.get(W.E_STATE) != W.ENTITY_ALIVE:
                continue
            mid = int(f.get(W.E_MASTER, -1) or -1)
            info = self.catalog.masters.get(mid)
            if mid in MONASTERY_MASTERS or (
                info is not None and info.kind == "building" and "monastery" in info.name.lower()
            ):
                out.append(int(eid))
        return sorted(out)

    def _market(self, out: list[dict[str, Any]], ev: dict[str, Any]) -> None:
        """Log a market row; one by the same player for the same resource and
        direction within 2 s of the previous one is merged into it."""
        key = (ev["player"], ev["resource"], ev["kind"])
        prev = self._market_last.get(key)
        if prev is not None and ev["t"] - prev.get("t_last", prev["t"]) <= MARKET_MERGE_MS:
            prev["amount"] += ev["amount"]
            prev["gold"] += ev["gold"]
            prev["count"] = prev.get("count", 1) + 1
            prev["t_last"] = ev["t"]
            return
        ev["count"] = 1
        self._market_last[key] = ev
        out.append(ev)

    def _chat_seen(
        self,
        other: list[tuple[int, Any, str]],
        own: list[tuple[int, Any, str]],
        chat: dict[str, Any],
    ) -> bool:
        """Whether this chat already reached the log through the other path
        (frame stream vs Oracle). A match consumes the other path's entry."""
        t, player, text = int(chat["t"]), chat.get("player"), str(chat.get("text", ""))
        other[:] = [c for c in other if t - c[0] <= CHAT_MATCH_MS]
        for i, c in enumerate(other):
            if c[1] == player and c[2] == text:
                del other[i]
                return True
        own[:] = [c for c in own if t - c[0] <= CHAT_MATCH_MS]
        own.append((t, player, text))
        return False

    def oracle_chat(self, msg: dict[str, Any], paused: bool = False) -> None:
        """Log a chat from the Oracle stream (every one, paused or not) at the
        newest world time; the same chat arriving later in the frame stream is
        dropped, not logged twice."""
        with self._lock:
            chat = {
                "t": max(self.time, self._prev_frame_t, 0),
                "cat": "chat",
                "kind": "chat",
                "player": msg.get("playerid"),
                "channel": msg.get("channel", 0),
                "text": msg.get("text", ""),
                "taunt": msg.get("taunt"),
                "to": chat_recipients(msg.get("destinationmap")),
                "oracle": True,
                "paused": paused,
            }
            if self._chat_seen(self._chats_frame, self._chats_oracle, chat):
                return
            self.events.append(chat)
            self.version += 1
            self.changed.notify_all()

    def _wonder_countdown(self, kind: str, ev: dict[str, Any], t: int) -> None:
        player = int(ev.get("ownerid", 0) or 0)
        remaining = ev.get("remainingtime")
        start = {"wonder_completed": "wonder", "relics_held": "relic", "ruins_held": "koth"}
        stop = {"wonder_destroyed", "relics_lost", "ruins_lost"}
        if kind in start:
            self._countdown = (start[kind], player)
            self._countdown_prev = None
            if kind == "ruins_held" and remaining is not None and self._koth is not None:
                held = t - self._koth[1] if self._koth[0] > 0 else 0
                self._koth_required = held + int(remaining) * 1000
        elif kind in stop and self._countdown is not None and self._countdown[1] == player:
            self._countdown = None

    def _tech_named(self, tech: int, name: str) -> bool:
        info = self.catalog.techs.get(tech)
        return info is not None and str(info.get("name", "")).strip().lower() == name

    def _has_tech(self, player: Node | None, name: str) -> bool:
        if player is None:
            return False
        states = player.fields.get(W.P_RESEARCH)
        if not isinstance(states, dict):
            return False
        for tid, rs in states.items():
            if rs.fields.get(W.R_STATE) == W.RESEARCH_DONE and self._tech_named(tid, name):
                return True
        return False

    def _treason_gold(self, commands: list[dict[str, Any]]) -> list[tuple[int, float]]:
        """Treason commands (game command 10, ``var1`` = the traitor) in this
        frame with the player's gold *before* the frame's patch."""
        found = [
            int(c.get("var1", 0) or 0)
            for c in commands
            if c.get("kind") == "game" and int(c.get("gamecommandid", 0) or 0) == TREASON_COMMAND
        ]
        if not found:
            return []
        world = W.world_of(self.patcher.root)
        players = W.players_of(world) if world is not None else {}
        return [(pid, W.attr(players[pid], "gold")) for pid in found if pid in players]

    def _commands(self, t: int, commands: list[dict[str, Any]]) -> None:
        for c in commands:
            kind = c.get("kind", "")
            if kind in _NON_ACTIONS:
                continue
            # The issuing player: unit orders carry ``commplayerid``; queue,
            # build and market commands name their player differently.
            pid = c.get("commplayerid", c.get("playerid", c.get("unitplayerid")))
            if pid is None:
                continue
            ipid = int(pid)
            effective = True
            if kind in _UNIT_ORDERS:
                sig = _order_signature(c)
                last = self._last_order.get(ipid)
                effective = last is None or last[0] != sig or t - last[1] >= EAPM_REPEAT_MS
                self._last_order[ipid] = (sig, t)
            if kind in _BY_SELECTION:
                military = not self._economic_order(c)
            else:
                military = kind in _MILITARY_COMMANDS and not self._economic_order(c)
            self._apm[ipid].append((t, military, effective))
            self._apm_total[ipid] += 1
            if effective:
                self._eapm_total[ipid] += 1

    def _economic_order(self, c: dict[str, Any]) -> bool:
        """A move/interact order given only to villagers, fishing ships or trade
        units is economy, not military."""
        ids = c.get("unitids") or ()
        if not ids:
            return False
        for uid in ids:
            meta = self.entity_meta.get(int(uid))
            info = self.catalog.masters.get(meta[1]) if meta else None
            if info is None or info.cls not in W.ECO_CLASSES:
                return False
        return True

    def _apm_now(self, pid: int, t: int) -> dict[str, int]:
        q = self._apm.get(pid)
        if not q:
            return {
                "total": 0,
                "eco": 0,
                "military": 0,
                "effective": 0,
                "effective_eco": 0,
                "effective_military": 0,
            }
        while q and q[0][0] < t - APM_WINDOW_MS:
            q.popleft()
        mil = eff = eff_mil = 0
        for _, m, e in q:
            if m:
                mil += 1
            if e:
                eff += 1
                if m:
                    eff_mil += 1
        return {
            "total": len(q),
            "eco": len(q) - mil,
            "military": mil,
            "effective": eff,
            "effective_eco": eff - eff_mil,
            "effective_military": eff_mil,
        }

    # -- queries --------------------------------------------------------------

    @property
    def start(self) -> int:
        return self.keyframes[0].time if self.keyframes else 0

    @property
    def end(self) -> int:
        return self.keyframes[-1].time if self.keyframes else 0

    # The readers below take no lock: ``feed`` holds it for a whole keyframe build
    # (about 100 ms late in an 8-player game), and views, terrain and trees are
    # read from lists that are only appended to or swapped whole, each step atomic
    # under the GIL. Waiting on the lock made view fetches slow exactly while a
    # recording loads or a live game streams.

    def _keyframe_index(self, keyframes: list[Keyframe], t: int | None) -> int:
        """The keyframe at or before ``t`` (the first one before it, the newest for
        None); -1 when there is none yet."""
        if not keyframes:
            return -1
        if t is None:
            return len(keyframes) - 1
        return max(0, bisect_right(keyframes, t, key=lambda k: k.time) - 1)

    def _is_final(self, keyframes: list[Keyframe], i: int) -> bool:
        """Whether keyframe ``i`` and the tracks that follow it can no longer change.

        Its successor is appended only after its unit track is stored, and no
        projectile sample joins its buffer once the successor exists, so answer this
        before reading the tracks.
        """
        return self.complete or i + 1 < len(keyframes)

    def view_at(self, t: int | None) -> dict[str, Any] | None:
        keyframes = self.keyframes
        i = self._keyframe_index(keyframes, t)
        if i < 0:
            return None
        final = self._is_final(keyframes, i)
        kf = keyframes[i]
        v: dict[str, Any] = json.loads(zlib.decompress(kf.blob))
        fog = self.fog
        fi = bisect_right(fog, kf.time, key=lambda f: f[0]) - 1
        if fi >= 0:
            v["fog"] = base64.b64encode(fog[fi][1]).decode()
        trees = self.trees
        ti = bisect_right(trees, kf.time, key=lambda f: f[0]) - 1
        if ti >= 0:
            v["trees_t"] = trees[ti][0]
        terrain = self.terrain
        ri = bisect_right(terrain, kf.time, key=lambda f: f[0]) - 1
        if ri >= 0:
            v["terrain_t"] = terrain[ri][0]
        # The previous keyframe's track too: trails need the flight so far.
        prev = keyframes[i - 1].time if t is not None and i >= 1 else None
        v["missile_track"] = (self.missiles_after(prev) if prev is not None else []) + (
            self.missiles_after(kf.time)
        )
        v["unit_track"] = self.units_after(kf.time)
        if not final:
            # The newest keyframe's tracks are still filling: the browser asks again.
            v["final"] = False
        return v

    def view_json(self, t: int | None) -> bytes | None:
        """:meth:`view_at` as the JSON ``/api/view`` sends, without parsing anything.

        The keyframe is stored as JSON text, and so are the tracks, so the response
        is spliced from them: parsing a late-game keyframe (257 KB) and encoding it
        again took about 10 ms a request, three times that while a recording loads.
        A final response (:meth:`_is_final`) never changes and is kept
        (:data:`VIEW_CACHE_SIZE`). The output is byte for byte what encoding
        :meth:`view_at` compactly gives: keyframes hold none of the added keys.
        """
        keyframes = self.keyframes
        i = self._keyframe_index(keyframes, t)
        if i < 0:
            return None
        key = (i, t is None)
        with self._cache_lock:
            hit = self._view_cache.get(key)
            if hit is not None:
                self._view_cache.move_to_end(key)
                return hit
        final = self._is_final(keyframes, i)
        kf = keyframes[i]
        body = zlib.decompress(kf.blob)
        parts = [body[:-1]]  # the keyframe object, still open
        fog = self.fog
        fi = bisect_right(fog, kf.time, key=lambda f: f[0]) - 1
        if fi >= 0:
            parts += [b',"fog":"', base64.b64encode(fog[fi][1]), b'"']
        trees = self.trees
        ti = bisect_right(trees, kf.time, key=lambda f: f[0]) - 1
        if ti >= 0:
            parts.append(b',"trees_t":%d' % trees[ti][0])
        terrain = self.terrain
        ri = bisect_right(terrain, kf.time, key=lambda f: f[0]) - 1
        if ri >= 0:
            parts.append(b',"terrain_t":%d' % terrain[ri][0])
        prev = keyframes[i - 1].time if t is not None and i >= 1 else None
        missiles = self._missiles_json(kf.time)
        if prev is not None:
            missiles = _join_arrays(self._missiles_json(prev), missiles)
        parts += [b',"missile_track":', missiles, b',"unit_track":', self._units_json(kf.time)]
        parts.append(b"}" if final else b',"final":false}')
        out = b"".join(parts)
        if final:
            with self._cache_lock:
                self._view_cache[key] = out
                while len(self._view_cache) > VIEW_CACHE_SIZE:
                    self._view_cache.popitem(last=False)
        return out

    def _missiles_json(self, kf_t: int) -> bytes:
        """:meth:`missiles_after` as JSON text."""
        return _track_json(self.missiles, kf_t, lambda: self._missile_kf, lambda: self._missile_buf)

    def _units_json(self, kf_t: int) -> bytes:
        """:meth:`units_after` as JSON text."""
        return _track_json(self.unit_tracks, kf_t, lambda: self._track_kf, lambda: self._track_buf)

    def keyframe_at(self, t: int | None) -> dict[str, Any] | None:
        """The keyframe :meth:`view_at` would show, without fog or tracks, for the
        unit and group panels. Shared with other callers: read it, never change it.
        A few are kept (:data:`DECODED_CACHE_SIZE`; a keyframe never changes once
        stored): the panel asks about a selection at the same moment repeatedly."""
        keyframes = self.keyframes
        i = self._keyframe_index(keyframes, t)
        if i < 0:
            return None
        with self._cache_lock:
            hit = self._decoded_cache.get(i)
            if hit is not None:
                self._decoded_cache.move_to_end(i)
                return hit
        v: dict[str, Any] = json.loads(zlib.decompress(keyframes[i].blob))
        with self._cache_lock:
            self._decoded_cache[i] = v
            while len(self._decoded_cache) > DECODED_CACHE_SIZE:
                self._decoded_cache.popitem(last=False)
        return v

    def terrain_at(self, t: int) -> tuple[int, bytes] | None:
        """The live tile terrain in force at ``t``: (snapshot time, base terrain bytes
        then layer bytes, as :func:`world.terrain_tiles`)."""
        terrain = self.terrain
        ri = bisect_right(terrain, t, key=lambda f: f[0]) - 1
        if ri < 0:
            return None
        tt, blob = terrain[ri]
        return tt, zlib.decompress(blob)

    def trees_at(self, t: int) -> tuple[int, bytes, list[int]] | None:
        trees = self.trees
        ti = bisect_right(trees, t, key=lambda f: f[0]) - 1
        if ti < 0:
            return None
        tt, blob, kinds = trees[ti]
        return tt, zlib.decompress(blob), kinds

    def add_event(self, event: dict[str, Any]) -> None:
        """Record an event that did not come through the frame stream."""
        with self._lock:
            if event.get("kind") in HIGH_PRIORITY:
                event.setdefault("priority", "high")
            self.events.append(event)
            self.version += 1
            self.changed.notify_all()

    def unit_stats(
        self, eid: int, t: int | None = None, since: int | None = None
    ) -> dict[str, Any]:
        """Everything the unit panel shows about one entity as of ``t``.

        Kills, eco/friendly kills, damage dealt/taken (with the per-master
        breakdown), monk conversions, activity time, the entity's state at the
        nearest keyframe (garrison, construction, gate, charge) and its master
        statistics *as its owner has them* at that time.
        """
        # Decoded before taking the lock: keyframes never change once stored, and
        # decoding one is the slow part of this request.
        keyframe = self.keyframe_at(t) or {}
        with self._lock:
            out = {"kills": 0.0, "eco_kills": 0.0, "dealt": 0.0, "taken": 0.0, "died": 0.0}
            by_target: dict[str, float] = defaultdict(float)
            by_attacker: dict[str, float] = defaultdict(float)
            monk = {"conversions": 0, "eco": 0, "heresy": 0}
            friendly = 0
            for when, kind, amount, other in self.unit_log.get(eid, ()):
                if t is not None and when > t:
                    continue
                if since is not None and when < since:
                    continue
                if kind == "dealt":
                    by_target[str(other)] += amount
                elif kind == "taken":
                    by_attacker[str(other)] += amount
                if kind == "friendly_kill":
                    friendly += 1
                elif kind == "convert":
                    monk["conversions"] += 1
                elif kind == "convert_eco":
                    monk["eco"] += 1
                elif kind == "heresy":
                    monk["heresy"] += 1
                else:
                    key = {"kill": "kills", "eco_kill": "eco_kills"}.get(kind, kind)
                    out[key] = out.get(key, 0.0) + amount
            out["kills"] += out["eco_kills"]
            keep = ("kills", "eco_kills", "dealt", "taken", "died")
            result: dict[str, Any] = {k: round(out[k], 1) for k in keep}
            result["activity"] = self._unit_activity(eid, t)
            result["activity_lm"] = self._unit_activity(eid, t, window=APM_WINDOW_MS)
            end = self.time if t is None else t
            result["activity_scope"] = self._unit_activity(
                eid, t, window=max(0, end - since) if since is not None else None
            )
            result.update(military_review(self.unit_log.get(eid, ()), end, since))
            result["since_ms"] = since
            result["born"] = self._born.get(eid)
            result["resource_totals"] = self.resource_history.entity(eid, end)
            result["healing"] = self.healing_history.totals([eid], end, since)
            result["friendly_kills"] = friendly
            result["monk"] = monk
            result["damage_by_target"] = {k: round(v, 1) for k, v in by_target.items()}
            result["damage_by_attacker"] = {k: round(v, 1) for k, v in by_attacker.items()}
            result.update(self._entity_state(eid, t, keyframe))
            query_ms = self.time if t is None else int(t)
            result.update(
                entity_stats_validity_version=1,
                entity_id=eid,
                as_of_ms=query_ms,
                valid_from_ms=query_ms,
                valid_until_ms=self._entity_master_valid_until(
                    eid, result["owner"], result["master"], query_ms
                ),
            )
            return result

    def group_stats(
        self, ids: Iterable[int], t: int | None = None, since: int | None = None
    ) -> dict[str, Any]:
        """What the unit panel shows for a selection of many: the group's combat
        totals as of ``t`` (deaths: members that died by then), the seconds its
        members spent in each activity (``activity`` over their lives,
        ``activity_lm`` over the last minute) and, per ``"owner:master"``, the
        statistics that owner's master has then (upgrades and civilisation
        bonuses applied)."""
        keys = ("kills", "eco_kills", "deaths", "dealt", "taken", "conversions")
        totals = dict.fromkeys(keys, 0.0)
        types: dict[str, Any] = {}
        entity_types: dict[str, Any] = {}
        life: dict[str, float] = defaultdict(float)
        last: dict[str, float] = defaultdict(float)
        scoped: dict[str, float] = defaultdict(float)
        review_log: list[tuple[int, str, float, int]] = []
        ids = list(dict.fromkeys(ids))
        # Outside the lock, as in unit_stats.
        rows = {row[0]: row for row in (self.keyframe_at(t) or {}).get("entities", ())}
        with self._lock:
            query_ms = self.time if t is None else int(t)
            for eid in ids:
                for k, v in self._unit_activity(eid, t).items():
                    life[k] += v
                for k, v in self._unit_activity(eid, t, window=APM_WINDOW_MS).items():
                    last[k] += v
                for k, v in self._unit_activity(
                    eid, t, window=max(0, query_ms - since) if since is not None else None
                ).items():
                    scoped[k] += v
                review_log.extend(self.unit_log.get(eid, ()))
                for when, kind, amount, _other in self.unit_log.get(eid, ()):
                    if t is not None and when > t:
                        continue
                    if since is not None and when < since:
                        continue
                    if kind == "died":
                        totals["deaths"] += 1
                    elif kind in ("kill", "eco_kill"):
                        totals["kills"] += amount
                        if kind == "eco_kill":
                            totals["eco_kills"] += amount
                    elif kind in ("dealt", "taken"):
                        totals[kind] += amount
                    elif kind in ("convert", "convert_eco"):
                        totals["conversions"] += 1
                owner, mid = self._entity_master_identity(eid, t, rows.get(eid))
                effective = self.entity_master_stats(eid, owner, mid, t)
                entity_types[str(eid)] = {
                    "owner": owner,
                    "master": mid,
                    "stats": (
                        {k: effective.get(k) for k in GROUP_STAT_KEYS}
                        if effective is not None
                        else None
                    ),
                    "valid_from_ms": query_ms,
                    "valid_until_ms": self._entity_master_valid_until(eid, owner, mid, query_ms),
                }
                key = f"{owner}:{mid}"
                if owner > 0 and key not in types:
                    st = self.master_stats(owner, mid, t)
                    types[key] = {k: st.get(k) for k in GROUP_STAT_KEYS} if st else None
        return {
            "totals": {k: round(v, 1) for k, v in totals.items()},
            "types": types,
            "entity_types": entity_types,
            "entity_stats_validity_version": 1,
            "as_of_ms": query_ms,
            "activity": {k: round(v, 1) for k, v in life.items()},
            "activity_lm": {k: round(v, 1) for k, v in last.items()},
            "activity_scope": {k: round(v, 1) for k, v in scoped.items()},
            "since_ms": since,
            "healing": self.healing_history.totals(ids, query_ms, since),
            **military_review(review_log, query_ms, since),
        }

    def _entity_master_valid_until(self, eid: int, owner: int, mid: int, t: int) -> int:
        """Exclusive forward-only bound, read under group_stats' Timeline lock.

        Bound the effective statistics, not activity totals or Entity geometry.
        An upcoming first private/source entry also bounds shared-only entities.
        No lifetime/identity is inferred before the requested time.
        """
        until = self.time + 1
        log = self.entity_master_log.get(eid, ())
        i = bisect_right(log, t, key=lambda entry: entry[0])
        if i < len(log):
            until = min(until, log[i][0])
        current = log[i - 1] if i else None
        private_or_missing = (
            current is not None
            and current[1:3] == (owner, mid)
            and current[3] in ("private", "missing")
        )
        if not private_or_missing and owner > 0:
            shared = self.master_log.get((owner, mid), ())
            j = bisect_right(shared, t, key=lambda entry: entry[0])
            if j < len(shared):
                until = min(until, shared[j][0])
        return max(t, until)  # Future/out-of-extent queries have an empty interval.

    def _entity_master_identity(
        self, eid: int, t: int | None, row: Sequence[Any] | None
    ) -> tuple[int, int]:
        owner, mid = (
            (int(row[1]), int(row[2])) if row is not None else self.entity_meta.get(eid, (-1, -1))
        )
        # For absent/dead rows, retain the historical private identity rather than latest metadata.
        log = self.entity_master_log.get(eid, ())
        i = len(log) - 1 if t is None else bisect_right(log, t, key=lambda e: e[0]) - 1
        if row is None and i >= 0:
            owner, mid = log[i][1:3]
        return owner, mid

    def _entity_state(self, eid: int, t: int | None, v: dict[str, Any]) -> dict[str, Any]:
        """The entity in keyframe ``v`` (:meth:`keyframe_at` ``t``), plus its owner's
        master stats."""
        key = str(eid)
        row = next((r for r in v.get("entities", ()) if r[0] == eid), None)
        owner, mid = self._entity_master_identity(eid, t, row)
        out: dict[str, Any] = {"owner": owner, "master": mid}
        stats = self.entity_master_stats(eid, owner, mid, t)
        if stats is not None:
            out["stats"] = stats
            out.update(stats)
        garrison: list[dict[str, Any]] = []
        for s in (v.get("players") or {}).values():
            for uid, umid, hp, hpmax in (s.get("garrison_units") or {}).get(key, ()):
                garrison.append({"id": uid, "master": umid, "hp": hp, "max_hp": hpmax})
        out["garrison"] = garrison
        out["mods"] = (v.get("unit_mods") or {}).get(key)
        out["livestock_owner"] = (v.get("livestock_owner") or {}).get(key)
        out["construction_pct"] = (v.get("construction") or {}).get(key)
        # Only gates have a lock (walls and other buildings report nothing).
        info = self.catalog.masters.get(mid)
        is_gate = info is not None and "gate" in info.name.lower()
        out["gate_locked"] = (eid in (v.get("gates_locked") or ())) if is_gate else None
        charge = (v.get("charge") or {}).get(key)
        max_charge = float(((stats or {}).get("charge") or {}).get("attack", 0) or 0)
        out["charge_now"] = charge
        # Monk/priest faith and charged attacks are the same per-entity counter.
        out["faith"] = round(min(1.0, charge / max_charge), 3) if charge and max_charge else None
        if row is not None:
            out["hp_fraction"] = row[5]
        return out

    def _unit_activity(
        self, eid: int, t: int | None, window: int | None = None
    ) -> dict[str, float]:
        """Seconds per activity for one entity, over its life or the last window."""
        log = self.activity_log.get(eid, [])
        end = self.time if t is None else t
        start = end - window if window is not None else -1
        deaths = [when for when, kind, _, _ in self.unit_log.get(eid, ()) if kind == "died"]
        if deaths:
            end = min(end, min(deaths))
        out: dict[str, float] = defaultdict(float)
        for i, (when, act) in enumerate(log):
            if when > end:
                break
            nxt = log[i + 1][0] if i + 1 < len(log) else end
            a, b = max(when, start), min(nxt, end)
            if b > a:
                missing = sum(max(0, min(b, right) - max(a, left)) for left, right in self.skips)
                out[W.ACTIVITY_NAMES[act]] += max(0, b - a - missing) / 1000.0
        return {k: round(v, 1) for k, v in out.items()}

    def events_between(self, t0: int, t1: int) -> list[dict[str, Any]]:
        """Events with ``t0 <= t <= t1``, oldest first.

        Without the lock, like the view readers: ``events`` is only appended to,
        so the first ``n`` entries are fixed once seen, and waiting for a whole
        frame's ingestion made the event panel's requests take 100 ms to 3 s late
        in a game. Events arrive in time order, so this is a binary search; one
        logged out of order (an earlier time) falls back to a scan.
        """
        events = self.events
        n = len(events)
        if not self._events_in_order(events, n):
            return [e for e in events[:n] if t0 <= e["t"] <= t1]
        lo = bisect_left(events, t0, 0, n, key=_time_of)
        hi = bisect_right(events, t1, lo, n, key=_time_of)
        return events[lo:hi]

    def _events_in_order(self, events: list[dict[str, Any]], n: int) -> bool:
        """Whether ``events[:n]`` is in time order, checking only the new ones."""
        checked, ordered, last = self._events_order
        if checked >= n or not ordered:
            return ordered
        for i in range(checked, n):
            t = events[i]["t"]
            if t < last:
                ordered = False
                break
            last = t
        self._events_order = (n, ordered, last)
        return ordered

    def series_json(self, since: int | None = None) -> dict[str, list[dict[str, Any]]]:
        """The time series per player; with ``since``, only rows with ``t >= since``
        (every player is still listed), for a browser that already has the rest.

        Read without the lock: rows are only appended, at keyframes, in time order
        (each sample is at least :data:`SERIES_MS` after the last). The full result
        is kept until the next version; it is 4-5 MB late in an 8-player game, and
        every open statistics screen asks for it. Callers must not modify it.
        """
        version = self.version
        cached = self._series_cache
        if cached is None or cached[0] != version:
            # list() takes the items at once: a new player's key cannot appear mid-loop.
            cached = (version, {pid: rows[:] for pid, rows in list(self.series.items())})
            self._series_cache = cached
        full = cached[1]
        if since is None:
            return full
        return {pid: rows[bisect_left(rows, since, key=_time_of) :] for pid, rows in full.items()}

    def summary(self, t: int | None = None) -> dict[str, Any]:
        """End-of-game / statistics-screen aggregates as of ``t`` (None = latest)."""
        with self._lock:
            last = (self._last_view if t is None else self.view_at(t)) or {}
            end = int(last.get("time", self.time) or 0)
            out: dict[str, Any] = {}
            events = [e for e in self.events if e["t"] <= end]
            for pid, s in (last.get("players") or {}).items():
                if pid == "0":
                    continue
                ipid = int(pid)
                rows = [r for r in self.series.get(pid, []) if r["t"] <= end]
                kills = [e for e in events if e["kind"] == "kill" and e.get("player") == ipid]
                created: dict[str, int] = defaultdict(int)
                for e in events:
                    if e["kind"] == "trained" and e.get("player") == ipid:
                        created[str(e.get("master"))] += 1
                minutes = end / 60_000
                eff_actions = rows[-1].get("actions_effective", 0) if rows else 0
                out[pid] = {
                    "kills": s["kills"],
                    "deaths": s["deaths"],
                    "razings": s["razings"],
                    "buildings_lost": s["buildings_lost"],
                    "collected": s["collected"],
                    "collected_rate": s.get("collected_rate"),
                    "resource_income": s.get("resource_income"),
                    "kill_value": s["kill_value"],
                    "relic_gold": s["relic_gold"],
                    "tribute_received": s["tribute_received"],
                    "tribute_sent": s.get("tribute_sent", 0),
                    "techs": s["techs_researched"],
                    "conversions": s["conversions"],
                    "desertions": s.get("desertions", 0),
                    "age_times": {str(k): v for k, v in self._ages[ipid].items() if v <= end},
                    "peak_villagers": max((r["villagers"] for r in rows), default=0),
                    "peak_military": max((r["military"] for r in rows), default=0),
                    "peak_army_value": s.get("peak_army_value", round(self._peak_army[ipid])),
                    "avg_apm": round(sum(r["apm"] for r in rows) / len(rows)) if rows else 0,
                    "peak_apm": max((r["apm"] for r in rows), default=0),
                    "geapm": round(eff_actions / minutes) if minutes >= 1 else 0,
                    "floating": _floating(rows),
                    "float_hrs": _float_hours(rows),
                    "eco_kills": sum(1 for k in kills if k["victim"].get("eco")),
                    "most_kills": self._most_kills(ipid, end),
                    "most_created": sorted(created.items(), key=lambda kv: -kv[1])[:3],
                    "most_created_lines": self._most_created_lines([ipid], events),
                    "score_sub": s.get("score_sub") or dict.fromkeys(_SCORE_SUB_KEYS, 0),
                    "explored": rows[-1]["explored"] if rows else 0,
                    # Villager-seconds spent idle, integrated from the units' activity
                    # (the game's villagerIdleSecondsTotal attribute is something else).
                    "idle_seconds": s.get("efficiency_all", {}).get("idle", 0),
                    "efficiency": s.get("efficiency", {}).get("pct", 0),
                    "worst_minute_efficiency": min(
                        (r["efficiency_lm"] for r in rows if r["t"] >= 120_000), default=0
                    ),
                    "tc_idle_seconds": s.get("tc_idle_seconds", 0),
                    "housed_seconds": s.get("housed_seconds", 0),
                    "score": s.get("score_total", sum(s.get("score", {}).values())),
                    "status": s["status"],
                    # When the player went out (resigned / defeated / dropped), if so.
                    "out_t": next(
                        (
                            e["t"]
                            for e in events
                            if e["cat"] == "status"
                            and e.get("player") == ipid
                            and e["kind"] in ("resigned", "lost", "dropped")
                        ),
                        None,
                    ),
                }
            _placings(out)
            out["teams_most_created"] = self._teams_most_created(list(out), events)
            return out

    def _unit_line(self, mid: int) -> str:
        """The unit line a master belongs to (fishing ships are one line);
        ``m<id>`` when the game data knows no line."""
        if self._unit_lines is None:
            lines = getattr(self.data, "unit_lines", {})
            lines = lines() if callable(lines) else lines
            self._unit_lines = dict(lines) if isinstance(lines, dict) else {}
        info = self.catalog.masters.get(mid)
        if info is not None and info.cls == W.CLASS_FISHING_BOAT:
            return "m13"
        return self._unit_lines.get(mid, f"m{mid}")

    def _is_military_unit(self, mid: int) -> bool:
        """A countable army unit for "most created": a unit that is not eco,
        a King, an animal or a building, and not an excluded master."""
        if mid in MOST_CREATED_EXCLUDED:
            return False
        info = self.catalog.masters.get(mid)
        if info is None or info.kind != "unit":
            return False
        ok = getattr(info, "most_created_ok", None)
        if ok is not None:
            return bool(ok)
        return info.cls not in W._NON_MILITARY_CLASSES

    def _most_created_lines(self, pids: list[int], events: list[dict[str, Any]]) -> list[list[Any]]:
        """Top three military unit lines trained by these players:
        ``[line_key, count, icon_master]`` (icon = the line's most-trained master)."""
        by_line: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        who = set(pids)
        for e in events:
            mid = e.get("master")
            if e["kind"] != "trained" or e.get("player") not in who or mid is None:
                continue
            if self._is_military_unit(int(mid)):
                by_line[self._unit_line(int(mid))][int(mid)] += 1
        rows: list[list[Any]] = [
            [line, sum(c.values()), max(c, key=lambda m: (c[m], -m))] for line, c in by_line.items()
        ]
        rows.sort(key=lambda r: (-int(r[1]), str(r[0])))
        return rows[:3]

    def _teams_most_created(
        self, pids: list[str], events: list[dict[str, Any]]
    ) -> dict[str, list[list[Any]]]:
        """Per allied side (``team_key`` of the lobby) its top three unit lines."""
        teams: dict[str, list[int]] = defaultdict(list)
        players = self.match.get("players", {}) if self.match else {}
        for pid in pids:
            teams[str((players.get(int(pid)) or {}).get("team_key", 100 + int(pid)))].append(
                int(pid)
            )
        return {k: self._most_created_lines(v, events) for k, v in teams.items()}

    def _most_kills(self, pid: int, end: int) -> dict[str, Any] | None:
        """The player's unit with the most kills by ``end``."""
        best: tuple[int, int] | None = None  # (kills, entity id)
        for eid, times in self._kills_by_unit.items():
            if self.entity_meta.get(eid, (-1, -1))[0] != pid:
                continue
            n = bisect_right(times, end)
            if n and (best is None or n > best[0]):
                best = (n, eid)
        if best is None:
            return None
        return {"unit_master": self.entity_meta[best[1]][1], "kills": best[0], "id": best[1]}

    def status(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "time": self.time,
            "frames": self.frames,
            "complete": self.complete,
            "errors": self.errors,
            "desynced": self.desynced,
            "version": self.version,
            "catalog_version": self.catalog.version,
            "skips": [list(s) for s in self.skips],
            "keyframe_ms": self.keyframe_step_ms,
        }

    def wait_change(self, version: int, timeout: float) -> int:
        with self._lock:
            deadline = _time.monotonic() + timeout
            while self.version == version and not self.complete:
                left = deadline - _time.monotonic()
                if left <= 0:
                    break
                self.changed.wait(left)
            return self.version


_SCORE_SUB_KEYS = ("exploration", "research", "units_buildings", "resources_banked")


def years(ms: float) -> int:
    """Game milliseconds as whole game years (event texts round to whole years)."""
    return round(ms / YEAR_MS)


def ruin_remaining_ms(held: float | None) -> int | None:
    """A monument holder's time left before victory from ``Player.ruinHeldTime``
    (-1 / absent: not the holder): ``max(held - 1, 0) / 10`` years of 5 s."""
    if held is None or held <= -1:
        return None
    return round(max(held - 1.0, 0.0) / 10 * YEAR_MS)


def unit_ref(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """``{id, owner, master}`` of a resolved entity (``who()`` result), or None
    when the entity is unknown (its owner could not be resolved)."""
    if not row or "owner" not in row:
        return None
    return {"id": row.get("id"), "owner": row.get("owner"), "master": row.get("master")}


def score_sub(p: Node) -> dict[str, int]:
    """The score sub-rows from ``Player.victoryPointMap`` (missing entries
    count 0): exploration (7), research (30), units & buildings (29) and
    resources banked (24 + 25 + 26 + 4)."""
    vpm = p.fields.get(W.P_VP_MAP)
    items = (
        vpm.items() if isinstance(vpm, dict) else enumerate(vpm if isinstance(vpm, list) else ())
    )
    pts: dict[int, int] = {}
    for key, e in items:
        if not isinstance(e, Node):
            continue
        eid = e.fields.get(_VP_ID)
        eid = int(key) if eid is None else int(eid)
        pts[eid] = pts.get(eid, 0) + int(e.fields.get(W.VP_POINTS, 0) or 0)
    return {
        "exploration": pts.get(_VP_EXPLORATION, 0),
        "research": pts.get(_VP_RESEARCH, 0),
        "units_buildings": pts.get(_VP_UNITS_BUILDINGS, 0),
        "resources_banked": sum(pts.get(i, 0) for i in _VP_RESOURCES_BANKED),
    }


def housed_state(
    p: Node, production: Iterable[dict[str, Any]], ents: dict[int, Node], limit: int = 0
) -> tuple[bool, int]:
    """The housed test and ``populationStatus`` (0 normal, 1 housed, 2 at
    the overall limit). Housed: the player is playing, ``n`` > 0 of its
    buildings have a *unit* at the production-queue head, ``pop + n <= unitLimit``
    and ``n > maxPop`` (the headroom)."""
    pop = W.attr(p, "population")
    head = W.attr(p, "maxPop")
    cap = W.attr(p, "unitLimit") or float(limit or 0)
    n = 0
    for b in production:
        q = b.get("queue") or ()
        first = q[0] if q else None
        if first is not None:
            if int(first.get("unit", -1)) != -1 and int(first.get("count", 0) or 0) > 0:
                n += 1
        elif (b.get("current") or {}).get("unit") is not None:
            n += 1
    playing = W.player_status(p) == "playing"
    housed = bool(playing and n > 0 and (not cap or pop + n <= cap) and n > head)
    if housed:
        return True, 1
    return False, 2 if cap and pop >= cap else 0


def _track_json(
    stored: dict[int, bytes],
    kf_t: int,
    filling: Callable[[], int],
    buffer: Callable[[], list[Any]],
) -> bytes:
    """A keyframe's track as JSON text: stored, or the buffer still filling.

    Read without the lock. Ingestion stores a full buffer before it starts the
    next one, so a track looked for again after reading the buffer is found
    stored if it was stored meanwhile; the buffer read then may be the next
    keyframe's. (A final view is cached for good: it must not keep that.)
    """
    blob = stored.get(kf_t)
    if not blob:
        buf = list(buffer()) if kf_t == filling() else []
        blob = stored.get(kf_t)
        if not blob:
            return json.dumps(buf, separators=(",", ":")).encode()
    return zlib.decompress(blob)


def _join_arrays(a: bytes, b: bytes) -> bytes:
    """Two compact JSON arrays as one (``[1]`` and ``[2]`` give ``[1,2]``)."""
    if a == b"[]":
        return b
    if b == b"[]":
        return a
    return a[:-1] + b"," + b[1:]


def _time_of(event: dict[str, Any]) -> int:
    t: int = event["t"]
    return t


def _ev(t: int, cat: str, kind: str, **fields: Any) -> dict[str, Any]:
    """An event; the high-priority kinds carry ``priority: 'high'``."""
    ev: dict[str, Any] = {"t": t, "cat": cat, "kind": kind, **fields}
    if kind in HIGH_PRIORITY:
        ev["priority"] = "high"
    return ev


def chat_recipients(mask: Any) -> list[int]:
    """``PlayerChat.destinationmap`` -> player ids (bit *k* = player *k*).

    An absent or zero map (zero values are omitted) means everyone and gives
    an empty list. The bit layout is the game's player-mask convention; no
    captured chat has carried a map yet.
    """
    m = int(mask or 0)
    return [k for k in range(1, 9) if m >> k & 1]


def _order_signature(c: dict[str, Any]) -> str:
    """What a unit order does, ignoring flags; locations rounded to the tile."""
    out: dict[str, Any] = {}
    for k, v in c.items():
        if k in _ORDER_NOISE:
            continue
        if isinstance(v, dict) and "x" in v:
            v = [int(float(v.get("x", 0) or 0)), int(float(v.get("y", 0) or 0))]
        elif isinstance(v, list) and k == "unitids":
            v = sorted(v)
        out[k] = v
    return json.dumps(out, sort_keys=True, separators=(",", ":"), default=str)


#: Masters whose "under attack" notice is high priority: town centres, castles, kings.
_KEY_TARGETS = W.TOWN_CENTER_MASTERS | W.CASTLE_MASTERS | W.KING_MASTERS

#: Result order for placings: winners first, then players still in, then out.
_RESULT_RANK = {"won": 0, "playing": 1}


def _placings(out: dict[str, dict[str, Any]]) -> None:
    """1-based placing per player: by result; players who went out rank by how long
    they lasted (the last one out places best), then by score."""

    def key(pid: str) -> tuple[int, float, float]:
        o = out[pid]
        gone = o.get("out_t")
        lasted = -float(gone) if gone is not None else 0.0
        return (_RESULT_RANK.get(o["status"], 2), lasted, -float(o["score"] or 0))

    order = sorted(out, key=key)
    for i, pid in enumerate(order, 1):
        out[pid]["placing"] = i


#: Victim classes whose death is not a combat kill: livestock, prey/predator
#: animals, trees, resources (game unit-class ids, see world.py).
_NOT_KILLS = frozenset({58, 9, 10, 15, 7, 8, 32, 5, 33, 31, 29})

_WONDER = {
    0: "wonder_started",
    1: "wonder_completed",
    2: "wonder_destroyed",
    3: "relics_held",
    4: "relics_lost",
    5: "ruins_held",
    6: "ruins_lost",
}


_PRODUCTIVE = ("gather_food", "gather_wood", "gather_gold", "gather_stone", "building", "repairing")


def _productive(acts: dict[str, float]) -> float:
    return round(sum(acts.get(k, 0.0) for k in _PRODUCTIVE))


def _unproductive(acts: dict[str, float]) -> float:
    return round(sum(v for k, v in acts.items() if k not in _PRODUCTIVE and k != "garrisoned"))


def _efficiency(acts: dict[str, float]) -> float:
    """Share of villager time spent gathering, building or repairing (%)."""
    total = sum(v for k, v in acts.items() if k != "garrisoned")
    return round(100.0 * _productive(acts) / total, 1) if total else 0.0


def _efficiency_groups(acts: dict[str, float]) -> dict[str, int]:
    """Whole-game villager-seconds: gathering, moving, building/repairing, idle."""
    return {
        "gather": round(sum(v for k, v in acts.items() if k.startswith("gather_"))),
        "move": round(acts.get("moving", 0.0)),
        "build": round(acts.get("building", 0.0) + acts.get("repairing", 0.0)),
        "idle": round(acts.get("idle", 0.0)),
    }


def _res(t: Any) -> str:
    try:
        # Zero (food) is omitted from protobuf messages: absent means food.
        return W.RESOURCE_NAMES[int(t or 0)]
    except (TypeError, ValueError, IndexError):
        return str(t)


# The visibility map (one UInt32 per tile) as one integer, 32 bits per tile from
# the lowest: shifting and masking it does a per-tile bit operation for every
# tile at once in C (a Python loop over a 240x240 map took 14 ms a keyframe).
_BYTE_MASKS: dict[tuple[int, int], int] = {}


def _tile_mask(n: int, low: int) -> int:
    """``low`` in the lowest byte of each of ``n`` 32-bit tiles."""
    key = (n, low)
    got = _BYTE_MASKS.get(key)
    if got is None:
        if len(_BYTE_MASKS) > 8:
            _BYTE_MASKS.clear()
        got = _BYTE_MASKS[key] = int.from_bytes(bytes((low, 0, 0, 0)) * n, "little")
    return got


def _visible_int(vm: Any) -> int | None:
    try:
        packed = array("I", vm)
    except (TypeError, OverflowError):
        return None  # not plain UInt32s: the per-tile loop handles it
    return int.from_bytes(packed.tobytes(), "little") if packed.itemsize == 4 else None


def _fog_blob(world: Node) -> bytes:
    """Per tile: visible byte then explored byte (bit n-1 = player n)."""
    vm = world.fields.get(W.W_VISIBLE) or []
    n = len(vm)
    buf = bytearray(n * 2)
    big = _visible_int(vm)
    if big is not None:
        mask = _tile_mask(n, 0xFF)
        buf[0::2] = ((big >> 1) & mask).to_bytes(4 * n, "little")[0::4]
        buf[1::2] = ((big >> 17) & mask).to_bytes(4 * n, "little")[0::4]
        return zlib.compress(bytes(buf), 6)
    for i, v in enumerate(vm):
        v = int(v)
        buf[2 * i] = (v >> 1) & 0xFF
        buf[2 * i + 1] = (v >> 17) & 0xFF
    return zlib.compress(bytes(buf), 6)


def _exploration(world: Node) -> dict[int, float]:
    vm = world.fields.get(W.W_VISIBLE) or []
    if not vm:
        return {}
    n = len(vm)
    big = _visible_int(vm)
    if big is not None:
        # Player p's explored bit is bit 16 + p: count it over every tile.
        one = _tile_mask(n, 1)
        seen = {pid: ((big >> (16 + pid)) & one).bit_count() for pid in range(1, 9)}
        return {pid: round(100.0 * c / n, 1) for pid, c in seen.items()}
    counts = [0] * 9
    for v in vm:
        e = (int(v) >> 16) & 0x1FF
        while e:
            low = e & -e
            counts[low.bit_length() - 1] += 1
            e ^= low
    return {pid: round(100.0 * counts[pid] / n, 1) for pid in range(1, 9)}


def _floating(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Average and peak unspent resources (the end screen's 'float')."""
    if not rows:
        return {"avg": 0.0, "peak": 0.0}
    totals = [sum(r[f"res_{k}"] for k in W.RESOURCE_NAMES) for r in rows]
    return {"avg": round(sum(totals) / len(totals)), "peak": round(max(totals))}


def _float_hours(rows: list[dict[str, Any]]) -> float:
    """Unspent resources integrated over game time, in resource-hours."""
    total = sum(sum(r[f"res_{k}"] for k in W.RESOURCE_NAMES) for r in rows)
    return round(total * SERIES_MS / 3_600_000, 1)


_PB_COMMAND: Any = None


def _decode_raw_command(c: dict[str, Any]) -> dict[str, Any]:
    """Expand a command recorded as raw protobuf bytes (older recordings)."""
    global _PB_COMMAND
    try:
        if _PB_COMMAND is None:
            from google.protobuf.json_format import MessageToDict

            from vantage.rpc import cade_pb2 as pb

            _PB_COMMAND = (pb.Command, MessageToDict)
        cls, to_dict = _PB_COMMAND
        m = cls.FromString(base64.b64decode(c["b64"]))
        which = m.WhichOneof("command")
        if which is None:
            return {"kind": "unknown"}
        return {"kind": which, **to_dict(getattr(m, which), preserving_proto_field_name=True)}
    except Exception:  # protobuf unavailable or malformed bytes: not an action
        return {"kind": "raw"}


def _digest(patch: bytes) -> bytes:
    """A snapshot's identity for :meth:`Timeline.repeats_state` (about 25 ms for a
    23 MB late-game snapshot, against seconds to apply it)."""
    return hashlib.blake2b(patch, digest_size=16).digest()


def settle_heap() -> None:
    """Take everything alive now out of the cyclic garbage collector's scans.

    Call after feeding a full-state frame (the timeline also calls it every
    :data:`SETTLE_KEYFRAMES` keyframes). A 6-8 player snapshot is about a
    million tree objects; with them tracked, every full collection paused the
    whole process (ingestion and every HTTP request) for up to 213 ms, 35 times in
    25 game minutes (8-player recording, 2026-10-18). The stream builds no
    reference cycles (a whole load with collection off left 0 cyclic garbage), so
    frozen objects are still freed by reference counting when the game drops
    them. One full collection first keeps existing garbage out of the frozen set.
    """
    gc.collect()
    gc.freeze()


def load_recording(path: str, data: GameData, progress: Any = None) -> Timeline:
    """Build a complete timeline from a ``.vrec`` file."""
    from vantage.frames import read_frames

    tl = Timeline(data)
    for i, f in enumerate(read_frames(path)):
        if tl.feed(f) and f.is_snapshot:
            settle_heap()
        if progress is not None and i % 200 == 0:
            progress(tl)
    tl.finish()
    return tl

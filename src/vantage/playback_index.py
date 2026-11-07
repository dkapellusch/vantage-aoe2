"""Persistent completed read-only VREC playback index.

Cache identity binds exact recording, query-consumer source and metadata bytes.
Cache miss/corruption uses ordinary ingestion; this is not resumable/live state.
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import sys
import threading
import time
import uuid
import weakref
import zlib
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, cast

from vantage import timeline as timeline_module
from vantage.patch import Node
from vantage.schema import SCHEMA as QUERY_SCHEMA
from vantage.timeline import Timeline
from vantage.world import Catalog, MasterInfo

from .playback_data import content_manifest, fresh_data

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from vantage.gamedata import GameData


SCHEMA = 3  # 3: the resource and healing histories are stored too
HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
FIELDS = (
    "series",
    "events",
    "match",
    "map",
    "fog",
    "trees",
    "terrain",
    "sprites",
    "activity_log",
    "unit_log",
    "master_log",
    "entity_master_log",
    "entity_meta",
    "skips",
    "game_ended",
    "time",
    "frames",
    "errors",
    "complete",
    "version",
    "keyframe_step_ms",
    "desynced",
    "missiles",
    "_missile_buf",
    "_missile_kf",
    "unit_tracks",
    "_track_buf",
    "_track_kf",
    "_born",
    "_ages",
    "_peak_army",
    "_kills_by_unit",
    "_last_view",
    "_unit_lines",
)
CATALOG_FIELDS = ("masters", "techs", "terrain_colors", "version", "world_sprites", "owner_names")


class CacheMiss(ValueError):
    pass


class Cancelled(RuntimeError):
    pass


class StopAny:
    """Event view for native-job and Session generation cancellation together."""

    def __init__(self, *events: Any) -> None:
        if not events:
            raise ValueError("at least one cancellation event required")
        self.events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self.events)

    def wait(self, timeout: Any) -> Any:
        deadline = time.monotonic() + timeout
        while not self.is_set():
            left = deadline - time.monotonic()
            if left <= 0:
                break
            self.events[0].wait(min(left, 0.05))
        return self.is_set()


def canonical(value: dict[Any, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_pin(path: Any, stop: Any = None) -> Any:
    with Path(path).open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        digest = hashlib.sha256()
        while block := stream.read(4 * 1024 * 1024):
            checked(stop)
            digest.update(block)
    return dict(bytes=size, sha256=digest.hexdigest())


CONSUMER_MODULES = (
    "vantage",
    "vantage.frames",
    "vantage.gamedata",
    "vantage.patch",
    "vantage.schema",
    "vantage.timeline",
    "vantage.world",
    "vantage.sprites",
    "vantage.bc7",
    "vantage.sld",
    "vantage.smx",
    "vantage.rpc.cade_pb2",
)


def source_identity(
    stop: Any = None,
) -> Any:
    # Resolve actual named consumer origins, so a staged package and installed
    # package both bind the modules they execute. No caller-supplied source token.
    forge_spec = importlib.util.find_spec("vantage")
    if forge_spec is None or not forge_spec.origin:
        raise CacheMiss("vantage source package origin unavailable")
    source_root = Path(forge_spec.origin).resolve().parent
    all_forge = [
        dict(path=str(path.relative_to(source_root.parent)), **file_pin(path, stop))
        for path in sorted(source_root.rglob("*.py"))
    ]
    modules = []
    for name in CONSUMER_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin:
            raise CacheMiss(f"query consumer source unavailable: {name}")
        path = Path(spec.origin)
        modules.append(dict(module=name, **file_pin(path, stop)))
    schema_spec: Any = importlib.util.find_spec("vantage.schema")
    schema_path = Path(schema_spec.origin).with_name("cade_schema.json")
    # Raw-command expansion optionally uses protobuf; bind its installed runtime
    # source/binary bytes and version too, without importing a replay or GameAPI.
    protobuf = None
    try:
        distribution = importlib.metadata.distribution("protobuf")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        runtime = []
        for entry in sorted(distribution.files or (), key=str):
            relative = str(entry)
            if relative.startswith("google/") and Path(relative).suffix in {".py", ".so", ".pyd"}:
                runtime.append(
                    dict(name=relative, **file_pin(distribution.locate_file(entry), stop))
                )
        protobuf = dict(version=distribution.version, files=runtime)
    return dict(
        all_forge_python=all_forge,
        named_modules=modules,
        schema_source=file_pin(schema_path, stop),
        index_sources=[
            dict(name=name, **file_pin(HERE / name, stop))
            for name in ("playback_index.py", "playback_data.py")
        ],
        format=SCHEMA,
        python=sys.version,
        sqlite=sqlite3.sqlite_version,
        zlib=zlib.ZLIB_RUNTIME_VERSION,
        protobuf=protobuf,
    )


def identity(recording: Path, data: GameData, stop: Any = None) -> Any:
    try:
        metadata = content_manifest(data, lambda: checked(stop))
    except (ValueError, OSError, TypeError) as error:
        raise CacheMiss(str(error)) from error
    return dict(
        recording=file_pin(recording, stop), game_data=metadata, consumer=source_identity(stop)
    )


def checked(stop: Any) -> None:
    if stop is not None and stop.is_set():
        raise Cancelled("index job cancelled")


class Writer:
    def __init__(self, db: sqlite3.Connection, stop: Any) -> None:
        self.db, self.stop = db, stop

    def blob(self, value: bytes) -> str:
        checked(self.stop)
        key = sha(value)
        self.db.execute("INSERT OR IGNORE INTO blobs VALUES (?, ?)", (key, value))
        return key

    def encode(self, value: Any, depth: int = 0) -> Any:
        checked(self.stop)
        if depth > 128:
            raise CacheMiss("index state nesting limit")
        if value is None or type(value) in (bool, int, str):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise CacheMiss("nonfinite index scalar")
            return value

        def rec(x: Any) -> Any:
            return self.encode(x, depth + 1)

        if isinstance(value, bytes):
            return ["b", self.blob(value)]
        if isinstance(value, Node):
            return ["n", value.model, rec(value.fields), value.touched]
        if isinstance(value, MasterInfo):
            fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(MasterInfo)}
            return ["m", rec(fields)]
        if isinstance(value, dict):
            return ["d", [[rec(k), rec(v)] for k, v in value.items()]]
        if isinstance(value, (list, tuple, set)):
            values = [rec(x) for x in value]
            if isinstance(value, set):
                values.sort(key=canonical)
            return [{list: "l", tuple: "t", set: "s"}[type(value)], values]
        raise CacheMiss(f"unwhitelisted index type {type(value).__name__}")


class Store:
    def __init__(self, db: Any, fd: Any) -> None:
        self.db, self.fd = db, fd
        self.lock = threading.Lock()
        self.blobs_read = 0

    def blob(self, key: str) -> bytes:
        with self.lock:
            row = self.db.execute("SELECT data FROM blobs WHERE hash=?", (key,)).fetchone()
            self.blobs_read += 1
        if row is None or sha(row[0]) != key:
            raise CacheMiss("missing/corrupt index blob")
        data: bytes = row[0]
        return data

    def decode(self, value: Any, depth: int = 0) -> Any:
        if depth > 128:
            raise CacheMiss("index state nesting limit")
        if value is None or type(value) in (bool, int, float, str):
            if type(value) is float and not math.isfinite(value):
                raise CacheMiss("nonfinite scalar")
            return value
        if not isinstance(value, list) or not value:
            raise CacheMiss("invalid tagged index value")

        def rec(x: Any) -> Any:
            return self.decode(x, depth + 1)

        tag, *args = value
        if tag == "b" and len(args) == 1 and isinstance(args[0], str):
            return self.blob(args[0])
        if tag == "d" and len(args) == 1:
            return {rec(k): rec(v) for k, v in args[0]}
        if tag in ("l", "t", "s") and len(args) == 1:
            return {"l": list, "t": tuple, "s": set}[tag](rec(x) for x in args[0])
        if tag == "n" and len(args) == 3 and type(args[0]) is int and type(args[2]) is bool:
            fields = rec(args[1])
            if (
                args[0] not in QUERY_SCHEMA._names
                or type(fields) is not dict
                or any(type(key) is not int for key in fields)
            ):
                raise CacheMiss("invalid cached Node model/fields")
            return Node(args[0], fields, args[2])
        if tag == "m" and len(args) == 1:
            fields = rec(args[0])
            if set(fields) != {f.name for f in dataclasses.fields(MasterInfo)}:
                raise CacheMiss("master schema differs")
            return MasterInfo(**fields)
        raise CacheMiss("unknown/malformed tagged index value")

    def close(self) -> None:
        self.db.close()
        os.close(self.fd)


@dataclasses.dataclass(frozen=True)
class LazyKeyframe:
    time: int
    key: str
    store: Store

    @property
    def blob(self) -> bytes:
        return self.store.blob(self.key)


class ReadOnlyCatalog(Catalog):
    def immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("completed playback catalog cannot ingest")

    master = own_master = load_techs = immutable


class ReadOnlyTimeline(Timeline):
    _index_finalizer: Any
    _index_store: Any
    _index_source_identity: Any

    def immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("completed playback index cannot ingest")

    # Read-only: these names raise instead of ingesting.
    feed = feed_all = finish = add_event = oracle_chat = immutable  # type: ignore[assignment]

    def close(self) -> None:
        self._index_finalizer()


def publish(
    timeline: Any,
    recording: Path,
    root: Path,
    expected: Any,
    stop: Any = None,
    commit_guard: type[Any] = contextlib.nullcontext,
) -> Path:
    """Publish only a complete stable-source snapshot; pending work is never readable."""
    checked(stop)
    if identity(recording, timeline.data, stop) != expected:
        raise CacheMiss("source/consumer/GameData changed during ingestion")
    if getattr(timeline, "_index_source_identity", None) != expected:
        raise CacheMiss("Timeline is not bound to this ordinary ingestion input identity")
    if not timeline.complete or timeline.errors or timeline.desynced:
        raise CacheMiss("only complete, error-free ordinary ingestion can be cached")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    key = sha(canonical(expected))
    pending = root / (".pending-" + uuid.uuid4().hex)
    pending.mkdir()
    try:
        db_path = pending / "index.sqlite3"
        db = sqlite3.connect(db_path)
        try:
            db.executescript(
                "CREATE TABLE blobs(hash TEXT PRIMARY KEY, data BLOB NOT NULL);"
                "CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), data BLOB);"
            )
            writer = Writer(db, stop)
            with timeline._lock:
                state = {name: getattr(timeline, name) for name in FIELDS}
                state["catalog"] = {
                    name: getattr(timeline.catalog, name) for name in CATALOG_FIELDS
                }
                state["resource_history"] = timeline.resource_history.query_state()
                state["healing_history"] = timeline.healing_history.query_state()
                encoded = writer.encode(state)
                keys = [(k.time, writer.blob(k.blob)) for k in timeline.keyframes]
                payload = canonical(dict(schema=SCHEMA, state=encoded, keyframes=keys))
                db.execute("INSERT INTO state VALUES (1, ?)", (payload,))
            db.commit()
        finally:
            db.close()
        checked(stop)
        if identity(recording, timeline.data, stop) != expected:
            raise CacheMiss("source changed while index was written")
        with db_path.open("rb") as stream:
            os.fsync(stream.fileno())
        manifest = dict(schema=SCHEMA, identity=expected, database=file_pin(db_path))
        with (pending / "committed.json").open("x") as out:
            out.write(canonical(manifest).decode())
            out.flush()
            os.fsync(out.fileno())
        checked(stop)
        final = root / key
        retired = None
        with (root / (key + ".lock")).open("a+b") as lock:
            while True:
                checked(stop)
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if stop is not None:
                        stop.wait(0.05)
                    else:
                        threading.Event().wait(0.05)
            with commit_guard():
                checked(stop)
                if final.exists():
                    retired = root / (".retired-" + uuid.uuid4().hex)
                    os.replace(final, retired)
                os.replace(pending, final)
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        if retired is not None:
            shutil.rmtree(retired)
        return final
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def restore(recording: Path, data: GameData, root: Path, stop: Any = None) -> ReadOnlyTimeline:
    """Return a completed index or CacheMiss. No Frame reader/Patcher is called."""
    checked(stop)
    # A previous generation may have warmed lazy metadata. Clone before any
    # identity/query work, preserving its original mod configuration inputs.
    requested_data = data
    try:
        data = fresh_data(data)
        expected = identity(recording, data, stop)
    except (ValueError, OSError) as error:
        raise CacheMiss(str(error)) from error
    directory = Path(root) / sha(canonical(expected))
    db = None
    fd = None
    try:
        manifest = json.loads((directory / "committed.json").read_bytes())
        if manifest != dict(schema=SCHEMA, identity=expected, database=manifest["database"]):
            raise CacheMiss("index identity/schema mismatch")
        path = directory / "index.sqlite3"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(os.dup(fd), "rb") as stream:
            digest = hashlib.sha256()
            while block := stream.read(4 * 1024 * 1024):
                checked(stop)
                digest.update(block)
            actual = dict(bytes=os.fstat(fd).st_size, sha256=digest.hexdigest())
        if actual != manifest["database"]:
            raise CacheMiss("index content hash differs")
        db = sqlite3.connect(
            f"file:/proc/self/fd/{fd}?mode=ro&immutable=1", uri=True, check_same_thread=False
        )
        db.execute("PRAGMA query_only=ON")
        store = Store(db, fd)
        payload = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        if payload["schema"] != SCHEMA:
            raise CacheMiss("state schema differs")
        state = store.decode(payload["state"])
        if set(state) != {*FIELDS, "catalog", "resource_history", "healing_history"} or set(
            state["catalog"]
        ) != set(CATALOG_FIELDS):
            raise CacheMiss("stored field inventory differs")
        timeline: Any = ReadOnlyTimeline(data)
        timeline.patcher = None  # A read-only index is not resumable simulation state.
        timeline.catalog = ReadOnlyCatalog(data)
        for name, value in state.pop("catalog").items():
            setattr(timeline.catalog, name, value)
        timeline.resource_history.restore_query_state(state.pop("resource_history"))
        timeline.healing_history.restore_query_state(state.pop("healing_history"))
        for name, value in state.items():
            setattr(timeline, name, value)
        timeline._ages = defaultdict(dict, timeline._ages)
        timeline._peak_army = defaultdict(float, timeline._peak_army)
        keys = payload["keyframes"]
        if any(
            type(t) is not int or t < 0 or not isinstance(key, str) or len(key) != 64
            for t, key in keys
        ):
            raise CacheMiss("keyframe index shape differs")
        if any(a[0] > b[0] for a, b in pairwise(keys)):
            raise CacheMiss("keyframes out of order")
        for _t, key in keys:
            if db.execute("SELECT 1 FROM blobs WHERE hash=?", (key,)).fetchone() is None:
                raise CacheMiss("keyframe refers to missing blob")
        timeline.keyframes = [LazyKeyframe(t, key, store) for t, key in keys]
        if not timeline.complete or timeline.errors or timeline.desynced:
            raise CacheMiss("stored completion flags rejected")
        checked(stop)
        # Re-resolve the original requested configuration, not this job's frozen
        # mod order. Catch recording/metadata/source/profile-order races while
        # database hydration ran, before the candidate can be installed.
        if identity(recording, fresh_data(requested_data), stop) != expected:
            raise CacheMiss("recording/metadata/consumer changed during index restore")
        timeline._index_source_identity = expected
        timeline._index_store = store
        # Existing requests retain their local Timeline reference. Replacement
        # must not close its file while such a request still reads a lazy blob.
        timeline._index_finalizer = weakref.finalize(timeline, store.close)
        return cast(ReadOnlyTimeline, timeline)
    except Cancelled:
        if db is not None:
            db.close()
        if fd is not None:
            os.close(fd)
        raise
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        RecursionError,
        OverflowError,
        sqlite3.Error,
    ) as error:
        if db is not None:
            db.close()
        if fd is not None:
            os.close(fd)
        raise CacheMiss(str(error)) from error


def ingest_recording(recording: Path, data: GameData, stop: Any) -> Timeline:
    """Ordinary VREC ingestion, with immutable input identity before/after binding."""
    from vantage.frames import read_frames

    requested_data = data
    # Custom/unmanifestable metadata still uses ordinary ingestion.
    with contextlib.suppress(ValueError, OSError):
        data = fresh_data(data)
    try:
        expected = identity(recording, data, stop)
    except CacheMiss:
        expected = None
    timeline: Any = Timeline(data)
    for frame in read_frames(recording):
        checked(stop)
        timeline.feed(frame)
        if frame.is_snapshot:
            timeline_module.settle_heap()
    timeline.finish()
    if expected is not None and identity(recording, fresh_data(requested_data), stop) != expected:
        raise CacheMiss("source/metadata changed during ordinary ingestion")
    timeline._index_source_identity = expected
    return cast(Timeline, timeline)


def load_completed(recording: Path, data: GameData, index_root: Path, stop: Any = None) -> Any:
    """Return (fresh_data, completed Timeline), caching only ordinary query state.

    Native callers still independently validate committed conversion/header/
    extent/gameEnded pins before adoption. Cache errors never become a ready
    native result and never prevent a valid ordinary ingestion from succeeding.
    Cancellation and ordinary-ingestion errors propagate to the Session owner.
    """
    checked(stop)
    try:
        candidate: Any = restore(recording, data, index_root, stop)
    except (ValueError, OSError, sqlite3.Error):
        candidate = ingest_recording(recording, data, stop)
        expected = getattr(candidate, "_index_source_identity", None)
        if expected is not None:
            with contextlib.suppress(CacheMiss, OSError, sqlite3.Error):
                publish(candidate, recording, index_root, expected, stop)
    try:
        checked(stop)
        expected = getattr(candidate, "_index_source_identity", None)
        if expected is not None and identity(recording, fresh_data(data), stop) != expected:
            raise CacheMiss("recording/metadata/consumer changed before completed load returned")
    except BaseException:
        if isinstance(candidate, ReadOnlyTimeline):
            candidate.close()
        raise
    return candidate.data, candidate

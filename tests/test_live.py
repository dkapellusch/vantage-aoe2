"""vantage.live: the CadeRemote client, against an in-process fake game."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent import futures
from pathlib import Path
from typing import Any

import pytest

grpc = pytest.importorskip("grpc")
pytest.importorskip("google.protobuf")

from tests.helpers import fid, game_frames, snapshot_builder  # noqa: E402
from vantage.frames import Frame, read_frames, read_header  # noqa: E402
from vantage.gamedata import GameData  # noqa: E402
from vantage.live import LiveGame  # noqa: E402
from vantage.rpc import cade_pb2 as pb  # noqa: E402
from vantage.server import Session  # noqa: E402


class FakeGame:
    """Answers the CadeRemote methods Vantage uses, streaming synthetic frames."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.selected_game = 2  # AoE2; 1 = Return of Rome
        #: The frames each Frames stream sends.
        self.stream: Callable[[], list[Frame]] = lambda: game_frames(6)

    def _info(self, request: Any) -> Any:
        mode = "modes\\Pompeii\\" if self.selected_game == 1 else ""
        r = pb.InfoResponse(gameversion=185872, apiversion=22, basedirectory="Z:\\nowhere")
        r.selectedgame.enumvalue = self.selected_game
        r.selectedgame.modepath = mode
        return r

    def _set_game(self, request: Any) -> Any:
        if not request.confirm:  # like the game mid-match: asks for confirmation
            return pb.SetDesiredGameResponse(code=5)
        self.selected_game = request.desiredgame
        return pb.SetDesiredGameResponse(code=0, selectedgame=request.desiredgame)

    def handler(self) -> Any:
        def unary(name: str, req_t: Any, reply: Any) -> Any:
            def fn(request: Any, context: Any) -> Any:
                self.calls.append((name, request))
                return reply(request)

            return grpc.unary_unary_rpc_method_handler(
                fn,
                request_deserializer=req_t.FromString,
                response_serializer=lambda m: m.SerializeToString(),
            )

        def frames(request: Any, context: Any) -> Iterator[Any]:
            self.calls.append(("Frames", request))
            for f in self.stream():
                seq = pb.FrameSequence(sendingworldtime=f.time)
                fr = seq.frame.add(time=f.time, patch=f.patch)
                for ev in f.events:
                    if ev["kind"] == "playerchat":
                        fr.event.add().playerchat.text = ev["text"]
                yield seq

        def oracle(requests: Any, context: Any) -> Iterator[Any]:
            first = next(requests)
            self.calls.append(("Oracle", first))
            msg = pb.OracleMessage()
            msg.gamepaused.paused = True
            msg.gamepaused.pausedbyplayerid = 2
            yield msg
            chat = pb.OracleMessage()
            chat.gamechat.playerid = 2
            chat.gamechat.text = "brb"
            yield chat
            yield pb.OracleMessage(gamestate=3)  # bare enum, not a message
            time.sleep(0.5)

        methods = {
            "Info": unary("Info", pb.InfoRequest, self._info),
            "SetDesiredGame": unary("SetDesiredGame", pb.SetDesiredGameRequest, self._set_game),
            "Pause": unary(
                "Pause", pb.PauseRequest, lambda r: pb.PauseResponse(success=True, changed=True)
            ),
            "SetFogOfWar": unary(
                "SetFogOfWar", pb.SetFogOfWarRequest, lambda r: pb.SetFogOfWarResponse(success=True)
            ),
            "SetPerspective": unary(
                "SetPerspective",
                pb.SetPerspectiveRequest,
                lambda r: pb.SetPerspectiveResponse(success=True, playerid=r.playerid),
            ),
            "SetGameSpeed": unary(
                "SetGameSpeed",
                pb.SetGameSpeedRequest,
                lambda r: pb.SetGameSpeedResponse(success=True),
            ),
            "LoadGame": unary(
                "LoadGame",
                pb.LoadGameRequest,
                lambda r: pb.LoadGameResponse(code=3 if not r.confirm else 0),
            ),
            "StartScenario": unary(
                "StartScenario",
                pb.StartScenarioRequest,
                lambda r: pb.StartScenarioResponse(
                    accepted=r.scenarioPath.endswith(".aoe2scenario"),
                    reason="" if r.scenarioPath.endswith(".aoe2scenario") else "not a scenario",
                    launchId=7 if r.restartIfRunning else 3,
                ),
            ),
            "ChangeWindowState": unary(
                "ChangeWindowState",
                pb.ChangeWindowStateRequest,
                lambda r: pb.ChangeWindowStateResponse(code=0),
            ),
            "Oracle": grpc.stream_stream_rpc_method_handler(
                oracle,
                request_deserializer=pb.OraclePrayer.FromString,
                response_serializer=lambda m: m.SerializeToString(),
            ),
            "Frames": grpc.unary_stream_rpc_method_handler(
                frames,
                request_deserializer=pb.FramesRequest.FromString,
                response_serializer=lambda m: m.SerializeToString(),
            ),
        }
        return grpc.method_handlers_generic_handler("cade_api.rpc.CadeRemote", methods)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[FakeGame, int]]:
    monkeypatch.setenv("VANTAGE_CERTS", str(tmp_path / "no-certs"))  # plaintext for the fake
    game = FakeGame()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers((game.handler(),))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield game, port
    finally:
        server.stop(0)


def test_rpcs(fake: tuple[FakeGame, int]) -> None:
    game, port = fake
    live = LiveGame(port=port).connect(timeout=5)
    try:
        info = live.info()
        assert (info.game_version, info.api_version) == (185872, 22)
        assert live.pause(True) and live.set_fog(False) and live.set_speed("FAST")
        assert live.set_perspective(2)
        assert live.load_replay("C:\\r.aoe2record") == "SUCCESS"  # retried with confirm
        assert live.set_window("MINIMIZED")
        oracle = list(live.oracle())
        assert oracle[0] == {"kind": "gamepaused", "paused": True, "pausedbyplayerid": 2}
        assert oracle[1]["kind"] == "gamechat" and oracle[1]["text"] == "brb"
        assert oracle[2] == {"kind": "gamestate", "value": 3}
        assert (info.selected_game, info.selected_mode) == (2, "")
        assert live.set_desired_game(1) == "SUCCESS"  # retried with confirm
        assert [r.confirm for n, r in game.calls if n == "SetDesiredGame"] == [False, True]
        assert live.info().selected_mode == "modes\\Pompeii\\"
        loads = [r for n, r in game.calls if n == "LoadGame"]
        assert [r.confirm for r in loads] == [False, True]
        assert loads[0].loadreplay.filepath == "C:\\r.aoe2record"
        frames = list(live.frames(resolution_ms=250))
        assert [f.time for f in frames][:3] == [0, 500, 1000]
        assert frames[0].is_snapshot
        req = next(r for n, r in game.calls if n == "Frames")
        assert req.desiredresolutions[0].gametimeresolution == 250
        assert not req.particledefinitionwhitelist and req.disableparticles
        list(live.frames(particles=True, particle_whitelist=["fire_small_left", "smoke_trail"]))
        req = [r for n, r in game.calls if n == "Frames"][-1]
        assert not req.disableparticles
        assert list(req.particledefinitionwhitelist) == ["fire_small_left", "smoke_trail"]
    finally:
        live.close()


def test_start_scenario(fake: tuple[FakeGame, int]) -> None:
    game, port = fake
    live = LiveGame(port=port).connect(timeout=5)
    try:
        ok = live.start_scenario("C:\\s\\Test.aoe2scenario", use_test_difficulty=True)
        assert ok == {"accepted": True, "reason": "", "launch_id": 3}
        bad = live.start_scenario("C:\\s\\x.txt", restart_if_running=True)
        assert bad == {"accepted": False, "reason": "not a scenario", "launch_id": 7}
        sent = [r for n, r in game.calls if n == "StartScenario"]
        assert sent[0].scenarioPath == "C:\\s\\Test.aoe2scenario" and sent[0].useTestDifficulty
        assert not sent[0].restartIfRunning and sent[1].restartIfRunning
    finally:
        live.close()


def test_stream_errors_map_to_the_launcher_states() -> None:
    from vantage.live import classify_stream_error

    class Err(Exception):
        def __init__(self, code: str, details: str = "") -> None:
            self._c, self._d = code, details

        def code(self) -> Any:
            return type("C", (), {"name": self._c})()

        def details(self) -> str:
            return self._d

    denied = Err("PERMISSION_DENIED", "PLAYER_NO_CAPTUREAGE")
    assert classify_stream_error(denied) == "closed-player"
    assert classify_stream_error(Err("PERMISSION_DENIED", "other")) == "closed-error"
    assert classify_stream_error(Err("UNAVAILABLE")) == "closed-unavailable"
    assert classify_stream_error(ValueError("x")) == "closed-error"


def test_session_live_ingests_and_records(fake: tuple[FakeGame, int], tmp_path: Path) -> None:
    _, port = fake
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        tl = session.timeline
        if tl is not None and tl.time >= 6000:
            break
        time.sleep(0.05)
    tl = session.timeline
    assert tl is not None and tl.time >= 6000 and tl.errors == 0
    assert any(e["kind"] == "chat" for e in tl.events)
    assert session.source.get("paused") is True and session.source.get("paused_by") == 2
    assert any(e.get("paused") and e["text"] == "brb" for e in tl.events)  # chat while paused
    # Control works mid-stream and between streams (over its own connection).
    deadline = time.monotonic() + 10
    result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = session.control("window", "MINIMIZED")
        if result.get("ok"):
            break
        time.sleep(0.02)
    assert result == {"ok": True}, session.error
    # The fake's stream ends and the next one starts again at t=0: a new game.
    first_generation = session.generation
    deadline = time.monotonic() + 15
    while session.generation == first_generation and time.monotonic() < deadline:
        time.sleep(0.05)
    assert session.generation > first_generation
    session.stop()
    recs = sorted(tmp_path.glob("live-*.vrec"))
    assert len(recs) == session.generation  # one recording per game
    assert session.source["game_version"] == 185872


def test_session_switches_game_and_reads_return_of_rome_data(
    fake: tuple[FakeGame, int], tmp_path: Path
) -> None:
    game, port = fake
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=True, replay="C:\\r.aoe2record", game=1)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (session.timeline and session.timeline.time > 0):
        time.sleep(0.05)
    session.stop()
    assert game.selected_game == 1
    assert session.source["switch_result"] == "SUCCESS"
    assert session.data.mode == "Pompeii" and session.describe()["game"] == "ror"
    header = read_header(session.source["recording"])
    assert header["game_mode"] == "Pompeii"


def _wait(cond: Any, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_load_replay_asks_unless_told(fake: tuple[FakeGame, int]) -> None:
    game, port = fake
    live = LiveGame(port=port).connect(timeout=5)
    try:
        assert live.load_replay("C:\\r.aoe2record", confirm=False) == "FAILED_PLAYING_NEED_CONFIRM"
        assert live.load_replay("C:\\r.aoe2record", confirm=True) == "SUCCESS"
        assert live.load_replay("x", confirm=True, cloud=True) == "SUCCESS"
        loads = [r for n, r in game.calls if n == "LoadGame"]
        assert [r.confirm for r in loads] == [False, True, True] and loads[2].loadreplay.cloud
        assert live.set_desired_game(1, confirm=False) == "FAILED_PLAYING_NEED_CONFIRM"
    finally:
        live.close()


def test_play_replay_never_confirms_for_the_user(
    fake: tuple[FakeGame, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import threading
    import urllib.request

    from vantage.server import App, serve

    monkeypatch.setenv("VANTAGE_DATA_DIR", str(tmp_path / "data"))
    game, port = fake
    d = tmp_path / "drive_c" / "users" / "steamuser" / "savegame"
    d.mkdir(parents=True)
    (d / "r.aoe2record").write_bytes(b"x")
    session = Session(GameData(None), tmp_path)
    srv = serve("127.0.0.1", 0, session, [d])
    app: App = srv.app  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(body: dict[str, Any]) -> Any:
        req = urllib.request.Request(base + "/api/live", data=json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    try:
        win = app._windows_replay_path("r.aoe2record")
        got = post({"port": port, "replay": win, "game": 2})
        assert got == {"ok": False, "needs_confirm": True, "code": "FAILED_PLAYING_NEED_CONFIRM"}
        assert session.source["status"] == "needs_confirm"
        assert [r.confirm for n, r in game.calls if n == "LoadGame"] == [False]
        got = post({"port": port, "replay": win, "confirm": True})
        assert got["ok"]
        if got.get("pending"):
            # /api/live may return before the background load finishes. The
            # confirmation contract still requires the eventual game result.
            assert _wait(lambda: session.source.get("load_result") == "SUCCESS")
        else:
            assert got["load_result"] == "SUCCESS"
        assert _wait(lambda: session.timeline is not None and session.timeline.time > 0)
    finally:
        session.stop()
        srv.shutdown()
        srv.server_close()


def test_recording_toggles_mid_session(fake: tuple[FakeGame, int], tmp_path: Path) -> None:
    _, port = fake
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=False)
    # The fake's stream is so short that "playing" may flip to "ended" between
    # polls: either proves a stream ran.
    assert _wait(lambda: session.source.get("status") in ("playing", "ended"))
    assert not list(tmp_path.glob("live-*.vrec"))
    assert session.set_recording(True)["ok"]
    assert _wait(lambda: session.source.get("recording_active") is True)
    stopped = session.set_recording(False)
    assert stopped["ok"] and stopped["saved"] == session.source["recording_saved"]
    assert session.source["recording_active"] is False
    session.stop()
    (rec,) = tmp_path.glob("live-*.vrec")
    assert read_header(rec)["source"] == "live"


def test_joining_a_lobby_asks_before_leaving_a_game(
    fake: tuple[FakeGame, int], tmp_path: Path
) -> None:
    game, port = fake
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=False, lobby="12345", confirm=False)
    assert _wait(lambda: session.source.get("status") == "needs_confirm")
    joins = [r for n, r in game.calls if n == "LoadGame"]
    assert [r.confirm for r in joins] == [False]  # asked, did not agree on its own
    assert joins[0].spectatelobby.lobbyid == "12345"
    session.open_live(port=port, record=False, lobby="12345", confirm=True)
    assert _wait(lambda: len([n for n, _ in game.calls if n == "LoadGame"]) == 2)
    assert [r.confirm for n, r in game.calls if n == "LoadGame"][-1] is True
    session.stop()


def test_port_open_is_a_plain_tcp_probe() -> None:
    import socket

    from vantage.live import port_open

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert port_open("127.0.0.1", port)
    assert not port_open("127.0.0.1", port)


def test_an_ended_game_is_neither_reapplied_nor_rerecorded_on_reconnect(
    fake: tuple[FakeGame, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the game ends every reconnect opens with the same snapshot: it is not
    fed again or written again, and reconnecting backs off."""
    import vantage.server as S

    game, port = fake
    snap = snapshot_builder(2000).push(fid("Root", "world"))
    snap.assign(fid("World", "gameEnded"), "Boolean", 1).pop()
    ended = Frame(time=2000, patch=snap.forward())
    game.stream = lambda: [ended]
    delays: list[tuple[bool, int]] = []

    def delay(game_over: bool, idle: int) -> float:
        delays.append((game_over, idle))
        return 0.02

    monkeypatch.setattr(S, "reconnect_delay", delay)
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=True)
    assert _wait(lambda: len(delays) >= 4)
    session.stop()
    tl = session.timeline
    assert tl is not None and tl.game_ended and tl.frames == 1 and tl.repeated_snapshots >= 3
    assert delays[:4] == [(True, 0), (True, 1), (True, 2), (True, 3)]
    (rec,) = tmp_path.glob("live-*.vrec")
    assert [f.time for f in read_frames(rec)] == [2000]  # one snapshot, not one per stream


def test_a_game_the_game_reports_over_stays_ended_across_reconnects(
    fake: tuple[FakeGame, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replay that reached its end has no gameEnded flag in the world, but the
    game says "match over" (Oracle game state). Every reconnect must keep saying
    so: the viewer decides "the game is over" from the status, and a status that
    went connecting / ready / playing again left it frozen at the last frame."""
    import vantage.server as S

    game, port = fake
    snap = snapshot_builder(2000).push(fid("Root", "world")).pop()
    game.stream = lambda: [Frame(time=2000, patch=snap.forward())]
    delays: list[int] = []
    monkeypatch.setattr(S, "reconnect_delay", lambda over, idle: delays.append(idle) or 0.15)
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=False)
    assert _wait(lambda: session.source.get("status") == "ended")
    seen: set[Any] = set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(delays) < 5:
        seen.add(session.source.get("status"))
        time.sleep(0.002)
    session.stop()
    assert len(delays) >= 5, "the stream did not reconnect"
    assert seen == {"ended"}


def test_the_last_moments_of_a_game_that_ended_become_viewable(
    fake: tuple[FakeGame, int], tmp_path: Path
) -> None:
    """The frames after the newest 1 s keyframe (where a replay's result is decided)
    are shown once the game says it is over, so the last view is the last state."""
    from tests.helpers import delta, snapshot_frame

    game, port = fake
    game.stream = lambda: [
        snapshot_frame(0),
        Frame(time=1050, patch=delta(1050).forward()),
        Frame(time=1450, patch=delta(1450).forward()),
    ]
    session = Session(GameData(None), tmp_path)
    session.open_live(port=port, record=False)
    tl = session.timeline
    assert tl is not None
    assert _wait(lambda: session.source.get("status") == "ended")
    assert _wait(lambda: tl.keyframes and tl.keyframes[-1].time == 1450)
    assert tl.time == 1450 and not tl.complete  # viewable, yet the session is still following the game
    session.stop()


def test_reconnect_backs_off_only_once_the_game_is_over() -> None:
    from vantage.server import RECONNECT_ENDED_MAX_S, RECONNECT_S, reconnect_delay

    assert reconnect_delay(False, 5) == RECONNECT_S
    assert [reconnect_delay(True, n) for n in range(3)] == [3.0, 6.0, 12.0]
    assert reconnect_delay(True, 50) == RECONNECT_ENDED_MAX_S == 60.0

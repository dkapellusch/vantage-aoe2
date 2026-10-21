"""Live connection to the game's ``CadeRemote`` server, speaking the full API.

The game (AoE2 DE) serves ``cade_api.rpc.CadeRemote`` on ``127.0.0.1:4341`` over
mutual TLS once it is running (certificates: :mod:`vantage.certs`). Methods are
called by their wire path with the complete message set rebuilt in
``rpc/cade.proto`` -- all eleven ``Event`` kinds, ``Oracle``, ``SetDesiredGame``
and ``StartScenario`` included.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from vantage.frames import Frame

_PATH = "/cade_api.rpc.CadeRemote/"

#: Speed names accepted by :meth:`LiveGame.set_speed`, slowest first.
SPEEDS = ("SLOW", "NORMAL", "FAST", "EXTRA_FAST")


#: Where the game serves its spectator API.
GAME_HOST = "127.0.0.1"
GAME_PORT = 4341


def port_open(host: str = GAME_HOST, port: int = GAME_PORT, timeout: float = 0.25) -> bool:
    """Whether anything accepts a TCP connection on ``host:port``: a plain
    connect, no TLS, so it answers "is the game running?" at once, where a gRPC
    connect without the certificate only times out."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


#: The newest API version this message set covers: a game that reports a higher
#: one may stream fields Vantage does not know yet ("closed-needs-update").
MAX_API_VERSION = 22
#: ``PermissionDenied`` detail the game sends when it refuses the API to a player.
PLAYER_NO_CAPTUREAGE = "PLAYER_NO_CAPTUREAGE"


def classify_stream_error(exc: BaseException) -> str:
    """The stream status for a failed connection: ``closed-player`` (the
    game refuses the API to a player account), ``closed-unavailable`` (nothing is
    listening) or ``closed-error``."""
    code, details = getattr(exc, "code", None), getattr(exc, "details", None)
    name = getattr(code(), "name", "") if callable(code) else ""
    text = details() if callable(details) else ""
    if name == "PERMISSION_DENIED" and text == PLAYER_NO_CAPTUREAGE:
        return "closed-player"
    return "closed-unavailable" if name == "UNAVAILABLE" else "closed-error"


@dataclass(frozen=True, slots=True)
class LiveInfo:
    game_version: int
    api_version: int
    base_directory: str
    user_directory: str
    language: str
    mods: tuple[str, ...]
    #: The game the client has selected: 0 Age of Empires II, 1 Return of Rome
    #: (``selected_mode`` is the mode folder, e.g. ``modes/Pompeii``).
    selected_game: int = 0
    selected_mode: str = ""


class LiveGame:
    """A session with a running game."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4341) -> None:
        self.target = f"{host}:{port}"
        self._channel: Any = None
        self._calls: dict[str, Callable[..., Any]] = {}
        self._stream: Any = None
        self._oracle: Any = None
        self._lock = threading.Lock()

    def connect(self, timeout: float = 5.0) -> LiveGame:
        """Open a *private* connection to the game.

        The game serves one stream per connection: a second stream on a
        connection that already carried one fails with TSI_DATA_CORRUPTED
        (measured). gRPC normally shares TCP connections between channels to
        the same target, so each LiveGame asks for its own subchannel pool.
        """
        import grpc

        from vantage.certs import SERVER_NAME, CadeError, channel_credentials

        creds = channel_credentials()
        options: list[tuple[str, Any]] = [
            ("grpc.max_receive_message_length", 128 * 1024 * 1024),
            ("grpc.use_local_subchannel_pool", 1),
            # The game's TLS writer corrupts records when it is given a very
            # large HTTP/2 window (it sends big snapshots in one burst):
            # TSI_DATA_CORRUPTED on 6-player games. A bounded window without
            # BDP growth paces it.
            ("grpc.http2.bdp_probe", 0),
            ("grpc.http2.lookahead_bytes", 1 << 20),
        ]
        if creds is None:
            channel = grpc.insecure_channel(self.target, options=options)
        else:
            options += [
                ("grpc.ssl_target_name_override", SERVER_NAME),
                ("grpc.default_authority", SERVER_NAME),
            ]
            channel = grpc.secure_channel(self.target, creds, options=options)
        try:
            grpc.channel_ready_future(channel).result(timeout=timeout)
        except grpc.FutureTimeoutError as exc:
            channel.close()
            raise CadeError(f"no CadeRemote server reachable at {self.target}") from exc
        self._channel = channel
        return self

    def close(self) -> None:
        self.cancel_frames()
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    # -- plumbing -------------------------------------------------------------

    def _call(self, method: str, request: Any, reply_type: Any, timeout: float) -> Any:
        channel = self._channel
        if channel is None:
            raise RuntimeError("not connected")
        fn = self._calls.get(method)
        if fn is None:
            fn = channel.unary_unary(
                _PATH + method,
                request_serializer=lambda m: m.SerializeToString(),
                response_deserializer=reply_type.FromString,
            )
            self._calls[method] = fn
        return fn(request, timeout=timeout)

    # -- RPCs -----------------------------------------------------------------

    def info(self, timeout: float = 5.0) -> LiveInfo:
        from vantage.rpc import cade_pb2 as pb

        r = self._call("Info", pb.InfoRequest(), pb.InfoResponse, timeout)
        return LiveInfo(
            game_version=int(r.gameversion),
            api_version=int(r.apiversion),
            base_directory=str(r.basedirectory),
            user_directory=str(r.userdirectory),
            language=str(r.languagecode),
            mods=tuple(r.enabledmoddirectories),
            selected_game=int(r.selectedgame.enumvalue),
            selected_mode=str(r.selectedgame.modepath),
        )

    def set_desired_game(
        self, game: int, timeout: float = 120.0, confirm: bool | None = None
    ) -> str:
        """Switch the client between Age of Empires II (2) and Return of Rome (1).

        ``confirm`` as in :meth:`load_replay`.
        """
        from vantage.rpc import cade_pb2 as pb

        def _go(confirm: bool) -> int:
            req = pb.SetDesiredGameRequest(desiredgame=game, confirm=confirm)
            return int(self._call("SetDesiredGame", req, pb.SetDesiredGameResponse, timeout).code)

        code = _go(bool(confirm))
        if confirm is None and code == pb.SetDesiredGameResponse.FAILED_PLAYING_NEED_CONFIRM:
            code = _go(True)
        return str(pb.SetDesiredGameResponse.Code.Name(code))

    def pause(self, paused: bool, timeout: float = 5.0) -> bool:
        from vantage.rpc import cade_pb2 as pb

        r = self._call("Pause", pb.PauseRequest(paused=paused), pb.PauseResponse, timeout)
        return bool(r.success)

    def set_fog(self, fog: bool, timeout: float = 5.0) -> bool:
        from vantage.rpc import cade_pb2 as pb

        req = pb.SetFogOfWarRequest(fogofwar=fog)
        return bool(self._call("SetFogOfWar", req, pb.SetFogOfWarResponse, timeout).success)

    def set_perspective(self, player_id: int, timeout: float = 5.0) -> bool:
        from vantage.rpc import cade_pb2 as pb

        req = pb.SetPerspectiveRequest(playerid=player_id)
        return bool(self._call("SetPerspective", req, pb.SetPerspectiveResponse, timeout).success)

    def set_speed(self, speed: str, timeout: float = 5.0) -> bool:
        from vantage.rpc import cade_pb2 as pb

        req = pb.SetGameSpeedRequest(speed=SPEEDS.index(speed))
        return bool(self._call("SetGameSpeed", req, pb.SetGameSpeedResponse, timeout).success)

    def load_replay(
        self,
        windows_path: str,
        timeout: float = 180.0,
        confirm: bool | None = None,
        cloud: bool = False,
    ) -> str:
        """Ask the game to open a ``.aoe2record`` (a path as the game sees it, or
        with ``cloud`` a cloud replay name).

        The game answers ``FAILED_PLAYING_NEED_CONFIRM`` when loading would end
        a game in progress. ``confirm=False`` returns that answer so the user
        can be asked; ``confirm=True`` agrees up front. ``confirm=None`` (the
        default) asks first and then agrees: it is for command-line use only,
        where the user's own command (``vantage record --replay``) is
        the agreement. The web UI never uses it.
        """
        from vantage.rpc import cade_pb2 as pb

        def _go(confirm: bool) -> int:
            req = pb.LoadGameRequest(
                loadreplay=pb.LoadGameRequest.LoadReplay(filepath=windows_path, cloud=cloud),
                confirm=confirm,
                timeoutseconds=int(timeout),
            )
            return int(self._call("LoadGame", req, pb.LoadGameResponse, timeout).code)

        code = _go(bool(confirm))
        if confirm is None and code == pb.LoadGameResponse.FAILED_PLAYING_NEED_CONFIRM:
            code = _go(True)
        return str(pb.LoadGameResponse.Code.Name(code))

    def spectate_lobby(
        self, lobby_id: str, timeout: float = 180.0, confirm: bool | None = None
    ) -> str:
        """Join a lobby as a spectator. ``confirm`` works as in :meth:`load_replay`:
        joining can end a game in progress, so the web UI asks first."""
        from vantage.rpc import cade_pb2 as pb

        def _go(confirm: bool) -> int:
            req = pb.LoadGameRequest(
                spectatelobby=pb.LoadGameRequest.SpectateLobby(lobbyid=lobby_id),
                confirm=confirm,
                timeoutseconds=int(timeout),
            )
            return int(self._call("LoadGame", req, pb.LoadGameResponse, timeout).code)

        code = _go(bool(confirm))
        if confirm is None and code == pb.LoadGameResponse.FAILED_PLAYING_NEED_CONFIRM:
            code = _go(True)
        return str(pb.LoadGameResponse.Code.Name(code))

    def set_window(self, mode: str, timeout: float = 5.0) -> bool:
        """Change the game window: NORMAL, MINIMIZED, MAXIMIZED, FULLSCREEN, RESTORE."""
        from vantage.rpc import cade_pb2 as pb

        codes = {"NORMAL": 1, "MINIMIZED": 2, "MAXIMIZED": 3, "FULLSCREEN": 4, "RESTORE": 5}
        req = pb.ChangeWindowStateRequest(modechange=codes[mode])
        reply = self._call("ChangeWindowState", req, pb.ChangeWindowStateResponse, timeout)
        return int(reply.code) == 0

    def start_scenario(
        self,
        scenario_path: str,
        use_test_difficulty: bool = False,
        restart_if_running: bool = False,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Start a scenario file (the 13th RPC).

        Returns ``{accepted, reason, launch_id}``."""
        from vantage.rpc import cade_pb2 as pb

        req = pb.StartScenarioRequest(
            scenarioPath=scenario_path,
            useTestDifficulty=use_test_difficulty,
            restartIfRunning=restart_if_running,
        )
        r = self._call("StartScenario", req, pb.StartScenarioResponse, timeout)
        return {"accepted": bool(r.accepted), "reason": str(r.reason), "launch_id": int(r.launchId)}

    def oracle(self) -> Iterator[dict[str, Any]]:
        """Game/UI status messages (pause, screen, window, lobby, chat) as dicts.

        A bidirectional stream: one ``InfoRequest`` prayer opens it; the game then
        pushes status changes until :meth:`cancel_frames`/:meth:`close`.
        """
        from google.protobuf.json_format import MessageToDict

        from vantage.rpc import cade_pb2 as pb

        channel = self._channel
        if channel is None:
            raise RuntimeError("not connected")
        hold = threading.Event()

        def prayers() -> Iterator[Any]:
            yield pb.OraclePrayer(inforequest=pb.OraclePrayer.InfoRequest())
            hold.wait()

        call = channel.stream_stream(
            _PATH + "Oracle",
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=pb.OracleMessage.FromString,
        )(prayers())
        with self._lock:
            self._oracle = call
        try:
            for msg in call:
                which = msg.WhichOneof("content") if msg.DESCRIPTOR.oneofs else None
                if which is None:
                    out = MessageToDict(msg, preserving_proto_field_name=True)
                    if out:
                        yield {"kind": "state", **out}
                    continue
                value = getattr(msg, which)
                if isinstance(value, int):  # gametype / gamestate are bare enums
                    yield {"kind": which, "value": value}
                    continue
                yield {
                    "kind": which,
                    **MessageToDict(value, preserving_proto_field_name=True),
                }
        except Exception as exc:
            if _is_cancel(exc):
                return
            raise
        finally:
            hold.set()
            with self._lock:
                self._oracle = None

    def frames(
        self,
        resolution_ms: int | None = 100,
        particles: bool = False,
        particle_whitelist: list[str] | None = None,
        category_ms: dict[int, int] | None = None,
    ) -> Iterator[Frame]:
        """Stream frames until :meth:`cancel_frames` or the server ends the stream.

        ``resolution_ms`` coarsens game time per frame; the patches stay
        cumulative so nothing is lost, only intermediate states are skipped.
        """
        from vantage.frames import from_proto
        from vantage.rpc import cade_pb2 as pb

        channel = self._channel
        if channel is None:
            raise RuntimeError("not connected")
        req = pb.FramesRequest(
            disableparticles=not particles, processattacknotificationsforallplayers=True
        )
        if particles and particle_whitelist:
            # The game streams only whitelisted particle effects (empty = none).
            req.particledefinitionwhitelist.extend(particle_whitelist)
        if resolution_ms is not None:
            req.desiredresolutions.append(
                pb.FramesRequest.ResolutionEntry(key=0, gametimeresolution=resolution_ms)
            )
        # Per-category resolutions (FramesRequest.ResolutionEntry.Category: 1 low
        # priority, 2 sleeping units...): coarser ones spare the game work.
        for key, ms in (category_ms or {}).items():
            req.desiredresolutions.append(
                pb.FramesRequest.ResolutionEntry(key=key, gametimeresolution=ms)
            )
        call = channel.unary_stream(
            _PATH + "Frames",
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=pb.FrameSequence.FromString,
        )(req)
        with self._lock:
            self._stream = call
        try:
            for seq in call:
                wt = int(seq.sendingworldtime)
                for fr in seq.frame:
                    yield from_proto(fr, wt)
        except Exception as exc:
            if _is_cancel(exc):
                return
            raise
        finally:
            with self._lock:
                self._stream = None

    def cancel_frames(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.cancel()
            if self._oracle is not None:
                self._oracle.cancel()


def _is_cancel(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return callable(code) and getattr(code(), "name", "") == "CANCELLED"

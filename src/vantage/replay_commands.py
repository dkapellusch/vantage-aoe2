"""DE input commands recovered from paired captures and native handlers.

Only established wire layouts are decoded. Unknown IDs and unsupported variants return
``None``; callers retain the original :class:`ReplayOperation` bytes. A decoded
command is an order, not proof it succeeded. The dictionary uses the existing
Vantage ``Frame.commands`` vocabulary. See ``native-replay-playback.md``.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from typing import Any


class ReplayCommandError(ValueError):
    """A DE command header disagrees with its enclosing record."""


def _ids(raw: bytes, start: int, count: int) -> list[int] | None:
    if not 0 <= count <= 16384 or len(raw) != start + count * 4:
        return None
    return [v[0] for v in struct.iter_unpack("<i", raw[start:])]


def _location(raw: bytes, start: int) -> dict[str, float]:
    x, y = struct.unpack_from("<ff", raw, start)
    return {"x": x, "y": y}


def decode_replay_command(
    raw: bytes, *, previous_selection: Sequence[int] | None = None
) -> dict[str, Any] | None:
    """Decode an established modern DE action; preserve unsupported shapes as raw.

    The usual command header is ``u8 id, u8 player, u16 body_size``. Resign
    has a distinct five-byte legacy form. No selection, movement, resource or
    production result is invented for an unsupported command.
    """
    if not raw:
        raise ReplayCommandError("empty command")
    action = raw[0]
    if action == 11 and len(raw) == 5:
        return {"kind": "resign", "playerid": raw[1], "commplayerid": raw[2]}
    if len(raw) < 4:
        raise ReplayCommandError("truncated DE command header")
    if struct.unpack_from("<H", raw, 2)[0] != len(raw) - 4:
        raise ReplayCommandError("DE command length disagrees with action length")
    player = raw[1]
    if (
        action == 10
        and len(raw) == 44
        and raw[4:8] == b"\x01\0\0\0"
        and raw[16:20] == bytes(4)
        and raw[42] in {0, 1}
        and raw[43] in {0, 1}
    ):
        # Measured single-recipient AI orders. The two control words are
        # deliberately guarded; group/issuer variants remain unsupported.
        recipient, target = struct.unpack_from("<ii", raw, 8)
        x, y, z, distance = struct.unpack_from("<ffff", raw, 24)
        ai_order = {
            "kind": "aiorder",
            "playerid": player,
            "recipient": recipient,
            "ordertype": struct.unpack_from("<i", raw, 20)[0],
            "orderpriority": raw[40],
            "targetowner": raw[41],
            "location": {"x": x, "y": y, "z": z},
            "range": distance,
            "immediate": bool(raw[42]),
            "infront": bool(raw[43]),
        }
        if target != -1:
            ai_order["target"] = target
        return ai_order
    if action == 41 and len(raw) == 12:
        master, obj = struct.unpack_from("<ii", raw, 4)
        return {"kind": "transformobject", "playerid": player, "masterid": master, "objid": obj}
    if action == 117 and len(raw) >= 33 and raw[6:8] == b"\0\0":
        # Mapper141863580 case117 and the native UnitOrder protobuf parser
        # establish the four flags' distinct order. The reserved count word
        # is guarded; compressed/group variants are not guessed.
        ids = _ids(raw, 33, struct.unpack_from("<H", raw, 4)[0])
        if ids is not None and all(flag in {0, 1} for flag in raw[29:33]):
            target, unique, param = struct.unpack_from("<i8xiI", raw, 8)
            order = {
                "kind": "unitorder",
                "action": raw[28],
                "param": param,
                "location": _location(raw, 12),
                "uniqueId": unique,
                "extend": bool(raw[29]),
                "split": bool(raw[30]),
                "instant": bool(raw[31]),
                "humanorder": bool(raw[32]),
                "unitids": ids,
            }
            if target != -1:
                order["targetid"] = target
            return order
    if action == 103 and len(raw) == 20:
        command, var1, var2, var3, var4 = struct.unpack_from("<IhhfI", raw, 4)
        return {
            "kind": "game",
            "gamecommandid": command,
            "var1": var1,
            "var2": var2,
            "var3": var3,
            "var4": var4,
        }
    if action in {1, 38, 44, 134} and len(raw) >= 8:
        ids = _ids(raw, 8, struct.unpack_from("<I", raw, 4)[0])
        if ids is not None:
            kind = {1: "stop", 38: "autoscout", 44: "seekshelter", 134: "gobacktowork2"}[action]
            return {"kind": kind, "unitids": ids}
    if action == 20 and len(raw) >= 12:
        ids = _ids(raw, 12, struct.unpack_from("<I", raw, 4)[0])
        if ids is not None:
            follow = {"kind": "follow", "unitids": ids}
            target = struct.unpack_from("<i", raw, 8)[0]
            if target != -1:
                follow["targetid"] = target
            return follow
    if action in {18, 23} and len(raw) >= 12:
        count, state = struct.unpack_from("<Ii", raw, 4)
        ids = _ids(raw, 12, count)
        if ids is not None:
            if action == 18:
                return {"kind": "unitaistate", "state": state, "unitids": ids}
            return {
                "kind": "formformation",
                "playerid": player,
                "formationtype": state,
                "unitids": ids,
            }
    if action == 100 and len(raw) == 16:
        unit, unique, obj = struct.unpack_from("<iii", raw, 4)
        return {
            "kind": "make",
            "unitid": unit,
            "unitplayerid": player,
            "objid": obj,
            "uniqueid": unique,
        }
    if action == 101 and len(raw) == 17 and raw[16] in {0, 1}:
        primary, count, technology, unique = struct.unpack_from("<ihhi", raw, 4)
        if count == 1:
            # Native single constructor0x140f5e100 emits no selection array.
            # unitid is the saved primary, not a resolved research candidate.
            # Technology type0x20 follows a distinct executor path; decoding
            # these common wire fields does not choose or validate that path.
            # Cade's mapper overreads raw+17 here and may invent buildingids.
            return {
                "kind": "research",
                "unitid": primary,
                "unitplayerid": player,
                "techid": technology,
                "uniqueid": unique,
                "extend": bool(raw[16]),
            }
    if action == 129 and len(raw) >= 20:
        count, unused, building, unit, amount, button = struct.unpack_from("<Ihhhhi", raw, 4)
        ids = _ids(raw, 20, count)
        if ids is not None and unused == 0:
            return {
                "kind": "multiqueue",
                "playerid": player,
                "selectedbuildingid": building,
                "trainid": unit,
                "traincount": amount,
                "buildingids": ids,
                "buttonlocationid": button,
            }
    if action in {130, 132} and len(raw) >= 9:
        ids = _ids(raw, 9, struct.unpack_from("<I", raw, 4)[0])
        if ids is not None:
            return {
                "kind": "setgatherstate" if action == 130 else "resetbuildings",
                "state": raw[8],
                "unitids": ids,
            }
    if action in {111, 120} and len(raw) >= 25:
        count = struct.unpack_from("<I", raw, 4)[0]
        ids = _ids(raw, 25, count)
        if ids is not None:
            target, word = struct.unpack_from("<ii", raw, 16)
            if action == 120 and raw[24] == 0:
                gather = {
                    "kind": "setgatherpoint",
                    "targetmasterid": word,
                    "location": _location(raw, 8),
                    "unitids": ids,
                }
                if target != -1:
                    gather["targetid"] = target
                return gather
            if action == 111 and raw[24] == bool(count):
                unload = {
                    "kind": "unload",
                    "location": _location(raw, 8),
                    "unloadflag": struct.unpack_from("<I", raw, 20)[0],
                    "unitids": ids,
                }
                if target != -1:
                    unload["unloadunittype"] = target
                return unload
    if action == 37 and len(raw) == 9:
        return {
            "kind": "unittypeaistate",
            "unittype": struct.unpack_from("<i", raw, 4)[0],
            "playerid": player,
            "state": raw[8],
        }
    if action == 135 and len(raw) == 46:
        return {
            "kind": "changeplayername",
            "playerid": player,
            "newname": raw[4:].split(b"\0", 1)[0].decode("utf-8", "replace"),
        }
    if action in {0, 2, 3} and len(raw) >= 24:
        count = struct.unpack_from("<H", raw, 16)[0]
        if count == 0xFFFF:
            ids = list(previous_selection) if previous_selection is not None else None
            if len(raw) != 24:
                ids = None
        else:
            ids = _ids(raw, 24, count)
        if ids is not None and all(v in {0, 1} for v in raw[18:22]):
            target = struct.unpack_from("<i", raw, 4)[0]
            certain = struct.unpack_from("<h", raw, 22)[0]
            out = {
                "kind": {0: "interact", 2: "work", 3: "move"}[action],
                "commplayerid": player,
                "location": _location(raw, 8),
                "instant": bool(raw[20]),
                "humanorder": bool(raw[21]),
                "unitids": ids,
                "extend": bool(raw[19]),
                "controlheld": bool(raw[18]),
            }
            if target != -1:
                out["targetid"] = target
            if action != 2:
                out["certainaction"] = certain
            return out
    if action == 102 and len(raw) >= 32:
        ids = _ids(raw, 32, struct.unpack_from("<I", raw, 4)[0])
        if ids is not None and raw[30] in {0, 1} and raw[31] in {0, 1}:
            obj, unique, sprite, frame = struct.unpack_from("<iiiH", raw, 16)
            return {
                "kind": "build",
                "unitplayerid": player,
                "location": _location(raw, 8),
                "objid": obj,
                "uniqueid": unique,
                "spriteoverrideid": sprite,
                "frame": frame,
                "extend": bool(raw[30]),
                "instant": bool(raw[31]),
                "unitids": [] if ids == [-1] else ids,
            }
    return None


class ReplayCommandDecoder:
    """Decode an ordered stream, retaining each player's compressed selection.

    The measured interact/work/move family shares selections per issuing
    player. A count of ``0xffff`` reuses that family selection. An unsupported
    command clears the player's cache: later reuse remains unknown until an
    explicit selection establishes it again. Construct a new decoder on seek
    unless replaying the preceding commands to restore this state.
    """

    def __init__(self) -> None:
        self._selections: dict[int, list[int]] = {}

    def decode(self, raw: bytes) -> dict[str, Any] | None:
        player = raw[1] if len(raw) >= 2 else -1
        command = decode_replay_command(raw, previous_selection=self._selections.get(player))
        if command is None:
            self._selections.pop(player, None)
        elif raw[0] in {0, 2, 3}:
            self._selections[player] = list(command["unitids"])
        return command

"""Compare replay orders to the real game's independently captured commands."""

from __future__ import annotations

import gzip
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from vantage.replay_commands import (
    ReplayCommandDecoder,
    ReplayCommandError,
    decode_replay_command,
)


def _nondefault(value: Any) -> Any:
    # Protobuf omits default scalars/lists. It keeps an explicitly present
    # empty location message. Float JSON uses fewer digits than binary f32.
    if isinstance(value, dict):
        return {k: _nondefault(v) for k, v in value.items() if v or isinstance(v, dict)}
    if isinstance(value, list):
        return [_nondefault(v) for v in value]
    return value


def _same(actual: Any, expected: Any) -> None:
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _same(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected, strict=True):
            _same(a, b)
    elif isinstance(expected, float):
        assert math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6)
    else:
        assert actual == expected


def test_complete_first_minute_against_independent_native_capture() -> None:
    path = Path(__file__).parent / "fixtures" / "native_replay_commands_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    decoder = ReplayCommandDecoder()
    unknown: Counter[int] = Counter()
    decoded = 0
    known_oracle_defects = 0
    for case in fixture["cases"]:
        raw = bytes.fromhex(case["raw_hex"])
        command = decoder.decode(raw)
        if command is None:
            unknown[raw[0]] += 1
        else:
            if raw[0] == 101:
                # Keep the captured oracle unchanged. Its mapper reads an
                # i32 beyond this fixed17-byte packet and exports[-751].
                # The native packet contains primary9694 and no ID array.
                assert case["offset"] == 3153797 and case["time_ms"] == 38
                assert case["raw_hex"] == "65050d00de25000001001600ffffffff00"
                assert case["expected"]["buildingids"] == [-751]
                assert command["unitid"] == case["expected"]["unitid"] == 9694
                assert "buildingids" not in command
                expected = {k: v for k, v in case["expected"].items() if k != "buildingids"}
                _same(_nondefault(command), expected)
                known_oracle_defects += 1
            else:
                _same(_nondefault(command), case["expected"])
            decoded += 1
    assert len(fixture["cases"]) == 2674
    assert decoded == 2674
    assert unknown == {}
    assert known_oracle_defects == 1


def test_all_paired_additional_families_through_five_minutes() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_additional_commands_54800.json.gz"
    cases = json.loads(gzip.decompress(path.read_bytes()))["cases"]
    assert len(cases) == 749
    kinds: Counter[str] = Counter()
    for case in cases:
        actual = decode_replay_command(bytes.fromhex(case["raw_hex"]))
        assert actual is not None
        _same(_nondefault(actual), case["expected"])
        kinds[actual["kind"]] += 1
    assert kinds == {"aiorder": 113, "unload": 194, "setgatherpoint": 442}


def test_complete_ordered_five_minutes_including_new_families_and_selection_history() -> None:
    path = Path(__file__).parent / "fixtures/native_replay_commands_five_minutes_54800.json.gz"
    fixture = json.loads(gzip.decompress(path.read_bytes()))
    decoder = ReplayCommandDecoder()
    defects = {3153797: [-751], 4049341: [16777216], 4192670: [0]}
    seen_defects = set()
    new_kinds: Counter[str] = Counter()
    for case in fixture["cases"]:
        raw = bytes.fromhex(case["raw_hex"])
        command = decoder.decode(raw)
        assert command is not None, case
        expected = case["expected"]
        if case["offset"] in defects:
            # Keep the native oracle and existing first-minute exception intact.
            # All three packets use the proven fixed17B/count1 constructor.
            assert raw[0] == 101 and len(raw) == 17
            assert struct.unpack_from("<h", raw, 8)[0] == 1
            assert expected["buildingids"] == defects[case["offset"]]
            assert "buildingids" not in command
            expected = {key: value for key, value in expected.items() if key != "buildingids"}
            seen_defects.add(case["offset"])
        _same(_nondefault(command), expected)
        if raw[0] in {20, 44, 117, 132, 134}:
            new_kinds[command["kind"]] += 1
    assert len(fixture["cases"]) == 15644
    assert seen_defects == defects.keys()
    assert new_kinds == {
        "unitorder": 45,
        "follow": 16,
        "seekshelter": 3,
        "gobacktowork2": 1,
        "resetbuildings": 1,
    }
    # The final native frame ends four commands before the raw300000ms cutoff.
    # Their input decoding is checked, without inventing a native counterpart.
    assert len(fixture["unpaired"]) == 4
    for case in fixture["unpaired"]:
        command = decoder.decode(bytes.fromhex(case["raw_hex"]))
        assert command is not None
        _same(command, case["decoded"])


def _packet(action: int, body: bytes, *, player: int = 1) -> bytes:
    return struct.pack("<BBH", action, player, len(body)) + body


def _unit_order(flags: tuple[int, int, int, int] = (0, 0, 1, 0)) -> bytes:
    body = struct.pack("<IiffiIB4B", 2, 123, 2.5, -3.25, -1, 0xFFEEDDCC, 255, *flags)
    return _packet(117, body + struct.pack("<ii", 42, 99))


@pytest.mark.parametrize("bits", range(16))
def test_unit_order_flag_mapping_and_all_wire_fields(bits: int) -> None:
    flags = tuple((bits >> index) & 1 for index in range(4))
    # The native protobuf parser independently binds member40..43 to fields
    # extend/instant/humanorder/split. The input mapper swaps raw30/31/32.
    command = decode_replay_command(_unit_order((flags[0], flags[1], flags[2], flags[3])))
    assert command == {
        "kind": "unitorder",
        "targetid": 123,
        "action": 255,
        "param": 0xFFEEDDCC,
        "location": {"x": 2.5, "y": -3.25},
        "uniqueId": -1,
        "extend": bool(flags[0]),
        "split": bool(flags[1]),
        "instant": bool(flags[2]),
        "humanorder": bool(flags[3]),
        "unitids": [42, 99],
    }


@pytest.mark.parametrize(("action", "kind"), ((44, "seekshelter"), (134, "gobacktowork2")))
@pytest.mark.parametrize("ids", ([], [42], [42, 99, 123]))
def test_new_selection_only_commands_have_exact_count_and_list(
    action: int,
    kind: str,
    ids: list[int],
) -> None:
    body = struct.pack("<I", len(ids)) + struct.pack(f"<{len(ids)}i", *ids)
    assert decode_replay_command(_packet(action, body)) == {"kind": kind, "unitids": ids}


@pytest.mark.parametrize("target", (-1, 123))
def test_follow_and_reset_building_wire_fields(target: int) -> None:
    body = struct.pack("<Iiii", 2, target, 42, 99)
    expected = {"kind": "follow", "unitids": [42, 99]}
    if target != -1:
        expected["targetid"] = target
    assert decode_replay_command(_packet(20, body)) == expected
    assert decode_replay_command(_packet(132, struct.pack("<IBii", 2, 255, 42, 99))) == {
        "kind": "resetbuildings",
        "state": 255,
        "unitids": [42, 99],
    }


@pytest.mark.parametrize("flag_index", (29, 30, 31, 32))
def test_unit_order_unsupported_flag_is_not_partially_decoded(flag_index: int) -> None:
    raw = bytearray(_unit_order())
    raw[flag_index] = 2
    assert decode_replay_command(bytes(raw)) is None


def test_unit_order_reserved_word_and_missing_selection_remain_unsupported() -> None:
    raw = bytearray(_unit_order())
    raw[6] = 1
    assert decode_replay_command(bytes(raw)) is None
    truncated = _unit_order()[:-4]
    assert decode_replay_command(_packet(117, truncated[4:])) is None


@pytest.mark.parametrize("action", (20, 44, 117, 132, 134))
def test_new_family_known_orders_preserve_movement_cache_and_bad_shapes_invalidate(
    action: int,
) -> None:
    packets = {
        20: _packet(20, struct.pack("<Iii", 1, 123, 99)),
        44: _packet(44, struct.pack("<Ii", 1, 99)),
        117: _unit_order(),
        132: _packet(132, struct.pack("<IBi", 1, 1, 99)),
        134: _packet(134, struct.pack("<Ii", 1, 99)),
    }
    decoder = ReplayCommandDecoder()
    decoder.decode(_move(1, [42]))
    assert decoder.decode(packets[action]) is not None
    assert decoder.decode(_move(1, None))["unitids"] == [42]
    # A bad header raises before any cache mutation; a valid header around an
    # unsupported shape follows the existing conservative invalidation policy.
    with pytest.raises(ReplayCommandError):
        decoder.decode(packets[action][:-1])
    assert decoder.decode(_move(1, None))["unitids"] == [42]
    bad = _packet(action, packets[action][4:-1])
    assert decoder.decode(bad) is None
    assert decoder.decode(_move(1, None)) is None


def _move(player: int, ids: list[int] | None) -> bytes:
    count = len(ids) if ids is not None else 0xFFFF
    body = struct.pack("<iffH4Bh", -1, 5, 7, count, 0, 0, 1, 1, 0)
    if ids is not None:
        body += struct.pack(f"<{len(ids)}i", *ids)
    return struct.pack("<BBH", 3, player, len(body)) + body


def test_compressed_selections_are_per_player_and_require_history() -> None:
    decoder = ReplayCommandDecoder()
    assert decoder.decode(_move(1, None)) is None
    decoder.decode(_move(1, [10]))
    decoder.decode(_move(2, [20, 30]))
    assert decoder.decode(_move(1, None))["unitids"] == [10]
    assert decoder.decode(_move(2, None))["unitids"] == [20, 30]
    assert decode_replay_command(_move(1, None)) is None


def test_returned_command_cannot_mutate_selection_history() -> None:
    decoder = ReplayCommandDecoder()
    command = decoder.decode(_move(1, [10]))
    command["unitids"].append(20)
    assert decoder.decode(_move(1, None))["unitids"] == [10]


def test_unknown_order_invalidates_compressed_selection() -> None:
    decoder = ReplayCommandDecoder()
    decoder.decode(_move(1, [10]))
    assert decoder.decode(b"\xfe\x01\0\0") is None
    assert decoder.decode(_move(1, None)) is None
    decoder.decode(_move(1, [40]))
    assert decoder.decode(_move(1, None))["unitids"] == [40]


@pytest.mark.parametrize("raw", [b"", b"\x01", b"\x01\x02\0", b"\x03\x01\xff\xff"])
def test_invalid_command_header_is_reported(raw: bytes) -> None:
    with pytest.raises(ReplayCommandError):
        decode_replay_command(raw)


def test_unsupported_shape_remains_unknown() -> None:
    # No implicit truncation or guessed selection for a missing object id.
    command = _move(1, [10])[:-4]
    command = command[:2] + struct.pack("<H", len(command) - 4) + command[4:]
    assert decode_replay_command(command) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "6f05190001000000000080bf000080bf172600000300000001de250000",
            {
                "kind": "unload",
                "location": {"x": -1.0, "y": -1.0},
                "unloadflag": 3,
                "unloadunittype": 9751,
                "unitids": [9694],
            },
        ),
        (
            "7801190001000000abd62c43abe2dc42ffffffffffffffff00c2250000",
            {
                "kind": "setgatherpoint",
                "targetmasterid": -1,
                "location": {"x": 172.83855, "y": 110.44271},
                "unitids": [9666],
            },
        ),
    ],
)
def test_native_nonempty_unload_and_location_only_gather_point(raw: str, expected) -> None:
    _same(_nondefault(decode_replay_command(bytes.fromhex(raw))), expected)


@pytest.mark.parametrize("offset,value", [(4, 2), (16, 1), (42, 2), (43, 2)])
def test_unmeasured_ai_order_controls_remain_raw(offset: int, value: int) -> None:
    raw = bytearray.fromhex(
        "0a022800010000002b260000ffffffff00000000c10200000000204200009642000080bf0000803f01ff0100"
    )
    raw[offset] = value
    assert decode_replay_command(bytes(raw)) is None


@pytest.mark.parametrize(
    "encoded",
    [
        "6f05190001000000000080bf000080bf172600000300000001de250000",
        "7801190001000000abd62c43abe2dc42ffffffffffffffff00c2250000",
    ],
)
def test_unload_and_gather_point_reject_partial_lists_and_unknown_control(encoded: str) -> None:
    raw = bytearray.fromhex(encoded)
    raw[24] = 2
    assert decode_replay_command(bytes(raw)) is None
    raw = raw[:-1]
    struct.pack_into("<H", raw, 2, len(raw) - 4)
    assert decode_replay_command(bytes(raw)) is None


def _research(
    primary: int = 9694,
    tech: int = 22,
    unique: int = -1,
    extend: int = 0,
    count: int = 1,
    tail: bytes = b"",
) -> bytes:
    body = struct.pack("<ihhiB", primary, count, tech, unique, extend) + tail
    return struct.pack("<BBH", 101, 5, len(body)) + body


@pytest.mark.parametrize(
    "primary,tech,unique,extend",
    [(9694, 22, -1, 0), (12345, 32767, 7, 1), (-2147483648, -32768, -2147483648, 1), (0, 0, 0, 0)],
)
def test_single_research_preserves_wire_fields_without_inventing_selection(
    primary: int, tech: int, unique: int, extend: int
) -> None:
    # Decoding an input does not assert native ID validity, tech bounds or
    # successful execution; the native executor rejects some such orders.
    raw = _research(primary, tech, unique, extend)
    assert len(raw) == 17
    command = decode_replay_command(raw, previous_selection=[10, 20])
    assert command == {
        "kind": "research",
        "unitid": primary,
        "unitplayerid": 5,
        "techid": tech,
        "uniqueid": unique,
        "extend": bool(extend),
    }
    assert "buildingids" not in command and "unitids" not in command
    assert raw == _research(primary, tech, unique, extend)


@pytest.mark.parametrize("count", [-32768, -1, 0, 2, 60, 500, 32767])
def test_research_count_variants_remain_raw_without_native_player_context(count: int) -> None:
    # Nonpositive counts clamp to0 in the native validator. Larger counts
    # use a context-dependent60/500 cap and a distinct selected-ID path.
    assert decode_replay_command(_research(count=count)) is None


@pytest.mark.parametrize(
    "count,tail",
    [(1, struct.pack("<i", 1111)), (2, struct.pack("<2i", 9694, 1111)), (2, b"\0\0\0")],
)
def test_group_research_and_partial_arrays_remain_raw(count: int, tail: bytes) -> None:
    # The group constructor's count1 form has21 bytes; do not confuse its
    # explicit array with the fixed17-byte single constructor.
    assert decode_replay_command(_research(count=count, tail=tail)) is None


@pytest.mark.parametrize("length", [4, 8, 12, 16, 18, 20, 24])
def test_research_unknown_shapes_preserve_raw_bytes(length: int) -> None:
    raw = bytearray((_research() + bytes(8))[:length])
    struct.pack_into("<H", raw, 2, length - 4)
    before = bytes(raw)
    assert decode_replay_command(before) is None
    assert bytes(raw) == before


@pytest.mark.parametrize("extend", [2, 255])
def test_unmeasured_research_control_stays_raw(extend: int) -> None:
    assert decode_replay_command(_research(extend=extend)) is None


def test_research_does_not_replace_movement_selection_and_header_failure_is_atomic() -> None:
    decoder = ReplayCommandDecoder()
    decoder.decode(_move(5, [10, 20]))
    malformed = _research()[:-1]  # Header still declares the full packet.
    with pytest.raises(ReplayCommandError):
        decoder.decode(malformed)
    assert decoder.decode(_move(5, None))["unitids"] == [10, 20]
    assert decoder.decode(_research())["unitid"] == 9694
    assert decoder.decode(_move(5, None))["unitids"] == [10, 20]
    assert decoder.decode(_research(count=2)) is None
    assert decoder.decode(_move(5, None)) is None

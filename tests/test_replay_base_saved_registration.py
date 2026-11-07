"""Owned Python source controls; no original executable or native oracle."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from vantage.replay_base_saved_registration import (
    ReplayBaseSavedRegistrationFP,
    ReplayBaseSavedRegistrationFPCall,
    ReplayBaseSavedRegistrationScratch,
    bind_replay_base_saved_registration,
    register_replay_saved_base,
)
from vantage.replay_task_rebuild import (
    ReplayTaskRebuildCalls,
    ReplayTaskRebuildStorage,
    UnresolvedReplayTaskRebuild,
)

S, M, OWNER = 0x1000, 0x4000, 0x8000
GAME, MODE, WORLD, ROWS = 0x10000, 0x11000, 0x12000, 0x14000
PLAYER, STATE, REL = 0x18000, 0x1C000, 0x20000
VTABLE, PVTABLE, CAST = 0x22000, 0x24000, 0x26000
IMPORT, VIRTUAL, FP = 0x28000, 0x29000, 0x2A000
ENTRY, IAT = 0x1412488E0, 0x143199960
GLOBAL = 0x144353698
U64 = (1 << 64) - 1
MASTER_KEY = 0x6A586EB28AC201FC + 0x0CF19788B2554E70


class Storage:
    """Small strict-defined byte carrier with coherent live local views."""

    def __init__(self) -> None:
        self.bytes: dict[int, int] = {}
        self.locals: list[tuple[int, memoryview]] = []
        self.frames: list[bytes] = []
        self.events: list[tuple[str, int, int, int]] = []
        self.read_hook: Callable[[int, int, int], None] | None = None
        self.write_hook: Callable[[int, int, int], None] | None = None
        self.context = ReplayTaskRebuildStorage(S, self.read, self.write)

    def get(self, address: int, width: int) -> int:
        for base, view in self.locals:
            if base <= address and address + width <= base + len(view):
                return int.from_bytes(view[address - base : address - base + width], "little")
        try:
            return int.from_bytes(bytes(self.bytes[address + i] for i in range(width)), "little")
        except KeyError as error:
            raise UnresolvedReplayTaskRebuild(f"undefined test byte{error.args[0]:x}") from error

    def put(self, address: int, width: int, value: int) -> None:
        raw = (value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        for base, view in self.locals:
            if base <= address and address + width <= base + len(view):
                view[address - base : address - base + width] = raw
                return
        self.bytes.update((address + i, byte) for i, byte in enumerate(raw))

    def read(self, address: int, width: int) -> int:
        value = self.get(address, width)
        self.events.append(("r", address, width, value))
        if self.read_hook:
            self.read_hook(address, width, value)
        return value

    def write(self, address: int, width: int, value: int) -> None:
        self.put(address, width, value)
        self.events.append(("w", address, width, value))
        if self.write_hook:
            self.write_hook(address, width, value)

    @contextmanager
    def bind(self, view: memoryview) -> Iterator[int]:
        base = 0x100000 + len(self.frames) * 0x1000
        self.locals.append((base, view))
        try:
            yield base
        finally:
            self.frames.append(bytes(view))
            assert self.locals.pop() == (base, view)


def encoded_class(value: int) -> int:
    return ((value + 0x47E37DFF0616CE4F) & U64) ^ 0x349E37847AD69F19


def encoded_type(value: int) -> int:
    return (value - 0x5B32AA7995D95916 + 0x50A06BCECEBEF905) & U64


class Scene:
    def __init__(self, word: int = 0x40000000, master_state: int = 0) -> None:
        self.mem = Storage()
        m = self.mem
        m.put(S, 0x400, 0)
        m.put(M, 0x300, 0)
        for address, width, value in (
            (GLOBAL, 8, GAME),
            (GAME + 0x560, 8, MODE),
            (MODE + 8, 4, 0),
            (S + 0x10, 8, M + MASTER_KEY),
            (M + 0x1D4, 4, master_state),
            (M + 0x18, 8, encoded_class(2)),
            (M + 0x38, 8, encoded_type(2)),
            (S + 0x18, 8, OWNER),
            (GAME + 0x5C0, 8, WORLD),
            (WORLD + 0x768, 8, ROWS),
            (WORLD + 0x770, 8, ROWS + 16),
            (ROWS, 8, PLAYER),
            (OWNER + 0x180, 8, REL),
            (REL, 8, 1),
            (OWNER + 0x648, 4, 0),
            (PLAYER + 0x90, 4, 205),
            (PLAYER + 0x98, 8, STATE),
            (PLAYER, 8, PVTABLE),
            (PVTABLE + 0x1C8, 8, FP),
            (S, 8, VTABLE),
            (VTABLE + 0x1E8, 8, VIRTUAL),
            (S + 0x188, 1, 2),
            (IAT, 8, IMPORT),
        ):
            m.put(address, width, value)
        self.set_word(word)
        self.coordinates = (0x7FC12345, 0x80000000, 1)
        x, y, z = self.coordinates
        for offset, encoded in (
            (0x170, x + (0x12345678 << 32) + 0x183CAC30D2441D0E - 0x4C3FBA69E4EA7FD1),
            (0x178, y + (0x23456789 << 32) + 0x61501AA6ECFD980A - 0x6C5EAB60B426DD28),
            (0x180, z + (0x3456789A << 32) - 0x2B3719EF44DE99FF - 0x21D14A25ED7C802C),
        ):
            m.put(S + offset, 8, encoded)
        self.cast = 0
        self.fp_requests: list[ReplayBaseSavedRegistrationFPCall] = []
        self.imports: list[tuple[int, tuple[int, ...]]] = []
        self.virtuals: list[tuple[int, tuple[int, ...]]] = []
        self.import_effect: Callable[[], None] | None = None
        self.fp_effect: Callable[[ReplayBaseSavedRegistrationFPCall], None] | None = None
        self.virtual_effect: Callable[[], None] | None = None

    def set_word(self, word: int) -> None:
        plaintext = 0xA1B2C3D400000000 | word
        encoded = ((plaintext ^ 0xA9834B738A7DD167) + 0x042AC42976FCCEF5) & U64
        self.mem.put(STATE + 0x660, 8, encoded ^ 0xC22D6B496D833977 ^ 0x6AE24D3352F04511)

    def terminal(self, target: int, args: tuple[int, ...], data: memoryview | None) -> int:
        assert data is None
        assert args == (S, 0, 0x14411D848, 0x14411FFA8, 0)
        self.imports.append((target, args))
        self.mem.put(S + 0x2E4, 4, self.mem.get(S + 0x2E4, 4) + 1)
        if self.import_effect:
            self.import_effect()
        return self.cast

    def mixed(self, request: ReplayBaseSavedRegistrationFPCall) -> None:
        self.fp_requests.append(request)
        assert self.mem.get(request.stack_address, 4) == request.stack5_u32
        assert self.mem.get(request.stack_address + 8, 4) == request.stack6_u32
        assert self.mem.get(request.stack_address + 16, 8) == request.stack7_address
        self.mem.put(request.stack7_address, 1, 7)
        self.mem.put(S + 0x2D8, 4, 0x80)
        self.mem.put(S + 0x2E0, 4, self.mem.get(S + 0x2E0, 4) + 1)
        if self.fp_effect:
            self.fp_effect(request)

    def ordinary(self, target: int, args: tuple[int, ...], data: memoryview | None) -> None:
        if target != VIRTUAL or data is not None:
            raise UnresolvedReplayTaskRebuild(f"unknown test effect{target:x}")
        self.virtuals.append((target, args))
        self.mem.put(S + 0x2D8, 4, 0x40)
        if self.virtual_effect:
            self.virtual_effect()

    def bound(self, *, fp: bool = True, imports: bool = True) -> ReplayTaskRebuildCalls:
        return bind_replay_base_saved_registration(
            self.mem.context,
            ReplayTaskRebuildCalls(self.ordinary),
            imports=ReplayTaskRebuildCalls(self.terminal if imports else None),
            fp_calls=ReplayBaseSavedRegistrationFP(self.mixed if fp else None),
            bind_local=self.mem.bind,
            scratch=ReplayBaseSavedRegistrationScratch(bytes([0xA5]) * 0xB0),
        )

    def run(self, *, direct: bool = False, fp: bool = True, imports: bool = True) -> None:
        bound = self.bound(fp=fp, imports=imports)
        if direct:
            register_replay_saved_base(
                self.mem.context,
                S,
                calls=bound,
                fp_calls=ReplayBaseSavedRegistrationFP(self.mixed if fp else None),
                bind_local=self.mem.bind,
                scratch=ReplayBaseSavedRegistrationScratch(bytes([0xA5]) * 0xB0),
            )
        else:
            assert bound.call is not None
            assert bound.call(ENTRY, (S,), None) is None


@pytest.mark.parametrize("direct", [False, True])
def test_full_positive_actual_helper_graph_and_live_mixed_abi(direct: bool) -> None:
    s = Scene()
    s.run(direct=direct)
    assert s.mem.get(M + 0x1D4, 4) == 2
    assert s.mem.get(S + 0x2D8, 4) == 0x81
    assert len(s.imports) == 1
    (request,) = s.fp_requests
    assert (request.target, request.receiver, request.command) == (FP, PLAYER, 0x2B9)
    assert (request.xmm2_u32, request.xmm3_u32, request.stack5_u32) == s.coordinates
    assert s.mem.frames[0][0x21:0x28] == bytes([0, 0, 0, 0xA5, 0xA5, 0xA5, 0xA5])
    assert s.mem.frames[0][0x99:0xA0] == (2).to_bytes(8, "little")[1:]
    assert s.mem.frames[0][0x98] == 7
    assert not s.mem.locals
    with pytest.raises(UnresolvedReplayTaskRebuild):
        s.mem.get(request.stack7_address, 1)


@pytest.mark.parametrize("mode,state", [(4, 0), (0, 1)])
def test_early_returns_do_not_require_later_world_or_effects(mode: int, state: int) -> None:
    s = Scene(master_state=state)
    s.mem.put(MODE + 8, 4, mode)
    del s.mem.bytes[GAME + 0x5C0]
    s.run(fp=False, imports=False)
    assert not s.imports and not s.fp_requests and not s.virtuals
    if mode == 4:
        assert not any(event[1] == S + 0x10 for event in s.mem.events)


def test_initial_master_is_held_for_first_cmp_after_frame_store() -> None:
    s = Scene(master_state=1)
    other = 0x50000
    s.mem.put(other + 0x1D4, 4, 0)

    def mutate(address: int, width: int, value: int) -> None:
        if address == 0x1000A0:
            s.mem.put(address, 8, other)

    s.mem.write_hook = mutate
    s.run()
    assert s.mem.get(M + 0x1D4, 4) == 1
    assert not any(event[1] == other + 0x1D4 for event in s.mem.events)


def test_null_rtti_skips_undefined_tag_and_nonnull_zero_skips_tag() -> None:
    for result in (0, CAST):
        s = Scene()
        s.cast = result
        s.mem.put(CAST + 0x900, 4, 0)
        del s.mem.bytes[S + 0x188]
        s.run()
        assert bool(s.fp_requests) == (result == 0)
        assert not any(event[1] == S + 0x188 for event in s.mem.events)


@pytest.mark.parametrize(
    "word,admitted",
    [
        (0, False),
        (0x80000000, False),
        (1, True),
        (0x80000001, True),
        (0x3F800000, True),
        (0xBF800000, True),
        (0x7F800000, True),
        (0xFF800000, True),
        (0x7FC12345, True),
        (0x7F800001, True),
    ],
)
def test_ucomiss_zero_and_unordered_routes(word: int, admitted: bool) -> None:
    s = Scene()
    s.cast = CAST
    s.mem.put(CAST + 0x900, 4, word)
    s.run()
    assert bool(s.fp_requests) == admitted
    assert s.mem.get(M + 0x1D4, 4) == (2 if admitted else 1)


@pytest.mark.parametrize(
    "word,direction",
    [
        (0, 0),
        (0x80000000, 0),
        (1, 0),
        (0x80000001, 0),
        (0x3F7FFFFF, 0),
        (0xBF7FFFFF, 0),
        (0x3F800000, 1),
        (0xBF800000, -1),
        (0x40300000, 1),
        (0xC0300000, -1),
        (0x4EFFFFFF, 1),
        (0xCEFFFFFF, -1),
        (0x4F000000, -1),
        (0xCF000000, -1),
        (0x7F800000, -1),
        (0xFF800000, -1),
        (0x7F7FFFFF, -1),
        (0x7FC12345, -1),
        (0x7F800001, -1),
    ],
)
def test_raw_cvtt_masked_specials_and_sign_selected_effect(word: int, direction: int) -> None:
    s = Scene(word, master_state=3)
    s.run()
    assert bool(s.fp_requests) == (direction > 0)
    assert bool(s.virtuals) == (direction < 0)
    assert s.mem.get(M + 0x1D4, 4) == (1 if direction == 0 else 3)
    if direction < 0:
        assert s.virtuals == [(VIRTUAL, (S, OWNER, 0, 0xFFFFFFFF, 0))]
        assert s.mem.get(S + 0x2DC, 4) == 1
        assert s.mem.get(S + 0x2D8, 4) == 0x41


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 0),
        (899, 0),
        (900, 1),
        (999, 1),
        (1000, 2),
        (0xFFFFFFFF, 2),
        (0x80000000, 2),
        (0x100000384, 1),
    ],
)
def test_actual_classification_helper_low_ecx(raw: int, expected: int) -> None:
    s = Scene()
    call = s.bound().call
    assert call is not None
    assert call(0x1410B9EE0, (raw,), None) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 0),
        (1, 1),
        (0xFFFFFFFF, 1),
        (0x80000000, 0x80000000),
        (0x7FFFFFFF, 0x7FFFFFFF),
        (0x100000002, 2),
    ],
)
def test_actual_abs_helper_neg32_cmovs(raw: int, expected: int) -> None:
    call = Scene().bound().call
    assert call is not None
    assert call(0x140A81440, (raw,), None) == expected


def test_actual_three_getters_and_rtti_current_terminal_routing() -> None:
    s = Scene()
    call = s.bound().call
    assert call is not None
    assert call(0x140D6A940, (GAME,), None) == 0
    s.mem.put(GAME + 0x560, 8, 0)
    assert call(0x140D6A940, (GAME,), None) == 0
    assert call(0x140D6ACC0, (GAME,), None) == WORLD
    assert call(0x141603FF0, (U64,), None) == 0x767
    args = (S, 0, 0x14411D848, 0x14411FFA8, 0)
    for target in (ENTRY, IMPORT):
        s.mem.put(IAT, 8, target)
        assert call(0x142D6E3D5, args, None) == 0
    assert [target for target, _ in s.imports] == [ENTRY, IMPORT]
    assert sum(event[0] == "r" and event[1] == IAT for event in s.mem.events) == 2


@pytest.mark.parametrize("case", ["null", "same", "unrelated", "threshold", "zero"])
def test_skipped_rows_reach_next_row_with_current_begin_reload(case: str) -> None:
    s = Scene()
    second = ROWS + 0x100
    s.mem.put(WORLD + 0x770, 8, ROWS + 32)
    s.mem.put(second + 16, 8, PLAYER)
    s.mem.put(REL, 8, 0x101)
    if case == "null":
        s.mem.put(ROWS, 8, 0)
    elif case == "same":
        s.mem.put(ROWS, 8, OWNER)
    elif case == "unrelated":
        s.mem.put(REL, 1, 0)
        s.mem.put(PLAYER + 0x180, 8, REL + 0x100)
        s.mem.put(REL + 0x100, 1, 0)
    elif case == "threshold":
        s.mem.put(PLAYER + 0x90, 4, 204)
    else:
        s.set_word(0)

    def advance(address: int, width: int, value: int) -> None:
        if address == ROWS:
            s.mem.put(WORLD + 0x768, 8, second)
            if case in ("unrelated", "threshold", "zero"):
                s.mem.put(second + 16, 8, PLAYER + 0x1000)
                s.mem.put(PLAYER + 0x1000, 8, PVTABLE)
                s.mem.put(PLAYER + 0x1090, 4, 205)
                s.mem.put(PLAYER + 0x1098, 8, STATE + 0x1000)
                encoded = Scene().mem.get(STATE + 0x660, 8)
                s.mem.put(STATE + 0x1660, 8, encoded)

    s.mem.read_hook = advance
    s.run()
    assert len(s.fp_requests) == 1
    assert s.mem.get(S + 0x2D8, 4) == 0x82
    assert sum(event[:3] == ("r", WORLD + 0x768, 8) for event in s.mem.events) == 3


def test_reverse_relationship_signed_owner_id_and_type_category_one() -> None:
    s = Scene(0x44618000)  # 902.0 -> category1,key2
    s.mem.put(REL, 1, 0)
    s.mem.put(OWNER + 0x648, 4, 0xFFFFFFFF)
    s.mem.put(PLAYER + 0x180, 8, REL + 0x100)
    s.mem.put(REL + 0xFF, 1, 1)
    s.run()
    assert len(s.fp_requests) == 1


def test_rejection_stops_before_later_rows_and_existing_mask_rejects() -> None:
    for mask in (0, 1):
        s = Scene()
        s.mem.put(WORLD + 0x770, 8, ROWS + 32)
        if not mask:
            s.mem.put(M + 0x18, 8, encoded_class(3))
        s.mem.put(S + 0x2D8, 4, mask)
        s.run()
        assert s.mem.get(M + 0x1D4, 4) == 1
        assert not s.fp_requests
        assert not any(event[1] == ROWS + 16 for event in s.mem.events)


def test_rtti_mutations_keep_held_begin_current_recipient_and_initial_master() -> None:
    s = Scene()
    recipient = PLAYER + 0x1000
    s.mem.put(recipient, 8, PVTABLE)

    def effects() -> None:
        s.mem.put(WORLD + 0x768, 8, ROWS + 0x100)
        s.mem.put(ROWS, 8, recipient)
        s.mem.put(0x1000A0, 8, 0xDEAD0000)

    s.import_effect = effects
    s.run()
    assert s.fp_requests[0].receiver == recipient
    assert s.mem.get(M + 0x1D4, 4) == 2


def test_selected_fp_target_is_held_before_current_coordinate_loads() -> None:
    s = Scene()

    def mutate(address: int, width: int, value: int) -> None:
        if address == S + 0x180:
            s.mem.put(PVTABLE + 0x1C8, 8, FP + 1)

    s.mem.read_hook = mutate
    s.run()
    assert s.fp_requests[0].target == FP
    assert s.mem.get(PVTABLE + 0x1C8, 8) == FP + 1


def test_fresh_game_world_read_and_held_count_end_before_begin() -> None:
    s = Scene()
    game2, world2 = GAME + 0x1000, WORLD + 0x1000
    s.mem.put(game2 + 0x5C0, 8, world2)
    s.mem.put(world2 + 0x768, 8, ROWS)
    s.mem.put(world2 + 0x770, 8, ROWS + 15)

    def mutate(address: int, width: int, value: int) -> None:
        if address == MODE + 8:
            s.mem.put(GLOBAL, 8, game2)
        if address == world2 + 0x768:
            s.mem.put(world2 + 0x770, 8, ROWS + 16)

    s.mem.read_hook = mutate
    s.run()
    assert s.mem.get(M + 0x1D4, 4) == 1
    assert not s.fp_requests
    assert not any(event[1] == ROWS for event in s.mem.events)


@pytest.mark.parametrize("boundary", ["imports", "fp", "fp_raise", "virtual_raise"])
def test_refusal_and_failure_keep_prior_effects_without_final_mask_commit(boundary: str) -> None:
    s = Scene(
        0xC0000000 if boundary == "virtual_raise" else 0x40000000,
        master_state=3 if boundary == "virtual_raise" else 0,
    )

    def fail() -> None:
        raise UnresolvedReplayTaskRebuild("actual effect refused")

    if boundary == "fp_raise":
        s.fp_effect = lambda request: fail()
    if boundary == "virtual_raise":
        s.virtual_effect = fail
    with pytest.raises(UnresolvedReplayTaskRebuild):
        s.run(fp=boundary != "fp", imports=boundary != "imports")
    assert not s.mem.locals
    assert s.mem.get(M + 0x1D4, 4) == (
        0 if boundary == "imports" else 3 if boundary == "virtual_raise" else 2
    )
    if boundary == "fp_raise":
        assert s.mem.get(S + 0x2D8, 4) == 0x80
        assert s.mem.frames[-1][0x98] == 7
    if boundary == "virtual_raise":
        assert s.mem.get(S + 0x2DC, 4) == 1
        assert s.mem.get(S + 0x2D8, 4) == 0x40


def test_unknown_virtual_or_iat_bytes_refuse_at_reach() -> None:
    s = Scene(0xC0000000, master_state=3)
    s.mem.put(VTABLE + 0x1E8, 8, VIRTUAL + 1)
    with pytest.raises(UnresolvedReplayTaskRebuild):
        s.run()
    assert s.mem.get(S + 0x2DC, 4) == 1
    assert s.mem.get(S + 0x2D8, 4) == 0
    s = Scene()
    del s.mem.bytes[IAT]
    with pytest.raises(UnresolvedReplayTaskRebuild):
        s.run()
    assert s.mem.get(M + 0x1D4, 4) == 0


@pytest.mark.parametrize("target,args", [(ENTRY, ()), (0x140A81440, (0, 1)), (0x142D6E3D5, (S,))])
def test_known_binding_arity_refuses(target: int, args: tuple[int, ...]) -> None:
    call = Scene().bound().call
    assert call is not None
    with pytest.raises(ValueError):
        call(target, args, None)


def test_explicit_provider_and_seed_validation() -> None:
    with pytest.raises(ValueError):
        ReplayBaseSavedRegistrationScratch(bytes(0xAF))
    with pytest.raises(ValueError):
        ReplayBaseSavedRegistrationFPCall(FP, PLAYER, 0, 1 << 32, 0, 0, 0, 0, 0)

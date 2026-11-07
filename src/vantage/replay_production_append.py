"""Complete the proven Master70/ffffffff unit queue append after its real cast.

The existing queue stage stops before RTTI. This separate helper requires the
exact positive native Master70 context established by the original runtime
oracle; it does not implement or infer a cast for another master hierarchy.
Evidence: world-envelope/production-queue-rtti/README.md.
"""

from __future__ import annotations

from dataclasses import replace

from vantage.replay_production_queue import (
    ReplayProductionQueueState,
    ReplayProductionQueueTransition,
)
from vantage.replay_production_resources import _integer

# Same four decoded fields as SavedMaster.vectors[0x338]: hhBI on the wire,
# occupying12 bytes per native entry. No padding or pointer value is invented.
Master70TrainingLocation = tuple[int, int, int, int]


def finish_replay_master70_queue_append(
    pending: ReplayProductionQueueTransition,
    *,
    training_locations: tuple[Master70TrainingLocation, ...],
) -> ReplayProductionQueueState:
    """Native141284d59 through the returned append for the proved Master70 graph.

    The caller must supply the selected master with the exact native positive
    Master70 RTTI context (original vtable1432bc168), not merely an unknown
    object's numeric type byte. The oracle executed the actual declared runtime
    import for this graph; this helper neither executes RTTI nor accepts a
    guessed success/null result. Other hierarchies require separate proof.

    Consume only the needs_unit_cast checkpoint produced after charging,
    tracking, cache writes and UID assignment, with research=-1 and flags=u32
    ffffffff. training_locations is the current selected master's decoded
    vector338: signed16 time/building ID, u8 button and u32 hotkey. Set field2c
    to the first entry's building-ID bits, or0 for an empty vector, then advance
    used, total units and byte revision. UID, cache, padding, other slots and
    all remaining slot fields retain their checkpoint bytes.

    Allocation and other flag values (which enter an object-ID selector path)
    are explicitly unsupported. This is a pure queue completion, not the
    upstream command's charging/tracking or an entity-production scheduler.
    """
    if not isinstance(pending, ReplayProductionQueueTransition):
        raise ValueError("Master70 completion requires a pending queue transition")
    if pending.stage != "needs_unit_cast":
        raise ValueError("Master70 completion requires the needs_unit_cast checkpoint")
    state = pending.state
    if state.used >= state.capacity:
        raise ValueError("Master70 completion requires a backed unused capacity slot")
    slot = state.slots[state.used]
    if slot.flags != 0xFFFFFFFF or slot.research_id != -1:
        raise ValueError("Master70 completion supports only unit research=-1, flags=ffffffff")
    if not 0 <= slot.unit_id <= 32767 or not 0 <= state.units < 15:
        raise ValueError("pending Master70 unit/count is outside the supported native profile")
    if not 1 <= slot.quantity <= 15 - state.units:
        raise ValueError("pending quantity is outside the accepted native15-unit bound")
    if slot.uid != ((state.next_uid - 1) & 0xFFFFFFFFFFFFFFFF) or slot.costs != state.cache:
        raise ValueError("pending slot does not retain its staged UID and current cost cache")
    if not isinstance(training_locations, tuple):
        raise ValueError("Master70 training locations must be decoded native entries")
    for entry in training_locations:
        if not isinstance(entry, tuple) or len(entry) != 4:
            raise ValueError("Master70 training location requires four decoded fields")
        for value, low, high, label in zip(
            entry,
            (-32768, -32768, 0, 0),
            (32767, 32767, 255, 0xFFFFFFFF),
            ("time", "building ID", "button", "hotkey"),
            strict=True,
        ):
            _integer(value, low, high, f"Master70 training {label}")
    value = training_locations[0][1] & 0xFFFF if training_locations else 0
    slots = list(state.slots)
    slots[state.used] = replace(slot, field_2c_bits=value)
    return replace(
        state,
        used=state.used + 1,
        units=state.units + slot.quantity,
        revision=(state.revision + 1) & 255,
        slots=tuple(slots),
    )

"""Compose the existing build54800 logical World caller phases.

Entry141628bf0, normal return14162ba59 and player backedge ab8e->c90 are
verified in world-update-driver-source-v1/source.json. This joins callers;
it does not supply missing descendants or restore a recording's World.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .replay_task_rebuild import ReplayTaskRebuildCalls, ReplayTaskRebuildStorage
from .replay_world_update_command_bridge import run_replay_world_update_command_bridge
from .replay_world_update_control_flags import run_replay_world_update_control_flags
from .replay_world_update_player_links import (
    ReplayWorldUpdatePlayerLinks,
    ReplayWorldUpdatePlayerLinksReentry,
    run_replay_world_update_player_links,
)
from .replay_world_update_player_pass import (
    ReplayWorldUpdatePlayerPass,
    run_replay_world_update_player_pass,
)
from .replay_world_update_postpass import run_replay_world_update_postpass
from .replay_world_update_prelude import run_replay_world_update_prelude
from .replay_world_update_replay_phase import run_replay_world_update_replay_phase
from .replay_world_update_special_mode import run_replay_world_update_special_mode


@dataclass(frozen=True, slots=True)
class ReplayWorldUpdateServices:
    """Explicit category providers; missing reached capabilities still refuse.

    Relationship providers must bind count_home to this invocation's logical
    frame. HOME arguments and partial-register annotations retain the phase
    APIs' meanings. No category falls back to another category or to calls.
    """

    notification_home_calls: ReplayTaskRebuildCalls
    logger_home_calls: ReplayTaskRebuildCalls
    virtual_calls: ReplayTaskRebuildCalls
    virtual_2e8_calls: ReplayTaskRebuildCalls
    policy_home_calls: ReplayTaskRebuildCalls
    position_home_calls: ReplayTaskRebuildCalls
    relationship_calls: ReplayTaskRebuildCalls
    cleanup_virtual_calls: ReplayTaskRebuildCalls
    unit_fp_calls: ReplayTaskRebuildCalls
    geometry_calls: ReplayTaskRebuildCalls
    format_home_calls: ReplayTaskRebuildCalls
    record_home_calls: ReplayTaskRebuildCalls
    runtime_calls: ReplayTaskRebuildCalls
    watson_home_calls: ReplayTaskRebuildCalls

    def __post_init__(self) -> None:
        if any(not isinstance(getattr(self, f.name), ReplayTaskRebuildCalls) for f in fields(self)):
            raise ValueError("explicit category-specific World update Calls required")


def run_replay_world_update(
    context: ReplayTaskRebuildStorage,
    calls: ReplayTaskRebuildCalls,
    world: int,
    incoming_status: int,
    *,
    logical_frame: int,
    services: ReplayWorldUpdateServices,
    mxcsr: int,
) -> int:
    """Run the logical entry through its actual idle, replay or tail return.

    All eight existing phase implementations run on the same caller-supplied
    backed frame. Its untouched bytes and phase-held metadata remain intact.
    Prelude/replay early returns stop immediately; c90 re-entry executes links
    again without restarting admission, clock updates or primary c59 setup.

    The exact masked1f80 profile is required for the complete phase graph.
    Reached child exceptions propagate with earlier memory effects preserved.
    No clock, frame allocation/seed, loop cap, child success, simulation commit
    or native physical prologue/epilogue is supplied by this composition.
    A returned caller status does not establish a runnable restored World.
    """
    if not isinstance(services, ReplayWorldUpdateServices):
        raise ValueError("explicit World update services required")
    if type(mxcsr) is not int or mxcsr != 0x1F80:
        raise ValueError("exact masked MXCSR1f80 World update profile required")
    prelude = run_replay_world_update_prelude(
        context,
        calls,
        world,
        incoming_status,
        logical_frame=logical_frame,
        mxcsr=mxcsr,
    )
    if prelude.returned_status is not None:
        return prelude.returned_status
    replay = run_replay_world_update_replay_phase(context, calls, prelude)
    if replay.returned_status is not None:
        return replay.returned_status
    bridge = run_replay_world_update_command_bridge(
        context,
        calls,
        replay,
        notification_home_calls=services.notification_home_calls,
        logger_home_calls=services.logger_home_calls,
        mxcsr=mxcsr,
    )
    special = run_replay_world_update_special_mode(
        context,
        calls,
        bridge,
        logger_home_calls=services.logger_home_calls,
        mxcsr=mxcsr,
    )
    flags = run_replay_world_update_control_flags(context, calls, special)
    links = run_replay_world_update_player_links(
        context,
        calls,
        flags,
        logger_home_calls=services.logger_home_calls,
        relationship_calls=services.relationship_calls,
        virtual_calls=services.virtual_calls,
    )
    tail_phase: ReplayWorldUpdatePlayerLinks | ReplayWorldUpdatePlayerPass
    if links.next_address == 0x14162AB9E:
        tail_phase = links
    else:
        while True:
            player = run_replay_world_update_player_pass(
                context,
                calls,
                links,
                virtual_calls=services.virtual_calls,
                virtual_2e8_calls=services.virtual_2e8_calls,
                policy_home_calls=services.policy_home_calls,
                position_home_calls=services.position_home_calls,
                relationship_calls=services.relationship_calls,
                mxcsr=mxcsr,
            )
            if not isinstance(player, ReplayWorldUpdatePlayerLinksReentry):
                tail_phase = player
                break
            links = run_replay_world_update_player_links(
                context,
                calls,
                player,
                logger_home_calls=services.logger_home_calls,
                relationship_calls=services.relationship_calls,
                virtual_calls=services.virtual_calls,
            )
    tail = run_replay_world_update_postpass(
        context,
        calls,
        tail_phase,
        virtual_calls=services.virtual_calls,
        cleanup_virtual_calls=services.cleanup_virtual_calls,
        unit_fp_calls=services.unit_fp_calls,
        geometry_calls=services.geometry_calls,
        format_home_calls=services.format_home_calls,
        record_home_calls=services.record_home_calls,
        runtime_calls=services.runtime_calls,
        watson_home_calls=services.watson_home_calls,
    )
    # The concrete postpass always prepares a DWORD return, including its
    # shared replay-stop arm. Do not invent success for a broken phase contract.
    if tail.returned_status is None:
        raise RuntimeError("World postpass did not prepare its actual return")
    return tail.returned_status

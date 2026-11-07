"""Explicit native engine selection with no default-build fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .native_conversion import pin
from .native_engine_protocol import (
    CAPTURE_PROTOCOL,
    PROTOCOL_VERSION,
    ConversionRequest,
    EngineProtocolError,
    ReplayIdentity,
    content_digest,
)

FAMILY_FIELDS = {
    "build",
    "save_version",
    "options_version",
    "dataset_id",
    "game_mode",
    "selected_content_mode",
}
PROFILE_ROLES = {"source", "runtime", "encoder"}


@dataclass(frozen=True)
class EngineSpec:
    engine_id: str
    families: tuple[dict[Any, Any], ...]
    capabilities: tuple[str, ...]
    profiles: dict[Any, Any]
    qualification: str = "experimental"
    backend: str = "v32-sdk-1"

    @classmethod
    def from_json(cls, value: dict[Any, Any]) -> EngineSpec:
        if (
            value.get("protocol_version") != PROTOCOL_VERSION
            or type(value.get("protocol_version")) is not int
            or value.get("capture_protocol") != CAPTURE_PROTOCOL
            or value.get("backend") != "v32-sdk-1"
            or value.get("qualification") != "experimental"
        ):
            # A later release must add a checked qualification-attestation format.
            raise EngineProtocolError("Unsupported engine contract or qualification")
        families = value.get("families")
        if (
            type(families) is not list
            or not families
            or any(
                type(f) is not dict
                or set(f) != FAMILY_FIELDS
                or any(type(v) is not int for v in f.values())
                for f in families
            )
        ):
            raise EngineProtocolError("Explicit replay families are required")
        caps = value.get("capabilities")
        if (
            type(caps) is not list
            or any(type(c) is not str or not c for c in caps)
            or caps != sorted(set(caps))
        ):
            raise EngineProtocolError("Capabilities must be sorted unique names")
        profiles = value.get("profiles")
        if type(profiles) is not dict or set(profiles) != PROFILE_ROLES:
            raise EngineProtocolError("Three explicit native profiles are required")
        for row in profiles.values():
            if (
                type(row) is not dict
                or set(row) != {"path", "bytes", "sha256"}
                or type(row["path"]) is not str
                or not Path(row["path"]).is_absolute()
                or type(row["bytes"]) is not int
                or row["bytes"] <= 0
                or type(row["sha256"]) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            ):
                raise EngineProtocolError("Invalid engine profile pin")
        identity = {
            k: value[k]
            for k in (
                "protocol_version",
                "capture_protocol",
                "backend",
                "qualification",
                "families",
                "capabilities",
            )
        }
        identity["profiles"] = {
            k: {n: v for n, v in r.items() if n != "path"} for k, r in profiles.items()
        }
        expected = content_digest(identity)
        if value.get("engine_id") != expected:
            raise EngineProtocolError("Engine contract identity differs")
        return cls(expected, tuple(families), tuple(caps), profiles)

    def verify_profiles(self) -> None:
        for row in self.profiles.values():
            path = Path(row["path"])
            if path.resolve(strict=True) != path or pin(path) != row:
                raise EngineProtocolError(f"Engine profile changed: {path}")


class EngineRegistry:
    def __init__(self, engines: tuple[EngineSpec, ...]):
        if not engines or len({e.engine_id for e in engines}) != len(engines):
            raise EngineProtocolError("Registry must have distinct explicit engines")
        self.engines = engines

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> EngineRegistry:
        observed = pin(path)
        raw = path.read_bytes()
        value = json.loads(raw)
        if (
            observed["sha256"] != expected_sha256
            or pin(path) != observed
            or value.get("kind") != "vantage_native_engine_registry"
            or type(value.get("version")) is not int
            or value["version"] != 1
        ):
            raise EngineProtocolError("Registry identity or schema differs")
        return cls(tuple(EngineSpec.from_json(v) for v in value["engines"]))

    def select(self, request: ConversionRequest) -> tuple[EngineSpec, ReplayIdentity]:
        from .native_input import NativeInputError, describe_native_input
        from .replay import read_replay

        if not isinstance(request, ConversionRequest):
            raise EngineProtocolError("Typed conversion request required")
        if not request.allow_experimental:
            raise EngineProtocolError("These engine packages require experimental opt-in")
        replay = request.replay.resolve(strict=True)
        initial = pin(replay)
        header = read_replay(replay, with_duration=False)
        candidates = [
            e for e in self.engines if any(f["build"] == header.build for f in e.families)
        ]
        if not candidates:
            raise EngineProtocolError(f"Unsupported replay build: {header.build}")
        try:
            d = describe_native_input(replay)
        except NativeInputError as error:
            raise EngineProtocolError(f"Unsupported replay input: {error}") from error
        if pin(replay) != initial or d.recording_sha256 != initial["sha256"]:
            raise EngineProtocolError("Replay changed during identification")
        identity = ReplayIdentity(
            initial["sha256"],
            initial["bytes"],
            d.build,
            d.save_version,
            d.options_version,
            d.dataset_id,
            d.game_mode,
            d.selected_content_mode,
        )
        candidates = [
            e
            for e in candidates
            if identity.family() in e.families
            and set(request.required_capabilities) <= set(e.capabilities)
        ]
        if len(candidates) != 1:
            raise EngineProtocolError("No unique engine satisfies replay family and capabilities")
        selected = candidates[0]
        selected.verify_profiles()
        return selected, identity

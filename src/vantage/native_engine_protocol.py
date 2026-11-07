"""Build-independent request and result contracts for native replay workers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
CAPTURE_PROTOCOL = "v32-streams-1"


class EngineProtocolError(ValueError):
    """A request is unsupported before native worker startup."""


def content_digest(value: dict[Any, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class ConversionRequest:
    replay: Path
    protocol_version: int = PROTOCOL_VERSION
    required_capabilities: tuple[str, ...] = ()
    allow_experimental: bool = False

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != PROTOCOL_VERSION:
            raise EngineProtocolError("Unsupported native engine protocol version")
        if (
            type(self.required_capabilities) is not tuple
            or any(type(c) is not str or not c for c in self.required_capabilities)
            or len(set(self.required_capabilities)) != len(self.required_capabilities)
        ):
            raise EngineProtocolError("Required capabilities must be unique names")
        if type(self.allow_experimental) is not bool:
            raise EngineProtocolError("Experimental opt-in must be boolean")


@dataclass(frozen=True)
class ReplayIdentity:
    sha256: str
    bytes: int
    build: int
    save_version: int
    options_version: int
    dataset_id: int
    game_mode: int
    selected_content_mode: int

    def family(self) -> dict[Any, Any]:
        return {key: value for key, value in asdict(self).items() if key not in {"sha256", "bytes"}}


@dataclass(frozen=True)
class ConversionResult:
    status: str
    engine_id: str
    replay: ReplayIdentity
    recording: dict[Any, Any] | None = None
    conversion_report: dict[Any, Any] | None = None
    capabilities: tuple[str, ...] = ()
    message: str | None = None
    protocol_version: int = PROTOCOL_VERSION
    capture_protocol: str = CAPTURE_PROTOCOL

    def __post_init__(self) -> None:
        if self.status not in {"ready", "cancelled", "failed"}:
            raise EngineProtocolError("Unsupported conversion result status")
        if self.status == "ready" and (not self.recording or not self.conversion_report):
            raise EngineProtocolError("A ready result requires recording and terminal provenance")
        if self.status != "ready" and (
            self.recording is not None or self.conversion_report is not None
        ):
            raise EngineProtocolError("Failed or cancelled work cannot publish a recording")

    def to_json(self) -> dict[Any, Any]:
        return asdict(self)

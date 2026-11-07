"""Adapt the existing V32 converter to the stable native engine contract."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .native_conversion import ConversionCancelled, ConversionError, pin
from .native_engine_protocol import ConversionRequest, ConversionResult, EngineProtocolError
from .native_engine_registry import EngineRegistry
from .native_v32_config import V32Config


class V32Engine:
    """One request; selection happens before compiler or worker construction."""

    def __init__(
        self,
        registry: EngineRegistry,
        *,
        cache_dir: Path,
        runtime_timeout: float = 2400,
        encoder_timeout: float = 1800,
        reuse_job: Path | None = None,
    ) -> None:
        self.registry = registry
        self.cache_dir = cache_dir
        self.runtime_timeout = runtime_timeout
        self.encoder_timeout = encoder_timeout
        self.reuse_job = reuse_job
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._converter: Any = None
        self._used = False

    def cancel(self) -> None:
        with self._lock:
            self._cancelled.set()
            if self._converter is not None:
                self._converter.cancel()

    def convert(self, request: ConversionRequest) -> ConversionResult:
        with self._lock:
            if self._used:
                raise EngineProtocolError("Native engine instances are single-use")
            self._used = True
        spec, identity = self.registry.select(request)
        with self._lock:
            if self._cancelled.is_set():
                return ConversionResult("cancelled", spec.engine_id, identity)
            p = spec.profiles
            config = V32Config(
                profile=Path(p["source"]["path"]),
                profile_sha256=p["source"]["sha256"],
                runtime_profile=Path(p["runtime"]["path"]),
                runtime_profile_sha256=p["runtime"]["sha256"],
                encoder_config=Path(p["encoder"]["path"]),
                encoder_config_sha256=p["encoder"]["sha256"],
                cache_dir=self.cache_dir,
                replay_roots=(request.replay.resolve().parent,),
                runtime_timeout=self.runtime_timeout,
                encoder_timeout=self.encoder_timeout,
                reuse_job=self.reuse_job,
            )
            self._converter = config.converter()
        try:
            recording = self._converter.convert(request.replay.resolve(strict=True))
            report_path = recording.parent / "conversion.json"
            report_pin = pin(report_path)
            report = json.loads(report_path.read_bytes())
            if (
                report.get("status") != "conversion_verified"
                or report.get("recording_end_reason") not in {"native_game_end", "recording_eof"}
                or pin(report_path) != report_pin
                or pin(request.replay)["sha256"] != identity.sha256
            ):
                raise ConversionError("Converted recording provenance differs")
            spec.verify_profiles()
            with self._lock:
                if self._cancelled.is_set():
                    return ConversionResult("cancelled", spec.engine_id, identity)
                return ConversionResult(
                    "ready", spec.engine_id, identity, pin(recording), report_pin, spec.capabilities
                )
        except ConversionCancelled as error:
            return ConversionResult("cancelled", spec.engine_id, identity, message=str(error))
        except ConversionError as error:
            return ConversionResult("failed", spec.engine_id, identity, message=str(error))

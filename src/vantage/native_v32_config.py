"""Explicit configuration for the experimental V32 Session backend."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class V32Config:
    profile: Path
    profile_sha256: str
    cache_dir: Path
    replay_roots: tuple[Path, ...]
    runtime_profile: Path
    runtime_profile_sha256: str
    encoder_config: Path
    encoder_config_sha256: str
    runtime_timeout: float = 2400
    encoder_timeout: float = 1800
    stage_timeout: float = 300
    compile_timeout: float = 180
    reuse_job: Path | None = None
    update_cap: int | None = None

    def __post_init__(self) -> None:
        # Positive-first projections use cap+1 in a DWORD; all V32 inputs
        # require at least three syncs and two additional guard slots.
        if self.update_cap is not None and (
            type(self.update_cap) is not int or not 5 <= self.update_cap <= 0xFFFFFFFE
        ):
            raise ValueError("V32 update cap must be an integer between 5 and 4294967294")
        for name in ("profile_sha256", "runtime_profile_sha256", "encoder_config_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise ValueError(f"explicit V32 {name} required")
        for name in ("profile", "runtime_profile", "encoder_config"):
            path = getattr(self, name).expanduser().resolve(strict=True)
            if not path.is_file():
                raise ValueError(f"invalid V32 {name}")
            object.__setattr__(self, name, path)
        for name in ("runtime_timeout", "encoder_timeout", "stage_timeout", "compile_timeout"):
            if not 0 < getattr(self, name) <= (3600 if name == "compile_timeout" else 86400):
                raise ValueError(f"invalid V32 {name}")
        roots = tuple(root.expanduser().resolve(strict=True) for root in self.replay_roots)
        if any(not root.is_dir() for root in roots) or len(set(roots)) != len(roots):
            raise ValueError("native replay roots must be distinct configured directories")
        object.__setattr__(self, "cache_dir", self.cache_dir.expanduser().resolve())
        object.__setattr__(self, "replay_roots", roots)
        if self.reuse_job is not None:
            job = self.reuse_job.expanduser().resolve(strict=True)
            if not job.is_dir():
                raise ValueError("invalid V32 retained job")
            object.__setattr__(self, "reuse_job", job)

    def converter(self) -> Any:
        from .native_v32_backend import V32Conversion

        return V32Conversion(self)

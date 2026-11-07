"""The engine boundary rejects unsupported inputs before constructing a worker."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from vantage.native_conversion import ConversionCancelled, ConversionError, pin
from vantage.native_engine_protocol import (
    CAPTURE_PROTOCOL,
    ConversionRequest,
    ConversionResult,
    EngineProtocolError,
    ReplayIdentity,
    content_digest,
)
from vantage.native_engine_registry import EngineRegistry, EngineSpec
from vantage.native_engine_v32 import V32Engine

FAMILY = dict(
    build=54800,
    save_version=4515430,
    options_version=1150050304,
    dataset_id=1,
    game_mode=0,
    selected_content_mode=2,
)


@pytest.fixture
def setup_engine(tmp_path, monkeypatch):
    from vantage import native_input, replay

    recording = tmp_path / "record.aoe2record"
    recording.write_bytes(b"replay-input")
    profiles = {}
    for role in ("source", "runtime", "encoder"):
        path = tmp_path / f"{role}.json"
        path.write_text("{}")
        profiles[role] = pin(path)
    doc = dict(
        protocol_version=1,
        capture_protocol=CAPTURE_PROTOCOL,
        backend="v32-sdk-1",
        qualification="experimental",
        families=[FAMILY],
        capabilities=["world_frames"],
        profiles=profiles,
    )
    content = dict(
        doc, profiles={k: {n: v for n, v in r.items() if n != "path"} for k, r in profiles.items()}
    )
    doc["engine_id"] = content_digest(content)
    spec = EngineSpec.from_json(doc)
    desc = SimpleNamespace(**FAMILY, recording_sha256=pin(recording)["sha256"])
    monkeypatch.setattr(replay, "read_replay", lambda *a, **kw: SimpleNamespace(build=desc.build))
    monkeypatch.setattr(native_input, "describe_native_input", lambda p: desc)
    return recording, profiles, doc, spec, desc


def test_rejects_unknown_protocol_and_false_boolean():
    for version in (True, 0, 2):
        with pytest.raises(EngineProtocolError):
            ConversionRequest(Path("unused"), protocol_version=version)
    with pytest.raises(EngineProtocolError):
        ConversionRequest(Path("unused"), allow_experimental="yes")


def test_registry_requires_experimental_opt_in_and_matching_family(setup_engine):
    recording, _, _, spec, desc = setup_engine
    registry = EngineRegistry((spec,))
    with pytest.raises(EngineProtocolError, match="opt-in"):
        registry.select(ConversionRequest(recording))
    request = ConversionRequest(recording, allow_experimental=True)
    assert registry.select(request)[0] == spec
    desc.build = 99999
    with pytest.raises(EngineProtocolError, match="Unsupported replay build"):
        registry.select(request)
    desc.build, desc.dataset_id = 54800, 3
    with pytest.raises(EngineProtocolError, match="No unique engine"):
        registry.select(request)


def test_missing_capability_and_ambiguous_engine_are_rejected(setup_engine):
    from dataclasses import replace

    recording, _, _, spec, _ = setup_engine
    with pytest.raises(EngineProtocolError, match="No unique engine"):
        EngineRegistry((spec,)).select(
            ConversionRequest(recording, required_capabilities=("events",), allow_experimental=True)
        )
    with pytest.raises(EngineProtocolError, match="No unique engine"):
        EngineRegistry((spec, replace(spec, engine_id="other"))).select(
            ConversionRequest(recording, allow_experimental=True)
        )


def test_changed_profile_and_registry_digest_are_rejected(setup_engine, tmp_path):
    recording, profiles, doc, spec, _ = setup_engine
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(
        json.dumps(dict(kind="vantage_native_engine_registry", version=1, engines=[doc]))
    )
    registry = EngineRegistry.load(registry_file, pin(registry_file)["sha256"])
    assert registry.engines == (spec,)
    with pytest.raises(EngineProtocolError, match="Registry identity"):
        EngineRegistry.load(registry_file, "0" * 64)
    Path(profiles["source"]["path"]).write_text("changed")
    with pytest.raises(EngineProtocolError, match="profile changed"):
        registry.select(ConversionRequest(recording, allow_experimental=True))


def test_request_cannot_start_worker_when_unsupported(setup_engine, tmp_path, monkeypatch):
    recording, _, _, spec, desc = setup_engine
    desc.build = 12345
    starts = []
    monkeypatch.setattr("vantage.native_engine_v32.V32Config", lambda **kw: starts.append(kw))
    with pytest.raises(EngineProtocolError):
        V32Engine(EngineRegistry((spec,)), cache_dir=tmp_path).convert(
            ConversionRequest(recording, allow_experimental=True)
        )
    assert starts == []


@pytest.mark.parametrize(
    "error,status",
    [
        (ConversionCancelled("cancelled"), "cancelled"),
        (ConversionError("checksum mismatch"), "failed"),
    ],
)
def test_failed_or_cancelled_conversion_never_publishes(
    setup_engine,
    tmp_path,
    monkeypatch,
    error,
    status,
):
    recording, _, _, spec, _ = setup_engine

    class Converter:
        def convert(self, replay):
            raise error

    monkeypatch.setattr("vantage.native_engine_v32.V32Config.converter", lambda self: Converter())
    engine = V32Engine(EngineRegistry((spec,)), cache_dir=tmp_path)
    result = engine.convert(ConversionRequest(recording, allow_experimental=True))
    assert result.status == status and result.recording is None
    with pytest.raises(EngineProtocolError, match="single-use"):
        engine.convert(ConversionRequest(recording, allow_experimental=True))


def test_cancel_before_creation_starts_no_worker(setup_engine, tmp_path, monkeypatch):
    recording, _, _, spec, _ = setup_engine
    starts = []
    monkeypatch.setattr("vantage.native_engine_v32.V32Config", lambda **kw: starts.append(kw))
    engine = V32Engine(EngineRegistry((spec,)), cache_dir=tmp_path)
    engine.cancel()
    result = engine.convert(ConversionRequest(recording, allow_experimental=True))
    assert result.status == "cancelled" and not starts


def test_invalid_result_does_not_look_ready():
    identity = ReplayIdentity("0" * 64, 5, **FAMILY)
    with pytest.raises(EngineProtocolError, match="provenance"):
        ConversionResult("ready", "engine", identity)
    with pytest.raises(EngineProtocolError, match="cannot publish"):
        ConversionResult("failed", "engine", identity, recording={"path": "x"})


def test_mutated_contract_identity_is_rejected(setup_engine):
    _, _, doc, _, _ = setup_engine
    doc["families"] = [dict(FAMILY, build=12345)]
    with pytest.raises(EngineProtocolError, match="identity differs"):
        EngineSpec.from_json(doc)

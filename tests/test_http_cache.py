"""Large JSON and source assets compress without buffering streams or artwork."""

from __future__ import annotations

import gzip

import pytest

from vantage.http_cache import content_encoding


@pytest.mark.parametrize("kind", ["application/json", "text/javascript", "text/css", "text/html"])
def test_large_data_compresses_and_preserves_existing_vary(kind: str) -> None:
    raw = b'{"catalog":"' + b"x" * 5000 + b'"}'
    body, headers = content_encoding(raw, kind, "gzip, br", {"Vary": "Origin"})
    assert len(body) < len(raw) // 10
    assert gzip.decompress(body) == raw
    assert headers == {"Content-Encoding": "gzip", "Vary": "Origin, Accept-Encoding"}


@pytest.mark.parametrize("accept", ["", "identity", "gzip;q=0", "gzip;q=0, *;q=1", "gzip;q=bad"])
def test_negotiation_respects_clients_declining_gzip(accept: str) -> None:
    raw = b"x" * 4096
    assert content_encoding(raw, "application/json", accept)[0] == raw


def test_small_responses_images_and_streams_are_not_compressed() -> None:
    for body, kind in [
        (b"{}", "application/json"),
        (b"x" * 4096, "image/png"),
        (b"x" * 4096, "text/event-stream"),
    ]:
        assert content_encoding(body, kind, "gzip") == (body, {})

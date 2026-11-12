"""Bounded, negotiated compression shared by the desktop viewer and upload hub."""

from __future__ import annotations

import gzip
from functools import lru_cache


@lru_cache(maxsize=8)
def _gzip_body(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=3, mtime=0)


def content_encoding(
    body: bytes,
    ctype: str,
    accept_encoding: str,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str]]:
    headers = dict(headers or {})
    if (
        ctype == "text/event-stream"
        or len(body) < 1024
        or not (
            ctype.startswith("text/")
            or ctype
            in (
                "application/json",
                "application/javascript",
                "image/svg+xml",
            )
        )
    ):
        return body, headers
    accepted = {}
    for item in accept_encoding.lower().split(","):
        coding, _, parameters = item.strip().partition(";")
        try:
            quality = float(parameters.strip().removeprefix("q=")) if parameters else 1.0
        except ValueError:
            quality = 0.0
        accepted[coding] = quality
    headers["Vary"] = ", ".join(filter(None, (headers.get("Vary"), "Accept-Encoding")))
    if accepted.get("gzip", accepted.get("*", 0)) > 0:
        zipped = _gzip_body(body)
        if len(zipped) < len(body):
            headers["Content-Encoding"] = "gzip"
            return zipped, headers
    return body, headers

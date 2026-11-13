"""A stand-in for the internet between a browser and the hub: HTTP/2 over TLS in
front (as Google's front end gives the real page), a delay and a bandwidth cap
behind it (the Cloud Run proxy, the tunnel home), then the upstream over
HTTP/1.1 with kept-alive connections (as Caddy does).

    uv run --with hypercorn --with httpx --with cryptography python tools/perf/remote_proxy.py \
        --listen 8797 --upstream http://127.0.0.1:8795 --rtt 80 --mbps 30 \
        [--header X-Hub-Proxy-Secret=... --header X-Goog-Authenticated-User-Email=...]

Each request waits rtt/2 before it is passed on and its answer rtt/2 before the
first byte goes back; the body then flows at the bandwidth cap (shared by all
answers, as one link is). The certificate is made on the spot and self-signed:
run the browser with --ignore-certificate-errors.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import tempfile
import time
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from hypercorn.asyncio import serve
from hypercorn.config import Config

HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "te", "trailer", "host"}


def certificate(folder: Path) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


class Link:
    """One link's bandwidth: answers queue for it byte by byte."""

    def __init__(self, bytes_per_s: float) -> None:
        self.rate = bytes_per_s
        self.free_at = 0.0

    async def send(self, n: int) -> None:
        if self.rate <= 0:
            return
        now = time.monotonic()
        start = max(now, self.free_at)
        self.free_at = start + n / self.rate
        if self.free_at > now:
            await asyncio.sleep(self.free_at - now)


def app(upstream: str, rtt_ms: float, mbps: float, extra: dict[str, str]):
    client = httpx.AsyncClient(
        base_url=upstream, timeout=120, limits=httpx.Limits(max_connections=200)
    )
    link = Link(mbps * 1e6 / 8)
    half = rtt_ms / 2000
    stats = {"requests": 0, "bytes": 0, "sprites": 0, "views": 0}

    async def handle(scope, receive, send):
        if scope["type"] != "http":
            return
        if scope["path"] == "/__stats":
            # What crossed the link since the last look (the benchmark asks).
            body = json.dumps(stats).encode()
            for k in stats:
                stats[k] = 0
            head = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
            await send({"type": "http.response.start", "status": 200, "headers": head})
            await send({"type": "http.response.body", "body": body})
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {
            k.decode(): v.decode() for k, v in scope["headers"] if k.decode().lower() not in HOP
        }
        headers.update(extra)
        path = scope["raw_path"].decode() if scope.get("raw_path") else scope["path"]
        if scope.get("query_string") and "?" not in path:
            path += "?" + scope["query_string"].decode()
        await asyncio.sleep(half)
        request = client.build_request(scope["method"], path, headers=headers, content=body)
        answer = await client.send(request, stream=True)
        try:
            await asyncio.sleep(half)
            out = [
                (k.encode(), v.encode())
                for k, v in answer.headers.multi_items()
                if k.lower() not in HOP
            ]
            await send(
                {"type": "http.response.start", "status": answer.status_code, "headers": out}
            )
            stats["requests"] += 1
            stats["sprites"] += "/sprite/" in path
            stats["views"] += "/api/view" in path
            async for chunk in answer.aiter_raw():
                await link.send(len(chunk))
                stats["bytes"] += len(chunk)
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await answer.aclose()

    return handle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--listen", type=int, required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--rtt", type=float, default=80, help="round trip added to every request, ms")
    ap.add_argument("--mbps", type=float, default=30, help="download bandwidth (0: unlimited)")
    ap.add_argument("--header", action="append", default=[], help="NAME=VALUE added upstream")
    args = ap.parse_args()
    extra = dict(h.split("=", 1) for h in args.header)
    with tempfile.TemporaryDirectory() as tmp:
        config = Config()
        config.bind = [f"127.0.0.1:{args.listen}"]
        config.certfile, config.keyfile = certificate(Path(tmp))
        config.alpn_protocols = ["h2", "http/1.1"]
        config.accesslog = None
        # Hypercorn closes a connection after 1,000 requests (and after 5 s without a new
        # one), whatever is still being sent on it. A viewer makes that many in its first
        # seconds over one HTTP/2 connection: every download under way then failed, the
        # 4-6 MB particle atlases among them. A link to a hosted hub does not do that.
        config.keep_alive_max_requests = 10**9
        config.keep_alive_timeout = 600
        asyncio.run(serve(app(args.upstream, args.rtt, args.mbps, extra), config))


if __name__ == "__main__":
    main()

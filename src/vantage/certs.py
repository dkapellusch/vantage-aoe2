"""Where Vantage finds the client certificate the game's API server asks for.

The game serves its spectator API over mutual TLS: it presents a server
certificate named ``ca-game-api`` and accepts only clients whose certificate
was issued by the same authority. Vantage does not ship that certificate.
Point ``VANTAGE_CERTS`` at a folder holding the three PEM files, or put them in
:func:`default_certs_dir`. See :data:`LIVE_GAMES_DOCS`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from vantage.paths import config_dir

#: The name the game's server certificate is issued to; the TLS handshake must
#: ask for it (SNI and ``:authority``), whatever host it connects to.
SERVER_NAME = "ca-game-api"
CA_FILE = "certificate-authority.pem"
CLIENT_CERT_FILE = "cade-client.pem"
CLIENT_KEY_FILE = "cade-client.key"
CERT_FILES = (CA_FILE, CLIENT_CERT_FILE, CLIENT_KEY_FILE)
#: The docs page about the certificate files and where they go.
LIVE_GAMES_DOCS = "https://github.com/dkapellusch/vantage/wiki/Live-games"


class CadeError(RuntimeError):
    """A connection or call to the game's API server failed."""


def default_certs_dir() -> Path:
    return config_dir() / "certs"


def certs_dir() -> Path:
    """``$VANTAGE_CERTS`` when set, else :func:`default_certs_dir`."""
    env = os.environ.get("VANTAGE_CERTS")
    return Path(env).expanduser() if env else default_certs_dir()


def missing_cert_files(folder: Path | None = None) -> list[str]:
    """The certificate files absent from ``folder`` (default :func:`certs_dir`)."""
    base = folder or certs_dir()
    return [name for name in CERT_FILES if not (base / name).is_file()]


def cert_status(folder: Path | None = None) -> dict[str, Any]:
    """The certificate folder, the files missing from it and the setup guide,
    as the UI shows them (``/api/session`` ``certs``)."""
    base = folder or certs_dir()
    return {"dir": str(base), "missing": missing_cert_files(base), "docs": LIVE_GAMES_DOCS}


def channel_credentials(folder: Path | None = None) -> Any | None:
    """gRPC credentials from the certificate folder, or None when it is incomplete
    (the connection is then attempted without TLS, which the real game refuses)."""
    base = folder or certs_dir()
    if missing_cert_files(base):
        return None
    import grpc

    return grpc.ssl_channel_credentials(
        root_certificates=(base / CA_FILE).read_bytes(),
        private_key=(base / CLIENT_KEY_FILE).read_bytes(),
        certificate_chain=(base / CLIENT_CERT_FILE).read_bytes(),
    )

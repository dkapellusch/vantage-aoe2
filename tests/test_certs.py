"""vantage.certs: the certificate files."""

from __future__ import annotations

from pathlib import Path

from vantage.certs import missing_cert_files


def test_missing_cert_files(tmp_path: Path) -> None:
    assert len(missing_cert_files(tmp_path)) == 3
    (tmp_path / "certificate-authority.pem").write_text("x")
    assert "certificate-authority.pem" not in missing_cert_files(tmp_path)

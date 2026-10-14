"""Local one-file import server does not need the web UI on :8080."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.request import urlopen

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from one_click_check import start_export_server  # noqa: E402


def test_serves_only_the_export_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "demo_checked.yaml"
        payload = b"proxies:\n  - name: HK-01\n"
        path.write_bytes(payload)
        extra = Path(td) / "secret.yaml"
        extra.write_bytes(b"do-not-serve")
        server, port, hits = start_export_server(path)
        try:
            url = f"http://127.0.0.1:{port}/{path.name}"
            with urlopen(url, timeout=3) as resp:
                assert resp.status == 200
                assert resp.read() == payload
            assert hits["n"] >= 1
            try:
                urlopen(f"http://127.0.0.1:{port}/secret.yaml", timeout=3)
                raise AssertionError("other files must not be served")
            except Exception as exc:
                if "404" not in str(exc) and "Not Found" not in str(exc):
                    # urlopen raises HTTPError 404
                    from urllib.error import HTTPError
                    if not isinstance(exc, HTTPError) or exc.code != 404:
                        raise
        finally:
            server.shutdown()


def main() -> int:
    try:
        test_serves_only_the_export_file()
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print("PASS  import server serves one file on localhost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

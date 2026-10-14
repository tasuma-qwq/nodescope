"""Offline tests for the one-click stable sync (fixed-port subscribe server)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import one_click_check as occ  # noqa: E402
from core.subscription import friendly_stable_base  # noqa: E402


def _fetch(port, path, timeout=3):
    return urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout)


def _free_port() -> int:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_friendly_stable_base():
    assert friendly_stable_base("gw树洞.yaml") == "gw树洞_已检测"
    assert friendly_stable_base("gw树洞_已检测") == "gw树洞_已检测"
    assert friendly_stable_base("").startswith("已检测")
    assert ":" not in friendly_stable_base("a:b*c.yaml")


def test_serve_latest_refreshes_content_and_headers():
    with tempfile.TemporaryDirectory() as td:
        saved_dir = occ.EXPORTS_DIR
        occ.EXPORTS_DIR = Path(td)
        port = _free_port()  # the real stable server may already own 57520
        try:
            occ.EXPORTS_DIR.mkdir(exist_ok=True)
            (occ.EXPORTS_DIR / occ.STABLE_FILENAME).write_bytes(b"proxies:\n  - name: v1\n")
            (occ.EXPORTS_DIR / occ.STABLE_META).write_text(
                json.dumps({"filename": "gw树洞_已检测.yaml", "userinfo": "upload=0; download=5; total=10"}),
                encoding="utf-8",
            )
            server = occ.build_latest_server(port)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with _fetch(port, f"/{occ.STABLE_FILENAME}") as resp:
                    assert resp.status == 200
                    assert resp.read() == b"proxies:\n  - name: v1\n"
                    assert resp.headers.get("subscription-userinfo") == "upload=0; download=5; total=10"
                    assert "filename*" in resp.headers.get("Content-Disposition", "")
                try:
                    _fetch(port, "/other.yaml")
                    raise AssertionError("foreign path must 404")
                except HTTPError as exc:
                    assert exc.code == 404

                # A new detection run overwrites the file; same URL must serve it.
                (occ.EXPORTS_DIR / occ.STABLE_FILENAME).write_bytes(b"proxies:\n  - name: v2\n")
                with _fetch(port, f"/{occ.STABLE_FILENAME}") as resp:
                    assert resp.read() == b"proxies:\n  - name: v2\n"
            finally:
                server.shutdown()
                server.server_close()
        finally:
            occ.EXPORTS_DIR = saved_dir


def test_spawn_stable_server_alive_then_kill():
    if occ._port_occupied():
        print("    (stable port already served; skipping spawn test)")
        return
    proc = occ._spawn_latest_server()
    assert proc is not None
    try:
        deadline = time.time() + 6
        while time.time() < deadline and not occ._server_alive():
            time.sleep(0.2)
        assert occ._server_alive(), "detached stable server must come alive"
    finally:
        proc.terminate()
    deadline = time.time() + 4
    while time.time() < deadline and occ._server_alive():
        time.sleep(0.2)
    assert not occ._server_alive(), "terminated server must stop answering"


def test_stable_headers_fallback_without_meta():
    with tempfile.TemporaryDirectory() as td:
        saved_dir = occ.EXPORTS_DIR
        occ.EXPORTS_DIR = Path(td)
        try:
            occ.EXPORTS_DIR.mkdir(exist_ok=True)
            (occ.EXPORTS_DIR / occ.STABLE_FILENAME).write_bytes(b"proxies: []\n")
            # No meta sidecar: headers fall back to content parsing → no userinfo.
            headers = occ._stable_headers("gw树洞_已检测.yaml")
            assert "subscription-userinfo" not in headers
            assert "filename*" in headers["Content-Disposition"]
            # Garbage meta must not crash either.
            (occ.EXPORTS_DIR / occ.STABLE_META).write_text("{broken", encoding="utf-8")
            headers2 = occ._stable_headers("gw树洞_已检测.yaml")
            assert "Content-Disposition" in headers2
        finally:
            occ.EXPORTS_DIR = saved_dir


def test_stable_profile_imported_detection():
    with tempfile.TemporaryDirectory() as td:
        saved_root = occ.APP_ROOT
        occ.APP_ROOT = Path(td)
        try:
            assert occ.stable_profile_imported() is False  # missing profiles.yaml
            (occ.APP_ROOT / "profiles.yaml").write_text(
                "current: u1\nitems:\n  - uid: u1\n    type: remote\n"
                "    url: http://127.0.0.1:57520/checked_latest.yaml\n",
                encoding="utf-8",
            )
            assert occ.stable_profile_imported() is True
            (occ.APP_ROOT / "profiles.yaml").write_text(
                "current: u1\nitems:\n  - uid: u1\n    type: remote\n"
                "    url: https://airport.example/sub\n",
                encoding="utf-8",
            )
            assert occ.stable_profile_imported() is False
        finally:
            occ.APP_ROOT = saved_root


def main() -> int:
    tests = [
        test_friendly_stable_base,
        test_serve_latest_refreshes_content_and_headers,
        test_stable_headers_fallback_without_meta,
        test_spawn_stable_server_alive_then_kill,
        test_stable_profile_imported_detection,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

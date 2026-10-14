"""Offline tests for subscription metadata: traffic parsing, headers, naming."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.subscription import (  # noqa: E402
    build_userinfo_header,
    content_disposition_header,
    friendly_export_base,
    parse_traffic_nodes,
    userinfo_from_extra,
    userinfo_from_traffic,
)

GB = 2**30


def _proxy(name):
    return {"name": name, "type": "ss", "server": "example.com"}


def test_traffic_pair_english():
    # "Traffic: a | b" = used | total (verified against Verge's extra numbers)
    traffic = parse_traffic_nodes([_proxy("Traffic: 2.38GB | 200GB")])
    assert traffic == {"used": int(2.38 * GB), "total": 200 * GB}


def test_used_chinese():
    traffic = parse_traffic_nodes([_proxy("已用流量：2.38 GB")])
    assert traffic == {"used": int(2.38 * GB)}


def test_remaining_chinese():
    traffic = parse_traffic_nodes([_proxy("剩余流量：150.75 GB")])
    assert traffic == {"remaining": int(150.75 * GB)}


def test_expire_formats():
    stamp = int(datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp())
    assert parse_traffic_nodes([_proxy("Expire: 2026-10-19")]) == {"expire": stamp}
    stamp2 = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    assert parse_traffic_nodes([_proxy("套餐到期：2026-10-01")]) == {"expire": stamp2}


def test_real_subscription_status_nodes():
    proxies = [
        _proxy("Expire: 2026-10-19"),
        _proxy("Traffic: 2.38GB | 200GB"),
        _proxy("Sync: 2026-09-18 16:00:03"),
    ]
    traffic = parse_traffic_nodes(proxies)
    assert traffic["used"] == int(2.38 * GB)
    assert traffic["total"] == 200 * GB
    assert traffic["expire"] == int(datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp())


def test_no_traffic_returns_none_and_never_raises():
    assert parse_traffic_nodes([_proxy("HK-01"), _proxy("JP 【8% 住宅|原生】")]) is None
    assert parse_traffic_nodes([]) is None
    assert parse_traffic_nodes(None) is None
    assert parse_traffic_nodes([None, "x", 3, {"no_name": 1}, _proxy("剩余流量：abc GB")]) is None


def test_userinfo_from_extra():
    extra = {"upload": 4544673755, "download": 21771941768, "total": 109521666048, "expire": 1789795070}
    assert userinfo_from_extra(extra) == extra
    assert userinfo_from_extra({"download": "0", "total": 100}) == {"total": 100}
    assert userinfo_from_extra(None) is None
    assert userinfo_from_extra({"download": "bad"}) is None


def test_userinfo_from_traffic_variants():
    values = userinfo_from_traffic({"used": int(2.38 * GB), "total": 200 * GB})
    assert values["download"] == int(2.38 * GB)
    assert values["total"] == 200 * GB
    assert values["upload"] == 0

    from_remaining = userinfo_from_traffic({"remaining": 100 * GB, "total": 200 * GB})
    assert from_remaining["download"] == 100 * GB

    only_remaining = userinfo_from_traffic({"remaining": 100 * GB})
    assert only_remaining == {"upload": 0, "download": 0, "total": 100 * GB}

    assert userinfo_from_traffic({"expire": 1789795070})["expire"] == 1789795070
    assert userinfo_from_traffic(None) is None
    assert userinfo_from_traffic({}) is None


def test_userinfo_header_format():
    header = build_userinfo_header(
        {"upload": 0, "download": 21771941768, "total": 109521666048, "expire": 1789795070}
    )
    assert header == "upload=0; download=21771941768; total=109521666048; expire=1789795070"
    assert build_userinfo_header(None) is None
    assert build_userinfo_header({"expire": -1}) is None


def test_friendly_export_base():
    base = friendly_export_base("gw树洞.yaml", datetime(2026, 9, 19, 14, 30))
    assert base == "gw树洞_已检测_0919-1430"
    base2 = friendly_export_base('Revo6W99lR0Z_checked_2026:09*18', datetime(2026, 9, 19, 9, 5))
    assert ":" not in base2 and "*" not in base2
    assert friendly_export_base("", datetime(2026, 9, 19, 0, 0)).startswith("已检测_")
    assert friendly_export_base(None, datetime(2026, 9, 19, 23, 59)).startswith("已检测_")


def test_content_disposition():
    header = content_disposition_header("gw树洞_已检测_0919-1430.yaml")
    assert "filename*=" in header and "attachment" in header
    assert ".yaml" in header
    assert "filename=" in content_disposition_header("plain.yaml")


def test_import_server_sends_headers():
    from one_click_check import start_export_server

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "gw树洞_已检测_0919-1430.yaml"
        payload = "proxies:\n  - name: HK-01\n".encode("utf-8")
        path.write_bytes(payload)
        headers = {
            "Content-Disposition": content_disposition_header(path.name),
            "subscription-userinfo": "upload=0; download=1; total=2; expire=3",
        }
        server, port, _ = start_export_server(path, headers)
        try:
            from urllib.parse import quote

            url = f"http://127.0.0.1:{port}/{quote(path.name)}"
            with urlopen(url, timeout=3) as resp:
                assert resp.status == 200
                assert resp.read() == payload
                assert resp.headers.get("subscription-userinfo") == headers["subscription-userinfo"]
                assert "filename*" in resp.headers.get("Content-Disposition", "")
        finally:
            server.shutdown()


def test_subscribe_endpoint_serves_latest_with_headers():
    import routers.api as api

    async def call():
        return await api.export_subscribe()

    saved_dir = api.EXPORTS_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            api.EXPORTS_DIR = os.path.join(td, "exports")
            os.makedirs(api.EXPORTS_DIR)
            # No latest yet → 404
            try:
                asyncio.run(call())
                raise AssertionError("missing latest must 404")
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status != 404:
                    raise
            # With latest + meta → 200, headers, body
            Path(api.EXPORTS_DIR, "checked_latest.yaml").write_bytes(b"proxies: []\n")
            Path(api.EXPORTS_DIR, "checked_latest.meta.json").write_text(
                '{"userinfo": "upload=0; download=5; total=10", "filename": "已检测_0919-1430_8节点.yaml"}',
                encoding="utf-8",
            )
            resp = asyncio.run(call())
            assert resp.status_code == 200
            assert resp.body == b"proxies: []\n"
            assert resp.headers["subscription-userinfo"] == "upload=0; download=5; total=10"
            assert "filename*" in resp.headers["content-disposition"]
            # Meta lost → still serves, header falls back to node parsing (none here)
            os.remove(Path(api.EXPORTS_DIR, "checked_latest.meta.json"))
            resp2 = asyncio.run(call())
            assert resp2.status_code == 200
            assert "subscription-userinfo" not in resp2.headers
    finally:
        api.EXPORTS_DIR = saved_dir


def main() -> int:
    tests = [
        test_traffic_pair_english,
        test_remaining_chinese,
        test_expire_formats,
        test_real_subscription_status_nodes,
        test_no_traffic_returns_none_and_never_raises,
        test_userinfo_from_extra,
        test_userinfo_from_traffic_variants,
        test_userinfo_header_format,
        test_friendly_export_base,
        test_content_disposition,
        test_import_server_sends_headers,
        test_subscribe_endpoint_serves_latest_with_headers,
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

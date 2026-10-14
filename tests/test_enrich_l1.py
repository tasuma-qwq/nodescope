"""L1 ip-api failure must not skip DNSBL / L2/L3."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.ip_checker import IPChecker  # noqa: E402
from core.sources import dnsbl, ipapi  # noqa: E402


async def _run() -> None:
    orig_ipapi = ipapi.IPApiSource.check
    orig_dnsbl = dnsbl.DNSBLSource.check

    async def no_ipapi(self, ip):
        return None

    async def hit(self, ip):
        return {"hits": ["bl.spamcop.net"], "reasons": {"bl.spamcop.net": "x"}}

    ipapi.IPApiSource.check = no_ipapi
    dnsbl.DNSBLSource.check = hit
    try:
        result = await IPChecker().enrich("1.2.3.4", api_keys={})
        assert "ipapi_failed" in (result.get("multi_errors") or []), result
        assert result.get("dnsbl_blacklisted") is True, result
        assert "dnsbl" in (result.get("multi_sources") or []), result
        assert result.get("dnsbl_hits") == ["bl.spamcop.net"], result
    finally:
        ipapi.IPApiSource.check = orig_ipapi
        dnsbl.DNSBLSource.check = orig_dnsbl


def main() -> int:
    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print("PASS  enrich continues after ip-api failure")
    return 0


def test_enrich_continues_after_l1_failure():
    asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

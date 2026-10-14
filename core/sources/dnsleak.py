"""DNS leak check via edns.ip-api.com through the current proxy."""
from typing import Dict, Optional

import aiohttp

_UNKNOWN = {
    "dns_leak": None,
    "dns_leak_state": "unknown",
    "dns_ip": "",
    "dns_geo": "",
}

_EDNS_URL = "https://edns.ip-api.com/json"


class DNSLeakSource:
    async def check(self, proxy: Optional[str] = None, exit_ip: Optional[str] = None) -> Dict:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(_EDNS_URL, proxy=proxy) as resp:
                    if resp.status != 200:
                        return dict(_UNKNOWN)
                    data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return dict(_UNKNOWN)
            dns = data.get("dns")
            if not isinstance(dns, dict):
                return dict(_UNKNOWN)
            dns_ip = str(dns.get("ip") or "").strip()
            if not dns_ip:
                return dict(_UNKNOWN)
            dns_geo = str(dns.get("geo") or "")
            if exit_ip is None:
                return {
                    "dns_leak": None,
                    "dns_leak_state": "unknown",
                    "dns_ip": dns_ip,
                    "dns_geo": dns_geo,
                }
            if dns_ip == str(exit_ip).strip():
                return {
                    "dns_leak": False,
                    "dns_leak_state": "clean",
                    "dns_ip": dns_ip,
                    "dns_geo": dns_geo,
                }
            return {
                "dns_leak": True,
                "dns_leak_state": "leak",
                "dns_ip": dns_ip,
                "dns_geo": dns_geo,
            }
        except Exception:
            return dict(_UNKNOWN)

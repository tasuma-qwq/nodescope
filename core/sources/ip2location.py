"""L2: IP2Location.io — enabled only when API key is configured."""
from typing import Dict, Optional

import aiohttp


class IP2LocationSource:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""

    async def check(self, ip: str) -> Optional[Dict]:
        if not self.api_key:
            return None
        url = "https://api.ip2location.io/"
        params = {"key": self.api_key, "ip": ip}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        return None
                    data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return None
            if data.get("error"):
                return None
            def _b(key):
                v = data.get(key)
                return bool(v) if v is not None else None

            return {
                "country_code": data.get("country_code") or None,
                "country": data.get("country_name") or None,
                "isp": data.get("isp") or None,
                "usage_type": data.get("usage_type") or None,
                "is_proxy": _b("is_proxy"),
                "is_tor": _b("is_tor"),
                "is_vpn": _b("is_vpn"),
                "is_datacenter": _b("is_datacenter"),
                "is_mobile": _b("is_mobile"),
            }
        except Exception:
            return None

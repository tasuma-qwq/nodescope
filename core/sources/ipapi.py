"""L1: ip-api.com — free, no API key required."""
from typing import Dict, Optional

import aiohttp


class IPApiSource:
    async def check(self, ip: str) -> Optional[Dict]:
        url = (
            f"http://ip-api.com/json/{ip}"
            "?fields=status,message,country,countryCode,regionName,city,"
            "timezone,isp,org,as,mobile,proxy,hosting,query"
        )
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        return None
                    data = await resp.json(content_type=None)
            if not isinstance(data, dict) or data.get("status") != "success":
                return None
            return {
                "country_code": data.get("countryCode") or None,
                "country": data.get("country") or None,
                "city": data.get("city") or None,
                "region": data.get("regionName") or None,
                "isp": data.get("isp") or None,
                "org": data.get("org") or None,
                "asn": data.get("as") or None,
                "is_mobile": bool(data.get("mobile")),
                "is_proxy": bool(data.get("proxy")),
                "is_hosting": bool(data.get("hosting")),
            }
        except Exception:
            return None

"""L3: IPQualityScore — enabled only when API key is configured."""
from typing import Dict, Optional

import aiohttp


class IPQSSource:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""

    async def check(self, ip: str) -> Optional[Dict]:
        if not self.api_key:
            return None
        url = f"https://www.ipqualityscore.com/api/json/ip/{self.api_key}/{ip}"
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        return None
                    data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return None
            if data.get("success") is False:
                return None
            fraud = data.get("fraud_score")
            asn_val = data.get("ASN") if data.get("ASN") is not None else data.get("asn")
            if asn_val is not None and not str(asn_val).startswith("AS"):
                asn_val = f"AS{asn_val}"
            def _b(key):
                v = data.get(key)
                return bool(v) if v is not None else None

            return {
                "fraud_score": int(fraud) if fraud is not None else None,
                "is_vpn": _b("vpn"),
                "is_proxy": _b("proxy"),
                "is_tor": _b("tor"),
                "connection_type": data.get("connection_type") or None,
                "country_code": data.get("country_code") or None,
                "city": data.get("city") or None,
                "isp": data.get("ISP") or data.get("isp") or None,
                "asn": str(asn_val) if asn_val is not None else None,
            }
        except Exception:
            return None

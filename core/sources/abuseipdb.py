"""L2: AbuseIPDB — enabled only when API key is configured."""
from typing import Dict, Optional

import aiohttp


class AbuseIPDBSource:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""

    async def check(self, ip: str) -> Optional[Dict]:
        if not self.api_key:
            return None
        url = "https://api.abuseipdb.com/api/v2/check"
        headers = {
            "Key": self.api_key,
            "Accept": "application/json",
        }
        params = {"ipAddress": ip, "maxAgeInDays": 90}
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status < 200 or resp.status >= 300:
                        return None
                    payload = await resp.json(content_type=None)
            if not isinstance(payload, dict):
                return None
            if payload.get("errors"):
                return None
            data = payload.get("data") or {}
            if not isinstance(data, dict):
                return None
            score = data.get("abuseConfidenceScore")
            reports = data.get("totalReports")
            return {
                "abuse_score": int(score) if score is not None else None,
                "total_reports": int(reports) if reports is not None else None,
                "usage_type": data.get("usageType") or None,
            }
        except Exception:
            return None

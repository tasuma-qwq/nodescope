"""DNSBL blacklist lookup via dnspython. Hit on any zone is a hard veto."""
from __future__ import annotations

import asyncio
import ipaddress
from typing import Dict, List, Optional, Tuple

import dns.exception
import dns.resolver

DEFAULT_ZONES = [
    "zen.spamhaus.org", "bl.spamcop.net", "dnsbl.sorbs.net",
    "dnsbl.dronebl.org", "b.barracudacentral.org", "bl.blocklist.de",
    "tor.dnsbl.sectoor.de",
]

_LOOPBACK_NET = ipaddress.ip_network("127.0.0.0/8")
# Spamhaus "blocked / open resolver" answers (not a listing).
_BLOCKED_RESOLVER_NET = ipaddress.ip_network("127.255.255.0/24")


def _reverse_ipv4(ip: str) -> Optional[str]:
    try:
        addr = ipaddress.IPv4Address((ip or "").strip())
    except (ipaddress.AddressValueError, ValueError, AttributeError):
        return None
    return ".".join(reversed(str(addr).split(".")))


def _is_dnsbl_a_hit(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr in _LOOPBACK_NET and addr not in _BLOCKED_RESOLVER_NET
    except (ValueError, TypeError):
        return False


def _txt_reason(rdata) -> str:
    strings = getattr(rdata, "strings", None)
    if strings:
        parts = []
        for s in strings:
            if isinstance(s, bytes):
                parts.append(s.decode("utf-8", "replace"))
            else:
                parts.append(str(s))
        return "".join(parts)
    text = rdata.to_text()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


class DNSBLSource:
    def __init__(self, zones: Optional[List[str]] = None):
        self.zones = list(zones) if zones is not None else list(DEFAULT_ZONES)

    def _query_zone(self, reversed_ip: str, zone: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = 2.0
            resolver.lifetime = 3.0
            query = f"{reversed_ip}.{zone}"
            answers = resolver.resolve(query, "A")
            hit = False
            for rdata in answers:
                if _is_dnsbl_a_hit(rdata.to_text().strip()):
                    hit = True
                    break
            if not hit:
                return (None, None)
            reason = None
            try:
                txts = resolver.resolve(query, "TXT")
                parts = [_txt_reason(rdata) for rdata in txts]
                parts = [p for p in parts if p]
                reason = " ".join(parts) if parts else None
            except Exception:
                reason = None
            return (zone, reason)
        except dns.resolver.NXDOMAIN:
            return (None, None)
        except dns.exception.Timeout:
            return (None, None)
        except Exception:
            return (None, None)

    async def check(self, ip: str) -> Optional[Dict]:
        try:
            reversed_ip = _reverse_ipv4(ip)
            if reversed_ip is None:
                return {"hits": [], "reasons": {}}

            tasks = [
                asyncio.wait_for(
                    asyncio.to_thread(self._query_zone, reversed_ip, zone),
                    timeout=4,
                )
                for zone in self.zones
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []

            hits: List[str] = []
            reasons: Dict[str, Optional[str]] = {}
            for res in results:
                if isinstance(res, Exception) or not res:
                    continue
                try:
                    zone, reason = res
                except (TypeError, ValueError):
                    continue
                if zone:
                    hits.append(zone)
                    reasons[zone] = reason
            return {"hits": hits, "reasons": reasons}
        except Exception:
            return {"hits": [], "reasons": {}}

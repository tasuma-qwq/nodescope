import asyncio
import ipaddress
import aiohttp
from typing import Optional, Dict, List

# Strategies
from .sources.ping0 import Ping0Source
from .sources.ippure import IPPureSource
from .sources.browser import BrowserSource
from .sources.ipapi import IPApiSource
from .sources.abuseipdb import AbuseIPDBSource
from .sources.ip2location import IP2LocationSource
from .sources.ipqs import IPQSSource
from .sources.dnsbl import DNSBLSource, DEFAULT_ZONES
from .sources.dnsleak import DNSLeakSource
from .sources.ipv6 import check as check_ipv6
from .unlock import format_unlock_summary, run_unlock_checks
from utils.config_loader import load_config

# Keep waiting this long for the primary source after the secondary already succeeded.
PRIORITY_GRACE = 1.0


def _map_ip_type(raw: Optional[str]) -> Optional[str]:
    """Map provider usage/connection type strings to Chinese labels.

    Returns None when raw is empty (caller should try next source);
    returns a label (including "未知") when raw is present.
    """
    if not raw:
        return None
    s = str(raw).lower()
    if any(k in s for k in ("residential", "fixed line", "fixedline")) or s in ("isp", "rsv"):
        return "住宅"
    if any(k in s for k in ("mobile", "cellular")) or s == "mob":
        return "移动"
    if any(k in s for k in ("datacenter", "data center", "hosting", "transit")) or s in ("dch", "cdn"):
        return "数据中心"
    if any(k in s for k in ("corporate", "commercial", "business")) or s in ("com", "org"):
        return "商业"
    return "未知"


def _derive_ip_type_from_ipapi(l1: Dict) -> str:
    if l1.get("is_hosting"):
        return "数据中心"
    if l1.get("is_mobile"):
        return "移动"
    return "住宅"


def _merge_bool(*values) -> Optional[bool]:
    """Merge bool flags: any True wins; else any False; else None."""
    found_false = False
    for v in values:
        if v is True:
            return True
        if v is False:
            found_false = True
    return False if found_false else None


def _count_true(*values) -> int:
    """Number of sources that say True — powers the cross-vote +20 rule."""
    return sum(1 for v in values if v is True)


def _resolve_dnsbl_zones(dnsbl_zones) -> List[str]:
    """None → config.yaml / DEFAULT_ZONES; explicit value used as-is."""
    if dnsbl_zones is not None:
        if isinstance(dnsbl_zones, str):
            parsed = [z.strip() for z in dnsbl_zones.split(",") if z.strip()]
            return parsed
        if isinstance(dnsbl_zones, (list, tuple)):
            return [str(z).strip() for z in dnsbl_zones if str(z).strip()]
        return list(DEFAULT_ZONES)
    cfg = load_config("config.yaml") or {}
    raw = cfg.get("dnsbl_zones")
    if isinstance(raw, list):
        parsed = [str(z).strip() for z in raw if str(z).strip()]
        return parsed or list(DEFAULT_ZONES)
    if isinstance(raw, str):
        parsed = [z.strip() for z in raw.split(",") if z.strip()]
        return parsed or list(DEFAULT_ZONES)
    return list(DEFAULT_ZONES)


class IPChecker:
    def __init__(self, headless=True):
        self._headless = headless
        
        # Components
        self.ping0 = Ping0Source()
        self.ippure = IPPureSource()
        self.browser_source = BrowserSource(headless=headless)
        
        self.cache = {} # Map IP -> Result Dict

    def clear_cache(self):
        """Clears the IP result cache."""
        self.cache.clear()
        print("[IPChecker] Cache cleared.")

    @property
    def headless(self):
        return self._headless

    @headless.setter
    def headless(self, value):
        self._headless = value
        self.browser_source.headless = value

    async def start(self):
        await self.browser_source.start()

    async def stop(self):
        await self.browser_source.stop()

    async def get_simple_ip(self, proxy=None):
        """Fast IPv4 check for caching. One session for both fallback URLs."""
        urls = ["http://api.ipify.org", "http://v4.ident.me"]
        timeout = aiohttp.ClientTimeout(total=3)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for url in urls:
                    try:
                        async with session.get(url, proxy=proxy) as resp:
                            if resp.status != 200:
                                continue
                            ip = (await resp.text()).strip()
                            try:
                                addr = ipaddress.IPv4Address(ip)
                            except (ipaddress.AddressValueError, ValueError):
                                continue
                            if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
                                continue
                            return str(addr)
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    # --- Multi-source enrich layer ---

    async def enrich(self, ip: str, api_keys: Optional[Dict] = None,
                     dnsbl_enabled: bool = True, dnsbl_zones=None) -> Dict:
        """L1/L2/L3 multi-source enrichment. Never raises."""
        try:
            return await asyncio.wait_for(
                self._enrich_impl(ip, api_keys, dnsbl_enabled=dnsbl_enabled, dnsbl_zones=dnsbl_zones),
                timeout=6,
            )
        except asyncio.TimeoutError:
            return {
                "geo": "", "isp": "", "asn": "", "ip_type": "未知",
                "multi_native": "未知", "multi_native_reason": "enrich 超时",
                "multi_sources": [], "multi_errors": ["enrich_timeout"],
                "ipqs_fraud_score": None, "ipqs_veto": False,
                "abuse_score": None, "is_proxy": None, "is_vpn": None,
                "is_tor": None, "is_datacenter": None,
                "dnsbl_hits": [], "dnsbl_blacklisted": False, "dnsbl_reasons": {},
            }
        except Exception:
            return {
                "multi_errors": ["enrich_failed"],
                "dnsbl_hits": [], "dnsbl_blacklisted": False, "dnsbl_reasons": {},
            }

    async def _enrich_impl(self, ip: str, api_keys: Optional[Dict] = None,
                           dnsbl_enabled: bool = True, dnsbl_zones=None) -> Dict:
        # None → load from config.yaml; {} or explicit dict → use as-is (empty = skip L2/L3)
        if api_keys is None:
            cfg = load_config("config.yaml") or {}
            keys = {
                "abuseipdb_key": cfg.get("abuseipdb_key", "") or "",
                "ip2location_key": cfg.get("ip2location_key", "") or "",
                "ipqs_key": cfg.get("ipqs_key", "") or "",
            }
        else:
            keys = {
                "abuseipdb_key": api_keys.get("abuseipdb_key", "") or "",
                "ip2location_key": api_keys.get("ip2location_key", "") or "",
                "ipqs_key": api_keys.get("ipqs_key", "") or "",
            }

        multi_sources = []
        multi_errors = []

        # L1: ip-api (best-effort). Failure must not skip L2/L3/DNSBL.
        l1 = await IPApiSource().check(ip)
        if l1:
            multi_sources.append("ipapi")
        else:
            l1 = {}
            multi_errors.append("ipapi_failed")

        abuse_key = keys.get("abuseipdb_key", "")
        ip2_key = keys.get("ip2location_key", "")
        ipqs_key = keys.get("ipqs_key", "")

        l2_abuse: Optional[Dict] = None
        l2_ip2: Optional[Dict] = None
        l3_ipqs: Optional[Dict] = None
        dnsbl_result: Optional[Dict] = None

        tasks = []
        task_names = []
        if abuse_key:
            tasks.append(AbuseIPDBSource(abuse_key).check(ip))
            task_names.append("abuseipdb")
        if ip2_key:
            tasks.append(IP2LocationSource(ip2_key).check(ip))
            task_names.append("ip2location")
        if ipqs_key:
            tasks.append(IPQSSource(ipqs_key).check(ip))
            task_names.append("ipqs")
        if dnsbl_enabled:
            zones = _resolve_dnsbl_zones(dnsbl_zones)
            tasks.append(DNSBLSource(zones).check(ip))
            task_names.append("dnsbl")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for name, res in zip(task_names, results):
                if isinstance(res, Exception) or res is None:
                    multi_errors.append(f"{name}_failed")
                else:
                    multi_sources.append(name)
                    if name == "abuseipdb":
                        l2_abuse = res
                    elif name == "ip2location":
                        l2_ip2 = res
                    elif name == "ipqs":
                        l3_ipqs = res
                    elif name == "dnsbl":
                        dnsbl_result = res

        # geo (L1 first, then L2/L3 if ip-api failed)
        city = (l1.get("city") or "") if l1 else ""
        cc = (l1.get("country_code") or "") if l1 else ""
        if not cc and l2_ip2:
            cc = l2_ip2.get("country_code") or ""
        if not city and l3_ipqs:
            city = l3_ipqs.get("city") or ""
        if not cc and l3_ipqs:
            cc = l3_ipqs.get("country_code") or ""
        if city and cc:
            geo = f"{city}, {cc}"
        elif cc:
            geo = cc
        elif city:
            geo = city
        else:
            geo = ""

        # isp / asn fallback chain
        isp = (l1.get("isp") or "") or ""
        if not isp and l2_ip2:
            isp = l2_ip2.get("isp") or ""
        if not isp and l3_ipqs:
            isp = l3_ipqs.get("isp") or ""

        asn = (l1.get("asn") or "") or ""
        if not asn and l3_ipqs:
            asn = l3_ipqs.get("asn") or ""

        # ip_type priority: IPQS connection_type → IP2Location usage_type → derive from ip-api
        ip_type = "未知"
        mapped = None
        if l3_ipqs and l3_ipqs.get("connection_type"):
            mapped = _map_ip_type(l3_ipqs.get("connection_type"))
        elif l2_ip2 and l2_ip2.get("usage_type"):
            mapped = _map_ip_type(l2_ip2.get("usage_type"))
        if mapped is not None:
            ip_type = mapped
        elif l1:
            ip_type = _derive_ip_type_from_ipapi(l1)

        # multi_native: compare ip-api vs IP2Location country codes
        a_cc = (l1.get("country_code") or "").upper() if l1 else ""
        b_cc = (l2_ip2.get("country_code") or "").upper() if l2_ip2 else ""
        if a_cc and b_cc:
            if a_cc == b_cc:
                multi_native, multi_native_reason = "原生", f"多源国家码一致 ({a_cc})"
            else:
                multi_native, multi_native_reason = (
                    "广播",
                    f"多源国家码不一致: ip-api={a_cc}, IP2Location={b_cc}",
                )
        elif a_cc or b_cc:
            only = a_cc or b_cc
            multi_native, multi_native_reason = "原生", f"仅有单源地理数据 ({only})，按原生假设"
        else:
            multi_native, multi_native_reason = "未知", "无地理数据"

        # L3 veto / scores
        ipqs_fraud_score = None
        ipqs_veto = False
        if l3_ipqs and l3_ipqs.get("fraud_score") is not None:
            ipqs_fraud_score = l3_ipqs["fraud_score"]
            ipqs_veto = ipqs_fraud_score >= 85

        abuse_score = None
        if l2_abuse and l2_abuse.get("abuse_score") is not None:
            abuse_score = l2_abuse["abuse_score"]

        is_proxy = _merge_bool(
            l1.get("is_proxy") if l1 else None,
            l2_ip2.get("is_proxy") if l2_ip2 else None,
            l3_ipqs.get("is_proxy") if l3_ipqs else None,
        )
        is_vpn = _merge_bool(
            l2_ip2.get("is_vpn") if l2_ip2 else None,
            l3_ipqs.get("is_vpn") if l3_ipqs else None,
        )
        # Single-source True stays on the node (display) but must not score;
        # risk_score only fires +20 when two independent sources agree.
        is_proxy_votes = _count_true(
            l1.get("is_proxy") if l1 else None,
            l2_ip2.get("is_proxy") if l2_ip2 else None,
            l3_ipqs.get("is_proxy") if l3_ipqs else None,
        )
        is_vpn_votes = _count_true(
            l2_ip2.get("is_vpn") if l2_ip2 else None,
            l3_ipqs.get("is_vpn") if l3_ipqs else None,
        )
        is_tor = _merge_bool(
            l2_ip2.get("is_tor") if l2_ip2 else None,
            l3_ipqs.get("is_tor") if l3_ipqs else None,
        )
        is_datacenter = _merge_bool(
            l1.get("is_hosting") if l1 else None,
            l2_ip2.get("is_datacenter") if l2_ip2 else None,
        )

        dnsbl_hits = list((dnsbl_result or {}).get("hits") or [])
        dnsbl_reasons = dict((dnsbl_result or {}).get("reasons") or {})
        dnsbl_blacklisted = bool(dnsbl_hits)

        return {
            "geo": geo,
            "isp": isp,
            "asn": asn,
            "ip_type": ip_type,
            "multi_native": multi_native,
            "multi_native_reason": multi_native_reason,
            "multi_sources": multi_sources,
            "multi_errors": multi_errors,
            "ipqs_fraud_score": ipqs_fraud_score,
            "ipqs_veto": ipqs_veto,
            "abuse_score": abuse_score,
            "is_proxy": is_proxy,
            "is_vpn": is_vpn,
            "is_proxy_votes": is_proxy_votes,
            "is_vpn_votes": is_vpn_votes,
            "is_tor": is_tor,
            "is_datacenter": is_datacenter,
            "dnsbl_hits": dnsbl_hits,
            "dnsbl_blacklisted": dnsbl_blacklisted,
            "dnsbl_reasons": dnsbl_reasons,
        }

    # --- Main Interface ---

    async def check_browser(self, url="https://ippure.com/", proxy=None, timeout=20000):
        """Full browser check"""
        
        # 1. Cleaner Fast IP & Cache Logic
        current_ip = await self.get_simple_ip(proxy)
        if current_ip and current_ip in self.cache:
            # Strict mode: Only accept cache if it has bot_score (from browser check)
            cached = self.cache[current_ip]
            if "bot_score" in cached:
                print(f"     [Cache Hit] {current_ip}")
                return cached
        
        if current_ip:
            print(f"     [New IP] {current_ip}")
        else:
            print("     [Warning] Fast IP check failed. Scanning with browser...")

        # 2. Delegate to Browser Source
        result = await self.browser_source.check(proxy)
        
        # Inject IP if browser failed to find it but simple check passed
        if result["ip"] == "❓" and current_ip:
            result["ip"] = current_ip

        # Cache Update
        if result["ip"] != "❓" and result["pure_score"] != "❓":
            self.cache[result["ip"]] = result.copy()
            
        return result

    async def check_fast(self, proxy=None, source="ping0", fallback=True, enable_multi=True, api_keys=None,
                         dnsbl_enabled=True, dnsbl_zones=None, dns_leak_enabled=True, unlock_enabled=False,
                         ipv6_enabled=False):
        """
        Fast mode: Prioritizes source (ping0/ippure), falls back if enabled.
        Optionally overlays multi-source enrich fields when enable_multi is True.
        """
        try:
            # Hard timeout of 15 seconds for core check only (not enrich)
            result = await asyncio.wait_for(
                self._check_fast_impl(proxy, source, fallback),
                timeout=15
            )
        except asyncio.TimeoutError:
            print(f"     [check_fast] Total timeout exceeded")
            return {
                "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
                "pure_score": "❓", "shared_users": "N/A", "full_string": "【⏱️ Timeout】",
                "ip": "❓", "error": "Timeout", "source": "timeout"
            }

        if enable_multi and "multi_sources" not in result:
            ip = result.get("ip")
            if ip and ip not in ("❓", ""):
                enriched = await self.enrich(
                    ip, api_keys, dnsbl_enabled=dnsbl_enabled, dnsbl_zones=dnsbl_zones
                )
                result.update(enriched)
                errors = enriched.get("multi_errors") or []
                if "enrich_timeout" not in errors and "enrich_failed" not in errors:
                    self.cache[ip] = result.copy()

        if dns_leak_enabled and "multi_sources" in result and result.get("ip") not in (None, "❓", ""):
            try:
                dns = await asyncio.wait_for(
                    DNSLeakSource().check(proxy, exit_ip=result.get("ip")), timeout=5
                )
            except asyncio.TimeoutError:
                dns = {"dns_leak": None, "dns_leak_state": "unknown", "dns_ip": "", "dns_geo": ""}
            except Exception:
                dns = {"dns_leak": None, "dns_leak_state": "unknown", "dns_ip": "", "dns_geo": ""}
            result = dict(result)
            result.update(dns)

        result = await self._attach_unlock(result, proxy, unlock_enabled)
        result = await self._attach_ipv6(result, proxy, ipv6_enabled)
        return result

    async def _attach_ipv6(self, result, proxy, ipv6_enabled):
        """IPv6 egress probe. Display-only: appended on a fresh dict after the
        cache write, so the cached entry stays probe-free."""
        if not ipv6_enabled:
            return result
        out = dict(result)
        try:
            v6 = await asyncio.wait_for(check_ipv6(proxy), timeout=6)
        except Exception:
            v6 = {"ipv6": None}
        out.update(v6)
        return out

    async def _attach_unlock(self, result, proxy, unlock_enabled):
        """Overlay AI/streaming unlock probes. Display-only: appended after the
        cache write on a fresh dict, so the cached entry stays unlock-free."""
        if not unlock_enabled:
            return result
        out = dict(result)
        try:
            unlock = await asyncio.wait_for(
                run_unlock_checks(proxy if isinstance(proxy, str) else None), timeout=20
            )
        except Exception:
            unlock = {}
        out["unlock"] = unlock
        out["unlock_summary"] = format_unlock_summary(unlock)
        return out
    
    async def _check_fast_impl(self, proxy=None, source="ping0", fallback=True):
        """Internal implementation of check_fast with prioritization"""
        # 0. Check Cache First (Optimization)
        try:
            fast_ip = await self.get_simple_ip(proxy)
            if fast_ip and fast_ip in self.cache:
                # print(f"     [Cache Hit] {fast_ip}")
                return self.cache[fast_ip]
        except Exception:
            pass # Ignore fast check errors and proceed to normal check

        # Helper wrappers to update cache
        async def try_ping0():
            res = await self.ping0.check(proxy)
            if res and res.get("ip") and res["ip"] != "❓":
                self.cache[res["ip"]] = res.copy()
                return res
            return None

        async def try_ippure():
            res = await self.ippure.check(proxy)
            if res and res.get("ip") and res["ip"] != "❓":
                self.cache[res["ip"]] = res.copy()
                return res
            return None

        fail_result = {
            "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
            "pure_score": "❓", "shared_users": "N/A", "full_string": "【❌ Check Failed】",
            "ip": "❓", "error": f"All sources failed (Primary: {source})", "source": "failed"
        }

        primary_coro = try_ping0 if source == "ping0" else try_ippure
        secondary_coro = try_ippure if source == "ping0" else try_ping0

        if not fallback:
            try:
                result = await primary_coro()
            except Exception:
                result = None
            return result if result else fail_result

        primary_task = asyncio.create_task(primary_coro())
        secondary_task = asyncio.create_task(secondary_coro())

        def _value(task):
            if not task.done() or task.cancelled():
                return None
            exc = task.exception()
            if exc is not None:
                return None
            return task.result()

        async def _settle():
            for t in (primary_task, secondary_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(primary_task, secondary_task, return_exceptions=True)

        try:
            await asyncio.wait(
                {primary_task, secondary_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # 1) Primary finished and succeeded → keep it (same as the old fast path)
            if primary_task.done():
                primary_res = _value(primary_task)
                if primary_res:
                    return primary_res
                if not secondary_task.done():
                    await asyncio.wait({secondary_task})
                secondary_res = _value(secondary_task)
                if secondary_res:
                    print(f"     [Check] {source} failed, falling back...")
                    return secondary_res
                return fail_result

            # Secondary finished first
            secondary_res = _value(secondary_task)
            if secondary_res:
                # 2) Secondary succeeded first → 1.0s grace window for primary
                await asyncio.wait({primary_task}, timeout=PRIORITY_GRACE)
                if primary_task.done():
                    primary_res = _value(primary_task)
                    if primary_res:
                        return primary_res
                    print(f"     [Check] {source} failed, falling back...")
                    return secondary_res
                return secondary_res

            # 3) First finisher was a failure → wait for the other
            await asyncio.wait({primary_task})
            primary_res = _value(primary_task)
            if primary_res:
                return primary_res
            return fail_result
        finally:
            await _settle()

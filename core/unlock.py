"""AI / streaming unlock probes, ported from lmc999/RegionRestrictionCheck.

Each service is probed through the node's proxy with browser-like headers.
Results describe service availability, NOT IP pollution, so they stay out of
risk_score, the numeric labels and the result cache (same treatment as
dns_leak). Pure display data behind a config switch.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import aiohttp

UA_BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": UA_BROWSER,
    "Accept": "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
_OPENAI_API_HEADERS = {
    "User-Agent": UA_BROWSER,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Authorization": "Bearer null",
    "Content-Type": "application/json",
    "Origin": "https://platform.openai.com",
    "Referer": "https://platform.openai.com/",
}
# Public placeholder cookies from RRC (no account): keep Netflix off the
# signup-wall redirect so the title pages answer with real status codes.
_NETFLIX_COOKIES = {
    "flwssn": "d2c72c47-49e9-48da-b7a2-2dc6d7ca9fcf",
    "nfvdid": "BQFmAAEBEMZa4XMYVzVGf9-kQ1HXumtAKsCyuBZU4QStC6CGEGIVznjNuuTerLAG8v2-9V_kYhg5uxTB5_yyrmqc02U5l1Ts74Qquezc9AE-LZKTo3kY3g%3D%3D",
}
_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=8)
_UNLOCK_TIMEOUT = 20

_GEMINI_REGION_RE = re.compile(r',2,1,200,"([A-Z]{3})"')
_TRACE_LOC_RE = re.compile(r"^loc=([A-Za-z]{2,3})\s*$", re.MULTILINE)
_YT_REGION_RE = re.compile(r'"INNERTUBE_CONTEXT_GL"\s*:\s*"([^"]+)"')


def _page_issue(status: int, body: str) -> Optional[str]:
    if not status or status >= 500:
        return "failed"
    text = body.lower()
    if status == 429 or any(marker in text for marker in (
        "<title>just a moment", "cf-chl-", "challenge-platform",
        "verify you are human", "checking your browser",
    )):
        return "unknown"
    return None


async def _fetch(session: Any, url: str, *, headers: Dict = None, cookies: Dict = None,
                 proxy: str = None, retries: int = 1) -> tuple:
    """(status, body, final_url); (0, '', '') after retries on network failure."""
    for attempt in range(max(retries, 0) + 1):
        try:
            async with session.get(
                url, headers=headers or dict(_BROWSER_HEADERS), cookies=cookies,
                proxy=proxy or None,
            ) as resp:
                raw = await resp.read()
                return resp.status, raw.decode("utf-8", errors="ignore"), str(resp.url)
        except Exception:
            if attempt >= retries:
                return 0, "", ""
            await asyncio.sleep(0.5)
    return 0, "", ""


async def check_chatgpt(session: Any, proxy_url: str = None) -> Dict[str, Any]:
    """Endpoint signals, never account eligibility or successful model use.

    An accessible favicon cannot override an explicit regional API rejection.
    Challenges and unexpected responses remain unknown.
    """
    api_status, api_body, _ = await _fetch(
        session, "https://api.openai.com/compliance/cookie_requirements",
        headers=_OPENAI_API_HEADERS, proxy=proxy_url,
    )
    app_status, app_body, _ = await _fetch(
        session, "https://ios.chat.openai.com/", proxy=proxy_url,
    )
    api_issue = _page_issue(api_status, api_body)
    app_issue = _page_issue(app_status, app_body)
    api_blocked = not api_issue and "unsupported_country" in api_body
    app_blocked = not app_issue and "VPN" in app_body
    try:
        api_json = json.loads(api_body)
        api_ok = (200 <= api_status < 300 and not api_issue
                  and isinstance(api_json, dict) and "feature_flags" in api_json
                  and "error" not in api_json)
    except (ValueError, TypeError):
        api_ok = False
    app_ok = (200 <= app_status < 300 and not app_issue and not app_blocked
              and any(marker in app_body.lower() for marker in ("chatgpt", "openai")))
    region = None
    _, trace_body, _ = await _fetch(
        session, "https://chat.openai.com/cdn-cgi/trace", proxy=proxy_url,
    )
    if trace_body:
        match = _TRACE_LOC_RE.search(trace_body)
        if match:
            region = match.group(1)
    if api_blocked and app_blocked:
        out = {"status": "no"}
    elif app_blocked and api_ok:
        out = {"status": "web_only"}
    elif api_blocked and app_ok:
        out = {"status": "app_only"}
    elif api_ok and app_ok:
        out = {"status": "yes"}
    else:
        out = {"status": "failed" if api_issue == app_issue == "failed" else "unknown"}
    if region:
        out["region"] = region
    return out


async def check_gemini(session: Any, proxy_url: str = None) -> Dict[str, Any]:
    """gemini.google.com answers with a JS marker + region when available."""
    status, body, _ = await _fetch(session, "https://gemini.google.com", proxy=proxy_url)
    if issue := _page_issue(status, body):
        return {"status": issue}
    if not body:
        return {"status": "failed"}
    if status == 200 and "45631641,null,true" in body:
        match = _GEMINI_REGION_RE.search(body)
        return {"status": "yes", "region": match.group(1) if match else None}
    if status == 200 and any(marker in body.lower() for marker in (
        "not supported in your country", "not available in your country",
    )):
        return {"status": "no"}
    return {"status": "unknown"}


async def check_claude(session: Any, proxy_url: str = None) -> Dict[str, Any]:
    """claude.ai redirects region-blocked exits to an anthropic.com page."""
    status, body, final_url = await _fetch(session, "https://claude.ai/", proxy=proxy_url)
    if not final_url:
        return {"status": "failed"}
    parsed = urlsplit(final_url)
    if (parsed.hostname in ("anthropic.com", "www.anthropic.com")
            and parsed.path.rstrip("/") == "/app-unavailable-in-region"):
        return {"status": "no"}
    if issue := _page_issue(status, body):
        return {"status": issue}
    if status == 200 and body and final_url.rstrip("/") == "https://claude.ai":
        return {"status": "yes"}
    return {"status": "unknown"}


async def check_netflix(session: Any, proxy_url: str = None) -> Dict[str, Any]:
    """Non-original title answers 200 only where the full catalogue works."""
    s1, body1, final1 = await _fetch(
        session, "https://www.netflix.com/title/81280792",
        cookies=_NETFLIX_COOKIES, proxy=proxy_url,
    )
    if issue := _page_issue(s1, body1):
        return {"status": issue}
    if s1 == 200 and urlsplit(final1).path.rstrip("/") == "/title/81280792":
        return {"status": "yes"}
    if s1 == 200:
        return {"status": "unknown"}
    if s1 in (403, 404):
        s2, body2, final2 = await _fetch(
            session, "https://www.netflix.com/title/70143836",
            cookies=_NETFLIX_COOKIES, proxy=proxy_url,
        )
        if issue := _page_issue(s2, body2):
            return {"status": issue}
        if s2 == 200 and urlsplit(final2).path.rstrip("/") == "/title/70143836":
            return {"status": "originals"}
        if s2 in (403, 404):
            return {"status": "no"}
        return {"status": "failed"}
    return {"status": "failed"}


async def check_youtube(session: Any, proxy_url: str = None) -> Dict[str, Any]:
    """YouTube Premium region check (RRC WebTest_YouTube)."""
    status, body, _ = await _fetch(
        session, "https://www.youtube.com/premium",
        cookies={
            "YSC": "FSCWhKo2Zgw",
            "PREF": "f7=4000",
            "SOCS": "CAISOAgD",
            "VISITOR_INFO1_LIVE": "Di84mAIbgKY",
        },
        proxy=proxy_url,
    )
    if issue := _page_issue(status, body):
        return {"status": issue}
    if not body:
        return {"status": "failed"}
    if status != 200:
        return {"status": "unknown"}
    if "www.google.cn" in body:
        return {"status": "no", "region": "CN"}
    if "premium is not available in your country" in body.lower():
        return {"status": "no"}
    match = _YT_REGION_RE.search(body)
    region = match.group(1) if match else None
    if "ad-free" in body.lower():
        out: Dict[str, Any] = {"status": "yes"}
        if region:
            out["region"] = region
        return out
    return {"status": "failed"}


_PROBES = {
    "chatgpt": check_chatgpt,
    "gemini": check_gemini,
    "claude": check_claude,
    "netflix": check_netflix,
    "youtube": check_youtube,
}


async def run_unlock_checks(proxy_url: str = None) -> Dict[str, Dict]:
    """Run every probe for one node in parallel; one session, closed after."""
    out: Dict[str, Dict] = {}

    async def guarded(key: str, probe):
        try:
            out[key] = await probe
        except Exception:
            out[key] = {"status": "failed"}

    try:
        # Gemini answers with a >8KB CSP report-uri header line; aiohttp's
        # default 8190-byte header limit rejects it before the body arrives.
        async with aiohttp.ClientSession(
            timeout=_PROBE_TIMEOUT, max_line_size=2 ** 17, max_field_size=2 ** 17
        ) as session:
            await asyncio.gather(
                *(guarded(key, probe(session, proxy_url)) for key, probe in _PROBES.items())
            )
    except Exception:
        pass
    return out


_SUMMARY_ICON = {
    "yes": "✅", "originals": "🟡", "web_only": "🟡", "app_only": "🟡",
    "no": "❌", "unknown": "❔", "failed": "❔",
}
_SUMMARY_NAME = {"chatgpt": "GPT", "gemini": "GM", "claude": "C", "netflix": "NF", "youtube": "YT"}


def format_unlock_summary(unlock: Any) -> str:
    """Compact UI string, e.g. 'GPT✅ GM✅US C✅ NF❌'. Never raises."""
    if not isinstance(unlock, dict):
        return ""
    marks = []
    for key, name in _SUMMARY_NAME.items():
        entry = unlock.get(key)
        if not isinstance(entry, dict):
            continue
        icon = _SUMMARY_ICON.get(entry.get("status"), "❔")
        region = entry.get("region") if entry.get("status") == "yes" and key in ("gemini", "chatgpt", "youtube") else None
        marks.append(f"{name}{icon}{region or ''}")
    return " ".join(marks)

"""Offline tests for AI/streaming unlock probes (fake session, no network)."""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core.ip_checker as ip_mod  # noqa: E402
import core.unlock as unlock  # noqa: E402
from core.unlock import (  # noqa: E402
    check_chatgpt,
    check_claude,
    check_gemini,
    check_netflix,
    check_youtube,
    format_unlock_summary,
)


class FakeResponse:
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self._body = body.encode("utf-8")
        self.url = url

    async def read(self):
        return self._body


class FakeCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """routes: list of (url_prefix, status, body, final_url); first prefix wins."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        for prefix, status, body, final in self.routes:
            if url.startswith(prefix):
                return FakeCtx(FakeResponse(status, body, final or url))
        return FakeCtx(FakeResponse(0, "", ""))


GEMINI_OK = 'snippet 45631641,null,true more ,2,1,200,"USA" data'
CHATGPT_CLEAN_API = '{"feature_flags": {}}'
CHATGPT_CLEAN_APP = "<html> welcome to chatgpt</html>"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


def test_chatgpt_yes_no_partial_failed():
    session = FakeSession([
        ("https://api.openai.com", 200, CHATGPT_CLEAN_API, None),
        ("https://ios.chat.openai.com", 200, CHATGPT_CLEAN_APP, None),
    ])
    assert run(check_chatgpt(session, "http://127.0.0.1:1")) == {"status": "yes"}

    session = FakeSession([
        ("https://api.openai.com", 200, "unsupported_country_region_territories", None),
        ("https://ios.chat.openai.com", 200, "<html>VPN</html>", None),
    ])
    assert run(check_chatgpt(session, None)) == {"status": "no"}

    session = FakeSession([
        ("https://api.openai.com", 200, CHATGPT_CLEAN_API, None),
        ("https://ios.chat.openai.com", 200, "unavailable VPN", None),
    ])
    assert run(check_chatgpt(session, None)) == {"status": "web_only"}

    session = FakeSession([
        ("https://api.openai.com", 200, "unsupported_country", None),
        ("https://ios.chat.openai.com", 200, CHATGPT_CLEAN_APP, None),
    ])
    assert run(check_chatgpt(session, None)) == {"status": "app_only"}

    session = FakeSession([])  # everything network-fails
    assert run(check_chatgpt(session, None)) == {"status": "failed"}


def test_gemini_yes_with_region_no_and_failed():
    session = FakeSession([("https://gemini.google.com", 200, GEMINI_OK, None)])
    assert run(check_gemini(session, None)) == {"status": "yes", "region": "USA"}

    session = FakeSession([("https://gemini.google.com", 200, "<html>consent</html>", None)])
    assert run(check_gemini(session, None)) == {"status": "unknown"}

    session = FakeSession([])
    assert run(check_gemini(session, None)) == {"status": "failed"}


def test_claude_redirect_judgement():
    session = FakeSession([("https://claude.ai", 200, "<html>", "https://claude.ai/")])
    assert run(check_claude(session, None)) == {"status": "yes"}

    session = FakeSession([
        ("https://claude.ai", 302, "", "https://www.anthropic.com/app-unavailable-in-region"),
    ])
    assert run(check_claude(session, None)) == {"status": "no"}

    session = FakeSession([("https://claude.ai", 200, "<html>", "https://claude.ai/signup")])
    assert run(check_claude(session, None))["status"] == "unknown"


def test_netflix_full_originals_none_failed():
    session = FakeSession([
        ("https://www.netflix.com/title/81280792", 200, "<html>", None),
    ])
    assert run(check_netflix(session, None)) == {"status": "yes"}

    session = FakeSession([
        ("https://www.netflix.com/title/81280792", 403, "", None),
        ("https://www.netflix.com/title/70143836", 200, "<html>", None),
    ])
    assert run(check_netflix(session, None)) == {"status": "originals"}

    session = FakeSession([
        ("https://www.netflix.com/title/81280792", 403, "", None),
        ("https://www.netflix.com/title/70143836", 404, "", None),
    ])
    assert run(check_netflix(session, None)) == {"status": "no"}

    session = FakeSession([])
    assert run(check_netflix(session, None)) == {"status": "failed"}


def test_run_unlock_checks_never_raises():
    async def ok(session, proxy=None):
        return {"status": "yes"}

    async def boom(session, proxy=None):
        raise RuntimeError("probe exploded")

    saved = dict(unlock._PROBES)
    unlock._PROBES = {"chatgpt": ok, "gemini": boom}
    try:
        out = run(unlock.run_unlock_checks("http://127.0.0.1:1"))
        assert out["chatgpt"] == {"status": "yes"}
        assert out["gemini"] == {"status": "failed"}
    finally:
        unlock._PROBES = saved


def test_format_unlock_summary():
    summary = format_unlock_summary({
        "chatgpt": {"status": "yes"},
        "gemini": {"status": "yes", "region": "US"},
        "claude": {"status": "no"},
        "netflix": {"status": "originals"},
    })
    assert summary == "GPT✅ GM✅US C❌ NF🟡"
    assert format_unlock_summary(None) == ""
    assert format_unlock_summary({"chatgpt": "garbage"}) == ""


def test_check_fast_attach_unlock_display_only():
    checker = ip_mod.IPChecker(headless=True)

    async def fake_checks(proxy=None):
        return {"chatgpt": {"status": "yes"}, "gemini": {"status": "failed"}}

    saved = ip_mod.run_unlock_checks
    ip_mod.run_unlock_checks = fake_checks
    try:
        base = {"ip": "1.2.3.4", "pure_score": "8%"}
        merged = run(checker._attach_unlock(base, "http://127.0.0.1:1", True))
        assert merged["unlock"]["chatgpt"] == {"status": "yes"}
        assert "GPT✅" in merged["unlock_summary"]
        assert "unlock" not in base, "original (cached) dict must stay untouched"

        untouched = run(checker._attach_unlock(base, "http://127.0.0.1:1", False))
        assert untouched is base and "unlock" not in untouched
    finally:
        ip_mod.run_unlock_checks = saved


def test_chatgpt_favicon_confirmation_and_trace_region():
    # A favicon success cannot override the API's explicit regional rejection.
    session = FakeSession([
        ("https://api.openai.com", 200, "unsupported_country", None),
        ("https://ios.chat.openai.com", 200, CHATGPT_CLEAN_APP, None),
        ("https://chatgpt.com/favicon.ico", 200, "icon", None),
        ("https://chat.openai.com/cdn-cgi/trace", 200, "fl=1\nloc=SG\ntz=Asia/Singapore\n", None),
    ])
    out = run(check_chatgpt(session, None))
    assert out == {"status": "app_only", "region": "SG"}, out
    assert not any("favicon" in url for url in session.requested)

    # favicon 403 confirms the block.
    session = FakeSession([
        ("https://api.openai.com", 200, "unsupported_country", None),
        ("https://ios.chat.openai.com", 200, CHATGPT_CLEAN_APP, None),
        ("https://chatgpt.com/favicon.ico", 403, "", None),
    ])
    assert run(check_chatgpt(session, None)) == {"status": "app_only"}

    # Summary shows the chatgpt region too.
    assert "GPT🟡" in format_unlock_summary({"chatgpt": out})


def test_youtube_premium_region_variants():
    body = '"INNERTUBE_CONTEXT_GL":"TW" ... ad-free ...'
    session = FakeSession([("https://www.youtube.com/premium", 200, body, None)])
    assert run(check_youtube(session, None)) == {"status": "yes", "region": "TW"}

    session = FakeSession([("https://www.youtube.com/premium", 200, "Premium is not available in your country", None)])
    assert run(check_youtube(session, None)) == {"status": "no"}

    session = FakeSession([("https://www.youtube.com/premium", 200, "redirect www.google.cn consent", None)])
    assert run(check_youtube(session, None)) == {"status": "no", "region": "CN"}

    session = FakeSession([])
    assert run(check_youtube(session, None)) == {"status": "failed"}

    # page loads but no known marker → failed (page error), never fabricated
    session = FakeSession([("https://www.youtube.com/premium", 200, "random page", None)])
    assert run(check_youtube(session, None)) == {"status": "failed"}


def test_summary_includes_youtube():
    summary = format_unlock_summary({
        "chatgpt": {"status": "yes"},
        "gemini": {"status": "yes", "region": "USA"},
        "claude": {"status": "yes"},
        "netflix": {"status": "originals"},
        "youtube": {"status": "yes", "region": "TW"},
    })
    assert summary == "GPT✅ GM✅USA C✅ NF🟡 YT✅TW"
    # youtube key absent → omitted, old behavior unchanged
    assert "YT" not in format_unlock_summary({"chatgpt": {"status": "yes"}})


def main() -> int:
    tests = [
        test_chatgpt_yes_no_partial_failed,
        test_chatgpt_favicon_confirmation_and_trace_region,
        test_gemini_yes_with_region_no_and_failed,
        test_claude_redirect_judgement,
        test_netflix_full_originals_none_failed,
        test_youtube_premium_region_variants,
        test_summary_includes_youtube,
        test_run_unlock_checks_never_raises,
        test_format_unlock_summary,
        test_check_fast_attach_unlock_display_only,
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

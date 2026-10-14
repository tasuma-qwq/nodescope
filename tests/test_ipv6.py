"""Offline tests for the IPv6 egress probe."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core.ip_checker as ip_mod  # noqa: E402
from core.sources.ipv6 import check  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def text(self):
        return self._body


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, status, body):
        self._resp = _Resp(status, body)

    def get(self, url, **kwargs):
        assert url == "https://api6.ipify.org"
        return _Ctx(self._resp)

    async def close(self):
        pass


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


def test_ipv6_success_returns_address():
    out = _run(check("http://127.0.0.1:1", session_factory=lambda t: _Session(200, " 2001:db8::1 \n")))
    assert out == {"ipv6": "2001:db8::1"}, out


def test_ipv6_unavailable_v4_or_error():
    # Connection failure (no v6 route) → factory raises → probe returns None.
    def broken_factory(timeout):
        raise OSError("no v6 route")
    assert _run(check(None, session_factory=broken_factory)) == {"ipv6": None}

    # Endpoint answers but with an IPv4 literal → not v6 egress.
    assert _run(check(None, session_factory=lambda t: _Session(200, "1.2.3.4"))) == {"ipv6": None}

    # Non-200 → None.
    assert _run(check(None, session_factory=lambda t: _Session(503, "x"))) == {"ipv6": None}


def test_check_fast_ipv6_display_only_not_cached():
    checker = ip_mod.IPChecker(headless=True)

    async def fake_check(proxy=None, timeout=5):
        return {"ipv6": "2001:db8::1"}

    saved = ip_mod.check_ipv6
    ip_mod.check_ipv6 = fake_check
    try:
        base = {"ip": "1.2.3.4", "pure_score": "8%"}
        merged = _run(checker._attach_ipv6(base, "http://127.0.0.1:1", True))
        assert merged["ipv6"] == "2001:db8::1", merged
        assert "ipv6" not in base, "cached/original dict must stay untouched"

        # Disabled → untouched, same object.
        off = _run(checker._attach_ipv6(base, "http://127.0.0.1:1", False))
        assert off is base and "ipv6" not in off

        # Probe failure → ipv6 None but present.
        async def boom(proxy=None, timeout=5):
            raise RuntimeError("x")
        ip_mod.check_ipv6 = boom
        failed = _run(checker._attach_ipv6({"ip": "1.2.3.4"}, None, True))
        assert failed["ipv6"] is None
    finally:
        ip_mod.check_ipv6 = saved


def main() -> int:
    tests = [
        test_ipv6_success_returns_address,
        test_ipv6_unavailable_v4_or_error,
        test_check_fast_ipv6_display_only_not_cached,
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

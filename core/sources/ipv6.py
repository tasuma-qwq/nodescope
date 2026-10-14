"""IPv6 egress probe: does this node have a working IPv6 exit at all?

api6.ipify.org is IPv6-only — a successful answer proves v6 egress (and gives
the address); any failure means no usable v6 (or the probe was blocked).
Display-only, like dns_leak: never scored, never cached.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp

_PROBE_URL = "https://api6.ipify.org"


def _default_session_factory(timeout: float):
    return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))


async def check(proxy: Any = None, timeout: float = 5, session_factory=None) -> Dict[str, Optional[str]]:
    """Returns {"ipv6": "<address>"} when v6 egress works, else {"ipv6": None}."""
    factory = session_factory or _default_session_factory
    session = None
    try:
        session = factory(timeout)
        async with session.get(_PROBE_URL, proxy=proxy or None) as resp:
            if resp.status == 200:
                text = (await resp.text()).strip()
                if text and ":" in text:
                    return {"ipv6": text}
    except Exception:
        pass
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass
    return {"ipv6": None}

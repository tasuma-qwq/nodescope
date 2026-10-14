"""Aggregate detection signals into a 0-100 risk score.

Pure function: missing/unparseable signals are skipped. Never raises.
pure_score is pollution (higher = dirtier), mapped as int(pure * 0.5).
Broadcast is scored from multi_native / ip_src / native, not ip_type.
dns_leak_state is ignored.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

_BROADCAST_FIELDS = ("multi_native", "ip_src", "native")

_MISSING = {
    "",
    "?",
    "❓",
    "n/a",
    "na",
    "unknown",
    "未知",
    "—",
    "-",
    "error",
    "none",
    "null",
}

def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return True
        if text in ("❓", "—"):
            return True
        return text.lower() in _MISSING
    return False


def _parse_score(value: Any) -> Optional[float]:
    """Parse a 0-100 score; skip placeholders and non-numeric values."""
    if _is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        text = str(value).strip().replace("%", "")
        if _is_missing(text):
            return None
        try:
            num = float(text)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(num):
        return None
    if num < 0:
        num = 0.0
    elif num > 100:
        num = 100.0
    return num


def _as_true(value: Any) -> bool:
    """True-only flag. Missing / False / unknown → not a hit."""
    if value is True:
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"):
        return True
    return False


def _level(score: Optional[int]) -> str:
    if score is None:
        return "未知"
    if score <= 30:
        return "低风险"
    if score <= 60:
        return "中风险"
    return "高风险"


def _broadcast_field(node: Dict) -> Optional[str]:
    """First of multi_native / ip_src / native whose text contains 广播."""
    for key in _BROADCAST_FIELDS:
        val = node.get(key)
        if _is_missing(val):
            continue
        if "广播" in str(val):
            return key
    return None


def compute_risk_score(node: Dict) -> Dict:
    """Aggregate detection signals into a 0-100 risk score.

    Returns {"risk_score": int|None, "risk_level": str, "breakdown": {signal: points}}.
    Never raises.
    """
    try:
        return _compute(node)
    except Exception:
        return {"risk_score": None, "risk_level": "未知", "breakdown": {}}


def _compute(node: Any) -> Dict:
    if not isinstance(node, dict):
        return {"risk_score": None, "risk_level": "未知", "breakdown": {}}

    breakdown: Dict[str, int] = {}
    used = 0
    total = 0

    pure = _parse_score(node.get("pure_score"))
    if pure is not None:
        pts = int(pure * 0.5)
        breakdown["pure_score"] = pts
        total += pts
        used += 1

    abuse = _parse_score(node.get("abuse_score"))
    if abuse is not None:
        pts = int(abuse * 0.3)
        breakdown["abuse_score"] = pts
        total += pts
        used += 1

    ipqs = _parse_score(node.get("ipqs_fraud_score"))
    if ipqs is not None:
        pts = int(ipqs * 0.2)
        breakdown["ipqs_fraud_score"] = pts
        total += pts
        used += 1

    if _as_true(node.get("is_tor")):
        breakdown["is_tor"] = 30
        total += 30
        used += 1

    # proxy/vpn +20 needs TWO independent sources agreeing True. The merged
    # is_proxy/is_vpn flags (any-True) stay display-only; vote counts decide.
    def _votes(key: str):
        val = node.get(key)
        if isinstance(val, bool) or not isinstance(val, int):
            return 0
        return val

    if _votes("is_proxy_votes") >= 2:
        breakdown["is_proxy"] = 20
        total += 20
        used += 1
    elif _votes("is_vpn_votes") >= 2:
        breakdown["is_vpn"] = 20
        total += 20
        used += 1

    if _as_true(node.get("is_datacenter")):
        breakdown["is_datacenter"] = 15
        total += 15
        used += 1

    bcast_key = _broadcast_field(node)
    if bcast_key is not None:
        breakdown[bcast_key] = 10
        total += 10
        used += 1

    dnsbl = _as_true(node.get("dnsbl_blacklisted"))
    if dnsbl:
        used += 1

    if used == 0:
        return {"risk_score": None, "risk_level": "未知", "breakdown": {}}

    if dnsbl:
        total = max(total, 90)
        breakdown["dnsbl_blacklisted"] = 90

    total = min(int(total), 100)
    return {
        "risk_score": total,
        "risk_level": _level(total),
        "breakdown": breakdown,
    }

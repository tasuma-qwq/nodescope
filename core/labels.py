"""Text-only node-name labels. No emoji / color dots."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.risk_score import compute_risk_score

FAIL_LABEL = "【检测失败】"
_LABEL_RE = re.compile(r"(?:\s*【[^】]*】)+\s*$")
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


def strip_existing_label(name: str) -> str:
    """Remove trailing 【...】 blocks so re-checks do not stack suffixes."""
    if not isinstance(name, str):
        return ""
    return _LABEL_RE.sub("", name).strip()


def _clean(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in ("❓", "—"):
        return None
    if text.lower() in _MISSING:
        return None
    return text


def format_data_label(result: Dict) -> str:
    """Build 【8% 住宅|原生 共享10-50 综合12】 from a check result. Never raises."""
    try:
        if not isinstance(result, dict):
            return FAIL_LABEL

        parts = []

        score = _clean(result.get("pure_score"))
        if score and not score.endswith("%"):
            try:
                float(score)
                score = f"{score}%"
            except (TypeError, ValueError):
                pass
        if score:
            parts.append(score)

        ip_attr = _clean(result.get("ip_attr"))
        ip_type = _clean(result.get("ip_type"))
        kind = ip_attr or ip_type

        native = _clean(result.get("ip_src")) or _clean(result.get("multi_native"))
        if kind and native:
            parts.append(f"{kind}|{native}")
        elif kind:
            parts.append(kind)
        elif native:
            parts.append(native)

        shared = _clean(result.get("shared_users"))
        if shared:
            parts.append(f"共享{shared}")

        risk = compute_risk_score(result)
        if risk.get("risk_score") is not None:
            parts.append(f"综合{risk['risk_score']}")

        if result.get("dnsbl_blacklisted") is True:
            parts.append("黑名单")

        if not parts:
            return FAIL_LABEL
        return "【" + " ".join(parts) + "】"
    except Exception:
        return FAIL_LABEL

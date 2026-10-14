"""Shareable reports built from a strict whitelist, never subscription data."""
from datetime import datetime, timezone
import math
from typing import Any


def _number(value: Any, maximum: float = 100):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0 <= number <= maximum:
        return None
    return int(number) if number.is_integer() else number


def build_report(nodes):
    """All names are aliases. No IPs, free-text errors, URLs or credentials."""
    entries = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        status = node.get("status")
        if status == "pending":
            outcome = "pending"
        elif status in ("✅", "⚠️ 降级"):
            outcome = "measured"
        else:
            outcome = "failed"
        services = {}
        raw_services = node.get("unlock")
        if isinstance(raw_services, dict):
            for key in ("chatgpt", "gemini", "claude", "netflix", "youtube"):
                result = raw_services.get(key)
                if not isinstance(result, dict):
                    continue
                signal = result.get("status")
                if signal in ("yes", "no", "unknown", "failed", "web_only", "app_only", "originals"):
                    services[key] = signal
        entry = {
            "node": f"Node {len(entries) + 1:03}",
            "outcome": outcome,
            "pollution_percent": _number(node.get("pure_score")),
            "risk_score": _number(node.get("risk_score")),
            "delay_ms": _number(node.get("delay_ms"), maximum=3_600_000),
            "dnsbl_listed": node.get("dnsbl_blacklisted") if isinstance(node.get("dnsbl_blacklisted"), bool) else None,
            "service_signals": services,
        }
        entries.append(entry)
    return {
        "schema_version": 1,
        "application": "NodeScope",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "privacy": "Node names are aliases; IPs, credentials and raw messages are excluded.",
        "interpretation": "Lower pollution/risk is better. Null means unmeasured. Service signals do not prove account eligibility.",
        "summary": {
            "total": len(entries),
            **{status: sum(entry["outcome"] == status for entry in entries)
               for status in ("pending", "measured", "failed")},
        },
        "nodes": entries,
    }

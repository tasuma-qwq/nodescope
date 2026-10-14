"""Best-effort subscription metadata for exported configs.

Parses the traffic/expiry status nodes airports embed in `proxies` (Chinese
and subconverter English formats) so a re-served checked YAML can carry the
same `subscription-userinfo` header the original subscription had — that
header is what Clash Verge turns into the traffic bar on the profile card.
Pure helpers; never raise.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

_UNIT_BYTES = {"KB": 2**10, "MB": 2**20, "GB": 2**30, "TB": 2**40, "PB": 2**50}

# subconverter style: "Traffic: 2.38GB | 200GB" = (used | total) — verified
# against Verge's own extra numbers (download+upload ≈ first figure).
_TRAFFIC_PAIR_RE = re.compile(
    r"Traffic\s*[:：]\s*([\d.]+)\s*(KB|MB|GB|TB|PB)\s*[|｜/]\s*([\d.]+)\s*(KB|MB|GB|TB|PB)",
    re.IGNORECASE,
)
# Chinese style: "剩余流量：150.75 GB" / "可用流量: 8.2GB"
_REMAINING_RE = re.compile(
    r"(?:剩余|可用)流量?\s*[:：]?\s*([\d.]+)\s*(KB|MB|GB|TB|PB)"
)
_USED_RE = re.compile(
    r"(?:已用|使用)流量?\s*[:：]?\s*([\d.]+)\s*(KB|MB|GB|TB|PB)"
)
_EXPIRE_RE = re.compile(
    r"(?:套餐?到期(?:时间|日期)?|到期(?:时间|日期)?|Expire)\s*[:：]?\s*"
    r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})",
    re.IGNORECASE,
)
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


def _to_bytes(value: str, unit: str) -> Optional[int]:
    try:
        amount = float(value)
        factor = _UNIT_BYTES[str(unit).upper()]
        return int(amount * factor)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def parse_traffic_nodes(proxies: Any) -> Optional[Dict[str, int]]:
    """Scan status-node names for used/remaining traffic and expiry date.

    Returns {'used'/'remaining': bytes, 'total': bytes, 'expire': unix
    seconds} with only the fields actually found; None when nothing
    parseable. "Traffic: a | b" reads as used|total, 剩余流量 as remaining.
    """
    out: Dict[str, int] = {}
    for proxy in proxies or []:
        if not isinstance(proxy, dict):
            continue
        name = str(proxy.get("name") or "")
        if not name:
            continue
        if "used" not in out or "total" not in out:
            pair = _TRAFFIC_PAIR_RE.search(name)
            if pair:
                used = _to_bytes(pair.group(1), pair.group(2))
                total = _to_bytes(pair.group(3), pair.group(4))
                if used is not None:
                    out.setdefault("used", used)
                if total is not None:
                    out.setdefault("total", total)
        if "remaining" not in out:
            hit = _REMAINING_RE.search(name)
            if hit:
                remaining = _to_bytes(hit.group(1), hit.group(2))
                if remaining is not None:
                    out["remaining"] = remaining
        if "used" not in out:
            hit = _USED_RE.search(name)
            if hit:
                used = _to_bytes(hit.group(1), hit.group(2))
                if used is not None:
                    out["used"] = used
        if "expire" not in out:
            hit = _EXPIRE_RE.search(name)
            if hit:
                try:
                    dt = datetime(
                        int(hit.group(1)),
                        int(hit.group(2)),
                        int(hit.group(3)),
                        tzinfo=timezone.utc,
                    )
                    out["expire"] = int(dt.timestamp())
                except ValueError:
                    pass
        if "total" in out and ("remaining" in out or "used" in out) and "expire" in out:
            break
    return out or None


def userinfo_from_extra(extra: Any) -> Optional[Dict[str, int]]:
    """Normalize a Clash Verge profile item's extra (upload/download/total/expire)."""
    if not isinstance(extra, dict):
        return None
    out: Dict[str, int] = {}
    for key in ("upload", "download", "total", "expire"):
        value = extra.get(key)
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[key] = value
    return out or None


def userinfo_from_traffic(traffic: Optional[Dict[str, int]]) -> Optional[Dict[str, int]]:
    """Derive userinfo numbers from parsed status nodes.

    used+total → download = used; remaining+total → download = total-
    remaining; remaining only → treat the remaining amount as the visible
    quota (download 0); expiry only → header carries just expire. Never
    invents usage numbers.
    """
    if not traffic:
        return None
    used = traffic.get("used")
    remaining = traffic.get("remaining")
    total = traffic.get("total")
    expire = traffic.get("expire")
    out: Dict[str, int] = {"upload": 0}
    if total and used is not None:
        out["download"] = max(min(used, total), 0)
        out["total"] = total
    elif total and remaining is not None:
        out["download"] = max(total - remaining, 0)
        out["total"] = total
    elif remaining:
        out["download"] = 0
        out["total"] = remaining
    elif used:
        out["download"] = used
    elif not expire:
        return None
    if expire:
        out["expire"] = expire
    return out


def build_userinfo_header(values: Optional[Dict[str, int]]) -> Optional[str]:
    """'upload=0; download=...; total=...; expire=...' — Verge's traffic bar."""
    if not values:
        return None
    parts = []
    for key in ("upload", "download", "total", "expire"):
        value = values.get(key)
        if value is None:
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        parts.append(f"{key}={value}")
    return "; ".join(parts) if parts else None


def friendly_export_base(source_name: Any, when: datetime) -> str:
    """'gw树洞.yaml' → 'gw树洞_已检测_0919-1430'; always filename-safe."""
    stem = str(source_name or "").strip()
    stem = re.sub(r"\.ya?ml$", "", stem, flags=re.IGNORECASE)
    stem = _ILLEGAL_FILENAME_RE.sub("-", stem).strip().strip(".-")
    if not stem:
        stem = "已检测"
    return f"{stem}_已检测_{when.strftime('%m%d-%H%M')}"


def friendly_stable_base(source_name: Any) -> str:
    """'gw树洞.yaml' → 'gw树洞_已检测' — stable card name across runs."""
    stem = str(source_name or "").strip()
    stem = re.sub(r"\.ya?ml$", "", stem, flags=re.IGNORECASE)
    stem = _ILLEGAL_FILENAME_RE.sub("-", stem).strip().strip(".-")
    if not stem:
        stem = "已检测"
    if stem.endswith("_已检测"):
        return stem
    return f"{stem}_已检测"


def content_disposition_header(filename: str) -> str:
    """RFC 5987 pair: ASCII fallback plus UTF-8 filename* for CJK names."""
    raw = str(filename or "checked.yaml")
    ascii_fallback = _ILLEGAL_FILENAME_RE.sub(
        "-", raw.encode("ascii", "ignore").decode("ascii")
    ).strip()
    ascii_fallback = re.sub(r"_+", "_", ascii_fallback) or "checked.yaml"
    if "." not in ascii_fallback:
        ascii_fallback += ".yaml"
    encoded = quote(raw, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"

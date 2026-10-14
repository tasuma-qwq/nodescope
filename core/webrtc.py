"""WebRTC ICE candidate parsing and leak judgment (no network)."""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, List, Optional


def parse_candidate_line(line: str) -> Optional[Dict]:
    try:
        if line is None:
            return None
        parts = str(line).strip().split()
        if not parts or not parts[0].startswith("candidate:"):
            return None
        try:
            typ_index = parts.index("typ")
            cand_type = parts[typ_index + 1] if typ_index + 1 < len(parts) else "unknown"
        except (ValueError, IndexError):
            cand_type = "unknown"
        return {
            "raw": line,
            "foundation": parts[0].replace("candidate:", "", 1),
            "component": parts[1] if len(parts) > 1 else "",
            "protocol": parts[2] if len(parts) > 2 else "",
            "priority": parts[3] if len(parts) > 3 else "",
            "ip": parts[4] if len(parts) > 4 else "",
            "port": parts[5] if len(parts) > 5 else "",
            "type": cand_type,
        }
    except Exception:
        return None


def candidates_from_sdp(sdp: str) -> List[Dict]:
    out: List[Dict] = []
    try:
        if not sdp:
            return out
        for line in re.split(r"\r?\n", str(sdp)):
            if line.startswith("a=candidate:"):
                parsed = parse_candidate_line(line[2:])
                if parsed:
                    out.append(parsed)
        return out
    except Exception:
        return out


def is_private_or_local(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(str(ip).strip())
        return bool(addr.is_private or addr.is_loopback or addr.is_link_local)
    except Exception:
        return False


def unique_candidates(candidates) -> List[Dict]:
    out: List[Dict] = []
    seen = set()
    try:
        if not isinstance(candidates, (list, tuple)):
            return out
        for c in candidates:
            if not isinstance(c, dict) or not c.get("ip"):
                continue
            key = (c.get("ip"), c.get("port"), c.get("protocol"), c.get("type"))
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out
    except Exception:
        return out


def _empty_report(http_ip: str, candidate_count: int = 0) -> Dict:
    return {
        "state": "protected_or_blocked",
        "leak_detected": False,
        "http_ip": http_ip,
        "candidate_count": candidate_count,
        "ips": [],
        "public_ips": [],
        "private_or_local": [],
        "mdns": [],
        "leaked_public_ips": [],
        "score_impact": 0,
        "findings": [
            {"id": "webrtc_no_candidates", "severity": "info", "points": 0},
        ],
    }


def parse_webrtc_report(http_ip: str, candidates: List[Dict]) -> Dict:
    try:
        http_ip_s = "" if http_ip is None else str(http_ip)
        if not isinstance(candidates, list):
            return _empty_report(http_ip_s, 0)

        valid: List[Dict] = []
        for c in candidates:
            if isinstance(c, dict):
                valid.append(c)

        ips: List[str] = []
        for c in valid:
            try:
                ip = str(c.get("ip") or "").strip()
            except Exception:
                continue
            if ip and ip not in ips:
                ips.append(ip)

        private_or_local = [ip for ip in ips if is_private_or_local(ip)]
        mdns = [ip for ip in ips if ip.endswith(".local")]
        public_ips = [
            ip for ip in ips
            if (not is_private_or_local(ip)) and (not ip.endswith(".local"))
        ]
        leaked_public_ips = [ip for ip in public_ips if ip != http_ip_s]

        findings: List[Dict[str, Any]] = []
        score_impact = 0
        state = "protected_or_blocked"

        if leaked_public_ips:
            state = "public_ip_leak_detected"
            score_impact += 45
            findings.append({
                "id": "webrtc_public_ip_mismatch",
                "severity": "critical",
                "points": 45,
            })
        elif http_ip_s in public_ips:
            state = "webrtc_public_ip_matches_http_ip"
            findings.append({
                "id": "webrtc_public_ip_matches_http_ip",
                "severity": "info",
                "points": 0,
            })

        if private_or_local:
            score_impact += 10
            findings.append({
                "id": "webrtc_local_ip_exposed",
                "severity": "medium",
                "points": 10,
            })

        if mdns:
            findings.append({
                "id": "webrtc_mdns_masking",
                "severity": "info",
                "points": 0,
            })

        if not valid:
            findings.append({
                "id": "webrtc_no_candidates",
                "severity": "info",
                "points": 0,
            })

        leak_detected = bool(leaked_public_ips) or bool(private_or_local)

        return {
            "state": state,
            "leak_detected": leak_detected,
            "http_ip": http_ip_s,
            "candidate_count": len(valid),
            "ips": ips,
            "public_ips": public_ips,
            "private_or_local": private_or_local,
            "mdns": mdns,
            "leaked_public_ips": leaked_public_ips,
            "score_impact": score_impact,
            "findings": findings,
        }
    except Exception:
        try:
            http_ip_s = "" if http_ip is None else str(http_ip)
        except Exception:
            http_ip_s = ""
        return _empty_report(http_ip_s, 0)

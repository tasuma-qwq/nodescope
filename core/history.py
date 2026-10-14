"""Batch-check history snapshots: timestamped JSON files, optionally git-committed."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

SNAPSHOT_DIR = "history"
SNAPSHOT_FIELDS = [
    "name", "original_name", "ip", "pure_score", "pure_emoji", "risk", "shared", "bot",
    "geo", "isp", "asn", "ip_type", "multi_native", "multi_native_reason",
    "dnsbl_blacklisted", "dnsbl_hits", "dns_leak_state", "dns_ip",
    "source", "status", "error", "full_string",
    "risk_score", "risk_level",
]
_NAME_RE = re.compile(r"^[\w.\-]+\.json$")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GIT_TIMEOUT_SEC = 20


def _ts_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.gmtime())


def _snapshot_abs_dir() -> Path:
    return _PROJECT_ROOT / SNAPSHOT_DIR


def _rel_path(name: str) -> str:
    return f"{SNAPSHOT_DIR}/{name}"


def _extract_nodes(nodes: Any) -> List[Dict]:
    extracted: List[Dict] = []
    if not isinstance(nodes, list):
        return extracted
    for node in nodes:
        if not isinstance(node, dict):
            continue
        item = {}
        for field in SNAPSHOT_FIELDS:
            if field in node:
                item[field] = node.get(field)
        extracted.append(item)
    return extracted


def _created_at_from_path(path: str) -> str:
    fname = os.path.basename(path or "")
    match = re.match(r"^(\d{8}_\d{6})", fname)
    if match:
        return match.group(1)
    return fname.rsplit(".", 1)[0] if fname else ""


def save_snapshot(nodes: List[Dict], batch_id: str = "", summary: Optional[Dict] = None) -> str:
    tmp_path = None
    try:
        snap_dir = _snapshot_abs_dir()
        os.makedirs(str(snap_dir), exist_ok=True)
        extracted = _extract_nodes(nodes)
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fname = f"{_ts_stamp()}_{uuid.uuid4().hex[:6]}.json"
        payload = {
            "meta": {
                "created_at": created_at,
                "batch_id": "" if batch_id is None else str(batch_id),
                "node_count": len(extracted),
                "summary": summary if isinstance(summary, dict) else {},
            },
            "nodes": extracted,
        }
        tmp_path = snap_dir / f".tmp_{fname}"
        final_path = snap_dir / fname
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(final_path))
        return _rel_path(fname)
    except Exception as e:
        print(f"[history] save_snapshot failed: {e}", file=sys.stderr)
        try:
            if tmp_path is not None and Path(tmp_path).exists():
                Path(tmp_path).unlink()
        except Exception:
            pass
        return ""


def list_snapshots() -> List[Dict]:
    try:
        snap_dir = _snapshot_abs_dir()
        if not snap_dir.is_dir():
            return []
        items: List[Dict] = []
        for entry in snap_dir.glob("*.json"):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            try:
                with open(entry, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("meta") if isinstance(data, dict) else {}
                if not isinstance(meta, dict):
                    meta = {}
                summary = meta.get("summary")
                items.append({
                    "name": entry.name,
                    "path": _rel_path(entry.name),
                    "created_at": meta.get("created_at", ""),
                    "node_count": meta.get("node_count", 0),
                    "batch_id": meta.get("batch_id", ""),
                    "summary": summary if isinstance(summary, dict) else {},
                })
            except Exception:
                continue
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return items
    except Exception as e:
        print(f"[history] list_snapshots failed: {e}", file=sys.stderr)
        return []


def load_snapshot(name: str) -> Optional[Dict]:
    try:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            return None
        snap_dir = _snapshot_abs_dir().resolve()
        target = (snap_dir / name).resolve()
        try:
            target.relative_to(snap_dir)
        except ValueError:
            return None
        if not target.is_file():
            return None
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def trend_for_node(node_name: str) -> List[Dict]:
    """Aggregate one node's fields across snapshots (oldest first). Never raises."""
    try:
        if not isinstance(node_name, str) or not node_name:
            return []
        snapshots = list_snapshots()
        if not isinstance(snapshots, list):
            return []
        snapshots = snapshots[:50]
        items: List[Dict] = []
        time_formats = ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y%m%d_%H%M%S")
        for snap in snapshots:
            try:
                if not isinstance(snap, dict):
                    continue
                name = snap.get("name")
                if not isinstance(name, str) or not name:
                    continue
                data = load_snapshot(name)
                if not isinstance(data, dict):
                    continue
                nodes = data.get("nodes")
                if not isinstance(nodes, list):
                    continue
                matched = None
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    orig = node.get("original_name")
                    if isinstance(orig, str) and orig:
                        if orig == node_name:
                            matched = node
                            break
                    elif node.get("name") == node_name:
                        matched = node
                        break
                if matched is None:
                    continue
                created_at = ""
                meta = data.get("meta")
                if isinstance(meta, dict):
                    created_at = meta.get("created_at") or ""
                if not created_at:
                    created_at = snap.get("created_at") or ""
                if not isinstance(created_at, str):
                    created_at = str(created_at) if created_at is not None else ""
                parsed = None
                for fmt in time_formats:
                    try:
                        parsed = time.strptime(created_at, fmt)
                        break
                    except Exception:
                        continue
                if parsed is None:
                    continue
                items.append({
                    "time": created_at,
                    "risk_score": matched.get("risk_score"),
                    "risk_level": matched.get("risk_level"),
                    "pure_score": matched.get("pure_score"),
                    "dnsbl_blacklisted": matched.get("dnsbl_blacklisted"),
                    "dns_leak_state": matched.get("dns_leak_state"),
                    "source": matched.get("source"),
                })
            except Exception:
                continue
        items.reverse()
        return items
    except Exception:
        return []


def git_commit_snapshot(path: str, node_count: int = 0) -> bool:
    try:
        if not path or not isinstance(path, str):
            return False
        root = str(_PROJECT_ROOT)
        add = subprocess.run(
            ["git", "add", "--", path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
        )
        if add.returncode != 0:
            print(f"[history] git add failed: {add.stderr}", file=sys.stderr)
            return False
        created_at = _created_at_from_path(path)
        message = f"history: {created_at} {int(node_count)} nodes"
        # Pathspec keeps the commit limited to this snapshot even if other
        # paths were already staged in the index.
        commit = subprocess.run(
            ["git", "commit", "-m", message, "--", path],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
        )
        if commit.returncode != 0:
            print(f"[history] git commit failed: {commit.stderr}", file=sys.stderr)
            return False
        return True
    except FileNotFoundError:
        print("[history] git not found", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[history] git_commit_snapshot failed: {e}", file=sys.stderr)
        return False


def save_with_git(
    nodes: List[Dict],
    batch_id: str = "",
    summary: Optional[Dict] = None,
    auto_commit: bool = False,
) -> Dict:
    try:
        path = save_snapshot(nodes, batch_id=batch_id, summary=summary)
        if not path:
            return {"path": "", "committed": False}
        committed = False
        if auto_commit:
            n = len(nodes) if isinstance(nodes, list) else 0
            committed = bool(git_commit_snapshot(path, node_count=n))
        return {"path": path, "committed": committed}
    except Exception as e:
        print(f"[history] save_with_git failed: {e}", file=sys.stderr)
        return {"path": "", "committed": False}

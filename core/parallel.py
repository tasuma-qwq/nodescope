"""Pure helpers for mihomo listeners-based parallel detection."""
from __future__ import annotations

import copy
import socket
from typing import Any, Dict, List, Optional


def snapshot_selections(proxies_state: Any) -> Dict[str, Any]:
    """{selector group: chosen node} — config reloads can reset these."""
    try:
        return {
            name: p.get("now")
            for name, p in (proxies_state or {}).items()
            if isinstance(p, dict) and str(p.get("type", "")).lower() == "selector" and p.get("now")
        }
    except Exception:
        return {}


async def reapply_selections(controller: Any, selections_before: Dict[str, Any]) -> None:
    """Re-apply selector picks a config reload may have reset. Never raises."""
    try:
        if not selections_before:
            return
        get_proxies = getattr(controller, "get_proxies", None)
        switch_proxy = getattr(controller, "switch_proxy", None)
        if get_proxies is None or switch_proxy is None:
            return
        after = await get_proxies() or {}
        changed = [
            (group, now)
            for group, now in selections_before.items()
            if isinstance(after.get(group), dict) and after[group].get("now") != now
        ]
        for group, now in changed:
            await switch_proxy(group, now)
        if changed:
            print(f"已恢复 {len(changed)} 个分组的节点选择: {', '.join(g for g, _ in changed)}")
    except Exception:
        pass

_NON_REAL_TYPES = {
    "selector",
    "url-test",
    "fallback",
    "load-balance",
    "direct",
    "reject",
}


def is_real_proxy(p: Dict) -> bool:
    """True when type is a concrete outbound (not a group / built-in)."""
    try:
        if not isinstance(p, dict):
            return False
        proxy_type = p.get("type")
        if proxy_type is None:
            return False
        return str(proxy_type).strip().lower() not in _NON_REAL_TYPES
    except Exception:
        return False


def build_parallel_config(
    base: Dict, node_names: List[str], ports: List[int]
) -> Optional[Dict]:
    """Deep-copy base and attach one mixed listener per node. Never raises."""
    try:
        if not isinstance(base, dict):
            return None
        if node_names is None or ports is None:
            return None
        names = list(node_names)
        port_list = list(ports)
        if len(names) != len(port_list):
            return None
        new_cfg = copy.deepcopy(base)
        listeners = []
        for idx, name in enumerate(names):
            listeners.append({
                "name": f"p2-{idx}",
                "type": "mixed",
                "port": port_list[idx],
                "listen": "127.0.0.1",
                "proxy": name,
            })
        # Existing listeners (dict or list) are this tool's injection; rebuild.
        new_cfg["listeners"] = listeners
        return new_cfg
    except Exception:
        return None


def _is_port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def find_free_ports(count: int, base_port: int = 17800) -> List[int]:
    """Return `count` unused TCP ports starting at base_port. Never raises."""
    try:
        need = int(count)
        port = int(base_port)
        if need <= 0:
            return []
        if port < 1:
            port = 1
        found: List[int] = []
        attempts = 0
        max_attempts = max(need * 20, 1000)
        while len(found) < need and port <= 65535 and attempts < max_attempts:
            attempts += 1
            if _is_port_free(port):
                found.append(port)
            port += 1
        return found
    except Exception:
        return []


def plan_batches(node_names: List[str], batch_size: int = 12) -> List[List[str]]:
    """Split node names into batches of at most batch_size. Never raises."""
    try:
        if not node_names:
            return []
        size = int(batch_size)
        if size <= 0:
            return []
        names = list(node_names)
        return [names[i:i + size] for i in range(0, len(names), size)]
    except Exception:
        return []


def looks_like_full_clash_config(cfg) -> bool:
    """True when cfg can be PUT as a full mihomo config without dropping the API."""
    try:
        if not isinstance(cfg, dict):
            return False
        proxies = cfg.get("proxies")
        if not isinstance(proxies, list) or not proxies:
            return False
        ext = str(cfg.get("external-controller") or "").strip()
        mixed = cfg.get("mixed-port")
        port = cfg.get("port")
        if not ext and mixed in (None, 0) and port in (None, 0):
            return False
        return True
    except Exception:
        return False


def config_has_nodes(cfg, node_names: List[str]) -> bool:
    """True when every node name exists in cfg['proxies']. Never raises."""
    try:
        if not isinstance(cfg, dict) or not node_names:
            return False
        names = {
            p.get("name")
            for p in (cfg.get("proxies") or [])
            if isinstance(p, dict)
        }
        return all(name in names for name in node_names)
    except Exception:
        return False


def select_parallel_base(original_yaml, runtime_yaml, node_names: List[str]) -> Optional[Dict]:
    """Pick a full running config that contains every target node.

    Prefer the Clash runtime YAML (dns/tun/controller intact) over a pasted
    subscription fragment. GET /configs is not a valid base (no proxies).
    Never raises.
    """
    try:
        names = list(node_names or [])
        if not names:
            return None
        for cand in (runtime_yaml, original_yaml):
            if looks_like_full_clash_config(cand) and config_has_nodes(cand, names):
                return cand
        return None
    except Exception:
        return None

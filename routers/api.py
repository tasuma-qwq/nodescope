from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from ruamel.yaml import YAML, YAMLError
import asyncio
import uuid
import json
import copy
import io
import os
from datetime import datetime
from typing import Dict, List, Any
from urllib.parse import quote

# Local imports
from state import state
from schemas import StartRequest, UpdateNodeRequest, ExportRequest, RecheckRequest
from core.clash_api import ClashController
from core.risk_score import compute_risk_score
from core.privacy import public_data
from core.report import build_report
from core.labels import FAIL_LABEL, format_data_label, strip_existing_label
from core.subscription import (
    build_userinfo_header,
    content_disposition_header,
    parse_traffic_nodes,
    userinfo_from_traffic,
)
from core.parallel import (
    is_real_proxy,
    build_parallel_config,
    find_free_ports,
    plan_batches,
    reapply_selections,
    select_parallel_base,
    snapshot_selections,
)

router = APIRouter(prefix="/api")
yaml = YAML()
yaml.preserve_quotes = True

EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")

# Stable "latest checked subscription" backing GET /api/export/subscribe.
LATEST_EXPORT = "checked_latest.yaml"
LATEST_META = "checked_latest.meta.json"


def _parse_zones(value):
    """list → as-is; str → comma-split; empty → None (enrich falls back to DEFAULT_ZONES)."""
    if isinstance(value, list):
        parsed = [str(z).strip() for z in value if str(z).strip()]
        return parsed or None
    if isinstance(value, str):
        parsed = [z.strip() for z in value.split(",") if z.strip()]
        return parsed or None
    return None


def _resolve_selector(proxies_state: Dict[str, Dict], requested: str, node_names: List[str]) -> str:
    """Pick a selectable group that actually contains the submitted nodes."""
    selector_groups = {
        name: proxy for name, proxy in (proxies_state or {}).items()
        if proxy.get("type", "").lower() == "selector"
    }
    if not selector_groups:
        raise RuntimeError("Clash 中未找到可切换的 Selector 代理组")

    target_names = set(node_names)

    def coverage(name: str) -> int:
        return len(target_names.intersection(selector_groups[name].get("all", [])))

    # Keep an explicitly supplied group when it is compatible with this YAML.
    if requested in selector_groups and coverage(requested):
        return requested

    # A stale group name is common after switching subscriptions. Prefer a
    # non-GLOBAL selector containing the largest subset of submitted nodes.
    candidates = [(coverage(name), name) for name in selector_groups if name != "GLOBAL"]
    matched, selector = max(candidates, default=(0, ""))
    if matched:
        print(f"[Web] Selector '{requested}' does not match this subscription; using '{selector}'.")
        return selector

    if coverage("GLOBAL"):
        print(f"[Web] Selector '{requested}' does not match this subscription; using 'GLOBAL'.")
        return "GLOBAL"

    available = ", ".join(selector_groups)
    raise RuntimeError(f"没有包含待测节点的 Selector 代理组。可用组: {available}")


def _as_float_score(value):
    """Parse a pure_score/risk value; skip placeholders like ❓."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text or text in ("❓", "?", "N/A", "—", "-", "Error"):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _make_node_data(i, name, proxy, result) -> Dict:
    """Build the success-path node_data dict (field set and order unchanged)."""
    if (not isinstance(result, dict) or result.get("ip") in (None, "", "❓")
            or result.get("source") == "failed"):
        return _make_failed_node_data(i, name, proxy, "检测源未返回有效结果")
    risk = compute_risk_score(result)
    base = strip_existing_label(name) or name
    return {
        "id": i,
        "original_name": base,
        "name": f"{base}{format_data_label(result)}",
        "ip": result.get("ip", "❓"),
        "pure_score": result.get("pure_score", "❓"),
        "risk": result.get("pure_score", "❓"),
        "bot": result.get("bot_score", "N/A"),  # For non-fast mode
        "shared": result.get("shared_users", "N/A"),  # For fast mode
        "type": result.get("ip_attr", "❓"),
        "native": result.get("ip_src", "❓"),
        "source": result.get("source", "unknown"),
        "status": "✅" if result.get("source") == "ping0" else "⚠️ 降级",
        "geo": result.get("geo", ""),
        "isp": result.get("isp", ""),
        "asn": result.get("asn", ""),
        "ip_type": result.get("ip_type", ""),
        "multi_native": result.get("multi_native", ""),
        "multi_native_reason": result.get("multi_native_reason", ""),
        "multi_sources": result.get("multi_sources", []),
        "ipqs_fraud_score": result.get("ipqs_fraud_score"),
        "ipqs_veto": result.get("ipqs_veto", False),
        "abuse_score": result.get("abuse_score"),
        "dnsbl_hits": result.get("dnsbl_hits", []),
        "dnsbl_blacklisted": result.get("dnsbl_blacklisted", False),
        "dns_leak": result.get("dns_leak"),
        "dns_leak_state": result.get("dns_leak_state", "unknown"),
        "dns_ip": result.get("dns_ip", ""),
        "unlock_summary": result.get("unlock_summary", ""),
        "unlock": result.get("unlock", {}),
        "ipv6": result.get("ipv6") or "",
        "delay_ms": None,
        "risk_score": risk["risk_score"],
        "risk_level": risk["risk_level"],
        "proxy_config": proxy
    }


def _make_failed_node_data(i, name, proxy, error=None) -> Dict:
    """Error-branch node_data matching the serial exception payload."""
    node_data = {
        "id": i,
        "original_name": strip_existing_label(name) or name,
        "name": f"{strip_existing_label(name) or name}{FAIL_LABEL}",
        "ip": "❓",
        "pure_score": "❓",
        "geo": "",
        "isp": "",
        "asn": "",
        "ip_type": "",
        "multi_native": "",
        "multi_native_reason": "",
        "multi_sources": [],
        "ipqs_fraud_score": None,
        "ipqs_veto": False,
        "abuse_score": None,
        "dnsbl_hits": [],
        "dnsbl_blacklisted": False,
        "dns_leak": None,
        "dns_leak_state": "unknown",
        "dns_ip": "",
        "unlock_summary": "",
        "ipv6": "",
        "delay_ms": None,
        "risk_score": None,
        "risk_level": "未知",
        "status": "❌ 失败",
        "proxy_config": proxy
    }
    if error is not None:
        node_data["error"] = str(error)
    return node_data


def _history_summary(nodes: List[Dict]) -> Dict[str, Any]:
    scores = []
    blacklisted = 0
    dns_leak = 0
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        score = _as_float_score(node.get("pure_score", node.get("risk")))
        if score is not None:
            scores.append(score)
        if node.get("dnsbl_blacklisted"):
            blacklisted += 1
        if node.get("dns_leak_state") == "leak":
            dns_leak += 1
    avg_pure = round(sum(scores) / len(scores), 2) if scores else None
    return {"avg_pure": avg_pure, "blacklisted": blacklisted, "dns_leak": dns_leak}


# --- Helper Function to run check in background ---
async def _run_check(proxies: List[Dict], config: Dict):
    """Background task: check all nodes using Clash API"""
    # Get config values
    api_url = config.get("clash_api_url", "http://127.0.0.1:9097")
    api_secret = config.get("clash_api_secret", "")
    selector = config.get("selector_name", "GLOBAL")
    fast_mode = config.get("fast_mode", True)
    source = config.get("source", "ping0")
    fallback = config.get("fallback", True)
    headless = config.get("headless", True)
    
    # Update checker headless setting dynamically
    state.checker.headless = headless
    
    # Check if empty
    if not proxies:
        state.is_running = False
        state.events.append({"type": "complete", "total": 0})
        return
        
    state.total = len(proxies)
    
    # Initialize Clash controller
    controller = ClashController(api_url, api_secret)
    
    original_mode = None
    original_global = None
    original_selections = {}
    try:
        # Snapshot state so a detection run is reversible.
        configs = await controller.get_configs()
        proxies_state = await controller.get_proxies()
        original_mode = configs.get("mode") if configs else None
        global_state = proxies_state.get("GLOBAL") if proxies_state else None
        original_global = global_state.get("now") if global_state else None
        original_selections = snapshot_selections(proxies_state)
        selector = _resolve_selector(
            proxies_state,
            selector,
            [proxy.get("name", "") for proxy in proxies],
        )

        # Set Global mode for testing and route GLOBAL through the requested selector.
        if not await controller.set_mode("global"):
            raise RuntimeError("无法切换 Clash 到全局模式")
        if selector != "GLOBAL" and not await controller.switch_proxy("GLOBAL", selector):
            raise RuntimeError(f"无法将 GLOBAL 切换到代理组: {selector}")
        
        # Get proxy port from Clash API
        port = await controller.get_running_port()
        proxy_url = f"http://127.0.0.1:{port}"
        print(f"[Web] Using Clash proxy: {proxy_url}")
        
    except Exception as e:
        # If setup changed routing before failing, put the user's state back.
        await reapply_selections(controller, original_selections)
        if original_mode:
            await controller.set_mode(original_mode)
        state.events.append({
            "type": "error",
            "node_name": "Clash API",
            "error": f"无法连接到 Clash API: {e}"
        })
        state.is_running = False
        state.checker.clear_cache() # Clear cache on error
        state.events.append({"type": "complete", "total": 0})
        return
    
    checked_count = 0
    
    for i, proxy in enumerate(proxies):
        if not state.is_running:
            break
        
        name = proxy.get("name", f"Node {i}")
        state.current_node = name
        
        try:
            # 1. Switch to this node via Clash API
            print(f"[Web] Switching to: {name}")
            switched = await controller.switch_proxy(selector, name)
            
            if not switched:
                node_data = {
                    "id": i,
                    "original_name": strip_existing_label(name) or name,
                    "name": f"{strip_existing_label(name) or name}{FAIL_LABEL}",
                    "ip": "❓",
                    "pure_score": "❓",
                    "geo": "",
                    "isp": "",
                    "asn": "",
                    "ip_type": "",
                    "multi_native": "",
                    "multi_native_reason": "",
                    "multi_sources": [],
                    "ipqs_fraud_score": None,
                    "ipqs_veto": False,
                    "abuse_score": None,
                    "dnsbl_hits": [],
                    "dnsbl_blacklisted": False,
                    "dns_leak": None,
                    "dns_leak_state": "unknown",
                    "dns_ip": "",
                    "risk_score": None,
                    "risk_level": "未知",
                    "status": "❌ 切换失败",
                    "proxy_config": proxy
                }
                state.nodes[i] = node_data
                state.events.append({"type": "progress", "progress": checked_count + 1, "total": state.total, "node": node_data})
                checked_count += 1
                continue
            
            # 2. Wait for switch to take effect
            await asyncio.sleep(1)

            # Latency test runs concurrently with the check (zero added wall time).
            get_delay = getattr(controller, "get_delay", None)
            delay_task = asyncio.create_task(get_delay(name)) if get_delay else None

            # 3. Check IP through Clash proxy
            if fast_mode:
                result = await state.checker.check_fast(
                    proxy_url,
                    source=source,
                    fallback=fallback,
                    enable_multi=config.get("enable_multi_source", True),
                    api_keys={k: config.get(k, "") for k in ("abuseipdb_key", "ip2location_key", "ipqs_key")},
                    dnsbl_enabled=config.get("dnsbl_enabled", True),
                    dnsbl_zones=_parse_zones(config.get("dnsbl_zones") or config.get("dnsbl_zones_str", "")),
                    dns_leak_enabled=config.get("dns_leak_enabled", True),
                    unlock_enabled=config.get("unlock_enabled", False),
                    ipv6_enabled=config.get("ipv6_enabled", False),
                )
            else:
                result = await state.checker.check_browser(proxy=proxy_url)

            node_data = _make_node_data(i, name, proxy, result)
            if delay_task is not None:
                try:
                    delay = await asyncio.wait_for(delay_task, timeout=8)
                    node_data["delay_ms"] = delay if isinstance(delay, int) else None
                except Exception:
                    pass
            state.nodes[i] = node_data
            
            # Push event
            checked_count += 1
            state.events.append({
                "type": "progress",
                "progress": checked_count,
                "total": state.total,
                "node": node_data
            })
            
        except Exception as e:
            node_data = {
                "id": i,
                "original_name": strip_existing_label(name) or name,
                "name": f"{strip_existing_label(name) or name}{FAIL_LABEL}",
                "ip": "❓",
                "pure_score": "❓",
                "geo": "",
                "isp": "",
                "asn": "",
                "ip_type": "",
                "multi_native": "",
                "multi_native_reason": "",
                "multi_sources": [],
                "ipqs_fraud_score": None,
                "ipqs_veto": False,
                "abuse_score": None,
                "dnsbl_hits": [],
                "dnsbl_blacklisted": False,
                "dns_leak": None,
                "dns_leak_state": "unknown",
                "dns_ip": "",
                "risk_score": None,
                "risk_level": "未知",
                "status": "❌ 失败",
                "error": str(e),
                "proxy_config": proxy
            }
            state.nodes[i] = node_data
            checked_count += 1
            state.events.append({
                "type": "error",
                "node_name": name,
                "error": str(e)
            })
        
        state.progress = checked_count
    
    # Restore the user's pre-check routing state.
    await reapply_selections(controller, original_selections)
    if original_mode:
        await controller.set_mode(original_mode)

    # Persist a history snapshot after the batch loop. Failures must not
    # affect the detection response (start_check already returned; this
    # only delays the SSE complete event).
    if config.get("history_enabled", True) and state.nodes:
        try:
            from core.history import save_with_git
            summary = _history_summary(state.nodes)
            save_with_git(
                state.nodes,
                batch_id=str(state.task_id or ""),
                summary=summary,
                auto_commit=config.get("history_auto_commit", False),
            )
        except Exception:
            pass

    # Complete
    state.is_running = False
    state.checker.clear_cache() # Clear cache on completion
    state.events.append({"type": "complete", "total": len(state.nodes)})


def _finalize_check(config: Dict, app_state) -> None:
    """History snapshot + complete event. Failures must not raise."""
    if config.get("history_enabled", True) and app_state.nodes:
        try:
            from core.history import save_with_git
            summary = _history_summary(app_state.nodes)
            save_with_git(
                app_state.nodes,
                batch_id=str(app_state.task_id or ""),
                summary=summary,
                auto_commit=config.get("history_auto_commit", False),
            )
        except Exception:
            pass
    app_state.is_running = False
    try:
        app_state.checker.clear_cache()
    except Exception:
        pass
    app_state.events.append({"type": "complete", "total": len(app_state.nodes)})


def _load_verge_runtime_config():
    """Load Clash Verge's generated runtime YAML (full proxies+dns+controller). Never raises."""
    try:
        appdata = os.environ.get("APPDATA") or ""
        path = os.path.join(
            appdata,
            "io.github.clash-verge-rev.clash-verge-rev",
            "clash-verge.yaml",
        )
        if not appdata or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _gather_batch(coros, should_continue) -> List[Any]:
    """Run one batch's check coroutines, cancelling them once should_continue() is False.

    Finished tasks keep their real result/exception; tasks cancelled by the
    stop flag come back as asyncio.CancelledError so the caller can skip them.
    """
    tasks = [asyncio.ensure_future(c) for c in coros]
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, timeout=0.2, return_when=asyncio.FIRST_COMPLETED
            )
            if pending and not should_continue():
                break
    finally:
        stragglers = [t for t in tasks if not t.done()]
        for t in stragglers:
            t.cancel()
        if stragglers:
            await asyncio.wait(stragglers)
    results: List[Any] = []
    for t in tasks:
        if t.cancelled():
            results.append(asyncio.CancelledError())
        elif t.exception() is not None:
            results.append(t.exception())
        else:
            results.append(t.result())
    return results


async def _run_check_parallel(proxies, config, state, controller, source, fallback, fast_mode) -> bool:
    """Try parallel mode. Returns True if fully handled (nodes filled), False to fall back to serial."""
    restored = False
    base = None
    try:
        if not config.get("parallel_check", True):
            return False
        if not fast_mode or not proxies or len(proxies) < 2:
            return False
        if state is None or getattr(state, "nodes", None) is None:
            return False

        # GET /configs is a general summary (no proxies). Putting it back
        # would wipe outbounds. Validate names via /proxies and PUT a full YAML.
        proxies_state = await controller.get_proxies()
        if not isinstance(proxies_state, dict) or not proxies_state:
            return False
        selections_before = snapshot_selections(proxies_state)
        real_names = {
            name for name, p in proxies_state.items() if is_real_proxy(p)
        }
        names = [p.get("name", "") for p in proxies]
        if any(name not in real_names for name in names):
            return False

        base = select_parallel_base(
            getattr(state, "original_yaml", None),
            _load_verge_runtime_config(),
            names,
        )
        if not base:
            print("[Web] Parallel check skipped: no full Clash config with proxies")
            return False

        ports = find_free_ports(len(names))
        if len(ports) < len(names):
            return False

        new_cfg = build_parallel_config(base, names, ports)
        if not new_cfg:
            return False

        ok = await controller.reload_config(new_cfg)
        if not ok:
            return False

        try:
            checked_count = 0
            offset = 0
            batches = plan_batches(names)
            print(f"[Web] Parallel check: {len(names)} nodes in {len(batches)} batch(es)")
            for batch_names in batches:
                if not state.is_running:
                    break
                batch_items = []
                for j, name in enumerate(batch_names):
                    i = offset + j
                    batch_items.append((i, name, ports[i], proxies[i]))
                offset += len(batch_names)

                coros = [
                    state.checker.check_fast(
                        f"http://127.0.0.1:{port}",
                        source=source,
                        fallback=fallback,
                        enable_multi=config.get("enable_multi_source", True),
                        api_keys={k: config.get(k, "") for k in ("abuseipdb_key", "ip2location_key", "ipqs_key")},
                        dnsbl_enabled=config.get("dnsbl_enabled", True),
                        dnsbl_zones=_parse_zones(config.get("dnsbl_zones") or config.get("dnsbl_zones_str", "")),
                        dns_leak_enabled=config.get("dns_leak_enabled", True),
                        unlock_enabled=config.get("unlock_enabled", False),
                        ipv6_enabled=config.get("ipv6_enabled", False),
                    )
                    for i, name, port, proxy in batch_items
                ]
                results = await _gather_batch(coros, lambda: state.is_running)
                # Batch-concurrent latency test via the Clash API (display-only).
                # Skipped when stop just cancelled the batch — restore first.
                delay_by_name = {}
                if state.is_running:
                    delay_results = await asyncio.gather(
                        *(controller.get_delay(name) for i, name, port, proxy in batch_items),
                        return_exceptions=True,
                    )
                    delay_by_name = {
                        name: (d if isinstance(d, int) else None)
                        for (i, name, port, proxy), d in zip(batch_items, delay_results)
                    }
                for (i, name, port, proxy), result in zip(batch_items, results):
                    if isinstance(result, asyncio.CancelledError):
                        # Stop request: never checked, keep the pending row
                        # instead of fabricating a failed result.
                        continue
                    if isinstance(result, Exception):
                        node_data = _make_failed_node_data(i, name, proxy, result)
                    else:
                        try:
                            node_data = _make_node_data(i, name, proxy, result)
                        except Exception as e:
                            node_data = _make_failed_node_data(i, name, proxy, e)
                    node_data["delay_ms"] = delay_by_name.get(name)
                    state.nodes[i] = node_data
                    checked_count += 1
                    state.events.append({
                        "type": "progress",
                        "progress": checked_count,
                        "total": state.total,
                        "node": node_data,
                    })
                state.progress = checked_count
        finally:
            restored = True
            restored_ok = await controller.reload_config(base)
            if not restored_ok:
                print("[Web] Failed to restore Clash config after parallel check")
            await reapply_selections(controller, selections_before)

        _finalize_check(config, state)
        return True
    except Exception as e:
        print(f"[Web] Parallel check failed, will fall back to serial: {e}")
        if not restored and base is not None:
            try:
                restored_ok = await controller.reload_config(base)
                if not restored_ok:
                    print("[Web] Failed to restore Clash config after parallel check")
            except Exception as restore_err:
                print(f"[Web] Failed to restore Clash config after parallel check: {restore_err}")
        return False


async def _run_check_with_parallel(proxies: List[Dict], config: Dict):
    """Prefer parallel detection; any failure falls back to the serial path."""
    try:
        api_url = config.get("clash_api_url", "http://127.0.0.1:9097")
        api_secret = config.get("clash_api_secret", "")
        controller = ClashController(api_url, api_secret)
        source = config.get("source", "ping0")
        fallback = config.get("fallback", True)
        fast_mode = config.get("fast_mode", True)
        if await _run_check_parallel(proxies, config, state, controller, source, fallback, fast_mode):
            return
    except Exception as e:
        print(f"[Web] Parallel mode unavailable, falling back to serial: {e}")
    await _run_check(proxies, config)


# --- Routes ---

def _busy():
    task = getattr(state, "task", None)
    return (state.is_running or getattr(state, "is_rechecking", False)
            or (task is not None and not task.done()))


def _validate_options(config):
    boolean_keys = ("fast_mode", "fallback", "headless", "enable_multi_source",
                    "dnsbl_enabled", "dns_leak_enabled", "unlock_enabled", "ipv6_enabled",
                    "parallel_check", "history_enabled", "history_auto_commit")
    string_keys = ("clash_api_url", "clash_api_secret", "selector_name", "source",
                   "skip_keywords_str", "abuseipdb_key", "ip2location_key", "ipqs_key")
    if (any(key in config and not isinstance(config[key], bool) for key in boolean_keys)
            or any(key in config and not isinstance(config[key], str) for key in string_keys)
            or config.get("source", "ping0") not in ("ping0", "ippure")):
        raise HTTPException(status_code=400, detail="检测选项格式无效")


def _load_subscription(content):
    data = yaml.load(content)
    if not isinstance(data, dict):
        raise ValueError("YAML 顶层必须是包含 proxies 的对象")
    proxies = data.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise ValueError("proxies 必须是非空节点列表")
    names = set()
    for proxy in proxies:
        if not isinstance(proxy, dict):
            raise ValueError("每个节点必须是对象")
        name = proxy.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("每个节点必须有非空名称")
        if name in names:
            raise ValueError("节点名称不能重复")
        names.add(name)
    groups = data.get("proxy-groups", [])
    if not isinstance(groups, list) or any(not isinstance(group, dict) for group in groups):
        raise ValueError("proxy-groups 必须是对象列表")
    return data

@router.post("/webrtc-report")
async def webrtc_report(request: Request):
    """Judge WebRTC ICE candidates against the HTTP/proxy exit IP."""
    from core.webrtc import parse_webrtc_report
    http_ip = ""
    candidates = []
    try:
        body = await request.json()
        if isinstance(body, dict):
            raw_ip = body.get("http_ip")
            http_ip = "" if raw_ip is None else str(raw_ip)
            raw_cands = body.get("candidates")
            if isinstance(raw_cands, list):
                candidates = raw_cands
    except Exception:
        pass
    try:
        return parse_webrtc_report(http_ip, candidates)
    except Exception:
        return parse_webrtc_report("", [])


@router.post("/validate")
async def validate_yaml(request: StartRequest):
    """Validate YAML format"""
    try:
        data = _load_subscription(request.yaml_content)
        proxies = data["proxies"]
        
        return {"valid": True, "node_count": len(proxies)}
    
    except (YAMLError, ValueError):
        return JSONResponse({"valid": False, "error": "订阅格式无效：请检查 YAML、节点列表和名称"}, status_code=400)


@router.post("/start")
async def start_check(request: StartRequest):
    """Start node checking task"""
    if _busy():
        raise HTTPException(status_code=409, detail="任务正在运行中")
    _validate_options(request.config)
    
    try:
        data = _load_subscription(request.yaml_content)
        proxies = data["proxies"]
        
        if not proxies:
            raise HTTPException(status_code=400, detail="未找到 proxies 节点")
        
        # Initialize state
        state.task_id = str(uuid.uuid4())
        state.is_running = True
        state.original_yaml = data
        state.nodes = []
        state.events = []  # Clear previous events
        state.progress = 0
        # Filter proxies based on skip keywords
        skip_keywords_str = request.config.get("skip_keywords_str", "")
        skip_keywords = [kw.strip() for kw in skip_keywords_str.split(",") if kw.strip()]
        
        active_proxies = []
        for p in proxies:
            name = p.get("name", "")
            if skip_keywords and any(kw in name for kw in skip_keywords):
                print(f"[Web] Skipping (in start): {name}")
                continue
            active_proxies.append(p)
            
            # Pre-fill node for immediate display
            state.nodes.append({
                "id": len(active_proxies) - 1,
                "original_name": name,
                "name": name,
                "ip": "...",
                "pure_score": "",
                "risk": "",
                "shared": "",
                "type": "",
                "native": "",
                "source": "",
                "geo": "",
                "isp": "",
                "asn": "",
                "ip_type": "",
                "multi_native": "",
                "multi_native_reason": "",
                "multi_sources": [],
                "ipqs_fraud_score": None,
                "ipqs_veto": False,
                "abuse_score": None,
                "dnsbl_hits": [],
                "dnsbl_blacklisted": False,
                "dns_leak": None,
                "dns_leak_state": "unknown",
                "dns_ip": "",
                "unlock_summary": "",
                "ipv6": "",
                "delay_ms": None,
                "risk_score": None,
                "risk_level": "未知",
                "status": "pending",
                "proxy_config": p
            })

        state.total = len(active_proxies)
        
        # Prefer parallel (mihomo listeners); any failure falls back to serial.
        state.task = asyncio.create_task(_run_check_with_parallel(active_proxies, request.config))
        
        return {"task_id": state.task_id, "total": state.total}
    
    except (YAMLError, ValueError):
        raise HTTPException(status_code=400, detail="订阅格式无效：请检查 YAML、节点列表和名称")


@router.get("/progress")
async def progress_stream():
    """SSE endpoint for progress updates"""
    async def event_generator():
        last_sent = 0
        while True:
            # Send new events
            while last_sent < len(state.events):
                event = state.events[last_sent]
                yield f"data: {json.dumps(public_data(event), ensure_ascii=False)}\n\n"
                last_sent += 1
            
            # Check if complete
            if not state.is_running and last_sent >= len(state.events):
                break
            
            await asyncio.sleep(0.1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.post("/stop")
async def stop_check():
    """Stop running task"""
    if not state.is_running:
        raise HTTPException(status_code=400, detail="没有正在运行的任务")
    
    state.is_running = False
    state.events.append({"type": "stopped"})
    return {"status": "stopped"}


@router.get("/nodes")
async def get_nodes():
    """Get all nodes"""
    return {"nodes": public_data(state.nodes), "is_running": state.is_running}


@router.get("/report")
async def download_report():
    """Download an anonymous metrics-only JSON report, separate from YAML export."""
    return JSONResponse(build_report(state.nodes), headers={
        "Content-Disposition": 'attachment; filename="nodescope-report.json"',
    })


@router.get("/history")
async def get_history():
    """List saved detection snapshots (newest first)."""
    try:
        from core.history import list_snapshots
        return {"items": list_snapshots()}
    except Exception:
        return {"items": []}


@router.get("/history/trend")
async def get_history_trend(node: str = ""):
    """Aggregate one node's trend across snapshots. Never raises."""
    if not node:
        return {"node": node, "items": []}
    try:
        from core.history import trend_for_node
        return {"node": node, "items": trend_for_node(node)}
    except Exception:
        return {"node": node, "items": []}


@router.get("/history/{name}")
async def get_history_item(name: str):
    """Load one snapshot by filename. 404 if missing or path is unsafe."""
    try:
        from core.history import load_snapshot
        data = load_snapshot(name)
    except Exception:
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    return data


@router.put("/nodes/{node_id}")
async def update_node(node_id: int, request: UpdateNodeRequest):
    """Update node name"""
    if _busy():
        raise HTTPException(status_code=409, detail="请等待检测和配置恢复完成")
    for node in state.nodes:
        if node["id"] == node_id:
            node["name"] = request.name
            return {"status": "updated", "node": public_data(node)}
    
    raise HTTPException(status_code=404, detail="节点不存在")


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: int):
    """Delete node"""
    if _busy():
        raise HTTPException(status_code=409, detail="请等待检测和配置恢复完成")
    for i, node in enumerate(state.nodes):
        if node["id"] == node_id:
            state.nodes.pop(i)
            return {"status": "deleted"}
    
    raise HTTPException(status_code=404, detail="节点不存在")


@router.post("/nodes/{node_id}/recheck")
async def recheck_node(node_id: int, request: RecheckRequest):
    """Recheck a specific node"""
    if _busy():
        raise HTTPException(status_code=409, detail="请等待检测和配置恢复完成")
    state.is_rechecking = True
    try:
        _validate_options(request.config)
        return await _recheck_node(node_id, request)
    finally:
        state.is_rechecking = False


async def _recheck_node(node_id: int, request: RecheckRequest):
    
    # Find the node
    target_node = None
    target_index = -1
    for i, node in enumerate(state.nodes):
        if node["id"] == node_id:
            target_node = node
            target_index = i
            break
    
    if not target_node:
        raise HTTPException(status_code=404, detail="节点不存在")
        
    name = target_node["name"]
    original_name = target_node.get("original_name", name)
    
    # Get config from request
    config = request.config
    if not config:
        print("[Warning] Received EMPTY config for recheck! This usually means frontend app.js is outdated (cached).")

    api_url = config.get("clash_api_url", "http://127.0.0.1:9097")
    api_secret = config.get("clash_api_secret", "")
    selector = config.get("selector_name", "GLOBAL")
    fast_mode = config.get("fast_mode", True)
    source = config.get("source", "ping0")
    fallback = config.get("fallback", True)
    headless = config.get("headless", True)
    
    # Update checker headless setting dynamically
    state.checker.headless = headless
   



    controller = ClashController(api_url, api_secret)
    original_mode = None
    original_global = None
    original_selections = {}
    
    try:
        # Snapshot and resolve the selector against the current Clash config.
        configs = await controller.get_configs()
        proxies_state = await controller.get_proxies()
        original_mode = configs.get("mode") if configs else None
        global_state = proxies_state.get("GLOBAL") if proxies_state else None
        original_global = global_state.get("now") if global_state else None
        original_selections = snapshot_selections(proxies_state)
        selector = _resolve_selector(proxies_state, selector, [original_name])

        # 1. Switch
        print(f"[Recheck] Switching to: {original_name}")
        if not await controller.set_mode("global"):
            raise Exception("无法切换 Clash 到全局模式")
        if selector != "GLOBAL" and not await controller.switch_proxy("GLOBAL", selector):
            raise Exception(f"无法将 GLOBAL 切换到代理组: {selector}")
        switched = await controller.switch_proxy(selector, original_name)
        
        if not switched:
             raise Exception("切换节点失败")
             
        # 2. Wait
        await asyncio.sleep(1)

        # Latency test runs concurrently with the check (zero added wall time);
        # the fresh value also clears any stale delay from a previous batch.
        get_delay = getattr(controller, "get_delay", None)
        delay_task = asyncio.create_task(get_delay(original_name)) if get_delay else None
 
        
        
        # 3. Check
        port = await controller.get_running_port()
        proxy_url = f"http://127.0.0.1:{port}"
        
         # 3. Check IP through Clash proxy
        if fast_mode:
            result = await state.checker.check_fast(
                proxy_url,
                source=source,
                fallback=fallback,
                enable_multi=config.get("enable_multi_source", True),
                api_keys={k: config.get(k, "") for k in ("abuseipdb_key", "ip2location_key", "ipqs_key")},
                dnsbl_enabled=config.get("dnsbl_enabled", True),
                dnsbl_zones=_parse_zones(config.get("dnsbl_zones") or config.get("dnsbl_zones_str", "")),
            dns_leak_enabled=config.get("dns_leak_enabled", True),
            unlock_enabled=config.get("unlock_enabled", False),
            ipv6_enabled=config.get("ipv6_enabled", False),
        )
        else:
            result = await state.checker.check_browser(proxy=proxy_url)

        if delay_task is not None:
            try:
                delay = await asyncio.wait_for(delay_task, timeout=8)
                if isinstance(delay, int):
                    result = dict(result)
                    result["_delay_ms"] = delay
            except Exception:
                pass

        # Share the same success/failure contract as batch checks.
        node_data = _make_node_data(node_id, original_name, target_node["proxy_config"], result)
        node_data["delay_ms"] = result.get("_delay_ms") if isinstance(result, dict) else None

        state.nodes[target_index] = node_data
        
        # 5. Push Event manually to trigger UI update
        event = {
            "type": "update", # New event type for single update
            "node": node_data
        }
        state.events.append(event)
        
        return {"status": "success", "node": public_data(node_data)}

    except Exception as e:
        print(f"[Recheck] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await reapply_selections(controller, original_selections)
        if original_mode:
            await controller.set_mode(original_mode)


@router.post("/export")
async def export_yaml(request: ExportRequest):
    """Export selected nodes as YAML"""
    selected_nodes = [n for n in state.nodes if n["id"] in request.node_ids]
    
    if not selected_nodes:
        raise HTTPException(status_code=400, detail="请选择要导出的节点")
    
    # Build name mapping for proxy-groups sync
    name_map = {n["original_name"]: n["name"] for n in selected_nodes}
    original_proxy_names = {
        proxy.get("name") for proxy in state.original_yaml.get("proxies", [])
    }
    
    # Clone original YAML (Deep Copy to avoid mutating state)
    export_data = copy.deepcopy(state.original_yaml)
    
    # Replace proxies with updated config and name
    new_proxies = []
    for node in selected_nodes:
        proxy = node["proxy_config"].copy()
        proxy["name"] = node["name"]
        new_proxies.append(proxy)
    
    export_data["proxies"] = new_proxies
    
    # Update proxy-groups
    for group in export_data.get("proxy-groups", []):
        new_group_proxies = []
        for proxy_name in group.get("proxies", []):
            if proxy_name in name_map:
                new_group_proxies.append(name_map[proxy_name])
            elif proxy_name in original_proxy_names:
                continue  # Omit every original proxy that was not selected.
            else:
                new_group_proxies.append(proxy_name)  # Keep DIRECT, REJECT, etc.
        group["proxies"] = new_group_proxies
    
    # Generate YAML
    stream = io.StringIO()
    yaml.dump(export_data, stream)
    yaml_content = stream.getvalue()

    # Save to file system for URL access. A stable "latest" copy backs
    # GET /api/export/subscribe so an imported Verge profile can be
    # refreshed with 更新 instead of importing a new profile every run.
    task_id = state.task_id or str(uuid.uuid4())
    now = datetime.now()
    filename = f"已检测_{now:%m%d-%H%M}_{len(selected_nodes)}节点.yaml"
    filepath = os.path.join(EXPORTS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    userinfo = build_userinfo_header(
        userinfo_from_traffic(parse_traffic_nodes(state.original_yaml.get("proxies")))
    )
    meta = {
        "userinfo": userinfo,
        "filename": filename,
        "task_id": task_id,
    }
    with open(os.path.join(EXPORTS_DIR, LATEST_EXPORT), "w", encoding="utf-8") as f:
        f.write(yaml_content)
    try:
        with open(os.path.join(EXPORTS_DIR, LATEST_META), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError:
        pass  # header-less subscribe still works

    return {
        "yaml": yaml_content,
        "filename": filename,
        "url": f"/exports/{quote(filename)}",
        "subscribe_url": "/api/export/subscribe",
    }


@router.get("/export/subscribe")
async def export_subscribe():
    """Serve the newest export with traffic headers, so one Verge profile
    can be updated in place (更新) instead of re-importing every run."""
    latest_path = os.path.join(EXPORTS_DIR, LATEST_EXPORT)
    if not os.path.isfile(latest_path):
        raise HTTPException(status_code=404, detail="尚无已检测配置：请先在页面导出一次")
    try:
        with open(latest_path, "rb") as f:
            content = f.read()
    except OSError:
        raise HTTPException(status_code=404, detail="已检测配置读取失败")
    if not content:
        raise HTTPException(status_code=404, detail="已检测配置为空")

    try:
        with open(os.path.join(EXPORTS_DIR, LATEST_META), "r", encoding="utf-8") as f:
            meta = json.load(f) or {}
    except Exception:
        meta = {}
    display_name = str(meta.get("filename") or LATEST_EXPORT)
    headers = {"Content-Disposition": content_disposition_header(display_name)}
    userinfo = meta.get("userinfo")
    if not userinfo:
        try:
            data = yaml.load(io.StringIO(content.decode("utf-8"))) or {}
            userinfo = build_userinfo_header(
                userinfo_from_traffic(parse_traffic_nodes(data.get("proxies")))
            )
        except Exception:
            userinfo = None
    if userinfo:
        headers["subscription-userinfo"] = str(userinfo)
    return Response(content=content, media_type="text/yaml; charset=utf-8", headers=headers)

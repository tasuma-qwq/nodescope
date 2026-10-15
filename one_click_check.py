"""Check the current Clash Verge subscription without copying YAML or secrets.

The script only reads Clash Verge's local configuration. During a run it changes
the active selector one node at a time, then restores the previous mode and
GLOBAL selection before writing an independent checked YAML export.

Node names keep the original subscription set. Suffixes are text-only data
(e.g. 【8% 住宅|原生 综合4】), not color emoji.
"""

import asyncio
import copy
import http.server
import hashlib
import json
import os
import re
import socket
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse
from urllib.request import urlopen

import yaml

from core.clash_api import ClashController
from core.ip_checker import IPChecker
from core.labels import FAIL_LABEL, format_data_label, strip_existing_label
from core.parallel import (
    build_parallel_config,
    find_free_ports,
    is_real_proxy,
    plan_batches,
    reapply_selections,
    select_parallel_base,
    snapshot_selections,
)
from core.history import list_snapshots, load_snapshot, save_with_git, trend_for_node
from core.subscription import (
    build_userinfo_header,
    content_disposition_header,
    friendly_stable_base,
    parse_traffic_nodes,
    userinfo_from_extra,
    userinfo_from_traffic,
)
from core.unlock import format_unlock_summary
from core.risk_score import compute_risk_score


APP_ROOT = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "io.github.clash-verge-rev.clash-verge-rev"
PROJECT_ROOT = Path(__file__).resolve().parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
SKIP_KEYWORDS = ("剩余", "重置", "到期", "有效期", "官网", "网址", "更新", "公告", "建议",
                 "expire", "traffic", "sync", "remain", "official", "网站")


def is_status_node(name: str) -> bool:
    text = str(name or "").lower()
    return any(keyword in text for keyword in SKIP_KEYWORDS)

# Stable sync endpoint: the checked YAML is served here on a fixed port so a
# Clash Verge profile imported ONCE can be refreshed via its 更新 button.
STABLE_PORT = 57520
STABLE_FILENAME = "checked_latest.yaml"
STABLE_META = "checked_latest.meta.json"
STABLE_BASE_URL = f"http://127.0.0.1:{STABLE_PORT}"
# /__ping answers this marker so _server_alive can tell our server from any
# unrelated program that happens to own the port.
SERVER_MARKER = "nodescope-sync-" + hashlib.sha256(str(EXPORTS_DIR.resolve()).encode("utf-8")).hexdigest()[:16]
_LATEST_SERVER_PROC: Optional[subprocess.Popen] = None

# Optional AI/streaming unlock probes (--unlock); display-only, adds ~8s/node.
UNLOCK_ENABLED = "--unlock" in sys.argv


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def current_profile_path() -> Tuple[Path, str, Dict[str, Any]]:
    profiles = load_yaml(APP_ROOT / "profiles.yaml")
    current_uid = profiles.get("current")
    item = next((item for item in profiles.get("items", []) if item.get("uid") == current_uid), None)
    if not item or item.get("type") != "remote":
        raise RuntimeError("当前 Clash Verge 配置不是可检测的订阅配置")

    profile_path = APP_ROOT / "profiles" / item["file"]
    if not profile_path.exists():
        raise RuntimeError(f"找不到当前订阅文件: {profile_path}")
    return profile_path, item.get("name") or current_uid, item


def resolve_selector(proxies_state: Dict[str, Dict[str, Any]], node_names: Iterable[str]) -> str:
    selectors = {
        name: proxy
        for name, proxy in proxies_state.items()
        if proxy.get("type", "").lower() == "selector"
    }
    if not selectors:
        raise RuntimeError("Clash 中未找到可切换的 Selector 代理组")

    nodes = set(node_names)
    candidates = []
    for name, proxy in selectors.items():
        if name == "GLOBAL":
            continue
        candidates.append((len(nodes.intersection(proxy.get("all", []))), name))

    coverage, selector = max(candidates, default=(0, ""))
    if coverage:
        return selector
    if nodes.intersection(selectors.get("GLOBAL", {}).get("all", [])):
        return "GLOBAL"
    raise RuntimeError("当前订阅的节点不在任何可切换代理组中")


def export_checked_config(original: Dict[str, Any], labels: Dict[str, str], output_path: Path) -> None:
    """Keep the original subscription; only append text labels to checked nodes."""
    export_data = copy.deepcopy(original)
    name_map: Dict[str, str] = {}

    for proxy in export_data.get("proxies", []):
        old_name = proxy.get("name") or ""
        base = strip_existing_label(old_name) or old_name
        suffix = labels.get(old_name) or labels.get(base)
        new_name = f"{base}{suffix}" if suffix else old_name
        name_map[old_name] = new_name
        proxy["name"] = new_name

    for group in export_data.get("proxy-groups", []):
        if "proxies" not in group:
            continue
        group["proxies"] = [name_map.get(name, name) for name in group["proxies"]]

    with output_path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(export_data, file, allow_unicode=True, sort_keys=False)


def start_export_server(output_path: Path, headers: Dict[str, str] = None):
    """Serve only this YAML on a random localhost port. Never exposes other files."""
    file_bytes = output_path.read_bytes()
    filename = output_path.name
    hits = {"n": 0}

    from core.local_http import LocalSubscriptionHandler

    class Handler(LocalSubscriptionHandler):
        def _respond(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/yaml; charset=utf-8")
            self.send_header("Content-Length", str(len(file_bytes)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def _match(self) -> bool:
            path = unquote(urlparse(self.path).path).lstrip("/")
            return path == filename

        def do_HEAD(self):
            if not self._match():
                self.send_error(404)
                return
            self._respond()
            hits["n"] += 1

        def do_GET(self):
            if not self._match():
                self.send_error(404)
                return
            self._respond()
            self.wfile.write(file_bytes)
            hits["n"] += 1

        def log_message(self, format, *args):
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, port, hits


def import_into_clash(output_path: Path, profile_name: str, headers: Dict[str, str] = None) -> bool:
    """Serve the export locally and open Clash Verge's import protocol. No web UI needed."""
    server = None
    try:
        server, port, hits = start_export_server(output_path, headers)
        public_url = f"http://127.0.0.1:{port}/{quote(output_path.name)}"
        with urlopen(public_url, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            body = response.read()
        if not body:
            raise RuntimeError("本地临时导入服务返回空文件")

        uri = (
            "clash://install-config?"
            f"url={quote(public_url, safe='')}&name={quote(profile_name, safe='')}"
        )
        os.startfile(uri)
        print("已唤起 Clash Verge 导入配置，请在弹窗中确认。")
        print("等待 Clash 下载配置（最多 90 秒，无需先开检测器网页）...")
        deadline = time.time() + 90
        while time.time() < deadline:
            if hits["n"] >= 2:
                time.sleep(1.5)
                print("Clash 已拉取配置。")
                return True
            time.sleep(0.2)
        print("未检测到 Clash 下载。可在 Verge 中手动导入下面这个文件：")
        print(f"  {output_path}")
        return False
    except OSError as error:
        print(f"\n配置已生成，但无法自动唤起 Clash Verge: {error}")
        print(f"请手动导入: {output_path}")
        return False
    except Exception as error:
        print(f"\n自动导入失败: {error}")
        print(f"请手动导入: {output_path}")
        return False
    finally:
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass


def _stable_headers(display_name: str) -> Dict[str, str]:
    """Fresh per-request headers: content-disposition + traffic userinfo."""
    headers = {"Content-Disposition": content_disposition_header(display_name)}
    userinfo = None
    try:
        meta = json.loads((EXPORTS_DIR / STABLE_META).read_text(encoding="utf-8"))
        userinfo = (meta or {}).get("userinfo")
    except Exception:
        userinfo = None
    if not userinfo:
        try:
            data = yaml.safe_load((EXPORTS_DIR / STABLE_FILENAME).read_text(encoding="utf-8")) or {}
            userinfo = build_userinfo_header(
                userinfo_from_traffic(parse_traffic_nodes(data.get("proxies")))
            )
        except Exception:
            userinfo = None
    if userinfo:
        headers["subscription-userinfo"] = str(userinfo)
    return headers


def build_latest_server(port: int = None) -> http.server.ThreadingHTTPServer:
    """Serve exports/checked_latest.yaml on the fixed port, re-reading disk
    on every request so new runs sync the same URL without a restart."""
    latest_path = EXPORTS_DIR / STABLE_FILENAME

    from core.local_http import LocalSubscriptionHandler

    class Handler(LocalSubscriptionHandler):
        def _respond(self):
            try:
                body = latest_path.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/yaml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in _stable_headers(f"{_stable_display_base()}.yaml").items():
                self.send_header(key, value)
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)

        def _match(self) -> bool:
            path = unquote(urlparse(self.path).path).lstrip("/")
            return path == STABLE_FILENAME

        def do_HEAD(self):
            if self._match():
                self._respond()
            elif self.path.startswith("/__ping"):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(SERVER_MARKER)))
                self.end_headers()
            else:
                self.send_error(404)

        def do_GET(self):
            if self._match():
                self._respond()
            elif self.path.startswith("/__ping"):
                body = SERVER_MARKER.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            return

    return http.server.ThreadingHTTPServer(("127.0.0.1", STABLE_PORT if port is None else port), Handler)


def _stable_display_base() -> str:
    """Card/file name for the stable export; falls back to the meta json."""
    try:
        meta = json.loads((EXPORTS_DIR / STABLE_META).read_text(encoding="utf-8"))
        name = str((meta or {}).get("filename") or "")
        if name.endswith(".yaml"):
            return name[:-5]
    except Exception:
        pass
    return STABLE_FILENAME[:-5]


def serve_latest_forever() -> None:
    build_latest_server().serve_forever()


def _server_alive() -> bool:
    """True only when OUR current server answers /__ping with the marker."""
    try:
        with urlopen(f"{STABLE_BASE_URL}/__ping", timeout=1.5) as response:
            return response.status == 200 and response.read().decode("utf-8", "ignore").strip() == SERVER_MARKER
    except Exception:
        return False


def _port_occupied() -> bool:
    sock = socket.socket()
    sock.settimeout(1.5)
    try:
        sock.connect(("127.0.0.1", STABLE_PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _spawn_latest_server() -> Optional[subprocess.Popen]:
    global _LATEST_SERVER_PROC
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = str(pythonw if pythonw.exists() else exe)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [launcher, str(Path(__file__).resolve()), "--serve"],
        cwd=str(PROJECT_ROOT),
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _LATEST_SERVER_PROC = proc
    return proc


def ensure_latest_server() -> bool:
    """Have the stable sync endpoint running (replace stale spawns if needed)."""
    if _server_alive():
        return True
    if _port_occupied():
        print("端口 57520 被其他程序或另一份副本占用，固定同步不可用，回退一次性导入。")
        return False
    proc = _spawn_latest_server()
    if proc is None:
        return False
    deadline = time.time() + 5
    while time.time() < deadline:
        if _server_alive():
            return True
        time.sleep(0.2)
    return False


def stable_profile_imported() -> bool:
    """True when some Verge profile already points at the stable URL."""
    try:
        profiles = load_yaml(APP_ROOT / "profiles.yaml")
        for item in profiles.get("items", []) or []:
            if f"127.0.0.1:{STABLE_PORT}" in str(item.get("url") or ""):
                return True
    except Exception:
        pass
    return False


_REGION_KEYWORDS = (
    ("香港", "香港"), ("台湾", "台湾"), ("日本", "日本"), ("美国", "美国"),
    ("新加坡", "新加坡"), ("韩国", "韩国"), ("马来西亚", "马来"), ("泰国", "泰国"),
    ("英国", "英国"), ("德国", "德国"), ("法国", "法国"), ("荷兰", "荷兰"),
    ("土耳其", "土耳其"), ("阿根廷", "阿根廷"), ("越南", "越南"), ("菲律宾", "菲律宾"),
    ("印度", "印度"), ("澳门", "澳门"), ("加拿大", "加拿大"), ("澳大利亚", "澳洲"),
    ("澳洲", "澳洲"), ("俄罗斯", "俄罗斯"),
)
# OpenAI / Google 都不服务这些地区，AI 类用途要避开。
_AI_EXCLUDED_REGIONS = {"香港", "澳门", "俄罗斯", "其他"}


def region_of(name: str) -> str:
    text = str(name or "")
    for key, label in _REGION_KEYWORDS:
        if key in text:
            return label
    return "其他"


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


# GPT 解锁状态参与 AI 推荐排序：确认可用 < 部分可用 < 无数据 < 确认封锁。
_GPT_RANK = {"yes": 0, "web_only": 1, "app_only": 1, "unknown": 2, "failed": 2, "no": 3}


def _usable_results(results_by_name: Dict[str, Any]) -> List[Dict[str, Any]]:
    parsed = []
    for name, result in (results_by_name or {}).items():
        if not isinstance(result, dict):
            continue
        if result.get("ip") in (None, "", "❓") or result.get("source") not in {"ping0", "ippure"}:
            continue
        try:
            pure = float(str(result.get("pure_score", "")).replace("%", "").strip())
        except (TypeError, ValueError):
            continue
        src = f"{result.get('ip_src') or ''}{result.get('multi_native') or ''}"
        kind = f"{result.get('ip_attr') or ''}{result.get('ip_type') or ''}"
        risk = compute_risk_score(result).get("risk_score")
        unlock = result.get("unlock") if isinstance(result.get("unlock"), dict) else None
        gpt = (unlock or {}).get("chatgpt") if isinstance((unlock or {}).get("chatgpt"), dict) else {}
        parsed.append({
            "name": name,
            "region": region_of(name),
            "pure": pure,
            "native": "广播" not in src,
            "residential": "住宅" in kind,
            "risk": risk if isinstance(risk, int) else 99,
            "delay": result.get("_delay") if isinstance(result.get("_delay"), int) else None,
            "unlock": format_unlock_summary(unlock) if unlock else "",
            "gpt_rank": _GPT_RANK.get((gpt or {}).get("status"), 9),
        })
    return parsed


def _ai_sort_key(row):
    return (
        row["gpt_rank"],
        0 if row["native"] else 1,
        0 if row["residential"] else 1,
        row["risk"],
        row["pure"],
    )


def _general_sort_key(row):
    return (row["risk"], row["pure"])


def _describe(row) -> str:
    kind = "原生住宅" if row["native"] and row["residential"] else ("原生" if row["native"] else "广播")
    delay = f", {row['delay']}ms" if row["delay"] else ""
    unlock = f", {row['unlock']}" if row["unlock"] else ""
    return f"{row['name']}（{row['region']}, 污染{row['pure']:g}%, {kind}, 综合{row['risk']}{delay}{unlock}）"


def print_usage_summary(results_by_name: Dict[str, Any]) -> None:
    """End-of-run hints: region overview + per-use picks. Never raises."""
    try:
        parsed = _usable_results(results_by_name)
        if len(parsed) < 3:
            return

        print("\n—— 用途推荐（基于污染度/属性/来源/综合分，仅供参考，AI 可用性请以解锁探针为准）——")
        ai_pool = [r for r in parsed if r["region"] not in _AI_EXCLUDED_REGIONS]
        ai_pool.sort(key=_ai_sort_key)
        has_unlock = any(r["unlock"] for r in parsed)
        if ai_pool:
            tail = "，已按实测 GPT 解锁排序）" if has_unlock else "）"
            print(f"  GPT/Gemini 首选（非港 + 原生住宅优先{tail}")
            for row in ai_pool[:3]:
                print(f"    · {_describe(row)}")
        else:
            print("  GPT/Gemini 首选: 无非港可用节点，请切换订阅或节点。")

        general = sorted(parsed, key=_general_sort_key)
        print("  GitHub/X/日常（低综合分优先）:")
        for row in general[:3]:
            print(f"    · {_describe(row)}")

        by_region: Dict[str, List[Dict[str, Any]]] = {}
        for row in parsed:
            by_region.setdefault(row["region"], []).append(row)
        overview = []
        for region, rows in sorted(by_region.items(), key=lambda kv: -len(kv[1])):
            natives = sum(1 for r in rows if r["native"])
            median = _median([r["pure"] for r in rows])
            overview.append(f"{region} {len(rows)}个(原生{natives}, 污染中位{median:g}%)")
        print("  地区概览: " + " | ".join(overview))
    except Exception:
        pass


_LABEL_RE = re.compile(r"【([^】]*)】")
_PCT_RE = re.compile(r"^([\d.]+)%")


def load_previous_labels(path: Path) -> Dict[str, Dict[str, Any]]:
    """Parse labeled node names from the previous stable export. Never raises.

    Returns {base_name: {"pure": float|None, "fail": bool}} keyed by the
    label-stripped node name.
    """
    try:
        import yaml as _yaml
        data = _yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for proxy in data.get("proxies", []) or []:
        if not isinstance(proxy, dict):
            continue
        name = str(proxy.get("name") or "")
        if not name:
            continue
        match = _LABEL_RE.search(name)
        label = match.group(1) if match else ""
        base = _LABEL_RE.sub("", name).strip()
        if not base:
            continue
        row: Dict[str, Any] = {"pure": None, "fail": FAIL_LABEL in name}
        if not row["fail"]:
            pct = _PCT_RE.match(label)
            if pct:
                try:
                    row["pure"] = float(pct.group(1))
                except ValueError:
                    pass
        out[base] = row
    return out


def print_changes_vs_previous(old_labels: Dict[str, Dict[str, Any]], results_by_name: Dict[str, Any]) -> None:
    """Diff this run against the previous export. Never raises.

    Reports: recovered (was fail, now ok), regressed (was ok, now fail),
    and pollution shifts of ≥10 points. Quiet when there is nothing to say.
    """
    try:
        if not old_labels:
            return
        recovered, regressed, dirtier, cleaner = [], [], [], []
        for name, result in (results_by_name or {}).items():
            if not isinstance(result, dict):
                continue
            base = strip_existing_label(name) or name
            old = old_labels.get(base)
            if old is None:
                continue
            fail_now = result.get("ip") in (None, "", "❓") or result.get("source") not in {"ping0", "ippure"}
            if old.get("fail") and not fail_now:
                recovered.append(base)
                continue
            if not old.get("fail") and fail_now:
                regressed.append(base)
                continue
            if fail_now:
                continue
            try:
                pure_now = float(str(result.get("pure_score", "")).replace("%", "").strip())
            except (TypeError, ValueError):
                continue
            pure_old = old.get("pure")
            if not isinstance(pure_old, (int, float)):
                continue
            delta = pure_now - pure_old
            if delta >= 10:
                dirtier.append(f"{base}（{pure_old:g}% → {pure_now:g}%）")
            elif delta <= -10:
                cleaner.append(f"{base}（{pure_old:g}% → {pure_now:g}%）")

        lines = []
        if recovered:
            lines.append(f"  恢复检出: {', '.join(recovered[:8])}" + ("…" if len(recovered) > 8 else ""))
        if regressed:
            lines.append(f"  转为失败: {', '.join(regressed[:8])}" + ("…" if len(regressed) > 8 else ""))
        if dirtier:
            lines.append(f"  明显变脏: {', '.join(dirtier[:6])}" + ("…" if len(dirtier) > 6 else ""))
        if cleaner:
            lines.append(f"  明显变净: {', '.join(cleaner[:6])}" + ("…" if len(cleaner) > 6 else ""))
        if lines:
            print("\n—— 与上次检测对比 ——")
            for line in lines:
                print(line)
    except Exception:
        pass


def build_history_nodes(labels: Dict[str, str], results_by_name: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Snapshot rows for core/history (same whitelist contract as the Web)."""
    rows: List[Dict[str, Any]] = []
    for name, result in (results_by_name or {}).items():
        if not isinstance(result, dict):
            continue
        base = strip_existing_label(name) or name
        ok = result.get("ip") not in (None, "", "❓") and result.get("source") in {"ping0", "ippure"}
        risk = compute_risk_score(result) if ok else {"risk_score": None, "risk_level": "未知"}
        rows.append({
            "name": f"{base}{labels.get(name, '')}",
            "original_name": base,
            "ip": result.get("ip", "❓"),
            "pure_score": result.get("pure_score", "❓"),
            "risk": result.get("pure_score", "❓"),
            "source": result.get("source", "unknown"),
            "status": "✅" if ok else "❌ 失败",
            "error": result.get("error"),
            "geo": result.get("geo", ""),
            "isp": result.get("isp", ""),
            "asn": result.get("asn", ""),
            "ip_type": result.get("ip_type", ""),
            "multi_native": result.get("multi_native", ""),
            "dnsbl_blacklisted": bool(result.get("dnsbl_blacklisted")),
            "dns_leak_state": "unknown",
            "risk_score": risk.get("risk_score"),
            "risk_level": risk.get("risk_level", "未知"),
        })
    return rows


def save_run_history(labels: Dict[str, str], results_by_name: Dict[str, Any]) -> None:
    """Persist this run under git-managed history/. Never raises."""
    try:
        rows = build_history_nodes(labels, results_by_name)
        if not rows:
            return
        pures = []
        for row in rows:
            try:
                pures.append(float(str(row["pure_score"]).replace("%", "").strip()))
            except (TypeError, ValueError):
                continue
        summary = {
            "avg_pure": round(sum(pures) / len(pures), 2) if pures else None,
            "blacklisted": sum(1 for r in rows if r["dnsbl_blacklisted"]),
            "dns_leak": 0,
        }
        info = save_with_git(rows, batch_id=time.strftime("%Y%m%d-%H%M%S"), summary=summary, auto_commit=False)
        path = (info or {}).get("path") or ""
        if path:
            print(f"已存档: {path}{'（已 git 提交）' if (info or {}).get('committed') else ''}")
    except Exception:
        pass


def print_trend(keyword: str) -> None:
    """--trend: print one node's cross-run history. Never raises."""
    try:
        keyword = str(keyword or "").strip()
        if not keyword:
            print("用法: --trend <节点名关键词>")
            return
        names = set()
        for snap in list_snapshots()[:50]:
            data = load_snapshot(snap.get("name", "")) or {}
            for node in data.get("nodes", []) or []:
                if not isinstance(node, dict):
                    continue
                for key in ("original_name", "name"):
                    val = node.get(key)
                    if isinstance(val, str) and keyword in val:
                        names.add(strip_existing_label(val) or val)
        matches = sorted(names)[:5]
        if not matches:
            print(f"历史快照中没有匹配「{keyword}」的节点（history/ 共 {len(list_snapshots())} 份快照）。")
            return
        for name in matches:
            print(f"\n[{name}]")
            rows = trend_for_node(name)
            if not rows:
                print("  （无有效记录）")
                continue
            for row in rows:
                pure = row.get("pure_score", "❓")
                risk = row.get("risk_score")
                risk_text = "—" if risk is None else str(risk)
                fail = " 失败" if row.get("status") and "❌" in str(row.get("status")) else ""
                print(f"  {row.get('time', '?')}  污染 {pure}  综合 {risk_text}{fail}  来源 {row.get('source', '?')}")
    except Exception as error:
        print(f"趋势查询失败: {error}")


def clean_old_exports(keep: int = 2) -> None:
    """--clean-exports: delete legacy per-run exports, opt-in.

    Keeps the stable pair plus the newest `keep` legacy files. Never raises.
    """
    try:
        legacy = []
        for p in EXPORTS_DIR.glob("*.yaml"):
            if p.name == STABLE_FILENAME:
                continue
            if "_checked_" in p.name or p.name.startswith("clash_checked"):
                legacy.append(p)
        legacy.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        victims = legacy[keep:]
        if not victims:
            print("exports/ 没有需要清理的旧导出。")
            return
        removed = 0
        for p in victims:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        print(f"已清理 {removed} 个旧导出文件（保留最新 {min(keep, len(legacy))} 个旧文件 + {STABLE_FILENAME}）。")
    except Exception as error:
        print(f"清理失败: {error}")


async def run_parallel_check(
    controller: ClashController,
    checker: IPChecker,
    original_config: Dict[str, Any],
    runtime_config: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    labels: Dict[str, str],
    failures: List[str],
    results_out: Dict[str, Any] = None,
) -> bool:
    """mihomo listeners-based parallel check (same safety valve as the Web UI).

    Returns True when fully handled (labels/failures filled); False makes the
    caller fall back to the serial path. The base config is restored on every
    exit path.
    """
    names = [p["name"] for p in candidates]
    proxies_state = await controller.get_proxies()
    if not isinstance(proxies_state, dict) or not proxies_state:
        return False
    # Reload can reset selector picks; snapshot every group's choice to replay
    # after the config is restored.
    selections_before = snapshot_selections(proxies_state)
    real_names = {n for n, p in proxies_state.items() if is_real_proxy(p)}
    if any(name not in real_names for name in names):
        print("并行前置不满足: 节点名未全部在当前配置中，回退串行")
        return False

    base = select_parallel_base(original_config, runtime_config, names)
    if not base:
        print("并行前置不满足: 无含全部节点的完整配置，回退串行")
        return False

    ports = find_free_ports(len(names))
    if len(ports) < len(names):
        print("并行前置不满足: 空闲端口不足，回退串行")
        return False

    new_cfg = build_parallel_config(base, names, ports)
    if not new_cfg:
        return False

    if not await controller.reload_config(new_cfg):
        print("并行前置不满足: 注入 listeners 失败，回退串行")
        return False

    port_by_name = dict(zip(names, ports))
    try:
        batches = plan_batches(names)
        print(f"并行检测: {len(names)} 节点 / {len(batches)} 批（批内并发，无需切换节点）")
        for batch_index, batch in enumerate(batches, start=1):
            coros = [
                checker.check_fast(
                    f"http://127.0.0.1:{port_by_name[name]}",
                    source="ippure",
                    fallback=True,
                    enable_multi=True,
                    dns_leak_enabled=False,
                    unlock_enabled=UNLOCK_ENABLED,
                    ipv6_enabled=True,
                )
                for name in batch
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)
            # Batch-concurrent latency test: nearly free next to the checks.
            delay_results = await asyncio.gather(
                *(controller.get_delay(name) for name in batch), return_exceptions=True
            )
            delay_by_name = {
                name: (d if isinstance(d, int) else None)
                for name, d in zip(batch, delay_results)
            }
            print(f"[批次 {batch_index}/{len(batches)}]")
            for name, result in zip(batch, results):
                delay = delay_by_name.get(name)
                delay_text = f" [{delay}ms]" if isinstance(delay, int) else ""
                if isinstance(result, Exception):
                    print(f"  {name}  检测失败: {result}")
                    failures.append(f"{name}\t检测失败: {result}")
                    labels[name] = FAIL_LABEL
                    continue
                if UNLOCK_ENABLED:
                    unlock_line = format_unlock_summary(result.get("unlock"))
                    if unlock_line:
                        print(f"  解锁[{name}]: {unlock_line}")
                if result.get("ip") == "❓" or result.get("source") not in {"ping0", "ippure"}:
                    reason = result.get("error", "检测源未返回有效 IP")
                    print(f"  {name}  检测失败: {reason}")
                    failures.append(f"{name}\t检测失败: {reason}")
                    labels[name] = FAIL_LABEL
                    continue
                labels[name] = format_data_label(result)
                geo = result.get("geo") or ""
                v6 = f" [v6✓]" if result.get("ipv6") else ""
                print(f"  {name}  {result.get('ip')} {labels[name]}{delay_text}{v6}{('  ' + geo) if geo else ''}")
                if results_out is not None:
                    row = dict(result)
                    row["_delay"] = delay_by_name.get(name)
                    results_out[name] = row
        return True
    finally:
        restored = await controller.reload_config(base)
        print("已恢复 base 配置。" if restored else "恢复 base 配置失败，请手动检查 Clash 配置！")
        await reapply_selections(controller, selections_before)


async def main() -> int:
    verge_config = load_yaml(APP_ROOT / "clash-verge.yaml")
    api_url = f"http://{verge_config.get('external-controller', '127.0.0.1:9097')}"
    secret = verge_config.get("secret", "")
    profile_path, profile_name, profile_item = current_profile_path()
    original = load_yaml(profile_path)
    candidates = [
        proxy for proxy in original.get("proxies", [])
        if proxy.get("name") and not is_status_node(proxy["name"])
    ]
    if not candidates:
        raise RuntimeError("当前订阅没有可检测节点")

    controller = ClashController(api_url, secret)
    configs = await controller.get_configs()
    proxies_state = await controller.get_proxies()
    if not configs or not proxies_state:
        raise RuntimeError("无法连接 Clash 外部控制器，请确认 Clash Verge 正在运行")

    selector = resolve_selector(proxies_state, (node["name"] for node in candidates))
    original_mode = configs.get("mode")
    original_global = proxies_state.get("GLOBAL", {}).get("now")
    original_selections = snapshot_selections(proxies_state)
    port = await controller.get_running_port()
    local_proxy = f"http://127.0.0.1:{port}"
    checker = IPChecker(headless=True)
    labels: Dict[str, str] = {}
    failures: List[str] = []
    results_by_name: Dict[str, Any] = {}

    print(f"当前订阅: {profile_name}")
    print(f"检测节点: {len(candidates)} | 代理组: {selector}{' | AI解锁: 开' if UNLOCK_ENABLED else ''}")

    parallel_handled = False
    if "--serial" in sys.argv:
        print("已指定 --serial，走串行检测。")
    else:
        try:
            parallel_handled = await run_parallel_check(
                controller, checker, original, verge_config, candidates, labels, failures,
                results_out=results_by_name,
            )
        except Exception as error:
            print(f"并行检测不可用，回退串行: {error}")

    if parallel_handled:
        print("\n并行检测完成，Clash 配置已恢复。")
    else:
        print("串行检测：期间会短暂逐个切换节点，完成后自动恢复。\n")
        try:
            if not await controller.set_mode("global"):
                raise RuntimeError("无法切换 Clash 到全局模式")
            if selector != "GLOBAL" and not await controller.switch_proxy("GLOBAL", selector):
                raise RuntimeError(f"无法将 GLOBAL 切换到代理组: {selector}")

            for index, proxy in enumerate(candidates, start=1):
                name = proxy["name"]
                print(f"[{index}/{len(candidates)}] {name}")
                if not await controller.switch_proxy(selector, name):
                    print("  切换失败")
                    failures.append(f"{name}\t切换失败")
                    labels[name] = FAIL_LABEL
                    continue

                await asyncio.sleep(1)
                get_delay = getattr(controller, "get_delay", None)
                delay_task = asyncio.create_task(get_delay(name)) if get_delay else None
                result = await checker.check_fast(
                    local_proxy,
                    source="ippure",
                    fallback=True,
                    enable_multi=True,
                    dns_leak_enabled=False,
                    unlock_enabled=UNLOCK_ENABLED,
                )
                if UNLOCK_ENABLED:
                    unlock_line = format_unlock_summary(result.get("unlock"))
                    print(f"  解锁: {unlock_line or '（无结果）'}")
                delay = None
                if delay_task is not None:
                    try:
                        delay = await asyncio.wait_for(delay_task, timeout=8)
                    except Exception:
                        delay = None
                delay_text = f" [{delay}ms]" if isinstance(delay, int) else ""
                if result.get("ip") == "❓" or result.get("source") not in {"ping0", "ippure"}:
                    reason = result.get("error", "检测源未返回有效 IP")
                    print(f"  检测失败{delay_text}: {reason}")
                    failures.append(f"{name}\t检测失败: {reason}")
                    labels[name] = FAIL_LABEL
                    continue

                labels[name] = format_data_label(result)
                geo = result.get("geo") or ""
                ip_addr = result.get("ip") or ""
                extra = f"  {geo}" if geo else ""
                print(f"  {ip_addr} {labels[name]}{delay_text}{extra}")
                results_by_name[name] = {**result, "_delay": delay}
        finally:
            await reapply_selections(controller, original_selections)
            if original_mode:
                await controller.set_mode(original_mode)

    EXPORTS_DIR.mkdir(exist_ok=True)
    tagged = sum(1 for value in labels.values() if value != FAIL_LABEL)
    stable_base = friendly_stable_base(profile_name or profile_path.stem)
    output_path = EXPORTS_DIR / STABLE_FILENAME
    previous_labels = load_previous_labels(output_path)  # before overwrite
    export_checked_config(original, labels, output_path)
    print(f"\n完成: {tagged}/{len(candidates)} 个节点取得真实结果（原订阅节点全部保留）")
    if not UNLOCK_ENABLED:
        print("（提示：加 --unlock 可附带 GPT/Gemini/Claude/Netflix 解锁检测，每节点最多 +20s）")
    print(f"配置: {output_path}")
    try:
        legacy = [
            p.name for p in EXPORTS_DIR.glob("*.yaml")
            if p.name != STABLE_FILENAME and ("_checked_" in p.name or p.name.startswith("clash_checked"))
        ]
        if legacy:
            print(f"提示: exports/ 还有 {len(legacy)} 个旧流程导出文件，可手动清理（现在只使用 {STABLE_FILENAME}）")
    except Exception:
        pass
    if failures:
        print(f"未检出: {len(failures)}（节点名标记为检测失败，未从订阅删除）")
    print_usage_summary(results_by_name)
    print_changes_vs_previous(previous_labels, results_by_name)
    if "--no-history" not in sys.argv:
        save_run_history(labels, results_by_name)

    # Verge turns subscription-userinfo into the profile card's traffic bar;
    # prefer Verge's own last-known numbers, fall back to status nodes.
    traffic = userinfo_from_extra(profile_item.get("extra")) or userinfo_from_traffic(
        parse_traffic_nodes(original.get("proxies"))
    )
    meta = {"filename": f"{stable_base}.yaml", "userinfo": build_userinfo_header(traffic)}
    try:
        (EXPORTS_DIR / STABLE_META).write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as error:
        print(f"提示: 流量信息暂不可写: {error}")

    if ensure_latest_server():
        if stable_profile_imported():
            print(f"结果已同步。打开 Clash Verge，对「{stable_base}」这张配置点 更新 即可刷新检测分数。")
        else:
            uri = (
                "clash://install-config?"
                f"url={quote(f'{STABLE_BASE_URL}/{STABLE_FILENAME}', safe='')}"
                f"&name={quote(stable_base, safe='')}"
            )
            os.startfile(uri)
            print(f"首次使用：已唤起 Clash Verge 导入「{stable_base}」（含流量信息），请在弹窗中确认。")
            print("之后每次一键检测，只需在 Verge 对这张配置点 更新，检测分数就会原地刷新，不再生成新订阅。")
        return 0 if tagged else 2

    # Fallback: one-shot temp server import (persistent sync unavailable).
    print("固定同步服务启动失败，回退为一次性导入。")
    import_into_clash(output_path, stable_base, _stable_headers(f"{stable_base}.yaml"))
    return 0 if tagged else 2


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NodeScope：读取 Clash Verge 当前订阅并直接检测，无需网页。")
    parser.add_argument("--unlock", action="store_true", help="附带 AI / 流媒体端点探测")
    parser.add_argument("--serial", action="store_true", help="强制串行检测")
    parser.add_argument("--no-history", action="store_true", help="不保存本地检测历史")
    parser.add_argument("--trend", nargs="?", const="", help="查看节点关键词的历史趋势")
    parser.add_argument("--clean-exports", action="store_true", help="清理旧导出，保留最新文件")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.parse_args()
    if "--serve" in sys.argv:
        serve_latest_forever()
        raise SystemExit(0)
    if "--trend" in sys.argv:
        index = sys.argv.index("--trend")
        keyword = sys.argv[index + 1] if index + 1 < len(sys.argv) and not sys.argv[index + 1].startswith("--") else ""
        print_trend(keyword)
        raise SystemExit(0)
    if "--clean-exports" in sys.argv:
        clean_old_exports()
        raise SystemExit(0)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as error:
        print(f"\n错误: {error}")
        raise SystemExit(1)

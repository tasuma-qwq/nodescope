"""Offline tests for clash_automator's numeric-label and restore alignment."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clash_automator as ca  # noqa: E402
from core.labels import FAIL_LABEL  # noqa: E402


class FakeController:
    def __init__(self, switch_ok=True):
        self.switch_ok = switch_ok
        self.modes = []
        self.selections = []

    async def switch_proxy(self, selector, proxy_name):
        self.selections.append((selector, proxy_name))
        return self.switch_ok

    async def get_configs(self):
        return {"mode": "rule"}

    async def get_proxies(self):
        return {"GLOBAL": {"type": "Selector", "now": "grp", "all": ["grp"]}}


class FakeChecker:
    async def check_fast(self, proxy=None, source="ping0", fallback=True):
        return {"ip": "1.2.3.4", "source": "ping0", "pure_score": "8%",
                "ip_attr": "住宅", "ip_src": "原生"}


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=10))


def test_single_proxy_returns_numeric_label_and_fail_label():
    ok = _run(ca.test_single_proxy(FakeController(), FakeChecker(), "香港01", "grp", "http://127.0.0.1:1"))
    assert ok.startswith("【") and "8%" in ok and FAIL_LABEL not in ok, ok

    bad = _run(ca.test_single_proxy(FakeController(switch_ok=False), FakeChecker(), "香港01", "grp", "http://127.0.0.1:1"))
    assert bad == FAIL_LABEL, bad


def test_save_config_results_keeps_all_and_strips_old_labels():
    config = {
        "proxies": [
            {"name": "香港A 【9% 机房|广播 综合9】", "type": "ss"},
            {"name": "状态节点（剩余流量：10GB）", "type": "ss"},
        ],
        "proxy-groups": [{"name": "grp", "proxies": ["香港A 【9% 机房|广播 综合9】", "状态节点（剩余流量：10GB）", "DIRECT"]}],
    }
    results_map = {"香港A 【9% 机房|广播 综合9】": "【8% 住宅|原生 综合4】"}
    out_path = os.path.join(tempfile_dir(), "out.yaml")
    ca.save_config_results(config, results_map, out_path)
    text = open(out_path, encoding="utf-8").read()
    assert "香港A 【8% 住宅|原生 综合4】" in text, text
    assert "状态节点（剩余流量：10GB）" in text, "traffic-info nodes must survive"
    assert "DIRECT" in text
    assert "9% 机房" not in text, "old label must be stripped before appending"
    cleanup(out_path)


def tempfile_dir():
    import tempfile
    return tempfile.gettempdir()


def cleanup(path):
    try:
        os.remove(path)
    except OSError:
        pass


def main() -> int:
    tests = [
        test_single_proxy_returns_numeric_label_and_fail_label,
        test_save_config_results_keeps_all_and_strips_old_labels,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

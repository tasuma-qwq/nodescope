"""Offline tests for the one-click parallel check (fake controller/checker)."""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import one_click_check as occ  # noqa: E402

NAMES = [f"node{i:02d}" for i in range(13)]  # 2 batches: 12 + 1
occ.find_free_ports = lambda n: [40000 + i for i in range(n)]  # deterministic
occ.UNLOCK_ENABLED = False


class FakeController:
    def __init__(self, names, reload_ok=True):
        self.names = list(names)
        self.reload_ok = reload_ok
        self.reloads = []
        self.delay_calls = []
        self.switch_calls = []
        self.reloaded = False

    async def get_proxies(self):
        base = {n: {"type": "ss", "now": "", "all": []} for n in self.names}
        # After the (simulated) reload, the selector reset to a default node —
        # exactly the collateral the snapshot/replay fix exists for.
        picked = "新加坡03" if self.reloaded else "美国01"
        base["Proxies"] = {"type": "selector", "now": picked, "all": list(self.names)}
        return base

    async def reload_config(self, cfg):
        self.reloads.append(cfg)
        self.reloaded = True
        return self.reload_ok

    async def switch_proxy(self, group, name):
        self.switch_calls.append((group, name))
        return True

    async def get_delay(self, name, timeout_ms=5000, test_url=None):
        self.delay_calls.append(name)
        return 123


class FakeChecker:
    """Maps the per-node port back to the node name (ports patched deterministic)."""

    def __init__(self, fail_names=(), raise_names=()):
        self.fail_names = set(fail_names)
        self.raise_names = set(raise_names)
        self.names_seen = []

    async def check_fast(self, proxy=None, **kwargs):
        port = int(str(proxy).rsplit(":", 1)[1])
        name = NAMES[port - 40000]
        self.names_seen.append(name)
        if name in self.raise_names:
            raise RuntimeError(f"boom {name}")
        if name in self.fail_names:
            return {"ip": "❓", "source": "failed", "error": "down"}
        return {"ip": "1.2.3.4", "source": "ippure", "pure_score": "8%"}


def _candidates(names):
    return [{"name": n, "type": "ss", "server": "example.com"} for n in names]


def _full(names):
    return {
        "mixed-port": 7897,
        "external-controller": "127.0.0.1:9097",
        "proxies": _candidates(names),
    }


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=30))


def test_parallel_happy_path_restores_base():
    controller = FakeController(NAMES)
    checker = FakeChecker()
    labels, failures = {}, []
    handled = _run(occ.run_parallel_check(
        controller, checker, _full(NAMES), None, _candidates(NAMES), labels, failures
    ))
    assert handled is True
    assert len(controller.reloads) == 2, "inject once, restore once"
    assert "listeners" in controller.reloads[0]
    assert "listeners" not in controller.reloads[-1]
    assert len(labels) == 13 and not failures
    assert all(v != occ.FAIL_LABEL for v in labels.values())
    assert len(checker.names_seen) == 13, "each node gets its own mixed port"
    assert sorted(controller.delay_calls) == sorted(NAMES), "batch latency test covers every node"
    # Reload reset the selector -> snapshot/replay must restore the user's pick.
    assert ("Proxies", "美国01") in controller.switch_calls, controller.switch_calls


def test_parallel_reload_failure_falls_back():
    controller = FakeController(["a", "b"], reload_ok=False)
    labels, failures = {}, []
    handled = _run(occ.run_parallel_check(
        controller, FakeChecker(), _full(["a", "b"]), None, _candidates(["a", "b"]), labels, failures
    ))
    assert handled is False and not labels and not failures


def test_parallel_name_mismatch_falls_back():
    controller = FakeController(["other"])
    labels, failures = {}, []
    handled = _run(occ.run_parallel_check(
        controller, FakeChecker(), _full(["a"]), None, _candidates(["a"]), labels, failures
    ))
    assert handled is False and not labels


def test_parallel_fragment_base_falls_back():
    controller = FakeController(["a"])
    labels, failures = {}, []
    fragment = {"proxies": [{"name": "a", "type": "ss"}]}  # not a full config
    handled = _run(occ.run_parallel_check(
        controller, FakeChecker(), fragment, None, _candidates(["a"]), labels, failures
    ))
    assert handled is False


def test_parallel_single_node_error_does_not_kill_batch():
    names = ["node00", "node01", "node02"]
    controller = FakeController(names)
    checker = FakeChecker(raise_names={"node01"})
    labels, failures = {}, []
    handled = _run(occ.run_parallel_check(
        controller, checker, _full(names), None, _candidates(names), labels, failures
    ))
    assert handled is True
    assert labels["node00"] != occ.FAIL_LABEL and labels["node02"] != occ.FAIL_LABEL
    assert labels["node01"] == occ.FAIL_LABEL
    assert len(failures) == 1 and "node01" in failures[0]


def test_status_nodes_skipped_chinese_and_english():
    # English status nodes (gw树洞 style) must be skipped like Chinese ones.
    assert occ.is_status_node("Expire: 2026-10-19")
    assert occ.is_status_node("Traffic: 2.38GB | 200GB")
    assert occ.is_status_node("Sync: 2026-09-18 16:00:03")
    assert occ.is_status_node("剩余流量：150GB")
    assert occ.is_status_node("套餐到期：2026-10-01")
    assert not occ.is_status_node("🇰🇷 Pro-韩国-01|v202605")
    assert not occ.is_status_node("🇺🇸 美国-BGP-03")
    assert not occ.is_status_node("🇹🇼 台湾家宽01")


def main() -> int:
    tests = [
        test_parallel_happy_path_restores_base,
        test_parallel_reload_failure_falls_back,
        test_parallel_name_mismatch_falls_back,
        test_parallel_fragment_base_falls_back,
        test_parallel_single_node_error_does_not_kill_batch,
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

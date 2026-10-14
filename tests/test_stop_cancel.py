"""Offline tests: stop cancels in-flight parallel checks, restore still runs."""
from __future__ import annotations

import asyncio
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import routers.api as api  # noqa: E402


NAMES = ["hk-01", "jp-02"]
CONFIG = {
    "parallel_check": True,
    "history_enabled": False,
    "enable_multi_source": False,
    "dnsbl_enabled": False,
    "dns_leak_enabled": False,
}


def _proxy_list(names=NAMES):
    return [{"name": n, "type": "ss", "server": "example.com"} for n in names]


def _full_config(names=NAMES):
    return {
        "mixed-port": 7897,
        "external-controller": "127.0.0.1:9097",
        "proxies": _proxy_list(names),
    }


def _pending_nodes(proxies):
    return [
        {"id": i, "name": p["name"], "status": "pending", "proxy_config": p}
        for i, p in enumerate(proxies)
    ]


class HangingChecker:
    """check_fast never returns on its own; counts starts and cancellations."""

    def __init__(self):
        self.started = 0
        self.cancelled = 0
        self.completed = 0

    async def check_fast(self, proxy=None, **kwargs):
        self.started += 1
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self.completed += 1
        return {"ip": "1.2.3.4", "source": "ping0"}

    def clear_cache(self):
        pass


class QuickChecker(HangingChecker):
    async def check_fast(self, proxy=None, **kwargs):
        self.started += 1
        await asyncio.sleep(0.01)
        self.completed += 1
        return {"ip": "1.2.3.4", "source": "ping0"}


class FakeController:
    def __init__(self, names=NAMES):
        self.names = list(names)
        self.reloads = []

    async def get_proxies(self):
        return {n: {"type": "ss", "now": "", "all": []} for n in self.names}

    async def reload_config(self, cfg):
        self.reloads.append(cfg)
        return True

    async def get_delay(self, name, timeout_ms=5000, test_url=None):
        return 100


class SerialController:
    def __init__(self):
        self.modes = []
        self.switches = []

    async def get_configs(self):
        return {"mode": "rule"}

    async def get_proxies(self):
        return {
            "GLOBAL": {"type": "Selector", "now": "grp", "all": ["grp"]},
            "grp": {"type": "selector", "now": "hk-01", "all": list(NAMES)},
        }

    async def set_mode(self, mode):
        self.modes.append(mode)
        return True

    async def switch_proxy(self, group, name):
        self.switches.append((group, name))
        return True

    async def get_running_port(self):
        return 19090


def _fake_parallel_state(checker):
    proxies = _proxy_list()
    state = types.SimpleNamespace(
        checker=checker,
        task_id="test-task",
        is_running=True,
        nodes=_pending_nodes(proxies),
        original_yaml=_full_config(),
        progress=0,
        total=len(proxies),
        current_node="",
        events=[],
    )
    return state, proxies


async def _run_parallel(state, proxies, controller):
    api._load_verge_runtime_config = lambda: None
    api.find_free_ports = lambda n: [40000 + k for k in range(n)]
    return await api._run_check_parallel(
        proxies, dict(CONFIG), state, controller, "ping0", True, True
    )


def test_stop_cancels_inflight_and_restores():
    async def scenario():
        checker = HangingChecker()
        state, proxies = _fake_parallel_state(checker)
        controller = FakeController()
        task = asyncio.ensure_future(_run_parallel(state, proxies, controller))
        for _ in range(200):
            if checker.started >= 2:
                break
            await asyncio.sleep(0.01)
        assert checker.started == 2, "both batch checks should be in flight"

        state.is_running = False  # what POST /api/stop does
        handled = await asyncio.wait_for(task, timeout=10)

        assert handled is True
        assert checker.cancelled == 2, "in-flight checks must be cancelled"
        assert checker.completed == 0
        assert len(controller.reloads) == 2, "inject once, restore once"
        assert "listeners" in controller.reloads[0]
        assert controller.reloads[-1] is state.original_yaml
        assert all(node["status"] == "pending" for node in state.nodes), \
            "cancelled nodes keep the pending row, no fabricated results"
        assert any(e["type"] == "complete" for e in state.events)

    asyncio.run(asyncio.wait_for(scenario(), timeout=30))


def test_no_stop_completes_and_restores_once():
    async def scenario():
        checker = QuickChecker()
        state, proxies = _fake_parallel_state(checker)
        controller = FakeController()
        handled = await asyncio.wait_for(
            _run_parallel(state, proxies, controller), timeout=30
        )
        assert handled is True
        assert checker.completed == 2
        assert checker.cancelled == 0
        assert len(controller.reloads) == 2
        assert controller.reloads[-1] is state.original_yaml
        assert state.nodes[0]["ip"] == "1.2.3.4"
        assert state.nodes[0]["status"] == "✅"
        assert state.events[-1]["type"] == "complete"

    asyncio.run(asyncio.wait_for(scenario(), timeout=60))


def test_serial_stops_before_next_node():
    async def scenario():
        checker = HangingChecker()

        async def stop_during_first(proxy=None, **kwargs):
            checker.started += 1
            api.state.is_running = False  # user pressed stop during node 1
            return {"ip": "1.2.3.4", "source": "ping0"}

        checker.check_fast = stop_during_first
        controllers = []
        saved_checker = api.state.checker
        saved_controller = api.ClashController
        api.state.checker = checker
        api.state.is_running = True
        api.state.total = 2
        api.state.progress = 0
        api.state.nodes = _pending_nodes(_proxy_list())
        api.state.events = []
        api.ClashController = lambda url, secret: controllers.append(
            SerialController()
        ) or controllers[-1]
        try:
            await asyncio.wait_for(
                api._run_check(_proxy_list(), {"history_enabled": False}),
                timeout=30,
            )
        finally:
            api.state.checker = saved_checker
            api.ClashController = saved_controller

        assert checker.started == 1, "node 2 must never be checked"
        controller = controllers[0]
        assert ("grp", "hk-01") in controller.switches
        assert ("grp", "jp-02") not in controller.switches, \
            "serial path stops before the next node"
        assert api.state.nodes[1]["status"] == "pending"
        assert controller.modes[-1] == "rule", "original mode restored"
        assert any(e["type"] == "complete" for e in api.state.events)

    asyncio.run(asyncio.wait_for(scenario(), timeout=60))


def main() -> int:
    tests = [
        test_stop_cancels_inflight_and_restores,
        test_no_stop_completes_and_restores_once,
        test_serial_stops_before_next_node,
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

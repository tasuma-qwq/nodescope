"""Synthetic controller/checker for workflow tests and the explicit UI demo."""
import asyncio
import copy

DEMO_YAML = """proxies:
  - name: Demo-A
    type: ss
    server: 192.0.2.1
    port: 443
    cipher: aes-128-gcm
    password: demo-only-not-a-real-proxy
  - name: Demo-B
    type: ss
    server: 192.0.2.2
    port: 443
    cipher: aes-128-gcm
    password: demo-only-not-a-real-proxy
proxy-groups:
  - name: Demo
    type: select
    proxies: [Demo-A, Demo-B, DIRECT]
"""


class DemoController:
    def __init__(self, *args):
        self.mode = "rule"
        self.selections = {"GLOBAL": "Demo", "Demo": "Demo-B"}

    async def get_configs(self):
        return {"mode": self.mode, "mixed-port": 17890}

    async def get_proxies(self):
        return {"GLOBAL": {"type": "Selector", "now": self.selections["GLOBAL"], "all": ["Demo"]},
                "Demo": {"type": "Selector", "now": self.selections["Demo"], "all": ["Demo-A", "Demo-B", "DIRECT"]},
                "Demo-A": {"type": "ss"}, "Demo-B": {"type": "ss"}}

    async def set_mode(self, mode):
        self.mode = mode
        return True

    async def switch_proxy(self, group, name):
        self.selections[group] = name
        return True

    async def get_running_port(self):
        return 17890

    async def get_delay(self, name, **kwargs):
        return 95 if name == "Demo-A" else 215


class DemoChecker:
    headless = True

    async def check_fast(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        return {"ip": "192.0.2.42", "source": "ping0", "pure_score": "8%",
                "ip_attr": "演示住宅", "ip_src": "演示原生", "shared_users": "10-50",
                "geo": "DEMO", "isp": "Synthetic data", "asn": "AS0",
                "unlock": {"claude": {"status": "unknown"}}, "unlock_summary": "C❔"}

    async def check_browser(self, *args, **kwargs):
        return await self.check_fast()

    def clear_cache(self):
        pass

    async def stop(self):
        pass

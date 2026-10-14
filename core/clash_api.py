import io
import urllib.parse

import aiohttp
from ruamel.yaml import YAML


def config_to_payload(cfg: dict):
    """Dump a Clash config dict to a YAML string for PUT /configs payload. Never raises."""
    try:
        if not isinstance(cfg, dict) or not cfg:
            return None
        yaml = YAML()
        yaml.preserve_quotes = True
        stream = io.StringIO()
        yaml.dump(cfg, stream)
        payload = stream.getvalue()
        return payload if payload and payload.strip() else None
    except Exception:
        return None

class ClashController:
    def __init__(self, api_url, secret=""):
        self.api_url = api_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json"
        }

    async def switch_proxy(self, selector, proxy_name):
        """Switches the selector to the specified proxy."""
        url = f"{self.api_url}/proxies/{urllib.parse.quote(selector)}"
        payload = {"name": proxy_name}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, json=payload, headers=self.headers, timeout=5) as resp:
                    if resp.status == 204:
                        return True
                    else:
                        print(f"Failed to switch to {proxy_name}. Status: {resp.status}")
                        return False
        except Exception as e:
            print(f"API Error switching to {proxy_name}: {e}")
            return False

    async def set_mode(self, mode):
        """Sets the Clash mode (global, rule, direct)."""
        url = f"{self.api_url}/configs"
        payload = {"mode": mode}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=self.headers, timeout=5) as resp:
                    if resp.status == 204:
                        print(f"Successfully set mode to: {mode}")
                        return True
                    else:
                        print(f"Failed to set mode logic. Status: {resp.status}")
                        return False
        except Exception as e:
            print(f"API Error setting mode: {e}")
            return False

    async def get_running_port(self):
        """Fetches the mixed-port or http-port from running instance."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/configs", headers=self.headers) as resp:
                    if resp.status == 200:
                        conf = await resp.json()
                        if conf.get('mixed-port', 0) != 0: return conf['mixed-port']
                        if conf.get('port', 0) != 0: return conf['port']
                        if conf.get('socks-port', 0) != 0: return conf['socks-port']
        except Exception:
            pass
        return 7897 # Default fallback
    
    async def get_delay(self, proxy_name, timeout_ms=5000, test_url="http://www.gstatic.com/generate_204"):
        """Latency test via GET /proxies/{name}/delay. Returns ms int, None on failure."""
        url = (
            f"{self.api_url}/proxies/{urllib.parse.quote(str(proxy_name))}/delay"
            f"?timeout={int(timeout_ms)}&url={urllib.parse.quote(test_url)}"
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self.headers, timeout=timeout_ms / 1000 + 3
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        delay = data.get("delay")
                        if isinstance(delay, (int, float)):
                            return int(delay)
                    return None
        except Exception:
            return None

    async def get_proxies(self):
        """Fetches all proxies."""
        try:
             async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/proxies", headers=self.headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('proxies', {})
        except Exception as e:
            print(f"Error fetching proxies: {e}")
        return None

    async def get_configs(self):
        """Returns the active Mihomo config for reversible test runs."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/configs", headers=self.headers, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            print(f"Error fetching configs: {e}")
        return None

    async def reload_config(self, cfg: dict) -> bool:
        """Replace the running config via PUT /configs?force=true. Never raises.

        Mihomo expects {"path": "..."} or {"payload": "<yaml>"}, not the
        config object itself (GET /configs fields are a general summary).
        """
        try:
            payload = config_to_payload(cfg)
            if not payload:
                return False
            url = f"{self.api_url}/configs?force=true"
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, json={"payload": payload}, headers=self.headers, timeout=30
                ) as resp:
                    if resp.status in (200, 204):
                        return True
                    print(f"Failed to reload config. Status: {resp.status}")
                    return False
        except Exception as e:
            print(f"API Error reloading config: {e}")
            return False

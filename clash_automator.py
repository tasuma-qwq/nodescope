import asyncio
import yaml
import os
import sys
from typing import Dict, Any, List

# Import Utils
from utils.config_loader import load_config
from core.ip_checker import IPChecker
from core.clash_api import ClashController
from core.parallel import snapshot_selections, reapply_selections
from core.labels import FAIL_LABEL, format_data_label, strip_existing_label

# --- CONFIGURATION ---
cfg = load_config("config.yaml") or {}

CLASH_CONFIG_PATH = cfg.get('yaml_path', r"YOUR_CLASH_CONFIG_PATH_HERE")
CLASH_API_URL = cfg.get('clash_api_url', "http://127.0.0.1:9097")
CLASH_API_SECRET = cfg.get('clash_api_secret', "")
SELECTOR_NAME = cfg.get('selector_name', "GLOBAL")
OUTPUT_SUFFIX = cfg.get('output_suffix', "_checked")
FAST_MODE = cfg.get('fast_mode', True) 
SKIP_KEYWORDS = cfg.get('skip_keywords', ["剩余", "重置", "到期", "有效期", "官网", "网址", "更新", "公告"])
HEADLESS = cfg.get('headless', True)
SOURCE = cfg.get('source', 'ping0')
FALLBACK = cfg.get('fallback', True)

async def test_single_proxy(controller: ClashController, checker: IPChecker, proxy_name: str, selector: str, local_proxy: str, 
                          fast_mode: bool = FAST_MODE, source: str = SOURCE, fallback: bool = FALLBACK) -> Dict[str, Any]:
    """
    Tests a single proxy: switches to it, waits, and checks IP.
    Returns the result dictionary (or error dict).
    """
    print(f"\nTesting: {proxy_name}")
    
    # ... switch logic same ...
    
    # 1. Switch Node
    print(f"  -> Switching {selector} ...")
    switched = await controller.switch_proxy(selector, proxy_name)
    if not switched:
        print("  -> Switch failed, skipping IP check.")
        return FAIL_LABEL

    # 2. Wait for switch to take effect
    await asyncio.sleep(1) 

    # 3. Check IP
    print(f"  -> Running IP Check ({'Fast Mode' if fast_mode else 'Browser Mode'})...")
    res = None
    
    if fast_mode:
        res = await checker.check_fast(proxy=local_proxy, source=source, fallback=fallback)
    else:
        # Browser Mode
        try:
            res = await checker.check_browser(proxy=local_proxy)
        except Exception as e:
            print(f"     Check error: {e}")
    
    if not res:
            res = {"full_string": "【❌ Error】", "ip": "Error", "pure_score": "?", "bot_score": "?"}

    full_str = res.get('full_string', 'N/A')
    ip_addr = res.get('ip', 'Unknown')
    p_score = res.get('pure_score', 'N/A')
    b_score = res.get('bot_score', 'N/A')
    s_users = res.get('shared_users', 'N/A')

    print(f"  -> Result: {full_str}")

    details_str = f"  -> Details: IP: {ip_addr} | 污染度: {p_score}"
    if b_score != 'N/A':
        details_str += f" | Bot流量比: {b_score}"
    if s_users != 'N/A':
        details_str += f" | 共享人数: {s_users}"
    print(details_str)

    # Numeric label convention (same as Web/one-click): 【8% 住宅|原生 综合12】
    if res.get("ip") in (None, "", "❓", "Error"):
        return FAIL_LABEL
    return format_data_label(res)

def save_config_results(original_config: dict, results_map: Dict[str, str], output_path: str):
    """
    Appends numeric labels to proxy names (every original node is kept) and saves.
    """
    print("\nUpdating config names...")
    new_proxies = []
    name_mapping = {} # Old -> New

    proxies = original_config.get('proxies', [])
    for proxy in proxies:
        old_name = proxy['name']
        if old_name in results_map:
            base = strip_existing_label(old_name) or old_name
            new_name = f"{base} {results_map[old_name]}"
            proxy['name'] = new_name
            name_mapping[old_name] = new_name
        new_proxies.append(proxy)
    
    original_config['proxies'] = new_proxies

    # Update groups
    if 'proxy-groups' in original_config:
        for group in original_config['proxy-groups']:
            if 'proxies' in group:
                new_group_proxies = []
                for p_name in group['proxies']:
                    if p_name in name_mapping:
                        new_group_proxies.append(name_mapping[p_name])
                    else:
                        new_group_proxies.append(p_name)
                group['proxies'] = new_group_proxies
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(original_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"\nSuccess! Saved updated config to: {output_path}")
    except Exception as e:
        print(f"Error saving config: {e}")

async def main():
    print(f"Loading config from: {CLASH_CONFIG_PATH}")
    if not os.path.exists(CLASH_CONFIG_PATH):
        print(f"Error: Config file not found at {CLASH_CONFIG_PATH}")
        return

    try:
        with open(CLASH_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config_data = yaml.full_load(f)
    except Exception as e:
        print(f"Error parsing YAML: {e}")
        return

    proxies = config_data.get('proxies', [])
    if not proxies:
        print("No 'proxies' found in config.")
        return

    print(f"Found {len(proxies)} proxies to test.")
    
    controller = ClashController(CLASH_API_URL, CLASH_API_SECRET)

    # Snapshot routing state so the run is reversible (mode + GLOBAL selection).
    original_mode = None
    original_global = None
    original_selections = {}
    try:
        configs = await controller.get_configs()
        proxies_state = await controller.get_proxies()
        original_mode = configs.get("mode") if configs else None
        global_state = proxies_state.get("GLOBAL") if proxies_state else None
        original_global = global_state.get("now") if global_state else None
        original_selections = snapshot_selections(proxies_state)
    except Exception:
        pass

    # FORCE GLOBAL MODE
    await controller.set_mode("global")
    
    # DETECT PORT
    mixed_port = await controller.get_running_port()
    print(f"Detected Running Port from API: {mixed_port}")

    local_proxy_url = f"http://127.0.0.1:{mixed_port}"
    print(f"Using Local Proxy: {local_proxy_url}")
    
    selector_to_use = SELECTOR_NAME
    # (Optional) Verify selector existence logic could go here, omitting for brevity/fidelity to original flow for now

    checker = IPChecker(headless=HEADLESS)
    await checker.start()

    results_map = {} # name -> result_string

    try:
        for i, proxy in enumerate(proxies):
            name = proxy['name']

            # Check Skip logic
            should_skip = False
            for kw in SKIP_KEYWORDS:
                if kw in name:
                    should_skip = True
                    break

            if should_skip:
                print(f"\n[{i+1}/{len(proxies)}] Skipping (Status Node): {name}")
                continue

            print(f"[{i+1}/{len(proxies)}] Progress...", end="")

            # CALL TEST FUNCTION
            res = await test_single_proxy(controller, checker, name, selector_to_use, local_proxy_url)
            results_map[name] = res

    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Saving current progress...")
    finally:
        await checker.stop()
        # Restore the user's pre-check routing state.
        try:
            await reapply_selections(controller, original_selections)
            if original_mode:
                await controller.set_mode(original_mode)
        except Exception as restore_error:
            print(f"Restore routing failed: {restore_error}")

    # SAVE RESULTS
    base = os.path.basename(CLASH_CONFIG_PATH)
    filename, ext = os.path.splitext(base)
    output_filename = f"{filename}{OUTPUT_SUFFIX}{ext}"
    output_path = os.path.join(os.getcwd(), output_filename)
    
    save_config_results(config_data, results_map, output_path)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())

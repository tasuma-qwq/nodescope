from .base import BaseCheckSource
from curl_cffi.requests import AsyncSession
import re
from typing import Dict, Optional

class Ping0Source(BaseCheckSource):


    def get_shared_emoji(self, shared_str):
        if not shared_str or shared_str == "N/A":
            return "❓"
        try:
            nums = re.findall(r'\d+', shared_str)
            if not nums: return "❓"
            upper = int(nums[-1]) if len(nums) > 1 else int(nums[0])
            if "+" in shared_str: upper += 1
            if upper <= 10: return "🟢"
            if upper <= 100: return "🟡"
            if upper <= 1000: return "🟠"
            if upper <= 10000: return "🔴"
            return "⚫"
        except Exception:
            return "❓"

    async def check(self, proxy: Optional[str] = None) -> Optional[Dict]:
        url = "https://ping0.cc/"
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        try:
            async with AsyncSession(proxies=proxies, impersonate="chrome124", timeout=5) as session:
                resp = await session.get(url)
                
                if resp.status_code != 200:
                    return None
                
                html = resp.text
                
                # Cloudflare detection
                if "<title>Just a moment...</title>" in html or "challenge-platform" in html or "cf-turnstile" in html:
                    print("     [Ping0] Cloudflare blocked, falling back to ippure")
                    return None
                
                result = {
                    "ip": "❓", "ip_attr": "❓", "ip_src": "❓",
                    "pure_score": "❓", "shared_users": "N/A",
                    "pure_emoji": "❓", "shared_emoji": "❓",
                    "full_string": "", "error": None, "source": "ping0"
                }
                
                # 1. IP
                ip_match = re.search(r"window\.ip\s*=\s*'([^']+)'", html)
                if not ip_match:
                    ip_match = re.search(r'href="[^"]*?/ping/([0-9.]+)"', html)
                if ip_match:
                    result["ip"] = ip_match.group(1).strip()
                
                # 2. Type
                type_match = re.search(r'<div class="line line-iptype">.*?<span class="label[^>]*>(.*?)</span>', html, re.DOTALL)
                if type_match:
                    raw_type = type_match.group(1).strip()
                    if "机房" in raw_type or "IDC" in raw_type: result["ip_attr"] = "机房"
                    elif "家庭" in raw_type or "住宅" in raw_type: result["ip_attr"] = "住宅"
                    else: result["ip_attr"] = raw_type
                
                # 3. Score
                score_match = re.search(r'class="riskitem riskcurrent"[^>]*><span class="value">(\d+)%</span>', html)
                if score_match:
                    result["pure_score"] = f"{score_match.group(1)}%"
                    result["pure_emoji"] = self.get_emoji(result["pure_score"])
                
                # 4. Native
                native_match = re.search(r'<div class="line line-nativeip">.*?<span class="label[^>]*>(.*?)</span>', html, re.DOTALL)
                if native_match:
                    raw_native = native_match.group(1).strip()
                    if "广播" in raw_native: result["ip_src"] = "广播"
                    elif "原生" in raw_native: result["ip_src"] = "原生"
                    else: result["ip_src"] = raw_native
                
                # 5. Shared
                shared_match = re.search(r'usecount="([^"]+)"', html)
                if not shared_match:
                    shared_match = re.search(r'class="usecountbar"[^>]*>\s*(.*?)\s*</div>', html, re.DOTALL)
                if shared_match:
                    result["shared_users"] = shared_match.group(1).strip()
                    result["shared_emoji"] = self.get_shared_emoji(result["shared_users"])
                
                # Finish
                attr = result["ip_attr"] if result["ip_attr"] != "❓" else ""
                src = result["ip_src"] if result["ip_src"] != "❓" else ""
                info = f"{attr}|{src}".strip()
                if info == "|" or not info: info = "未知"
                
                result["full_string"] = f"【{result['pure_emoji']}{result['shared_emoji']} {info}】"
                
                return result
                
        except Exception as e:
            print(f"     [Ping0] Error: {e}")
            return None

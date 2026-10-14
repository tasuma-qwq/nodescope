from .base import BaseCheckSource
from curl_cffi.requests import Session
import asyncio
from typing import Dict, Optional

class IPPureSource(BaseCheckSource):


    def _check_sync(self, proxy: Optional[str] = None):
        url = "https://my.ippure.com/v1/info"
        result = {
            "pure_emoji": "❓", "shared_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
            "pure_score": "❓", "shared_users": "N/A", "full_string": "", "ip": "❓", 
            "error": None, "source": "ippure"
        }
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            with Session(proxies=proxies, impersonate="chrome110", timeout=5) as session:
                resp = session.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    result["ip"] = data.get("ip", "❓")
                    
                    f_score = data.get("fraudScore")
                    if f_score is not None:
                        result["pure_score"] = f"{f_score}%"
                        result["pure_emoji"] = self.get_emoji(result["pure_score"])
                    
                    is_resi = data.get("isResidential", False)
                    result["ip_attr"] = "住宅" if is_resi else "机房"
                    
                    is_broad = data.get("isBroadcast", False)
                    result["ip_src"] = "广播" if is_broad else "原生"
                    
                    result["shared_emoji"] = ""
                    
                    attr = result["ip_attr"] if result["ip_attr"] != "❓" else ""
                    src = result["ip_src"] if result["ip_src"] != "❓" else ""
                    info = f"{attr}|{src}".strip()
                    if info == "|" or not info: info = "未知"
                    result["full_string"] = f"【{result['pure_emoji']} {info}】"
                else:
                    result["error"] = f"API Error {resp.status_code}"
                    result["full_string"] = "【❌ API Error】"
        except Exception as e:
            print(f"     [ippure] curl_cffi error: {e}")
            result["error"] = str(e)
            result["full_string"] = "【❌ Error】"
        return result

    async def check(self, proxy: Optional[str] = None) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._check_sync, proxy)

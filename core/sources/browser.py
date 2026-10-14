from .base import BaseCheckSource
from playwright.async_api import async_playwright
import re
import asyncio
from typing import Dict, Optional

class BrowserSource(BaseCheckSource):
    def __init__(self, headless=True):
        self.headless = headless
        self.playwright = None
        self.browser = None

    async def start(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )

    async def stop(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None



    async def check(self, proxy: Optional[str] = None) -> Dict:
        if not self.browser:
            await self.start()
            
        context_args = {
             "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if proxy:
            # Playwright proxy format: { "server": "http://127.0.0.1:7890" }
            # Incoming proxy arg is likely "http://127.0.0.1:7890"
            context_args["proxy"] = {"server": proxy}
            
        context = await self.browser.new_context(**context_args)
        
        # Resource blocking
        await context.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "media", "font"] 
            else route.continue_())

        page = await context.new_page()
        
        result = {
            "pure_emoji": "❓", "bot_emoji": "❓", "ip_attr": "❓", "ip_src": "❓",
            "pure_score": "❓", "bot_score": "❓", "full_string": "", "ip": "❓", "error": None, "source": "ippure"
        }

        try:
            await page.goto("https://ippure.com/", wait_until="domcontentloaded", timeout=20000)
            try:
                await page.wait_for_selector("text=人机流量比", timeout=10000)
            except: pass 
            
            await page.wait_for_timeout(2000)
            text = await page.inner_text("body")

            # 1. IPPure Score
            score_match = re.search(r"IPPure系数.*?(\d+%)", text, re.DOTALL)
            if score_match:
                result["pure_score"] = score_match.group(1)
                result["pure_emoji"] = self.get_emoji(result["pure_score"])

            # 2. Bot Ratio
            bot_match = re.search(r"bot\s*(\d+(\.\d+)?)%", text, re.IGNORECASE)
            if bot_match:
                val = bot_match.group(0).replace('bot', '').strip()
                if not val.endswith('%'): val += "%"
                result["bot_score"] = val
                result["bot_emoji"] = self.get_emoji(val)

            # 3. Attributes
            attr_match = re.search(r"IP属性\s*\n\s*(.+)", text)
            if not attr_match: attr_match = re.search(r"IP属性\s*(.+)", text)
            if attr_match:
                raw = attr_match.group(1).strip()
                result["ip_attr"] = re.sub(r"IP$", "", raw)

            # 4. Source
            src_match = re.search(r"IP来源\s*\n\s*(.+)", text)
            if not src_match: src_match = re.search(r"IP来源\s*(.+)", text)
            if src_match:
                raw = src_match.group(1).strip()
                result["ip_src"] = re.sub(r"IP$", "", raw)

            # 5. Fallback IP
            if result["ip"] == "❓":
                ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
                if ip_match: result["ip"] = ip_match.group(0)

            # String
            attr = result["ip_attr"] if result["ip_attr"] != "❓" else ""
            src = result["ip_src"] if result["ip_src"] != "❓" else ""
            info = f"{attr}|{src}".strip()
            if info == "|" or not info: info = "未知"
            
            result["full_string"] = f"【{result['pure_emoji']}{result['bot_emoji']} {info}】"

        except Exception as e:
            result["error"] = str(e)
            result["full_string"] = "【❌ Error】"
        finally:
            if not self.headless:
                print("     [Debug] Waiting 5s before closing browser window...")
                await asyncio.sleep(5)
            await page.close()
            await context.close()
            
        return result

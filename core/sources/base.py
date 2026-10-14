import abc
from typing import Dict, Optional

class BaseCheckSource(abc.ABC):
    def get_emoji(self, percentage_str):
        try:
            val = float(percentage_str.replace('%', ''))
            # Logic from ipcheck.py with user approved thresholds
            if val <= 10: return "⚪"
            if val <= 30: return "🟢"
            if val <= 50: return "🟡"
            if val <= 70: return "🟠"
            if val <= 90: return "🔴"
            return "⚫"
        except Exception:
            return "❓"

    @abc.abstractmethod
    async def check(self, proxy: Optional[str] = None) -> Dict:
        """
        Execute check logic.
        Returns a result dictionary.
        """
        pass

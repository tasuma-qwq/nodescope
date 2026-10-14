from typing import Dict, List, Optional
from core.ip_checker import IPChecker
import asyncio

class AppState:
    def __init__(self):
        self.checker = IPChecker(headless=True)
        self.task_id: Optional[str] = None
        self.is_running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.is_rechecking: bool = False
        self.nodes: List[Dict] = []
        self.original_yaml: Dict = {}
        self.progress: int = 0
        self.total: int = 0
        self.current_node: str = ""
        self.events: List[Dict] = []

# Global instance
state = AppState()

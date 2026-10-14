"""Same-origin boundary for the standalone subscription servers."""
from http.server import BaseHTTPRequestHandler
from core.local_access import is_local_request


class LocalSubscriptionHandler(BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request():
            return False
        if not is_local_request(self.headers):
            self.send_error(403, "Local same-origin access required")
            return False
        return True

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

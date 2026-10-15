"""Protect the unauthenticated loopback UI against cross-site requests."""
from urllib.parse import urlsplit

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_local_request(headers, scheme="http"):
    """Shared by FastAPI and the CLI subscription HTTP servers."""
    headers = {key.lower(): value for key, value in headers.items()}
    try:
        host = urlsplit("http://" + headers.get("host", ""))
        if (host.hostname not in LOCAL_HOSTS or host.username or host.password
                or host.path or host.query or host.fragment):
            return False
        host_port = host.port or 80
        origin = headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if (parsed.scheme != scheme or parsed.hostname != host.hostname
                    or origin_port != host_port or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment):
                return False
        return headers.get("sec-fetch-site", "") in ("", "none", "same-origin")
    except ValueError:
        return False


class LocalAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin1").lower(): value.decode("latin1")
                   for key, value in scope.get("headers", [])}
        if not is_local_request(headers, scope.get("scheme", "http")):
            from starlette.responses import JSONResponse
            response = JSONResponse({"detail": "NodeScope 仅允许本地同源访问"}, status_code=403)
            await response(scope, receive, send)
            return

        async def protected_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(message)

        await self.app(scope, receive, protected_send)

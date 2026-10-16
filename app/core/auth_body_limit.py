"""Transport-level byte limit for unauthenticated authentication JSON bodies.

Reject before FastAPI or Pydantic accumulates or parses the request. The ASGI
receive stream is replayed unchanged after buffering at most AUTH_BODY_LIMIT
bytes, including for requests without Content-Length (e.g. chunked uploads).
"""
from collections import deque

from starlette.responses import JSONResponse

AUTH_BODY_LIMIT = 4096
AUTH_ENDPOINTS = frozenset(("/api/auth/login", "/api/auth/setup"))


class AuthenticationBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or scope.get("path") not in AUTH_ENDPOINTS):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(
                    scope, receive, send)
                return
            if declared < 0 or declared > AUTH_BODY_LIMIT:
                await self._too_large(scope, receive, send)
                return

        buffered = deque()
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                buffered.append(message)
                continue
            size += len(message.get("body", b""))
            if size > AUTH_BODY_LIMIT:
                await self._too_large(scope, receive, send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if buffered:
                return buffered.popleft()
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _too_large(scope, receive, send):
        response = JSONResponse({"detail": "Authentication JSON body exceeds 4 KiB."},
                                status_code=413, headers={"Connection": "close"})
        await response(scope, receive, send)

"""Reject oversized request bodies before they are parsed or spooled to disk (SEC-04).

Starlette parses a multipart upload, and writes it to a temporary file, before the route handler
runs, so a size check in the handler comes too late. This ASGI middleware refuses a request whose
declared Content-Length is over the limit, and stops reading a streamed (chunked) body as soon as
it passes the limit: it answers 413 itself and tells the app the client disconnected. Nothing is
raised across the app, because BaseHTTPMiddleware would wrap it into a generic error.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await _reject(send, 400, "Invalid Content-Length")
                    return
                if declared > self.max_bytes:
                    await _reject(send, 413, self._detail())
                    return
        received = 0
        started = rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    if not started:
                        await _reject(send, 413, self._detail())
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # we already answered 413; drop whatever the app tries to send
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    def _detail(self) -> str:
        return f"Request body exceeds {self.max_bytes // (1024 * 1024)} MB"


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})

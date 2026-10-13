"""Request body size limit for the live FastAPI app (installed in core/main.py, docs/specs/auth.md "Request body limit").

Every request body is capped at `settings.max_request_body_bytes` (default 1 MB, `MAX_REQUEST_BODY_BYTES`, 0 = off). The largest legitimate body
today is a saved view's filters (bounded to 20 KB by the schema); a bulk add of 200 tickers is about 3 KB and the export-ids request is a GET query.

* A declared `Content-Length` above the limit is refused with 413 before the app reads a byte.
* A body with no (or a false) `Content-Length` (chunked, or a lying client) is counted as it arrives; the chunk that crosses the limit makes the
  middleware answer 413 and the app sees a disconnect. FastAPI turns any exception raised from `receive` into a 400, so the 413 is sent here
  instead of raised.

The answer is generic (`{"detail": "Request body too large."}`), never the size or the limit. The limit is read on every request, like the
Host / Origin guard. It sits inside that guard (a forged cross-site POST is still a 403, a bad Host a 400) and in front of the login dependency,
so an unauthenticated caller cannot make the server buffer more than the limit. Cron jobs and scripts never go through the app.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import settings

TOO_LARGE_DETAIL = "Request body too large."


async def _reject(send: Send) -> None:
    body = json.dumps({"detail": TOO_LARGE_DETAIL}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = settings.max_request_body_bytes
        if scope["type"] != "http" or limit <= 0:
            await self.app(scope, receive, send)
            return

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break  # the server rejects a malformed length itself
                if declared > limit:
                    await _reject(send)
                    return
                break

        received = 0
        refused = False
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit and not response_started:
                    refused = True
                    await _reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if refused:
                return  # the 413 is already out; whatever the app says next is dropped
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not refused:
                raise
            # The app read the "disconnect" we fed it after the 413 and failed on it (a raw Request.body() raises ClientDisconnect);
            # the answer is out, so the error is dropped instead of reaching the server's 500 handler.

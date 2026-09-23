"""A scripted local HTTP model endpoint (KIT_SPEC 11.2). Owner: B4.

    with HttpStub([{"status": 429, "headers": {"Retry-After": "1"}}, {"text": "hello"}]) as hs:
        url = hs.url("/v1/chat/completions")
        ...
        hs.requests   # [{"path", "method", "header_names", "has_auth", "body"}]

A ThreadingHTTPServer on 127.0.0.1:0 serves POST /v1/chat/completions (OpenAI chat shape) and /v1/messages
(Anthropic shape); any path ending in one of those works too (e.g. /api/paas/v4/chat/completions). Each request
consumes the next scripted response; when the script is exhausted the default response (200 with `default_text`) is
served. A scripted item is {"status": int, "headers": {...}, "text": str, "body": obj|str, "delay_s": float}.
Authorization / x-api-key values are never recorded, only whether they were present.
"""

import json
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover - Python < 3.7
    raise


def openai_body(text):
    return {"id": "chatcmpl-stub", "object": "chat.completion", "model": "stub",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}


def anthropic_body(text):
    return {"id": "msg_stub", "type": "message", "role": "assistant", "model": "stub",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20}}


class HttpStub(object):
    def __init__(self, script=None, default_text="PONG"):
        self.script = list(script or [])
        self.default_text = default_text
        self.requests = []
        self._lock = threading.Lock()
        self.server = None
        self.thread = None

    def __enter__(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence the default stderr access log
                pass

            def do_POST(self):  # noqa: N802 (stdlib naming)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                names = sorted(k.lower() for k in self.headers.keys())
                rec = {"path": self.path, "method": "POST", "header_names": names,
                       "has_auth": "authorization" in names or "x-api-key" in names, "body": body,
                       "ts": time.time()}
                with stub._lock:
                    stub.requests.append(rec)
                    item = stub.script.pop(0) if stub.script else {}
                if item.get("delay_s"):
                    time.sleep(float(item["delay_s"]))
                status = int(item.get("status", 200))
                if "body" in item:
                    payload = item["body"]
                elif status == 200:
                    text = item.get("text", stub.default_text)
                    payload = anthropic_body(text) if self.path.rstrip("/").endswith("/messages") \
                        else openai_body(text)
                else:
                    payload = {"error": {"type": "stub_error", "message": "scripted status %d" % status}}
                data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (item.get("headers") or {}).items():
                    self.send_header(k, str(v))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1})
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, *exc):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        return False

    @property
    def port(self):
        return self.server.server_address[1]

    def url(self, path="/v1/chat/completions"):
        return "http://127.0.0.1:%d%s" % (self.port, path)

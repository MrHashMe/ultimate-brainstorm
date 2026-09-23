"""OpenAI-compatible chat HTTP backend (openai-chat-http): stdlib urllib, off unless configured. KIT_SPEC 5.2.

POST url  Authorization: Bearer $KEY
body {"model", "messages":[{"role":"user","content":P}], "max_tokens": 16000}; output choices[0].message.content.
On 429 or 5xx: exponential back-off honoring Retry-After, at most 2 retries. No tools.
The key is read from the environment and goes only into a request header (never argv, logs or meta).
"""

import json
import socket
import time

try:
    import urllib.error as _uerr
    import urllib.request as _ureq
except ImportError:  # pragma: no cover
    _ureq = _uerr = None

from .. import redact
from . import classify_error, host_of, result, usage_block


class _NoRedirect(_ureq.HTTPRedirectHandler):
    """Never follow a redirect: urllib would re-send the Authorization / x-api-key header to the Location host.
    A 3xx then surfaces as an HTTPError (a failed attempt)."""

    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


_OPENER = _ureq.build_opener(_NoRedirect)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

MAX_TOKENS = 16000
MAX_RETRIES = 2
MAX_RETRY_AFTER_S = 60.0
_sleep = time.sleep  # test seam


def _retry_after(value):
    if not value:
        return None
    try:
        return max(0.0, float(str(value).strip()))
    except (ValueError, RecursionError):
        return None  # HTTP-date form: fall back to exponential back-off


def post_json(url, headers, payload, timeout_s, max_retries=MAX_RETRIES):
    """POST JSON with back-off on 429/5xx. Returns (status_code|None, body_bytes, exc|None, retries_used)."""
    data = json.dumps(payload).encode("utf-8")
    deadline = time.monotonic() + float(timeout_s or 420)
    retries = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, b"", socket.timeout("deadline reached"), retries
        req = _ureq.Request(url, data=data, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        req.add_header("Content-Type", "application/json")
        try:
            with _OPENER.open(req, timeout=remaining) as resp:
                return resp.status, resp.read(), None, retries
        except _uerr.HTTPError as e:
            code = e.code
            try:
                body = e.read()
            except (OSError, ValueError):
                body = b""
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                e.close()
            except (OSError, ValueError):
                pass
            if (code == 429 or 500 <= code < 600) and retries < max_retries:
                delay = _retry_after(retry_after)
                if delay is None:
                    delay = float(2 ** retries)
                delay = min(delay, MAX_RETRY_AFTER_S)
                if time.monotonic() + delay >= deadline:
                    return code, body, None, retries
                _sleep(delay)
                retries += 1
                continue
            return code, body, None, retries
        except (_uerr.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            return None, b"", e, retries


def _is_timeout(exc):
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


def http_failure(code, body, exc, cmd, model, timeout_s):
    """Call result for a non-2xx response or a transport error."""
    if exc is not None:
        if _is_timeout(exc):
            return result("timeout", error_class="timeout", error="HTTP request timed out after %ss" % timeout_s,
                          cmd=cmd, model=model)
        return result("failed", error_class="network", error="HTTP transport error: %s" % exc.__class__.__name__,
                      cmd=cmd, model=model)
    text = redact.redact(body.decode("utf-8", "replace"))[:500]
    if code in (401, 403):
        ec = "auth"
    elif code == 404:
        ec = "not_found"
    elif code == 429:
        ec = "rate_limit"
    elif code is not None and code >= 500:
        ec = "network"
    else:
        ec = classify_error(text)
    return result("failed", error_class=ec, error="HTTP %s: %s" % (code, text), exit_code=code, cmd=cmd, model=model,
                  stderr_tail=text)


def precheck(ctx):
    """(key, model, failure-or-None): the backend is off unless enabled, keyed and given a model."""
    b = ctx.bcfg
    if b.get("enabled") is False:
        return None, None, result("unavailable", error_class="not_found", error="%s is disabled (enable it in "
                                  "UB_HOME/families.json after a live selftest)" % ctx.backend_id)
    key_env = b.get("key_env")
    key = (ctx.base_env.get(key_env) or "").strip() if key_env else ""
    if not key:
        return None, None, result("unavailable", error_class="auth", error="%s is not set" % (key_env or "key_env"))
    model = (ctx.alt_model if (ctx.alt and ctx.alt_model) else None) or b.get("model")
    if not model:
        return None, None, result("unavailable", error_class="not_found", error="%s has no model configured"
                                  % ctx.backend_id)
    if not b.get("url"):
        return None, None, result("unavailable", error_class="not_found", error="%s has no url" % ctx.backend_id)
    scheme = str(b.get("url")).split(":", 1)[0].lower()
    if scheme != "https" and not (scheme == "http" and host_of(b.get("url")) in _LOCAL_HOSTS):
        return None, None, result("unavailable", error_class="policy", error="%s: the url must use https (the key "
                                  "would travel in clear text)" % ctx.backend_id)
    return key, model, None


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def run(ctx):
    key, model, fail = precheck(ctx)
    if fail:
        return fail
    url = ctx.bcfg["url"]
    cmd = "POST %s" % url
    payload = {"model": model, "messages": [{"role": "user", "content": ctx.prompt}], "max_tokens": MAX_TOKENS}
    code, body, exc, _retries = post_json(url, {"Authorization": "Bearer %s" % key}, payload, ctx.timeout_s)
    if exc is not None or code is None or not (200 <= code < 300):
        return http_failure(code, body, exc, cmd, model, ctx.timeout_s)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        text = _content_text(data["choices"][0]["message"]["content"])
    except (ValueError, RecursionError, KeyError, IndexError, TypeError):
        return result("failed", error_class="bad_output", error="unexpected chat completions response", cmd=cmd,
                      model=model, exit_code=code)
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    usage = usage_block(_num(u.get("prompt_tokens")), _num(u.get("completion_tokens")), None)
    if text is None or not text.strip():
        return result("failed", error_class="bad_output", error="empty completion", cmd=cmd, model=model,
                      exit_code=code, usage=usage)
    return result("ok", text=text, usage=usage, cmd=cmd, model=model, exit_code=code)

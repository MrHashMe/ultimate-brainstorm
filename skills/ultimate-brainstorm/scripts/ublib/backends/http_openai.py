"""OpenAI-compatible chat HTTP backend (openai-chat-http): stdlib urllib, off unless configured. KIT_SPEC 5.2.

POST url  Authorization: Bearer $KEY
body {"model", "messages":[{"role":"user","content":P}], "max_tokens": 16000}; output choices[0].message.content.
On 429 or 5xx: at most 2 retries with full-jitter back-off (backends.backoff_delay), honoring Retry-After (seconds or
an HTTP-date). Every request, its back-off and the reading of the response stay inside one deadline (the attempt's
timeout), and the response body is read in chunks up to RESPONSE_CAP_BYTES. No tools.
finish_reason "length" = output truncated (the adapter reports it invalid); "content_filter" or a message.refusal =
the model refused (failed, error_class policy, not retried on this backend).
The key is read from the environment and goes only into a request header (never argv, logs or meta). A loopback url
(the only one allowed over http://) is called directly, never through a proxy.
"""

import json
import socket

try:
    import urllib.error as _uerr
    import urllib.request as _ureq
except ImportError:  # pragma: no cover
    _ureq = _uerr = None

from .. import redact
from .. import validate
from . import (_get, backoff_delay, classify_error, host_of, now, num, parse_retry_after, pause, result,
               usage_block)


class _NoRedirect(_ureq.HTTPRedirectHandler):
    """Never follow a redirect: urllib would re-send the Authorization / x-api-key header to the Location host.
    A 3xx then surfaces as an HTTPError (a failed attempt)."""

    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


class ResponseTooLarge(ValueError):
    """The response body passed RESPONSE_CAP_BYTES."""


_OPENER = _ureq.build_opener(_NoRedirect)
# A loopback server is always called directly: through HTTP_PROXY or the Windows system proxy the key and the prompt
# would reach the proxy (in clear text for http://), and the proxy cannot reach this machine's loopback anyway.
_DIRECT_OPENER = _ureq.build_opener(_ureq.ProxyHandler({}), _NoRedirect)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

MAX_TOKENS = 16000
MAX_RETRIES = 2
MAX_TRIES = MAX_RETRIES + 1  # requests one attempt can send (adapter.request_reserve)
# The JSON of a 2 MB answer, escaped as \uXXXX in the worst case, plus the envelope.
RESPONSE_CAP_BYTES = 6 * validate.OUTPUT_CAP_BYTES + 64 * 1024
ERROR_BODY_BYTES = 64 * 1024
CHUNK = 64 * 1024


def _set_read_timeout(resp, seconds):
    """Best effort: bound the next socket read by the time left (urllib's timeout is per socket operation)."""
    sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
    try:
        if sock is not None:
            sock.settimeout(max(0.05, seconds))
    except OSError:
        pass


def _read_body(resp, deadline, cap, strict=True):
    """The body in CHUNK reads, checking the deadline between reads. Past cap: ResponseTooLarge (strict) or the first
    cap bytes. Past the deadline: socket.timeout."""
    chunks, total = [], 0
    read = getattr(resp, "read1", None) or resp.read
    while True:
        left = deadline - now()
        if left <= 0:
            raise socket.timeout("deadline reached while reading the response")
        _set_read_timeout(resp, left)
        chunk = read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            if strict:
                raise ResponseTooLarge("the response is larger than %d bytes" % cap)
            chunks.append(chunk[:cap - (total - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def post_json(url, headers, payload, timeout_s, max_retries=MAX_RETRIES):
    """POST JSON with back-off on 429/5xx, all inside one deadline of timeout_s.

    Returns (status_code|None, body_bytes, exc|None, requests_sent, retry_after_s|None). retry_after_s is the last
    Retry-After the server sent (seconds), for the adapter's own retry."""
    data = json.dumps(payload).encode("utf-8")
    opener = _DIRECT_OPENER if host_of(url) in _LOCAL_HOSTS else _OPENER
    deadline = now() + float(timeout_s or 420)
    sent = 0
    while True:
        remaining = deadline - now()
        if remaining <= 0:
            return None, b"", socket.timeout("deadline reached"), sent, None
        req = _ureq.Request(url, data=data, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        req.add_header("Content-Type", "application/json")
        sent += 1
        try:
            with opener.open(req, timeout=remaining) as resp:
                return resp.status, _read_body(resp, deadline, RESPONSE_CAP_BYTES), None, sent, None
        except _uerr.HTTPError as e:
            code = e.code
            try:
                body = _read_body(e, deadline, ERROR_BODY_BYTES, strict=False)
            except (OSError, ValueError, AttributeError):  # no body, or the deadline passed while reading it
                body = b""
            retry_after = parse_retry_after(e.headers.get("Retry-After") if e.headers else None)
            try:
                e.close()
            except (OSError, ValueError):
                pass
            if (code == 429 or 500 <= code < 600) and sent <= max_retries:
                delay = backoff_delay(sent - 1, retry_after)
                if now() + delay >= deadline:
                    return code, body, None, sent, retry_after
                pause(delay)
                continue
            return code, body, None, sent, retry_after
        except ResponseTooLarge as e:
            return None, b"", e, sent, None
        except (_uerr.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            return None, b"", e, sent, None


def _is_timeout(exc):
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


def http_failure(code, body, exc, cmd, model, timeout_s, requests=1, retry_after=None):
    """Call result for a non-2xx response or a transport error."""
    common = {"cmd": cmd, "model": model, "requests": requests}
    if exc is not None:
        if _is_timeout(exc):
            return result("timeout", error_class="timeout", error="HTTP request timed out after %ss" % timeout_s,
                          **common)
        if isinstance(exc, ResponseTooLarge):
            return result("failed", error_class="bad_output", error="HTTP %s" % exc, retryable=False, **common)
        return result("failed", error_class="network", error="HTTP transport error: %s" % exc.__class__.__name__,
                      **common)
    text = redact.redact(body.decode("utf-8", "replace"))[:500]
    retryable = True
    if code in (401, 403):
        ec = "auth"
    elif code == 404:
        ec = "not_found"
    elif code in (429, 503, 529):
        ec = "rate_limit"  # capacity: the same class a CLI reports for "overloaded"
    elif code is not None and code >= 500:
        ec = "network"
    else:
        ec = classify_error(text)
        retryable = code == 408  # any other 4xx: the same request fails the same way
    return result("failed", error_class=ec, error="HTTP %s: %s" % (code, text), exit_code=code, stderr_tail=text,
                  retryable=retryable, retry_after=retry_after, **common)


def precheck(ctx):
    """(key, model, failure-or-None): the backend is off unless enabled, keyed and given a model."""
    b = ctx.bcfg
    if b.get("enabled") is False:
        return None, None, result("unavailable", error_class="not_found", error="%s is disabled (enable it in "
                                  "UB_HOME/families.json after a live selftest)" % ctx.backend_id)
    key_env = b.get("key_env")
    key = (_get(ctx.base_env, key_env) or "").strip() if key_env else ""  # Windows: any case, as detection reads it
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


def finish_result(text, stop, refused, cmd, model, code, usage, requests):
    """The call result for a 2xx answer: refusal, truncation at MAX_TOKENS, empty, or ok."""
    common = {"cmd": cmd, "model": model, "exit_code": code, "usage": usage, "requests": requests}
    if refused:
        return result("failed", error_class="policy", error="the model refused (%s)" % stop, retryable=False,
                      **common)
    empty = text is None or not text.strip()
    if stop == "truncated" and empty:
        return result("failed", error_class="bad_output", error="the output hit max_tokens=%d before any text"
                      % MAX_TOKENS, retryable=False, **common)
    if empty:
        return result("failed", error_class="bad_output", error="empty completion", **common)
    return result("ok", text=text, truncated=stop == "truncated", **common)


def run(ctx):
    key, model, fail = precheck(ctx)
    if fail:
        return fail
    url = ctx.bcfg["url"]
    cmd = "POST %s" % url
    payload = {"model": model, "messages": [{"role": "user", "content": ctx.prompt}], "max_tokens": MAX_TOKENS}
    code, body, exc, sent, retry_after = post_json(url, {"Authorization": "Bearer %s" % key}, payload, ctx.timeout_s)
    if exc is not None or code is None or not (200 <= code < 300):
        return http_failure(code, body, exc, cmd, model, ctx.timeout_s, sent, retry_after)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        choice = data["choices"][0]
        message = choice["message"]
        text = _content_text(message["content"])
    except (ValueError, RecursionError, KeyError, IndexError, TypeError):
        return result("failed", error_class="bad_output", error="unexpected chat completions response", cmd=cmd,
                      model=model, exit_code=code, requests=sent)
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    usage = usage_block(num(u.get("prompt_tokens")), num(u.get("completion_tokens")), None)
    reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    refusal = message.get("refusal") if isinstance(message, dict) else None
    refused = reason == "content_filter" or (isinstance(refusal, str) and bool(refusal.strip())
                                             and not (text or "").strip())
    stop = "truncated" if reason == "length" else "finish_reason=%s" % reason
    return finish_result(text, stop, refused, cmd, model, code, usage, sent)

"""Anthropic Messages HTTP backend (anthropic-http): stdlib urllib, off unless configured. KIT_SPEC 5.2.

POST url  x-api-key: $KEY  anthropic-version: 2023-06-01
body {"model", "max_tokens": 16000, "messages":[{"role":"user","content":P}]}; output = the concatenated text blocks.
Back-off, retries, deadline and response cap as in http_openai. stop_reason "max_tokens" = output truncated;
"refusal" = the model refused (failed, error_class policy, not retried on this backend). No tools.
"""

import json

from . import num, result, usage_block
from .http_openai import MAX_TOKENS, finish_result, http_failure, post_json, precheck

ANTHROPIC_VERSION = "2023-06-01"


def run(ctx):
    key, model, fail = precheck(ctx)
    if fail:
        return fail
    url = ctx.bcfg["url"]
    cmd = "POST %s" % url
    payload = {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": ctx.prompt}]}
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    code, body, exc, sent, retry_after = post_json(url, headers, payload, ctx.timeout_s)
    if exc is not None or code is None or not (200 <= code < 300):
        return http_failure(code, body, exc, cmd, model, ctx.timeout_s, sent, retry_after)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        blocks = data["content"]
        text = "".join(b.get("text", "") for b in blocks
                       if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    except (ValueError, RecursionError, KeyError, TypeError):
        return result("failed", error_class="bad_output", error="unexpected messages response", cmd=cmd, model=model,
                      exit_code=code, requests=sent)
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    usage = usage_block(num(u.get("input_tokens")), num(u.get("output_tokens")), None)
    if data.get("type") == "error":
        return result("failed", error_class="bad_output", error="empty message", cmd=cmd, model=model, exit_code=code,
                      usage=usage, requests=sent)
    reason = data.get("stop_reason")
    stop = "truncated" if reason == "max_tokens" else "stop_reason=%s" % reason
    return finish_result(text, stop, reason == "refusal", cmd, model, code, usage, sent)

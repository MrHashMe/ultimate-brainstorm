"""Anthropic Messages HTTP backend (anthropic-http): stdlib urllib, off unless configured. KIT_SPEC 5.2.

POST url  x-api-key: $KEY  anthropic-version: 2023-06-01
body {"model", "max_tokens": 16000, "messages":[{"role":"user","content":P}]}; output = the concatenated text blocks.
Back-off and retries as in http_openai. No tools.
"""

import json

from . import result, usage_block
from .http_openai import MAX_TOKENS, http_failure, post_json, precheck

ANTHROPIC_VERSION = "2023-06-01"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def run(ctx):
    key, model, fail = precheck(ctx)
    if fail:
        return fail
    url = ctx.bcfg["url"]
    cmd = "POST %s" % url
    payload = {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": ctx.prompt}]}
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    code, body, exc, _retries = post_json(url, headers, payload, ctx.timeout_s)
    if exc is not None or code is None or not (200 <= code < 300):
        return http_failure(code, body, exc, cmd, model, ctx.timeout_s)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        blocks = data["content"]
        text = "".join(b.get("text", "") for b in blocks
                       if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    except (ValueError, RecursionError, KeyError, TypeError):
        return result("failed", error_class="bad_output", error="unexpected messages response", cmd=cmd, model=model,
                      exit_code=code)
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    usage = usage_block(_num(u.get("input_tokens")), _num(u.get("output_tokens")), None)
    if data.get("type") == "error" or not text.strip():
        return result("failed", error_class="bad_output", error="empty message", cmd=cmd, model=model, exit_code=code,
                      usage=usage)
    return result("ok", text=text, usage=usage, cmd=cmd, model=model, exit_code=code)

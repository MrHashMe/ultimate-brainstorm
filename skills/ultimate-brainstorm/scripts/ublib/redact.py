"""Secret redaction for logs, meta files, calls.jsonl and cards (KIT_SPEC 3.1 item 9, 5.4).

Secrets are read only from environment variables. Anything that is logged goes through redact() first, which
replaces every known secret value (and a few well-known key shapes) with "[REDACTED]".

API (not frozen in 4.8; B2 internal, safe for B3/B4):
    SECRET_ENV_NAMES, MASK
    is_secret_name(name) -> bool
    known_secret_values(environ=None) -> list[str]
    redact(text, secrets=None) -> str
    redact_obj(obj, secrets=None) -> object          deep copy with strings redacted and secret-named keys masked
    format_cmd(argv, secrets=None) -> str             display form of an argv list, redacted
    env_names(env) -> list[str]                       variable NAMES only (never values)
"""

import os
import re

__all__ = ["SECRET_ENV_NAMES", "MASK", "MIN_SECRET_LEN", "is_secret_name", "known_secret_values", "redact",
           "redact_obj", "format_cmd", "env_names"]

MASK = "[REDACTED]"
MIN_SECRET_LEN = 8

SECRET_ENV_NAMES = (
    "ZAI_API_KEY", "ZAI_PAYG_API_KEY", "Z_AI_API_KEY",
    "KIMI_API_KEY", "KIMI_CODE_API_KEY", "MOONSHOT_API_KEY",
    "OPENAI_API_KEY", "CODEX_API_KEY",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "GITHUB_TOKEN", "GH_TOKEN",
)

_SECRET_NAME_RE = re.compile(r"(API_?KEY|AUTH_?TOKEN|ACCESS_?TOKEN|_TOKEN$|^TOKEN$|SECRET|PASSWORD|PASSWD|CREDENTIAL|"
                             r"(^|_)KEY$|_KEY_)", re.IGNORECASE)
# Names that match the pattern but never hold secrets.
_NOT_SECRET = {"UB_JOB_FILE", "UB_JOB_ID", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "MAX_TOKENS"}

_SHAPES = (
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)(\bx-api-key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._~+/=\-]{8,}"),
)


def is_secret_name(name):
    """True for environment/JSON key names that hold secrets (API keys, tokens, passwords)."""
    if not isinstance(name, str) or not name:
        return False
    up = name.upper()
    if up in _NOT_SECRET:
        return False
    return up in SECRET_ENV_NAMES or bool(_SECRET_NAME_RE.search(up))


def known_secret_values(environ=None):
    """Values (length >= 8) of every secret-named variable in environ (default os.environ), longest first."""
    env = os.environ if environ is None else environ
    values = set()
    for name, value in env.items():
        if isinstance(value, str) and len(value.strip()) >= MIN_SECRET_LEN and is_secret_name(name):
            values.add(value.strip())
            if value != value.strip():
                values.add(value)
    return sorted(values, key=len, reverse=True)


def redact(text, secrets=None):
    """Return text with every known secret value and known key shapes replaced by [REDACTED].

    secrets: an iterable of extra literal values to scrub; the environment's secret values are always included.
    """
    if text is None:
        return text
    if not isinstance(text, str):
        text = str(text)
    values = set(known_secret_values())
    for s in secrets or ():
        if isinstance(s, str) and len(s) >= MIN_SECRET_LEN:
            values.add(s)
    for v in sorted(values, key=len, reverse=True):
        if v in text:
            text = text.replace(v, MASK)
    for rx in _SHAPES:
        if rx.groups:
            text = rx.sub(lambda m: m.group(1) + MASK, text)
        else:
            text = rx.sub(MASK, text)
    return text


def redact_obj(obj, secrets=None):
    """Deep copy of a JSON-like object: strings redacted; values under secret-named keys masked entirely."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if is_secret_name(k) and isinstance(v, str) and v:
                out[k] = MASK
            else:
                out[k] = redact_obj(v, secrets)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact(obj, secrets)
    return obj


def _quote(arg):
    if arg == "":
        return '""'
    if re.search(r"[\s\"']", arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def format_cmd(argv, secrets=None):
    """A display string for an argv list (for meta "cmd" and logs), redacted. Never used to run anything."""
    return redact(" ".join(_quote(str(a)) for a in (argv or [])), secrets)


def env_names(env):
    """Sorted variable names of an environment mapping; values are never returned."""
    return sorted((env or {}).keys())

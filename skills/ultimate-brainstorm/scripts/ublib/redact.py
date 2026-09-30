"""Secret redaction for logs, meta files, calls.jsonl and cards (KIT_SPEC 3.1 item 9, 5.4).

Secrets are read only from environment variables. Anything that is logged goes through redact() first, which
replaces every known secret value (the values of secret-named variables, the password of a proxy URL) and the
well-known credential shapes with "[REDACTED]": sk- keys, Bearer / Basic authorization values, x-api-key headers,
JWTs, GitHub (classic and fine-grained), GitLab, AWS access key, Slack, Google API and Hugging Face tokens, key=value
or "key": "value" pairs for token/secret/password/signature/credential names, also with a prefix (DATABASE_PASSWORD=,
AWS_SECRET_ACCESS_KEY=, X-Amz-Signature=, "db_password": ...; JSON, assignments, URL query strings; a value of digits
only is not a secret), "name: value" lines (YAML, headers), the userinfo of a URL (scheme://user:password@host, an
empty user, or a 16+ character token alone before the @) and PEM private key blocks. Credentials a CLI keeps itself
(OAuth tokens) never appear in the environment, so the shapes are what catch them. Every shape runs in linear time:
redact() sees whole CLI transcripts (kimi samples) and error bodies that a web page can fill.

API (not frozen in 4.8; B2 internal, safe for B3/B4):
    SECRET_ENV_NAMES, MASK
    is_secret_name(name) -> bool
    known_secret_values(environ=None) -> list[str]
    redact(text, secrets=None) -> str
    redact_obj(obj, secrets=None) -> object          deep copy with strings redacted and secret-named keys masked
    format_cmd(argv, secrets=None) -> str             display form of an argv list, redacted
"""

import os
import re

try:
    from urllib.parse import urlsplit
except ImportError:  # pragma: no cover
    from urlparse import urlsplit  # type: ignore

__all__ = ["SECRET_ENV_NAMES", "MASK", "MIN_SECRET_LEN", "is_secret_name", "known_secret_values", "redact",
           "redact_obj", "format_cmd"]

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

_PROXY_NAME_RE = re.compile(r"^(?:HTTPS?|ALL|FTP)_PROXY$", re.IGNORECASE)
# Names whose value is a credential. The short ones (key, token, sig, ...) only count as key=value (query strings,
# assignments) or as a quoted key ("token": "..."); the long ones also as a "name: value" header line.
_LONG_NAMES = (r"(?:x-api-key|api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|"
               r"client[_-]?secret|password|passwd)")
_NAMES = r"(?:%s|secret|token|sig|signature|key|pwd)" % _LONG_NAMES
_WORDS = r"(?:%s|secret|token|sig|signature|key|pwd|credential)s?" % _LONG_NAMES  # what may end a (prefixed) name
_VALUE = r"[^\s\"'&,;<>{}\[\]]{8,}"
_NOT_A_NUMBER = r"(?=[^\s\"'&,;<>{}\[\]]*[^\s\"'&,;<>{}\[\]0-9])"  # max_tokens=100000000 is not a secret
_PREFIX = r"(?:[A-Za-z0-9]+[_.-])"  # one segment of a prefixed name: DATABASE_, X-Amz-, db.
_END = r"(?![A-Za-z0-9_.-])"  # the secret word ends the name
_SCHEME = r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://"  # starts only where a scheme can start: linear

# Each shape masks the whole match, or only what lies between its "pre" and "post" groups. A shape never re-scans a
# run it already failed on (anchored starts, bounded prefixes): quadratic shapes stalled a worker on adversarial text.
_SHAPES = (
    re.compile(r"(?P<pre>-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----)[\s\S]*?"
               r"(?:(?P<post>-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----)|\Z)"),  # an unterminated block: to the end
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained token
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),  # GitLab personal access token
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),  # Google API key
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),  # Hugging Face token
    re.compile(r"(?i)(?P<pre>\bBearer\s+)[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)(?P<pre>\bBasic\s+)(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{8,}={0,2}"),
    re.compile(r"(?P<pre>" + _SCHEME + r"[^\s/:@\"'<>]*:)[^\s@/\"'<>]+(?P<post>@)"),  # URL user:password@ (or :pw@)
    re.compile(r"(?P<pre>" + _SCHEME + r")[^\s/:@\"'<>]{16,}(?P<post>@)"),  # URL token@ (a token as the user)
    re.compile(r"(?i)(?P<pre>(?<![A-Za-z0-9_-])" + _NAMES + r"=)" + _VALUE),  # ?key=..., token=...
    re.compile(r"(?i)(?P<pre>(?<![A-Za-z0-9_.-])" + _PREFIX + r"+" + _WORDS + _END + r"\s*=\s*[\"']?)"
               + _NOT_A_NUMBER + _VALUE),  # DATABASE_PASSWORD=..., X-Amz-Signature=..., API_KEY = "..."
    re.compile(r"(?i)(?P<pre>[\"']" + _PREFIX + r"*" + _WORDS + r"[\"']\s*:\s*[\"']?)" + _NOT_A_NUMBER
               + _VALUE),  # "token": "...", "db_password": "..."
    re.compile(r"(?i)(?P<pre>(?<![A-Za-z0-9_-])" + _LONG_NAMES + r"\s*:\s*)" + _VALUE),  # x-api-key: ...
    re.compile(r"(?im)(?P<pre>^[ \t]*(?:-[ \t]+)?[\"']?" + _PREFIX + r"*" + _WORDS + r"[\"']?[ \t]*:[ \t]*[\"']?)"
               + _NOT_A_NUMBER + _VALUE),  # YAML / header lines: token: ..., PRIVATE-TOKEN: ..., - db_password: ...
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
        elif isinstance(value, str) and isinstance(name, str) and _PROXY_NAME_RE.match(name):
            try:
                password = urlsplit(value.strip()).password
            except ValueError:
                password = None
            if password and len(password) >= MIN_SECRET_LEN:
                values.add(password)
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
        text = rx.sub(_mask_match, text)
    return text


def _mask_match(m):
    groups = m.groupdict()
    return (groups.get("pre") or "") + MASK + (groups.get("post") or "")


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

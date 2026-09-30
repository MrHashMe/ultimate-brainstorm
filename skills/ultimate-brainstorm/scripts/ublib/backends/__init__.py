"""Model backends: shared call context, environment policy, error classes, secret temp files (KIT_SPEC 5.2-5.4).

Every backend module exposes:
    run(ctx) -> dict            one attempt; never raises for model/process failures
    build_argv(ctx, paths)      (CLI backends) the exact argv of 5.2, for tests and `family.py explain`
and goes through ublib.proc.run (the single process seam) for processes.

The result dict of one attempt ("call result"):
    {"status": "ok|failed|timeout|unavailable|refused", "text": str|None, "error_class": None|<4.7 class>,
     "error": str, "exit_code": int|None, "usage": {...}, "cmd": str (redacted), "stderr_tail": str,
     "model": str|None, "web_used": bool, "requests": int, "retryable": bool, "retry_after": float|None,
     "truncated": bool}
"requests" counts the backend requests the attempt really sent (CLI invocations; HTTP requests including the
internal retries; 0 when it stopped before any contact). "retryable" false: the same prompt would fail the same way on
this backend, so the adapter moves to the next one. "retry_after": seconds a server asked to wait. "truncated": the
model stopped at its output-token limit (the adapter reports the output invalid; a repair call cannot fit either).
Status "invalid" (a CLI printed more than its stdout cap) ends the job at once: no retry, repair or next backend.

Stdout caps (stdout_cap): claude-cli prints one JSON object, which is buffered and capped at CLAUDE_STDOUT_CAP_BYTES
(6 x the 2 MB answer cap + 64 KB). codex-cli and kimi-cli print JSONL, which is parsed line by line as it arrives
(JsonLines, proc.run on_line: nothing is buffered, every event is seen), capped at STREAM_CAP_BYTES in total. The
backend key max_stdout_mb (a positive number) replaces either cap.
"""

import datetime
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time

try:
    from urllib.parse import urlparse
except ImportError:  # pragma: no cover
    from urlparse import urlparse  # type: ignore

from .. import filesproto
from .. import proc
from .. import redact
from .. import textio

__all__ = ["CallContext", "DENY_EXACT", "DENY_PREFIXES", "PROVIDER_DENY", "scrub_env", "child_env", "classify_error",
           "result",
           "usage_block", "write_secret_file", "remove_quietly", "ub_tmp_dir", "new_call_dir", "module_for",
           "run_process", "host_of", "is_anthropic_url", "tools_has", "STDERR_TAIL", "sweep_stale_calls",
           "user_codex_home", "is_ub_codex_home", "user_principal", "model_for", "work_dir", "num",
           "iter_json_objects", "endpoint_serves", "backoff_delay", "parse_retry_after", "pause", "now",
           "BACKOFF_CAP_S", "JsonLines", "stdout_cap", "CLAUDE_STDOUT_CAP_BYTES", "STREAM_CAP_BYTES"]

STDERR_TAIL = 2000
CLAUDE_STDOUT_CAP_BYTES = 6 * 2 * 1024 * 1024 + 64 * 1024  # one result object with a JSON-escaped 2 MB answer
STREAM_CAP_BYTES = 256 * 1024 * 1024                       # a streamed JSONL run (not buffered): bounds a flood

# 5.3 denylist: removed from every child environment.
DENY_EXACT = (
    "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_MAX_CONTEXT_TOKENS", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY", "CODEX_HOME",
    "KIMI_API_KEY", "KIMI_CODE_API_KEY",
    "ZAI_API_KEY", "ZAI_PAYG_API_KEY", "Z_AI_API_KEY",
    "API_TIMEOUT_MS", "UB_HOST_FAMILY",
)
DENY_PREFIXES = ("ANTHROPIC_", "KIMI_MODEL_")
# Also removed from provider children (claude-cli@glm, @kimi, @kimi-code): they would route the call to Bedrock,
# Vertex or Foundry, which reject the provider's model ids.
PROVIDER_DENY = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


class CallContext(object):
    """Everything one backend attempt needs. Built by ublib.adapter; `family.py explain` builds a dry one."""

    def __init__(self, **kw):
        self.job = kw.get("job") or {}
        self.job_id = kw.get("job_id") or self.job.get("id") or "adhoc"
        self.job_file = kw.get("job_file") or ""
        self.prompt = kw.get("prompt") or ""
        self.backend_id = kw.get("backend_id") or ""
        self.bcfg = kw.get("bcfg") or {}
        self.btype = kw.get("btype") or self.bcfg.get("type") or self.backend_id.split("@", 1)[0]
        self.provider = kw.get("provider", self.bcfg.get("provider"))
        self.cfg = kw.get("cfg") or {}
        self.family = kw.get("family") or ""
        self.alt = bool(kw.get("alt"))
        self.alt_model = kw.get("alt_model")
        self.tier = kw.get("tier") or "default"
        self.tools = kw.get("tools") or "none"
        self.cwd_mode = kw.get("cwd_mode") or "empty"
        self.repo_root = kw.get("repo_root")
        self.call_dir = kw.get("call_dir")
        self.timeout_s = kw.get("timeout_s") or 420
        self.run_dir = kw.get("run_dir")
        self.schema_path = kw.get("schema_path")
        self.ub_home = kw.get("ub_home")
        self.base_env = dict(kw.get("base_env") if kw.get("base_env") is not None else os.environ)

    @property
    def exe_name(self):
        return self.bcfg.get("exe") or self.btype.split("-", 1)[0]


# ---------------------------------------------------------------- env policy (5.3)

def _upper(name):
    return name.upper() if os.name == "nt" else name


def _denied(name):
    up = name.upper()
    if up in DENY_EXACT:
        return True
    return any(up.startswith(p) for p in DENY_PREFIXES)


def scrub_env(base_env=None):
    """A copy of base_env with every 5.3 denylisted variable removed."""
    base = os.environ if base_env is None else base_env
    return {k: v for k, v in base.items() if not _denied(k)}


_get = proc._env_get  # case-insensitive on Windows


def host_of(url):
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def is_anthropic_url(url):
    h = host_of(url)
    return h == "anthropic.com" or h.endswith(".anthropic.com")


def endpoint_serves(url, family):
    """True when an endpoint URL serves the given family (detect.endpoint_family)."""
    from ..detect import endpoint_family  # lazy: detect imports this package
    return endpoint_family(url) == family


def is_ub_codex_home(path, ub_home=None):
    """True when path lies under <UB_HOME>/codex-homes/ (a launcher's provider home, never the user's own)."""
    if not path:
        return False
    try:
        home = ub_home or os.environ.get("UB_HOME") or os.path.join(os.path.expanduser("~"), ".ultimate-brainstorm")
        root = os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser(home), "codex-homes")))
        p = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
    except (TypeError, ValueError):
        return False
    return p == root or p.startswith(root.rstrip("\\/") + os.sep)


def user_codex_home(env, ub_home=None):
    """The user's own CODEX_HOME for the native codex-cli backend: CODEX_HOME unless a codex-glm / codex-kimi launcher
    replaced it with a UB-owned home, in which case UB_USER_CODEX_HOME (set by the launcher; empty = ~/.codex).
    Returns a path, or None for the default ~/.codex."""
    cur = _get(env, "CODEX_HOME")
    if cur and not is_ub_codex_home(cur, ub_home):
        return cur
    if cur:
        orig = _get(env, "UB_USER_CODEX_HOME") or ""
        if orig and not is_ub_codex_home(orig, ub_home):
            return orig
    return None


def child_env(ctx, extra=None):
    """The child environment for one backend attempt: denylist, per-backend add-back, always-set names (5.3)."""
    base = ctx.base_env
    env = scrub_env(base)

    def add_back(name):
        v = _get(base, name)
        if v is not None and v != "":
            env[name] = v

    btype, provider = ctx.btype, ctx.provider
    if btype == "claude-cli" and not provider:
        orig = _get(base, "ANTHROPIC_BASE_URL")
        if not orig or is_anthropic_url(orig):
            for n in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
                add_back(n)
    elif btype == "claude-cli":
        for k in [k for k in env if k.upper() in PROVIDER_DENY]:
            del env[k]
    elif btype == "codex-cli":
        if ctx.bcfg.get("codex_home"):
            from .. import families
            env["CODEX_HOME"] = families.expand_path(ctx.bcfg["codex_home"], ctx.ub_home)
            tok = ctx.bcfg.get("token_env")
            if tok:
                add_back(tok)
        else:
            for n in ("OPENAI_API_KEY", "CODEX_API_KEY"):
                add_back(n)
            # the base URL only when it serves the family of this call: a proxy or another vendor's endpoint would
            # answer under this family's label (codex_cli.run refuses such a call)
            url = _get(base, "OPENAI_BASE_URL")
            if url and endpoint_serves(url, ctx.family or "gpt"):
                add_back("OPENAI_BASE_URL")
            # never add back a UB-owned provider home (codex-glm / codex-kimi) for the native gpt backend
            own = user_codex_home(base, ctx.ub_home)
            if own:
                env["CODEX_HOME"] = own
    elif btype == "kimi-cli":
        if ctx.bcfg.get("env_model"):
            for k, v in base.items():
                if k.upper().startswith("KIMI_MODEL_"):
                    env[k] = v
    env["UB_JOB_ID"] = str(ctx.job_id)
    env["UB_JOB_FILE"] = str(ctx.job_file or "")
    env["NO_COLOR"] = "1"
    for k, v in (extra or {}).items():
        env[k] = v
    return env


# ---------------------------------------------------------------- errors

# The classifiers read error channels only (stderr, error events, error records, error response bodies), never model
# output or tool results. Rate limits and overload are tested before auth: their messages may mention logging in.
_RATE_RE = re.compile(r"(\b429\b|\b529\b|rate[ _-]?limit|too many requests|quota|overloaded)", re.I)
_AUTH_RE = re.compile(r"((?:status|http|error|code)\W{0,3}40[13]\b|\b40[13]\s+(?:unauthori|forbidden)|"
                      r"\bunauthori[sz]ed\b|\bforbidden\b|invalid[ _-]?(?:x-)?api[ _-]?key|"
                      r"\bapi[ _-]?key\b.{0,40}\binvalid\b|incorrect api key|\bnot logged in\b|"
                      r"please (?:run /)?log ?in\b|\brun\s+[`'\"]?/?[\w-]*\s*login\b|/login\b|"
                      r"authentication(?:_error| failed| required| error)|(?:invalid|expired|missing) credentials?\b|"
                      r"permission denied.{0,40}(?:token|key))", re.I)
_SANDBOX_RE = re.compile(r"(sandbox.*(?:network|denied|blocked)|network.*(?:sandbox|restricted|disabled)|"
                         r"operation not permitted \(os error 1\))", re.I)  # [U-8]
_NETWORK_RE = re.compile(r"(enotfound|econnrefused|econnreset|etimedout|eai_again|getaddrinfo|network error|"
                         r"connection (?:refused|reset|error|closed)|could not resolve|unable to connect|"
                         r"failed to connect|\bdns\b|\bssl\b|certificate|socket hang up|fetch failed)", re.I)
_NOTFOUND_RE = re.compile(r"(command not found|is not recognized as an internal|no such file or directory.*(?:claude|"
                          r"codex|kimi)|model.*not found|unknown model|model_not_found)", re.I)


def classify_error(text, default="internal"):
    """Map error text (stderr, an error message, an error event; never model output) to a 4.7 error_class."""
    t = text or ""
    if _RATE_RE.search(t):
        return "rate_limit"
    if _AUTH_RE.search(t):
        return "auth"
    if _SANDBOX_RE.search(t):
        return "sandbox_network"
    if _NETWORK_RE.search(t):
        return "network"
    if _NOTFOUND_RE.search(t):
        return "not_found"
    return default


def usage_block(input_tokens=None, output_tokens=None, cost_usd=None, source=None):
    if source is None:
        source = "reported" if (input_tokens is not None or output_tokens is not None or cost_usd is not None) \
            else "none"
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd, "source": source}


def result(status, text=None, error_class=None, error="", exit_code=None, usage=None, cmd="", stderr_tail="",
           model=None, web_used=False, requests=0, retryable=True, retry_after=None, truncated=False):
    return {"status": status, "text": text, "error_class": error_class, "error": error or "", "exit_code": exit_code,
            "usage": usage or usage_block(), "cmd": cmd or "", "stderr_tail": stderr_tail or "", "model": model,
            "web_used": bool(web_used), "requests": int(requests or 0), "retryable": bool(retryable),
            "retry_after": retry_after, "truncated": bool(truncated)}


def tail(text, n=STDERR_TAIL):
    text = text or ""
    return text[-n:] if len(text) > n else text


def tools_has(tools, what):
    return what in (tools or "none").split("+")


def num(v):
    """A reported number, or None (bools and strings are not numbers)."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def model_for(ctx):
    """The -m model of a codex or kimi attempt: the alt seat's model, then the fast-tier model, then the configured
    one; None means the CLI default."""
    if ctx.alt and ctx.alt_model:
        return ctx.alt_model
    if ctx.tier == "fast" and ctx.bcfg.get("fast_model"):
        return ctx.bcfg["fast_model"]
    return ctx.bcfg.get("model")


def work_dir(ctx):
    """The child's working folder: the repository for cwd=repo jobs, else a fresh empty <call_dir>/ub-empty."""
    if ctx.cwd_mode == "repo" and ctx.repo_root:
        return ctx.repo_root
    cwd = os.path.join(ctx.call_dir, "ub-empty")
    os.makedirs(cwd, exist_ok=True)
    return cwd


def _lines(buf, nl):
    start, n = 0, len(buf)
    while start < n:
        end = buf.find(nl, start)
        if end < 0:
            end = n
        yield buf[start:end]
        start = end + 1


def iter_json_objects(raw):
    """Yield the JSON objects of a JSONL stream (bytes or str) one line at a time: the stream is never decoded as a
    whole and no list of events is kept. UTF-16 output (rare) is decoded first."""
    if not raw:
        return
    if isinstance(raw, str):
        buf, nl, brace = raw, "\n", "{"
    elif raw[:2] in (b"\xff\xfe", b"\xfe\xff") or textio._looks_utf16(raw):
        buf, nl, brace = textio.decode_bytes(raw), "\n", "{"
    else:
        buf, nl, brace = (raw[3:] if raw[:3] == b"\xef\xbb\xbf" else raw), b"\n", b"{"
    for line in _lines(buf, nl):
        obj = _json_line(line, brace)
        if obj is not None:
            yield obj


def _json_line(line, brace=b"{"):
    """One JSONL line (bytes or str) -> dict, or None when it is not a JSON object."""
    line = line.strip()
    if not line.startswith(brace):
        return None
    try:
        obj = json.loads(line)
    except UnicodeDecodeError:  # an invalid UTF-8 byte: decode this line tolerantly
        try:
            obj = json.loads(line.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            return None
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


class JsonLines(object):
    """The JSON objects of a CLI's JSONL stdout, handed to handle(obj) one at a time: line by line while the CLI runs
    (on_line: proc.run's streaming mode, so nothing is buffered and every event is seen), or all at once from bytes
    (feed_bytes: a result that was not streamed, e.g. a mocked proc.run). `fed` is True once anything arrived.

    A line longer than proc.LINE_CAP_BYTES arrives as its head only and goes to oversized(head_bytes). A UTF-16 stream
    (rare; recognized on its first line) cannot be cut at b"\\n": it is collected, up to proc.LINE_CAP_BYTES, and
    decoded by finish(); a longer one sets `undecodable` (the caller must not trust what it did not see)."""

    def __init__(self, handle, oversized=None):
        self.handle, self.oversized = handle, oversized
        self.fed = self.undecodable = False
        self._first = True
        self._utf16 = None  # bytearray while a UTF-16 stream is collected

    def on_line(self, raw, whole=True):
        self.fed = True
        if self._first:
            self._first = False
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or textio._looks_utf16(raw):
                self._utf16 = bytearray()
            elif raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
        if self._utf16 is not None:
            if self.undecodable or not whole or len(self._utf16) + len(raw) >= proc.LINE_CAP_BYTES:
                self.undecodable, self._utf16 = True, bytearray()
            else:
                self._utf16 += raw + b"\n"  # the exact bytes again: the split removed only this b"\n"
            return
        if not whole:
            if self.oversized is not None:
                self.oversized(raw)
            return
        obj = _json_line(raw)
        if obj is not None:
            self.handle(obj)

    def feed_bytes(self, raw):
        """A whole stream at once (bytes or str), one object at a time."""
        self.fed = True
        for obj in iter_json_objects(raw):
            self.handle(obj)

    def finish(self):
        """After the stream ended: decode a collected UTF-16 stream."""
        data, self._utf16 = self._utf16, None
        if data and not self.undecodable:
            for obj in iter_json_objects(bytes(data)):
                self.handle(obj)


def stdout_cap(ctx, streamed):
    """The stdout byte cap of one CLI attempt: backend key max_stdout_mb (a positive number of MB), else
    STREAM_CAP_BYTES for a streamed JSONL CLI (codex, kimi) or CLAUDE_STDOUT_CAP_BYTES (claude's one JSON object)."""
    mb = ctx.bcfg.get("max_stdout_mb")
    if isinstance(mb, (int, float)) and not isinstance(mb, bool) and mb > 0:
        return int(mb * 1024 * 1024)
    return STREAM_CAP_BYTES if streamed else CLAUDE_STDOUT_CAP_BYTES


# ---------------------------------------------------------------- back-off

BACKOFF_CAP_S = 60.0
_rng = random.Random()
_sleep = time.sleep  # test seam: every back-off sleep goes through pause()
_clock = time.monotonic  # test seam: every deadline check goes through now()


def now():
    return _clock()


def pause(seconds):
    if seconds and seconds > 0:
        _sleep(seconds)


def backoff_delay(n, retry_after=None, cap=BACKOFF_CAP_S):
    """Seconds to wait before retry n (0 = the first retry): full jitter, uniform in [0, min(cap, 2^(n+1))]. A
    server's Retry-After (seconds) wins, capped at cap."""
    if retry_after is not None:
        try:
            return min(max(0.0, float(retry_after)), cap)
        except (TypeError, ValueError):
            pass
    return _rng.uniform(0.0, min(cap, 2.0 ** (n + 1)))


def parse_retry_after(value, now_epoch=None):
    """A Retry-After header value (delta-seconds or an HTTP-date) as seconds from now, or None."""
    s = str(value).strip() if value is not None else ""
    if not s:
        return None
    try:
        return max(0.0, float(s))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return max(0.0, dt.timestamp() - (time.time() if now_epoch is None else now_epoch))


# ---------------------------------------------------------------- temp files and secrets

def ub_tmp_dir(ub_home):
    """UB_HOME/tmp, created with mode 0700."""
    path = os.path.join(ub_home, "tmp")
    os.makedirs(path, mode=0o700, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def _safe_id(job_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(job_id or "job"))[:60]


def new_call_dir(ub_home, job_id):
    """A fresh per-attempt folder under UB_HOME/tmp, named call-<pid>-<job>-*; the caller removes it in finally, and
    sweep_stale_calls() removes the folders of workers that were killed before their finally ran."""
    return tempfile.mkdtemp(prefix="call-%d-%s-" % (os.getpid(), _safe_id(job_id)), dir=ub_tmp_dir(ub_home))


STALE_CALL_S = 6 * 3600 + 600  # longer than any per-kind timeout plus 10 minutes
_CALL_DIR_RE = re.compile(r"^call-(\d+)-")
# The secret files of profiles/launch.py (its SECRET_FILE_RE): a launcher's settings or MCP file with a provider token.
# launch.py records its own process identity next to each one, in <file>.id (its IDENT_SUFFIX).
_LAUNCH_FILE_RE = re.compile(r"^(launch|zai-mcp)-(\d+)-[0-9a-f]{12}\.json$")
_LAUNCH_ID_SUFFIX = ".id"


def _launcher_gone(pid, path, mtime):
    """True when the launcher that wrote the secret file path (at mtime) no longer runs: its pid is free, or the
    process that holds the pid now is not the one recorded in path.id (a reused pid). The same rule as profiles/
    launch.py's sweep: only identities of the same kind are compared (Windows, Linux and macOS `ps` identities do not
    change with a clock step, and ps runs in UTC). A file without an .id (an older launcher) is judged by the Windows
    creation time, which no clock step moves; elsewhere it is kept while its pid runs. An unknown identity keeps the
    file."""
    if not proc.pid_alive(pid):
        return True
    now = proc.process_identity(pid)
    if not now:
        return False
    try:
        with open(path + _LAUNCH_ID_SUFFIX, "r", encoding="utf-8") as f:
            recorded = f.read().strip()
    except (OSError, ValueError):
        recorded = ""
    kind = now.split(":", 1)[0]
    if recorded:
        return recorded != now and recorded.split(":", 1)[0] == kind
    if kind == "win":
        started = proc.process_start_time(pid)
        return started is not None and started > mtime + 1.0
    return False


def sweep_stale_calls(ub_home, max_age_s=STALE_CALL_S):
    """Delete what killed processes left in UB_HOME/tmp: call-<pid>-* folders whose worker is gone (or that are older
    than max_age_s), and launch-<pid>-* / zai-mcp-<pid>-* files of launchers that ended without cleanup (never by age:
    an interactive session can run longer), each with its .id file. They can hold a provider token (settings-*.json, a
    launcher's settings or MCP file) or a prompt. An .id file whose secret file is already gone is left to
    profiles/launch.py's own sweep. Returns the number removed; never raises."""
    removed = 0
    try:
        tmp = os.path.join(ub_home, "tmp")
        names = os.listdir(tmp)
    except (OSError, TypeError):
        return 0
    now = time.time()
    for name in names:
        launch = _LAUNCH_FILE_RE.match(name)
        if not launch and not name.startswith("call-"):
            continue
        path = os.path.join(tmp, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        m = launch or _CALL_DIR_RE.match(name)
        try:
            if launch:
                stale = _launcher_gone(int(m.group(2)), path, mtime)
            else:
                stale = bool(m) and not proc.pid_alive(int(m.group(1)))
        except (ValueError, OSError):
            stale = False
        if stale or (not launch and now - mtime > max_age_s):
            remove_quietly(path)
            if not os.path.lexists(path):
                removed += 1
                if launch:
                    remove_quietly(path + _LAUNCH_ID_SUFFIX)
    return removed


_PRINCIPAL = []


def user_principal():
    """The icacls principal for the current user: '*<SID>' (from whoami /user), else DOMAIN\\USER, else USER."""
    if _PRINCIPAL:
        return _PRINCIPAL[0]
    val = None
    who = proc.system_tool("whoami")
    if who:
        try:
            cp = subprocess.run([who, "/user", "/fo", "csv", "/nh"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            m = re.search(r"(S-1-[0-9-]+)", cp.stdout.decode("utf-8", "replace"))
            if cp.returncode == 0 and m:
                val = "*" + m.group(1)
        except (OSError, subprocess.SubprocessError):
            val = None
    if not val:
        user = os.environ.get("USERNAME") or ""
        if not user:
            import getpass
            user = getpass.getuser()
        dom = os.environ.get("USERDOMAIN") or ""
        val = ("%s\\%s" % (dom, user)) if dom else user
    _PRINCIPAL.append(val)
    return val


def _icacls_restrict(path):
    exe = proc.system_tool("icacls")
    if not exe:
        raise OSError("icacls not found in %SystemRoot%\\System32")
    user = user_principal()
    cp = subprocess.run([exe, path, "/inheritance:r", "/grant:r", "%s:F" % user],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if cp.returncode != 0:
        raise OSError("icacls could not restrict %s (exit %d)" % (os.path.basename(path), cp.returncode))


def write_secret_file(path, text):
    """Create path with permission 0600 (Windows: icacls /inheritance:r /grant:r USER:F) BEFORE writing text.

    The caller deletes it in a finally block (remove_quietly). Raises OSError when the file cannot be secured.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    try:
        if os.name == "nt":
            _icacls_restrict(path)
        else:
            os.chmod(path, 0o600)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except BaseException:
        remove_quietly(path)
        raise
    return path


def remove_quietly(path):
    if not path:
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.lexists(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- process helper

def unsafe_argument_message(ctx, argv, exc):
    """The reason for a .cmd/.bat shim refusal, naming the kit path (or config value) that holds the character and
    the fix."""
    exe = os.path.basename(str(argv[0]))
    for i, a in enumerate(argv[1:], 1):
        bad = sorted(set(ch for ch in str(a) if ch in proc.CMD_UNSAFE_CHARS))
        if not bad:
            continue
        shown = ", ".join("CR" if c == "\r" else "LF" if c == "\n" else repr(c) for c in bad)
        for label, root, fix in (
                ("the run folder", ctx.run_dir, "move the project to a folder without these characters"),
                ("the repository", ctx.repo_root, "move the repository to a folder without these characters"),
                ("UB_HOME", ctx.ub_home, "set UB_HOME to a folder without these characters")):
            try:
                hit = bool(root) and filesproto.inside(root, a)
            except (TypeError, ValueError):  # e.g. an embedded NUL: not a path
                hit = False
            if hit:
                return ("%s (%s) contains %s, which cannot pass through the %s shim (cmd.exe re-parses it); %s"
                        % (label, textio.to_posix(root), shown, exe, fix))
        return ("argument %d for %s (a configured value) contains %s, which cannot pass through a .cmd/.bat shim; "
                "change it in UB_HOME/families.json" % (i, exe, shown))
    return str(exc)


def run_process(ctx, argv, env, cwd, stdin_bytes, secrets=(), stream=None):
    """Run one CLI attempt through proc.run. Returns (ProcResult or None, failure call-result or None, cmd str).
    stream: a JsonLines that receives the stdout lines as they arrive (codex, kimi); else stdout is buffered.
    A failure returned here happened before the CLI started (requests 0), or the CLI printed more than its stdout cap
    (stdout_cap): its tree was killed and the attempt is "invalid" (bad_output, requests 1), never parsed from the
    truncated stream and final for the job (no retry, repair or next backend: the same flood would follow)."""
    cmd = redact.format_cmd(argv, secrets)
    cap = stdout_cap(ctx, stream is not None)
    try:
        pr = proc.run(argv, cwd=cwd, env=env, stdin_bytes=stdin_bytes, timeout_s=ctx.timeout_s, max_stdout=cap,
                      on_line=stream.on_line if stream is not None else None)
    except proc.ExecutableNotFound as e:
        return None, result("unavailable", error_class="not_found", error=str(e), cmd=cmd), cmd
    except proc.UnsafeArgument as e:
        # a kit path or config value that a .cmd shim cannot pass: a setup problem, never retried
        return None, result("unavailable", error_class="config", error=unsafe_argument_message(ctx, argv, e),
                            cmd=cmd, retryable=False), cmd
    except OSError as e:
        return None, result("failed", error_class="internal", error="could not start %s: %s"
                            % (os.path.basename(argv[0]), e.__class__.__name__), cmd=cmd), cmd
    if getattr(pr, "overflow", False):  # checked before timed_out: both can be set
        return None, result("invalid", error_class="bad_output", error="%s printed more than the %s MB stdout cap; "
                            "its process tree was killed" % (os.path.basename(argv[0]),
                                                             ("%.1f" % (cap / 1048576.0)).rstrip("0").rstrip(".")),
                            exit_code=pr.returncode, cmd=cmd, stderr_tail=tail(decode(pr.stderr_bytes)),
                            requests=1, retryable=False), cmd
    return pr, None, cmd


def decode(raw):
    return textio.decode_bytes(raw or b"")


def module_for(btype):
    """The backend module for a backend type."""
    if btype == "claude-cli":
        from . import claude_cli as m
    elif btype == "codex-cli":
        from . import codex_cli as m
    elif btype == "kimi-cli":
        from . import kimi_cli as m
    elif btype == "openai-chat-http":
        from . import http_openai as m
    elif btype == "anthropic-http":
        from . import http_anthropic as m
    elif btype == "stub":
        from . import stub as m
    else:
        raise KeyError("unknown backend type %r" % btype)
    return m

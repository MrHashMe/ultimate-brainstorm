"""Model backends: shared call context, environment policy, error classes, secret temp files (KIT_SPEC 5.2-5.4).

Every backend module exposes:
    run(ctx) -> dict            one attempt; never raises for model/process failures
    build_argv(ctx, paths)      (CLI backends) the exact argv of 5.2, for tests and `family.py explain`
and goes through ublib.proc.run (the single process seam) for processes.

The result dict of one attempt ("call result"):
    {"status": "ok|failed|timeout|unavailable|refused", "text": str|None, "error_class": None|<4.7 class>,
     "error": str, "exit_code": int|None, "usage": {...}, "cmd": str (redacted), "stderr_tail": str,
     "model": str|None, "web_used": bool}
"""

import os
import re
import shutil
import subprocess
import tempfile
import time

try:
    from urllib.parse import urlparse
except ImportError:  # pragma: no cover
    from urlparse import urlparse  # type: ignore

from .. import proc
from .. import redact
from .. import textio

__all__ = ["CallContext", "DENY_EXACT", "DENY_PREFIXES", "scrub_env", "child_env", "classify_error", "result",
           "usage_block", "write_secret_file", "remove_quietly", "ub_tmp_dir", "new_call_dir", "module_for",
           "run_process", "host_of", "is_anthropic_url", "tools_has", "STDERR_TAIL", "ERROR_CLASSES", "STATUSES",
           "sweep_stale_calls", "user_codex_home", "is_ub_codex_home", "user_principal"]

STATUSES = ("ok", "failed", "invalid", "timeout", "refused", "unavailable")
ERROR_CLASSES = ("auth", "network", "rate_limit", "timeout", "bad_output", "policy", "not_found", "sandbox_network",
                 "internal")
STDERR_TAIL = 2000

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
        self.dry = bool(kw.get("dry"))

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


def _get(env, name):
    if os.name == "nt":
        up = name.upper()
        for k, v in env.items():
            if k.upper() == up:
                return v
        return None
    return env.get(name)


def host_of(url):
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def is_anthropic_url(url):
    h = host_of(url)
    return h == "anthropic.com" or h.endswith(".anthropic.com")


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
    elif btype == "codex-cli":
        if ctx.bcfg.get("codex_home"):
            from .. import families
            env["CODEX_HOME"] = families.expand_path(ctx.bcfg["codex_home"], ctx.ub_home)
            tok = ctx.bcfg.get("token_env")
            if tok:
                add_back(tok)
        else:
            for n in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
                add_back(n)
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

_AUTH_RE = re.compile(r"(\b40[13]\b|unauthori[sz]ed|forbidden|invalid[ _-]?(?:x-)?api[ _-]?key|api key.*invalid|"
                      r"not logged in|please log ?in|\blog ?in\b|\blogin\b|authenticat|credential|"
                      r"permission denied.*(?:token|key))", re.I)
_RATE_RE = re.compile(r"(\b429\b|rate[ _-]?limit|too many requests|quota|overloaded|\b529\b)", re.I)
_SANDBOX_RE = re.compile(r"(sandbox.*(?:network|denied|blocked)|network.*(?:sandbox|restricted|disabled)|"
                         r"operation not permitted \(os error 1\))", re.I)  # [U-8]
_NETWORK_RE = re.compile(r"(enotfound|econnrefused|econnreset|etimedout|eai_again|getaddrinfo|network error|"
                         r"connection (?:refused|reset|error|closed)|could not resolve|unable to connect|"
                         r"failed to connect|dns|ssl|certificate|socket hang up|fetch failed)", re.I)
_NOTFOUND_RE = re.compile(r"(command not found|is not recognized as an internal|no such file or directory.*(?:claude|"
                          r"codex|kimi)|model.*not found|unknown model|model_not_found)", re.I)


def classify_error(text, default="internal"):
    """Map error text (stderr, an error message, an error event) to a 4.7 error_class."""
    t = text or ""
    if _AUTH_RE.search(t):
        return "auth"
    if _RATE_RE.search(t):
        return "rate_limit"
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
           model=None, web_used=False):
    return {"status": status, "text": text, "error_class": error_class, "error": error or "", "exit_code": exit_code,
            "usage": usage or usage_block(), "cmd": cmd or "", "stderr_tail": stderr_tail or "", "model": model,
            "web_used": bool(web_used)}


def tail(text, n=STDERR_TAIL):
    text = text or ""
    return text[-n:] if len(text) > n else text


def tools_has(tools, what):
    return what in (tools or "none").split("+")


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


def sweep_stale_calls(ub_home, max_age_s=STALE_CALL_S):
    """Delete UB_HOME/tmp/call-<pid>-* folders whose worker is gone (or that are older than max_age_s). They can hold
    a provider token (settings-*.json) or a prompt when a worker was killed (ub stop, SIGTERM, timeout, crash).
    Returns the number removed; never raises."""
    removed = 0
    try:
        tmp = os.path.join(ub_home, "tmp")
        names = os.listdir(tmp)
    except (OSError, TypeError):
        return 0
    now = time.time()
    for name in names:
        if not name.startswith("call-"):
            continue
        path = os.path.join(tmp, name)
        try:
            age = now - os.path.getmtime(path)
        except OSError:
            continue
        m = _CALL_DIR_RE.match(name)
        dead = False
        if m:
            try:
                dead = not proc.pid_alive(int(m.group(1)))
            except (ValueError, OSError):
                dead = False
        if dead or age > max_age_s:
            remove_quietly(path)
            if not os.path.lexists(path):
                removed += 1
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

def run_process(ctx, argv, env, cwd, stdin_bytes, secrets=()):
    """Run one CLI attempt through proc.run. Returns (ProcResult or None, failure call-result or None, cmd str)."""
    cmd = redact.format_cmd(argv, secrets)
    try:
        pr = proc.run(argv, cwd=cwd, env=env, stdin_bytes=stdin_bytes, timeout_s=ctx.timeout_s)
    except proc.ExecutableNotFound as e:
        return None, result("unavailable", error_class="not_found", error=str(e), cmd=cmd), cmd
    except proc.UnsafeArgument as e:
        return None, result("failed", error_class="internal", error=str(e), cmd=cmd), cmd
    except OSError as e:
        return None, result("failed", error_class="internal", error="could not start %s: %s"
                            % (os.path.basename(argv[0]), e.__class__.__name__), cmd=cmd), cmd
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

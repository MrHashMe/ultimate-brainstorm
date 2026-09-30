"""CLI / key / endpoint detection, reclassification and live preflight (KIT_SPEC 4.8, 5.5).

Frozen API (4.8):
    detect(cfg=None, live=False, only=None) -> dict      shape: see 4.8 "detect --json shape"

Extras: endpoint_family(url), claude_settings(env), claude_settings_endpoint(env), claude_user_context(bcfg,
        family, env), claude_carried_settings(env, provider), claude_worker_memory(ub_home), codex_config_family(env),
        codex_mcp_servers(codex_home, unsafe), codex_mcp_unread(codex_home), codex_user_instructions(env),
        kimi_model_family(env, model, env_model), kimi_mislabel(bcfg, env, models), read_toml(path, unread),
        shim_path_problem(exe_path, ub_home, run_dir, repo_root), cli_info(name, env), version_tuple(text), KEY_NAMES,
        LEGACY_KIMI_NOTE, USER_CONTEXT_NOTE.
"""

import concurrent.futures
import json
import os
import re
import shutil
import tempfile
import time

from . import families as fam
from . import proc
from . import textio
from .backends import PROVIDER_DENY, scrub_env, host_of, user_codex_home

__all__ = ["detect", "endpoint_family", "claude_settings", "claude_settings_endpoint", "claude_user_context",
           "claude_carried_settings", "claude_worker_memory", "codex_config_family", "codex_mcp_servers",
           "codex_mcp_unread", "codex_user_instructions", "kimi_model_family", "kimi_mislabel", "read_toml",
           "shim_path_problem", "cli_info", "version_tuple", "KEY_NAMES", "LEGACY_KIMI_NOTE", "PING_PROMPT",
           "WEB_PROBE_PROMPT", "USER_CONTEXT_NOTE"]

KEY_NAMES = ("ZAI_API_KEY", "ZAI_PAYG_API_KEY", "KIMI_API_KEY", "KIMI_CODE_API_KEY", "OPENAI_API_KEY",
             "ANTHROPIC_API_KEY")
LEGACY_KIMI_NOTE = "upgrade: npm install -g @moonshot-ai/kimi-code, then kimi migrate"
KIMI_LOGIN_NOTE = "run: kimi login"
PING_PROMPT = "Reply with the single word PONG."
# [U-5] live check that `codex exec -c web_search=live` really searches: one search, one URL back.
WEB_PROBE_PROMPT = ("Use your web search tool once to find the official Python website, then reply with only the full "
                    "https URL of the search result you used. If you cannot search the web, reply with exactly: "
                    "NO WEB ACCESS")
_NO_WEB_RE = re.compile(r"(cannot|can't|can not|unable to|don't have|do not have|no)\s+(web|browse|search|access "
                        r"(to )?the (web|internet)|internet)|NO WEB ACCESS", re.I)
KIMI_GLM_NOTE = "Kimi Code is configured for GLM (not a GLM-supported tool)"
KIMI_FOREIGN_NOTE = "Kimi Code is configured for %s (%s); only a Kimi endpoint serves the kimi family"
# The endpoint of a Kimi Code provider `type` whose table has no base_url (Kimi Code's providers.md: base_url is
# optional for every type). An unknown type stays None.  # [U-34] config layout
_KIMI_TYPE_URL = {"kimi": "https://api.moonshot.ai/v1", "anthropic": "https://api.anthropic.com",
                  "openai": "https://api.openai.com/v1", "openai_responses": "https://api.openai.com/v1",
                  "google-genai": "https://generativelanguage.googleapis.com",
                  "vertexai": "https://aiplatform.googleapis.com"}
# The key of a provider's [providers.<p>.env] sub-table that Kimi Code reads as its base_url when the table has none
# (Kimi Code's overrides.md and env-vars.md).  # [U-34] config layout
_KIMI_TYPE_ENV = {"kimi": "KIMI_BASE_URL", "anthropic": "ANTHROPIC_BASE_URL", "openai": "OPENAI_BASE_URL",
                  "openai_responses": "OPENAI_BASE_URL"}
KIMI_HOST_GLM_NOTE = "GLM plan keys are not used from a Kimi Code host"
VERSION_TIMEOUT_S = 15
PING_TIMEOUT_S = 60
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_LOGIN_FIX = {"claude-cli": "run `claude` once and sign in", "codex-cli": "run: codex login",
              "kimi-cli": KIMI_LOGIN_NOTE}
_CODEX_HOME_SETUP = {"glm": "setup-glm", "kimi": "setup-kimi"}  # codex-cli@<p>: the install.py command for its home
USER_CONTEXT_NOTE = "user context: "  # prefix of the notes that say which user instructions reach worker calls
# Keys of the user's Claude settings.json that can carry the login or the route of a claude-cli call. An isolated
# call gets them through its own --settings file (claude_carried_settings).
_CLAUDE_ROUTE_KEYS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "env")
_MCP_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MEMORY_FILES = ("CLAUDE.md", "CLAUDE.local.md")  # the project memory files Claude Code reads from cwd upwards


# ---------------------------------------------------------------- helpers

def version_tuple(text):
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    return tuple(int(x) for x in (m.group(1), m.group(2), m.group(3) or "0"))


def _version_str(t):
    return ".".join(str(x) for x in t) if t else None


def endpoint_family(url):
    """Which family an endpoint URL serves (5.5): None/anthropic.com -> claude; z.ai/bigmodel.cn -> glm;
    moonshot/kimi.ai/kimi.com -> kimi; *.openai.com and Azure OpenAI (*.openai.azure.com) -> gpt; any other host ->
    "custom:<host>"."""
    if not url:
        return "claude"
    h = host_of(url) or str(url).lower()
    if h == "anthropic.com" or h.endswith(".anthropic.com"):
        return "claude"
    if h == "z.ai" or h.endswith(".z.ai") or "bigmodel.cn" in h:
        return "glm"
    if "moonshot" in h or h.endswith("kimi.ai") or h.endswith("kimi.com"):
        return "kimi"
    if h == "openai.com" or h.endswith(".openai.com") or h.endswith(".openai.azure.com"):
        return "gpt"
    return "custom:%s" % h


def _home():
    return os.path.expanduser("~")


def _claude_dir(env):
    d = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(_home(), ".claude")


def claude_settings(env=None):
    """(the user's Claude settings.json as a dict, or None when it is missing or unreadable; its path)."""
    env = os.environ if env is None else env
    path = os.path.join(_claude_dir(env), "settings.json")
    if not os.path.isfile(path):
        return None, path
    try:
        data = textio.read_json(path)
    except (OSError, ValueError):
        return None, path
    return (data if isinstance(data, dict) else None), path


def claude_settings_endpoint(env=None):
    """(ANTHROPIC_BASE_URL from the Claude settings file or None, settings path)."""
    data, path = claude_settings(env)
    block = data.get("env") if isinstance(data, dict) else None
    url = block.get("ANTHROPIC_BASE_URL") if isinstance(block, dict) else None
    return (url if isinstance(url, str) and url.strip() else None), path


def claude_user_context(bcfg, family, env=None):
    """"isolate" when a claude-cli worker call skips the user's settings sources (argv --setting-sources project:
    no user settings, hooks, plugins or user memory), else "inherit".  # [U-43]

    Backend key "user_context": "auto" (default) and "isolate" isolate: what can carry the login or the route
    (claude_carried_settings) goes into the call's own --settings file instead [U-43]. "inherit" never isolates, and a
    native claude-cli seated for another family (reclassified through the user's settings.json) always inherits: that
    file is its route. env: unused (the decision no longer depends on the user's settings)."""
    bcfg = bcfg or {}
    mode = bcfg.get("user_context") or "auto"
    if mode == "inherit" or (not bcfg.get("provider") and family and family != "claude"):
        return "inherit"
    return "isolate"


def claude_carried_settings(env=None, provider=False):
    """What an isolated claude-cli call takes over from the user's settings.json into its own 0600 --settings file, so
    that skipping the user's settings sources keeps the login and the route; {} when nothing applies.  # [U-43]

    Native backend: the keys apiKeyHelper, awsAuthRefresh, awsCredentialExport and env (only an object), as they are
    (the label check already refuses a call whose settings.json routes to another family). Provider backends (their
    route and token are the provider's): only the env entries a child environment keeps (5.3: never ANTHROPIC_*, a
    vendor key, a model or cloud switch) and no helper command (it would hand the user's own credentials to the
    provider)."""
    data, _path = claude_settings(env)
    if not isinstance(data, dict):
        return {}
    if not provider:
        return dict((k, data[k]) for k in _CLAUDE_ROUTE_KEYS
                    if data.get(k) and (k != "env" or isinstance(data[k], dict)))
    block = data.get("env") if isinstance(data.get("env"), dict) else {}
    kept = dict((k, v) for k, v in scrub_env(block).items()
                if isinstance(k, str) and isinstance(v, str) and k.upper() not in PROVIDER_DENY)
    return {"env": kept} if kept else {}


def claude_worker_memory(ub_home):
    """The CLAUDE.md / CLAUDE.local.md files in the folders above the empty folder claude-cli workers run in
    (UB_HOME/tmp/call-*/ub-empty). Claude Code reads project memory from its working folder up to (not including) the
    root, so these reach every such call whatever user_context says; detect reports them."""
    out = []
    d = os.path.abspath(os.path.join(ub_home, "tmp"))
    while os.path.dirname(d) != d:
        for name in _MEMORY_FILES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                out.append(path)
        d = os.path.dirname(d)
    return out


def _codex_dir(env, raw=False):
    """The Codex home. raw=False (the native codex-cli backend): the user's own home, never a UB-owned
    codex-homes/<p> that a codex-glm / codex-kimi launcher exported (UB_USER_CODEX_HOME holds the original).
    raw=True: CODEX_HOME exactly as set (what the Codex host process itself uses)."""
    if raw:
        d = (env.get("CODEX_HOME") or "").strip()
    else:
        d = (user_codex_home(env, fam.ub_home()) or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(_home(), ".codex")


# The TOML reading without tomllib: one token per match (whitespace and comments are dropped).
_TOML_TOKEN_RE = re.compile(r'(?P<ws>[ \t\r]+)|(?P<nl>\n)|(?P<comment>#[^\n]*)'
                            r'|(?P<mls>"""(?:[^"\\]|\\[\s\S]|"(?!""))*"{3,5}|\'\'\'[\s\S]*?\'{3,5})'
                            r'|(?P<str>"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\')'
                            r'|(?P<punct>[\[\]{}=,.])|(?P<bare>[^\s\[\]{}=,.#"\']+)')
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TOML_END = ("end", "", 0)
_TOML_MAX_DEPTH = 128  # arrays and inline tables nested deeper are not read (Python's recursion limit is near)
_TOML_U_ESCAPE_RE = re.compile(r"\\(\\|U([0-9A-Fa-f]{8}))")


def _json_u_escape(m):
    """A \\UXXXXXXXX escape as JSON's \\uXXXX (a surrogate pair above U+FFFF); an escaped backslash stays."""
    if not m.group(2):  # an escaped backslash
        return m.group(0)
    cp = int(m.group(2), 16)
    if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:  # no character: json.loads then rejects the escape as written
        return m.group(0)
    if cp < 0x10000:
        return "\\u%04x" % cp
    cp -= 0x10000
    return "\\u%04x\\u%04x" % (0xD800 + (cp >> 10), 0xDC00 + (cp & 0x3FF))


def _toml_str(tok):
    """The value of a string token (the escapes of a multi-line basic string are kept as written)."""
    if tok[:3] in ('"""', "'''"):
        body = tok[3:-3]
        return body[2:] if body.startswith("\r\n") else body[1:] if body.startswith("\n") else body
    if tok[0] == "'":
        return tok[1:-1]
    try:
        return json.loads(_TOML_U_ESCAPE_RE.sub(_json_u_escape, tok), strict=False)
    except ValueError:  # a TOML 1.1 escape (\e, \x) or an invalid one: kept as written
        return tok[1:-1]


def _toml_put(table, path, value):
    """table[path[0]]...[path[-1]] = value, creating the tables between; ValueError when a value is in the way."""
    for k in path[:-1]:
        table = table.setdefault(k, {})
        if not isinstance(table, dict):
            raise ValueError(k)
    table[path[-1]] = value


class _TomlSubset(object):
    """The TOML reading without tomllib (Python 3.9/3.10, and a text tomllib rejects): tables, dotted and quoted
    keys, strings (multi-line ones too), arrays and inline tables, over any number of lines; every other value is kept
    as its text, and [[array tables]] are skipped. A statement it cannot read (also one nesting arrays and inline tables
    deeper than _TOML_MAX_DEPTH) is skipped and its line number listed in .unread, so no key is ever read from inside a
    string or from a broken line."""

    def __init__(self, text):
        self.toks, self.i, self.data, self.unread = [], 0, {}, []
        pos, line = 0, 1
        while pos < len(text):
            m = _TOML_TOKEN_RE.match(text, pos)
            kind, val = (m.lastgroup, m.group()) if m else ("bad", text[pos])
            if kind not in ("ws", "comment"):
                self.toks.append((kind, val, line))
            line += val.count("\n")
            pos += len(val)
        table = self.data
        while self.peek() is not _TOML_END:
            if self.peek()[0] == "nl":
                self.i += 1
                continue
            start = self.i
            header = self.peek()[1] == "["
            try:
                if header:
                    table = {}  # the keys under a header that cannot be read go nowhere
                    table = self.header()
                else:
                    path = self.key()
                    self.take("=")
                    _toml_put(table, path, self.value())
                if self.peek()[0] not in ("nl", "end"):
                    raise ValueError("text after the statement")
            except ValueError:
                self.unread.append(self.toks[start][2])
                self.i = start
                self.skip(header)

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else _TOML_END

    def take(self, want=None):
        tok = self.peek()
        if tok is _TOML_END or tok[0] == "bad" or (want is not None and tok[1] != want):
            raise ValueError(tok[1])
        self.i += 1
        return tok

    def skip(self, header):
        """Past the statement at self.i: its line (a header), else up to a line end outside brackets."""
        depth = 0
        while self.peek() is not _TOML_END:
            kind, val, _line = self.toks[self.i]
            self.i += 1
            if kind == "nl" and (header or depth <= 0):
                return
            if kind == "punct" and val in "[{":
                depth += 1
            elif kind == "punct" and val in "]}":
                depth -= 1

    def skip_nl(self):
        while self.peek()[0] == "nl":
            self.i += 1

    def header(self):
        self.take("[")
        if self.peek()[1] == "[":  # [[an array of tables]]: not read
            self.take("[")
            self.key()
            self.take("]")
            self.take("]")
            return {}
        path = self.key()
        self.take("]")
        table = self.data
        for k in path:
            table = table.setdefault(k, {})
            if not isinstance(table, dict):
                raise ValueError(k)
        return table

    def key(self):
        path = [self.segment()]
        while self.peek()[1] == ".":
            self.i += 1
            path.append(self.segment())
        return path

    def segment(self):
        kind, val, _line = self.take()
        if kind == "str":
            return _toml_str(val)
        if kind == "bare" and _BARE_KEY_RE.match(val):
            return val
        raise ValueError(val)

    def value(self, depth=0):
        """The value at self.i; depth: the arrays and inline tables around it."""
        kind, val, _line = self.take()
        if kind in ("str", "mls"):
            return _toml_str(val)
        if kind == "bare":  # a number, boolean or date, as its text (a float's dot is a token of its own)
            while self.peek()[0] == "bare" or self.peek()[1] == ".":
                val += self.take()[1]
            return val
        if val not in ("[", "{"):
            raise ValueError(val)
        if depth >= _TOML_MAX_DEPTH:
            raise ValueError("nested deeper than %d levels" % _TOML_MAX_DEPTH)
        close, out = ("]", []) if val == "[" else ("}", {})
        self.skip_nl()  # an inline table over several lines is TOML 1.1, which Codex may accept
        while self.peek()[1] != close:
            if close == "]":
                out.append(self.value(depth + 1))
            else:
                path = self.key()
                self.take("=")
                _toml_put(out, path, self.value(depth + 1))
            self.skip_nl()
            if self.peek()[1] != close:
                self.take(",")
                self.skip_nl()
        self.take(close)
        return out


def _parse_toml(text, unread=None):
    """tomllib (3.11+), else _TomlSubset (enough for the keys the kit reads: providers, profiles, models, MCP server
    names). unread (a list): gets the line numbers of the statements _TomlSubset could not read."""
    try:
        import tomllib  # 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - TOML that tomllib rejects falls through to the subset reading
        pass
    reader = _TomlSubset(text)
    if unread is not None:
        unread.extend(reader.unread)
    return reader.data


def read_toml(path, unread=None):
    """A TOML file as a dict (tomllib, or the subset reading on 3.9/3.10 and for a file tomllib rejects); None when
    the file is missing or unreadable. unread: see _parse_toml."""
    if not path or not os.path.isfile(path):
        return None
    try:
        data = _parse_toml(textio.read_text(path), unread)
    except OSError:
        return None
    return data if isinstance(data, dict) else None


def _table(data, *keys):
    for k in keys:
        data = data.get(k) if isinstance(data, dict) and isinstance(k, str) else None
    return data if isinstance(data, dict) else {}


def codex_config_family(env=None, raw=False):
    """(family, provider, base_url, config path) of the native Codex CLI: $CODEX_HOME/config.toml (default ~/.codex),
    its default `profile` (profiles.<p>.model_provider wins over the top-level model_provider), and OPENAI_BASE_URL
    from env for the built-in openai provider. raw: see _codex_dir."""
    env = os.environ if env is None else env
    path = os.path.join(_codex_dir(env, raw), "config.toml")
    data = read_toml(path) or {}
    profile = _table(data, "profiles", data.get("profile"))
    provider = profile.get("model_provider") or data.get("model_provider")
    if not provider or str(provider).lower() == "openai":
        url = (env.get("OPENAI_BASE_URL") or "").strip()
        if url:
            return endpoint_family(url), provider, url, path
        return "gpt", provider, None, path
    provs = data.get("model_providers") if isinstance(data.get("model_providers"), dict) else {}
    pcfg = provs.get(provider) if isinstance(provs.get(provider), dict) else {}
    base = pcfg.get("base_url")
    p = str(provider).lower()
    if base:
        f = endpoint_family(base)
        if not f.startswith("custom:"):
            return f, provider, base, path
    if "zai" in p or "z.ai" in p or "bigmodel" in p or "glm" in p:
        return "glm", provider, base, path
    if "moonshot" in p or "kimi" in p:
        return "kimi", provider, base, path
    return "custom:%s" % (host_of(base) or p), provider, base, path


def codex_mcp_servers(codex_home, unsafe=False):
    """Names of the MCP servers (mcp_servers.<name>, as tables, inline tables or dotted keys) in
    <codex_home>/config.toml that are safe as a -c key path (Codex splits the path at every dot and reads no quotes);
    unsafe=True: the other names, which no override can reach. No name is safe when part of the file could not be read
    (codex_mcp_unread): a misread name would make Codex refuse its config on every call."""
    unread = []
    data = read_toml(os.path.join(codex_home, "config.toml"), unread) if codex_home else None
    if unread and not unsafe:
        return []
    return sorted(n for n in _table(data, "mcp_servers") if bool(_MCP_NAME_RE.match(n)) != bool(unsafe))


def codex_mcp_unread(codex_home):
    """The line numbers of <codex_home>/config.toml that the reading without tomllib could not read: then no MCP
    server is switched off per call (codex_mcp_servers), and detect says so."""
    unread = []
    if codex_home:
        read_toml(os.path.join(codex_home, "config.toml"), unread)
    return unread


def codex_user_instructions(env=None):
    """Path of the user's global Codex instructions ($CODEX_HOME/AGENTS.override.md or AGENTS.md, non-empty) that
    native codex-cli workers load, else None. No per-call override is known, so detect reports it."""
    env = os.environ if env is None else env
    home = _codex_dir(env)
    for name in ("AGENTS.override.md", "AGENTS.md"):
        p = os.path.join(home, name)
        try:
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
        except OSError:
            pass
    return None


def _probe_env():
    env = scrub_env(os.environ)
    env["NO_COLOR"] = "1"
    return env


def cli_info(name, env=None):
    """{"path", "version", "shim"} for one CLI: shutil.which + `<exe> --version` (15 s timeout)."""
    env = env or _probe_env()
    path = proc.resolve_exe(name, env)
    info = {"path": textio.to_posix(path) if path else None, "version": None,
            "shim": bool(path and path.lower().endswith((".cmd", ".bat", ".ps1")))}
    if not path:
        return info
    try:
        pr = proc.run([path, "--version"], cwd=None, env=env, stdin_bytes=None, timeout_s=VERSION_TIMEOUT_S)
        text = textio.decode_bytes(pr.stdout_bytes) + "\n" + textio.decode_bytes(pr.stderr_bytes)
        info["version"] = _version_str(version_tuple(text)) if not pr.timed_out else None
    except (proc.ProcError, OSError, ValueError):
        pass
    return info


def _kimi_home(env):
    d = (env.get("KIMI_CODE_HOME") or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(_home(), ".kimi-code")


def _kimi_logged_in(env, env_model=False):
    """A Kimi Code login, or KIMI_MODEL_* variables - the latter only when backends.kimi-cli.env_model is true,
    because 5.3 strips KIMI_MODEL_* from every child otherwise."""
    if os.path.isdir(os.path.join(_kimi_home(env), "credentials")):
        return True
    return bool(env_model) and bool((env.get("KIMI_MODEL_NAME") or "").strip())


def kimi_model_family(env=None, model=None, env_model=False):
    """(family or None, base_url or None, config path): the family whose endpoint serves the model a kimi-cli call
    uses. model: the `-m` name of the call (None: Kimi Code's default_model). env_model (backend key): a
    KIMI_MODEL_BASE_URL in env decides, and with KIMI_MODEL_NAME set and no URL, the default endpoint of
    KIMI_MODEL_PROVIDER_TYPE (default kimi). Else $KIMI_CODE_HOME/config.toml: models.<model>.provider ->
    providers.<p>.base_url (without one, the *_BASE_URL key of providers.<p>.env for its `type`, _KIMI_TYPE_ENV, then
    the type's default endpoint, _KIMI_TYPE_URL), and only when that names no provider table, the one family of every
    base_url line in the file. None when nothing names an endpoint (a missing or unreadable file, a provider of an
    unknown type without base_url).  # [U-34] config layout"""
    env = os.environ if env is None else env
    path = os.path.join(_kimi_home(env), "config.toml")
    url = (env.get("KIMI_MODEL_BASE_URL") or "").strip() if env_model else ""
    if not url and env_model and (env.get("KIMI_MODEL_NAME") or "").strip():
        # the provider Kimi Code builds from KIMI_MODEL_*: without a URL, the default endpoint of its type
        url = _KIMI_TYPE_URL.get((env.get("KIMI_MODEL_PROVIDER_TYPE") or "").strip() or "kimi") or ""
    if url:
        return endpoint_family(url), url, path
    if not os.path.isfile(path):
        return None, None, path
    try:
        text = textio.read_text(path)
    except OSError:
        return None, None, path
    data = _parse_toml(text)
    provider = _table(data, "providers", _table(data, "models", model or data.get("default_model")).get("provider"))
    if provider:
        t, base = str(provider.get("type")), None
        # Kimi Code's order: the table's base_url, the *_BASE_URL key of its env sub-table, the type's default
        for u in (provider.get("base_url"), _table(provider, "env").get(_KIMI_TYPE_ENV.get(t)), _KIMI_TYPE_URL.get(t)):
            if isinstance(u, str) and u.strip():
                base = u
                break
    else:
        urls = re.findall(r'^\s*base_url\s*=\s*["\']([^"\']+)["\']', text, re.M)
        base = urls[0] if len(set(endpoint_family(u) for u in urls)) == 1 else None
    if not isinstance(base, str) or not base.strip():
        return None, None, path
    return endpoint_family(base), base, path


def kimi_mislabel(bcfg, env=None, models=(None,)):
    """The note that makes a kimi-cli backend unavailable when Kimi Code would answer one of these `-m` names (None:
    its default model) from another family's endpoint (kimi_model_family), else None: KIMI_GLM_NOTE for GLM (never a
    Kimi Code route), otherwise KIMI_FOREIGN_NOTE. Only a Kimi endpoint, or none the kit can tell, serves kimi."""
    served = [kimi_model_family(env, m, bool((bcfg or {}).get("env_model"))) for m in models]
    if any(f == "glm" for f, _base, _path in served):
        return KIMI_GLM_NOTE
    for f, base, _path in served:
        if f not in (None, "kimi"):
            return KIMI_FOREIGN_NOTE % (f, host_of(base) or base)
    return None


# ---------------------------------------------------------------- main

def _families_in_scope(cfg, only):
    order = [f for f in (cfg.get("order") or []) if f in (cfg.get("families") or {})]
    for f in (cfg.get("families") or {}):
        if f not in order:
            order.append(f)
    if only:
        wanted = [fam.split_label(x)[0] for x in only]
        order = [f for f in order if f in wanted]
    return order


def _host(env, claude_ep, codex_fam):
    forced = (env.get("UB_HOST_FAMILY") or "").strip().lower()
    agent = (env.get("UB_HOST") or "").strip() or "other"
    if forced in fam.FAMILY_VENDORS:
        return {"agent": agent, "family": forced, "source": "env"}
    if agent == "claude-code":
        url = claude_ep or env.get("ANTHROPIC_BASE_URL")
        if url:
            f = endpoint_family(url)
            if f in fam.FAMILY_VENDORS:
                return {"agent": agent, "family": f, "source": "endpoint"}
    if agent == "codex":
        if codex_fam in fam.FAMILY_VENDORS and codex_fam != "gpt":
            return {"agent": agent, "family": codex_fam, "source": "endpoint"}
    return {"agent": agent, "family": fam.HOST_DEFAULT_FAMILY.get(agent), "source": "default"}


def shim_path_problem(exe_path, ub_home, run_dir=None, repo_root=None):
    """The reason a .cmd/.bat shim cannot run kit calls, else None: its own path, UB_HOME (every CLI call passes
    UB_HOME/tmp paths), the run folder (claude's run-folder deny rules) or the repository (codex -C) holds a cmd.exe
    metacharacter. The engine passes run_dir / repo_root only for families of the host's vendor in a repository run
    (ub.shim_problems, whenever it seats the run's families: at run creation, on a host change and for a migrated v1
    run); detection checks the shim and UB_HOME alone."""
    if not exe_path or not str(exe_path).lower().endswith((".cmd", ".bat")):
        return None
    exe = os.path.basename(str(exe_path))
    try:
        proc.check_cmd_args(exe_path, [])
    except proc.UnsafeArgument as e:
        return str(e)
    for label, path, fix in (("UB_HOME", ub_home, "set UB_HOME to a folder without these characters"),
                             ("the run folder", run_dir, "move the project to a folder without these characters"),
                             ("the repository", repo_root, "move the repository to a folder without these characters")):
        bad = sorted(set(ch for ch in str(path or "") if ch in proc.CMD_UNSAFE_CHARS))
        if bad:
            return ("%s (%s) contains %s, which the %s shim cannot receive (cmd.exe re-parses it); %s"
                    % (label, textio.to_posix(path), ", ".join(repr(c) for c in bad), exe, fix))
    return None


def _backend_status(cfg, bid, clis, env, claude_fam, codex_fam, kimi_ok):
    """(available: bool, serves: family or None, note: str) for one configured backend."""
    b = fam.backend_cfg(cfg, bid)
    t = b.get("type") or bid.split("@", 1)[0]
    if t in ("openai-chat-http", "anthropic-http"):
        if b.get("enabled") is False:
            return False, None, "%s disabled" % bid
        key_env = b.get("key_env")
        if not key_env or not (env.get(key_env) or "").strip():
            return False, None, "%s not set" % (key_env or "key_env")
        if not b.get("model"):
            return False, None, "%s has no model configured" % bid
        served = endpoint_family(b.get("url")) if b.get("url") else None
        return True, (served if served in fam.FAMILY_VENDORS else None), ""
    exe = b.get("exe") or t.split("-", 1)[0]
    info = clis.get(exe) or {}
    problem = shim_path_problem(info.get("path"), cfg.get("_ub_home") or fam.ub_home())
    if problem:
        return False, None, problem
    provider = b.get("provider")
    if t == "claude-cli":
        if provider:
            try:
                tok, _var, token = fam.provider_token(cfg, provider, env)
            except ValueError as e:  # a hand-edited entry of the wrong shape: this provider only, never a crash
                return False, None, str(e)
            if not token:
                return False, None, "%s not set" % (tok or "token_env")
            if not fam.provider_settings_env(cfg, provider).get("ANTHROPIC_BASE_URL"):  # the worker refuses it too
                return False, None, "provider %s has no base_url in families config" % provider
            if not info.get("path"):
                return False, None, "%s not on PATH" % exe
            return True, None, ""
        if not info.get("path"):
            return False, None, "%s not on PATH" % exe
        if not _min_ok(info, b):
            return False, None, "%s older than %s" % (exe, b.get("min_version"))
        return True, claude_fam, ""
    if t == "codex-cli":
        if b.get("codex_home"):
            tok = b.get("token_env")
            if tok and not (env.get(tok) or "").strip():
                return False, None, "%s not set" % tok
            if not info.get("path"):
                return False, None, "%s not on PATH" % exe
            if not _min_ok(info, b):
                return False, None, "%s older than %s" % (exe, b.get("min_version"))
            home = fam.expand_path(b["codex_home"], cfg.get("_ub_home"))
            if not os.path.isdir(home):
                setup = _CODEX_HOME_SETUP.get(provider or bid.partition("@")[2])
                return False, None, ("codex home missing: run install.py %s --codex" % setup if setup
                                     else "codex home %s missing" % textio.to_posix(home))
            return True, None, ""
        if not info.get("path"):
            return False, None, "%s not on PATH" % exe
        if not _min_ok(info, b):
            return False, None, "%s older than %s" % (exe, b.get("min_version"))
        return True, codex_fam, ""
    if t == "kimi-cli":
        if not info.get("path"):
            return False, None, "%s not on PATH" % exe
        if info.get("legacy"):
            return False, None, LEGACY_KIMI_NOTE
        if not kimi_ok:
            return False, None, KIMI_LOGIN_NOTE
        # every model its calls can pass: the configured one (None: Kimi Code's default), the fast tier's, alt seats'
        alts = [f.get("alt_model") for f in (cfg.get("families") or {}).values()
                if isinstance(f, dict) and bid in (f.get("backends") or [])]
        models = [b.get("model")] + [m for m in [b.get("fast_model")] + alts if m]
        note = kimi_mislabel(b, env, models)
        return (False, None, note) if note else (True, None, "")
    return False, None, "unknown backend type %s" % t


def _is_native(cfg, bid):
    """A CLI backend on the user's own login/config (no provider settings file, no private Codex home)."""
    b = fam.backend_cfg(cfg, bid)
    return (fam.backend_type(cfg, bid) in ("claude-cli", "codex-cli") and not b.get("provider")
            and not b.get("codex_home"))


def _user_context_notes(cfg, f, chain, env, memory=()):
    """Notes naming the user's own instructions that still reach this family's worker calls (28). memory: the
    claude_worker_memory() files."""
    notes = []
    for bid in chain:
        t, b = fam.backend_type(cfg, bid), fam.backend_cfg(cfg, bid)
        if t == "claude-cli" and memory:
            notes.append("%s%s workers read %s (project memory above their folder in UB_HOME/tmp)"
                         % (USER_CONTEXT_NOTE, bid, ", ".join(textio.to_posix(p) for p in memory)))
        if t == "claude-cli" and claude_user_context(b, f, env) == "inherit":
            why = ("its route is the user's settings.json" if not b.get("provider") and f != "claude"
                   else "user_context is inherit")
            notes.append("%s%s workers load the user's Claude settings, hooks, plugins and CLAUDE.md (%s)"
                         % (USER_CONTEXT_NOTE, bid, why))
        elif t == "codex-cli" and _is_native(cfg, bid):
            path = codex_user_instructions(env)
            if path:
                notes.append("%s%s workers load the user's Codex instructions %s" % (USER_CONTEXT_NOTE, bid,
                                                                                     textio.to_posix(path)))
            home = _codex_dir(env)
            left = codex_mcp_servers(home, unsafe=True)
            if left:
                notes.append("%s%s workers still start the MCP servers %s (a name with a character outside "
                             "A-Z a-z 0-9 _ - cannot be switched off per call; their tool calls are refused)"
                             % (USER_CONTEXT_NOTE, bid, ", ".join(left)))
            unread = codex_mcp_unread(home)
            if unread:
                notes.append("%s%s workers start every MCP server of %s: the kit could not read line %s of it "
                             "(Python 3.11+ reads any valid TOML), so no server is switched off per call; their tool "
                             "calls are refused" % (USER_CONTEXT_NOTE, bid,
                                                    textio.to_posix(os.path.join(home, "config.toml")),
                                                    ", ".join(str(n) for n in unread[:5])))
    return notes


def _min_ok(info, b):
    want = version_tuple(b.get("min_version") or "")
    have = version_tuple(info.get("version") or "")
    return not want or not have or have >= want


def detect(cfg=None, live=False, only=None):
    """Detect CLIs, keys, endpoints and the backend chain of every family (5.5). See 4.8 for the shape."""
    cfg = cfg or fam.load_families()
    env = os.environ
    scope = _families_in_scope(cfg, only)
    fake = fam.fake_families()
    forced_host = fam.fake_host_families()
    claude_ep, claude_settings_path = claude_settings_endpoint(env)
    codex_f, codex_prov, codex_base, codex_path = codex_config_family(env)
    if codex_base and (not codex_prov or str(codex_prov).lower() == "openai"):
        codex_path = "OPENAI_BASE_URL"  # the built-in openai provider pointed elsewhere by the environment
    host_codex_f = codex_config_family(env, raw=True)[0]
    out = {"schema": 1, "generated_at": textio.now_iso(), "fake": fake,
           "host": _host(env, claude_ep, host_codex_f),
           "clis": {}, "keys": {k: bool((env.get(k) or "").strip()) for k in KEY_NAMES},
           "families": {}, "reclassified": [], "live": {}}

    # Which CLIs matter for the families in scope.
    needed = []
    for f in scope:
        for bid in ((cfg.get("families") or {}).get(f) or {}).get("backends") or []:
            b = fam.backend_cfg(cfg, bid)
            t = b.get("type") or ""
            if t.endswith("-cli"):
                exe = b.get("exe") or t.split("-", 1)[0]
                if exe not in needed:
                    needed.append(exe)
    if "claude" not in needed and any(f in scope for f in ("glm", "kimi")):
        needed.append("claude")  # a reclassified claude-cli may serve glm/kimi
    probe_env = _probe_env()
    for exe in ("claude", "codex", "kimi"):
        if fake or exe not in needed:
            info = {"path": None, "version": None, "shim": False}
        else:
            info = cli_info(exe, probe_env)
        if exe == "kimi":
            kv = version_tuple(info.get("version") or "")
            kmin = version_tuple(fam.backend_cfg(cfg, "kimi-cli").get("min_version") or "2.0.0")
            info["legacy"] = bool(kv and kmin and kv < kmin)
        out["clis"][exe] = info

    if fake:
        disabled = fam.fake_disabled()
        for f in scope:
            primary = ((((cfg.get("families") or {}).get(f) or {}).get("backends")) or [None])[0]
            web = fam.backend_web(cfg, primary) if primary else False
            if f in forced_host:
                chain, notes = ["host"], ["forced to host by UB_FAKE_HOST_BACKEND"]
            elif f in disabled:
                chain, notes = [], ["disabled by UB_FAKE_DISABLE"]
            else:
                chain, notes = ["stub"], []
            out["families"][f] = {"available": bool(chain), "backend": chain[0] if chain else None, "chain": chain,
                                  "web": bool(chain) and web and chain != ["host"], "vendor": fam.vendor_of(f, cfg),
                                  "notes": notes}
    else:
        claude_fam = endpoint_family(claude_ep)
        kimi_ok = _kimi_logged_in(env, bool(fam.backend_cfg(cfg, "kimi-cli").get("env_model")))
        statuses = {}
        for bid in (cfg.get("backends") or {}):
            statuses[bid] = _backend_status(cfg, bid, out["clis"], env, claude_fam, codex_f, kimi_ok)
        extras = {}
        # Reclassification: a native CLI whose own config points at another vendor serves that family.
        for bid, (ok, serves, _n) in statuses.items():
            if not ok or serves is None:
                continue
            if fam.backend_type(cfg, bid).endswith("-http"):
                continue  # an HTTP backend at another vendor's endpoint is dropped below, never re-seated
            native_family = {"claude-cli": "claude", "codex-cli": "gpt"}.get(fam.backend_type(cfg, bid))
            if serves != native_family:
                cli = fam.backend_type(cfg, bid).split("-", 1)[0]
                src = claude_settings_path if cli == "claude" else codex_path
                ep = claude_ep if cli == "claude" else (codex_base or "")
                out["reclassified"].append({"cli": cli, "source": textio.to_posix(src) if os.path.isabs(src) else src,
                                            "endpoint": host_of(ep) or ep, "as": serves})
                if serves in fam.FAMILY_VENDORS:
                    extras.setdefault(serves, []).append(bid)
        strict_glm = fam.strict_glm(cfg)
        memory = claude_worker_memory(cfg.get("_ub_home") or fam.ub_home())
        for f in scope:
            fcfg = (cfg.get("families") or {}).get(f) or {}
            native_family = {"claude-cli": "claude", "codex-cli": "gpt"}
            chain, notes = [], []
            for bid in fcfg.get("backends") or []:
                ok, serves, note = statuses.get(bid, (False, None, "unknown backend %s" % bid))
                nf = native_family.get(fam.backend_type(cfg, bid)) if _is_native(cfg, bid) else None
                if ok and nf and serves != nf:
                    ok, note = False, "%s is configured for %s (reclassified)" % (fam.backend_type(cfg, bid), serves)
                if ok and fam.backend_type(cfg, bid).endswith("-http") and serves and serves != f:
                    ok, note = False, "%s points at a %s endpoint (reclassified)" % (bid, serves)
                if ok and f == "glm" and out["host"].get("agent") == "kimi" and \
                        fam.backend_type(cfg, bid) in ("claude-cli", "codex-cli"):
                    ok, note = False, KIMI_HOST_GLM_NOTE  # 14: Kimi host nested families never carry GLM plan keys
                if ok:
                    chain.append(bid)
                elif note and note not in notes:
                    notes.append(note)
            for bid in extras.get(f, []):
                if bid not in chain:
                    chain.append(bid)
                    notes.append("%s reclassified as %s" % (bid, f))
            if f == "glm" and strict_glm:  # [U-20]
                dropped = [b for b in chain if fam.backend_type(cfg, b) in ("claude-cli", "codex-cli")]
                chain = [b for b in chain if b not in dropped]
                if dropped:
                    notes.append("allow_scripted_plan_use is false: GLM runs only as the host family")
                if out["host"]["family"] == "glm":
                    chain = ["host"] + chain
            if f in forced_host:
                chain = ["host"]
                notes.append("forced to host by UB_FAKE_HOST_BACKEND")
            notes += _user_context_notes(cfg, f, chain, env, memory)
            if chain:
                notes = [n for n in notes if "reclassified" in n or "allow_scripted" in n or "UB_FAKE" in n
                         or n == KIMI_HOST_GLM_NOTE or n.startswith(USER_CONTEXT_NOTE)]
            out["families"][f] = {"available": bool(chain), "backend": chain[0] if chain else None, "chain": chain,
                                  "web": bool(chain) and chain[0] != "host" and fam.backend_web(cfg, chain[0]),
                                  "vendor": fam.vendor_of(f, cfg), "notes": notes}
    if live:
        _preflight(cfg, out)
    return out


# ---------------------------------------------------------------- live preflight

def _ping_one(cfg, f, detect_result, base_dir, web=False):
    """One preflight job: PING (tools none, contract PONG), or with web=True the [U-5] web probe (tools web).
    Returns (meta, seconds, output text or None)."""
    from . import adapter  # lazy: adapter imports detect
    tag = ("web-%s" % f) if web else f
    run_dir = tempfile.mkdtemp(prefix="ping-%s-" % tag, dir=base_dir)
    try:
        prompt_rel = "prompts/ping-%s.prompt.md" % tag
        textio.write_text_atomic(os.path.join(run_dir, prompt_rel), (WEB_PROBE_PROMPT if web else PING_PROMPT) + "\n")
        contract = {"type": "text", "min_chars": 1} if web else {"type": "text", "regex": "PONG", "min_chars": 1}
        job = {"schema": 1, "run": textio.to_posix(run_dir), "id": "ping-%s" % tag, "step": "preflight",
               "kind": "researcher" if web else "ping",
               "template": "PING", "family": f, "tier": "default", "prompt_file": prompt_rel,
               "out": "ping/%s.txt" % tag, "tools": "web" if web else "none", "cwd": "empty", "repo_root": None,
               "timeout_s": PING_TIMEOUT_S * (3 if web else 1), "retries": 0, "contract": contract,
               "schema_file": None, "split": None, "fallback": [], "provisional": False,
               "privacy": {"vendor_ok": True, "web_ok": True, "code_ok": False}, "host_prompt_file": None, "stub": {}}
        t0 = time.monotonic()
        meta = adapter.execute_job(job, detect_result=detect_result, log=False)
        text = None
        try:
            text = textio.read_text(os.path.join(run_dir, "ping", "%s.txt" % tag))
        except OSError:
            text = None
        return meta, time.monotonic() - t0, text
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def web_probe_passed(text):
    """[U-5] True when the probe output carries an http(s) URL and no 'cannot browse' wording."""
    t = text or ""
    return bool(re.search(r"https?://\S+", t)) and not _NO_WEB_RE.search(t)


def _preflight(cfg, out):
    """One parallel `ping` job per candidate family (5.5). Failures mark the family unavailable with the fix;
    a failing host family falls back to the host backend (HOST_BATCH).  # [U-14]"""
    targets = [f for f, info in out["families"].items() if info["available"] and info["chain"] != ["host"]]
    if not targets:
        return
    from .backends import ub_tmp_dir
    base_dir = ub_tmp_dir(cfg.get("_ub_home") or fam.ub_home())
    snapshot = json.loads(json.dumps(out))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(targets))) as ex:
        futs = {ex.submit(_ping_one, cfg, f, snapshot, base_dir): f for f in targets}
        for fut in concurrent.futures.as_completed(futs):
            f = futs[fut]
            info = out["families"][f]
            try:
                meta, secs, _text = fut.result()
            except Exception as e:  # noqa: BLE001 - a preflight crash is a failed ping, never a crash
                meta, secs = {"status": "failed", "error_class": "internal", "error": e.__class__.__name__}, 0.0
            if meta.get("status") == "ok":
                out["live"][f] = "PONG ok %.1fs" % secs
                continue
            ec = meta.get("error_class") or "internal"
            out["live"][f] = "FAIL %s %.1fs" % (ec, secs)
            backend = meta.get("backend") or info.get("backend")
            if ec == "auth":
                fix = _LOGIN_FIX.get(fam.backend_type(cfg, backend) if backend else "", "check the login or key")
            elif ec == "sandbox_network":
                fix = "approve network access for the ub command prefix (see references/hosts.md)"  # [U-8]
            else:
                fix = "preflight %s via %s failed (%s)" % (f, backend, ec)
            info["notes"].append(fix)
            host = out.get("host") or {}
            if f == host.get("family") and host.get("agent") in fam.HOST_DEFAULT_FAMILY:
                info.update({"available": True, "backend": "host", "chain": ["host"], "web": False})
                info["notes"].append("host family runs as host sub-agents (HOST_BATCH)")
            else:
                info.update({"available": False, "backend": None, "chain": [], "web": False})
    _web_probe(cfg, out, base_dir)


def _web_probe(cfg, out, base_dir):
    """[U-5] Families whose first backend is codex-cli with web on get one live web-search job. When the output shows
    no search (no URL, or 'cannot browse'), the family is marked web=false so the seats move web jobs elsewhere."""
    for f, info in out["families"].items():
        chain = info.get("chain") or []
        if not info.get("available") or not info.get("web") or not chain or chain[0] == "host":
            continue
        if fam.backend_type(cfg, chain[0]) != "codex-cli":
            continue
        snapshot = json.loads(json.dumps(out))
        try:
            meta, secs, text = _ping_one(cfg, f, snapshot, base_dir, web=True)
        except Exception as e:  # noqa: BLE001
            meta, secs, text = {"status": "failed", "error_class": "internal", "error": e.__class__.__name__}, 0.0, None
        ok = meta.get("status") == "ok" and web_probe_passed(text)
        out["live"]["%s.web" % f] = ("web ok %.1fs" % secs) if ok else ("web FAIL %.1fs" % secs)
        if not ok:
            info["web"] = False
            info["notes"].append("the live web-search probe found no search results: web jobs go to other families "
                                 "[U-5]")

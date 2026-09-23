"""CLI / key / endpoint detection, reclassification and live preflight (KIT_SPEC 4.8, 5.5).

Frozen API (4.8):
    detect(cfg=None, live=False, only=None) -> dict      shape: see 4.8 "detect --json shape"

Extras: endpoint_family(url), claude_settings_endpoint(env), codex_config_family(env), cli_info(name, env),
        version_tuple(text), KEY_NAMES, LEGACY_KIMI_NOTE.
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
from .backends import scrub_env, host_of, user_codex_home

__all__ = ["detect", "endpoint_family", "claude_settings_endpoint", "codex_config_family", "kimi_config_family",
           "cli_info", "version_tuple", "KEY_NAMES", "LEGACY_KIMI_NOTE", "PING_PROMPT", "WEB_PROBE_PROMPT"]

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
KIMI_HOST_GLM_NOTE = "GLM plan keys are not used from a Kimi Code host"
VERSION_TIMEOUT_S = 15
PING_TIMEOUT_S = 60
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_LOGIN_FIX = {"claude-cli": "run `claude` once and sign in", "codex-cli": "run: codex login",
              "kimi-cli": KIMI_LOGIN_NOTE}


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
    moonshot/kimi.ai/kimi.com -> kimi; api.openai.com -> gpt; any other host -> "custom:<host>"."""
    if not url:
        return "claude"
    h = host_of(url) or str(url).lower()
    if h == "anthropic.com" or h.endswith(".anthropic.com"):
        return "claude"
    if h == "z.ai" or h.endswith(".z.ai") or "bigmodel.cn" in h:
        return "glm"
    if "moonshot" in h or h.endswith("kimi.ai") or h.endswith("kimi.com"):
        return "kimi"
    if h == "openai.com" or h.endswith(".openai.com"):
        return "gpt"
    return "custom:%s" % h


def _home():
    return os.path.expanduser("~")


def _claude_dir(env):
    d = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(_home(), ".claude")


def claude_settings_endpoint(env=None):
    """(ANTHROPIC_BASE_URL from the Claude settings file or None, settings path)."""
    env = os.environ if env is None else env
    path = os.path.join(_claude_dir(env), "settings.json")
    if not os.path.isfile(path):
        return None, path
    try:
        data = textio.read_json(path)
    except (OSError, ValueError):
        return None, path
    block = data.get("env") if isinstance(data, dict) else None
    url = block.get("ANTHROPIC_BASE_URL") if isinstance(block, dict) else None
    return (url if isinstance(url, str) and url.strip() else None), path


def _codex_dir(env, raw=False):
    """The Codex home. raw=False (the native codex-cli backend): the user's own home, never a UB-owned
    codex-homes/<p> that a codex-glm / codex-kimi launcher exported (UB_USER_CODEX_HOME holds the original).
    raw=True: CODEX_HOME exactly as set (what the Codex host process itself uses)."""
    if raw:
        d = (env.get("CODEX_HOME") or "").strip()
    else:
        d = (user_codex_home(env, fam.ub_home()) or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(_home(), ".codex")


def _parse_toml(text):
    try:
        import tomllib  # 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - malformed TOML falls through to the regex reading
        pass
    out = {"model_providers": {}}
    section = None
    for raw in text.split("\n"):
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        m = re.match(r"^\[\s*([^\]]+?)\s*\]$", line)
        if m:
            section = m.group(1).strip()
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*[\"']([^\"']*)[\"']", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if section is None:
            out[key] = val
        else:
            pm = re.match(r"^model_providers\.[\"']?([A-Za-z0-9_-]+)[\"']?$", section)
            if pm:
                out["model_providers"].setdefault(pm.group(1), {})[key] = val
    return out


def codex_config_family(env=None, raw=False):
    """(family, provider, base_url, config path) from $CODEX_HOME/config.toml (default ~/.codex). raw: see
    _codex_dir."""
    env = os.environ if env is None else env
    path = os.path.join(_codex_dir(env, raw), "config.toml")
    if not os.path.isfile(path):
        return "gpt", None, None, path
    try:
        data = _parse_toml(textio.read_text(path))
    except OSError:
        return "gpt", None, None, path
    provider = data.get("model_provider") if isinstance(data, dict) else None
    if not provider or str(provider).lower() == "openai":
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


def kimi_config_family(env=None):
    """(family or None, base_url or None, config path): the family Kimi Code's own default model serves, read from
    $KIMI_CODE_HOME/config.toml. None when the file is missing or names no endpoint.  # [U-34] config layout"""
    env = os.environ if env is None else env
    path = os.path.join(_kimi_home(env), "config.toml")
    if not os.path.isfile(path):
        return None, None, path
    try:
        text = textio.read_text(path)
    except OSError:
        return None, None, path
    base = None
    data = None
    try:
        import tomllib  # 3.11+
        data = tomllib.loads(text)
    except Exception:  # noqa: BLE001 - 3.9/3.10 or malformed TOML: the regex reading below
        data = None
    if isinstance(data, dict):
        default = data.get("default_model")
        models = data.get("models") if isinstance(data.get("models"), dict) else {}
        provs = data.get("providers") if isinstance(data.get("providers"), dict) else {}
        m = models.get(default) if isinstance(default, str) else None
        if isinstance(m, dict):
            p = provs.get(m.get("provider")) if isinstance(m.get("provider"), str) else None
            if isinstance(p, dict) and isinstance(p.get("base_url"), str):
                base = p["base_url"]
    if base is None:
        urls = re.findall(r'^\s*base_url\s*=\s*["\']([^"\']+)["\']', text, re.M)
        fams = set(endpoint_family(u) for u in urls)
        if len(fams) == 1 and urls:
            base = urls[0]
    if not base:
        return None, None, path
    return endpoint_family(base), base, path


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
    provider = b.get("provider")
    if t == "claude-cli":
        if provider:
            tok = ((cfg.get("providers") or {}).get(provider) or {}).get("token_env")
            if not tok or not (env.get(tok) or "").strip():
                return False, None, "%s not set" % (tok or "token_env")
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
            home = fam.expand_path(b["codex_home"], cfg.get("_ub_home"))
            if not os.path.isdir(home):
                return False, None, "codex home missing: run install.py setup-%s --codex" % (provider or "glm")
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
        kf = kimi_config_family(env)[0]
        if kf == "glm":
            return False, None, KIMI_GLM_NOTE
        return True, None, ""
    return False, None, "unknown backend type %s" % t


def _is_native(cfg, bid):
    """A CLI backend on the user's own login/config (no provider settings file, no private Codex home)."""
    b = fam.backend_cfg(cfg, bid)
    return (fam.backend_type(cfg, bid) in ("claude-cli", "codex-cli") and not b.get("provider")
            and not b.get("codex_home"))


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
    claude_ep, claude_settings = claude_settings_endpoint(env)
    codex_f, _codex_prov, codex_base, codex_path = codex_config_family(env)
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
                src = claude_settings if cli == "claude" else codex_path
                ep = claude_ep if cli == "claude" else (codex_base or "")
                out["reclassified"].append({"cli": cli, "source": textio.to_posix(src),
                                            "endpoint": host_of(ep) or ep, "as": serves})
                if serves in fam.FAMILY_VENDORS:
                    extras.setdefault(serves, []).append(bid)
        strict_glm = not bool(((cfg.get("families") or {}).get("glm") or {}).get("allow_scripted_plan_use", True))
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
            if chain:
                notes = [n for n in notes if "reclassified" in n or "allow_scripted" in n or "UB_FAKE" in n
                         or n == KIMI_HOST_GLM_NOTE]
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

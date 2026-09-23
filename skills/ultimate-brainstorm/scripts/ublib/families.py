"""Families config: load + merge, backend chains, provider settings env (KIT_SPEC 4.8, 4.9, 5.1, 5.5).

Frozen API (4.8):
    load_families(scripts_dir=None, ub_home=None) -> dict
    resolve_chain(cfg, family, detect_result) -> list
    provider_settings_env(cfg, provider, tier="default", region=None) -> dict

Extras (B2 internal, safe for B3/B4):
    ub_home(env=None) -> str                     $UB_HOME or ~/.ultimate-brainstorm
    split_label(label) -> (family, alt)          "gpt-alt" -> ("gpt", True)
    vendor_of(label, cfg=None) -> str             claude=anthropic, gpt=openai, kimi=moonshot, glm=zhipu
    backend_cfg(cfg, backend_id) -> dict          {} for unknown ids; "stub" and "host" are built in
    backend_type(cfg, backend_id) -> str
    backend_provider(cfg, backend_id) -> str|None
    backend_web(cfg, backend_id) -> bool
    expand_path(path, ub_home=None) -> str        "~/.ultimate-brainstorm/..." follows UB_HOME
    timeout_for(cfg, kind) -> int
    fake_families(), fake_disabled(), fake_host_families()   test seams (3.3, 4.19)
"""

import copy
import json
import os

from . import SCRIPTS_DIR
from . import textio

__all__ = ["load_families", "resolve_chain", "provider_settings_env", "ub_home", "split_label", "vendor_of",
           "backend_cfg", "backend_type", "backend_provider", "backend_web", "expand_path", "timeout_for",
           "fake_families", "fake_disabled", "fake_host_families", "FAMILY_VENDORS", "DEFAULT_FILE",
           "HOST_DEFAULT_FAMILY"]

DEFAULT_FILE = "families.default.json"
FAMILY_VENDORS = {"claude": "anthropic", "gpt": "openai", "kimi": "moonshot", "glm": "zhipu"}
HOST_DEFAULT_FAMILY = {"claude-code": "claude", "codex": "gpt", "kimi": "kimi", "zcode": "glm"}
_BUILTIN_BACKENDS = {
    "stub": {"type": "stub", "web": False, "native_schema": False},
    "host": {"type": "host", "web": False, "native_schema": False},
}
_UB_DEFAULT_PREFIX = "~/.ultimate-brainstorm"


# ---------------------------------------------------------------- environment and labels

def ub_home(env=None):
    """UB_HOME: $UB_HOME, otherwise ~/.ultimate-brainstorm (3.2). Absolute, native separators."""
    env = os.environ if env is None else env
    val = (env.get("UB_HOME") or "").strip()
    if val:
        return os.path.abspath(os.path.expanduser(val))
    return os.path.abspath(os.path.join(os.path.expanduser("~"), ".ultimate-brainstorm"))


def _csv_env(name):
    return [p.strip().lower() for p in (os.environ.get(name) or "").split(",") if p.strip()]


def fake_families():
    """UB_FAKE_FAMILIES=1: every family is available through the stub backend (test seam, 3.3)."""
    return (os.environ.get("UB_FAKE_FAMILIES") or "").strip() == "1"


def fake_disabled():
    """UB_FAKE_DISABLE=a,b: families reported unavailable in fake mode."""
    return _csv_env("UB_FAKE_DISABLE")


def fake_host_families():
    """UB_FAKE_HOST_BACKEND=glm[,kimi]: families whose chain is forced to ["host"] (exercises HOST_BATCH)."""
    return _csv_env("UB_FAKE_HOST_BACKEND")


def split_label(label):
    """("gpt", False) for "gpt"; ("gpt", True) for "gpt-alt". Other labels are returned as is."""
    label = (label or "").strip()
    if label.endswith("-alt") and len(label) > 4:
        return label[:-4], True
    return label, False


def vendor_of(label, cfg=None):
    """Vendor of a family label (5.7): X-alt has the vendor of X; any other label is its own vendor."""
    fam, _alt = split_label(label)
    if cfg:
        v = ((cfg.get("families") or {}).get(fam) or {}).get("vendor")
        if v:
            return v
    return FAMILY_VENDORS.get(fam, fam)


# ---------------------------------------------------------------- loading

def _deep_merge(base, over):
    """Dicts merge recursively; any other value (lists, scalars, null) replaces."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_families(scripts_dir=None, ub_home=None):
    """families.default.json deep-merged with UB_HOME/families.json (user overrides).

    A broken override file is ignored; the reason goes to cfg["_warnings"]. The resolved home is cfg["_ub_home"].
    """
    scripts_dir = scripts_dir or SCRIPTS_DIR
    home = ub_home or globals()["ub_home"]()
    path = os.path.join(scripts_dir, DEFAULT_FILE)
    cfg = textio.read_json(path)
    if not isinstance(cfg, dict):
        raise ValueError("%s is not a JSON object" % path)
    warnings = []
    user = os.path.join(home, "families.json")
    if os.path.isfile(user):
        try:
            over = textio.read_json(user)
            if isinstance(over, dict):
                cfg = _deep_merge(cfg, over)
            else:
                warnings.append("%s is not a JSON object; ignored" % textio.to_posix(user))
        except (OSError, ValueError) as e:
            warnings.append("%s could not be read (%s); ignored" % (textio.to_posix(user), e.__class__.__name__))
    cfg["_warnings"] = warnings
    cfg["_ub_home"] = home
    return cfg


def _cfg_home(cfg):
    return (cfg or {}).get("_ub_home") or ub_home()


def expand_path(path, ub_home=None):
    """Expand a config path. "~/.ultimate-brainstorm/..." follows UB_HOME (so tests and custom homes work)."""
    if not path:
        return path
    p = str(path).replace("\\", "/")
    if p == _UB_DEFAULT_PREFIX or p.startswith(_UB_DEFAULT_PREFIX + "/"):
        home = ub_home or globals()["ub_home"]()
        rest = p[len(_UB_DEFAULT_PREFIX):].lstrip("/")
        return os.path.abspath(os.path.join(home, *rest.split("/"))) if rest else home
    return os.path.abspath(os.path.expanduser(str(path)))


# ---------------------------------------------------------------- backends

def backend_cfg(cfg, backend_id):
    if backend_id in _BUILTIN_BACKENDS:
        return dict(_BUILTIN_BACKENDS[backend_id])
    b = ((cfg or {}).get("backends") or {}).get(backend_id)
    return dict(b) if isinstance(b, dict) else {}


def backend_type(cfg, backend_id):
    t = backend_cfg(cfg, backend_id).get("type")
    if t:
        return t
    return (backend_id or "").split("@", 1)[0]


def backend_provider(cfg, backend_id):
    return backend_cfg(cfg, backend_id).get("provider")


def backend_web(cfg, backend_id):
    """Static web capability of a backend (5.5). HTTP backends have no tools, so no web."""
    b = backend_cfg(cfg, backend_id)
    if b.get("type") in ("openai-chat-http", "anthropic-http"):
        return False
    return bool(b.get("web", False))


def timeout_for(cfg, kind):
    t = (((cfg or {}).get("defaults") or {}).get("timeouts_s") or {}).get(kind)
    try:
        return int(t) if t else 420
    except (TypeError, ValueError):
        return 420


# ---------------------------------------------------------------- chains

def _strict_glm(cfg):
    return not bool(((cfg.get("families") or {}).get("glm") or {}).get("allow_scripted_plan_use", True))


def resolve_chain(cfg, family, detect_result):
    """Ordered backend ids usable now for a family label (claude, gpt-alt, host, ...).

    - "host" -> ["host"]; UB_FAKE_HOST_BACKEND families -> ["host"];
    - UB_FAKE_FAMILIES=1 -> ["stub"] (or [] for UB_FAKE_DISABLE families);
    - otherwise the chain detection computed (detect_result["families"][fam]["chain"]). When detect_result is None,
      detection runs now for that family only.
    - strict GLM (families.glm.allow_scripted_plan_use false, 5.6 rule 6) drops worker-run GLM backends; GLM is then
      reachable only as the host family, through HOST_BATCH.  # [U-20]
    """
    fam, _alt = split_label(family)
    if fam == "host":
        return ["host"]
    if fam in fake_host_families():
        return ["host"]
    if fake_families():
        return [] if fam in fake_disabled() else ["stub"]
    if detect_result is None:
        from . import detect as _detect  # lazy: detect imports this module
        detect_result = _detect.detect(cfg, live=False, only=[fam])
    info = ((detect_result or {}).get("families") or {}).get(fam) or {}
    chain = [b for b in (info.get("chain") or []) if isinstance(b, str)]
    if fam == "glm" and _strict_glm(cfg):
        chain = [b for b in chain if b == "host" or backend_type(cfg, b) not in ("claude-cli", "codex-cli")]
        host_fam = ((detect_result or {}).get("host") or {}).get("family")
        if host_fam == "glm" and "host" not in chain:
            chain = ["host"] + chain
    return chain


# ---------------------------------------------------------------- providers

def provider_settings_env(cfg, provider, tier="default", region=None):
    """The env block for a claude-cli provider backend (4.9), WITHOUT the token value.

    Callers add {token_var: os.environ[token_env]} only when writing the 0600 settings file.
    An unknown region falls back to "global" (the Moonshot cn Anthropic endpoint is not included).  # [U-22]
    """
    prov = ((cfg or {}).get("providers") or {}).get(provider)
    if not isinstance(prov, dict):
        raise KeyError("unknown provider %r" % provider)
    urls = prov.get("base_url") or {}
    reg = region or (cfg or {}).get("region") or "global"
    if isinstance(urls, str):
        base = urls
    else:
        base = urls.get(reg) or urls.get("global")
    models = prov.get("models") or {}
    default_model = models.get("default")
    fast_model = models.get("fast") or default_model
    tier_model = models.get(tier) or default_model
    env = {}
    if base:
        env["ANTHROPIC_BASE_URL"] = base
    if tier_model:
        env["ANTHROPIC_MODEL"] = tier_model
    if default_model:
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = default_model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = default_model
        env["ANTHROPIC_DEFAULT_FABLE_MODEL"] = default_model
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = default_model
    if fast_model:
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = fast_model
    for k, v in (prov.get("env") or {}).items():
        env[str(k)] = str(v)
    return env


def provider_token(cfg, provider, environ=None):
    """(token_env, token_var, value_or_None) for a provider. The value is never logged."""
    environ = os.environ if environ is None else environ
    prov = ((cfg or {}).get("providers") or {}).get(provider) or {}
    token_env = prov.get("token_env")
    token_var = prov.get("token_var") or "ANTHROPIC_AUTH_TOKEN"
    value = (environ.get(token_env) or "").strip() if token_env else ""
    return token_env, token_var, (value or None)


def dump(cfg):
    """JSON text of a config without the private keys (for debugging)."""
    return json.dumps({k: v for k, v in (cfg or {}).items() if not k.startswith("_")}, indent=1, sort_keys=True)

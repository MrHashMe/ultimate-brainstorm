"""Job construction from templates (KIT_SPEC 4.4, 6.11, 6.12).

build_jobs(ctx, step) expands a DISPATCH step into job dicts: the step's fanout gives items, the step's `job` block
gives defaults (with {item.<key>} substitution), the item overrides them. For every job the engine writes
prompts/<id>.prompt.md (the filled template) and jobs/<id>.json; for families whose chain resolves to `host` it also
writes the HOST_BATCH variant prompts/<id>.host.md, which ends with an `OUTPUT FILE: <abs out>` line.

Template rendering follows the rules in templates/manifest.json: the header line is dropped, a ub-choices block picks
the text of one row, every other comment block is removed, a line that is only one empty placeholder is removed, and
placeholders are substituted in one pass.
"""

import json
import os
import re

from .. import textio
from . import DEFAULT_TIMEOUTS_S, EngineError, base_family, is_alt
from . import privacy as privacy_mod
from . import registry

PH_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
ITEM_RE = re.compile(r"\{item\.([A-Za-z0-9_]+)\}")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
GEN_HEADER = "GEN-HEADER"
SKILL_GUARD = "Do not load or invoke any skill; this prompt is the whole task."
WORKER_OUTPUT_RULE = "Print only the result."
HOST_OUTPUT_RULE = "Write only the requested output to the file on the next line."
HOST_RULE = ("Write only the result (exactly what the prompt asks you to print, nothing else) to the OUTPUT FILE "
             "named on the last line, creating folders as needed. Reply with one line.")


# ---------------------------------------------------------------- template rendering (templates/manifest.json rules)

CHOICES_RE = re.compile(r"<!-- ub-choices: ([A-Z][A-Z0-9_]*) key=([A-Z][A-Z0-9_]*)[ \t]*\n(.*?)\n-->[ \t]*\n?", re.S)
COMMENT_RE = re.compile(r"<!--.*?-->[ \t]*\n?", re.S)
ARG_RE = re.compile(r"<!-- ub-argument:begin -->[ \t]*\n(.*?)<!-- ub-argument:end -->", re.S)
LONE_PH_RE = re.compile(r"^\s*\{\{([A-Z][A-Z0-9_]*)\}\}\s*$")


def strip_header(text):
    """Drop line 1 when it is the '<!-- ub-template: ... -->' header."""
    lines = (text or "").split("\n")
    if lines and lines[0].lstrip().startswith("<!-- ub-template:"):
        lines = lines[1:]
    return "\n".join(lines)


def choice_table(rows):
    table = {}
    for r in rows.split("\n"):
        if "|" not in r:
            continue
        k, v = r.split("|", 1)
        table[k.strip()] = v.strip()
    return table


def render(text, resolve, strip_comments=True, template=None):
    """Render a template body (header already stripped) with resolve(name) -> str | None (None = unknown).

    A ub-choices block sets its PLACEHOLDER to the row picked by the value of KEY (the row text is rendered too);
    every other <!-- --> block is removed (strip_comments); a line that is exactly one placeholder with an empty
    value is removed; one substitution pass (filled values are content and never re-scanned).
    Raises EngineError naming every unknown placeholder."""
    missing = []
    cache = {}

    def value(name):
        if name in cache:
            return cache[name]
        v = resolve(name)
        if v is None:
            missing.append(name)
        else:
            v = str(v)
        cache[name] = v
        return v

    def sub(t):
        def repl(m):
            v = value(m.group(1))
            return m.group(0) if v is None else v
        return PH_RE.sub(repl, t)

    for name, key, rows in CHOICES_RE.findall(text or ""):
        kv = value(key)
        if kv is None:
            continue
        row = choice_table(rows).get(kv.strip())
        if row is not None:
            cache[name] = sub(row)
    body = CHOICES_RE.sub("", text or "")
    if strip_comments:
        body = COMMENT_RE.sub("", body)
    out = []
    for ln in body.split("\n"):
        m = LONE_PH_RE.match(ln)
        if m:
            v = value(m.group(1))
            if v is not None and not v.strip():
                continue
        out.append(ln)
    rendered = sub("\n".join(out))
    if missing:
        raise EngineError("template %s uses unknown placeholders: %s" % (template or "?", ", ".join(sorted(set(
            missing)))), fix=["reinstall the kit (templates and engine versions differ): install.py update"])
    return rendered


def resolver(ctx, jc):
    """Placeholder lookup for a job context: item vars win over registry placeholders (FACTS is always filtered)."""
    vars_ = dict((str(k).upper(), v) for k, v in ((jc or {}).get("vars") or {}).items())

    def resolve(name):
        if name in vars_ and name not in ("FACTS",):
            v = vars_[name]
            return "" if v is None else v
        fn = registry.PLACEHOLDERS.get(name)
        if fn is None:
            return None
        v = fn(ctx, jc)
        return "" if v is None else v
    return resolve


def fill(ctx, text, jc):
    """Render `text` for a job context (see render). Unknown placeholders raise EngineError."""
    return render(text, resolver(ctx, jc), template=(jc or {}).get("template"))


def fill_doc(tpl, mapping):
    """Fill a docs or gate template with a fixed mapping (header dropped, empty lone lines removed); None when the
    template uses a placeholder that is not in the mapping."""
    try:
        return render(strip_header(tpl), lambda n: mapping.get(n) if n in mapping else None, strip_comments=False)
    except EngineError:
        return None


def render_doc(name, mapping, fallback=None, folder="docs"):
    """templates/<folder>/<name> filled with mapping; `fallback` (text or callable) when the template is missing or
    names a placeholder the mapping lacks."""
    tpl = registry.load_template(name, folder, raw=True)
    if tpl is not None:
        out = fill_doc(tpl, mapping)
        if out is not None:
            return out.rstrip("\n") + "\n"
    if callable(fallback):
        fallback = fallback()
    return fallback


def host_argument(ctx, name, jc):
    """The filled ub-argument block of templates/host/<name>.md (the whole body when there is no block)."""
    raw = registry.load_template(name, "host")
    if raw is None:
        return None
    m = ARG_RE.search(raw)
    body = m.group(1) if m else raw
    return fill(ctx, body, dict(jc or {}, template=name)).strip("\n") + "\n"


def placeholders_in(text):
    return sorted(set(PH_RE.findall(text or "")))


def template_text(name):
    """The prompt text for a template name (header line removed; GEN-HEADER comes in through {{GEN_HEADER}})."""
    body = registry.load_template(name)
    if body is None:
        raise EngineError("template %s is missing (templates/prompts/%s.md)" % (name, name),
                          fix=["reinstall the kit: install.py update"])
    return body


# ---------------------------------------------------------------- jobs

def _subst(value, item):
    if isinstance(value, str):
        def repl(m):
            v = item.get(m.group(1))
            return "" if v is None else str(v)
        full = ITEM_RE.fullmatch(value)
        if full and not isinstance(item.get(full.group(1)), str) and item.get(full.group(1)) is not None:
            return item.get(full.group(1))
        return ITEM_RE.sub(repl, value)
    if isinstance(value, list):
        return [_subst(v, item) for v in value]
    if isinstance(value, dict):
        return dict((k, _subst(v, item)) for k, v in value.items())
    return value


def job_id(step_id, item_id):
    jid = step_id if not item_id else "%s-%s" % (step_id, item_id)
    jid = re.sub(r"[^A-Za-z0-9._-]", "-", jid)[:80]
    if not JOB_ID_RE.match(jid):
        raise EngineError("invalid job id %r" % jid)
    return jid


def timeout_for(ctx, kind):
    cfg = {}
    try:
        cfg = ctx.deps.families_cfg() if ctx.deps else {}
    except Exception:
        cfg = {}
    t = ((cfg.get("defaults") or {}).get("timeouts_s") or {}).get(kind)
    return int(t or DEFAULT_TIMEOUTS_S.get(kind, 420))


def retries_for(ctx):
    try:
        cfg = ctx.deps.families_cfg() if ctx.deps else {}
    except Exception:
        cfg = {}
    return int((cfg.get("defaults") or {}).get("retries", 1))


def items_for(ctx, step):
    name = step.get("fanout") or "single"
    fn = registry.FANOUTS.get(name)
    if fn is None:
        raise EngineError("pipeline.json names an unknown fanout: %s" % name)
    return fn(ctx, step) or []


def build_jobs(ctx, step, write=True):
    """Build (and write) every job of a DISPATCH step. Raises privacy.PolicyBlock or EngineError."""
    items = items_for(ctx, step)
    defaults = step.get("job") or {}
    jobs = []
    for item in items:
        spec = _subst(defaults, item)
        for k, v in item.items():
            if k in ("vars", "checks", "meta", "stub") or v is not None or k not in spec:
                spec[k] = v
        jobs.append(make_job(ctx, step, spec, write=write))
    return jobs


def make_job(ctx, step, spec, write=True, jid=None, family=None, provisional=False):
    """One job dict (4.4) from a merged spec; writes its prompt(s) and job file."""
    jid = jid or job_id(step["id"], spec.get("id"))
    fam = family or spec.get("family") or ctx.host_family
    kind = spec.get("kind") or "generator"
    tools = spec.get("tools") or "none"
    priv = ctx.state.get("privacy") or {}
    if not priv.get("web", True) and "web" in tools:
        tools = tools.replace("+web", "").replace("web", "none") or "none"
        if tools == "read+none":
            tools = "read"
    cwd = spec.get("cwd") or "empty"
    repo_root = spec.get("repo_root") if cwd == "repo" else None
    if cwd == "repo" and privacy_mod.needs_code_strip(ctx.state, fam):
        cwd, repo_root = "empty", None
        tools = "web" if "web" in tools else "none"
    contract = spec.get("contract") or {"type": "text"}
    jc = {"family": fam, "item": spec, "vars": spec.get("vars") or {}, "job_id": jid, "tools": tools,
          "template": spec.get("template"), "contract": contract, "out": spec.get("out"), "kind": kind}
    host_prompt = None
    if spec.get("prompt_file"):
        prompt_rel = spec["prompt_file"]
        if not ctx.exists(prompt_rel):
            raise EngineError("prompt file %s is missing for job %s" % (prompt_rel, jid))
        prompt = ctx.read(prompt_rel)
    else:
        tpl = spec.get("template")
        if not tpl:
            raise EngineError("job %s has neither a template nor a prompt file" % jid)
        body = template_text(tpl)
        prompt = fill(ctx, body, jc).rstrip() + "\n"
        prompt_rel = "prompts/%s.prompt.md" % jid
        if ctx.is_host_chain(fam) and spec.get("out"):
            host_prompt = fill(ctx, body, dict(jc, host=True)).rstrip() + "\n"
    allow = [ctx.state.get("topic", ""), ctx.state.get("idea_text", "")]
    privacy_mod.run_checks(prompt, list(spec.get("checks") or []) + list(step.get("checks") or []), ctx.run_dir,
                           jid, allow=allow)
    out = spec.get("out")
    if not out:
        raise EngineError("job %s has no output path" % jid)
    host_rel = None
    if ctx.is_host_chain(fam):
        host_rel = "prompts/%s.host.md" % jid
    split = spec.get("split")
    job = {
        "schema": 1,
        "run": textio.to_posix(ctx.run_dir),
        "id": jid,
        "step": step["id"],
        "kind": kind,
        "template": spec.get("template") or os.path.basename(prompt_rel).split(".")[0],
        "family": fam,
        "tier": spec.get("tier") or "default",
        "prompt_file": prompt_rel,
        "out": out,
        "tools": tools,
        "cwd": cwd,
        "repo_root": textio.to_posix(repo_root) if repo_root else None,
        "timeout_s": int(spec.get("timeout_s") or timeout_for(ctx, kind)),
        "retries": retries_for(ctx),
        "contract": contract,
        "schema_file": run_schema(ctx, spec.get("schema"), write),
        "split": split,
        "fallback": [f for f in (spec.get("fallback") or []) if f != fam],
        "provisional": bool(provisional or is_alt(fam)),
        "privacy": privacy_mod.job_privacy(ctx.state, fam, tools, cwd),
        "host_prompt_file": host_rel,
        "stub": spec.get("stub") or {},
    }
    if spec.get("meta"):
        job["engine"] = dict(spec["meta"])
    if write:
        if not spec.get("prompt_file"):
            _write_if_changed(ctx.path(prompt_rel), prompt)
        if host_rel:
            if not (host_prompt and host_prompt.rstrip().split("\n")[-1].startswith("OUTPUT FILE:")):
                host_prompt = host_variant(ctx, prompt, out)
            _write_if_changed(ctx.path(host_rel), host_prompt)
        _write_json_if_changed(ctx.path("jobs", jid + ".json"), job)
    return job


def run_schema(ctx, ref, write=True):
    """schema_file is run-relative (4.4): an `SK:templates/schemas/<f>` schema is copied into <run>/schemas/<f> so
    the run folder is self-contained; a run-relative reference is kept as it is."""
    if not ref or not isinstance(ref, str):
        return None
    if not ref.startswith("SK:"):
        return ref
    from . import SK_DIR
    src = os.path.join(SK_DIR, *ref[3:].split("/"))
    rel = "schemas/%s" % os.path.basename(src)
    if write and os.path.exists(src):
        try:
            _write_if_changed(ctx.path(rel), textio.read_text(src))
        except OSError:
            return None
    return rel


def host_variant(ctx, prompt, out):
    """HOST_BATCH variant of a prompt that was not rendered from a template (bs.py judge prompts): the worker
    output rule is swapped for the host rule and the prompt ends with `OUTPUT FILE: <abs out>`."""
    lines = prompt.rstrip().split("\n")
    if lines and lines[-1].strip() == WORKER_OUTPUT_RULE:
        lines = lines[:-1]
    text = "\n".join(lines).replace(WORKER_OUTPUT_RULE, HOST_OUTPUT_RULE)
    return text.rstrip() + "\n\n" + HOST_RULE + "\nOUTPUT FILE: %s\n" % textio.to_posix(ctx.path(out))


def _write_if_changed(path, text):
    if os.path.exists(path):
        try:
            if textio.read_text(path) == textio.normalize_newlines(text):
                return
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.write_text_atomic(path, text)


def _write_json_if_changed(path, obj):
    if os.path.exists(path):
        try:
            if textio.read_json(path) == json.loads(json.dumps(obj)):
                return
        except (OSError, ValueError):
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.write_json_atomic(path, obj)


def fallback_job(ctx, step, job, fam):
    """A PROVISIONAL copy of a failed job on another family (suffix .fb-<fam>, same out)."""
    spec = {"id": None, "template": job.get("template"), "kind": job.get("kind"), "tools": job.get("tools"),
            "cwd": "empty", "out": job.get("out"), "contract": job.get("contract"), "split": job.get("split"),
            "stub": job.get("stub"), "schema": job.get("schema_file"), "fallback": []}
    fid = job_id(job["id"], "fb-" + fam)[:80]
    prompt_rel = job.get("prompt_file")
    prompt = ctx.read(prompt_rel)
    # The fallback prompt is a copy (prompts are family-neutral except FACTS filtering, re-applied for code privacy).
    if privacy_mod.needs_code_strip(ctx.state, fam):
        prompt = privacy_mod.strip_code(prompt)
    new_rel = "prompts/%s.prompt.md" % fid
    _write_if_changed(ctx.path(new_rel), prompt)
    spec["prompt_file"] = new_rel
    new = make_job(ctx, step, spec, write=False, jid=fid, family=fam, provisional=True)
    new["provisional"] = True
    new["fallback"] = []
    new["template"] = job.get("template")
    if ctx.is_host_chain(fam):
        new["host_prompt_file"] = "prompts/%s.host.md" % fid
        _write_if_changed(ctx.path(new["host_prompt_file"]), host_variant(ctx, prompt, new["out"]))
    _write_json_if_changed(ctx.path("jobs", fid + ".json"), new)
    return new


def load_job(ctx, jid):
    return ctx.read_json("jobs/%s.json" % jid, None)


def family_label_ok(label):
    return bool(re.match(r"^[a-z][a-z0-9-]*$", str(label or "")))


def base(label):
    return base_family(label)

"""Job construction from templates (KIT_SPEC 4.4, 6.11, 6.12).

build_jobs(ctx, step) expands a DISPATCH step into job dicts: the step's fanout gives items, the step's `job` block
gives defaults, the item overrides them. For every job the engine writes prompts/<id>.prompt.md (the filled template)
and jobs/<id>.json; for families whose chain resolves to `host` it also writes the HOST_BATCH variant
prompts/<id>.host.md, which ends with an `OUTPUT FILE: <abs out>` line. Every job carries its input_digest (4.4): what
the job is built from, so the driver sees when a job file no longer matches its inputs (#85).

Template rendering follows the rules in templates/manifest.json: the header line is dropped, a ub-choices block picks
the text of one row, every other comment block is removed, a line that is only one empty placeholder is removed, and
placeholders are substituted in one pass.
"""

import hashlib
import json
import os
import re

from .. import textio
from . import DEFAULT_TIMEOUTS_S, EngineError, is_alt
from . import privacy as privacy_mod
from . import registry

PH_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
GEN_HEADER = "GEN-HEADER"
SKILL_GUARD = "Do not load or invoke any skill; this prompt is the whole task."
WORKER_OUTPUT_RULE = "Print only the result."
HOST_OUTPUT_RULE = "Write only the requested output to the file on the next line."
HOST_RULE = ("Write only the result (exactly what the prompt asks you to print, nothing else) to the OUTPUT FILE "
             "named on the last line, creating folders as needed. Reply with one line.")
CODEBASE_HEADING = registry.CODEBASE_FIT.split("\n", 1)[0]  # "## 5. Codebase fit": the CHECK heading _check_item adds


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
    """Placeholder lookup for a job context: item vars win over registry placeholders (FACTS is always filtered).

    Privacy and untrusted text (6.8, C8): for a family whose prompts must carry no code (privacy.code_filtered: another
    vendor, privacy.code false, a repo-labeled run) every value goes through strip_code, whatever its source, a value
    quoted from run files (registry.DATA_PLACEHOLDERS) with the strict rule of a DATA block's body; the templates
    themselves carry no code, so the worker's contains_code check on the whole prompt holds (make_job strips the
    whole prompt once more, which leaves such a prompt as it is). Those quoted values are then wrapped in a DATA
    block."""
    vars_ = dict((str(k).upper(), v) for k, v in ((jc or {}).get("vars") or {}).items())
    strip = privacy_mod.code_filtered(ctx.state, (jc or {}).get("family") or ctx.host_family, ctx.run_dir)

    def resolve(name):
        if name in vars_ and name not in ("FACTS",):
            v = vars_[name]
        else:
            fn = registry.PLACEHOLDERS.get(name)
            if fn is None:
                return None
            v = fn(ctx, jc)
        v = "" if v is None else str(v)
        if strip:
            v = privacy_mod.strip_code(v, strict=name in registry.DATA_PLACEHOLDERS)
        if name in registry.DATA_PLACEHOLDERS:
            v = privacy_mod.fence_data(name, v)
        return v
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


def _item_spec(defaults, item):
    """A job spec: the step's job defaults with the fanout item's values over them."""
    spec = json.loads(json.dumps(defaults))
    for k, v in item.items():
        if k in ("vars", "checks", "meta", "stub") or v is not None or k not in spec:
            spec[k] = v
    return spec


def build_jobs(ctx, step, write=True):
    """Build (and write) every job of a DISPATCH step. `write` may be a predicate on the built job (dict): only those
    jobs are written (the driver rebuilds stale jobs this way). Two items that make the same job id are refused before
    any job is written: the second would overwrite the first one's jobs/<id>.json. Raises privacy.PolicyBlock or
    EngineError."""
    defaults = step.get("job") or {}
    specs = [_item_spec(defaults, item) for item in items_for(ctx, step)]
    ids = [job_id(step["id"], spec.get("id")) for spec in specs]
    dup = sorted(set(i for i in ids if ids.count(i) > 1))
    if dup:
        raise EngineError("step %s builds job %s more than once (its fanout listed the same item twice)"
                          % (step["id"], ", ".join(dup)))
    return [make_job(ctx, step, spec, write=write, jid=jid) for spec, jid in zip(specs, ids)]


def template_version(name):
    """'v1' from a prompt template's header line '<!-- ub-template: NAME v1 kind=... -->'; None without one."""
    raw = registry.load_template(name, raw=True) if name else None
    m = re.match(r"\s*<!-- ub-template:\s*\S+\s+(v\d+)", raw or "")
    return m.group(1) if m else None


def input_digest(job, prompt, host_prompt=None):
    """sha256 of what a job is built from (4.4): the job as built (template, family, tools, cwd, contract, chain,
    fallbacks, privacy stamp, ...), the template version and the filled prompt(s), i.e. the placeholder values after
    privacy filtering. The engine rebuilds a job that has not run when this no longer matches (#85)."""
    body = dict((k, v) for k, v in job.items() if k != "input_digest")
    body["template_version"] = template_version(job.get("template"))
    body["prompt_sha256"] = textio.sha256_text(prompt)
    body["host_prompt_sha256"] = textio.sha256_text(host_prompt) if host_prompt else None
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def make_job(ctx, step, spec, write=True, jid=None, family=None, provisional=False):
    """One job dict (4.4) from a merged spec; writes its prompt(s) and job file (`write` may be a predicate on the
    job, see build_jobs)."""
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
          "template": spec.get("template"), "contract": contract, "out": spec.get("out"), "kind": kind, "cwd": cwd,
          "repo_root": repo_root}
    host_prompt = None
    filtered = False  # a prompt file (bs.py judges) that is filtered in place when written
    strip = privacy_mod.code_filtered(ctx.state, fam, ctx.run_dir)
    if spec.get("prompt_file"):
        prompt_rel = spec["prompt_file"]
        if not ctx.exists(prompt_rel):
            raise EngineError("prompt file %s is missing for job %s" % (prompt_rel, jid))
        prompt = ctx.read(prompt_rel)
        if strip:
            # a prompt written outside the templates (bs.py judges) for another vendor: filtered in place (C8)
            clean = privacy_mod.strip_code(prompt)
            filtered = clean != prompt
            prompt = clean
    else:
        tpl = spec.get("template")
        if not tpl:
            raise EngineError("job %s has neither a template nor a prompt file" % jid)
        body = template_text(tpl)
        prompt = fill(ctx, body, jc).rstrip() + "\n"
        prompt_rel = "prompts/%s.prompt.md" % jid
        if ctx.is_host_chain(fam) and spec.get("out"):
            host_prompt = fill(ctx, body, dict(jc, host=True)).rstrip() + "\n"
        if strip:
            # every value went through strip_code on its own; the whole prompt goes through it once more, so a value
            # that reads differently inside its template line never makes the worker's contains_code refuse the
            # prompt (strip_code is idempotent: a prompt whose values compose cleanly stays as it is)
            prompt = privacy_mod.strip_code(prompt)
            host_prompt = privacy_mod.strip_code(host_prompt) if host_prompt else host_prompt
    allow = [ctx.state.get("topic", ""), ctx.state.get("idea_text", "")]
    checks = list(spec.get("checks") or []) + list(step.get("checks") or [])
    judged = any(c in ("origin_label", "origin_label_check") for c in checks)
    sources, prepare = _judge_inputs(ctx, spec) if judged else ((), None)
    try:
        privacy_mod.run_checks(prompt, checks, ctx.run_dir, jid, allow=allow,
                               aliases=run_aliases(ctx) if judged else None,
                               labels=sorted(ctx.state.get("families") or {}), sources=sources)
    except privacy_mod.PolicyBlock as e:
        if e.rule != "origin_label_check" or not prepare:
            raise
        # a prepared prompt file is written once: after the fix, the step that prepares it runs again
        redo = '%s redo "%s" %s --yes' % (ctx.state.get("runner") or "ub", textio.to_posix(ctx.run_dir), prepare)
        raise privacy_mod.PolicyBlock(e.rule, "%s Remove it there, then prepare the judge prompts again: %s"
                                      % (e, redo), e.job_id, fix=["remove the text from the file named above, then: "
                                                                  "%s" % redo])
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
        "schema_file": run_schema(ctx, spec.get("schema"), write is not False),
        "split": split,
        "fallback": [f for f in (spec.get("fallback") or []) if f != fam],
        "provisional": bool(provisional or is_alt(fam)),
        "privacy": privacy_mod.job_privacy(ctx.state, fam, tools, cwd, ctx.run_dir),
        "host_prompt_file": host_rel,
        "stub": spec.get("stub") or {},
    }
    chain = ctx.family_chain(fam)
    if chain:
        job["chain"] = chain  # C13: the worker skips detection and re-checks only PATH and keys
    if spec.get("meta"):
        job["engine"] = dict(spec["meta"])
    if host_rel and not (host_prompt and host_prompt.rstrip().split("\n")[-1].startswith("OUTPUT FILE:")):
        host_prompt = host_variant(ctx, prompt, out)
    job["input_digest"] = input_digest(job, prompt, host_prompt if host_rel else None)
    if callable(write):
        write = write(job)
    if write and cwd == "repo":
        ctx.state.setdefault("privacy", {})["repo_read"] = True  # the repo label (C8): see privacy.repo_labeled
        hide_runs_from_repo(ctx.run_dir, repo_root)
    if write:
        if not spec.get("prompt_file") or filtered:
            _write_if_changed(ctx.path(prompt_rel), prompt)
        if host_rel:
            _write_if_changed(ctx.path(host_rel), host_prompt)
        _write_json_if_changed(ctx.path("jobs", jid + ".json"), job)
    return job


_HEADING_ID_RE = re.compile(r"^#{2,4}[ \t]*([A-Z][A-Za-z0-9]*-\d+)\b", re.M)  # '### S3-04 Title'


def run_aliases(ctx):
    """The alias IDs of this run, which a judge prompt may not hold (6.7 rule 6): every pool file's idea headings
    (also a block its contract did not count), the lens, import and seed IDs (registry.pool_aliases) and the aliases
    the curators recorded (merges.json, quick/curated.json), each only with a prefix of the kit or a team seed file's
    H<name>: an imported heading such as '## GPT-4 shift summaries' holds no alias ID, and the neutral IDs judges see
    (I-001, Q-01) are none."""
    ids = set(registry.pool_aliases(ctx)[0])
    for path in textio.glob_in(ctx.run_dir, "pool", "*.md"):
        try:
            ids.update(_HEADING_ID_RE.findall(textio.read_text(path)))
        except OSError:
            continue
    for rel in ("merges.json", "quick/curated.json"):
        data = ctx.read_json(rel, {})
        for idea in (data.get("ideas") if isinstance(data, dict) else None) or []:
            if isinstance(idea, dict) and isinstance(idea.get("aliases"), list):
                ids.update(str(a).strip() for a in idea["aliases"])
    team = [os.path.basename(p)[len("00_HUMAN_SEEDS_"):-3] for p in textio.glob_in(ctx.run_dir, "00_HUMAN_SEEDS_*.md")]
    rx = re.compile(r"^(?:%s)-\d+$" % "|".join([privacy_mod.ALIAS_PREFIXES] +
                                               ["H" + t for t in team if re.match(r"^[A-Za-z0-9]+$", t)]))
    return sorted(a for a in ids if rx.match(a))


def _judge_inputs(ctx, spec):
    """(the run files a judge prompt is built from, in the order an origin-label refusal searches them for the match;
    the step that prepares the job's prompt file, None for a template job, which the next build fills again)."""
    folder = (spec.get("prompt_file") or "").split("/")[0]
    quick = ctx.mode == "quick"
    if folder == "screen":  # the quick screen's lines are written from the quick curation
        files = ["quick/curated.json" if quick else "screen/ideas.md", "screen/header.md"]
        script = "prepare_quick_screen" if quick else "prepare_screen"
    elif folder == "tournament":
        files, script = ["tournament/cards.md", "tournament/header.md"], "prepare_tournament"
    else:
        return ["10_ARCHITECTURE/review/sheet_*.md", "10_ARCHITECTURE/00_BRIEF.md",
                "10_ARCHITECTURE/quality-scenarios.md"], None
    from . import pipeline  # lazy: pipeline imports this module
    return files, next((s["id"] for s in pipeline.load_steps() if s.get("script") == script), None)


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


def _rebuilt_spec(ctx, step, job, fam):
    """The spec to build `job` again for the fallback family `fam`, or None when a copy of its prompt serves.

    A job built to read the repository (cwd repo) or to answer CHECK section 5 is rebuilt from its step's item for a
    family whose prompts carry no code (6.8), and a cwd-repo job for a family that may not read the repository
    (registry.repo_access: another vendor with privacy code = yes, or no git repository any more): the repository is
    dropped (so the REPO_SCOPE line is empty), section 5 is neither asked (CODEBASE_FIT empty) nor required by the
    contract, and every value is filtered for the family. A copy of the original prompt would still ask for the
    repository the copy cannot read. None as well when the step's fanout no longer yields the job (the filtered copy
    is used then). A family that may read the repository gets a copy that keeps it (fallback_job)."""
    no_repo = job.get("cwd") == "repo" and not registry.repo_access(ctx, fam)
    if not privacy_mod.needs_code_strip(ctx.state, fam) and not no_repo:
        return None
    if job.get("cwd") != "repo" and CODEBASE_HEADING not in ((job.get("contract") or {}).get("headings") or []):
        return None
    defaults = step.get("job") or {}
    try:
        specs = [_item_spec(defaults, item) for item in items_for(ctx, step)]
        spec = next((s for s in specs if s.get("template") and not s.get("prompt_file")
                     and job_id(step["id"], s.get("id")) == job["id"]), None)
    except (EngineError, OSError, ValueError):
        return None
    if spec is None:
        return None
    contract = dict(spec.get("contract") or {})
    if contract.get("headings"):
        contract["headings"] = [h for h in contract["headings"] if h != CODEBASE_HEADING]
    spec.update(contract=contract, fallback=[], vars=dict(spec.get("vars") or {}, CODEBASE_FIT=""))
    if no_repo:
        tools = [t for t in (spec.get("tools") or "none").split("+") if t != "read"]
        spec.update(cwd="empty", repo_root=None, tools="+".join(tools) or "none")
    return spec


def fallback_job(ctx, step, job, fam):
    """A PROVISIONAL copy of a failed job on another family (id suffix -fb-<fam>, same out). A job that reads the
    repository or asks for CHECK section 5 is rebuilt for a family whose prompts carry no code or that may not read the
    repository (_rebuilt_spec). A copy for a family that may read the repository (the usual `<host>-alt` of a repo job)
    keeps cwd repo, its repo_root and read tools, so its prompt's REPO_SCOPE line ('your working folder is its root')
    stays true; any other copy runs in an empty folder."""
    fid = job_id(job["id"], "fb-" + fam)[:80]
    spec = _rebuilt_spec(ctx, step, job, fam)
    if spec is not None:
        return make_job(ctx, step, spec, jid=fid, family=fam, provisional=True)
    repo = job.get("cwd") == "repo" and bool(job.get("repo_root")) and registry.repo_access(ctx, fam)
    tools = job.get("tools") or "none"
    if not repo:  # an empty folder has nothing to read
        tools = "+".join(t for t in tools.split("+") if t != "read") or "none"
    contract = job.get("contract")
    prompt_rel = job.get("prompt_file")
    prompt = ctx.read(prompt_rel)
    if (job.get("cwd") == "repo" and not repo) or privacy_mod.needs_code_strip(ctx.state, fam):
        # the step no longer yields the job (_rebuilt_spec found no item): the copy drops what a rebuild would, the
        # REPO_SCOPE line and CHECK section 5 (asked in the prompt, required by the contract)
        prompt = "\n".join(ln for ln in prompt.split("\n") if not ln.startswith(registry.REPO_SCOPE_START))
        prompt = prompt.replace(registry.CODEBASE_FIT + "\n", "")
        if isinstance(contract, dict) and contract.get("headings"):
            contract = dict(contract, headings=[h for h in contract["headings"] if h != CODEBASE_HEADING])
    spec = {"id": None, "template": job.get("template"), "kind": job.get("kind"), "tools": tools,
            "cwd": "repo" if repo else "empty", "repo_root": job.get("repo_root") if repo else None,
            "out": job.get("out"), "contract": contract, "split": job.get("split"),
            "stub": job.get("stub"), "schema": job.get("schema_file"), "fallback": []}
    # The fallback prompt is a copy (prompts are family-neutral except code privacy, re-applied for the new family).
    prompt = privacy_mod.refilter_prompt(prompt, ctx.state, fam, ctx.run_dir)
    if privacy_mod.code_filtered(ctx.state, fam, ctx.run_dir):
        # the text make_job checks is the text the worker reads: the file, host variant and input_digest use it
        prompt = privacy_mod.strip_code(prompt)
    new_rel = "prompts/%s.prompt.md" % fid
    _write_if_changed(ctx.path(new_rel), prompt)
    spec["prompt_file"] = new_rel
    new = make_job(ctx, step, spec, write=False, jid=fid, family=fam, provisional=True)
    if new["cwd"] == "repo":  # make_job(write=False) records neither the repo label nor the ignore files
        ctx.state.setdefault("privacy", {})["repo_read"] = True
        hide_runs_from_repo(ctx.run_dir, new["repo_root"])
    new["provisional"] = True
    new["fallback"] = []
    new["template"] = job.get("template")
    host_prompt = None
    if ctx.is_host_chain(fam):
        new["host_prompt_file"] = "prompts/%s.host.md" % fid
        host_prompt = host_variant(ctx, prompt, new["out"])
        _write_if_changed(ctx.path(new["host_prompt_file"]), host_prompt)
    new["input_digest"] = input_digest(new, prompt, host_prompt)
    _write_json_if_changed(ctx.path("jobs", fid + ".json"), new)
    return new


def load_job(ctx, jid):
    return ctx.read_json("jobs/%s.json" % jid, None)


IGNORE_ALL = "# ultimate-brainstorm run files: not part of the codebase (hidden from repo-reading jobs)\n*\n"


def hide_runs_from_repo(run_dir, repo_root):
    """Keep the run folders out of a repo-reading job's search (#97): a .gitignore of '*' in the run folder and, when
    the run root is its own folder inside the repository (the default <project>/brainstorm), in the run root too, so
    earlier runs are hidden as well. Existing files are never changed; a run outside the repository needs nothing. The
    prompt's REPO_SCOPE line says the same in words."""
    if not run_dir or not repo_root:
        return
    root = os.path.normcase(os.path.abspath(repo_root))
    run_dir = os.path.abspath(run_dir)
    if not os.path.normcase(run_dir).startswith(root.rstrip("\\/") + os.sep):
        return
    for d in (run_dir, os.path.dirname(run_dir)):
        path = os.path.join(d, ".gitignore")
        if os.path.normcase(d) == root or os.path.exists(path):
            continue
        try:
            textio.write_text_atomic(path, IGNORE_ALL)  # [U-95] agents' Grep/Glob/rg skip git-ignored files
        except OSError:
            pass

#!/usr/bin/env python3
"""Static checks for the kit (KIT_SPEC 11.7). Owner: B4. Standard library only; also used by tests/static/.

Usage:
    python tools/validate_kit.py [--json] [--group G ...] [--no-exec]
    python tools/validate_kit.py --drift-agents-ts agents.ts [--json] [--report drift-report.md]
        (drift.yml: compare vercel-labs/skills src/agents.ts with EXPECTED_UPSTREAM; exit 0 no drift, 1 drift,
         2 unreadable file)

Groups: manifests, tree, skill, openai_yaml, single_skill_md, versions, targets, components, families, workflows.
`versions` also runs `ub.py --version`, `family.py --version`, `bs.py --version` and `install.py version` unless
--no-exec is given. Exit code: 0 when every selected check passes, 1 otherwise, 2 on usage errors.

Python API: run_checks(kit=KIT, groups=None, execute=True) -> {group: [problem, ...]}; each check_<group>(kit)
returns a list of problem strings; drift(agents_ts_text, expected=None) -> list of problems.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK_REL = "skills/ultimate-brainstorm"
MANIFESTS = {
    "claude_plugin": ".claude-plugin/plugin.json",
    "claude_marketplace": ".claude-plugin/marketplace.json",
    "codex_plugin": ".codex-plugin/plugin.json",
    "codex_marketplace": ".agents/plugins/marketplace.json",
    "kimi_plugin": ".kimi-plugin/plugin.json",
    "kimi_marketplace": ".kimi-plugin/marketplace.json",
}
VERSIONED = ("claude_plugin", "codex_plugin", "kimi_plugin")
FORBIDDEN_ROOT = ("plugin.json", "agents", "bin", "hooks", ".mcp.json", "commands")
SKILL_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
KIMI_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", ".venv", "venv"}


def _p(kit, rel):
    return os.path.join(kit, *rel.split("/"))


def load_json(kit, rel, problems):
    path = _p(kit, rel)
    if not os.path.isfile(path):
        problems.append("missing: %s" % rel)
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except ValueError as e:
        problems.append("%s: invalid JSON (%s)" % (rel, e))
        return None


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            for s in _strings(v):
                yield s
    elif isinstance(obj, list):
        for v in obj:
            for s in _strings(v):
                yield s


# ---------------------------------------------------------------- manifests

def check_manifests(kit=KIT):
    problems = []
    data = {k: load_json(kit, rel, problems) for k, rel in MANIFESTS.items()}
    cp = data["claude_plugin"]
    if isinstance(cp, dict) and not cp.get("name"):
        problems.append(".claude-plugin/plugin.json: missing name")
    cm = data["claude_marketplace"]
    if isinstance(cm, dict):
        if not isinstance(cm.get("owner"), dict) or not cm["owner"].get("name"):
            problems.append(".claude-plugin/marketplace.json: missing owner.name")
        plugins = cm.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            problems.append(".claude-plugin/marketplace.json: plugins[] missing or empty")
        else:
            for i, p in enumerate(plugins):
                if not isinstance(p, dict) or not p.get("source") or not p.get("name"):
                    problems.append(".claude-plugin/marketplace.json: plugins[%d] lacks name or source" % i)
    xp = data["codex_plugin"]
    if isinstance(xp, dict):
        if not xp.get("name"):
            problems.append(".codex-plugin/plugin.json: missing name")
        if not xp.get("skills"):
            problems.append(".codex-plugin/plugin.json: missing skills")
        dp = (xp.get("interface") or {}).get("defaultPrompt") if isinstance(xp.get("interface"), dict) else None
        if not isinstance(dp, list) or not dp:
            problems.append(".codex-plugin/plugin.json: interface.defaultPrompt missing")
        else:
            if len(dp) > 3:
                problems.append(".codex-plugin/plugin.json: interface.defaultPrompt has more than 3 entries")
            for s in dp:
                if not isinstance(s, str) or len(s) > 128:
                    problems.append(".codex-plugin/plugin.json: defaultPrompt entry longer than 128 chars: %r" % s)
    xm = data["codex_marketplace"]
    if isinstance(xm, dict):
        plugins = xm.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            problems.append(".agents/plugins/marketplace.json: plugins[] missing or empty")
        else:
            for i, p in enumerate(plugins):
                if not isinstance(p, dict) or not p.get("source"):
                    problems.append(".agents/plugins/marketplace.json: plugins[%d] lacks source" % i)
    kp = data["kimi_plugin"]
    if isinstance(kp, dict) and not KIMI_NAME.match(str(kp.get("name") or "")):
        problems.append(".kimi-plugin/plugin.json: name %r does not match %s" % (kp.get("name"), KIMI_NAME.pattern))
    km = data["kimi_marketplace"]
    if isinstance(km, dict) and km.get("version") != "2":
        problems.append('.kimi-plugin/marketplace.json: version must be "2"')
    for key, obj in data.items():
        if obj is None:
            continue
        rel = MANIFESTS[key]
        for s in _strings(obj):
            if "\\" in s:
                problems.append("%s: path with a backslash: %r" % (rel, s))
            if s.startswith("./"):
                target = _p(kit, s[2:].rstrip("/")) if s != "./" else kit
                if not os.path.exists(target):
                    problems.append("%s: path %s does not exist" % (rel, s))
    return problems


def check_tree(kit=KIT):
    problems = []
    for name in FORBIDDEN_ROOT:
        if os.path.exists(os.path.join(kit, name)):
            problems.append("forbidden at the repo root: %s" % name)
    return problems


# ---------------------------------------------------------------- SKILL.md

def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        if v[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return v


def parse_frontmatter(text):
    """(dict, error) for the YAML frontmatter subset used by SKILL.md: top-level `key: value` and one level of
    indented `key: value` under a key with an empty value. Block scalars (| and >) are joined with spaces."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "first line is not ---"
    try:
        end = lines.index("---", 1)
    except ValueError:
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            return None, "frontmatter is not closed with ---"
    out, cur_key, block = {}, None, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] not in " \t":
            m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
            if not m:
                return None, "unparsable frontmatter line: %r" % raw
            key, val = m.group(1), m.group(2).strip()
            cur_key, block = key, None
            if val in ("|", ">", "|-", ">-"):
                out[key] = ""
                block = key
            elif val == "":
                out[key] = {}
            else:
                out[key] = _unquote(val)
        else:
            if block is not None:
                out[block] = (out[block] + " " + raw.strip()).strip()
                continue
            m = re.match(r"^\s+([A-Za-z0-9_-]+):\s*(.*)$", raw)
            if m and isinstance(out.get(cur_key), dict):
                out[cur_key][m.group(1)] = _unquote(m.group(2))
            elif isinstance(out.get(cur_key), str):
                out[cur_key] = (out[cur_key] + " " + raw.strip()).strip()
    return out, None


def check_skill(kit=KIT):
    problems = []
    path = _p(kit, SK_REL + "/SKILL.md")
    if not os.path.isfile(path):
        return ["missing: %s/SKILL.md" % SK_REL]
    size = os.path.getsize(path)
    if size > 12 * 1024:
        problems.append("SKILL.md is %d bytes, more than 12 KB" % size)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if text.startswith("﻿"):
        problems.append("SKILL.md starts with a BOM")
        text = text[1:]
    if text.split("\n", 1)[0].rstrip("\r") != "---":
        problems.append("SKILL.md: the first line is not ---")
    fm, err = parse_frontmatter(text)
    if err:
        problems.append("SKILL.md: " + err)
        return problems
    extra = sorted(set(fm) - SKILL_KEYS)
    if extra:
        problems.append("SKILL.md: frontmatter keys not allowed: %s" % ", ".join(extra))
    if fm.get("name") != os.path.basename(SK_REL):
        problems.append("SKILL.md: name %r differs from the folder name %r" % (fm.get("name"),
                                                                             os.path.basename(SK_REL)))
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        problems.append("SKILL.md: description missing")
    elif len(desc) > 1024:
        problems.append("SKILL.md: description has %d characters, more than 1024" % len(desc))
    comp = fm.get("compatibility")
    if isinstance(comp, str) and len(comp) > 500:
        problems.append("SKILL.md: compatibility has %d characters, more than 500" % len(comp))
    return problems


def skill_version(kit=KIT):
    path = _p(kit, SK_REL + "/SKILL.md")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        fm, _err = parse_frontmatter(f.read())
    meta = (fm or {}).get("metadata")
    return meta.get("version") if isinstance(meta, dict) else None


def check_openai_yaml(kit=KIT):
    rel = SK_REL + "/agents/openai.yaml"
    path = _p(kit, rel)
    if not os.path.isfile(path):
        return ["missing: %s" % rel]
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(?m)^policy:\s*\n((?:[ \t]+.*\n?)+)", text)
    if not m or not re.search(r"(?m)^[ \t]+allow_implicit_invocation:\s*false\s*$", m.group(1)):
        return ["%s: policy.allow_implicit_invocation is not false" % rel]
    return []


def find_skill_md(kit=KIT):
    found = []
    for dirpath, dirnames, filenames in os.walk(kit):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.lower() == "skill.md":
                found.append(os.path.relpath(os.path.join(dirpath, name), kit).replace("\\", "/"))
    return sorted(found)


def check_single_skill_md(kit=KIT):
    found = find_skill_md(kit)
    expected = SK_REL + "/SKILL.md"
    if found == [expected]:
        return []
    if not found:
        return ["no SKILL.md found (expected %s)" % expected]
    return ["exactly one SKILL.md must exist (%s); found: %s" % (expected, ", ".join(found))]


# ---------------------------------------------------------------- versions

def read_version(kit=KIT):
    path = os.path.join(kit, "VERSION")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def changelog_heading(kit=KIT):
    path = os.path.join(kit, "CHANGELOG.md")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.startswith("#"):
                return line.strip()
    return None


VERSION_COMMANDS = (
    (SK_REL + "/scripts/ub.py", ["--version"]),
    (SK_REL + "/scripts/family.py", ["--version"]),
    (SK_REL + "/scripts/bs.py", ["--version"]),
    ("install/install.py", ["version"]),
)


def command_version(kit, rel, args, timeout=60):
    """(output, error) of `python <rel> <args>`."""
    path = _p(kit, rel)
    if not os.path.isfile(path):
        return None, "missing: %s" % rel
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run([sys.executable, path] + list(args), cwd=kit, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "%s %s: %s" % (rel, " ".join(args), e)
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        return out, "%s %s exited %d" % (rel, " ".join(args), proc.returncode)
    return out, None


def check_versions(kit=KIT, execute=True):
    problems = []
    version = read_version(kit)
    if not version:
        return ["missing or empty: VERSION"]
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        problems.append("VERSION %r is not X.Y.Z" % version)
    for key in VERSIONED:
        sub = []
        obj = load_json(kit, MANIFESTS[key], sub)
        if obj is None:
            problems.extend(sub)
        elif obj.get("version") != version:
            problems.append("%s: version %r != VERSION %r" % (MANIFESTS[key], obj.get("version"), version))
    sv = skill_version(kit)
    if sv != version:
        problems.append("SKILL.md metadata.version %r != VERSION %r" % (sv, version))
    head = changelog_heading(kit)
    if head is None:
        problems.append("CHANGELOG.md: missing or has no heading")
    elif version not in head:
        problems.append("CHANGELOG.md top heading %r does not contain %s" % (head, version))
    init = _p(kit, SK_REL + "/scripts/ublib/__init__.py")
    if os.path.isfile(init):
        with open(init, "r", encoding="utf-8") as f:
            m = re.search(r'^KIT_VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
        if not m or m.group(1) != version:
            problems.append("ublib.KIT_VERSION %r != VERSION %r" % (m.group(1) if m else None, version))
    if execute:
        for rel, args in VERSION_COMMANDS:
            out, err = command_version(kit, rel, args)
            if err:
                problems.append(err)
            elif version not in (out or ""):
                problems.append("%s %s printed %r, not %s" % (rel, " ".join(args), (out or "").strip()[:80],
                                                              version))
    return problems


# ---------------------------------------------------------------- targets / components / families

def _is_argv(x):
    return isinstance(x, list) and x and all(isinstance(a, str) for a in x)


def check_targets(kit=KIT):
    problems = []
    t = load_json(kit, "install/targets.json", problems)
    if not isinstance(t, dict):
        return problems
    if t.get("schema") != 1:
        problems.append("targets.json: schema must be 1")
    if not isinstance(t.get("verified"), str) or not t["verified"]:
        problems.append("targets.json: verified (dated string) missing")
    kit_obj = t.get("kit") if isinstance(t.get("kit"), dict) else {}
    for k in ("name", "repo", "skill", "marker", "marketplace", "plugin"):
        if not kit_obj.get(k):
            problems.append("targets.json: kit.%s missing" % k)
    if kit_obj.get("marker") and kit_obj["marker"] != ".ub-owned":
        problems.append("targets.json: kit.marker must be .ub-owned")
    rp = t.get("runtime_paths")
    if not isinstance(rp, list) or not rp:
        problems.append("targets.json: runtime_paths missing")
    else:
        for rel in rp:
            if not os.path.exists(_p(kit, rel)):
                problems.append("targets.json: runtime path %s does not exist" % rel)
        for must in ("skills", "install", "profiles", "VERSION"):
            if must not in rp:
                problems.append("targets.json: runtime_paths lacks %s" % must)
    agents = t.get("agents") if isinstance(t.get("agents"), dict) else {}
    for name in ("claude-code", "codex", "kimi", "zcode"):
        a = agents.get(name)
        if not isinstance(a, dict):
            problems.append("targets.json: agents.%s missing" % name)
            continue
        for k in ("detect", "copy", "invoke", "reload"):
            if k not in a:
                problems.append("targets.json: agents.%s.%s missing" % (name, k))
        copy = a.get("copy") if isinstance(a.get("copy"), dict) else {}
        for scope in ("user", "project"):
            if not isinstance(copy.get(scope), str):
                problems.append("targets.json: agents.%s.copy.%s missing" % (name, scope))
    for name in ("claude-code", "codex"):
        native = (agents.get(name) or {}).get("native")
        if not isinstance(native, dict):
            problems.append("targets.json: agents.%s.native missing" % name)
            continue
        if not isinstance(native.get("min"), str):
            problems.append("targets.json: agents.%s.native.min missing" % name)
        for k in ("marketplace_add", "install", "list", "uninstall", "marketplace_remove"):
            if not _is_argv(native.get(k)):
                problems.append("targets.json: agents.%s.native.%s is not an argv list" % (name, k))
    if (agents.get("codex") or {}).get("copy", {}).get("user") not in (None, "~/.agents/skills"):
        problems.append("targets.json: codex user copy must be ~/.agents/skills (U-11)")
    return problems


_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _unpinned(step, comp):
    """Why a component step runs third-party content that is not pinned (None when it is pinned): npx packages need an
    exact version and `skills add` sources a #<commit>; marketplace sources a ref plus the component's 40-hex "commit"
    (install.py checks the clone against it); `uv tool install` a git source at a commit or pkg==version."""
    exe = step[0]
    if exe == "npx":
        pkgs = [a for a in step[1:] if not a.startswith("-")]
        if not pkgs or not re.search(r".@\d+\.\d+\.\d+$", pkgs[0]):
            return "npx package without an exact version"
        if pkgs[1:2] == ["add"] and len(pkgs) > 2 and not re.search(r"#[0-9a-f]{40}$", pkgs[2]):
            return "skills source without #<40-hex commit>"
        return None
    if step[1:4] == ["plugin", "marketplace", "add"]:
        if len(step) < 5 or "@" not in step[4]:
            return "marketplace source without an @ref"
        if not _SHA40.match(str(comp.get("commit") or "")):
            return "marketplace source without a 40-hex \"commit\" pin on the component"
        return None
    if exe == "uv" and step[1:3] == ["tool", "install"]:
        src = step[step.index("--from") + 1] if "--from" in step else ""
        if not (re.search(r"@[0-9a-f]{40}$", src) or any("==" in a for a in step[3:])):
            return "uv tool without --from <git>@<40-hex commit> or ==<version>"
    return None


def _archive_problems(name, comp):
    """An archive component is pinned twice: the archive of one 40-hex commit (the component's "commit") and, per skill
    folder, the SHA-256 of its content (install.py tree_sha256), which no re-compression of the archive changes."""
    problems = []
    arc = comp.get("archive")
    commit = str(comp.get("commit") or "")
    if not isinstance(arc, dict) or not _SHA40.match(commit):
        return ["components.json: %s.archive needs an object and a 40-hex \"commit\"" % name]
    url, fname = str(arc.get("url") or ""), str(arc.get("file") or "")
    if not re.match(r"^https://codeload\.github\.com/[\w.-]+/[\w.-]+/tar\.gz/%s$" % commit, url):
        problems.append("components.json: %s.archive.url is not a codeload tar.gz of the commit %s" % (name, commit))
    if not re.match(r"^[\w.-]+\.tar\.gz$", fname):
        problems.append("components.json: %s.archive.file must be a plain <name>.tar.gz" % name)
    skills = arc.get("skills") if isinstance(arc.get("skills"), dict) else {}
    if sorted(skills) != sorted(comp.get("skills") or []):
        problems.append("components.json: %s.archive.skills must pin exactly the component's skills" % name)
    for skill, pin in sorted(skills.items()):
        if not isinstance(pin, dict) or not re.match(r"^[0-9a-f]{64}$", str(pin.get("sha256") or "")) or \
                not re.match(r"^[\w.-]+(/[\w.-]+)*$", str(pin.get("path") or "")) or ".." in str(pin.get("path")):
            problems.append("components.json: %s.archive.skills.%s needs a relative path and a 64-hex sha256"
                            % (name, skill))
    return problems


def check_components(kit=KIT):
    problems = []
    c = load_json(kit, "install/components.json", problems)
    if not isinstance(c, dict):
        return problems
    if c.get("schema") != 1:
        problems.append("components.json: schema must be 1")
    comps = c.get("components") if isinstance(c.get("components"), dict) else {}
    if not comps:
        problems.append("components.json: components missing")
    core = c.get("core")
    if not isinstance(core, list) or not core:
        problems.append("components.json: core missing")
    else:
        for name in core:
            if name not in comps:
                problems.append("components.json: core component %s is not defined" % name)
            elif comps[name].get("extra"):
                problems.append("components.json: core component %s is marked extra" % name)
    for name, comp in comps.items():
        if not isinstance(comp, dict):
            problems.append("components.json: %s is not an object" % name)
            continue
        if "archive" in comp:
            problems.extend(_archive_problems(name, comp))
        for agent, spec in comp.items():
            if agent in ("ref", "extra", "needs", "env", "commit", "source_match", "skills", "archive"):
                continue
            if not isinstance(spec, dict):
                problems.append("components.json: %s.%s is not an object" % (name, agent))
                continue
            steps = spec.get("steps")
            if steps is not None and (not isinstance(steps, list) or not all(_is_argv(s) for s in steps)):
                problems.append("components.json: %s.%s.steps must be a list of argv lists" % (name, agent))
            if spec.get("copy_to") and "archive" not in comp:
                problems.append("components.json: %s.%s.copy_to needs the component's archive" % (name, agent))
            if steps is None and "manual" not in spec and not spec.get("copy_to"):
                problems.append("components.json: %s.%s has neither steps, copy_to nor manual" % (name, agent))
            for step in steps or []:
                for arg in step:
                    if re.search(r"_(KEY|TOKEN)\b", arg) and "<" not in arg:
                        problems.append("components.json: %s.%s step mentions a key value: %r" % (name, agent, arg))
                why = _unpinned(step, comp)
                if why:
                    problems.append("components.json: %s.%s step %s: %s" % (name, agent, " ".join(step), why))
    clis = c.get("clis")
    if not isinstance(clis, dict) or not all(isinstance(v, dict) and v.get("npm") for v in clis.values()):
        problems.append("components.json: clis entries need an npm package")
    return problems


def check_families(kit=KIT):
    problems = []
    f = load_json(kit, SK_REL + "/scripts/families.default.json", problems)
    if not isinstance(f, dict):
        return problems
    fams = f.get("families") if isinstance(f.get("families"), dict) else {}
    backends = f.get("backends") if isinstance(f.get("backends"), dict) else {}
    providers = f.get("providers") if isinstance(f.get("providers"), dict) else {}
    for name in f.get("order") or []:
        if name not in fams:
            problems.append("families.default.json: order names unknown family %s" % name)
    for name, fam in fams.items():
        for b in (fam or {}).get("backends") or []:
            if b not in backends:
                problems.append("families.default.json: family %s references unknown backend %s" % (name, b))
    for name, b in backends.items():
        prov = (b or {}).get("provider")
        if prov and prov not in providers:
            problems.append("families.default.json: backend %s references unknown provider %s" % (name, prov))
    for name, p in providers.items():
        for k in ("token_env", "token_var", "base_url", "models"):
            if k not in (p or {}):
                problems.append("families.default.json: provider %s lacks %s" % (name, k))
    return problems


# ---------------------------------------------------------------- workflows (supply chain, 10.7 / 11.8)

WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/release.yml", ".github/workflows/drift.yml")
_USES_RE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def _jobs(text):
    """[(job id, body)] of a workflow file's top-level `jobs:` map (two-space indented job ids)."""
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        start = lines.index("jobs:")
    except ValueError:
        return []
    out, cur = [], None
    for line in lines[start + 1:]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        m = _JOB_RE.match(line)
        if m:
            cur = [m.group(1), []]
            out.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return [(j, "\n".join(body)) for j, body in out]


def _publish_problems(body):
    """The publishing job of release.yml never replaces a release: before `gh release create` it fails (exit 1) when
    `gh release view` finds a release for the tag, and it never uploads to, edits or deletes a release."""
    problems = []
    create = body.find("gh release create")
    refuse = re.search(r'if gh release view "\$GITHUB_REF_NAME"[^\n]*; then\n(?:[^\n]*\n){0,2}?\s*exit 1\n', body)
    if create < 0:
        problems.append("release.yml: the publish job never runs gh release create")
    elif refuse is None or refuse.start() > create:
        problems.append("release.yml: the publish job must fail (exit 1) when a release for the tag already exists, "
                        "before gh release create")
    for verb in ("upload", "edit", "delete", "delete-asset"):
        if re.search(r"\bgh release %s\b" % verb, body):
            problems.append("release.yml: gh release %s changes a published release" % verb)
    return problems


def _release_build_problems(text):
    """release.yml runs tools/release.py with --notes, and --no-acceptance only behind the CHANGELOG override line."""
    problems = []
    runs = [ln for ln in text.split("\n")
            if re.search(r"\btools/release\.py\b", ln) and not ln.lstrip().startswith("#")]
    if not runs:
        problems.append("release.yml: tools/release.py never runs")
    body = "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))
    if runs and "--notes release-notes.md" not in body:
        problems.append("release.yml: tools/release.py runs without --notes release-notes.md (the acceptance state)")
    for ln in runs:
        if "--no-acceptance" in ln:
            problems.append("release.yml: tools/release.py runs with --no-acceptance unconditionally")
    if "--no-acceptance" in body and not re.search(r"if grep -q '\^Acceptance override:' release-notes\.md; then\n"
                                                    r"\s*set -- \"\$@\" --no-acceptance\n", body):
        problems.append("release.yml: --no-acceptance is passed without the CHANGELOG line 'Acceptance override:'")
    return problems


def check_workflows(kit=KIT):
    """Every action pinned to a full commit SHA with a `# vX.Y.Z` comment, checkout without persisted credentials,
    `permissions: {}` at the top and per job, a timeout on every job, ci.py with --timeout, a release that never
    replaces a release (it fails when one exists for the tag) and attests its assets, the acceptance gate of
    release.py kept in the build, and a drift issue that is updated instead of re-opened."""
    problems = []
    texts = {}
    for rel in WORKFLOWS:
        path = _p(kit, rel)
        if not os.path.isfile(path):
            problems.append("missing: %s" % rel)
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = texts[rel] = f.read().replace("\r\n", "\n")
        lines = text.split("\n")
        if not re.search(r"(?m)^permissions:\s*\{\}\s*$", text):
            problems.append("%s: the top-level permissions must be {} (each job asks for what it needs)" % rel)
        for i, line in enumerate(lines, 1):
            m = _USES_RE.match(line)
            if not m or m.group(1).startswith("./"):
                continue
            ref, rest = m.group(1), m.group(2)
            if not re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", ref) or not re.search(r"#\s*v\d+\.\d+\.\d+", rest):
                problems.append("%s:%d: %s is not pinned to a full commit SHA with a # vX.Y.Z comment" % (rel, i, ref))
            if ref.startswith("actions/checkout@") and \
                    not re.search(r"persist-credentials:\s*false", "\n".join(lines[i:i + 4])):
                problems.append("%s:%d: actions/checkout without persist-credentials: false" % (rel, i))
        for i, line in enumerate(lines, 1):
            if re.search(r"\bpython tools/ci\.py\b", line) and "--timeout" not in line:
                problems.append("%s:%d: tools/ci.py runs without --timeout" % (rel, i))
            if "--clobber" in line:
                problems.append("%s:%d: --clobber replaces published release assets" % (rel, i))
        for job, body in _jobs(text):
            if re.search(r"(?m)^    uses:\s*\./", body):
                continue  # a reusable-workflow call: its jobs carry their own timeouts
            if not re.search(r"(?m)^    timeout-minutes:\s*\d+\s*$", body):
                problems.append("%s: job %s has no timeout-minutes" % (rel, job))
            if not re.search(r"(?m)^    permissions:", body):
                problems.append("%s: job %s does not declare its permissions" % (rel, job))
    rel_text = texts.get(".github/workflows/release.yml", "")
    if rel_text:
        if "actions/attest-build-provenance@" not in rel_text:
            problems.append("release.yml: the assets are not attested (actions/attest-build-provenance)")
        writers = [j for j, body in _jobs(rel_text) if re.search(r"(?m)^      contents:\s*write", body)]
        if len(writers) != 1:
            problems.append("release.yml: exactly one job (publish) may hold contents: write, found %s" % writers)
        for j, body in _jobs(rel_text):
            if j in writers and ("id-token: write" not in body or "attestations: write" not in body):
                problems.append("release.yml: job %s needs id-token: write and attestations: write" % j)
            if j in writers:
                problems.extend(_publish_problems(body))
        problems.extend(_release_build_problems(rel_text))
    drift_text = texts.get(".github/workflows/drift.yml", "")
    if drift_text and "gh issue create" in drift_text and "gh issue list" not in drift_text:
        problems.append("drift.yml: opens an issue without looking for the open one first")
    return problems


# ---------------------------------------------------------------- unverified items (KIT_SPEC section 15, 11.9)

SPEC_REL = "docs/design/KIT_SPEC.md"
ACCEPTANCE_REL = "docs/ACCEPTANCE.md"
_U_ROW = re.compile(r"^\| U-(\d+) ", re.M)
_U_TAG = re.compile(r"\[U-(\d+)")
_TAG_SKIP_DIRS = SKIP_DIRS | {"research"}
_TAG_DOT_DIRS = (".github", ".claude-plugin", ".codex-plugin", ".agents", ".kimi-plugin")  # other .dirs are not the kit


def _read(kit, rel):
    try:
        with open(_p(kit, rel), "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def code_tags(kit=KIT):
    """{n: [files]} for every [U-n] tag outside the spec and ACCEPTANCE.md (code, configuration and docs)."""
    tags = {}
    for dirpath, dirnames, filenames in os.walk(kit):
        dirnames[:] = [d for d in dirnames if d not in _TAG_SKIP_DIRS and (not d.startswith(".") or d in _TAG_DOT_DIRS)]
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, kit).replace(os.sep, "/")
            if rel in (SPEC_REL, ACCEPTANCE_REL) or name.endswith((".pyc", ".png", ".zip", ".gz")):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            for n in set(_U_TAG.findall(text)):
                tags.setdefault(int(n), []).append(rel)
    return tags


def check_unverified(kit=KIT):
    """KIT_SPEC section 15 lists exactly the items docs/ACCEPTANCE.md has a live-check row for, and every [U-n] tag in
    the kit names one of them, so no assumption is used without its fallback and its live check."""
    problems = []
    spec, acc = _read(kit, SPEC_REL), _read(kit, ACCEPTANCE_REL)
    if spec is None or acc is None:
        return ["missing: %s" % (SPEC_REL if spec is None else ACCEPTANCE_REL)]
    m = re.search(r"(?ms)^## 15\..*?(?=^## 16\.)", spec)
    if not m:
        return ["%s: section 15 (Unverified items) not found before section 16" % SPEC_REL]
    spec_ids = set(int(n) for n in _U_ROW.findall(m.group(0)))
    acc_ids = set(int(n) for n in _U_ROW.findall(acc))
    for n in sorted(spec_ids - acc_ids):
        problems.append("U-%d is in KIT_SPEC section 15 but has no row in %s" % (n, ACCEPTANCE_REL))
    for n in sorted(acc_ids - spec_ids):
        problems.append("U-%d has a row in %s but is not in KIT_SPEC section 15" % (n, ACCEPTANCE_REL))
    for n, files in sorted(code_tags(kit).items()):
        if n not in spec_ids:
            problems.append("[U-%d] is used in %s but is not in KIT_SPEC section 15"
                            % (n, ", ".join(sorted(files)[:3])))
    return problems


CHECKS = {
    "manifests": check_manifests,
    "tree": check_tree,
    "skill": check_skill,
    "openai_yaml": check_openai_yaml,
    "single_skill_md": check_single_skill_md,
    "versions": check_versions,
    "targets": check_targets,
    "components": check_components,
    "families": check_families,
    "workflows": check_workflows,
    "unverified": check_unverified,
}


def run_checks(kit=KIT, groups=None, execute=True):
    out = {}
    for name in groups or CHECKS:
        fn = CHECKS[name]
        out[name] = fn(kit, execute=execute) if name == "versions" else fn(kit)
    return out


# ---------------------------------------------------------------- drift (drift.yml)

# The folders vercel-labs/skills (`npx skills add -a <agent>`, src/agents.ts) is expected to use, per agent key. This is
# an explicit map, not the installer's copy targets: the installer deliberately writes ~/.agents/skills for Codex (never
# the -g target ~/.codex/skills) and {kimi_home}/skills for Kimi (10.3). A difference means upstream moved a folder:
# review install/targets.json, install/install.py and this map by hand.
EXPECTED_UPSTREAM = {
    "claude-code": {"project": ".claude/skills", "user": "~/.claude/skills"},
    "codex": {"project": ".agents/skills", "user": "~/.codex/skills"},
    "kimi-code-cli": {"project": ".agents/skills", "user": "~/.agents/skills"},
    "zcode": {"project": ".zcode/skills", "user": "~/.zcode/skills"},
}
# Home variables agents.ts joins paths onto, when its own `const` declarations cannot be read.
HOME_VARS = {"home": "~", "claudeHome": "~/.claude", "codexHome": "~/.codex", "configHome": "~/.config"}
_Q = "['\"`]"
_LIT = "([^'\"`\\n]+)"


def _home_vars(text):
    """{variable: path} from `const <v> = ... join(home, '<dir>')` declarations in agents.ts, over HOME_VARS."""
    out = dict(HOME_VARS)
    for m in re.finditer(r"const\s+(\w+)\s*=[^;\n]*?\bjoin\(\s*home\s*,\s*%s%s%s\s*\)" % (_Q, _LIT, _Q), text):
        out[m.group(1)] = "~/" + m.group(2).strip("/")
    return out


def _entry_paths(block, homes):
    """{"project": ..., "user": ...} read from one agents.ts entry (skillsDir, globalSkillsDir); missing keys = the
    entry has a form this parser does not know."""
    got = {}
    m = re.search(r"\bskillsDir\s*:\s*%s%s%s" % (_Q, _LIT, _Q), block)
    if m:
        got["project"] = re.sub(r"^\./", "", m.group(1)).strip("/")
    m = re.search(r"\bglobalSkillsDir\s*:\s*join\(\s*(\w+)\s*,\s*%s%s%s\s*\)" % (_Q, _LIT, _Q), block)
    if m and m.group(1) in homes:
        got["user"] = homes[m.group(1)].rstrip("/") + "/" + m.group(2).strip("/")
    return got


def _agent_block(text, key):
    m = re.search(r"""(?<![\w-])['"]?%s['"]?\s*:\s*\{""" % re.escape(key), text)
    if not m:
        return None
    depth, i = 0, m.end() - 1
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[m.end() - 1:i + 1]
        i += 1
    return text[m.end() - 1:]


def drift(agents_ts_text, expected=None):
    """Compare the skills folders vercel-labs/skills uses (src/agents.ts) with EXPECTED_UPSTREAM, exactly, per agent
    and scope. An entry this parser cannot read is one "parser-outdated" problem (never a guess)."""
    problems = []
    homes = _home_vars(agents_ts_text)
    for key, want in sorted((expected or EXPECTED_UPSTREAM).items()):
        block = _agent_block(agents_ts_text, key)
        if block is None:
            problems.append("agents.ts: no entry for %s" % key)
            continue
        got = _entry_paths(block, homes)
        for scope in ("project", "user"):
            if scope not in got:
                problems.append("parser-outdated: %s: cannot read its %s skills folder (skillsDir / globalSkillsDir "
                                "form changed); update tools/validate_kit.py" % (key, scope))
            elif got[scope] != want[scope]:
                problems.append("%s %s folder is %r upstream, expected %r" % (key, scope, got[scope], want[scope]))
    return problems


def drift_report(problems):
    """Markdown for the drift issue, ending in a marker drift.yml compares to avoid repeating the same report."""
    digest = hashlib.sha256("\n".join(sorted(problems)).encode("utf-8")).hexdigest()
    lines = ["The weekly drift check found differences between vercel-labs/skills `src/agents.ts` and the folders the "
             "installer expects (tools/validate_kit.py EXPECTED_UPSTREAM). Review install/targets.json, "
             "install/install.py and that map by hand; this workflow never edits the repository.", ""]
    lines += ["- " + p for p in problems]
    lines += ["", "<!-- drift-sha: %s -->" % digest]
    return "\n".join(lines) + "\n"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="validate_kit.py", description="Static checks for the kit (KIT_SPEC 11.7)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--group", action="append", choices=sorted(CHECKS))
    ap.add_argument("--no-exec", action="store_true", help="do not run the --version commands")
    ap.add_argument("--kit", default=KIT)
    ap.add_argument("--drift-agents-ts", metavar="FILE")
    ap.add_argument("--report", metavar="FILE", help="with --drift-agents-ts: write the issue text (Markdown) here")
    args = ap.parse_args(argv)
    if args.drift_agents_ts:
        try:
            with open(args.drift_agents_ts, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            sys.stderr.write("validate_kit.py: cannot read %s: %s\n" % (args.drift_agents_ts, e))
            return 2
        problems = drift(text)
        if args.report:
            with open(args.report, "w", encoding="utf-8", newline="\n") as f:
                f.write(drift_report(problems))
        if args.json:
            print(json.dumps({"drift": problems}, ensure_ascii=True))
        else:
            for p in problems:
                print("DRIFT: " + p)
            print("drift: %s" % ("none" if not problems else "%d mismatch(es)" % len(problems)))
        return 1 if problems else 0
    results = run_checks(args.kit, args.group, execute=not args.no_exec)
    failed = sum(len(v) for v in results.values())
    if args.json:
        print(json.dumps({"ok": failed == 0, "checks": results}, ensure_ascii=True))
    else:
        for group, problems in results.items():
            print("%-16s %s" % (group, "PASS" if not problems else "FAIL (%d)" % len(problems)))
            for p in problems:
                print("    - " + p)
        print("static checks: %s" % ("all passed" if not failed else "%d problem(s)" % failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

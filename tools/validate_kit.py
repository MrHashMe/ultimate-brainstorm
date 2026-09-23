#!/usr/bin/env python3
"""Static checks for the kit (KIT_SPEC 11.7). Owner: B4. Standard library only; also used by tests/static/.

Usage:
    python tools/validate_kit.py [--json] [--group G ...] [--no-exec]
    python tools/validate_kit.py --drift-agents-ts agents.ts [--json]     (drift.yml: compare with targets.json)

Groups: manifests, tree, skill, openai_yaml, single_skill_md, versions, targets, components, families.
`versions` also runs `ub.py --version`, `family.py --version`, `bs.py --version` and `install.py version` unless
--no-exec is given. Exit code: 0 when every selected check passes, 1 otherwise, 2 on usage errors.

Python API: run_checks(kit=KIT, groups=None, execute=True) -> {group: [problem, ...]}; each check_<group>(kit)
returns a list of problem strings; drift(agents_ts_text, targets) -> list of problems.
"""

import argparse
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
    "bundle_plugin": "bundles/stack/.claude-plugin/plugin.json",
}
VERSIONED = ("claude_plugin", "codex_plugin", "kimi_plugin", "bundle_plugin")
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
    bp = data["bundle_plugin"]
    if isinstance(bp, dict) and not bp.get("name"):
        problems.append("bundles/stack/.claude-plugin/plugin.json: missing name")
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
        for agent, spec in comp.items():
            if agent in ("ref", "extra", "needs", "env"):
                continue
            if not isinstance(spec, dict):
                problems.append("components.json: %s.%s is not an object" % (name, agent))
                continue
            steps = spec.get("steps")
            if steps is not None and (not isinstance(steps, list) or not all(_is_argv(s) for s in steps)):
                problems.append("components.json: %s.%s.steps must be a list of argv lists" % (name, agent))
            if steps is None and "manual" not in spec:
                problems.append("components.json: %s.%s has neither steps nor manual" % (name, agent))
            for step in steps or []:
                for arg in step:
                    if re.search(r"_(KEY|TOKEN)\b", arg) and "<" not in arg:
                        problems.append("components.json: %s.%s step mentions a key value: %r" % (name, agent, arg))
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
}


def run_checks(kit=KIT, groups=None, execute=True):
    out = {}
    for name in groups or CHECKS:
        fn = CHECKS[name]
        out[name] = fn(kit, execute=execute) if name == "versions" else fn(kit)
    return out


# ---------------------------------------------------------------- drift (drift.yml)

AGENT_KEYS = {"claude-code": "claude-code", "codex": "codex", "kimi": "kimi-code-cli", "zcode": "zcode"}
HOME_TOKENS = {"{claude_home}": ".claude", "{kimi_home}": ".kimi-code"}


def _norm_target(path):
    p = path
    for k, v in HOME_TOKENS.items():
        p = p.replace(k, v)
    p = p.replace("{project}/", "").replace("~/", "")
    return p.strip("/")


def _agent_block(text, key):
    m = re.search(r"""['"]?%s['"]?\s*:\s*\{""" % re.escape(key), text)
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


def drift(agents_ts_text, targets):
    """Compare the skills dirs that vercel-labs/skills uses (src/agents.ts) with targets.json copy paths."""
    problems = []
    agents = (targets or {}).get("agents") or {}
    for ours, theirs in AGENT_KEYS.items():
        block = _agent_block(agents_ts_text, theirs)
        if block is None:
            problems.append("agents.ts: no entry for %s" % theirs)
            continue
        literals = [s.strip("/") for s in re.findall(r"""['"`]([^'"`\n]*skills[^'"`\n]*)['"`]""", block)]
        copy = (agents.get(ours) or {}).get("copy") or {}
        for scope in ("user", "project"):
            want = copy.get(scope)
            if not isinstance(want, str):
                continue
            norm = _norm_target(want)
            if not any(lit == norm or lit.endswith("/" + norm) or norm.endswith(lit) for lit in literals if lit):
                problems.append("%s %s path %r (normalized %r) not found in agents.ts %s entry %s" % (
                    ours, scope, want, norm, theirs, literals[:6]))
    return problems


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
    args = ap.parse_args(argv)
    if args.drift_agents_ts:
        with open(args.drift_agents_ts, "r", encoding="utf-8") as f:
            text = f.read()
        problems = []
        targets = load_json(args.kit, "install/targets.json", problems)
        problems += drift(text, targets)
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

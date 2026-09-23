"""ublib.engine: the ultimate-brainstorm autopilot engine (KIT_SPEC sections 4.1-4.3, 4.11-4.13, 6-9).

Modules:
    state        run.json load/save, 00_RUN.md, locks, events, run discovery, supersede
    seats        deterministic family seat assignment (6.6)
    privacy      vendor gating, code stripping, seed-leak / pool-leak / origin-label checks (6.7, 6.8)
    registry     named predicates, fanout sources, placeholders and scripts used by pipeline.json
    builders     job construction from templates (4.4)
    gates        HUMAN gates: policies, answer templates, validation, application, display text
    cards        card JSON (4.12) and text rendering
    progress     PROGRESS.md, ETA, `ub plan`, budgets (6.9)
    pipeline     pipeline.json interpreter and the driver loop (6.3)
    render       Markdown subset -> 11_PROPOSAL/index.html; zip; pandoc export (8.5)
    render_arch  drivers/candidates/decisions/stack JSON -> architecture documents (7.x)
    handoff      stage 14: publish, handoff seeds, 12_HANDOFF.md (9)
    migrate      v1 run folder -> run.json (6.10)
    terminal     `ub run` stdin gate prompts and the deterministic reply parser (6.3)

Only the Python standard library and the B2 foundation modules (ublib.textio, schema_lite, validate, filesproto,
proc, redact) are imported at module level. The B2 runtime modules (ublib.batch, ublib.detect, ublib.families) are
imported lazily through pipeline.Deps so that every engine module can be unit-tested with fakes.
"""

import os

from .. import KIT_VERSION, SCRIPTS_DIR, SK_DIR

ENGINE_VERSION = KIT_VERSION

TEMPLATES_DIR = os.path.join(SK_DIR, "templates")
PIPELINE_FILE = os.path.join(SCRIPTS_DIR, "pipeline.json")
ESTIMATES_FILE = os.path.join(SCRIPTS_DIR, "estimates.json")
UB_PY = os.path.join(SCRIPTS_DIR, "ub.py")
BS_PY = os.path.join(SCRIPTS_DIR, "bs.py")
FAMILY_PY = os.path.join(SCRIPTS_DIR, "family.py")

FAMILY_ORDER = ("claude", "gpt", "kimi", "glm")
VENDORS = {"claude": "anthropic", "gpt": "openai", "kimi": "moonshot", "glm": "zhipu"}
HOST_DEFAULT_FAMILY = {"claude-code": "claude", "codex": "gpt", "kimi": "kimi", "zcode": "glm"}
HOSTS = ("claude-code", "codex", "kimi", "zcode", "terminal", "other")

MODES = ("quick", "standard", "deep", "proposal")
VARIANTS = ("software", "product", "growth", "research", "marketing", "creative", "naming", "general")
AUTOPILOTS = ("hands-on", "guided", "full-auto")
APPROACH_VARIANTS = ("research", "marketing", "creative", "naming")
REPO_VARIANTS = ("software", "growth")

# 6.3: the wait W per host (seconds) and the host shell timeout that goes with it.
HOST_WAIT_S = {"claude-code": 540, "kimi": 270, "codex": 100, "zcode": 50, "other": 50, "terminal": 540}

# 6.1: default budget caps.
BUDGET_CAPS = {"quick": 60, "standard": 180, "deep": 600, "proposal": 90}

STAGE_NAMES = {
    0: "Kickoff", 1: "Seeds", 2: "Frame", 3: "Ground", 4: "Diverge", 5: "Map", 6: "Screen", 7: "Checks",
    8: "Evolve", 9: "Tournament", 10: "Decision", 11: "Probe", 12: "Architecture", 13: "Proposal", 14: "Handoff",
}
LAST_STAGE = 14

# 4.4 job kinds (estimates.json has one entry per kind).
JOB_KINDS = ("ping", "generator", "researcher", "curator", "judge", "checker", "normalizer", "reviewer", "synthesis",
             "writer", "arch-author", "arch-judge", "rubric", "redteam", "fixer", "frame")

# Fallback timeouts when families.default.json (B2) is not available (same values as 4.9).
DEFAULT_TIMEOUTS_S = {"ping": 60, "frame": 420, "generator": 420, "curator": 480, "judge": 300, "researcher": 600,
                      "checker": 480, "normalizer": 300, "reviewer": 420, "synthesis": 420, "writer": 720,
                      "arch-author": 600, "arch-judge": 420, "rubric": 300, "redteam": 420, "fixer": 600}


def vendor_of(label):
    """Vendor of a family label (claude, gpt-alt, host, ...). Unknown labels are their own vendor (5.7)."""
    if not label:
        return None
    base = base_family(label)
    return VENDORS.get(base, base)


def base_family(label):
    """'gpt-alt' -> 'gpt'; 'claude' -> 'claude'."""
    label = str(label or "")
    return label[:-4] if label.endswith("-alt") else label


def is_alt(label):
    return str(label or "").endswith("-alt")


class EngineError(Exception):
    """An error the engine reports as a BLOCKED card (with `fix` commands when known)."""

    def __init__(self, message, fix=None, say=None):
        Exception.__init__(self, message)
        self.fix = list(fix or [])
        self.say = say


class UsageError(Exception):
    """Bad command-line usage (exit code 2)."""

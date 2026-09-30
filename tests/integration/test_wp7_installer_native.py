"""Native plugin ownership (audit findings #68, #69). Owner: WP7.

#68 uninstall keeps UB_HOME/kit (the local marketplace the plugin loads from) while a plugin removal fails, never
    removes the marketplace while its plugin is still installed, and removes a plugin that comes from UB_HOME/kit even
    when the manifest lost its record.
#69 the native route trusts neither an "already exists" answer nor a name-only match: a marketplace named
    ultimate-brainstorm that points anywhere but UB_HOME/kit blocks the row (--force replaces it), and a plugin from
    such a source is never recorded as the kit's.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import inst  # noqa: E402

PLUGIN = "ultimate-brainstorm@ultimate-brainstorm"
FOREIGN = "MrHashMe/ultimate-brainstorm@v2.0.0"


def reg_path(th):
    return os.path.join(th.home, ".fakecli-registry.json")


def registry(th, tool="claude"):
    try:
        with open(reg_path(th), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    out = {"marketplaces": {}, "plugins": {}}
    for key, reg in data.items():
        if key.startswith(tool + "|"):
            out["marketplaces"].update(reg.get("marketplaces", {}))
            out["plugins"].update(reg.get("plugins", {}))
    return out


def seed_foreign(th, with_plugin=True):
    """The state route 2 of 10.2 leaves: the kit's marketplace name registered from GitHub at an old tag."""
    key = "claude|%s" % os.path.normcase(th.env["CLAUDE_CONFIG_DIR"])
    entry = {"marketplaces": {"ultimate-brainstorm": {"source": FOREIGN}}, "plugins": {}}
    if with_plugin:
        entry["plugins"][PLUGIN] = {"scope": "user"}
    with open(reg_path(th), "w", encoding="utf-8") as f:
        json.dump({key: entry}, f)


def kit_dir(th):
    return os.path.join(th.ub_home, "kit")


class UninstallKeepsTheMarketplace(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_failed_plugin_removal_keeps_the_kit(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            th.add_rules([{"tool": "claude", "argv_regex": r"^plugin uninstall", "action": "fail", "exit": 1,
                           "stderr": "boom: the plugin is busy"}])
            data, proc = inst.run_json(th, "uninstall", "--yes", exit=1)
            status = {r["item"]: r["status"] for r in data["results"]}
            self.assertEqual(status.get("plugin ultimate-brainstorm"), "failed", data["results"])
            self.assertEqual(status.get("staged kit"), "skipped", data["results"])
            self.assertTrue(os.path.isdir(kit_dir(th)), "the plugin still loads from UB_HOME/kit")
            reg = registry(th)
            self.assertIn(PLUGIN, reg["plugins"])
            self.assertIn("ultimate-brainstorm", reg["marketplaces"], "no marketplace removal under a live plugin")
            th.set_scenario([])
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertFalse(os.path.exists(kit_dir(th)))
            self.assertEqual(registry(th), {"marketplaces": {}, "plugins": {}})

    def test_kit_sourced_plugin_without_a_record_is_removed(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            self.assertEqual(inst.run(th, "install", "--yes", "--components", "none").returncode, 0)
            path = os.path.join(th.ub_home, "install-manifest.json")
            m = inst.read_manifest(th)
            m["entries"] = [e for e in m["entries"] if e.get("route") != "native"]  # an interrupted apply
            with open(path, "w", encoding="utf-8") as f:
                json.dump(m, f)
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertEqual(registry(th), {"marketplaces": {}, "plugins": {}},
                             "no plugin is left registered against a deleted UB_HOME/kit")
            self.assertFalse(os.path.exists(kit_dir(th)))


class ForeignMarketplace(unittest.TestCase):
    def setUp(self):
        inst.require_installer()

    def test_foreign_plugin_blocks_and_is_never_adopted(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            seed_foreign(th)
            plan = inst.run_plan(th, "--agents", "claude-code", "--components", "none")
            row = inst.rows(plan, agent="claude-code", how="native")
            self.assertEqual([r["action"] for r in row], ["blocked"], plan["rows"])
            self.assertTrue(any(FOREIGN in w for w in plan["warnings"]), plan["warnings"])
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            self.assertEqual(registry(th)["marketplaces"]["ultimate-brainstorm"]["source"], FOREIGN)
            # the next update must not adopt it either
            self.assertEqual(inst.run(th, "update", "--yes", "--agents", "claude-code", "--components",
                                      "none").returncode, 4)
            m = os.path.join(th.ub_home, "install-manifest.json")
            natives = [e for e in (inst.read_manifest(th)["entries"] if os.path.isfile(m) else [])
                       if e.get("route") == "native"]
            self.assertEqual(natives, [], "a plugin from another source is never recorded as the kit's")
            proc = inst.run(th, "uninstall", "--yes")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertIn(PLUGIN, registry(th)["plugins"], "uninstall keeps the user's own plugin")

    def test_force_replaces_the_foreign_marketplace(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            seed_foreign(th)
            proc = inst.run(th, "install", "--yes", "--force", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            reg = registry(th)
            self.assertTrue(paths.same_path(reg["marketplaces"]["ultimate-brainstorm"]["source"], kit_dir(th)), reg)
            self.assertIn(PLUGIN, reg["plugins"])
            natives = [e for e in inst.read_manifest(th)["entries"] if e.get("route") == "native"]
            self.assertEqual([e["agent"] for e in natives], ["claude-code"])

    def test_already_registered_answer_is_checked(self):
        with inst.installer_home(tools=("claude", "node")) as th:
            seed_foreign(th, with_plugin=False)
            th.add_rules([{"tool": "claude", "argv_regex": r"^plugin marketplace add", "action": "fail", "exit": 1,
                           "stderr": "Marketplace 'ultimate-brainstorm' is already installed. Remove it first."}])
            plan = inst.run_plan(th, "--agents", "claude-code", "--components", "none")
            self.assertEqual([r["action"] for r in inst.rows(plan, agent="claude-code", how="native")], ["blocked"])
            proc = inst.run(th, "install", "--yes", "--agents", "claude-code", "--components", "none")
            self.assertEqual(proc.returncode, 4, paths.describe(proc))
            self.assertEqual(registry(th)["plugins"], {}, "nothing is installed from the foreign source")

    def test_already_registered_answer_is_checked_at_apply_time(self):
        # the marketplace list is unreadable while planning, so only the apply-time check can catch it
        with inst.installer_home(tools=("claude", "node")) as th:
            seed_foreign(th, with_plugin=False)
            th.add_rules([{"tool": "claude", "argv_regex": r"^plugin marketplace list", "action": "fail", "exit": 1,
                           "max_hits": 1},
                          {"tool": "claude", "argv_regex": r"^plugin marketplace add", "action": "fail", "exit": 1,
                           "stderr": "Marketplace 'ultimate-brainstorm' is already installed. Remove it first."}])
            data, _proc = inst.run_json(th, "install", "--yes", "--agents", "claude-code", "--components", "none",
                                        exit=1)
            row = [r for r in data["results"] if r["item"] == "plugin ultimate-brainstorm"][0]
            self.assertEqual(row["status"], "failed", data["results"])
            self.assertIn(FOREIGN, row["detail"])
            self.assertEqual(registry(th)["plugins"], {}, "nothing is installed from the foreign source")
            self.assertTrue(os.path.isdir(os.path.join(th.ub_home, "kit")))


class SourceClassification(unittest.TestCase):
    """marketplace_source on list shapes the fakes do not produce [U-50]: only positive evidence is "foreign"."""

    def setUp(self):
        inst.require_installer()

    def classify(self, th, node):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ub_install_wp7_src", paths.INSTALL_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ctx = mod.Ctx(mod.build_parser().parse_args(["plan"]), environ=th.env)
        ctx.cache[("marketplaces", "claude-code", None)] = [node] if node is not None else None
        return mod.marketplace_source(ctx, "claude-code")[0]

    def test_shapes(self):
        with inst.installer_home(tools=("node",)) as th:
            kit = os.path.join(th.ub_home, "kit")
            other = th.write(os.path.join(th.root, "other kit", ".claude-plugin", "marketplace.json"), "{}\n")
            other = os.path.dirname(os.path.dirname(other))
            url = "file:///" + paths.posix(kit).lstrip("/")
            cases = [
                ({"name": "ultimate-brainstorm", "source": {"source": "directory", "path": kit}}, "kit"),
                ({"name": "ultimate-brainstorm", "source": url}, "kit"),
                ({"name": "ultimate-brainstorm", "source": {"source": "github", "repo": "MrHashMe/ultimate-brainstorm"},
                  "installLocation": os.path.join(th.home, ".claude", "plugins", "marketplaces", "x")}, "foreign"),
                ({"name": "ultimate-brainstorm", "source": "https://github.com/x/ultimate-brainstorm.git"}, "foreign"),
                ({"name": "ultimate-brainstorm", "path": other}, "foreign"),
                ({"name": "ultimate-brainstorm", "installLocation": other}, None),  # a location says nothing
                ({"name": "ultimate-brainstorm", "source": "directory"}, None),
                ({"name": "something-else", "source": "a/b"}, "absent"),
                (None, None),
            ]
            for node, want in cases:
                self.assertEqual(self.classify(th, node), want, node)


if __name__ == "__main__":
    unittest.main()

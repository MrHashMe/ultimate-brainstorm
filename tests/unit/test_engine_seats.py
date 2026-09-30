"""B3 engine: deterministic seat assignment (KIT_SPEC 6.6) for 1-4 families, every host family, privacy vendors=no
and web capabilities; minimal re-seating on a cross-host continue (6.10)."""

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import VENDORS, base_family  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402
from ublib.engine import seats  # noqa: E402

ALL = ("claude", "gpt", "kimi", "glm")


def assign(host, fams, mode="standard", web=None, variant="product", run="2026-09-23-x"):
    web = web if web is not None else tl.WEB
    F = seats.family_list(host, list(fams))
    return seats.assign(run, host, F, dict((f, web.get(f, False)) for f in F), mode, variant)


class FamilyListTests(unittest.TestCase):
    def test_host_first_then_order(self):
        self.assertEqual(seats.family_list("kimi", ["claude", "gpt", "kimi", "glm"]), ["kimi", "claude", "gpt", "glm"])
        self.assertEqual(seats.family_list("glm", ["gpt"]), ["gpt"])
        self.assertEqual(seats.family_list("claude", ["claude", "gpt"], ["anthropic"]), ["claude"])


class AssignTests(unittest.TestCase):
    def test_every_combination_is_valid(self):
        for mode in ("quick", "standard", "deep", "proposal"):
            for n in range(1, 5):
                for fams in itertools.combinations(ALL, n):
                    for host in ALL:
                        s = assign(host, fams if host in fams else (host,) + fams, mode)
                        self.check_invariants(s, host, mode)

    def check_invariants(self, s, host, mode):
        others = s["others"]
        alt = host + "-alt"
        self.assertEqual(s["families"][0], host)
        self.assertEqual(s["generators"]["S1"], host)
        self.assertEqual(s["generators"]["S2"], host)
        for k in ("S3", "S5"):
            f = s["generators"][k]
            self.assertTrue(f in others or f == alt, (k, f))
        if not others:
            self.assertTrue(s["single_family"])
            self.assertEqual(s["generators"]["S3"], alt)
        # red-team: advocate and critic always differ
        for i in range(6):
            adv, crit = seats.redteam_pair(s, i)
            self.assertNotEqual(adv, crit)
        # judges
        if mode == "quick":
            # the blind quick screen: the host and the other quick generator family, plus a third family that
            # generated nothing (a neutral judge); one family: no quick screen
            self.assertEqual(s["screen_judges"], [host] + others[:2] if others else [alt])
            self.assertEqual(seats.quick_screen_ok(s), bool(others))
            self.assertEqual(s["tournament_judges"], [others[0] if others else alt])
        elif mode == "deep":
            self.assertLessEqual(len(s["tournament_judges"]), 4)
        else:
            self.assertEqual(s["tournament_judges"][0], host)
            self.assertLessEqual(len(s["tournament_judges"]), 3)
        self.assertGreaterEqual(len(s["tournament_judges"]), 1)
        # architecture authors: K per mode
        self.assertEqual(len(s["arch_authors"]), seats.ARCH_K[mode])
        self.assertEqual(sorted(s["arch_archetypes"]), sorted("%d" % (i + 1) for i in range(seats.ARCH_K[mode])))
        # proposal
        self.assertEqual(s["proposal"]["drafter"], host)
        self.assertNotEqual(s["proposal"]["redteam"], host)
        self.assertTrue(s["proposal"]["rubric"])

    def test_standard_four_families_claude_host(self):
        s = assign("claude", ALL)
        # the non-host round-robin starts at rng(run, "generators") (here 2 of gpt, kimi, glm)
        self.assertEqual(s["rotation"], 2)
        self.assertEqual(s["generators"], {"S1": "claude", "S2": "claude", "S4": "claude", "S3": "glm", "S5": "gpt"})
        self.assertEqual(s["rr_next"], 4)
        self.assertEqual(seats.gap_families(s, 2), ["kimi", "glm"])  # GAP continues the round-robin
        self.assertEqual(s["screen_judges"], ["claude", "gpt", "kimi"])
        self.assertEqual(s["researcher"], ["claude"])
        self.assertEqual(s["arch_authors"], ["gpt", "kimi", "glm"])
        self.assertEqual(s["arch_judges"], ["claude", "gpt", "kimi", "glm"])  # one non-author: every family judges
        self.assertEqual(s["proposal"]["rubric"], ["gpt", "kimi"])

    def test_s4_goes_to_a_web_family(self):
        s = assign("kimi", ("kimi", "gpt"))
        self.assertEqual(s["generators"]["S4"], "gpt")
        self.assertEqual(s["researcher"], ["gpt"])
        s = assign("kimi", ("kimi", "glm"))  # no web family at all
        self.assertEqual(s["generators"]["S4"], "kimi")
        self.assertEqual(s["checker_pool"], ["kimi"])

    def test_deep_adds_second_researcher_and_lenses(self):
        s = assign("claude", ALL, "deep")
        self.assertEqual(len(s["researcher"]), 2)
        self.assertNotEqual(s["researcher"][0], s["researcher"][1])
        for i in range(1, 7):
            self.assertIn("L%d" % i, s["generators"])
        self.assertEqual(len(s["tournament_judges"]), 4)

    def test_single_family_uses_alt_everywhere(self):
        s = assign("gpt", ("gpt",))
        self.assertTrue(s["single_family"])
        self.assertEqual(s["screen_judges"], ["gpt", "gpt-alt"])
        self.assertEqual(s["rotation"], 0)
        self.assertEqual(s["proposal"]["redteam"], "gpt-alt")
        self.assertEqual(seats.redteam_pair(s, 0), ("gpt", "gpt-alt"))
        self.assertTrue(s["arch_same_family"])

    def test_deterministic(self):
        a = assign("claude", ALL, "deep", run="r1")
        b = assign("claude", ALL, "deep", run="r1")
        self.assertEqual(a, b)

    def test_checker_differs_from_origin_vendor(self):
        s = assign("claude", ALL)
        f, same = seats.checker_for(s, "anthropic")
        self.assertNotEqual(VENDORS[base_family(f)], "anthropic")
        self.assertFalse(same)
        f, same = seats.checker_for(assign("claude", ("claude",)), "anthropic")
        self.assertTrue(same)

    def test_review_lenses_avoid_the_writer(self):
        s = assign("claude", ALL, "deep")
        m = seats.review_lens_families(s, "gpt", ["L1", "L2", "L3", "L4"])
        for lens, fam in m.items():
            self.assertNotEqual(base_family(fam), "gpt")
        self.assertIn(m["L1"], s["web_families"])

    def test_premortem_differs_from_leader_author(self):
        s = assign("claude", ALL)
        self.assertNotEqual(seats.premortem_family(s, "gpt"), "gpt")
        self.assertEqual(seats.premortem_family(assign("gpt", ("gpt",)), "gpt"), "gpt-alt")


class PrivacyVendorTests(tl.EngineTestCase):
    def test_private_run_is_single_family(self):
        ctx = self.make_ctx(privacy={"vendors": False, "web": False})
        s = ctx.state["seats"]
        self.assertEqual(ctx.state["privacy"]["allowed_vendors"], ["anthropic"])
        self.assertEqual(s["families"], ["claude"])
        self.assertTrue(s["single_family"])
        self.assertEqual(s["generators"]["S3"], "claude-alt")
        self.assertEqual(s["researcher"], ["claude"])
        self.assertEqual(s["web_families"], [])

    def test_allowed_vendors(self):
        self.assertEqual(pv.allowed_vendors("gpt", ["claude", "gpt"], False), ["openai"])
        self.assertEqual(pv.allowed_vendors("gpt", ["claude", "gpt"], True), ["anthropic", "openai"])

    def test_web_off_removes_web_families(self):
        ctx = self.make_ctx(privacy={"web": False})
        self.assertEqual(ctx.state["seats"]["web_families"], [])


class ReseatTests(unittest.TestCase):
    def test_minimal_reseat_keeps_available_seats(self):
        old = assign("claude", ALL)
        fresh = assign("claude", ("claude", "gpt", "glm"))
        new, changes = seats.reseat_minimal(old, fresh, ["claude", "gpt", "glm"], "claude")
        for k, f in old["generators"].items():  # a seat keeps its family while that family is available
            if f == "kimi":
                self.assertNotEqual(new["generators"][k], "kimi")
            else:
                self.assertEqual(new["generators"][k], f)
        self.assertNotIn("kimi", new["screen_judges"])
        self.assertEqual(new["screen_judges"][:2], ["claude", "gpt"])
        self.assertTrue(changes)
        self.assertTrue(all(before == "kimi" for key, before, after in changes))
        self.assertEqual(new["arch_archetypes"], old["arch_archetypes"])

    def test_nothing_changes_when_all_remain(self):
        old = assign("claude", ALL)
        new, changes = seats.reseat_minimal(old, assign("claude", ALL), list(ALL), "claude")
        self.assertEqual(changes, [])
        self.assertEqual(new["generators"], old["generators"])


if __name__ == "__main__":
    unittest.main()

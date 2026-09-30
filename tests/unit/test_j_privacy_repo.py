"""Phase J, repository access (KIT_SPEC 6.8, 6.8a): a project that is a git worktree or a submodule (its .git is a
file 'gitdir: ...') is a git repository for repository access as it already was for the repo label, so the host
vendor's checker and researcher read it and the run folders are hidden from it (hunt: a project that is a git worktree
or submodule is never read)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import builders, pipeline, registry  # noqa: E402
from ublib.engine import privacy as pv  # noqa: E402

STEPS = dict((s["id"], s) for s in pipeline.load_steps())


def git_file(project, text="gitdir: ../main/.git/worktrees/feature\n"):
    with open(os.path.join(project, ".git"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


class GitRepoTests(tl.EngineTestCase):
    def test_a_folder_or_a_gitdir_file_is_a_repository(self):
        self.assertFalse(pv.is_git_repo(self.project))
        self.assertFalse(pv.is_git_repo(None))
        git_file(self.project)
        self.assertTrue(pv.is_git_repo(self.project))
        git_file(self.project, "\ufeffgitdir: C:/code/app/.git/modules/lib\n")  # a BOM from a Windows editor
        self.assertTrue(pv.is_git_repo(self.project))
        git_file(self.project, "not a git pointer\n")
        self.assertFalse(pv.is_git_repo(self.project))
        os.remove(os.path.join(self.project, ".git"))
        os.makedirs(os.path.join(self.project, ".git"))
        self.assertTrue(pv.is_git_repo(self.project))

    def test_a_worktree_project_is_read_by_the_host_vendor(self):
        git_file(self.project)
        ctx = self.make_ctx(variant="software", families=("claude", "gpt"))
        self.assertTrue(registry.is_repo(ctx))
        self.assertTrue(registry.repo_access(ctx, "claude"))
        self.assertFalse(registry.repo_access(ctx, "gpt"))
        self.assertTrue(pv.repo_labeled(ctx.state, ctx.run_dir))
        self.assertTrue(registry._p_repo_variant(ctx, None))  # step 2.0, the repository snapshot, runs
        ctx.write_json("origins.json", {"I-001": "human"})
        ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": "I-001", "reason": "x"}]})
        check = builders.build_jobs(ctx, STEPS["7.1"])[0]
        self.assertEqual((check["family"], check["cwd"]), ("claude", "repo"))
        self.assertIn("read", check["tools"])
        self.assertIn("You may read the repository", ctx.read(check["prompt_file"]))
        self.assertTrue(os.path.exists(os.path.join(ctx.run_dir, ".gitignore")))  # the run folders stay hidden
        ground = builders.build_jobs(ctx, STEPS["3.1"])[0]
        self.assertEqual((ground["family"], ground["cwd"]), ("claude", "repo"))

    def test_a_growth_run_in_a_submodule_is_a_repository_run(self):
        git_file(self.project, "gitdir: ../.git/modules/app\n")
        ctx = self.make_ctx(variant="growth", families=("claude", "gpt"))
        self.assertTrue(registry.repo_access(ctx, "claude"))
        self.assertTrue(pv.code_filtered(ctx.state, "gpt", ctx.run_dir))


if __name__ == "__main__":
    unittest.main()

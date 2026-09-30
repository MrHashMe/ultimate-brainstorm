"""B2 adapter tests: Kimi Code CLI v2 backend (KIT_SPEC 0.3 item 2, 5.2, 5.3, 5.6 rule 5) - argv, agent file,
${ escaping, env additions, tolerant stream-json parsing, sample capture. Process calls are mocked at proc.run."""

import os
import sys
import unittest
from unittest import mock

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "tests", "fixtures", "adapter"))

import adapter_testlib as tl  # noqa: E402
from ublib import adapter, textio  # noqa: E402
from ublib.backends import CallContext, kimi_cli  # noqa: E402

KIMI_P = "Carry out the task in your system instructions now. Output only the requested result."
STRING = tl.fixture_bytes("kimi", "string.jsonl")


class KimiBase(tl.AdapterTestCase):
    def run_job(self, job, responses, chain=("kimi-cli",)):
        fake = tl.FakeRun(responses)
        det = tl.chain_detect({"kimi": list(chain)}, host_family="claude")
        with mock.patch("ublib.proc.run", side_effect=fake), \
                mock.patch("ublib.proc.resolve_exe", side_effect=tl.fake_resolve()):
            meta = adapter.execute_job(job, detect_result=det)
        return meta, fake


def capture_agent(seen, stdout=STRING):
    def respond(call):
        argv = call["argv"]
        path = argv[argv.index("--agent-file") + 1]
        seen["agent"] = textio.read_text(path)
        seen["skills"] = argv[argv.index("--skills-dir") + 1]
        seen["skills_listing"] = sorted(os.listdir(seen["skills"]))
        return tl.PR(0, stdout)
    return respond


class ArgvAgentFileTests(KimiBase):
    def test_argv_and_agent_file(self):
        seen = {}
        prompt = "Do not load or invoke any skill; this prompt is the whole task.\nKeep ${HOME} and ${x} literal.\n"
        job = self.make_job(family="kimi", prompt=prompt)
        meta, fake = self.run_job(job, [capture_agent(seen)])
        self.assertEqual(meta["status"], "ok")
        call = fake.calls[0]
        argv = call["argv"]
        agent = argv[argv.index("--agent-file") + 1]
        self.assertEqual(argv[1:], ["--agent-file", agent, "--skills-dir", seen["skills"], "--output-format",
                                    "stream-json", "-p", KIMI_P])
        self.assertIsNone(call["stdin"])
        for bad in ("--yolo", "--auto", "--plan"):
            self.assertNotIn(bad, argv)
        self.assertFalse(any("literal" in a for a in argv))
        self.assertEqual(seen["skills_listing"], [])
        self.assertEqual(call["cwd_listing"], [])
        lines = seen["agent"].split("\n")
        self.assertEqual(lines[:6], ["---", "name: ub-oneshot",
                                     "description: Isolated one-shot worker for ultimate-brainstorm. The final "
                                     "message is the complete result.",
                                     "tools: []", "subagents: []", "---"])
        self.assertIn("Keep $ {HOME} and $ {x} literal.", seen["agent"])
        self.assertNotIn("${", seen["agent"])
        self.assertFalse(os.path.exists(agent))  # temp files removed after the call

    def test_tools_profiles_in_frontmatter_and_steps(self):
        seen = {}
        job = self.make_job(family="kimi", tools="web")
        _m, fake = self.run_job(job, [capture_agent(seen)])
        self.assertIn("tools: [WebSearch, FetchURL]", seen["agent"])
        self.assertEqual(fake.calls[0]["env"]["KIMI_LOOP_MAX_STEPS_PER_TURN"], "40")
        self.assertEqual(kimi_cli.tools_list("read"), ["Read", "Grep", "Glob"])
        self.assertEqual(kimi_cli.tools_list("none"), [])

    def test_model_flag_when_configured(self):
        self.write_families_override({"backends": {"kimi-cli": {"model": "kimi-test", "fast_model": "kimi-fast"}}})
        job = self.make_job(family="kimi", tier="fast")
        _m, fake = self.run_job(job, [tl.PR(0, STRING)])
        argv = fake.calls[0]["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], "kimi-fast")
        self.assertEqual(argv[-2:], ["-p", KIMI_P])


class EnvTests(KimiBase):
    def test_env_additions_and_denylist(self):
        os.environ.update({"KIMI_MODEL_NAME": "k", "KIMI_MODEL_BASE_URL": "https://example.test",
                           "KIMI_API_KEY": "moonshot-key-0123456789", "KIMI_SHELL_PATH": "C:/bash.exe",
                           "KIMI_CODE_HOME": os.path.join(self.tmp, "kh")})
        job = self.make_job(family="kimi")
        _m, fake = self.run_job(job, [tl.PR(0, STRING)])
        env = fake.calls[0]["env"]
        self.assertEqual(env["KIMI_CODE_NO_AUTO_UPDATE"], "1")
        self.assertEqual(env["KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE"], "exit")
        self.assertEqual(env["KIMI_LOOP_MAX_STEPS_PER_TURN"], "4")
        for n in ("KIMI_MODEL_NAME", "KIMI_MODEL_BASE_URL", "KIMI_API_KEY"):
            self.assertNotIn(n, env)
        self.assertEqual(env["KIMI_SHELL_PATH"], "C:/bash.exe")
        self.assertIn("KIMI_CODE_HOME", env)

    def test_env_model_adds_back_kimi_model_vars(self):
        self.write_families_override({"backends": {"kimi-cli": {"env_model": True}}})
        os.environ.update({"KIMI_MODEL_NAME": "k", "KIMI_MODEL_BASE_URL": "https://api.moonshot.ai/v1"})
        job = self.make_job(family="kimi")
        _m, fake = self.run_job(job, [tl.PR(0, STRING)])
        self.assertEqual(fake.calls[0]["env"]["KIMI_MODEL_NAME"], "k")

    def test_policy_refuses_glm_plan_through_kimi_env_model(self):
        self.write_families_override({"backends": {"kimi-cli": {"env_model": True}}})
        os.environ.update({"KIMI_MODEL_NAME": "glm-5.3", "KIMI_MODEL_BASE_URL": "https://api.z.ai/api/coding/paas/v4"})
        job = self.make_job(family="kimi")
        meta, fake = self.run_job(job, [tl.PR(0, STRING)])
        self.assertEqual(meta["status"], "refused")
        self.assertEqual(meta["error_class"], "policy")
        self.assertEqual(adapter.exit_code_for(meta["status"]), 7)
        self.assertEqual(fake.calls, [])


class StreamParseTests(KimiBase):
    def parse(self, name):
        return kimi_cli.parse_stream(tl.fixture_text("kimi", name))

    def test_variants(self):
        self.assertEqual(self.parse("string.jsonl"), "Plain string answer.")
        self.assertEqual(self.parse("parts.jsonl"), "Answer in two parts.")
        self.assertEqual(self.parse("tool_noise.jsonl"), "Final answer after tools.")
        self.assertEqual(self.parse("message_nested.jsonl"), "Nested message content.")
        self.assertIsNone(self.parse("no_final.jsonl"))

    def test_last_assistant_wins(self):
        text = '{"role":"assistant","content":"first"}\n{"role":"assistant","content":"second"}\n'
        self.assertEqual(kimi_cli.parse_stream(text), "second")

    def test_no_final_is_bad_output_and_retried(self):
        job = self.make_job(family="kimi")
        meta, fake = self.run_job(job, [tl.PR(0, tl.fixture_bytes("kimi", "no_final.jsonl"))])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(meta["error_class"], "bad_output")
        self.assertEqual(meta["status"], "failed")

    def test_login_failure_is_auth(self):
        ctx = CallContext(bcfg={}, btype="kimi-cli", timeout_s=5)
        r = kimi_cli.parse(tl.PR(1, b"", b"Error: not logged in. Run kimi login"), ctx, "cmd")
        self.assertEqual(r["error_class"], "auth")

    def test_samples_saved_for_first_three_calls(self):
        for i in range(5):
            job = self.make_job(family="kimi", job_id="k%d" % i)
            self.run_job(job, [tl.PR(0, tl.fixture_bytes("kimi", "tool_noise.jsonl"))])
        d = os.path.join(self.run_dir, "logs", "kimi-samples")  # inside the run folder, never in UB_HOME
        self.assertEqual(sorted(os.listdir(d)), ["sample-1.jsonl", "sample-2.jsonl", "sample-3.jsonl"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "tmp", "kimi-samples")))


if __name__ == "__main__":
    unittest.main()

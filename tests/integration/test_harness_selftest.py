"""B4 harness self-tests (KIT_SPEC 12.4 acceptance): fakecli native formats parse back, .cmd shims pass %* intact,
tmphome isolates HOME and USERPROFILE, fsnap, http_stub and the answerer's card loop. Owner: B4."""

import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402
import answerer  # noqa: E402
import fsnap  # noqa: E402
import shims  # noqa: E402
from http_stub import HttpStub  # noqa: E402
from tmphome import TmpHome  # noqa: E402

from ublib import textio, validate  # noqa: E402

JSON_CONTRACT = {"type": "json", "schema": {"type": "object", "additionalProperties": False, "required": ["answer"],
                                            "properties": {"answer": {"type": "string"}}}}
TEXT_CONTRACT = {"type": "text", "regex": "PONG"}


def shim(th, tool):
    return os.path.join(th.bin, tool + (".cmd" if os.name == "nt" else ""))


def call(th, tool, args, stdin=b"", env_extra=None, timeout=60):
    env = dict(th.env)
    env.update(env_extra or {})
    return subprocess.run([shim(th, tool)] + list(args), input=stdin, env=env, cwd=th.project,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def write_job(th, contract, jid="t-1", template="X", kind="writer"):
    job = {"schema": 1, "id": jid, "kind": kind, "template": template, "contract": contract, "run": th.project}
    path = os.path.join(th.root, "job-%s.json" % jid)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f)
    return path, {"UB_JOB_FILE": path, "UB_JOB_ID": jid}


class FakeCliFormats(unittest.TestCase):
    def test_claude_json_result(self):
        with TmpHome(tools=("claude",)) as th:
            _p, env = write_job(th, TEXT_CONTRACT)
            r = call(th, "claude", ["-p", "Follow the instructions", "--output-format", "json"], b"prompt body", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            obj = json.loads(r.stdout.decode("utf-8"))
            self.assertEqual((obj["type"], obj["subtype"], obj["is_error"]), ("result", "success", False))
            ok, errors, _ = validate.check_contract(obj["result"], TEXT_CONTRACT, None)
            self.assertTrue(ok, errors)
            entry = th.fake_calls("claude")[-1]
            self.assertEqual(entry["stdin_sha256"], textio.sha256_text("prompt body"))
            self.assertEqual(entry["job_id"], "t-1")
            self.assertIn("UB_JOB_FILE", entry["env_names"])

    def test_codex_o_file_and_jsonl(self):
        with TmpHome(tools=("codex",)) as th:
            _p, env = write_job(th, JSON_CONTRACT)
            out = os.path.join(th.tmp, "last dir", "last.txt")
            os.makedirs(os.path.dirname(out))
            r = call(th, "codex", ["exec", "--skip-git-repo-check", "-o", out, "--json", "-"], b"p", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            events = [json.loads(l) for l in r.stdout.decode("utf-8").splitlines() if l.strip()]
            self.assertEqual([e["type"] for e in events], ["thread.started", "item.completed", "turn.completed"])
            self.assertEqual(events[-1]["usage"]["output_tokens"], 20)
            ok, errors, _ = validate.check_contract(textio.read_text(out), JSON_CONTRACT, None)
            self.assertTrue(ok, errors)
            self.assertTrue(paths.same_path(th.fake_calls("codex")[-1]["o_file"], out))

    def test_kimi_stream_json(self):
        with TmpHome(tools=("kimi",)) as th:
            _p, env = write_job(th, JSON_CONTRACT)
            agent = th.write(os.path.join(th.tmp, "agent.md"),
                             "---\nname: ub-oneshot\ntools: []\nsubagents: []\n---\nDo it. $ {x}\n")
            r = call(th, "kimi", ["--agent-file", agent, "--output-format", "stream-json", "-p", "Go"], b"", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            msgs = [json.loads(l) for l in r.stdout.decode("utf-8").splitlines() if l.strip()]
            self.assertEqual(msgs[-1]["role"], "assistant")
            ok, errors, _ = validate.check_contract(msgs[-1]["content"], JSON_CONTRACT, None)
            self.assertTrue(ok, errors)
            snap = th.fake_calls("kimi")[-1]["agent_file"]
            self.assertIn("tools: []", snap["frontmatter"])
            self.assertTrue(snap["body_has_escaped"])
            self.assertFalse(snap["body_has_dollar_brace"])
            # tool-call noise variant
            th.set_scenario([{"tool": "kimi", "argv_regex": "-p", "action": "stub", "kimi_variant": "tools"}])
            r = call(th, "kimi", ["--agent-file", agent, "--output-format", "stream-json", "-p", "Go"], b"", env)
            msgs = [json.loads(l) for l in r.stdout.decode("utf-8").splitlines() if l.strip()]
            self.assertEqual([m["role"] for m in msgs], ["assistant", "tool", "assistant"])
            self.assertTrue(msgs[0]["tool_calls"])
            text = msgs[-1]["content"][0]["text"]
            self.assertTrue(validate.check_contract(text, JSON_CONTRACT, None)[0])

    def test_corruption_actions(self):
        with TmpHome(tools=("claude",)) as th:
            _p, env = write_job(th, JSON_CONTRACT)
            args = ["-p", "x", "--output-format", "json"]
            th.set_scenario([{"tool": "claude", "action": "utf16"}])
            raw = call(th, "claude", args, b"", env).stdout
            self.assertTrue(raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"))
            self.assertEqual(json.loads(textio.decode_bytes(raw))["type"], "result")
            th.set_scenario([{"tool": "claude", "action": "bom"}])
            raw = call(th, "claude", args, b"", env).stdout
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            th.set_scenario([{"tool": "claude", "action": "fence"}])
            res = json.loads(call(th, "claude", args, b"", env).stdout)["result"]
            self.assertIn("```json", res)
            self.assertTrue(validate.check_contract(res, JSON_CONTRACT, None)[0])
            th.set_scenario([{"tool": "claude", "action": "garbage"}])
            res = json.loads(call(th, "claude", args, b"", env).stdout)["result"]
            self.assertFalse(validate.check_contract(res, JSON_CONTRACT, None)[0])
            th.set_scenario([{"tool": "claude", "action": "empty"}])
            self.assertEqual(json.loads(call(th, "claude", args, b"", env).stdout)["result"], "")
            th.set_scenario([{"tool": "claude", "action": "is_error"}])
            obj = json.loads(call(th, "claude", args, b"", env).stdout)
            self.assertTrue(obj["is_error"])
            self.assertEqual(obj["subtype"], "error_during_execution")
            th.set_scenario([{"tool": "claude", "action": "fail", "exit": 3, "stderr": "not logged in"}])
            r = call(th, "claude", args, b"", env)
            self.assertEqual(r.returncode, 3)
            self.assertIn(b"not logged in", r.stderr)

    def test_rules_max_hits_static_record(self):
        with TmpHome(tools=("claude", "npx")) as th:
            th.set_scenario([
                {"tool": "claude", "argv_regex": "--version", "action": "fail", "exit": 1, "max_hits": 1},
                {"tool": "npx", "argv_regex": r"skills@1\.7\.0 add", "action": "record",
                 "create_dirs": ["~/.claude/skills/grilling"]}])
            self.assertEqual(call(th, "claude", ["--version"]).returncode, 1)
            r = call(th, "claude", ["--version"])
            self.assertEqual(r.returncode, 0)
            self.assertIn(b"2.1.280", r.stdout)
            r = call(th, "npx", ["-y", "skills@1.7.0", "add", "mattpocock/skills"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isdir(os.path.join(th.home, ".claude", "skills", "grilling")))
            self.assertEqual(th.fake_calls("npx")[-1]["argv"][:3], ["-y", "skills@1.7.0", "add"])

    def test_sleep_spawns_child(self):
        with TmpHome(tools=("codex",)) as th:
            th.set_scenario([{"tool": "codex", "action": "sleep", "sleep_s": 1, "spawn_child": True}])
            _p, env = write_job(th, TEXT_CONTRACT)
            out = os.path.join(th.tmp, "o.txt")
            r = call(th, "codex", ["exec", "-o", out, "-"], b"", env)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(th.log + ".children") as f:
                rec = json.loads(f.readline())
            self.assertIn("child", rec)
            self.assertTrue(os.path.isfile(out))

    def test_plugin_registry_simulation(self):
        with TmpHome(tools=("claude", "codex")) as th:
            kit = paths.KIT
            self.assertEqual(call(th, "claude", ["plugin", "marketplace", "add", kit]).returncode, 0)
            self.assertEqual(call(th, "claude", ["plugin", "install", "ultimate-brainstorm@ultimate-brainstorm",
                                                 "--scope", "user"]).returncode, 0)
            lst = json.loads(call(th, "claude", ["plugin", "list", "--json"]).stdout)
            self.assertEqual(lst[0]["id"], "ultimate-brainstorm@ultimate-brainstorm")
            self.assertEqual(call(th, "codex", ["plugin", "add", "a@b", "--json"]).returncode, 0)
            lst = json.loads(call(th, "codex", ["plugin", "list", "--json"]).stdout)
            self.assertEqual(lst["plugins"][0]["id"], "a@b")
            self.assertEqual(call(th, "codex", ["plugin", "remove", "a@b", "--json"]).returncode, 0)
            self.assertEqual(json.loads(call(th, "codex", ["plugin", "list", "--json"]).stdout)["plugins"], [])

    def test_settings_snapshot_hashes_secrets(self):
        with TmpHome(tools=("claude",)) as th:
            token = "sk-test-SECRET-token-123456"
            settings = th.write(os.path.join(th.tmp, "s.json"), json.dumps(
                {"env": {"ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic", "ANTHROPIC_AUTH_TOKEN": token}}))
            call(th, "claude", ["--settings", settings, "--version"])
            snap = th.fake_calls("claude")[-1]["settings"]
            self.assertTrue(snap["exists"])
            self.assertEqual(snap["env"]["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
            self.assertTrue(snap["env"]["ANTHROPIC_AUTH_TOKEN"].startswith("sha256:"))
            self.assertNotIn(token, th.log_text())


class ShimArgv(unittest.TestCase):
    CASES = [["--model", "glm-5.3[1m]"], ["-C", "C:/a dir/with spaces", "-o", "x y/last.txt"],
             ["-c", "web_search=live", "a,b;c", "=x="], ["--tools", "", "--max-turns", "3"],
             ["mcp__*", "Read,Grep,Glob", "tab\tx"]]

    def test_percent_star_passes_args_intact(self):
        with TmpHome(tools=("codex",)) as th:
            for args in self.CASES:
                with self.subTest(args=args):
                    th.clear_log()
                    r = call(th, "codex", ["plugin", "noop"] + args)
                    self.assertIn(r.returncode, (0, 2), r.stderr)
                    self.assertEqual(th.fake_calls("codex")[-1]["argv"], ["plugin", "noop"] + args)

    @unittest.skipIf(os.name == "nt", "POSIX sh shims only")
    def test_posix_shim_needs_nothing_from_path(self):
        # CI runners keep Python outside /usr/bin, so the tests' PATH has no coreutils; a shim that calls `dirname`
        # (or anything else) passes locally with a system Python and fails there. An empty PATH catches it anywhere.
        with TmpHome(tools=("codex",)) as th:
            r = call(th, "codex", ["plugin", "noop", "x y"], env_extra={"PATH": os.path.join(th.root, "empty")})
            self.assertIn(r.returncode, (0, 2), r.stderr)
            self.assertNotIn(b"not found", r.stderr)
            self.assertEqual(th.fake_calls("codex")[-1]["argv"], ["plugin", "noop", "x y"])

    def test_cmd_shim_text(self):
        self.assertEqual(shims.cmd_text("claude"), '@"%UB_FAKE_PY%" "%~dp0fakecli.py" claude %*\r\n')
        with TmpHome(tools=("claude",)) as th:
            made = shims.install_fakes(os.path.join(th.root, "wbin"), ("claude",), windows=True)
            with open(made["claude"], "rb") as f:
                self.assertTrue(f.read().endswith(b"%*\r\n"))


class TmpHomeIsolation(unittest.TestCase):
    def test_home_and_userprofile(self):
        saved = os.environ.get("ANTHROPIC_BASE_URL")
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.z.ai/api/anthropic"
        try:
            with TmpHome(tools=()) as th:
                code = ("import os, json; print(json.dumps({'home': os.path.expanduser('~'), "
                        "'env': sorted(os.environ)}))")
                r = paths.run([sys.executable, "-c", code], env=th.env, cwd=th.project)
                data = json.loads(r.out)
                self.assertTrue(paths.same_path(data["home"], th.home))
                self.assertTrue(paths.same_path(th.env["USERPROFILE"], th.home))
                self.assertTrue(paths.same_path(th.env["HOME"], th.home))
                self.assertNotIn("ANTHROPIC_BASE_URL", data["env"])
                self.assertTrue(th.env["UB_HOME"].startswith(th.home))
                self.assertEqual(th.env["UB_FAKE_PY"], sys.executable)
                self.assertTrue(th.env["PATH"].split(os.pathsep)[0] == th.bin)
                self.assertIn(" ", th.root)
                root = th._base
            self.assertFalse(os.path.exists(root))
        finally:
            if saved is None:
                os.environ.pop("ANTHROPIC_BASE_URL", None)
            else:
                os.environ["ANTHROPIC_BASE_URL"] = saved

    def test_patched_environ_restores(self):
        before = dict(os.environ)
        with TmpHome(tools=()) as th:
            with th.patched_environ():
                self.assertEqual(os.environ["HOME"], th.home)
        self.assertEqual(dict(os.environ), before)


class FsnapTests(unittest.TestCase):
    def test_diff(self):
        with TmpHome(tools=()) as th:
            a = th.write(os.path.join(th.project, "a.txt"), "a")
            th.write(os.path.join(th.project, "sub", "b.txt"), "b")
            before = fsnap.snapshot(th.project)
            time.sleep(0.05)
            th.write(a, "a2")
            th.write(os.path.join(th.project, "c.txt"), "c")
            os.remove(os.path.join(th.project, "sub", "b.txt"))
            d = fsnap.diff(before, fsnap.snapshot(th.project))
            self.assertEqual(d["changed"], ["a.txt"])
            self.assertEqual(d["added"], ["c.txt"])
            self.assertEqual(d["removed"], ["sub/b.txt"])
            fsnap.assert_unchanged(self, before, before)


class HttpStubTests(unittest.TestCase):
    def test_retry_after_then_ok(self):
        script = [{"status": 429, "headers": {"Retry-After": "1"}}, {"text": "hello"}]
        with HttpStub(script) as hs:
            body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "x"}]}).encode()
            req = urllib.request.Request(hs.url(), data=body, headers={"Authorization": "Bearer k",
                                                                      "Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(cm.exception.code, 429)
            self.assertEqual(cm.exception.headers.get("Retry-After"), "1")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            self.assertEqual(data["choices"][0]["message"]["content"], "hello")
            req2 = urllib.request.Request(hs.url("/v1/messages"), data=body, headers={"x-api-key": "k"})
            with urllib.request.urlopen(req2, timeout=10) as resp:
                self.assertEqual(json.loads(resp.read())["content"][0]["text"], "PONG")
            self.assertEqual(len(hs.requests), 3)
            self.assertTrue(all(r["has_auth"] for r in hs.requests))
            self.assertNotIn("Bearer k", json.dumps(hs.requests))


FAKE_UB = r'''
import json, os, sys
args = sys.argv[1:]
def card(run, **kw):
    c = {"ub": "2.0.0", "run": run, "runner": 'py -3 "%s"' % __file__.replace("\\", "/")}
    c.update(kw)
    with open(os.path.join(run, "state.json"), "w") as f:
        json.dump(c, f)
    print(json.dumps(c))
def runner():
    return 'py -3 "%s"' % __file__.replace("\\", "/")
if args[0] == "init":
    run = os.path.join(os.getcwd(), "run").replace("\\", "/")
    os.makedirs(os.path.join(run, "answers"), exist_ok=True)
    os.makedirs(os.path.join(run, "jobs"), exist_ok=True)
    af = run + "/answers/G0.json"
    card(run, type="HUMAN", step="0.2", gate="G0", show="Kickoff", answer_file=af,
         answer_template={"reply": None, "confirm": None}, default_answer={"confirm": True},
         answer_cmd='%s answer "%s" G0 --file "%s" --json' % (runner(), run, af))
elif args[0] == "answer":
    run, gate, f = args[1], args[2], args[4]
    ans = json.load(open(f))
    if gate == "G0":
        assert ans["confirm"] is True
        card(run, type="AUTO", step="4.2", then='%s next "%s" --wait-s 540 --json' % (runner(), run))
    else:
        assert ans["chosen"] == "I-007", ans
        card(run, type="DONE", step="14.4", show="done", links={})
elif args[0] == "next":
    run = args[1]
    assert args[args.index("--wait-s") + 1] == "20", args
    st = json.load(open(os.path.join(run, "state.json")))
    if st["step"] == "4.2":
        os.makedirs(os.path.join(run, "frame"), exist_ok=True)
        card(run, type="HOST", step="2.1g", task={"template": "/x/FRAME-GRILL.md", "skill": "grilling",
             "argument_file": run + "/a.md", "writes": [run + "/01_FRAME.md", run + "/criteria.json"],
             "done_cmd": '%s done "%s" 2.1g --json' % (runner(), run)})
    elif st["step"] == "2.1g":
        job = {"id": "4.2-S2", "run": run, "template": "S2-VS", "kind": "generator",
               "contract": {"type": "idea-blocks", "prefix": "S2", "min": 3}}
        json.dump(job, open(os.path.join(run, "jobs", "4.2-S2.json"), "w"))
        open(os.path.join(run, "p.md"), "w").write("prompt")
        card(run, type="HOST_BATCH", step="4.2b", jobs=[{"id": "4.2-S2", "prompt_file": run + "/p.md",
             "out": run + "/pool/S2.md", "tools": "none"}], then='%s next "%s" --wait-s 540 --json' % (runner(), run))
    else:
        assert open(os.path.join(run, "pool", "S2.md")).read().count("### S2-") == 3
        af = run + "/answers/G8b.json"
        card(run, type="HUMAN", step="10.5", gate="G8b", show="Finalists I-003 I-007\nSuggested by rule: I-003",
             answer_file=af, answer_template={"reply": None, "chosen": None, "why": None},
             default_answer={"reply": "", "accept_recommendation": True},
             answer_cmd='%s answer "%s" G8b --file "%s" --json' % (runner(), run, af))
elif args[0] == "done":
    run = args[1]
    assert os.path.isfile(os.path.join(run, "01_FRAME.md"))
    assert json.load(open(os.path.join(run, "criteria.json")))["Feasibility"] == 25
    card(run, type="AUTO", step="2.1g", then='%s next "%s" --wait-s 540 --json' % (runner(), run))
'''


class AnswererTests(unittest.TestCase):
    def test_tokenize_and_args(self):
        cmd = 'py -3 "C:/Users/U/My Kit/ub.py" answer "C:/p q/run" G8b --file "C:/p q/run/answers/G8b.json" --json'
        self.assertEqual(answerer.ub_args(cmd), ["answer", "C:/p q/run", "G8b", "--file",
                                                 "C:/p q/run/answers/G8b.json", "--json"])
        self.assertEqual(answerer.ub_args('"C:/x/bin/ub.cmd" next "r" --json'), ["next", "r", "--json"])
        self.assertEqual(answerer.tokenize('a "" b'), ["a", "", "b"])

    def test_pick_non_leader(self):
        card = {"show": "Finalists: I-003, I-007, I-012\nSuggested by rule; you decide: I-007"}
        self.assertEqual(answerer.pick_non_leader(card), "I-003")

    def test_drive_fake_engine(self):
        with TmpHome(tools=()) as th:
            ub = th.write(os.path.join(th.root, "fake_ub.py"), textwrap.dedent(FAKE_UB))
            a = answerer.Answerer(env=th.env, cwd=th.project, ub_py=ub, wait_s=20,
                                  choices={"G8b": lambda c: {"chosen": answerer.pick_non_leader(c),
                                                             "why": "cheaper pilot", "accept_recommendation": False}})
            final = a.drive(a.ub("init", "--host", "claude-code", "--text", "x", "--json"))
            self.assertEqual(final["type"], "DONE", a.trace)
            self.assertEqual([t["type"] for t in a.trace], ["HUMAN", "AUTO", "HOST", "AUTO", "HOST_BATCH", "HUMAN",
                                                            "DONE"])
            self.assertEqual(a.answers["G8b"]["chosen"], "I-007")
            self.assertEqual(a.answers["G0"]["reply"], "")


if __name__ == "__main__":
    unittest.main()

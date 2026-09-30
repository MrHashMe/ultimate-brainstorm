"""E2: redaction knows more credential shapes and runs in linear time (finding 31, reviewer note P3-backends-1).

The shapes the Phase D verifier still saw pass verbatim into meta, .failed.md and calls.jsonl are masked now:
prefixed names (DATABASE_PASSWORD=, AWS_SECRET_ACCESS_KEY=, X-Amz-Signature=, OPENAI_API_KEY = "..."), fine-grained
GitHub, GitLab and AWS key ids, URL userinfo with an empty user or a token alone, YAML/header lines. The PEM and URL
userinfo shapes used to be quadratic on adversarial text (4000 BEGIN lines: 10 s; 256 KB of 'a.': 23 s) and redact()
sees whole kimi samples and fetched error bodies; every shape is now linear."""

import os
import sys
import time
import unittest

_KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_KIT, "skills", "ultimate-brainstorm", "scripts"))

from ublib import redact  # noqa: E402

M = redact.MASK


class ShapeTests(unittest.TestCase):
    def test_prefixed_names_and_query_params(self):
        cases = {
            "DATABASE_PASSWORD=hunter2hunter2 AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY":
                "DATABASE_PASSWORD=%s AWS_SECRET_ACCESS_KEY=%s" % (M, M),
            'OPENAI_API_KEY = "abcdefghijklmnopqrstu1234"': 'OPENAI_API_KEY = "%s"' % M,
            "o?X-Amz-Security-Token=FQoGZXIvYXdzEBYaDK123456&X-Amz-Signature=abcdef0123456789abcdef&X-Amz-Date=1":
                "o?X-Amz-Security-Token=%s&X-Amz-Signature=%s&X-Amz-Date=1" % (M, M),
            '{"db_password": "hunter2hunter2", "n": 1}': '{"db_password": "%s", "n": 1}' % M,
            "token: abcdefghijklmnop1234": "token: %s" % M,
            "  - api_key: 'abcdefgh12345678'": "  - api_key: '%s'" % M,
        }
        for text, want in cases.items():
            self.assertEqual(redact.redact(text), want)

    def test_token_formats(self):
        for token in ("github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz", "glpat-abcdefghijklmnopqrstu",
                      "AKIAIOSFODNN7EXAMPLE", "xoxb-123456789012-abcdefghij", "hf_abcdefghijklmnopqrstuvwxyzABCDEF",
                      "AIza" + "B" * 35):
            self.assertEqual(redact.redact("seen %s here" % token), "seen %s here" % M, token)
        self.assertEqual(redact.redact("PRIVATE-TOKEN: glpat-abcdefghijklmnopqrstu"), "PRIVATE-TOKEN: %s" % M)

    def test_url_userinfo(self):
        self.assertEqual(redact.redact("https://:tok_abcdefghijklmnop@git.example.com/r.git"),
                         "https://:%s@git.example.com/r.git" % M)
        self.assertEqual(redact.redact("https://tok_abcdefghijklmnop@git.example.com/r.git"),
                         "https://%s@git.example.com/r.git" % M)
        self.assertEqual(redact.redact("proxy http://alice:s3cr3t-pass@proxy:3128 x"),
                         "proxy http://alice:%s@proxy:3128 x" % M)

    def test_ordinary_text_is_kept(self):
        for text in ('{"max_tokens": 16000, "input_tokens": 123456789, "output_tokens": 320}',
                     "max_tokens=1000000000 max_output_tokens=128000000", "The token: is shown below",
                     "Error: invalid_api_key: Incorrect API key provided", "The key: understanding the handover",
                     "https://registry.npmjs.org/@scope/pkg", "ssh://git@github.com/org/repo.git",
                     "git@github.com:org/repo.git", "https://example.com:8080/path@anchor",
                     "codex exec -c notify=[] -c mcp_servers.node_repl.enabled=false -c features.shell_tool=false",
                     "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"):
            self.assertEqual(redact.redact(text), text)

    def test_pem_blocks(self):
        pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----\nafter"
        self.assertEqual(redact.redact(pem), "-----BEGIN PRIVATE KEY-----%s-----END PRIVATE KEY-----\nafter" % M)
        # an unterminated block (a cut transcript) is masked to the end, past a certificate's END line
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA\n-----END CERTIFICATE-----\nMIIEpB"
        self.assertEqual(redact.redact(text), "-----BEGIN RSA PRIVATE KEY-----%s" % M)


class LinearTimeTests(unittest.TestCase):
    """Each input took seconds to minutes with a quadratic shape; linear shapes take milliseconds. The bound is loose
    (a slow CI machine) and still far below what the quadratic shapes needed."""

    def timed(self, text):
        t0 = time.perf_counter()
        redact.redact(text)
        return time.perf_counter() - t0

    def test_adversarial_inputs(self):
        inputs = {
            "pem": "-----BEGIN RSA PRIVATE KEY-----\n" * 4000 + "-----END CERTIFICATE-----\n",  # 9.95 s before
            "scheme run": "a." * 128000,  # 23.5 s before
            "scheme run with dashes": "a-" * 128000,
            "jwt-like run": "eyJaaaaaaaaaa-" * 20000,
            "prefixed name run": "a_" * 128000,
            "quoted name run": '"' + "a_" * 128000,
            "url without userinfo": "http://" + "a" * 256000,
            "schemes": "a://" * 64000,
        }
        for name, text in inputs.items():
            self.assertLess(self.timed(text), 2.0, name)


if __name__ == "__main__":
    unittest.main()

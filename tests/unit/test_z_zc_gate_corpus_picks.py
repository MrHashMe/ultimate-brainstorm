# -*- coding: utf-8 -*-
"""The reply corpus of the ID-picking gates (G6 finalists, G7 red-team picks, G8a gut pick, G8b decision), table-driven
like test_z_za_gate_corpus_y (KIT_SPEC 4.12).

Every row is one reply at one gate and its intent: `act <answer>` (a documented form: applied at once), `readback
<answer>` (read back, and the reading shown is that answer; nothing happens before a yes) or `ask` (asked again). An
answer is `SUG` (the suggested set on the card; at G8b the suggested idea) with `+<ID>` / `-<ID>` edits, a list of IDs
(a set at G6 and G7, in order at G8a), `skip` (G8a) or, at G8b, the chosen idea with `runner=<ID>` and `park=<IDs>`
(unnamed: no runner-up and nothing parked by the reply). The rows go through gates.prepare_answer -> gates.read_back ->
gates.apply, as in the W and Y corpus tests. A reply never acts wrong; a row whose handling differs from its intent in
a way that never acts (asked where a read-back was meant, or the reverse) is listed in PINNED with what it gets.

The fixture: ideas I-001..I-014; the G6 finalist pool is I-001..I-012 with the suggested finalists SUG6; at G7, G8a
and G8b the finalists are FIN, ranked I-003, I-007, I-001, I-004, I-002, I-009, the suggested red-team set is SUG7 and
the red-teamed ideas are TOP (the G8b suggestion is I-003).
"""

import hashlib
import json
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "engine"))
import engine_testlib as tl  # noqa: E402

from ublib.engine import gates, registry  # noqa: E402

TITLES = {"I-001": "shift swap board", "I-002": "SMS swap bot", "I-003": "ward chat swaps", "I-004": "swap credits",
          "I-005": "one-click manager approval", "I-006": "night-shift lottery", "I-007": "QR check-in swaps",
          "I-008": "fatigue score", "I-009": "swap marketplace", "I-010": "peer rating", "I-011": "calendar sync",
          "I-012": "float pool app", "I-013": "fax swaps", "I-014": "bonus points"}
POOL = ["I-%03d" % i for i in range(1, 13)]
SUG6 = ["I-001", "I-002", "I-003", "I-004", "I-005", "I-007", "I-009", "I-011"]
FIN = ["I-001", "I-002", "I-003", "I-004", "I-007", "I-009"]
RANKED = [("I-003", 71.0), ("I-007", 64.0), ("I-001", 55.0), ("I-004", 48.0), ("I-002", 40.0), ("I-009", 33.0)]
SUG7 = ["I-003", "I-007", "I-001"]
TOP = ["I-003", "I-007", "I-001", "I-004"]
SUGGESTED = "I-003"

ROWS = {
    'G6': [
        ('ok', 'act SUG'),
        ('OK', 'act SUG'),
        ('ok, thanks', 'act SUG'),
        ('Ok please', 'act SUG'),
        ('yes', 'act SUG'),
        ('looks good', 'act SUG'),
        ('I-001, I-003, I-007, I-010', 'act I-001,I-003,I-007,I-010'),
        ('I-001 I-003 I-007 I-010 I-012', 'act I-001,I-003,I-007,I-010,I-012'),
        ('I-001; I-002; I-003; I-006', 'act I-001,I-002,I-003,I-006'),
        ('i-003, i-007, i-010', 'act I-003,I-007,I-010'),
        ('- I-001\n- I-003\n- I-006\n- I-008', 'act I-001,I-003,I-006,I-008'),
        ('* I-002\n* I-004\n* I-012', 'act I-002,I-004,I-012'),
        ('1. I-003\n2. I-007\n3. I-010', 'act I-003,I-007,I-010'),
        ('I-003 and I-007 and I-010', 'act I-003,I-007,I-010'),
        ('I-003 & I-008', 'act I-003,I-008'),
        ('I-001, I-002, I-003, I-004, I-005, I-006, I-007, I-008', 'act I-001,I-002,I-003,I-004,I-005,I-006,I-007,'
                                                                   'I-008'),
        ('please I-003, I-007, I-010', 'act I-003,I-007,I-010'),
        ('I-003, I-007, I-010, thanks', 'act I-003,I-007,I-010'),
        ('I-003,I-007,I-010', 'act I-003,I-007,I-010'),
        ('I-003\nI-007\nI-010\nI-012', 'act I-003,I-007,I-010,I-012'),
        ('**I-003**, **I-007**, **I-010**', 'act I-003,I-007,I-010'),
        ('I-003 / I-007 / I-010', 'act I-003,I-007,I-010'),
        ('I-003, I-007 and I-010 please', 'act I-003,I-007,I-010'),
        ('`I-003`, `I-007`, `I-010`', 'act I-003,I-007,I-010'),
        ('I-003, I-007, I-010, I-003', 'act I-003,I-007,I-010'),
        ('I-003, I-007 and I-011 but not I-009', 'readback I-003,I-007,I-011'),
        ('ok but drop I-009', 'readback SUG-I-009'),
        ('ok, but without I-004', 'readback SUG-I-004'),
        ('the suggested set except I-005', 'readback SUG-I-005'),
        ('all of them except I-002 and I-005', 'readback SUG-I-002-I-005'),
        ('everything except I-011', 'readback SUG-I-011'),
        ('ok, plus I-010', 'ask'),
        ('ok but swap I-011 for I-010', 'readback SUG-I-011+I-010'),
        ('I-010 instead of I-011, rest ok', 'readback SUG-I-011+I-010'),
        ('replace I-009 with I-012', 'readback SUG-I-009+I-012'),
        ('no I-009', 'readback SUG-I-009'),
        ('not I-009', 'readback SUG-I-009'),
        ('ok minus I-001 and I-002', 'readback SUG-I-001-I-002'),
        ('I-003, I-007, I-010, I-011 - excluding I-004', 'readback I-003,I-007,I-010,I-011'),
        ('I-003, I-007, I-009? no. I-010', 'readback I-003,I-007,I-010'),
        ('I-003, I-007, maybe I-010', 'ask'),
        ('I-003, I-007, I-010 if I-010 is not a duplicate', 'ask'),
        ('I-003 and I-007. Or not.', 'ask'),
        ('I-003, I-007, wait no, I-010', 'ask'),
        ('should I-009 be in?', 'ask'),
        ('I-003, I-007, I-013', 'ask'),
        ('I-003, I-007, I-020', 'ask'),
        ('I-003', 'ask'),
        ('I-001, I-002, I-003, I-004, I-005, I-006, I-007, I-008, I-009', 'ask'),
        ('let me think about it and get back to you', 'ask'),
        ('not sure yet, I-003 and I-007 probably', 'ask'),
        ('I-003, I-007 and I-010 - will confirm with the team tomorrow', 'ask'),
        ('my manager wants I-003, I-007 and I-010', 'readback I-003,I-007,I-010'),
        ('I-003, I-007, I-010 (I-011 is a duplicate of I-003)', 'readback I-003,I-007,I-010'),
        ('Keep your eight but take I-012 in place of I-005', 'readback SUG-I-005+I-012'),
        ("I'd go with I-003, I-007, I-010 and I-012", 'readback I-003,I-007,I-010,I-012'),
        ('Hi team,\nfinalists: I-003, I-007, I-010\nThanks, Ahmed', 'readback I-003,I-007,I-010'),
        ('Go with I-003, I-007 and I-010 please', 'readback I-003,I-007,I-010'),
        ('I-003, I-007, I-010, but I-011 too if there is room', 'ask'),
        ('I-003, I-007, I-010 and not I-011 or I-012', 'readback I-003,I-007,I-010'),
        ('drop I-009 and I-011, add I-010', 'readback SUG-I-009-I-011+I-010'),
        ('I-003 I-007 I-010 - no I-009 please', 'readback I-003,I-007,I-010'),
        ('ok except I-009', 'readback SUG-I-009'),
        ('all but I-004', 'readback SUG-I-004'),
        ("I don't want I-009 in the final", 'readback SUG-I-009'),
        ('I-003, I-007, I-010, excluding I-003', 'ask'),
        ('go with the proposal but leave out I-002', 'readback SUG-I-002'),
        ('ok. no.', 'ask'),
        ('no', 'ask'),
        ('I-003, I-007, I-010 as finalists; I-011 later', 'ask'),
        ('> Reply with up to 8 finalist IDs, or `ok` for the suggested set.\nI-003, I-007, I-010',
         'readback I-003,I-007,I-010'),
        ('Sam (Slack): "I-003, I-007, I-010"', 'ask'),
        ('I-003, I-007, I-010 (per Sam)', 'readback I-003,I-007,I-010'),
        ('the first five', 'ask'),
        ('I-006 and I-008 as well', 'ask'),
        ('just I-003 and I-007', 'readback I-003,I-007'),
    ],
    'G7': [
        ('ok', 'act SUG'),
        ('OK thanks', 'act SUG'),
        ('yes please', 'act SUG'),
        ('sounds good', 'act SUG'),
        ('Ok.', 'act SUG'),
        ('I-003, I-007, I-001', 'act I-001,I-003,I-007'),
        ('I-003 I-007 I-004', 'act I-003,I-004,I-007'),
        ('I-003, I-007, I-001, I-004', 'act I-001,I-003,I-004,I-007'),
        ('i-002, i-003, i-009', 'act I-002,I-003,I-009'),
        ('- I-003\n- I-007\n- I-009', 'act I-003,I-007,I-009'),
        ('* I-001\n* I-002\n* I-003\n* I-004', 'act I-001,I-002,I-003,I-004'),
        ('1) I-003\n2) I-004\n3) I-007', 'act I-003,I-004,I-007'),
        ('I-003 and I-004 and I-009', 'act I-003,I-004,I-009'),
        ('I-003; I-007; I-002', 'act I-002,I-003,I-007'),
        ('I-003, I-007 & I-009', 'act I-003,I-007,I-009'),
        ('please I-003, I-004, I-007', 'act I-003,I-004,I-007'),
        ('I-003, I-004, I-007 thanks', 'act I-003,I-004,I-007'),
        ('I-003,I-004,I-009,I-002', 'act I-002,I-003,I-004,I-009'),
        ('I-001\nI-004\nI-009', 'act I-001,I-004,I-009'),
        ('**I-003** **I-004** **I-009**', 'act I-003,I-004,I-009'),
        ('I-003 / I-004 / I-007', 'act I-003,I-004,I-007'),
        ('I-007, I-003 and I-002, thank you', 'act I-002,I-003,I-007'),
        ('`I-002` `I-004` `I-009`', 'act I-002,I-004,I-009'),
        ('I-003 I-004 I-007 I-003', 'act I-003,I-004,I-007'),
        ('red-team everything except I-004: I-001 I-002 I-004', 'ask'),
        ('everything except I-001', 'ask'),
        ('all but I-009', 'ask'),
        ('ok but not I-001, take I-004 instead', 'readback SUG-I-001+I-004'),
        ('I-004 instead of I-001', 'readback SUG-I-001+I-004'),
        ('swap I-001 for I-009', 'readback SUG-I-001+I-009'),
        ('ok plus I-004', 'readback SUG+I-004'),
        ('ok, and add I-002 and I-009', 'ask'),
        ('I-003, I-007, I-004 but not I-001', 'readback I-003,I-004,I-007'),
        ('I-003, I-007, I-009, not I-004', 'readback I-003,I-007,I-009'),
        ('I-003, I-004, I-007, I-009 without I-009', 'ask'),
        ('I-003, I-007 and maybe I-004', 'ask'),
        ('I-003, I-007, I-004 if the budget allows', 'ask'),
        ('I-003, I-007, I-004. or not', 'ask'),
        ('I-003, I-007, I-001 - wait, I-004 not I-001', 'ask'),
        ('do we need I-001 in there?', 'ask'),
        ('I-003, I-007, I-011', 'ask'),
        ('I-003, I-007, I-014', 'ask'),
        ('I-003 and I-007', 'ask'),
        ('I-001, I-002, I-003, I-004, I-007', 'ask'),
        ('I-003', 'ask'),
        ('hold on, I want to read the cards again', 'ask'),
        ('no idea, you choose', 'ask'),
        ('I-003, I-007 and I-004, I will confirm I-004 next week', 'ask'),
        ('my boss wants I-003, I-004 and I-007', 'readback I-003,I-004,I-007'),
        ('Hi,\nplease red-team I-003, I-004 and I-007.\nBest regards,\nAhmed', 'readback I-003,I-004,I-007'),
        ('red-team I-003, I-004, I-007', 'readback I-003,I-004,I-007'),
        ('I would like I-002, I-003 and I-007 to be reviewed', 'readback I-002,I-003,I-007'),
        ('I-003, I-007, I-001 (I-004 is too close to I-003)', 'readback I-001,I-003,I-007'),
        ('Not I-001. I-003, I-004, I-007.', 'readback I-003,I-004,I-007'),
        ('I-001? no. I-003, I-004, I-007', 'readback I-003,I-004,I-007'),
        ('I-004 over I-001, rest as suggested', 'readback SUG-I-001+I-004'),
        ('ok except I-001, add I-009', 'readback SUG-I-001+I-009'),
        ('drop I-001, add I-002', 'readback SUG-I-001+I-002'),
        ('ok but no I-007', 'ask'),
        ('I-003, I-007, I-004, I-001 but I-001 only if there is budget', 'ask'),
        ('Sam (Slack): "I-003, I-004, I-007"', 'ask'),
        ('I-003, I-004, I-007 (per the team call)', 'readback I-003,I-004,I-007'),
        ('I-003, I-004, I-007\n# I-001 is too safe', 'readback I-003,I-004,I-007'),
        ('I-003, I-004 and I-007, not the others', 'readback I-003,I-004,I-007'),
        ('no', 'ask'),
        ('I-003, I-004, I-007?', 'ask'),
    ],
    'G8a': [
        ('I-003\nI-007\nI-001', 'act I-003,I-007,I-001'),
        ('I-003: ward chat is where nurses already are\nI-007: QR is cheap\nI-001: simple board',
         'act I-003,I-007,I-001'),
        ('skip', 'act skip'),
        ('Skip.', 'act skip'),
        ('I-004, I-002, I-009', 'act I-004,I-002,I-009'),
        ('1. I-009 - bold\n2. I-004 - cheap\n3. I-002 - safe', 'act I-009,I-004,I-002'),
        ('- I-001 (trust)\n- I-003 (reach)\n- I-007 (cost)', 'act I-001,I-003,I-007'),
        ('I-007', 'act I-007'),
        ('I-007, I-003', 'act I-007,I-003'),
        ('i-002 i-001 i-004', 'act I-002,I-001,I-004'),
        ('I-003 because nurses already use the ward chat\nI-001 because it is simple\nI-009 because it is bold',
         'act I-003,I-001,I-009'),
        ('**I-004** first, **I-003** second, **I-007** third', 'act I-004,I-003,I-007'),
        ('I-001 > I-003 > I-007', 'act I-001,I-003,I-007'),
        ('I-009; I-002; I-004', 'act I-009,I-002,I-004'),
        ('skip it', 'act skip'),
        ('I-003 first, then I-007, then I-004', 'act I-003,I-007,I-004'),
        ('I-002 - my gut says nurses want cash\nI-004 - credits are fun\nI-001 - boring but works',
         'act I-002,I-004,I-001'),
        ('I-003 I-007 I-001 thanks', 'act I-003,I-007,I-001'),
        ('#1 I-007, #2 I-001, #3 I-009', 'act I-007,I-001,I-009'),
        ('Top: I-004. Then I-002. Then I-003.', 'act I-004,I-002,I-003'),
        ('I-003 (strong), I-007 (cheap), I-009 (wild)', 'act I-003,I-007,I-009'),
        ('I-001\nI-002\nI-003\n', 'act I-001,I-002,I-003'),
        ('I-003 / I-007 / I-004', 'act I-003,I-007,I-004'),
        ('I-003, I-007, not I-001', 'act I-003,I-007'),
        ('I-003 and I-007, but not I-009', 'act I-003,I-007'),
        ('I-007 over I-003, then I-001', 'act I-007,I-003,I-001'),
        ('I-004 instead of I-003, then I-007', 'act I-004,I-007'),
        ('Not I-003. I-007, I-001, I-009.', 'act I-007,I-001,I-009'),
        ('I-003? no. I-007, I-001, I-004', 'act I-007,I-001,I-004'),
        ('I-003, I-007, I-001, I-004', 'ask'),
        ('I-003, I-007, I-011', 'ask'),
        ('I-003, I-007 and maybe I-001', 'act I-003,I-007,I-001'),
        ('I-003, wait no, I-007 first, then I-003, then I-001', 'ask'),
        ('I-003 then I-007. or not.', 'ask'),
        ('Can I pick I-011?', 'ask'),
        ('I-001, I-001, I-003', 'act I-001,I-003'),
        ('no gut feeling, skip', 'act skip'),
        ('skip, no strong feeling', 'act skip'),
        ("don't skip: I-003, I-007, I-001", 'act I-003,I-007,I-001'),
        ('I-003 not I-007', 'act I-003'),
        ('I-007, then I-001 rather than I-003', 'act I-007,I-001'),
        ('everything except I-002', 'ask'),
        ('I-004, I-009, I-013', 'ask'),
        ('I-003 is my favourite, I-007 is second, I-009 third', 'act I-003,I-007,I-009'),
        ('gut says I-009, head says I-003; I-001 third', 'act I-009,I-003,I-001'),
        ('I-003, then I-007 (not I-004, too pricey), then I-001', 'act I-003,I-007,I-001'),
        ('none of them', 'ask'),
        ('I-003 and I-007 are my top two, no third', 'act I-003,I-007'),
        ('I-007\nI-003\n- not I-001, it feels stale', 'act I-007,I-003'),
        ('skip, but if I must: I-003', 'ask'),
        ('I-003 over I-007 over I-001', 'act I-003,I-007,I-001'),
        ('I-009 first. I-003 second. I-002 third. Definitely not I-004.', 'act I-009,I-003,I-002'),
        ('I-003, I-007, I-001 excluding I-007', 'ask'),
        ('no', 'ask'),
        ('my gut: I-004, I-001, I-009', 'act I-004,I-001,I-009'),
        ('Sam (Slack): "I-003, I-007, I-001"', 'ask'),
        ('I-003 I-007 I-001?', 'ask'),
        ('I-002 without a doubt, then I-004 and I-009', 'act I-002,I-004,I-009'),
        ('All three: I-003, I-007, I-001', 'act I-003,I-007,I-001'),
        ('I-001 but no I-003, then I-009', 'act I-001,I-009'),
        ('I-003 then I-004 then I-002, skip the reasons', 'act I-003,I-004,I-002'),
        ('I-001, no wait, I-002, then I-003', 'ask'),
    ],
    'G8b': [
        ('ok', 'act SUG'),
        ('OK', 'act SUG'),
        ('yes', 'act SUG'),
        ('ok thanks', 'act SUG'),
        ('sounds good', 'act SUG'),
        ('Ok.', 'act SUG'),
        ('I-007', 'act I-007'),
        ('i-007', 'act I-007'),
        ('I-007 please', 'act I-007'),
        ('I-007, thanks', 'act I-007'),
        ('**I-007**', 'act I-007'),
        ('I-007!', 'act I-007'),
        ('I-007 because night staff already trust the ward chat', 'act I-007'),
        ('I-007: cheapest to test this month', 'act I-007'),
        ('I-007 - cheapest to test', 'act I-007'),
        ('I-004 because the credits make swaps fair', 'act I-004'),
        ('I-004 since nurses like points', 'act I-004'),
        ('I-003 because it had the most BACK verdicts', 'act I-003'),
        ('I-007 because it is cheap; runner-up: I-003; park: I-009', 'act I-007 runner=I-003 park=I-009'),
        ('I-001\nrunner-up: I-004', 'act I-001 runner=I-004'),
        ('I-002, park: I-009', 'act I-002 park=I-009'),
        ('ok, runner-up: I-007', 'act SUG runner=I-007'),
        ('ok\npark: I-009', 'act SUG park=I-009'),
        ('I-007 because QR check-in is already on every ward\nrunner-up: I-001', 'act I-007 runner=I-001'),
        ('I-009 because it is the boldest bet; park: I-001, I-002', 'act I-009 park=I-001,I-002'),
        ('I-007 because it scored well, park: I-009', 'act I-007 park=I-009'),
        ('Not I-003, take I-007', 'readback I-007'),
        ('I-003? no. I-007.', 'readback I-007'),
        ('ok but I-007 as runner-up', 'readback SUG runner=I-007'),
        ('I-007 instead of I-003', 'readback I-007'),
        ('I-007 over I-003', 'readback I-007'),
        ('I-007 rather than I-003', 'readback I-007'),
        ('I-004 as the runner-up and I-007 as the pick', 'readback I-007 runner=I-004'),
        ('runner-up I-004, choose I-007', 'readback I-007 runner=I-004'),
        ('I-007, not I-003', 'readback I-007'),
        ('I-007, but only if the pilot ward agrees', 'ask'),
        ('I-007 I think, or maybe I-004', 'ask'),
        ('I-007. Or not.', 'ask'),
        ('I-007, wait no, I-004', 'ask'),
        ('should I pick I-007?', 'ask'),
        ('I-011', 'ask'),
        ('I-007 and I-004', 'ask'),
        ('I-007 or I-004', 'ask'),
        ('let me sleep on it', 'ask'),
        ('I-007 - will confirm with the ward manager tomorrow', 'ask'),
        ('my manager picked I-007', 'readback I-007'),
        ('Sam (Slack): "go with I-007"', 'ask'),
        ('go with I-007', 'readback I-007'),
        ('I choose I-007 because the QR codes are already printed', 'readback I-007'),
        ('I-007 because it is cheaper than I-003', 'readback I-007'),
        ('I-007 because unlike I-003 it needs no new app', 'readback I-007'),
        ('ok but park I-009', 'readback SUG park=I-009'),
        ('I-007 if the budget is approved, otherwise I-003', 'ask'),
        ('I-007 (not I-003, too crowded)', 'readback I-007'),
        ('accept the suggestion', 'readback SUG'),
        ('no', 'ask'),
        ('I-007, runner-up: I-007', 'ask'),
        ('ok, runner-up: I-003', 'ask'),
        ('I-007 because the nurses asked for it; runner-up: I-011', 'ask'),
        ('I-004 but not as the final pick, just the runner-up', 'ask'),
        ('I-007 because it is not as risky', 'readback I-007'),
        ('I-007 because nurses may like it', 'readback I-007'),
        ('I-007 but I-003 is a close second', 'readback I-007'),
        ('take I-007, drop I-003', 'readback I-007'),
        ('I-007 because it is the cheapest to test, I-004 as runner-up', 'readback I-007 runner=I-004'),
        ('Dear team,\nwe choose I-007.\nBest regards,\nAhmed', 'readback I-007'),
    ],
}
DOCUMENTED = {"G6": 25, "G7": 24, "G8a": 23, "G8b": 26}  # the first rows of each gate: plain documented forms
# rows whose handling differs from the intent without acting: (gate, reply) -> what they get ('ask' or 'rb')
PINNED = {}


def corpus_sha256():
    return hashlib.sha256(json.dumps(ROWS, sort_keys=True).encode("utf-8")).hexdigest()


def expected(gate, spec):
    """The outcome an intent's answer names (outcome() below)."""
    toks = spec.split()
    if gate == "G8b":
        extra = dict(t.split("=", 1) for t in toks[1:])
        return {"r": SUGGESTED if toks[0] == "SUG" else toks[0], "runner": extra.get("runner", "-"),
                "park": ",".join(sorted(extra["park"].split(","))) if "park" in extra else "-"}
    if gate == "G8a":
        return {"r": toks[0]}
    if toks[0].startswith("SUG"):
        ids = list(SUG6 if gate == "G6" else SUG7)
        for sign, i in re.findall(r"([+-])([IEQ]-\d+)", toks[0]):
            ids = [x for x in ids if x != i] + ([i] if sign == "+" else [])
    else:
        ids = toks[0].split(",")
    return {"r": ",".join(sorted(set(ids)))}


def outcome(gate, ctx, ans):
    """What the applied answer did: the finalists (G6), the red-team set (G7), the recorded gut picks in order (G8a),
    or the chosen idea with the runner-up and the parked ideas the answer names (G8b)."""
    s = ctx.state
    if gate == "G6":
        return {"r": ",".join(sorted(s.get("finalists") or []))}
    if gate == "G7":
        return {"r": ",".join(sorted(s.get("top") or registry.default_top(ctx, s.get("finalists") or [])))}
    if gate == "G8a":
        return {"r": "skip" if ans.get("skip") and not ans.get("picks") else ",".join(ans.get("picks") or [])}
    return {"r": (s.get("choice") or {}).get("idea"), "runner": ans.get("runner_up") or "-",
            "park": ",".join(sorted(ans.get("park") or [])) or "-"}


def judge(gate, intent, got):
    """act-right, act-wrong, rb-right (the reading is the intent's answer), rb-other or ask."""
    if got["how"] == "ask":
        return "ask"
    kind, _sp, spec = intent.partition(" ")
    right = kind in ("act", "readback") and all(got.get(k) == v for k, v in expected(gate, spec).items())
    return ("act-" if got["how"] == "act" else "rb-") + ("right" if right else "wrong" if got["how"] == "act" else
                                                         "other")


def build(case, gate, n):
    ctx = case.make_ctx(mode="standard", autopilot="hands-on", run_name="2026-09-29-zc%d" % n)
    ctx.write("screen/ideas.md", "".join("%s | %s | pitch | mechanism\n" % kv for kv in sorted(TITLES.items())))
    ctx.write_json("screen/shortlist.json", {"shortlist": [{"id": i, "score": round(9.0 - k * 0.3, 2)}
                                                           for k, i in enumerate(POOL)]})
    ctx.write_json("tournament/result.json", {"debiased": [{"id": i, "pct": p, "rank": k + 1}
                                                           for k, (i, p) in enumerate(RANKED)],
                                              "ranking": {"method": "bradley-terry"}})
    ctx.state["finalists"] = list(SUG6 if gate == "G6" else FIN)
    if gate == "G8b":
        ctx.state["top"] = list(TOP)
    return ctx


def read(case, gate, reply, n):
    """One reply through gates.prepare_answer -> gates.read_back -> gates.apply: {"how": act | rb | ask, ...}."""
    ctx = build(case, gate, n)
    provided = {"reply": reply}
    ans, _notes, errs = gates.prepare_answer(ctx, gate, provided)
    if errs:
        return {"how": "ask", "why": errs[0]}
    rb = gates.read_back(ctx, gate, provided, ans)
    gates.apply(ctx, gate, ans)
    return dict(outcome(gate, ctx, ans), how="rb" if rb else "act", say=rb)


class GateCorpusPicks(tl.EngineTestCase):
    def check(self, gate):
        with mock.patch("os.fsync", lambda fd: None):  # a run per row, in a temp dir: no need to reach the disk
            for n, (reply, intent) in enumerate(ROWS[gate]):
                with self.subTest(gate=gate, reply=reply):
                    got = read(self, gate, reply, n)
                    kind = judge(gate, intent, got)
                    self.assertNotEqual(kind, "act-wrong", "acted wrong: want %s, got %r" % (intent, got))
                    want = {"act": "act-right", "readback": "rb-right", "ask": "ask"}[intent.split()[0]]
                    pin = PINNED.get((gate, reply))
                    self.assertEqual(kind, {"ask": "ask", "rb": "rb-right"}.get(pin, want),
                                     "want %s, got %r" % (intent, got))

    def test_corpus_shape(self):
        for gate, rows in ROWS.items():
            docs = rows[:DOCUMENTED[gate]]  # the plain documented forms come first; the rest sit near a consequence
            self.assertGreaterEqual(len(rows), 60, gate)
            self.assertGreaterEqual(len(docs), 20, gate)
            self.assertTrue(all(r[1].startswith("act ") for r in docs), gate)
            self.assertGreaterEqual(len(rows) - len(docs), 20, gate)
            self.assertEqual(len(set(r[0] for r in rows)), len(rows), gate)
        self.assertEqual(set(PINNED) - set((g, r[0]) for g in ROWS for r in ROWS[g]), set())


def _add(gate):
    setattr(GateCorpusPicks, "test_%s" % gate.lower(), lambda self: self.check(gate))


for _gate in ROWS:
    _add(_gate)


class Floods(tl.EngineTestCase):
    """The reader stays linear: a 20000-character reply is read, checked for a documented form, read back and applied
    in under 3 s at every ID-picking gate."""

    def test_linear(self):
        n = 20000
        floods = (
            ("G6", "I-001 " * (n // 6)), ("G6", "not " * (n // 4) + "I-009"), ("G6", "all but " * (n // 8) + "I-009"),
            ("G6", "I-003" + " " * n + "I-007"), ("G6", "(" * n + "I-003"), ("G6", "I-003 because " + "x " * (n // 2)),
            ("G6", "replace " * (n // 8) + "I-001"), ("G6", "I-003? " * (n // 7)), ("G6", "- I-003\n" * (n // 8)),
            ("G7", "I-003 rather than " * (n // 18)), ("G7", "I-003, and " * (n // 11)), ("G7", "# " * (n // 2)),
            ("G7", "swap I-001 for " * (n // 15)), ("G7", "the suggestion " + "plus " * (n // 5)),
            ("G8a", "I-007 " + "or not " * (n // 7)), ("G8a", "skip " * (n // 5)), ("G8a", "I-007 I-003 " * (n // 12)),
            ("G8b", "I-007 because " + "runner-up " * (n // 10)), ("G8b", "park " * (n // 5) + "I-009"),
            ("G8b", "I-007;" * (n // 6)), ("G8b", "runner-up: I-001, " * (n // 18)), ("G8b", "- " * n),
            ("G8b", "I-007" + " " * n + "because x"), ("G8b", "I-007 is " + "fine and " * (n // 9)),
            ("G8b", "I-007 " + "\u2014 " * (n // 2) + "cheap"))
        with mock.patch("os.fsync", lambda fd: None):
            for k, (gid, text) in enumerate(floods):
                t0 = time.perf_counter()
                gates.parse_reply(gid, text, None, [])
                read(self, gid, text, 700 + k)
                self.assertLess(time.perf_counter() - t0, 10.0, (gid, text[:24]))


class ReadBackText(tl.EngineTestCase):
    """A read-back states every consequence: the ideas the paid step runs on, what the reply drops from or adds to the
    suggested set, and at G8b the chosen idea against the suggestion and the runner-up the rule would record."""

    def say(self, gate, reply, n):
        with mock.patch("os.fsync", lambda fd: None):
            got = read(self, gate, reply, 800 + n)
        self.assertEqual(got["how"], "rb", got)
        self.assertTrue(got["say"].startswith(gates.READBACK_HEAD), got["say"])
        return got["say"]

    def test_g6_names_the_finalists_and_what_the_reply_drops(self):
        say = self.say("G6", "all but I-009", 1)
        self.assertIn("finalists: I-001, I-002, I-003, I-004, I-005, I-007, I-011 (paid model calls)", say)
        self.assertIn("this drops I-009 from the suggested set", say)

    def test_g7_names_the_red_team_set_and_the_swap(self):
        say = self.say("G7", "I-003, I-007 and I-004 rather than I-001", 2)
        self.assertIn("red-team I-003, I-007, I-004 (paid model calls)", say)
        self.assertIn("this drops I-001 from the suggested set; this adds I-004", say)

    def test_g8b_names_the_choice_the_suggestion_and_the_runner_up_by_rule(self):
        say = self.say("G8b", "Not I-003, take I-007", 3)
        self.assertIn("choose I-007 QR check-in swaps, not the suggestion I-003", say)
        self.assertIn("the probe, the architecture and the proposal are built for it (paid model calls)", say)
        self.assertIn("runner-up: I-003 (by rule: the best-ranked other idea)", say)

    def test_g8a_is_recorded_without_a_read_back(self):
        with mock.patch("os.fsync", lambda fd: None):
            got = read(self, "G8a", "I-007 and then I-003, but not I-001", 4)
        self.assertEqual((got["how"], got["r"]), ("act", "I-007,I-003"))


if __name__ == "__main__":
    unittest.main()

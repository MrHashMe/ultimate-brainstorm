# Privacy

This page says what leaves your machine, to whom, and how to limit it. The short version: your topic and ideas go to
the model families you set up and to web search; your code stays with your host agent's vendor unless you allow more;
keys never leave your environment variables; there is no telemetry.

## What goes where

| What | Goes to | When |
|---|---|---|
| Your topic, your seed ideas, the frame, the ideas the models generate | every model family you set up (Anthropic, OpenAI, Moonshot, Zhipu/Z.ai) | whenever a job for that family runs |
| Search queries built from your topic and ideas | the web search tool of the family doing research (Claude's or Codex's web search). Z.ai's search tools (`setup-glm --zai-mcp`) receive queries only when you use them yourself in a `claude-glm` session | research, prior-art checks, stack version checks |
| Facts about your repo (file paths, and file contents only if you allow it) | your host agent's vendor; other vendors only with `code = yes` | software and growth runs inside a repo |
| Your answers to the questions | stored in the run folder; the text you type is used in prompts where the step needs it (for example your reasons for a decision) | every question |
| API keys | only the vendor they belong to | each call; never written anywhere except a temporary settings file readable only by you, deleted after the call |
| Usage data about the kit | nobody | never: there is no telemetry. When the kit runs `npx skills`, it sets `DISABLE_TELEMETRY=1` |

Everything the pipeline produces stays in `brainstorm/<run>/` on your machine. Nothing is published or committed unless
you say yes at the handoff question, and even then it is only copied into your project's `docs/` folder.

## The privacy question at the start

The first card of every run shows the plan and asks three things (you can answer in one line):

| Setting | Default | If you turn it off |
|---|---|---|
| **web**: may the research and check steps use web search? | yes | no web search at all. Research says "NOT SEARCHED", prior-art checks say "NOT CHECKED" (and can never kill an idea), stack versions stay "NOT SEARCHED" |
| **vendors**: may other vendors (other model families) see the idea text? | yes | only your host agent's vendor is used. Every "other family" seat uses the same vendor in a fresh context, and the results are marked PROVISIONAL |
| **code**: may code facts and repo files go to vendors other than your host's? | no | (this is already the default) other vendors get file paths but no file contents and no code blocks, only the domain terms you approved, and they are never run inside your repo |

## The `private` keyword

Type `private` before your topic, for example `/ultimate-brainstorm private payroll tool for our HR team`. It turns
off web search and other vendors in one go: every job runs on your host agent's vendor, nothing is searched, and every
cross-family step is marked PROVISIONAL.

## Enforcement

These answers are binding. The kit checks them twice: when it builds each job, and again in the process that makes
the call. A job that would break them (a web job with web off, a job for a vendor you excluded, a repo job for another
vendor with code off) is refused and reported; it never runs quietly.

**Full-auto remembers your privacy answer.** The first `full-auto` run asks the kickoff question once and saves your
web / vendors / code answers as `privacy_defaults` in `~/.ultimate-brainstorm/config.json`; later full-auto runs use
them without asking. See or change them with `ub config get privacy_defaults` and
`ub config set privacy_defaults '{"web": true, "vendors": false, "code": false}'` (remove the key from config.json to be asked again).
`private`, `web: no` and `vendors: no` typed with a topic still apply to that run.

Other safeguards:
- Model calls run in an empty temporary folder, with no tools unless the step needs web search (or reading your repo,
  for your host vendor only).
- Prompts never contain API keys. Logs and call records are scrubbed of any key value the kit knows.
- The GLM Coding Plan key is used only through Claude Code or Codex, never over plain HTTP.

## What each vendor may keep

What happens to your data after it reaches a vendor is governed by that vendor's terms and your plan (for example,
whether conversations may be used for training). The kit cannot change that. If this matters for a topic, use
`private`, or set up only the vendors whose terms you accept.

## In a git repo

For software and growth runs, add `brainstorm/` to `.git/info/exclude` (local, never committed) so run files stay out
of `git status` and commits. The kit never commits, pushes or changes git settings.

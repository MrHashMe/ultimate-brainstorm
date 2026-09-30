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
| Opening `index.html` of the proposal pack while online | cdn.jsdelivr.net receives your IP address when the page loads its pinned Mermaid script; nothing of the proposal is sent (no referrer, and the page's security policy blocks every other request). A run without web access (`private`, or web: no) gets a page that loads no script at all; its diagrams show their source | each time the page is opened online |
| API keys | only the vendor they belong to | each call; never written anywhere except a temporary settings file readable only by you, deleted after the call |
| Usage data about the kit | nobody | never: there is no telemetry. The installer runs no `npx skills` (the component skills come from a pinned archive); the manual `npx skills` routes in the docs set `DISABLE_TELEMETRY=1` |

Everything the pipeline produces stays in `brainstorm/<run>/` on your machine (Kimi transcripts kept for diagnostics
included: the first megabyte of the first 3 of each run in `logs/kimi-samples/`, redacted, never for jobs that read
your repository). The only other
record is the list of your runs (path and topic) in the kit home's `runs.json`. Nothing is published or committed
unless you say yes at the handoff question, and even then it is only copied into your project's `docs/<run>/` folder.

## The privacy question at the start

The first card of every run shows the plan and asks three things (you can answer in one line):

| Setting | Default | If you turn it off |
|---|---|---|
| **web**: may the research and check steps use web search? | yes | no web search at all. Research says "NOT SEARCHED", prior-art checks say "NOT CHECKED" (and can never kill an idea), stack versions stay "NOT SEARCHED" |
| **vendors**: may other vendors (other model families) see the idea text? | yes | only your host agent's vendor is used. Every "other family" seat uses the same vendor in a fresh context, and the results are marked PROVISIONAL |
| **code**: may code facts and repo files go to vendors other than your host's? | no | (this is already the default) other vendors get file paths but no file contents and no code: no fenced or indented code blocks, no `<pre>`/`<code>` elements and no inline code that reads as a statement (diagrams stay); an indented line right under a sentence or a list item is removed too when that sentence or item ends with `:` (also inside bold or italics, as in `**Install:**`) or when the line reads as code (`=`, `;`, braces, `->`, `::`, a call, a leading keyword such as `def`, `import`, `SELECT` or `FROM`, a trailing `:`, `key: value` with a one-word or quoted value, `#include`, a decorator, `require`, `export default`, `$ `, a command option such as `-H`, or bare names such as `API_KEY`), together with the indented lines right above it; in text quoted from earlier steps (facts, checks, reviews, architecture files, proposal sections) every line indented 4 or more columns is removed unless it is a list item or only cites a path or URL, whatever list item it sits in; in the kit's own prompt text, indented prose that is not introduced by a `:` and lines that only cite a path or URL stay, which is why repo-reading jobs are told to cite `path:line` only; inline code such as `os.environ[...]`, `SELECT ... FROM` or `import x` is removed too (a known limit: a span is read on one line, so inline code that a line break splits over two lines stays); only the domain terms you approved (those marked `[proposed]`, never the terms of your repository's CONTEXT.md; a term or heading without the mark on its own line is left out together with the definition and source lines under it, in the facts and in the proposal's glossary, Appendix E, which the proposal reviewers read); and they never run inside your repo. In a software or growth run inside a git repository (a git worktree or submodule too) this applies to everything those vendors are sent (checks, reviews, architecture files, proposal sections), not only to the facts |

## The `private` keyword

Type `private` before your topic, for example `/ultimate-brainstorm private payroll tool for our HR team`. It turns
off web search and other vendors in one go: every job runs on your host agent's vendor, nothing is searched, and every
cross-family step is marked PROVISIONAL.

## Enforcement

These answers are binding. The kit checks them twice: when it builds each job, and again in the process that makes
the call, which reads the prompt itself. A job that would break them (a web job with web off, a job for a vendor you
excluded, a repo job for another vendor with code off, or a prompt for another vendor that still contains code from
your repository) is refused before anything is sent and reported; it never runs quietly.

Reality checks by another vendor's model (privacy `code` = no) are not asked for the codebase-fit section or for
file:line citations, and every check prompt tells the model to run no shell commands and read no local files (the host
vendor's checker may read the repository in software and growth runs).

**Full-auto remembers your privacy answer.** The first `full-auto` run asks the kickoff question once and saves your
web / vendors / code answers, with the vendors the kickoff card listed as seeing your idea text (`vendor_set`), as
`privacy_defaults` in `~/.ultimate-brainstorm/config.json`; later full-auto runs use them without asking. A later
full-auto run with a family from a vendor that list does not name (you set up Kimi, say) asks the kickoff question
again and saves the new list: your consent never widens silently. Defaults saved by 2.0.x (no vendor list) are asked
once more. With `vendors: no` saved, only your host's vendor sees your idea text, so a new family never asks. See or
change them with `ub config get privacy_defaults` and `ub config set privacy_defaults '{"web": true, "vendors": false,
"code": false}'` (remove the key from config.json to be asked again; `"vendors": true` without a `vendor_set` is asked
once). A value other than `true` or `false` (`ub config set privacy_defaults.vendors no` stores the word `no`) is no
saved answer: the kickoff question is asked. `private`, and `web: no`, `vendors: no` and `code: no` typed before the
topic or at the end of a line (`full-auto vendors: no payroll tool`, `payroll tool, vendors: none`), apply to that run
over the saved answers (a typed `yes` is the kickoff card's to give; a pair inside the topic, such as `a code: yes/no
review bot`, stays in the topic). A `no` the kickoff cannot tell is a setting, such as `(vendors: no)`, `vendors=no`,
`**vendors:** no` or a sentence that puts `no`, `not`, `without`, `never`, `don't`, `avoid`, `skip` or `only` within
three words of `vendors`, `web search` or a vendor or model name (`no vendors please`, `without web search`, `don't
send anything to OpenAI`), makes the kickoff card ask, even in full-auto; `ub run` with no input stops at that card
instead of using the saved answers, and so does a terminal G0 that shows again after a reply it could not apply. Other
wordings (`No web.`, `web off`, `vendors: not allowed`, `Keep it confidential.`) are not read: type `web: no`,
`vendors: no`, `code: no` or `private`. A run continued on another host (`ub continue RUN --host codex`) or in a
terminal (`ub run --continue RUN`) never seats a family of a vendor your kickoff answer did not list, other than the
vendor of the agent you move the run to (OpenAI for Codex): that agent reads the run anyway, and with `vendors: no` it
takes every seat. A host of no known family (`--host other`) and a terminal have no such exemption. Moved back to an
agent of a listed vendor, the run is hosted by that vendor's family again.

Other safeguards:
- Model calls run in an empty temporary folder, with no tools unless the step needs web search (or reading your repo,
  for your host vendor only). Codex has a shell, connectors, plugins and sub-agents of its own: the kit switches them
  off for these calls and discards any answer that used anything the step did not allow (a shell, a file edit, an MCP
  tool, a sub-agent, a web search, or anything it does not recognize; the call is refused, never retried). Your own
  Claude settings, hooks and plugins, and your Codex hooks, memories, notify program and the MCP servers named in your
  `~/.codex/config.toml`, are kept out of these calls (a Codex MCP server whose name has a character other than
  letters, digits, `_` and `-`, such as a dot, or one from a system or project Codex config, still starts, and so does
  every server of that config.toml when the kit cannot read part of the file without Python 3.11+ (`family.py detect`
  names the line); any call to such a server is refused); the parts of your Claude settings that carry your login or
  network route (the `env` block, an `apiKeyHelper`) are passed to each call in a temporary file only you can read,
  deleted afterwards. `family.py detect`, the kickoff card and `ub doctor` list what still applies (for example your
  `~/.codex/AGENTS.md`). Claude workers that read your repository are also denied the kit's run folders by tool rules,
  so they never read earlier runs' prompts or outputs. A `CLAUDE.md` in your kit home's parent folders reaches Claude
  workers as project memory; `family.py detect` names it.
- Prompts never contain API keys. Logs and call records are scrubbed of any key value the kit knows and of common
  credential shapes (tokens, passwords in URLs, authorization headers, private keys).
- Text that earlier steps wrote (checks, research summaries, reviews, the decision record, architecture files)
  reaches later prompts only inside marked DATA blocks, and every prompt says that text inside them is quoted data,
  never instructions. One exception: the frame questions stay plain in the frame writer's prompt, next to your answers
  to them, because together they are that step's task.
- The GLM Coding Plan key is used only through Claude Code or Codex, never over plain HTTP.

## What each vendor may keep

What happens to your data after it reaches a vendor is governed by that vendor's terms and your plan (for example,
whether conversations may be used for training). The kit cannot change that. If this matters for a topic, use
`private`, or set up only the vendors whose terms you accept.

## In a git repo

For software and growth runs, the kit writes a `.gitignore` (containing `*`) into the run folder and into
`brainstorm/` the first time it builds a job that reads your repository, so run files stay out of `git status`,
commits and code searches. To hide them before that, add `brainstorm/` to `.git/info/exclude` (local, never
committed). The kit never commits, pushes or changes git settings.

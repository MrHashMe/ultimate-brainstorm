# Changelog 2.1.0

All notable changes to ultimate-brainstorm are listed here, newest first.

## 2.1.0 - 2026-09-30

Reliability, fairness and privacy release. A run stays consistent when several sessions touch it, the rankings rest
on sounder statistics, repository code no longer reaches other vendors, and the install is pinned and verifiable.
One breaking change: G14 now publishes each run into its own `docs/<run>/` folder (see Publishing). A gate reply that
is not in the card's own words is now read back, and acts only after your `yes` (see Validation and parsing).

Acceptance override: released at the owner's request before the live acceptance run of docs/ACCEPTANCE.md. Every
change passes the offline suites on Linux, macOS and Windows (Python 3.9, 3.12 and 3.14); the checks not yet verified
live are listed at the end of these notes.

### Concurrency and run state

- One session drives a run at a time, decided by an operating-system lock that is freed when its process ends, even
  after a crash; `run.json` saves are checked against a revision number, so another session's answer is never
  overwritten. A terminal no longer holds the run while it waits for your answer. A command refused because another
  session drives the run changes nothing, and its card retries it (a `continue --host` switch is no longer lost).
- `ub stop` pauses the run: it creates `.ub/STOP`, stops the workers, and nothing is launched or called until
  `continue` or `run --continue` resumes it. The agent's own `ub next` never lifts a stop, and `ub stop` on a finished
  run does nothing. `ub stop` names the workers it could not verify (their process identity cannot be read) instead
  of dropping them silently, and keeps their markers. It no longer reports a service or another user's process that
  reused a dead worker's process ID (Windows, Linux) as a worker to stop by hand; that marker is removed.
- Redo, switch, import and gate resets move old outputs through a journal: a file another program holds open no
  longer leaves finished steps without their outputs, and the card names the file.
- Host tasks and host sub-agent batches are leased to one session; `done` accepts only files written after the task
  was handed out, and a re-armed host job is handed out again instead of reusing its old output. A `done` for a task
  never handed out issues the task, and a late write after a takeover is named. A HOST step that was blocked while its
  card was issued (an engine error fixed as the card said) is accepted once done, instead of being handed out again
  forever. A task's files are fsynced before `done` records it; a file still held open keeps the task waiting for
  `done_cmd` again. A session whose task was taken over and accepted elsewhere, and that changed its files afterwards,
  gets a BLOCKED card instead of driving on. The engine's own rewrite of an accepted host file (2.2 normalizing the
  criteria weights, a G2c correction) no longer gives a displaced session's `done` a BLOCKED late-write card that
  suggests a redo; a real late write is still named.
- A lease holder no longer waits for itself. A HOST_BATCH lease holder's AUTO cards keep its `--lease`, the lease ends
  when every host job has its outcome, and another session's poll counts finished host jobs. A session that holds a
  host sub-agent lease also keeps its `--lease` on the cards it gets mid-step: the budget question's `answer_cmd` and
  the `next`, `answer` and `budget` fix commands (`answer` and `budget` now take `--lease`), so its own answer no longer
  waits, as "another session", for its lease to expire. SKILL.md: a fallback `next` adds the `--lease` of the last
  `then` or `task.done_cmd`, so a HOST task holder that lost its card gets the task back instead of waiting up to an
  hour for itself; the wait card says so. `ub run --continue` takes over a host task another session holds, as
  `continue` does: the terminal skips it at once instead of waiting up to an hour.
- A job is called at most once per prompt: a per-job outcome counter stops relaunches based on a stale view, a
  crashed worker leaves a failed record instead of looping as pending, and a job whose worker keeps dying is given up
  after 6 relaunches so its fallback runs.
- A worker ended by SIGTERM, SIGBREAK or Ctrl+C records a `killed` failure for the prompt it ran, so its fallback runs
  and the job is no longer relaunched without count (it read `pending` before); `ub stop`, superseded jobs and a
  worker the kit itself stops still leave nothing. A relaunch that stops a stale worker keeps the result that worker
  recorded meanwhile, and the new worker is not skipped as "already finished".
- The budget counts backend requests (retries included), not launches, and a launch starts only when its worst case
  fits the cap. New `ub budget RUN --max-calls N` raises the cap; a budget stop then goes on by itself, and
  `continue` and `ub list` no longer treat it as finished.
- Jobs that have not run are rebuilt when their inputs change (a new frame, a host switch, other privacy answers); a
  failed job re-seated to another family runs on its new seat. A family that fails authentication is not used until
  `continue`, `run --continue` or a BLOCKED retry detects it again (log in first).
- A reframe, redo or import moves the ideas of every gap round. A redo stops only the workers of the steps it redoes,
  and moves only the outputs of the steps this run takes (never those of a step it skips): the
  `redo <run> Q.3s --yes` that a failed quick screen's card suggests no longer leaves the run BLOCKED for good, and
  `redo Q.4` and a proposal-mode `redo P.2` no longer move the files of the finished earlier step (quick Q.3p's screen
  prompts, proposal P.1's idea as I-001). A redo that starts after the gap step (5.3c or later) keeps the gap-round
  counters and never counts a gap round twice, so deep mode no longer opens an extra gap round that writes over an
  earlier round's ideas, and its second gap round still opens when the re-curated pool needs it.
- `ub import` in quick mode curates the pool again from Q.3; it used to say so and do nothing. In proposal mode it is
  refused, because a proposal run has no idea pool. Its note now says whether the curation runs again or is still to
  come.
- A busy card never repeats free text in a command line (`answer --choice` is retried through a file), and it treats
  the typographic double quotes U+201C, U+201D and U+201E like `"` (PowerShell ends a double-quoted string there), so
  such an argument is never repeated either. `init --text "continue RUN"` refused by a busy run is retried as
  `continue RUN` instead of a false BLOCKED card.
- `ub run continue|status|stop` no longer start a run named after the word; `ub run quick` without a topic is a usage
  error. A command word (`stop`, `status`, `doctor`, `continue`) is a command only when nothing follows it or what
  follows names an existing run folder, tried as typed and with its whitespace collapsed, so a run path with two spaces
  in a row is found. Text after it that can only mean a run folder but names none (a mistyped run path or name) is
  BLOCKED "run folder not found" before anything is created: `ub run stop|status|continue <run>` no longer starts a new
  run named after the command line. Any other text is a topic: `ub run "stop smoking coach for nurses"` starts a run
  with that topic, and an agent kickoff whose rest is not a run folder
  (`/ultimate-brainstorm doctor appointment reminders ...`) no longer prints a doctor report or a misleading "run folder
  not found": the card asks you to put a mode word first (`standard doctor appointment reminders ...`), and nothing
  runs. `status <run name>` now finds the run under the run root. A `.cmd` shim family is no longer taken out by a
  metacharacter in a folder its calls never receive, and `continue --host` checks the `.cmd` shims of the family that
  keeps reading the repository (the run's host family after the switch), not those of the new agent's family.
- v1 runs detect their families when migrated; a kit 2.0.3 driver and this kit respect each other's lock, a 2.0.3 worker
  still running after an update is stopped by `ub stop`, and a 2.0.3 run continued under another host keeps its done
  host jobs. Alongside kit 2.0.3 drivers during an upgrade, this kit creates `.ub/lock.json` exclusively before it reads
  run.json, so a 2.0.3 driver cannot take the run in between. The record's 2.0.3 heartbeat is refreshed every 30 s while
  the run is driven, so a hard-killed driver's record expires for 2.0.3 after 120 s even when its pid is reused. A
  record written by this kit always carries `since`. During an upgrade, a kit 2.0.x `ub run` waiting at a gate keeps its
  run: its old heartbeat counts while the process that wrote it runs, the rule the installer uses (one implementation,
  `proc.legacy_driver_live`, shared by the engine and the installer, so on Linux and macOS a 2.0.x `ub run` that a
  forward clock step made look started after its last beat is recognized by its command line, ub.py on that run).
  Before, it was taken over after 120 s and then wrote its stale answer over this kit's work. A stale `.ub/lock.json`
  record that another program holds open is no longer driven past. A driver that stalled for more than 120 s while a
  2.0.3 driver took its record now stops without saving (BLOCKED "another session took over this run; this one stopped
  without saving").
- Gate answers are type-checked: unknown fields are refused with the list of valid ones, a comma list of idea IDs is
  accepted, and IDs are checked against the run. An answer file must hold a JSON object (the answer template) or a
  JSON string (the reply): `true`, a number or a list re-asks the gate instead of being read as free text. An idea ID
  named twice counts once (G6 needs two distinct finalists), and the G8b runner-up must be another idea than the
  chosen one.
- `ub init --text-file`: the skill now writes your words to `brainstorm/.kickoff.txt`, so no shell ever expands `$`,
  backticks or `$(...)` in them. `ub run "<topic>"`, as the docs show it, now starts a run (it was a usage error); its
  words still pass through your shell, so put a topic with `$`, backticks or quotes in a file: `ub run --text-file F`.
- A file named with `--seeds-file`, `--idea-file`, `import`, `--note-file`, `attach-s1 --doc` or `--raw` that cannot be
  read is now a usage error (exit 2), not an "internal error". A missing seeds file no longer leaves an empty run folder
  behind, and a bad `--raw` no longer leaves a half-done attach. The seeds file is copied as UTF-8 with LF.
- Your seeds file is no longer replaced at the kickoff. Seeds in the G0 reply (and, in proposal mode, the proposal idea)
  are added to a `--seeds-file` or to the file you wrote while G0 waited, and its Problem, ideas, Obvious and Off-limits
  stay. A file with only Obvious or Off-limits keeps them when the reply has no seeds, and a redo or a new G0 answer
  merges into your version again.
- `skip` at G1 keeps a seeds file's Problem, Obvious and Off-limits (the prompts quote the Off-limits) and puts the
  SKIPPED line above them; it used to replace the whole file.
- Fixed: the Start command failed in Windows PowerShell 5.1 when no optional skill was installed (`--components ""`
  reached ub.py as a missing value). The skill now writes `--components="<list>"`, and `--components` without a value
  means no components.
- Parked and killed ideas never survive a re-curation, a repeated `probe-result MISSED` no longer kills the
  runner-up, and `switch --idea` checks the ID and designs a new probe. A switch (`switch --idea`, G13 runner-up) and
  a K6 kill (`probe-result MISSED`) are kept in run.json `decision_log`, committed together with the redo they cause,
  and every rewrite of 08_DECISION.md shows them; in quick mode they no longer vanish when Q.8 writes the file again.
  An idea killed by its probe is no longer listed as 'not chosen at the decision'. A probe MISSED with no runner-up, or
  with only a runner-up its own probe killed, no longer leaves the killed idea as the decision: at G9 the run stops
  before the architecture, and a finished run renders its documents again. The DONE card names the kill and the
  finalists you can switch to, instead of asking you to run the same probe again. A switch never makes an idea its probe
  killed the runner-up.
- v1 run folders migrate only under the lock and keep their original as `00_RUN.v1.md`; `bs.py` names
  `ub continue` for them (`ub status` only reads a run). A poll that changes nothing writes nothing.
- Windows without long-path support: `ub init` shortens the run folder name until every file fits in 259 characters
  (or asks for a shorter `--root`), a redo checks every destination before it moves anything, and `ub doctor`
  reports the setting.
- A run or project folder whose path contains `[` (for example `client [2026]`) works: every glob over the run or
  project folder takes the folder literally (`textio.glob_in`). A redo moves its outputs, `continue` finds the run, the
  curator sees the pool, and the bs.py and lint scans, the privacy leak checks, progress, render and migrate see their
  files.
- A run is no longer started in a folder whose path holds a `$` before a name, a backtick or a double quote (also
  U+201C/D/E). Bash and PowerShell change these inside the double quotes of every card command, so every command reached
  another folder; use `--root` to start the run elsewhere. The same check applies to the kit's own folder. `continue` on
  a run already in such a folder is BLOCKED, with fixes to move the folder or to resume it in a terminal
  (`run --continue '<run>'`). `%`, `!` and `c$/` shares still work.
- `switch --idea` refuses an idea its own probe killed (K6) and names the finalists you can still switch to (or says
  none is left). Once the chosen idea's probe missed with no runner-up left, PROPOSAL.md, the one-pager, index.html and
  the architecture README read "KILLED (K6): the chosen idea's pre-registered probe missed; no runner-up is left"
  instead of APPROVED or DRAFT. 12_HANDOFF.md then ends with a warning not to build the idea instead of "Do not reopen
  the choice of idea or architecture.", and so does a seed written after the kill.
- The "another session is driving this run" card names a kit 2.0.x `ub run` that waits at a gate: "a kit 2.0.x session
  (pid P, host) is waiting for an answer in its terminal: answer it there, or close it (Ctrl+C), to continue here", and
  `ub stop` tells you to close that session there. A stale `.ub/lock.json` that another program holds open is named with
  that reason, and `ub stop` says the stop is not recorded yet: close that program and run stop again.
- A run that kit 2.0.3 started keeps its probe kills after the update. When it loads, the `Killed: <ID> - K6` and
  `Switched (...)` lines of its 08_DECISION.md become run.json `decision_log`, and its MISSED probe record names the
  killed idea. A dead 2.0.3 run then reads KILLED (K6), and its DONE card names the finalists left instead of asking you
  to run the probe again. `switch --idea`, a MISSED and G13 `runner-up` never take back an idea its probe killed, and
  reporting the same MISSED again writes no second K6 line or ledger row.
- A redo from 5.3c or 5.3m no longer counts a gap round a second time when kit 2.0.3 (or an earlier 2.1 build) already
  counted it, so deep mode's second gap round still opens after the update.
- A `--seeds-file` without the v1 sections is no longer replaced at the kickoff; this covers an idea list as `ub import`
  takes it, free text, and `#` or `###` headings. A heading named like a seed section becomes that section, other text
  goes under `## Ideas`, and its ideas reach the run. `skip` at G1 puts the SKIPPED line above such text instead of
  replacing it.
- After a K6 kill with no runner-up on a finished run, the handoff seed and the copies G14 published under `docs/<run>/`
  are rendered again too: the K6 warning, no 'Do not reopen ...', and KILLED instead of AUTOPILOT DRAFT. The DONE card
  shows the proposal as `(KILLED (K6))`.
- A run that kit 2.0.3 left dead (the chosen idea's probe MISSED with no runner-up left) gets its proposal, one-pager,
  architecture README, 12_HANDOFF.md, handoff seed and the copies G14 published under `docs/<run>/` rendered again once,
  on its next `continue` or the same MISSED again, with no paid call. Before, they still read AUTOPILOT DRAFT and 'Do
  not reopen ...'.
- `ub stop` on an empty or unparseable .ub/lock.json that another program holds open now says to close that program, not
  to stop a kit 2.0.3 session that does not exist. The busy card shows 'pid ?' for a record with no pid.
- Card commands always start with the kit that prints the card. Before, they used the runner run.json stored when the
  run started. After a plugin update, the old version's engine drove the run, or every command failed once its folder
  was removed. A run.json copied in with a repository could also put any command into the cards.
- A run.json that is valid JSON but not an object ([], null), or whose steps, gates, options or other objects,
  interrupt, supersede journal, families, seats, host or exec.wait_s hold a value of the wrong type, or an odd
  UB_HOME/runs.json entry, no longer stops `ub list`, a bare `continue`, `continue <run>` or `next` with an internal
  error: `continue` of that run is BLOCKED and names its run.json with a fix. An unreadable run.json is now named with
  its path and a fix.
- An unreadable run.json (cut off or empty) is now named with the JSON error of the file itself, e.g. `<run>/run.json is
  unreadable: the text starts with JSON that is not valid: Unterminated string ...`. Before, the card called your file
  "the output", wording meant for model output.

### Ranking and selection

- The tournament ranking is a Bradley-Terry fit on one share per pair, with seeded 90% intervals, the Condorcet winner
  and majority cycles. A pair with no neutral judge keeps both vendors' judges, and a missing verdict is never read as
  a loss. When no bias-free comparison connects the finalists, or every judge family is flagged, the ranking falls
  back to raw points and says why.
- A TIE in both orders counts as position-consistent; a fallback call counts as the family that answered it.
- Screen: every judge counts; a judge's preference for its own vendor's ideas is measured as a difference in
  differences against another judge on ideas neither vendor wrote (so a lenient judge is not flagged) and taken off its
  own-vendor scores when it is larger than its noise (1.5 standard errors of the per-idea differences; a smaller gap is
  shown in the Own-origin gap section, not corrected, so a small pool no longer lowers a judge for noise); two judges
  that cannot be told apart are reported, not guessed, and a judge pair counts as unattributable only while one of the
  two has no measured gap: a quick run with three or more families (and a standard screen whose third vendor wrote fewer
  than 3 ideas) no longer prints 'WARN: <a> and <b> together ... neither score is corrected' under two judges it
  measured and corrected. The G4 card shows the screen's own-origin FLAG and the WARN of a judge pair it cannot correct;
  it says a FLAGged judge's own-vendor scores were lowered only when the screen actually lowered them, and a gap within
  noise reads `not corrected: within noise`. The K3 floor also trips on a criterion every judge scored 1. Duplicate,
  unknown and out-of-range judge records are dropped with a warning.
- A G4 rescue now reaches the reality checks, the survivors and the finalists. Before, 04_SHORTLIST.md was rendered
  before the answer was recorded, so every rescue was silently dropped. The `Rescued:` line now lists IDs only, with
  each reason on its own line, so an idea named in a rescue reason (for example a K1 kill) no longer comes back.
- `bs.py status` reads the `Rescued:` line as the engine does: an ID in a reason an older kit wrote in parentheses there
  no longer asks for a check of an idea that was not rescued. The line is read in one pass; deeply nested parentheses
  took quadratic time.
- Tournament: a judge's one-order verdicts (a failed, missing or substituted call) are no evidence in the debiased
  ranking or the self-preference audit, and a seat's own -alt answering one of its calls keeps the seat's orders paired.
  An older result.json that does not score every card is ranked by raw points.
- A card headed `## I-001 - Title` or `## I-001: Title` (the NORMALIZER contract accepts both) is I-001's card
  everywhere. Step 9.3 rewrites tournament/cards.md as one `## <ID>` card per finalist. The tournament now ranks the
  finalists' ids, the self-preference correction and audit apply, and the red-team set, the G7/G8b standings and the
  card texts follow the tournament. Before, such ids matched no finalist and the ranking fell back to id order.
- Red-team files: a review's kept `.failed.md` and the rebuttals are no longer read as reviews. G8b and Appendix D list
  only the reviews' verdict lines, with the family still hidden at G8b. Each 10.3r rebuttal runs once on its seated
  family: no duplicate job ids with families like `gpt.md.failed`, and no CRITIC rebuttal on the ADVOCATE's family.
  SYNTHESIS no longer gets failure records as reviews.
- Finalists: evolved ideas inherit their parents' screen score and get up to 2 of the 8 places; the finalist cut
  counts the whole pool, not only the survivors, and screened survivors fill the places beyond the 2 evolved-idea slots
  before any further evolved idea. A redo of EVOLVE (8.1) replaces the E ideas' origins instead of keeping the first
  run's.
- Architecture matrix: per-judge centering, a `confounded` leader status, and EXCLUDED is reachable with two families.
  The default architecture choice passes over a leader that a judge vetoed and says why. With every candidate EXCLUDED
  by vetoes it is the best-scored candidate instead of simply A: G11 records why in the answer and in a run note, the
  card shows `no leader`, and the pre-mortem is written about that candidate. A criterion an other-family judge left out
  drops out of W for everyone; a leader or runner-up only its author family judged is `self-judged` (G11 asks, or notes
  it in full-auto); a judge that favours its own candidate keeps a lead it tilts from reading `clear`. Two families
  judging each other's candidates report their combined self-preference (matrix.json `own_candidate_pairs`; the
  per-judge gap showed only a third of it). When it is flagged, a lead over the other family's candidates is a close
  call, not `clear`. A criterion left out of W also makes the lead a close call. Every arch judge must score every
  criterion of every candidate (a nested cover; a left-out criterion earns the repair call). In quick mode with two
  families the one architecture judge is the host, which also wrote one of the two candidates: that lead is now
  `self-judged`, so guided quick runs ask at G11. The G11 card shows, per candidate, how many judges of other families
  scored it, and the matrix warnings.
- With four families in standard and proposal mode every family judges the candidate architectures it did not write
  (only the host judged before).
- Gap rounds run when the largest cluster holds more than 25% of the ideas or fewer than 80% of the axis cells are
  covered. Generator seats rotate by a seeded offset, so across runs every strategy meets every family. A one-family
  run without an alternate model seats one judge instead of the same model twice, and a kit 2.0.3 single-family run
  whose `<host>-alt` runs the same model keeps one screen and tournament judge (an older kit's judge list made only of
  the host and `<host>-alt` counts as one judge), also when it is updated while a screen or tournament judge step is in
  flight: that step's `<host>-alt` judge (its job, worker, output and prepared prompts) is dropped, so the same model is
  no longer counted as two judges. Origins compare vendors, so `claude` and `claude-alt` are one origin. A cross-host
  continue on which none of the old judge families is available seats the new host's model once as a screen and
  tournament judge, not two or three times (`<host>-alt` only once, and only when its alt_model is another model).
- Quick-mode curation no longer sees which model wrote which idea; `bs.py quick-pick` derives each idea's origin.
- Quick mode no longer lets the curating model pick the finalists from its own scores: both families that generated
  the ideas score the curated one-line versions blind (no source labels, each in its own order, the screen's
  origin-label check), and `bs.py quick-pick` takes the finalists from their scores with the screen's own-origin
  correction (`quick/screen.md` shows how). A one-family run keeps the curator's scores and says so. Quick mode makes
  16 model calls with three or more families: a third family, which generated nothing, joins the blind quick screen as
  a neutral judge, so each generator family's preference is measured and corrected without human ideas. Two families
  make 15 calls and one family 13 (13 before).
- New developer tool `tools/eval.py` evaluates finished run folders: yield per strategy and family, judge agreement,
  position consistency and self-preference.
- When vetoes exclude every architecture candidate, the architecture README and the proposal writers' evidence pack say
  `leader none (every candidate EXCLUDED)` instead of `leader None (close-call)`. The AUTO-DECISION line gives the rule
  that took the default candidate, and Alternatives considered lists each veto reason once.
- When every candidate is EXCLUDED, PROPOSAL.md Appendix C ends `Leader: none (every candidate EXCLUDED).` with rank
  `-`, as the architecture README does, instead of `Leader: None (close-call).`
- Quick mode: a curated id that is not shaped `Q-01` (for example `Q 01` or `Q-04b`) no longer stops the tournament at
  9.3 or silently drops a finalist from it. `bs.py prepare-tournament` reads the run's finalists' cards, as 9.3 wrote
  them.

### Privacy and untrusted content

- With privacy `code` off, repository code no longer reaches other vendors through checks, reviews, architecture files
  or proposal sections: in a software or growth run inside a git repository every value of another vendor's prompt is
  stripped of code, and the worker refuses (exit 7) a prompt for another vendor that still contains code.
- Code stripping handles unclosed and longer fences, tildes, indented blocks, fences in lists and quotes, `<pre>` and
  `<code>`, and inline code that reads as a statement; file paths and mermaid diagrams stay. It is linear on any input.
  An inline code span is read on one line: inline code that a line break splits over two lines stays (a known limit).
- Text that models or web pages wrote reaches later prompts only inside DATA blocks that its content cannot forge, and
  every prompt says such text is data, never instructions. This includes the ideas and cards the judges see, the
  landscape lines on the G3 card, the decision record (08_DECISION.md) in the probe and approach prompts, the
  architecture drivers' quality goals in the architecture judges' prompts, and the elements taken from other candidates
  with G11's `+ steal` in the architecture writer's prompt. The frame questions stay plain in the frame writer's prompt,
  next to your answers to them: together they are that step's task.
- `bs.py sources` cites model outputs only. The adapter's `*.meta.json` (an HTTP backend's endpoint URL), `*.failed.md`
  and `*.status.json` records no longer become S-### sources in PROPOSAL.md and other vendors' prompts. An entry an
  older kit took only from such a record is dropped, and its id is never reused.
- Jobs that read your repository no longer read the run folders: the kit writes `.gitignore` files there, Claude
  workers get tool rules that deny them, and the prompt says so. Another vendor's reality check is not asked for
  codebase fit, and check prompts forbid shell commands.
- A project that is a git worktree or submodule (its `.git` is a file) is read as a repository: your host vendor's
  checkers and researchers read it, and the run folders are hidden from them.
- A fallback of a repository-reading job (reality checks, grounding, architecture authors, writers) to another vendor
  with privacy `code` off is rebuilt for that vendor: it is no longer asked for codebase fit or told it may read the
  repository.
- An empty allowed-vendors list now allows no vendor everywhere.
- Code stripping also removes an indented line right under a sentence or a list item when that sentence or item ends
  with `:` (also inside bold or italics, as in `**The handler is:**` or `<strong>Install:</strong>`, or after a `<code>`
  element) or when the line reads as code (`=`, `;`, braces, a call, a code keyword or Dockerfile instruction, a
  trailing colon, `key: value`, `"key":`, `#include`, a decorator, `require`, `export default`, `$ `, a command option,
  bare names such as `API_KEY`), together with the indented lines right above it. In the kit's own prompt text, indented
  prose that no `:` introduces and lines that only cite a path or URL stay; text quoted from earlier steps (facts,
  checks, reviews, architecture files, proposal sections) no longer carries any line indented 4 or more columns to
  another vendor unless it is a list item or only cites a path or URL. This includes code at a nested list item's
  content column and signal-less lines such as a header or a plain `npm run` under a claim, as 2.0.3 did. `-x`,
  `**bold**` and `3.14` are no longer list items, and inline code such as `os.environ["X"]`, `SELECT ... FROM` and
  `import x` is removed. A fallback prompt stays code-free after the A2 filter, and a same-vendor fallback of a
  repository job keeps the repository.
- An inline code span or a `<code>` element on an indented continuation line, or a heading that holds a `<code>`
  element, no longer makes the worker refuse an engine-filtered prompt for another vendor (exit 7, 'contains code'), and
  scanning a long indented line for code takes linear time again. Nor does a multi-line audience in the frame make it
  refuse a reality-check prompt: the audience now sits on its own line in the check and tournament prompts, and the
  engine strips every filtered prompt once more as a whole.
- Domain terms from your repository's CONTEXT.md no longer reach other vendors. Before, they got through when their
  definition merely contained the word 'proposed' or when they were written as numbered items, `+` items or table rows.
  Only terms with the `[proposed]` source mark are sent.
- The kickoff card and `ub doctor` list the user instructions that still reach worker calls (the Codex AGENTS.md, a
  CLAUDE.md above UB_HOME/tmp, inherited Claude settings, Codex MCP servers that cannot be switched off).
- The judges' origin-label check refuses only this run's own alias IDs (the quick generators' `QA-` and `QB-` IDs among
  them) and origin labels such as `Origin: gpt`, never your own topic. It no longer blocks a run on ordinary words
  (`rotas generated by a solver`, `Deployment strategy: blue-green`, `CORS origin:`) or on alias-shaped tokens
  (`an L4-7 load balancer`, `H-2 visa`). The card names the file that holds the match and the step to redo.
- The grounding prompt asks for each domain term on its own line, as `- **Term** [proposed]: definition` or `- **Term**
  [CONTEXT.md]: definition`, the shape the A2 filter reads. Terms grouped under a source heading, or a FRAME term marked
  another way, no longer lose every approved term for other vendors, and a definition wrapped onto a second line no
  longer sends part of a CONTEXT.md term.
- A project that is a git worktree or submodule also counts as a repository when `ub init` infers the variant (software)
  and when the host vendor's `.cmd` shims are checked against the paths its jobs get.
- A judge prompt refused by the origin-label check gets a BLOCKED card whose fix is the redo of the step that prepares
  the prompt (`redo <run> 6.1|Q.3p|9.3 --yes`). Before, the fix was a `next`, which never prepares the prompt again.
- The judges' origin-label check now refuses only the kit's own label syntax: a label word followed by `:` or `=`, or
  written inside parentheses as in `(written by human)`. An origin name or alias prefix counts only as the whole value,
  and only the prefixes of this run's own alias IDs count. Ordinary idea and architecture wording no longer blocks the
  screen, tournament or architecture judges: `Storage strategy: S3 buckets`, `Escalation strategy: human agents`,
  `written by human volunteers`, `the origin S3 bucket`. A label wrapped in markdown (`**Origin:** gpt`, `Origin:
  `gpt``) is refused again.
- An imported idea list whose heading starts with an ordinary term such as `GPT-4`, `COVID-19` or `K-12` no longer
  blocks the judge steps. Only IDs with the kit's alias prefixes, or a team seed file's `H<name>`, count as alias IDs.
- A CONTEXT.md term no longer sends its definition to other vendors when the definition wraps onto an unindented line or
  sits under a heading that names CONTEXT.md. A bold-led term or table row nested under a `[proposed]` term is sent only
  when it carries its own `[proposed]` mark.
- A local model backend (`http://localhost`, `127.0.0.1` or `[::1]`, the documented `local` family) is always called
  directly. Behind `HTTP_PROXY`, or a Windows system proxy whose `<local>` bypass misses `127.0.0.1`, its key and the
  whole prompt went to the proxy in clear text and the local server was never reached. Any other endpoint still honors
  the proxy settings.
- A CONTEXT.md term written under a heading no longer reaches other vendors when its source line (`Source: CONTEXT.md`)
  or its definition sits below the heading, also after a `**Definition**` line or a blank line. A heading inside the
  domain terms now counts as a term: other vendors get it, with its body, only when the heading line itself carries the
  `[proposed]` mark.
- The judges' origin-label check runs in linear time again. A label word followed by thousands of markdown marks, such
  as a fill-in blank `Strategy: ____` in a curated idea, cost seconds per judge job (quadratic in the run's length).
- G0 kickoff keeps privacy requests: `private mode` and `keep it private` start a private run, and `web: no`, `vendors:
  none` and `code: off` turn those off. A privacy-like seed line (`no web search`, `no vendors please`) or an unclear
  value (`web: maybe`) is asked again instead of starting the run with web search and all vendors on.
- Domain terms from your repository's CONTEXT.md no longer reach other vendors through the proposal's glossary. The
  proposal rubric, red-team, one-pager and fix prompts quote PROPOSAL.md, and its Appendix E copied the grounding step's
  domain terms unfiltered. Other vendors now get only the `[proposed]` terms there (plus the frame's own domain
  language), also in a fallback copy of a prompt written for your host's vendor. In a proposal assembled by an older
  kit, the whole Appendix E is filtered for them: only its `[proposed]` terms stay. In PROPOSAL.md, the grounding step's
  terms now sit under `### Domain terms (today's system)` in Appendix E.
- G0 kickoff: a privacy request in any wording ('no web-search', 'web off', 'no internet', 'only use Claude', "don't
  send my idea to other companies", 'offline, go', 'go, keep everything local') is asked again. Before, the run started
  with web search and every vendor on and sent the request to the vendors as a seed idea. 'keep it private' and 'web:
  off' / 'vendors: off' still apply directly, and a list item stays a seed.
- G0 kickoff: privacy wishes in other words (`turn off web`, `no other LLMs`, `just claude please`), mode words in a
  sentence, `no go`, deferrals (`give me a sec`) and lines ending with `:` ask; `Kindly change the mode to deep` and
  `go, deep` read the setting, confirmation and no-ideas sentences start with no seed, `web:` / `vendors:` values end at
  a bracket or ` # `, and list items stay seeds.
- A fallback copy of a repository check whose step no longer yields it (the shortlist changed after the check was
  seated) no longer tells another vendor that it may read the repository or requires `## 5. Codebase fit`: the copy
  drops that line and that section, as a rebuilt job does.
- Full-auto privacy defaults also remember the vendors the kickoff card listed as seeing your idea text (`vendor_set`):
  a later full-auto run with a family from a vendor outside that list asks the kickoff question again and saves the new
  list, so consent never widens silently. Defaults saved by 2.0.x are asked once more; `private`, privacy typed with the
  topic and a saved `vendors: no` are never asked again for a vendor.
- `web: no`, `vendors: no` and `code: no` typed before the topic or at the end of a line (`full-auto web: no, vendors:
  no payroll tool`, `payroll tool for HR, vendors: none`) apply to that run over the saved full-auto defaults and no
  longer end up in the topic. `none`, `never`, fullwidth letters and a hidden zero-width character read as they do in a
  gate reply, and a `no` stands over a `yes` for the same key. A typed `yes` is still the kickoff card's to give, and a
  pair inside the topic or idea (`a code: yes/no review bot`, `Platforms - web: no, kiosk: yes.`) stays there. A `no`
  the kickoff cannot tell is a setting (`(vendors: no)`, `vendors: no (client NDA)`, `vendors: no and web: no`, quoted,
  marked up, with `=` or an emoji: `"vendors": "no"`, `**vendors:** no`, `vendors=no`, `web search: no`) or a sentence
  that puts `no`, `not`, `without`, `never`, `don't`, `avoid`, `skip` or `only` within three words of `vendors`, `web
  search` or a vendor or model name (`no vendors please`, `without web search`, `vendors - no`, `don't send anything to
  OpenAI`, `only Claude`) makes the kickoff card ask, even in full-auto, and says how to apply it, and `ub run` with no
  input stops at that card instead of taking the saved yes; so does a terminal G0 that shows again after a typed reply
  it could not apply (`no vendors please`) when the input then ends. Other wordings (`No web.`, `web off`, `vendors:
  not allowed`, `Keep it confidential.`) are not read: type `web: no`, `vendors: no`, `code: no` or `private`. Before,
  the pairs became part of the topic and the run used the saved defaults, so your idea text went to every vendor. A pair
  taken as a setting leaves no comma in the topic, also at the end of the line before it or after a Chinese or Arabic
  comma; `forbidden`, `disallowed`, `prohibited`, `refused` and `rejected` count as no in a pair.
- `ub config set privacy_defaults.vendors no` (the word the kickoff card uses) stores the word `no`, which a run read as
  yes: full-auto runs then started with web search, every vendor and code sharing on. A saved value that is not `true`
  or `false` is now no saved answer, and the kickoff card asks.
- `ub continue RUN --host X` and a terminal continue (`ub run --continue RUN`) never seat a family of a vendor your
  kickoff answer did not list, other than the vendor of the agent you move the run to (it reads the run anyway; with
  `vendors: no` it takes every seat). Before, the re-detection on the new host widened the allowed vendors and could
  give the lost seats, or the terminal's host role, to another vendor's family without asking. With vendors on, a
  listed vendor the new host lacks stays allowed for a switch back, and the vendor your kickoff listed is never
  marked "not listed" after a move. A run moved to another vendor's agent and back is hosted by a listed vendor's
  family again (before, it stayed on the other vendor's family), and its host family is no longer shown as off after a
  move there and back again. A host of no known family (`--host other`) takes no vendor exemption, like a terminal, and
  a kickoff answered again (`ub redo`) lists its vendors anew at the next move. The fix command of a terminal run that
  stops for want of input is written with forward slashes.

### Workers and backends

- A call ends when the CLI exits; whatever is left of its process tree is killed (Windows Job Object, POSIX process
  group; a group is signaled only when the target leads it, and a stop that lands while a CLI starts kills it). Codex
  and Kimi output is read line by line as it arrives (a 256 MB flood cap, no buffering), Claude's one JSON answer is
  capped at 12 MB (`max_stdout_mb` overrides either); past a cap the job ends invalid at once. stderr keeps a 64 KB
  tail. Markers record each process's identity (a time-zone independent start time), so `ub stop` and relaunches
  never kill a reused process ID. On macOS and BSD a killed child that its parent has not reaped (a zombie) counts as
  gone, as on Linux; it used to make `ub stop` wait out its whole grace period.
- Codex workers: shell, MCP servers (each disabled by name; the ineffective `mcp_servers={}` override is gone),
  connectors, plugins, sub-agents, hooks, memories, notify and web search are switched off where the job does not need
  them, and every JSONL item is checked against an allowlist: anything outside the job's tools, or unknown, is refused
  (exit 7; `allow_items` admits a harmless new item type). Codex needs 0.100.0 or newer. `--output-schema` gets the
  schema without its min/max bounds; the output is still checked against them. Endless reconnects are switched off too
  (`features.unbounded_connection_retries`): from Codex 0.158 an unreachable endpoint no longer holds each attempt until
  its timeout, so the chain can fall back. Without Python 3.11+ (or for a config.toml that tomllib rejects) the kit
  reads the TOML structure itself, so MCP servers defined as inline tables or dotted keys are switched off too and a
  table header inside a multi-line string is never taken for a server; when part of config.toml cannot be read, no
  server is switched off by name and `family.py detect` names the line. A config.toml that nests arrays or inline tables
  about 1000 levels deep no longer crashes detection (`ub init`, a re-detection, `family.py detect`): a statement nested
  more than 128 levels deep is reported as unread. Without Python 3.11+, a `\UXXXXXXXX` escape in a quoted MCP server
  name is decoded, so that server is switched off too.
- Claude workers skip your own Claude settings, hooks and plugins (`user_context: auto`), and your login and network
  route (`env`, `apiKeyHelper`) are carried into each call's own 0600 settings file; provider backends honor the
  alternate seat's model. `family.py detect` names what still reaches workers, for example a `CLAUDE.md` above the kit
  home or your `~/.codex/AGENTS.md`. A repository that is itself the runs folder is never denied to Claude workers. A
  settings.json whose `env` is not an object is no longer carried (it made every native Claude call fail before the
  CLI started).
- Kimi Code is used as the kimi family only while the model the kit calls is served by a Kimi endpoint. If Kimi Code's
  `config.toml` points that model (its default, or the configured `model`, `fast_model` or `alt_model`) at Z.ai, OpenAI,
  Anthropic or any other host, kimi-cli is unavailable: `family.py detect` says `Kimi Code is configured for ...`. The
  endpoint is read as Kimi Code reads it. A provider without `base_url` counts as the `*_BASE_URL` key of its
  `[providers.<p>.env]` table (`KIMI_BASE_URL`, `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`), else as its `type`'s own
  endpoint (`anthropic`, `openai`, `google-genai`, ...), so Kimi Code's own documented Anthropic setup is caught too; a
  type the kit does not know is not checked. With `env_model` on, `KIMI_MODEL_NAME` without `KIMI_MODEL_BASE_URL` counts
  as the endpoint of `KIMI_MODEL_PROVIDER_TYPE` (default `kimi`). A worker checks the call's model again before Kimi
  Code starts. A config switched during a run no longer sends a job to a vendor the run does not allow, or sends GLM
  Coding Plan traffic through Kimi Code. The note for a missing Kimi Codex home now names `install.py setup-kimi
  --codex` (it named `setup-glm`).
- Retries use a jittered back-off and honor Retry-After, every job has a deadline of twice its timeout, and
  `defaults.retries: 0` is honored. No attempt (retry, next backend or repair call) starts with less than min(30 s, a
  quarter of the timeout) left before the job deadline, a retry whose back-off would leave less moves to the next
  backend at once, and an attempt the deadline cut short that times out reports the earlier failure instead of ending
  the job timeout. HTTP backends detect truncated and refused answers and read bounded bodies.
- Windows: an HTTP backend whose `key_env` is written in another letter case than the variable now finds its key.
  Detection used to seat it, and then every call failed with '<key_env> is not set'.
- Errors are classified from error channels only, never from model output. New error class `config`: a `.cmd` shim
  that cannot receive a kit path, or a native CLI that now serves another family. Redaction also covers JWTs,
  query-string keys, Basic and URL credentials, PEM keys, prefixed secret names, YAML and header lines, and GitHub,
  GitLab, AWS, Slack, Google and Hugging Face token formats, in linear time.
- Every `logs/calls.jsonl` row records the backend requests it sent. Kimi transcript samples stay in the run folder
  and are never kept for jobs that read your repository (only their first megabyte). Workers delete the secret files of
  launchers that died, judged by the launcher's recorded process identity (its `.id` file) like the launcher itself,
  so a clock step can no longer delete a running session's settings file, and the `.id` file goes with its secret
  file. On macOS a reused process ID with another `ps` start time no longer keeps a dead launcher's secret file.
- The host output of a sub-agent is flushed to disk before the kit records it as done.
- A host sub-agent's JSON output is stored in the same canonical form as a worker's (the engine's ids), and its ledger
  row counts no backend request.
- Windows: a provider's `token_env` written in another letter case than the variable (for example `zai_api_key` for
  ZAI_API_KEY) now finds the token in the claude-cli@glm, @kimi and @kimi-code workers and in the `claude-glm`,
  `claude-kimi`, `codex-glm` and `codex-kimi` launchers. Detection seated such a backend, then every call failed with
  '<token_env> is not set', and the launchers said 'Set <token_env> first'.
- A `claude-cli@<provider>` backend whose provider has no `http(s)://` base URL (a families.json override that sets
  `base_url`, or the provider's `env` `ANTHROPIC_BASE_URL`, to null, empty, blank or anything else) is now unavailable
  (`provider <p> has no base_url in families config`), and a worker on such a chain returns unavailable before it writes
  any settings file. Before, Claude Code started with the provider's token and no usable `ANTHROPIC_BASE_URL`, so the
  token went to Anthropic's endpoint. The launchers already refused an empty URL and now refuse a blank one too. A
  provider entry of the wrong shape (for example `base_url` a list, or `models` or `env` not an object) leaves only that
  provider's backends unavailable, with a note naming the key; `family.py detect`, `ub doctor` and `ub init` run as
  usual. A worker whose chain was chosen before the edit refuses that provider the same way (status unavailable, no
  CLI started) instead of failing with an internal error.

### Validation and parsing

- Every parser of model output is linear: one fence scanner and one heading scanner, shared by the validator, the lints
  and the renderer. Degenerate outputs no longer take seconds to hours. A bare [ASSUMPTION] tag reads at most 2000
  characters on each side, and an `[ASSUMPTION: ...]` or `[ESTIMATE: ...]` tag at most 2000 characters of text (blanks
  around the text, a no-break space too, do not count). So `bs.py assumptions` and lint P8 stay linear on a line full of
  tags, closed or not. Before, 8000 bare tags on one line took about 13 s and 16000 about a minute; 20000 unclosed
  `[ASSUMPTION: ` tags took about 30 s.
- JSON extraction never returns a fragment of an output that starts with a malformed JSON document; a cut-off document
  after other text can still yield an inner object, which the contract's schema then refuses. NaN and Infinity are
  rejected. Judge covers are exact (no repeated or unknown IDs; IDs that differ only by invisible characters are mapped
  to the engine's IDs), and 1-5 scores are bounded in the schemas.
- CURATOR and QUICK-CURATE outputs that list an idea key or id twice, or leave a key, title, pitch, mechanism, cluster
  or the aliases empty, now fail their contracts (new json contract options `unique` and `nonempty`) and earn the repair
  call. Before, they blocked `bs.py map`, quick-pick or Q.3p later with no fix.
- FILE-protocol writes are all or nothing, also across a crash. A `.json` file must be strict JSON that matches its
  register schema; a marker line inside a file, a path printed twice (the last copy won before), paths that differ
  only in letter case and paths with invisible characters are rejected; writers refuse to write without allowed globs.
- Step 12.12 never deletes ADR files because `decisions.json` is malformed. ADR slugs are capped at 40 characters, and
  a Windows path that is too long says so (only a length error is relabeled; access denied or a full disk keep their
  own message).
- An `=== END FILE ===` line anywhere outside a FILE block makes the output invalid; a failed FILE-protocol commit stays
  undone even when another process recovers the folder at that moment, and a commit that fails and is interrupted
  while it cleans up is undone by the next write (its journal is marked aborted once every file is back), never
  finished with only some of its files. ARCH-FIX and PROPOSAL-FIX may write exactly the files they fix, and keep the
  per-file headings and diagram types of the steps that wrote the files; a stray file path in their output earns a
  repair.
- Lint A4: a STACK-VERIFY version such as `latest (managed service)` renders in chosen/stack.md as UNVERIFIED (a WARN)
  instead of an A4 FAIL that no ARCH-FIX pass could clear. The renderer and the lint share one unpinned-version rule.
  Lints A2/P2 no longer take a lowercase generic type argument (`list<string>`, `Promise<void>`, `Vec<u8>`) for a
  `<...>` placeholder. The approach build type's placeholder check now uses the lint's rule, so inline code and `<br>`
  pass there too.
- `bs.py assumptions` reads the Owner: / Decide by: fields of proposal section 13 in linear time (a 40,000-space run on
  one line took 20-35 s). Its section 13 questions and owners no longer keep a field's `)`, `|` or `;` or a trailing `,`
  or `-` (`Which database do we pick?)`, `Is HIPAA in scope? ||`, `CFO,`), and they are deduplicated against the STATUS
  trailers' questions, so G13 counts each once.
- `bs.py sources` reads each line, JSON string and JSON object once, so a run of `[` before a URL (80,000 took 10 s)
  and thousands of URLs on one line or in one JSON string (8,000 took 6 s) stay linear. A source's title is its line
  without its URLs, so it no longer quotes the line's other URLs, and a date inside a URL is no longer taken as another
  source's access date.
- The engine reads a section of a model file by the contract's own heading and fence rule. A `# comment` in a fenced
  shell block or a quoted `## 2.` heading no longer cuts short or replaces what the decision card, the probe's kill
  assumptions, the closing card and quick mode's Milestone 0 show; `bs.py status` reads the seeds file the same way,
  and the red team's kill assumptions ignore fenced examples. The deep merge of the second family's LANDSCAPE (3.2), the
  seed-leak check and the v1 migration's seeds proof read `## ` sections the same way: a fenced `## C` line no longer
  cuts the merged LANDSCAPE short or leaves an unclosed fence in 02_CONTEXT.md, and a fenced `## Ideas` line no longer
  counts as seeds.
- Free-text gate replies are parsed in linear time: a G2 reply with a long run of blank lines (40,000 took 10 s), G8b
  or G14 replies with long whitespace runs, and a G1 or G5 reply with a long run of line breaks, spaces or tabs. A G2
  answer (`1: ...`) is the rest of its own line, so a number with nothing after it no longer takes the next line as its
  answer, and an answer after a no-break, narrow no-break or ideographic space (a pasted or IME-typed `1.　...`) is
  still read.
- G11: `go with C`, `yes, B` and `ok B + steal ...` now choose the letter they name instead of the suggestion, and a
  reply that starts with the article `a` is no longer read as candidate A. A `choice` the host wrote wins over an
  acceptance only the reply parser read. An answer that names another candidate and also accepts the suggestion is asked
  again.
- G12: `accept` and `reject` name ADRs by the numbers the card shows (3, "3", "ADR-0003", "0003-slug"). Before, an
  answer file with the card's numbers was silently ignored, and G13 approve then accepted the ADR the user had rejected.
  An unknown ADR, or one both accepted and rejected, is asked again, and a status an older kit stored under such a key
  survives the sign-off.
- Variant inference matches whole words only and needs a phrase for words that are common in app topics. 'A study
  planner app', 'brand-new', 'ad-free', 'user story mapping tool' and 'state of the art' no longer choose research,
  marketing or creative, which skip the architecture stage. 'Tool' and plurals such as 'apps' count as product. The
  kickoff card now marks an inferred variant: "(inferred; start your reply with another variant to change it)".
- A G0 reply line such as `Go!`, `Yes please.`, `go ahead`, `Sounds good, let's go!` or `Standard, guided.` is now read
  as the confirmation or the keywords it holds: each word is read without the punctuation around it, and common
  confirmation phrases count as `go`. Before, such a line became a seed idea, which 0.3 now adds to your seeds file.
- A job file, a `.meta.json` or a `logs/calls.jsonl` line that holds JSON but no object (a list, a number, `null`), a
  job id that is not a string or a call kind that is not a string is skipped by the progress block; it stopped `ub
  status` and every card of the run with an internal error. NaN, infinite and negative durations no longer skew the time
  estimate.
- A curation that lists an idea key or id twice or leaves a field empty (an older kit's, or one its contract missed) now
  blocks `bs.py map` (5.2, 5.3m, 5.4m), quick-pick (Q.4) and the quick screen (Q.3p) with the fix that redoes that
  curation (`redo <run> 5.1|5.3c|5.4c|Q.3 --yes`), instead of `doctor --json` or no fix.
- A software or growth run whose project folder is not a git repository no longer asks its checkers for section 5
  (Codebase fit, cite file:line): no job there reads any code, so a checker could only invent the citations.
- A step whose fanout lists the same item twice is BLOCKED ("step S builds job J more than once") before any job file is
  written. Before, one item silently overwrote the other's job.
- Every free-text gate reply is now read by one reader. It reads clauses, and a clause with a negation refuses what it
  names. The same confirmation words count at every gate (`yeah`, `yep`, `LGTM`, `Confirmed.`, `Correct.`, `Proceed.`,
  `sure thing`, `Let's start`, `OK — go ahead`). An unclear or contradictory reply is asked again with the reason. It is
  never taken as a paid redo, a publish, a kill, a PASSED probe, a raised budget or an architecture choice.
- G0: `yeah`, `Proceed.`, `go…`, `Go ahead` with an emoji and `Looks good - thanks!` confirm instead of becoming seed
  ideas, and `OK, go ahead with standard please` keeps the mode. G2c/G10: these confirmations, `Yes.`, `ok!` and `Looks
  good, thanks!` are no longer taken as corrections and added to the frame or the drivers (at G10, a paid drivers redo),
  and a bare `no` is asked again.
- G11: a letter named in a negation (`avoid A`, `reject A, take the next best`, `I don't want C`) or next to an
  acceptance (`Yes, go ahead. C seemed overkill`) is no longer taken as the choice. `yes please`, `ok thanks` and
  `accept the recommendation` take the suggestion again.
- G12: `accept all, reject 3`, `ok, reject 3`, `accept all except 3` and `approve all but ADR 3` reject ADR 3. Before,
  the reject clause was dropped and G13 approve accepted the ADR. A number no verb places (`3 looks wrong`) is asked
  again.
- G9 / GB / GX: `3 of 10 passed, so the probe missed` is asked again instead of being recorded PASSED (which skipped
  K6). `stop at 120` is asked again instead of raising the cap. `don't continue, stop` stops.
- G14: `do not publish`, `Don’t publish`, `never publish` and `publish nothing` publish nothing. Before, they copied the
  architecture, ADRs and proposal into the project's `docs/`. A reply that publishes and refuses is asked again.
- G4/G5: each verb governs its own IDs. `keep I-003, kill I-007` kills only I-007, `don't kill I-003` keeps it, and
  `confirm I-004, clear I-005` clears I-005.
- G13: `Yes.`, `ok.` and `Looks good, thanks` approve instead of starting a paid change round. `switch to a simpler
  architecture` and a switch to the current architecture are asked again. The card now shows what `switch` and
  `runner-up` would redo, and about how many requests each costs, before anything is redone.
- A reply that refuses in its next clause is refused: `B? no.` at G11, `Publish? No.` and `publish? not yet` at G14,
  `Passed? Not really, 3 of 10` at G9, `raise to 300? no.` at GB, `kill I-003? no.` at G5 and `reject 3? no` at G12 are
  asked again or refuse the action. Before, each took the action it answered no to.
- Deferring or calling off counts as a refusal (`stop`, `wait`, `hold off`, `later`, `cancel`, `not yet`): `cancel
  publishing`, `Hold off on publishing` and `publishing can wait` publish nothing. At G10, G13 and the v1-run offer,
  `stop` and `not yet` are asked again or stop the run. A paid, irreversible or budget action is taken only from a
  clause that names it with no refusal.
- G13: `approve it`, `I approve`, `Approve as is`, `approve all` and `Approved as is.` approve. `stop`, `not yet`,
  `don't approve` and praise alone (`Great work`) are asked again. None of these starts a paid PROPOSAL-FIX change round
  any more. G2c/G10: `Yes, that's correct`, `I agree`, `Spot on`, `ok as is` and `Exactly` confirm instead of starting a
  paid drivers redo.
- G9 reads a miss in other words as `missed` (`that failed the bar`, `fell short: 4/10`, `did not pass the bar`, `below
  the pass bar`), and `pass` alone names no result (`pass rate: 3 of 10`). Two results or a refused echo (`passed with 3
  of 10, which is a miss`, `passed, missed`, `Passed? Well, no.`) are asked again, never PASSED. A keyword with a note
  (`missed: we did not reach 10 sign-ups`, `stop: this is not worth it`) is read as said.
- G4/G5: `I don't want to kill I-003` and `no need to kill I-003` keep the idea, `I-003: kill, I-007: keep` kills only
  I-003, and `I-004: confirm, I-005: clear` confirms only I-004. G12: a number the next clause speaks against (`accept 1
  2, 3 is wrong`, `reject 3, 2 is fine`) is asked again instead of carried.
- A reply with no word at all (`?`, `...`, an emoji) is asked again at every gate. Before, G11 took the suggested
  architecture. G1 `not yet` and `skip? no, I'm still writing` are asked again instead of being read as done or skip.
- G0: a refusal at the kickoff (`no`, `stop`, `not now`) is no longer a seed idea; the kickoff asks what to change. At
  the v1-run offer, `No, stop.`, `please stop` and `No, don't extend it` stop the run, and a reply that is neither `go`
  nor a refusal is asked again. Before, all of them extended the run into the paid architecture and proposal stages.
- GB: a number too long to be a cap (more than 9 digits) is asked again instead of an internal-error BLOCKED card. The
  G11 reader is linear again in one-letter words (`a ` x 20000 took 9 s).
- G0 kickoff: hedges, deferrals, questions and refusals (`not yet, let me think`, `Hmm, not sure`, `I don't know`, `Can
  you explain the modes?`, `no, make it deep`) are asked again instead of becoming seed ideas, and a mode request in a
  sentence (`use deep mode`, `make it deep`) changes the mode. A list item is still a seed.
- The v1-run offer asks again on a hedge or a question (`hmm not sure`, `I don't understand`, `Not sure what extend
  means`) instead of stopping the run for good.
- An echoed question answered by any refusal (`Passed? Not today.`, `Publish? Nope.`), and a refusal after an
  interjection (`Publish? Hmm, no.`, `Sadly, no`), refuses the action at every gate. Before, only a closed list of bare
  replies did.
- Every apostrophe form negates (U+00B4, backtick, U+2032, U+FF07): `don´t publish` publishes nothing and `don´t kill
  I-003` keeps the idea.
- G13/G10/G2c: a change request (`Please fix the proposal`, `Please fix the drivers`) starts a change round instead of
  approving. Sign-offs and confirmations (`sign off`, `No notes`, `ok, continue`) approve. A mixed reply (`approve and
  publish`, `Quality goals are fine`) is asked again.
- G4/G5: each ID takes the verb that names it (`kill I-003, not I-007` kills only I-003, `rescue I-004 and I-005`
  rescues both, `kill both` and `kill i-003` work), and `rather` and `instead` are no longer negations. At G4, an ID
  with no verb or a verb outside the G4 set (`kill I-004`) is asked again.
- A deferral word counts only where it governs the action: `wait list`, `pause button`, `cancel flow` and `can hold more
  traffic` no longer park a kept idea, drop a rescue or re-ask with a wrong reason.
- G2f: `put it back`, `revert it`, `undo the change` and `restore instead` restore the framing. An empty reply, `yes`,
  two keywords or a refused keep are asked again instead of silently keeping the edit.
- G14: `publish all but the proposal` publishes everything except the proposal, and a bare `yes` or `go ahead` is asked
  again.
- G1 `almost done` and a relative GB raise (`raise by 100`) are asked again, and G12 ranges (`reject 2-3`) cover every
  ADR in the range.
- 2.2 checks a host-written criteria.json against the criteria schema. A value that is not a number is dropped and a
  negative weight counts as 0, each with a note, and the weights are then normalized to 100. The judges never score a
  key `bs.py screen` cannot read (before, it exited 5 after the paid screen calls).
- Variant inference: features, APIs, bugs and conversions count after any word that means changing this repo or product
  ('add social features', 'improve search features', 'fix checkout conversions', 'our APIs'). A research, marketing,
  naming or creative phrase inside a product topic leaves it a product only when the phrase names what the product
  handles ('an app that suggests songs for workouts', 'a thesis writing app', 'a brand monitoring SaaS'). A product the
  work is about keeps the approach variant, as in 2.0.3, also when the subject product has its own modifier ('our SaaS
  product needs a go-to-market campaign', 'our app for nurses needs a marketing campaign', 'my startup in Dubai needs a
  brand', 'naming our new budgeting app', 'a research paper comparing note-taking apps'). So 'a habit tracker app with
  social features' and 'a tool that tracks e-commerce conversions' no longer pick software or growth. A verb in a
  `whose`, `because`, `since`, `while`, `when` or `if` clause belongs to that clause ('a booking app for salons whose
  owners have no marketing skills' stays a product), and the plurals `names for` and `brands` count ('names for my pet
  grooming business' is naming).
- `bs.py assumptions`: a parenthesized Owner or Decide-by value such as `Owner: Alice (CTO)` or `Decide by: M1 (before
  pilot)` stays whole, and `[Owner: ...]`, dash separators and a trailing `.` or `*` leave no stray characters in the
  question. So open-questions.md no longer lists such a question twice next to the STATUS trailer's copy.
- Gate replies: an unanswered question, a hedge, a condition, a self-correction or a deferral ('later', 'wait', 'hold
  on') next to an action word is asked again instead of taking the action. This covers PASSED/MISSED, stop, cap raise,
  restore, publish, switch, runner-up, kill, rescue, ADR reject and the v1 extend. A deferral at the v1-run offer no
  longer stops the run.
- Negation has a scope: 'kill I-003, not I-007', 'B not A', 'restore not keep' and 'publish arch, not proposal' act on
  the named item, and 'stop? no continue' continues. A polite request after a question ('Switch to B? Please.', 'Can you
  publish the architecture? Thanks', 'Restore? Please do.') is a request, not a refusal. Texting forms (k, ya, pls,
  thats right) confirm.
- G2c, G10 and G13 start a correction, a drivers redo or a paid change round only when the reply asks for an edit (an
  edit verb or quoted text). Confirmations with notes, typos, one-word unknowns, questions, hedges and deferrals are
  asked again, and so is a refused or unanswered switch next to other content ('Switch to B? Costs matter more').
- G4/G5: the verb reaches past a word ('kill idea I-003', 'drop I-003', 'clear the flag on I-004', 'kill it' when one ID
  is named) and carries through a list ('kill I-003, I-007 too'). A reply that places no candidate, one verb for two IDs
  in one piece, and 'kill' at G4 are asked again instead of closing the gate with the default.
- G0 reads 'full auto', 'hands on', 'deep pls', 'no seeds, go' and chat lines ('Looks good to me - go ahead, thanks!')
  as settings or confirmations, not seed ideas. A mode or autopilot said inside a sentence is asked again.
- G9 reads miss phrases ('fell short', 'not even close') and notes after a verdict ('passed, churn below 5%'), and asks
  again on 'passed but only 3 of 10' and on a MISSED that refuses the kill. G11: one chosen letter next to refused ones
  wins ('no A, take B'). G12 reads 'accept everything', 'accept 1,2 reject 3' and a reason after 'reject 1:', and asks
  again on an exclusion in words ('except the SMS one'). G1 reads 'done' with a past duration. GX reads 'keep going' and
  a STOP someone else said.
- A field the host filled in the answer (G5 kill, G13 action, G14 publish/handoff, the v1-run confirm) wins over the
  reply text. GB's relative-raise pattern is linear on a long run of digits.
- Gate replies: the closed world at every acting gate, in one place (`gates._uncovered`): a word the reader does not
  know next to what the gate acts on asks again instead of acting. Notes are free where marked (brackets, ` # ` / ` // `
  comments, quoted card lines, greetings and sign-offs, `from my side`); a note that says no is read with the reply
  (`publish all # not the proposal` leaves the proposal out), and a note that corrects the answer asks (`raise to 300
  (no, 250)`).
- Gate replies: questions without `?` (`do I kill I-003`, `is 300 enough`), hedges (including `not 100% sure`, `sort
  of`, `I need to check ... first`, `please advise`), conditions (`as long as`, `provided`, `assuming`, `once`), dated
  deferrals (`publish tomorrow`), self-corrections (`A, actually B`, `X - wait, Y`), narrowed echoes (`kill I-003 and
  I-007? only I-003`), sarcasm (`why not`) and the figurative `I would kill for I-007` now ask instead of acting; `I'll
  publish it myself` publishes nothing.
- v1-run offer: it extends only on a plain go and stops only on a plain stop (`no, thanks`, `call it a day`); polite
  declines (`I'm done, thanks`), courtesy (`Noted with thanks`), hedges, `not yet`, `why not` and limits after go (`go,
  but no proposal`) ask.
- G2c/G10/G13: a reply changes the frame, the drivers or the proposal only on a plain edit request or a correcting
  statement; remarks (`I read it all`), deferrals (`Don't approve yet, ...`), `ok?` questions, changes the kit cannot
  see (`the changes discussed in the meeting`) and vague changes ask, while `No corrections from my side`, `ack`,
  `Kindly proceed`, `Noted with thanks`, `leave them tagged`, `corrections: n/a`, `Spot on` and quoted or JSON keywords
  confirm.
- G12/G14: word-named exclusions (`All good except SMS`, `publish everything, omit the proposal`) and spoken ADR numbers
  ask, and a range names each ADR in it (`reject 1..3`, `accept 1-3`); `N: reason` ends at the next verb, numbers in
  notes and because-reasons are skipped, `Reject 3, the rest are fine` accepts the rest; a reason after `publish:` no
  longer refuses the publish, `publish the ADRs too please` publishes the ADRs, and an item named only in a later note
  asks.
- G4/G5/G1/G2f/G9/G11/GB: `plus`, `as well as` and bracketed ID lists place every ID, dictated IDs (`I dash 003`) read,
  a kill without an ID or an ID no verb places asks, `no reason to keep` no longer keeps and `can't not rescue` rescues;
  G1 synonyms read and `done in five minutes` / `can I skip?` ask; G2f `revert` meaning reply asks; G9 `missed, but keep
  the idea` and `passed, sort of` ask; G11 framed choices and `lgtm, suggestion A` read; GB skips cited numbers and
  bracket notes.
- Answer-file fields typed as the reply (`choice: B`, `action: approve`, `{"confirm": true}`) read as fields, and
  `false` / `no` / `off` / `0` refuse (`publish: false` publishes nothing, `restore: false` keeps CONTEXT.md); `kindly`,
  `noted`, `ack`, spoken punctuation (`publish comma handoff none period`) and dictated `know` for `no` are read.
- Fenced `Fails if` examples in 07_REDTEAM.md or a check no longer reach the architecture brief (12.1), the proposal's
  evidence pack C (13.1), the handoff seed or a finalist's main risk; before, only the probe's kill assumptions skipped
  them.
- A JSON integer too large for a float (a duration in logs/calls.jsonl, a weight in criteria.json, a quality-goal weight
  from the architecture drivers, a score or weight bs.py reads) is skipped like any other non-number. A quality-goal
  weight that is no finite number, or is negative, counts as 0 before the weights are scaled to 70, and a finite
  weight near the float limit scales to 70 instead of NaN (which the 12.7 matrix showed as a clear leader). Before,
  such an integer raised OverflowError out of the progress block, out of step 2.2's criteria check and out of step
  12.2. A proposal heading whose number is thousands of digits long no longer stops index.html from being built.
- Gate replies: doubt is read on the whole reply, notes included, on every path (answer-file fields, G0 and the v1-run
  offer too): a hedge, a question, a condition, a deferral, a self-correction, a refusal or a reply cut off mid-sentence
  asks wherever it stands (`raise to 300 (not sure)`, `go # idk`, `idk, kill I-003`, `Not sure yet. Kill I-003.`, `Once
  legal has signed off: publish all`, `raise to 300 (make it 250)`, `Keep I-003 as the backup and kill I-007 after the
  pilot`, `yes, but tell me the cost first`); the `check ... first` hedge is read in linear time.
- Gate replies: a field typed as the reply (`kill: ...`, `accept: ...`, `publish: ...`) is taken only when its value
  reads in full as the field's form, and anything else is read as a reply with every check (`kill: I-003, not I-007`
  kills I-003, `publish: all?` asks); words that change the action are no longer filler: modals (`I might kill I-003`),
  G2f `keep the original` / `discard the old version`, GX `wait`, G14 `some` / `a few` / `else` and GB `raise to over
  300` ask.
- Gate replies: text that is not the user's own answer is a note: a colleague's line (`Sam (Slack): 'reject 3'`, `@sam
  should ...`, `ask Sam about ...`), the card's own text pasted back, a pasted document, a signature, a `cc` line or a
  forwarded header; a reply of nothing else asks, a remark about someone else does not answer an echoed action question,
  and at G0 such text is never a seed. A greeting line that holds the answer (`Hi, B`) is read.
- Gate replies: every reply is normalized first (NFKC, then format characters such as zero-width spaces dropped), so a
  fullwidth `web: no` is a setting and a fullwidth `publish` publishes; a word that mixes scripts (a look-alike
  `publish`) is unknown and asks.
- Gate replies: plain replies are read, not asked again (`Passed, was 8 of 10`, `publish everything, do it`, `publish
  all at once`, `as soon as possible, raise to 300`, `Stop here, we'll pick it up next quarter if at all`), and so are
  plain confirmations in transliterated and other-language words (`tayeb`, `aywa`, `shukran`, `si`, `oui`, `perfecto`,
  `achha theek hai`), courtesy words (`done ta`) and everyday forms of the actions (`sign it off`, `lock it in`,
  `rubber-stamp it`, G11 `switch to B`, G13 `switch to the runner-up`); at the v1-run offer a sign-off asks, since it
  may mean wrap up.
- G2c/G10/G13: a frame correction, a paid drivers redo or a change round starts only when the whole reply is a
  correction: a confirmation beside a remark (`fine by me, I don't know much about this`, `no errors`), a change put off
  (`yes, but I'll probably want to change things later`, `ok, corrections to follow`, `approved the budget with finance,
  still need to read the rest`), a reply that changes nothing (`Remove nothing, it's fine`, `None of that changes the
  drivers`), an edit question answered no (`... ? no, keep them`) and a note to a colleague confirm or ask; an edit
  whose text holds a yes word (`Add: swaps must be approved by the charge nurse`) and a polite request ending in `?`
  (`can you add accessibility?`) are corrections; G13 `changes: ... and switch to B` and `switch` with `runner-up` in
  one clause ask.
- G0: privacy words in Spanish, French and Portuguese (`privado`, `confidencial`, `confidentiel`, `sin internet`) ask
  for the setting; a refusal to start (`Don't start yet`), two modes or autopilots (`standard and deep`), a setting in
  everyday words (`do the most thorough one`) and a line that answers another card (`publish all, ce`) ask; a plain
  confirmation (`Looks fine to me, start whenever you're ready`) starts with no seed; `- web: no` as a list item is a
  setting, and an `Idea:` line outside proposal mode is a seed.
- G4/G9/G12/G14/GB/GX/G2f: an ID both confirmed and cleared, and a rescue followed by another instruction, ask (G4);
  `passed it on to Sam` and a passed result with a disputed target ask, and `we missed it: 4 swaps against a target of
  10` is missed (G9); a number in a reason that names no ADR of the run is a note (G12); `publish it but keep it
  private` (or local, confidential) asks (G14); a raise with no number beside `stop` asks, and a card figure cited
  before the raise is skipped (GB); `continue but change the question a bit` asks, and a colleague's `reframe` is a note
  (GX); `don't restore yet` and `I'd rather keep my original` ask (G2f).
- Gate replies are read back before they act. A reply in the card's own words acts at once (`kill I-003`, `publish all,
  ce`, `raise to 300`, `ok`, `ok, reject 3`, `go with B`, `passed, 18/20 used it`); any other reply the kit can read
  changes nothing yet: the same card comes back with "I read your reply as: <what the kit will do>. Reply yes to do
  that, or tell me what you want instead." `yes` (or `ok`, `go ahead`, `do it`, a thumbs-up) applies exactly that
  reading, `no` asks again with the card's reply forms, a yes or no with more words (`yes, and kill I-007 too`) asks for
  the whole answer in one reply, and other words are read afresh. A G2c or G10 correction, a G13 `changes:` round and
  the G0 seeds are always read back, the seeds as the vendors will receive them; at G13, `approve` after a reading of a
  switch or a change round is asked once (a second `approve` keeps the card's architecture). A reading the run has moved
  past (a stop and continue, a redo, a restore, a default answer, another gate) is not applied: a late `yes` asks again.
  The autopilot, defaults and answer-file fields a host fills are never read back, and a field the host fills beside
  `yes` (a G13 `switch_to`) wins over the reading; hosts write the answer to a read-back with only `reply` filled.
  Terminal mode shows a reading once, not as an error.
- Gate replies: more doubt is asked again instead of acting: a condition or deferral before a colon (`Pending legal
  review: publish all`), `wait not yet` or `not yet` after a decision, a take-back (`kill I-003. or not.`, `add offline
  mode as a goal. I don't know`), `No to <X>` (X is never done), reported or relayed speech (`The user says go`, `Legal
  says no`, `I think he wants to kill I-003`), a request outside the card beside a yes (`yes. also can you email this to
  my boss`), a precondition (`tell me the cost 1st`), `missed, can we rerun it` (MISSED is not recorded), an action put
  off with `later`, `kill both. no, keep both`, `publish it but keep it private`, privacy words and declines in other
  languages at G0 (`vertraulich`, `nein danke`) and a retraction after `go` (`nvm`, `wait a sec`). A forwarded or quoted
  message below the answer is a note, never an extra reject, kill or publish.
- Gate replies: plain replies are read (and read back) instead of asked again: texting forms (`ty`, `np`, `rn`, `u`,
  `w/`, `im`, `yea`, `didnt`, `2 n 3`), an apology or a word of trust beside the answer, a reason after `bc`,
  `skipping`, `did it`, `leave as is`, `continuing`, the user's own `Label: ...` lines (`Choice: "B"`, `Except: the
  proposal`, `Executive summary: mention the pilot budget`), a correction that ends in `No other issues` or names a role
  (`Managers should review every swap`), `200µs` and `10⁶` (the micro sign and superscripts are kept) and `<word>`
  placeholders typed as in the card (`publish <proposal>`). `- web: no, vendors: no` and `web: no, vendors: no. go` are
  settings, and G12 `ok reject 3` without its comma accepts every ADR but 3.
- Gate replies: text after a label (`changes:`, `rescue <ID>:`, `topic:`) is read like any other reply: a take-back, a
  deferral, a condition, relayed speech or a pointer to changes the kit cannot see (`changes: never mind`, `changes:
  will send tomorrow`, `changes: Legal says no`, `rescue I-012: only if legal agrees`) is asked again or read back,
  never acted on, and an action inside a rescue reason (`rescue I-012: cheap, kill I-004`) is asked again. `no need <X>`
  refuses X; `I don't not want to <X>` is asked again; `prepone <X>, rest ok` and `corrections: <text>` are corrections
  and `ok, move forward` is a yes; `raise to 300 but after the meeting` is asked again; G12 `ok reject` without a number
  is asked again and `reject 3, rest ok` accepts the rest; G13 `no, switch to C` and `don't approve, switch to B` are
  read back as the switch; G14 `not the ADRs`, `everything but the ADRs` and `only the proposal, none` are asked again,
  and `only publish the proposal` publishes the proposal and the ADRs it links to, and the read-back says so; only the
  ticked lines of a markdown checkbox list count; G0 privacy requests in more languages (`keine Websuche`, `без
  интернета`, `bez interneta`, `sirf Claude`, `bas Claude`) and `not yet` with more words are asked about, and email
  closing lines (`Looking forward to the results.`, `Thanks in advance!`) are no seed ideas. Replies of any length are
  read in linear time.
- Finalist, red-team and decision replies follow the read-back too: `ok` or the IDs alone act at once (at the decision
  also `I-007 because <reason>`, with `runner-up: <ID>` and `park: <IDs>`); other words are read back with every
  consequence (the set, and what it drops from or adds to the suggested one; at the decision the chosen idea against the
  suggestion, that the probe, architecture and proposal are built for it, and the runner-up the rule records).
  Exclusions and contrasts are read, never picked: `Not I-003, take I-007` chooses I-007, `... but not I-009` leaves
  I-009 out, `all but I-009` and `I-004 instead of I-001` edit the suggested set, `I-004 as runner-up` is never the
  choice. A reply that both takes and leaves out an idea, names an idea the card does not offer or a count outside the
  limits (finalists 2-8, red team 3-4) is asked again. The gut pick is recorded without a read-back: the IDs in the
  order given, never one the reply excludes, more than 3 asked again.
- `restore CONTEXT.md` / `keep CONTEXT.md` at the repository-docs checkpoint and `extend` at the v1-run offer act at
  once, like the card's own keywords.
- Read-backs: a card asked again while a reading waits (a question, an unclear reply) still shows the reading, so a
  `yes` or `ok` after it confirms what the user last saw, and so do `alright`, `all right`, `aye`, `make it so` and
  `that's what I meant` (before, they were read as a new answer, which at G5 parked the ideas the reading killed). The
  card's own word beside a reading it contradicts is asked once, and the same word again is the card's: `go` (also `ok
  go`, `let's go`) after a reading that stops a v1 run, `approve` beside a G13 switch, and G14 `publish` beside a
  reading that names a handoff or publishes less (before, it published everything and dropped the handoff at once). A
  relayed yes (`The user says yes`) beside a waiting reading asks for the whole answer instead of reading back the
  card's default. At the kickoff, a new reply that leaves out the privacy a waiting reading keeps (`start` after `let's
  go, and keep it private`) shows the private reading again, and `yes` starts the private run. G5 `no, keep both of
  them` keeps them (before, it parked them).
- Finalist, red-team and decision replies: an idea ID next to a word the reader does not know is not a pick, so the
  reply is asked again (`I-008 trumps I-001`, `I-001 until I-004`, `I-009 can go`, `ok? or should I add I-004`), and so
  is an ID after a negation (`I don't like I-009`, `never fund I-009`), one put away (`take I-009 off the list`, `put
  I-009 aside`, `on hold`), one after `done with` or `push back on`, and one followed by a negation, a modal or a no
  (`I-009 is not good`, `I-009 doesnt work`, `I-009 can't work`, `I-003, I-007, I-009, no`, `I-009 - nope.`). More
  exclusions are read (`anything but I-002`, `cut`, `scrap`, `ditch`, `bin`, `reject`, `veto`, `nix`, `axe`, `strike`,
  `skip`, `no to`, `apart from`, `get rid of`, `w/o`, `leave I-009 out`, `I-009 is out`, `~~I-009~~`), `X beats Y` and
  `better than` contrast like `over`, and `I prefer I-004 to I-009` (also `I prefer idea I-004 to I-009`, `I'd rather
  have I-004 to I-009`) is asked again as a comparison, not as a range; `I-009 and I-011 out` is asked again. A refused
  rest (`I-001, I-003, not the rest`, `discharge the rest`) keeps the reply's own IDs, a kept rest (`keep the rest`)
  edits the suggested set, and any other rest (`forget the rest`, `the rest can go`) is asked again. An ID range
  (`I-001-I-004`, `I-001 to I-004`, `up to`, `till`) is asked again. The gut pick never records an idea the reply
  excludes or rejects (before, `veto I-009` and `I don't like I-009` recorded I-009); `don't forget I-001` and `I-003 or
  not` are asked again, and the question quotes the words it could not place.
- Gate replies: `second thoughts`, `still reviewing` and `pending` take a reply back or put it off only as your own
  words (`I'm having second thoughts`, `I've had second thoughts`, `having 2nd thoughts` and `changes: pending legal`
  are asked again, `rescue I-012: decision pending` is read back;
  `changes: let users have second thoughts before paying` is a change); `I guess`, `I suppose`, `for now` and
  `provisionally` after a decision pick are read back; a G4 rescue reason naming the other flagged ideas (`the rest`,
  `everything else`, `the leftovers`) is read back; a G11 steal element is checked for doubt like other labelled text
  and `borrow` steals (`C, but borrow A's offline cache`); G5 `kill all but I-007` is asked again; `corrections:
  <deferral or pointer>` (`tbd`, `as discussed`, `Legal says no`) and a `changes:` body that only reports progress or
  points elsewhere (`pending`, `to come`, `in progress`, `still thinking`, `attached`, `see attached`, `per our
  discussion`) are asked again; `no adjustments`, `without revisions`, `no rework needed`, `no updates` and `no edits
  whatsoever` refuse an edit; G12 `everything except 3` and `every ADR except 3` accept the rest; G14 reads `Compound
  Engineering` as the `ce` handoff, asks again for `none, Compound Eng.` and for a publish in words it cannot read
  beside a handoff (`publica todo, ce`), and never reads the noun `copy` as a publish (`no, I already have a copy` is
  read back as no publish, `I already have a copy` alone is asked again); G0 `LGTM, ship it`, `I consent` and `consent
  to proceed` start with no seed, `I do not consent` is asked again, `deep, hands-on, web: no` acts, and a short line
  that names the web or a model in any language (`uniquement Claude`, `hors ligne`, `web yok`, `bidoon internet`) is
  asked about as privacy; G9 `at least once` is no condition; G1 `done, but I still need to add ...`, `done, one more
  to add` and `done, wait one more` are asked again, while a seeds line such as `done - nurses still have to add their
  shifts by hand` is read back; GB `raise to 300 but not until Monday`, `, just not today` and `but next week` are
  asked again; a clause with its own subject (`publish all, and we launch next week`) is a remark, not a delay; `I
  wouldn't not extend`, `I'm not against extending` and other double negations are asked again, and `go without the
  proposal` is asked instead of read as a stop; numbered, lettered, empty (`[]`) and ballot-box checkboxes count only
  when ticked; a G10 correction that ends `..., a 1-hour delay is fine` is read back as the correction; `dont`, `cant`,
  `havent`, `doesnt` and other contractions typed without the apostrophe, `w/o`, `b/c` and `w/` are read (`rescue
  I-012: havent decided` and `I-007: doesnt work for us` are read back), and every answer, idea, reason, correction
  or change the kit stores keeps your words (`A/B/C testing`, French `dont`, `offline w/`).
- Gate replies pasted from a chat: a line's time stamp (`[17:01]`, `[5:00 PM]`) is dropped, a line another name leads is
  that person's words, not your answer, and your own line that only agrees with it (`me: yes`, `me: +1`) is read back as
  their words, or asked again at a gate that takes your words as text or acts without a read-back. Before, a colleague's
  IDs were recorded as your gut pick and the hour was read as the budget cap.
- Finalist, red-team and decision replies: an exclusion verb after the ID (`I-009 reject`, `I-009 vetoed`, `I-009 nix`,
  `I-009 scrap`, `I-009 skipped`, `I-009 dead`) and a no after any run of punctuation (`I-009 -- no`, `I-009... no`,
  `I-009 -> no`, `I-009 thanks, no`, `I-009 [no]`) are asked again. The gut pick has no read-back, so a rejection right
  after an ID and a separator (`I-007: not good`, `I-007, doesn't work`, `I-007 (not good)`, `I-007 = no`) is asked
  again there too; `I-007, not sure`, `not I-009`, `no others` and `I-003, I-007 kill the others` stay as they were.
  Before, these recorded the rejected idea as a gut pick.
- Gate replies: `I changed my mind`, `second guessing`, `oops`, `disregard that`, `strike that`, `cancel that` (not
  `cancel that subscription flow`) and more forms of `second thoughts` (`I've had a second thought`, `I keep having
  second thoughts`, `I am starting to get second thoughts`, `me having second thoughts`) take a reply back, and a
  longer deferral (`on hold until Friday`, `I will decide tomorrow`, also in a G9 note after the count; in a reason
  also `the legal review is still pending`, `the decision is still pending on my side`) puts it off. After `changes:`
  a sentence such as `note that the pilot results are still pending` stays a change request (it is read back
  whole). `second thoughts` with no punctuation or clause lead before it (`passed, 18/20 having second thoughts`) is
  still not read; put a comma or a full stop before it.
- Answers, ideas and cells you typed are stored as typed even when a later item repeats part of an earlier one
  (`- bot w/o login` then `- out login`; before, the second took the first one's words), and the cells of a JSON reply
  keep them too.
- Free-text gate replies stay linear on a long run of blank lines (G12 and G14: `ok` or `publish` then 20000 line
  breaks took 9 to 40 s), of spaces (`comma` and `period` said aloud; a G4 reason; a G0 `topic:` line) and of dashes
  (`Legal says no`).

### Proposal fix passes

- The proposal fix (13.6) sees ONE-PAGER.md after the sections, and reprints it in full when a change alters a figure,
  a date, a milestone or the ask it states. Before, a fix that moved the ask in section 1 left the one-pager with the
  old figures, because the one-pager's text was not in the fix prompt.
- New lint rule P11 (warn): the one-pager states every money figure of section 1, and every money figure or ISO date
  in the one-pager still appears in sections 1-13. Amounts are compared as exact numbers (currency, thousands
  separators and `k`, `M`, `MM`, `B` magnitudes normalized, so `$9k-$27k` equals `9,000-27,000 USD` and
  `9,000 USD to 27,000 USD`). The basis of an `[ESTIMATE: range; basis]` tag is not a headline figure, and a date
  after an amount (`$800 - 2026-10-01`) is not a range.
- For another vendor, the one-pager in the proposal prompts is filtered apart from the proposal, so the glossary
  filter of an Appendix E that runs to the end of the proposal no longer drops the one-pager from the prompt.
- A second fix pass (13.6b, then the assembly 13.4c) runs once when a lint FAIL or a P11 item is left after 13.6 and
  G13 has not been shown yet. A run that reached sign-off under an older kit is never re-fixed, `redo 13.7` included.
  `ub plan` counts the pass as an optional call (standard 55-74 calls).
- The G13 card lists the lint FAILs and P11 items still open (the first 8, then a count pointing to lint.md) and the
  `changes: fix the lint items` reply that runs another fix round while change rounds are left; `approve` signs off
  with them open. A `changes:` round runs both fix passes.

### Publishing (breaking: copies go to `docs/<run>/`)

- G14 copies each approved item into the run's own folder and keeps the run's layout: `docs/<run>/10_ARCHITECTURE/`
  (with its `adr/`) and `docs/<run>/11_PROPOSAL/`. Files are copied byte for byte, so every link resolves unchanged,
  and two runs never mix (a run claims its `docs/<run>/`, so a run of the same name in another run root is refused),
  even when they publish at the same moment. A run claims `docs/<run>/` in one step (the whole claim is hard-linked, or
  on Windows renamed, into place; an empty claim left on another disk without hard links is taken over by its own run
  after a minute), so a publish interrupted while it claims no longer locks its run out, even on a disk without hard
  links (exFAT, FAT32, some network shares), and a claim that another run of the same name takes while this run checks
  is refused, never adopted. What a run published is recorded in `brainstorm/<run>/handoff/published.json`; an
  interrupted publish just runs again. Copies made by kit 2.0.x (`docs/architecture/`, `docs/adr/`, `docs/proposal/`,
  `docs/<item>/ub-<run>/`) are left as they are and named on the G14 card; move or delete them yourself.
- Published files get the mode a new file gets under your umask (0644 under 022) instead of 0600; an unchanged file
  keeps the mode you gave it.
- A run without web access gets an `index.html` that loads no script.
- `index.html` loads one pinned Mermaid build (11.17.2) with Subresource Integrity under a Content-Security-Policy and
  sends no referrer. Link targets are escaped once, and `//host` and `/path` targets become `#`. A missing or broken
  page or handoff-seed template stops with a BLOCKED card instead of a built-in fallback. A proposal page rendered by
  kit 2.0.x (a floating Mermaid import without integrity, or any script in a run without web access) is rendered again
  before the G13, G14 or DONE card links to it and before a publish or `ub export --format html` hands it out.
- Publishing and proposal assembly finish an interrupted file write first and never copy its temporary files. The
  LEDGER probe row is written only for the chosen idea. Appendix D shows the ranking method and the Condorcet result.
- G14 reads exclusions in any wording ('apart from', 'other than', 'excluding', 'minus', 'leave out', 'keep the proposal
  private'), additions ('too', 'as well', 'and nothing else'), 'Spec Kit' and a later 'none'. A deferral ('I'll publish
  later myself') publishes nothing. A bare 'yes' or 'go ahead' is asked again, and so is an open handoff on software and
  growth runs. A handoff the project does not offer is refused.

### Installer and supply chain

- Every component source is pinned: mattpocock skills to a commit archive with content SHA-256 pins (no longer
  `npx skills@1.7.0`, so no npm dependency ranges are resolved at install and no Node is needed for them), Compound
  Engineering and pm-skills to release tags whose commit is checked when the marketplace clone can be read, spec-kit to
  a commit, bmad and idea-reality to exact versions. claude-council has no release tag and is marked UNPINNED. Workflow
  actions are pinned to commit SHAs. With `UB_INSTALL_OFFLINE=1`, the mattpocock skills install from `UB_COMPONENTS_DIR`
  when it holds the pinned archive. A re-install keeps the drift record of a skill folder the installer put there with
  the commit that folder came from (`commits`), so after a pin bump doctor's drift warning names the right commit.
  `doctor` warns `stack.<skill>.unpinned` for a grilling or domain-modeling folder it has no record of that is not the
  pinned content (for example a kit 2.0.x npx install), and `uninstall` lists the component folders it copied (they stay
  installed). A marketplace answered "already ..." with exit 0 is named as an earlier registration too.
- `install.py doctor` reports a component or kit skill file it cannot read (held open by another program, no read
  permission) as a WARN instead of crashing, and no longer crashes on a Claude settings.json whose `env` is not an
  object.
- Releases carry GitHub build provenance attestations. The bootstrap scripts and `install.py update` verify them with
  `gh attestation verify` when the GitHub CLI is signed in, and require the attestation to come from
  `.github/workflows/release.yml` for the tag `v<version>` (`--signer-workflow`, `--source-ref`); an old gh is "not
  checked", never a pass. `--require-attestation` turns a missing check into an error. A published release is never
  replaced. `install.py update` refuses a release archive whose `VERSION` is not its tag's version, and a
  releases/latest older than 2.1.0 (the first attested release; name an older release with `--tag` to install it), so
  relabelling a release no longer skips the provenance check or the downgrade guard. Like the bootstrap scripts, it asks
  `gh attestation --help` and `gh auth status --active --hostname github.com` first (a stale second account or an
  enterprise host with a sign-in problem no longer skips the check) and pins verify to github.com (`--hostname
  github.com`, also in the manual command the bootstrap scripts print), then treats every failed `gh attestation verify`
  as a refusal except a timeout or gh's exit code 4 (authentication required), which count as "not checked", so a
  refusal that quotes a workflow or branch named `network` or `timeout` is no longer taken for "gh could not check". In
  all three installers, a gh that cannot load Sigstore's trust root (`error creating Sigstore verifier`, for example
  behind a proxy that blocks it) is "not checked", not a refusal; a refusal now says gh did not confirm the archive and
  names the way out (run the check by hand where gh reaches GitHub and Sigstore, then `install.py update --source DIR`).
  All three read `unknown flag` and that Sigstore phrase only in gh's own words, outside its quoted values.
- tools/release.py refuses to build while docs/ACCEPTANCE.md lacks live results (exit 3); `--no-acceptance`
  (release.yml: only behind an `Acceptance override:` line in the version's CHANGELOG section) lists what is
  unverified in the release notes. A "not tested" or "not yet verified live" Doctor cell no longer counts as a host
  check. validate_kit checks that KIT_SPEC section 15, docs/ACCEPTANCE.md and the code tags agree.
- `install` and `update` do not swap the kit under a run with live workers or a live driver (`--force` overrides), and
  only one installer applies changes at a time (`UB_HOME/install.lock`). The installer re-checks its plan under
  install.lock (another installer's apply, a run that became live: exit 4, nothing applied), recognizes kit 2.0.x
  drivers (.ub/lock.json heartbeat), keeps UB_HOME/kit when a plugin's CLI is missing at uninstall, finishes a partial
  uninstall on re-run, and blocks a kit marketplace registered from a folder that no longer exists. A kit 2.0.x
  `ub run` waiting at a question (no heartbeat for over 120 s) still counts as a live driver while the process that
  wrote its last heartbeat runs (on Linux and macOS also after a forward clock step, recognized by its command line:
  ub.py on that run). The block names such a session with its pid and says to answer or close it in its terminal:
  `ub stop` does not end a kit 2.0.x session. This kit's own `.ub/lock.json` record never counts, and neither does a
  heartbeat more than 120 s in the future, so a hard-killed `ub next` whose pid was reused never blocks install, update
  and uninstall.
- `--force` and `--migrate-v1` now back up the whole folder they replace; `.git`, `.build` and caches used to be left
  out of the backup and then deleted. Symlinks are listed in the backup's `LINKS.txt` and never followed. An owned copy
  that holds a `.git`, `.build` or a symlink now counts as edited: update and removal back it up, and uninstall keeps it
  (`--force` backs it up and removes it).
- `update` run from another kit copy (a second clone, an unpacked release, the bootstrap scripts) now stages that copy.
  It used to re-stage the older clone the manifest recorded and report "Nothing to do". The staged kit's own installer
  still re-stages the recorded clone. `update` also stages the source kit's own `runtime_paths`, so a path that a newer
  release adds is staged even when an older installer runs the update. A refused downgrade now blocks every row that
  would apply the older kit. Before, an interactive `install` or `update --source <older kit>` replaced the agents'
  copies and the manifest version while UB_HOME/kit stayed newer.
- An interrupted install keeps and re-records its manifest, and its leftovers are removed by the next install, update
  or uninstall (`doctor` reports them). The native route checks that the plugin loads from the staged kit.
  `uninstall` keeps `UB_HOME/kit` when a plugin removal fails. When it keeps UB_HOME/kit because a plugin's CLI is
  missing or a plugin's source is unknown, it names the remedy that works: put the missing CLI back on PATH and run
  uninstall again, or run `uninstall --purge` if you no longer use that agent (without its CLI the installer cannot see
  a plugin removed by hand, so removing it by hand never let uninstall finish); for a plugin of unknown source, remove
  the plugin first (or pass `--force`), then run uninstall again. `--purge` moves Codex's own data in the provider homes
  to backups.
- `uninstall` now removes each native plugin in the agent home the manifest recorded, for example the
  `--claude-config-dir` or `--codex-home` of that install. Run without that flag, it used to report success, delete
  UB_HOME/kit and leave the plugin registered against the deleted folder. Two Codex homes now each get their own
  marketplace removal. A `--scope project` Claude install whose project folder was deleted or moved now uninstalls: only
  the marketplace removal runs, with a warning that gives the command for a moved project. A plugin command that could
  not start or timed out no longer counts as "not installed".
- `--login` now signs in to the `--codex-home` or `--kimi-home` that the plugin rows use. It used to sign in to the
  default home and ask again on every run.
- Launchers delete their secret files on abnormal exit, and the next launch removes those of launchers that died.
  claude-glm / claude-kimi: no token file is left behind by a console close racing the normal cleanup, a second
  SIGTERM/SIGHUP no longer interrupts the cleanup, and the stale-file sweep compares process identities (a clock step
  no longer makes a live session's file look stale; an unreadable `.id` counts as no record).
  `UB_RELEASE_DIR` picks the newest archive by version number.
- The `.cmd` and `.ps1` launchers (`ub`, `claude-glm`, `claude-kimi`, `codex-glm`, `codex-kimi`) now start when UB_HOME
  or the installer's Python sits under a non-ASCII path, such as a Windows profile named `C:\Users\José`. The `.ps1`
  gets a UTF-8 BOM, and the `.cmd` reads its path lines under code page 65001 and then restores the console's code page.
  `ub.ps1` exits 9009, no longer 0, when its Python is gone, and `launch.py render-launcher` no longer crashes on such a
  path.
- install.ps1, run through the one-line scriptblock route, now passes an unquoted comma list
  (`--agents claude-code,zcode`, `--with-clis claude,codex,kimi`) on as typed. install.py's stderr no longer aborts the
  script when the caller redirects `2>&1`.
- `claude-glm` and `claude-kimi` take a provider's endpoint and models from the worker's own rule
  (`ublib.families.provider_settings_env`). A `families.json` `region` the provider has no URL for (`cn` for `kimi`) now
  falls back to global, as the pipeline's calls do, instead of refusing every start. An explicit `--region` the provider
  lacks is still refused. A provider with no URL at all now exits 2 instead of starting Claude Code on Anthropic's
  endpoint with the provider token.
- The launchers refuse a `families.json` that is valid JSON but the wrong shape (a non-object top level, `providers` /
  `backends` or one of their entries, or an entry's `base_url`, `models` or `env`; a `region`, `token_env` or
  `token_var` that is not a string). They exit 2 with a message naming the key, instead of a Python traceback with exit
  1. `setup-glm --codex` / `setup-kimi --codex` block the Codex home on such a file instead of rendering it without its
  `codex_base_url` override. `setup-glm` and `setup-kimi` refuse the same file with exit 2 and the key; a single-URL
  `base_url` is refused only by `--region cn`, which would have to write into it.
- `install.py doctor` no longer crashes when ANTHROPIC_BASE_URL, or a Codex `model_provider` / `base_url`, is not a
  string (a number, list or boolean in settings or config.toml); the value is treated as unset.
- The staged installer recognizes itself through any spelling of UB_HOME (a junction, symlink, subst drive or 8.3 name):
  `update` re-stages the recorded source clone, and a later install through the alias keeps that clone recorded as the
  source.
- `update` and `uninstall --force` keep the empty folders of a backed-up .git or .build (refs/, objects/info, ...), so
  the backup of a user's .git is still a repository.
- `install --with-clis`: when the plan rebuilt after the CLI rows has blocked rows, `--yes` applies nothing more and
  exits 4 (only the CLI rows were applied). Interactively the changed plan is shown and confirmed again, and a no exits
  5. The `--yes` blocked-rows exit is also recorded in the plan as 4.
- On Windows, uninstall keeps the case of the user's CLAUDE.md / AGENTS.md when it removes the routing block (it had
  renamed them to claude.md / agents.md).
- A backup's `LINKS.txt` lists a Windows symlink's target as a plain path (without the `\\?\` prefix Windows adds).
- install.sh prints gh's words with `printf`, not `echo`: under dash, `echo` turns a backslash sequence in a quoted
  certificate identity into a control character.
- install.sh exits with install.py's exit code (2 usage, 3 no agent, 4 blocked, 5 cancelled) instead of collapsing them
  to 1, as install.ps1 already did.

### Tests

- Failure-injection suite (`tests/e2e/test_wp8_failure_injection.py`) covering every vector of the architecture
  audit's section 6, and guard tests (`tests/unit/test_wp8_guards.py`) that kill the mutants the other suites let
  survive.
- `tests/unit/test_proposal_fix.py`: the fix prompt carries ONE-PAGER.md, 13.6b runs only on a lint FAIL or P11
  item left after 13.6, and a stub run whose fix moves the ask in section 1 gets the one-pager back in line.
- CI gives each test job 75 minutes and each suite 40 minutes: the Windows jobs took up to 45 minutes, the old
  job limit, and the unit suite up to 1344 of its 1500 seconds.
- `tests/static/test_wp9b_docs_sync.py` keeps the documented call, time and token figures equal to `ub plan` and
  requires a `docs/ACCEPTANCE.md` row with a live check for every `[U-n]` tag in the code.
- Regression tests for the follow-up fixes of the audit's verification rounds (`tests/unit/test_e1_*.py` to
  `test_x_*.py`, `tests/integration/test_e4_*.py`, `test_h_*.py`, `test_j*.py` and `test_l_*.py`,
  `tests/e2e/test_e1_run_argv.py`, `tests/static/test_e4_release_gates.py`, `test_h_*.py` and `test_j*.py`; KIT_SPEC
  11.11).

### Removed

- The v1 mode of `bs.py` (its golden files and legacy tests), `bs.py dupcheck` and the deep 5.2d/5.2m loop.
- The judges' `confidence` and `decisive_reason` fields, the reviewer's confidence suffix and the architecture judges'
  `confidence` field.
- `budget.max_usd`, `counters.g2c_loops`, seven unused pipeline predicates and `{item.x}` job templating.
- The experimental `bundles/stack` plugin, the installer's built-in launcher renderers, and the built-in page and
  handoff-seed fallbacks.
- The `.ub-published` markers, the fixed `docs/architecture`, `docs/adr` and `docs/proposal` targets and ADR link
  rewriting.
- The stub responder left the skill for `tests/harness/stubs.py`: an installed kit in fake mode (`UB_FAKE_FAMILIES=1`)
  answers only PING.

## 2.0.3 - 2026-09-26

Bug-fix release for G14 publishing: runs never mix in `docs/` any more, and ADRs are published once.

### Fixed

- A second run's G14 publish mixed into the first run's `docs/architecture`, `docs/adr` and `docs/proposal`:
  the kit treated files listed in another run's `.ub-published` marker as its own, so `docs/adr` ended up with two
  unrelated ADR sets both numbered 0001, same-named files (README.md, PROPOSAL.md, ...) were replaced and the
  marker was rewritten to claim both runs' files. A folder that holds another run's package (or files the kit did
  not publish) is now never written: the run publishes into `docs/<run>/<item>/` instead. This replaces the old
  fallback `docs/<item>/ub-<run>/`, which is still updated in place when a run republishes. The G14 card shows the
  real target for each copy and warns, naming the other run; `12_HANDOFF.md` records where each copy went and, on
  a new `Not published:` line, what was not copied and why. ADRs are not renumbered: each run keeps its own ADR
  log.
- Publishing is safer in general. Only a run's own earlier copy is updated in place. A file it replaces, or a
  file it no longer has (the old ADR set after `ub switch --arch`, say, also when the new architecture has no ADRs),
  goes to `_superseded/<stamp>/published/<item>/` first (it was `_superseded/<stamp>/published/docs/<item>/`); an
  unchanged file is left alone and not backed up, and a backup never overwrites an older one. The `.ub-published`
  marker (now `schema: 2`) is written before the first change, so an interrupted publish resumes in the same
  folder, and `12_HANDOFF.md` still lists what the interrupted attempt moved or replaced. Files are written through a
  temp file and a rename, so a hard link in `docs/` is replaced, not written through. A fixed folder that is (or
  holds) a link or junction counts as taken, so the copy goes to `docs/<run>/<item>/`; the item is not published
  when `docs/` is a link, or when that run folder is (or holds) a link or is taken too. OS and editor files
  (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `.gitkeep`, swap files) are never published and never make a folder
  look taken. Names read from disk (another run's name, a link's name) are escaped before they go on the card. An
  item with no files (zero ADRs) shows "nothing to publish", unless this run published it before: then its old copy
  moves to the backup. Listing an item twice publishes it once.
- G14 `publish` copied every ADR twice, to `docs/architecture/adr/` and to `docs/adr/` (or both under
  `docs/<run>/`), and the two copies drifted apart as soon as one was edited. ADRs are now published once, to the
  adr copy, and publishing `architecture` or `proposal` publishes them too, so every link is written against a fresh
  copy. The architecture copy leaves out `adr/`, and the ADR links in the architecture README (decision index),
  `chosen/`, the proposal (Appendix A, sections) and `index.html` point at the adr copy. The proposal's ADR links
  (`../10_ARCHITECTURE/adr/...`), which were broken in every published copy, now resolve. If no adr folder can be
  placed at all, the ADR links are left as they are and the card says so. Old ADR files (in the architecture copy, or
  renamed after
  `ub switch --arch`) move to `_superseded`, except files that a published copy of this run not in the answer still
  links to: those stay until nothing links to them. A second copy of the run (made while `docs/adr` was a link, say)
  moves to the backup the same way. A publish writes every copy first and moves old files last, so an interrupted
  one never takes away a file a published copy links to, and resuming it ends with every link resolving. Links are
  rewritten in the bytes, so encoding, BOM and line endings are kept. The G14 card says where the ADRs go.
- Folders last written by 2.0.2 or earlier are not repaired automatically, because their marker cannot tell one
  run's files from another's. When a run publishes into such a folder again, every file the old marker lists that
  the package does not have stays in place (it may be another run's, or this run's own old ADR), the card warns, and
  the new marker keeps those files apart (`legacy_files`); in a folder with such leftovers the card also warns before
  a file with another content is replaced (it is backed up first). To clear the leftovers, move them aside by hand.
  To split folders 2.0.2 mixed, move `docs/architecture`, `docs/adr` and `docs/proposal` aside and run
  `ub redo <run> 14.2 --yes` for each run, oldest first (it asks G14 again); the files 2.0.2 replaced are in the
  later run's `_superseded/<stamp>/published/`.

## 2.0.2 - 2026-09-23

Bug-fix release for two timing-dependent failures seen on Windows.

### Fixed

- The same model call could run twice for one job. When the three proposal-section workers (13.2) created the same
  new folder at the same moment, Windows sometimes reported the target path in a long `\\?\` form. The kit then
  wrongly rejected the valid answer as "outside the output root" and asked the model again. The path is now
  normalized first, and an answer that is valid but cannot be written is retried on disk instead of asking the model
  again.
- Only one worker can run a job at a time. Each worker now holds a lock file for its job (`.ub/jobs/<id>.lock`),
  which the operating system releases when the worker ends, even if it is killed. A job that is running, finished,
  or was just run by another worker is never called again, whoever starts it. The launcher and its worker recognize
  each other by a launch token, so this also works in a Windows virtual environment, where the launcher sees a
  different process id than the worker's. A late heartbeat no longer makes a live worker look dead.
- Reading a worker's status file on Windows could fail with "Permission denied" when it was read at the moment the
  worker was updating it. Reads now retry for up to a second, so the kit no longer mistakes a running or finished job
  for a stopped one, and `ub stop` no longer misses a live worker.
- A dead job whose old worker process cannot be stopped now shows a BLOCKED card that suggests `ub stop`, instead of
  waiting forever.
- Tests: the Retry-After check uses a monotonic clock, so wall-clock steps (seen under WSL2) no longer fail it.

## 2.0.1 - 2026-09-23

Bug-fix release. CI now runs every suite on Windows, macOS and Linux (Python 3.9, 3.12, 3.14) and is green.

### Fixed

- Background workers: the job-state check read the "done" marker before the "running" marker, so a model call that
  finished between the two reads looked pending and was launched a second time (duplicate calls and duplicate
  records). The running marker is now read first.
- `install.ps1` now stops on every error. Before, if a cmdlet such as `Get-FileHash` failed to load (for example when
  Windows PowerShell 5.1 inherits a PowerShell 7 module path), the bootstrap could exit 0 without verifying the
  download or installing anything.
- The experimental Claude bundle manifest has an `author`, so `claude plugin validate --strict` passes.
- Tests: the POSIX fake-CLI shims no longer depend on `dirname` being on PATH (this failed every fake CLI call on the
  GitHub Linux and macOS runners); golden files are compared with normalized line endings; bootstrap tests run on
  elevated Windows runners.

## 2.0.0 - 2026-09-23

First public release of the kit (v2). It replaces the single v1 skill with an installable package that runs in
Claude Code, Codex, Kimi Code and ZCode.

### Added

- One-line installers for macOS, Linux, WSL, Git Bash (`install.sh`) and Windows PowerShell 5.1 or newer
  (`install.ps1`). Each downloads one release archive, checks its SHA-256 and then runs the Python installer.
- `install/install.py` with `plan`, `install`, `update`, `uninstall` and `doctor`. It shows a plan first, changes
  nothing until you agree, records what it wrote in an install manifest and can undo it exactly.
- Plugin manifests for Claude Code and Codex, plus a universal skills layout (`.agents/skills`) for other hosts.
- A full pipeline, from sealed human seeds to handoff: frame, research, five isolated idea strategies, map, screen,
  prior-art checks, a tournament judged in both orders by several model families, red team, your decision, probe,
  competing architectures judged blind, and a cited proposal with a one-pager and an HTML pack.
- Model family routing for Claude, GPT (Codex), Kimi and GLM (Z.ai), with launchers and per-family overrides
  (`docs/FAMILIES.md`).
- Standard (guided) and full-auto modes. Every run is kept in files under `brainstorm/<date>-<topic>/`, so you can stop
  and continue at any time.
- Privacy controls at the first question: turn off web search, other vendors or both, or type `private`. API keys are
  read from environment variables only. There is no telemetry.
- `doctor` checks for every host, and `docs/TROUBLESHOOTING.md` lists every message the pipeline can stop with.
- Reproducible release builds (`tools/release.py`) with `SHA256SUMS`, and CI that runs every test suite first.

### Changed

- The v1 `bs.py` engine is kept, and its old test harnesses have been ported into the kit's own test suite.
- `docs/GUIDE.md` has been updated for v2: the stack, the pipeline and install steps for each host.

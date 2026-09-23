# Notices and credits

ultimate-brainstorm is released under the MIT License (see `LICENSE`). It installs nothing from the projects below
unless the user asks for that component; where their ideas, rules or names are reused, they are credited here.
No third-party code is vendored into this repository.

## Methods and formats reused (adapted or paraphrased)

| Source | License | What the kit reuses | Where |
|---|---|---|---|
| BMAD Method (bmad-code-org) | MIT | PRD quality rubric and product-brief ideas; Facilitator stance in deep mode | Stage 13 proposal prompts, deep-mode facilitation |
| pm-skills | MIT | Red-team method for a decided idea | Stage 10 red-team, `proposal` mode |
| Compound Engineering (EveryInc) | MIT | Bake-off pattern (competing candidates judged side by side); `ce-ideate`, `ce-brainstorm`, `ce-plan` as optional components | Stage 12 architecture candidates, Stage 14 handoff |
| MADR 4.0 (Markdown Architectural Decision Records) | MIT OR CC0-1.0 | ADR section layout | `10_ARCHITECTURE/` ADRs |
| arc42 | names only | Section names of the architecture document | `10_ARCHITECTURE/` |
| C4 model (Simon Brown) | names only | "Context" view naming and levels | Rendered context diagram |
| Semantic Anchors | paraphrased | Traceability rules between drivers, decisions and proposal sections | Stage 12-13 lints |
| creative-director | CC BY 4.0 | Creative-brief rules (the attribution line is kept wherever its rules are reused) | Creative and naming variants |

## Sources of the v1 guide

`docs/GUIDE.md` is based on `ULTIMATE_BRAINSTORMING_WORKFLOW.md` (v1). Its evidence rules cite, among others:
Diehl and Stroebe 1987; Mullen et al. 1991; Girotra, Terwiesch and Ulrich 2010; Qin et al. (CHI 2025);
Wadinambiarachchi et al. (CHI 2024); Kumar et al. 2024/25; Doshi and Hauser 2024; Maier et al. (CHI 2026);
Meincke, Mollick and Terwiesch 2024; Zhang et al. 2025 (Verbalized Sampling); Si, Yang and Hashimoto 2024;
Si et al. 2024; Si, Hashimoto and Yang 2025; Chen et al. 2026; Wenger and Kenett 2025; Artificial Hivemind 2025;
Padmakumar and He 2024; Peeperkorn et al. 2024; Nova 2024; SciMON 2024; Wang et al. 2023; Panickssery et al. 2024;
Zheng et al. 2023; Tripathi et al. 2025; PairS 2024; Sinhahajari et al. 2026; Chakrabarty et al. (CHI 2024);
Organisciak et al. 2023; Du et al. 2023; Liang et al.; Smit et al.; Ueda et al. (SIGDIAL 2025);
Google co-scientist 2025; Boussioux et al. 2024; Lee and Chung 2024; Ashkinaze et al. 2024.
The full citations and the finding each one supports are in `docs/GUIDE.md` section 2.1.

Mechanisms copied as prompts (not installed), as credited in the guide's sections 2.2 and 2.3: Verbalized Sampling,
gstack forcing questions, PAL stance guardrails, Google co-scientist evolve and tournament, the lateral-thinking
transfer method, idea-validation-agents risk test, GSD explore's admit / refute / abstain dispositions, Hermes
anti-slop tests, ADHD anchor-stripped brief, claude-brainstorm-multiagent coverage grid, cc-thinking-skills TRIZ
template, and Anthropic product-brainstorming "opposite" and "subtraction" ideas.

## Optional components the installer can add

The installer can install these on request; each keeps its own license, and nothing from them is copied here:
Compound Engineering (EveryInc), Matt Pocock skills (`grilling`, `domain-modeling`), and the `npx skills` CLI
(vercel-labs/skills). See `install/components.json` for the pinned versions.

## Trademarks

Claude and Claude Code are trademarks of Anthropic. Codex and GPT are trademarks of OpenAI. Kimi is a trademark of
Moonshot AI. GLM, Z.ai and ZCode are trademarks of their owners. They are named only to describe compatibility.

# HANDOFF — transfer to local PC (Claude Code + ECC)

## What this project is
AMD AI League Match 4 hackathon entry: asymmetric Web Information Retrieval pipeline
(typed discriminative primitives NOUL/SCORE/CHOICE + ONE generative call).
Read order: BUILD_SPEC.md → CORPUS.md → DEMO_SCRIPT.md. CLAUDE.md is auto-loaded by Claude Code.

## Setup on the new machine
```bash
npm install -g @anthropic-ai/claude-code
cd amd-ai-league
claude            # first-run login
```
Optional quality gate: install the ECC plugin (everything-claude-code) if you want /verify, /plan, agents.

## Execution order (one session per command)
1. `/corpus`  — fill corpus.json with 6 verified conflict cases (uses web search)
2. `/build`   — pipeline NOUL→SCORE→CHOICE→guard→generator; DoD: ticker <1.2s on a corpus query
3. `/baseline`— classic agentic RAG on same corpus; real measured numbers → BUILD_SPEC.md §3
4. `/demo-ui` — single-file HTML instrument panel, animates ONLY real run.json data
Then: record the 2-min video per DEMO_SCRIPT.md. Deadline: Oct 27.

## Kickoff prompt (paste this first in Claude Code)

Read BUILD_SPEC.md, CORPUS.md and DEMO_SCRIPT.md fully before doing anything.
This is a hackathon demo (deadline Oct 27): build the demo, not the product — cut anything
not visible in the 120s video. Hard rules: never fake timings or counters; the generator
may output status=unresolved (that is a feature); Python stdlib + httpx only; the UI is a
single HTML file with no build step.
Start with /corpus. When corpus.json passes its definition of done, continue with /build.
Report measured numbers after each command; do not proceed to the next command until the
current one meets its definition of done.

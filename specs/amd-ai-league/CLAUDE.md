# Project: AMD AI League Match 4 — Asymmetric Web Information Retrieval

## What this is
Hackathon entry for Lablab.ai "AMD AI League" Match 4 (Intelligent Web Information Retrieval).
Core thesis: a hybrid asymmetric pipeline where typed discriminative primitives (NOUL=bool gate, SCORE=rank, CHOICE=conflict/verdict) do 90% of the decisions in tens of ms, and the generative LLM does exactly ONE call on 2-3 validated sources. The generative model never classifies; the discriminative never synthesizes.

## Authoritative docs (read before ANY task)
- `BUILD_SPEC.md` — module contracts, metric definitions, stack decisions. Do not deviate from interfaces.
- `CORPUS.md` — demo data rules (verified ground truth, primary sources).
- `DEMO_SCRIPT.md` — the 120s video structure.

## Non-negotiable rules
- Deadline-driven: this is a hackathon demo, NOT production. Cut anything not visible in the 2-minute video.
- Never fake timings or counters. Every number shown in the demo UI comes from real measured values dumped by the pipeline.
- The generator may output `status: unresolved` — that's a feature (typed failure), don't "fix" it.
- Python: stdlib + httpx + a small embedding fallback (TF-IDF ok). No heavy frameworks.
- Generator key: `OPENROUTER_API_KEY` from env. Model: an open-source class (Llama-3.1-8B via OpenRouter).
- No servers to bind in phase 1; single-file HTML UI in the demo phase.

## Key commands (added as tasks are built)
- `python pipeline.py "<query>"` — run the full DAG, prints per-stage ticker
- `python baseline_agent.py "<query>"` — runs the classic agentic baseline for comparison metrics

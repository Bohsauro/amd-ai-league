# AMD AI League — Match 4 · Asymmetric Web Information Retrieval

> **One generative call instead of an agentic loop.** A deterministic, five-stage
> discriminative pipeline (retrieve → filter → rank → reconcile → guard) collapses
> contradictory news coverage into a reconciled, cited answer with a **single LLM
> call** — where the classic agentic baseline burns **5 calls and 46.5k tokens**.

Submission for the **AMD AI League, Match 4 — Intelligent Web Information Retrieval**
(lablab.ai). All numbers in the tables are **measured from real runs**, never estimated:
file `specs/amd-ai-league/VERIFIED_NUMBERS.md` is generated from `backend/run.json` and
`backend/baseline_metrics.json` (`bin/gen-verified-numbers`).

## What it does, concretely

Given a query like *"What EPS did AMD report for Q3 2024?"*, the pipeline:

1. **Pools** a pre-curated corpus of 10 real-world financial conflict cases (53 snippets:
   press releases, earnings calls, 10-Q filings, news, and deliberately noisy SEO junk);
2. **NOUL gate** drops noise/boilerplate/off-topic snippets (~64% of the pool);
3. **SCORE** ranks survivors by relevance × reliability (authority, recency, cross-source
   numeric consistency);
4. **CHOICE** reconciles pairwise figure conflicts — *GAAP $0.47 vs non-GAAP $0.92* — into
   a typed verdict (CONFLICT / RESOLVED / INSUFFICIENT);
5. **GUARD** checks the verdict's confidence against a threshold and refuses to proceed
   when the winning claim lacks primary-source support;
6. **Generator** makes exactly **one** LLM call over the 2–3 best sources and returns a
   JSON verdict with citations — or **skips** ("the generator can refuse").

## Measured results (run of 2026-10-26, provider: Groq)

| | this pipeline | agentic baseline |
|---|---|---|
| LLM calls | **1** | 5 |
| tokens | **1,572** (1,390 prompt + 182 out) | 46,563 (43,127 + 3,436) |
| end-to-end | **440 ms** | 30,570 ms |
| cost (OpenRouter) | not instrumented | $0.0102 (3-run median, printed by baseline) |
| output | CONFLICT · resolved · 3 citations | free prose that collapses GAAP/non-GAAP |

→ **−96.6% tokens · 69.5× faster** · NOUL drops **34 of 53** snippets (64.2%) before any
LLM call (discriminative side: **7 ms**; the single generator call: 433 ms).

Batch throughput (10 parallel live runs, measured): max 526 ms e2e, median 235 ms.

## Architecture

```
query
  -> RETRIEVER   corpus (10 cases, 53 snippets) + optional --live snapshot JSON
  -> NOUL        deterministic gate: keep/drop (noise, boilerplate, off-topic)  -> drop ~64%
  -> SCORE       relevance[0,1] x reliability[0,1] (authority, recency, numeric consistency)
  -> CHOICE      pairwise figure reconcile (GAAP vs non-GAAP, $4B vs $8B, announced vs actual)
  -> GUARD       confidence < 0.60 -> expand / INSUFFICIENT (never fakes a confident answer)
  -> GENERATOR   exactly 1 LLM call, top 2-3 validated sources, typed JSON {answer, citations}
```

The demo UI is a single-file page (`frontend/index.html`) that reads `frontend/run.json` —
no hardcoded numbers, animated counters driven by the measured run.

## Quick start (fresh clone, no API key needed)

```bash
# 1. Verify: the Definition-of-Done gate (corpus, run, baseline, UI, 77 unit tests)
./bin/verify                          # 17 checks, all green

# 2. Watch the demo offline (deterministic, no LLM calls, does not touch run.json)
./bin/demo --offline

# 3. Replay the frozen verified run (the recording fallback if OpenRouter is down)
./bin/demo --frozen

# 4. Live run (needs OPENROUTER_API_KEY in .env; falls back to the frozen run on error)
./bin/demo --freeze                   # 10 cases -> run.json -> frontend/ + ticker

# 5. Serve the demo UI (LAN + Tailscale, never localhost-only)
./bin/demo --serve                    # http://0.0.0.0:8500/index.html
```

Without an API key the live path degrades gracefully: the generator refuses, the runner
detects the operational error and replays the **frozen verified run**, clearly labelled
`FALLBACK CONGELATO` — stale numbers are never relabeled as fresh.

Reproduce the numbers:

```bash
./bin/gen-verified-numbers            # regenerates VERIFIED_NUMBERS.md from run.json + baseline
cd backend
python pipeline.py FC-01 --dump-json  # single-case run -> run.json
python -m pytest                      # 77 unit tests: NOUL, SCORE, GUARD, corpus, pipeline
```

## Corpus — 10 real conflict cases, every URL verified

| case | conflict |
|---|---|
| FC-01 | Intel Q2 2024: GAAP EPS $(0.38) vs non-GAAP $0.02 |
| FC-02 | Broadcom–VMware: $61B equity vs ~$69B incl. debt |
| FC-03 | Boeing CEO transition: announced end-2024 vs actual Aug 8, 2024 |
| FC-04 | AMD Instinct MI325X: 256GB vs 288GB HBM3E |
| FC-05 | Noise/SEO query on NVIDIA revenue (the gate's spam case) |
| FC-06 | Microsoft–Inflection: undisclosed vs $650M vs >$1B (measured INSUFFICIENT → generator refuses) |
| FC-07 | NVIDIA Q3 FY25: GAAP $0.78 vs non-GAAP $0.81 EPS; $35.08B vs $33.16B expected |
| FC-08 | AMD Q3 2024: GAAP $0.47 vs non-GAAP $0.92 EPS |
| FC-09 | iPhone 16 "built for Apple Intelligence" (Sep 20) vs AI shipping Oct 28 |
| FC-10 | Amazon–Anthropic: $4B cumulative (Mar 2024) vs $8B (Nov 2024) |

Every `source_url` was fetched and verified HTTP 200 when the corpus was built (two Apple
launch-period pages are cited as dated Internet Archive snapshots because the live pages
were later rewritten). Source schema, dates and anti-leakage rules are enforced by the
shared validator `backend/corpus_validation.py` — the same module the gate and the tests use.

## Repo layout

```
bin/                 verify (DoD gate), demo (runner + fallback), gen-verified-numbers
backend/             pipeline (6 stages), corpus.json, run.json, 77 unit tests in tests/
frontend/            single-file demo UI + run.json copy
specs/amd-ai-league/ BUILD_SPEC, DEMO_SCRIPT (120s video), VERIFIED_NUMBERS (generated), corpus docs
```

## Honesty notes (what this is and is not)

- **Measured**: all token/latency/cost figures above, from run.json / baseline_metrics.json.
- **Not claimed**: ROCm/AMD-GPU execution (no AMD GPU on the dev box — throughput framing is
  architectural, token/query based); live web retrieval (SerpAPI not used; the "live"
  channel is an optional `--live snapshot.json`); "same answer quality" (no eval harness).
- The latency is dominated by the single generator call (408 of 415 ms): the value shown is
  *calls and tokens*, not discriminator speed.
- The demo video script and its runbook are in `specs/amd-ai-league/DEMO_SCRIPT.md`.

## Docs

- `specs/amd-ai-league/BUILD_SPEC.md` — contracts and architecture
- `specs/amd-ai-league/PLAN.md` — delivery plan
- `specs/amd-ai-league/VERIFIED_NUMBERS.md` — generated, single source for every number
- `STATUS.md` — current state and gotchas
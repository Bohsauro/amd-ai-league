#!/usr/bin/env python3
"""Classic agentic baseline for the AMD AI League demo.

Pattern measured here (BUILD_SPEC section 3): an agentic loop of up to 5 LLM
calls where EVERY call receives the ENTIRE corpus, unfiltered. The model
chooses the next action (re-rank / extract / reconcile / synthesize); the last
call always writes the final answer.

All token counts come from the real `usage` object returned by the API. No
estimates, no fabricated timings. If usage is missing the run fails.

Usage:
    python baseline_agent.py "FC-01"
    python baseline_agent.py "FC-01" --out baseline_metrics.json

`baseline_metrics.json` is written in the frozen schema
(`specs/amd-ai-league/schemas/baseline_metrics.schema.json`, v1.0). Because that
schema sets `additionalProperties: false`, the run-to-run dispersion (median /
min / max over repeated runs) is written to a companion file,
`baseline_metrics_dispersion.json`, instead of being smuggled into the schema
document. Use `--runs N` (default 3) to control the repetition count.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
CORPUS_PATH = SCRIPT_DIR / "corpus.json"
DEFAULT_OUT = SCRIPT_DIR / "baseline_metrics.json"
DEFAULT_DISPERSION_OUT = SCRIPT_DIR / "baseline_metrics_dispersion.json"
SCHEMA_VERSION = "1.0"

OPENROUTER_URL = os.environ.get(
    "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"
)
DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct"
MAX_CALLS = 5

ALLOWED_NEXT = {
    "plan": ["rerank", "extract"],
    "rerank": ["extract", "reconcile"],
    "extract": ["reconcile", "synthesize"],
    "reconcile": ["synthesize"],
    "synthesize": [],
}

ACTION_BRIEF = {
    "plan": (
        "Plan the reconciliation. Identify the query's key figure/claim and list "
        "which snippets look relevant. Do not answer yet. Set next_action to "
        "'rerank' or 'extract'."
    ),
    "rerank": (
        "Re-rank ALL snippets by relevance to the query. Return the ordered ids "
        "(most relevant first) and one short reason per id. Set next_action to "
        "'extract' or 'reconcile'."
    ),
    "extract": (
        "Extract the factual/numeric claims from the snippets that bear on the "
        "query. For every claim give source id, the exact figure/text and a short "
        "quote. Set next_action to 'reconcile' or 'synthesize'."
    ),
    "reconcile": (
        "Compare the extracted claims. Mark agree / disagree / unrelated, flag "
        "conflicting pairs and decide which source is most authoritative. Set "
        "next_action to 'synthesize'."
    ),
    "synthesize": (
        "Write the FINAL answer for the user. Return status 'resolved' or "
        "'unresolved' (use unresolved if the evidence is insufficient), a concise "
        "answer, a confidence in [0,1], and citations as [{source_id, claim_id}]."
    ),
}


def resolve_model() -> str:
    """Use the same model as pipeline.py's generator when it is importable."""
    env_model = os.environ.get("OPENROUTER_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()
    try:
        import generator  # type: ignore

        for name in ("MODEL", "MODEL_NAME", "GENERATOR_MODEL", "DEFAULT_MODEL"):
            value = getattr(generator, name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass
    return DEFAULT_MODEL


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    for key in ("cases", "corpus", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    raise ValueError(f"{path}: cannot find a list of cases")


def resolve_query(raw: str, corpus: list[dict[str, Any]]) -> tuple[str | None, str, list[dict[str, Any]]]:
    """Return (case_id, query, sources) for a case id or a literal query."""
    needle = raw.strip()
    for case in corpus:
        case_id = str(case.get("id", ""))
        if needle.lower() == case_id.lower() or needle.lower() == str(case.get("query", "")).lower():
            return case_id or None, str(case.get("query") or needle), list(case.get("sources") or [])
    return None, needle, []


def resolve_case(
    raw: str, corpus_path: Path
) -> tuple[str | None, str, list[dict[str, Any]], str]:
    """Resolve exactly like pipeline.py (same retriever, same corpus, same live set)."""
    try:
        import retriever  # type: ignore
    except ImportError:
        corpus = load_corpus(corpus_path)
        case_id, query, sources = resolve_query(raw, corpus)
        return case_id, query, sources, "local"

    cases = retriever.load_corpus(corpus_path)
    case, snippets, mode = retriever.select_case(cases, raw)
    snippets = snippets + retriever.load_live_snippets()
    case_id = str(case.get("id")) if case else None
    query = str(case.get("query") or raw) if case else raw.strip()
    return case_id, query, [snippet.to_dict() for snippet in snippets], mode


def snippet_block(sources: list[dict[str, Any]]) -> str:
    """Every snippet, full content, no filtering: the point of the baseline."""
    if not sources:
        return "(no corpus snippets; answer from the query only)"
    parts = []
    for idx, src in enumerate(sources, 1):
        sid = src.get("id", f"S{idx}")
        meta = " | ".join(
            str(src[k])
            for k in ("source_name", "publisher_type", "date", "source_url", "title")
            if src.get(k)
        )
        parts.append(f"[{sid}] {meta}\n{src.get('content', '')}")
    return "\n\n".join(parts)


def build_messages(
    query: str,
    snippets: str,
    scratchpad: list[dict[str, Any]],
    action: str,
    call_no: int,
) -> list[dict[str, str]]:
    system = (
        "You are a classic agentic research assistant doing web information "
        "retrieval. You have at most 5 LLM calls. EVERY call receives the whole "
        "retrieved corpus, unfiltered. Work step by step and keep state in JSON. "
        "Reply with a single JSON object and no markdown fences."
    )
    history = (
        json.dumps(scratchpad, ensure_ascii=False, indent=2)
        if scratchpad
        else "(empty: this is the first call)"
    )
    next_actions = ALLOWED_NEXT.get(action, [])
    next_hint = ", ".join(next_actions) if next_actions else "(none, final answer)"
    user = f"""QUERY
{query}

RETRIEVED CORPUS ({len(snippets.splitlines())} lines, ALL snippets, no filter)
{snippets}

WORK SO FAR (your previous JSON outputs)
{history}

CALL {call_no} OF {MAX_CALLS}
Action for this call: {action}
{ACTION_BRIEF[action]}

Allowed next_action values after this call: {next_hint}
Return JSON with this shape:
{{
  "action": "{action}",
  "result": <object or string with the work for this call>,
  "next_action": <one allowed value or null>
}}
For the synthesize action also include at top level:
  "answer": <string>, "confidence": <number 0..1>,
  "citations": [{{"source_id": "...", "claim_id": "..."}}],
  "status": "resolved" | "unresolved"
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"result": value}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                value = json.loads(text[start : end + 1])
                return value if isinstance(value, dict) else {"result": value}
            except json.JSONDecodeError:
                pass
    return {"action": None, "result": text, "next_action": None}


def call_llm(
    client: httpx.Client,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    call_no: int,
    action: str = "plan",
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """One real LLM call. Returns (parsed_json, usage, latency_ms)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 450 if action == "synthesize" else 1500,
        "response_format": {"type": "json_object"},
        "provider": {"sort": "latency"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost/amd-ai-league",
        "X-Title": "AMD AI League baseline",
    }
    started = time.perf_counter()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.post(OPENROUTER_URL, json=payload, headers=headers)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            data = response.json()
            break
        except Exception as exc:  # noqa: BLE001 - surface after retries
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"LLM call {call_no} failed: {exc}") from exc
    else:  # pragma: no cover - defensive
        raise RuntimeError(f"LLM call {call_no} failed: {last_error}")
    latency_ms = (time.perf_counter() - started) * 1000.0

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM call {call_no}: malformed response: {data}") from exc

    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise RuntimeError(
            f"LLM call {call_no}: response has no usage object; refusing to estimate tokens"
        )
    required = ("prompt_tokens", "completion_tokens")
    missing = [key for key in required if not isinstance(usage.get(key), int)]
    if missing:
        raise RuntimeError(
            f"LLM call {call_no}: usage missing {missing}; refusing to estimate tokens"
        )

    parsed = parse_json(content)
    if "usage" not in parsed and isinstance(data.get("usage"), dict):
        pass
    return parsed, usage, latency_ms


def _candidate_objects(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Final-answer shapes vary: top level, nested under result, or JSON string."""
    out: list[dict[str, Any]] = [obj]
    pending: list[Any] = [obj.get("result"), obj.get("final"), obj.get("output")]
    while pending:
        value = pending.pop(0)
        if isinstance(value, dict):
            if value not in out:
                out.append(value)
            pending.extend([value.get("result"), value.get("final")])
        elif isinstance(value, str):
            parsed = parse_json(value)
            if isinstance(parsed, dict) and parsed not in out:
                out.append(parsed)
    return out


def extract_final(final: dict[str, Any]) -> tuple[str, list[Any], str, Any]:
    candidates = _candidate_objects(final)
    answer: Any = None
    status = None
    confidence = None
    citations: list[Any] = []
    for candidate in candidates:
        if answer is None:
            value = candidate.get("answer")
            if isinstance(value, dict):
                value = value.get("text") or value.get("answer") or json.dumps(
                    value, ensure_ascii=False
                )
            if isinstance(value, str) and value.strip():
                answer = value.strip()
        if status is None and candidate.get("status") in ("resolved", "unresolved"):
            status = candidate["status"]
        if confidence is None and isinstance(candidate.get("confidence"), (int, float)):
            confidence = candidate["confidence"]
        if not citations and isinstance(candidate.get("citations"), list):
            citations = candidate["citations"]
    if answer is None:
        answer = json.dumps(final.get("result", final), ensure_ascii=False)
    return answer, citations, status or "unresolved", confidence


def pick_next(action: str, parsed: dict[str, Any], call_no: int) -> str:
    if call_no >= MAX_CALLS:
        return "synthesize"
    proposed = parsed.get("next_action")
    allowed = ALLOWED_NEXT.get(action, [])
    if isinstance(proposed, str) and proposed in allowed:
        return proposed
    if allowed:
        return allowed[0]
    return "synthesize"


PATTERN = (
    f"classic agentic loop: up to {MAX_CALLS} LLM calls, "
    "ALL corpus snippets sent on every call, no filtering"
)
GPU_SEC_NOTE = (
    "not measurable in this run: hosted OpenRouter API, no AMD GPU attached; "
    "do not present as a measured GPU figure"
)


def run_once(
    query: str,
    case_id: str | None,
    sources: list[dict[str, Any]],
    selection_mode: str = "case_id",
    run_no: int = 1,
    run_total: int = 1,
) -> dict[str, Any]:
    """One full agentic baseline run. All numbers come from real API usage."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    model = resolve_model()
    snippets = snippet_block(sources)

    print(
        f"BASELINE run {run_no}/{run_total}: query={case_id or query!r} "
        f"sources={len(sources)} model={model}"
    )
    print(f"pattern: classic agentic loop, up to {MAX_CALLS} calls, FULL corpus each call")

    calls: list[dict[str, Any]] = []
    scratchpad: list[dict[str, Any]] = []
    action = "plan"
    total_started = time.perf_counter()
    final_parsed: dict[str, Any] = {}

    with httpx.Client(timeout=120.0) as client:
        for call_no in range(1, MAX_CALLS + 1):
            if call_no == MAX_CALLS:
                action = "synthesize"
            messages = build_messages(query, snippets, scratchpad, action, call_no)
            parsed, usage, latency_ms = call_llm(
                client, api_key, model, messages, call_no, action
            )
            input_tokens = usage["prompt_tokens"]
            output_tokens = usage["completion_tokens"]
            record = {
                "n": call_no,
                "purpose": action,
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "ms": round(latency_ms, 2),
                "cost_usd": usage.get("cost"),
                "next_action": None,
            }
            calls.append(record)
            scratchpad.append({"call": call_no, "action": action, "output": parsed})
            print(
                f"  call {call_no}/{MAX_CALLS} action={action:<10} "
                f"{latency_ms:8.1f}ms  in={input_tokens:<6} out={output_tokens:<5}"
            )
            next_action = pick_next(action, parsed, call_no)
            record["next_action"] = next_action
            if call_no >= MAX_CALLS:
                final_parsed = parsed
                break
            action = next_action

    total_latency_ms = (time.perf_counter() - total_started) * 1000.0

    answer, citations, status, confidence = extract_final(final_parsed)
    costs = [c["cost_usd"] for c in calls if isinstance(c["cost_usd"], (int, float))]
    total_cost = round(sum(costs), 8) if costs else None

    return {
        "case_id": case_id,
        "query": query,
        "model": model,
        "pattern": PATTERN,
        "corpus_sources": len(sources),
        "selection_mode": selection_mode,
        "calls": calls,
        "totals": {
            "llm_calls": len(calls),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            "e2e_ms": round(total_latency_ms, 2),
        },
        "answer": answer,
        "status": status,
        "confidence": confidence,
        "citations": citations,
        "cost_usd_total": total_cost,
        "raw_final": final_parsed,
    }


def _total_tokens(result: dict[str, Any]) -> int:
    return result["totals"]["prompt_tokens"] + result["totals"]["completion_tokens"]


def select_median_run(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Representative run: median by total tokens, tie-broken by e2e latency."""
    ordered = sorted(results, key=lambda r: (_total_tokens(r), r["totals"]["e2e_ms"]))
    return ordered[(len(ordered) - 1) // 2]


def schema_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """Project a measured run onto the frozen baseline_metrics schema v1.0."""
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": result["case_id"] or "",
        "query": result["query"],
        "model": result["model"],
        "calls": [
            {
                "n": call["n"],
                "purpose": call["purpose"],
                "prompt_tokens": call["prompt_tokens"],
                "completion_tokens": call["completion_tokens"],
                "ms": call["ms"],
            }
            for call in result["calls"]
        ],
        "totals": dict(result["totals"]),
        "answer": result["answer"],
    }


def dispersion_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Run-to-run spread, kept outside the schema document (see module docstring)."""
    tokens = [_total_tokens(r) for r in results]
    latencies = [r["totals"]["e2e_ms"] for r in results]
    costs = [r["cost_usd_total"] for r in results if isinstance(r["cost_usd_total"], (int, float))]
    return {
        "case_id": results[0]["case_id"],
        "model": results[0]["model"],
        "pattern": results[0]["pattern"],
        "corpus_sources": results[0]["corpus_sources"],
        "selection_mode": results[0]["selection_mode"],
        "runs": [
            {"n": i + 1, "total_tokens": tokens[i], "e2e_ms": latencies[i]}
            for i in range(len(results))
        ],
        "total_tokens": {
            "median": statistics.median(tokens),
            "min": min(tokens),
            "max": max(tokens),
        },
        "total_latency_ms": {
            "median": statistics.median(latencies),
            "min": min(latencies),
            "max": max(latencies),
        },
        "cost_usd_total": round(sum(costs), 8) if costs else None,
        "gpu_sec_per_query": None,
        "gpu_sec_note": GPU_SEC_NOTE,
        "note": (
            "Dispersion lives here, not in baseline_metrics.json: the frozen schema "
            "(additionalProperties: false) only allows schema_version, case_id, query, "
            "model, calls, totals, answer."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classic agentic baseline on the demo corpus")
    parser.add_argument("query", help="corpus case id (e.g. FC-01) or literal query")
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--dispersion-out",
        type=Path,
        default=None,
        help="dispersion file path (default: next to --out; backend/ for the default --out)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="repeated runs used for the dispersion interval (default 3; use 1 for a quick check)",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.dispersion_out is not None:
        dispersion_out = args.dispersion_out
    elif args.out == DEFAULT_OUT:
        dispersion_out = DEFAULT_DISPERSION_OUT
    else:
        dispersion_out = args.out.with_name(f"{args.out.stem}_dispersion.json")

    case_id, query, sources, selection_mode = resolve_case(args.query, args.corpus)
    results = [
        run_once(query, case_id, sources, selection_mode, i + 1, args.runs)
        for i in range(args.runs)
    ]

    chosen = select_median_run(results)
    metrics = schema_metrics(chosen)
    args.out.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.runs > 1:
        dispersion = dispersion_metrics(results)
        dispersion_out.write_text(
            json.dumps(dispersion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print("\nFINAL ANSWER (median run)")
    print(metrics["answer"])
    print(
        f"\nBASELINE TOTAL: {metrics['totals']['e2e_ms']:.1f}ms | "
        f"calls={metrics['totals']['llm_calls']} | "
        f"tokens={metrics['totals']['prompt_tokens'] + metrics['totals']['completion_tokens']} "
        f"(in={metrics['totals']['prompt_tokens']}, out={metrics['totals']['completion_tokens']})"
    )
    if chosen["cost_usd_total"] is not None:
        print(f"cost=${chosen['cost_usd_total']:.8f}")
    if args.runs > 1:
        tokens = [_total_tokens(r) for r in results]
        latencies = [r["totals"]["e2e_ms"] for r in results]
        print(
            f"dispersion over {args.runs} runs: "
            f"tokens median={statistics.median(tokens)} [{min(tokens)}..{max(tokens)}] | "
            f"latency median={statistics.median(latencies):.1f}ms "
            f"[{min(latencies):.1f}..{max(latencies):.1f}]"
        )
        print(f"dispersion written to {dispersion_out}")
    print(f"metrics written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

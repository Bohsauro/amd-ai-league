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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
CORPUS_PATH = SCRIPT_DIR / "corpus.json"
DEFAULT_OUT = SCRIPT_DIR / "baseline_metrics.json"

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
    try:
        import generator  # type: ignore

        for name in ("MODEL", "MODEL_NAME", "GENERATOR_MODEL", "DEFAULT_MODEL"):
            value = getattr(generator, name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)


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
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """One real LLM call. Returns (parsed_json, usage, latency_ms)."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 700,
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


def run(query: str, case_id: str | None, sources: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    model = resolve_model()
    snippets = snippet_block(sources)

    print(f"BASELINE: query={case_id or query!r} sources={len(sources)} model={model}")
    print(f"pattern: classic agentic loop, up to {MAX_CALLS} calls, FULL corpus each call")

    calls: list[dict[str, Any]] = []
    scratchpad: list[dict[str, Any]] = []
    action = "plan"
    total_started = time.perf_counter()

    with httpx.Client(timeout=120.0) as client:
        for call_no in range(1, MAX_CALLS + 1):
            if call_no == MAX_CALLS:
                action = "synthesize"
            messages = build_messages(query, snippets, scratchpad, action, call_no)
            parsed, usage, latency_ms = call_llm(
                client, api_key, model, messages, call_no
            )
            input_tokens = usage["prompt_tokens"]
            output_tokens = usage["completion_tokens"]
            total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
            record = {
                "call": call_no,
                "action": action,
                "latency_ms": round(latency_ms, 2),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
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

    final = final_parsed
    answer = final.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        result = final.get("result")
        answer = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    citations = final.get("citations") if isinstance(final.get("citations"), list) else []
    status = final.get("status") if final.get("status") in ("resolved", "unresolved") else "unresolved"
    confidence = final.get("confidence")

    costs = [c["cost_usd"] for c in calls if isinstance(c["cost_usd"], (int, float))]
    total_cost = round(sum(costs), 8) if costs else None

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "query_id": case_id,
        "query": query,
        "model": model,
        "pattern": (
            f"classic agentic loop: up to {MAX_CALLS} LLM calls, "
            "ALL corpus snippets sent on every call, no filtering"
        ),
        "corpus_sources": len(sources),
        "total_latency_ms": round(total_latency_ms, 2),
        "llm_calls": len(calls),
        "total_input_tokens": sum(c["input_tokens"] for c in calls),
        "total_output_tokens": sum(c["output_tokens"] for c in calls),
        "total_tokens": sum(c["total_tokens"] for c in calls),
        "calls": calls,
        "cost_usd_total": total_cost,
        "gpu_sec_per_query": None,
        "gpu_sec_note": (
            "not measurable in this run: hosted OpenRouter API, no AMD GPU attached; "
            "do not present as a measured GPU figure"
        ),
        "final_answer": answer,
        "final_status": status,
        "final_confidence": confidence,
        "final_citations": citations,
        "final_raw": final,
    }
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classic agentic baseline on the demo corpus")
    parser.add_argument("query", help="corpus case id (e.g. FC-01) or literal query")
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    corpus = load_corpus(args.corpus)
    case_id, query, sources = resolve_query(args.query, corpus)
    metrics = run(query, case_id, sources)

    args.out.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("\nFINAL ANSWER")
    print(metrics["final_answer"])
    print(
        f"\nBASELINE TOTAL: {metrics['total_latency_ms']:.1f}ms | "
        f"calls={metrics['llm_calls']} | "
        f"tokens={metrics['total_tokens']} "
        f"(in={metrics['total_input_tokens']}, out={metrics['total_output_tokens']})"
    )
    if metrics["cost_usd_total"] is not None:
        print(f"cost=${metrics['cost_usd_total']:.8f}")
    print(f"metrics written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

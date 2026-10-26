from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from choice import ChoiceResult, decide
from config import E2E_BUDGET_MS, EXPAND_K, MAX_EXPANSIONS, TOP_K, TOP_K_MAX, TOP_K_MIN
from generator import generate
from guard import GuardResult, check
from noul import NoulResult, gate
from retriever import DEFAULT_CORPUS_PATH, load_corpus, load_live_snippets, pool_snippets, select_case
from score import ScoreResult, rank
from textutil import token_estimate

BASE_DIR = Path(__file__).resolve().parent
RUN_JSON_PATH = BASE_DIR / "run.json"
BUDGET_MS = E2E_BUDGET_MS


def _stage_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _score_to_dict(result: ScoreResult, used_in_generation: bool) -> dict[str, Any]:
    data = result.to_dict()
    data["used_in_generation"] = used_in_generation
    return data


def _source_view(
    noul_result: NoulResult,
    score_result: ScoreResult | None,
    used_in_generation: bool,
) -> dict[str, Any]:
    snippet = noul_result.snippet
    content = snippet.content.strip()
    view = {
        "id": snippet.id,
        "source_name": snippet.source_name,
        "publisher_type": snippet.publisher_type,
        "date": snippet.date,
        "source_url": snippet.source_url,
        "title": snippet.title,
        "content_preview": content[:600] + ("…" if len(content) > 600 else ""),
        "tokens_est": token_estimate(f"{snippet.title} {snippet.content}"),
        "keep": noul_result.keep,
        "reason": noul_result.reason,
        "noul_confidence": round(noul_result.confidence, 4),
        "similarity": round(noul_result.similarity, 4),
        "rank": score_result.rank if score_result else None,
        "relevance": round(score_result.relevance, 4) if score_result else None,
        "reliability": round(score_result.reliability, 4) if score_result else None,
        "score": round(score_result.score, 4) if score_result else None,
        "used_in_generation": used_in_generation,
    }
    return view


def _apply_insufficient(choice: ChoiceResult, guard_result: GuardResult) -> ChoiceResult:
    choice.label = guard_result.label
    choice.verdict = guard_result.verdict
    return choice


def run(
    query_arg: str,
    corpus_path: str | Path | None = None,
    live_path: str | Path | None = None,
    top_k: int = TOP_K,
    expand_k: int = EXPAND_K,
    offline: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()

    retriever_started = time.perf_counter()
    cases = load_corpus(corpus_path or DEFAULT_CORPUS_PATH)
    case, _case_snippets, mode = select_case(cases, query_arg)
    if mode == "missing_case":
        raise ValueError(f"case inesistente: {query_arg}")
    snippets = pool_snippets(cases) + load_live_snippets(live_path)
    retriever_ms = _stage_ms(retriever_started)
    query = str(case.get("query") or query_arg).strip() if case and mode in {"case_id", "case_query"} else query_arg
    case_id = str(case.get("id") or "") if case else ""

    noul_started = time.perf_counter()
    noul_results = gate(snippets, query)
    noul_ms = _stage_ms(noul_started)
    kept = [result for result in noul_results if result.keep]
    dropped = [result for result in noul_results if not result.keep]

    score_started = time.perf_counter()
    scoring_candidates = [
        result for result in kept if not case_id or result.snippet.case_id == case_id
    ]
    candidate_cap = max(top_k, expand_k, min(8, len(scoring_candidates)))
    all_ranked = rank(scoring_candidates, query, top_k=candidate_cap)
    score_ms = _stage_ms(score_started)
    current = all_ranked[:top_k]

    choice_started = time.perf_counter()
    choice = decide(current, query)
    choice_ms = _stage_ms(choice_started)

    guard_started = time.perf_counter()
    guard_result = check(choice, len(all_ranked), len(current), already_expanded=False)
    expanded = False
    if guard_result.action == "expand" and MAX_EXPANSIONS >= 1:
        expanded = True
        extra_choice_started = time.perf_counter()
        current = all_ranked[: min(expand_k, len(all_ranked))]
        choice = decide(current, query)
        choice_ms += _stage_ms(extra_choice_started)
        guard_result = check(choice, len(all_ranked), len(current), already_expanded=True)
    if guard_result.action == "insufficient":
        choice = _apply_insufficient(choice, guard_result)
    guard_ms = _stage_ms(guard_started)

    generator_started = time.perf_counter()
    skip_reason = "offline mode" if offline else "guard: evidence insufficient"
    generation = generate(
        query,
        choice,
        current,
        skip=offline or not guard_result.sufficient,
        skip_reason=skip_reason,
    )
    generator_ms = _stage_ms(generator_started)

    used_ids = {citation["source_id"] for citation in generation.get("citations", [])}
    if not used_ids and generation.get("called"):
        used_ids = set(generation.get("selected_source_ids") or [result.snippet.id for result in current[:3]])
    score_by_id = {result.snippet.id: result for result in all_ranked}
    sources = [
        _source_view(noul_result, score_by_id.get(noul_result.snippet.id), noul_result.snippet.id in used_ids)
        for noul_result in noul_results
    ]
    ranking = [
        _score_to_dict(result, result.snippet.id in used_ids)
        for result in all_ranked
    ]

    total_ms = round((time.perf_counter() - started) * 1000.0, 3)
    raw_tokens_est = sum(token_estimate(f"{s.title} {s.content}") for s in snippets)
    kept_tokens_est = sum(token_estimate(f"{r.snippet.title} {r.snippet.content}") for r in kept)
    usage = generation.get("usage") or {}
    generator_total = usage.get("total_tokens")
    generator_prompt = usage.get("prompt_tokens")
    generator_completion = usage.get("completion_tokens")
    generator_called = bool(generation.get("called"))
    if generator_called and isinstance(generator_total, int):
        tokens_gen_consumed = generator_total
        tokens_gen_measured = True
    elif generator_called:
        tokens_gen_consumed = int(generation.get("prompt_tokens_est") or 0)
        tokens_gen_measured = False
    else:
        tokens_gen_consumed = 0
        tokens_gen_measured = False
    if generator_called:
        savings_base = generator_prompt if isinstance(generator_prompt, int) else tokens_gen_consumed
        saved = raw_tokens_est - savings_base
        saved_pct = (saved / raw_tokens_est * 100.0) if raw_tokens_est else 0.0
        saved_pct = round(saved_pct, 1)
    else:
        saved = 0
        saved_pct = 0.0

    run_data: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "query_arg": query_arg,
        "case_id": case_id,
        "case_subject": str(case.get("subject") or "") if case else "",
        "selection_mode": mode,
        "offline": offline,
        "model": generation.get("model"),
        "stages": {
            "retriever": {
                "ms": retriever_ms,
                "snippets": len(snippets),
            },
            "noul": {
                "ms": noul_ms,
                "total": len(noul_results),
                "kept": len(kept),
                "dropped": len(dropped),
                "drop_pct": round(len(dropped) / len(noul_results) * 100.0, 1) if noul_results else 0.0,
                "empty_corpus": not kept,
                "decisions": [result.to_dict() for result in noul_results],
            },
            "score": {
                "ms": score_ms,
                "ranked_count": len(all_ranked),
                "top_k": len(current),
                "ranking": ranking,
            },
            "choice": {
                "ms": choice_ms,
                **choice.to_dict(),
            },
            "guard": {
                "ms": guard_ms,
                "expanded": expanded,
                "expansions_used": 1 if expanded else 0,
                **guard_result.to_dict(),
            },
            "generator": {
                "ms": generator_ms,
                **generation,
            },
        },
        "sources": sources,
        "total_ms": total_ms,
        "budget_ms": BUDGET_MS,
        "within_budget": total_ms < BUDGET_MS,
        "gen_calls": 1 if generator_called else 0,
        "token_count_method": "usage" if tokens_gen_measured else "estimate",
        "totals": {
            "e2e_ms": total_ms,
            "llm_calls": 1 if generator_called else 0,
            "gen_calls": 1 if generator_called else 0,
            "prompt_tokens": generator_prompt if isinstance(generator_prompt, int) else 0,
            "completion_tokens": generator_completion if isinstance(generator_completion, int) else 0,
            "token_count_method": "usage" if tokens_gen_measured else "estimate",
        },
        "tokens": {
            "raw_est": raw_tokens_est,
            "kept_est": kept_tokens_est,
            "curated_est": int(generation.get("prompt_tokens_est") or 0),
            "generator_prompt": generator_prompt,
            "generator_completion": generator_completion,
            "generator_total": generator_total,
            "gen_consumed": tokens_gen_consumed,
            "gen_consumed_measured": tokens_gen_measured,
            "saved": saved,
            "saved_pct": round(saved_pct, 1),
            "estimate_method": "chars/4",
        },
        "ticker": {},
    }
    run_data["ticker"] = _ticker_lines(run_data)
    return run_data


def _ticker_lines(data: dict[str, Any]) -> dict[str, str]:
    stages = data["stages"]
    noul = stages["noul"]
    score = stages["score"]
    choice = stages["choice"]
    guard = stages["guard"]
    generator = stages["generator"]
    tokens = data["tokens"]

    if choice["label"] == "CONFLICT" and choice["conflict_pairs"]:
        pair = choice["conflict_pairs"][0]
        choice_label = f"CONFLICT {pair['a']} vs {pair['b']}"
    elif choice["label"] == "RESOLVED":
        choice_label = f"RESOLVED {len(choice['evidence'])} fonti"
    else:
        choice_label = choice["label"]

    if guard["action"] == "insufficient":
        guard_label = f"INSUFFICIENT (conf {guard['confidence']:.2f})"
    elif guard["expanded"]:
        guard_label = f"pass dopo expand (conf {guard['confidence']:.2f})"
    else:
        guard_label = f"pass (conf {guard['confidence']:.2f})"

    if generator.get("called"):
        status = generator.get("status")
        if status == "resolved":
            gen_label = f"resolved | {len(generator.get('citations') or [])} citations"
        else:
            error = (generator.get("error") or "no evidence").split("\n")[0][:80]
            gen_label = f"{status} | {error}"
    else:
        reason = (generator.get("error") or "guard insufficient").split("\n")[0][:80]
        gen_label = f"skipped | {reason}"

    measured = tokens.get("gen_consumed_measured")
    consumed = tokens.get("gen_consumed", 0)
    if not generator.get("called"):
        consumed_label = "0"
    elif measured:
        consumed_label = f"{consumed}"
    else:
        consumed_label = f"~{consumed} (est)"
    raw_label = f"{tokens.get('raw_est', 0)}"
    saved_pct = float(tokens.get("saved_pct", 0.0))
    if saved_pct == 0:
        savings_label = "0%"
    elif saved_pct > 0:
        savings_label = f"-{saved_pct:.0f}%"
    else:
        savings_label = f"+{abs(saved_pct):.0f}% overhead"
    return {
        "noul": f"NOUL: {noul['kept']}/{noul['total']} keep ({noul['dropped']} drop)",
        "score": f"SCORE: top{score['top_k']} ordinati",
        "choice": f"CHOICE: {choice_label}",
        "guard": f"GUARD: {guard_label}",
        "generator": f"GEN: {gen_label}",
        "total": (
            f"TOTAL: {data['total_ms']:.0f}ms | tokens_gen_consumed: {consumed_label} | "
            f"tokens_crud_est: {raw_label} ({savings_label})"
        ),
    }


def print_ticker(data: dict[str, Any]) -> None:
    stages = data["stages"]
    ticker = data["ticker"]
    print(f"{ticker['noul']:<42} [{stages['noul']['ms']:.0f}ms]")
    print(f"{ticker['score']:<42} [{stages['score']['ms']:.0f}ms]")
    print(f"{ticker['choice']:<42} [{stages['choice']['ms']:.0f}ms]")
    print(f"{ticker['guard']:<42} [{stages['guard']['ms']:.0f}ms]")
    print(f"{ticker['generator']:<42} [{stages['generator']['ms']:.0f}ms]")
    print(ticker["total"])
    if not data["within_budget"]:
        print(
            f"WARN: total {data['total_ms']:.0f}ms over budget {data['budget_ms']:.0f}ms",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AMD AI League asymmetric retrieval pipeline")
    parser.add_argument("query", nargs="?", default="FC-01", help="case id (FC-01) or free query")
    parser.add_argument("--dump-json", action="store_true", help=f"scrive {RUN_JSON_PATH.name}")
    parser.add_argument("--corpus", default=None, help="path alternativo a corpus.json")
    parser.add_argument("--live", default=None, help="JSON opzionale con risultati live")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="candidati passati a CHOICE (5-8)")
    parser.add_argument("--expand-k", type=int, default=EXPAND_K, help="candidati dopo espansione GUARD")
    parser.add_argument("--offline", action="store_true", help="salta la chiamata al generatore")
    args = parser.parse_args(argv)
    if not TOP_K_MIN <= args.top_k <= TOP_K_MAX:
        print(f"ERROR: --top-k fuori range {TOP_K_MIN}-{TOP_K_MAX}: {args.top_k}", file=sys.stderr)
        return 2
    if args.expand_k < args.top_k:
        print("ERROR: --expand-k deve essere >= --top-k", file=sys.stderr)
        return 2

    try:
        data = run(
            args.query,
            corpus_path=args.corpus,
            live_path=args.live,
            top_k=args.top_k,
            expand_k=args.expand_k,
            offline=args.offline,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_ticker(data)
    if args.dump_json:
        RUN_JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"run.json -> {RUN_JSON_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

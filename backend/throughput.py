from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pipeline
from retriever import load_corpus

BASE_DIR = Path(__file__).resolve().parent
RUN_JSON_PATH = BASE_DIR / "run.json"


def _measure(case_id: str, offline: bool) -> tuple[str, float]:
    started = time.perf_counter()
    pipeline.run(case_id, offline=offline)
    return case_id, round((time.perf_counter() - started) * 1000.0, 1)


def measure(
    runs: int,
    offline: bool,
    corpus_path: str | Path | None = None,
    workers: int | None = None,
) -> dict[str, Any]:
    if runs < 1:
        raise ValueError("--runs deve essere >= 1")
    cases = load_corpus(corpus_path)
    case_ids = [str(case.get("id")) for case in cases if case.get("id")]
    if not case_ids:
        raise ValueError("corpus senza casi")
    jobs = [case_ids[index % len(case_ids)] for index in range(runs)]
    concurrency = min(workers or runs, runs)

    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        measured = list(pool.map(lambda case_id: _measure(case_id, offline), jobs))
    wall_ms = round((time.perf_counter() - wall_started) * 1000.0, 1)

    results = [
        {"query_id": case_id, "e2e_ms": e2e_ms}
        for case_id, e2e_ms in measured
    ]
    latencies = [e2e_ms for _, e2e_ms in measured]
    mode = "offline" if offline else "live"
    note = (
        f"{mode} parallel batch, {runs} runs, concurrency {concurrency}"
        + (" (generator skipped)" if offline else " (generator called where guard passes)")
    )
    return {
        "mode": mode,
        "n_runs": runs,
        "concurrency": concurrency,
        "wall_ms": wall_ms,
        "median_e2e_ms": round(statistics.median(latencies), 1),
        "max_e2e_ms": max(latencies),
        "results": results,
        "note": note,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure parallel pipeline throughput into run.json")
    parser.add_argument("--runs", type=int, default=10, help="numero di run paralleli (default 10)")
    parser.add_argument("--workers", type=int, default=None, help="worker concorrenti (default = runs)")
    parser.add_argument("--live", action="store_true", help="chiama anche il generatore (default: offline)")
    parser.add_argument("--corpus", default=None, help="path alternativo a corpus.json")
    parser.add_argument("--input", default=str(RUN_JSON_PATH), help="run.json da arricchire")
    parser.add_argument("--output", default=None, help="run.json di uscita (default: stesso di --input)")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    try:
        payload = measure(args.runs, offline=not args.live, corpus_path=args.corpus, workers=args.workers)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    data = json.loads(input_path.read_text(encoding="utf-8"))
    data["throughput"] = payload
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"THROUGHPUT: {payload['n_runs']} runs · concurrency {payload['concurrency']} · "
        f"{payload['mode']} · median {payload['median_e2e_ms']}ms · max {payload['max_e2e_ms']}ms · "
        f"wall {payload['wall_ms']}ms"
    )
    print(f"throughput -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Test di integrazione della pipeline (modalita' offline, senza rete).

La modalita' offline salta il generatore: e' il percorso usato dal fallback per
la registrazione, quindi deve produrre un run.json completo e valido.
"""

from __future__ import annotations

import json

import pytest

from config import E2E_BUDGET_MS, TOP_K
from pipeline import main, print_ticker, run


@pytest.fixture(scope="module")
def offline_run():
    return run("FC-01", offline=True)


def test_offline_run_marks_itself_offline(offline_run):
    assert offline_run["offline"] is True
    assert offline_run["selection_mode"] == "case_id"
    assert offline_run["case_id"] == "FC-01"


def test_offline_run_skips_the_generator(offline_run):
    generator = offline_run["stages"]["generator"]
    assert generator["called"] is False
    assert generator["status"] == "skipped"
    assert offline_run["gen_calls"] == 0
    assert offline_run["totals"]["llm_calls"] == 0


def test_offline_run_has_all_stages(offline_run):
    assert set(offline_run["stages"]) == {
        "retriever",
        "noul",
        "score",
        "choice",
        "guard",
        "generator",
    }


def test_offline_run_respects_budget(offline_run):
    assert isinstance(offline_run["total_ms"], (int, float))
    assert offline_run["total_ms"] < E2E_BUDGET_MS
    assert offline_run["within_budget"] is True
    assert offline_run["budget_ms"] == E2E_BUDGET_MS


def test_offline_run_noul_counts_are_consistent(offline_run):
    noul = offline_run["stages"]["noul"]
    assert noul["total"] == noul["kept"] + noul["dropped"]
    assert noul["total"] > 0
    assert len(noul["decisions"]) == noul["total"]


def test_offline_run_ranking_is_capped_by_top_k(offline_run):
    score = offline_run["stages"]["score"]
    assert score["top_k"] <= TOP_K
    assert len(offline_run["stages"]["score"]["ranking"]) >= score["top_k"]
    ranks = [item["rank"] for item in offline_run["stages"]["score"]["ranking"]]
    assert ranks == sorted(ranks)


def test_offline_run_tokens_are_zero_and_estimates_present(offline_run):
    tokens = offline_run["tokens"]
    assert tokens["gen_consumed"] == 0
    assert tokens["gen_consumed_measured"] is False
    assert tokens["raw_est"] > 0
    assert tokens["kept_est"] > 0
    assert tokens["raw_est"] >= tokens["kept_est"]


def test_offline_run_ticker_has_all_lines(offline_run):
    ticker = offline_run["ticker"]
    assert set(ticker) == {"noul", "score", "choice", "guard", "generator", "total"}
    assert ticker["noul"].startswith("NOUL:")
    assert ticker["generator"].startswith("GEN: skipped")


def test_offline_run_is_json_serialisable(offline_run):
    payload = json.dumps(offline_run, ensure_ascii=False)
    assert len(payload) > 1000
    assert json.loads(payload)["case_id"] == "FC-01"


def test_print_ticker_writes_six_lines(offline_run, capsys):
    print_ticker(offline_run)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 6
    assert out[-1].startswith("TOTAL:")


def test_missing_case_raises_value_error():
    with pytest.raises(ValueError, match="case inesistente"):
        run("FC-99", offline=True)


def test_free_query_still_runs():
    data = run("who won the 2022 world cup", offline=True)
    assert data["selection_mode"] == "free_query"
    assert data["case_id"] == ""
    assert data["stages"]["noul"]["total"] > 0


def test_top_k_out_of_range_is_rejected_by_cli(capsys):
    exit_code = main(["FC-01", "--top-k", "3", "--offline"])
    assert exit_code == 2
    assert "fuori range" in capsys.readouterr().err


def test_expand_k_smaller_than_top_k_is_rejected_by_cli(capsys):
    exit_code = main(["FC-01", "--top-k", "7", "--expand-k", "5", "--offline"])
    assert exit_code == 2
    assert "expand-k" in capsys.readouterr().err

"""Test dell'ordinamento SCORE (relevance x reliability).

Verificano: esclusione degli snippet scartati da NOUL, ordinamento decrescente
per score, numerazione dei rank, tie-break deterministico per id, cap top_k e
peso dell'autorita' del publisher sulla reliability.
"""

from __future__ import annotations

from noul import NoulResult
from retriever import Snippet
from score import rank

QUERY = "AMD Instinct MI325X memory capacity"

HOT = (
    "AMD Instinct MI325X memory capacity is 256GB of HBM3E. The MI325X memory "
    "capacity doubles the previous generation and AMD said the Instinct MI325X "
    "ships with 256GB HBM3E memory capacity for inference workloads."
)
WARM = (
    "AMD described the Instinct MI325X accelerator in a briefing and mentioned "
    "the memory capacity alongside bandwidth figures for large model inference."
)
COLD = (
    "The company also discussed supply agreements with several server vendors "
    "and repeated its full year outlook for the data center business unit."
)


def make_snippet(snippet_id: str, content: str, publisher_type: str = "press") -> Snippet:
    return Snippet(
        id=snippet_id,
        source_url="https://real-outlet.com/story",
        source_name="Real Outlet",
        publisher_type=publisher_type,
        date="2024-10-10",
        content=content,
        title="AMD Instinct MI325X update",
    )


def kept(snippet: Snippet, similarity: float = 0.5) -> NoulResult:
    return NoulResult(
        snippet=snippet,
        keep=True,
        confidence=0.8,
        reason="keep",
        similarity=similarity,
        signals={},
    )


def dropped(snippet: Snippet) -> NoulResult:
    return NoulResult(
        snippet=snippet,
        keep=False,
        confidence=0.9,
        reason="spam",
        similarity=0.1,
        signals={},
    )


def test_empty_input_returns_empty_list():
    assert rank([], QUERY) == []


def test_only_dropped_results_returns_empty_list():
    assert rank([dropped(make_snippet("S1", HOT))], QUERY) == []


def test_scores_are_sorted_descending():
    results = rank(
        [
            kept(make_snippet("FC-01-S3", COLD), 0.1),
            kept(make_snippet("FC-01-S1", HOT), 0.9),
            kept(make_snippet("FC-01-S2", WARM), 0.5),
        ],
        QUERY,
    )
    scores = [result.score for result in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0].snippet.id == "FC-01-S1"


def test_ranks_are_sequential_from_one():
    results = rank(
        [
            kept(make_snippet("FC-01-S1", HOT), 0.9),
            kept(make_snippet("FC-01-S2", WARM), 0.5),
            kept(make_snippet("FC-01-S3", COLD), 0.1),
        ],
        QUERY,
    )
    assert [result.rank for result in results] == list(range(1, len(results) + 1))


def test_top_k_caps_results_but_keeps_best():
    noul_results = [
        kept(make_snippet("FC-01-S1", HOT), 0.9),
        kept(make_snippet("FC-01-S2", WARM), 0.5),
        kept(make_snippet("FC-01-S3", COLD), 0.1),
    ]
    results = rank(noul_results, QUERY, top_k=2)
    assert len(results) == 2
    assert [result.rank for result in results] == [1, 2]
    assert results[0].snippet.id == "FC-01-S1"


def test_identical_snippets_tie_break_by_id():
    first = rank(
        [kept(make_snippet("FC-01-S2", HOT)), kept(make_snippet("FC-01-S1", HOT))],
        QUERY,
    )
    second = rank(
        [kept(make_snippet("FC-01-S1", HOT)), kept(make_snippet("FC-01-S2", HOT))],
        QUERY,
    )
    assert [result.snippet.id for result in first] == ["FC-01-S1", "FC-01-S2"]
    assert [result.snippet.id for result in first] == [result.snippet.id for result in second]


def test_official_publisher_has_higher_reliability_than_blog():
    results = rank(
        [
            kept(make_snippet("FC-01-S1", HOT, publisher_type="official")),
            kept(make_snippet("FC-01-S2", HOT, publisher_type="blog")),
        ],
        QUERY,
    )
    by_id = {result.snippet.id: result for result in results}
    assert by_id["FC-01-S1"].reliability > by_id["FC-01-S2"].reliability
    assert by_id["FC-01-S1"].reliability_breakdown["authority"] == 1.0
    assert by_id["FC-01-S2"].reliability_breakdown["authority"] == 0.35


def test_relevance_and_reliability_are_bounded():
    results = rank(
        [
            kept(make_snippet("FC-01-S1", HOT), 0.9),
            kept(make_snippet("FC-01-S2", COLD), 0.1),
        ],
        QUERY,
    )
    for result in results:
        assert 0.0 <= result.relevance <= 1.0
        assert 0.0 <= result.reliability <= 1.0
        assert result.score == result.relevance * result.reliability


def test_dropped_results_never_appear_in_ranking():
    results = rank(
        [
            kept(make_snippet("FC-01-S1", HOT)),
            dropped(make_snippet("FC-01-S9", HOT)),
        ],
        QUERY,
    )
    assert [result.snippet.id for result in results] == ["FC-01-S1"]

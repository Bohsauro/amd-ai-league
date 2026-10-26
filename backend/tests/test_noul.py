"""Test del gate NOUL (discriminative filtering).

Coprono: scarto del rumore per publisher_type e dominio, boilerplate, snippet
troppo corti, keep con confidenza nel range dichiarato, rispetto del target di
scarto (60-70%), determinismo e caso corpus vuoto.
"""

from __future__ import annotations

import pytest

from config import NOUL_DROP_TARGET
from noul import gate
from retriever import Snippet

QUERY = "AMD Instinct MI325X memory capacity HBM3E"

GOOD_TEXT = (
    "AMD said the Instinct MI325X accelerator ships with 256GB of HBM3E memory "
    "and 6TB/s of bandwidth, positioning the part against the NVIDIA H200 for "
    "large model inference. The company repeated the memory capacity figure in "
    "the press release and in the analyst briefing, and described the platform "
    "as available in the fourth quarter of the year for OEM systems."
)


def make_snippet(
    snippet_id: str,
    content: str = GOOD_TEXT,
    *,
    publisher_type: str = "press",
    source_url: str = "https://example-real-news.com/story",
    source_name: str = "Real News",
    title: str = "AMD updates Instinct roadmap",
) -> Snippet:
    return Snippet(
        id=snippet_id,
        source_url=source_url,
        source_name=source_name,
        publisher_type=publisher_type,
        date="2024-10-10",
        content=content,
        title=title,
    )


def by_id(results):
    return {result.snippet.id: result for result in results}


def test_empty_input_returns_empty():
    assert gate([], QUERY) == []


def test_noise_publisher_type_is_dropped():
    results = gate([make_snippet("S1", publisher_type="noise")], QUERY)
    assert len(results) == 1
    assert results[0].keep is False
    assert results[0].reason == "spam"
    assert results[0].confidence >= 0.9


def test_seo_publisher_type_maps_to_seo_reason():
    results = gate([make_snippet("S1", publisher_type="seo")], QUERY)
    assert results[0].keep is False
    assert results[0].reason == "seo"


def test_blacklisted_domain_is_dropped_as_seo():
    results = gate(
        [make_snippet("S1", source_url="https://contentfarm.example/amd-mi325x")],
        QUERY,
    )
    assert results[0].keep is False
    assert results[0].reason == "seo"


def test_blacklisted_name_hint_is_dropped():
    results = gate([make_snippet("S1", source_name="Best SEO Spam Daily")], QUERY)
    assert results[0].keep is False
    assert results[0].reason == "seo"


def test_short_snippet_is_dropped_as_spam():
    long_snippets = [make_snippet(f"S{i}") for i in range(1, 5)]
    short = make_snippet("S9", content="AMD MI325X.")
    results = by_id(gate(long_snippets + [short], QUERY))
    assert results["S9"].keep is False
    assert results["S9"].reason == "spam"
    assert results["S9"].signals["length_ratio"] < 0.18


def test_boilerplate_heavy_snippet_is_dropped():
    boilerplate = (
        "Subscribe to our newsletter and accept all cookies. Sign up for the "
        "advertisement free edition. Follow us and read more about the AMD "
        "Instinct MI325X memory capacity story on our related articles page."
    )
    long_snippets = [make_snippet(f"S{i}") for i in range(1, 5)]
    results = by_id(gate(long_snippets + [make_snippet("S9", content=boilerplate)], QUERY))
    assert results["S9"].keep is False
    assert results["S9"].reason == "boilerplate"


def test_good_snippet_is_kept_with_bounded_confidence():
    results = gate([make_snippet("S1")], QUERY)
    assert results[0].keep is True
    assert results[0].reason == "keep"
    assert 0.58 <= results[0].confidence <= 0.99
    assert results[0].signals["words"] > 0


def test_gate_respects_drop_target_on_a_real_pool():
    """Su un pool vero (>=10) il gate scarta fino al target 60-70%."""
    snippets = [
        make_snippet(f"S{i}", content=f"{GOOD_TEXT} Copy number {i} for the pool.")
        for i in range(1, 13)
    ]
    results = gate(snippets, QUERY)
    total = len(results)
    expected_keep = round(total * (1.0 - sum(NOUL_DROP_TARGET) / 2.0))
    kept = [result for result in results if result.keep]
    dropped = [result for result in results if not result.keep]
    assert len(kept) == expected_keep
    assert len(dropped) == total - expected_keep
    # gli scarti extra sono motivati come off-topic, non come rumore
    assert all(result.reason == "off-topic" for result in dropped)


def test_small_pool_is_not_quota_cut():
    """Quattro sorgenti pertinenti non devono essere decimate da una quota."""
    results = gate([make_snippet(f"S{i}") for i in range(1, 5)], QUERY)
    assert all(result.keep for result in results)


def test_single_good_snippet_is_kept():
    """Regressione: con un solo snippet la quota non deve azzerare il pool."""
    results = gate([make_snippet("S1")], QUERY)
    assert len(results) == 1
    assert results[0].keep is True


def test_gate_keeps_order_and_is_deterministic():
    snippets = [make_snippet(f"S{i}") for i in range(1, 6)]
    first = [(r.snippet.id, r.keep, round(r.confidence, 6)) for r in gate(snippets, QUERY)]
    second = [(r.snippet.id, r.keep, round(r.confidence, 6)) for r in gate(snippets, QUERY)]
    assert first == second
    assert [row[0] for row in first] == [s.id for s in snippets]


def test_offtopic_drop_confidence_is_bounded():
    snippets = [
        make_snippet(f"S{i}", content=f"{GOOD_TEXT} Copy number {i} for the pool.")
        for i in range(1, 11)
    ]
    for result in gate(snippets, QUERY):
        if result.reason == "off-topic":
            assert 0.50 <= result.confidence <= 0.94


@pytest.mark.parametrize("publisher_type", ["official", "press", "report", "blog"])
def test_legit_publisher_types_survive(publisher_type):
    results = gate([make_snippet("S1", publisher_type=publisher_type)], QUERY)
    assert results[0].keep is True

"""Test di validazione del corpus reale + test anti-leakage del ground truth.

Il corpus e' la dipendenza critica della demo: se un caso ha URL finti, date
sbagliate o contenuti troppo corti il gate `bin/verify` deve fallire. Questi
test usano lo stesso modulo di validazione del gate (`corpus_validation.py`),
quindi non possono divergere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from corpus_validation import (
    CONTENT_MAX,
    CONTENT_MIN,
    MIN_SOURCES,
    load_corpus_cases,
    validate_corpus,
)
from generator import build_messages
from noul import gate
from retriever import DEFAULT_CORPUS_PATH, pool_snippets
from score import rank
from choice import decide
MIN_CASES = 10
CORPUS_PATH = Path(DEFAULT_CORPUS_PATH)
CASES = load_corpus_cases(CORPUS_PATH)


def test_corpus_file_exists():
    assert CORPUS_PATH.exists(), f"corpus mancante: {CORPUS_PATH}"


def test_corpus_has_at_least_six_cases():
    assert len(CASES) >= MIN_CASES


def test_corpus_case_ids_are_unique_and_conforming():
    ids = [str(case.get("id", "")) for case in CASES]
    assert len(ids) == len(set(ids)), f"id duplicati: {ids}"
    assert all(ids), "ogni caso deve avere un id"
    for case_id in ids:
        assert case_id.startswith("FC-"), case_id


def test_corpus_passes_full_validation():
    report = validate_corpus(CASES)
    assert report.ok, report.summary()


def test_every_case_has_enough_sources():
    for case in CASES:
        assert len(case.get("sources") or []) >= MIN_SOURCES, case.get("id")


def test_content_length_within_bounds():
    for case in CASES:
        for source in case.get("sources") or []:
            length = len(source.get("content") or "")
            assert CONTENT_MIN <= length <= CONTENT_MAX, f"{source.get('id')}: {length}"


def test_no_placeholder_domains_in_real_sources():
    """Solo le sorgenti 'noise' possono simulare domini finti (sono il rumore)."""
    fake = re.compile(r"(example\.(com|org|net)|acme\.|\.example|test\.local)", re.I)
    for case in CASES:
        assert not fake.search(str(case.get("truth_url") or "")), case.get("id")
        for source in case.get("sources") or []:
            if source.get("publisher_type") == "noise":
                continue
            assert not fake.search(str(source.get("source_url") or "")), source.get("id")
            assert not fake.search(str(source.get("content") or "")), source.get("id")


def test_ground_truth_never_reaches_the_snippets():
    """`truth` e `verdict_in_corpus` sono metadati di valutazione, non input."""
    for snippet in pool_snippets(CASES):
        assert not hasattr(snippet, "truth")
        assert "truth" not in snippet.extra
        assert "verdict_in_corpus" not in snippet.extra
        assert "truth_url" not in snippet.extra


def test_ground_truth_never_reaches_the_generator_prompt():
    case = CASES[0]
    query = str(case["query"])
    snippets = [s for s in pool_snippets(CASES) if s.case_id == case["id"]]
    ranked = rank([r for r in gate(snippets, query) if r.keep], query)
    choice = decide(ranked, query)
    messages, _selected, _est = build_messages(query, choice, ranked)
    prompt = "\n".join(message["content"] for message in messages)
    assert "verdict_in_corpus" not in prompt
    assert str(case["truth"]) not in prompt
    assert str(case.get("claim") or "") not in prompt


@pytest.mark.parametrize("case", CASES, ids=[str(c.get("id")) for c in CASES])
def test_case_truth_url_is_absolute_http(case):
    assert str(case["truth_url"]).startswith("http")


def test_validate_corpus_flags_fake_domains():
    broken = [
        {
            "id": "FC-01",
            "subject": "s",
            "query": "q",
            "claim": "c",
            "truth": "t",
            "truth_url": "https://acme.example/truth",
            "sources": [
                {
                    "id": "FC-01-S1",
                    "source_name": "n",
                    "publisher_type": "press",
                    "date": "2024-01-01",
                    "title": "t",
                    "source_url": "https://example.com/a",
                    "content": "x" * 250,
                }
            ],
        }
    ]
    report = validate_corpus(broken)
    assert not report.ok
    assert any("truth_url" in item for item in report.fake_urls)


def test_validate_corpus_flags_thin_and_bad_schema():
    broken = [
        {
            "id": "FC-01",
            "subject": "s",
            "query": "q",
            "claim": "c",
            "truth": "t",
            "truth_url": "https://real.example.org/x",
            "sources": [
                {
                    "id": "WRONG-ID",
                    "source_name": "n",
                    "publisher_type": "gossip",
                    "date": "10/10/2024",
                    "title": "",
                    "source_url": "https://real.example.org/a",
                    "content": "short",
                }
            ],
        }
    ]
    report = validate_corpus(broken)
    assert not report.ok
    assert report.thin_cases
    assert report.source_problems

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import AUTHORITY, RELIABILITY_WEIGHTS
from noul import NoulResult
from retriever import Snippet
from textutil import FigureClaim, TfidfIndex, extract_figures, figures_agree, figures_conflict, parse_date


@dataclass
class ScoreResult:
    snippet: Snippet
    relevance: float
    reliability: float
    reliability_breakdown: dict[str, float]
    score: float
    rank: int = 0
    figures: list[FigureClaim] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = self.snippet.to_dict()
        data.update(
            {
                "rank": self.rank,
                "relevance": round(self.relevance, 4),
                "reliability": round(self.reliability, 4),
                "reliability_breakdown": {
                    key: round(value, 4) for key, value in self.reliability_breakdown.items()
                },
                "score": round(self.score, 4),
            }
        )
        return data


def _authority(publisher_type: str) -> float:
    return AUTHORITY.get((publisher_type or "unknown").lower(), AUTHORITY["unknown"])


def _recency(date_value: str, reference: datetime | None) -> float:
    parsed = parse_date(date_value)
    if not parsed or not reference:
        return 0.5
    age_days = max(0.0, (reference - parsed).total_seconds() / 86400.0)
    return max(0.0, 1.0 - age_days / 365.0)


def _numeric_consistency(
    own: list[FigureClaim],
    other: list[FigureClaim],
    lexical_similarity: float,
) -> float:
    if not own or not other:
        return min(1.0, lexical_similarity * 2.5)
    has_agree = any(figures_agree(a, b) for a in own for b in other)
    has_conflict = any(figures_conflict(a, b) for a in own for b in other)
    if has_agree and not has_conflict:
        return 1.0
    if has_conflict and not has_agree:
        return 0.0
    if has_agree and has_conflict:
        return 0.5
    return min(1.0, lexical_similarity * 2.5)


def rank(noul_results: list[NoulResult], query: str, top_k: int = 8) -> list[ScoreResult]:
    kept = [result for result in noul_results if result.keep]
    if not kept:
        return []
    texts = [f"{result.snippet.title} {result.snippet.content}".strip() for result in kept]
    index = TfidfIndex(texts)
    query_vector = index.vector(query)
    similarities = [index.similarity(query, text) for text in texts]
    max_similarity = max(similarities) if similarities else 0.0
    dates = [parse_date(result.snippet.date) for result in kept]
    known_dates = [date for date in dates if date is not None]
    reference = max(known_dates) if known_dates else None
    figures = [extract_figures(result.snippet.content) for result in kept]

    scored: list[ScoreResult] = []
    for position, result in enumerate(kept):
        similarity = similarities[position]
        if max_similarity > 0:
            relative = similarity / max_similarity
        else:
            relative = 0.0
        absolute = min(1.0, similarity / 0.4)
        relevance = max(0.0, min(1.0, 0.7 * relative + 0.3 * absolute))

        authority = _authority(result.snippet.publisher_type)
        recency = _recency(result.snippet.date, reference)

        others = [other for other in range(len(texts)) if other != position]
        consistency_values = [
            _numeric_consistency(figures[position], figures[other], index.similarity(texts[position], texts[other]))
            for other in others
        ]
        consistency = sum(consistency_values) / len(consistency_values) if consistency_values else 0.5

        reliability = (
            RELIABILITY_WEIGHTS["authority"] * authority
            + RELIABILITY_WEIGHTS["recency"] * recency
            + RELIABILITY_WEIGHTS["consistency"] * consistency
        )
        breakdown = {"authority": authority, "recency": recency, "consistency": consistency}
        scored.append(
            ScoreResult(
                snippet=result.snippet,
                relevance=relevance,
                reliability=reliability,
                reliability_breakdown=breakdown,
                score=relevance * reliability,
                figures=figures[position],
            )
        )

    scored.sort(key=lambda item: (-item.score, -item.reliability, -item.relevance, item.snippet.id))
    for rank_index, item in enumerate(scored, start=1):
        item.rank = rank_index
    return scored[:top_k]


if __name__ == "__main__":
    import json
    import sys

    from noul import gate
    from retriever import retrieve

    query = sys.argv[1] if len(sys.argv) > 1 else "FC-01"
    for result in rank(gate(retrieve(query), query), query):
        print(json.dumps(result.to_dict(), ensure_ascii=False))

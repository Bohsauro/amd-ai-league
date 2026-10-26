"""CHOICE — pairwise reconciliation and typed verdict.

Confidence formula (deterministic, spec BUILD_SPEC §2.5):
- CONFLICT: reliability-weighted share of the winning figure over the runner-up,
  plus small bonuses for an official winner and for multiple corroborating
  sources. If no official/primary source supports the winning claim, confidence
  is capped at 0.55: anonymous-source majorities are not sufficient evidence.
- RESOLVED: 0.58 + 0.05 per agreeing pair + 0.18 * top reliability, capped 0.95.
- INSUFFICIENT: 0.35 (or 0.0 with an empty input).
The 0.60 threshold is normative and lives in config.GUARD_THRESHOLD.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from score import ScoreResult
from textutil import (
    FigureClaim,
    best_sentence,
    content_tokens,
    figures_agree,
    figures_conflict,
)


@dataclass
class PairJudgement:
    a: str
    b: str
    relation: str
    agreements: list[tuple[FigureClaim, FigureClaim]] = field(default_factory=list)
    conflicts: list[tuple[FigureClaim, FigureClaim]] = field(default_factory=list)


@dataclass
class ChoiceResult:
    label: str
    verdict: str
    claim_id: str
    confidence: float
    evidence: list[str]
    conflict_pairs: list[dict[str, Any]]
    supporting: dict[str, list[str]] = field(default_factory=dict)
    claim: str = ""
    claim_key: list[Any] = field(default_factory=list)
    pairs: list[PairJudgement] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "verdict": self.verdict,
            "claim": self.claim,
            "claim_id": self.claim_id,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "conflict_pairs": self.conflict_pairs,
            "supporting": self.supporting,
        }


def classify_pair(a: ScoreResult, b: ScoreResult) -> PairJudgement:
    agreements: list[tuple[FigureClaim, FigureClaim]] = []
    conflicts: list[tuple[FigureClaim, FigureClaim]] = []
    for figure_a in a.figures:
        for figure_b in b.figures:
            if figures_conflict(figure_a, figure_b):
                conflicts.append((figure_a, figure_b))
            elif figures_agree(figure_a, figure_b):
                agreements.append((figure_a, figure_b))
    if conflicts:
        relation = "disagree"
    elif agreements:
        relation = "agree"
    else:
        relation = "unrelated"
    return PairJudgement(a.snippet.id, b.snippet.id, relation, agreements, conflicts)


def _claim_id(label: str, key: Any, evidence: list[str]) -> str:
    digest = hashlib.sha1(f"{label}|{key}|{','.join(evidence)}".encode("utf-8")).hexdigest()[:10]
    return f"CL-{digest}"


def _sentence_for(result: ScoreResult, figures: list[FigureClaim], query_terms: set[str]) -> str:
    if figures:
        best = max(figures, key=lambda figure: len(figure.context & query_terms))
        return best.sentence
    return best_sentence(result.snippet.content, query_terms)


def decide(score_results: list[ScoreResult], query: str = "") -> ChoiceResult:
    if not score_results:
        return ChoiceResult(
            label="INSUFFICIENT",
            verdict="No valid sources after the gate.",
            claim_id=_claim_id("INSUFFICIENT", "none", []),
            confidence=0.0,
            evidence=[],
            conflict_pairs=[],
        )

    query_terms = set(content_tokens(query))
    by_id = {result.snippet.id: result for result in score_results}
    pairs: list[PairJudgement] = []
    for index, result in enumerate(score_results):
        for other in score_results[index + 1:]:
            pairs.append(classify_pair(result, other))

    conflicting = [pair for pair in pairs if pair.relation == "disagree"]
    agreeing = [pair for pair in pairs if pair.relation == "agree"]
    strong_conflicts = [
        pair
        for pair in conflicting
        if by_id[pair.a].reliability_breakdown.get("authority", 0.0) >= 0.70
        and by_id[pair.b].reliability_breakdown.get("authority", 0.0) >= 0.70
    ]

    if strong_conflicts:
        dispute: dict[tuple[str, float], dict[str, Any]] = defaultdict(lambda: {"weight": 0.0, "sources": []})
        for pair in strong_conflicts:
            for figure_a, figure_b in pair.conflicts:
                for source_id, figure in ((pair.a, figure_a), (pair.b, figure_b)):
                    entry = dispute[figure.key]
                    if source_id not in entry["sources"]:
                        entry["weight"] += by_id[source_id].reliability
                        entry["sources"].append(source_id)
                        entry.setdefault("figures", {})[source_id] = figure
        ordered = sorted(dispute.items(), key=lambda item: (item[1]["weight"], item[0]), reverse=True)
        winner_key, winner = ordered[0]
        runner_up_weight = ordered[1][1]["weight"] if len(ordered) > 1 else 0.0
        winner_sources = sorted(winner["sources"], key=lambda sid: by_id[sid].reliability, reverse=True)
        winner_result = by_id[winner_sources[0]]
        winner_figures = [winner["figures"][sid] for sid in winner_sources if sid in winner["figures"]]
        ratio = (
            winner["weight"] / (winner["weight"] + runner_up_weight)
            if winner["weight"] + runner_up_weight
            else 0.0
        )
        authority = winner_result.reliability_breakdown.get("authority", 0.5)
        other_authorities = [
            max(by_id[sid].reliability_breakdown.get("authority", 0.5) for sid in entry["sources"])
            for key, entry in ordered[1:]
        ]
        best_other_authority = max(other_authorities) if other_authorities else 0.0
        confidence = ratio
        if authority >= 0.9:
            confidence += 0.08
        if len(winner_sources) >= 2:
            confidence += 0.05
        if authority >= 0.9 and best_other_authority <= 0.6:
            confidence += 0.05
        confidence = max(0.0, min(0.97, confidence))
        has_primary_support = any(
            by_id[source_id].reliability_breakdown.get("authority", 0.0) >= 0.90
            for source_id in winner_sources
        )
        if not has_primary_support:
            confidence = min(confidence, 0.55)
        verdict_sentence = _sentence_for(winner_result, winner_result.figures, query_terms)
        label = "CONFLICT"
        verdict = f"{winner_result.snippet.source_name}: {verdict_sentence}"
        claim = winner_result.figures[0].label if winner_result.figures else ""
        conflict_pairs = [
            {
                "a": pair.a,
                "b": pair.b,
                "relation": "disagree",
                "figures": [
                    {"a": figure_a.label, "b": figure_b.label}
                    for figure_a, figure_b in pair.conflicts
                ],
            }
            for pair in strong_conflicts
        ]
        supporting = {
            (f"{key[1]:g}{key[0]}" if key[0] else f"{key[1]:g}"): entry["sources"]
            for key, entry in dispute.items()
        }
        return ChoiceResult(
            label=label,
            verdict=verdict,
            claim_id=_claim_id(label, winner_key, winner_sources),
            confidence=confidence,
            evidence=winner_sources,
            conflict_pairs=conflict_pairs,
            supporting=supporting,
            claim=claim,
            claim_key=list(winner_key),
            pairs=pairs,
        )

    if agreeing:
        sources = sorted(
            {pair.a for pair in agreeing} | {pair.b for pair in agreeing},
            key=lambda sid: by_id[sid].reliability,
            reverse=True,
        )
        top = by_id[sources[0]]
        shared_figures = [
            figure_a
            for pair in agreeing
            for figure_a, _figure_b in pair.agreements
            if pair.a == top.snippet.id or pair.b == top.snippet.id
        ]
        confidence = min(0.95, 0.58 + 0.05 * len(agreeing) + 0.18 * top.reliability)
        verdict = f"{top.snippet.source_name}: {_sentence_for(top, shared_figures, query_terms)}"
        claim = shared_figures[0].label if shared_figures else ""
        return ChoiceResult(
            label="RESOLVED",
            verdict=verdict,
            claim_id=_claim_id("RESOLVED", claim, sources),
            confidence=confidence,
            evidence=sources,
            conflict_pairs=[],
            supporting={claim: sources} if claim else {},
            claim=claim,
            pairs=pairs,
        )

    top = max(score_results, key=lambda result: result.reliability)
    return ChoiceResult(
        label="INSUFFICIENT",
        verdict=f"{top.snippet.source_name}: {best_sentence(top.snippet.content, query_terms)}",
        claim_id=_claim_id("INSUFFICIENT", top.snippet.id, [top.snippet.id]),
        confidence=0.35,
        evidence=[],
        conflict_pairs=[],
        pairs=pairs,
    )


if __name__ == "__main__":
    import json
    import sys

    from noul import gate
    from retriever import retrieve

    query = sys.argv[1] if len(sys.argv) > 1 else "FC-01"
    ranked = __import__("score").rank(gate(retrieve(query), query), query, top_k=8)
    print(json.dumps(decide(ranked, query).to_dict(), ensure_ascii=False, indent=2))

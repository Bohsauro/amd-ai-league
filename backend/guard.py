from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from choice import ChoiceResult
from config import GUARD_THRESHOLD

THRESHOLD = GUARD_THRESHOLD


@dataclass
class GuardResult:
    triggered: bool
    action: str
    sufficient: bool
    confidence: float
    label: str
    verdict: str
    reason: str
    threshold: float = THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "action": self.action,
            "sufficient": self.sufficient,
            "confidence": round(self.confidence, 4),
            "label": self.label,
            "verdict": self.verdict,
            "reason": self.reason,
            "threshold": self.threshold,
        }


def check(
    choice: ChoiceResult,
    available_count: int,
    used_count: int,
    already_expanded: bool = False,
    threshold: float = THRESHOLD,
    primary_support: bool | None = None,
) -> GuardResult:
    confidence_low = choice.confidence < threshold
    provenance_missing = primary_support is False and choice.label != "INSUFFICIENT"
    if not confidence_low and not provenance_missing:
        return GuardResult(
            triggered=False,
            action="pass",
            sufficient=True,
            confidence=choice.confidence,
            label=choice.label,
            verdict=choice.verdict,
            reason=f"confidence {choice.confidence:.2f} >= {threshold:.2f}",
            threshold=threshold,
        )
    if not already_expanded and available_count > used_count:
        if provenance_missing:
            reason = (
                f"no official source supports the winning claim ({choice.claim or 'n/a'}); "
                f"expando da {used_count} a {available_count} candidati"
            )
        else:
            reason = (
                f"confidence {choice.confidence:.2f} < {threshold:.2f}; "
                f"expando da {used_count} a {available_count} candidati"
            )
        return GuardResult(
            triggered=True,
            action="expand",
            sufficient=False,
            confidence=choice.confidence,
            label=choice.label,
            verdict=choice.verdict,
            reason=reason,
            threshold=threshold,
        )
    if provenance_missing:
        reason = (
            f"no official source supports the winning claim ({choice.claim or 'n/a'}); "
            f"confidence {choice.confidence:.2f}, espansione esaurita"
        )
    else:
        reason = f"confidence {choice.confidence:.2f} < {threshold:.2f}; espansione esaurita"
    return GuardResult(
        triggered=True,
        action="insufficient",
        sufficient=False,
        confidence=choice.confidence,
        label="INSUFFICIENT",
        verdict="Insufficient evidence: no primary source prevails over the conflict.",
        reason=reason,
        threshold=threshold,
    )

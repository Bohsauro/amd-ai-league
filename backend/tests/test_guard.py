"""Test della soglia GUARD (0.60) e delle tre azioni: pass, expand, insufficient.

Il threshold e' normativo e vive in config.GUARD_THRESHOLD: i test lo leggono da
li', non lo ricopiano, cosi' un cambio di config fa fallire il test giusto.
"""

from __future__ import annotations

import pytest

from choice import ChoiceResult
from config import GUARD_THRESHOLD
from guard import THRESHOLD, check


def make_choice(confidence: float, label: str = "CONFLICT", claim: str = "256GB") -> ChoiceResult:
    return ChoiceResult(
        label=label,
        verdict="AMD: the MI325X memory capacity is 256GB of HBM3E.",
        claim_id="CL-test0001",
        confidence=confidence,
        evidence=["FC-04-S1", "FC-04-S2"],
        conflict_pairs=[{"a": "FC-04-S1", "b": "FC-04-S3", "relation": "disagree", "figures": []}],
        claim=claim,
    )


def test_threshold_is_the_config_value():
    assert THRESHOLD == GUARD_THRESHOLD


def test_confidence_above_threshold_passes():
    result = check(make_choice(0.80), available_count=8, used_count=6)
    assert result.triggered is False
    assert result.action == "pass"
    assert result.sufficient is True
    assert result.threshold == GUARD_THRESHOLD


def test_confidence_exactly_at_threshold_passes():
    """Il confronto e' stretto (<): 0.60 esatto non deve far scattare il guard."""
    result = check(make_choice(GUARD_THRESHOLD), available_count=8, used_count=6)
    assert result.action == "pass"
    assert result.sufficient is True


def test_confidence_below_threshold_expands_when_room_is_left():
    result = check(make_choice(0.40), available_count=8, used_count=6)
    assert result.triggered is True
    assert result.action == "expand"
    assert result.sufficient is False
    assert "expando da 6 a 8" in result.reason


def test_confidence_below_threshold_without_room_is_insufficient():
    result = check(make_choice(0.40), available_count=6, used_count=6, already_expanded=True)
    assert result.triggered is True
    assert result.action == "insufficient"
    assert result.sufficient is False
    assert result.label == "INSUFFICIENT"
    assert "espansione esaurita" in result.reason


def test_missing_primary_support_triggers_guard_even_with_high_confidence():
    result = check(make_choice(0.90), available_count=8, used_count=6, primary_support=False)
    assert result.triggered is True
    assert result.action == "expand"
    assert "no official source supports the winning claim" in result.reason


def test_missing_primary_support_exhausted_is_insufficient():
    result = check(
        make_choice(0.90),
        available_count=6,
        used_count=6,
        already_expanded=True,
        primary_support=False,
    )
    assert result.action == "insufficient"
    assert result.label == "INSUFFICIENT"
    assert "no official source supports the winning claim" in result.reason


def test_primary_support_true_does_not_trigger_on_provenance():
    result = check(make_choice(0.80), available_count=8, used_count=6, primary_support=True)
    assert result.action == "pass"


def test_already_insufficient_label_is_not_treated_as_missing_provenance():
    """Se CHOICE ha gia' label INSUFFICIENT non si riapre il ramo provenance."""
    result = check(
        make_choice(0.35, label="INSUFFICIENT"),
        available_count=8,
        used_count=6,
        primary_support=False,
    )
    assert result.action == "expand"
    assert "no official source" not in result.reason


def test_custom_threshold_is_honoured():
    result = check(make_choice(0.65), available_count=8, used_count=6, threshold=0.70)
    assert result.action == "expand"
    assert result.threshold == 0.70


def test_to_dict_rounds_and_exposes_threshold():
    payload = check(make_choice(0.123456), available_count=8, used_count=6).to_dict()
    assert payload["confidence"] == 0.1235
    assert payload["threshold"] == GUARD_THRESHOLD
    assert set(payload) == {
        "triggered",
        "action",
        "sufficient",
        "confidence",
        "label",
        "verdict",
        "reason",
        "threshold",
    }


@pytest.mark.parametrize("confidence,expected", [(0.59, "expand"), (0.61, "pass")])
def test_threshold_boundary_neighbourhood(confidence, expected):
    assert check(make_choice(confidence), available_count=8, used_count=6).action == expected

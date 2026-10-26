"""Test della selezione provider del generatore (pin Groq per la demo)."""

from __future__ import annotations

import os

from generator import _provider_options


def test_default_pins_groq():
    os.environ.pop("OPENROUTER_PROVIDER_ONLY", None)
    options = _provider_options()
    assert options["only"] == ["Groq"]
    assert options["sort"] == "latency"


def test_env_override_supports_multiple_providers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROVIDER_ONLY", "Groq,AWS Bedrock")
    assert _provider_options()["only"] == ["Groq", "AWS Bedrock"]


def test_empty_env_removes_the_pin(monkeypatch):
    monkeypatch.setenv("OPENROUTER_PROVIDER_ONLY", "  , ")
    options = _provider_options()
    assert "only" not in options
    assert options["sort"] == "latency"
"""Test offline per il sample config Prometheus (Fase 4C-B3)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "deployment" / "prometheus.yml"


def test_prometheus_sample_config_contract() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "job_name: spesemed-api" in text
    assert "metrics_path: /metrics" in text
    assert 'targets: ["api:8000"]' in text
    assert "METRICS_IP_ALLOWLIST" in text


def test_prometheus_sample_config_has_no_credentials() -> None:
    text = CONFIG.read_text(encoding="utf-8").lower()
    for marker in ("password:", "secret:", "token:", "api_key:", "authorization:", "bearer "):
        assert marker not in text, f"sample config contains credential marker {marker!r}"


def test_prometheus_sample_config_valid_with_promtool() -> None:
    promtool = shutil.which("promtool")
    if not promtool:
        pytest.skip("promtool non installato: verifica YAML delegata al parser")
    subprocess.run([promtool, "check", "config", str(CONFIG)], check=True)

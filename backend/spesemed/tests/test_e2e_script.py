"""SPESEMED - Test del validator E2E (tests/e2e/run_e2e.py).

Verifica che lo script di validazione:
    - Resti eseguibile/importabile (syntax OK).
    - Con env mancanti ESCA SUBITO (exit 2) SENZA emettere richieste di rete:
      safety net per evitare che un run accidentale scriva su :8000 live
      (le richieste di scrittura al backend live sono vietate dal README).
    - Non contenga secrets hardcoded (grep sk_/whsec_/SUPABASE_SERVICE_KEY).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

E2E_SCRIPT = Path(__file__).parent / "e2e" / "run_e2e.py"

# Nomi di secret che NON devono MAI comparire nel file (anche in commenti).
_LEAK_MARKERS = ("sk_live_", "sk_test_", "whsec_", "SUPABASE_SERVICE_KEY=ey")


def _clean_env() -> dict:
    """Env senza variabili SPESEMED_* (per forzare il fail-fast)."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("SPESEMED_"):
            env.pop(key)
    return env


def test_script_is_importable_without_network():
    """La sintassi e' valida (compila senza errori)."""
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(E2E_SCRIPT)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_missing_env_fails_fast_exit_2_no_requests():
    """Senza env richieste, exit code 2 e nessuno step eseguito."""
    r = subprocess.run(
        [sys.executable, str(E2E_SCRIPT)],
        capture_output=True, text=True, env=_clean_env(),
        timeout=30,
    )
    assert r.returncode == 2, f"atteso exit 2, got {r.returncode}: {r.stdout} {r.stderr}"
    # Deve comparire la guida per l'operatore.
    assert "variabili ambiente mancanti" in r.stdout
    # Nessuno step eseguito (nessun [OK]/[FAIL]/[SKIP]).
    assert "RIEPILOGO" not in r.stdout


def test_script_contains_no_secrets():
    """Il validator non deve contenere secret (sk_/whsec_/service key)."""
    content = E2E_SCRIPT.read_text()
    for marker in _LEAK_MARKERS:
        assert marker not in content, f"Possibile leak nel validator: {marker!r}"
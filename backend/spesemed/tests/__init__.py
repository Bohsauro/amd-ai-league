# tests/__init__.py
# ----------------
# Questo file è vuoto di proposito ("intentionally empty") e serve solo a
# rendere la cartella `tests/` un package Python, permettendo l'esecuzione
# dei test con `python -m tests.test_imports` o `pytest tests/`.
#
# Convenzioni:
#   - I file `test_*.py` esportano funzioni `test_*()` compatibili con pytest.
#   - Per eseguire i test senza dipendenze extra:  python -m tests.test_imports
#   - Per eseguire con pytest (consigliato in CI): pytest tests/ -v

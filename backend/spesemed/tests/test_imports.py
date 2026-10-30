"""SPESEMED - Smoke test per validare importazioni e validatori.

Adattato alla nuova struttura package (src/spesemed/core/).

Questo test NON chiama OpenRouter (non serve API key). Valida solo:
    - Import di tutti i moduli core senza errori
    - Comportamento di default di SpesaMedica (tutti Optional)
    - Validatori tolerant (CF normalizzato, importo arrotondato, esercente trim)
    - Coerenza della tassonomia tra taxonomy.py e models.py
    - Coerenza del SYSTEM_PROMPT (le categorie sono interpolate)

Esecuzione:
    python -m tests.test_imports
    oppure: pytest tests/ -v

Per testare l'API: pytest tests/test_api.py (da creare in Fase 2).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Aggiungi la root del progetto al sys.path per trovare il package `spesemed`.
# pyproject.toml ha `pythonpath = ["src"]` per pytest, ma per `python -m` lo
# settiamo anche manualmente per coprire l'esecuzione standalone.
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# =============================================================================
# Helpers per catturare i log di warning dei validatori
# =============================================================================
class _CaptureLogHandler(logging.Handler):
    """Handler che accumula i messaggi di log in una lista in memoria."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _with_log_capture(fn) -> tuple[any, list[str]]:
    handler = _CaptureLogHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        result = fn()
        return result, handler.messages
    finally:
        root.removeHandler(handler)


# =============================================================================
# Test
# =============================================================================
def test_import_all_modules() -> None:
    """Tutti i moduli core si importano senza errori."""
    from spesemed.core import extractor, file_utils, models, prompts, taxonomy  # noqa: F401
    print("[OK] Tutti i moduli core importati correttamente")


def test_spesa_medica_default() -> None:
    """SpesaMedica() con tutti i campi default deve essere sensato."""
    from spesemed.core.models import SpesaMedica

    s = SpesaMedica()
    assert s.data_spesa is None
    assert s.esercente is None
    assert s.importo_totale is None
    assert s.codice_fiscale_paziente is None
    assert s.categoria_spesa == "Altro"
    assert not s.is_complete
    print("[OK] Default SpesaMedica coerenti")


def test_spesa_medica_tolerant_normalization() -> None:
    """I validatori tolerant normalizzano input OCR-friendly senza bloccare."""
    from spesemed.core.models import SpesaMedica

    s = SpesaMedica(
        data_spesa="2024-03-15",
        esercente="  Farmacia Centrale di Rossi Mario & C.  ",
        importo_totale=45.567,
        codice_fiscale_paziente="rss mra85 a01h501w",
        categoria_spesa="Farmaci",
    )
    assert s.esercente == "Farmacia Centrale di Rossi Mario & C."
    assert s.importo_totale == 45.57
    assert s.codice_fiscale_paziente == "RSSMRA85A01H501W"
    assert s.is_complete
    assert s.missing_fields == []
    print("[OK] Validatori tolerant normalizzano correttamente")


def test_spesa_medica_invalid_cf_warns_but_accepts() -> None:
    """Un CF malformato dall'OCR NON deve bloccare l'estrazione (leniente)."""
    from spesemed.core.models import SpesaMedica

    # 17 caratteri (errore OCR tipico)
    cf_malformato = "RSSMRA85A01H501WX"

    def build() -> SpesaMedica:
        return SpesaMedica(codice_fiscale_paziente=cf_malformato)

    s, logs = _with_log_capture(build)

    assert s.codice_fiscale_paziente is not None
    assert s.codice_fiscale_paziente == cf_malformato
    assert any("codice_fiscale" in m for m in logs), (
        f"Atteso warning sul CF malformato, got logs: {logs}"
    )
    print(f"[OK] CF malformato (17 char) mantenuto con warning: '{s.codice_fiscale_paziente}'")


def test_spesa_medica_lowercase_cf_accepted() -> None:
    """Un CF in lowercase deve essere accettato e normalizzato in UPPERCASE."""
    from spesemed.core.models import SpesaMedica

    s = SpesaMedica(codice_fiscale_paziente="rssmra85a01h501w")
    assert s.codice_fiscale_paziente == "RSSMRA85A01H501W"
    print("[OK] CF lowercase normalizzato in UPPERCASE")


def test_taxonomy_consistency() -> None:
    """models.py e taxonomy.py devono referenziare la stessa lista categorie."""
    from spesemed.core.models import CategoriaSpesa
    from spesemed.core.taxonomy import CATEGORIE_SPESA, CATEGORIE_DESC

    assert set(CategoriaSpesa.__args__) == set(CATEGORIE_SPESA)
    assert set(CATEGORIE_DESC.keys()) == set(CATEGORIE_SPESA)
    print(f"[OK] Tassonomia coerente: {CATEGORIE_SPESA}")


def test_importo_negative_clamped_to_zero() -> None:
    """Un importo negativo (errore OCR) viene azzerato con warning."""
    from spesemed.core.models import SpesaMedica

    def build() -> SpesaMedica:
        return SpesaMedica(importo_totale=-45.50)

    s, logs = _with_log_capture(build)

    assert s.importo_totale == 0.0
    assert any("importo_totale" in m for m in logs)
    print("[OK] Importo negativo clampato a zero con warning")


def test_system_prompt_includes_categories() -> None:
    """Il SYSTEM_PROMPT deve contenere tutte le categorie per guidare l'AI."""
    from spesemed.core.prompts import SYSTEM_PROMPT
    from spesemed.core.taxonomy import CATEGORIE_SPESA

    for cat in CATEGORIE_SPESA:
        assert f'"{cat}"' in SYSTEM_PROMPT, (
            f"Categoria '{cat}' mancante dal SYSTEM_PROMPT"
        )
    keywords = ["OCR", "JSON", "data_spesa", "esercente", "importo_totale",
                "codice_fiscale_paziente", "categoria_spesa"]
    for kw in keywords:
        assert kw in SYSTEM_PROMPT, f"Parola chiave '{kw}' mancante"
    print(f"[OK] SYSTEM_PROMPT contiene tutte le {len(CATEGORIE_SPESA)} categorie + keywords")


def test_api_module_imports() -> None:
    """I moduli API si importano senza eseguire effetti collaterali (no FastAPI startup).

    Nota: importare spesemed.api.main esegue st.set_page_config-like side effect
    (in realta' solo logging e CORS setup). Per evitare di avviare il server
    durante i test, importiamo solo i moduli non-main.
    """
    from spesemed.api import config as api_config
    from spesemed.api import dependencies as api_dep
    from spesemed.api import schemas as api_sch
    from spesemed.api.routes import health, jobs  # noqa: F401

    # Verifica che settings sia istanziato correttamente
    assert hasattr(api_config, "settings")
    assert hasattr(api_config.settings, "api_version")
    assert hasattr(api_config.settings, "openrouter_model")

    # Verifica che la mock auth dependency esista
    assert hasattr(api_dep, "get_current_user")
    assert callable(api_dep.get_current_user)

    # Verifica schemas
    assert hasattr(api_sch, "HealthResponse")
    assert hasattr(api_sch, "ExtractSyncResponse")
    print("[OK] Moduli API importati correttamente")


def test_main_app_loads() -> None:
    """L'app FastAPI si istanzia correttamente con i router montati."""
    from spesemed.api.main import app

    # Verifica percorsi tramite schema OpenAPI
    openapi_paths = set(app.openapi().get("paths", {}).keys())
    assert "/api/v1/health" in openapi_paths
    assert "/api/v1/extract" in openapi_paths
    assert "/api/v1/jobs/{job_id}" in openapi_paths

    # Verifica che la route root '/' sia registrata nell'app
    raw_paths = {getattr(r, "path", "") for r in app.routes if hasattr(r, "path")}
    assert "/" in raw_paths or "/" in openapi_paths

    # Verifica tags OpenAPI
    openapi_tags = [t["name"] for t in app.openapi_tags]
    assert "health" in openapi_tags
    assert "extract" in openapi_tags
    assert "jobs" in openapi_tags
    print(f"[OK] FastAPI app con {len(openapi_paths)} percorsi OpenAPI registrati")


# =============================================================================
# Entry-point
# =============================================================================
def main() -> int:
    test_functions = [
        test_import_all_modules,
        test_spesa_medica_default,
        test_spesa_medica_tolerant_normalization,
        test_spesa_medica_invalid_cf_warns_but_accepts,
        test_spesa_medica_lowercase_cf_accepted,
        test_taxonomy_consistency,
        test_importo_negative_clamped_to_zero,
        test_system_prompt_includes_categories,
        test_api_module_imports,
        test_main_app_loads,
    ]
    failures: list[tuple[str, Exception]] = []
    for fn in test_functions:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, e))
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failures.append((fn.__name__, e))
            print(f"[FAIL] {fn.__name__} (ERROR): {type(e).__name__}: {e}")

    if failures:
        print(f"\n[FAIL] {len(failures)}/{len(test_functions)} test falliti.")
        return 1
    print(f"\n[PASS] Tutti i {len(test_functions)} smoke test passati!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

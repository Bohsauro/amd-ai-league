"""SPESEMED - Test fixtures condivisi (offline, no Supabase/docker richiesti).

Queste fixture permettono di testare l'API senza:
  - Server Supabase reale
  - OpenRouter API key reale
  - Network calls (mock totale)

Pattern (post-Fase 4 refactor DI-friendly):
    Tutti gli endpoint chiamano ``supabase_client.func()`` con ``from .. import
    supabase_client``, quindi basta mockare il MODULO sorgente (1 sola patch)
    invece che ogni sito importatore (4 patch).
"""
from __future__ import annotations

import os
import warnings
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Forza env di test PRIMA di importare l'applicazione.
# NB: API_ENV resta "development" ma FIX C3 richiede ALLOW_DEV_MOCK_AUTH=true
# esplicito per abilitare X-User-Id fallback in get_current_user.
# NB: PROMETHEUS_METRICS_ENABLED e ADMIN_TOKEN sono NECESSARI per abilitare
# i test del modulo test_metrics.py (endpoint /metrics + /admin/reset-jwks-cache).
os.environ.setdefault("API_ENV", "development")
os.environ.setdefault("ALLOW_DEV_MOCK_AUTH", "true")
os.environ.setdefault("OPENROUTER_API_KEY", "")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "")
os.environ.setdefault("SUPABASE_JWT_SECRET", "")
os.environ.setdefault("RATE_LIMIT_EXTRACT", "100/minute")
os.environ["RATE_LIMIT_STORAGE_BACKEND"] = "memory"
os.environ["REDIS_URL"] = ""
os.environ.setdefault("RATE_LIMIT_LOGIN", "100/minute")
os.environ.setdefault("RATE_LIMIT_SIGNUP", "100/hour")
os.environ.setdefault("RATE_LIMIT_JOBS", "100/minute")
os.environ.setdefault("PROMETHEUS_METRICS_ENABLED", "true")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-32chars-min-12345")


@pytest.fixture
def mock_supabase_client():
    """Mock del client supabase-py (auth, table, storage)."""
    client = MagicMock()

    auth_result = MagicMock()
    auth_result.user.id = "user-uuid-test-1234"
    auth_result.session.access_token = "fake-jwt-token-test"
    auth_result.session.refresh_token = "fake-refresh-token-test"
    auth_result.session.expires_in = 3600
    client.auth.sign_in_with_password.return_value = auth_result
    client.auth.sign_up.return_value = auth_result
    client.auth.refresh_session.return_value = auth_result
    client.auth.sign_out.return_value = None

    jobs_query = MagicMock()
    jobs_query.execute.return_value.data = []
    jobs_table = MagicMock()
    jobs_table.select.return_value = jobs_query
    jobs_table.insert.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
    jobs_table.update.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
    client.table.return_value = jobs_table

    client.storage.from_.return_value = MagicMock(
        upload=MagicMock(return_value=None),
        download=MagicMock(return_value=b"fake-pdf-content"),
    )

    return client


@pytest.fixture
def mock_supabase(monkeypatch, mock_supabase_client):
    """Patch del modulo sorgente `spesemed.api.supabase_client`.

    Pattern DI: le route chiamano ``supabase_client.func()`` via attribute
    access sul modulo. Monkeypatchare il modulo sorgente aggiorna TUTTE le
    route senza dover patchare 4+ reference separate.

    Patches:
      - ``spesemed.api.supabase_client.get_supabase_client`` -> mock_client
      - ``spesemed.api.supabase_client.is_supabase_configured`` -> True
    """
    import spesemed.api.supabase_client as sb
    monkeypatch.setattr(sb, "get_supabase_client", lambda: mock_supabase_client)
    monkeypatch.setattr(sb, "is_supabase_configured", lambda: True)
    return mock_supabase_client


@pytest.fixture
def test_client():
    """FastAPI TestClient (sync, basato su starlette TestClient)."""
    from spesemed.api.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers():
    """Header mock X-User-Id per test in dev (UUID RFC 4122: FIX C2).

    NB: deve essere UUID valido perche' la validazione in get_current_user
    blocca path-traversal e injection. UUID v4 canonico generato offline.
    """
    return {"X-User-Id": "00000000-0000-4000-8000-000000000001"}


@pytest.fixture
def bearer_headers():
    """Header con Bearer token (opaco in dev)."""
    return {"Authorization": "Bearer fake-test-bearer-token-do-not-validate"}


# =============================================================================
# Test environment isolation (autouse)
# =============================================================================
# ROOT CAUSE (audit pre-go-live 2025): `core/extractor.py` chiama
# `load_dotenv()` a MODULE LOAD time (per la CLI). Questo sovrascrive i
# `os.environ.setdefault(...)` di questo conftest perche':
#
#   1. conftest.setdefault esegue BEFORE test imports (module-load time)
#   2. tests transitively importano core/extractor.py via routes/extract.py
#   3. core/extractor.py esegue `load_dotenv()` che legge .env e MERGE
#      valori in os.environ (override effettivo sulle stringhe vuote)
#   4. Risultato: `settings = Settings()` (creato al primo import) legge
#      valori .env reali, non i valori di test.
#
# FIX: fixture autouse function-scope che forza LATER nel ciclo di vita
# (dopo module imports, prima del test body):
#
#   - monkeypatch.setattr(settings, ...)  [Pydantic fields mutabili]
#   - reset_supabase_client()             [singleton _client]
#
# Tests che USANO `mock_supabase` continuano a funzionare: quella fixture
# patcha le funzioni sul modulo `spesemed.api.supabase_client`
# indipendentemente dalle env vars / settings.
# =============================================================================
@pytest.fixture(autouse=True)
def _isolate_test_env(monkeypatch):
    """Forza env offline (env vars + settings singleton + supabase client).

    Sovrascrive i campi del singleton `settings` di Pydantic e resetta
    il singleton Supabase client, garantendo che nessun test erediti
    stato dal .env locale o da test eseguiti in precedenza.
    """
    from spesemed.api.config import settings
    import spesemed.api.supabase_client as _sb_client_mod

    # 1) Reset singleton client Supabase (creato da test precedenti o dal
    #    lifespan del test_client). monkeypatch.setattr garantisce
    #    AUTO-CLEANUP: se il test e/o fixture salta (pytest.skip, exception),
    #    il teardown ripristina il valore originale. reset_supabase_client()
    #    muterebbe _client = None in modo permanente per la sessione.
    monkeypatch.setattr(_sb_client_mod, "_client", None)

    # 2) Override diretto dei campi Settings via monkeypatch.
    #    Pydantic v2 permette setattr su field dopo la creazione.
    #
    # NB: patcha TUTTE le reference al singleton. `test_security_fixes.py`
    # (FIX M4) esegue `importlib.reload(cfg_mod)` che CREA un secondo oggetto
    # Settings; `spesemed.api.dependencies.settings` resta il riferimento al
    # vecchio. Patchando entrambi gli oggetti i test sono robusti a prescindere
    # dall'ordine di esecuzione (regressione vista su test_summary.py).
    import spesemed.api.dependencies as _deps_mod
    settings_objects = {id(settings): settings, id(_deps_mod.settings): _deps_mod.settings}

    overrides = {
        "openrouter_api_key": "",
        "supabase_url": "",
        "supabase_service_key": "",
        "supabase_jwt_secret": "",
        "supabase_jwks_url": "",
        "api_env": "development",
        "allow_dev_mock_auth": True,
        "prometheus_metrics_enabled": True,
        "rate_limit_storage_backend": "memory",
        "redis_url": "",
        "admin_token": "test-admin-token-32chars-min-12345",
        # NB: lista vuota in development = fail-open (by design in
        # check_metrics_authorization). TestClient usa "testclient" come
        # host, non e' un IP valido, quindi il default ["127.0.0.1"]
        # bloccherebbe (403). Vedi metrics_acl.py per la logica.
        "metrics_ip_allowlist": [],
    }
    for obj in settings_objects.values():
        for field, value in overrides.items():
            monkeypatch.setattr(obj, field, value)

    yield


# =============================================================================
# Prometheus metrics reset (autouse)
# =============================================================================
# Counters e Histogram sono singleton a livello modulo. Senza reset per-test,
# i sample si accumulano cross-test contaminando le assertion di test_metrics.py.
#
# LIMITATION NOTA su prometheus-client:
#   Il reset via direct attribute access (`counter._value.set(0)`, ecc.) richiede
#   che il metric sia stato "usato" almeno una volta (es. `.inc()` chiamato).
#   Su metric fresh (mai usato), alcuni attributi interni sono class-level
#   descriptors senza `set()` reale, quindi il reset fallisce con AttributeError.
#   Workaround: try/except stretto AttributeError attorno a ogni reset call,
#   con `warnings.warn()` per rendere le regression API future visibili in CI.
#
# DIFESA IN PROFONDITA':
#   pyproject.toml ha pin `"prometheus-client>=0.20.0,<0.26.0,!=0.25.0"` per
#   escludere 0.25.0 (bug noto in `Metric.clear()` su `_lock`).
def _safe_set_value(value_obj) -> None:
    """Set di un Value/Histogram sample, no-op se non ancora inizializzato."""
    try:
        value_obj.set(0.0)
    except AttributeError as e:
        # Class-level descriptor (metric fresh mai usato): skip + warning
        # per rendere regression API future visibili in CI.
        warnings.warn(
            f"Prometheus reset skip su fresh metric (AttributeError: {e})",
            stacklevel=2,
        )


def _reset_histogram_buckets(hist) -> None:
    """Azzera i bucket di un Histogram (lista di Value o dict legacy)."""
    buckets = getattr(hist, "_buckets", None)
    if isinstance(buckets, dict):
        buckets.clear()
    elif isinstance(buckets, list):
        for bucket in buckets:
            _safe_set_value(bucket)


def _reset_histogram(hist) -> None:
    """Azzera sum e bucket di un Histogram, parent e child con label."""
    if hasattr(hist, "_sum"):
        _safe_set_value(hist._sum)
    _reset_histogram_buckets(hist)
    if hasattr(hist, "_metrics") and isinstance(hist._metrics, dict):
        for child in list(hist._metrics.values()):
            if hasattr(child, "_sum"):
                _safe_set_value(child._sum)
            _reset_histogram_buckets(child)


@pytest.fixture(autouse=True)
def _reset_prometheus_metrics():
    """Reset dei Counter/Histogram Prometheus prima di ogni test (autouse)."""
    from spesemed.api import metrics

    def _reset_counter(counter) -> None:
        # Reset no-label parent value (per Counter senza labelnames).
        if hasattr(counter, "_value"):
            _safe_set_value(counter._value)
        # Reset child samples labeled (API moderna 0.21+: _child_samples).
        # NB: prometheus_client 0.21+ lazy-init `_value`; la chiamata
        # `_child_samples()` internamente accede `self._value.get()` che
        # fallisce se il counter non e' mai stato usato. try/except per
        # rendere il reset best-effort (in difesa-in-profondita').
        if hasattr(counter, "_child_samples"):
            try:
                for child in list(counter._child_samples()):
                    if hasattr(child, "_value"):
                        _safe_set_value(child._value)
            except Exception as e:
                warnings.warn(
                    f"Prometheus reset skip (_child_samples): {e}",
                    stacklevel=2,
                )
        # Fallback API vecchia (< 0.21): dict `_metrics` di label values -> child.
        if hasattr(counter, "_metrics") and isinstance(counter._metrics, dict):
            for child in counter._metrics.values():
                if hasattr(child, "_value"):
                    _safe_set_value(child._value)

    for counter in (
        metrics.jwt_failures_total,
        metrics.jwks_cache_resets_total,
        metrics.http_requests_total,
    ):
        _reset_counter(counter)

    # Histogram reset: i metric con label (es. http_request_duration_seconds
    # con labelnames=("method",)) non hanno _sum/_buckets sul parent: i valori
    # stanno nei child (hist._metrics[labelvalues]). Senza questo reset il
    # parent verrebbe skippato e l'isolamento per-test andrebbe perso.
    for hist in (
        metrics.jwt_decode_duration_seconds,
        metrics.http_request_duration_seconds,
    ):
        _reset_histogram(hist)

    yield

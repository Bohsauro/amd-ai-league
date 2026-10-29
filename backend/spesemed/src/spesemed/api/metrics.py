"""SPESEMED API - Prometheus metrics (Fase 3.5 + Fase 4C).

Esposizione:
  GET  /metrics                                -> Counter/Histogram Prometheus exposition format
  POST /admin/auth/reset-jwks-cache            -> reset manuale cache (header X-Admin-Token)

Metriche definite:
  - spesemed_jwt_failures_total{reason="..."}  Counter: tentativi auth falliti, label reason
                                                 per distinguere le cause (cardinalita' bassa,
                                                 ~11 valori finiti).
  - spesemed_jwt_decode_duration_seconds       Histogram: durata di decode_supabase_jwt()
                                                 (latency distribution buckets 1ms..5s).
  - spesemed_jwt_jwks_cache_resets_total       Counter: reset manuali della cache JWKS
                                                 (utile per confermare remediation key rotation).
  - spesemed_http_requests_total{method,status_class}
                                               Counter: richieste HTTP per metodo e classe
                                                 di status (cardinalita' < 6x8, nessun label
                                                 per path/utente).
  - spesemed_http_request_duration_seconds    Histogram: durata delle richieste HTTP in secondi.

DESIGN CARDINALITA':
  Label `reason` ha SOLO valori da JWT_FAILURE_REASONS; ogni tentativo di label
  sconosciuta viene coercito a "general_decode_error" per prevenire OOM Prometheus.
  NON esponiamo MAI `kid` come label (kid illimitati se Supabase ruota chiavi).

NO USER DATA LEAKAGE (Fase 4C):
  Le metriche HTTP NON hanno etichette per path (i path contengono job_id/file_hash/
  user_id -> cardinalita' illimitata e possibile PII) ne' per utente. L'unico
  dato esposto e' metodo HTTP + classe di status (2xx/3xx/4xx/5xx), entrambi
  a cardinalita' finita e non identificativa.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from fastapi import Request, Response
from prometheus_client import Counter, Histogram

# =============================================================================
# Label values (cardinalita' bassa voluta)
# =============================================================================

# Tuple ordinata: usata sia per documentare le label valide che per type-safety
# nelle chiamate a record_failure().
JWT_FAILURE_REASONS: tuple[str, ...] = (
    "header_malformed",           # jwt.get_unverified_header() fallisce (DecodeError)
    "alg_unsupported",            # alg non in {"HS256","ES256"} (es. "none", HS512, RS256)
    "config_missing",             # HS256 senza secret o ES256 senza JWKS URL (503)
    "jwks_lookup_failed",         # kid non trovato in JWKS (PyJWKClientError)
    "jwks_invalid_signature",     # ES256 firma non valida (InvalidSignatureError su EC)
    "hs256_invalid_signature",    # HS256 firma non valida
    "expired",                    # token scaduto (ExpiredSignatureError)
    "issuer_mismatch",            # iss != atteso (cross-project o config errata)
    "role_unauthorized",          # role non in {"authenticated","anon"} (es. service_role)
    "missing_required_claim",     # manca exp/sub/iss required
    "general_decode_error",       # altri PyJWTError (catch-all)
)


# =============================================================================
# Metriche (registry di default di prometheus_client)
# =============================================================================

jwt_failures_total = Counter(
    "spesemed_jwt_failures_total",
    "Numero di JWT rifiutati per categoria di fallimento.",
    labelnames=("reason",),
)


# Buckets calibrati su JWT decode atteso:
#   HS256 hot path:        ~0.5-2ms
#   ES256 cached:          ~2-10ms
#   ES256 cold cache cold: ~50-300ms (JWKS fetch)
#   JWKS timeout rete:     ~5s
jwt_decode_duration_seconds = Histogram(
    "spesemed_jwt_decode_duration_seconds",
    "Durata di decode_supabase_jwt() in secondi (latenza auth singola request).",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)


jwks_cache_resets_total = Counter(
    "spesemed_jwt_jwks_cache_resets_total",
    "Numero di reset manuali della cache JWKS (admin endpoint, utili in key rotation).",
)


# =============================================================================
# Metriche HTTP a livello applicativo (Fase 4C)
# =============================================================================
# Cardinalita' volutamente bassa: method (8 metodi HTTP standard) x status_class
# (5 classi 1xx..5xx). MAI label per path/utente/query (cardinalita' illimitata
# + possibile PII nei path con job_id/user_id).
http_requests_total = Counter(
    "spesemed_http_requests_total",
    "Richieste HTTP totali per metodo e classe di status (cardinalita' bassa).",
    labelnames=("method", "status_class"),
)

# Buckets calibrati sul profilo API: health/auth <10ms, extract 100ms-5s (AI),
# export ZIP qualche secondo.
http_request_duration_seconds = Histogram(
    "spesemed_http_request_duration_seconds",
    "Durata delle richieste HTTP in secondi (inclusa elaborazione in-process).",
    buckets=(0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Path esclusi dalle metriche HTTP: lo scraper Prometheus stesso non deve
# inquinare i conteggi con il suo polling periodico.
_HTTP_METRICS_SKIP_PATHS = {"/metrics", "/favicon.ico"}


# =============================================================================
# Helper API (safeguard per caller)
# =============================================================================


def record_failure(reason: str) -> None:
    """Increment del counter con safe-label.

    Se `reason` non e' in JWT_FAILURE_REASONS, viene coercito a
    'general_decode_error' per NON introdurre label sconosciute
    (protezione cardinality OOM Prometheus).
    """
    if reason not in JWT_FAILURE_REASONS:
        reason = "general_decode_error"
    jwt_failures_total.labels(reason=reason).inc()


@contextmanager
def jwt_decode_timer() -> Iterator[None]:
    """Context manager per misurare la durata di decode_supabase_jwt().

    Usage:
        with jwt_decode_timer():
            payload = jwt.decode(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        jwt_decode_duration_seconds.observe(time.perf_counter() - start)


def _status_class(status_code: int) -> str:
    """Riduce un codice HTTP (200, 404, 503) alla classe (2xx, 4xx, 5xx).

    Cardinalita' finita (5 valori) per evitare label con status esatto
    (che comunque sarebbero pochi, ma la classe e' piu' robusta a variazioni).
    """
    return f"{(status_code or 0) // 100}xx"


async def prometheus_http_metrics(request: Request, call_next) -> Response:
    """Middleware ASGI che registra metriche HTTP generiche (no user data).

    Registra prima/chiama/dopo per ogni request non in `_HTTP_METRICS_SKIP_PATHS`:
        - ``spesemed_http_requests_total{method,status_class}``
        - ``spesemed_http_request_duration_seconds``

    E' indipendente da auth: funziona sia per endpoint pubblici (health, plan)
    che protetti (extract, jobs). NON espone path/utente (vedi docstring modulo).

    Usage in main.py:
        @app.middleware("http")
        async def _http_metrics(request: Request, call_next):
            return await prometheus_http_metrics(request, call_next)
    """
    path = getattr(request, "url", None)
    if path is not None and getattr(path, "path", "") in _HTTP_METRICS_SKIP_PATHS:
        return await call_next(request)

    method = (request.method or "UNKNOWN").upper()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except BaseException:
        # Errori non gestiti (500): registra comunque con classe 5xx.
        http_requests_total.labels(method=method, status_class="5xx").inc()
        http_request_duration_seconds.observe(time.perf_counter() - start)
        raise
    status_class = _status_class(response.status_code)
    http_requests_total.labels(method=method, status_class=status_class).inc()
    http_request_duration_seconds.observe(time.perf_counter() - start)
    return response

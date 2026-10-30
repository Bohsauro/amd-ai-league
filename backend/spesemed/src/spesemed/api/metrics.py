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
  - spesemed_http_requests_total{method,status}
                                               Counter: richieste HTTP per metodo e status
                                                 code (cardinalita' bounded, nessuna label
                                                 per path/utente). Definita in
                                                 ``metrics_http.py`` e re-esportata qui
                                                 per compatibilita' degli import.
  - spesemed_http_request_duration_seconds    Histogram: durata delle richieste HTTP in secondi
                                                 (definita in ``metrics_http.py``).

DESIGN CARDINALITA':
  Label `reason` ha SOLO valori da JWT_FAILURE_REASONS; ogni tentativo di label
  sconosciuta viene coercito a "general_decode_error" per prevenire OOM Prometheus.
  NON esponiamo MAI `kid` come label (kid illimitati se Supabase ruota chiavi).

NO USER DATA LEAKAGE (Fase 4C):
  Le metriche HTTP NON hanno etichette per path (i path contengono job_id/file_hash/
  user_id -> cardinalita' illimitata e possibile PII) ne' per utente. L'unico
  dato esposto e' metodo HTTP + status code, entrambi a cardinalita' finita e
  non identificativa. Vedi ``metrics_http.py``.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import Counter, Histogram

from .metrics_http import (  # noqa: F401 - re-export per import storici
    http_request_duration_seconds,
    http_requests_total,
    prometheus_http_metrics,
)

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

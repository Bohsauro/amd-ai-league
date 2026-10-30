"""SPESEMED API - Metriche HTTP Prometheus (Fase 4C, RED).

Metriche application-level per il pattern RED (Rate, Errors, Duration):
  - ``spesemed_http_requests_total{method,status}``      Counter: richieste totali
                                                         (status = codice HTTP
                                                         esatto a 3 cifre).
  - ``spesemed_http_request_duration_seconds{method}``   Histogram: latenza in
                                                         secondi per metodo.

DESIGN CARDINALITA':
  Label SOLO ``method`` e ``status``. NIENTE path/user/query: i path contengono
  job_id/file_hash/user_id (cardinalita' illimitata + possibile PII).
  ``method`` e' normalizzato a un set finito (GET/POST/PUT/PATCH/DELETE/OPTIONS/
  HEAD/OTHER); ``status`` e' il codice a 3 cifre (100..599) oppure ``"unknown"``.
  Entrambe le label hanno cardinalita' finita e non identificativa.

Il path ``/metrics`` (e ``/favicon.ico``) e' escluso dal conteggio: lo scraper
Prometheus non deve inquinare le proprie metriche con il polling periodico.
"""
from __future__ import annotations

import time

from fastapi import Request, Response
from prometheus_client import Counter, Histogram

# Metodi HTTP ammessi come label. Tutto il resto viene coercito a "OTHER" per
# impedire cardinalita' illimitata da method arbitrari (es. header malformati).
_ALLOWED_METHODS: frozenset[str] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
)
_OTHER_METHOD = "OTHER"
_UNKNOWN_STATUS = "unknown"

# Path esclusi dalle metriche HTTP (self-scrape noise + favicon).
HTTP_METRICS_SKIP_PATHS: frozenset[str] = frozenset({"/metrics", "/favicon.ico"})


http_requests_total = Counter(
    "spesemed_http_requests_total",
    "Richieste HTTP totali per method e status code (cardinalita' bounded).",
    labelnames=("method", "status"),
)

http_request_duration_seconds = Histogram(
    "spesemed_http_request_duration_seconds",
    "Latenza delle richieste HTTP in secondi per method (buckets 10ms..10s).",
    labelnames=("method",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def normalize_method(method: str | None) -> str:
    """Riporta il metodo HTTP al set finito di label ammesse."""
    normalized = (method or "").strip().upper()
    return normalized if normalized in _ALLOWED_METHODS else _OTHER_METHOD


def normalize_status(status_code: int | None) -> str:
    """Riporta il codice HTTP a una label stabile a 3 cifre (o "unknown")."""
    try:
        code = int(status_code)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _UNKNOWN_STATUS
    if 100 <= code <= 599:
        return str(code)
    return _UNKNOWN_STATUS


def record_http_request(
    method: str | None,
    status_code: int | None,
    duration_seconds: float,
) -> None:
    """Registra una richiesta HTTP su counter + histogram (label bounded)."""
    method_label = normalize_method(method)
    http_requests_total.labels(
        method=method_label, status=normalize_status(status_code)
    ).inc()
    http_request_duration_seconds.labels(method=method_label).observe(
        max(duration_seconds, 0.0)
    )


async def prometheus_http_metrics(request: Request, call_next) -> Response:
    """Middleware ASGI che registra le metriche HTTP RED (no user data).

    Registra per ogni request non in :data:`HTTP_METRICS_SKIP_PATHS`:
        - ``spesemed_http_requests_total{method,status}``
        - ``spesemed_http_request_duration_seconds{method}``

    Le eccezioni non gestite vengono conteggiate come status ``500`` e
    ri-sollevate (il framework produce la risposta 500). E' indipendente
    dall'autenticazione e non espone path/utente.

    Usage in ``main.py``::

        @app.middleware("http")
        async def _http_metrics(request: Request, call_next):
            return await prometheus_http_metrics(request, call_next)
    """
    url = getattr(request, "url", None)
    if url is not None and getattr(url, "path", "") in HTTP_METRICS_SKIP_PATHS:
        return await call_next(request)

    method = request.method
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except BaseException:
        record_http_request(method, 500, time.perf_counter() - start)
        raise
    record_http_request(method, response.status_code, time.perf_counter() - start)
    return response

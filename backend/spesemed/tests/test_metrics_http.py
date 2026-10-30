"""SPESEMED - Test metriche HTTP RED (Fase 4C-B1).

Copertura:
  - label bounded (method, status) e nomi metriche Prometheus;
  - normalizzazione method/status contro cardinalita' illimitata;
  - hit reale su endpoint (200/404) incrementa il counter;
  - /metrics escluso (self-scrape noise);
  - eccezioni non gestite registrate come status 500;
  - histogram di durata osservato.

NB: `conftest.py` azzera i counter Prometheus prima di ogni test; le assertion
usano comunque delta per robustezza all'ordine di esecuzione.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spesemed.api.metrics_http import (
    http_request_duration_seconds,
    http_requests_total,
    normalize_method,
    normalize_status,
    prometheus_http_metrics,
)


def _counter(method: str, status: str) -> float:
    return http_requests_total.labels(method=method, status=status)._value.get()


def _duration_sum(method: str) -> float:
    return http_request_duration_seconds.labels(method=method)._sum.get()


def test_http_metrics_labels_bounded():
    before = _counter("GET", "200")
    http_requests_total.labels(method="GET", status="200").inc()
    assert _counter("GET", "200") == before + 1.0
    # Status come stringa a 3 cifre: label stabile, cardinalita' finita.
    assert http_requests_total._labelnames == ("method", "status")
    assert http_request_duration_seconds._labelnames == ("method",)


def test_metric_names_and_no_path_label():
    assert f"{http_requests_total._name}_total" == "spesemed_http_requests_total"
    assert http_request_duration_seconds._name == "spesemed_http_request_duration_seconds"
    # Nessuna label path/user (cardinalita' illimitata + PII).
    assert "path" not in http_requests_total._labelnames
    assert "user" not in http_requests_total._labelnames


def test_method_and_status_normalization():
    assert normalize_method("get") == "GET"
    assert normalize_method("POST") == "POST"
    assert normalize_method("BREW") == "OTHER"
    assert normalize_method(None) == "OTHER"

    assert normalize_status(200) == "200"
    assert normalize_status(404) == "404"
    assert normalize_status(599) == "599"
    assert normalize_status(999) == "unknown"
    assert normalize_status(None) == "unknown"


def test_health_hit_increments_http_metrics(test_client):
    before = _counter("GET", "200")
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200
    assert _counter("GET", "200") == before + 1.0


def test_not_found_increments_404(test_client):
    before = _counter("GET", "404")
    response = test_client.get("/does-not-exist")
    assert response.status_code == 404
    assert _counter("GET", "404") == before + 1.0


def test_duration_histogram_observed(test_client):
    before = _duration_sum("GET")
    assert test_client.get("/api/v1/health").status_code == 200
    assert _duration_sum("GET") >= before


def test_labeled_histogram_reset_between_tests():
    """Il reset autouse azzera anche l'Histogram labelizzato (child per method).

    Senza reset dei child il parent di un Histogram con labelnames non espone
    _sum/_buckets: il reset sarebbe un no-op e i sample contaminerebbero i
    test successivi.
    """
    assert _duration_sum("GET") == 0.0


def test_metrics_scrape_not_counted(test_client):
    before = _counter("GET", "200")
    for _ in range(3):
        test_client.get("/metrics")
    assert _counter("GET", "200") == before


def test_unhandled_exception_counted_as_500():
    app = FastAPI()

    @app.middleware("http")
    async def _metrics(request, call_next):
        return await prometheus_http_metrics(request, call_next)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    before = _counter("GET", "500")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")
    assert response.status_code == 500
    assert _counter("GET", "500") == before + 1.0

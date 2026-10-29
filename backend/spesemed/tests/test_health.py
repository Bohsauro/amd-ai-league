"""SPESEMED - Test per endpoint /health e / (root meta)."""
from __future__ import annotations


def test_health_ok(test_client):
    """GET /api/v1/health ritorna 200 con openrouter_configured=False (no key in test)."""
    r = test_client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "spesemed-api"
    assert "version" in body
    assert body["openrouter_configured"] is False  # nessuna key in test


def test_root(test_client):
    """GET / ritorna info meta dell'API (200)."""
    r = test_client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "SPESEMED API"
    assert "version" in body
    assert body["phase"].startswith("3")  # Fase 3
    assert "endpoints" in body
    # Verifica che refresh e logout siano elencati
    endpoints = body["endpoints"]["auth"]
    assert any("signup" in e for e in endpoints)
    assert any("login" in e for e in endpoints)
    assert any("refresh" in e for e in endpoints)
    assert any("logout" in e for e in endpoints)


def test_openapi_exposes_auth_endpoints(test_client):
    """OpenAPI schema deve esporre i 5 endpoint di Fase 3."""
    r = test_client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/v1/auth/signup" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/extract" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/health" in paths

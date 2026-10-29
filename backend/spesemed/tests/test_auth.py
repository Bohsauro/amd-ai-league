"""SPESEMED - Test per endpoint auth (signup, login, refresh, logout).

Usa mock_supabase_client per evitare chiamate reali a Supabase.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# NB: mock_supabase fixture definita in tests/conftest.py (DI-friendly single-site patch).
# Era presente qui in Fase 3 ma e' stata rimossa: pytest la prendeva da conftest, sovrascrivendo
# la fixture completa (che patcha anche is_supabase_configured=True). Vedi PROJECT_STATUS.md.


def test_signup_503_without_supabase(test_client):
    """POST /auth/signup senza SUPABASE configurato ritorna 503."""
    r = test_client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert r.status_code == 503
    assert "Supabase" in r.json()["detail"]


def test_login_503_without_supabase(test_client):
    """POST /auth/login senza SUPABASE configurato ritorna 503."""
    r = test_client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert r.status_code == 503


def test_refresh_503_without_supabase(test_client):
    """POST /auth/refresh senza SUPABASE configurato ritorna 503."""
    r = test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "fake-refresh-token-min-10-chars"},
    )
    assert r.status_code == 503


def test_login_401_on_invalid_credentials(test_client, mock_supabase):
    """POST /auth/login con credenziali invalide ritorna 401 generico."""
    # Sovrascrivi il default (mock ritorna OK) per simulare errore
    mock_supabase.auth.sign_in_with_password.side_effect = Exception("invalid_grant")
    r = test_client.post(
        "/api/v1/auth/login",
        json={"email": "wrong@example.com", "password": "wrongpass"},
    )
    assert r.status_code == 401
    # Messaggio generico anti-enumeration
    assert r.json()["detail"] == "Credenziali non valide."


def test_login_success_returns_tokens(test_client, mock_supabase):
    """POST /auth/login OK ritorna AuthResponse con access/refresh token."""
    r = test_client.post(
        "/api/v1/auth/login",
        json={"email": "ok@example.com", "password": "validpass123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "fake-jwt-token-test"
    assert body["user_id"] == "user-uuid-test-1234"
    assert body["refresh_token"] == "fake-refresh-token-test"
    assert body["expires_in"] == 3600


def test_signup_validation_short_password(test_client):
    """POST /auth/signup con password <8 caratteri ritorna 422 (Pydantic validation)."""
    r = test_client.post(
        "/api/v1/auth/signup",
        json={"email": "test@example.com", "password": "short"},
    )
    assert r.status_code == 422


def test_logout_requires_bearer(test_client):
    """POST /auth/logout senza Authorization Bearer ritorna 401."""
    r = test_client.post("/api/v1/auth/logout")
    assert r.status_code == 401
    assert "Bearer" in r.json()["detail"]


def test_logout_with_bearer_returns_204(test_client):
    """POST /auth/logout con Bearer OK ritorna 204 No Content."""
    r = test_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer fake-bearer-token"},
    )
    # Senza supabase_client configurato -> best-effort return None (204)
    assert r.status_code in (204, 503)  # 204 se best-effort, 503 se supabase OK + errore


def test_refresh_returns_new_tokens(test_client, mock_supabase):
    """POST /auth/refresh con refresh_token valido ritorna nuovi tokens (rotazione)."""
    r = test_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "valid-refresh-token-12345"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "user_id" in body

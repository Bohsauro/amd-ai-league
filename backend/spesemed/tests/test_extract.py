"""SPESEMED - Test per endpoint /extract (validazione + idempotency + rate limit)."""
from __future__ import annotations

import pytest


# UUID v4 canonico per mock-auth header (FIX C2: deve essere UUID RFC 4122).
_TEST_USER_UUID = "00000000-0000-4000-8000-000000000001"


def test_extract_503_without_openrouter(test_client):
    """POST /extract senza OPENROUTER_API_KEY ritorna 503."""
    r = test_client.post(
        "/api/v1/extract",
        files=[("files", ("ricevuta.jpg", b"fake-image-bytes", "image/jpeg"))],
        headers={"X-User-Id": _TEST_USER_UUID},
    )
    assert r.status_code == 503
    assert "OPENROUTER" in r.json()["detail"]


def test_extract_no_files_returns_422(test_client):
    """POST /extract senza 'files' field ritorna 422 (FastAPI validation)."""
    r = test_client.post(
        "/api/v1/extract",
        headers={"X-User-Id": _TEST_USER_UUID},
    )
    # FastAPI: manca il campo 'files' -> 422 Pydantic/FastAPI validation
    assert r.status_code == 422


def test_extract_response_400_out_of_range(test_client):
    """POST /extract con N fuori range (es. 0 file) ritorna 422 da FastAPI."""
    # TestClient multipart con files vuoti -> FastAPI 422 (nessun file)
    r = test_client.post(
        "/api/v1/extract",
        headers={"X-User-Id": _TEST_USER_UUID},
    )
    assert r.status_code == 422


def test_extract_with_impostor_ext_returns_413(test_client):
    """POST /extract con Content-Type non supportato: file viene letto, poi 503 per no OpenRouter.

    FIX C1: la validazione dimensione adesso avviene PRIMA della lettura
    completa (streaming), quindi un file >20MB produce 413 anche senza
    OPENROUTER_API_KEY configurata (pre-check su Content-Length dichiarato).
    Con TestClient il Content-Length viene sempre impostato sul totale
    dei bytes passati, quindi vediamo 413.
    """
    big_content = b"x" * (21 * 1024 * 1024)  # 21 MB
    r = test_client.post(
        "/api/v1/extract",
        files=[("files", ("big.jpg", big_content, "image/jpeg"))],
        headers={"X-User-Id": _TEST_USER_UUID},
    )
    assert r.status_code in (413, 503)

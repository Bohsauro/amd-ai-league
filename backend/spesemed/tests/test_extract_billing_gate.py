"""SPESEMED - Gating billing su POST /api/v1/extract (Fase 4C-C7).

Offline: mock Supabase + extract_from_file, nessuna chiamata di rete.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from spesemed.api.config import settings


# =============================================================================
# Gating POST /api/v1/extract (Fase 4C-C7)
# =============================================================================

_TEST_USER_UUID = "00000000-0000-4000-8000-000000000001"
_ONE_FILE = [("files", ("ricevuta.jpg", b"fake-image-bytes", "image/jpeg"))]


def _table_mock(rows):
    """MagicMock di una tabella supabase con catena select/update/upsert."""
    table = MagicMock()
    for method in ("select", "eq", "limit", "update", "upsert", "insert"):
        getattr(table, method).return_value = table
    table.execute.return_value = MagicMock(data=rows)
    return table


def _entitlement_row(**overrides):
    row = {
        "user_id": _TEST_USER_UUID,
        "plan": "pro",
        "status": "active",
        "current_period_end": "2999-01-01T00:00:00+00:00",
        "extractions_limit": 100,
        "extractions_used": 0,
    }
    row.update(overrides)
    return row


def _patch_tables(monkeypatch, mock_supabase, entitlements, extractions):
    tables = {"entitlements": entitlements, "extractions": extractions}
    monkeypatch.setattr(mock_supabase, "table", lambda name: tables.get(name, _table_mock([])))


def _fake_spesa():
    from spesemed.core.models import SpesaMedica

    return SpesaMedica(
        data_spesa="2024-01-15",
        esercente="Farmacia Test",
        importo_totale=42.50,
        categoria_spesa="Farmaci",
    )


class TestExtractBillingGating:
    def test_extract_gated_402_when_billing_enabled_and_no_entitlement(
        self, monkeypatch, mock_supabase, test_client, auth_headers
    ):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-gating-test")
        _patch_tables(
            monkeypatch,
            mock_supabase,
            entitlements=_table_mock([]),
            extractions=_table_mock([]),
        )

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 402
        body = r.json()
        assert body["code"] == "payment_required"
        assert "Piano" in body["detail"]

    def test_extract_not_gated_when_billing_disabled(self, monkeypatch, test_client, auth_headers):
        monkeypatch.setattr(settings, "billing_enabled", False)
        monkeypatch.setattr(settings, "openrouter_api_key", "")

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 503
        assert r.status_code != 402
        assert "OPENROUTER" in r.json()["detail"]

    def test_extract_gated_402_when_entitlement_expired(
        self, monkeypatch, mock_supabase, test_client, auth_headers
    ):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-gating-test")
        _patch_tables(
            monkeypatch,
            mock_supabase,
            entitlements=_table_mock([_entitlement_row(current_period_end="2000-01-01T00:00:00+00:00")]),
            extractions=_table_mock([]),
        )

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 402
        assert r.json()["code"] == "payment_required"

    def test_extract_gated_402_when_quota_exhausted(
        self, monkeypatch, mock_supabase, test_client, auth_headers
    ):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-gating-test")
        _patch_tables(
            monkeypatch,
            mock_supabase,
            entitlements=_table_mock([_entitlement_row(extractions_used=100, extractions_limit=100)]),
            extractions=_table_mock([]),
        )

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 402
        assert r.json()["code"] == "payment_required"

    def test_extract_ok_when_entitlement_active(
        self, monkeypatch, mock_supabase, test_client, auth_headers
    ):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-gating-test")
        monkeypatch.setattr(
            "spesemed.api.routes.extract.extract_from_file",
            lambda *args, **kwargs: _fake_spesa(),
        )
        entitlements = _table_mock([_entitlement_row()])
        _patch_tables(monkeypatch, mock_supabase, entitlements, _table_mock([]))

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1
        entitlements.update.assert_called_once()
        assert entitlements.update.call_args.args[0]["extractions_used"] == 1

    def test_extract_cache_hit_does_not_consume_quota(
        self, monkeypatch, mock_supabase, test_client, auth_headers
    ):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "openrouter_api_key", "fake-key-for-gating-test")
        spesa = _fake_spesa()
        entitlements = _table_mock([_entitlement_row()])
        _patch_tables(
            monkeypatch,
            mock_supabase,
            entitlements,
            _table_mock([{"data": spesa.to_dict(), "model": "google/gemini-2.5-flash-lite"}]),
        )

        r = test_client.post("/api/v1/extract", files=_ONE_FILE, headers=auth_headers)

        assert r.status_code == 200, r.text
        assert r.json()["cached"] == [True]
        entitlements.update.assert_not_called()

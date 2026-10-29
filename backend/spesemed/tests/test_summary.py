"""SPESEMED - Test offline per GET /api/v1/summary (Profilo utente / usage).

Copre:
  - risposta vuota (nessuna spesa, nessun job)
  - aggregazione corretta: totali, importo totale, per categoria, job stats
  - 503 quando Supabase non configurato
  - esposizione in OpenAPI
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _spesa(data: dict) -> dict:
    """Riga extractions come ritornata da Supabase (colonna `data`)."""
    return {"data": data}


def _config_mock(mock_supabase, extractions=None, jobs=None):
    """Configura il mock Supabase per la rotta summary.

    NB: il client mockato in conftest ha `client.table()` che ritorna
    SEMPRE la stessa tabella; per summary servono due tabelle diverse
    (`extractions` con righe data + `jobs` con status).
    """
    mock_supabase.reset_mock()

    def _table(name: str):
        if name == "extractions":
            result = MagicMock()
            result.data = extractions or []
            return MagicMock(select=lambda *a, **k: MagicMock(
                eq=lambda *a, **k: MagicMock(execute=lambda: result)))
        if name == "jobs":
            result = MagicMock()
            result.data = jobs or []
            return MagicMock(select=lambda *a, **k: MagicMock(
                eq=lambda *a, **k: MagicMock(execute=lambda: result)))
        raise AssertionError(f"tabella inattesa: {name}")

    mock_supabase.table.side_effect = _table
    return mock_supabase


class TestSummary:
    def test_summary_vuoto(self, test_client, mock_supabase, auth_headers):
        """Nessuna spesa e nessun job → zeri e lista categorie vuota."""
        _config_mock(mock_supabase)
        r = test_client.get("/api/v1/summary", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_spese"] == 0
        assert body["totale_importo"] == 0.0
        assert body["total_jobs"] == 0
        assert body["jobs_done"] == 0
        assert body["jobs_failed"] == 0
        assert body["jobs_in_progress"] == 0
        assert body["per_categoria"] == []

    def test_summary_aggrega_spese(self, test_client, mock_supabase, auth_headers):
        """3 spese (2 Farmaci + 1 Visita) → totali e per_categoria corretti."""
        _config_mock(
            mock_supabase,
            extractions=[
                _spesa({
                    "data_spesa": "2024-03-15",
                    "esercente": "Farmacia A",
                    "importo_totale": 45.5,
                    "codice_fiscale_paziente": "RSSMRA85A01H501W",
                    "categoria_spesa": "Farmaci",
                }),
                _spesa({
                    "data_spesa": "2024-04-02",
                    "esercente": "Farmacia B",
                    "importo_totale": 10.0,
                    "codice_fiscale_paziente": "RSSMRA85A01H501W",
                    "categoria_spesa": "Farmaci",
                }),
                _spesa({
                    "data_spesa": "2024-05-10",
                    "esercente": "Studio Dentistico",
                    "importo_totale": 120.0,
                    "codice_fiscale_paziente": "RSSMRA85A01H501W",
                    "categoria_spesa": "Visita Specialistica",
                }),
            ],
            jobs=[
                {"status": "done"},
                {"status": "done"},
                {"status": "failed"},
                {"status": "processing"},
            ],
        )
        r = test_client.get("/api/v1/summary", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_spese"] == 3
        assert body["totale_importo"] == pytest.approx(175.5)  # 45.5+10+120
        # Ordinamento per importo decrescente.
        assert body["per_categoria"] == [
            {"categoria": "Visita Specialistica", "importo": 120.0, "count": 1},
            {"categoria": "Farmaci", "importo": 55.5, "count": 2},
        ]
        # Job stats.
        assert body["total_jobs"] == 4
        assert body["jobs_done"] == 2
        assert body["jobs_failed"] == 1
        assert body["jobs_in_progress"] == 1

    def test_summary_riga_non_parsabile_skippata(self, test_client, mock_supabase, auth_headers):
        """Una riga extractions malformata non fa fallire il summary (viene skippata)."""
        _config_mock(
            mock_supabase,
            extractions=[
                _spesa({"data_spesa": "2024-03-15", "esercente": "X",
                        "importo_totale": 5.0, "categoria_spesa": "Farmaci"}),
                _spesa({"importo_totale": "not-a-number"}),  # riga invalida
            ],
        )
        r = test_client.get("/api/v1/summary", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total_spese"] == 1
        assert body["totale_importo"] == 5.0

    def test_summary_no_supabase(self, test_client, auth_headers):
        """Supabase non configurato → 503 (by design, come gli altri endpoint)."""
        r = test_client.get("/api/v1/summary", headers=auth_headers)
        assert r.status_code == 503

    def test_summary_openapi(self, test_client):
        """GET /api/v1/summary deve essere esposto in OpenAPI."""
        r = test_client.get("/openapi.json")
        assert r.status_code == 200
        assert "/api/v1/summary" in r.json()["paths"]

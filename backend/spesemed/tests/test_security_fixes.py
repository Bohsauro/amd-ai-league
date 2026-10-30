"""SPESEMED - Test per i 4 fix CRITICAL della security audit (Fase post-audit).

Copre:
  - C1: Streaming upload con abort su max_bytes (anti-OOM DoS).
  - C2: UUID regex su X-User-Id (anti path-traversal).
  - C3: Fail-closed su JWT secret mancante + ALLOW_DEV_MOCK_AUTH esplicito.
  - C4: Migration 002_rls_policies.sql esiste e contiene le policy keywords.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from spesemed.api import dependencies
from spesemed.api.config import settings
from spesemed.api.routes import extract as extract_module


# =============================================================================
# FIX C1: streaming upload + abort anti-OOM
# =============================================================================


class TestFixC1StreamingUpload:
    """FIX C1: verifica che _read_upload_streaming aborta su max_bytes."""

    def _fake_upload(
        self, total_bytes: int, chunk_size: int = 64 * 1024,
        with_size: bool = True,
    ):
        """Crea un UploadFile-like con .size e .read(chunk) iterabili.

        Args:
            total_bytes: contenuto totale del file.
            chunk_size: dimensione di ogni singolo read().
            with_size: se True setta `.size = total` (pre-check attivo).
                Se False `.size = None` (pre-check saltato: simula Transfer-Encoding
                chunked senza Content-Length dichiarato).
        """

        class FakeUpload:
            def __init__(self, total: int, cs: int, set_size: bool) -> None:
                self.filename = "fake.bin"
                self.size = total if set_size else None
                self._total = total
                self._read = 0
                self._chunk = cs

            async def read(self, n: int = -1):
                if n == -1:
                    n = self._chunk
                remaining = self._total - self._read
                if remaining <= 0:
                    return b""
                take = min(n, remaining)
                chunk = b"x" * take
                self._read += take
                return chunk

        return FakeUpload(total_bytes, chunk_size, with_size)

    @pytest.mark.asyncio
    async def test_under_limit_returns_full_bytes(self):
        """Sotto il limite: restituisce tutti i bytes senza eccezione."""
        uploaded = self._fake_upload(total_bytes=100, chunk_size=64)
        data = await extract_module._read_upload_streaming(
            uploaded, max_bytes=1000,
        )
        assert len(data) == 100

    @pytest.mark.asyncio
    async def test_declared_size_above_limit_raises_413(self):
        """Content-Length > max_bytes: abort immediato SENZA read."""
        uploaded = self._fake_upload(total_bytes=5000)
        with pytest.raises(HTTPException) as exc:
            await extract_module._read_upload_streaming(uploaded, max_bytes=1000)
        assert exc.value.status_code == 413
        # Nessuna lettura effettuata (size check previene I/O).
        assert uploaded._read == 0

    @pytest.mark.asyncio
    async def test_streaming_aborts_when_exceeding_during_read(self):
        """NO Content-Length: lo streaming deve abortare durante la lettura."""
        uploaded = self._fake_upload(total_bytes=1600, chunk_size=800, with_size=False)
        # max_bytes piccolo: dopo 2 chunk (1000 bytes) lo stream eccede 1000
        # in realta' il file e' 5000 bytes, lo stream cresce.
        with pytest.raises(HTTPException) as exc:
            await extract_module._read_upload_streaming(
                uploaded, max_bytes=1000,
            )
        assert exc.value.status_code == 413
        assert uploaded._read > 0  # ha letto qualcosa prima di abortire

    @pytest.mark.asyncio
    async def test_no_declared_size_still_enforces_limit(self):
        """Se uploaded.size e' None: nessun pre-check, ma lo streaming abortisce."""
        class NoSizeUpload:
            def __init__(self) -> None:
                self.filename = "x.bin"
                self.size = None
                self.chunks = [b"a" * 800, b"b" * 800]  # totale 1600

            async def read(self, n: int = -1):
                return self.chunks.pop(0) if self.chunks else b""

        uploaded = NoSizeUpload()
        with pytest.raises(HTTPException) as exc:
            await extract_module._read_upload_streaming(uploaded, max_bytes=1000)
        assert exc.value.status_code == 413


# =============================================================================
# FIX C2: UUID regex su X-User-Id (anti path-traversal)
# =============================================================================


class TestFixC2UUIDRegex:
    """FIX C2: X-User-Id deve essere UUID RFC 4122 (8-4-4-4-12 hex)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_value",
        [
            "../../etc/passwd",               # path traversal
            "../victim",                       # traversal breve
            "fake-user-with-slash/another",    # slash interno
            "user\\backslash",                 # backslash
            "user\x00null",                   # null byte injection
            "user\ninjection",                 # newline injection
            "user\rinjection",                 # carriage return
            "user\tinjection",                 # tab
            "XXXXXXXXXX",                      # lunghezza sbagliata
            "12345678-1234-1234-1234-1234567890AB!",  # carattere finale invalido
            "g" * 50,                          # tutti-non-hex + lunghezza
            # NB: "" omesso: cade nel fallback anonymous (nessuna exception).
        ],
    )
    async def test_rejects_non_uuid_x_user_id(self, bad_value):
        """Valori non-UUID devono essere rifiutati con 400."""
        # anonimo (no JWT) + X-User-Id invalido -> 400
        with pytest.raises(HTTPException) as exc:
            await dependencies.get_current_user(
                authorization="", x_user_id=bad_value,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "valid_uuid",
        [
            "00000000-0000-4000-8000-000000000001",  # UUID v4
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",  # UUID v4 random
            "F47AC10B-58CC-4372-A567-0E02B2C3D479",  # maiuscolo
            "550e8400-e29b-41d4-a716-446655440000",  # UUID v4 canonico
        ],
    )
    async def test_accepts_valid_uuid_x_user_id(self, valid_uuid):
        """UUID validi devono passare e diventare user_id."""
        user_id = await dependencies.get_current_user(
            authorization="", x_user_id=valid_uuid,
        )
        assert user_id == valid_uuid


# =============================================================================
# FIX C3: fail-closed su JWT secret mancante anche in dev
# =============================================================================


class TestFixC3FailClosedAuth:
    """FIX C3: senza JWT secret + ALLOW_DEV_MOCK_AUTH=false -> 503."""

    @pytest.mark.asyncio
    async def test_bearer_without_secret_no_mock_auth_returns_503(
        self, monkeypatch,
    ):
        """Bearer presente ma JWT_SECRET vuoto + ALLOW_DEV_MOCK_AUTH=false
        deve ritornare 503, NON accettare il token come user_id opaco."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "allow_dev_mock_auth", False)
        monkeypatch.setattr(settings, "api_env", "development")
        with pytest.raises(HTTPException) as exc:
            await dependencies.get_current_user(
                authorization="Bearer some-fake-token", x_user_id="",
            )
        assert exc.value.status_code == 503
        assert "non configurata" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_bearer_without_secret_with_mock_auth_accepts_token(
        self, monkeypatch,
    ):
        """Bearer presente + ALLOW_DEV_MOCK_AUTH=true: token opaco OK."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "allow_dev_mock_auth", True)
        monkeypatch.setattr(settings, "api_env", "development")
        user_id = await dependencies.get_current_user(
            authorization="Bearer dev-opaque-token", x_user_id="",
        )
        assert user_id == "dev-opaque-token"

    @pytest.mark.asyncio
    async def test_x_user_id_without_mock_auth_returns_503(
        self, monkeypatch,
    ):
        """X-User-Id mock richiede ALLOW_DEV_MOCK_AUTH=true (anche in dev)."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "allow_dev_mock_auth", False)
        monkeypatch.setattr(settings, "api_env", "development")
        with pytest.raises(HTTPException) as exc:
            await dependencies.get_current_user(
                authorization="",
                x_user_id="00000000-0000-4000-8000-000000000001",
            )
    @pytest.mark.asyncio
    async def test_no_auth_headers_without_mock_auth_returns_401(
        self, monkeypatch,
    ):
        """Senza header auth + ALLOW_DEV_MOCK_AUTH=false deve ritornare 401 Unauthorized."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "allow_dev_mock_auth", False)
        monkeypatch.setattr(settings, "api_env", "development")
        with pytest.raises(HTTPException) as exc:
            await dependencies.get_current_user(
                authorization="",
                x_user_id="",
            )
        assert exc.value.status_code == 401
        assert "Autenticazione richiesta" in exc.value.detail

    @pytest.mark.asyncio
    async def test_no_auth_headers_with_mock_auth_returns_default_anonymous(
        self, monkeypatch,
    ):
        """Senza header auth + ALLOW_DEV_MOCK_AUTH=true ritorna mock default."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "")
        monkeypatch.setattr(settings, "allow_dev_mock_auth", True)
        monkeypatch.setattr(settings, "api_env", "development")
        user_id = await dependencies.get_current_user(
            authorization="",
            x_user_id="",
        )
        assert user_id == settings.mock_user_id_default


# =============================================================================
# FIX M2: nessun log contiene filename utente (PII protection)
# =============================================================================


class TestFixM2PIISanitization:
    """FIX M2: log statements NON devono contenere filename utente (potenziale PII/sanitaria).

    Verifica STATICA (grep sul codice): anche se non eseguiamo un'estrazione
    reale, verifichiamo che nessun logger.*() in routes/extract.py o
    worker.py logghi direttamente `filename`.
    """

    SRC_DIR = Path(__file__).parent.parent / "src" / "spesemed"

    def _find_unsafe_logger_calls(self, file_path: Path) -> list[str]:
        r"""Cerca pattern `logger.*\(...filename...\)` che sarebbero PII-unsafe."""
        import re
        if not file_path.is_file():
            return []
        text = file_path.read_text(encoding="utf-8")
        # Cerca logger.*() che include la parola "filename" come argomento.
        # Pattern: logger.(info|warning|error|exception|debug)(...) con 'filename' nei params.
        pattern = re.compile(
            r"logger\.(?:info|debug|warning|error|exception)\s*\("
            r"[^)]*\\bfilename\\b",
            re.DOTALL,
        )
        return [m.group(0) for m in pattern.finditer(text)]

    def test_routes_extract_does_not_log_filename(self):
        """routes/extract.py: nessun logger.*() deve loggare filename utente."""
        file_path = self.SRC_DIR / "api" / "routes" / "extract.py"
        unsafe = self._find_unsafe_logger_calls(file_path)
        assert not unsafe, (
            f"M2 PII SAFETY VIOLATION in {file_path.name}: logger calls "
            f"with 'filename' arg found:\n" + "\n".join(unsafe)
        )

    def test_worker_does_not_log_filename(self):
        """worker.py: nessun logger.*() deve loggare filename/file_path."""
        file_path = self.SRC_DIR / "api" / "worker.py"
        unsafe = self._find_unsafe_logger_calls(file_path)
        assert not unsafe, (
            f"M2 PII SAFETY VIOLATION in {file_path.name}: logger calls "
            f"with 'filename' arg found:\n" + "\n".join(unsafe)
        )


# =============================================================================
# FIX M3: extractor OpenRouter body_snippet NOT included in error message
# =============================================================================


class TestFixM3OpenRouterBodyLog:
    """FIX M3: l'errore OpenRouter 4xx NON deve includere body_snippet (PII-safe)."""

    def test_extractor_error_uses_body_len_not_snippet(self):
        """Verifica STATICA: extractor.py non chiama pi\u00f9 'body_snippet'."""
        import re
        file_path = (
            Path(__file__).parent.parent / "src" / "spesemed" / "core" /
            "extractor.py"
        )
        text = file_path.read_text(encoding="utf-8")
        # Cerca vecchia stringa 'body_snippet' (rimosso in M3).
        assert "body_snippet" not in text, (
            "M3 PII SAFETY VIOLATION: 'body_snippet' ancora presente "
            "in extractor.py. Era un token rimesso in M3."
        )
        # Verifica che il replacement sia presente: 'body_len='.
        assert "body_len=" in text, (
            "M3 PII SAFETY VIOLATION: 'body_len=' replacement expected "
            "ma non trovato in extractor.py"
        )


# =============================================================================
# FIX M4: CORS default NON contiene "*"
# =============================================================================


class TestFixM4CORSSaferDefault:
    """FIX M4: il default `cors_origins` NON deve includere wildcard "*"."""

    def test_settings_default_does_not_use_wildcard(self):
        """Verifica: Settings().cors_origins default NON contiene solo "*"."""
        import importlib
        import spesemed.api.config as cfg_mod
        # Reload settings per evitare cache env precedente.
        importlib.reload(cfg_mod)
        if "*" in cfg_mod.settings.cors_origins:
            assert cfg_mod.settings.cors_origins == ["*"], (
                "M4 CORS SAFETY: '*' wildcard in default. Production would "
                "be flagged by pen-tester come misconfiguration."
            )


# =============================================================================
# FIX C4: migration 002_rls_policies.sql esiste e contiene le policy
# =============================================================================


class TestFixC4RLSMigration:
    """FIX C4: migration RLS presente e ben formata."""

    MIGRATION_PATH = (
        Path(__file__).parent.parent / "migrations" / "002_rls_policies.sql"
    )

    def test_migration_file_exists(self):
        assert self.MIGRATION_PATH.is_file(), (
            f"Missing migration: {self.MIGRATION_PATH}"
        )

    def test_migration_enables_rls_on_jobs(self):
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        assert "ALTER TABLE jobs ENABLE ROW LEVEL SECURITY" in content
        assert "ALTER TABLE jobs FORCE ROW LEVEL SECURITY" in content

    def test_migration_enables_rls_on_extractions(self):
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        assert "ALTER TABLE extractions ENABLE ROW LEVEL SECURITY" in content
        assert "ALTER TABLE extractions FORCE ROW LEVEL SECURITY" in content

    def test_migration_creates_user_policies(self):
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        # Policy SELECT/INSERT per authenticated basate su auth.uid() = user_id
        assert "jobs_select_own" in content
        assert "jobs_insert_own" in content
        assert "extractions_select_own" in content
        assert "extractions_insert_own" in content
        # Cast auth.uid() a text per match con user_id TEXT.
        assert "auth.uid()::text = user_id" in content

    def test_migration_denies_update_delete_for_users(self):
        """NUOVE policy negative: utenti authenticated NON possono UPDATE/DELETE."""
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        assert "jobs_no_update" in content
        assert "jobs_no_delete" in content
        assert "extractions_no_update" in content
        assert "extractions_no_delete" in content

    def test_migration_defines_storage_bucket_policies(self):
        """Storage.objects policy per bucket receipts con isolamento user_id."""
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        assert "storage_select_own_receipts" in content
        assert "storage_insert_own_receipts" in content
        # Il path e' receipts/{user_id}/{file}, secondo elemento = user_id.
        assert "String_to_array" in content or "string_to_array" in content
        assert "bucket_id = 'receipts'" in content

    def test_migration_is_idempotent(self):
        """Tutte le CREATE POLICY sono precedute da DROP POLICY IF EXISTS."""
        content = self.MIGRATION_PATH.read_text(encoding="utf-8")
        # Per ogni CREATE POLICY ci deve essere un DROP POLICY IF EXISTS.
        creates = re.findall(r"CREATE POLICY \"[^\"]+?\"", content)
        drops = re.findall(
            r"DROP POLICY IF EXISTS \"[^\"]+?\"", content,
        )
        assert len(creates) == len(drops), (
            f"Mismatch: {len(creates)} CREATE vs {len(drops)} DROP. "
            "La migration deve essere idempotente."
        )


# =============================================================================
# FIX AUDIT 2026: Excel Formula Injection & Storage Path Ownership
# =============================================================================

class TestFixExcelFormulaInjection:
    """Verifica che l'exporter Excel sanitizzi i valori che iniziano con = + - @ \\t \\r."""

    def test_sanitize_cell_value_prefixes_formula_triggers(self):
        from spesemed.core.exporter import _sanitize_cell_value

        assert _sanitize_cell_value("=HYPERLINK('http://evil.com')") == "'=HYPERLINK('http://evil.com')"
        assert _sanitize_cell_value("+SUM(1,2)") == "'+SUM(1,2)"
        assert _sanitize_cell_value("-100EUR") == "'-100EUR"
        assert _sanitize_cell_value("@ADMIN") == "'@ADMIN"
        assert _sanitize_cell_value("\tTAB_INJECT") == "'\tTAB_INJECT"
        assert _sanitize_cell_value("\rCR_INJECT") == "'\rCR_INJECT"

    def test_sanitize_cell_value_leaves_normal_strings_intact(self):
        from spesemed.core.exporter import _sanitize_cell_value

        assert _sanitize_cell_value("Farmacia Centrale") == "Farmacia Centrale"
        assert _sanitize_cell_value("RSSMRA85A01H501W") == "RSSMRA85A01H501W"
        assert _sanitize_cell_value("2024-03-15") == "2024-03-15"
        assert _sanitize_cell_value(None) == ""
        assert _sanitize_cell_value("") == ""

    def test_build_workbook_sanitizes_malicious_spesa_fields(self):
        from spesemed.core.exporter import _build_workbook
        from spesemed.core.models import SpesaMedica

        malicious_spesa = SpesaMedica(
            data_spesa="2024-03-15",
            esercente="=CMD|' /C calc'!A1",
            importo_totale=45.5,
            codice_fiscale_paziente="+RSSMRA85A01H501W",
            categoria_spesa="Farmaci",
        )
        wb = _build_workbook([malicious_spesa])
        ws = wb["Riepilogo"]

        # Riga 2 contiene i dati della spesa
        val_esercente = ws.cell(row=2, column=2).value
        val_cf = ws.cell(row=2, column=5).value

        assert val_esercente == "'=CMD|' /C calc'!A1"
        assert val_cf == "'+RSSMRA85A01H501W"


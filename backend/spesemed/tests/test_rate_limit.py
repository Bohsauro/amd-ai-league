"""SPESEMED - Test del rate-limit storage (Fase 4 Redis).

Verifica che ``rate_limit._build_storage_uri`` risolva correttamente lo
storage backend slowapi/limits a partire dalla config:

    - ``memory`` / vuoto          -> ``memory://`` (per-worker, dev).
    - ``redis://host:port/db``    -> URI passata direttamente (multi-worker).
    - ``redis``                   -> usa REDIS_URL, con fallback safe a memory
                                     se REDIS_URL e' assente (WARNING).
    - valore non riconosciuto     -> fallback safe a ``memory://``.

Plus: ``_redact_redis_uri`` non deve leakare password nei log.

NB: queste funzioni leggono i campi dal singleton ``settings`` a runtime,
quindi possiamo monkeypatchare senza toccare il Limiter gia' istanziato.
"""
from __future__ import annotations

import logging
from typing import Optional

import pytest

from spesemed.api.config import settings
from spesemed.api.rate_limit import (
    _build_storage_uri,
    _redact_redis_uri,
    _storage_uri,
)


def _set_storage(monkeypatch, backend: str, redis_url: str = "") -> None:
    monkeypatch.setattr(settings, "rate_limit_storage_backend", backend)
    monkeypatch.setattr(settings, "redis_url", redis_url)


class TestBuildStorageUri:
    def test_empty_backend_falls_back_to_memory(self, monkeypatch):
        _set_storage(monkeypatch, "   ")
        assert _build_storage_uri() == "memory://"

    def test_memory_backend_returns_memory_uri(self, monkeypatch):
        _set_storage(monkeypatch, "memory")
        assert _build_storage_uri() == "memory://"

    def test_direct_redis_uri_uses_uri(self, monkeypatch):
        _set_storage(monkeypatch, "redis://redis:6379/0")
        assert _build_storage_uri() == "redis://redis:6379/0"

    def test_direct_rediss_uri_uses_uri(self, monkeypatch):
        _set_storage(monkeypatch, "rediss://redis:6379/0")
        assert _build_storage_uri() == "rediss://redis:6379/0"

    def test_redis_keyword_uses_redis_url(self, monkeypatch):
        _set_storage(monkeypatch, "redis", "redis://localhost:6379/2")
        assert _build_storage_uri() == "redis://localhost:6379/2"

    def test_redis_keyword_with_credentials_kept_verbatim(self, monkeypatch):
        _set_storage(
            monkeypatch,
            "redis",
            "redis://user:pass@localhost:6379/0",
        )
        assert _build_storage_uri() == "redis://user:pass@localhost:6379/0"

    def test_redis_keyword_without_redis_url_falls_back_to_memory(self, monkeypatch, caplog):
        """RATE_LIMIT_STORAGE_BACKEND=redis ma REDIS_URL vuota => fallback memoria
        con WARNING esplicito (i limiti restano PER-WORKER)."""
        _set_storage(monkeypatch, "redis", "")
        with caplog.at_level(logging.WARNING, logger="spesemed.api.rate_limit"):
            uri = _build_storage_uri()
        assert uri == "memory://"
        assert any(
            "REDIS_URL non configurata" in r.getMessage()
            for r in caplog.records
        )

    def test_unknown_backend_falls_back_to_memory(self, monkeypatch, caplog):
        _set_storage(monkeypatch, "in-memory-db")
        with caplog.at_level(logging.WARNING, logger="spesemed.api.rate_limit"):
            uri = _build_storage_uri()
        assert uri == "memory://"
        assert any(
            "non riconosciuto" in r.getMessage()
            for r in caplog.records
        )

    def test_default_settings_resolve_to_memory(self):
        """Con i default (backend='memory'), la URI istanziata alla import e'
        memory:// (offline dev resta privo di dipendenze Redis)."""
        assert _storage_uri == "memory://"


class TestRedactRedisUri:
    def test_no_credentials_unchanged(self):
        assert _redact_redis_uri("redis://localhost:6379/0") == "redis://localhost:6379/0"

    def test_password_redacted(self):
        assert (
            _redact_redis_uri("redis://:secret123@localhost:6379/0")
            == "redis://:***@localhost:6379/0"
        )

    def test_username_password_redacted(self):
        assert (
            _redact_redis_uri("redis://admin:hunter2@redis:6379/0")
            == "redis://admin:***@redis:6379/0"
        )

    def test_username_only_unchanged(self):
        assert (
            _redact_redis_uri("redis://default@localhost:6379/0")
            == "redis://default@localhost:6379/0"
        )

    def test_rediss_scheme_handled(self):
        assert (
            _redact_redis_uri("rediss://:topsecret@localhost:6379/1")
            == "rediss://:***@localhost:6379/1"
        )
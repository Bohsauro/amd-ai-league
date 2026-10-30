"""SPESEMED - Test readiness Redis in lifespan (Fase 4C-A2).

Obiettivo: se RATE_LIMIT_STORAGE_BACKEND=redis ma Redis e' irraggiungibile,
l'app deve loggare un ERROR chiaro AL BOOT (non 500/429 randomici al primo hit).
Nessun secret nei test, nessuna connessione esterna: il path "raggiungibile"
e' mockato, quello "irraggiungibile" usa una porta locale chiusa o un mock.
"""
from __future__ import annotations

import logging

import redis
from fastapi.testclient import TestClient

import spesemed.api.main as main
from spesemed.api.config import settings


def _set_backend(monkeypatch, backend: str, redis_url: str = "") -> None:
    monkeypatch.setattr(settings, "rate_limit_storage_backend", backend)
    monkeypatch.setattr(settings, "redis_url", redis_url)


def test_memory_backend_skips_redis(monkeypatch, caplog):
    _set_backend(monkeypatch, "memory")
    with caplog.at_level(logging.DEBUG, logger="spesemed.api"):
        assert main._check_redis_readiness() is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_empty_backend_skips_redis(monkeypatch, caplog):
    _set_backend(monkeypatch, "   ")
    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        assert main._check_redis_readiness() is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_redis_backend_reports_error_when_unreachable(monkeypatch, caplog):
    _set_backend(monkeypatch, "redis", "redis://localhost:6399/0")

    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        ok = main._check_redis_readiness()

    assert ok is False
    assert any(
        "Redis" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR
    )


def test_direct_redis_uri_reports_error_when_unreachable(monkeypatch, caplog):
    _set_backend(monkeypatch, "redis://localhost:6399/0")

    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        ok = main._check_redis_readiness()

    assert ok is False
    assert any("Redis NON raggiungibile" in r.getMessage() for r in caplog.records)


def test_redis_keyword_without_url_reports_error(monkeypatch, caplog):
    _set_backend(monkeypatch, "redis", "")

    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        ok = main._check_redis_readiness()

    assert ok is False
    assert any("REDIS_URL" in r.getMessage() for r in caplog.records)


def test_reachable_redis_returns_true(monkeypatch, caplog):
    _set_backend(monkeypatch, "redis", "redis://localhost:6379/0")
    calls = {}

    class _FakeClient:
        def ping(self):
            calls["ping"] = True
            return True

    def _fake_from_url(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _FakeClient()

    monkeypatch.setattr(redis, "from_url", _fake_from_url)

    with caplog.at_level(logging.INFO, logger="spesemed.api"):
        ok = main._check_redis_readiness()

    assert ok is True
    assert calls["ping"] is True
    assert calls["url"] == "redis://localhost:6379/0"
    assert calls["kwargs"]["socket_connect_timeout"] == 2
    assert calls["kwargs"]["socket_timeout"] == 2
    assert any("Redis readiness OK" in r.getMessage() for r in caplog.records)


def test_credentials_redacted_in_error_log(monkeypatch, caplog):
    _set_backend(monkeypatch, "redis://:s3cret@localhost:6399/0")

    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        ok = main._check_redis_readiness()

    assert ok is False
    assert "s3cret" not in caplog.text
    assert ":***@" in caplog.text


def test_unknown_backend_skips_without_error(monkeypatch, caplog):
    _set_backend(monkeypatch, "memcached://nope")

    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        assert main._check_redis_readiness() is True
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_lifespan_invokes_redis_readiness(monkeypatch):
    called = {"count": 0}

    def _fake_readiness() -> bool:
        called["count"] += 1
        return True

    monkeypatch.setattr(main, "_check_redis_readiness", _fake_readiness)

    with TestClient(main.app) as client:
        assert client.get("/api/v1/health").status_code == 200

    assert called["count"] >= 1

"""SPESEMED - Test delle metriche Prometheus per autenticazione JWT.

Verifica:
  - Ogni fail path in jwt_decoder incrementa il counter correttamente
    (label `reason` discriminante).
  - Histogram `spesemed_jwt_decode_duration_seconds` osserva latenza anche
    su success path.
  - GET /metrics ritorna formato Prometheus exposition (text/plain v0.0.4).
  - POST /admin/auth/reset-jwks-cache rispetta X-Admin-Token (200 vs 403).
  - ADMIN_TOKEN vuoto => endpoint disabilitato (403 fail-closed).

NB: `conftest.py` contiene fixture autouse `_reset_prometheus_metrics` che
azzerra Counter/Histogram prima di ogni test.
"""
from __future__ import annotations

import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from spesemed.api import jwt_decoder
from spesemed.api.config import settings
from spesemed.api.metrics import (
    jwks_cache_resets_total,
    jwt_decode_duration_seconds,
    jwt_failures_total,
    record_failure,
)


# =============================================================================
# Helpers
# =============================================================================


def _get_counter_value(counter, reason: str = "") -> float:
    """Ritorna il valore del Counter per label reason. 0.0 se label assente.

    API: usa la property _value del sample. Per Counter con label
    (jwt_failures_total{reason=...}), counter.labels(reason=X)._value.get().
    Per Counter senza label (jwks_cache_resets_total), counter._value.get()
    direttamente (e' il parent sample). Funziona su prometheus-client 0.25.0.
    """
    try:
        if reason:
            return counter.labels(reason=reason)._value.get()
        # No-label counter: parent sample
        return counter._value.get()
    except (KeyError, AttributeError):
        return 0.0


# =============================================================================
# Counter correctness
# =============================================================================


class TestJWTFailureCounter:
    def test_record_failure_with_valid_reason(self):
        """record_failure incrementa il Counter per la label data."""
        record_failure("expired")
        assert _get_counter_value(jwt_failures_total, "expired") == 1.0
        record_failure("expired")
        assert _get_counter_value(jwt_failures_total, "expired") == 2.0

    def test_record_failure_with_unknown_reason_coerced(self):
        """Label sconosciuta viene coercita a general_decode_error."""
        record_failure("totally-unknown-label")
        assert _get_counter_value(jwt_failures_total, "general_decode_error") == 1.0
        # La label sconosciuta NON deve apparire (cardinality safe).
        assert _get_counter_value(jwt_failures_total, "totally-unknown-label") == 0.0

    def test_decode_header_malformed_increments(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "any-secret")
        with pytest.raises(HTTPException):
            jwt_decoder.decode_supabase_jwt("not-a-jwt-just-a-string")
        assert _get_counter_value(jwt_failures_total, "header_malformed") == 1.0

    def test_decode_alg_unsupported_increments(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "any-secret")
        token = jwt.encode(
            {"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 3600,
             "role": "authenticated"},
            "any-secret", algorithm="HS512",
        )
        with pytest.raises(HTTPException):
            jwt_decoder.decode_supabase_jwt(token)
        assert _get_counter_value(jwt_failures_total, "alg_unsupported") == 1.0

    def test_decode_expired_increments(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        now = int(time.time())
        token = jwt.encode(
            {"sub": "alice", "aud": "authenticated", "exp": now - 3600,
             "role": "authenticated"},
            "test-secret", algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            jwt_decoder.decode_supabase_jwt(token)
        assert _get_counter_value(jwt_failures_total, "expired") == 1.0

    def test_decode_role_service_role_increments(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        now = int(time.time())
        token = jwt.encode(
            {"sub": "attacker", "aud": "authenticated", "exp": now + 3600,
             "role": "service_role"},
            "test-secret", algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            jwt_decoder.decode_supabase_jwt(token)
        assert _get_counter_value(jwt_failures_total, "role_unauthorized") == 1.0


class TestJWTDecodeHistogram:
    def test_successful_decode_observes_duration(self, monkeypatch):
        """Anche la decode success incrementa il conteggio dell'histogram."""
        monkeypatch.setattr(settings, "supabase_jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "supabase_url", "")
        now = int(time.time())
        token = jwt.encode(
            {"sub": "alice", "aud": "authenticated", "exp": now + 3600,
             "role": "authenticated"},
            "test-secret", algorithm="HS256",
        )
        before_sum = jwt_decode_duration_seconds._sum.get()
        jwt_decoder.decode_supabase_jwt(token)
        after_sum = jwt_decode_duration_seconds._sum.get()
        assert after_sum > before_sum  # almeno 1 osservazione registrata


class TestMetricsEndpoint:
    def _build_client(self, admin_token: str = "",
                      prometheus_enabled: bool = True,
                      peer_ip: str = "127.0.0.1") -> TestClient:
        """Crea un TestClient con peer IP controllato.

        NB: TestClient default = peer "testclient" (non IP). Per allinearsi
        al default allowlist di metrics_acl ([127.0.0.1, ::1]), passiamo un
        client tuple con IP reale.
        """
        from spesemed.api.main import app
        # Patch settings prima dell'init TestClient.
        settings.prometheus_metrics_enabled = prometheus_enabled
        settings.admin_token = admin_token
        # NB: TestClient signature: TestClient(app, ...).
        # `client` parameter sets request.client.host (default ("testclient", 50000)).
        return TestClient(app, client=(peer_ip, 50000))

    def test_metrics_returns_prometheus_format(self):
        with self._build_client(peer_ip="127.0.0.1") as client:
            response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert b"spesemed_jwt_failures_total" in response.content

    def test_metrics_disabled_returns_404(self, monkeypatch):
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", False)
        from spesemed.api.main import app
        # /metrics disabled => 404 PRIMA dell'ACL check.
        # Anche con IP esterno deve dare 404 (kill-switch batte ACL).
        with TestClient(app, client=("8.8.8.8", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 404

    def test_admin_reset_missing_token_returns_403(self):
        """ADMIN_TOKEN vuoto => endpoint disabilitato (fail-closed)."""
        with self._build_client(admin_token="") as client:
            response = client.post("/admin/auth/reset-jwks-cache")
        assert response.status_code == 403

    def test_admin_reset_wrong_token_returns_403(self):
        with self._build_client(admin_token="correct-secret") as client:
            response = client.post(
                "/admin/auth/reset-jwks-cache",
                headers={"X-Admin-Token": "wrong"},
            )
        assert response.status_code == 403

    def test_metrics_acl_default_loopback_allowed(self, monkeypatch):
        """Default allowlist ([127.0.0.1, ::1]) + peer 127.0.0.1 => 200.

        NB: settings.metrics_ip_allowlist ha default ["127.0.0.1","::1"],
        monkeypatch.setattr solo serve per 'resettare' se un test precedente
        l'ha modificato. NB: metrics_acl.settings e' lo stesso singleton
        di settings (import condiviso), quindi una sola setattr basta.
        """
        # NB: la default_factory popola "127.0.0.1","::1" gia' al boot.
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_acl_blocks_external_ip(self, monkeypatch):
        """Allowlist ristretta a 10.0.0.0/8 + peer 8.8.8.8 (esterno) => 403."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["10.0.0.0/8"])
        from spesemed.api.main import app
        with TestClient(app, client=("8.8.8.8", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 403
        assert "Metrics access denied" in response.json()["detail"]

    def test_metrics_acl_cidr_match(self, monkeypatch):
        """Se allowlist e' un CIDR (192.168.1.0/24), un peer nella subnet (192.168.1.5) => 200.

        Questo test prova il vero punto di forza dell'ACL: matching CIDR
        anziche' solo IP singolo (caso multi-host Prometheus).
        """
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["192.168.1.0/24"])
        from spesemed.api.main import app
        with TestClient(app, client=("192.168.1.5", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_acl_cidr_outsider_blocked(self, monkeypatch):
        """Subnet 192.168.1.0/24 NON contiene 192.168.2.5 => 403."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["192.168.1.0/24"])
        from spesemed.api.main import app
        with TestClient(app, client=("192.168.2.5", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 403

    def test_metrics_acl_ipv6_loopback_allowed(self, monkeypatch):
        """Peer IPv6 loopback (::1) e allowlist contiene "::1" => 200.

        NB: TestClient `client=(host, port)` e' un 2-tuple secondo ASGI spec.
        Un 4-tuple (host, port, flowinfo, scope_id) causa TypeError in Address.
        """
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["::1"])
        from spesemed.api.main import app
        with TestClient(app, client=("::1", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_acl_ipv4_mapped_ipv6_normalized(self, monkeypatch):
        """Peer `::ffff:127.0.0.1` (IPv4-mapped IPv6) deve matchare allowlist IPv4 127.0.0.1.

        Caso dual-stack socket reale: il client arriva come IPv6 ma
        il suo contenuto e' una v4. Senza normalizzazione, la rete
        127.0.0.1/32 non conterrebbe l'indirizzo IPv6-mapped.
        """
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1"])
        from spesemed.api.main import app
        with TestClient(app, client=("::ffff:127.0.0.1", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_acl_malformed_xff_fallback_peer(self, monkeypatch):
        """X-Forwarded-For non-IP + trust_xff=True => fallback al peer IP (NON 500)."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1"])
        monkeypatch.setattr(settings, "metrics_trust_xff", True)
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get(
                "/metrics",
                headers={"X-Forwarded-For": "not-an-ip-at-all"},
            )
        # Peer 127.0.0.1 in allowlist, XFF malformato ignorato, => 200.
        assert response.status_code == 200

    def test_metrics_acl_empty_list_production_fail_closed(self, monkeypatch):
        """api_env=production + allowlist vuota => 403 (fail-closed) anche con peer localhost."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", [])
        monkeypatch.setattr(settings, "api_env", "production")
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 403

    def test_metrics_acl_empty_list_development_fail_open(self, monkeypatch):
        """api_env=development + allowlist vuota => 200 (fail-open)."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", [])
        monkeypatch.setattr(settings, "api_env", "development")
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_acl_xff_trusted_proxy_uses_xff_ip(self, monkeypatch):
        """Peer 127.0.0.1 (trusted proxy) + X-Forwarded-For=8.8.8.8 NON in
        allowlist + metrics_trust_xff=True => 403 (client reale onorato)."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1"])
        monkeypatch.setattr(settings, "metrics_trust_xff", True)
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get(
                "/metrics",
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
        assert response.status_code == 403

    def test_metrics_acl_xff_untrusted_proxy_ignored(self, monkeypatch):
        """metrics_trust_xff=False (default) + peer 127.0.0.1 in allowlist => 200
        anche se X-Forwarded-For tenta spoof (XFF ignorato, peer IP usato)."""
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1"])
        # trust_xff lasciato al default (False) — niente monkeypatch ridondante.
        from spesemed.api.main import app
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            response = client.get(
                "/metrics",
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
        assert response.status_code == 200

    def test_loopback_only_metrics_warns_in_prod(self, monkeypatch, caplog):
        """In produzione con allowlist solo loopback, _warn_if_loopback_only_metrics_in_prod
        emette WARNING con suggerimento di aggiungere l'IP dello scraper.
        """
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1", "::1"])
        monkeypatch.setattr(settings, "api_env", "production")
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", True)
        from spesemed.api.main import _warn_if_loopback_only_metrics_in_prod
        with caplog.at_level(logging.WARNING, logger="spesemed.api"):
            _warn_if_loopback_only_metrics_in_prod()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "METRICS_IP_ALLOWLIST contiene solo loopback" in r.getMessage()
            for r in warnings
        ), f"Atteso WARNING su METRICS_IP_ALLOWLIST; got: {[r.getMessage() for r in warnings]}"

    def test_loopback_only_metrics_silent_in_dev(self, monkeypatch, caplog):
        """In development + allowlist solo loopback, il warning NON viene emesso."""
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1", "::1"])
        monkeypatch.setattr(settings, "api_env", "development")
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", True)
        from spesemed.api.main import _warn_if_loopback_only_metrics_in_prod
        with caplog.at_level(logging.WARNING, logger="spesemed.api"):
            _warn_if_loopback_only_metrics_in_prod()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any(
            "METRICS_IP_ALLOWLIST contiene solo loopback" in r.getMessage()
            for r in warnings
        ), "WARNING emesso in development (dovrebbe essere solo produzione)"

    def test_loopback_only_metrics_silent_when_scraper_ip_added(self, monkeypatch, caplog):
        """Aggiungere un IP reale (10.0.0.5) silenzia il warning (l'allowlist non e' piu' loopback-only)."""
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1", "::1", "10.0.0.5"])
        monkeypatch.setattr(settings, "api_env", "production")
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", True)
        from spesemed.api.main import _warn_if_loopback_only_metrics_in_prod
        with caplog.at_level(logging.WARNING, logger="spesemed.api"):
            _warn_if_loopback_only_metrics_in_prod()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any(
            "METRICS_IP_ALLOWLIST contiene solo loopback" in r.getMessage()
            for r in warnings
        ), "WARNING emesso nonostante IP scraper aggiunto (allowlist non loopback-only)"

    def test_loopback_only_metrics_silent_when_disabled(self, monkeypatch, caplog):
        """Se prometheus_metrics_enabled=False, il warning non viene emesso
        (operator ha esplicitamente disabilitato /metrics)."""
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1", "::1"])
        monkeypatch.setattr(settings, "api_env", "production")
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", False)
        from spesemed.api.main import _warn_if_loopback_only_metrics_in_prod
        with caplog.at_level(logging.WARNING, logger="spesemed.api"):
            _warn_if_loopback_only_metrics_in_prod()
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any(
            "METRICS_IP_ALLOWLIST contiene solo loopback" in r.getMessage()
            for r in warnings
        ), "WARNING emesso con /metrics disabilitato (FAIL: l'operator non intende scrapare)"

    def test_loopback_warning_emitted_via_lifespan_startup(self, monkeypatch, caplog):
        """Integration: il warning viene effettivamente emesso dal lifespan
        path reale (TestClient.__enter__ triggers lifespan startup).
        """
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["127.0.0.1", "::1"])
        monkeypatch.setattr(settings, "api_env", "production")
        monkeypatch.setattr(settings, "prometheus_metrics_enabled", True)
        from spesemed.api.main import app
        # NB: TestClient.__enter__ triggers lifespan startup, che chiama
        # _warn_if_loopback_only_metrics_in_prod() (FIX M6 audit 2025).
        with caplog.at_level(logging.WARNING, logger="spesemed.api"):
            with TestClient(app, client=("127.0.0.1", 50000)):
                pass  # solo startup; nessuna request necessaria.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "METRICS_IP_ALLOWLIST contiene solo loopback" in r.getMessage()
            for r in warnings
        ), (
            "Atteso WARNING emesso dal lifespan startup; "
            f"got: {[r.getMessage() for r in warnings]}"
        )

    def test_metrics_acl_denial_log_level_split(self, monkeypatch, caplog):
        """Denial log: WARNING contiene messaggio GENERICO (no IP),
        l'IP del client e' presente SOLO al livello DEBUG.
        """
        import logging
        monkeypatch.setattr(settings, "metrics_ip_allowlist", ["10.0.0.0/8"])
        from spesemed.api.main import app
        caplog.set_level(logging.DEBUG, logger="spesemed.api.metrics_acl")
        with TestClient(app, client=("8.8.8.8", 50000)) as client:
            response = client.get("/metrics")
        assert response.status_code == 403

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "Atteso almeno un WARNING nel log del denial."
        for rec in warning_records:
            # Il messaggio pubblico NON deve riflettere l'IP attacker.
            assert "8.8.8.8" not in rec.getMessage(), (
                f"WARNING message leakka l'IP: {rec.getMessage()!r}"
            )

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        # L'IP dell'attacker deve apparire solo a DEBUG (per investigation).
        assert any("8.8.8.8" in r.getMessage() for r in debug_records), (
            "Atteso IP attacker a livello DEBUG per forensics."
        )

    def test_admin_reset_correct_token_returns_200_and_increments_counter(self):
        from spesemed.api.main import app

        settings.admin_token = "correct-secret-32chars-min-12345"
        # Pre-popoliamo la cache per verificare che venga svuotata
        jwt_decoder._jwks_clients["https://fake.supabase.co/jwks"] = "fake-client"
        before = _get_counter_value(jwks_cache_resets_total, "")
        with TestClient(app) as client:
            response = client.post(
                "/admin/auth/reset-jwks-cache",
                headers={"X-Admin-Token": "correct-secret-32chars-min-12345"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        # Cache svuotata
        assert jwt_decoder._jwks_clients == {}
        # Counter incrementato
        after = _get_counter_value(jwks_cache_resets_total, "")
        assert after >= before + 1

"""SPESEMED - Test del modulo billing (Stripe Fase 4C).

Verifica:
  - No-op mode: senza STRIPE_SECRET_KEY / WEBHOOK_SECRET gli endpoint
    rispondono 503.
  - NESSUN secret nel workspace: i test usano chiavi fake esplicite.
  - POST /billing/checkout crea una Stripe Checkout Session (mock del
    client) e ritorna 200 + URL.
  - POST /billing/webhook: 503 se whsec mancante, 400 se firma non valida,
    200 + handle dell'evento se firma valida.
  - handle_webhook_event registra l'evento su `stripe_events` e persiste
    l'entitlement su `entitlements` (best-effort).
"""
from __future__ import annotations

import types

import pytest

from spesemed.api.config import settings
from spesemed.api import supabase_client


# =============================================================================
# Fake Stripe client (no network)
# =============================================================================

class FakeSession:
    def __init__(self, sid="cs_test_0001", url="https://checkout.stripe.com/c/pay/test", amount_total=999):
        self.id = sid
        self.url = url
        self.amount_total = amount_total


class FakeStripe:
    """Sostituto minimale del client stripe (checkout + webhook)."""

    def __init__(self, event_to_return=None, construct_event_error=None):
        self.checkout = types.SimpleNamespace()
        self.Webhook = types.SimpleNamespace()
        self.create_calls = []
        self.event_to_return = event_to_return
        self.construct_event_error = construct_event_error

        def _create(**kwargs):
            self.create_calls.append(kwargs)
            return FakeSession()

        self.checkout.Session = types.SimpleNamespace(create=_create)

        def _construct_event(payload, sig_header, secret):
            if self.construct_event_error:
                raise self.construct_event_error
            return self.event_to_return

        self.Webhook.construct_event = _construct_event


@pytest.fixture
def stripe_settings(monkeypatch):
    """Attiva Stripe con secret fake (mai reali nel workspace)."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake_0123456789")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_0123456789")
    monkeypatch.setattr(settings, "stripe_price_id", "price_test_0123456789")
    monkeypatch.setattr(settings, "stripe_currency", "eur")
    monkeypatch.setattr(settings, "billing_success_url", "https://app.spesemed.local/success?id={CHECKOUT_SESSION_ID}")
    monkeypatch.setattr(settings, "billing_cancel_url", "https://app.spesemed.local/cancel")
    # Kill switch (task 4C-C1): il default e' OFF, i test di checkout lo attivano.
    monkeypatch.setattr(settings, "billing_enabled", True)
    yield


@pytest.fixture
def fake_stripe_module(monkeypatch, stripe_settings):
    from spesemed.api import billing, billing_client
    fk = FakeStripe()
    # Skeleton legacy (plan/webhook) + wrapper DI (checkout): stesso fake.
    monkeypatch.setattr(billing, "_get_stripe_module", lambda: fk)
    monkeypatch.setattr(billing, "_stripe_module_cache", fk)
    monkeypatch.setattr(billing_client, "stripe", fk)
    yield fk
    billing._reset_stripe_module_cache()


COMPLETED_EVENT_DICT = {
    "id": "evt_test_completed_1",
    "type": "checkout.session.completed",
    "data": {
        "object": {
            "customer": "cus_test_123",
            "client_reference_id": "00000000-0000-4000-8000-000000000001",
            "subscription": "sub_test_456",
            "amount_total": 999,
        }
    },
}


class TestNoOpMode:
    def test_checkout_returns_503_when_not_configured(self, test_client, auth_headers):
        r = test_client.post("/api/v1/billing/checkout", json={}, headers=auth_headers)
        assert r.status_code == 503
        assert "Billing non configurato" in r.json()["detail"]

    def test_webhook_returns_503_when_not_configured(self, test_client):
        r = test_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"x"}',
            headers={"Stripe-Signature": "t=1,v1=deadbeef"},
        )
        assert r.status_code == 503
        assert "STRIPE_WEBHOOK_SECRET mancante" in r.json()["detail"]


class TestCheckout:
    def test_checkout_creates_session(self, fake_stripe_module, test_client, auth_headers):
        r = test_client.post("/api/v1/billing/checkout", json={}, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["checkout_url"].startswith("https://checkout.stripe.com")
        assert body["session_id"] == "cs_test_0001"
        assert body["mode"] == "test"

        # Verifica parametri passati a Stripe
        call = fake_stripe_module.create_calls[-1]
        assert call["mode"] == "subscription"
        assert call["client_reference_id"] == "00000000-0000-4000-8000-000000000001"
        assert call["line_items"] == [{"price": "price_test_0123456789", "quantity": 1}]
        assert call["success_url"] == settings.billing_success_url
        assert call["cancel_url"] == settings.billing_cancel_url
        assert "test_0123456789" not in call["metadata"]["user_id"]

    def test_checkout_works_without_body(self, fake_stripe_module, test_client, auth_headers):
        """Il client non deve poter scegliere prezzo/redirect: body non richiesto."""
        r = test_client.post("/api/v1/billing/checkout", headers=auth_headers)
        assert r.status_code == 200
        call = fake_stripe_module.create_calls[-1]
        assert call["line_items"] == [{"price": "price_test_0123456789", "quantity": 1}]
        assert "customer_email" not in call

    def test_checkout_accepts_optional_email(self, fake_stripe_module, test_client, auth_headers):
        """L'email (opzionale) arriva a Stripe come customer_email."""
        r = test_client.post(
            "/api/v1/billing/checkout",
            json={"email": "user@example.test"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert fake_stripe_module.create_calls[-1]["customer_email"] == "user@example.test"

    def test_checkout_ignores_client_price_and_redirect(self, fake_stripe_module, test_client, auth_headers):
        """Valori inviati dal client (price_id/success_url) NON sono usati."""
        r = test_client.post(
            "/api/v1/billing/checkout",
            json={
                "price_id": "price_custom_abc",
                "success_url": "https://evil.example/redirect",
                "cancel_url": "https://evil.example/cancel",
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        call = fake_stripe_module.create_calls[-1]
        assert call["line_items"] == [{"price": "price_test_0123456789", "quantity": 1}]
        assert call["success_url"] == settings.billing_success_url
        assert call["cancel_url"] == settings.billing_cancel_url

    def test_checkout_requires_auth(self, stripe_settings, fake_stripe_module, monkeypatch, test_client):
        """Senza header auth e con mock-auth DISABILITATO (come in produzione) => 401."""
        monkeypatch.setattr(settings, "allow_dev_mock_auth", False)
        r = test_client.post("/api/v1/billing/checkout", json={})
        assert r.status_code == 401

    def test_checkout_missing_price_id_returns_503(self, fake_stripe_module, monkeypatch, test_client, auth_headers):
        monkeypatch.setattr(settings, "stripe_price_id", "")
        r = test_client.post("/api/v1/billing/checkout", json={}, headers=auth_headers)
        assert r.status_code == 503
        assert fake_stripe_module.create_calls == []  # nessuna sessione senza price_id

    def test_checkout_kill_switch_returns_503(self, fake_stripe_module, monkeypatch, test_client, auth_headers):
        """BILLING_ENABLED=false => 503 anche con secret/price presenti."""
        monkeypatch.setattr(settings, "billing_enabled", False)
        r = test_client.post("/api/v1/billing/checkout", json={}, headers=auth_headers)
        assert r.status_code == 503
        assert fake_stripe_module.create_calls == []


class TestWebhook:
    def test_webhook_invalid_signature_returns_400(self, fake_stripe_module, test_client):
        def _bad_construct_event(payload, sig_header, secret):
            raise ValueError("No signatures found matching the expected signature")

        fake_stripe_module.Webhook.construct_event = _bad_construct_event
        r = test_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=1,v1=badsig"},
        )
        assert r.status_code == 400
        assert "Webhook sign check failed" in r.json()["detail"]

    def test_webhook_valid_event_returns_200_and_processes(self, fake_stripe_module, test_client):
        fake_stripe_module.event_to_return = dict(COMPLETED_EVENT_DICT)
        r = test_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=1,v1=validsig"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["received"] is True
        assert body["action"] == "subscription_created"

    def test_webhook_unsupported_event_ack_ignored(self, fake_stripe_module, test_client):
        fake_stripe_module.event_to_return = {"type": "customer.created", "data": {"object": {}}}
        r = test_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"customer.created"}',
            headers={"Stripe-Signature": "t=1,v1=validsig"},
        )
        assert r.status_code == 200
        assert r.json()["action"] == "ignored"

    def test_webhook_persists_entitlement_on_supabase(self, fake_stripe_module, mock_supabase, test_client):
        """Con Supabase mockato, l'evento completed scrive su stripe_events + entitlements."""
        fake_stripe_module.event_to_return = dict(COMPLETED_EVENT_DICT)

        client = supabase_client.get_supabase_client()
        # La tabella canonica dell'entitlement (migrations/004_billing.sql).
        entitlements_table = client.table("entitlements")

        r = test_client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=1,v1=validsig"},
        )
        assert r.status_code == 200
        entitlements_table.upsert.assert_called_once()
        kwargs = entitlements_table.upsert.call_args.kwargs
        payload = kwargs.get("object") or kwargs.get("values")
        # upsert(...) puo' essere chiamato posizionalmente; verifichiamo il dato.
        if payload is None and entitlements_table.upsert.call_args.args:
            payload = entitlements_table.upsert.call_args.args[0]
        assert payload["user_id"] == "00000000-0000-4000-8000-000000000001"
        assert payload["plan"] == "pro"
        assert payload["status"] == "active"
        # Il gating 402 legge extractions_limit/used: devono essere valorizzati.
        assert payload["extractions_limit"] == settings.billing_extractions_limit
        assert payload["extractions_used"] == 0
        # Idempotenza: l'evento va registrato su stripe_events.
        called_tables = [call.args[0] for call in client.table.call_args_list if call.args]
        assert "stripe_events" in called_tables
        assert "entitlements" in called_tables

# =============================================================================
# Fase 4C-C1: config + kill switch (nessun secret reale)
# =============================================================================

class TestBillingConfig:
    def test_billing_settings_defaults(self):
        """Kill switch OFF e default sicuri (nessun secret)."""
        from spesemed.api.config import settings

        assert settings.billing_enabled is False
        assert settings.stripe_secret_key == ""
        assert settings.stripe_webhook_secret == ""
        assert settings.stripe_price_id == ""
        assert settings.stripe_currency == "eur"
        assert settings.stripe_mode == "test"
        assert settings.billing_extractions_limit == 100
        assert settings.billing_success_url == ""
        assert settings.billing_cancel_url == ""

    def test_startup_error_when_billing_enabled_but_incomplete(self, monkeypatch, caplog):
        import logging

        from spesemed.api.main import _warn_if_billing_misconfigured

        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "stripe_secret_key", "")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "")
        monkeypatch.setattr(settings, "stripe_price_id", "")

        with caplog.at_level(logging.ERROR, logger="spesemed.api"):
            _warn_if_billing_misconfigured()

        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert any("BILLING_ENABLED=true" in m and "STRIPE_SECRET_KEY" in m for m in errors)
        assert any("STRIPE_WEBHOOK_SECRET" in m for m in errors)
        assert any("STRIPE_PRICE_ID" in m for m in errors)

    def test_startup_no_error_when_billing_disabled(self, monkeypatch, caplog):
        import logging

        from spesemed.api.main import _warn_if_billing_misconfigured

        monkeypatch.setattr(settings, "billing_enabled", False)
        monkeypatch.setattr(settings, "stripe_secret_key", "")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "")
        monkeypatch.setattr(settings, "stripe_price_id", "")

        with caplog.at_level(logging.ERROR, logger="spesemed.api"):
            _warn_if_billing_misconfigured()

        assert not [r for r in caplog.records if r.levelno == logging.ERROR]

    def test_startup_no_error_when_billing_complete(self, monkeypatch, caplog):
        import logging

        from spesemed.api.main import _warn_if_billing_misconfigured

        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake_0123456789")
        monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_0123456789")
        monkeypatch.setattr(settings, "stripe_price_id", "price_test_0123456789")

        with caplog.at_level(logging.ERROR, logger="spesemed.api"):
            _warn_if_billing_misconfigured()

        assert not [r for r in caplog.records if r.levelno == logging.ERROR]

    def test_checkout_url_falls_back_to_app_url(self, fake_stripe_module, monkeypatch, test_client, auth_headers):
        """Con BILLING_*_URL vuoti, il checkout deriva i redirect da APP_URL."""
        monkeypatch.setattr(settings, "billing_success_url", "")
        monkeypatch.setattr(settings, "billing_cancel_url", "")
        monkeypatch.setattr(settings, "app_url", "https://app.example.test")

        r = test_client.post("/api/v1/billing/checkout", json={}, headers=auth_headers)
        assert r.status_code == 200
        call = fake_stripe_module.create_calls[-1]
        assert call["success_url"] == "https://app.example.test/app/profilo?billing=success"
        assert call["cancel_url"] == "https://app.example.test/app/profilo?billing=cancel"


# =============================================================================
# GET /billing/status (Task 4C-C6)
# =============================================================================

class TestBillingStatus:
    def _configure_rows(self, client, rows):
        query = client.table.return_value.select.return_value
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value.data = rows
        return client

    def test_status_disabled_returns_200_free(self, monkeypatch, test_client, auth_headers):
        monkeypatch.setattr(settings, "billing_enabled", False)
        r = test_client.get("/api/v1/billing/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["billing_enabled"] is False
        assert body["plan"] == "free"
        assert body["status"] == "none"
        assert body["period_end"] is None
        assert body["extractions_limit"] == 0
        assert body["extractions_used"] == 0

    def test_status_active_entitlement(self, monkeypatch, mock_supabase, test_client, auth_headers):
        monkeypatch.setattr(settings, "billing_enabled", True)
        self._configure_rows(
            mock_supabase,
            [{
                "user_id": "00000000-0000-4000-8000-000000000001",
                "plan": "pro",
                "status": "active",
                "current_period_end": "2026-12-01T00:00:00+00:00",
                "extractions_limit": 100,
                "extractions_used": 12,
            }],
        )
        r = test_client.get("/api/v1/billing/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["billing_enabled"] is True
        assert body["plan"] == "pro"
        assert body["status"] == "active"
        assert body["period_end"] == "2026-12-01T00:00:00+00:00"
        assert body["extractions_limit"] == 100
        assert body["extractions_used"] == 12

    def test_status_no_row_returns_free(self, monkeypatch, mock_supabase, test_client, auth_headers):
        monkeypatch.setattr(settings, "billing_enabled", True)
        self._configure_rows(mock_supabase, [])
        r = test_client.get("/api/v1/billing/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["billing_enabled"] is True
        assert body["plan"] == "free"
        assert body["extractions_limit"] == 0
        assert body["extractions_used"] == 0

    def test_status_subscriptions_fallback(self, monkeypatch, mock_supabase, test_client, auth_headers):
        """Compatibilita' con lo skeleton gia' deployato (tabella subscriptions)."""
        monkeypatch.setattr(settings, "billing_enabled", True)

        def _table(name):
            table = types.SimpleNamespace()
            query = types.SimpleNamespace()
            query.select = lambda *a, **k: query
            query.eq = lambda *a, **k: query
            query.limit = lambda *a, **k: query
            query.execute = lambda: types.SimpleNamespace(
                data=[{
                    "plan": "pro",
                    "status": "active",
                    "current_period_end": "2026-12-01T00:00:00+00:00",
                }] if name == "subscriptions" else []
            )
            table.select = lambda *a, **k: query
            return table

        monkeypatch.setattr(mock_supabase, "table", _table)
        r = test_client.get("/api/v1/billing/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["plan"] == "pro"
        assert body["status"] == "active"
        assert body["extractions_limit"] == settings.billing_extractions_limit

    def test_status_never_5xx_when_db_fails(self, monkeypatch, mock_supabase, test_client, auth_headers):
        monkeypatch.setattr(settings, "billing_enabled", True)
        monkeypatch.setattr(mock_supabase, "table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
        r = test_client.get("/api/v1/billing/status", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["billing_enabled"] is True
        assert body["plan"] == "free"
        assert body["extractions_limit"] == 0

    def test_status_requires_auth(self, monkeypatch, test_client):
        monkeypatch.setattr(settings, "billing_enabled", False)
        monkeypatch.setattr(settings, "allow_dev_mock_auth", False)
        r = test_client.get("/api/v1/billing/status")
        assert r.status_code == 401

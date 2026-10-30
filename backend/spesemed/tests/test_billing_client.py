"""SPESEMED - Test offline del wrapper Stripe DI-friendly (Fase 4C-C3).

Nessuna chiamata di rete e nessun secret reale: il modulo `stripe` viene
sostituito con un fake e `settings` con un SimpleNamespace. Le chiavi usate
sono palesemente finte (`sk_test_fake_...`).
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from spesemed.api import billing_client


# =============================================================================
# Fake Stripe (no network)
# =============================================================================


class FakeSession:
    def __init__(self, sid="cs_test_0001", url="https://checkout.stripe.com/c/pay/test"):
        self.id = sid
        self.url = url


class FakeStripe:
    def __init__(self, event=None, construct_error=None):
        self.api_key = None
        self.create_calls = []
        self.event = event
        self.construct_error = construct_error

        def _create(**kwargs):
            self.create_calls.append(kwargs)
            return FakeSession()

        def _construct_event(payload, sig_header, secret):
            if self.construct_error:
                raise self.construct_error
            return self.event

        self.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(create=_create)
        )
        self.Webhook = types.SimpleNamespace(construct_event=_construct_event)


@pytest.fixture
def fake_settings(monkeypatch):
    fake = types.SimpleNamespace(
        billing_enabled=True,
        stripe_secret_key="sk_test_fake_0123456789",
        stripe_webhook_secret="whsec_test_fake_0123456789",
        stripe_price_id="price_test_fake_0123456789",
        stripe_currency="eur",
        stripe_mode="test",
        billing_extractions_limit=100,
        billing_success_url="",
        billing_cancel_url="",
        stripe_success_url="",
        stripe_cancel_url="",
        app_url="https://app.spesemed.local",
    )
    monkeypatch.setattr(billing_client, "settings", fake)
    return fake


@pytest.fixture
def fake_stripe(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(billing_client, "stripe", fake)
    return fake


# =============================================================================
# Kill switch / configurazione
# =============================================================================


class TestIsBillingConfigured:
    def test_false_without_keys(self, fake_settings, fake_stripe):
        fake_settings.stripe_secret_key = ""
        assert billing_client.is_billing_configured() is False

    def test_false_when_kill_switch_off(self, fake_settings, fake_stripe):
        fake_settings.billing_enabled = False
        assert billing_client.is_billing_configured() is False

    def test_false_when_stripe_library_missing(self, fake_settings, monkeypatch):
        monkeypatch.setattr(billing_client, "stripe", None)
        assert billing_client.is_billing_configured() is False

    def test_true_with_all_requirements(self, fake_settings, fake_stripe):
        assert billing_client.is_billing_configured() is True


# =============================================================================
# Checkout
# =============================================================================


class TestCreateCheckoutSession:
    def test_passes_user_reference_metadata_and_returns_url(self, fake_settings, fake_stripe):
        result = billing_client.create_checkout_session(
            user_id="00000000-0000-4000-8000-000000000001",
            email="user@example.test",
        )

        assert result == {
            "checkout_url": "https://checkout.stripe.com/c/pay/test",
            "session_id": "cs_test_0001",
        }
        call = fake_stripe.create_calls[-1]
        assert call["mode"] == "subscription"
        assert call["customer_email"] == "user@example.test"
        assert call["client_reference_id"] == "00000000-0000-4000-8000-000000000001"
        assert call["metadata"] == {"user_id": "00000000-0000-4000-8000-000000000001"}
        assert call["line_items"] == [{"price": "price_test_fake_0123456789", "quantity": 1}]
        assert call["success_url"] == "https://app.spesemed.local/app/profilo?billing=success"
        assert call["cancel_url"] == "https://app.spesemed.local/app/profilo?billing=cancel"
        assert fake_stripe.api_key == "sk_test_fake_0123456789"

    def test_uses_configured_redirect_urls(self, fake_settings, fake_stripe):
        fake_settings.billing_success_url = "https://app.test/ok"
        fake_settings.billing_cancel_url = "https://app.test/no"
        billing_client.create_checkout_session("u1", "u@example.test")
        call = fake_stripe.create_calls[-1]
        assert call["success_url"] == "https://app.test/ok"
        assert call["cancel_url"] == "https://app.test/no"

    def test_raises_when_not_configured(self, fake_settings, fake_stripe):
        fake_settings.billing_enabled = False
        with pytest.raises(billing_client.BillingNotConfiguredError):
            billing_client.create_checkout_session("u1", "u@example.test")
        assert fake_stripe.create_calls == []

    def test_does_not_log_secret(self, fake_settings, fake_stripe, caplog):
        billing_client.create_checkout_session("u1", "u@example.test")
        assert "sk_test_fake_0123456789" not in caplog.text


# =============================================================================
# Webhook parsing
# =============================================================================


class TestParseWebhookEvent:
    def test_returns_event_from_stripe(self, fake_settings, fake_stripe):
        event = {"type": "checkout.session.completed", "data": {"object": {}}}
        fake_stripe.event = event
        assert billing_client.parse_webhook_event(b'{"type":"x"}', "t=1,v1=sig") is event

    def test_invalid_signature_propagates(self, fake_settings, fake_stripe):
        fake_stripe.construct_error = ValueError("No signatures found")
        with pytest.raises(ValueError):
            billing_client.parse_webhook_event(b'{"type":"x"}', "t=1,v1=bad")

    def test_raises_when_library_missing(self, fake_settings, monkeypatch):
        monkeypatch.setattr(billing_client, "stripe", None)
        with pytest.raises(billing_client.BillingNotConfiguredError):
            billing_client.parse_webhook_event(b"{}", "sig")


# =============================================================================
# Mapping event -> entitlements
# =============================================================================


class TestMapEventToEntitlement:
    def test_checkout_completed_maps_to_upsert_row(self, fake_settings):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_test_123",
                    "client_reference_id": "user-1",
                    "subscription": "sub_test_456",
                    "subscription_status": "active",
                }
            },
        }
        row = billing_client.map_event_to_entitlement(event)
        assert row["user_id"] == "user-1"
        assert row["plan"] == "pro"
        assert row["status"] == "active"
        assert row["extractions_limit"] == 100
        assert row["extractions_used"] == 0
        assert row["stripe_customer_id"] == "cus_test_123"
        assert row["stripe_subscription_id"] == "sub_test_456"
        assert row["current_period_start"]
        assert row["current_period_end"]

    def test_checkout_completed_trialing(self, fake_settings):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": "user-1",
                    "subscription_status": "trialing",
                }
            },
        }
        assert billing_client.map_event_to_entitlement(event)["status"] == "trialing"

    def test_metadata_user_id_fallback(self, fake_settings):
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"user_id": "user-meta"}}},
        }
        assert billing_client.map_event_to_entitlement(event)["user_id"] == "user-meta"

    def test_subscription_updated_active(self, fake_settings):
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test_456",
                    "customer": "cus_test_123",
                    "status": "active",
                    "metadata": {"user_id": "user-1"},
                    "current_period_end": 1893456000,
                }
            },
        }
        row = billing_client.map_event_to_entitlement(event)
        assert row["status"] == "active"
        assert row["stripe_subscription_id"] == "sub_test_456"
        assert row["current_period_end"].startswith("2030-01-01")

    def test_subscription_updated_canceled_disables_entitlement(self, fake_settings):
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_test_456",
                    "status": "canceled",
                    "metadata": {"user_id": "user-1"},
                }
            },
        }
        row = billing_client.map_event_to_entitlement(event)
        assert row["status"] == "none"
        assert row["extractions_limit"] == 0

    def test_invoice_paid_resets_usage(self, fake_settings):
        event = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "customer": "cus_test_123",
                    "subscription": "sub_test_456",
                    "subscription_details": {"metadata": {"user_id": "user-1"}},
                    "lines": {"data": [{"period": {"end": 1893456000}}]},
                }
            },
        }
        row = billing_client.map_event_to_entitlement(event)
        assert row["extractions_used"] == 0
        assert row["current_period_end"].startswith("2030-01-01")

    def test_ignored_event_returns_none(self, fake_settings):
        assert billing_client.map_event_to_entitlement({"type": "customer.created", "data": {"object": {}}}) is None

    def test_missing_user_id_returns_none(self, fake_settings):
        event = {"type": "checkout.session.completed", "data": {"object": {}}}
        assert billing_client.map_event_to_entitlement(event) is None

    def test_supports_object_style_events(self, fake_settings):
        event = types.SimpleNamespace(
            type="checkout.session.completed",
            data=types.SimpleNamespace(
                object=types.SimpleNamespace(
                    client_reference_id="user-obj",
                    metadata={"user_id": "user-obj"},
                )
            ),
        )
        assert billing_client.map_event_to_entitlement(event)["user_id"] == "user-obj"


# =============================================================================
# Upsert
# =============================================================================


class TestUpsertEntitlement:
    def test_upserts_on_user_id(self):
        client = MagicMock()
        mapping = {"user_id": "user-1", "plan": "pro"}
        billing_client.upsert_entitlement(client, mapping)
        client.table.assert_called_once_with("entitlements")
        client.table.return_value.upsert.assert_called_once_with(
            mapping, on_conflict="user_id"
        )
        client.table.return_value.upsert.return_value.execute.assert_called_once()

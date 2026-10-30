"""SPESEMED - Test della route POST /api/v1/billing/webhook (Fase 4C-C5).

Copre: firma invalida fail-closed, evento valido (stripe_events + entitlements),
replay idempotente, eventi fuori scope, aggiornamenti entitlement, assenza di
payload nei log, ``event_type`` valorizzato in risposta/log (BOH-51 a) e kill
switch ``BILLING_ENABLED=false`` (503 senza scritture, BOH-51 c). Tutto
offline: Stripe e Supabase sono fake/mock, nessun secret reale nel workspace.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from spesemed.api import billing
from spesemed.api.config import settings


class FakeStripe:
    def __init__(self, event=None, construct_error=None):
        self.event = event
        self.construct_error = construct_error
        self.Webhook = types.SimpleNamespace(construct_event=self._construct_event)

    def _construct_event(self, payload, sig_header, secret):
        if self.construct_error:
            raise self.construct_error
        return self.event


@pytest.fixture
def stripe_env(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake_0123456789")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_0123456789")
    monkeypatch.setattr(settings, "stripe_price_id", "price_test_0123456789")
    yield


@pytest.fixture
def fake_stripe(monkeypatch, stripe_env):
    fake = FakeStripe()
    monkeypatch.setattr(billing, "_get_stripe_module", lambda: fake)
    monkeypatch.setattr(billing, "_stripe_module_cache", fake)
    yield fake
    billing._reset_stripe_module_cache()


def _completed_event(event_id="evt_test_0001", user_id="00000000-0000-4000-8000-000000000001"):
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_test_123",
                "client_reference_id": user_id,
                "subscription": "sub_test_456",
                "secret_payload_marker": "must-not-be-logged",
            }
        },
    }


def _post_webhook(test_client):
    return test_client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"checkout.session.completed"}',
        headers={"Stripe-Signature": "t=1,v1=validsig"},
    )


def _called_tables(mock_supabase):
    """Nomi delle tabelle toccate dal mock Supabase (il worker tocca 'jobs')."""
    return [call.args[0] for call in mock_supabase.table.call_args_list if call.args]


def test_webhook_invalid_signature_returns_400_without_db_write(
    fake_stripe, mock_supabase, test_client
):
    fake_stripe.construct_error = ValueError("No signatures found")

    r = _post_webhook(test_client)

    assert r.status_code == 400
    assert "Webhook sign check failed" in r.json()["detail"]
    # Nessuna scrittura sulle tabelle billing (il worker puo' toccare 'jobs').
    called_tables = _called_tables(mock_supabase)
    assert "stripe_events" not in called_tables
    assert "entitlements" not in called_tables


def test_webhook_valid_event_records_event_and_upserts_entitlement(
    fake_stripe, mock_supabase, test_client
):
    fake_stripe.event = _completed_event()

    r = _post_webhook(test_client)

    assert r.status_code == 200
    body = r.json()
    assert body["received"] is True
    assert body["action"] == "subscription_created"
    assert body["event_type"] == "checkout.session.completed"
    assert body["replayed"] is False

    table = mock_supabase.table.return_value
    table.insert.assert_called_once_with(
        {"event_id": "evt_test_0001", "type": "checkout.session.completed"}
    )
    table.upsert.assert_called_once()
    payload = table.upsert.call_args.args[0]
    assert payload["user_id"] == "00000000-0000-4000-8000-000000000001"
    assert payload["plan"] == "pro"
    assert payload["status"] == "active"
    # Tabelle canoniche (migrations/004_billing.sql): evento + entitlement.
    billing_tables = [
        t for t in _called_tables(mock_supabase) if t in ("stripe_events", "entitlements")
    ]
    assert billing_tables == ["stripe_events", "entitlements"]


def test_webhook_replay_is_idempotent(fake_stripe, mock_supabase, test_client):
    fake_stripe.event = _completed_event()
    table = mock_supabase.table.return_value
    table.insert.return_value.execute.side_effect = [
        MagicMock(),
        Exception("duplicate key value violates unique constraint"),
    ]

    first = _post_webhook(test_client)
    second = _post_webhook(test_client)

    assert first.status_code == 200
    assert first.json()["replayed"] is False
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    table.upsert.assert_called_once()


def test_webhook_unsupported_event_ack_ignored(fake_stripe, mock_supabase, test_client):
    fake_stripe.event = {"id": "evt_other_1", "type": "customer.created", "data": {"object": {}}}

    r = _post_webhook(test_client)

    assert r.status_code == 200
    assert r.json()["action"] == "ignored"
    table = mock_supabase.table.return_value
    table.insert.assert_called_once_with({"event_id": "evt_other_1", "type": "customer.created"})
    table.upsert.assert_not_called()


def test_webhook_subscription_updated_updates_status(fake_stripe, mock_supabase, test_client):
    fake_stripe.event = {
        "id": "evt_upd_1",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_test_456",
                "customer": "cus_test_123",
                "status": "past_due",
                "current_period_end": 1700000000,
            }
        },
    }

    r = _post_webhook(test_client)

    assert r.status_code == 200
    assert r.json()["action"] == "subscription_updated"
    table = mock_supabase.table.return_value
    table.update.assert_called_once()
    values = table.update.call_args.args[0]
    assert values["status"] == "past_due"
    assert values["current_period_end"].startswith("2023-11-14")
    called_tables = [call.args[0] for call in mock_supabase.table.call_args_list if call.args]
    assert "entitlements" in called_tables


def test_webhook_does_not_log_payload(fake_stripe, mock_supabase, test_client, caplog):
    fake_stripe.event = _completed_event()

    with caplog.at_level("INFO"):
        r = _post_webhook(test_client)

    assert r.status_code == 200
    assert "must-not-be-logged" not in caplog.text


def test_webhook_checkout_response_and_log_include_event_type(
    fake_stripe, mock_supabase, test_client, caplog
):
    """(a) checkout.session.completed: event_type valorizzato in risposta e log."""
    fake_stripe.event = _completed_event()

    with caplog.at_level("INFO"):
        r = _post_webhook(test_client)

    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "checkout.session.completed"
    assert body["action"] == "subscription_created"
    # Il log della route riporta il tipo evento (prima era type=None).
    assert "type=checkout.session.completed" in caplog.text
    assert "type=None" not in caplog.text


def test_webhook_kill_switch_returns_503_without_db_write(
    fake_stripe, mock_supabase, test_client, monkeypatch
):
    """(c) BILLING_ENABLED=false => 503, nessuna scrittura, firma non verificata."""
    monkeypatch.setattr(settings, "billing_enabled", False)
    fake_stripe.event = _completed_event()
    # Se la firma fosse verificata prima del kill switch, la risposta sarebbe 400.
    fake_stripe.construct_error = ValueError("No signatures found")

    r = _post_webhook(test_client)

    assert r.status_code == 503
    assert "BILLING_ENABLED=false" in r.json()["detail"]
    called_tables = _called_tables(mock_supabase)
    assert "stripe_events" not in called_tables
    assert "entitlements" not in called_tables


def test_webhook_kill_switch_blocks_processing_even_with_valid_signature(
    fake_stripe, mock_supabase, test_client, monkeypatch
):
    """(c) Kill switch OFF: nessuna scrittura su stripe_events/entitlements."""
    monkeypatch.setattr(settings, "billing_enabled", False)
    fake_stripe.event = _completed_event()

    r = _post_webhook(test_client)

    assert r.status_code == 503
    called_tables = _called_tables(mock_supabase)
    assert "stripe_events" not in called_tables
    assert "entitlements" not in called_tables


def test_webhook_without_secret_returns_503(fake_stripe, mock_supabase, test_client, monkeypatch):
    """Secret webhook assente => 503 (webhook non configurato)."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")

    r = _post_webhook(test_client)

    assert r.status_code == 503
    assert "STRIPE_WEBHOOK_SECRET mancante" in r.json()["detail"]
    called_tables = _called_tables(mock_supabase)
    assert "stripe_events" not in called_tables
    assert "entitlements" not in called_tables

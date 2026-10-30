"""SPESEMED - Test offline della migration 004_billing.sql (Fase 4C, BOH-25).

Non serve un database: verifichiamo il contratto SQL (idempotenza, tabelle,
RLS service_role-only, nessun secret) riusando l'audit pre-go-live.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "004_billing.sql"


def _load_audit_module():
    path = ROOT / "tests" / "audit_pre_go_live.py"
    spec = importlib.util.spec_from_file_location("audit_pre_go_live", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sql_text() -> str:
    assert MIGRATION.is_file(), f"migration mancante: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def audit_result():
    return _load_audit_module().audit_billing_migration()


def test_migration_exists_and_audit_passes(audit_result):
    assert audit_result["exists"] is True
    assert audit_result["ok"] is True, audit_result
    assert audit_result["syntax"]["balanced"] is True
    assert audit_result["syntax"]["ends_with_semi"] is True


def test_required_tables_and_rls(audit_result):
    checks = audit_result["checks"]
    assert checks["create_subscriptions"] is True
    assert checks["create_billing_events"] is True
    assert checks["rls_subscriptions"] is True
    assert checks["rls_billing_events"] is True
    assert checks["policy_subscriptions_service_role"] is True
    assert checks["policy_billing_events_service_role"] is True


def test_subscriptions_has_billing_columns(sql_text):
    table = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+subscriptions\s*\((.*?)\);",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert table is not None
    body = table.group(1).lower()
    for column in (
        "user_id",
        "plan",
        "status",
        "stripe_customer_id",
        "stripe_subscription_id",
        "current_period_end",
        "extractions_limit",
        "extractions_used",
        "updated_at",
    ):
        assert column in body, f"colonna mancante in subscriptions: {column}"


def test_billing_events_is_replay_safe(sql_text):
    table = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+billing_events\s*\((.*?)\);",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert table is not None
    body = table.group(1).lower()
    assert "event_id text primary key" in body
    assert "type text not null" in body
    assert "processed_at" in body


def test_migration_is_idempotent(sql_text):
    lower = sql_text.lower()
    assert "create table if not exists" in lower
    assert lower.count("drop policy if exists") >= 2
    assert "add column if not exists" in lower
    assert "create index if not exists" in lower


def test_no_secrets_in_migration(sql_text):
    assert "sk_test_" not in sql_text
    assert "sk_live_" not in sql_text
    assert "whsec_" not in sql_text
    assert not re.search(r"price_[A-Za-z0-9]{8,}", sql_text)

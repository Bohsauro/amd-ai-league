"""SPESEMED - Test offline della migration 004_billing.sql (Fase 4C, BOH-25).

Non serve un database: verifichiamo il contratto SQL (idempotenza, tabelle,
RLS service_role-only, upgrade da una 004 legacy, nessun secret) riusando
l'audit pre-go-live.

Nomi canonici: `entitlements` + `stripe_events` (spec 01-gap-analysis.md
§3.3 GAP-3.2, richiamato da 02-plan-4c.md -> Task 4C-C2). Sono le tabelle
usate dal runtime: api/billing_client.py, api/billing.py, api/routes/extract.py.
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
    assert checks["create_entitlements"] is True
    assert checks["create_stripe_events"] is True
    assert checks["rls_entitlements"] is True
    assert checks["rls_stripe_events"] is True
    assert checks["policy_entitlements_service_role"] is True
    assert checks["policy_stripe_events_service_role"] is True


def test_entitlements_has_billing_columns(sql_text):
    table = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+entitlements\s*\((.*?)\);",
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
        "current_period_start",
        "current_period_end",
        "extractions_limit",
        "extractions_used",
        "updated_at",
    ):
        assert column in body, f"colonna mancante in entitlements: {column}"


def test_stripe_events_is_replay_safe(sql_text):
    table = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+stripe_events\s*\((.*?)\);",
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
    assert "drop trigger if exists" in lower


def test_migration_does_not_create_legacy_tables(sql_text):
    """Le tabelle legacy non vengono (ri)create: unica fonte di verita'."""
    assert not re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+subscriptions\b", sql_text, re.IGNORECASE
    )
    assert not re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+billing_events\b", sql_text, re.IGNORECASE
    )


def test_migration_copies_legacy_rows(sql_text):
    """Upgrade da una 004 precedente: dati legacy copiati nelle tabelle canoniche."""
    assert "to_regclass('public.subscriptions')" in sql_text
    assert "to_regclass('public.billing_events')" in sql_text
    assert re.search(
        r"INSERT\s+INTO\s+entitlements\b.*?ON\s+CONFLICT\s*\(\s*user_id\s*\)\s*DO\s+NOTHING",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert re.search(
        r"INSERT\s+INTO\s+stripe_events\b.*?ON\s+CONFLICT\s*\(\s*event_id\s*\)\s*DO\s+NOTHING",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )


def test_migration_copies_legacy_allowance(sql_text):
    """L'upgrade deve migrare l'allowance (periodo + quota) delle righe legacy.

    Regressione: la copia perdeva current_period_start / extractions_limit /
    extractions_used, quindi un utente gia' attivo si ritrovava con quota 0 e
    il gating 402 lo bloccava.
    """
    insert = re.search(
        r"INSERT\s+INTO\s+entitlements\s*\((.*?)\)\s*SELECT(.*?)FROM\s*\(",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert insert is not None, "blocco INSERT INTO entitlements non trovato"
    columns = insert.group(1).lower()
    select = insert.group(2).lower()
    for column in (
        "current_period_start",
        "current_period_end",
        "extractions_limit",
        "extractions_used",
    ):
        assert column in columns, f"colonna non migrata: {column}"
        assert column in select, f"colonna non selezionata nell'upgrade: {column}"


def test_migration_upgrade_is_schema_aware(sql_text):
    """La copia legacy deve tollerare schemi 004 diversi (colonne assenti).

    La 004_stripe_subscriptions.sql (prima versione) non aveva
    current_period_start / extractions_limit / extractions_used: una copia con
    SELECT esplicito fallirebbe. to_jsonb() + (->>) legge solo le chiavi
    presenti, quindi l'upgrade resta idempotente su qualunque schema legacy.
    """
    assert re.search(r"to_jsonb\s*\(", sql_text, re.IGNORECASE)
    assert re.search(r"row_json\s*->>\s*'", sql_text, re.IGNORECASE)


def test_migration_legacy_defaults_are_fail_closed(sql_text):
    """Le righe legacy senza status/plan espliciti non devono diventare attive."""
    insert = re.search(
        r"INSERT\s+INTO\s+entitlements\s*\((.*?)\)\s*SELECT(.*?)FROM\s*\(",
        sql_text,
        re.IGNORECASE | re.DOTALL,
    )
    assert insert is not None
    select = insert.group(2).lower()
    assert "'none'" in select, "status legacy non mappato su 'none' (fail-closed)"
    assert "'free'" in select, "plan legacy non mappato su 'free' (fail-closed)"


def test_no_secrets_in_migration(sql_text):
    assert "sk_test_" not in sql_text
    assert "sk_live_" not in sql_text
    assert "whsec_" not in sql_text
    assert not re.search(r"price_[A-Za-z0-9]{8,}", sql_text)

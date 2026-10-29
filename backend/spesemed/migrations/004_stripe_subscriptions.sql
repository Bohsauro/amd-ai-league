-- =============================================================================
-- SPESEMED - Migrazione 004: Tabella subscriptions (Stripe billing Fase 4C)
-- =============================================================================
-- Eseguire nella SQL Editor di Supabase: https://supabase.com/dashboard/project/_/sql
-- Idempotente (usa IF NOT EXISTS). Opzionale per lo skeleton: il webhook
-- Stripe funziona in best-effort anche senza, loggando un WARNING per
-- subscription NON persistite.
-- =============================================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id UUID PRIMARY KEY,                 -- sub del JWT Supabase
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    plan TEXT NOT NULL DEFAULT 'pro',
    status TEXT NOT NULL DEFAULT 'active',    -- active | trialing | past_due | canceled
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indice per lookup per customer (webhook arrivano con customer_id Stripe).
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer
    ON subscriptions (stripe_customer_id);

-- Abilita Row Level Security (RLS): solo backend con service_role.
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access on subscriptions" ON subscriptions;
CREATE POLICY "Service role full access on subscriptions" ON subscriptions
    FOR ALL
    USING (auth.role() = 'service_role');
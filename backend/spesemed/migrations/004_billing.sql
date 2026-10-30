-- =============================================================================
-- SPESEMED - Migrazione 004: billing (subscriptions + billing_events)
-- =============================================================================
-- Eseguire nella SQL Editor di Supabase: https://supabase.com/dashboard/project/_/sql
--
-- Idempotente: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS
-- + DROP POLICY IF EXISTS. Puo' essere rieseguita senza errori ed e' sicura
-- anche su un DB che aveva gia' applicato la vecchia 004_stripe_subscriptions.sql.
--
-- RLS: entrambe le tabelle contengono dati di fatturazione (PII). Le policy
-- consentono l'accesso SOLO al service_role usato dal backend; il client
-- (anon/authenticated) non puo' leggere ne' scrivere.
-- =============================================================================

-- =============================================================================
-- subscriptions: stato subscription Stripe per utente (1 riga per user_id)
-- =============================================================================
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id UUID PRIMARY KEY,                  -- sub del JWT Supabase
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    plan TEXT NOT NULL DEFAULT 'pro',
    status TEXT NOT NULL DEFAULT 'active',     -- active | trialing | past_due | canceled
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    extractions_limit INT NOT NULL DEFAULT 0,  -- allowance mensile (0 = non applicata)
    extractions_used INT NOT NULL DEFAULT 0,   -- incremento atomico lato backend
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Riconcilia un DB che aveva applicato la vecchia migration 004 (solo tabella
-- subscriptions con schema ridotto): aggiunge le colonne mancanti senza
-- perdere i dati esistenti.
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'pro';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS extractions_limit INT NOT NULL DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS extractions_used INT NOT NULL DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Lookup per customer: i webhook Stripe arrivano con stripe_customer_id.
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer
    ON subscriptions (stripe_customer_id);

-- Trigger updated_at (funzione definita in 001_init.sql).
DROP TRIGGER IF EXISTS trg_subscriptions_touch_updated_at ON subscriptions;
CREATE TRIGGER trg_subscriptions_touch_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =============================================================================
-- billing_events: eventi Stripe processati (idempotenza webhook / replay-safe)
-- =============================================================================
-- event_id e' la PK: un evento Stripe ripetuto (retry/replay) non viene
-- processato due volte. Il backend fa INSERT ... ON CONFLICT DO NOTHING.
-- Non salviamo il payload completo: contiene PII e non serve al replay.
CREATE TABLE IF NOT EXISTS billing_events (
    event_id TEXT PRIMARY KEY,                 -- evt_... di Stripe
    type TEXT NOT NULL,                        -- es. checkout.session.completed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_events_type
    ON billing_events (type);

-- =============================================================================
-- Row Level Security: service_role-only su entrambe le tabelle
-- =============================================================================
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on subscriptions" ON subscriptions;
CREATE POLICY "Service role full access on subscriptions" ON subscriptions
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on billing_events" ON billing_events;
CREATE POLICY "Service role full access on billing_events" ON billing_events
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

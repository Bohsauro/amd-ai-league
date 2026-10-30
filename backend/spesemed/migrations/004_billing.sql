-- =============================================================================
-- SPESEMED - Migrazione 004: billing (entitlements + stripe_events)
-- =============================================================================
-- Eseguire nella SQL Editor di Supabase: https://supabase.com/dashboard/project/_/sql
--
-- Nomi canonici (spec specs/spesemed/tasks/01-gap-analysis.md §3.3 GAP-3.2,
-- richiamato da specs/spesemed/tasks/02-plan-4c.md -> Task 4C-C2):
--   entitlements  - piano + allowance per utente (1 riga per user_id)
--   stripe_events - eventi Stripe processati (PK event_id = idempotenza webhook)
-- Sono le STESSE tabelle lette/scritte dal runtime:
--   api/billing_client.py (checkout), api/billing.py (webhook + status),
--   api/routes/extract.py (gating 402).
--
-- Idempotente: CREATE TABLE IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS
-- + DROP POLICY IF EXISTS + DROP TRIGGER IF EXISTS. Puo' essere rieseguita senza
-- errori ed e' sicura anche su un DB che aveva gia' applicato una versione
-- precedente di questa 004 (subscriptions + billing_events) o la vecchia
-- 004_stripe_subscriptions.sql: in quel caso i dati legacy vengono copiati
-- nelle tabelle canoniche (le tabelle legacy non vengono cancellate).
--
-- RLS: entrambe le tabelle contengono dati di fatturazione (PII). Le policy
-- consentono l'accesso SOLO al service_role usato dal backend; il client
-- (anon/authenticated) non puo' leggere ne' scrivere.
--
-- Prerequisiti: 001_init.sql (funzione touch_updated_at()) e le funzioni
-- auth.role() / schema auth di Supabase. Le migration vanno applicate in
-- ordine (001 -> 002 -> 003 -> 004).
-- =============================================================================

-- =============================================================================
-- entitlements: piano e allowance dell'utente (1 riga per user_id)
-- =============================================================================
CREATE TABLE IF NOT EXISTS entitlements (
    user_id TEXT PRIMARY KEY,                  -- sub del JWT Supabase
    plan TEXT NOT NULL DEFAULT 'free',         -- free | pro
    status TEXT NOT NULL DEFAULT 'none',       -- none | active | trialing | past_due | canceled
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    extractions_limit INT NOT NULL DEFAULT 0,  -- allowance mensile (0 = non applicata)
    extractions_used INT NOT NULL DEFAULT 0,   -- incremento atomico lato backend
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Riconcilia una tabella `entitlements` preesistente con schema ridotto:
-- aggiunge le colonne mancanti senza perdere i dati esistenti.
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free';
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS extractions_limit INT NOT NULL DEFAULT 0;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS extractions_used INT NOT NULL DEFAULT 0;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Lookup per customer: i webhook Stripe arrivano con stripe_customer_id.
CREATE INDEX IF NOT EXISTS idx_entitlements_stripe_cust
    ON entitlements (stripe_customer_id);

-- Trigger updated_at (funzione definita in 001_init.sql).
DROP TRIGGER IF EXISTS trg_entitlements_touch_updated_at ON entitlements;
CREATE TRIGGER trg_entitlements_touch_updated_at
    BEFORE UPDATE ON entitlements
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =============================================================================
-- stripe_events: eventi Stripe processati (idempotenza webhook / replay-safe)
-- =============================================================================
-- event_id e' la PK: un evento Stripe ripetuto (retry/replay) non viene
-- processato due volte. Il backend fa INSERT ... ON CONFLICT DO NOTHING.
-- Non salviamo il payload completo: contiene PII e non serve al replay.
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id TEXT PRIMARY KEY,                 -- evt_... di Stripe
    type TEXT NOT NULL,                        -- es. checkout.session.completed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stripe_events_type
    ON stripe_events (type);

-- =============================================================================
-- Row Level Security: service_role-only su entrambe le tabelle
-- =============================================================================
ALTER TABLE entitlements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on entitlements" ON entitlements;
CREATE POLICY "Service role full access on entitlements" ON entitlements
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service role full access on stripe_events" ON stripe_events;
CREATE POLICY "Service role full access on stripe_events" ON stripe_events
    FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- =============================================================================
-- Upgrade da una 004 precedente (subscriptions + billing_events) o dalla vecchia
-- 004_stripe_subscriptions.sql: copia i dati legacy nelle tabelle canoniche.
-- Le tabelle legacy NON vengono cancellate (il backend le legge solo come
-- fallback di compatibilita' su GET /billing/status).
--
-- La copia e' schema-aware: la riga legacy viene letta con to_jsonb(), quindi
-- le colonne assenti nella versione legacy applicata (current_period_start,
-- extractions_limit, extractions_used esistono solo nella 004 piu' recente)
-- non fanno fallire la migration. L'allowance degli utenti gia' attivi viene
-- migrata per intero: una riga legacy senza quota esplicita riceve il default
-- di settings.billing_extractions_limit (100, vedi api/config.py), altrimenti
-- l'utente pagante resterebbe con quota 0 e il gating 402 lo bloccherebbe.
-- =============================================================================
DO $$
BEGIN
    IF to_regclass('public.subscriptions') IS NOT NULL THEN
        INSERT INTO entitlements (
            user_id,
            plan,
            status,
            current_period_start,
            current_period_end,
            extractions_limit,
            extractions_used,
            stripe_customer_id,
            stripe_subscription_id,
            created_at
        )
        SELECT
            legacy.row_json->>'user_id',
            COALESCE(legacy.row_json->>'plan', 'free'),
            CASE
                WHEN COALESCE(legacy.row_json->>'status', 'none')
                     IN ('active', 'trialing', 'past_due', 'canceled')
                    THEN legacy.row_json->>'status'
                ELSE 'none'
            END,
            NULLIF(legacy.row_json->>'current_period_start', '')::timestamptz,
            NULLIF(legacy.row_json->>'current_period_end', '')::timestamptz,
            CASE
                WHEN COALESCE(legacy.row_json->>'plan', 'free') <> 'free'
                    THEN COALESCE(
                        NULLIF(NULLIF(legacy.row_json->>'extractions_limit', '')::int, 0),
                        100
                    )
                ELSE COALESCE(NULLIF(legacy.row_json->>'extractions_limit', '')::int, 0)
            END,
            COALESCE(NULLIF(legacy.row_json->>'extractions_used', '')::int, 0),
            legacy.row_json->>'stripe_customer_id',
            legacy.row_json->>'stripe_subscription_id',
            COALESCE(NULLIF(legacy.row_json->>'created_at', '')::timestamptz, NOW())
        FROM (
            SELECT to_jsonb(s) AS row_json
            FROM public.subscriptions s
        ) AS legacy
        WHERE legacy.row_json->>'user_id' IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING;
    END IF;

    IF to_regclass('public.billing_events') IS NOT NULL THEN
        INSERT INTO stripe_events (event_id, type, created_at, processed_at)
        SELECT
            legacy.row_json->>'event_id',
            legacy.row_json->>'type',
            COALESCE(NULLIF(legacy.row_json->>'created_at', '')::timestamptz, NOW()),
            COALESCE(NULLIF(legacy.row_json->>'processed_at', '')::timestamptz, NOW())
        FROM (
            SELECT to_jsonb(e) AS row_json
            FROM public.billing_events e
        ) AS legacy
        WHERE legacy.row_json->>'event_id' IS NOT NULL
        ON CONFLICT (event_id) DO NOTHING;
    END IF;
END $$;

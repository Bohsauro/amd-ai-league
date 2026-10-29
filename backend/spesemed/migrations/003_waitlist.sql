-- =============================================================================
-- SPESEMED - Migrazione 003: Tabella waitlist (iscrizioni da Landing Page)
-- =============================================================================
-- Eseguire nella SQL Editor di Supabase: https://supabase.com/dashboard/project/_/sql
-- Idempotente (usa IF NOT EXISTS).
-- =============================================================================

CREATE TABLE IF NOT EXISTS waitlist (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indice per ricerca rapida per email
CREATE INDEX IF NOT EXISTS idx_waitlist_email ON waitlist (email);

-- Abilita Row Level Security (RLS)
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

-- Solo il service_role puo' leggere ed inserire nella tabella waitlist (backend-only)
DROP POLICY IF EXISTS "Service role full access on waitlist" ON waitlist;
CREATE POLICY "Service role full access on waitlist" ON waitlist
    FOR ALL
    USING (auth.role() = 'service_role');

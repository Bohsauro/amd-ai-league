-- =============================================================================
-- SPESEMED - Migrazione 001: schema iniziale (jobs + extractions + RPC worker)
-- =============================================================================
-- Eseguire nella SQL Editor di Supabase: https://supabase.com/dashboard/project/_/sql
-- Idempotente (usa IF NOT EXISTS / OR REPLACE ovunque).
--
-- PREREQUISITO: bucket Storage "receipts" creato PRIVATO dalla dashboard.
--   Storage -> New bucket -> Name: "receipts" -> Public: OFF -> Save
-- =============================================================================

-- =============================================================================
-- jobs: un job = un batch asincrono di N>3 file
-- =============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    file_count INT NOT NULL CHECK (file_count > 0),
    file_hashes TEXT[] NOT NULL DEFAULT '{}',
    model TEXT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs (user_id, created_at DESC);
-- Indice specifico per il polling del worker (pending + retry time)
CREATE INDEX IF NOT EXISTS idx_jobs_pending_retry
    ON jobs (next_retry_at NULLS FIRST, created_at)
    WHERE status = 'pending';

-- =============================================================================
-- extractions: cache idempotency (user_id, file_hash) + storico risultati
-- =============================================================================
CREATE TABLE IF NOT EXISTS extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    file_hash TEXT NOT NULL,
    filename TEXT,
    storage_path TEXT,
    data JSONB NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Idempotency: stesso utente + stesso file = stessa estrazione
    UNIQUE (user_id, file_hash)
);

CREATE INDEX IF NOT EXISTS idx_extractions_user ON extractions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_extractions_job ON extractions (job_id) WHERE job_id IS NOT NULL;

-- =============================================================================
-- Trigger: aggiorna updated_at automaticamente su jobs
-- =============================================================================
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jobs_touch_updated_at ON jobs;
CREATE TRIGGER trg_jobs_touch_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =============================================================================
-- RPC: claim_next_job — atomic job claim con FOR UPDATE SKIP LOCKED
-- =============================================================================
-- Chiamato dal worker Python. Atomico: due worker non possono claimare
-- lo stesso job simultaneamente. Rispetta next_retry_at per il backoff.
CREATE OR REPLACE FUNCTION claim_next_job(p_worker_id TEXT)
RETURNS SETOF jobs
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    UPDATE jobs
    SET status = 'processing',
        attempts = attempts + 1,
        updated_at = NOW()
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'pending'
          AND (next_retry_at IS NULL OR next_retry_at <= NOW())
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING *;

    IF FOUND THEN
        RAISE NOTICE 'Worker % claimed a job', p_worker_id;
    END IF;
END;
$$;

-- =============================================================================
-- RPC: reset_zombie_jobs — recupera job bloccati in 'processing' da troppo tempo
-- =============================================================================
-- Se un worker muore tra claim e completamento, il job resta 'processing'
-- all'infinito. Questa RPC resetta a 'pending' con next_retry_at = now+30s.
CREATE OR REPLACE FUNCTION reset_zombie_jobs(p_timeout_minutes INT)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    reset_count INT;
BEGIN
    UPDATE jobs
    SET status = 'pending',
        next_retry_at = NOW() + INTERVAL '30 seconds',
        updated_at = NOW()
    WHERE status = 'processing'
      AND updated_at < NOW() - (p_timeout_minutes || ' minutes')::INTERVAL;

    GET DIAGNOSTICS reset_count = ROW_COUNT;
    RETURN reset_count;
END;
$$;

-- =============================================================================
-- Storage policies (opzionale: la service_role_key le bypassa)
-- =============================================================================
-- Le policy seguenti si applicano solo se si usa la anon key (lato client).
-- Con service_role_key (lato server) si ha accesso completo, quindi non servono.
-- Documentazione: https://supabase.com/docs/guides/storage/security/access-control
-- Creare il bucket dalla dashboard (Storage -> New bucket -> Private).

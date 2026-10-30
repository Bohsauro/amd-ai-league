-- =============================================================================
-- SPESEMED - Migrazione 002: Row Level Security (RLS) per difesa-in-profondita'
-- =============================================================================
-- Idempotente (DROP POLICY IF EXISTS + CREATE POLICY ovunque).
-- Obiettivo: anche se il backend dimentica un `.eq("user_id", user_id)`
-- nelle Postgrest query, il DB rifiuta cross-user SELECT/INSERT.
--
-- NB: il backend usa SUPABASE_SERVICE_KEY (service_role) per la maggior
-- parte delle query: quel ruolo POSSIEDE l'attributo BYPASSRLS, quindi
-- NON e' filtrato dalle policies (worker + RPC claim_next_job funzionano).
-- Le policies si applicano invece al client futuro che si autentica con
-- il proprio JWT utente (anon key + Bearer token).
--
-- Eseguire via SQL Editor di Supabase (https://supabase.com/dashboard/project/_/sql).
-- =============================================================================

-- =============================================================================
-- TABELLA jobs
-- =============================================================================

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT ON jobs TO authenticated;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

DROP POLICY IF EXISTS "jobs_select_own" ON jobs;
CREATE POLICY "jobs_select_own"
    ON jobs
    FOR SELECT
    TO authenticated
    USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS "jobs_insert_own" ON jobs;
CREATE POLICY "jobs_insert_own"
    ON jobs
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid()::text = user_id);

-- UPDATE/DELETE: VIETATI per 'authenticated'.
-- Il job e' mutable solo dal worker Python via service_role
-- (che salta RLS tramite BYPASSRLS attribute).
-- Definire policy negative serves a bloccare esplicitamente anche se
-- i GRANT di default concedessero UPDATE/DELETE per errore.
DROP POLICY IF EXISTS "jobs_no_update" ON jobs;
CREATE POLICY "jobs_no_update"
    ON jobs
    FOR UPDATE
    TO authenticated
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS "jobs_no_delete" ON jobs;
CREATE POLICY "jobs_no_delete"
    ON jobs
    FOR DELETE
    TO authenticated
    USING (false);

-- =============================================================================
-- TABELLA extractions
-- =============================================================================

ALTER TABLE extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE extractions FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT ON extractions TO authenticated;

DROP POLICY IF EXISTS "extractions_select_own" ON extractions;
CREATE POLICY "extractions_select_own"
    ON extractions
    FOR SELECT
    TO authenticated
    USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS "extractions_insert_own" ON extractions;
CREATE POLICY "extractions_insert_own"
    ON extractions
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid()::text = user_id);

DROP POLICY IF EXISTS "extractions_no_update" ON extractions;
CREATE POLICY "extractions_no_update"
    ON extractions
    FOR UPDATE
    TO authenticated
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS "extractions_no_delete" ON extractions;
CREATE POLICY "extractions_no_delete"
    ON extractions
    FOR DELETE
    TO authenticated
    USING (false);

-- =============================================================================
-- STORAGE bucket 'receipts' (storage.objects)
-- =============================================================================
-- Path layout: receipts/{user_id}/{sha256}.{ext}
-- PG arrays sono 1-based: string_to_array('a/b/c','/') = {'a','b','c'}
-- Quindi indice [2] = user_id, [3] = filename.
-- =============================================================================

DROP POLICY IF EXISTS "storage_select_own_receipts" ON storage.objects;
CREATE POLICY "storage_select_own_receipts"
    ON storage.objects
    FOR SELECT
    TO authenticated
    USING (
        bucket_id = 'receipts'
        AND (storage.objects.name)::text LIKE 'receipts/%'
        AND (string_to_array(storage.objects.name, '/'))[2] = auth.uid()::text
    );

DROP POLICY IF EXISTS "storage_insert_own_receipts" ON storage.objects;
CREATE POLICY "storage_insert_own_receipts"
    ON storage.objects
    FOR INSERT
    TO authenticated
    WITH CHECK (
        bucket_id = 'receipts'
        AND (string_to_array(storage.objects.name, '/'))[2] = auth.uid()::text
    );

DROP POLICY IF EXISTS "storage_no_update_receipts" ON storage.objects;
CREATE POLICY "storage_no_update_receipts"
    ON storage.objects
    FOR UPDATE
    TO authenticated
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS "storage_no_delete_receipts" ON storage.objects;
CREATE POLICY "storage_no_delete_receipts"
    ON storage.objects
    FOR DELETE
    TO authenticated
    USING (false);

-- =============================================================================
-- RUOLO 'anon'
-- =============================================================================
-- Supabase include di default il ruolo 'anon' (chiave pubblica).
-- Non concediamo GRANT direttamente: nessun anon puo' toccare jobs/extractions.
-- Una policy "deny all" esplicita servirebbe solo se 'anon' avesse GRANT,
-- cosa che non facciamo. Documentazione di sicurezza.
-- =============================================================================

-- =============================================================================
-- RPC: claim_next_job / reset_zombie_jobs
-- =============================================================================
-- Le RPC restano SECURITY INVOKER (default). Il worker Python le evoca con
-- la SUPABASE_SERVICE_KEY, quindi gira nel ruolo Postgres 'service_role'
-- che possiede BYPASSRLS: le policy di sopra non si applicano alle RPC.
-- Non serve SECURITY DEFINER.
-- =============================================================================

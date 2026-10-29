# SPESEMED - Verify RLS Migration on Supabase

> **Operational protocol**: application + verification of
> `migrations/002_rls_policies.sql` on Supabase. To execute AFTER manual
> login to https://supabase.com/dashboard/project/_/sql.
>
> **Per pen-tester auditing**: questo protocollo è il "pass/fail contract"
> che documenta le aspettative di sicurezza post-deployment. Salva gli
> screenshot delle query come prova.

---

## §0 — Pre-flight checks (PRIMA di applicare la migration)

### §0.1 — Backup PITR attivo

```sql
-- Esegui questa query nel SQL Editor di Supabase.
-- Atteso: PITR enabled = TRUE
SELECT
    name,
    setting,
    short_desc
FROM pg_settings
WHERE name IN ('wal_level', 'max_wal_senders', 'archive_mode')
ORDER BY name;
```

Se `wal_level != 'replica'` o `archive_command` non configurato: **STOP**. Vai su Settings → Database → Point-in-time Recovery e abilita. PITR è REQUIRED per compliance GDPR + recovery (rollback migration possibile).

### §0.2 — Service role key verificata

Verifica che `SUPABASE_SERVICE_KEY` nel tuo `.env` di produzione sia effettivamente il **service_role** (non anon, non authenticated). Per distinguerlo:
- service_role: ~250 chars JWT, claims `role=service_role` (verificabile con jwt.io)
- anon: ~250 chars JWT, claims `role=anon`

Apri https://jwt.io, incolla il token, verifica campo `role` nel payload.

### §0.3 — Storage bucket `receipts` PRIVATO

In Supabase Dashboard → Storage → buckets → `receipts`: deve mostrare icona 🔒 (privato). Se pubblico: clicca `receipts` → "Make private".

### §0.4 — Test users pre-creati (per §3 + §6)

Crea 2 utenti test in **Supabase Dashboard → Authentication → Users → Add user**:

```text
User A:
  email: user_a@test.local
  password: (scegli una password robusta)
  Auto Confirm User: ✅ ON   ← IMPORTANTE: email_confirmed=true
                         (altrimenti GoTrue grant_type=password
                          fallisce con "Email not confirmed")

User B:
  email: user_b@test.local
  password: (scegli una password robusta)
  Auto Confirm User: ✅ ON
```

Annota i 2 UUID generati (saranno user_id delle righe di test in §3).
Senza questo pre-step il pen-tester può perdere 30 min in
"auth fallisce silenziosamente".

### §0.5 — 🔴 CRITICAL: UUID placeholder substitution

⚠️  **LE QUERY §3 E §3.6.5.1 USANO UUID SEGNAPOSTO HARDCODED
(`11111111-1111-4111-8111-111111111111` per user A,
`22222222-2222-4222-8222-222222222222` per user B).
Sostituiscili con gli UUID REALI generati in §0.4 PRIMA di eseguire le query.**

Senza questa sostituzione:
- §3 INSERT fallisce con violazione (se avessi FK su user_id) o
  mis-match con `auth.uid()` → 0 rows anziché 1 row.
- §3.6.5.1 INSERT cross-tenant fallisce con FK violation senza
  generare la riga di test, quindi non testabile.

**Comando per sostituire automaticamente:**

```bash
# Sostituisci i 2 placeholder UUID con quelli reali annotati in §0.4.
# Esegui UNA volta prima di lanciare qualsiasi query.
UUID_A="<UUID reale user A annotato>"
UUID_B="<UUID reale user B annotato>"

# Verifica substitution (deve mostrare 1 occorrenza per placeholder in ogni file).
sed -i.bak \
  -e "s/11111111-1111-4111-8111-111111111111/${UUID_A}/g" \
  -e "s/22222222-2222-4222-8222-222222222222/${UUID_B}/g" \
  deployment/VERIFY_RLS.md
```

**Windows PowerShell equivalente:**

```powershell
$UUID_A = "<UUID reale user A>"
$UUID_B = "<UUID reale user B>"
(Get-Content deployment\VERIFY_RLS.md) |
  ForEach-Object {
    $_ -replace '11111111-1111-4111-8111-111111111111', $UUID_A `
       -replace '22222222-2222-4222-8222-222222222222', $UUID_B
  } | Set-Content deployment\VERIFY_RLS.md
```

**Cleanup post-substitution (solo per bash/Linux/macOS):** `sed -i.bak`
crea SEMPRE un file `VERIFY_RLS.md.bak` (sovrascrive l'eventuale `.bak`
precedente). Rimuovilo:

```bash
rm -f deployment/VERIFY_RLS.md.bak
```

NB: la versione PowerShell qui sopra NON genera `.bak` (usa
`Set-Content` direttamente) — l'operatore Windows può saltare
questo `rm`.

**Nota di idempotenza assertiva:** esegui questo comando di sostituzione
**UNA sola volta** all'inizio della sessione di verifica. Rieseguire
non causa side-effect: `sed`/`-replace` escono con status 0 silenzioso
(nessuna stringa `11111111-...` o `22222222-...` rimasta → nessun match
→ nessuna modifica). Stai pure tranquillo se per sbaglio lo lanci 2 volte.

Dopo substitution i placeholder non sono più visibili nelle query §3/§3.6/§3.6.5.1
(mostrano gli UUID reali). Questa sezione §0.5 resta come instruzione
iniziale per future re-run della procedura.

**Alternativa elegante:** modificare la prima riga di questo file
subito dopo §0.4 per anteporre un PREAMBLE che ridefinisce i 2 UUID.
Tutte le query seguenti continueranno a usare i placeholder ma il
lettore capirà che vanno sostituiti.

---

## §1 — Apply Migration

### §1.1 — Apri SQL Editor

URL: `https://supabase.com/dashboard/project/<YOUR_PROJECT_REF>/sql/new`

(Sostituisci `<YOUR_PROJECT_REF>` con il tuo Reference ID da Settings → General)

### §1.2 — Copia-incolla la migration

Path locale: `C:\Users\giova\Desktop\progetti\SPESEMED\migrations\002_rls_policies.sql`

Comando per copiare negli appunti (alternativa a copy-paste manuale):
```bash
# macOS
cat /path/to/SPESEMED/migrations/002_rls_policies.sql | pbcopy

# Linux (xclip)
cat /path/to/SPESEMED/migrations/002_rls_policies.sql | xclip -selection clipboard

# Windows (PowerShell)
Get-Content migrations\002_rls_policies.sql | Set-Clipboard
```

Incolla nel SQL Editor di Supabase.

### §1.3 — Run migration

Click "Run" (Ctrl+Enter). Atteso nel footer:
> **Success. No rows returned**

(La migration è DDL puro: ALTER, GRANT, CREATE POLICY. Nessuna riga di output attesa.)

### §1.4 — Capture screenshot

Salva screenshot 1: SQL Editor con migration eseguita + footer "Success". Salva come `evidence/01_migration_applied.png`.

---

## §2 — Verify RLS: Anon (FAIL = GOOD)

### §2.1 — Query anon

Nel SQL Editor, esegui:

```sql
-- Forza contesto anonimo (bypass service_role introspezione).
SET ROLE anon;
SELECT id, user_id, status, file_count
FROM jobs
LIMIT 5;
RESET ROLE;
```

### §2.2 — Expected result

```
ERROR:  permission denied for table jobs
```
OR
```
Success. 0 rows
```
(Supabase restituisce 403 "permission denied" perché la GRANT a `anon` non è stata data.)

### §2.3 — Capture screenshot

Salva screenshot 2: query output. Salva come `evidence/02_anon_jobs_denied.png`.

**Questo è il FAIL-CLOSED behavior corretto**: un anon user NON può vedere jobs di nessuno.

---

## §3 — Verify RLS: Authenticated (OWN ONLY)

### §3.1 — Setup test data (workspace SQL Editor)

Esegui come service_role (default del SQL Editor):

```sql
-- Insert 2 test jobs: uno tuo, uno di un altro user fittizio.
INSERT INTO jobs (user_id, status, file_count, file_hashes, model)
VALUES
    ('11111111-1111-4111-8111-111111111111', 'pending', 2, ARRAY['hash1','hash2']::text[], 'google/gemini-2.5-flash-lite'),
    ('22222222-2222-4222-8222-222222222222', 'done', 3, ARRAY['hash3','hash4','hash5']::text[], 'google/gemini-2.5-flash-lite')
RETURNING id, user_id;
```

Salva gli ID di entrambi i job per riferimento.

### §3.2 — Query come authenticated user A

```sql
-- Simula user A autenticato (auth.uid() deve matchare user_id della riga 1).
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
SELECT id, user_id, status FROM jobs ORDER BY user_id;
RESET ROLE;
```

### §3.3 — Expected result

```
Success. 1 row:
  id | user_id                                | status
  -- | -------------------------------------- | --------
  1  | 11111111-1111-4111-8111-111111111111 | pending
```

**SOLO la riga del proprio user**. La riga del user B deve essere filtrata via RLS.

### §3.4 — Query come authenticated user B

```sql
SET LOCAL request.jwt.claim.sub TO '22222222-2222-4222-8222-222222222222';
SET ROLE authenticated;
SELECT id, user_id, status FROM jobs ORDER BY user_id;
RESET ROLE;
```

Expected: SOLO la riga del user B.

### §3.5 — Capture screenshot

Salva screenshot 3 (user A) e 4 (user B). `evidence/03_userA_sees_own.png`, `evidence/04_userB_sees_own.png`.

### §3.6 — 🔴 CRITICAL: Negative cross-tenant test

Questo è il test più importante per il pen-tester. Verifica che user A
**NON possa** vedere o modificare dati di user B anche se conosce lo UUID.

#### §3.6.1 — Read cross-tenant (user A prova a leggere dati di user B)

```sql
-- User A autenticato prova a SELECT esplicita del job di user B.
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
SELECT id, user_id, status FROM jobs
WHERE user_id = '22222222-2222-4222-8222-222222222222';
RESET ROLE;
```

**Expected:**
```
Success. 0 rows
```

Se restituisce 1 row: 🔴 **CRITICAL cross-tenant leak**. RLS fallita.

#### §3.6.2 — Update cross-tenant (user A prova a modificare job di user B)

```sql
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
UPDATE jobs SET status = 'pwned'
WHERE user_id = '22222222-2222-4222-8222-222222222222';
RESET ROLE;
```

**Expected:**
```
Success. 0 rows (UPDATE matches 0 rows)
```

#### §3.6.3 — Delete cross-tenant

```sql
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
DELETE FROM jobs WHERE user_id = '22222222-2222-4222-8222-222222222222';
RESET ROLE;
```

**Expected:** 0 rows deleted.

#### §3.6.4 — 🔴 INSERT cross-tenant (data poisoning attack)

Questo è il vettore più pericoloso: user A prova a inserire una riga
**spacciandosi per user B**, avvelenando i dati di user B senza
bisogno di leggerli.

```sql
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
INSERT INTO jobs (user_id, status, file_count, file_hashes, model)
VALUES ('22222222-2222-4222-8222-222222222222', 'pwned', 99, ARRAY['x']::text[], 'm');
RESET ROLE;
```

**Expected:**
```
ERROR: new row violates row-level security policy for table "jobs"
```

Se restituisce success: la policy INSERT non è `WITH CHECK` su `user_id`
e l'attaccante può scrivere dati per conto di altri utenti.

#### §3.6.5 — Disclaimer su limiti del test diretto SQL

⚠️  `SET LOCAL request.jwt.claim.sub` funziona solo in sessioni SQL dirette
(workspace SQL Editor / `psql`). NON è osservabile via PostgREST o
Supabase JS Client (che richiedono un JWT reale emesso da GoTrue).
Per test API-driven (più realistici per il pen-tester):
1. Crea 2 utenti reali via Dashboard → Authentication → Users.
2. Ottieni i loro JWT via `client.auth.sign_in_with_password(...)`.
3. Usa `curl -H "Authorization: Bearer <JWT_USER_A>"` per testare
   le stesse query come utente reale.

Senza questo disclaimer un attacker potrebbe aggirare RLS via API-driven
endpoints se la migration è applicata correttamente in SQL ma il
backend lascia field `user_id` scrivibile dal client.

#### §3.6.5.1 — Esempio API-driven (consigliato per pen-test realistico)

```bash
# 0. Prerequisite tool check.
command -v jq >/dev/null || { echo "INSTALL jq: brew install jq | apt install jq | choco install jq"; exit 1; }

# 1. Ottieni JWT reale di user A via GoTrue.
# NB 1: GoTrue richiede email_confirmed=true per grant_type=password
#       (vedi §0.4 pre-step test users creation).
# NB 2: gli access_token Supabase scadono in 1h. Per pen-test multi-ora,
#       rieseguire questo blocco ogni ~50min o usare refresh_token.
JWT_A=$(curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"user_a@test.local","password":"..."}' | jq -r .access_token)

# Fail-fast se l'auth e' fallita (jwt vuoto = errori silenziosi dopo).
[ -n "$JWT_A" ] || { echo "AUTH FAIL: user_a@test.local non confermato o password errata"; exit 1; }

# 2. Tenta INSERT cross-tenant via PostgREST (REST API).
# Prefer: return=representation forza PostgREST a restituire la riga
# (o l'errore) nel body invece di risposta vuota.
curl -i -X POST "$SUPABASE_URL/rest/v1/jobs" \
  -H "Authorization: Bearer $JWT_A" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"user_id":"22222222-2222-4222-8222-222222222222","status":"pwned","file_count":99,"file_hashes":["x"],"model":"m"}'
```

**Expected:** HTTP 401 Unauthorized con body
`{"message":"new row violates row-level security policy for table jobs"}`
(RLS blocca a livello PostgREST; auth.uid() risolve NULL quando sub non matcha → 401).

⚠️ Distinguere **401 (RLS blocca)** vs **403 (JWT invalido)**:
- 401 + `new row violates...` → ✅ policy WITH CHECK attiva via PostgREST.
- 403 + `Invalid JWT` → 🟠 JWT problema (test infrastructure, non RLS).

Se restituisce HTTP 201 con la riga creata: 🔴 **CRITICAL** — la policy
esiste solo a livello Postgres ma NON è applicata via REST API
(bug grave, migration 002 va rieseguita o PostgREST va riconfigurato).

Salva output completo (headers + body) come `evidence/05b_api_driven_insert_blocked.txt`.

#### §3.6.6 — Capture screenshot

Salva screenshot 5: `evidence/05_cross_tenant_blocked.png` (mostra tutte
e 3 le query in un unico screenshot per audit efficiency).

### §3.7 — Catalog completeness check (post-migration)

Verifica che tutte le policy attese siano effettivamente caricate in
`pg_catalog.pg_policies`:

```sql
SELECT tablename, policyname, cmd, roles, qual
FROM pg_policies
WHERE tablename IN ('jobs', 'extractions')
ORDER BY tablename, policyname;
```

**Expected:** minimo 6 policies visibili (jobs_select_own, jobs_insert_own,
jobs_no_update, jobs_no_delete, extractions_select_own, extractions_insert_own).
Se ne manca qualcuna: 🔴 RLS migration parzialmente applicata → rollback e re-apply.

Salva come `evidence/06_pg_policies_catalog.png`.

---

## §4 — Verify RLS: extractions (cross-table)

### §4.1 — Insert + Query

```sql
-- Insert come service_role.
INSERT INTO extractions (user_id, file_hash, data, model)
VALUES
    ('11111111-1111-4111-8111-111111111111', 'hashA1', '{"data_spesa":"2024-01-15","importo_totale": 42.50}'::jsonb, 'gemini'),
    ('22222222-2222-4222-8222-222222222222', 'hashB1', '{"data_spesa":"2024-02-15","importo_totale": 99.99}'::jsonb, 'gemini')
RETURNING id, file_hash;

-- Query come user A (dovrebbe vedere solo hashA1).
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
SELECT file_hash, data->>'data_spesa' FROM extractions;
RESET ROLE;
```

### §4.2 — Expected

Solo 1 row: `hashA1 | 2024-01-15`.

### §4.3 — Capture

Salva come `evidence/05_extractions_isolation.png`.

---

## §5 — Verify RLS: Service Role bypass (POSITIVE)

### §5.1 — Query come service_role

```sql
-- service_role bypassa RLS (per design).
SET ROLE service_role;
SELECT count(*) FROM jobs;
SELECT count(*) FROM extractions;
RESET ROLE;
```

### §5.2 — Expected

`jobs` count = N (entrambi i tuoi job, anche se appartengono a user diversi).
`extractions` count = N (entrambe le tue insertions).

### §5.3 — Significato

Conferma che il backend (che usa service_role key) può ancora vedere tutte le righe per la logica del worker.

---

## §6 — Verify RLS: Storage bucket isolation

### §6.1 — Insert file come user A

Storage bucket non è accessibile direttamente via SQL Editor (è una tabella di storage interna). Per testarlo serve uno script Python o uno strumento esterno.

Crea uno script locale `deployment/verify_storage_rls.py`:

```python
import os
import httpx
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]  # ANON (non service)

client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Signin come user A (per ottenere JWT).
client.auth.sign_in_with_password({
    "email": os.environ["USER_A_EMAIL"],
    "password": os.environ["USER_A_PASSWORD"],
})

# Upload file user A.
user_a_path = "receipts/11111111-1111-4111-8111-111111111111/test_a.pdf"
client.storage.from_("receipts").upload(
    user_a_path, b"fake-pdf-content-user-a",
    file_options={"content-type": "application/pdf"},
)

# List bucket: deve mostrare SOLO i file del proprio user_id.
files = client.storage.from_("receipts").list("receipts/")
for f in files:
    name = f.get("name", "")
    if "11111111" in name or "22222222" in name:
        print(f"  {name}")

# Expected: solo file con "11111111" nel path.
```

Esegui: `python deployment/verify_storage_rls.py`.

Salva output come `evidence/06_storage_isolation.txt`.

---

## §7 — Verify RLS: NO UPDATE/DELETE for users

### §7.1 — Tentativo UPDATE bloccato

```sql
-- user A prova a modificare la propria riga.
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
UPDATE jobs SET status = 'hacked' WHERE file_count = 2;
RESET ROLE;
```

### §7.2 — Expected

```
Success. 0 rows  (UPDATE matches 0 rows perché policy USING(false) blocca)
```

### §7.3 — Tentativo DELETE bloccato

```sql
SET LOCAL request.jwt.claim.sub TO '11111111-1111-4111-8111-111111111111';
SET ROLE authenticated;
DELETE FROM jobs WHERE file_count = 2;
RESET ROLE;
```

Expected: 0 rows deleted.

---

## §8 — Final verification matrix

| # | Test | Expected | Failure → Severity |
|---|------|----------|-------------------|
| §2 | SELECT anon | "permission denied" | 🔴 CRITICAL leak globale |
| §3.3 | SELECT authenticated user A | 1 row (own only) | 🔴 CRITICAL cross-user leak |
| §3.4 | SELECT authenticated user B | 1 row (own only) | 🔴 CRITICAL cross-user leak |
| §4 | SELECT extractions user A | 1 row (own only) | 🔴 CRITICAL cross-user leak |
| §5 | SELECT service_role | All rows | 🟢 OK se N > 0 (worker funziona) |
| §6 | Storage list user A | Own files only | 🔴 CRITICAL storage leak |
| §7.1 | UPDATE jobs user A | 0 rows affected | 🟢 OK (user cannot mutate) |
| §7.3 | DELETE jobs user A | 0 rows deleted | 🟢 OK (user cannot delete) |

---

## §9 — Cleanup post-verifica

Dopo aver confermato che la migration funziona:

```sql
-- Rimuovi i test data (workspace SQL Editor, come service_role).
DELETE FROM jobs WHERE user_id IN (
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222'
);
DELETE FROM extractions WHERE user_id IN (
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222'
);
```

---

## §10 — Evidence checklist per pen-tester

Salva tutti gli screenshot in `evidence/` (directory locale del repository):

```
evidence/
├── 01_migration_applied.png      (SQL Editor + success footer)
├── 02_anon_jobs_denied.png        (Section 2.2)
├── 03_userA_sees_own.png          (Section 3.3)
├── 04_userB_sees_own.png          (Section 3.4)
├── 05_extractions_isolation.png   (Section 4.2)
├── 06_storage_isolation.txt       (Section 6.2)
├── 07_update_blocked.png          (Section 7.2)
├── 08_delete_blocked.png          (Section 7.3)
└── README.md                       (summary + timestamp)
```

Il pen-tester richiederà questa cartella come PROVA del fix.

---

_Documento generato per supportare l'applicazione manuale della
migration RLS produzione. La cartella `evidence/` diventa parte del
deliverable per l'auditing security post-deploy._

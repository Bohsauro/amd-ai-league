# SPESEMED — Go-Live Runbook 🚀

> **Manuale operativo** per deploy del backend SPESEMED in produzione.
> Tempo stimato: **5-10 minuti** (escluso il bootstrap del progetto Supabase).
>
> **Cosa puoi fare tu (utente):** le 4 azioni qui sotto richiedono accesso
> admin al tuo progetto Supabase e al tuo account OpenRouter.
> **Cosa NON puoi fare io (assistente):** operazioni sulla dashboard di terze parti.

---

## 📋 Prerequisiti

- [ ] Account Supabase attivo (free tier ok: https://supabase.com)
- [ ] Account OpenRouter con API key (https://openrouter.ai/keys)
- [ ] Python 3.10+ in venv
- [ ] Repo SPESEMED clonato e dipendenze installate (`pip install -r requirements.txt`)

> **Bootstrap Supabase** (se non hai ancora un progetto): vai su
> https://supabase.com/dashboard → New project → attendi 2-3 minuti.

---

## STEP 1 — Applica la migration SQL (schema + RPC + triggers)

> Cosa installa: tabelle `jobs` + `extractions`, RPC `claim_next_job` con
> `FOR UPDATE SKIP LOCKED`, trigger `touch_updated_at`, indici performance.

### Opzione A — Dashboard Supabase (consigliata per la prima volta)

1. Apri https://supabase.com/dashboard → seleziona il tuo progetto.
2. Sidebar sinistra → **SQL Editor** (icona database con `>_`).
3. Click **"+ New query"** in alto a sinistra.
4. Apri localmente il file `migrations/001_init.sql` (133 righe) e copia TUTTO il contenuto.
5. Incolla nell'editor SQL del dashboard.
6. Click **"Run"** (oppure `Ctrl+Enter`).
7. Verifica: nel footer deve apparire "Success. No rows returned" (perché sono DDL, non DML).

> ⚠️ **BLOCCANTE FREQUENTE: Email confirmation in Supabase.**
> Di default Supabase Auth richiede **conferma email magic-link** prima del login.
> Questo blocca STEP 4.3 (login dopo signup restituisce `401 "Email not confirmed"`).
> **Fix (consigliato per dev):**
>
> 1. Sidebar → **Authentication** → **Providers** (o **Sign In/Up**)
> 2. Click su **Email**
> 3. Sezione **"Confirm email"** → toggle **OFF**
> 4. Save
>
> Per produzione: lascia `Confirm email ON` e configura un SMTP provider (Resend, SendGrid) per inviare i magic link.

### Opzione B — supabase CLI (per dev esperti / CI/CD)

```bash
# Installa supabase CLI (https://supabase.com/docs/guides/cli)
npm install -g supabase   # oppure: brew install supabase/tap/supabase

# Login
supabase login

# Init: scaffolda la cartella supabase/ (richiesto dalla CLI).
# NB: supabase-cli si aspetta migrations in supabase/migrations/, non nella root.
supabase init
mkdir -p supabase/migrations
cp ../migrations/001_init.sql supabase/migrations/   # o copia-incolla manuale

# Link al progetto remoto (lo trovi in Settings → General → Reference ID)
supabase link --project-ref <YOUR_PROJECT_REF>

# Applica la migration
supabase db push
```

### Verifica Step 1

Dopo l'esecuzione, controlla che esistano:

- **Table Editor → jobs** (vuota, struttura: id, user_id, status, file_count, file_hashes, model, claimed_by, claimed_at, expires_at, last_error, created_at, updated_at)
- **Table Editor → extractions** (vuota, struttura: id, job_id, user_id, file_hash UNIQUE, data jsonb, storage_path, filename, model, created_at)
- **Database → Functions → claim_next_job(p_worker_id TEXT)** (presente, `Returns: TABLE(...)`)
- **Database → Functions → reset_zombie_jobs(p_timeout_minutes INT)** (presente)
- **Database → Triggers → trg_jobs_touch_updated_at** (presente, ON jobs)

Se tutti e 5 ci sono, ✅ Step 1 completo.

---

## STEP 2 — Crea il bucket Storage `receipts`

> Cosa fa: bucket PRIVATO dove salvare le ricevute originali (PDF/JPG)
> in path `receipts/{user_id}/{sha256}.{ext}`. Mai pubblico (GDPR).

1. Apri https://supabase.com/dashboard → progetto → **Storage** (sidebar sinistra).
2. Click **"New bucket"** in alto a destra.
3. Configura:
   - **Name**: `receipts` (lowercase, esatto, NO underscore/spazi)
   - **Public bucket**: ❌ **OFF** (importante — deve essere privato)
   - **File size limit**: lascia default o imposta `52428800` (50 MB, se prevedi PDF grandi)
   - **Allowed MIME types**: lascia vuoto (accettiamo tutti)
4. Click **"Create bucket"**.

### Verifica Step 2

In Storage → buckets deve apparire `receipts` con l'icona 🔒 (privato).
Click su `receipts` → tab "Policies" → deve essere vuoto (no RLS policies per ora, usa service_role).

✅ Step 2 completo.

---

## STEP 3 — Popola il file `.env` con i secrets

> Cosa serve: 3 valori critici da Supabase + 1 da OpenRouter. MAI committare `.env`.

### 3.1 Copia il template

```bash
# macOS / Linux
cp .env.example .env

# Windows
copy .env.example .env
```

### 3.2 Riempi i campi

Apri `.env` in un editor e sostituisci i placeholder:

| Campo | Dove trovarlo in Supabase | Esempio |
|-------|--------------------------|---------|
| `SUPABASE_URL` | Settings → API → **Project URL** | `https://abc123.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Settings → API → **service_role** (secret, NON anon!) | `eyJhbGciOi...` (~200 chars) |
| `SUPABASE_JWT_SECRET` | Settings → API → **JWT Secret** (scroll in basso) | una stringa lunga ~32 chars |
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys → **Create Key** | `sk-or-v1-...` |
| `ALLOW_SIGNUP` | (manuale) | `true` per dev, `false` per produzione |
| `API_ENV` | (manuale) | `development` oppure `production` |

> ⚠️ **SICUREZZA**: la `SUPABASE_SERVICE_KEY` bypassa TUTTE le Row Level
> Security policies. Non esporla MAI al client. Solo backend.

### 3.3 Valida il file (opzionale ma consigliato)

```bash
cd SPESEMED
python -c "from spesemed.api.config import settings; print('OK | supabase_configured =', bool(settings.supabase_url and settings.supabase_service_key))"
```

Atteso: `OK | supabase_configured = True`.

### 3.4 Audit pre-go-live (riusalo ad ogni cambio .env)

```bash
python tests/audit_pre_go_live.py
```

Atteso: `>>> AUDIT PASSED: migration SQL sintatticamente OK, .env allineata a config.py.`
Il report dettagliato è in `tests/AUDIT_REPORT.md` (artifact, in .gitignore).

✅ Step 3 completo.

---

## STEP 4 — Boot del backend e smoke test autenticato

> Verifica end-to-end che l'API risponda correttamente con Supabase reale.

### 4.1 Avvia il server

```bash
# Modalità dev (1 worker, auto-reload)
python -m uvicorn spesemed.api.main:app --host 127.0.0.1 --port 8000

# Output atteso:
#   INFO:     Started server process [...]
#   INFO:     Waiting for application startup
#   INFO:     Application startup complete
#   INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 4.2 Health check (pubblico)

```bash
curl -sS http://127.0.0.1:8000/api/v1/health
```

Atteso:
```json
{
  "status": "ok",
  "service": "spesemed-api",
  "version": "0.3.0",
  "openrouter_configured": true
}
```

### 4.3 Crea utente + login (signup → login → token)

```bash
# 1. SIGNUP (crea utente in Supabase Auth)
curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@spesemed.it","password":"DemoPass123!"}'
```

Risposta attesa (`201 Created`):
```json
{
  "access_token": "eyJhbGciOi...",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "refresh_token": "v1.MWUx...",
  "expires_in": 3600
}
```

```bash
# 2. LOGIN (anche se signup ha gia' ritornato il token, testiamo login)
curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@spesemed.it","password":"DemoPass123!"}'
```

Salva l'`access_token` per i prossimi step:
```bash
TOKEN="<incolla-qui-il-access_token>"
```

### 4.4 Endpoint autenticato (con Bearer)

```bash
# GET /health con Bearer (deve accettare il JWT e ritornare 200)
curl -sS http://127.0.0.1:8000/api/v1/health \
  -H "Authorization: Bearer $TOKEN"
```

```bash
# GET /jobs/123 (job inesistente, atteso 404 non 503)
curl -sS -w "\n[HTTP=%{http_code}]\n" \
  http://127.0.0.1:8000/api/v1/jobs/123 \
  -H "Authorization: Bearer $TOKEN"
```

Atteso: `404 {"detail":"Job 123 non trovato."}` (non 503! se è 503 → SUPABASE_JWT_SECRET errato).

```bash
# POST /auth/refresh (rotazione token)
curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token_dal_login>"}'
```

```bash
# POST /auth/logout (best-effort 204)
curl -sS -w "\n[HTTP=%{http_code}]\n" -X POST \
  http://127.0.0.1:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

Atteso: `204 No Content` (o 200). Se `500` → errore nel try/except wrapper (raro, contattami).

### 4.5 Test estrazione reale (sync mode, 1 file)

```bash
# Prepara una ricevuta di test (qualsiasi PDF o JPG)
curl -sS -X POST http://127.0.0.1:8000/api/v1/extract \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@/path/to/una_ricevuta.pdf"
```

Atteso (200 OK):
```json
{
  "results": [
    {
      "data_spesa": "2024-...",
      "esercente": "Farmacia XYZ",
      "importo_totale": 12.50,
      "codice_fiscale_paziente": "RSSMRA...",
      "categoria_spesa": "Farmaci"
    }
  ],
  "count": 1,
  "file_hashes": ["abc123..."],
  "cached": [false],
  "model_used": "google/gemini-2.5-flash-lite"
}
```

### 4.6 Test idempotency (inviare lo stesso file 2x)

```bash
# Seconda chiamata con lo stesso file
curl -sS -X POST http://127.0.0.1:8000/api/v1/extract \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@/path/to/una_ricevuta.pdf"
```

Atteso: `"cached": [true]` (no nuovo consumo crediti OpenRouter).

✅ Step 4 completo → **BACKEND IN PRODUZIONE**.

---

## STEP 5 — Stripe billing (opzionale, test mode → live)

> Cosa installa: Checkout Session hosted da Stripe, webhook firmato e
> persistenza della subscription su Supabase. **Nessun dato carta transita
> dal backend** (PCI scope = SAQ A).
>
> Nota di stato: questa fase espone `GET /billing/plan`, `POST /billing/checkout`
> e `POST /billing/webhook`. Il **gating quota/402 su `/extract`** è un task
> separato e non è richiesto per configurare il billing.

### 5.1 Crea Product + Price ricorrente

1. Stripe Dashboard → **Product catalog → Add product**.
2. Nome: `SPESEMED PRO` (o il nome commerciale scelto).
3. Prezzo: ricorrente, mensile, importo desiderato (es. `9.99 EUR`).
4. Salva e copia il **Price ID** (`price_...`): va in `STRIPE_PRICE_ID`.
5. (Solo live) Configura **Stripe Tax** / dati fiscali dell'account secondo
   il tuo commercialista. La tassazione è una scelta di prodotto: il codice
   non la impone.

### 5.2 API keys

Stripe Dashboard → **Developers → API keys**:

- **Secret key** (`sk_test_...` o `sk_live_...`) → `STRIPE_SECRET_KEY`.
- La **publishable key** NON serve al backend: il browser riceve solo
  `checkout_url` e completa il pagamento su Stripe.

### 5.3 Webhook endpoint

Stripe Dashboard → **Developers → Webhooks → Add endpoint**:

- **Endpoint URL**: `https://<api-host>/api/v1/billing/webhook`
- **Eventi**: minimo `checkout.session.completed`.
  Gli altri eventi (`customer.subscription.*`, `invoice.*`) vengono accettati
  e ack-ati con `action=ignored`; l'aggiornamento del loro stato è backlog.
- Copia la **Signing secret** (`whsec_...`) → `STRIPE_WEBHOOK_SECRET`.

Il webhook non usa Bearer/JWT: l'autenticazione è la firma `Stripe-Signature`.
Una firma invalida restituisce `400` (fail-closed); un secret mancante `503`.

### 5.4 Popola `.env` e riavvia

```dotenv
STRIPE_SECRET_KEY=sk_live_...          # sk_test_... finché sei in test
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
STRIPE_CURRENCY=eur
STRIPE_SUCCESS_URL=https://app.spesemed.it/app/profilo?billing=success
STRIPE_CANCEL_URL=https://app.spesemed.it/app/profilo?billing=cancel
BILLING_PLAN_NAME=SPESEMED PRO
```

```bash
# verifica a caldo (nessun secret nella risposta)
curl -sS https://<api-host>/api/v1/billing/plan | python3 -m json.tool
# atteso: "stripe_configured": true, "webhook_configured": true
```

### 5.5 Persistenza subscription (consigliata)

Applica `backend/spesemed/migrations/004_stripe_subscriptions.sql` nella SQL
Editor di Supabase. La migration è idempotente e crea `subscriptions` con RLS
service_role-only. Senza migration il webhook risponde comunque `200` ma logga
un WARNING e non persiste la riga.

### 5.6 Test locale con Stripe CLI e carte finte

```bash
stripe login
stripe listen --forward-to localhost:8000/api/v1/billing/webhook
# copia il whsec_... stampato in STRIPE_WEBHOOK_SECRET e riavvia l'API

stripe trigger checkout.session.completed
```

`stripe trigger` verifica firma e ack: l'evento sintetico può non contenere
`client_reference_id`, quindi non aspettarti la persistenza. Per il flusso
completo usa una Checkout Session reale (`POST /billing/checkout` con Bearer)
e le carte pubbliche di test Stripe:

| Scenario | Numero | Scadenza / CVC |
|---|---|---|
| Successo | `4242 4242 4242 4242` | data futura / qualsiasi 3 cifre |
| Rifiuto | `4000 0000 0000 0002` | data futura / qualsiasi 3 cifre |
| 3DS | `4000 0027 6000 3184` | data futura / qualsiasi 3 cifre |

Mai usare carte reali in test. Verifica nei log `subscription_created` e la
riga in `subscriptions`.

### 5.7 Redis readiness (multi-worker)

Se `API_WORKERS > 1`, lo storage in-memory di slowapi moltiplica i limiti per
worker. Configura:

```dotenv
RATE_LIMIT_STORAGE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

Al boot l'API esegue un readiness check e logga un ERRORE chiaro se Redis non
è raggiungibile; con `memory` + multi-worker logga un WARNING. Per un singolo
worker il default `memory` resta valido.

### 5.8 Incidenti e rollback billing

| Sintomo | Causa | Remediation |
|---|---|---|
| `/billing/checkout` → `503` | Secret/price mancanti o libreria `stripe` assente | Verifica `.env` + `GET /billing/plan`; reinstalla requirements; riavvia |
| Webhook → `503` | `STRIPE_WEBHOOK_SECRET` mancante | Imposta il signing secret dell'endpoint corretto |
| Webhook → `400` | Firma invalida / secret di un altro endpoint / body riscritto dal proxy | Usa il secret giusto, non modificare il body, rigenera il secret se serve |
| Webhook `200` ma niente in `subscriptions` | Migration 004 assente o Supabase non configurato | Applica migration, verifica `SUPABASE_*`, controlla i WARNING nei log |
| Sospetto leak chiave | Secret finita in log/repo | Ruota subito in Stripe, aggiorna `.env`/vault, riavvia, controlla i log |
| Vuoi disattivare il billing | — | Svuota `STRIPE_SECRET_KEY` (checkout → `503`, nessuna chiamata Stripe). Svuota anche `STRIPE_WEBHOOK_SECRET` per far rispondere `503` al webhook |

**Mai** loggare chiavi o body webhook completi: contengono PII. Ruota i secret
se esposti e usa sempre il test mode finché il prodotto non è pronto.

✅ Step 5 completo → **BILLING CONFIGURATO** (test o live).

---

## 🔍 Troubleshooting

| Errore | Causa probabile | Fix |
|--------|----------------|-----|
| `503 "Supabase non configurato"` su /auth/* | `SUPABASE_URL` o `SUPABASE_SERVICE_KEY` mancanti in `.env` | Verifica con `python -c "from spesemed.api.config import settings; print(settings.supabase_url)"` |
| `401 "Invalid JWT"` su /jobs con Bearer valido | `SUPABASE_JWT_SECRET` sbagliato (corrisponde a un altro progetto) | Settings → API → copia JWT Secret aggiornato |
| `500 Internal Server Error` su /auth/logout | (raro) eccezione supabase-py non gestita | Controlla log uvicorn; il try/except best-effort dovrebbe loggare e ritornare 204 |
| `429 Too Many Requests` su /auth/login (5+ rapidi) | Rate limit anti-brute-force (slowapi, default 5/min) | Aspetta 1 minuto o cambia `RATE_LIMIT_LOGIN` in `.env` |
| `Connection refused` su Supabase | Rete / firewall | `curl https://<your-project>.supabase.co` per test connettività |
| `Migration SQL failed: relation already exists` | Hai gia' applicato la migration una volta | OK: skip o drop manuale `DROP TABLE jobs, extractions CASCADE;` (solo dev) |

---

## 🔐 Security checklist post-go-live

Dopo aver completato i 5 step, verifica in Supabase Dashboard e Stripe Dashboard:

- [ ] **Authentication → Providers**: solo `Email` (disabilita Google/GitHub se non usati)
- [ ] **Authentication → URL Configuration**:
  - Site URL: il tuo dominio produzione (es. `https://spesemed.it`)
  - Redirect URLs: lista dei callback auth (per SPA web)
- [ ] **Database → Replication**: la tabella `extractions` NON deve essere pubblicata (no realtime)
- [ ] **Storage → receipts → Policies**: vuoto (nessuna policy = solo service_role può leggere/scrivere)
- [ ] **Settings → API → Service Role Key**: ruotala periodicamente (90 giorni)
- [ ] **Settings → Billing → Spend Cap**: imposta un cap su OpenRouter per evitare bill shock
- [ ] **Stripe → API keys**: la secret key è solo in `.env`/vault, mai in git o log
- [ ] **Stripe → Webhooks**: endpoint HTTPS, signing secret ruotabile, evento minimo `checkout.session.completed`
- [ ] **Stripe → Tax/fiscal settings**: configurazione fiscale decisa dal proprietario/commercialista
- [ ] **Redis**: se `API_WORKERS > 1`, `RATE_LIMIT_STORAGE_BACKEND=redis` + `REDIS_URL` e readiness verde al boot

---

## 🚀 Prossimi step (Fase 4 backlog)

Dopo il go-live, le evoluzioni naturali sono:

1. **Gating quota/402 + UI Profilo/piano** (4C-C7/C9): bloccare `/extract` senza quota e mostrare lo stato piano nel frontend
2. **UI Streamlit** legacy (drag & drop + tabella editabile) — non più necessaria con la SPA web
3. **OpenAPI SDK client** auto-generato per il frontend
4. **CI/CD GitHub Actions** completo (deploy automatico dopo migration merge)
5. **Sentry + Prometheus** monitoring (settings pronti: `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`)

---

## 📊 Observability stack (Prometheus + alerting)

### Metriche esposte
- **Endpoint**: `GET /metrics` (formato Prometheus exposition v0.0.4)
- **Auth**: NESSUNA (no JWT) — per design: se Supabase ruota la chiave JWKS
  e blocca l'auth, Prometheus DEVE poter scrapare le metriche che
  segnalano il problema. Protezione demandata a NetworkPolicy/reverse proxy.
- **Metriche custom SPESEMED**:
  - `spesemed_jwt_failures_total{reason="..."}` — Counter fallimenti auth per
    categoria (~11 valori: `header_malformed`, `alg_unsupported`,
    `config_missing`, `jwks_lookup_failed`, `hs256_invalid_signature`,
    `jwks_invalid_signature`, `expired`, `issuer_mismatch`,
    `role_unauthorized`, `missing_required_claim`, `general_decode_error`).
  - `spesemed_jwt_decode_duration_seconds` — Histogram latenza decode JWT.
  - `spesemed_jwt_jwks_cache_resets_total` — Counter reset manuali cache JWKS.
  - `spesemed_http_requests_total{method,status_class}` — Counter richieste HTTP
    (cardinalità bassa: nessun path/utente, `/metrics` escluso).
  - `spesemed_http_request_duration_seconds` — Histogram latenza richieste HTTP.

### Disabilitazione (solo dietro proxy con auth custom)
```bash
PROMETHEUS_METRICS_ENABLED=false   # /metrics ritorna 404
```

### Admin endpoint: reset cache JWKS (remediation key rotation)
Per forzare re-fetch JWKS Supabase quando le chiavi sono ruotate ma la
cache locale ha ancora il vecchio set:
```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
     https://<api>/admin/auth/reset-jwks-cache
# Risposta 200: {"status":"ok","action":"reset_jwks_cache","next_request_will_refetch":true}
# 403 se ADMIN_TOKEN vuoto o X-Admin-Token non matcha.
```
Genera `ADMIN_TOKEN` con: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### Alerting rules
File `docs/observability/alerts.yaml` con 5 regole pronte, inclusa
`SPESEMEDJWKSKeyRotationMissed` che detecta Supabase key rotation non
recepita dalla cache (vedi Runbook operativo sotto per remediation).

### Runbook operativo
Vedi `docs/observability/RUNBOOK.md` per le 5 playbook dettagliate:
trigger → diagnosi → remediation per ciascun alert.

---

_Documento generato per SPESEMED. Se un path Supabase UI è cambiato (succede 1-2 volte/anno),
controlla https://supabase.com/docs per il path aggiornato._

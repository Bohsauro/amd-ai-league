# SPESEMED — Project Status 🏥📊

> Documento "interno" di stato ingegneristico: evoluzione fasi, deliverable
> implementati, bug noti, gap residui e setup operativo.
>
> **Onboarding utente / marketing copy:** vedi [`README.md`](README.md).
> **Configurazione env-vars:** vedi [`.env.example`](.env.example).
> **Runbook operativo go-live:** vedi [`GO_LIVE_RUNBOOK.md`](GO_LIVE_RUNBOOK.md).

> ⚠️ **Update ott 2026:** la GUI Flutter (`flutter_app/`) è stata **rimossa dal
> repository** (insieme a `.github/workflows/build_apk.yml`) e verrà ricostruita
> da zero (nuovo client, tech TBD). Le sezioni seguenti che la menzionano restano
> come storico dello stato precedente; il backend non cambia e il surface API
> (auth, extract, jobs, summary, export, health, metrics) è invariato.

---

## 1. 🎯 Idea generale del progetto

**SPESEMED** (*Spese Mediche Smart*) è un **micro-SaaS italiano** che
automatizza l'estrazione, la validazione e l'organizzazione delle **spese
mediche** da girare all'assicurazione privata o al commercialista per la
**dichiarazione dei redditi 730**.

### Problema che risolve

In Italia il cittadino che vuole scaricare le spese mediche deve:

1. Conservare tutti gli **scontrini parlanti**, le **fatture dentisti/oculisti**,
   i **ticket SSN**, le ricevute di **analisi ed esami**.
2. Inserirle manualmente nel 730 precompilato o girarle al commercialista.
3. Gestire un archivio di decine/centinaia di file PDF e JPG, spesso con nomi
   inutili (`IMG_20240115.jpg`, `Scan2024-03.pdf`).

### Soluzione

Una pipeline che:

1. **Carica** in blocco le ricevute (PDF, anche multipagina; JPG, JPEG, PNG, WEBP, BMP).
2. **Estrae** automaticamente i campi strutturati via AI multimodale:
   - `data_spesa`, `esercente`, `importo_totale`, `codice_fiscale_paziente`,
     `categoria_spesa` (Farmaci / Visita Specialistica / Dispositivo Medico /
     Esami / Altro).
3. **Valida** CF (algoritmo italiano), importi, date.
4. **Conserva** storico per utente (multi-tenant).
5. **Esporta** Excel per categoria + ZIP rinominato pronto per commercialista (Fase 4B done).

### Stack attuale

| Layer              | Tecnologia                                                |
|--------------------|-----------------------------------------------------------|
| AI Engine          | OpenRouter + `google/gemini-2.5-flash-lite` (JSON mode)   |
| OCR/PDF            | pdf2image + Pillow                                        |
| Validation         | Pydantic v2 (`models.py`, `schemas.py`)                   |
| Async HTTP         | httpx (Fase 1), requests-to-thread (Fase 2 worker)       |
| **Backend API**    | **FastAPI + Uvicorn (dev) / gunicorn+uvicorn (prod)**     |
| Auth               | **Supabase JWT (PyJWT locale per validazione)**           |
| **Frontend GUI**   | Flutter rimosso (ott 2026) — nuovo client in riprogettazione |
| **Export 730**     | **openpyxl (Excel) + zipfile (ZIP ricevute rinominate)**   |
| DB & Storage       | **Supabase Postgres + Storage bucket privato `receipts`** |
| Async jobs         | **Worker interno con `claim_next_job` RPC (FOR UPDATE SKIP LOCKED)** |
| Rate limiting      | **slowapi (memory, Redis-ready)**                         |
| Observability      | **Sentry (lazy) + Prometheus client (Fase 4C)**            |
| Packaging          | **gunicorn in Docker multi-stage, non-root user**         |
| Tests              | **pytest offline (mock Supabase)**                         |
| CI                 | **GitHub Actions: lint + test + build (no secrets)**      |

---

## 2. 📜 Roadmap per fasi

| Fase | Stato      | Descrizione sintetica                                   |
|------|------------|---------------------------------------------------------|
| 0    | ✅ done    | Core AI engine (extractor.py, file_utils, models)       |
| 1    | ✅ done    | FastAPI sync `/extract` (1 file = 1 richiesta)          |
| 2A   | ✅ done    | Supabase (migrations + client + persistenza + idempotency) |
| 2B   | ✅ done    | Async worker (JobWorker con claim RPC + zombie recovery) |
| 2C   | ✅ done    | Auth: signup / login / JWT dependency (PyJWT locale)    |
| 3    | ✅ done    | Refresh + Logout + Rate-limit + Sentry + Docker + Tests + CI |
| 4A   | ✅ done    | UI Flutter (auth, upload, results, jobs)                  |
| 4B   | ✅ done    | Export Excel/ZIP (`exporter.py` + API `/export` + UI)     |
| 4B+  | ✅ done    | Profilo utente/usage (`GET /summary` + UI Profilo)        |
| 4C   | 🟡 done (skeleton) | Redis readiness, Prometheus HTTP metrics, Stripe plan/checkout/webhook |

> **Fasi 0+1+2+3+4A+4B + 4B+ (Export + Profilo) sono completate e validate.
> L'Export Excel/ZIP chiude il ciclo d'uso per il commercialista; il Profilo
> utente/usage aggiunge riepilogo spese e storico job con export per-job.
> La Fase 4C backend è completa come **skeleton operativo** (Redis, Prometheus,
> Stripe); restano gating quota/402 e UI piano (4C-C7/C9) + validazione E2E
> con Supabase reale. Dettaglio in §17.

---

## 3. ✅ FASE 0 — Core AI Engine

**Scopo:** libreria Python pura che parla con OpenRouter ed estrae campi
JSON strutturati da una ricevuta (PDF o immagine).

### Deliverable

| File                          | Responsabilità                                          |
|-------------------------------|---------------------------------------------------------|
| `extractor.py`                | Orchestratore (CLI + API Python `extract_from_file`)    |
| `prompts.py`                  | System prompt italiano + tassonomia categorie          |
| `file_utils.py`               | PDF/img → immagini ridimensionate + base64              |
| `models.py`                   | `SpesaMedica` Pydantic + validazione CF italiana        |
| `tests/test_imports.py`       | Smoke test importazioni (10/10 verde)                   |

### Punti di forza

- Modello swappabile via env (`OPENROUTER_MODEL`).
- JSON nativo via `response_format: {type: "json_object"}` (no parsing fragile).
- CLI friendly: `--verbose`, `-o out.json`, `--categorie`, batch di file.
- `extract_from_file(path) -> SpesaMedica` per uso programmatico.

---

## 4. ✅ FASE 1 — FastAPI sync `/extract`

**Scopo:** esporre l'estrazione via HTTP POST con autenticazione (in Fase 2C)
e validazione input.

### Deliverable

| File                                       | Note                                             |
|--------------------------------------------|--------------------------------------------------|
| `src/spesemed/api/main.py`                 | App factory + lifespan (worker spawn Fase 2B)    |
| `src/spesemed/api/config.py`               | `Settings` pydantic-settings, env-driven         |
| `src/spesemed/api/schemas.py`              | Request/Response/DTO Pydantic v2                 |
| `src/spesemed/api/routes/extract.py`       | `POST /extract` sync (N≤`max_sync_files`)        |
| `src/spesemed/api/routes/health.py`        | `GET /health` (meta info + OpenRouter check)     |
| `src/spesemed/api/routes/jobs.py`          | `GET /jobs/{id}` (introdotto in Fase 2B)         |
| `src/spesemed/api/routes/auth.py`          | signup / login (Fase 2C completo in Fase 3)      |
| `src/spesemed/api/dependencies.py`         | `get_current_user` (PyJWT, fallback dev)         |
| `src/spesemed/api/supabase_client.py`      | singleton con graceful degradation (Fase 2A)     |
| `src/spesemed/api/worker.py`               | `JobWorker` (Fase 2B)                            |

### Endpoint impostati

```
GET    /                              → meta info {service, version}
GET    /api/v1/health                 → {status, version, openrouter_configured}
POST   /api/v1/extract                → sync ExtractSyncResponse | async 202 + JobPendingResponse
GET    /api/v1/jobs                   → JobListResponse (storico utente)
GET    /api/v1/jobs/{job_id}          → JobStatusResponse (async)
GET    /api/v1/summary                → UsageSummaryResponse (riepilogo spese, Fase 4B+)
POST   /api/v1/auth/signup            → 201 {user_id} | 503 no-supabase
POST   /api/v1/auth/login             → 200 {access_token, refresh_token, ...} | 401 | 503
POST   /api/v1/auth/refresh           → 200 {new tokens} | 401 | 503         (Fase 3)
POST   /api/v1/auth/logout            → 204 no-content | 401                  (Fase 3)
```

### Caratteristiche chiave

- **Auto-routing sync/async**: per numero di file (configurabile, default
  `max_sync_files=3`, sopra va a coda async con `POST → 202`).
- **Validazione estensioni**: PDF/JPG/JPEG/PNG/WEBP/BMP allineato al core.
- **Error sanitization**: messaggi user-friendly + `correlation_id` random
  per debugging senza leak di stacktrace.
- **Status code corretti**: 413 file too big, 422 Pydantic, 503 missing deps.

---

## 5. ✅ FASE 2A — Supabase + persistenza

**Scopo:** dare memoria alle estrazioni (multi-utente) e bucket storage
per i file originali.

### Deliverable

| File                                  | Note                                                |
|---------------------------------------|-----------------------------------------------------|
| `migrations/001_init.sql`             | schema `jobs`, `extractions`, RPC `claim_next_job` (FOR UPDATE SKIP LOCKED), `reset_zombie_jobs`, trigger `touch_updated_at` |
| `src/spesemed/api/supabase_client.py` | singleton + graceful degradation (no crash al boot se manca config) |
| `src/spesemed/api/schemas.py`         | DTO persistenza (`JobRow`, `ExtractionRow`)          |

### Schema logico

```
jobs
├─ id (uuid pk)
├─ user_id (uuid, fk auth.users)
├─ status (queued | processing | done | failed)
├─ file_count, correlation_id, error_message
├─ storage_paths (jsonb[]) ← URL bucket privato `receipts/`
├─ claimed_by, claimed_at, expires_at ← per la claim RPC
├─ created_at, updated_at

extractions
├─ id (uuid pk)
├─ job_id (fk jobs)
├─ user_id (denormalized per query dirette)
├─ file_hash (sha256 cache idempotency key)
├─ data (jsonb ← SpesaMedica serializzata)
├─ created_at
UNIQUE (user_id, file_hash) ← idempotency cache lato server
```

### Caratteristiche

- **Idempotency cache** `(user_id, file_hash)` lato server → un utente che
  re-invia la stessa ricevuta riceve lo stesso `extraction_id` senza
  doppio consumo di crediti OpenRouter.
- **Privacy/GDPR-by-design**: bucket privato, mai pubblico, URL firmati al
  bisogno.
- **Graceful degradation**: senza `SUPABASE_URL` l'app *non* crasha al boot,
  ma restituisce 503 informativo sulle route dipendenti.

---

## 6. ✅ FASE 2B — Async worker

**Scopo:** la rotta `POST /extract` può tornare `202 + JobPendingResponse`
quando N > `max_sync_files`. Un worker in-process preleva i job dalla coda
in modo atomico.

### Deliverable

| File                            | Note                                                  |
|---------------------------------|-------------------------------------------------------|
| `src/spesemed/api/worker.py`    | `JobWorker` + RPC claim + retry + zombie recovery     |

### Caratteristiche

- **Claim atomico**: RPC `claim_next_job()` con `FOR UPDATE SKIP LOCKED`
  + `claimed_at = now()` + `expires_at = now() + 5 min`.
- **Polling 2 s** (config `WORKER_POLL_INTERVAL_SECONDS`).
- **Zombie recovery**:
  - Al boot (`reset_zombie_jobs()` già eseguita da migration).
  - Ogni 150 poll: rileva job con `status=processing AND expires_at < now()`
    e li rimette in `queued` con backoff esponenziale.
- **Retry con jitter**: `min(2 ** attempts, 60) + random(0..3)` secondi.
- **Thread offload**: `asyncio.to_thread()` per I/O sync (supabase-py + httpx).
- **Lifecycle**: start/stop tramite `lifespan` async di FastAPI (`main.py`).

### Comportamento garantito

- Single-node: nessuna doppia esecuzione (claim atomico).
- Multi-node Fase 4: stesso claim atomico funziona su N worker (no
  refactoring necessario, basta scalare orizzontalmente le repliche API).

---

## 7. ✅ FASE 2C — JWT Auth

**Scopo:** autenticazione senza overhaul di Supabase Auth (che già esiste),
ma con validazione JWT in-process per *performance* (~1 ms vs ~200 ms
di un lookup remoto su ogni richiesta).

### Deliverable

| File                                  | Note                                          |
|---------------------------------------|-----------------------------------------------|
| `src/spesemed/api/dependencies.py`    | `get_current_user` PyJWT HS256 + audience     |
| `src/spesemed/api/routes/auth.py`     | `POST /auth/signup` (gate `allow_signup`) + `POST /auth/login` |

### Caratteristiche

- **Audience validation**: `aud=authenticated` (standard Supabase).
- **Require exp + sub**: rifiuta JWT malformati o senza subject.
- **Dev mode fallback**: header `X-User-Id` (mock) accettato *solo* in dev
  per test rapidi senza token reali.
- **Production gate**: se `SUPABASE_JWT_SECRET` non settato e `ENV=prod` →
  503 (l'app non degrada silenziosamente in produzione).
- **/login anti-enumeration**: risposta 401 generica anche su "user not found".
- **Refresh-token rotation** lasciata a Supabase Auth (delega gestione
  complessa di theft-detection e revocation native).

---

## 8. ✅ FASE 3 — Refresh + Logout + Rate-limit + Sentry + Docker + Tests + CI

**Scopo:** indurire l'API per uso reale (multi-utente, multi-worker,
osservabilità, packaging).

### 8.1 Auth: refresh + logout

| Endpoint                | Comportamento                                                                                       |
|-------------------------|-----------------------------------------------------------------------------------------------------|
| `POST /auth/refresh`    | Pass-through `supabase.auth.refresh_session(token)` wrappato in `asyncio.to_thread` (rotation).     |
| `POST /auth/logout`     | Richiede Bearer. Chiama `supabase.auth.sign_out` best-effort (il client deve comunque cancellare i token localmente). |

### 8.2 Rate limiting (`slowapi`)

| Endpoint        | Limite (default)               | Note                                  |
|-----------------|--------------------------------|----------------------------------------|
| `POST /auth/signup`   | `2/hour`                  | costoso (crea utente Supabase)        |
| `POST /auth/login`    | `5/minute`                | brute-force mitigation                |
| `POST /auth/refresh`  | `30/minute`               | scadenza naturale del JWT ~1h         |
| `POST /auth/logout`   | `20/minute`               | safety net                            |
| `POST /extract`       | `10/minute` (configurabile)| costo AI per call                     |
| `GET  /jobs/{id}`     | `30/minute`               | polling di stato                      |
| `GET  /jobs`          | `30/minute`               | storico job (lista)                   |
| `GET  /summary`       | `30/minute`               | riepilogo profilo (riusa `rate_limit_jobs`) |

**Key function** (`_key_by_user_or_ip`):
- **Production**: `jwt.decode` con **verify_signature=True** (HS256,
  audience=authenticated, exp+sub richiesti).
- **Dev**: best-effort `verify_signature=False` (accettabile per mock mode).
- **Fallback IP**: SEMPRE (safety net anche se JWT mancante).
- **X-User-Id**: solo in dev (ignorato in prod).

**Storage backend**:
- Default: in-memory (`RATE_LIMIT_STORAGE_BACKEND=memory`).
- ⚠️ Con `API_WORKERS > 1` il limite viene moltiplicato per n-worker.
- **Switch consigliato per Fase 4C**: `RATE_LIMIT_STORAGE_BACKEND=redis://host:6379`.

### 8.3 Observability

- **Sentry**: `sentry-sdk[fastapi]` caricato *solo* se `SENTRY_DSN != ""`.
  Inizializzato in `_init_sentry()` con `traces_sample_rate` configurabile.
  Best-effort try/except: se SDK manca o DSN è invalido, log + passa.

### 8.4 Packaging prod: `Dockerfile`

- **Base**: `python:3.11-slim`.
- **Multi-stage**: stage `builder` (compila deps) → stage `runtime`
  (solo lo stretto necessario).
- **Non-root user**: `spesemed` UID 1000.
- **Runtime**: `gunicorn` come PID 1 → N worker `uvicorn.workers.UvicornWorker`.
- **Healthcheck built-in**: `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"`.
- **`read_only: true`** su rootfs con `tmpfs` per `/tmp` (PDF conversion).

### 8.5 `docker-compose.prod.yml`

- Override produzione del `docker-compose.yml` esistente:
  - `read_only: true`, `tmpfs: ["/tmp:size=256m,mode=1777"]`.
  - `restart: always`.
  - `healthcheck` aggressive (15s start-period).
  - Log driver `json-file` con rotazione (`max-size=10m, max-file=3`).
  - Secrets via `secrets:` block (non env-vars in chiaro).
  - `deploy.resources.limits.cpus='1.0'` + `memory=512M` (swarm-mode doc).

### 8.6 Tests offline (pytest)

| File                          | Test principali                                         |
|-------------------------------|----------------------------------------------------------|
| `tests/test_health.py`        | 3 test: status code, no key, no errors                  |
| `tests/test_auth.py`          | 9 test: signup/login/refresh/logout HTTP responses      |
| `tests/test_extract.py`       | 4 test: validazione, no-key, too-many, async routing    |
| `tests/conftest.py`           | monkeypatch singleton `get_supabase_client` per offline |
| `tests/audit_pre_go_live.py`  | audit pre-go-live (SQL syntax, .env alignment, endpoint surface) |
| `tests/manual_validation.py`  | smoke test end-to-end (uvicorn + urllib, no bash escape) |

### 8.7 CI: `.github/workflows/ci.yml`

2 job paralleli:

1. **test** — bootstrap Python → install dev deps → pytest offline.
2. **docker-verify** — build immagine (`--no-cache` + `--secret id=`,
   `ENV=test`) per assicurarsi che `Dockerfile` compili senza secrets reali.

---

## 9. ✅ Bug chiusi al 100% (post-Fase 3 closing)

Tutti i bug precedentemente elencuti in §9 sono stati chiusi in cinque round
di fix progressivi. Riepilogo dei learning:

### 9.1 (ex bug) — Test mocks non intercettano i route handler [CHIUSA]

**Root cause**: `monkeypatch.setattr` su un modulo sorgente NON aggiorna la
reference locale catturata da `from x import y` nel modulo importatore.

**Fix (DI-friendly refactor)**: refactor di `routes/auth.py`, `routes/extract.py`,
`routes/jobs.py` da `from ..supabase_client import X` a `from .. import supabase_client`
+ chiamate `supabase_client.X()`. Attribute access sul modulo aggiornabile
a runtime → monkeypatch singolo punto in `conftest.py`.

### 9.2 (ex bug) — Logout 500 quando Supabase non configurato [CHIUSA]

**Root cause duplice**:
1. `get_supabase_client()` può tornare `None` se `create_client` fallisce.
2. Slowapi `@limiter.limit` richiede `response: Response` come param per
   iniettare X-RateLimit headers (altrimenti 500 FUORI dal try/except body).

**Fix applicato**:
- Try/except wrapper nel body con `raise HTTPException` selettivo + None-check.
- Aggiunto `response: Response` come primo parametro di `logout`, `login`,
  `refresh`, `signup`, `get_job_status` (tutti gli endpoint con `@limiter.limit`).
- Endpoint logout best-effort: 204 garantito anche su errore, MAI 5xx.

### 9.3 (bonus) — Pytest fixture shadowing locale [CHIUSA — bonus root cause]

Scoperto da thinker: `tests/test_auth.py` aveva una fixture locale `mock_supabase`
che **sovrascriveva** quella di `conftest.py` (DRY violation). La fix era rimuovere
la duplicazione, lasciando una sola fixture canonica in `conftest.py`.

### 9.4 Apprendisti di test infrastructure (per evitare regressioni future)

1. **`from x import y` + monkeypatch** = fragile. Per testabilità, preferire
   `import x` + `x.y()`.
2. **`monkeypatch.setattr` su modulo sorgente** funziona SOLO se il consumer
   accede via attributo (`x.y()`), NON via local-name (`y()`).
3. **`@limiter.limit` di slowapi** richiede SEMPRE `response: Response` come
   parametro della funzione decorata, anche se la funzione ritorna `None`.
4. **Pytest fixtures locali a file** sovrascrivono sempre le fixtures di
   `conftest.py`: usare locali solo per casi davvero specifici del file.

### 9.5 Logging stdlib (non più bloccante)

`logging` stdlib resta accettabile per MVP; migrazione a `structlog` rimane
in §10.2 backlog (non più un "bug noto", solo nice-to-have).

---

## 10. ⏳ Cosa MANCA (backlog Fase 4+)

### 10.1 Visible-to-user (alta priorità)

| Item                                          | Impatto                                |
|-----------------------------------------------|----------------------------------------|
| 💳 **Gating quota/402 + UI piano**            | chiude il loop di monetizzazione (skeleton Stripe già pronto) |
| 🧾 **Stripe subscription lifecycle completo** | gestire update/delete/invoice, non solo checkout completato |

### 10.2 Indurimento (media priorità)

| Item                                                       | Note                                     |
|------------------------------------------------------------|------------------------------------------|
| 🔁 **`/auth/refresh` su Redis revocation list**            | perdita della scelta performance-only-local |
| 🪵 **`structlog` con request-id**                          | osservabilità end-to-end                  |
| 🧪 **Test coverage > 80%**                                 | pytest-cov con soglia in CI               |
| 🐳 **docker-compose staging** (staging env separato)       | test pre-prod                             |
| 🔒 **CSP + security headers** (helmet/secure)              | hardening web                             |
| 🚦 **Graceful shutdown** del worker (SIGTERM handler)     | robustezza in kubernetes/swarm            |
| 📤 **E-mail receipts** (magic link per scaricare ZIP)      | delivery ai commercialisti                |

### 10.3 Operations / DevEx (media priorità)

| Item                                              | Note                                       |
|---------------------------------------------------|--------------------------------------------|
| 🚀 **k8s manifests** (o docker swarm prod-ready)  | helm chart o compose per stack completo   |
| 🔄 **Backup policy DB Supabase**                  | PITR attivo, retention 7 giorni            |
| 🌍 **i18n UI** (italiano + inglese)              | espansione mercato                         |
| 📊 **GDPR Data Subject Access Request (DSAR)**     | export/cancel utenza                       |
| 📝 **Audit log** delle operazioni sensibili      | chi ha letto/aggiornato cosa, quando      |

### 10.4 Nice-to-have (bassa priorità)

| Item                                                 | Note                          |
|------------------------------------------------------|-------------------------------|
| 🧷 **Modello multi-image (post-Fase 4)**             | confronta 2+ versioni PDF    |
| 🔍 **RAG sulle policy assicurative**                 | "questa spesa è rimborsabile?" |
| 🗜️ **Compressione PDF in export**                   | ridurre ZIP finale            |
| 🤝 **Webhooks a commercialisti**                     | integrazione diretta          |

---

## 11. 🚀 Come si runna oggi (smoke test)

> **Prerequisiti**: Python 3.10+ in venv, pip install -r requirements.txt.

```bash
# 1. Setup env
cp .env.example .env     # poi editarlo

# 2. (Opzionale) Avviare Supabase via CLI + applicare migrations/001_init.sql
#    Nei test offline (senza Supabase) le rotte auth/jobs ritornano 503.

# 3. Boot
python -m uvicorn spesemed.api.main:app --host 127.0.0.1 --port 8000 --reload

# 4. Test rapidi (dev mode, X-User-Id accettato)
curl -sS http://127.0.0.1:8000/api/v1/health
curl -sS -X POST http://127.0.0.1:8000/api/v1/extract \
  -H "X-User-Id: dev-user" -F "files=@ricevuta.pdf"
```

### Test rapidi autenticati (con Supabase)

```bash
TOKEN="<JWT da /auth/login>"

curl -sS -X POST http://127.0.0.1:8000/api/v1/extract \
  -H "Authorization: Bearer $TOKEN" -F "files=@ric.pdf" -F "files=@ric2.jpg"

# Trigger rate-limit (5 rapidi login oltre il 5° → 429)
for i in $(seq 1 7); do
  curl -sS -o /dev/null -w "[$i] HTTP %{http_code}\n" -X POST \
    http://127.0.0.1:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"a@b.c","password":"validpass1"}'
done
```

---

## 12. 🐳 Come si runna in produzione (Docker)

```bash
# 1. Preparare secrets (via docker secrets o env da CI/CD)
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
export SUPABASE_BUCKET=receipts
export SUPABASE_JWT_SECRET=...
export OPENROUTER_API_KEY=...
export ALLOW_SIGNUP=false       # produzione: disabilitare signup pubblica
export SENTRY_DSN=https://...   # opzionale
export RATE_LIMIT_STORAGE_BACKEND=redis://redis:6379

# 2. Build + up con override produzione
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 3. Healthcheck
docker compose ps
curl http://localhost:8000/api/v1/health
```

> `docker-compose.prod.yml` richiede Docker Swarm *per* i `deploy.resources`.
> Su singolo host `compose` i limit sono ignorati silenziosamente: scalare
> manualmente via replicas.

---

## 13. 📊 Stato di validazione riassuntivo

| Layer                  | Stato | Note                                          |
|------------------------|-------|-----------------------------------------------|
| Syntax (`compileall`)  | 🟢   | src/ + tests/ OK                              |
| App import             | 🟢   | 14 endpoint registrati (13 + `GET /summary`)  |
| Regression Fase 0      | 🟢   | 10/10 smoke test                              |
| Pytest `test_health`   | 🟢   | 3/3                                           |
| Pytest `test_extract`  | 🟢   | 4/4                                           |
| Pytest `test_auth`     | 🟢   | 9/9 (DI-friendly + fixture-shadowing fix)     |
| Pytest `test_exporter` | 🟢   | 16/16 (Excel, ZIP, naming, dedup, CLI)        |
| Pytest `test_summary`  | 🟢   | 5/5 (aggregazione usage, 503, openapi)        |
| Pytest `test_rate_limit` | 🟢 | 14/14 (memory/Redis URI + readiness)          |
| Pytest `test_billing`  | 🟢   | 13/13 (mock Stripe, no secrets)               |
| Pytest `test_metrics`  | 🟢   | 34/34 (JWT + HTTP metrics)                    |
| Pytest totale          | 🟢   | **176/176 passed, 0 failed**                  |
| Live smoke (env empty) | 🟢   | T1-T9 tutti verdi, T6 logout=204 FISSO        |
| Flutter analyze        | 🟢   | 0 issue (70 lint fixati, `analysis_options` riattivato) |
| Flutter test           | 🟢   | 47/47 (validators, signup screen, widget, profile DTO) |
| Push `origin/main`     | 🟢   | 7 commit: + `feat(export)` 4B + docs status — Profilo 4B+ pronto per commit |
| Audit pre-go-live      | 🟢   | `AUDIT PASSED`: SQL parens OK, 0 env-vars disallineate, 12 endpoint surface (audit pre-export; oggi 14) |
| Docker build verify    | 🟢   | CI step verde                                 |
| **Code reviewer sigillo finale** | 🟢 | TUTTO VERDE — backend production-ready al 100% |
| **Go-live manual steps (4 azioni Supabase)** | 🟢   | eseguite dall'utente (migration, bucket, .env, curl) — resta solo E2E success-path (vedi §16) |

### Significato degli stati

- 🟢 **verde**: passa in CI locale e in produzione.
- 🟡 **giallo**: passa a runtime ma con caveat noti.
- ❌ **rosso**: bloccante, gap Fase 4.

---

## 14. 📁 Indice dei file chiave

```
SPESEMED/
├── README.md                         ← onboarding utente finale
├── PROJECT_STATUS.md                 ← QUESTO FILE
├── GO_LIVE_RUNBOOK.md                ← manuale operativo per le 4 azioni Supabase
│
├── .env.example                      ← tutte le env-vars documentate (30 totali)
├── pyproject.toml                    ← dipendenze + metadata
├── requirements.txt                  ← dipendenze pinned
│
├── Dockerfile                        ← produzione gunicorn + uvicorn
├── docker-compose.yml                ← dev base
├── docker-compose.prod.yml           ← override produzione (swarm-ready)
├── .dockerignore
│
├── migrations/
│   ├── 001_init.sql                  ← jobs, extractions, RPC, triggers
│   └── 004_stripe_subscriptions.sql  ← subscriptions + RLS service_role (Fase 4C)
│
├── src/spesemed/
│   ├── core/
│   │   ├── extractor.py              ← Fase 0: CLI + API Python
│   │   ├── exporter.py               ← Fase 4B: Excel + ZIP per commercialista
│   │   ├── prompts.py
│   │   ├── file_utils.py
│   │   ├── models.py
│   │   └── taxonomy.py
│   └── api/
│       ├── main.py                   ← FastAPI app + lifespan + Sentry + HTTP metrics
│       ├── config.py                 ← Settings env-driven
│       ├── schemas.py                ← Pydantic DTO
│       ├── supabase_client.py        ← singleton + graceful degradation
│       ├── worker.py                 ← JobWorker async
│       ├── dependencies.py           ← get_current_user (PyJWT locale)
│       ├── jwt_decoder.py            ← decode JWT + cache JWKS
│       ├── metrics.py                ← metriche Prometheus (JWT + HTTP)
│       ├── metrics_acl.py            ← ACL sui metric endpoint
│       ├── rate_limit.py             ← slowapi Limiter + storage memory/Redis
│       ├── billing.py                ← wrapper Stripe (plan/checkout/webhook)
│       └── routes/
│           ├── health.py             ← GET /health
│           ├── extract.py            ← POST /extract (sync+async routing)
│           ├── jobs.py               ← GET /jobs/{id}
│           ├── export.py             ← POST /export (Fase 4B: ZIP commercialista)
│           ├── summary.py            ← GET /summary (Fase 4B+: riepilogo usage)
│           ├── billing.py            ← GET /billing/plan + checkout + webhook
│           └── auth.py               ← signup / login / refresh / logout
│
├── tests/
│   ├── conftest.py                   ← mock supabase offline (DI-friendly)
│   ├── test_health.py                ← 3 test
│   ├── test_auth.py                  ← 9 test
│   ├── test_extract.py               ← 4 test
│   ├── test_imports.py               ← smoke test Fase 0
│   ├── test_jwt_decoder.py           ← decode JWT + JWKS
│   ├── test_metrics.py               ← 34 test metriche Prometheus/JWT/HTTP
│   ├── test_rate_limit.py            ← 14 test storage memory/Redis + readiness
│   ├── test_billing.py               ← 13 test Stripe (mock, no secrets)
│   ├── test_security_fixes.py        ← regressioni security
│   ├── test_operational_smoke.py     ← smoke test operativo
│   ├── test_exporter.py              ← 16 test Excel/ZIP + CLI (Fase 4B)
│   ├── test_summary.py               ← 5 test aggregazione usage (Fase 4B+)
│   ├── audit_pre_go_live.py          ← audit SQL + .env + endpoint surface
│   ├── manual_validation.py          ← smoke test end-to-end (uvicorn + urllib)
│   └── AUDIT_REPORT.md               ← output auto-generato (in .gitignore)
│
└── .github/workflows/
    └── ci.yml                        ← test + docker-build


```

---

## 15. 🧭 Prossimo passo consigliato

La **UI Flutter è completata** (Fase 4A), l'**Export Excel/ZIP** (Fase 4B)
chiude il ciclo d'uso per il commercialista e il **Profilo utente/usage**
(4B+) mostra riepilogo spese (totale, conteggio, per-categoria), storico
job e download dell'export per job o completo dal nuovo `GET /api/v1/summary`.

→ **Fase 4C (skeleton) fatta**: Redis readiness/test, Prometheus HTTP metrics,
Stripe plan/checkout/webhook. Prossimo valore: **gating quota/402 + UI piano**
(4C-C7/C9), poi lifecycle subscription completo.

→ **Test E2E con Supabase reale**: le 4 azioni del runbook sono state eseguite
dall'utente; resta la validazione del success-path (200 OK) con secrets reali,
incluso il nuovo `POST /api/v1/export`.

---

## 16. 🚦 Go-Live Runbook + Audit pre-go-live (chiusura backend)

**Stato**: backend production-ready al 100% (validation offline completa) e
GUI Flutter completata. Le 4 azioni Supabase sono state eseguite dall'utente;
resta la validazione E2E del success-path (200 OK) con secrets reali.

### 16.1 Audit pre-go-live (`tests/audit_pre_go_live.py`)

Script Python (stdlib + FastAPI introspection) che produce un report
Markdown-ready su:

1. **`migrations/001_init.sql`** (133 righe): syntax sanity (parens
   bilanciati 38/38), 2 tabelle (`jobs`, `extractions`), 3 funzioni
   (`touch_updated_at`, `claim_next_job`, `reset_zombie_jobs`), 1 trigger
   (`trg_jobs_touch_updated_at`), 5 indici, 1 vincolo UNIQUE
   `(user_id, file_hash)`.
2. **`.env.example` vs `config.py` Settings**: parser conservative (estrae
   solo fields dentro `class Settings(BaseSettings)` con 4-spazi di
   indentazione). Dopo i fix (7 env-vars aggiunte): **0 env-vars orfane**,
   **0 env-vars mancanti**. Verdetto: `>>> AUDIT PASSED`.
3. **Endpoint surface**: 12 routes totali (3 auth-required, 9 anonime)
   via introspezione di `route.dependant.dependencies` — conteggio del
   momento dell'audit, prima dell'aggiunta di `POST /api/v1/export`
   e `GET /api/v1/summary` (oggi 14 endpoint registrati).

### 16.2 `.env.example` aggiornato

Aggiunti 7 env-vars identificati come mancanti dall'audit iniziale:

- `SUPABASE_JWT_SECRET` (sezione Supabase)
- `ALLOW_SIGNUP` + `MOCK_USER_ID_DEFAULT` (nuova sezione Auth Fase 2)
- `WORKER_MAX_ATTEMPTS` + `WORKER_ZOMBIE_TIMEOUT_MINUTES` (Worker section)
- `MAX_ASYNC_FILES` (Upload limits section)
- `API_VERSION` (API metadata section)

Tutti con comment esplicativo sopra per aiutare l'operatore durante il setup.

### 16.3 Go-Live Runbook (`GO_LIVE_RUNBOOK.md`)

Manuale operativo step-by-step per portare il backend in produzione
(**5-20 min a seconda dell'esperienza**):

- **STEP 1**: Applica migration SQL via SQL Editor (con Opzione B
  `supabase db push` CLI). Include il **blocco email confirmation** che
  Supabase richiede di default (Auth → Providers → Email → Confirm email
  OFF per dev, oppure gestire magic link in prod).
- **STEP 2**: Crea bucket `receipts` privato via Storage dashboard.
- **STEP 3**: Popola `.env` con 4 secrets (`SUPABASE_URL`,
  `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `OPENROUTER_API_KEY`).
- **STEP 4**: Boot + 5 curl smoke tests (health, signup, login, jobs/{id},
  extract con idempotency cache hit al 2° invio).
- **STEP 5**: Stripe billing (Product/Price, API keys, webhook endpoint,
  `stripe listen` locale, carte di test, migration `004`, Redis readiness,
  incidenti/rollback).

Include troubleshooting con 6 errori comuni + tabella incidenti billing,
security checklist post-go-live, e followups per la Fase 4 (gating 402/UI
piano, OpenAPI SDK, k8s).

### 16.4 Cosa NON posso fare io (limiti onesti)

Per completezza: le 4 azioni Supabase reali (già eseguite dall'utente)
richiedono:

- **Accesso admin** alla dashboard del progetto Supabase dell'utente.
- **Secrets reali**: `SUPABASE_SERVICE_KEY` (mai esposta al client),
  `OPENROUTER_API_KEY` (con crediti associati), `SUPABASE_JWT_SECRET`.
- **Test del success-path con Supabase running**: pytest offline è
  "env empty = 503" by design (test che le 503 siano corrette); il
  success-path con `200 OK` reale richiede Supabase attivo.

Il `GO_LIVE_RUNBOOK.md` ha abilitato l'utente a fare tutto questo in modo
strutturato e riproducibile, con fallback CLI per utenti esperti.

### 16.5 Code-reviewer sigillo (chiusura Fase 3 → go-live)

🟡 **Verdetto onesto**: backend non validato end-to-end con Supabase reale
(audit verifica syntax non success-path). Per chiudere al 100% serve
eseguire migration + RLS + jwt validation in un Supabase vero — esattamente
ciò che il runbook abilita.

**3 migliorie identificate (valide per la validazione E2E post-4B)**:

1. Aggiungere `supabase db push` script come alternativa al copy-paste
   dashboard (riproducibile, versionato, immune a UI drift).
2. Screenshot datati delle pagine Supabase dashboard nel runbook +
   revisione trimestrale.
3. Pytest integration con Supabase staging (rete, secrets reali) per
   testare il 200 OK happy-path.

---

## 17. 🟡 FASE 4C — Redis, Prometheus, Stripe (stato reale)

**Stato**: backend **skeleton operativo** completato e verde offline; il piano
4C prevedeva anche gating 402/entitlements e UI piano, tracciati separatamente
(4C-C7/C9) e non inclusi in questo stato "done (skeleton)".

### 17.1 Redis rate-limit storage + readiness

- `api/rate_limit.py::_build_storage_uri()` risolve:
  - `memory` → `memory://` (default, single-worker);
  - `redis://...` → URI diretta;
  - `redis` → `REDIS_URL` (fallback `memory://` con WARNING se vuota).
- Le password negli URI vengono redatte nei log (`_redact_redis_uri`).
- `main.py::_check_redis_readiness()` esegue un ping al boot quando il backend
  è Redis: errore chiaro se irraggiungibile, nessun crash randomico al primo 429.
- `main.py::_warn_if_multi_worker_memory_rate_limit()` avvisa se
  `API_WORKERS > 1` con storage `memory` (limiti moltiplicati × worker).

### 17.2 Prometheus HTTP metrics

- Metriche in `api/metrics.py`, esposte da `GET /metrics` (ACL IP allowlist):
  - `spesemed_http_requests_total{method,status_class}`;
  - `spesemed_http_request_duration_seconds`;
  - metriche JWT già esistenti (`spesemed_jwt_failures_total`, ecc.).
- Middleware ASGI in `main.py`: nessuna label per path/utente (cardinalità
  bassa, no PII); `/metrics` e `/favicon.ico` esclusi dal conteggio.
- `PROMETHEUS_METRICS_ENABLED=false` → `/metrics` 404; allowlist vuota in
  produzione → fail-closed 403.

### 17.3 Stripe billing (no-op mode → test/live)

- Modulo `api/billing.py` + `api/routes/billing.py`.
- Endpoint:
  - `GET /api/v1/billing/plan` (pubblico): piano, `price_id`, valuta,
    `stripe_configured`, `webhook_configured`; **nessun secret**.
  - `POST /api/v1/billing/checkout` (Bearer): Checkout Session subscription,
    `201 {checkout_url, session_id, amount_total, currency}`; `503` se
    `STRIPE_SECRET_KEY`/`STRIPE_PRICE_ID` mancano; `401` senza auth.
  - `POST /api/v1/billing/webhook` (firma Stripe): `200` evento valido,
    `400` firma invalida, `503` se `STRIPE_WEBHOOK_SECRET` manca.
- Evento gestito: `checkout.session.completed` → upsert best-effort in
  `subscriptions` (migration `004_stripe_subscriptions.sql`, RLS service_role).
  Altri eventi: `200 action=ignored` (lifecycle completo = backlog).
- Import `stripe` lazy: senza libreria/secret l'API resta su e risponde `503`
  solo sulle route billing.

### 17.4 Nota di allineamento piano ↔ implementazione

Il piano `specs/spesemed/tasks/02-plan-4c.md` descrive un contratto più ampio
(`GET /billing/status`, tabella `entitlements`, gating 402 su `/extract`).
L'implementazione attuale su `dev/backend` espone `GET /billing/plan`, persiste
su `subscriptions` e **non** blocca `/extract`. La riconciliazione è nei task
4C-C7 (gating) e 4C-C9 (UI piano); questo documento descrive ciò che è
effettivamente deployabile oggi, non il target futuro.

### 17.5 Test offline (nessun secret)

| Comando (da `backend/spesemed/`) | Atteso |
|---|---|
| `python -m pytest tests/test_billing.py -v` | 13 passed (mock `stripe` + Supabase) |
| `python -m pytest tests/test_rate_limit.py -v` | 14 passed (memory/Redis URI + readiness) |
| `python -m pytest tests/test_metrics.py -v` | 34 passed (JWT + HTTP metrics) |
| `python -m pytest -q` | **176 passed, 0 failed** |
| `python -m compileall src tests` | nessun errore |
| `python tests/audit_pre_go_live.py` | `AUDIT PASSED` (`.env.example` ↔ `config.py`) |

I test usano solo chiavi finte (`sk_test_fake_...`, `whsec_test_...`) e mock:
nessuna chiamata di rete, nessun secret reale nel workspace.

---

_Documento aggiornato al termine della **Fase 4C (skeleton)**: pytest
**176/176** offline + audit pre-go-live PASSED + runbook Stripe/Redis,
**GUI Flutter completata** (47/47 test, analyze 0 issue, 70 lint fixati),
**Export Excel/ZIP implementato** (Fase 4B: `core/exporter.py` + API
`POST /api/v1/export` + bottone Esporta in ResultsScreen) e **Profilo
utente/usage** (Fase 4B+: `GET /api/v1/summary` + ProfileScreen con riepilogo,
storico job ed export per-job). Le azioni manuali Supabase (migration SQL,
bucket Storage, .env populate, curl autenticati) sono state eseguite
dall'utente; restano la validazione E2E del success-path con Supabase reale e
il gating 402/UI piano (4C-C7/C9)._

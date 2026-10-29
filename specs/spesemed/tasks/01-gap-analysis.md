# SPESEMED — Gap Analysis Fase 4C (Redis, Prometheus, Stripe)

> Issue: BOH-13 · Autore: agent-po · Data: ott 2026
> Scope: individuare cosa manca per chiudere la Fase 4C (indurimento &
> monetizzazione) e cosa c'è GIA' e non va rifatto. Path reali letti:
> `backend/spesemed/src/spesemed/api/`, `backend/spesemed/docker-compose*.yml`,
> `backend/spesemed/tests/`, `backend/spesemed/pyproject.toml`,
> `specs/spesemed/.env.example`, `specs/spesemed/PROJECT_STATUS.md` (§10 backlog).

---

## 0. Sintesi esecutiva

| Area 4C | Stato attuale | Gap residuo |
|---|---|---|
| **Redis rate-limit storage** | 🟡 ~70% fatto | Codice + docker-compose + env già pronti. Mancano: test automatici del path redis, readiness check all'avvio, campo /health (opzionale). |
| **Prometheus /metrics** | 🟡 ~65% fatto | Endpoint + ACL + kill-switch + 20 test già presenti. Mancano: metriche HTTP application-level (richieste/errori/latenza), sample config per lo scraper. |
| **Stripe billing** | 🔴 0% fatto | Assente ovunque: dipendenza, env, migration, API (checkout/webhook/status), gating su /extract, test. |
| **E2E success-path** | 🔴 da validare | Script + checklist pronti nel piano (`03-e2e-plan.md`); esecuzione con secrets reali al proprietario. |

Legenda: 🟢 = fatto e verificato · 🟡 = parzialmente fatto, gap puntuali · 🔴 = da costruire.

---

## 1. GAP-1 — Redis rate-limit storage

### 1.1 Cosa c'è già (NON rifare)

| Componente | Path | Stato |
|---|---|---|
| Risoluzione storage URI | `backend/spesemed/src/spesemed/api/rate_limit.py:33-101` (`_build_storage_uri`: `"memory"` → `memory://`, `"redis://..."` → URI, `"redis"` → usa `REDIS_URL`) | ✅ implementato, redazione password inclusa |
| Key function ibrida | `rate_limit.py:104-153` (`_key_by_user_or_ip`: sub JWT verificato in prod, IP fallback, X-User-Id solo dev) | ✅ testato (Fase 3, CRIT-1) |
| Limiter singleton | `rate_limit.py:159-165` (`Limiter(storage_uri=_storage_uri, strategy="fixed-window", headers_enabled=True)`) | ✅ |
| Config env | `config.py:191-209` (`rate_limit_storage_backend` default `"memory"`, `redis_url` default `""`) | ✅ |
| Compose dev | `docker-compose.yml:17-31` (servizio `redis:7-alpine` + healthcheck) e `:46-49` (`RATE_LIMIT_STORAGE_BACKEND=redis`, `REDIS_URL=redis://redis:6379/0`) | ✅ |
| Compose prod | `docker-compose.prod.yml:18-45` (redis persistente AOF, `expose` senza porta esterna) e `:64-68` (env redis) | ✅ |
| Env docs | `specs/spesemed/.env.example:86-111` (sezione "Rate limiting (Fase 3 + Fase 4 Redis)", `REDIS_URL`) | ✅ |
| Warning multi-worker | `main.py:64-80` (`_warn_if_multi_worker_memory_rate_limit`) chiamato in lifespan `main.py:210` | ✅ testato |

### 1.2 Gap residui

#### GAP-1.1 — Nessun test automatico del path Redis
- **File/riga attuali**: `rate_limit.py:33-101` ha la logica, ma `tests/` non contiene un `test_rate_limit.py`: i test esistenti (`test_security_fixes.py`, `test_metrics.py`) coprono comportamenti con storage memory e non verificano mai che `RATE_LIMIT_STORAGE_BACKEND=redis` produca l'URI corretto e che `REDIS_URL` venga rispettato.
- **Cosa aggiungere**: `backend/spesemed/tests/test_rate_limit.py` con unit test di `_build_storage_uri()`:
  - `rate_limit_storage_backend="memory"` → `memory://`
  - `rate_limit_storage_backend="redis://redis:6379/0"` → pass-through
  - `rate_limit_storage_backend="redis"` + `redis_url="redis://redis:6379/0"` → `redis://redis:6379/0`
  - URI con password → password redatta (nessun secret nel log)
  - `rate_limit_storage_backend="redis"` + `redis_url=""` → fallback documentato (decidere: memory + WARNING, vedi GAP-1.2)
- **Rischi**: regressione silenziosa al cambio di versione `limits[redis]`/`slowapi`; URI malformato che al boot non fallisce ma produce 500 al primo 429.

#### GAP-1.2 — Readiness check all'avvio (Redis giù)
- **File/riga attuali**: `main.py:180-232` (lifespan) non verifica mai la raggiungibilità di Redis quando `rate_limit_storage_backend` è redis. `limits`/`redis-py` si connettono lazy: l'app parte "verde" anche con Redis giù e il primo endpoint rate-limited può fallire con 500 invece di un errore chiaro.
- **Cosa aggiungere**: nel lifespan, prima dello yield: se storage=redis → `redis.asyncio.from_url(...).ping()` con timeout breve (es. 1-2s); log WARNING esplicito se irraggiungibile ("Redis non raggiungibile: i rate-limit NON sono condivisi/attivi — fixare REDIS_URL o passare a memory"). Decisione progettuale: **non far crashare il boot** in dev (fail-open con WARNING), ma in produzione (`API_ENV=production`) loggare ERROR e uscire con codice non-zero? → raccomandazione: fail-fast **solo** se `RATE_LIMIT_STORAGE_BACKEND=redis` esplicito + `API_ENV=production`; altrimenti WARNING. (Il compose prod ha già `depends_on: condition: service_healthy`, quindi il fail-fast è coerente.)
- **Rischi**: boot bloccato se Redis temporaneamente giù in prod; trade-off documentato nel piano.

#### GAP-1.3 — /health non espone lo stato Redis (opzionale)
- **File/riga attuali**: `routes/health.py` (risponde `{status, service, version, openrouter_configured}`), schema `schemas.py:19-27` (`HealthResponse`).
- **Cosa aggiungere** (nice-to-have): campi `redis_configured` / `redis_ok` opzionali (default false) solo quando `rate_limit_storage_backend` è redis. Non bloccante per la 4C; se fatto, aggiornare `HealthResponse` + test in `test_health.py`.
- **Rischi**: un ping Redis su ogni /health aggiunge latenza; farlo con timeout 1s e solo se abilitato, oppure esporre solo `redis_configured` (statico) e lasciare il ping al solo startup.

### 1.3 Rischi generali GAP-1

| Rischio | Severità | Mitigazione |
|---|---|---|
| Boot con Redis giù → 500 sui rate-limit | Alta | Startup ping + WARNING/ERROR esplicito (GAP-1.2) |
| Cambio `limits[redis]` versione rompe URI | Media | Pin già presenti (`limits[redis]>=3.0.0`, `redis>=5,<6`); unit test GAP-1.1 |
| Password Redis nei log | Media | Già redatta (`rate_limit.py:88-99`); testarlo in GAP-1.1 |
| Multi-worker con memory (limiti ×N) | Media | Warning già attivo (`main.py:64-80`); Redis obbligatorio in prod compose |

---

## 2. GAP-2 — Prometheus /metrics (esposizione + ACL)

### 2.1 Cosa c'è già (NON rifare)

| Componente | Path | Stato |
|---|---|---|
| Endpoint `/metrics` Prometheus exposition | `main.py:339-374` (`generate_latest()`, `content_type=text/plain; version=0.0.4`) | ✅ |
| Kill-switch totale | `main.py:362-366` (`prometheus_metrics_enabled=False` → 404) + `config.py:214-218` | ✅ |
| ACL IP/CIDR in-process | `metrics_acl.py:109-155` (`check_metrics_authorization`: loopback default, CIDR, IPv4-mapped IPv6, XFF trusted, fail-closed prod / fail-open dev) | ✅ |
| Trust XFF | `config.py:233-241` (`metrics_trust_xff`) + `metrics_acl.py:82-106` | ✅ |
| Metriche JWT esistenti | `metrics.py:54-76` (`spesemed_jwt_failures_total{reason}`, `spesemed_jwt_decode_duration_seconds`, `spesemed_jwt_jwks_cache_resets_total`) con protezione cardinality (`metrics.py:84-93`) | ✅ |
| Admin reset JWKS cache | `main.py:380-429` (X-Admin-Token, rate-limit 5/min, fail-closed) | ✅ |
| Test | `tests/test_metrics.py` (20+ test: formato, 404, ACL, XFF, IPv6, fail-closed/open, warning startup) | ✅ |

### 2.2 Gap residui

#### GAP-2.1 — Manca la telemetria HTTP applicativa (RED)
- **File/riga attuali**: `metrics.py` espone solo metriche JWT. Il backlog (`PROJECT_STATUS.md` §10.2) chiede esplicitamente "counter richieste, errori per status, latenza". Nessun middleware HTTP metrics esiste in `main.py` (solo CORS `:267-273`, SlowAPI `:277`).
- **Cosa aggiungere**:
  - Nuovo modulo `backend/spesemed/src/spesemed/api/metrics_http.py` con:
    - `spesemed_http_requests_total{method, status}` (Counter) — label **bounded**: method ∈ {GET,POST,PUT,PATCH,DELETE,OPTIONS,HEAD,OTHER}, status ∈ {1xx..5xx, "unknown"}. NIENTE label `path` (cardinality OOM).
    - `spesemed_http_request_duration_seconds{method}` (Histogram, buckets ~0.005..10s) — o `{method, status}` se si vuole latenza per esito (cardinalità ancora bounded).
  - Middleware `BaseHTTPMiddleware` (o puro `@app.middleware("http")`) in `main.py` che:
    1. osserva l'avvio della request,
    2. chiama `call_next`,
    3. registra status + durata nel `finally`.
  - Il middleware deve **non** misurare `/metrics` stesso? Decisione: misuralo pure (sono poche richieste, ma evitare self-scrape noise è più pulito → escludere il path `/metrics` dalla metrica duration, documentato).
- **Rischi**: cardinality su label `path` (MOLTO alto rischio OOM con route parameterizzate come `/jobs/{job_id}`); soluzione = solo method+status. Overhead di timing minimo. Test: verify che un hit su `/api/v1/health` incrementi `spesemed_http_requests_total{method="GET",status="200"}`.

#### GAP-2.2 — Nessuna config di esempio per lo scraper
- **File/riga attuali**: `deployment/` contiene Caddyfile, RUN_OPERATIONS.sh, SMOKE_TEST.sh, GENERATE_SECRETS.sh — nessun `prometheus.yml`.
- **Cosa aggiungere** (nice-to-have operativo): `deployment/prometheus.yml` di esempio con job `spesemed-api` (scrape `http://api:8000/metrics`, `metrics_path: /metrics`), alert di base su `spesemed_http_requests_total{status=~"5.."}` e `spesemed_jwt_failures_total`. Non serve per la pipeline offline, ma chiude il cerchio operativo.
- **Rischi**: bassi (file statico); attenzione a `METRICS_IP_ALLOWLIST` se lo scraper è su host diverso → documentare in `.env.example:143-145` (già presente) e nel runbook.

#### GAP-2.3 — Test delle nuove metriche HTTP
- **File/riga attuali**: `tests/test_metrics.py` non copre metriche HTTP (non esistono ancora).
- **Cosa aggiungere**: estensioni a `tests/test_metrics.py` (o `tests/test_metrics_http.py`):
  - hit su health → counter incrementato con label giuste,
  - hit su route inesistente (404) → counter status 404,
  - errore 500 forzato (es. route che solleva) → counter status 500,
  - istogramma observato (sum > 0),
  - `/metrics` continua a rispettare ACL (nessuna regressione).

### 2.3 Rischi generali GAP-2

| Rischio | Severità | Mitigazione |
|---|---|---|
| Cardinality OOM (label path/user) | Alta | Solo method+status; `record_failure` già coerce label ignote |
| /metrics pubblico per misconfig proxy | Alta | ACL in-process già presente (defense-in-depth) |
| Overhead middleware su ogni request | Bassa | `time.perf_counter` + incremento label bounded; trascurabile |
| Self-scrape inflaziona le metriche | Bassa | Escludere `/metrics` dalla metrica duration (non dal counter) |

---

## 3. GAP-3 — Stripe billing (da costruire)

### 3.1 Stato attuale
- **grep "stripe" nel backend: 0 risultati.** Nessuna dipendenza in `pyproject.toml`/`requirements.txt`, nessuna env in `config.py`/`.env.example`, nessuna migration, nessuna route, nessun test, nessun riferimento frontend.

### 3.2 Modello di prodotto raccomandato (MVP)
- **Subscription mensile** con **allowance mensile di estrazioni** (non crediti puri): piano "Pro" → N estrazioni/mese (default suggerito 100), conteggio resettato a inizio periodo. Semplice da implementare, testare offline e spiegare all'utente italiano (micro-copy calma).
- **Checkout hosted da Stripe** (Checkout Session): zero PCI scope, nessuna carta gestita dal backend.
- **Gating**: `POST /api/v1/extract` (il vero driver di costo, chiamate AI OpenRouter). Export NON gated nell'MVP (costo marginale ~0).
- **Kill switch**: `BILLING_ENABLED=false` (default) → comportamento attuale identico (tutti i 135 test verdi restano verdi). Con `true`, utenti senza entitlement attivo ricevono **402 Payment Required** (`code="payment_required"`).
- **Stato utente** derivato da webhook Stripe → tabella `entitlements` (no chiamate Stripe on-read).

### 3.3 Gap enumerati (tutti da costruire)

#### GAP-3.1 — Dipendenza + env + config
- **Da aggiungere**:
  - `pyproject.toml` + `requirements.txt`: `stripe>=9.0.0,<11.0.0` (stabile, API 2024+; adattare il pin alla versione del momento dell'implementazione).
  - `config.py` nuovi campi `Settings`:
    - `billing_enabled: bool = False` (kill switch),
    - `stripe_secret_key: str = ""`,
    - `stripe_webhook_secret: str = ""`,
    - `stripe_price_id: str = ""` (price "Pro" mensile),
    - `stripe_currency: str = "eur"`,
    - `stripe_mode: str = "test"` (test|live, per log/etichette),
    - `billing_extractions_limit: int = 100` (allowance mensile default),
    - `stripe_webhook_rate_limit: str = "60/minute"`.
  - `specs/spesemed/.env.example`: sezione `# --- Billing (Fase 4C Stripe) ---` con commenti (mai committare le chiavi).
- **Rischi**: segreto Stripe esposto in log → mai loggare chiavi; test mode vs live key confuse → campo `stripe_mode` + WARNING startup se `billing_enabled` e chiave mancante.

#### GAP-3.2 — Migration SQL `004_billing.sql`
- **Da aggiungere** (`backend/spesemed/migrations/004_billing.sql`), idempotente come le altre:
  ```sql
  CREATE TABLE IF NOT EXISTS entitlements (
      user_id TEXT PRIMARY KEY,
      plan TEXT NOT NULL DEFAULT 'free',
      status TEXT NOT NULL DEFAULT 'none',
      current_period_start TIMESTAMPTZ,
      current_period_end TIMESTAMPTZ,
      extractions_limit INT NOT NULL DEFAULT 0,
      extractions_used INT NOT NULL DEFAULT 0,
      stripe_customer_id TEXT,
      stripe_subscription_id TEXT,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_entitlements_stripe_cust ON entitlements (stripe_customer_id);

  CREATE TABLE IF NOT EXISTS stripe_events (
      event_id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  ALTER TABLE entitlements ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS "Service role full access on entitlements" ON entitlements;
  CREATE POLICY "Service role full access on entitlements" ON entitlements
      FOR ALL USING (auth.role() = 'service_role');

  ALTER TABLE stripe_events ENABLE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS "Service role full access on stripe_events" ON stripe_events;
  CREATE POLICY "Service role full access on stripe_events" ON stripe_events
      FOR ALL USING (auth.role() = 'service_role');
  ```
- **Nota**: `stripe_events.event_id` PK = idempotenza webhook (replay-safe). Incremento `extractions_used`: fatto lato backend su ogni estrazione riuscita (non in SQL) con UPDATE atomico; alternativa SQL RPC `bump_extraction_usage(user_id)` — preferire l'UPDATE applicativo per semplicità, documentare il race (2 worker) e mitigare con `UPDATE ... SET extractions_used = extractions_used + 1 WHERE user_id = ...` (atomico su riga).
- **Rischi**: RLS mancante (dati fatturazione PII!) → policy service_role-only obbligatoria; errore migration in produzione → idempotente (IF NOT EXISTS) come le altre.

#### GAP-3.3 — Wrapper Stripe DI-friendly `api/billing_client.py`
- **Da aggiungere**: modulo con:
  - `is_billing_configured() -> bool` (key + webhook secret + price id presenti),
  - `create_checkout_session(user_id, email, price_id, success_url, cancel_url) -> dict` (chiama `stripe.checkout.Session.create` con `mode="subscription"`, `client_reference_id=user_id`, `metadata={"user_id": user_id}`),
  - `parse_webhook_event(payload, sig_header) -> event` (chiama `stripe.Webhook.construct_event`),
  - `map_event_to_entitlement(event) -> Optional[dict]` (traduce `checkout.session.completed`, `customer.subscription.updated/deleted`, `invoice.paid` in upsert di `entitlements`),
  - `reset_billing_client()` per test.
  - Pattern identico a `supabase_client.py` (singleton + graceful degradation + import modulare per monkeypatch pulito).
- **Rischi**: wrapper "magico" difficile da testare → mock via monkeypatch di `stripe.*` (no network); nessun secret nei log.

#### GAP-3.4 — Route `POST /api/v1/billing/checkout` (auth)
- **Da aggiungere** (`routes/billing.py`): crea la Checkout Session per l'utente autenticato, ritorna:
  ```json
  {"checkout_url": "https://checkout.stripe.com/...", "session_id": "cs_...", "mode": "test|live"}
  ```
  - Risposte: 200 OK, 503 se `billing_enabled=false` o chiavi mancanti, 401 se non autenticato, 429 con rate-limit (`stripe_webhook_rate_limit` o nuovo `rate_limit_checkout="10/minute"`).
  - `success_url` e `cancel_url` da settings: `billing_success_url` (default `{APP_URL}/app/profilo?billing=success`) e `billing_cancel_url`.
- **Rischi**: open redirect via success_url → mai accettare URL dal client; usare settings.

#### GAP-3.5 — Route `POST /api/v1/billing/webhook` (pubblica, firma)
- **Da aggiungere**: endpoint **senza** `get_current_user`; legge `stripe-signature` header, verifica con `STRIPE_WEBHOOK_SECRET` via `construct_event` (400 se firma invalida / payload malformato), **idempotente** via `stripe_events.event_id` (INSERT ... ON CONFLICT DO NOTHING; se già processato → 200 immediato), poi mappa l'evento su `entitlements` (upsert) e ritorna 200.
  - Eventi minimi MVP: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid` (refresh periodo + limite).
  - Rate-limit soft (60/min) come safety net; la firma è il vero gate.
- **Test offline**: costruire payload firmato con secret di test locale (la lib `stripe` permette `WebhookSignature`), verificare 200/400/replay idempotente con mock di `supabase_client`.
- **Rischi**: event replay → idempotenza via PK; firma non verificata → 400 fail-closed; payload gigante → limitare body; log di eventi Stripe → mai loggare payload interi (contengono PII), solo `event.type` + `event.id`.

#### GAP-3.6 — Route `GET /api/v1/billing/status` (auth)
- **Da aggiungere**: stato entitlement per il client (Profilo):
  ```json
  {"plan": "pro", "status": "active", "period_end": "...", "extractions_limit": 100, "extractions_used": 12, "billing_enabled": true}
  ```
  - 200; `billing_enabled=false` → `{"billing_enabled": false}` (nessun 503: il client non deve rompersi).
  - Rate-limit 30/minuto.
- **Rischi**: leak cross-tenant → query per `user_id` dal token, mai da body.

#### GAP-3.7 — Gating su `POST /api/v1/extract`
- **Da aggiungere** in `routes/extract.py` (subito dopo il check 503 di Supabase, prima del branch sync/async):
  ```python
  if settings.billing_enabled and not await _user_has_entitlement(user_id):
      raise HTTPException(
          status_code=status.HTTP_402_PAYMENT_REQUIRED,
          detail="Piano gratuito esaurito o abbonamento non attivo. Abbonati per continuare.",
      )
  ```
  con `_user_has_entitlement`: legge `entitlements` per user_id; attivo se `status='active'` (o trialing) e `period_end > now` e `extractions_used < extractions_limit`. Al successo di estrazione (sync **e** async worker), incremento atomico `extractions_used`.
  - Nota worker async: il gating preventivo avviene alla creazione del job; il consumo va conteggiato quando il worker completa le estrazioni (aggiornare `worker.py` per chiamare il bump; oppure MVP: contare al momento della creazione del job — trade-off documentato: contare alla creazione è più semplice e testabile, ma sovra-conta se il job fallisce; **raccomandazione MVP**: bump alla creazione del job per sync, bump al completamento nel worker per async; se troppo complesso, bump alla creazione per entrambi e nota di miglioramento).
- **Rischi**: race su `extractions_used` (2 request simultanee) → UPDATE atomico `SET extractions_used = extractions_used + 1`; double-count con idempotency cache (file già estratto) → NON incrementare su cache hit; 402 deve usare il formato ErrorResponse standard (il client React lo gestisce); utenti "free" senza row in entitlements → status=free, limit=0 → 402 quando `billing_enabled`.

#### GAP-3.8 — Frontend minimo (contratto per agent-ui-ux, NON implementato dal PO)
- **Da aggiungere** in `frontend-app` (lavoro di agent-ui-ux, qui solo contratto):
  - Profilo: sezione "Piano" che chiama `GET /billing/status` e mostra piano/stato/usage;
  - Bottone "Abbonati" → `POST /billing/checkout` → redirect a `checkout_url`;
  - Gestione 402 su /extract → messaggio calmo in italiano + CTA abbonamento;
  - Dopo checkout, il webhook aggiorna l'entitlement; il client rifresca `/billing/status` al ritorno (`?billing=success`).
- **Rischi**: nessuna chiave Stripe lato client (solo URL di checkout); niente `pk_test` nel bundle.

### 3.4 Rischi generali GAP-3

| Rischio | Severità | Mitigazione |
|---|---|---|
| Firma webhook non verificata | Critica | `construct_event` fail-closed; test 400 |
| Replay eventi | Alta | PK `stripe_events.event_id` + ON CONFLICT DO NOTHING |
| Double-count estrazioni | Alta | UPDATE atomico; no bump su cache hit |
| Chiavi Stripe nei log/bundle | Alta | Mai loggare; mai `pk_*` nel frontend; WARNING startup se chiave mancante con billing_enabled |
| 402 rompe client esistenti | Media | Kill switch `BILLING_ENABLED=false` default; formato ErrorResponse standard |
| Conformità IVA/fatturazione (Italia) | Media | Stripe Tax opzionale; documentare che il proprietario configura le impostazioni fiscali nel dashboard Stripe (fuori scope codice) |
| Race period reset | Bassa | `invoice.paid` aggiorna `current_period_*` e azzera `extractions_used` |

---

## 4. Cosa NON è un gap (già coperto)

- ✅ 429 handler JSON custom (`main.py:283-306`)
- ✅ Rate-limit per endpoint (auth 2/h, login 5/min, refresh 30/min, logout 20/min, extract 10/min, jobs 30/min, summary, export 10/min)
- ✅ Warning startup multi-worker + memory (`main.py:64-80`)
- ✅ ACL /metrics completa con test
- ✅ Admin endpoint con rate-limit e fail-closed
- ✅ Docker Compose Redis (dev e prod)
- ✅ Env vars documentate per Redis e metrics
- ✅ Backend live :8000 (resta del proprietario; nessuna modifica diretta)

---

## 5. Fonti verificate

- `backend/spesemed/src/spesemed/api/rate_limit.py`, `metrics.py`, `metrics_acl.py`, `config.py`, `main.py`, `supabase_client.py`, `schemas.py`
- `backend/spesemed/src/spesemed/api/routes/{extract,export,auth}.py`
- `backend/spesemed/docker-compose.yml`, `docker-compose.prod.yml`
- `backend/spesemed/tests/test_metrics.py`, `conftest.py`
- `backend/spesemed/migrations/001_init.sql`, `003_waitlist.sql`
- `backend/spesemed/pyproject.toml`, `requirements.txt`
- `specs/spesemed/README.md`, `PROJECT_STATUS.md`, `.env.example`, `TASK_FRONTEND.md`
- `frontend/spesemed/design/DESIGN.md`, `frontend/spesemed/frontend-app/src/`
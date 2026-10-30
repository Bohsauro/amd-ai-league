# SPESEMED — Onboarding per la company (kickoff)

> Micro-SaaS italiano: estrazione automatica spese mediche da ricevute (PDF/JPG)
> per assicurazione e dichiarazione 730. Backend FastAPI **già in produzione su :8000**
> (gunicorn, live), frontend SPA Vite+React18+TS **già costruito** in `frontend-app/`.
> Il backend 4C è pronto come **skeleton operativo**: Redis readiness, metriche
> Prometheus HTTP, Stripe (plan/status/checkout/webhook + gating 402 su /extract).
> Restano validazione E2E con Supabase reale, lifecycle webhook completo + UI
> piano (task separati) e audit qualità frontend.

## Stato (fonte: PROJECT_STATUS.md, oct 2026)

- Fasi 0-3, 4A(web), 4B (Export Excel/ZIP), 4B+ (Profilo/usage) ✅ done
- pytest **239 passed, 1 skipped** offline (mock Supabase) + audit pre-go-live PASSED + GO_LIVE_RUNBOOK operativo
- Backend **live su http://localhost:8000** (gunicorn 2 worker, bind 0.0.0.0:8000) → `/api/v1/health` 200
- Flutter GUI rimossa (ott 2026) → la GUI web reale è `frontend-app/` (Vite+React18+TS, design "Verde Calma")
- **4C backend done (skeleton)**: Redis rate-limit storage con readiness, metriche HTTP Prometheus, Stripe `plan`/`status`/`checkout`/`webhook` + gating 402, con no-op mode e test offline
- **Resta**: validazione E2E success-path con secrets reali, lifecycle webhook completo (4C-C5) + UI Profilo/piano (4C-C9), audit qualità frontend

## Mappa ruoli → domini di scrittura (path nel workspace)

| Ruolo | Agente | Scrive in | Contenuto |
|---|---|---|---|
| CEO | agent-ceo | radice (review/merge) | coordinamento, epic |
| PO | agent-po | `specs/spesemed/` | doc, task, decisioni prodotto |
| Core Dev | agent-core-dev | `backend/spesemed/` | codice backend Python |
| UI/UX | agent-ui-ux | `frontend/spesemed/` | SPA React + design |
| Reviewer | agent-reviewer | nulla (read-only) | APPROVE/REJECT su richiesta |

**Path importanti (riscritti per i domini — NON usare i path originali):**

- Backend sorgente: `backend/spesemed/src/spesemed/` (api/, core/, ecc.)
- Test backend: `backend/spesemed/tests/` (pytest, mock Supabase, offline)
- Migrations: `backend/spesemed/migrations/` (001_init.sql, 002_rls_policies.sql, 003_waitlist.sql, 004_billing.sql)
- Deployment: `backend/spesemed/deployment/` (Caddyfile, RUN_OPERATIONS.sh, SMOKE_TEST.sh, GENERATE_SECRETS.sh)
- Config: `backend/spesemed/.env.example` — **i secrets veri NON sono nel workspace** (stanno in `/home/bohsauro/SPESEMED/.env`, fuori portata)
- Frontend app: `frontend/spesemed/frontend-app/` (src/, vite.config.ts, package.json)
- Design system: `frontend/spesemed/design/DESIGN.md` (autoritativo: palette "Verde Calma", Manrope+JetBrains Mono), `PRODUCT.md`, `verde-calma.html` (mockup navigabile approvato)
- Task UI originali: `specs/spesemed/TASK_FRONTEND.md` (contratto API da verificare nei sorgenti)
- Runbook go-live: `specs/spesemed/GO_LIVE_RUNBOOK.md` · Test guide: `specs/spesemed/TEST_GUIDE.md` · Security: `specs/spesemed/SECURITY.md`

## Regole operative (OBBLIGATORIE)

1. **Backend live su :8000 è del proprietario**: NON riavviarlo, NON modificarlo. I fix si
   sviluppano in `backend/spesemed/`, si testano con pytest offline (mock Supabase) e si
   consegnano per la review. Niente curl di scrittura contro :8000.
2. **Secrets**: mai chiedere/leggere `/home/bohsauro/SPESEMED/.env`. Test offline con mock
   (come `tests/conftest.py`). ALLOW_DEV_MOCK_AUTH=false in produzione → niente fallback
   `X-User-Id`: serve login Supabase reale.
3. **CORS**: `config.py` cors_origins default = localhost:3000 e :8501. La Vite dev DEVE
   restare su **porta 3000** (`vite.config.ts` ha già `host: true` per LAN/Tailscale).
4. **Design**: nessun colore hardcoded fuori dalle var del DESIGN.md; hit target ≥44px,
   contrasti WCAG AA, microcopy italiano calmo, niente emoji. Verifica qualità con
   `npx impeccable detect` (se disponibile).
5. **Commit**: ogni step su git con identità bot (`git -c user.name='ai-company-bot' -c user.email='bot@ai-company.local'`), mai su main direttamente (branch per ruolo: `dev/backend`, `dev/frontend`, ...). Consolidamento a fine lavoro.
6. **Ticket**: stato `in_review` → review di agent-reviewer → `done` SOLO con APPROVE (gate `bin/close-ticket`). Commento finale con numeri/path reali, no dichiarazioni vage.
7. **Verify**: se esiste un gate per SPESEMED, tenerlo verde; al minimo `python -m pytest` in `backend/spesemed/` deve restare verde.

## Cosa NON rifare (già fatto e verificato)

- Core AI engine (extractor, prompts, file_utils, models) — Fase 0 ✅
- API FastAPI (auth, extract, jobs, summary, export, health, metrics) — Fasi 1-4B+ ✅
- Supabase migrations + RLS + bucket — già applicate dall'utente ✅
- Export Excel/ZIP + Profilo/usage — Fase 4B/4B+ ✅
- SPA React di base (login, dashboard, carica, risultati, storico, esporta, profilo) — già costruita, da AUDITARE non da rifare ✅
- 4C backend: Redis readiness/test, metriche HTTP Prometheus, Stripe skeleton (`billing.py`,
  `billing_client.py`, `routes/billing.py`, migration 004, `tests/test_billing.py`) ✅

## Lavoro residuo (in ordine di valore)

1. **Validazione E2E success-path con Supabase reale** (health→signup→login→jobs→extract→export;
   200 OK reali) — richiede secrets: preparare script + istruzioni, l'esecuzione finale la fa il proprietario.
2. **Lifecycle webhook + UI Profilo/piano** (4C-C5/C9): il gating 402 è implementato,
   ma il webhook gestisce solo `checkout.session.completed` e il frontend non mostra
   ancora stato piano/uso.
3. **Audit qualità frontend-app**: impeccable detect, build `npm run build` senza errori,
   aderenza DESIGN.md, accessibilità, gestione errori/loading, refresh token su 401.

## Stripe billing — setup, test locale e runbook incidenti

Questa sezione copre il billing **test mode**. Per la produzione vedi anche
`GO_LIVE_RUNBOOK.md` §5 (stessa procedura, chiavi live e webhook pubblico).

### Cosa espone il backend

| Metodo | Path | Auth | Comportamento |
|---|---|---|---|
| GET | `/api/v1/billing/plan` | no | Info pubbliche piano (`stripe_configured`, `webhook_configured`, `price_id`, valuta). Nessun secret. |
| GET | `/api/v1/billing/status` | Bearer | Stato piano dell'utente (`billing_enabled`, `plan`, `status`, `period_end`, limit/used). Mai 5xx: degrada a free. |
| POST | `/api/v1/billing/checkout` | Bearer | Crea una Checkout Session (`200 {checkout_url, session_id, mode, amount_total, currency}`). Body opzionale `{email}`. `503` se kill switch OFF o config incompleta. |
| POST | `/api/v1/billing/webhook` | firma Stripe | Verifica `Stripe-Signature`; `400` firma invalida, `503` se `STRIPE_WEBHOOK_SECRET` manca, `200` altrimenti. |

Con `BILLING_ENABLED=true`, `POST /api/v1/extract` risponde `402 payment_required`
se l'utente non ha un entitlement attivo o ha esaurito la quota; il consumo non
aumenta sui cache hit. La quota vive nella tabella `entitlements` (vedi §5.5 del
runbook per lo SQL se la migration non la include ancora).

No-op mode: con `BILLING_ENABLED=false` (default) o chiavi/price mancanti il billing
non chiama Stripe e `/billing/checkout` risponde `503` con messaggio chiaro. Il resto
dell'API continua a funzionare.

### 1. Setup dashboard Stripe (test mode)

1. Attiva il **test mode** in alto a destra nella Dashboard Stripe.
2. **Product catalog → Add product**: nome (es. `SPESEMED PRO`), prezzo ricorrente
   mensile (es. `9.99 EUR`). Salva e copia il **Price ID** (`price_...`).
3. **Developers → API keys**: copia la **Secret key** di test (`sk_test_...`).
   La publishable key non serve al backend: il browser va solo su `checkout_url`.
4. **Developers → Webhooks → Add endpoint** (per il deploy pubblico):
   - URL: `https://<api-host>/api/v1/billing/webhook`
   - Eventi: `checkout.session.completed` (minimo) + `customer.subscription.updated`,
     `invoice.paid` (consigliati). Lo skeleton attuale persiste `checkout.session.completed`;
     gli altri eventi sono ack-ati con `action=ignored` finché non arriva il lifecycle completo.
   - Copia la **Signing secret** (`whsec_...`).
5. Compila `.env` (mai committare):

```dotenv
BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
STRIPE_CURRENCY=eur
STRIPE_MODE=test
BILLING_EXTRACTIONS_LIMIT=100
BILLING_SUCCESS_URL=http://localhost:3000/app/profilo?billing=success
BILLING_CANCEL_URL=http://localhost:3000/app/profilo?billing=cancel
BILLING_PLAN_NAME=SPESEMED PRO
```

6. Riavvia l'API e verifica:

```bash
curl -sS http://127.0.0.1:8000/api/v1/billing/plan | python3 -m json.tool
# atteso: "stripe_configured": true, "webhook_configured": true
```

### 2. Webhook locale con Stripe CLI

```bash
# una volta sola
stripe login

# in un terminale dedicato: inoltra gli eventi all'API locale
stripe listen --forward-to localhost:8000/api/v1/billing/webhook
# stampa: Ready! Your webhook signing secret is whsec_...
# copia quel whsec_... in STRIPE_WEBHOOK_SECRET e riavvia l'API

# in un altro terminale: verifica firma + ack dell'endpoint
stripe trigger checkout.session.completed
```

`stripe trigger` serve a verificare firma e risposta dell'endpoint: l'evento
sintetico può non avere `client_reference_id`, quindi non aspettarti la
persistenza. Per il flusso completo apri un checkout reale (sotto) e usa una
carta di test: allora il webhook contiene `client_reference_id` e, con Supabase
configurato + migration `004_billing.sql` applicata, la riga compare
in `subscriptions` (`user_id`, `stripe_customer_id`, `stripe_subscription_id`, `plan`, `status`).
Se Supabase non è configurato l'API risponde comunque `200` (best-effort) e
logga un WARNING: la subscription non viene persistita.

### 3. Test con numeri di carta finti (Stripe test mode)

Apri il `checkout_url` restituito da `POST /billing/checkout` e usa **solo carte di test
pubbliche Stripe**:

| Scenario | Numero | Scadenza / CVC |
|---|---|---|
| Pagamento riuscito | `4242 4242 4242 4242` | qualsiasi data futura / qualsiasi 3 cifre |
| Carta rifiutata | `4000 0000 0000 0002` | qualsiasi data futura / qualsiasi 3 cifre |
| Autenticazione 3DS richiesta | `4000 0027 6000 3184` | qualsiasi data futura / qualsiasi 3 cifre |

Non usare numeri di carte reali, nemmeno in test. Dopo il pagamento verifica:
`GET /billing/status` con piano/limite aggiornati, log webhook `subscription_created`, riga in `subscriptions`.
Il redirect finale è `BILLING_SUCCESS_URL` (o `BILLING_CANCEL_URL` se annulli).

### 4. Test offline (nessun secret, nessuna rete)

Esegui da `backend/spesemed/`:

```bash
python -m pytest tests/test_billing.py -v       # 27 passed (mock stripe + supabase)
python -m pytest tests/test_extract_billing_gate.py -v  # 6 passed (402/quota/cache)
python -m pytest tests/test_rate_limit.py -v    # 16 passed (memory/redis URI + readiness)
python -m pytest tests/test_metrics.py -v       # 37 passed (JWT + HTTP metrics)
python -m pytest -q                             # 239 passed, 1 skipped, 0 failed
python -m compileall src tests                  # nessun errore
```

I test usano chiavi finte (`sk_test_fake_...`, `whsec_test_...`) e mockano `stripe.*`:
nessuna chiamata di rete, nessun secret reale nel workspace.

### 5. Runbook incidenti billing

| Sintomo | Diagnosi | Remediation |
|---|---|---|
| `/billing/checkout` → `503 Billing non configurato` | `BILLING_ENABLED=false`, `STRIPE_SECRET_KEY`/`STRIPE_PRICE_ID` vuoti o libreria `stripe` assente | Controlla `.env` (kill switch + chiavi); reinstalla `pip install -r requirements.txt`; riavvia l'API |
| `/billing/plan` → `stripe_configured=false` con chiave presente | Import `stripe` fallito o chiave con spazi/newline | `python -c "import stripe; print(stripe.VERSION)"`; ricontrolla il valore in `.env` |
| Webhook → `503 STRIPE_WEBHOOK_SECRET mancante` | Secret del webhook non impostato | Copia il `whsec_...` giusto (produzione: endpoint Stripe; locale: output di `stripe listen`) e riavvia |
| Webhook → `400 Webhook sign check failed` | Secret sbagliato, body modificato da proxy, firma di un altro endpoint | Usa il signing secret dell'endpoint corretto; assicurati che il proxy non riscriva il body; rigenera il secret |
| Webhook `200` ma nessuna riga in `subscriptions` | Supabase non configurato, migration 004 non applicata o `client_reference_id` assente | Applica la migration, verifica `SUPABASE_*`, controlla i log (WARNING con user id troncato) |
| Checkout creato ma redirect errato | `BILLING_SUCCESS_URL`/`BILLING_CANCEL_URL` non aggiornati | Correggi le URL in `.env` (devono essere raggiungibili dal browser) e riavvia |
| Doppio evento / replay | Stripe ritenta gli eventi non-2xx | L'endpoint è idempotente per natura su `subscriptions` (upsert per `user_id`); verifica i log, non duplicare manualmente |
| `Stripe API version drift` dopo upgrade | Pin `stripe>=9,<14` cambiato o breaking change SDK | Ripristina il pin, riesegui `pytest tests/test_billing.py`, aggiorna solo con test verdi |
| Chiave live usata per errore in test | `sk_live_...` in `.env` di sviluppo | Sostituisci con `sk_test_...`, ruota la chiave live dalla Dashboard, controlla i log per addebiti |

**Sicurezza**: non loggare mai `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` o il body
completo del webhook (contiene PII). Ruota i secret se sospetti un leak. Il webhook
verifica la firma **prima** di processare l'evento; una firma invalida è sempre `400`.
# SPESEMED — Validazione E2E success-path (Fase 4C)

> Lo script `run_e2e.py` valida il success-path del backend contro un
> **Supabase reale**: `health → signup → login → jobs → extract → export`.
> È pensato per essere eseguito dal **proprietario** con i suoi secrets.
> Il workspace NON contiene alcun secret.

## Requisiti

- Backend avviato e raggiungibile (default `http://localhost:8000`).
- Supabase configurato lato backend (`.env` con `SUPABASE_URL` +
  `SUPABASE_SERVICE_KEY` + `SUPABASE_JWT_SECRET`).
- OpenRouter configurato per lo step `extract` (`OPENROUTER_API_KEY`).
- Python 3.10+ con `httpx` (presente nelle dipendenze del backend).

## Esecuzione

Lo script legge TUTTO da variabili d'ambiente (mai secrets nel codice):

```bash
export SPESEMED_API_BASE=http://localhost:8000    # default se omesso
export SPESEMED_TEST_EMAIL=you@example.com
export SPESEMED_TEST_PASSWORD='S3cret!Pass'
export SPESEMED_TEST_RECEIPT=/path/to/ricevuta.jpg   # OPZIONALE (step extract)

python tests/e2e/run_e2e.py
```

### Exit code

| Code | Significato |
|------|-------------|
| `0`  | PASS: health + login OK e nessuno step tentato è fallito |
| `1`  | FAIL: almeno uno step obbligatorio/tentato è fallito |
| `2`  | Config mancante (env non impostati) — nessuna richiesta emessa |

### Semantica degli step

- `health` / `login`: **obbligatori** — devono rispondere `200`, altrimenti FAIL.
- `signup`: se l'utente esiste già risponde `SKIP` (accettato), se
  `ALLOW_SIGNUP=false` risponde `SKIP`.
- `jobs` / `export`: `503` (Supabase non configurato) => `SKIP`.
- `extract`: richiede `SPESEMED_TEST_RECEIPT`; `503` (OpenRouter/Supabase
  mancanti) => `SKIP`. Atteso `200` (sync) o `202` (async).
- `export` con `400` "nessuna estrazione da esportare" => `SKIP` (endpoint OK).

## Test offline

La suite pytest resta valida offline grazie ai mock in `tests/conftest.py`:

```bash
python -m pytest -q          # 173 test (135+ richiesti)
```

## Stripe billing (Fase 4C) — cosa serve per attivarlo

Il billing è un skeleton in `no-op mode`: senza secrets gli endpoint
rispondono `503` senza che parta alcuna chiamata di rete. Per attivarlo:

1. **Account Stripe** → Dashboard → Developers → API keys: copia la
   **secret key** (`sk_test_...`) in `STRIPE_SECRET_KEY` (nel `.env`, mai nel repo).
2. **Product + Price** ricorrente (es. 9.99 EUR/mese) → copia il `price_id`
   (`price_1Q...`) in `STRIPE_PRICE_ID`.
3. **Webhook** → "Add endpoint": `https://<api-host>/api/v1/billing/webhook`
   con eventi `checkout.session.completed` e `customer.subscription.deleted`;
   copia la **signing secret** (`whsec_...`) in `STRIPE_WEBHOOK_SECRET`.
4. **Redirect** configurati: `STRIPE_SUCCESS_URL` / `STRIPE_CANCEL_URL`
   (default: `app.spesemed.local`, da adattare al dominio reale).
5. (Opzionale) applica `migrations/004_stripe_subscriptions.sql` su Supabase:
   la subscription verrà persistita best-effort (`service_role`).

Endpoints esposti:

| Endpoint | Descrizione |
|----------|-------------|
| `GET  /api/v1/billing/plan`     | info pubbliche piano (nessun secret) |
| `POST /api/v1/billing/checkout` | crea Stripe Checkout Session (auth) |
| `POST /api/v1/billing/webhook`  | riceve eventi Stripe (firma verificata) |

Verifica "dry" dell'integrazione senza Stripe reale: `python -m pytest tests/test_billing.py -q`.
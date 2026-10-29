# SPESEMED — Piano di validazione E2E (Supabase reale)

Stato: pronto per esecuzione da parte del proprietario (BOH-13 / Fase 4C).
File correlati: `01-gap-analysis.md`, `02-plan-4c.md`, `scripts/e2e_success_path.py`.

## 1. Scopo

Validare il success-path completo di SPESEMED contro un'istanza **reale**
dell'API configurata con **Supabase reale** e **OpenRouter**:

    health -> signup -> login -> jobs -> extract -> export (200 OK)

Lo script incluso è **secret-free by design**: non contiene né richiede alcuna
chiave (Supabase/OpenRouter/Stripe). Parla solo con gli endpoint pubblici
dell'API; i secrets vivono sul server. Questo permette al proprietario di
eseguirlo ovunque (anche da un host remoto) senza maneggiare credenziali.

## 2. Prerequisiti lato server (verificare PRIMA di eseguire)

| # | Requisito | Dove/config | Come verificare |
|---|-----------|-------------|-----------------|
| 1 | API in esecuzione (uvicorn, `API_WORKERS>=1`) | `.env` del server | `curl -s http://localhost:8000/api/v1/health` |
| 2 | Supabase configurato | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `SUPABASE_BUCKET` | health mostra `supabase_configured=true`? |
| 3 | OpenRouter configurato | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | health mostra `openrouter_configured=true` (senza, extract fallisce 503) |
| 4 | Signup abilitato | `ALLOW_SIGNUP=true` | altrimenti `POST /auth/signup` -> 403 |
| 5 | Storage bucket e policies | bucket `SUPABASE_BUCKET` (default `receipts`) + storage e auth attivi | proiettare `auth.users` / `storage.objects` nel dashboard |
| 6 | Worker attivo (solo se si testa l'async con N>3 file) | processo worker separato | vedere log worker / job completati |
| 7 | (4C opzionale) Stripe configurato | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` | `GET /api/v1/billing/plan` -> `stripe_configured=true` |
| 8 | (4C opzionale) `/metrics` visibile | `PROMETHEUS_METRICS_ENABLED=true`, `METRICS_IP_ALLOWLIST` include l'IP dello script | `curl -s http://localhost:8000/metrics` |

> NOTA: in caso di progetti Supabase con **email confirmation obbligatoria**,
> il signup via API potrebbe ritornare successo ma il login fallire con 401
> finché l'email non è confermata. Per il test E2E usare un utente con
> conferma disabilitata O confermare l'email dal dashboard prima del login
> (o usare il magic-link). Vedi "Casi di fallimento" §6.

## 3. Com'è fatto lo script

Path: `specs/spesemed/tasks/scripts/e2e_success_path.py`
Dipendenze: **solo stdlib Python 3.9+** (`urllib`, nessun `pip install`).

Step eseguiti (in ordine):

| # | Step | Endpoint | Atteso |
|---|------|----------|--------|
| 1 | health | `GET /api/v1/health` | 200, `status="ok"` |
| 2 | signup | `POST /api/v1/auth/signup` | 201 + `access_token` (utente e2e temporaneo) |
| 3 | login | `POST /api/v1/auth/login` | 200 + `access_token` |
| 4 | jobs | `GET /api/v1/jobs` (Bearer) | 200 + lista job |
| 5 | extract | `POST /api/v1/extract` (multipart `files=`) | 200 sync (N<=3) oppure 202 async + poll fino a `done` |
| 6 | export | `POST /api/v1/export` body `{}` | 200, ZIP valido (`PK` magic), salvato su `--outdir` |
| 7 | billing/plan (opz.) | `GET /api/v1/billing/plan` | 200 + flag config |
| 8 | metrics (opz.) | `GET /metrics` | 200 (o 403/404 atteso se non permesso) |

Exit codes: `0` tutto PASS · `2` config locale errata (es. `--file` mancante) ·
`3` health/auth falliti · `4` extract/export falliti.

## 4. Istruzioni esatte per il proprietario

### 4.1 Preparazione

1. Clonare/portare il repo sul host di test (o sulla macchina del server).
2. Preparare **una ricevuta medica di esempio** (PDF, JPG, JPEG, PNG, WEBP o
   BMP; max `MAX_UPLOAD_SIZE_MB`, default 20MB). Idealmente una ricevuta con
   farmacia/laboratorio, data e importo ben leggibili. Senza un file reale
   l'extract fallirà (422 se il documento non contiene dati estraibili).
   Consiglio: creare `e2e_samples/` e salvarci `ricevuta_prova.pdf`.
3. (Solo se si esegue da host remoto) assicurarsi che l'URL base sia
   raggiungibile e che l'IP dello script sia in `METRICS_IP_ALLOWLIST` se si
   vuole validare `/metrics`.

### 4.2 Esecuzione completa

```bash
cd /percorso/workspace
export SPESEMED_API_URL="http://localhost:8000"        # o URL del deploy
# Opzionali: credenziali FISSE per il test (altrimenti generate al volo):
export SPESEMED_E2E_EMAIL="e2e.prova@example.com"
export SPESEMED_E2E_PASSWORD="sostituiscimi-con-una-password-forte"

python3 specs/spesemed/tasks/scripts/e2e_success_path.py \
    --file e2e_samples/ricevuta_prova.pdf \
    --outdir e2e_output
```

Atteso a fine esecuzione:

```
[Riepilogo: N PASS / 0 FAIL]
```

e un file `e2e_output/e2e_export_<timestamp>.zip` contenente
`SPESEMED_riepilogo.xlsx` + ricevute rinominate.

### 4.3 Esecuzione parziale (solo auth, senza AI/export)

```bash
python3 specs/spesemed/tasks/scripts/e2e_success_path.py --no-extract \
    --url http://localhost:8000
```

Utile quando Supabase è ok ma OpenRouter non è ancora configurato, o per
validare rapidamente health+signup+login+jobs senza consumare crediti LLM.

### 4.4 Invarianti da rispettare

- **Nessun secret negli argomenti**: lo script non accetta chiavi. Se un test
  remoto fallisce per CORS/allowlist, NON aggiungere credenziali allo script:
  sistemare il server (env/allowlist) o usare un tunnel.
- Non lanciare più di 2 signup/ora dallo stesso IP (rate-limit `2/hour`):
  se si ripete il test, riusare le stesse credenziali (lo script fa login
  diretto se il signup fallisce).

## 5. Checklist manuale

| # | Azione | Comando/verifica | Risultato atteso |
|---|--------|------------------|------------------|
| C1 | Health check | `curl -s http://localhost:8000/api/v1/health \| python3 -m json.tool` | `status=ok`, `openrouter_configured=true`, `supabase_configured=true` |
| C2 | Signup | vedere output script step 2 | `[PASS] signup` con 201 |
| C3 | Login | vedere output script step 3 | `[PASS] login` con 200 + token |
| C4 | Jobs (auth richiesto) | vedere output script step 4 | `[PASS] jobs` con 200 |
| C5 | Extract sync | un file <=3 → vedere output step 5 | `[PASS] extract (sync)` con `count>=1`, `model_used` valorizzato |
| C6 | Extract async (opz.) | 4+ file → 202 → poll | `[PASS] extract (async done)` con `completed_count` corretto |
| C7 | Export | vedere output step 6 | `[PASS] export` con zip salvato e magic `PK` |
| C8 | Contenuto ZIP | `unzip -l e2e_output/e2e_export_*.zip` | presenza `SPESEMED_riepilogo.xlsx` e ricevute |
| C9 | (4C) Piano pubblico | `curl -s http://localhost:8000/api/v1/billing/plan` | 200, `stripe_configured` coerente con env |
| C10 | (4C) Checkout | `curl -s -X POST http://localhost:8000/api/v1/billing/checkout -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{}'` | 201 + `checkout_url` (se Stripe configurato) oppure 503 con messaggio chiaro |
| C11 | (4C) Metrica | `curl -s http://localhost:8000/metrics \| head -30` | testo `text/plain` con metriche `spesemed_*` (o 403 se IP non in allowlist) |

> La checklist C1–C8 è interamente coperta dallo script; le righe qui servono
> da traccia ripercorribile e per debug punto-punto.

## 6. Casi di fallimento attesi e interpretazione

| Sintomo | Causa probabile | Azione |
|---------|-----------------|--------|
| `[FAIL] health` | API giù o URL errato | avviare uvicorn / correggere `--url` |
| `[FAIL] signup` 403 | `ALLOW_SIGNUP=false` sul server | impostare `true` (o testare con utente pre-esistente in login) |
| `[FAIL] signup` 429 | rate-limit `2/hour` per IP | attendere o cambiare IP/rete |
| `[FAIL] login` 401 | email confirmation obbligatoria / utente non confermato | confermare l'email nel dashboard Supabase o disabilitare la conferma per il test |
| `[FAIL] login` 503 | Supabase non configurato sul server | verificare `SUPABASE_*` in `.env` del server |
| `[FAIL] extract` 503 | OpenRouter mancante | verificare `OPENROUTER_API_KEY`; senza, la pipeline LLM non può estrarre |
| `[FAIL] extract` 422 | documento non estraibile (nessun dato medico) | usare una ricevuta reale e leggibile |
| `[FAIL] extract` 413 | file oltre `MAX_UPLOAD_SIZE_MB` | ridurre/ricompattare il file |
| `[FAIL] export` 400 | nessuna estrazione per l'utente | eseguire prima un extract riuscito (stesso utente) |
| `[FAIL] export` 503 | Supabase non configurato | come sopra |
| `[SKIP] extract` exit 2 | `--file` mancante senza `--no-extract` | fornire `--file` o usare `--no-extract` |
| metrics 403/404 | IP non in allowlist / `PROMETHEUS_METRICS_ENABLED=false` | **atteso**: validare solo se l'IP è autorizzato (mai disabilitare l'ACL per far passare il test) |

## 7. Estensioni Fase 4C coperte (opzionali, non bloccanti)

Lo script include due probe non bloccanti per la 4C:

1. `GET /api/v1/billing/plan` — conferma che il modulo billing risponde e
   NON espone secrets (flag booleani soltanto).
2. `GET /metrics` — conferma che l'exposition Prometheus risponde (o che i
   guard ACL funzionano: 403/404 su IP non autorizzati).

**Non coperte dallo script (richiedono strumenti Stripe/browser):**

- `POST /api/v1/billing/webhook` con firma reale → testare con
  `stripe listen --forward-to localhost:8000/api/v1/billing/webhook` e
  `stripe trigger checkout.session.completed` (vedi `02-plan-4c.md`, task 4C-C5).
- Redirect browser del checkout → aprire `checkout_url` manualmente in modalità
  test Stripe (card `4242 4242 4242 4242`).
- Rate-limit condiviso Redis tra 2 worker → procedura manuale in
  `02-plan-4c.md` task 4C-A3 (richiede `docker compose` con redis).

## 8. Pulizia post-test

- Eliminare l'utente e2e dal dashboard Supabase (`Authentication -> Users`) se
  non serve conservarlo; oppure lasciarlo come utente di smoke-test.
- I file caricati restano nel bucket `receipts`: rimuoverli da
  `Storage -> receipts` se il test era solo prova.
- L'eventuale cartella `e2e_output/` è locale e può essere cancellata.

## 9. Criteri di chiusura (Done Definition E2E)

- [ ] Lo script termina con exit code `0` e `PASS` su tutti gli step obbligatori
- [ ] `e2e_output/e2e_export_<ts>.zip` creato, con magic bytes `PK` e contenuto non vuoto
- [ ] Checklist C1–C8 ripercorribili manualmente (documentare output in un commento sul ticket di esecuzione)
- [ ] Nessun secret presente nello script né nei suoi output/log
- [ ] Conferma visiva nel dashboard Supabase: utente e2e, record estratti, file nel bucket
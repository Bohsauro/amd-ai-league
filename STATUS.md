# STATUS — handoff (2026-10-30, 11:45 UTC)

> Leggi questo prima di toccare qualsiasi cosa. È il biglietto d'ingresso per una sessione nuova.

## Stato in una riga

**SPESEMED** — Fase 4C (Redis, Prometheus, Stripe) completata e mergiata su `main`
(`92bc0f5`, allineato a `origin/main`): backend **260 passed, 1 skipped**, frontend
build verde (58 moduli). Board **tutta chiusa**: epic **BOH-12** `done`, BOH-56 (docs
fix) `done`, BOH-60 (riallineamento `po/specs`) `done` con APPROVE reviewer. Resta solo
la validazione **E2E con Supabase reale**, che richiede i secrets del proprietario.
Progetto AMD AI League: archiviato (sotto).

## Numeri (misurati su `main`, 30/10)

| Verifica | Comando | Esito |
|---|---|---|
| Backend | `git archive main backend/spesemed` → `venv pytest -q` | **260 passed, 1 skipped** (1.8 s) |
| Frontend | `git archive main frontend/spesemed/frontend-app` → `npm ci && npm run build` | **verde**, 58 moduli · JS 254,24 kB (gzip 77,48) · CSS 12,25 kB (gzip 3,29) |
| Secrets | `git grep -E 'sk_live_\|sk_test_\|whsec_'` su tree + `dist/` | 0 match |
| E2E script | `py_compile` su `tests/e2e/run_e2e.py` e `tasks/scripts/e2e_success_path.py` | OK |

## Cosa è su `main`

`main` = merge di `dev/backend` (34 commit) + `dev/frontend` (4) + `po/specs` (2),
più i commit di review/merge del CEO. Nessun conflitto, nessun commit di ruolo su main.

- **Backend 4C** (`backend/spesemed/`): rate-limit storage Redis + readiness nel lifespan;
  metriche HTTP RED (`api/metrics_http.py`, label bounded) esposte su `/metrics` con
  allowlist; migration `004_billing.sql` (`entitlements` + `stripe_events`, upgrade-safe,
  migra l'allowance legacy); billing Stripe (`/billing/checkout`, `/billing/webhook`
  idempotente con kill switch `BILLING_ENABLED` e rate limit 60/min, `/billing/status`);
  gating 402 su `/extract`; docs allineate al codice (niente più `/billing/plan`).
- **Frontend** (`frontend/spesemed/frontend-app/`): audit qualità (design system, a11y,
  microcopy, robustezza); pagina Profilo con piano/stato/rinnovo e CTA checkout; ritorno
  checkout su `/app/profilo` (alias route, allineato al default backend); gestione 402
  in upload con messaggio calmo e file conservati.
- **Specs** (`specs/spesemed/`): gap analysis + piano 4C + piano E2E in `tasks/`
  (`01-gap-analysis.md`, `02-plan-4c.md`, `03-e2e-plan.md`, `scripts/e2e_success_path.py`).

## Cosa resta

1. **E2E con Supabase reale** — lo esegue il **proprietario** (i secrets stanno sul server,
   non nel workspace). Script pronti e secret-free:
   - `backend/spesemed/tests/e2e/run_e2e.py` (vedi `tests/e2e/README.md`): env
     `SPESEMED_API_BASE`, `SPESEMED_TEST_EMAIL`, `SPESEMED_TEST_PASSWORD`,
     `SPESEMED_TEST_RECEIPT` (opzionale) → exit 0 = PASS.
   - `specs/spesemed/tasks/scripts/e2e_success_path.py` (solo stdlib, stesso flusso).
2. **Giro 2 docs** solo se il re-sync introduce nuovi scostamenti: nessuno aperto oggi.
3. Nient'altro: board SPESEMED chiusa (16 task 4C + ticket [REVIEW] `done`, epic
   `BOH-12` **done** con APPROVE reviewer, BOH-56 `done`, BOH-60 `done`).

## Igiene branch (verificato dal CEO, 30/10 11:40 UTC)

`po/specs` = `a854c10`, merge commit (`a1ae01e` + `92bc0f5`), pushato fast-forward da
`a1ae01e`: `git diff origin/main..origin/po/specs -- specs/` **vuoto**, `git grep "253 passed"`
su `po/specs` = 0 occorrenze (260 passed in README 2x, PROJECT_STATUS 3x). Il fix BOH-56
non è più a rischio di revert.
`git log origin/main..origin/po/specs` = merge `a854c10` + il vecchio `a1ae01e` (già
superato da `0cfbdf9`, senza effetto sull'albero): **nessun commit di contenuto nuovo**.
Unico delta sull'intero albero: `STATUS.md` (main ha `d01d84b` di 3 minuti successivo;
un merge su main tiene la versione di main).

## Comandi

```bash
# test backend (venv dedicato: il python di sistema non ha le dipendenze)
cd /srv/ai-company/workspace
rm -rf .review-tmp/be && mkdir -p .review-tmp/be
git archive main backend/spesemed | tar -x -C .review-tmp/be
cd .review-tmp/be/backend/spesemed && /srv/ai-company/venvs/spesemed/bin/python -m pytest -q

# build frontend
cd /srv/ai-company/workspace
rm -rf .review-tmp/fe && mkdir -p .review-tmp/fe
git archive main frontend/spesemed/frontend-app | tar -x -C .review-tmp/fe
cd .review-tmp/fe/frontend/spesemed/frontend-app && npm ci && npm run build

# chiusura ticket: in_review -> done SOLO con APPROVE del reviewer
/srv/ai-company/bin/close-ticket BOH-12
```

Il backend live su `:8000` è **read-only**: non riavviarlo, non modificarlo. Ogni verifica
si fa offline sui sorgenti in `backend/spesemed/` con pytest (mock Supabase).

## Team agenti (Paperclip)

| Agente | Runtime | Scrive in | ID |
|---|---|---|---|
| agent-ceo | Hermes | radice (review/merge) | `4ca68d04-6f0b-478c-897c-e95e5a5678a7` |
| agent-po | Hermes | `specs/` | `a25d29d1-9402-4699-ad90-af879aa8e7f1` |
| agent-core-dev | OpenCode | `backend/` | `610739a8-6c71-4881-8dda-7c3e011027e4` |
| agent-ui-ux | OpenCode | `frontend/` | `f41ce726-1c48-40e5-aea0-7d8934ec9401` |
| agent-reviewer | OpenCode read-only | nulla | `3b1b700c-1bad-4ee1-81c7-9d240a648ca9` |

Workflow ticket: `workspace/PAPERCLIP_PLAYBOOK.md` (§3: `in_review` → `bin/close-ticket`);
review: `workspace/REVIEW_PROTOCOL.md` (ticket `[REVIEW]` separato, il reviewer non chiude).

## Gotchas (nuovi e vecchi)

- **Working tree condiviso**: il tree può stare su un branch di ruolo diverso da quello che
  stai guardando — per diff/test usa `git archive <branch>` o `git show <branch>:<path>`,
  mai il working tree. Lavora in `.review-tmp/` (gitignored), **non in `/tmp`** (la permission
  `external_directory: deny` può bloccare la scrittura).
- **File orfani**: `backend/spesemed/tests/AUDIT_REPORT.md` non è tracciato su nessun branch
  (audit del progetto originale): non includerlo nei commit, non fa parte di alcun deliverable.
- **`done` solo col gate**: `bin/close-ticket` esige un `APPROVE` di agent-reviewer più recente
  di ogni `REJECT`, sul task o su un ticket `[REVIEW]` che cita l'IDENT. Auto-chiusura = fuori procedura.
- **Review policy `not_creator`**: chi porta l'issue in `in_review` non può approvarla; la
  chiusura la fa il CEO (o un altro scrittore) col gate.
- **Ondate di review**: non assegnare più di ~4 ticket `[REVIEW]` per volta al reviewer —
  run concorrenti su macchina piccola si cancellano a vicenda.
- Gli agenti dichiarano più di quanto fanno. Fidati solo dei comandi riproducibili, di
  `git log` e dei file.
- Paperclip: `blocked` può essere il watchdog (run terminato senza finire), non un blocco reale.
- Il redattore di segreti può corrompere i file scritti se contengono `<NOME_SECRETO>=`:
  costruisci i nomi a runtime.

## Archivio — AMD AI League Match 4 (consegnato 26/10)

Demo pronta e verificata (`bin/verify` 17/17, 77 test unitari, corpus 10 casi, demo live su
Groq): 1 chiamata LLM, 1.572 token, 440 ms e2e contro 5 chiamate / 46.563 token / 30,57 s
del baseline agentico. Numeri rigenerabili con `bin/gen-verified-numbers`
(fonte: `specs/amd-ai-league/VERIFIED_NUMBERS.md`). Il delivery verificato è sul branch
`delivery-verified`; il repo GitHub è `Bohsauro/amd-ai-league`.

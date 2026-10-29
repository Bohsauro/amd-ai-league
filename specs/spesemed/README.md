# SPESEMED — Onboarding per la company (kickoff)

> Micro-SaaS italiano: estrazione automatica spese mediche da ricevute (PDF/JPG)
> per assicurazione e dichiarazione 730. Backend FastAPI **già in produzione su :8000**
> (gunicorn, live), frontend SPA Vite+React18+TS **già costruito** in `frontend-app/`.
> Il lavoro residuo: **Fase 4C** (Redis, Prometheus, Stripe) + validazione E2E con
> Supabase reale + audit qualità frontend.

## Stato (fonte: PROJECT_STATUS.md, oct 2026)

- Fasi 0-3, 4A(web), 4B (Export Excel/ZIP), 4B+ (Profilo/usage) ✅ done
- pytest 135/135 offline (mock Supabase) + audit pre-go-live PASSED + GO_LIVE_RUNBOOK operativo
- Backend **live su http://localhost:8000** (gunicorn 2 worker, bind 0.0.0.0:8000) → `/api/v1/health` 200
- Flutter GUI rimossa (ott 2026) → la GUI web reale è `frontend-app/` (Vite+React18+TS, design "Verde Calma")
- **Resta**: Fase 4C (Redis rate-limit storage, Prometheus /metrics, Stripe billing) + validazione E2E success-path con secrets reali

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
- Migrations: `backend/spesemed/migrations/` (001_init.sql, 002_rls_policies.sql, 003_waitlist.sql)
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

## Lavoro residuo (in ordine di valore)

1. **Fase 4C backend**: Redis rate-limit storage (slowapi Redis-ready), Prometheus /metrics
   (già c'è `metrics.py` + `metrics_acl.py`: verificarne esposizione/conformità), Stripe billing.
2. **Validazione E2E success-path con Supabase reale** (health→signup→login→jobs→extract→export;
   200 OK reali) — richiede secrets: preparare script + istruzioni, l'esecuzione finale la fa il proprietario.
3. **Audit qualità frontend-app**: impeccable detect, build `npm run build` senza errori,
   aderenza DESIGN.md, accessibilità, gestione errori/loading, refresh token su 401.
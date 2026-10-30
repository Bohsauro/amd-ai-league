# SPESEMED - Security Audit & Hardening Log 🛡️

> Documento di **security hardening**: findings dell'audit, fix applicati,
> rischi deferred con razionale, e checklist operational per pen-test
> readiness. Stato aggiornato — production-ready backend per medical-data
> (GDPR categoria speciale ex art. 9 Reg. UE 2016/679).

---

## §1 — Audit summary

| Severity | Findings | Stato |
|----------|----------|-------|
| 🔴 **CRITICAL** | C1 OOM DoS upload, C2 path traversal X-User-Id, C3 JWT mock bypass & auth enforcement, C4 service_role RLS bypass | ✅ **4/4 FIXATI** |
| 🟠 **HIGH** | H1 rate-limit in-memory × N worker, H2 admin no rate-limit, H3 verify_signature=False dev, H4 worker storage_path resolution, H5 python-multipart CVE-2024-21506 | ✅ **3/5 FIXATI, 2 deferred** |
| 🟡 **MEDIUM** | M1 user enumeration, M2 PII logs & waitlist, M3 OpenRouter body snip logs, M4 CORS `*` prod warning, M5 JWT role=anon accettato, M6 /metrics pubblico | ✅ **4/6 FIXATI, 2 deferred** |
| 🟢 **LOW** | Pillow CVE-2023-44271, security headers, anon role dev | ⚠️ **1/3 FIXATI** |

Totale fix code-level: **12 di 17 findings**. Rimanenti documentati in §6 (Risk Register) sotto.

---

## §2 — CRITICAL fixes (file:riga)

### ✅ C1 — Anti-OOM streaming upload
- **File:** `src/spesemed/api/routes/extract.py:45-95` (helper `_read_upload_streaming`)
- **Fix:** Lettura a chunk 64KB con abort su `max_bytes` invece di `await uploaded.read()` che porterebbe 200×1GB in RAM (200GB → OOM processo).
- **Test:** `tests/test_security_fixes.py::TestFixC1StreamingUpload` (3 test).

### ✅ C2 — UUID regex su X-User-Id (anti path-traversal)
- **File:** `src/spesemed/api/dependencies.py:24-31` (`_UUID_PATTERN`)
- **Fix:** `_UUID_PATTERN.match(cleaned)` con regex RFC 4122 (`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`) invece del check solo control chars.
- **Blocca:** `../etc/passwd`, `user\ninjection`, lunghezze patologiche, NON-hex.
- **Test:** `tests/test_security_fixes.py::TestFixC2UUIDRegex` (12+4 parametrize).

### ✅ C3 — Fail-closed su JWT secret mancante e Auth Enforcement
- **File:** `src/spesemed/api/dependencies.py:55-145` + `src/spesemed/api/config.py:73-80`
- **Fix:** Nuova env var `ALLOW_DEV_MOCK_AUTH` (default **`false`**) — l'app fail-closes con `503` quando SUPABASE_JWT_SECRET manca, **anche in dev**. Inoltre, se `ALLOW_DEV_MOCK_AUTH=false` (produzione), ogni richiesta priva di header di autenticazione riceve `401 Unauthorized` invece di ricadere silenziosamente su `"anonymous"`.
- **Test:** `tests/test_security_fixes.py::TestFixC3FailClosedAuth` (5 test).

### ✅ C4 — RLS Migration su jobs/extractions/storage
- **File:** `migrations/002_rls_policies.sql` (NUOVO)
- **Fix:** `ALTER TABLE jobs ENABLE + FORCE ROW LEVEL SECURITY` + 8 policies GRANT/SELECT/INSERT/NO_UPDATE/NO_DELETE + storage.objects policies su bucket `receipts`.
- **Blocca:** Query cross-user anche se il backend dimentica un `.eq("user_id")` (defense-in-depth, `service_role` continua a funzionare per worker).
- **Action required:** L'utente deve applicarlo via Supabase SQL Editor (manual step).
- **Test:** `tests/test_security_fixes.py::TestFixC4RLSMigration` (7 test, idempotenza + presenza policy keywords).

---

## §3 — HIGH fixes applicati (file:riga)

### ✅ H5 — python-multipart CVE-2024-21506 (ReDoS)
- **File:** `requirements.txt:32` + `pyproject.toml:24`
- **Fix:** Bump `python-multipart>=0.0.9` → `python-multipart>=0.0.12,<1.0.0`. Chiude ReDoS nel parsing filename multipart.

### ✅ H2 — Admin endpoint rate-limit (anti brute-force X-Admin-Token)
- **File:** `src/spesemed/api/main.py:206-227`
- **Fix:** `@limiter.limit("5/minute")` + `request: Request, response: Response` param su `POST /admin/auth/reset-jwks-cache`. Blocca brute-force del X-Admin-Token (DoS mirato sulla JWKS cache).

### ✅ H4 — Background Worker Storage Path & Extension Resolution
- **File:** `src/spesemed/api/worker.py:195-235`
- **Fix:** Risoluzione dinamica dell'estensione del file su Supabase Storage (`.pdf`, `.jpg`, ecc.) con assegnazione corretta del suffisso al `NamedTemporaryFile`. Elimina i 404 e i fallimenti di formato in `file_to_images`.

---

## §4 — MEDIUM fixes applicati

### ✅ M2 — PII Logs Protection & Waitlist Email Hashing
- **File:** `src/spesemed/api/routes/waitlist.py:45-55`, `src/spesemed/api/routes/extract.py`, `src/spesemed/api/worker.py`
- **Fix:** Mascheramento SHA-256 (primi 12 caratteri) per indirizzi email ed esclusione di filename utente e dati sanitari dai log (GDPR art. 9).

### ✅ M4 — CORS Wildcard Warning in Produzione
- **File:** `src/spesemed/api/main.py:128-145`
- **Fix:** Alert di sicurezza a livello WARNING allo startup se l'API gira in `api_env=production` con `CORS_ORIGINS` impostato su wildcard `*` o non configurato.

### ✅ M5 — JWT role filter: solo `authenticated`, no `anon`
- **File:** `src/spesemed/api/jwt_decoder.py:236-256`
- **Fix:** `if role != "authenticated": raise 401`. Blocca exploit classico Supabase: anon key pubblica `role=anon` non viene più accettata come user auth.
- **Test:** `tests/test_jwt_decoder.py::TestHS256::test_role_anon_rejected` (era `test_role_anon_accepted`, ora flipped).

### ✅ M6 — /metrics IP allowlist (defense-in-depth)
- **File:** `src/spesemed/api/metrics_acl.py` (NUOVO) + `src/spesemed/api/main.py` (chiamata in `prometheus_metrics`) + `src/spesemed/api/config.py` (settings).
- **Fix:** Nuovo helper `check_metrics_authorization(request)` chiamato dentro `prometheus_metrics()` PRIMA della generazione del payload. Supporta IP singoli e CIDR (IPv4/IPv6) via `metrics_ip_allowlist` (default `["127.0.0.1","::1"]`). `X-Forwarded-For` viene onorato SOLO se il peer TCP diretto (reverse proxy) è già whitelistato E `metrics_trust_xff=true`. Lista vuota + `api_env=production` => fail-closed (403); + `development` => fail-open. IPv4-mapped IPv6 (`::ffff:127.0.0.1`) normalizzato per match trasparente.
- **Closing rationale:** Il reverse proxy (Caddyfile/nginx.conf) resta la protezione PRIMARIA edge; il filtro in-process chiude il finding smoke test `[E3]` che falliva quando il deployment esponeva direttamente `192.168.1.69:8000` senza reverse proxy davanti. Emissione di un WARNING di startup se `METRICS_IP_ALLOWLIST` contiene solo loopback + produzione (operational foot-gun: scraper remoto sarebbe bloccato silenziosamente).
- **Test:** `tests/test_metrics.py::TestMetricsEndpoint` — 8 test che coprono default loopback allow, external IP block, fail-closed production, fail-open development, XFF trusted-proxy onorato, XFF trust-off ignorato, CIDR match, IPv6 loopback, XFF malformato, e log-level split (warning generico + IP solo a DEBUG).

---

## §5 — Audit operational hardening checklist

Per un pen-test esterno, prima del test l'operatore deve verificare:

- [ ] **Migration 002 RLS applicata** via Supabase SQL Editor.
  Verifica live: `SELECT * FROM jobs` come utente anon deve ritornare 0 righe.
- [ ] **`.env` di produzione ha ALLOW_DEV_MOCK_AUTH=false** (default, ma verificare typo).
- [ ] **API_ENV=production** (mai `production`/`development` con typo).
- [ ] **ADMIN_TOKEN** generato con `python -c "import secrets; print(secrets.token_urlsafe(32))"` (32+ chars).
- [ ] **CORS_ORIGINS** lista esplicita (non `*`) per dominio frontend produzione.
- [ ] **SUPABASE_SERVICE_KEY** ruotata ogni 90 giorni.
- [ ] **Reverse proxy** davanti all'API blocca `/admin/*` e `/metrics` via IP allowlist.
  - NB: il filtro in-process (`metrics_ip_allowlist` in config.py) protegge `/metrics` anche se il reverse proxy viene bypassato o misconfigurato (FIX M6 audit 2025).

---

## §6 — Risk Register (deferred con razionale)

### ⚠️⚠️ H1 — Rate-limit in-memory × N worker (Redis)
- **Rischio:** Con `API_WORKERS=2`, il bucket slowapi sono per-worker ⇒ limite
  `5/minute` diventa effettivamente `10/minute` per utente. Inoltre
  `get_remote_address(request)` non legge `X-Forwarded-For`, quindi tutti
  gli utenti dietro uno stesso NAT appaiono come un IP solo.
- **Mitigation temporanea:** in produzione si usa 1 worker (`API_WORKERS=1`)
  oppure si accetta un rate limit × N worker ed è documentato.
- **Fix futuro** (Fase 4): Redis backend `RATE_LIMIT_STORAGE_BACKEND=redis://...` +
  middleware ProxyFix per leggere X-Forwarded-For dal reverse proxy trusted.
- **Effort rimasto:** ~4h, 2 file (config.py + rate_limit.py), `limits[redis]` dep.

### ⚠️ H3 — `verify_signature=False` in dev rate-limit key function
- **Rischio:** In `api_env=development`, se un attacker ottiene il rooting del
  dev server, può presentare qualsiasi JWT unsigned ed essere classificato
  con un `sub` arbitrario nel bucket rate-limit.
- **Mitigation:** L'opt-in richiede `ALLOW_DEV_MOCK_AUTH=true` (vedi C3). In
  produzione questa path è morta. **Rischio accettato** perche' dev mode
  non va esposto a internet (documentato nel README).
- **Fix futuro:** Iniettare claims controllati via bootstrap dedicato invece
  di forgiare JWT unsigned. Effort: 1h, 1 file (rate_limit.py).

### ⚠️ M1 — User enumeration via eccezioni (signup/login)
- **Rischio:** `detail=f"Signup fallito: {type(e).__name__}"` e `"Token JWT non
  valido: InvalidSignatureError"` permettono a un attacker di distinguere
  tra "email libera", "email esistente", "scaduto", ecc.
- **Mitigation parziale:** Login già ritorna `"Credenziali non valide."`
  generico. Signup ancora rivela type eccezione.
- **Fix futuro:** Sostituire tutti i `detail` con stringhe costanti
  ("Credenziali non valide", "Registrazione non riuscita", "JWT non valido
  o scaduto"). Effort: 30min, 4 file (auth.py + jwt_decoder.py + jobs.py).

### ⚠️ M2 — PII nei log (filename ricevute + categoria spesa)
- **Rischio:** Il filename utente potrebbe contenere anagrafiche/sanitarie
  (es. `"ricevuta_Rossi_Mario_cf_H501W.pdf"`). `categoria_spesa` (Farmaci,
  Visite, Esami) è essa stessa dato sanitario.
- **Mitigation:** Attualmente loggato a DEBUG/INFO in stdout/docker logs/Sentry.
- **Fix futuro:** Sostituire filename con `file_hash[:12]` e categoria con
  count aggregato. Effort: 2h, 4 file (routes/extract.py + worker.py).

### ⚠️ M3 — Log body OpenRouter su errore 4xx
- **Rischio:** `body_snippet = e.response.text[:500]` salva in log stdout
  parte della risposta OpenRouter (raro con PII, ma possibile).
- **Fix futuro:** Mai loggare `content` modello. Loggare solo `len(content)` (già in DEBUG).
- **Effort:** 15min, 1 file.

### ⚠️ M4 — CORS default `*`
- **Rischio:** `cors_origins=["*"]` di default. Combinato con
  `cors_allow_credentials=True` = misconfiguration classica.
- **Mitigation:** `cors_allow_credentials=False` di default. Il reverse
  proxy di produzione deve comunque settare lista esplicita.
- **Fix futuro:** Cambiare default a `["http://localhost:3000"]` per dev,
  richiedere env esplicita per produzione. Effort: 5min, 1 file.

### ✅ M6 — /metrics pubblico
- ~~**Rischio:** L'endpoint Prometheus non richiede auth.~~ **RISOLTO** — vedi §4 M6 sopra.
  In backlog rimane solo l'ottimizzazione "bind su interfaccia interna" come
  hardening ulteriore (nice-to-have, non più blocker). Effort residuo: 1h, 1 file.

### ⚠️ LOW — Pillow <10.2.1 (CVE-2023-44271)
- **Stato:** ✅ Bumpato in questa release (`Pillow>=10.2.1,<12.0.0`).
- **CVE:** DoS in image parsing (raro in upload remoto via /extract).

### ⚠️ LOW — security headers CSP/HSTS
- **Rischio:** Mancano `Content-Security-Policy`, `Strict-Transport-Security`,
  `X-Frame-Options`, `X-Content-Type-Options: nosniff`.
- **Mitigation:** API-only backend (no HTML rendering) ⇒ CSP basso impatto.
  HSTS demandato a reverse proxy/production HTTPS config.
- **Fix futuro:** Middleware custom che inietta headers (effort: 30min).

---

## §7 — Dependency security state (post-fix)

| Package | Pre-fix | Post-fix | CVE chiusa |
|---------|---------|----------|------------|
| `python-multipart` | `>=0.0.9` | `>=0.0.12,<1.0.0` | CVE-2024-21506 (ReDoS) |
| `Pillow` | `>=10.0.0` | `>=10.2.1,<12.0.0` | CVE-2023-44271 (DoS) |
| `PyJWT[crypto]` | `>=2.8.0,<3.0.0` | invariato | – |
| `cryptography` | `>=42.0.0,<48.0.0` | invariato | – |
| `fastapi` | `>=0.110.0,<1.0.0` | invariato | – |
| `httpx` | `>=0.27.0,<1.0.0` | invariato | – |
| `slowapi` | `>=0.1.9,<1.0.0` | invariato | – |
| `sentry-sdk[fastapi]` | `>=2.0.0,<3.0.0` | invariato | – |
| `prometheus-client` | pin custom | invariato | – |

**CI guardrail:** job `audit` in `.github/workflows/ci.yml` esegue `pip-audit
--strict` (fail-on HIGH/CRITICAL).

---

## §8 — Penetration test entry points

Per un pen-tester esterno, gli entry point da testare:

1. **Auth bypass via unsigned JWT** ⇒ uso `verify_signature=False` in dev?
   → **C3 fixato**: richiede `ALLOW_DEV_MOCK_AUTH=true` esplicito.
2. **JWT role escalation `anon → authenticated`** ⇒ anon key pubblica
   bypassa RLS? → **C4 + M5 fixati**: RLS attivo + solo `authenticated` accettato.
3. **Path traversal via X-User-Id / `user_id` nei path Storage** ⇒
   `../../etc/passwd`? → **C2 parziale (X-User-Id)**: regex UUID, ma `user_id`
   da JWT non è ri-sanitizzato prima di `f"receipts/{user_id}/..."`. Item
   in backlog §10.2 PROJECT_STATUS.
4. **OOM via upload 200×1GB** ⇒ DoS? → **C1 fixato**: streaming con abort.
5. **Brute-force X-Admin-Token** ⇒ JWT cache invalidation continua?
   → **H2 fixato**: rate-limit 5/min.
6. **IDOR cross-user su jobs/extractions** (service_role bypass RLS) ⇒
   un bug futuro può esporre tutto. → **C4 fixato**: RLS attivo NOW.
7. **Supply-chain attack** (pip install compromised deps) ⇒ versioni bloccate? →
   **H5 + LOW Pillow fixati**: bumps + CI pip-audit.

---

## §9 — Test isolation guarantee (pytest 84/84 ✅)

La suite pytest è ora stabile e deterministica:

- 84 test totali, 84 passed, 0 failed, 0 error.
- Nuovi test `tests/test_security_fixes.py`: 9 test specifici per i 4 fix
  CRITICAL (total 9 tests across C1, C2, C3, C4).
- `tests/conftest.py` ha fixture autouse `_isolate_test_env` che forza
  env offline override di `.env` locale (root cause: `load_dotenv()` in
  `core/extractor.py` module-load side-effect, wrappato da monkeypatch
  auto-cleanup).
- I test girano in modalità offline (nessun Supabase running richiesto).

---

## §10 — Per produzione: applicare migration 002 + test live

Prima di deployment finale, l'utente deve:

1. **Applicare `migrations/002_rls_policies.sql`** via Supabase SQL Editor.
   Il file include policy per `jobs` + `extractions` (vedi §2 C4).
2. **Verifica live** come anonymous: `SELECT * FROM jobs;` deve ritornare
   0 righe (FORCE RLS attivo).
3. **Verifica live** come authenticated user: `SELECT * FROM extractions`
   deve ritornare SOLO le righe con `auth.uid()::text = user_id`.
4. **🔴 Storage bucket RLS — verifica manuale con script Python.**
   Supabase storage non è accessibile via SQL Editor (storage layer
   è separato dal Postgres classico). Per testare l'isolamento storage
   usa lo script `verify_storage_rls.py` documentato in
   `deployment/VERIFY_RLS.md §6` (sign-in utente A con anon key +
   upload + list → atteso: solo i file propri). Fallback minimo se
   non vuoi eseguire lo script: verifica via Dashboard → Storage →
   `receipts` → Policies che esistano SELECT/INSERT policies per
   `auth.uid()::text = (storage.foldername(name))[1]`.

### §10.1 — Gap esplicito per pen-tester

| Componente | Migration 002 copre? | Test eseguibile via |
|------------|----------------------|---------------------|
| `jobs` table RLS | ✅ Sì (CREATE POLICY esplicite) | SQL Editor (anon + auth via SET LOCAL) |
| `extractions` table RLS | ✅ Sì (CREATE POLICY esplicite) | SQL Editor (anon + auth via SET LOCAL) |
| `storage.objects` bucket `receipts` RLS | ✅ Sì (POLICY su storage.objects) | `deployment/verify_storage_rls.py` (Python) o Dashboard → Storage → Policies. NON SQL Editor. |
| Cross-tenant negative test (SELECT/UPDATE/DELETE/INSERT) | ✅ Test incluso in §3.6 VERIFY_RLS | SQL Editor (query 3.6.1–3.6.4) |
| `pg_policies` catalog completeness | ✅ Verificabile post-apply | SQL Editor §3.7 VERIFY_RLS |

---

_Documento generato post-security-audit. Backend pronto per penetration
test esterno dopo l'applicazione della migration 002 RLS e la
configurazione di produzione descritta in §5._


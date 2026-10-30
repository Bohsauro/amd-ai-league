# SPESEMED — Guida al Test End-to-End 🧪

> Documento operativo: tutto ciò che serve per testare il backend FastAPI e
> la GUI Flutter, dal setup dei secret all'esecuzione dei flussi utente.
>
> **Prerequisiti generali**: Python 3.10+, Flutter 3.27+ (Dart 3.5+),
> account Supabase attivo, account OpenRouter con crediti.
>
> ⚠️ **Update ott 2026:** la GUI Flutter è stata rimossa dal repository e verrà
> ricostruita da zero (nuovo client, tech TBD). Le sezioni che riguardano
> l'app (§1.3, §3.2, §4 e le parti di §5-§8 legate alle schermate) restano
> come riferimento storico; il **backend FastAPI resta pienamente testabile
> in autonomia** con §1.1-§1.2, §2 e §3.1 (più i test offline: `pytest`).

---

## 0. Decisione rapida: cosa vuoi testare?

| Vuoi testare… | Sezione | Tempo |
|---|---|---|
| Solo Auth (login/signup/reset/delete) | [§4](#4-avvia-lapp-flutter) + [§5.1](#51-test-auth-senza-backend) | 5 min |
| Flusso completo (upload + estrazione AI) | [§1] → [§2] → [§3] → [§4] → [§5.2](#52-test-flusso-completo-con-backend) | 20-30 min |

**Regola d'oro**: le schermate Auth parlano direttamente con Supabase cloud
(via `supabase_flutter` SDK); le schermate Upload/Results/Jobs parlano con il
backend FastAPI. Per testare Upload/Jobs **devi accendere il backend**.

---

## 1. Prerequisiti di sistema

### 1.1 Poppler (per la conversione PDF nel backend)

Richiesto da `pdf2image` per convertire i PDF in immagini per il modello AI.

- **Windows**: scarica [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases),
  estrai e aggiungi `poppler-XX.X.X/Library/bin` al `PATH` di sistema.
  Verifica: apri un terminale nuovo e `pdftoppm -v` deve rispondere.
- **macOS**: `brew install poppler`
- **Ubuntu/Debian**: `sudo apt install poppler-utils`

### 1.2 Python + dipendenze backend

```bash
cd /c/Users/giova/Desktop/progetti/SPESEMED   # adatta al tuo percorso

# Crea e attiva venv (se non già fatto)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# Installa le dipendenze (usa pyproject.toml come fonte canonica)
pip install -e ".[dev]"
```

Verifica: `python -c "import spesemed.api.main; print('OK')"` → stampa `OK`.

### 1.3 Flutter SDK + dipendenze app

```bash
cd /c/Users/giova/Desktop/progetti/SPESEMED/flutter_app

# Verifica Flutter installato
flutter --version               # atteso: Flutter 3.27+ / Dart 3.5+

# Scaffolda le piattaforme se mancano (già fatto in questo progetto)
# flutter create . --project-name spesemed_auth --org com.spesemed --platforms android,ios,web

# Installa le dipendenze Dart
flutter pub get
```

Verifica: `flutter analyze` → "No issues found!".

---

## 2. Setup Supabase (DB + Storage + Auth)

> Saltare questa sezione SOLO se testi esclusivamente Auth (Supabase Auth è
> già attivo di default sui nuovi progetti). Per Upload/Jobs serve lo schema DB.

### 2.1 Crea/apri un progetto Supabase

1. Vai su [supabase.com](https://supabase.com) → New Project (o usa uno esistente).
2. Annota il **Project URL** (`https://<project-ref>.supabase.co`) da
   Settings → API.

### 2.2 Applica la migration `001_init.sql` (schema jobs + extractions)

1. Dashboard Supabase → **SQL Editor** → New query.
2. Apri il file `migrations/001_init.sql` locale, copia tutto, incolla nell'editor.
3. Click **Run** (Ctrl+Enter). Atteso: "Success. No rows returned".
4. Verifica: esegui `SELECT count(*) FROM jobs;` → deve tornare `0` (tabella esiste).

### 2.3 Applica la migration `002_rls_policies.sql` (sicurezza, opzionale ma raccomandato)

1. Stesso SQL Editor, incolla il contenuto di `migrations/002_rls_policies.sql`.
2. **Run**. Atteso: "Success. No rows returned".
3. Verifica: `SELECT tablename, policyname FROM pg_policies WHERE tablename IN ('jobs','extractions');`
   → almeno 6 policies elencate.

> La RLS filtra per `auth.uid()::text = user_id`. Il backend usa la
> `service_role` key (bypassa RLS), quindi i test backend non sono influenzati.
> La RLS protegge invece un client diretto con anon key.

### 2.4 Crea il bucket Storage `receipts` (privato)

1. Dashboard Supabase → **Storage** → **New bucket**.
2. Name: `receipts` → **Public: OFF** (deve essere PRIVATO) → **Save**.
3. Verifica: il bucket mostra l'icona 🔒 (lock).

### 2.5 Configura Auth per i test

Dashboard Supabase → **Authentication** → **Providers** → **Email**:
- **Enable email signup**: ON
- **Confirm email**: ON (per testare EmailVerificationScreen)
  - OPPURE OFF se vuoi login immediato senza verifica (più veloce per smoke test).

**Per test rapidi**: crea un utente da Dashboard → Authentication → Users →
**Add user** con email + password + **Auto Confirm User: ON** (salta la verifica email).

### 2.6 Recupera i 4 secret per il backend `.env`

Dalla stessa dashboard, Settings → **API**:

| Secret | Dove | Note |
|---|---|---|
| `SUPABASE_URL` | "Project URL" | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_KEY` | "service_role key" (NON anon!) | ~250 chars JWT, `role=service_role` nel payload |
| `SUPABASE_JWT_SECRET` | "JWT Secret" (tab Advanced) | Solo per progetti HS256 (legacy); lascia vuoto se ES256 moderno |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | Richiede account + crediti (min $5) |

> **Verifica service_role vs anon**: incolla la key su [jwt.io](https://jwt.io),
> il campo `role` nel payload deve essere `service_role` (NON `anon`).

---

## 3. Configura i file `.env`

### 3.1 Backend (`.env` nella root del progetto)

Il file `.env` esiste già ma i 4 secret sono vuoti. Apri `.env` e popola:

```ini
# --- OpenRouter ---
OPENROUTER_API_KEY=sk-or-v1-la-tua-chiave-reale-qui

# --- Supabase ---
SUPABASE_URL=https://tuo-project-ref.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...la-tua-service-role-key...
SUPABASE_JWT_SECRET=il-tuo-jwt-secret          # vuoto se progetto ES256 moderno

# --- Dev mode (per test locali) ---
API_ENV=development
ALLOW_DEV_MOCK_AUTH=false                       # true solo se vuoi X-User-Id mock
ALLOW_SIGNUP=true                               # false in prod
```

Gli altri valori (`CORS_ORIGINS`, rate limits, ecc.) hanno default sensati per dev.

> NB: se nel `flutter_app/.env` non hai ancora `API_BASE_URL`, il default in
> dev mode è `http://10.0.2.2:8000` (emulatore Android). Per web/desktop vedi §3.2.

### 3.2 Flutter app (`flutter_app/.env`)

Il file ha già `SUPABASE_URL` + `SUPABASE_ANON_KEY`. **Aggiungi `API_BASE_URL`**
in base a dove lanci l'app:

| Target test | `API_BASE_URL` da impostare | Perché |
|---|---|---|
| Emulatore Android | `http://10.0.2.2:8000` (default, anche se omesso) | `10.0.2.2` mappa all'host del PC |
| Chrome / Web | `http://localhost:8000` | Browser gira sul PC stesso |
| Windows desktop | `http://localhost:8000` | App gira sul PC stesso |
| Dispositivo fisico (phone) | `http://<IP-PC-sulla-stessa-WiFi>:8000` (es. `http://192.168.1.69:8000`) | Il phone raggiunge il PC via LAN |

Esempio `flutter_app/.env` completo:

```ini
SUPABASE_URL=https://tuo-project-ref.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...la-tua-anon-key...   # pubblica, NON service_role
API_BASE_URL=http://localhost:8000                 # adatta al target (vedi tabella)
```

> ⚠️ **Mai** mettere la `service_role` key nel `flutter_app/.env`: l'app usa
> l'**anon key** (pubblica, vincolata da RLS). La service_role serve solo al backend.

### 3.3 Supabase Auth: configurazione deep-link (solo se testi reset password via email)

Per testare il flusso `forgot password → email → reset`:
- **Web**: il `flutter_app/web/index.html` deve gestire il redirect magic link.
- **Android**: intent filter in `android/app/src/main/AndroidManifest.xml`.
- **iOS**: universal link in `ios/Runner/Info.plist` (richiede dominio HTTPS).

Per smoke test locali puoi saltare: usa la Dashboard Supabase → Authentication →
Users per resettare la password manualmente.

---

## 4. Avvia l'app Flutter

### 4.1 Avvia il backend (solo se testi Upload/Results/Jobs)

In un terminale **separato** (rimane aperto):

```bash
cd /c/Users/giova/Desktop/progetti/SPESEMED
.venv\Scripts\activate           # attiva venv se non già attivo

# Avvia in dev mode (auto-reload sui cambiamenti)
python -m uvicorn spesemed.api.main:app --host 0.0.0.0 --port 8000 --reload
```

- `--host 0.0.0.0`: raggiungibile da dispositivo fisico via LAN (non solo localhost).
  Per test solo Chrome/desktop basta `--host 127.0.0.1`.
- `--reload`: riavvia automaticamente al salvataggio di file Python.

### 4.2 Smoke test backend (verifica che sia up)

In un **altro** terminale:

```bash
# 1. Health check (deve tornare 200). Verifica anche openrouter_configured.
curl http://localhost:8000/api/v1/health
#   Atteso: {"status":"ok","openrouter_configured":true,...}
#   Se openrouter_configured=false → OPENROUTER_API_KEY non caricata
#     (verifica .env e che uvicorn sia partito dalla root del progetto).

# 2. Login reale (se Supabase Auth configurato + utente creato in §2.5).
#    Verifica end-to-end: backend -> Supabase Auth -> JWT.
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@spesemed.it","password":"Password123"}'
#   Atteso: 200 + {"access_token":"eyJ...","user_id":"..."}
#   401 = credenziali sbagliate o email non confermata
#   503 = Supabase non configurato (SUPABASE_URL/SERVICE_KEY vuoti nel .env)
#   429 = rate-limit 5/minuto: aspetta 60s o usa un altro utente
```

> **NB su X-User-Id mock**: l'header `X-User-Id` richiede `ALLOW_DEV_MOCK_AUTH=true`
> nel `.env` backend E un UUID RFC 4122 valido (es.
> `00000000-0000-4000-8000-000000000001`), NON stringhe arbitrarie. Con il
> default `false` (raccomandato), l'app fail-closes con 503. Per test rapidi
> senza Supabase reale, imposta `ALLOW_DEV_MOCK_AUTH=true` + usa un UUID
> valido; per test realistici usa il login (punto 2 sopra).
>
> Non usiamo `/extract` come smoke test qui perché richiede multipart + auth
> + Supabase + OpenRouter tutti configurati: troppi moving parts per un
> check "il backend è up?". `/health` + `/auth/login` coprono i due layer
> critici (config caricata + Supabase Auth raggiungibile).

### 4.3 Avvia la Flutter app

In un **terzo** terminale:

```bash
cd /c/Users/giova/Desktop/progetti/SPESEMED/flutter_app
flutter run -d chrome          # web
# flutter run -d windows       # desktop Windows
# flutter run -d <device-id>   # emulatore o device fisico (flutter devices per lista)
```

Primo avvio: `flutter pub get` + build iniziale (~30-60s). L'app apre su
`/login`. Se vedi `ErrorApp` con "Configurazione mancante" → `flutter_app/.env`
non ha `SUPABASE_URL` o `SUPABASE_ANON_KEY` (in release manca anche `API_BASE_URL`).

---

## 5. Scenari di test

### 5.1 Test Auth (senza backend)

Non serve il backend acceso. Testa in ordine:

1. **Signup** (`/signup`): email + password (min 8 char, 1 maiuscola, 1 numero)
   + accetta ToS → snack "Registrazione riuscita".
   - Se "Confirm email" ON → redirect a `/email-verification`.
   - Se OFF → redirect a `/home` (login automatico).

2. **Email verification** (`/email-verification`): se sei qui,
   - Apri la casella email → clicca il link → torna nell'app
   - Click "Ho verificato, continua" → refresh sessione → redirect `/home`.
   - Click "Invia di nuovo l'email" → cooldown 60s sul bottone.

3. **Login** (`/login`): email + password → redirect `/home` (o
   `/email-verification` se email non confermata).
   - Test 401: password sbagliata → banner "Credenziali non valide".
   - Test rate-limit: 5 login falliti rapidi → 429 "Troppe richieste".

4. **Forgot password** (`/forgot-password`): inserisci email →
   snack "Se l'email esiste, riceverai a breve un link".
   - Anti-enumeration: stesso messaggio anche se email non esiste.

5. **Reset password** (`/reset-password`): clicka il link nell'email →
   l'app rileva `PASSWORD_RECOVERY` → screen reset → nuova password →
   snack "Password aggiornata" + logout automatico → `/login`.

6. **Change password** (`/change-password`, da `/home`): nuova password →
   snack "Password aggiornata" + pop.

7. **Delete account** (`/delete-account`, da `/home`):
   - Spunta "Ho capito che questa azione è irreversibile"
   - Click "Elimina il mio account" → dialog → digita `ELIMINA` → conferma.
   - Snack "Account eliminato" → redirect `/login`.

8. **Logout** (icona in AppBar di `/home`): sessione cancellata → redirect `/login`.

**Comandi rapidi**:
```bash
# Per smoke test senza UI: crea utente via Dashboard Supabase
# (Authentication → Users → Add user → Auto Confirm ON) poi login diretto.
```

### 5.2 Test flusso completo (con backend)

**Prerequisiti**: backend acceso (§4.1) + smoke test verdi (§4.2) + utente
autenticato nell'app (§5.1 step 3).

#### 5.2.1 Upload sync (≤ 3 file)

1. Da `/home` → "Carica ricevute".
2. Click "Galleria" → seleziona 1-3 immagini/PDF di ricevute mediche reali.
   - Oppure "Fotocamera" → scatta una foto a una ricevuta.
3. Vedi l'anteprima lista file (nome + dimensione + thumbnail per immagini).
4. Click "Estrai N ricevute con AI" → spinner.
5. **Atteso**: redirect a `/results` con:
   - Summary card (count + modello usato, es. `gemini-2.5-flash-lite`)
   - Una card per ricevuta con: esercente, data, importo (€), categoria, CF.
   - Badge "Cache" se reinvi lo stesso file (idempotency cache lato backend).

**Tempo**: ~2-5s per file (chiamata OpenRouter). Se timeout → verifica crediti
OpenRouter e connessione rete.

#### 5.2.2 Upload async (> 3 file)

1. Da `/home` → "Carica ricevute" → seleziona 4-50 file.
2. Click "Estrai N ricevute con AI".
3. **Atteso**: redirect a `/jobs` con `jobId` in polling.
4. Screen dettaglio job mostra:
   - Status card: `In coda...` → `Elaborazione in corso...` → `Completato!`
   - Progress bar `X / N file processati` (polling ogni 2s).
   - Al `done`: lista risultati (stesso formato di `/results`).
   - Al `failed`: card errore con `job.error` (es. "OpenRouter timeout").

**Tempo**: dipende da N file + coda worker. Il worker polla ogni 2s.

#### 5.2.3 Storico jobs

1. Da `/home` → "Storico elaborazioni" (`/jobs` senza `jobId`).
2. **Atteso**: lista paginata (20 per pagina) dei job dell'utente, ordinati per data.
3. Scroll in fondo → "load more" automatico (offset pagination).
4. Click su una card → dettaglio job (polling se ancora attivo).
5. Pull-to-refresh → ricarica la lista.

**Verifica isolamento multi-utente**: crea un secondo utente, loggati, verifica
che vedi SOLO i tuoi job (non quelli dell'utente A). Se vedi job altrui →
RLS non applicata o backend non filtra per `user_id` (bug).

---

## 6. Troubleshooting

| Sintomo | Causa probabile | Fix |
|---|---|---|
| `ErrorApp` "Configurazione mancante" al boot | `flutter_app/.env` senza `SUPABASE_URL`/`SUPABASE_ANON_KEY` | Popola il `.env` (§3.2) e riavvia |
| `ErrorApp` "API_BASE_URL mancante" (solo release) | Build release senza `API_BASE_URL` nel `.env` | Aggiungi `API_BASE_URL` (§3.2) o testa in debug mode |
| Login 401 "Credenziali non valide" | Password sbagliata OPPURE email non confermata | Verifica `emailConfirmedAt` in Dashboard Supabase → Users |
| Login 429 "Troppe richieste" | Rate-limit 5/minuto attivato | Aspetta 60s o usa un utente diverso |
| Upload → "Errore di rete" | Backend non acceso OPPURE `API_BASE_URL` sbagliato | Verifica backend up (§4.2) + `API_BASE_URL` coerente col target |
| Upload → 503 "OPENROUTER_API_KEY non configurata" | Secret vuoto nel `.env` backend | Popola `OPENROUTER_API_KEY` (§3.1) + riavvia uvicorn |
| Upload → 503 "Supabase non configurato" | `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` vuoti | Popola i secret (§3.1) + riavvia uvicorn |
| Upload → errore estrazione "ref=nohash" | OpenRouter irraggiungibile o crediti esauriti | Verifica crediti su openrouter.ai/credits + connessione |
| Job resta "pending" all'infinito | Worker non partito (Supabase non configurato al boot) | Verifica log uvicorn: "JobWorker started" deve apparire |
| `/jobs` vuoto anche dopo upload | Query filtra per `user_id` del JWT; mismatch tra auth app e backend | L'app usa il JWT Supabase → il backend estrae `sub` come `user_id`. Verifica che l'upload usi lo stesso utente |
| Email di verifica non arriva | Supabase email rate-limit o spam | Dashboard → Authentication → Users → resend; controlla spam |
| `pdftoppm: command not found` | Poppler non installato/non nel PATH | Installa Poppler (§1.1) + riavvia terminale |
| Flutter "No issues found" ma app non parte | Cache stale | `flutter clean && flutter pub get && flutter run` |

### 6.1 Log utili per debug

- **Backend**: log uvicorn nel terminale dove l'hai lanciato (livello INFO in dev).
  Per debug verboso: `--log-level debug`.
- **App**: `flutter run -v` per log Dart verbosi; console del browser per web.
- **Supabase**: Dashboard → Logs → Auth logs (login falliti, email inviate).

### 6.2 Reset stato per ripartire da zero

```bash
# Backend: reset singleton client (se test multipli cambiano config)
# (nessun comando: basta riavviare uvicorn)

# Supabase DB: pulisci tabelle (SQL Editor)
DELETE FROM extractions;
DELETE FROM jobs;

# Supabase Storage: svuota bucket (Dashboard → Storage → receipts → elimina file)

# App: clear cache
cd flutter_app
flutter clean && flutter pub get
```

---

## 7. Checklist finale pre-test

- [ ] Poppler installato (`pdftoppm -v` risponde)
- [ ] Python venv attivato + `pip install -e ".[dev]"` fatto
- [ ] Flutter 3.27+ installato + `flutter pub get` fatto
- [ ] Progetto Supabase attivo + migration `001_init.sql` applicata
- [ ] (Opz) migration `002_rls_policies.sql` applicata
- [ ] Bucket Storage `receipts` creato PRIVATO
- [ ] Utente test creato in Supabase Auth (Auto Confirm ON per rapidità)
- [ ] `.env` backend: 4 secret popolati (`OPENROUTER_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`)
- [ ] `flutter_app/.env`: `SUPABASE_URL` + `SUPABASE_ANON_KEY` + `API_BASE_URL` (per target test)
- [ ] Backend avviato (`uvicorn ... --reload`) + `/api/v1/health` torna 200
- [ ] App avviata (`flutter run -d <target>`) + login riuscito

---

## 8. Comandi rapidi (copy-paste)

```bash
# === Backend ===
cd /c/Users/giova/Desktop/progetti/SPESEMED
.venv\Scripts\activate
python -m uvicorn spesemed.api.main:app --host 0.0.0.0 --port 8000 --reload

# Smoke test backend (altro terminale) — vedi §4.2 per gli status attesi
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@spesemed.it","password":"Password123"}'
# NB: per test /extract con X-User-Id (mock) vedi §4.2 — richiede
#     ALLOW_DEV_MOCK_AUTH=true + UUID RFC 4122 valido, NON stringhe arbitrarie.

# === Flutter app ===
cd /c/Users/giova/Desktop/progetti/SPESEMED/flutter_app
flutter run -d chrome          # web
# flutter run -d windows       # desktop
# flutter run -d <device-id>   # mobile (flutter devices per lista)

# === Test suite (senza app) ===
cd /c/Users/giova/Desktop/progetti/SPESEMED
python -m pytest tests/ -q             # backend offline (114 test)
cd flutter_app && flutter test          # app validators + widget (18 test)
```

---

_Guida generata per il test end-to-end di SPESEMED (backend FastAPI + Flutter app).
Per il go-live in produzione: vedi `GO_LIVE_RUNBOOK.md` (4 azioni Supabase + secrets reali)._

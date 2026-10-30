# TASK.md — Build frontend SPESEMED (delegata ad agy)

> Documento self-contained per chi implementa il frontend reale di SPESEMED.
> Lavora **in questa cartella** (`frontend-app/`). Non toccare il backend
> (`../src/`, `../migrations/`): è read-only per riferimento.

## Obiettivo

Costruire il **frontend web reale** di SPESEMED (micro-SaaS italiano di spese
mediche) come SPA cliente completo, che consuma il backend FastAPI esistente.
Stack: **Vite + React 18 + TypeScript**. Package manager: **npm** (Node 24).
Router: React Router. Stile: sistema "Verde Calma" (vedi riferimenti).

## Riferimenti (leggere PRIMA, non inventare)

- `../frontend/DESIGN.md` — tokens e sistema visivo (palette, tipografia
  Manrope + JetBrains Mono, componenti, regole anti-pattern). **È la fonte
  autoritativa dei colori/tipi.**
- `../frontend/PRODUCT.md` — verità di prodotto: pubblico, tono, funzioni.
- `../frontend/verde-calma.html` — mockup navigabile (landing + app) già
  approvato: è il riferimento visivo stretto per layout e microcopy.
- **Backend (per il contratto API ESATTO — non indovinare le forme JSON):**
  - `../src/spesemed/api/routes/*.py` (endpoints e behaviour: auth, extract,
    jobs, summary, export, health)
  - `../src/spesemed/api/schemas.py` (DTO Pydantic: request/response ESATTI)
  - `../src/spesemed/core/models.py` (campo `SpesaMedica` ed estrazione)
  - `../src/spesemed/api/config.py` (env-vars, default `max_sync_files` ecc.)

Deriva endpoint, metodi, header, e shape JSON leggendo il sorgente e
riportandoli in `src/lib/api.ts` come client tipizzato.

## Backend — contratto atteso (verificare nel sorgente)

- Base URL da env `VITE_API_BASE_URL` (default `http://localhost:8000`),
  prefisso `/api/v1`.
- **Auth** (Supabase JWT HS256, audience `authenticated`):
  - `POST /auth/signup` → 201 `{user_id}`
  - `POST /auth/login` → 200 tokens | 401 | 503
  - `POST /auth/refresh` → 200 nuovi token | 401
  - `POST /auth/logout` → 204 (best-effort)
  - Header `Authorization: Bearer <jwt>`. In **dev** (toggle in config) userà
    header `X-User-Id` se non c'è token (fallback mock del backend). In prod
    mai `X-User-Id`.
- **Extraction**: `POST /extract`, multipart, campo `files` (lista). File
  ammessi: PDF, JPG, JPEG, PNG, WEBP, BMP. Comportamento sync/async: fino a
  `max_sync_files` (default 3) → risposta sincrona con i risultati; oltre →
  `202` con `{job_id}` da pollare.
- **Jobs**: `GET /jobs` (storico utente), `GET /jobs/{id}` (stato async).
- **Summary**: `GET /summary` → riepilogo spese (totale, conteggio, per
  categoria) vedi `schemas.py` per campi esatti.
- **Export**: `POST /export` → risposta binaria ZIP (Excel + ricevute
  rinominate `YYYY-MM-DD_esercente_importoCAT.ext`). Trigger download.

## Cosa implementare

Rotte/pagine (React Router):
1. **`/`** — Landing (da `verde-calma.html`, sezione Landing).
2. **`/login`** e **`/signup`** — card centrata, validazione inline (forza
   password per signup), errori amichevoli in italiano.
3. **`/app`** (protette) con underlay navigazione: **Dashboard**, **Carica**,
   **Risultati**, **Storico**, **Esporta**, **Profilo**.
   - **Dashboard**: banda riepilogo da `GET /summary` (totale esportabile,
     conteggio, chips per categoria) + ultime spese + job recenti.
   - **Carica**: drop-zone (drag&drop + click/file input), validazione
     estensioni e limite, multipli. Chiama `POST /extract`: se sync mostra i
     risultati; se async mostra `{job_id}` e **polling** `GET /jobs/{id}`
     (stato + avanzamento) fino a done/failed, con stale timer.
   - **Risultati**: lista spese estratte con campi editabili (data, esercente,
     importo, categoria, CF), stato "validato/in attesa", **conferma salva**.
   - **Storico**: `GET /jobs` con stato, esporta per job quando disponibile.
   - **Esporta**: spiegazione + `POST /export` → scarica ZIP (usa `fetch` +
     `blob` + download; gestisci errori e loading).
   - **Profilo**: logout (best-effort `POST /auth/logout` + cleanup token) +
     refresh token.
6. Gestione token: store in memoria + `localStorage` (documenta il trade-off),
   axios/fetch wrapper che aggiunge Bearer, auto-refresh on 401, logout su 403.

## Requisiti non funzionali

- Tipo **TypeScript strict**, niente `any` evitabile.
- Applicare i tokens Verde Calma (nessun colore hardcoded fuori dalle var).
- **Accessibilità e qualità** come da `DESIGN.md`: hit target ≥44px, focus
  states, `prefers-reduced-motion`, contrasti WCAG AA, semantic HTML.
- Responsive (mobile first), niente overflow orizzontale.
- Microcopy in italiano, calmo e concreto. Cento dati sensibili: mostra i
  badge di fiducia ("Bucket privato", "CF validato") nel flusso.
- Niente emoji; icone SVG minimali solo dove aiutano la scansione.
- Non introdurre backend: nessun bisogno di secrets reali per compilare
  (usa un client che fallisce gracefully se `VITE_API_BASE_URL` non punta a
  un backend attivo).

## Ambiente

- Node v24, npm 11 (usa npm). Niente pnpm.
- Scaffold Vite + React + TS + React Router direttamente qui.
- Verifica finale obbligatoria: `npm run build` in **nessun errore**.

## Deliverable

- App completa in questa cartella, con `README.md` breve (come avviare:
  `.env.example` con `VITE_API_BASE_URL`; `npm i && npm run dev`; `build`).
- Riepilogo finale: cosa hai costruito + output di `npm run build`.
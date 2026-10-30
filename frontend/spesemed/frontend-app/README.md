# SPESEMED — Frontend Web Client

SPA web in **React 18 + TypeScript + Vite** per **SPESEMED** (Spese Mediche Smart), costruita secondo il design system **Verde Calma** (`../frontend/DESIGN.md` e `../frontend/verde-calma.html`) e collegata agli endpoint dell'API FastAPI.

## Funzionalità Principali

- **Landing Page**: Replica pixel-accurate del mockup approvato, con hero, spiegazione "Come funziona", garanzie di privacy GDPR e form interattivo per la lista d'attesa (`POST /api/v1/waitlist`).
- **Autenticazione**: `/login` e `/signup` con card centrata, validazione inline della complessità password, gestione errori in italiano, token rotation automatico.
- **Dashboard (`/app/dashboard`)**: Totale esportabile e riepilogo per categorie fiscali (`GET /api/v1/summary`), ultime spese registrate e stato dei job recenti.
- **Carica Ricevute (`/app/upload`)**: Drop-zone drag & drop con validazione estensioni (.pdf, .jpg, .png, .webp, .bmp) e limiti. Auto-routing:
  - Fino a 3 file: estrazione sincrona (`POST /api/v1/extract`).
  - Oltre 3 file: estrazione asincrona (`202 Accepted`) con polling su `GET /api/v1/jobs/{id}`, barra di avanzamento e timer stale.
- **Risultati (`/app/results`)**: Spese estratte con campi editabili (data `YYYY-MM-DD`, categoria, importo, codice fiscale, esercente) e verifica validità del CF.
- **Storico (`/app/jobs`)**: Elenco paginato dei lavori dell'utente con download diretto dell'archivio per singolo job.
- **Esporta (`/app/export`)**: Generazione e download binario dello ZIP per il commercialista (`POST /api/v1/export`) contenente Excel riepilogativo e file rinominati `YYYY-MM-DD_esercente_importoCAT.ext`.
- **Profilo (`/app/profile`)**: Informazioni sessione, rinnovo manuale token (refresh) e logout sicuro.

## Gestione Token & Trade-off Architetturale

La gestione delle credenziali di autenticazione adotta un approccio **ibrido**:
- **Stato in memoria di runtime**: L'access token JWT è gestito tramite Context React e consumato dal wrapper `fetch` in `src/lib/api.ts`.
- **Persistenza in `localStorage`**: Consente la continuità della sessione ai reload del browser.
- **Sicurezza**: I token sono protetti da Refresh Token Rotation (ogni refresh invalida il token precedente). In caso di errore 401, il client tenta un singolo rinnovo coordinato prima di invalidare la sessione; in caso di 403, viene eseguito il logout immediato.

## Requisiti di Sistema

- Node.js 24+
- npm 11+

## Avvio Rapido

1. **Configurazione ambiente**:
   Copia il file `.env.example` in `.env`:
   ```bash
   cp .env.example .env
   ```
   Verifica che `VITE_API_BASE_URL` punti al backend (predefinito: `http://localhost:8000`).

2. **Installazione dipendenze**:
   ```bash
   npm install
   ```

3. **Avvio in sviluppo**:
   ```bash
   npm run dev
   ```
   L'applicazione sarà disponibile su `http://localhost:3000`.

4. **Compilazione per produzione**:
   ```bash
   npm run build
   ```
   Esegue il controllo statico dei tipi con TypeScript (`tsc`) e il bundle con Vite (`vite build`) generando la directory `dist/`.

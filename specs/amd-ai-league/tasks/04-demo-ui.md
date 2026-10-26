# Task 04 — Demo UI single-file (numeri reali, zero fake)

**Assegnatario:** agent-ui-ux · **Output:** `frontend/index.html` (+ `frontend/run.json`)

**Criteri di accettazione:** `PLAN.md` §4.4 (AC-UI, U1–U6). Il contratto dati è `BUILD_SPEC.md` §2.8 +
`schemas/run.schema.json`: la UI legge SOLO quei campi, nessun numero hardcoded, empty-state se manca `run.json`.

Leggi `specs/amd-ai-league/DEMO_SCRIPT.md` e `BUILD_SPEC.md` prima di iniziare.
Vanilla JS + CSS, nessun framework, nessun build step.

1. Pannello sinistro: diagramma del flusso — snippet in ingresso → NOUL (i droppati
   lampeggiano rossi e cadono) → SCORE (barre orizzontali animano sul punteggio) → CHOICE
   (coppie in conflitto collegate da linea rossa a zig-zag) → GENERATOR (pulse verde).
   Label con i ms per stage presi dal JSON della pipeline.
2. In alto: due contatori live, gli UNICI numeri animati:
   - E2E LATENCY (ms) che sale per stage, con barra grigia statica "agentic baseline: …ms"
   - TOKENS SAVED cumulativo, stile odometro, "-12,480 · -92%"
3. Sezione "What the GPU never saw": split-screen blob di token grezzi (sinistra, muro di
   testo grigio caotico) vs contesto curato 940 token (destra, card pulite colorate).
4. Sezione throughput: 10 righe query parallele che completano sotto 1s.
5. Consuma l'output REALE di `pipeline.py`: legge `run.json` (copia in `frontend/run.json`
   dal `backend/run.json` prodotto con `--dump-json`) e anima da numeri misurati.
   Se `run.json` manca: empty-state, mai dati finti.
6. Estetica: sfondo scuro, numeri monospace, un solo accento (verde), zero decorazioni.
   Deve sembrare un pannello strumenti, non una landing page.

**Definition of done:** aprendo `index.html` dopo un run reale si vedono esattamente le latenze
e i token di quel run; ogni sezione sta in uno schermo 1920x1080 per la registrazione pulita.

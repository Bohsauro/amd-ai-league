# PRODUCT.md — SPESEMED (verità di prodotto duratura)

> Compilato seguendo `/impeccable init` (ott 2026), partendo dall'analisi dei
> documenti del repo (README.md, PROJECT_STATUS.md, TEST_GUIDE.md, SECURITY.md).
> Questo file tiene i fatti duraturi del prodotto separati dalla direzione
> visiva (che vive in `DESIGN.md`).

## Chi è il prodotto

SPESEMED ("Spese Mediche Smart") è un micro-SaaS italiano che automatizza la
gestione delle spese mediche: OCR + estrazione AI delle ricevute, validazione,
organizzazione per categoria e **esportazione pronta per il commercialista /
assicurazione / 730**.

## Pubblico

Utente finale italiano, NON tecnico, spesso in fascia 40-70 anni che deve fare
il 730 o richiedere rimborsi. Vede strade di friczioni: accumulare scontrini
parlanti, parcelle dentisti/oculisti, ticket SSN, ricevute esami; trovare file
con nomi inutili (`IMG_20240115.jpg`); reinserirli a mano.

## Problema che risolve

Trasforma ricevute mediche (PDF anche multipagina, JPG, PNG, WEBP, BMP) in dati
strutturati e validati, esportabili in Excel e ZIP rinominati per il 730.

## Cosa fa (funzioni core documentate)

1. **Carica** ricevute in blocco.
2. **Estrae** via AI (OpenRouter + modello multimodale) i campi:
   `data_spesa`, `esercente`, `importo_totale`, `codice_fiscale_paziente`,
   `categoria_spesa`.
3. **Valida** CF italiano, importi, date.
4. **Conserva** storico per utente (multi-tenant, idempotency cache).
5. **Esporta** Excel per categoria + ZIP con ricevute rinominate
   `YYYY-MM-DD_esercente_importoCAT.ext` per il commercialista.
6. **Profilo**: riepilogo spese (totale, conteggio, per categoria) + storico
   job + export per-job.

Categorie: Farmaci / Visita Specialistica / Dispositivo Medico / Esami / Altro.

Tassonomia dei modi: sync (≤3 file) e async (>3 file → job con polling).

## Contesto operativo

- Backend FastAPI (`src/spesemed/`), auth JWT (Supabase), storage bucket
  PRIVATO `receipts` (GDPR) — mai pubblico.
- Rate-limit sugli endpoint (login 5/min, extract 10/min...).
- Il frontend Flutter storico è stato rimosso; il nuovo client è da costruire
  da zero (questo mockup ne è il primo passo visivo).
- Product surface attese: Landing + app (login/signup, dashboard/riepilogo,
  upload, risultati estrazione, storico job, esportazione, profilo).

## Vincoli

- Privacy/GDPR al centro: volere visibile dei segnali di sicurezza.
- Lingua: italiano. Tono: calmo, rassicurante, chiaro; mai tecnico.
- Consentito: verde (salute+denaro), con moderazione. Sconsigliato: estetiche
  dark/edgy, viola, "fintech di lusso" freddo.

## Voice

Calda, semplice, concreta. Messaggi generici ("Carica la ricevuta, sistemiamo
il resto.") invece di gergo ("estrazione JSON", "job id", "endpoint").
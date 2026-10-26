# Task 01 — Corpus demo (6 casi di conflitto verificati)

**Assegnatario:** agent-core-dev · **Output:** `backend/corpus.json`

**Criteri di accettazione:** `PLAN.md` §4.1 (AC-CORPUS, C1–C7). Schema macchina: `schemas/corpus.schema.json`.
Gli id delle sorgenti sono globali (`FC-0X-S<n>`), `publisher_type` è un enum chiuso, e `truth`/`verdict_in_corpus`
non devono mai raggiungere la pipeline (regola anti-leakage, BUILD_SPEC §2.1).

Riempi i template FC-01..FC-06 di `specs/amd-ai-league/CORPUS.md` con dati reali.
Regole (non negoziabili):

1. Ogni coppia deve avere una **ground truth verificabile** da fonte primaria (SEC filing,
   press release ufficiale, transcript earnings call). Usa la ricerca web per trovare coppie
   reali di articoli che si contraddicono sullo stesso numero.
2. Il campo `content` di ogni snippet: 2-4 frasi di testo reale citato/parafrasato con nome
   fonte e data reali — mai inventato.
3. Copertura: 1 conflitto earnings-guidance, 1 acquisition-amount, 1 data/CEO rumor,
   1 spec-sheet, 1 caso noise/SEO (per far demolire NOUL), 1 caso con evidenza insufficiente.
4. Il caso noise: NON inventare snippet finti — usa boilerplate realistico da pattern noti,
   marcato `publisher_type: "noise"`.
5. Formato: esattamente lo schema JSON di CORPUS.md.

**Definition of done:** `corpus.json` carica, 6 casi, ognuno con ≥4 sorgenti, ground truth
con URL primaria nel campo `truth`. Commenta sull'issue il riepilogo (casi + fonti primarie).

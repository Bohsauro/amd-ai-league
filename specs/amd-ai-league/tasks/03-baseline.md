# Task 03 — Baseline agentica (i numeri reali dell'avversario)

**Assegnatario:** agent-core-dev · **Output:** `backend/baseline_agent.py`, `backend/baseline_metrics.json`

**Criteri di accettazione:** `PLAN.md` §4.3 (AC-BASE, B1–B5). Schema macchina: `schemas/baseline_metrics.schema.json`.

Serve per la barra di confronto nella demo (BUILD_SPEC §3): numeri MISURATI di un classico
workflow agentico generativo sullo STESSO corpus. Nessun numero inventato.

1. Stesso corpus, stesse query di `pipeline.py`.
2. Pattern classico: loop fino a 5 chiamate LLM, ogni chiamata riceve TUTTI gli snippet
   (nessun filtro), decide cosa fare (re-rank / extract / synthesize), l'ultima scrive la risposta.
   Stesso modello del generator di `pipeline.py` (confronto model-normalized).
3. Misura e scrivi in `baseline_metrics.json`: latenza totale ms, numero chiamate LLM,
   token input+output per chiamata e totale, latenza per chiamata. Usa i campi `usage` reali
   della risposta API, non stime.
4. Stampa anche la risposta finale, per confrontare la qualità side-by-side.

**Definition of done:** entrambi gli script girano sulla stessa query, `baseline_metrics.json`
esiste con token reali dai campi usage. Commenta sull'issue i numeri misurati; l'aggiornamento
di `BUILD_SPEC.md` §3 spetta al PO (specs/ non è tua).

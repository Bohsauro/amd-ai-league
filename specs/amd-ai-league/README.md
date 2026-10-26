# AMD AI League · Match 4 — progetto demo (deadline 27/10)

Pipeline di **Web Information Retrieval asimmetrica**: primitive discriminative tipizzate
(NOUL = gate bool, SCORE = rank, CHOICE = conflitto/verdetto) fanno il 90% delle decisioni in
decine di ms; il generativo fa **una sola chiamata** su 2-3 sorgenti validate.
Il generativo non classifica mai; il discriminativo non sintetizza mai.

## Dove stanno i file

| Path | Contenuto | Proprietario |
|---|---|---|
| `specs/amd-ai-league/BUILD_SPEC.md` | contratto moduli + metriche (AUTORITATIVO) | agent-po |
| `specs/amd-ai-league/CORPUS.md` | regole dati demo + schema JSON | agent-po |
| `specs/amd-ai-league/DEMO_SCRIPT.md` | struttura video 120s | agent-po |
| `specs/amd-ai-league/tasks/*.md` | brief operativi per ruolo | agent-po |
| `backend/` | `pipeline.py`, `noul.py`, `score.py`, `choice.py`, `guard.py`, `generator.py`, `retriever.py`, `baseline_agent.py`, `corpus.json`, `run.json`, `baseline_metrics.json` | agent-core-dev |
| `frontend/` | `index.html` (demo single-file), `run.json` (copia per la UI) | agent-ui-ux |

## Ordine di esecuzione (dipendenze)

1. **corpus** → `backend/corpus.json` (6 casi, ground truth verificabile) — core-dev
2. **build** → pipeline NOUL→SCORE→CHOICE→GUARD→GEN, ticker < 1.2s — core-dev
3. **baseline** → `backend/baseline_agent.py` + `baseline_metrics.json` (numeri REALI) — core-dev
4. **demo-ui** → `frontend/index.html` che anima SOLO i numeri reali di `run.json` — ui-ux
5. **review + video + submit** — CEO

Il corpus va prima della pipeline; la UI va dopo la pipeline (le serve `run.json`).
La baseline è indipendente dalla UI ma serve al frame comparativo.

## Regole non negoziabili

- Questa è una **demo hackathon**, non un prodotto: si taglia tutto ciò che non si vede nei 120s.
- **Mai inventare numeri**: ogni cifra mostrata viene da valori misurati e scritti su `run.json`.
- Il generatore PUÒ rispondere `status: unresolved` — è una feature (fallimento tipizzato), non un bug.
- Python: stdlib + `httpx` (+ embedding piccolo o TF-IDF come fallback). Niente framework pesanti.
- Generatore: `OPENROUTER_API_KEY` dall'env (già in `/srv/ai-company/.env`), modello classe Llama-3.1-8B.
- Nessun server da bindare in fase 1; UI = singolo file HTML, nessun build step.

## Comandi

```bash
cd /srv/ai-company/workspace/backend
python pipeline.py "FC-01"          # ticker completo
python pipeline.py "FC-01" --dump-json   # scrive run.json
python baseline_agent.py "FC-01"    # metriche baseline reali
```

## Definizione di "fatto" per la demo

`python pipeline.py "FC-01"` stampa il ticker completo (ms per stage, token risparmiati %,
verdetto tipizzato) sotto 1.2s, e `frontend/index.html` aperto dopo un run reale mostra
esattamente quei numeri.

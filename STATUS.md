# STATUS — handoff (2026-10-26, 13:15 UTC)

> Leggi questo prima di toccare qualsiasi cosa. È il biglietto d'ingresso per una sessione nuova.

## Stato in una riga

Demo **AMD AI League Match 4** pronta e verificata: `bin/verify` **14/14**, tutti i ticket chiusi,
0 run attivi, repo pulito su `main` (commit `e26f7c1`).

## Numeri (dal run congelato, non stimati)

| | pipeline | baseline agentica |
|---|---|---|
| chiamate LLM | **1** | 5 |
| token | **1,572** (1,390+182) | 27,364 (25,618+1,746) |
| latenza e2e | **460 ms** | 3,568 ms |
| esito | CONFLICT · resolved · 3 citazioni | prosa che collassa GAAP/non-GAAP |

NOUL: 12/34 keep (22 scartati, 64,7%) · CHOICE conf 0,63 · **discriminative 6 ms · generator 454 ms**
Modello: `meta-llama/llama-3.1-8b-instruct` (OpenRouter → Groq). Costo: $0,000076 vs $0,00052.

Fonte unica numeri: `specs/amd-ai-league/VERIFIED_NUMBERS.md` — **generato**, mai a mano:
```bash
/srv/ai-company/bin/gen-verified-numbers
```
run.json sha256 `d972f87f2c27` · baseline_metrics.json sha256 `14a7d6b5f594`.

## Comandi

```bash
/srv/ai-company/bin/status      # cruscotto board/run/file
/srv/ai-company/bin/verify      # gate DoD (exit 1 se rosso)
/srv/ai-company/bin/standup     # fa parlare i 5 agenti
cd backend && python pipeline.py FC-01 --dump-json   # rigenera run.json
python baseline_agent.py FC-01                        # rigenera baseline_metrics.json
```

Demo UI: `python3 -m http.server 8500 --bind 0.0.0.0` dentro `frontend/`
→ http://100.69.55.38:8500/index.html (serve `run.json`, niente numeri hardcoded).

## Cosa resta (in ordine di valore)

1. **Registrare il video 120s** seguendo `specs/amd-ai-league/DEMO_SCRIPT.md` + `VERIFIED_NUMBERS.md`. Poi submit.
2. **Test unitari** (oggi: zero). Minimo: gate NOUL, ordinamento SCORE, soglia GUARD, validazione corpus.
3. **`bin/demo`**: un comando che esegue i 6 casi, scrive run.json, copia in `frontend/`, stampa il ticker.
4. **Fallback offline per la registrazione**: se OpenRouter cade, registrare dal run.json congelato (c'è già `--offline`).
5. **Corpus 6 → 10-12 casi** e decisione su SERPAPI (usarla in un frame o togliere il claim "live").
6. **Cleanup**: `textutil.py` duplicato, type hints/dataclass, `metrics.py` unico.
7. **Processo**: reviewer obbligatorio prima di `done` (oggi è facoltativo).

## Team agenti (Paperclip)

| Agente | Runtime | Scrive in | ID |
|---|---|---|---|
| agent-ceo | Hermes | radice (review/merge) | `4ca68d04-6f0b-478c-897c-e95e5a5678a7` |
| agent-po | Hermes | `specs/` | `a25d29d1-9402-4699-ad90-af879aa8e7f1` |
| agent-core-dev | OpenCode | `backend/` | `610739a8-6c71-4881-8dda-7c3e011027e4` |
| agent-ui-ux | OpenCode | `frontend/` | `f41ce726-1c48-40e5-aea0-7d8934ec9401` |
| agent-reviewer | OpenCode read-only | nulla | `3b1b700c-1bad-4ee1-81c7-9d240a648ca9` |

Svegliare: `POST /api/agents/<id>/wakeup` con `{"source":"on_demand"}` e header `Authorization: Bearer $PAPERCLIP_BOARD_API_KEY`
(`.env` in `/srv/ai-company/`). Workflow ticket: `workspace/PAPERCLIP_PLAYBOOK.md`; review: `workspace/REVIEW_PROTOCOL.md`.

## Gotchas

- **Gli agenti dichiarano più di quanto fanno.** Fidati solo di `bin/verify`, `git log` e dei file.
- Il gate `verify` ha già beccato: corpus con URL finti (`acme.example`), 44 violazioni di schema, `run.json` da corpus stub.
- `main` locale ≠ `origin/main` su GitHub (storie non correlate: gli agenti avevano pushato una copia separata).
  Il delivery verificato è pushato sul branch **`delivery-verified`**.
- Il redattore di segreti può corrompere i file scritti se contengono `<NOME_SECRETO>=`: costruisci i nomi a runtime.
- Paperclip: `blocked` può essere il watchdog (run terminato senza finire), non un blocco reale.

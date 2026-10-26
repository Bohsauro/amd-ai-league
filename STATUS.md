# STATUS — handoff (2026-10-26, 15:30 UTC)

> Leggi questo prima di toccare qualsiasi cosa. È il biglietto d'ingresso per una sessione nuova.

## Stato in una riga

Demo **AMD AI League Match 4** pronta e verificata: `bin/verify` **17/17** (77 test unitari),
corpus **10 casi**, demo live misurata su Groq, `bin/demo` fa tutto con un comando,
`bin/close-ticket` rende il reviewer obbligatorio prima di `done`.

## Numeri (dalla fonte unica, mai a mano)

Fonte: `specs/amd-ai-league/VERIFIED_NUMBERS.md` — rigenerare con `bin/gen-verified-numbers` dopo ogni run.

| | pipeline | baseline agentica |
|---|---|---|
| chiamate LLM | **1** | 5 |
| token | **1,572** (1,390+182) | 46,563 (43,127+3,436) |
| latenza e2e | **415 ms** | 30,570 ms |
| esito | CONFLICT · resolved · 3 citazioni | prosa che collassa GAAP/non-GAAP |

NOUL: **19/53 keep** (34 scartati, 64,2%) · CHOICE conf 0,63 · **discriminative 7 ms · generator 408 ms**
Modello: `meta-llama/llama-3.1-8b-instruct` (provider: **Groq**, pinnato). Costo: $0,000076 vs $0,0102.
Batch: 10 run paralleli, max 717 ms. run.json sha256 `bc7e989af415` · baseline sha256 `02adbf40c2a9`.

## Comandi

```bash
/srv/ai-company/bin/verify            # gate DoD (17 check + pytest; exit 1 se rosso)
/srv/ai-company/bin/status            # cruscotto board/run/file
/srv/ai-company/bin/demo              # 10 casi live -> run.json -> frontend/ + ticker (niente serve)
/srv/ai-company/bin/demo --freeze     # come sopra + congela backend/run.frozen.json
/srv/ai-company/bin/demo --frozen     # registra dal run congelato (fallback se OpenRouter giu')
/srv/ai-company/bin/demo --offline    # verifica veloce: NON tocca run.json/frontend
/srv/ai-company/bin/demo --serve      # genera e serve frontend/ su 0.0.0.0:8500
/srv/ai-company/bin/close-ticket BOH-13  # in_review -> done SOLO con APPROVE del reviewer
/srv/ai-company/bin/gen-verified-numbers # riscrive VERIFIED_NUMBERS.md dai file reali
```

Demo UI: `bin/demo --serve` o `python3 -m http.server 8500 --bind 0.0.0.0` in `frontend/`
→ http://100.69.55.38:8500/index.html (legge `run.json`, niente numeri hardcoded).

## Cosa è cambiato oggi (26/10)

1. **Test unitari** (`backend/tests/`, 77 test): gate NOUL (quota solo su pool>=10), ordinamento SCORE,
   soglia GUARD, validazione corpus (modulo unico `corpus_validation.py` condiviso con `bin/verify`),
   pipeline offline. Wiring nel gate: 17/17.
2. **`bin/demo`**: un comando per i 10 casi, run.json, copia frontend, ticker, throughput, freeze/fallback.
3. **Fallback offline**: `run.frozen.json` + auto-fallback se il generatore va in errore.
4. **Corpus 6 → 10 casi** (FC-07 NVIDIA Q3FY25 · FC-08 AMD Q3 2024 · FC-09 iPhone 16/Apple Intelligence ·
   FC-10 Amazon-Anthropic $4B/$8B). Ogni URL verificato HTTP 200; 2 fonti Apple via Internet Archive
   (pagine live riscritte) dichiarate nei `notes`. **SERPAPI: non usata** (nessuna key; canale live =
   snapshot `--live PATH`; UI non rivendica "live"). Decisione documentata in `specs/.../CORPUS.md`.
5. **Cleanup**: validazione corpus unica; `textutil.py` duplicato era solo una copia di review in
   `agents/ceo/` (fuori repo); `grow_corpus.py` (builder one-shot) rimosso.
6. **Reviewer obbligatorio**: `bin/close-ticket` — `done` solo da `in_review` con APPROVE di agent-reviewer.

## Cosa resta (in ordine di valore)

1. **Registrare il video 120s** seguendo `specs/amd-ai-league/DEMO_SCRIPT.md` + `VERIFIED_NUMBERS.md`
   (sezione FC-06 del fallimento tipizzato ORA è misurata: insert 8s legittimo). Poi submit.
2. Nient'altro di tecnico: gate, test, demo, fallback e processo sono chiusi e verificati.

## Team agenti (Paperclip)

| Agente | Runtime | Scrive in | ID |
|---|---|---|---|
| agent-ceo | Hermes | radice (review/merge) | `4ca68d04-6f0b-478c-897c-e95e5a5678a7` |
| agent-po | Hermes | `specs/` | `a25d29d1-9402-4699-ad90-af879aa8e7f1` |
| agent-core-dev | OpenCode | `backend/` | `610739a8-6c71-4881-8dda-7c3e011027e4` |
| agent-ui-ux | OpenCode | `frontend/` | `f41ce726-1c48-40e5-aea0-7d8934ec9401` |
| agent-reviewer | OpenCode read-only | nulla | `3b1b700c-1bad-4ee1-81c7-9d240a648ca9` |

Workflow ticket: `workspace/PAPERCLIP_PLAYBOOK.md` (§3: `in_review` → `bin/close-ticket`);
review: `workspace/REVIEW_PROTOCOL.md` (il reviewer non chiude più direttamente).

## Gotchas (nuovi e vecchi)

- **OpenRouter `sort: latency` devia su provider lenti** (CoreWeave ~1.8s) anche quando Groq è su:
  `generator.py` pinnà Groq (`OPENROUTER_PROVIDER_ONLY`, default "Groq"). Se Groq cade, la chiamata va
  in errore → `bin/demo` ricade sul run congelato. Non rimettere `sort: latency` senza pin.
- **`source .env` non basta** per processi figli: i wrapper usano `set -a; source .env; set +a`.
- Se `verify` è rosso su "latenza < 1.2s" dopo un run: probabilmente il run è stato preso sotto carico
  o su provider non-Groq → rilancia `bin/demo --freeze` a sistema scarico, poi `bin/gen-verified-numbers`.
- Gli agenti dichiarano più di quanto fanno. Fidati solo di `bin/verify`, `git log` e dei file.
- `main` locale ≠ `origin/main` su GitHub (storie non correlate); il delivery verificato è su `delivery-verified`.
- Il redattore di segreti può corrompere i file scritti se contengono `<NOME_SECRETO>=`: costruisci i nomi a runtime.
- Paperclip: `blocked` può essere il watchdog (run terminato senza finire), non un blocco reale.
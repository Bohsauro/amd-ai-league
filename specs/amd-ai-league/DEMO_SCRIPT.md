# AMD AI League · Match 4 — SCRIPT DEMO (120 secondi)

> Stato: **v1.1 (26/10)** — numeri letterali rimossi: ogni cifra a schermo è un segnaposto legato a
> `run.json` §2.8 o `baseline_metrics.json`. Vedi §0 (contratto segnaposto) e §9 (igiene dei claim).
> Lingua: inglese (mercato globale). Tono: dimostrativo, mai fumo.
> Due counter animati a schermo — null'altro si muove se non la pipeline.

---

## 0. Contratto segnaposto (vincolante per chi registra e per la UI)

**Regola unica:** nello script non esiste un numero scritto a mano. L'unica forma ammessa è `{{token}}`.
Chi registra sostituisce i token con i valori del run (§0.3), la UI legge gli stessi percorsi
(AC-UI U2/U4). Se un campo non esiste o è `null`, si usa il `fallback` dichiarato o si **taglia il frame**:
mai un numero inventato (D6).

### 0.1 Tabella segnaposto

| Token | Sorgente | Percorso JSON | Formato | Fallback se assente |
|---|---|---|---|---|
| `{{total_ms}}` | `run.json` | `total_ms` | int + `ms` | taglia il frame latenza |
| `{{budget_ms}}` | `run.json` | `budget_ms` | int + `ms` | — |
| `{{noul.total}}` | `run.json` | `stages.noul.total` | int | taglia il frame |
| `{{noul.dropped}}` | `run.json` | `stages.noul.dropped` | int | taglia il frame |
| `{{noul.kept}}` | `run.json` | `stages.noul.kept` | int | taglia il frame |
| `{{tokens.raw_est}}` | `run.json` | `tokens.raw_est` | int, separatore migliaia | taglia il frame |
| `{{tokens.generator_prompt}}` | `run.json` | `tokens.generator_prompt` | int, separatore migliaia | `tokens.curated_est` (etichettato `est.`) |
| `{{tokens.saved}}` | `run.json` | `tokens.saved` | int, separatore migliaia | — |
| `{{tokens.saved_pct}}` | `run.json` | `tokens.saved_pct` | 1 decimale + `%` | — |
| `{{tokens.gen_consumed}}` | `run.json` | `tokens.gen_consumed` | int, separatore migliaia | `0` se `called:false` |
| `{{gen.total_tokens}}` | `run.json` | `stages.generator.usage.total_tokens` | int | `0` se `called:false` |
| `{{gen.prompt_tokens}}` | `run.json` | `stages.generator.usage.prompt_tokens` | int | `0` |
| `{{gen.status}}` | `run.json` | `stages.generator.status` | stringa (`resolved`/`unresolved`/`skipped`/`error`) | — |
| `{{choice.label}}` | `run.json` | `stages.choice.label` | stringa (`RESOLVED`/`CONFLICT`/`INSUFFICIENT`) | — |
| `{{baseline.e2e_ms}}` | `baseline_metrics.json` | `totals.e2e_ms` | int + `ms` | `{{baseline.label}}` |
| `{{baseline.llm_calls}}` | `baseline_metrics.json` | `totals.llm_calls` | int | `{{baseline.label}}` |
| `{{baseline.prompt_tokens}}` | `baseline_metrics.json` | `totals.prompt_tokens` | int, migliaia | `{{baseline.label}}` |
| `{{baseline.label}}` | testo fisso | — | `"classic agent: {{baseline.llm_calls}} LLM calls per query (architectural, not measured here)"` | — |
| `{{batch.n_runs}}` | batch harness | numero di run lanciati | int | taglia la sezione throughput |
| `{{batch.max_total_ms}}` | batch harness | `max(total_ms)` sui run del batch | int + `ms` | taglia la sezione throughput |
| `{{baseline.saved_pct}}` | derivato (§0.5) | `100·(baseline totals.prompt_tokens − tokens.gen_consumed) / baseline totals.prompt_tokens` | 1 decimale + `%` | non mostrabile → si taglia il frame |

### 0.2 Regole di sostituzione

- **R1 — un solo run.** Tutti i token `run.json` vengono dallo **stesso** run (lo stesso file mostrato in UI).
  Mai mescolare un run `--offline` (split-screen) con un run live: se servono due run, si dichiara a schermo
  quale è quale (BUILD_SPEC §2.10).
- **R2 — baseline misurata o dichiarata.** Se `backend/baseline_metrics.json` esiste, la barra mostra
  `{{baseline.e2e_ms}}`. Se non esiste, la barra mostra `{{baseline.label}}`: **nessun numero**, etichetta
  architetturale esplicita (D4). Il `{{baseline.llm_calls}}` è un fatto di architettura (BUILD_SPEC §3), non
  una misura: si mostra solo dentro `{{baseline.label}}`, mai come cifra nuda.
- **R3 — derivati dichiarati.** `{{batch.*}}` sono gli unici valori non letti da un file: derivano da N run
  reali e si riproducono con il comando in §0.3. Se il batch non è stato eseguito, la sezione 1:20 si taglia
  (PLAN §7), non si stima.
- **R4 — sostituzione meccanica.** La tabella valori si genera con un comando, non a memoria (§0.3). Il testo
  finale non deve contenere la stringa `{{`.
- **R5 — guardia sul risparmio.** `{{tokens.saved_pct}}` confronta una **stima** dei soli snippet (`raw_est`) con
  il **prompt reale** (che include istruzioni di citazione e formattazione): con pochi snippet per caso
  l'overhead fisso può superare il contenuto e il rapporto diventa **≤ 0** (verificato su FC-01 il 26/10 —
  misura esatta nel commento BOH-3, non qui: i numeri invecchiano, il percorso no). Se `tokens.saved_pct ≤ 0`:
  **il frame "never saw" non si registra in questa forma** → si usa la variante B (§0.5, like-for-like su due
  misure) o si taglia il frame. Mai mostrare un risparmio negativo come se fosse un vantaggio, mai clampare
  il numero.

### 0.3 Come si generano i valori (un comando, riproducibile)

```bash
# valori da run.json (stesso run mostrato in UI)
jq -r '"total_ms=\(.total_ms|floor) budget_ms=\(.budget_ms|floor) " +
       "noul=\(.stages.noul.dropped)/\(.stages.noul.total) " +
       "raw_est=\(.tokens.raw_est) gen_prompt=\(.tokens.generator_prompt) " +
       "saved=\(.tokens.saved) saved_pct=\(.tokens.saved_pct) " +
       "gen_total=\(.stages.generator.usage.total_tokens // 0) " +
       "gen_status=\(.stages.generator.status) choice=\(.stages.choice.label)"' \
   backend/run.json

# valori baseline (se il file esiste)
jq -r '"baseline_e2e_ms=\(.totals.e2e_ms|floor) baseline_llm_calls=\(.totals.llm_calls) " +
       "baseline_prompt_tokens=\(.totals.prompt_tokens)"' backend/baseline_metrics.json

# throughput: N run reali, si mostra il peggiore
for i in $(seq 1 10); do python pipeline.py FC-01 --dump-json >/dev/null; jq .total_ms backend/run.json; done \
  | sort -n | tail -1
```

### 0.4 Elenco machine-readable (per UI e baseline)

Fonte unica: questo blocco. La UI non hardcoda nulla (AC-UI U4); chi cambia la mappa cambia qui.

```json
{
  "version": "1.1",
  "run_json": {
    "total_ms":                 {"path": "total_ms",                              "format": "int_ms"},
    "budget_ms":                {"path": "budget_ms",                             "format": "int_ms"},
    "noul.total":               {"path": "stages.noul.total",                     "format": "int"},
    "noul.dropped":             {"path": "stages.noul.dropped",                   "format": "int"},
    "noul.kept":                {"path": "stages.noul.kept",                      "format": "int"},
    "tokens.raw_est":           {"path": "tokens.raw_est",                        "format": "int_thousands"},
    "tokens.generator_prompt":  {"path": "tokens.generator_prompt",               "format": "int_thousands",
                                 "fallback": "tokens.curated_est"},
    "tokens.saved":             {"path": "tokens.saved",                          "format": "int_thousands"},
    "tokens.saved_pct":         {"path": "tokens.saved_pct",                      "format": "pct1"},
    "tokens.gen_consumed":      {"path": "tokens.gen_consumed",                   "format": "int_thousands", "null_as": 0},
    "gen.total_tokens":         {"path": "stages.generator.usage.total_tokens",   "format": "int", "null_as": 0},
    "gen.prompt_tokens":        {"path": "stages.generator.usage.prompt_tokens",  "format": "int", "null_as": 0},
    "gen.status":               {"path": "stages.generator.status",               "format": "string"},
    "choice.label":             {"path": "stages.choice.label",                   "format": "string"}
  },
  "baseline_json": {
    "baseline.e2e_ms":          {"path": "totals.e2e_ms",                         "format": "int_ms",
                                 "fallback": "baseline.label"},
    "baseline.llm_calls":       {"path": "totals.llm_calls",                      "format": "int",
                                 "fallback": "baseline.label"},
    "baseline.prompt_tokens":   {"path": "totals.prompt_tokens",                  "format": "int_thousands",
                                 "fallback": "baseline.label"}
  },
  "derived": {
    "batch.n_runs":             {"source": "batch harness", "format": "int"},
    "batch.max_total_ms":       {"source": "max(total_ms) over batch", "format": "int_ms"},
    "baseline.saved_pct":       {"source": "100*(baseline.totals.prompt_tokens - run.tokens.gen_consumed)/baseline.totals.prompt_tokens",
                                 "format": "pct1"}
  },
  "invariants": [
    "un solo run.json per tutti i token run_json (R1)",
    "se baseline_json assente -> baseline.label, mai un numero (R2)",
    "batch.* solo se il batch e' stato eseguito (R3)",
    "se tokens.saved_pct <= 0 -> variante B o frame tagliato (R5)",
    "il testo registrato non contiene '{{' (R4)"
  ]
}
```

---

## 0.5 Variante B — headline like-for-like (usare se R5 scatta)

Se `tokens.saved_pct ≤ 0` (corpus piccolo: l'overhead fisso del prompt generatore supera i token degli
snippet), il frame "raw context vs curated context" **non è registrabile**: i due lati non sono omogenei
(stima-snippet contro prompt-reale). Al suo posto si confrontano **due misure reali, stesso corpus, stesso
modello**: la baseline agentica e la nostra pipeline.

| Lato sinistro (baseline) | Lato destro (nostra) |
|---|---|
| `{{baseline.llm_calls}}` chiamate LLM | 1 chiamata |
| `{{baseline.prompt_tokens}}` prompt token (somma `usage` reali) | `{{tokens.generator_prompt}}` prompt token |
| `{{baseline.e2e_ms}}` ms end-to-end | `{{total_ms}}` ms end-to-end |

Headline ammessa: **"`{{baseline.prompt_tokens}}` → `{{tokens.gen_consumed}}` tokens per query
(`{{baseline.saved_pct}}`% fewer), `{{baseline.llm_calls}}` generative calls → 1, same corpus, same model."**
Nessun moltiplicatore, nessun range: due file, due misure, un comando. Se `baseline.saved_pct` risultasse
negativo la pipeline è più cara della baseline: si mostra il segno vero e si taglia il frame (mai girarlo).

```bash
# baseline.saved_pct: due misure omogenee (prompt vs consumo reale), un solo comando
jq -n --argjson b "$(jq '.totals.prompt_tokens // .total_input_tokens' backend/baseline_metrics.json)" \
      --argjson o "$(jq '.tokens.gen_consumed' backend/run.json)" \
      '{baseline_prompt:$b, ours:$o, saved_pct:(100*($b-$o)/$b*10|round/10)}'
```

> **Nessuna cifra in questa sezione, per costruzione.** Le misure che motivano la variante B sono sul ticket
> BOH-3 (commento del PO, 26/10) e si rigenerano con i comandi di §0.3: `baseline_metrics.json` va comunque
> rigenerato con lo schema `baseline_metrics.schema.json` in W3b, quindi ogni numero scritto qui invecchierebbe
> in un'ora. Il copione si compila **solo** da §0.3.

---

## 1. Apertura (0:00–0:15) — 3 frasi, problema reale

> "Two headlines, one earnings call, opposite numbers. An analyst has to reconcile them — or guess. That guessing costs money, and it's exactly where today's AI agents fail: they feed the *entire* noisy context to an expensive model and hope."

- Schermo: due headline in conflitto (es. "BEATS GUIDANCE" vs "DOWNGUARDS"). Nessuna cifra.
- Tasto Invio → query in esecuzione.

## 2. Pipeline live (0:15–0:55) — il cuore

> "Watch what the model *never* sees."

- Visual con flusso snippet → NOUL (rosso: drop) → SCORE (barre ascendenti) → CHOICE (zig-zag conflitto) → GENERATORE (verde).
- I due counter girano in diretta, alimentati da `run.json`:
  1. **E2E LATENCY** → `{{total_ms}}` ms, con barra fissa etichettata
     `baseline {{baseline.e2e_ms}} ms` (misurata) **oppure** `{{baseline.label}}` (non misurata).
     Scala della barra = `max(total_ms, baseline.e2e_ms)`; se la baseline non è misurata la barra **non**
     ha una scala numerica: resta l'etichetta architetturale.
  2. **BASE → SAVED** tokens (contachilometri): `{{tokens.raw_est}} → {{tokens.generator_prompt}} · −{{tokens.saved_pct}}%`.
     **Se R5 scatta** (`saved_pct ≤ 0`) il counter diventa la coppia omogenea di §0.5:
     `{{baseline.prompt_tokens}} → {{tokens.gen_consumed}} · −{{baseline.saved_pct}}%`.
- Narrazione sincronizzata: "NOUL discarded `{{noul.dropped}}` of `{{noul.total}}` sources before they cost a single token. CHOICE says `{{choice.label}}`. The generator received `{{tokens.generator_prompt}}` validated tokens, not `{{tokens.raw_est}}`."

## 3. What the GPU never saw (0:55–1:20) — il visual choc

> **Guardia R5:** se `{{tokens.saved_pct}}` ≤ 0 questo frame **non si registra** in questa forma: si passa alla
> variante B (§0.5) o si taglia. Motivo: i due lati non sarebbero omogenei (stima-snippet vs prompt reale).

> "Left: the raw `{{tokens.raw_est}}` tokens a classic agent would feed the model. Right: the `{{tokens.generator_prompt}}` tokens we fed it — already reconciled, already cited. That's `{{tokens.saved_pct}}%` less context, and the answer still carries its sources."

- Split-screen statico: contesto crudo (`{{tokens.raw_est}}`) vs contesto curato (`{{tokens.generator_prompt}}`) **dello stesso run** (R1).
- Riga di provenienza a schermo, obbligatoria: `run.json · total_ms {{total_ms}} · tokens.raw_est vs tokens.generator_prompt`.
- Speaker in silenzio 3s (silenzio = potenza).

## 4. Throughput (1:20–1:45) — scalabilità

> "Now `{{batch.n_runs}}` analysts ask at once." (lancio del batch)

> "Each row is its own measured run. The slowest of `{{batch.n_runs}}` was `{{batch.max_total_ms}}` ms — because five of the six stages never touch the model — only the last one generates."

- Schermo: `{{batch.n_runs}}` righe in parallelo, ognuna col proprio `total_ms`; in evidenza il massimo.
- Se il batch non è stato eseguito: **sezione tagliata** (PLAN §7), non simulata.

## 5. Chiusura (1:45–2:00) — differenziazione + AMD

> "Classic agents make the GPU do everything. We let the GPU do only the one thing it's for — generation — and push five of the six stages to fast, typed discriminative decisions. That's not a better model. It's a better computer. ROCm runs it, one card, batched."

- On-screen (solo valori misurati + claim architetturale, **nessun moltiplicatore**). Riga 1 se R5 **non**
  scatta, riga 1-bis se scatta (mai entrambe):

  ```
  {{tokens.raw_est}} → {{tokens.generator_prompt}} tokens · −{{tokens.saved_pct}}% context
  one generative call per query · the rest is a batched forward pass
  ```
  ```
  {{baseline.prompt_tokens}} → {{tokens.gen_consumed}} tokens per query · −{{baseline.saved_pct}}%
  one generative call per query · the rest is a batched forward pass
  ```

- Variante ammessa **solo se** `baseline_metrics.json` esiste (due misure, non un moltiplicatore):

  ```
  {{total_ms}} ms end-to-end · classic agent {{baseline.e2e_ms}} ms · {{baseline.llm_calls}} LLM calls vs 1
  ```

- Vietato su questo frame: "5-12x", "10-30x", "throughput per GPU", qualunque rapporto non misurato
  (BUILD_SPEC §0: senza GPU AMD il throughput è architetturale). Vedi §9.

## 6. FC-06 (fallimento tipizzato) — tagliato, non simulato (D5)

FC-06 **non è nel montaggio**. Motivo: il timebox non copre un terzo run e il frame non aggiunge nulla ai
120s. Se avanza tempo, insert opzionale da 8s con i numeri del run FC-06 (`{{gen.status}}` = `unresolved`,
`0` gen calls) — **mai** un fallimento recitato a mano. Questa è la dichiarazione esplicita richiesta da D5.

## 7. One-liner di backup (se il timing stringe)

> "Every token the generator never sees is free compute. We monetize ignorance."

Nessuna cifra: usabile senza sostituzioni.

## 8. Regole di registrazione

- 1 query live (realtà) + 1 rehearsal deterministico (`--offline`) per lo split-screen; i due run non si mescolano (R1).
- I counter **non** sono animati a mano: contano dal vivo dal processo reale, o leggono `run.json`.
- Prima di registrare: sostituire **tutti** i segnaposto di §0.1 con i valori di §0.3 e verificare che sul
  copione di registrazione (non su questo file) non resti nessuna doppia graffa: `grep -c '{{' <copione>` → 0.
- Se la latenza live sfora il budget, si mostra sforata (`within_budget: false`) e si taglia il throughput —
  mai truccare il ticker.
- Ogni frame con cifre ha una riga di provenienza a schermo (`run.json` / `baseline_metrics.json`): è la
  verifica visiva di D2/D6.

## 9. Igiene dei claim (cosa NON diciamo, e perché)

| Claim rimosso | Perché | Cosa diciamo al suo posto |
|---|---|---|
| "5-12x lower latency" | moltiplicatore non misurato su questa macchina | `{{total_ms}}` ms misurati; baseline solo se misurata |
| "10-30x throughput per GPU" | richiede GPU AMD (BUILD_SPEC §0) | "one generative call per query, the rest is a batched forward pass; ROCm runs it on one card" |
| "Same answer quality" | nessun eval harness nel timebox: non è verificabile con un comando del repo | "already reconciled, already cited" (fatto strutturale: `stages.choice.label`, citazioni in `run.json`) |
| "GPU-sec/query" come cifra | non misurabile senza GPU AMD | rapporto token/query (hardware-agnostico), misurato |

Un claim forte e vero non ha bisogno di cifre finte: "one generative call, the rest is a batched forward
pass" è architettura, non misura — e resta vero qualunque sia la latenza misurata.

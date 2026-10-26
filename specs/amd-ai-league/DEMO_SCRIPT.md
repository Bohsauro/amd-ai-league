# AMD AI League · Match 4 — SCRIPT DEMO (120 secondi)

> Stato: **v1.4 (26/10)** — copione approvato dal CEO (v1.3); unico edit: **§0.6 non contiene più numeri**.
> I valori di riferimento vivono solo in `agents/ceo/review/VERIFIED_NUMBERS.md`; qui restano i segnaposto
> obbligatori a schermo, il claim ROCm come **intenzione** e il fallimento tipizzato **condizionato alla misura**.
>
> **Changelog v1.4** (review CEO 10:31): corpo di §0.6 sostituito dal rinvio alla fonte unica + le due trappole
> che non dipendono dai numeri (file committati ≠ valori del copione; `saved_pct` diagnostica, mai "saved" a
> schermo) + nota di varianza senza cifre. Tolte anche le cifre residue in R5 e R6, che duplicavano gli stessi
> valori e sarebbero invecchiate con loro. §1–§5 e §7–§9 invariati.
>
> **Changelog v1.3** (review CEO 10:16 e 10:17): §5 senza "ROCm runs it" al presente; §6 con la condizione di
> misura sul typed failure; §9 con le due righe nuove.
> Lingua: inglese (mercato globale). Tono: dimostrativo, mai fumo.
> Due counter animati a schermo — null'altro si muove se non la pipeline.

> **Regola in testa al file:** ogni cifra a schermo proviene dal `run.json`/`baseline_metrics.json` della
> registrazione; se un numero non esiste, la frase si cancella.

---

## 0. Contratto segnaposto (vincolante per chi registra e per la UI)

**Regola unica:** nello script non esiste un numero scritto a mano. L'unica forma ammessa è `{{token}}`.
Chi registra sostituisce i token con i valori del run (§0.3), la UI legge gli stessi percorsi
(AC-UI U2/U4). Se un campo non esiste o è `null`, si usa il `fallback` dichiarato o si **taglia il frame**:
mai un numero inventato (D6).

Un numero scritto in questo file — anche in una tabella, anche come "esempio" — è già un numero falso:
invecchia al primo refactor. §0.6 non fa eccezione: **rinvia** i valori a `agents/ceo/review/VERIFIED_NUMBERS.md`
e non li duplica, così nel repo la fonte di verità resta una sola.

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
| `{{tokens.saved}}` | `run.json` | `tokens.saved` | int, separatore migliaia — **negativo = overhead** | **vietato a schermo** (diagnostica, come `saved_pct`) |
| `{{tokens.saved_pct}}` | `run.json` | `tokens.saved_pct` | 1 decimale + `%` | **vietato a schermo** — vedi R5 |
| `{{tokens.gen_consumed}}` | `run.json` | `tokens.gen_consumed` | int, separatore migliaia | `0` se `called:false` |
| `{{gen.total_tokens}}` | `run.json` | `stages.generator.usage.total_tokens` | int | `0` se `called:false` |
| `{{gen.prompt_tokens}}` | `run.json` | `stages.generator.usage.prompt_tokens` | int | `0` |
| `{{gen.status}}` | `run.json` | `stages.generator.status` | stringa (`resolved`/`unresolved`/`skipped`/`error`) | — |
| `{{choice.label}}` | `run.json` | `stages.choice.label` | stringa (`RESOLVED`/`CONFLICT`/`INSUFFICIENT`) | — |
| `{{baseline.e2e_ms}}` | `baseline_metrics.json` | `totals.e2e_ms` | int + `ms` | `{{baseline.label}}` |
| `{{baseline.llm_calls}}` | `baseline_metrics.json` | `totals.llm_calls` | int | `{{baseline.label}}` |
| `{{baseline.prompt_tokens}}` | `baseline_metrics.json` | `totals.prompt_tokens` | int, migliaia | `{{baseline.label}}` |
| `{{baseline.total_tokens}}` | `baseline_metrics.json` | `totals.prompt_tokens + totals.completion_tokens` | int, migliaia | `{{baseline.label}}` |
| `{{baseline.label}}` | testo fisso | — | `"classic agent: {{baseline.llm_calls}} LLM calls per query (architectural, not measured here)"` | — |
| `{{batch.n_runs}}` | batch harness | numero di run lanciati | int | taglia la sezione throughput |
| `{{batch.max_total_ms}}` | batch harness | `max(total_ms)` sui run del batch | int + `ms` | taglia la sezione throughput |
| `{{baseline.saved_pct}}` | derivato (§0.5) | `100·(baseline.total_tokens − tokens.gen_consumed) / baseline.total_tokens` | 1 decimale + `%` | non mostrabile → si taglia il frame |
| `{{baseline.latency_x}}` | derivato (§0.5) | `totals.e2e_ms / total_ms` | 1 decimale + `×` | non mostrabile → si taglia il frame |

### 0.2 Regole di sostituzione

- **R1 — un solo run.** Tutti i token `run.json` vengono dallo **stesso** run (lo stesso file mostrato in UI).
  Mai mescolare un run `--offline` (split-screen) con un run live: se servono due run, si dichiara a schermo
  quale è quale (BUILD_SPEC §2.10).
- **R2 — baseline misurata o dichiarata.** Se `backend/baseline_metrics.json` esiste **ed è conforme a
  `schemas/baseline_metrics.schema.json`** (`totals.*`), la barra mostra `{{baseline.e2e_ms}}`. Altrimenti
  mostra `{{baseline.label}}`: **nessun numero**, etichetta architetturale esplicita (D4). Un file in formato
  pre-contratto (senza `totals.*`) non è una misura: è un file da rigenerare (B2), e finché non lo è la
  barra resta senza cifra.
- **R3 — derivati dichiarati.** `{{batch.*}}` sono gli unici valori non letti da un file: derivano da N run
  reali e si riproducono con il comando in §0.3. Se il batch non è stato eseguito, la sezione 1:20 si taglia
  (PLAN §7), non si stima.
- **R4 — sostituzione meccanica.** La tabella valori si genera con un comando, non a memoria (§0.3). Il testo
  finale non deve contenere la stringa `{{`.
- **R5 — il rapporto `raw_est → generator_prompt` non va mai a schermo.** I due lati non sono omogenei:
  `raw_est` è una stima dei soli snippet (chars/4), `generator_prompt` è il prompt reale, che include system
  prompt, regole di citazione e formattazione. Con un corpus piccolo l'overhead fisso supera il contenuto e il
  rapporto diventa **negativo** (overhead); con un corpus largo può diventare positivo. Il segno dipende dal
  perimetro, quindi il valore non è citabile come risultato (verifica CEO, valori in `VERIFIED_NUMBERS.md`).
  Un risparmio negativo mostrato come vantaggio è falso; clampato a −100 è falso due volte. Quindi:
  `tokens.saved_pct` resta in `run.json` (senza clamp, per P14) come diagnostica, e **non compare in nessun
  frame**. L'headline è quella di §0.5, che confronta due misure reali.
- **R6 — baseline omogenea e databile.** Requisito duro: stesso **corpus** e stesso **modello** del run mostrato.
  La stessa sessione è la condizione ideale: se i due `generated_at` distano più di 10 min (§0.3), o la baseline
  non ha `generated_at`, il frame si registra lo stesso ma la riga di provenienza a schermo **dichiara entrambe
  le fonti con la loro data** ("baseline: earlier run"), così si vede che sono due misure separate. Baseline
  reali dello stesso caso danno valori diversi fra loro: è varianza dell'API, non errore — ma non si nasconde
  mescolando i run in silenzio.

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

# valori baseline (se il file esiste ed è conforme: totals.*)
jq -r '"baseline_e2e_ms=\(.totals.e2e_ms|floor) baseline_llm_calls=\(.totals.llm_calls) " +
       "baseline_prompt_tokens=\(.totals.prompt_tokens) " +
       "baseline_total_tokens=\(.totals.prompt_tokens + .totals.completion_tokens)"' \
   backend/baseline_metrics.json

# headline like-for-like (§0.5): due misure, un comando
jq -n --argjson b "$(jq '.totals.prompt_tokens + .totals.completion_tokens' backend/baseline_metrics.json)" \
      --argjson o "$(jq '.tokens.gen_consumed' backend/run.json)" \
      --argjson bt "$(jq '.totals.e2e_ms' backend/baseline_metrics.json)" \
      --argjson ot "$(jq '.total_ms' backend/run.json)" \
      '{baseline_total:$b, ours_total:$o, saved_pct:(100*($b-$o)/$b*10|round/10),
        latency_x:($bt/$ot*10|round/10)}'

# R6: la coppia e' della stessa sessione? (distanza fra i due generated_at, <= 10 min)
jq -r '.generated_at' backend/baseline_metrics.json backend/run.json

# throughput: N run reali, si mostra il peggiore
for i in $(seq 1 10); do python pipeline.py FC-01 --dump-json >/dev/null; jq .total_ms backend/run.json; done \
  | sort -n | tail -1
```

### 0.4 Elenco machine-readable (per UI e baseline)

Fonte unica: questo blocco. La UI non hardcoda nulla (AC-UI U4); chi cambia la mappa cambia qui.

```json
{
  "version": "1.2",
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
    "tokens.saved_pct":         {"path": "tokens.saved_pct",                      "format": "pct1",
                                 "on_screen": false,
                                 "reason": "R5: raw_est vs generator_prompt non omogeneo"},
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
    "baseline.total_tokens":    {"source": "baseline_json.totals.prompt_tokens + baseline_json.totals.completion_tokens",
                                 "format": "int_thousands"},
    "baseline.saved_pct":       {"source": "100*(baseline.total_tokens - run.tokens.gen_consumed)/baseline.total_tokens",
                                 "format": "pct1"},
    "baseline.latency_x":       {"source": "baseline_json.totals.e2e_ms / run.total_ms",
                                 "format": "x1"}
  },
  "invariants": [
    "un solo run.json per tutti i token run_json (R1)",
    "baseline e run della stessa sessione, stesso corpus, stesso modello (R6)",
    "se baseline_json assente o non conforme a totals.* -> baseline.label, mai un numero (R2)",
    "tokens.saved_pct non compare a schermo: headline = baseline vs noi (R5)",
    "batch.* solo se il batch e' stato eseguito (R3)",
    "il testo registrato non contiene '{{' (R4)"
  ]
}
```

---

## 0.5 Headline like-for-like (default, non una variante)

Il frame comparativo confronta **due misure reali, stesso corpus, stesso modello**: la baseline agentica
e la nostra pipeline. Non è una formula, è una sottrazione fra due file.

| Lato sinistro (baseline) | Lato destro (nostra) |
|---|---|
| `{{baseline.llm_calls}}` chiamate LLM | 1 chiamata |
| `{{baseline.total_tokens}}` token (in+out, somma `usage` reali) | `{{tokens.gen_consumed}}` token (in+out) |
| `{{baseline.prompt_tokens}}` prompt token | `{{tokens.generator_prompt}}` prompt token |
| `{{baseline.e2e_ms}}` ms end-to-end | `{{total_ms}}` ms end-to-end |

Headline ammessa: **"`{{baseline.total_tokens}}` → `{{tokens.gen_consumed}}` tokens per query
(`−{{baseline.saved_pct}}%`), `{{baseline.llm_calls}}` generative calls → 1, same corpus, same model."**
Nessun moltiplicatore, nessun range: due file, due misure, un comando.

- Il confronto è **total vs total** (in+out da entrambi i lati). Confrontare i soli `prompt_tokens` della
  baseline col totale nostro dà un numero più basso e sbagliato: la formula in §0.4 è quella giusta.
- `{{baseline.latency_x}}` è ammesso solo come rapporto fra due `e2e_ms` misurati, mai come range.
- Se `baseline.saved_pct` risultasse negativo la pipeline è più cara della baseline: si mostra il segno
  vero e si **taglia** il frame (mai girarlo).
- Se la baseline non è misurata (R2), questo frame **non esiste**: non si sostituisce con `raw_est`,
  si taglia e si tiene solo il claim architetturale di §5.

---

## 0.6 Valori di riferimento — rinvio alla fonte unica, NON testo di scena

I valori di riferimento vivono in `agents/ceo/review/VERIFIED_NUMBERS.md`, aggiornato dal gate CEO; qui non si
duplicano.

Questa sezione esiste per **revisionare** lo script (il frame è coerente? il claim regge?), non per essere letta:
a schermo vanno solo i segnaposto, compilati da §0.3 con il run della registrazione.

**Varianza, senza cifre.** Lo speedup dipende dal carico del provider e si calcola sempre dai due file della
registrazione; il token delta è stabile.

**Attenzione, due trappole già viste:**

1. I file committati **non** contengono i valori del copione, e non devono: `backend/baseline_metrics.json` e
   `backend/run.json` vengono rigenerati a ogni refactor (corpus ampliato; `generated_at` può essere assente, e
   per R6 la riga di provenienza a schermo dichiara "baseline: earlier run"). Copiare quei numeri qui li
   renderebbe falsi entro un'ora — da qui R1/R6 e il divieto di cifre letterali.
2. `tokens.saved_pct` è **diagnostica, non un claim**: il suo segno dipende dal perimetro del corpus e dal run
   (negativo quando il prompt reale supera la stima degli snippet, positivo quando il corpus è largo), quindi
   non è citabile come risultato. Da qui R5: non compare in nessun frame, e la parola
   "saved" non si usa mai a schermo — se il valore è negativo si dice **overhead**.

---

## 1. Apertura (0:00–0:15) — 3 frasi, problema reale

> "Two headlines, one earnings call, opposite numbers. An analyst has to reconcile them — or guess. That guessing costs money, and it's exactly where today's AI agents fail: they feed the *entire* noisy context to an expensive model and hope."

- Schermo: due headline in conflitto (es. "BEATS GUIDANCE" vs "DOWNGUARDS"). Nessuna cifra.
- Tasto Invio → query in esecuzione.

## 2. Pipeline live (0:15–0:55) — il cuore

> "Watch what the model *never* sees."

- Visual con flusso snippet → NOUL (rosso: drop) → SCORE (barre ascendenti) → CHOICE (zig-zag conflitto) → GENERATORE (verde).
- I due counter girano in diretta, alimentati da `run.json`:
  1. **E2E LATENCY** → `{{total_ms}}` ms, con barra etichettata `baseline {{baseline.e2e_ms}} ms` (misurata)
     **oppure** `{{baseline.label}}` (non misurata). Scala della barra = `max(total_ms, baseline.e2e_ms)`;
     se la baseline non è misurata la barra **non** ha una scala numerica: resta l'etichetta architetturale.
  2. **TOKENS PER QUERY** (contachilometri, like-for-like §0.5):
     `{{baseline.total_tokens}} → {{tokens.gen_consumed}} · −{{baseline.saved_pct}}%`.
     Se la baseline non è misurata il counter si ferma sul solo `{{tokens.gen_consumed}}`, etichettato
     "our tokens", **senza** rapporto e senza la coppia con `raw_est` (R5).
- Narrazione sincronizzata: "NOUL discarded `{{noul.dropped}}` of `{{noul.total}}` sources before they cost a single token. CHOICE says `{{choice.label}}`. One generative call: `{{gen.total_tokens}}` tokens in and out — the classic agent pays `{{baseline.llm_calls}}` calls and `{{baseline.total_tokens}}` for the same query."
  Se la baseline non è misurata, la seconda metà della frase si **cancella** (non si sostituisce).
- Il caso a schermo è la fonte dei suoi stessi numeri (R1): su FC-01 il drop è 1 di 6 nel run CEO, 1 di 5
  nel run attuale del refactor — **non è un errore**, è il run che gira. Sul caso noise (FC-05) il drop è
  totale: usabile come insert di 2s **solo** se quel run è quello a schermo, mai come numero preso in prestito.

## 3. What the GPU never saw (0:55–1:20) — il visual choc

> **Guardia:** questo frame è un **confronto**, quindi esiste solo se la baseline è misurata (R2) e viene
> dallo stesso corpus/modello (R6). Se manca, il frame si taglia: non si riempie con `raw_est` (R5).

> "Left: what a classic agent pays for this query — `{{baseline.llm_calls}}` calls, `{{baseline.total_tokens}}` tokens, every snippet re-sent on every call. Right: one call, `{{tokens.gen_consumed}}` tokens — already reconciled, already cited. `−{{baseline.saved_pct}}%`."

- Split-screen: a sinistra la **sequenza** delle chiamate della baseline (una riga per call, la somma che sale:
  `{{baseline.llm_calls}}` righe); a destra **una** riga sola. Il contrasto visivo è "N righe vs 1", non
  "tanto vs poco".
- Sotto i due lati, i due valori misurati: `{{baseline.total_tokens}}` vs `{{tokens.gen_consumed}}`.
- Riga di provenienza a schermo, obbligatoria:
  `run.json · total_ms {{total_ms}} · baseline_metrics.json · totals.e2e_ms {{baseline.e2e_ms}}`.
- Speaker in silenzio 3s (silenzio = potenza).
- **Vietato** in questo frame: `raw_est` come lato sinistro, `tokens.saved_pct`, la parola "context" riferita
  a un risparmio (R5), e qualunque frase sull'uguale qualità della risposta (nessun eval harness: §9).

## 4. Throughput (1:20–1:45) — scalabilità

> "Now `{{batch.n_runs}}` analysts ask at once." (lancio del batch)

> "Each row is its own measured run. The slowest of `{{batch.n_runs}}` was `{{batch.max_total_ms}}` ms — because five of the six stages never touch the model — only the last one generates."

- Schermo: `{{batch.n_runs}}` righe in parallelo, ognuna col proprio `total_ms`; in evidenza il massimo.
- Se il batch non è stato eseguito: **sezione tagliata** (PLAN §7), non simulata.
- **Nessuna cifra di GPU** in questa sezione (né token/sec, né run/sec, né "per GPU"): non c'è una GPU AMD
  su questa macchina, quindi quel numero non è misurabile (BUILD_SPEC §0). La scalabilità si mostra come
  latenza stabile per run — che è misurata.

## 5. Chiusura (1:45–2:00) — differenziazione + AMD

> "Classic agents make the GPU do everything. We let the GPU do only the one thing it's for — generation — and push five of the six stages to fast, typed discriminative decisions. That's not a better model. It's a better computer. Target: ROCm, one card, batched."

- On-screen (solo valori misurati + claim architetturale, **nessun moltiplicatore**):

  ```
  {{baseline.total_tokens}} → {{tokens.gen_consumed}} tokens per query · −{{baseline.saved_pct}}%
  {{baseline.llm_calls}} generative calls → 1
  one generative call per query · the rest is a batched forward pass
  target: ROCm · one card · batched
  ```

- Riga latenza ammessa **solo se** la baseline è misurata (R2/R6), come rapporto fra due misure:

  ```
  {{total_ms}} ms end-to-end · classic agent {{baseline.e2e_ms}} ms · {{baseline.latency_x}}×
  ```

- Se la baseline non è misurata: restano solo `{{tokens.gen_consumed}}` (etichettato "our tokens per query")
  e le righe architetturali. **Nessun numero al posto del confronto.**
- **ROCm è intenzione, non esecuzione.** Su questa macchina non c'è una GPU AMD (si gira via OpenRouter):
  "ROCm runs it" al presente è un'**affermazione di fatto** che non possiamo mostrare — un giudice chiede il
  run su ROCm e non c'è. Il claim si enuncia quindi come **portabilità by design** ("target: ROCm", "runs on
  ROCm by design"), mai come esecuzione avvenuta. Stessa regola dei numeri: si mostra solo ciò che è misurato,
  oppure lo si dichiara come intenzione (VERIFIED_NUMBERS §"Vietati").
- Vietato su questo frame: "5-12x", "10-30x", "throughput per GPU", "9.4k tokens saved", "ROCm runs it" al
  presente, qualunque rapporto non misurato (BUILD_SPEC §0: senza GPU AMD il throughput è architetturale). Vedi §9.

## 6. FC-06 (fallimento tipizzato) — ORA misurato, resta condizionale alla registrazione (D5)

Con il corpus a 10 casi (26/10), il run misurato delle 15:21 su FC-06 dà
`stages.choice.label = INSUFFICIENT`·`stages.guard.action = insufficient`·
`stages.generator.called = false`·`status = skipped` (jq su `backend/runs/FC-06.json`):
il **rifiuto tipizzato è prodotto dal codice ed è una feature dimostrata**. Il sweep delle 10:17
(sul corpus a 6 casi) aveva misurato il contrario (`CONFLICT` + `resolved`); con il pool a 53
sorgenti il caso Microsoft-Inflection non trova una fonte primaria dominante e il guard ferma
il generatore: è esattamente la parte "the generator can refuse".

L'insert da 8s va nel montaggio **solo se** al momento della registrazione:

1. il run di FC-06 usato è **quello del video** (stesso corpus/modello, R6), verificato con `jq`;
2. su quel run: `choice.label = INSUFFICIENT`, `guard.action = insufficient`,
   `generator.called = false`, `generator.status = skipped`;

Se una manca, la sezione **si taglia**: nessun fallimento recitato a mano, nessun `unresolved` scritto per
ipotesi. Nota di contratto: il fallimento tipizzato si presenta come **`skipped` + "0 gen calls"**, non come
`unresolved` (BUILD_SPEC §2.10) — `unresolved` significa che il generatore ha risposto senza risolvere, ed è
un'altra cosa. Questa è la dichiarazione esplicita richiesta da D5.

## 7. One-liner di backup (se il timing stringe)

> "Every token the generator never sees is free compute. We monetize ignorance."

Nessuna cifra: usabile senza sostituzioni.

## 8. Regole di registrazione

- **La coppia run + baseline si genera insieme**, nello stesso momento e con lo stesso corpus/modello (R6):
  un solo comando: `bin/demo --freeze` (esegue i 10 casi, misura il throughput, scrive `run.json`,
  congela per il fallback e copia in `frontend/`), poi `bin/gen-verified-numbers` per i segnaposto.
  Se una delle due è vecchia, la barra e i frame comparativi tornano a `{{baseline.label}}` / si tagliano.
- 1 query live (realtà) + 1 rehearsal deterministico (`--offline`) per lo split-screen; i due run non si mescolano (R1).
- I counter **non** sono animati a mano: contano dal vivo dal processo reale, o leggono `run.json`.
- Prima di registrare: sostituire **tutti** i segnaposto di §0.1 con i valori di §0.3 e verificare che sul
  copione di registrazione (non su questo file) non resti nessuna doppia graffa: `grep -c '{{' <copione>` → 0.
- Controllo anti-cifra-inventata sul copione compilato: ogni numero a schermo deve comparire nell'output di
  §0.3. In pratica: `grep -oE '[0-9][0-9.,]*' <copione> | sort -u` e ogni voce va ritrovata nei due file.
- Se la latenza live sfora il budget, si mostra sforata (`within_budget: false`) e si taglia il throughput —
  mai truccare il ticker.
- Ogni frame con cifre ha una riga di provenienza a schermo (`run.json` / `baseline_metrics.json`): è la
  verifica visiva di D2/D6.

## 9. Igiene dei claim (cosa NON diciamo, e perché)

| Claim rimosso | Perché | Cosa diciamo al suo posto |
|---|---|---|
| "−92% context" / "12.4k raw vs 940" | non omogeneo (stima snippet vs prompt reale) e aritmeticamente falso su questo corpus: il valore vero è negativo (R5) | `{{baseline.total_tokens}} → {{tokens.gen_consumed}}` con `−{{baseline.saved_pct}}%` |
| "the generator received 940 validated tokens, not 12,480" | confronta due grandezze diverse (prompt nostro vs token baseline) e usa cifre di un run vecchio | "`{{baseline.llm_calls}}` calls and `{{baseline.total_tokens}}` tokens vs one call and `{{tokens.gen_consumed}}`" |
| "5-12x lower latency" | moltiplicatore non misurato | `{{baseline.latency_x}}×`, solo fra due `e2e_ms` misurati |
| "10-30x throughput per GPU" | richiede GPU AMD (BUILD_SPEC §0) | "one generative call per query, the rest is a batched forward pass; target: ROCm, one card" |
| "ROCm runs it" (al presente) | nessuna GPU AMD su questa macchina: è un'**affermazione di fatto** non verificabile, più facile da contestare di una cifra | "target: ROCm · one card · batched" — portabilità dichiarata, non esecuzione (§5) |
| "the generator can refuse" / typed failure come feature | al 26/10 15:21 FC-06 dà `INSUFFICIENT` + `skipped` su `backend/runs/FC-06.json` (corpus 10 casi) | la frase si usa solo se il run del video è quello misurato (§6) |
| "9.4k tokens saved" | numero di un run vecchio, e su base non omogenea | il risparmio è quello di §0.5, con segno e provenienza |
| "Same answer quality" | nessun eval harness nel timebox: non è verificabile con un comando del repo | "already reconciled, already cited" (fatto strutturale: `stages.choice.label`, citazioni in `run.json`) |
| "GPU-sec/query" come cifra | non misurabile senza GPU AMD | rapporto token/query (hardware-agnostico), misurato |

Un claim forte e vero non ha bisogno di cifre finte: "one generative call, the rest is a batched forward
pass" è architettura, non misura — e resta vero qualunque sia la latenza misurata.

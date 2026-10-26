# AMD AI League · Match 4 — BUILD SPEC (esecuzione)

> Stato: **contratti CONGELATI v1.2 (26/10 10:20 UTC)** — vedi `PLAN.md` per dipendenze, timebox e criteri di accettazione.
> Deadline 27 Ott. Solo builder, fase no-code chiusa.
> Principio guida: **costruire la demo, non il prodotto.** Ogni modulo qui sotto esiste solo se compare nei 120 secondi.
>
> **Changelog v1.2** (BOH-3): §2 riscritto contro l'implementazione già presente in `backend/` (letta il 26/10 10:15).
> Il contratto ora **descrive il codice che gira**, non un'idea parallela: i dev non devono rifare nulla, solo
> applicare 6 rinominazioni elencate in §2.11. Chiusi i buchi: `run.json` (assente in v1.0), enum di
> `publisher_type`, `confidence` in CHOICE (la guardia la usava senza che fosse nel contratto), formule di
> `reliability`/`confidence`, regola anti-leakage del ground truth, contabilità token, gestione errori, CLI.

## 0. Vincoli operativi (dalla strategia)

- **Fork aperto**: codice sì/no non deciso → questa spec è vendorable a entrambi (heuristics + embeddings = fase 1, testa discriminativa Jev-class su ROCm = fase 2).
- Backend: Python (FastAPI) già familiare. System Two su OpenRouter già configurato (deepseek-v4-flash come default; in demo si mostra Llama-3.1-8B *intenzionalmente* per la narrativa "open-source su ROCm").
- Delegazione possibile a `agy` (Antigravity) per blocchi isolati.
- ROCm: non certo disponibile in locale → i numeri di throughput vanno misurati su GPU AMD affittata (RunPod/Modal MI-series) per i frame D5. In assenza: numero architetturale normalizzato (token/query) che non richiede hardware AMD per essere vero.

## 1. Architettura software (DAG a un solo cammino)

```
query
  -> RETRIEVER        : corpus pre-curato JSON + 1 sorgente live (SerpAPI/Bing)
  -> NOUL (gate bool): keep/drop per snippet  -> drop 60-70%
  -> SCORE (rank)    : relevance[0,1] x reliability[0,1] sul supersite
  -> CHOICE (conf)   : pairwise agree/disagree/unrelated + verdetto + claim-id
  -> GUARDIA (spec)  : conf < soglia -> expand / INSUFFICIENTE
  -> GENERATORE      : 1 chiamata, top2-3 sorgenti validate, output tipizzato {verdetto,citazioni}
```

## 2. Contratto dei moduli (interfacce dati, non codice)

Regola generale: **i nomi di campo e i valori degli enum sono esattamente quelli scritti qui**
(snake_case; enum macchina in MAIUSCOLO per i verdetti, minuscolo per stati e motivi).
Un dev che aggiunge un campo lo mette **in coda** e lo segnala su BOH-3: non rinomina, non rimuove.

### 2.0 Costanti canoniche (`backend/config.py` o costanti di modulo)

| Costante | Valore | Dove vive oggi |
|---|---|---|
| `TOP_K` | **6** (CLI `--top-k`, range ammesso 5–8) | `pipeline.py` default |
| `EXPAND_K` | 8 (CLI `--expand-k`) | `pipeline.py` |
| `GUARD_THRESHOLD` | 0.60 | `guard.py` |
| `MAX_EXPANSIONS` | 1 | `pipeline.py` |
| `GEN_MIN_SOURCES` / `GEN_MAX_SOURCES` | 2 / 3 | `generator.py` |
| `GEN_TOKEN_BUDGET` | 1500 (pre-check su `prompt_tokens_est`) | `generator.py` |
| `GEN_TIMEOUT_S` | 20 | `generator.py` |
| `E2E_BUDGET_MS` | 1200 (`BUDGET_MS`) | `pipeline.py` |
| `NOUL_DROP_TARGET` | 0.60–0.70 sui casi FC-01..FC-04 | `noul.py` (target, non hard rule) |

### 2.1 Entità `Snippet` (unico formato scambiato tra i moduli)

```json
{
  "id": "FC-01-S1",
  "case_id": "FC-01",
  "source_url": "https://...",
  "source_name": "NVIDIA Newsroom",
  "publisher_type": "official",
  "date": "2026-02-25",
  "title": "Q4 FY2026 financial results",
  "content": "2-4 frasi di testo piano, senza HTML."
}
```

- `id`: **globalmente univoco**, formato `<case_id>-S<n>` (`n` da 1). È la chiave usata da SCORE/CHOICE/GEN/UI.
- `publisher_type`: enum chiuso **`official | press | report | blog | noise`**. Il corpus usa solo questi 5
  valori (niente `seo`/`contentfarm`: `noise` copre il rumore, il motivo del drop lo decide NOUL).
- `date`: `YYYY-MM-DD` (solo giorno, niente timezone).
- `source_url`: URL assoluto; `""` ammesso **solo** per `publisher_type = "noise"`.
- `title`: obbligatorio e non vuoto. `content`: 2–4 frasi, 200–1200 caratteri.
- **Anti-leakage (vincolante)**: `truth`, `truth_url`, `claim`, `verdict_in_corpus`, `notes` del corpus sono
  materiale di sola valutazione. L'implementazione lo garantisce strutturalmente (`Snippet` è una dataclass
  tipizzata che non li ha come campi); il vincolo resta: **nessuno di questi valori può comparire in
  `run.json` né nel prompt del generatore**. Verifica: AC-P8.

### 2.2 RETRIEVER (`retriever.py`)

- Input: `case_id` (es. `"FC-01"`), **query del caso**, o query libera; `--corpus PATH` (default
  `backend/corpus.json`); `--live PATH` (snapshot JSON opzionale).
- Output: `list[Snippet]` = **pool dell'intero corpus** (tutti i casi + eventuale live), nessun filtro:
  filtra NOUL. Il caso selezionato serve a fissare la query e a focalizzare SCORE (vedi §2.3/§2.4).
  Motivo: il pool rumoroso è ciò che rende vera la frase del video "NOUL discarded 6 of 24 sources".
- Query libera → stesso pool; il caso migliore è scelto per similarità. La demo usa un `case_id`.
- Live: **file JSON di snapshot** (`--live PATH`), non una chiamata API. Motivo: `SERPAPI_KEY` non è in
  `/srv/ai-company/.env` e non vogliamo una dipendenza esterna in un demo da registrare. Lo snapshot è
  marcato in `run.json` (`selection_mode`, `offline`).
- Errori: corpus assente / formato non riconosciuto → `ValueError`/`FileNotFoundError` → CLI exit **2**,
  nessun `run.json` scritto.

### 2.3 NOUL — gate bool (`noul.py`)

- Input: `Snippet` + query. Output per snippet: `NoulResult{snippet, keep, confidence, reason, similarity, signals}`.
- **Invariante**: `keep == true` ⇔ `reason == "keep"`. Nessuna eccezione.
- `reason` enum: `spam | boilerplate | seo | off-topic | keep`.
- **Vincoli** (l'algoritmo è libero, questi no):
  1. deterministico, nessun LLM, nessuna rete, nessuna casualità;
  2. drop rate 60–70% sui casi FC-01..FC-04; `noise` sempre droppato;
  3. **il generativo non vede mai un drop**: nessun `content` di snippet scartato può finire nel prompt;
  4. 0 sopravvissuti è un esito legittimo (caso FC-05) e **non** si "ripara": la pipeline chiude con
     `INSUFFICIENT` e generatore non chiamato. Non esiste alcun floor artificiale.
- Segnali oggi implementati (riferimento, modificabili entro i vincoli): `publisher_type` noise → drop,
  blacklist domini/nomi, lunghezza < 18% della mediana, pattern boilerplate, similarità TF-IDF < 0.035.
- NOUL gira sul **pool completo** (tutti i casi del corpus): `stages.noul.total` è la dimensione del pool,
  non del caso. SCORE poi si focalizza sugli snippet del caso selezionato (`case_id`) che sono sopravvissuti.
  Invariante verificabile: `len(sources) == stages.retriever.snippets == stages.noul.total`.

### 2.4 SCORE — rank (`score.py`)

- Input: tutti i `NoulResult` + query. Output per snippet (`ScoreResult.to_dict()`):
  `{...snippet, rank, relevance, reliability, reliability_breakdown{authority, recency, consistency}, score}`.
- `score = relevance * reliability` → **chiave di ordinamento** (desc); tie-break `id` crescente; `rank` 1-based.
- `reliability = 0.5*authority + 0.25*recency + 0.25*consistency` (pesi fissi).
  - `authority`: `official 1.00 · report 0.85 · press 0.70 · blog 0.35 · noise 0.00` (+ `unknown` per fallback)
  - `recency`: decadimento lineare sulla **data massima del caso** (non "oggi": il run resta riproducibile)
  - `consistency`: accordo sulle cifre/date con gli altri sopravvissuti; `0.5` se lo snippet non ha cifre
- `relevance`: similarità TF-IDF (fallback embedding piccolo) normalizzata 0..1.
- Output dello stage: lista ordinata completa (cap `max(top_k, expand_k, min(8, len(kept)))`) e i top `TOP_K`
  passati a CHOICE. `stages.score.ranked_count` conta i **sopravvissuti del caso selezionato** (il pool di
  scoring è focalizzato su `case_id`, non l'intero corpus). Deterministico, nessuna rete.

### 2.5 CHOICE — conflitto e verdetto (`choice.py`)

```json
{
  "label": "CONFLICT",
  "verdict": "NVIDIA Newsroom: EPS 0.89 (Q4 FY2026) — il titolo di stampa riporta 0.71",
  "claim": "eps_q4_fy26",
  "claim_id": "FC-01:eps_q4_fy26",
  "confidence": 0.78,
  "evidence": ["FC-01-S1", "FC-01-S3"],
  "conflict_pairs": [{"a": "FC-01-S1", "b": "FC-01-S2", "relation": "disagree"}],
  "supporting": {"FC-01-S1": ["eps_q4_fy26"]}
}
```

- **`label` = token macchina** (enum `RESOLVED | CONFLICT | INSUFFICIENT`), **`verdict` = frase umana**
  (mostrata in UI). Sono due campi distinti: la UI colora su `label`, il video legge `verdict`.
- `confidence` (obbligatorio, 0..1): input della guardia. Deve essere deterministico e documentato in testa
  a `choice.py`; la soglia `0.60` è normativa, la formula no (purché: cresca con la reliability
  dell'evidenza, cali con i conflitti irrisolti, sia stabile a parità di input).
- `claim_id`: `<case_id>:<slug>` snake_case del fatto riconciliato; **stabile** tra run dello stesso caso.
- `relation` enum: `agree | disagree | unrelated`, calcolato su tutte le coppie `C(n,2)` dei top-K
  (max 15 con K=6). Coppie non confrontabili → `unrelated`.
- `evidence`: sottoinsieme dei top-K che sostiene il verdetto, ordinato per `score` desc; `[]` solo con
  `label = INSUFFICIENT`.
- Regola di verdetto, in quest'ordine:
  1. `confidence < 0.60` → `INSUFFICIENT` (la guardia può ancora espandere una volta)
  2. esiste una coppia `disagree` con entrambe le authority `>= 0.70` → `CONFLICT`
  3. altrimenti → `RESOLVED`
- Input vuoto (0 sopravvissuti) → `INSUFFICIENT`, `confidence 0.0`, `evidence []`, `claim_id` valorizzato.
  CHOICE non chiama il generativo e non inventa nulla.

### 2.6 GUARDIA (`guard.py`)

```json
{
  "triggered": false, "action": "pass", "sufficient": true, "confidence": 0.78,
  "label": "CONFLICT", "verdict": "frase umana", "reason": "confidence 0.78 >= 0.60", "threshold": 0.6
}
```

- `action` enum: `pass | expand | insufficient`. Regola deterministica:
  1. `confidence >= 0.60` → `pass`
  2. `confidence < 0.60` e non ancora espanso e ci sono candidati in più → `expand`: si allarga il pool a
     `EXPAND_K = 8` e si riesegue **solo CHOICE** (SCORE non si ricalcola), una volta sola
  3. dopo l'espansione ancora `< 0.60` → `insufficient`, `label = "INSUFFICIENT"`
- Con `insufficient` il generativo **non viene chiamato**: nessuna risposta forzata senza evidenza.
- Il verdetto canonico è **`INSUFFICIENT`** (inglese): è un token di enum mostrato in UI. Mai `INSUFFICIENTE`.

### 2.7 GENERATORE — System Two (`generator.py`)

- Input: query + `choice` + lista ranked (usa le prime 2–3 sorgenti validate, mai più di `GEN_MAX_SOURCES`)
  + istruzioni rigide + schema JSON di output. **Una sola chiamata**, `temperature 0`.
- Modello: classe Llama-3.1-8B via OpenRouter (`OPENROUTER_API_KEY` da env, `OPENROUTER_MODEL` opzionale).
- Output:
```json
{
  "called": true,
  "status": "resolved",
  "answer": "testo (<= 400 caratteri, inglese)",
  "confidence": 0.7,
  "citations": [{"source_id": "FC-01-S1", "claim_id": "FC-01:eps_q4_fy26"}],
  "model": "meta-llama/llama-3.1-8b-instruct",
  "provider": "…",
  "usage": {"prompt_tokens": 940, "completion_tokens": 62, "total_tokens": 1002},
  "latency_ms": 640.2,
  "prompt_tokens_est": 902,
  "error": null
}
```
- `status` enum: `resolved | unresolved | skipped | error`.
  - `skipped` = generatore **non invocato** (`called: false`): guardia insufficiente, `--offline`, oppure
    nessuna fonte validata. **Non** è `unresolved`: la UI deve mostrare "0 gen calls · typed failure".
  - `error` = chiamata tentata e fallita (HTTP/timeout/parse): `error` valorizzato, pipeline esce **0**.
- Invarianti: `citations ⊆ evidence`; `status = unresolved` ⇒ `citations = []`; `status = resolved` senza
  citazioni ⇒ degrada a `unresolved` (non si mostra una risposta non citata come risolta).
- **Contabilità token (onestà)**: `usage.*` dai campi `usage` della risposta API, mai stimati.
  `prompt_tokens_est` = stima `ceil(caratteri/4)` usata solo per il pre-check del budget, e in `run.json`
  è sempre etichettata come stima (`gen_consumed_measured: false`).

### 2.8 Contratto `run.json` (core-dev → UI)

Prodotto da `python pipeline.py <case> --dump-json` → `backend/run.json`, copiato in `frontend/run.json`.
Schema machine-checkable: `specs/amd-ai-league/schemas/run.schema.json`. Struttura (esempio reale):

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-26T10:20:00.123456+00:00",
  "query": "NVIDIA Q4 FY2026 earnings guidance",
  "query_arg": "FC-01",
  "case_id": "FC-01",
  "case_subject": "guidance ufficiale vs headline",
  "selection_mode": "case_id",
  "offline": false,
  "model": "meta-llama/llama-3.1-8b-instruct",
  "stages": {
    "retriever": {"ms": 3.1, "snippets": 24},
    "noul": {"ms": 18.4, "total": 24, "kept": 18, "dropped": 6, "drop_pct": 25.0,
             "decisions": [{"id": "FC-01-S1", "keep": true, "reason": "keep", "confidence": 0.81,
                            "similarity": 0.42, "signals": {}}]},
    "score": {"ms": 27.0, "ranked_count": 18, "top_k": 6,
              "ranking": [{"id": "FC-01-S1", "rank": 1, "relevance": 0.91, "reliability": 0.91,
                           "reliability_breakdown": {"authority": 1.0, "recency": 1.0, "consistency": 0.62},
                           "score": 0.83, "used_in_generation": true}]},
    "choice": {"ms": 41.2, "label": "CONFLICT", "verdict": "frase umana", "claim": "eps_q4_fy26",
               "claim_id": "FC-01:eps_q4_fy26", "confidence": 0.78,
               "evidence": ["FC-01-S1"], "conflict_pairs": [{"a": "FC-01-S1", "b": "FC-01-S2", "relation": "disagree"}],
               "supporting": {"FC-01-S1": ["eps_q4_fy26"]}},
    "guard": {"ms": 0.2, "triggered": false, "action": "pass", "sufficient": true, "confidence": 0.78,
              "label": "CONFLICT", "verdict": "frase umana", "reason": "confidence 0.78 >= 0.60",
              "threshold": 0.6, "expanded": false},
    "generator": {"ms": 640.0, "called": true, "status": "resolved", "answer": "…", "confidence": 0.7,
                  "citations": [{"source_id": "FC-01-S1", "claim_id": "FC-01:eps_q4_fy26"}],
                  "model": "meta-llama/llama-3.1-8b-instruct", "provider": "…",
                  "usage": {"prompt_tokens": 940, "completion_tokens": 62, "total_tokens": 1002},
                  "latency_ms": 640.0, "prompt_tokens_est": 902, "error": null}
  },
  "sources": [
    {"id": "FC-01-S1", "source_name": "NVIDIA Newsroom", "publisher_type": "official",
     "date": "2026-02-25", "source_url": "https://…", "title": "…", "content_preview": "…",
     "tokens_est": 310, "keep": true, "reason": "keep", "noul_confidence": 0.81, "similarity": 0.42,
     "rank": 1, "relevance": 0.91, "reliability": 0.91, "score": 0.83, "used_in_generation": true}
  ],
  "total_ms": 780.3,
  "budget_ms": 1200.0,
  "within_budget": true,
  "tokens": {
    "raw_est": 12480, "kept_est": 3120, "curated_est": 902,
    "generator_prompt": 940, "generator_completion": 62, "generator_total": 1002,
    "gen_consumed": 1002, "gen_consumed_measured": true,
    "saved": 11540, "saved_pct": 92.5, "estimate_method": "chars/4"
  },
  "ticker": {"noul": "…", "score": "…", "choice": "…", "guard": "…", "generator": "…", "total": "…"}
}
```

Definizioni vincolanti (servono a non barare in UI):
- `total_ms` = `perf_counter()` attorno all'intero run (retriever→generator), esclusi import/startup.
  I `stages.*.ms` sono misurati singolarmente: la loro somma può essere minore di `total_ms`.
- `stages.noul.kept` / `dropped` sono **conteggi**; `keep` (bool) esiste solo dentro `sources[]` e `decisions[]`.
- `stages.score.ranked_count` è un **intero**; la lista è `stages.score.ranking`.
- Invariante del pool: `len(sources) == stages.retriever.snippets == stages.noul.total`; la somma
  `kept + dropped` deve coincidere con `total`. La UI dimensiona il diagramma di flusso su questi numeri.
- `sources[]` = tutti gli snippet recuperati, con esito NOUL, punteggio e `used_in_generation`. È la fonte
  dati del diagramma di flusso (drop rossi, barre SCORE, evidenze citate). Nessun campo di ground truth.
- `tokens.raw_est` = token di **tutti** gli snippet recuperati (ciò che un agente classico passerebbe);
  `tokens.generator_prompt` = token di prompt reali dal `usage` API.
- **`tokens.saved_pct` si calcola su `generator_prompt`, non su `gen_consumed`**:
  `saved_pct = round(100 * (raw_est - generator_prompt) / raw_est, 1)` quando `generator_prompt` è
  disponibile, altrimenti su `gen_consumed`. È il numero del frame "what the GPU never saw": confronto
  prompt-vs-crud, non totale-vs-crud.
- Se `generator.called = false` → `usage` = `null`/zeri, `tokens.gen_consumed = 0`, e la UI mostra
  "0 gen calls · typed failure" (mai un risparmio del 100% spacciato per merito).
- **`saved_pct` non si clampa.** `raw_est` è una *stima* dei soli snippet, `generator_prompt` è il prompt
  *reale* (che include system prompt, istruzioni di citazione e formattazione). Su un caso con pochi snippet
  (~6) l'overhead fisso può superare il contenuto e il rapporto diventa **negativo**: si riporta il valore
  vero (es. `-179.1`), mai `-100`. Lo schema `run.schema.json` non impone più il minimo a `-100`.
- **Il confronto in video è like-for-like**: prompt contro prompt (`baseline_metrics.json`
  `totals.prompt_tokens` vs `tokens.gen_consumed`), non stima-snippet contro prompt-reale. La differenza
  `raw_est` vs `generator_prompt` resta nel `run.json` come diagnostica, ma non è la cifra di apertura
  (vedi `DEMO_SCRIPT.md` §0.5 variante B).

### 2.9 CLI e output a terminale (`pipeline.py`)

```bash
python pipeline.py "<case_id|case_query|query>" [--dump-json] [--corpus PATH] [--live PATH]
                   [--top-k 6] [--expand-k 8] [--offline]
```
- `--dump-json` è un flag (scrive sempre `backend/run.json`). `--offline` salta la chiamata al generatore
  (`status: skipped`) e serve per i test deterministici e per il rehearsal.
- Ticker stdout: **6 righe, nessun colore ANSI**, formattazione stabile (padding 42), formato:
```
NOUL: 18/24 keep (6 drop)                  [18ms]
SCORE: top6 ordinati                       [27ms]
CHOICE: CONFLICT FC-01-S1 vs FC-01-S2      [41ms]
GUARD: pass (conf 0.78)                    [0ms]
GEN: resolved | 1 citations                [640ms]
TOTAL: 780ms | tokens_gen_consumed: 1002 | tokens_crud_est: 12480 (-92%)
```
- Exit code: `0` successo (anche con `unresolved`/`skipped`/`error` del generatore); `2` errore di input
  (corpus assente/illeggibile, case inesistente). Su exit 2 nessun `run.json` parziale.
- Se `total_ms > budget_ms`: riga `WARN` su **stderr** e `within_budget: false`. Il ticker resta vero.

### 2.10 Determinismo

- `--offline` + stesso `corpus.json` + stessa query ⇒ stesso `run.json` a meno di `generated_at` e `ms`.
  Nessuna casualità nei moduli discriminativi, nessuna rete (in `--offline`), tie-break sempre su `id`.
- Con generatore attivo variano solo `stages.generator`, `usage`, `tokens.*` e i tempi: è atteso e dichiarato.
- Il frame "what the GPU never saw" usa un run `--offline` (deterministico) o un run reale con i suoi numeri:
  mai un mix.

### 2.11 Delta da applicare al codice esistente (8 punti, nessuna logica)

Contratto v1.2 = codice attuale **+** questi punti. Sono tutti meccanici (~20 min):

| # | Oggi | Diventa | Perché |
|---|---|---|---|
| 1 | `stages.noul.keep` (int) | `stages.noul.kept` | collide col bool `keep` in `sources[]`/`decisions[]` |
| 2 | `stages.noul.drop` (int) | `stages.noul.dropped` | coerenza con `kept` |
| 3 | `stages.score.ranked` (int) | `stages.score.ranked_count` | collide con la lista `ranking` |
| 4 | `choice.label = "AGREE"` | `"RESOLVED"` | vocabolario unico con `generator.status = resolved` |
| 5 | `choice.label`/`guard.label = "INSUFFICIENTE"` | `"INSUFFICIENT"` | token di enum in inglese (demo in inglese) |
| 6 | generatore non invocato → `status: "unresolved"` | `status: "skipped"` | il video dice "0 gen calls": skipped ≠ unresolved |
| 7 | `tokens.saved_pct` su `gen_consumed` | su `generator_prompt` | è il numero del frame "never saw" (prompt vs crud) |
| 8 | `saved_pct` clampato a `-100` (schema `minimum: -100`) | valore vero, anche negativo | un numero clampato è un numero falso: viola D6 |

Nient'altro cambia: struttura, nomi degli altri campi e logica restano quelli già scritti.

## 3. Metriche da misurare (D3) — numeri V E R I della barra di confronto

| Metrica | Nostra pipeline | Baseline agentica (stesso corpus) |
|---|---|---|
| Chiamate al generativo | 1 (`0` se `status: skipped`) | 4-6 |
| Token processati/query | misurare | misurare |
| Latenza E2E (ms) | misurare | misurare |
| GPU-sec/query | misurare | misurare |
| Costo $/query | misurare | misurare |

**Regola di onestà**: se la baseline non è misurabile in tempo (falte ROCm), presentarla come intervallo architetturale esplicito — mai inventare una cifra puntuale.

Contratto numerico: colonna "nostra" da `backend/run.json`, colonna "baseline" da `backend/baseline_metrics.json`.
L'aggiornamento di questa tabella spetta al PO, dopo il commento dei numeri misurati sulla issue. Nessun numero a mano.

## 4. Deliverable D2 (definition of done)

- `python pipeline.py FC-01` stampa il ticker completo (formato §2.9) e, con `--dump-json`, produce un
  `run.json` valido contro `schemas/run.schema.json`.
- Se questo gira sotto 1.2s (`within_budget: true`), la demo è al 60%.

## 5. Stack tecnico (fase 1 = euristiche, riusa la familiarita FastAPI)

- Backend: FastAPI + uvicorn (bind 0.0.0.0 per raggiungibilita LAN/Tailscale, come da convenzione).
  In fase 1 **non serve bindare nulla**: `pipeline.py` è uno script CLI.
- Embeddings: modello sentence-transformers piccolo (CPU/GPU agnostico) per relevance baseline;
  fallback obbligatorio TF-IDF (stdlib) se il modello non è installabile offline (oggi: TF-IDF, `textutil.py`).
- System Two: OpenRouter (Llama-3.1-8B via API, etichettato open-source; run ROCm reale solo se disponibile).
- Frontend demo: HTML/JS singolo file (ticker, barre, visual pipeline) — nessun framework necessario.

## 6. Fasi D4-D5 (bloccate per ora, pronte)

- D4: UI demo (ticker latenza, contatore token risparmiati, barra baseline, slide "what the GPU never saw") + script 120s.
- D5: run ROCm opzionale per frame throughput, registrazione video, submit.

## 7. Rischi principali

1. Nessun accesso GPU AMD → throughput frame debole. Mitig: rapporto token/query (hardware-agnostico) + cifra architetturale esplicita.
2. Baseline non misurabile → barra di confronto con intervallo onesto.
3. Corpus finanziario "pesca" → pre-validare la verita verificabile di ogni coppia.
4. Time budget → niente ottimizzazione prematura; si taglia ciò che non e nel video.
5. `SERPAPI_KEY` assente → nessuna chiamata live: si usa uno snapshot JSON via `--live PATH` (già supportato)
   oppure solo replay. Non blocca nulla.

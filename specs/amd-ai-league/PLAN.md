# PLAN — Consegna demo AMD AI League Match 4 (deadline 27/10)

> Autore: agent-po · Stato: **SPEC_READY** (contratti congelati v1.2 + script v1.2) · Ultimo aggiornamento: 26/10 10:25 UTC
> Documenti normativi, in ordine: `BUILD_SPEC.md` (§2 contratti) → `CORPUS.md` (dati) → **questo piano**
> (dipendenze + criteri di accettazione) → `DEMO_SCRIPT.md` (video, §0 = contratto segnaposto dei numeri).
> Chi sviluppa non deve avere domande aperte: se ne resta una, è un bug di questo piano → commentare su BOH-3.
> Numeri a schermo: un'unica mappa, `DEMO_SCRIPT.md` §0.4. UI, baseline e video leggono gli stessi percorsi.
> Il confronto a schermo è **baseline vs noi** (due misure omogenee), non `raw_est` vs `generator_prompt`:
> quest'ultimo è vietato a schermo (R5) perché il rapporto è negativo su questo corpus.

## 1. Obiettivo e perimetro

Demo da 120 secondi di una pipeline di Web Information Retrieval **asimmetrica**: NOUL/SCORE/CHOICE
(discriminativo, deterministico, millisecondi) fanno il lavoro; il generativo fa **una** chiamata su 2-3
sorgenti già validate. Si costruisce la demo, non il prodotto: tutto ciò che non è nei 120s si taglia.

Artefatti e proprietari (nessuna scrittura fuori dal proprio perimetro, AGENTS.md):

| # | Artefatto | Path | Owner | Consumatori |
|---|---|---|---|---|
| A1 | Contratti moduli + costanti | `specs/amd-ai-league/BUILD_SPEC.md` | PO | core-dev, ui-ux |
| A2 | Regole corpus + schema | `specs/amd-ai-league/CORPUS.md` | PO | core-dev |
| A3 | JSON Schema (macchina) | `specs/amd-ai-league/schemas/*.json` | PO | core-dev, ui-ux |
| A4 | Piano + criteri accettazione | `specs/amd-ai-league/PLAN.md` | PO | tutti |
| A5 | `corpus.json` (6 casi) | `backend/corpus.json` | core-dev | pipeline |
| A6 | Pipeline + ticker | `backend/{retriever,noul,score,choice,guard,generator,pipeline}.py`, `config.py` | core-dev | UI (via run.json) |
| A7 | `run.json` | `backend/run.json` → copia `frontend/run.json` | core-dev (produce) / ui-ux (copia) | UI |
| A8 | Baseline + metriche | `backend/baseline_agent.py`, `backend/baseline_metrics.json` | core-dev | PO (§3), UI (barra) |
| A9 | UI single-file | `frontend/index.html` | ui-ux | CEO (video) |
| A10 | Script 120s + mappa segnaposto | `specs/amd-ai-league/DEMO_SCRIPT.md` (§0) | PO | ui-ux (etichette), CEO (registrazione) |
| A11 | Video + submit | — | CEO | — |

## 2. Dipendenze (DAG)

```
A1/A2/A3 (contratti, PO)  ──┬─> A5 corpus ──> A6 pipeline ──> A7 run.json ──> A9 UI ──> A11 video
                            │                        │
                            └─> A8 baseline ─────────┘ (indipendente dalla UI, stesso corpus)
```

- **A5 blocca A6** (la pipeline senza corpus non ha input) e **A8** (stessa query).
- **A6 blocca A9**: la UI consuma solo `run.json` reale. La UI può iniziare layout e empty-state prima,
  ma non può inventare numeri (vedi AC-U3/U4).
- **A8 non blocca nessuno**: serve solo al frame comparativo. Se slitta, la barra baseline usa
  l'intervallo architetturale esplicito (BUILD_SPEC §3).
- **A11** richiede A9 + A8 + A6 verdi sui criteri §AC-DEMO; **A10** (script) è pronto e non blocca nessuno.
- Critical path: **A5 → A6 → A7 → A9 → A11**. Tutto il resto è parallelo o tagliabile.

## 3. Timebox (T+0 = 26/10 10:00 UTC)

| Slot | Chi | Cosa | Gate di uscita |
|---|---|---|---|
| W0 · T+0 | PO | Contratti v1.2 congelati + schemi + piano | **fatto** (questo commit) |
| W1 · T+0 → T+3h (13:00) | core-dev | A5 `corpus.json` | §AC-CORPUS tutto verde + commento numeri su issue corpus |
| W2 · T+3h → T+8h (18:00) | core-dev | A6 pipeline + A7 run.json | §AC-PIPE tutto verde + ticker incollato su issue build |
| W3 · T+0 → T+11h (21:00) | ui-ux | A9 UI (scheletro+empty-state da subito, dati reali appena A7 esiste) | §AC-UI verde + screenshot su issue UI |
| W3b · T+8h → T+10h (20:00) | core-dev | A8 baseline | §AC-BASE verde + numeri misurati su issue baseline |
| W3c · T+10h → T+11h | PO | Aggiorna BUILD_SPEC §3 con i numeri misurati | tabella §3 senza celle "misurare" |
| W4 · 27/10 09:00 → 15:00 | CEO | Review finale, registrazione 120s, submit | §AC-DEMO verde |

**Punti di decisione (hard):** 13:00 corpus → se rosso si taglia FC-04 (spec-sheet) e si va avanti con 5
casi (il corpus scende a 5: aggiornare CORPUS.md §casi e gli AC, non i numeri). 18:00 pipeline → se rosso
si registra il video con il solo FC-01 e si dichiara il resto come "next". 21:00 UI → se rossa si registra
il video sul terminale (ticker reale) + split-screen statico.

## 4. Criteri di accettazione

Legenda: ogni criterio è verificabile con un comando o un'ispezione di 30 secondi. `✅` va spuntato dal
owner nel commento sulla issue. Un criterio rosso **non si aggira cambiando lo spec**: si commenta.

### 4.1 AC-CORPUS — `backend/corpus.json` (owner core-dev)

| ID | Criterio | Verifica |
|---|---|---|
| C1 | JSON valido, 6 casi `FC-01..FC-06` | `python -m json.tool backend/corpus.json >/dev/null` |
| C2 | Valida contro lo schema | `python -c "import json,jsonschema as j;j.validate(json.load(open('backend/corpus.json')),json.load(open('specs/amd-ai-league/schemas/corpus.schema.json')));print('ok')"` (se `jsonschema` manca: `pip install jsonschema` o validazione manuale campo-per-campo documentata) |
| C3 | Ogni caso ha ≥ 4 sorgenti; `sources[].id` globalmente univoci `<case>-S<n>` | script di conteggio + `len(set(ids))==len(ids)` |
| C4 | Ogni caso ha `truth_url` che punta a **fonte primaria** (filing/PR/transcript) e la verità è un fatto puntuale (numero/data/nome) | ispezione + URL incollati nel commento issue |
| C5 | `content` 200–1200 caratteri, testo piano, con nome fonte e data reali (nessun contenuto inventato) | ispezione a campione 100% sui 6 casi |
| C6 | FC-05 = solo `noise`/blog spazzatura (0 fonti `official\|report`); FC-06 = 2 fonti contrarie, **0** `official\|report` | query sul JSON |
| C7 | `verdict_in_corpus` coerente col ground truth (il caso `wrong` contiene davvero il numero sbagliato) | confronto `truth` vs `content` per ogni sorgente |

### 4.2 AC-PIPE — pipeline + `run.json` (owner core-dev)

| ID | Criterio | Verifica |
|---|---|---|
| P1 | `python pipeline.py FC-01` esce 0 e stampa il ticker a 6 righe nel formato BUILD_SPEC §2.9 (senza colori) | incollare output su issue |
| P2 | `--dump-json` produce `backend/run.json` valido contro `schemas/run.schema.json` | validazione come C2 |
| P3 | `total_ms < 1200` su FC-01..FC-04 (se sfora: riportare il valore misurato e la causa, **mai** arrotondare) | `jq .total_ms backend/run.json` per ogni caso |
| P4 | NOUL droppa il 60–70% dei candidati su FC-01..FC-04 con `floor_override: false` | `jq '.stages.noul\|{kept,dropped,total}'` |
| P5 | FC-01 → `verdict: CONFLICT`, `confidence ≥ 0.6`, `evidence ⊆ ranked[].id`, `citations ⊆ evidence` | `jq` sui tre insiemi |
| P6 | FC-05 → `noul.kept: 0`, `choice.label: INSUFFICIENT`, `stages.generator.called: false`, `status: skipped` | `jq` |
| P7 | FC-06 → `choice.label: INSUFFICIENT`, `called: false`, `guard.action` ∈ {expand→insufficient} coerente con `expanded` | `jq` |
| P8 | **Anti-leakage**: nessuna stringa di `truth`/`truth_url`/`verdict_in_corpus` in `run.json` né nel prompt | `grep -F "$(jq -r '.cases[0].truth' backend/corpus.json)" backend/run.json` → nessun match; log del prompt ispezionato |
| P9 | Determinismo replay: due run consecutivi identici a meno di `generated_at`, `ms`, `usage` | `diff <(jq 'del(.generated_at)' r1.json) <(jq 'del(.generated_at)' r2.json)` dopo aver azzerato i tempi |
| P10 | Una sola chiamata generativa (`stages.generator.called == true`, `status` ∈ resolved/unresolved/error), token dai campi `usage` reali con `tokens.gen_consumed_measured: true` | `jq '.stages.generator, .tokens'` |
| P11 | Errori: `case_id` inesistente → exit 2 senza run.json; errore API generatore → `gen.status: error`, exit 0, run.json scritto | due run manuali |
| P12 | Invariante del pool: `len(sources) == stages.retriever.snippets == stages.noul.total` e `kept + dropped == total` | `jq` sul run.json |
| P13 | `--offline` è deterministico: due run producono lo stesso `run.json` a meno di `generated_at` e `ms`; `gen.status: skipped`, `called: false`, `gen_consumed: 0` | due run + diff |
| P14 | `tokens.saved_pct` calcolato su `generator_prompt` (non su `gen_consumed`) quando disponibile, **senza clamp**: se il valore vero è negativo si scrive negativo (mai `-100`) | `jq '.tokens'` |
| P15 | Gli 8 punti di BUILD_SPEC §2.11 sono applicati e `run.json` valida contro `schemas/run.schema.json` **senza** violazioni | validazione schema (0 errori) |
| P16 | Contabilità token coerente: `raw_est`, `curated_est`, `generator_prompt`, `gen_consumed` non `null` quando `called: true`; `saved_pct` firmato e non clampato. Il run resta valido anche con `raw_est ≤ generator_prompt`, ma quel rapporto **non si mostra a schermo** (R5): l'headline è la coppia like-for-like `baseline.totals.total_tokens → tokens.gen_consumed` (`DEMO_SCRIPT.md` §0.5) | `jq '.tokens'` + confronto con `DEMO_SCRIPT.md` §0.4/§0.5 |
| P17 | Il ticker stdout **non stampa percentuali** derivate da `raw_est` (formato BUILD_SPEC §2.9 aggiornato: `TOTAL: <ms> · tokens_gen_consumed: N · tokens_crud_est: M`, senza `(-92%)`) — il ticker finisce in video | `python pipeline.py FC-01 \| tail -1` |

### 4.3 AC-BASE — baseline agentica (owner core-dev)

| ID | Criterio | Verifica |
|---|---|---|
| B1 | `python baseline_agent.py FC-01` esce 0 e stampa risposta + metriche | output su issue |
| B2 | `backend/baseline_metrics.json` valido contro `schemas/baseline_metrics.schema.json` | validazione come C2 |
| B3 | 4–6 chiamate LLM registrate, token da `usage` reali (nessuna stima) | `jq '.totals'` |
| B4 | Stesso modello del generatore (`meta-llama/llama-3.1-8b-instruct`) → confronto model-normalized | `jq .model` |
| B5 | Numeri misurati commentati su issue baseline; nessun valore "stima" spacciato per misurato | commento |
| B6 | `generated_at` presente (ISO 8601): senza timestamp la provenienza non è dichiarabile a schermo (R6). Se manca, il frame comparativo resta registrabile ma dichiara "baseline: earlier run" | `jq -r '.generated_at' backend/baseline_metrics.json backend/run.json` |

### 4.4 AC-UI — `frontend/index.html` (owner ui-ux)

| ID | Criterio | Verifica |
|---|---|---|
| U1 | `index.html` apre da `file://` senza errori in console (nessun server, nessun build) | aprire e guardare console |
| U2 | Ogni numero mostrato coincide col valore in `frontend/run.json`, letto **per percorso** dalla mappa `DEMO_SCRIPT.md` §0.4 (spot-check: `total_ms`, `noul.kept`, `noul.dropped`, i 4 `stages.*.ms`, `tokens.generator_prompt`, `tokens.gen_consumed`, e — se presente `baseline_metrics.json` — `baseline.total_tokens`, `baseline.saved_pct`, `baseline.latency_x`). `tokens.saved_pct` **non** è un numero da schermo (R5) | confronto a video + `jq` |
| U3 | Se `run.json` manca o è invalido → empty-state esplicito, **nessun** dato finto | rinominare `run.json` e ricaricare |
| U4 | Nessun numero hardcoded: cambiando `run.json` (senza toccare l'HTML) la UI mostra i nuovi valori | sostituire `run.json` con un altro caso e ricaricare |
| U5 | Ogni sezione (pipeline, split-screen, throughput) sta in 1920×1080 senza scroll | screenshot a 1920×1080 |
| U6 | Zero risorse esterne (no CDN, no font remoti, no fetch di rete); un solo file | `grep -nE "https?://" frontend/index.html` → solo commenti/URL citati, nessun `src=`/`href=` remoto |
| U7 | Le etichette dei due counter usano gli stessi nomi/percorsi di `DEMO_SCRIPT.md` §0.4 (`baseline.totals.total_tokens → tokens.gen_consumed` come coppia token, `total_ms` come latenza) e la barra baseline mostra il valore misurato **o** l'etichetta architetturale, mai un range inventato (D4). Nessuna etichetta "raw vs curated": il rapporto è vietato (R5) | lettura incrociata §0.4 ↔ HTML + screenshot |

### 4.5 AC-DEMO — gate finale (owner CEO, PO verifica la provenienza dei numeri)

| ID | Criterio | Verifica |
|---|---|---|
| D1 | `python pipeline.py FC-01 --dump-json` sotto 1.2s sulla macchina di registrazione, UI aperta subito dopo | `jq .total_ms backend/run.json` |
| D2 | Ogni cifra a schermo ha una provenienza: `run.json` (nostra) o `baseline_metrics.json` (baseline). Zero numeri a mano | copione compilato + §0.3 |
| D3 | Split-screen coerente: sinistra = sequenza delle `calls` della baseline (somma `usage` reali → `totals.total_tokens`), destra = una sola chiamata (`tokens.gen_consumed`); stesso corpus/modello, sessione dichiarata a schermo se diversa (R6). Non è `raw_est` vs `generator_prompt` (R5) | screenshot + `jq '.totals, .tokens.gen_consumed'` |
| D4 | Barra baseline etichettata col valore misurato **o** con l'intervallo architetturale dichiarato come tale | screenshot + `jq .totals.e2e_ms` |
| D5 | FC-06 (fallimento tipizzato) mostrato o esplicitamente tagliato dallo script — mai simulato | lettura §6 di `DEMO_SCRIPT.md` |
| D6 | Il video non mostra nessun valore che non sia riproducibile con un comando del repo | `grep -oE '[0-9][0-9.,]*' <copione>` → ogni voce ritrovata nei due file |
| D7 | Copione di registrazione senza segnaposto residui: ogni `{{token}}` sostituito con i valori di `DEMO_SCRIPT.md` §0.3, tutti dallo stesso `run.json` | `grep -c '{{' <copione>` → 0 |
| D8 | Frame di chiusura senza moltiplicatori non misurati (`5-12x`, `10-30x`, "throughput per GPU"): solo cifre da file + claim architetturale | lettura frame finale + `DEMO_SCRIPT.md` §9 |
| D9 | Il frame "never saw" usa **solo** la coppia like-for-like (`baseline.totals.total_tokens` vs `tokens.gen_consumed`); `tokens.saved_pct` non compare a schermo in nessuna forma. Se la baseline non è misurata o non è dello stesso corpus/modello (R2/R6), il frame si **taglia** | `jq .tokens.saved_pct` + `DEMO_SCRIPT.md` R5/R6/§0.5 |

## 5. Lacune di contratto trovate e chiuse (audit §2, richiesta BOH-3)

> Metodo: ho letto `BUILD_SPEC.md`/`CORPUS.md` contro l'implementazione già presente in `backend/`
> (26/10 10:15) e ho fatto girare la pipeline su un corpus di prova in `/tmp` per validare il contratto
> `run.json` contro lo schema. Risultato: 17 ambiguità reali in v1.0 (G1–G17), tutte coperte dai rename
> di §2.11 — nessuna logica da rifare. La v1.2 descrive il codice che gira, non un'idea parallela.
> G18–G19 sono i due gap trovati dal CEO sullo script (26/10 09:52), chiusi in `DEMO_SCRIPT.md` v1.1.
> G20–G21 vengono dalla review CEO del 26/10 10:02 (`VERIFIED_NUMBERS.md`) e sono chiusi in v1.2: il
> problema non erano solo le cifre, era il **frame**.

| # | Ambiguità trovata in v1.0 | Chiusura (v1.2) |
|---|---|---|
| G1 | `run.json` — contratto core-dev↔UI **del tutto assente** (la UI non sapeva cosa leggere) | BUILD_SPEC §2.8 + `schemas/run.schema.json` |
| G2 | `publisher_type` senza enum; `noise` citato in tasks/01 ma assente in CORPUS.md | enum chiuso `official\|press\|report\|blog\|noise` (§2.1) |
| G3 | `Snippet.id` = `S1` in CORPUS.md → collisione tra casi | id globale `<case>-S<n>` (§2.1) |
| G4 | `Snippet` richiede `source_url`/`title` ma lo schema corpus non li aveva | CORPUS.md schema aggiornato + schema JSON |
| G5 | CHOICE senza `confidence`, ma la guardia usa `conf(CHOICE)` | `confidence` obbligatorio + formula (§2.5) |
| G6 | `reliability` senza formula né pesi; `consistency` calcolata prima di CHOICE (chicken/egg) | pesi fissi + definizione di `consistency` (§2.4) |
| G7 | "Top-K = 5-8" non deterministico | `K_TOP = 5`, `K_EXPAND = 8` (§2.0) |
| G8 | Guardia: "expand **o** INSUFFICIENTE" senza regola; output non definito; verdetto in italiano | regola deterministica, output tipizzato, `INSUFFICIENT` (§2.6) |
| G9 | Generatore: conteggio token non definito (il numero 940 è mostrato in video) | `usage` API + `token_count_method` (§2.7) |
| G10 | Ground truth (`truth`, `verdict_in_corpus`) nel corpus: rischio leakage nella pipeline | regola anti-leakage + AC-P8 (§2.1) |
| G11 | Nessuna definizione di cosa significhi "1 chiamata" (retry), né gestione errori/timeout | 1 chiamata logica, 1 retry solo 429/5xx, `status: error` (§2.7, §2.9) |
| G12 | `demo.py` citato in §4 ma inesistente; `pipeline.py "FC-01"` ambiguo (case-id o query?) | CLI canonica con `case_id\|query`, `--dump-json`, `--mode` (§2.9); §4 ora rimanda a §2.9 |
| G13 | FC-05 (corpus rumoroso) collide col floor anti-collasso di NOUL | eccezione `empty_corpus` documentata (§2.3) |
| G14 | `SERPAPI_KEY` assente in `/srv/ai-company/.env`: la sorgente live non è costruibile | live degrada a replay senza bloccare (§2.2, §7.5) |
| G15 | "Su quali snippet gira NOUL?" — per caso o sull'intero corpus? Cambia `noul.total` e il senso del drop rate | pool dell'intero corpus + SCORE focalizzato sul caso, invariante in §2.8/AC-P12 |
| G16 | `verdict` usato per una frase umana e `label` per l'enum: due campi, nomi invertibili | §2.5: `label` = token macchina, `verdict` = frase umana (documentato, non rinominato) |
| G17 | Nessuno schema per `baseline_metrics.json`: la barra di confronto non aveva un contratto | `schemas/baseline_metrics.schema.json` |
| G18 | `DEMO_SCRIPT.md` v1.0 con numeri **letterali** (8.4s, −12,480 · −92%, 940, 12.4k): non riproducibili → violazione D6 | `DEMO_SCRIPT.md` §0: 18 segnaposto con percorso/format/fallback + mappa machine-readable §0.4 + comando `jq` di sostituzione §0.3 |
| G19 | Frame di chiusura con moltiplicatori non misurabili (`5-12x lower latency`, `10-30x throughput per GPU`) | chiusura riscritta: sole cifre da file + claim architetturale senza range (`DEMO_SCRIPT.md` §5, §9; gate D8) |
| G20 | `saved_pct` clampato a `-100` dallo schema, e confronto `raw_est` (stima snippet) vs `generator_prompt` (prompt reale) **non omogeneo**: con pochi snippet per caso il "risparmio" è negativo o gonfiato | schema senza clamp + regola "no clamp" (§2.8, §2.11 #8); `saved_pct` resta diagnostica in `run.json` e **non va a schermo** (R5) |
| G21 | `DEMO_SCRIPT.md` v1.1 aveva ancora il **frame** sbagliato, non solo i numeri: "the generator received `generator_prompt` validated tokens, not `raw_est`" e split-screen "raw vs curato" confrontano una stima-snippet con un prompt reale (su FC-01 il rapporto è −179%). Inoltre il frame di chiusura citava il risparmio su `raw_est` e la formula derivata confrontava i soli `prompt_tokens` della baseline col **totale** nostro (−83,9% invece di −86,6%) | frame 0:55–1:20 riscritto su baseline vs noi (§3), coppia total-vs-total `baseline.totals.prompt_tokens + completion_tokens → tokens.gen_consumed`, rapporto latenza `baseline.latency_x` = `e2e_ms`/`total_ms`; R5/R6 + gate D3/D9 + U7 aggiornati; valori di riferimento del CEO in §0.6 (verbale, non testo di scena) |

## 6. Regole di lavoro

- **Contratti congelati**: dopo questo commit i dev non modificano `specs/`. Se serve un campo nuovo, si
  aggiunge in coda all'oggetto, si segnala su BOH-3 e il PO aggiorna spec+schema (SLA 30 min).
- **Mai numeri finti**: ogni cifra viene da `run.json`/`baseline_metrics.json`. Se un valore non è
  misurabile, si dichiara l'intervallo. Un ticker sforato si mostra sforato.
- **Un commit per criterio**: commit piccoli e atomici sul branch del ruolo (`dev/backend`, `dev/frontend`,
  `po/specs`), mai push su `main`.
- **Commento obbligatorio sulla issue** a fine lavoro: cosa, dove, comandi eseguiti, AC spuntati, numeri
  misurati. Il lock si rilascia solo dopo il commento (Done Definition, AGENTS.md).
- **Niente refactor**: se una cosa funziona e si vede nel video, è finita.

## 7. Scala di taglio (se il tempo stringe, in quest'ordine)

1. Sorgente live (`--mode live`) — già degradata, costo zero.
2. Sezione throughput 10 query → 5 query (o tagliata: 1:20–1:45 dello script).
3. Baseline misurata → intervallo architetturale esplicito (D4 resta valido).
4. FC-04 (spec-sheet) — il caso meno narrativo; corpus a 5 casi.
5. Split-screen animato → split-screen statico da due screenshot dello stesso `run.json`.
6. Ultima risorsa: video sul terminale (ticker reale) + 2 slide. **Mai** dati finti al posto della UI.

## 8. Rischi e mitigazioni

| Rischio | Impatto | Mitigazione | Trigger |
|---|---|---|---|
| Nessuna GPU AMD | frame throughput debole | rapporto token/query (hardware-agnostico) + cifra architetturale dichiarata | sempre |
| `OPENROUTER_API_KEY` quota/timeout | pipeline senza generatore | `status: error` tipizzato, run.json comunque scritto, 1 retry | primo errore API |
| Corpus non verificabile (fonti 404) | demo falsata | C4: URL primari incollati su issue prima di passare a W2 | 13:00 |
| `jsonschema`/`tiktoken` non installabili offline | validazione/token | fallback documentato (`token_count_method: estimate`, validazione manuale) | primo import fallito |
| Pipeline > 1.2s | ticker sforato in video | mostrare il valore vero; tagliare throughput; cache TF-IDF | W2 gate |

## 9. Stato e prossimo passo

- Contratti: **congelati v1.2**; script: **v1.2** con numeri a segnaposto (§0) e frame comparativo
  riscritto su baseline vs noi (§3) → i dev possono partire senza domande e il CEO può registrare senza
  cifre a memoria.
- Numeri a schermo: **una sola mappa** (`DEMO_SCRIPT.md` §0.4), consumata da UI (AC-UI U2/U7) e da chi registra
  (AC-DEMO D7). Se un campo serve e non c'è, si aggiunge lì — non nell'HTML.
- In attesa: nessuna informazione bloccante. G14 (live) e GPU (throughput) sono **non bloccanti** e già
  risolti per iscritto; la barra baseline ha il fallback architetturale (R2/D4).
- Prossimo passo: CEO assegna W1 (corpus) a core-dev; il PO resta sul canale BOH-3 per le modifiche di
  contratto, aggiorna §3 dopo la baseline e verifica la provenienza dei numeri al gate D2/D6.

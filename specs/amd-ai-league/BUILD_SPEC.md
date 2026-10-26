# AMD AI League · Match 4 — BUILD SPEC (esecuzione)

> Stato: pronto per build. Deadline 27 Ott. Solo builder, fase no-code chiusa.
> Principio guida: **costruire la demo, non il prodotto.** Ogni modulo qui sotto esiste solo se compare nei 120 secondi.

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

### RETRIEVER
- Output: `list[Snippet]` dove
  `Snippet = {id, source_url, source_name, publisher_type, date, content, title}`
- Corpus: file JSON pre-curato (vedi CORPUS.md). Live: 1 query reale.

### NOUL
- Input: Snippet. Output: `{keep: bool, confidence: float, reason: enum[spam,boilerplate,seo,off-topic,keep]}`
- Fase 1: euristiche (length, ratio, blacklist, embedding cos-sim con query, tag boilerplate). Fase 2: head classificatoria piccola.
- **Gate**: drop incondizionato prima di SCORE. Il generativo NON vede mai un drop.

### SCORE
- Output per sopravvissuto: `{id, relevance: 0..1, reliability: 0..1, reliability_breakdown: {authority, recency, consistency}}`
- Ordina desc. Top-K = 5-8.

### CHOICE
- Input: Top-K. Output: `{verdict, claim_id, evidence: [source_id], conflict_pairs: [{a,b,relation}]}`
- riconcilia affermazioni numericamente confrontabili (figure, date, nomi). Pesa reliability con accordo cross-sorgente.

### GUARDIA
- Regola: conf(CHOICE) < 0.6 -> o expand (piu candidati) o verdict="INSUFFICIENTE".
- Mai forzare il generativo a rispondere senza evidenza.

### GENERATORE (System Two)
- Input: query + top2-3 (<=1500 tok) + istruzioni rigide + schema output.
- Istruzioni: verdetto tipizzato, non allucinare, PUO dichiarare unresolved, citare come `{source_id, claim_id}`.
- Output: `{answer, confidence, citations:[{source_id, claim_id}], status: resolved|unresolved}`

## 3. Metriche da misurare (D3) — numeri V E R I della barra di confronto

| Metrica | Nostra pipeline | Baseline agentica (stesso corpus) |
|---|---|---|
| Chiamate al generativo | 1 | 4-6 |
| Token processati/query | misurare | misurare |
| Latenza E2E (ms) | misurare | misurare |
| GPU-sec/query | misurare | misurare |
| Costo $/query | misurare | misurare |

**Regola di onestà**: se la baseline non è misurabile in tempo (falte ROCm), presentarla come intervallo architetturale esplicito — mai inventare una cifra puntuale.

## 4. Deliverable D2 (definition of done)

- Uno script `demo.py` (o equivalente) che su 1 query del corpus stampa:
  ```
  NOUL: 18/24 keep (6 drop)   [18ms]
  SCORE: top5 ordinati         [27ms]
  CHOICE: CONFLICT A vs B      [41ms]
  GEN: resolved | evidencia   [640ms]
  TOTAL: 780ms | tokens_gen_consumed: 940 | tokens_crud: 12480 (-92%)
  ```
- Se questo gira sotto 1.2s, la demo è al 60%.

## 5. Stack tecnico (fase 1 = euristiche, riusa la familiarita FastAPI)

- Backend: FastAPI + uvicorn (bind 0.0.0.0 per raggiungibilita LAN/Tailscale, come da convenzione).
- Embeddings: modello sentence-transformers piccolo (CPU/GPU agnostico) per relevance baseline.
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
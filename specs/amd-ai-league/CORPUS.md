# AMD AI League · Match 4 — CORPUS (dati demo)

> Caso d'uso: riconciliazione real-time di dati finanziari in notizie conflittuali.
> Regola: ogni coppia deve avere una **verità verificabile** (fonte primaria: filing, earnings call trascritta, report ufficiale).
> Formato dati: JSON pre-curato, **10 casi (FC-01 … FC-10)** + snapshot live opzionale al demo (`--live PATH`).
> Decisione SERPAPI (2026-10-26): **non usata nella demo** — `SERPAPI_KEY` non è in `.env` e il
> tempo residuo al submit non giustifica l'onboarding di un'API a pagamento. Il canale "live"
> resta implementato come **snapshot JSON** (`--live PATH`, già supportato da retriever), e la UI
> non rivendica nessuna "sorgente live": l'etichetta mostrata è "Measured values from run.json".
> Contratto macchina: `schemas/corpus.schema.json`. Consegna in `backend/corpus.json` (task 01).

## Schema per caso

```json
{
  "id": "FC-01",
  "subject": "descrizione del fatto",
  "query": "frase query demo",
  "claim": "il fatto numerico da riconciliare, in una riga",
  "truth": "fatto esatto + URL della fonte primaria",
  "truth_url": "https://...",
  "sources": [
    {
      "id": "FC-01-S1",
      "source_name": "NVIDIA Newsroom",
      "publisher_type": "official",
      "date": "2026-02-25",
      "title": "Q4 FY2026 financial results",
      "source_url": "https://...",
      "content": "2-4 frasi di testo reale citato o parafrasato, con nome fonte e data.",
      "verdict_in_corpus": "correct"
    }
  ],
  "notes": "perche e un buon caso (dramma, figura numerica, trade-off)"
}
```

### Campi: regole vincolanti

- `id` caso: `FC-01` … `FC-06` (zero-padded, fissi — le issue e la UI li citano).
- `sources[].id`: **globalmente univoco**, formato `<case_id>-S<n>` con `n` da 1. `S1` da solo non è univoco.
- `publisher_type`: enum chiuso `official | press | report | blog | noise`
  (`noise` = publisher di rumore/SEO, ammesso solo nei casi FC-05 e come contorno; è un tipo di publisher,
  non un verdetto).
- `date`: `YYYY-MM-DD` (solo giorno, niente orari/timezone).
- `source_url`: URL assoluto; `""` ammesso **solo** per `publisher_type: "noise"`.
- `title`: obbligatorio, non vuoto.
- `content`: 2–4 frasi, testo piano (niente HTML/markdown), 200–1200 caratteri, nome fonte e data reali.
- `verdict_in_corpus`: enum `correct | wrong | partial | noise` — **etichetta di valutazione, non un input
  della pipeline**. Insieme a `truth`/`truth_url`/`claim`/`notes` è materiale di solo scoring:
  `retriever.py` deve rimuoverlo prima di consegnare gli snippet ai moduli (regola anti-leakage,
  BUILD_SPEC §2.1). Se il ground truth finisce nel prompt del generatore, il demo è falsato.
- `sources` per caso: **≥ 4**. Di cui almeno 1 `official|report` nei casi FC-01..FC-04.
- `truth` deve contenere un fatto puntuale (numero, data, nome) **e** l'URL primario in `truth_url`.

## Criteri di selezione (per ogni coppia)
1. **Figura numerica confrontabile** (EPS, guidance, market cap, target) → riconciliazione "quantificabile" = il demo piu forte.
2. **Contraddizione netta** tra 2 fonti affidabili (non spam vs fonte: deve esserci conflitto vero da rivelare).
3. **Una fonte chiara e definitiva** da citare come risoluzione (filing/trascrizione ufficiale).
4. Almeno 1 coppia con **rumore attorno** (SEO junk, blog speculativo) → per far brillare NOUL.
5. Almeno 1 coppia con **evidenza insufficiente** → per mostrare CHE COSA e unfinished/unresolved.

## I 6 casi (ruoli fissi — non cambiano)

| id | Tipo | Cosa deve dimostrare | Atteso dalla pipeline |
|---|---|---|---|
| FC-01 | Earnings guidance | guidance ufficiale vs headline sensazionalista che reinterpreta | `CONFLICT`, conf ≥ 0.6, 1 chiamata gen |
| FC-02 | Acquisizione | annuncio ufficiale vs blog con importo sbagliato | `RESOLVED` o `CONFLICT`, cifra corretta citata |
| FC-03 | Cambio CEO / date | comunicato vs rumor con data errata | `RESOLVED`, data corretta |
| FC-04 | Spec-sheet B2B (fallback) | scheda ufficiale vs retail con specifica sbagliata | `RESOLVED`, specifica corretta |
| FC-05 | Rumore / SEO | query finanziaria con risultati spazzatura | `noul.empty_corpus: true`, `INSUFFICIENT`, 0 chiamate gen |
| FC-06 | Evidenza insufficiente | due fonti contrarie, nessuna primaria | `INSUFFICIENT` (dopo 1 espansione), 0 chiamate gen |

La colonna "Atteso" è la base dei criteri di accettazione in `PLAN.md` (§AC-CORPUS / §AC-PIPE): se un caso
non produce l'esito atteso, si corregge il caso o l'euristica — non si aggiusta il numero a mano.

## Sorgente live (opzionale al demo)
- 1 query reale (es. "NVIDIA Q3 2026 earnings guidance") via SerpAPI/Bing.
- **`SERPAPI_KEY` non è presente in `/srv/ai-company/.env`**: la live è da considerarsi non disponibile e
  non blocca nulla (BUILD_SPEC §2.2). Se in futuro la chiave c'è, resta solo showcase.
- Attenzione: la verita live non e pre-validabile → usarla SOLO come showcase di realta, mai come caso dimostrativo chiave.

## Checklist pre-recording
- [ ] Verita di ogni coppia confermata su fonte primaria accessibile/archiviata.
- [ ] Rumore inserito in almeno 2 coppie.
- [ ] 1 caso "unresolved" pronto (FC-06) e 1 caso "corpus rumoroso" pronto (FC-05).
- [ ] Corpus versionato in JSON leggibile (per il "what the GPU never saw" split-screen).
- [ ] `corpus.json` valida contro `schemas/corpus.schema.json` e nessun campo di ground truth esposto
      agli snippet passati alla pipeline.

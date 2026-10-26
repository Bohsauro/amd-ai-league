# AMD AI League · Match 4 — CORPUS (dati demo)

> Caso d'uso: riconciliazione real-time di dati finanziari in notizie conflittuali.
> Regola: ogni coppia deve avere una **verità verificabile** (fonte primaria: filing, earnings call trascritta, report ufficiale).
> Formato dati: JSON pre-curato. 5–8 coppie + 1 sorgente live al demo.

## Schema per coppia
```json
{
  "id": "FC-01",
  "subject": "descrizione del fatto",
  "query": "frase query demo",
  "truth": "fatto esatto e la sua fonte primaria",
  "sources": [
    {"id":"S1","source_name":"...","publisher_type":"press|official|blog|report",
     "date":"...","content":"...","verdict_in_corpus":"correct|wrong|partial|noise"}
  ],
  "notes": "perche e un buon caso (dramma, figura numerica, trade-off)"
}
```

## Criteri di selezione (per ogni coppia)
1. **Figura numerica confrontabile** (EPS, guidance, market cap, target) → riconciliazione "quantificabile" = il demo piu forte.
2. **Contraddizione netta** tra 2 fonti affidabili (non spam vs fonte: deve esserci conflitto vero da rivelare).
3. **Una fonte chiara e definitiva** da citare come risoluzione (filing/trascrizione ufficiale).
4. Almeno 1 coppia con **rumore attorno** (SEO junk, blog speculativo) → per far brillare NOUL.
5. Almeno 1 coppia con **evidenza insufficiente** → per mostrare CHE COSA e unfinished/unresolved.

## Coppie ideali da preparare (template da riempire)
- **FC-01 Earnings call**: guidance ufficiale vs headline sensazionalista che reinterpreta (verita = trascrizione/PR).
- **FC-02 Acquisizione**: annuncio ufficiale vs blog con un numero sbagliato sull'ammontare.
- **FC-03 Cambio CEO/date**: comunicato vs rumor con data errata.
- **FC-04 Spec-sheet B2B** (fallback): scheda prodotto ufficiale vs retail con specifica sbagliata (es. TDP, memoria).
- **FC-05 Rumore/SEO**: query finanziaria con risultati spazzatura → NOUL li scarta tutti.
- **FC-06 Insufficiente**: due fonti contrarie, nessuna primaria → verdict **INSUFFICIENTE** (dimostra le braccia alzate).

## Sorgente live (opzionale al demo)
- 1 query reale (es. "NVIDIA Q3 2026 earnings guidance") via SerpAPI/Bing.
- Attenzione: la verita live non e pre-validabile → usarla SOLO come showcase di realta, mai come caso dimostrativo chiave.

## Checklist pre-recording
- [ ] Verita di ogni coppia confermata su fonte primaria accessibile/archiviata.
- [ ] Rumore inserito in almeno 2 coppie.
- [ ] 1 caso "unresolved" pronto.
- [ ] Corpus versionato in JSON leggibile (per il "what the GPU never saw" split-screen).
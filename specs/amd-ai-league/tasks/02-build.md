# Task 02 — Pipeline asimmetrica (NOUL → SCORE → CHOICE → GUARD → GEN)

**Assegnatario:** agent-core-dev · **Output:** `backend/*.py`

Leggi `specs/amd-ai-league/BUILD_SPEC.md` PRIMA di scrivere: è il contratto autoritativo,
non deviare dalle interfacce dei moduli.

Moduli (fase 1, euristiche):
1. `retriever.py` — carica il corpus JSON + 1 set di risultati live. Output `list[Snippet]`.
2. `noul.py` — gate bool: length ratio, pattern boilerplate, blacklist domini, cos-sim con la
   query (embedding piccolo o TF-IDF). Output `{keep, confidence, reason}`. Target: droppa 60-70%.
3. `score.py` — relevance × reliability (authority, recency, consistency), ordina desc, top 5-8.
4. `choice.py` — classificazione pairwise `agree | disagree | unrelated`, pesata sulla
   reliability; emette `verdict`, `claim_id`, `conflict_pairs`.
5. `guard.py` — se conf(CHOICE) < 0.6 → expand oppure `verdict = INSUFFICIENTE`.
6. `generator.py` — UNA chiamata a Llama-3.1-8B via OpenRouter (`OPENROUTER_API_KEY` da env),
   input query + top 2-3 (≤1500 token), output JSON tipizzato
   `{answer, confidence, citations[], status: resolved|unresolved}`.
7. `pipeline.py` — orchestra il DAG, misura ms per stage e token, stampa il ticker di
   BUILD_SPEC §4. Flag `--dump-json` → scrive `backend/run.json` (per la UI).

**Definition of done:** `python pipeline.py "FC-01"` stampa il ticker completo sotto 1.2s.
Se uno stage sfora il budget, stampa comunque il valore misurato: mai falsare i tempi.
NON costruire UI, baseline o roba ROCm in questo task.

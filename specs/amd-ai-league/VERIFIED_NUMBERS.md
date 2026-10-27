# VERIFIED NUMBERS — fonte unica per DEMO_SCRIPT

> Generato da `bin/gen-verified-numbers` leggendo i file reali. **Non modificare a mano.**

- run: `FC-01` · 2026-10-27T21:16:50.272414+00:00
- modello: `meta-llama/llama-3.1-8b-instruct` (provider: Groq)
- run.json sha256: `1d5c70e7aab1` · baseline_metrics.json sha256: `02adbf40c2a9`

## Valori per placeholder

| placeholder | valore | fonte |
|---|---|---|
| `{{total_ms}}` | **440 ms** | run.json total_ms |
| `{{budget_ms}}` | **1,200 ms** | run.json budget_ms |
| `{{noul.total}}` | **53** | run.json stages.noul.total |
| `{{noul.kept}}` | **19** | run.json stages.noul.kept |
| `{{noul.dropped}}` | **34** | run.json stages.noul.dropped |
| `{{choice.label}}` | **CONFLICT** | run.json stages.choice.label |
| `{{gen.status}}` | **resolved** | run.json stages.generator.status |
| `{{tokens.gen_consumed}}` | **1,572** | run.json tokens.gen_consumed |
| `{{tokens.generator_prompt}}` | **1,390** | run.json tokens.generator_prompt |
| `{{gen.prompt_tokens}}` | **1,390** | run.json tokens.generator_prompt |
| `{{gen.total_tokens}}` | **1,572** | run.json tokens.generator_total |
| `{{tokens.raw_est}}` | **5,033** | run.json tokens.raw_est |
| `{{tokens.saved}}` | **3,643** | run.json tokens.saved (diagnostica) |
| `{{tokens.saved_pct}}` | **72.4%** | run.json tokens.saved_pct (diagnostica) |
| `{{baseline.llm_calls}}` | **5** | baseline_metrics.json totals.llm_calls |
| `{{baseline.prompt_tokens}}` | **43,127** | baseline_metrics.json totals.prompt_tokens |
| `{{baseline.total_tokens}}` | **46,563** | baseline_metrics.json prompt+completion |
| `{{baseline.e2e_ms}}` | **30,570 ms** | baseline_metrics.json totals.e2e_ms |
| `{{baseline.saved_pct}}` | **96.6%** | calcolato: (baseline - gen_consumed) / baseline |
| `{{baseline.latency_x}}` | **69.5×** | calcolato: baseline.e2e_ms / total_ms |
| `{{batch.n_runs}}` | **10** | run.json throughput.n_runs |
| `{{batch.max_total_ms}}` | **526 ms** | run.json throughput.max_e2e_ms |

## I cinque numeri da dire ad alta voce

1. **5 chiamate LLM** la baseline, **1** la pipeline.
2. **46,563 token** vs **1,572** → **−96.6%**.
3. **30,570 ms** vs **440 ms** → **69.5× più veloce**.
4. **34 snippet scartati su 53** prima del generativo (64.2%).
5. **7 ms** tutto il lato discriminativo, **433 ms** la singola chiamata LLM.

## Verità da non nascondere

- Il tempo è quasi tutto la chiamata LLM (433 su 440 ms): il valore sta nel **numero di chiamate e nei token**, non nel tempo del lato discriminativo.
- La baseline è un loop agentico classico (5 chiamate su tutto il pool di 53 sorgenti), non ottimizzata: dichiaralo.
- Se un numero non è nel run, non si dice: si usa l'etichetta architetturale.

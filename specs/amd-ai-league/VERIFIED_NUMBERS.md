# VERIFIED NUMBERS — fonte unica per DEMO_SCRIPT

> Generato da `bin/gen-verified-numbers` leggendo i file reali. **Non modificare a mano.**

- run: `FC-01` · 2026-10-26T10:24:08.726989+00:00
- modello: `meta-llama/llama-3.1-8b-instruct` (provider: Groq)
- run.json sha256: `d972f87f2c27` · baseline_metrics.json sha256: `14a7d6b5f594`

## Valori per placeholder

| placeholder | valore | fonte |
|---|---|---|
| `{{total_ms}}` | **460 ms** | run.json total_ms |
| `{{budget_ms}}` | **1,200 ms** | run.json budget_ms |
| `{{noul.total}}` | **34** | run.json stages.noul.total |
| `{{noul.kept}}` | **12** | run.json stages.noul.kept |
| `{{noul.dropped}}` | **22** | run.json stages.noul.dropped |
| `{{choice.label}}` | **CONFLICT** | run.json stages.choice.label |
| `{{gen.status}}` | **resolved** | run.json stages.generator.status |
| `{{tokens.gen_consumed}}` | **1,572** | run.json tokens.gen_consumed |
| `{{tokens.generator_prompt}}` | **1,390** | run.json tokens.generator_prompt |
| `{{gen.prompt_tokens}}` | **1,390** | run.json tokens.generator_prompt |
| `{{gen.total_tokens}}` | **1,572** | run.json tokens.generator_total |
| `{{tokens.raw_est}}` | **2,686** | run.json tokens.raw_est |
| `{{tokens.saved}}` | **1,296** | run.json tokens.saved (diagnostica) |
| `{{tokens.saved_pct}}` | **48.3%** | run.json tokens.saved_pct (diagnostica) |
| `{{baseline.llm_calls}}` | **5** | baseline_metrics.json totals.llm_calls |
| `{{baseline.prompt_tokens}}` | **25,618** | baseline_metrics.json totals.prompt_tokens |
| `{{baseline.total_tokens}}` | **27,364** | baseline_metrics.json prompt+completion |
| `{{baseline.e2e_ms}}` | **3,568 ms** | baseline_metrics.json totals.e2e_ms |
| `{{baseline.saved_pct}}` | **94.3%** | calcolato: (baseline - gen_consumed) / baseline |
| `{{baseline.latency_x}}` | **7.8×** | calcolato: baseline.e2e_ms / total_ms |
| `{{batch.n_runs}}` | **10** | run.json throughput.n_runs |
| `{{batch.max_total_ms}}` | **636 ms** | run.json throughput.max_e2e_ms |

## I cinque numeri da dire ad alta voce

1. **5 chiamate LLM** la baseline, **1** la pipeline.
2. **27,364 token** vs **1,572** → **−94.3%**.
3. **3,568 ms** vs **460 ms** → **7.8× più veloce**.
4. **22 snippet scartati su 34** prima del generativo (64.7%).
5. **6 ms** tutto il lato discriminativo, **454 ms** la singola chiamata LLM.

## Verità da non nascondere

- Il tempo è quasi tutto la chiamata LLM (454 su 460 ms): il valore sta nel **numero di chiamate e nei token**, non nel tempo del lato discriminativo.
- La baseline è un loop agentico classico (5 chiamate su tutto il pool di 34 sorgenti), non ottimizzata: dichiaralo.
- Se un numero non è nel run, non si dice: si usa l'etichetta architetturale.

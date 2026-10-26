# AMD AI League · Match 4 — SCRIPT DEMO (120 secondi)

> Lingua: inglese (mercato globale). Tono: dimostrativo, mai vendute-fumo.
> Due counter animati a schermo — NULL'altro si muove se non la pipeline.

## Apertura (0:00–0:15) — 3 frasi, problema reale
> "Two headlines, one earnings call, opposite numbers. An analyst has to reconcile them — or guess. That guessing costs money, and it's exactly where today's AI agents fail: they feed the *entire* noisy context to an expensive model and hope."

- Schermo: due headline in conflitto (es. "BEATS GUIDANCE" vs "DOWNGUARDS").
- Tasto Invio → query in esecuzione.

## Pipeline live (0:15–0:55) — il cuore
> "Watch what the model *never* sees."
- Visual con flusso snippet → NOUL (rosso: drop) → SCORE (barre ascendenti) → CHOICE (zig-zag conflitto) → GENERATORE (verde).
- I due counter girano in diretta:
  1. **E2E LATENCY** (ms) con barra fissa "agentic baseline: 8.4s".
  2. **BASE → SAVED** tokens / GPU-sec (contachilometri, es. −12,480 · −92%).
- Narrazione sincronizzata: "NOUL discarded 6 of 24 sources before they cost a single token. CHOICE found the contradiction. The generator received 940 validated tokens, not 12,480."

## What the GPU never saw (0:55–1:20) — il visual choc
> "Left: the raw 12.4k tokens a classic agent would feed the model. Right: the 940 tokens we fed it — already reconciled, already cited. Same answer quality, 92% less context."
- Split-screen statico: contesto crudo vs contesto curato. Speaker in silenzio 3s (silenzio = potenza).

## Throughput (1:20–1:45) — scalabilità
> "Now ten analysts ask at once." (lancio 10 query)
> "Per-query latency holds under a second — because 90% of the decisions are a tiny batched forward-pass, not ten generations. On one card."
- Schermo: 10 righe in parallelo, latenza stabile <1s.

## Chiusura (1:45–2:00) — differenziazione + AMD
> "Classic agents make the GPU do everything. We let the GPU do only the one thing it's for — generation — and push 90% of the work to fast, typed discriminative decisions. That's not a better model. It's a better computer. ROCm runs it, one card, batched."
> On-screen: "9.4k tokens saved · 5-12x lower latency · 10-30x throughput per GPU."

## One-liner di backup (se il timing stringe)
> "Every token the generator never sees is free compute. We monetize ignorance."

## Regole di registrazione
- 1 query live (realta) + 1 rehearsal deterministico per il "never saw" split-screen.
- I counter NON sono animati a mano: contano dal vivo dal processo reale.
- Se la latenza live sfora, tagliare il throughput (sezione 1:20) — mai truccare il ticker.
# DESIGN.md — SPESEMED "Verde Calma" (tokens e sistema visivo)

> Direzione scelta (ott 2026): base Wise, temperata. Guida: skille
> `impeccable` (anti-pattern) + `claude-design` (processo) +
> `popular-web-designs` (tokens Wise).

## Principi

- Verde = fiducia (salute + denaro), calma, chiarezza per utenti non tecnici.
- Nessun anti-pattern impeccable: niente font overused (NON Inter/Arial),
  niente grigio su sfondo colorato, niente nero/grigio puro (tutto tinto di
  verde), niente card annidate, niente easing bounce.
- Un solo accent (verde). Rosso/giallo solo per errori/stati, non decorativi.
- Ombra minima (ring shadow): sensazione pulita e clinica.

## Tipo

- Primary: **Manrope** (alternative a Inter; distintivo, geometrico-warm,
  ottime cifre tabulari). Pesi 400/500/600/700/800.
- Mono (solo accent tecnico, file-naming): **JetBrains Mono** 400/500.
- Numeri finanziari: `font-variant-numeric: tabular-nums`.

## Palette (oklch/hex)

- --bg:        #ffffff        (sfondo pagina)
- --surface:   #f3f6ef        (avorio caldo, leggera tinta verde)
- --surface-2: #e6eeda        (bande più marcate)
- --ink:       #16211a        (titoli — quasi-nero TINTO di verde)
- --ink-2:     #44523f        (testo secondario — grigio tinto)
- --ink-3:     #66755f        (caption/muto — grigio-verde tinto)
- --line:      #d8e2cd        (bordi — linea chiara tinta, non grigio puro)
- --green:     #9fe870        (CTA / accent primario)
- --green-deep:#143300        (testo sui pulsanti verdi / accenti deep)
- --green-bg:  #e2f6d5        (menta — badge "done")
- --success:   #2e7d32 (testo successo) / bg #e2f6d5
- --danger:    #b3261e (testo) / bg #fbe9e7
- --warn:      #8a6d00 (testo) / bg #fbf1c8
- --info:      #0f6f8f (testo) / bg #e2f3f6   (note privacy)

## Componenti chiave

- **Bottoni**: pillola (radius 9999px), bg verde, testo verde-deep; hover
  scale(1.03), active scale(0.97); min-height ~44-48px; ease-out gentile.
- **Card**: radius 18-24px; bordi 1px --line; ring shadow
  `0 0 0 1px rgba(22,33,26,.06)`; NIENTE card-annidata: le zone dati usano
  bande colorate + tabelle con divisori, non box-in-box.
- **Chips/status**: pillola piccola; menta/bg per "ok", giallo per "in corso",
  rosso per errore. Mai testo grigio su sfondo colorato.
- **Form**: bordi 1px --line, radius 12px, focus ring verde, label well spec.

## Dominio delle maiuscole / tono

- Utili brevissimi e concreti. Hero: "Le tue spese mediche, ordinate e pronte
  per il commercialista."
- Microcopy fiducia sempre nel flusso: "Dati medici crittografati",
  "Bucket privato", "Codice fiscale validato".

## Superfici da mockare

Landing: nav, hero, come-funziona, fiducia/privacy, waitlist, footer.
App: login/signup, dashboard (riepilogo), upload, risultati, jobs/storico,
export. Preferire vista chiara (no dark). Responsive, accessibile, hit ≥44px.
# PAPERCLIP PLAYBOOK — come si lavora un ticket

> Le variabili `PAPERCLIP_API_URL`, `PAPERCLIP_CLI` e la tua `PAPERCLIP_AGENT_<RUOLO>_KEY`
> sono già nel tuo ambiente (i wrapper in `bin/` fanno `source /srv/ai-company/.env`).
> Il tuo ID agente e la tua chiave sono quelli del TUO ruolo — non usare quelle degli altri.

## 0. Chi sei

| Ruolo | Key env | ID agente | Scrivi solo in |
|---|---|---|---|
| CEO | `PAPERCLIP_AGENT_CEO_KEY` | `4ca68d04-6f0b-478c-897c-e95e5a5678a7` | radice (review/merge) |
| PO | `PAPERCLIP_AGENT_PO_KEY` | `a25d29d1-9402-4699-ad90-af879aa8e7f1` | `specs/` |
| core-dev | `PAPERCLIP_AGENT_CORE_DEV_KEY` | `610739a8-6c71-4881-8dda-7c3e011027e4` | `backend/` |
| ui-ux | `PAPERCLIP_AGENT_UI_UX_KEY` | `f41ce726-1c48-40e5-aea0-7d8934ec9401` | `frontend/` |

## 1. Leggi il ticket

```bash
$PAPERCLIP_CLI issue get BOH-5 --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"
```

`issue list` per vedere la coda:

```bash
$PAPERCLIP_CLI issue list --company-id "$PAPERCLIP_COMPANY_ID" \
  --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"
```

## 2. Lavora

- Il **lock** lo prende Paperclip quando parte il run sull'issue: non serve checkout manuale.
- Scrivi **solo** nella tua directory (tabella sopra). Fuori perimetro = lavoro buttato.
- Commit piccoli e atomici, sul branch del tuo ruolo:

```bash
cd /srv/ai-company/workspace
git checkout -B dev/backend        # oppure po/specs, dev/frontend
git add backend/ && git commit -m "feat(backend): pipeline noul->score->choice"
```

## 3. Chiudi il ticket (obbligatorio)

```bash
# riepilogo per il team (cosa, dove, test, numeri misurati)
$PAPERCLIP_CLI issue comment BOH-5 \
  --body "FATTO: ... / DOVE: ... / TEST: ... / NUMERI: ..." \
  --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"

# stato: in_review OBBLIGATORIO prima della review
$PAPERCLIP_CLI issue update BOH-5 --payload-json '{"status":"in_review"}' \
  --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"
```

Stati validi: `backlog`, `todo`, `in_progress`, `in_review`, `done`, `blocked`, `cancelled`.

### `done` SOLO dopo review — gate `bin/close-ticket`

**Nessun agente imposta `done` direttamente.** Dopo `in_review`, agent-reviewer
esamina (protocollo in `REVIEW_PROTOCOL.md`) e lascia un commento con `APPROVE`
o `REJECT`. La chiusura si fa con il gate:

```bash
/srv/ai-company/bin/close-ticket BOH-5     # exit 0 solo se c'è APPROVE del reviewer
```

Il gate verifica: stato `in_review` + commento di agent-reviewer con `APPROVE`
(più recente di eventuali `REJECT`). Se manca: exit 1, l'issue resta `in_review`.
Chiudere a mano via API è fuori procedura e richiede una decisione umana.

### Il flusso di review che funziona (ticket [REVIEW] separato)

**Problema reale:** l'assegnatario di un ticket `in_review` è l'AUTORE, quindi
agent-reviewer non lo vede nel suo inbox e non parte. Se gli assegni il ticket
originale, il run viene **cancellato** ("issue assignee changed before the queued
run could start") e l'auto-review è comunque vietata.

**Procedura corretta:**

1. L'autore lascia il ticket in `in_review` con il commento FATTO/DOVE/TEST/NUMERI.
2. Il CEO (o l'amministratore) apre un ticket `[REVIEW] <IDENT> — <titolo>` con
   `assigneeAgentId = agent-reviewer` (3b1b700c-1bad-4ee1-81c7-9d240a648ca9).
   Nel corpo: contesto (file + commit), cosa verificare, comandi riproducibili.
3. Il reviewer verifica e commenta **sul ticket [REVIEW]**:
   `APPROVE <IDENT>` oppure `REJECT <IDENT>` + prove.
4. `bin/close-ticket <IDENT>` chiude il task originale: il gate cerca l'APPROVE
   sia sul task sia sui ticket `[REVIEW]` collegati (il body deve citare l'IDENT).

**Attenzione alla review policy `not_creator`:** chi ha portato l'issue in
`in_review` non può approvarla/chiuderla (403 `review_policy_denied`). Se il
gate fallisce con quell'errore, la chiusura la deve fare un altro scrittore
(CEO o amministratore), non chi ha aperto la review.

**Chiavi:** fuori da un run d'agente il gate usa `PAPERCLIP_BOARD_API_KEY`;
dentro un run usa `PAPERCLIP_AGENT_CEO_KEY` + header `X-Paperclip-Run-Id`
(la CEO key da sola non può scrivere cross-issue: 403 "Cross-issue writes need a run").

**Ondate:** non assegnare più di ~4 ticket [REVIEW] per volta al reviewer —
13 run concorrenti su una macchina piccola fanno thrash e i run si cancellano.

## 4. Se sei bloccato

```bash
$PAPERCLIP_CLI issue update BOH-5 --payload-json '{"status":"blocked"}' \
  --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"
$PAPERCLIP_CLI issue comment BOH-5 --body "BLOCCO: <motivo preciso> — serve: <cosa>" ...
```

Mai inventare numeri o claim: se una misura non è disponibile, dillo e metti `unresolved`.

## 5. Regole d'oro

1. Un ticket = un deliverable verificabile.
2. Niente scritture fuori dal proprio perimetro.
3. Sempre commento finale con i numeri reali (o "non misurabile, motivo").
4. Se un altro agente ha bisogno del tuo output, linka il file esatto nel commento.

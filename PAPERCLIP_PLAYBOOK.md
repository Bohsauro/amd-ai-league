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

# stato
$PAPERCLIP_CLI issue update BOH-5 --payload-json '{"status":"in_review"}' \
  --api-base "$PAPERCLIP_API_URL" --api-key "$PAPERCLIP_AGENT_CORE_DEV_KEY"
```

Stati validi: `backlog`, `todo`, `in_progress`, `in_review`, `done`, `blocked`, `cancelled`.

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

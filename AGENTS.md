# AI Software Company - Costituzione del Team

## Mappa del workspace

| Directory    | Proprietario di scrittura | Altri        |
|--------------|---------------------------|--------------|
| `specs/`     | agent-po                  | tutti: lettura |
| `backend/`   | agent-core-dev            | tutti: lettura |
| `frontend/`  | agent-ui-ux               | tutti: lettura |
| radice       | solo review/merge (CEO)   | —            |

## Protocollo Paperclip (Task Lock)

Comandi esatti (get/comment/update/stati) in **`PAPERCLIP_PLAYBOOK.md`** — leggilo prima di
iniziare un ticket. Il lock lo prende Paperclip all'avvio del run: niente checkout manuale.

1. Ogni attività nasce come issue su Paperclip, assegnata a un agente.
2. L'agente acquisisce il lock (checkout dell'issue) prima di scrivere.
3. Si scrive SOLO nei path di propria competenza (tabella sopra).
4. A lavoro finito: commit + push sul branch, commento sull'issue, lock rilasciato.
5. Il CEO e' superadmin della board: smista, assegna, acquisisce e revoca i lock.

## Convenzioni commit

```
tipo(scope): descrizione   es. feat(backend): add auth middleware
tipi: feat, fix, docs, refactor, test, chore
```
- Commit piccoli e atomici.
- Niente push diretto su `main`: branch per ruolo (`po/specs`, `dev/backend`,
  `dev/frontend`), review + merge a cura del CEO/owner.

## Done Definition

- [ ] Codice conforme ai criteri di accettazione dell'issue
- [ ] Nessuna scrittura fuori dal proprio perimetro
- [ ] Commit + push sul branch del ruolo
- [ ] Riepilogo sulla issue Paperclip (cosa, dove, test fatti)
- [ ] `in_review` + **verdetto APPROVE di agent-reviewer** (gate `bin/close-ticket`)
- [ ] Lock rilasciato (se acquisito)

> `done` senza review è fuori procedura: `bin/close-ticket` rifiuta la chiusura
> se non c'è un APPROVE del reviewer sul ticket.

## LLM endpoint

Tutti gli agenti parlano con **PennyRoute** locale (`127.0.0.1:8490/v1`,
modello `penny`). La key vive in `/srv/ai-company/.env` e nei config dei
rispettivi agenti. Nessuna chiave esterna richiesta.
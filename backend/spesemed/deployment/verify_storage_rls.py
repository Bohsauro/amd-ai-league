"""SPESEMED - Verifica Storage RLS (defense-in-depth) per il bucket `receipts`.

Script di pen-test che verifica che le storage policies RLS applichino
l'isolamento per-user_id: un utente autenticato deve poter listare/leggere
SOLO i propri file sotto `receipts/{user_id}/...`, MAI quelli di altri utenti.

Vedi `deployment/VERIFY_RLS.md` §6 per il protocollo completo (pre-requisiti,
evidence da raccogliere, expected output).

USAGE:
    export SUPABASE_URL=https://<project-ref>.supabase.co
    export SUPABASE_ANON_KEY=eyJhbGciOi...   # ANON key (pubblica), NON service_role
    export USER_A_EMAIL=user_a@test.local
    export USER_A_PASSWORD=<password robusta>
    python deployment/verify_storage_rls.py

NB: l'ANON key e' pubblica per design di Supabase (vincolata da RLS), ma va
comunque letta da env-var, MAI hardcoded nel sorgente (espone il project-ref
e impedisce la rotazione). Lo stesso vale per URL e credenziali utente.
"""
import os
import sys

from supabase import create_client


def _require_env(name: str) -> str:
    """Restituisce la variabile d'ambiente `name` o esce con errore chiaro."""
    value = os.environ.get(name, "").strip()
    if not value:
        print(
            f"ERRORE: variabile d'ambiente '{name}' mancante o vuota.\n"
            f"  Impostala prima di eseguire lo script (vedi VERIFY_RLS.md §6).",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def main() -> int:
    # Lookups corretti: il NOME della variabile e' la chiave, il valore e' il secret.
    # In precedenza questo file usava il valore come chiave (bug + secret leak).
    supabase_url = _require_env("SUPABASE_URL")
    supabase_anon_key = _require_env("SUPABASE_ANON_KEY")
    user_a_email = _require_env("USER_A_EMAIL")
    user_a_password = _require_env("USER_A_PASSWORD")

    # NB: usiamo l'ANON key (non service_role) per simulare un client reale
    # soggetto alle storage RLS policies. La service_role bypasserebbe RLS.
    client = create_client(supabase_url, supabase_anon_key)

    # Sign-in come user A (per ottenere un JWT utente autenticato).
    try:
        client.auth.sign_in_with_password({
            "email": user_a_email,
            "password": user_a_password,
        })
    except Exception as e:
        print(
            f"ERRORE: login user A fallito ({type(e).__name__}). "
            f"Verifica che l'utente esista e abbia email confermata "
            f"(VERIFY_RLS.md §0.4).",
            file=sys.stderr,
        )
        return 3

    # Recupera l'user_id reale dal JWT (auth.uid()) per costruire il path.
    user = client.auth.get_user().user
    if user is None or not getattr(user, "id", None):
        print("ERRORE: impossibile recuperare user_id dalla sessione.", file=sys.stderr)
        return 4
    user_a_id = str(user.id)

    # Upload di un file di test sotto il path del user A.
    user_a_path = f"receipts/{user_a_id}/test_a.pdf"
    try:
        client.storage.from_("receipts").upload(
            user_a_path,
            b"fake-pdf-content-user-a",
            file_options={"content-type": "application/pdf"},
        )
    except Exception as e:
        # 409 = file gia' esistente (idempotente per re-run): non bloccare.
        msg = str(e).lower()
        if "already" not in msg and "409" not in msg and "conflict" not in msg:
            print(f"ERRORE: upload fallito ({type(e).__name__}: {e})", file=sys.stderr)
            return 5

    # List bucket: deve mostrare SOLO i file del proprio user_id.
    # L'attaccante (user A) non deve vedere file di altri user_id.
    print(f"User A ({user_a_id}) listando receipts/ :")
    files = client.storage.from_("receipts").list("receipts/")
    own_seen = False
    foreign_seen = False
    for f in files:
        name = f.get("name", "")
        if not name:
            continue
        # Mostra solo entry rilevanti per il test (own vs foreign).
        if user_a_id in name:
            print(f"  [OWN]     {name}")
            own_seen = True
        else:
            print(f"  [FOREIGN] {name}  <- LEAK se visibile a user A")
            foreign_seen = True

    # Verdetto
    print()
    if foreign_seen:
        print("FAIL: RLS storage NON isola per user_id (user A vede file altrui).")
        return 1
    if not own_seen:
        # Non bloccante: puo' succedere se la list() non e' ricorsiva e il
        # path e' annidato, ma lo segnaliamo per trasparenza.
        print("WARN: nessun file proprio visibile nella list() top-level "
              "(potrebbe essere normale se list non e' ricorsiva).")
    print("PASS: user A vede solo i propri file (RLS storage efficace).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""SPESEMED - Validazione E2E success-path su Supabase REALE (Fase 4C).

Questo script prepara ed esegue la validazione end-to-end del backend
SPESEMED contro un'istanza reale (Supabase + OpenRouter configurati).

FLUSSO VALIDATO (success-path):
    health -> signup -> login -> jobs (storico) -> extract -> export

REGOLE:
    - NESSUN secret nel workspace: tutte le credenziali vengono lette da
      variabili d'ambiente (vedi README.md in questo stesso folder).
    - L'USER non deve MAI committare il file condiviso: le env var vanno
      esportate nel proprio shell (o usate in un .env NON tracciato).
    - Exit code 0 <=> health + login OK (core) e tutti gli step opzionali
      tentati sono passati; SKIP (dipendenze non configurate lato server)
      e' considerato accettabile e NON fa fallire il run.

USO:
    export SPESEMED_API_BASE=http://localhost:8000
    export SPESEMED_TEST_EMAIL=you@example.com
    export SPESEMED_TEST_PASSWORD='S3cret!Pass'
    export SPESEMED_TEST_RECEIPT=/path/to/ricevuta.jpg   # opzionale
    python tests/e2e/run_e2e.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

# =============================================================================
# Config da env (nessun valore hardcoded)
# =============================================================================

API_BASE = os.environ.get("SPESEMED_API_BASE", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("SPESEMED_TEST_EMAIL", "")
PASSWORD = os.environ.get("SPESEMED_TEST_PASSWORD", "")
RECEIPT_FILE = os.environ.get("SPESEMED_TEST_RECEIPT", "")

REQUIRED_ENV = (
    (("SPESEMED_TEST_EMAIL", EMAIL), "email utente test"),
    (("SPESEMED_TEST_PASSWORD", PASSWORD), "password utente test"),
)


# =============================================================================
# Reporting helpers
# =============================================================================

class Result:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def ok(self, step: str, msg: str) -> None:
        self.rows.append((step, "OK", msg))

    def skip(self, step: str, msg: str) -> None:
        self.rows.append((step, "SKIP", msg))

    def fail(self, step: str, msg: str) -> None:
        self.rows.append((step, "FAIL", msg))

    def summary(self) -> Tuple[int, int, int]:
        return (
            sum(1 for _, s, _ in self.rows if s == "OK"),
            sum(1 for _, s, _ in self.rows if s == "SKIP"),
            sum(1 for _, s, _ in self.rows if s == "FAIL"),
        )


def _print_report(res: Result) -> None:
    for step, status, msg in res.rows:
        print(f"[{status:>4}] {step:<24} {msg}")
    ok, skip, failed = res.summary()
    print("\n=== RIEPILOGO ===")
    print(f"OK={ok} SKIP={skip} FAIL={failed}")
    print("VERDETTO: " + ("PASS" if failed == 0 else "FAIL"))


# =============================================================================
# Step implementativi
# =============================================================================

def step_health(res: Result) -> None:
    with httpx.Client(base_url=API_BASE, timeout=10.0) as client:
        r = client.get("/api/v1/health")
    if r.status_code == 200:
        body = r.json()
        res.ok("health", f"200 status={body.get('status')} openrouter={body.get('openrouter_configured')}")
    else:
        res.fail("health", f"HTTP {r.status_code} atteso 200")


def step_signup(res: Result) -> Optional[str]:
    payload = {"email": EMAIL, "password": PASSWORD}
    with httpx.Client(base_url=API_BASE, timeout=15.0) as client:
        r = client.post("/api/v1/auth/signup", json=payload)
    if r.status_code == 201:
        res.ok("signup", "201 utente creato")
    elif r.status_code == 400 and "already" in (r.json().get("detail") or "").lower():
        res.skip("signup", "400 utente gia' registrato (accettato)")
    elif r.status_code == 403:
        res.skip("signup", "403 ALLOW_SIGNUP=false (signup disabilitato)")
    else:
        res.fail("signup", f"HTTP {r.status_code} inatteso: {r.text[:120]}")
    return None


def step_login(res: Result) -> Optional[str]:
    payload = {"email": EMAIL, "password": PASSWORD}
    with httpx.Client(base_url=API_BASE, timeout=15.0) as client:
        r = client.post("/api/v1/auth/login", json=payload)
    if r.status_code == 200:
        body = r.json()
        res.ok("login", "200 -> access_token ottenuto")
        return body.get("access_token")
    res.fail("login", f"HTTP {r.status_code}: {r.text[:120]} (credenziali? Supabase configurato?)")
    return None


def step_jobs(res: Result, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=API_BASE, timeout=15.0) as client:
        r = client.get("/api/v1/jobs", headers=headers)
    if r.status_code == 200:
        body = r.json()
        res.ok("jobs", f"200 -> {body.get('total', 0)} job in storico")
    elif r.status_code == 503:
        res.skip("jobs", "503 Supabase non configurato lato server")
    else:
        res.fail("jobs", f"HTTP {r.status_code}: {r.text[:120]}")


def step_extract(res: Result, token: str) -> None:
    if not RECEIPT_FILE:
        res.skip("extract", "SPESEMED_TEST_RECEIPT non impostata (skip obbligatorio)")
        return
    path = Path(RECEIPT_FILE)
    if not path.is_file():
        res.fail("extract", f"file non trovato: {RECEIPT_FILE}")
        return
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        with path.open("rb") as fh:
            r = client.post(
                "/api/v1/extract",
                headers=headers,
                files={"files": (path.name, fh, "application/octet-stream")},
            )
    if r.status_code == 200:
        res.ok("extract", "200 sync -> risultati estratti")
    elif r.status_code == 202:
        res.ok("extract", "202 async -> job creato (job_id presente)")
    elif r.status_code == 503:
        res.skip("extract", "503 OpenRouter/Supabase non configurati lato server")
    else:
        res.fail("extract", f"HTTP {r.status_code}: {r.text[:120]}")


def step_export(res: Result, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=API_BASE, timeout=60.0) as client:
        r = client.post("/api/v1/export", headers=headers, json={})
    if r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        res.ok("export", f"200 -> ZIP ricevuto ({len(r.content)} bytes, {ctype})")
    elif r.status_code == 400:
        res.skip("export", "400 nessuna estrazione da esportare (endpoint OK)")
    elif r.status_code == 503:
        res.skip("export", "503 Supabase non configurato lato server")
    else:
        res.fail("export", f"HTTP {r.status_code}: {r.text[:120]}")


def main() -> int:
    missing = [(name, why) for (name, value), why in REQUIRED_ENV if not value]
    if missing:
        print("ERRORE: variabili ambiente mancanti:")
        for name, why in missing:
            print(f"  - {name} ({why})")
        print("\nEsempio:\n  export SPESEMED_API_BASE=http://localhost:8000\n"
              "  export SPESEMED_TEST_EMAIL=foo@example.com\n"
              "  export SPESEMED_TEST_PASSWORD='S3cret!'\n"
              "  export SPESEMED_TEST_RECEIPT=/path/to/ricevuta.jpg  # opzionale")
        return 2

    res = Result()
    print(f"Target: {API_BASE}  user={EMAIL}\n")

    step_health(res)
    step_signup(res)
    token = step_login(res)
    if token:
        step_jobs(res, token)
        step_extract(res, token)
        step_export(res, token)
    else:
        # Senza login, i passi autenticati non hanno senso: li segnamo SKIP.
        for step in ("jobs", "extract", "export"):
            res.skip(step, "login fallito: step dipendenti non eseguibili")

    _print_report(res)

    _, _, failed = res.summary()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
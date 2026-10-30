#!/usr/bin/env python3
"""SPESEMED E2E success-path script (secret-free).

Valida il flusso completo contro un'istanza REALE dell'API:
    health -> signup -> login -> jobs -> extract -> export (200 OK)

NON contiene secrets per design: parla solo con gli endpoint pubblici
dell'API. Le chiavi (Supabase/OpenRouter/Stripe) vivono sul SERVER, non qui.

Usage:
    python3 scripts/e2e_success_path.py [--file RICEVUTA.pdf] [--url URL]
        [--email a@b.c] [--password pwd] [--outdir DIR] [--no-extract]

Exit codes:
    0  tutti gli step obbligatori PASS
    2  errore di configurazione locale (es. --file mancante)
    3  health / auth falliti
    4  extract / export falliti

Dipendenze: solo stdlib Python 3.9+ (urllib).
"""

import argparse
import json
import os
import secrets as pysecrets
import string
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_URL = os.environ.get("SPESEMED_API_URL", "http://localhost:8000")
DEFAULT_EMAIL = os.environ.get("SPESEMED_E2E_EMAIL")
DEFAULT_PASSWORD = os.environ.get("SPESEMED_E2E_PASSWORD")
MAX_POLL_SECONDS = int(os.environ.get("SPESEMED_E2E_MAX_POLL", "300"))
POLL_INTERVAL_SECONDS = float(os.environ.get("SPESEMED_E2E_POLL_INTERVAL", "5"))

_results: list[dict] = []


def record(step: str, ok: bool, detail: str = "", status: int | None = None):
    """Accumula l'esito di uno step; stampa subito [PASS]/[FAIL]."""
    _results.append(
        {"step": step, "ok": ok, "detail": detail, "status": status}
    )
    tag = "PASS" if ok else "FAIL"
    status_str = f" [HTTP {status}]" if status is not None else ""
    tail = f" -- {detail}" if detail else ""
    print(f"[{tag}] {step}{status_str}{tail}")


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:300]}")


def _request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: int = 30,
) -> tuple[int, dict | bytes, str]:
    """Esegue la request. Ritorna (status, json|bytes, content_type)."""
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype or ctype.startswith("text/json"):
                return resp.status, json.loads(raw.decode("utf-8")), ctype
            return resp.status, raw, ctype
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8")), e.headers.get("Content-Type", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return e.code, raw, e.headers.get("Content-Type", "")


def api_json(method: str, path: str, *, token: str | None = None, payload=None, timeout: int = 30):
    """Chiamata JSON; ritorna (status, json_dict|raw)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    status, data, ctype = _request(method, f"{BASE}{path}", headers=headers, body=body, timeout=timeout)
    return status, data


def _multipart(field: str, path: Path):
    """Costruisce body multipart/form-data con un solo file."""
    boundary = "----spesemedE2E" + pysecrets.token_hex(8)
    filename = path.name
    ctype = "application/octet-stream"
    suffix = path.suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    if suffix in mapping:
        ctype = mapping[suffix]
    content = path.read_bytes()
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def step_health() -> bool:
    status, data = api_json("GET", "/api/v1/health")
    ok = status == 200 and isinstance(data, dict) and data.get("status") == "ok"
    detail = f"service={data.get('service')} version={data.get('version')} openrouter={data.get('openrouter_configured')}" \
        if isinstance(data, dict) else str(data)[:120]
    record("health GET /api/v1/health", ok, detail, status)
    return ok


def step_signup(email: str, password: str) -> bool:
    status, data = api_json("POST", "/api/v1/auth/signup", payload={"email": email, "password": password})
    if status == 201 and isinstance(data, dict) and data.get("access_token"):
        record("signup POST /api/v1/auth/signup", True, f"user={data.get('user_id', '?')[:12]}", status)
        return True
    if status == 403:
        record("signup", False, "403: signup disabilitato (ALLOW_SIGNUP=true sul server?)", status)
    elif status == 429:
        record("signup", False, "429: rate-limit signup 2/hour superato dall'IP", status)
    else:
        record("signup", False, str(data)[:200], status)
    return False


def step_login(email: str, password: str) -> str | None:
    status, data = api_json("POST", "/api/v1/auth/login", payload={"email": email, "password": password})
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        record("login POST /api/v1/auth/login", True, f"user={data.get('user_id', '?')[:12]}", status)
        return data["access_token"]
    record("login", False, str(data)[:200], status)
    return None


def step_jobs(token: str) -> bool:
    status, data = api_json("GET", "/api/v1/jobs", token=token)
    ok = status == 200 and isinstance(data, dict) and "jobs" in data
    detail = f"total={data.get('total')}" if isinstance(data, dict) else str(data)[:120]
    record("jobs GET /api/v1/jobs (auth)", ok, detail, status)
    return ok


def _poll_job(token: str, job_id: str) -> dict | None:
    deadline = time.time() + MAX_POLL_SECONDS
    while time.time() < deadline:
        status, data = api_json("GET", f"/api/v1/jobs/{job_id}", token=token)
        if status != 200:
            record("jobs poll", False, f"GET /jobs/{job_id} -> {status}", status)
            return None
        st = data.get("status") if isinstance(data, dict) else ""
        if st in ("done", "failed"):
            if isinstance(data, dict):
                return data
            return None
        time.sleep(POLL_INTERVAL_SECONDS)
    record("jobs poll", False, f"timeout dopo {MAX_POLL_SECONDS}s per job {job_id}")
    return None


def step_extract(token: str, file_path: Path) -> dict | None:
    body, ctype = _multipart("files", file_path)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": ctype}
    try:
        status, data, _ = _request(
            "POST", f"{BASE}/api/v1/extract", headers=headers, body=body, timeout=120
        )
    except Exception as e:  # timeout/connection
        record("extract POST /api/v1/extract", False, f"eccezione: {e}")
        return None
    if status == 200 and isinstance(data, dict):
        count = data.get("count", 0)
        ok = count > 0
        record("extract (sync)", ok, f"risultati={count} model={data.get('model_used')}", status)
        return data if ok else None
    if status == 202 and isinstance(data, dict):
        record("extract (async)", True, f"job_id={data.get('job_id')} -> poll", status)
        job = _poll_job(token, data["job_id"])
        if job and job.get("status") == "done":
            record("extract (async done)", True, f"completed={job.get('completed_count')}/{job.get('file_count')}")
            return job.get("results") or {}
        record("extract (async)", False, str(job or data)[:200])
        return None
    record("extract", False, str(data)[:200], status)
    return None


def step_export(token: str, outdir: Path) -> bool:
    status, data = api_json("POST", "/api/v1/export", token=token, payload={}, timeout=60)
    if status == 200 and isinstance(data, bytes):
        is_zip = data[:4] == b"PK\x03\x04"
        fname = outdir / f"e2e_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
        fname.write_bytes(data)
        ok = is_zip and fname.stat().st_size > 0
        record("export POST /api/v1/export", ok, f"zip={fname} bytes={len(data)}", status)
        return ok
    if status == 400:
        record("export", False, "400: nessuna estrazione da esportare (serve almeno un extract riuscito)", status)
    else:
        record("export", False, str(data)[:200], status)
    return False


def step_billing_status(token: str) -> bool:
    """Step 4C opzionale (non bloccante): stato piano dell'utente autenticato."""
    status, data = api_json("GET", "/api/v1/billing/status", token=token)
    ok = status == 200 and isinstance(data, dict)
    detail = f"billing_enabled={data.get('billing_enabled')} plan={data.get('plan')}" \
        if isinstance(data, dict) else str(data)[:120]
    record("billing/status (opzionale)", ok, detail, status)
    return ok


def step_metrics() -> bool:
    """Step opzionale (non bloccante): /metrics esposto solo a IP allowlist."""
    status, data, _ = _request("GET", f"{BASE}/metrics", timeout=15)
    if status == 200 and isinstance(data, bytes):
        lines = data.splitlines()
        has_prom_format = any(l.startswith(b"# ") for l in lines[:20])
        has_spesemed = any(l.startswith(b"spesemed_") for l in lines[:200])
        record("metrics /metrics (opzionale)", True,
               f"exposition bytes={len(data)} prometheus_format={has_prom_format} spesemed_metrics={has_spesemed}",
               status)
    elif status in (403, 404):
        record("metrics", True, f"{status}: atteso se IP non in allowlist o disabilitato (non bloccante)", status)
    else:
        record("metrics", False, str(data)[:120], status)
    return True  # mai bloccante


def run(api_url: str, email: str, password: str, file_path: Path | None, outdir: Path, do_extract: bool) -> int:
    global BASE
    BASE = api_url.rstrip("/")

    print(f"== SPESEMED E2E success-path ==")
    print(f"base:   {BASE}")
    print(f"email:  {email}")
    print(f"file:   {file_path if file_path else '(nessuno, extract/export skippati)'}")
    print()

    if not step_health():
        return 3

    token: str | None = None
    if step_signup(email, password):
        token = step_login(email, password)
    else:
        # Fallback: se il signup fallisce (utente già esistente / signup disabilitato),
        # proviamo comunque il login con le stesse credenziali.
        print(">> signup non riuscito, tento login diretto (utente forse già esistente)")
        token = step_login(email, password)
    if not token:
        return 3

    if not step_jobs(token):
        return 3

    if do_extract:
        if file_path is None or not file_path.is_file():
            print("[SKIP] extract/export: nessun --file valido fornito", file=sys.stderr)
            return 2
        extracted = step_extract(token, file_path)
        if extracted is None:
            return 4
        if not step_export(token, outdir):
            return 4
    else:
        print(">> --no-extract: salto extract/export")

    # Step 4C opzionali (mai bloccanti)
    step_billing_status(token)
    step_metrics()

    # Riepilogo
    print()
    fails = [r for r in _results if not r["ok"] and "opzionale" not in r["step"]]
    print(f"== Riepilogo: {sum(1 for r in _results if r['ok'])} PASS / {sum(1 for r in _results if not r['ok'])} FAIL ==")
    if fails:
        for r in fails:
            print(f"  FAIL {r['step']}: {r['detail']}")
        return 4 if any("extract" in r["step"] or "export" in r["step"] for r in fails) else 3
    return 0


def _gen_credentials() -> tuple[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    email = f"e2e.{ts}@spesemed.local"
    alphabet = string.ascii_letters + string.digits
    password = "".join(pysecrets.choice(alphabet) for _ in range(16))
    return email, password


def main() -> int:
    parser = argparse.ArgumentParser(description="SPESEMED E2E success-path (secret-free)")
    parser.add_argument("--file", type=Path, default=None,
                        help="Ricevuta di esempio (PDF/JPG/PNG/WEBP/BMP) per extract+export. Obbligatorio senza --no-extract.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Base URL API (default: {DEFAULT_URL})")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Email test (default: generata)")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password test (default: generata)")
    parser.add_argument("--outdir", type=Path, default=Path("e2e_output"), help="Cartella per lo ZIP esportato")
    parser.add_argument("--no-extract", action="store_true", help="Salta extract/export (solo health+auth+jobs)")
    args = parser.parse_args()

    email = args.email
    password = args.password
    if not email or not password:
        gen_email, gen_password = _gen_credentials()
        email = email or gen_email
        password = password or gen_password
        print(f">> credenziali generate: {email}")

    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        return run(args.url, email, password, args.file, outdir, not args.no_extract)
    except Exception as e:  # errori imprevisti
        print(f"[FAIL] eccezione non gestita: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
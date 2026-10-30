"""SPESEMED - Validazione manuale end-to-end del backend (Fase 0+1+2+3).

Scopo: produrre un report di validation riproducibile senza dipendere da bash
escaping, port collision o altre interferenze runtime.

Esegue:
  STEP1  syntax check (compileall src/ tests/)
  STEP2  pytest completo (test_health + test_auth + test_extract)
  STEP3  regressione (tests.test_imports)
  STEP4  spawn uvicorn su porta 8773 + 7 endpoint + burst + openapi paths
  STEP5  kill uvicorn

Uso:
    python tests/manual_validation.py

Exit 0 se tutti gli endpoint rispondono col codice atteso, altrimenti 1.

⚠️  AMBIENTE RICHIESTO: questo script assume `.env` VUOTO (env-empty mode).
    Se hai un `.env` con Supabase reale configurato (SUPABASE_URL +
    SUPABASE_SERVICE_KEY + SUPABASE_JWT_SECRET valorizzati), i test
    T2/T3/T6/T8 avranno risultati diversi dai valori attesi:
      - T2/T3 (login/refresh)  : supabase.auth reale restituirà 401 invece
        di 503 (Supabase auth lato server rifiuta credenziali inesistenti).
      - T6 (logout con Bearer opaco) : `decode_supabase_jwt` rifiuterà la
        stringa non-JWT invece di accettarla come user_id opaco (dev-mode).
        Questo NON e' regressione: e' il comportamento corretto della nuova
        auth ibrida con config prod reale.
    Per eseguire questo script in modalita' 'offline pura':
        mv .env .env.bak
        python tests/manual_validation.py
        mv .env.bak .env
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Path assoluto della root del progetto
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PORT = 8773
BASE = f"http://127.0.0.1:{PORT}"


def kill_zombies() -> None:
    """Kill pre-esistenti python.exe / uvicorn (best-effort)."""
    subprocess.run(["taskkill", "//F", "//IM", "python.exe"], capture_output=True)
    time.sleep(2)


def wait_port(port: int, timeout: float = 20.0) -> bool:
    """Blocca finche' localhost:port accetta connessioni TCP."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def http(method: str, path: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, str]:
    """Esegue una richiesta HTTP e ritorna (status_code, body_text)."""
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json"} if data else {}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main() -> int:
    kill_zombies()

    # === STEP1 syntax ===
    print("=== STEP1_SYNTAX ===")
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "src/", "tests/"],
        capture_output=True, text=True,
    )
    print("SYNTAX_OK" if r.returncode == 0 else f"FAIL: {r.stderr}")
    syntax_ok = r.returncode == 0

    # === STEP2 pytest ===
    print("\n=== STEP2_PYTEST ===")
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_health.py", "tests/test_auth.py", "tests/test_extract.py",
         "--tb=short", "-v", "--no-header"],
        capture_output=True, text=True,
    )
    print("\n".join(r.stdout.splitlines()[-40:]))
    pytest_passed = r.returncode == 0
    print(f"PYTEST_EXIT={r.returncode}")

    # === STEP3 regression imports ===
    print("\n=== STEP3_REGRESSION ===")
    r = subprocess.run([sys.executable, "-m", "tests.test_imports"],
                       capture_output=True, text=True)
    print("\n".join(r.stdout.splitlines()[-3:]))

    # === STEP4 live uvicorn ===
    print("\n=== STEP4_UVICORN ===")
    log = open(os.path.join(ROOT, ".uvicorn_manual.log"), "w")
    uvicorn = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "spesemed.api.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        stdout=log, stderr=subprocess.STDOUT,
    )
    all_pass = True
    try:
        if not wait_port(PORT, timeout=20):
            print(f"BOOT_FAIL: uvicorn (pid={uvicorn.pid}) non si e' bindato entro 20s")
            print("--- uvicorn log ---")
            log.flush()
            with open("/tmp/uvicorn_manual.log") as f:
                print(f.read()[-2000:])
            return 1
        print(f"BOOT_OK pid={uvicorn.pid}")

        cases = [
            # name, method, path, body, headers, expected
            ("T1_GET_health", "GET", "/api/v1/health", None, None, 200),
            ("T2_POST_login_NoSup", "POST", "/api/v1/auth/login",
             {"email": "a@b.c", "password": "validpass1"}, None, 503),
            ("T3_POST_refresh_NoSup", "POST", "/api/v1/auth/refresh",
             {"refresh_token": "valid-refresh-1234567890"}, None, 503),
            ("T4_POST_login_NoBody", "POST", "/api/v1/auth/login",
             None, None, 422),
            ("T5_POST_logout_NoBearer", "POST", "/api/v1/auth/logout",
             None, None, 401),
            ("T6_POST_logout_WithBearer", "POST", "/api/v1/auth/logout",
             None, {"Authorization": "Bearer fake-bearer-12345"}, 204),
            ("T7_POST_signup_ShortPwd", "POST", "/api/v1/auth/signup",
             {"email": "a@b.c", "password": "x"}, None, 422),
        ]
        for name, method, path, body, headers, expected in cases:
            code, text = http(method, path, body, headers)
            short = text[:120].replace("\n", " ")
            ok = code == expected
            mark = "OK" if ok else "FAIL"
            print(f"  [{mark}] {name} HTTP={code} atteso={expected} body={short}")
            all_pass = all_pass and ok

        # T8 burst login (3x rapid) — con env empty, tutti 503
        print("\n=== T8_BURST_LOGIN ===")
        for i in range(3):
            code, _ = http("POST", "/api/v1/auth/login",
                           {"email": "a@b.c", "password": "validpass1"})
            print(f"  burst[{i + 1}] HTTP={code}")

        # T9 OpenAPI paths
        print("\n=== T9_OPENAPI_PATHS ===")
        code, text = http("GET", "/openapi.json")
        if code == 200:
            data = json.loads(text)
            paths = sorted(data["paths"].keys())
            print(f"  paths_count={len(paths)} paths={paths}")

    finally:
        uvicorn.terminate()
        try:
            uvicorn.wait(timeout=5)
        except subprocess.TimeoutExpired:
            uvicorn.kill()
        kill_zombies()

    # === VERDETTO ===
    print("\n=== FINAL_VERDICT ===")
    print(f"  syntax_ok      = {syntax_ok}")
    print(f"  pytest_passed  = {pytest_passed}")
    print(f"  endpoints_ok   = {all_pass}")
    overall = syntax_ok and pytest_passed and all_pass
    print(f"  OVERALL        = {'PASS' if overall else 'FAIL'}")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())

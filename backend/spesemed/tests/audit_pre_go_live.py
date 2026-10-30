"""SPESEMED - Script di AUDIT pre-go-live (AUTO-GENERATED, do not edit manualmente).

Genera un report Markdown-ready su:
  1. migrations/001_init.sql: syntax sanity + tabelle/funzioni/trigger/indici
  2. .env.example vs config.py: env-vars coperte (orfane o mancanti)
  3. Endpoint surface: elenco endpoint con auth mode (via getattr + dependant check)

Uso:
    cd C:\\Users\\giova\\Desktop\\progetti\\SPESEMED
    python tests/audit_pre_go_live.py

Exit 0 sempre (script di sola lettura, non modifica nulla).
Output:
    - console: verdict ASCII (la console Windows cp1252 non regge unicode nel print)
    - file: tests/AUDIT_REPORT.md (UTF-8 con simboli unicode)
"""
from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "src"))

# Windows console: forza UTF-8 per evitare crash su caratteri unicode nei print
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, io.UnsupportedOperation):
    pass


def _extract_settings_class_body(text: str) -> str:
    """Estrai il blocco di codice dentro `class Settings(BaseSettings): ...`.

    Stop al primo top-level `class`, `def`, o assegnazione modulo-level dopo
    la classe (es. `settings = Settings()`).
    Restituisce il body della classe (escluso l'header).
    """
    m = re.search(r"class\s+Settings\s*\([^)]+\)\s*:", text)
    if not m:
        return ""
    start = m.end()
    rest = text[start:]
    end_match = re.search(r"\n(class\s+\w+[^(]|def\s+\w+|\w+\s*=\s*Settings\s*\(\s*\))", rest)
    end = end_match.start() if end_match else len(rest)
    return rest[:end]


def audit_sql(path: Path | None = None) -> dict:
    """Audit a migration SQL file (default: migrations/001_init.sql)."""
    path = path or ROOT / "migrations" / "001_init.sql"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    tables = []
    for lineno, line in enumerate(lines, 1):
        m = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", line, re.IGNORECASE)
        if m:
            tables.append((lineno, m.group(1)))

    functions = []
    for lineno, line in enumerate(lines, 1):
        m = re.search(r"(?:CREATE\s+OR\s+REPLACE\s+FUNCTION|CREATE\s+FUNCTION)\s+(\w+)\s*\(([^)]*)\)",
                      line, re.IGNORECASE)
        if m:
            functions.append((lineno, m.group(1), m.group(2).strip()))

    # Trigger: usa re.finditer sul testo intero con DOTALL per match multi-line
    triggers = []
    for m in re.finditer(r"CREATE\s+TRIGGER\s+(\w+).*?\bON\s+(\w+)\b",
                         text, re.IGNORECASE | re.DOTALL):
        line_no = text[:m.start()].count("\n") + 1
        triggers.append((line_no, m.group(1), m.group(2)))

    unique_constraints = []
    for lineno, line in enumerate(lines, 1):
        m = re.search(r"UNIQUE\s*\(([^)]+)\)", line, re.IGNORECASE)
        if m:
            unique_constraints.append((lineno, m.group(1).strip()))

    indexes = []
    for lineno, line in enumerate(lines, 1):
        m = re.search(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", line, re.IGNORECASE)
        if m:
            indexes.append((lineno, m.group(1)))

    parens_open = text.count("(")
    parens_close = text.count(")")
    final_semi = text.rstrip().endswith(";")
    comment_lines = sum(1 for ln in lines if ln.strip().startswith("--"))

    return {
        "file": str(path),
        "total_lines": len(lines),
        "tables": tables,
        "functions": functions,
        "triggers": triggers,
        "unique_constraints": unique_constraints,
        "indexes": indexes,
        "syntax": {
            "parens_open": parens_open,
            "parens_close": parens_close,
            "balanced": parens_open == parens_close,
            "ends_with_semi": final_semi,
            "comment_lines": comment_lines,
        },
    }


def audit_billing_migration() -> dict:
    """Audit offline di migrations/004_billing.sql (Fase 4C, BOH-25).

    Non esegue SQL: verifica struttura/idempotenza/RLS con gli stessi criteri
    conservativi dell'audit 001 (parentesi bilanciate, terminazione `;`) piu'
    i requisiti specifici del billing.
    """
    path = ROOT / "migrations" / "004_billing.sql"
    result = {"file": str(path), "exists": path.exists()}
    if not path.exists():
        result.update({"checks": {}, "ok": False})
        return result

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, text, re.IGNORECASE | re.DOTALL))

    checks = {
        "create_entitlements": has(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+entitlements\b"
        ),
        "create_stripe_events": has(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+stripe_events\b"
        ),
        "rls_entitlements": has(
            r"ALTER\s+TABLE\s+entitlements\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY"
        ),
        "rls_stripe_events": has(
            r"ALTER\s+TABLE\s+stripe_events\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY"
        ),
        "policy_entitlements_service_role": has(
            r"CREATE\s+POLICY\s+\"[^\"]+\"\s+ON\s+entitlements\b"
            r"[^;]*?auth\.role\(\)\s*=\s*'service_role'"
        ),
        "policy_stripe_events_service_role": has(
            r"CREATE\s+POLICY\s+\"[^\"]+\"\s+ON\s+stripe_events\b"
            r"[^;]*?auth\.role\(\)\s*=\s*'service_role'"
        ),
        "idempotent_policy_drop": text.lower().count("drop policy if exists") >= 2,
        "idempotent_add_column": "add column if not exists" in text.lower(),
        "legacy_upgrade_copy": has(
            r"to_regclass\('public\.subscriptions'\).*?to_regclass\('public\.billing_events'\)"
        ),
    }

    parens_open = text.count("(")
    parens_close = text.count(")")
    syntax = {
        "parens_open": parens_open,
        "parens_close": parens_close,
        "balanced": parens_open == parens_close,
        "ends_with_semi": text.rstrip().endswith(";"),
        "comment_lines": sum(1 for ln in lines if ln.strip().startswith("--")),
    }
    result.update(
        {
            "total_lines": len(lines),
            "checks": checks,
            "syntax": syntax,
            "ok": all(checks.values()) and syntax["balanced"] and syntax["ends_with_semi"],
        }
    )
    return result


def audit_dotenv_vs_config() -> dict:
    """Confronto .env.example vs Settings in config.py.

    Parser is CONSERVATIVE: estrae solo i field dichiarati dentro
    `class Settings(BaseSettings): ...` a 4-spazi di indentazione
    (esclude helper, fixture, mock, type annotations modulari).
    """
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    example_vars = set()
    for line in example.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            example_vars.add(line.split("=", 1)[0].strip())

    config_text = (ROOT / "src" / "spesemed" / "api" / "config.py").read_text(encoding="utf-8")

    # Env-vars ESPLICITE (env="...")
    config_env_explicit = set(re.findall(r'env\s*=\s*["\']([A-Z_][A-Z0-9_]*)["\']', config_text))

    # Env-vars IMPLICITE: Solo field dichiarati dentro `class Settings(BaseSettings)`
    # con 4-spazi di indentazione (class member, non helper).
    settings_body = _extract_settings_class_body(config_text)
    field_names = re.findall(r"^\s{4}([a-z_][a-z0-9_]*)\s*:", settings_body, re.MULTILINE)
    config_field_envs = {n.upper() for n in field_names}

    all_config_envs = config_env_explicit | config_field_envs

    return {
        "example_count": len(example_vars),
        "config_explicit_env_count": len(config_env_explicit),
        "config_field_env_count": len(config_field_envs),
        "example_vars": sorted(example_vars),
        "config_envs": sorted(all_config_envs),
        "orphan_in_example": sorted(example_vars - all_config_envs),
        "missing_in_example": sorted(all_config_envs - example_vars),
    }


def audit_endpoints() -> dict:
    """Elenco endpoint registrati nell'app FastAPI.

    Auth mode determinata via introspezione del `route.dependant.dependencies`:
    presenza di un dep il cui callable si chiama `get_current_user` indica Bearer
    richiesto (con X-User-Id dev fallback).
    """
    from spesemed.api.main import app

    auth_required = []
    anonymous = []

    for route in app.routes:
        if not hasattr(route, "path") or not hasattr(route, "methods"):
            continue
        path = route.path
        method = list(route.methods)[0] if route.methods else "-"

        requires_auth = False
        try:
            for dep in (route.dependant.dependencies or []):
                if dep.call.__name__ == "get_current_user":
                    requires_auth = True
                    break
        except Exception:
            pass

        (auth_required if requires_auth else anonymous).append((method, path))

    return {
        "total": len([r for r in app.routes if hasattr(r, "path")]),
        "auth_required": auth_required,
        "anonymous": anonymous,
    }


def render_report(sql: dict, env: dict, ep: dict, billing: dict | None = None) -> str:
    out = []
    out.append("# SPESEMED — Pre-Go-Live Audit Report\n")

    out.append("\n## 1. Migration `001_init.sql`\n")
    s = sql["syntax"]
    out.append(f"- **File**: `{sql['file']}` ({sql['total_lines']} righe)\n")
    out.append(f"- **Parens bilanciati**: {s['parens_open']} `(` vs {s['parens_close']} `)` -> "
               f"{'✅ balanced' if s['balanced'] else '❌ NOT balanced'}\n")
    out.append(f"- **Termina con `;`**: {'✅' if s['ends_with_semi'] else '❌'}\n")
    out.append(f"- **Linee di commento**: {s['comment_lines']}\n")
    out.append("\n### Tabelle (`CREATE TABLE`)\n")
    for lineno, name in sql["tables"]:
        out.append(f"  - L{lineno}: `{name}`\n")
    out.append("\n### Funzioni (`CREATE FUNCTION`)\n")
    for lineno, name, args in sql["functions"]:
        out.append(f"  - L{lineno}: `{name}({args})`\n")
    out.append("\n### Trigger\n")
    if not sql["triggers"]:
        out.append("  - (nessuno trovato)\n")
    for lineno, name, table in sql["triggers"]:
        out.append(f"  - L{lineno}: `{name}` ON `{table}`\n")
    out.append("\n### Vincoli UNIQUE\n")
    for lineno, cols in sql["unique_constraints"]:
        out.append(f"  - L{lineno}: `({cols})`\n")
    out.append("\n### Indici (CREATE INDEX)\n")
    for lineno, name in sql["indexes"]:
        out.append(f"  - L{lineno}: `{name}`\n")

    if billing is not None:
        out.append("\n## 1b. Migration `004_billing.sql`\n")
        if not billing.get("exists"):
            out.append(f"- **File**: `{billing['file']}` -> ❌ NON TROVATO\n")
        else:
            bs = billing["syntax"]
            out.append(f"- **File**: `{billing['file']}` ({billing['total_lines']} righe)\n")
            out.append(f"- **Parens bilanciati**: {bs['parens_open']} `(` vs {bs['parens_close']} `)` -> "
                       f"{'✅ balanced' if bs['balanced'] else '❌ NOT balanced'}\n")
            out.append(f"- **Termina con `;`**: {'✅' if bs['ends_with_semi'] else '❌'}\n")
            out.append(f"- **Linee di commento**: {bs['comment_lines']}\n")
            out.append("\n### Requisiti billing (idempotenza + RLS)\n")
            for check, passed in billing["checks"].items():
                out.append(f"  - {'✅' if passed else '❌'} `{check}`\n")
            out.append(f"\n> {'✅ billing migration OK' if billing['ok'] else '❌ billing migration NON conforme'}\n")

    out.append("\n## 2. `.env.example` vs `config.py` Settings\n")
    out.append(f"- **{env['example_count']}** env-vars documentate in `.env.example`\n")
    out.append(f"- **{env['config_explicit_env_count']}** env-vars esplicite (`env=\"...\"`) + "
               f"**{env['config_field_env_count']}** env-vars implicite (field name -> UPPER) = "
               f"**{len(env['config_envs'])}** totali lette da `config.py`\n")
    if env["orphan_in_example"]:
        out.append(f"\n### ⚠️ In `.env.example` ma **NON** in `config.py` ({len(env['orphan_in_example'])})\n")
        for v in env["orphan_in_example"]:
            out.append(f"  - `{v}`\n")
    else:
        out.append("\n> ✅ Nessuna env var orfana in `.env.example`\n")
    if env["missing_in_example"]:
        out.append(f"\n### ⚠️ In `config.py` ma **NON** in `.env.example` ({len(env['missing_in_example'])})\n")
        for v in env["missing_in_example"]:
            out.append(f"  - `{v}`\n")
    else:
        out.append("\n> ✅ Nessuna env var mancante in `.env.example`\n")
    out.append("\n### Tutte le env-vars (merged list)\n")
    out.append("| Env Var | `.env.example` | `config.py` |\n|---|---|---|\n")
    all_vars = sorted(set(env["example_vars"]) | set(env["config_envs"]))
    for v in all_vars:
        in_ex = "✅" if v in env["example_vars"] else "❌"
        in_cfg = "✅" if v in env["config_envs"] else "❌"
        out.append(f"| `{v}` | {in_ex} | {in_cfg} |\n")

    out.append("\n## 3. Endpoint surface\n")
    out.append(f"- **Totale routes**: {ep['total']}\n")
    out.append(f"- **Auth-required** (richiedono Bearer JWT o X-User-Id dev): {len(ep['auth_required'])}\n")
    for m, p in ep["auth_required"]:
        out.append(f"  - `{m} {p}`\n")
    out.append(f"- **Anonimi** (no auth): {len(ep['anonymous'])}\n")
    for m, p in ep["anonymous"]:
        out.append(f"  - `{m} {p}`\n")

    return "".join(out)


def main() -> int:
    print(">>> SPESEMED pre-go-live audit...\n")
    sql = audit_sql()
    billing = audit_billing_migration()
    env = audit_dotenv_vs_config()
    ep = audit_endpoints()
    report = render_report(sql, env, ep, billing)

    out_path = ROOT / "tests" / "AUDIT_REPORT.md"
    out_path.write_text(report, encoding="utf-8")
    print(f">>> Report salvato in `{out_path.relative_to(ROOT)}` (UTF-8)\n")

    bad = []
    if not sql["syntax"]["balanced"]:
        bad.append("parens non bilanciati in migration SQL")
    if not billing.get("ok"):
        failed = [name for name, ok in billing.get("checks", {}).items() if not ok]
        detail = ", ".join(failed) if failed else "file mancante o sintassi non valida"
        bad.append(f"004_billing.sql non conforme ({detail})")
    if env["orphan_in_example"] or env["missing_in_example"]:
        bad.append(f"{len(env['orphan_in_example']) + len(env['missing_in_example'])} env-vars disallineate")

    if bad:
        print(f">>> AUDIT FAILED: {'; '.join(bad)}")
        return 1
    print(">>> AUDIT PASSED: migration SQL sintatticamente OK (001 + 004_billing), .env allineata a config.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

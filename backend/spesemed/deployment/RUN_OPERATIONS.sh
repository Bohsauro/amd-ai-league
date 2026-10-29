#!/usr/bin/env bash
# =============================================================================
# SPESEMED - Production Operations Runner
# =============================================================================
# Esegue la sequenza raccomandata dopo deployment:
#   1. Audit pre-go-live (valida sintassi migration + .env allineamento)
#   2. SMOKE_TEST.sh contro URL produzione
#   3. Cattura output in evidence/SMOKE_TEST_OUTPUT.txt per chain-of-custody
#
# PREREQUISITI (esegui PRIMA di lanciare questo script):
#   - migration 002 applicata via Supabase SQL Editor (vedi VERIFY_RLS.md §1)
#   - .env.production.example compilato e salvato come .env (vedi GO_LIVE_RUNBOOK §3)
#   - reverse proxy (Caddyfile o nginx.conf) deployato con IP allowlist
#
# Usage:
#   chmod +x deployment/RUN_OPERATIONS.sh
#   ./deployment/RUN_OPERATIONS.sh https://api.spesemed.it
#
# Exit code:
#   0 = tutto OK
#   1 = audit fallito
#   2 = smoke test fallito
#   3 = dipendenze mancanti (jq, curl, python)
# =============================================================================
set -euo pipefail

API_BASE="${1:-}"
OUTPUT_DIR="evidence"
OUTPUT_FILE="$OUTPUT_DIR/SMOKE_TEST_OUTPUT.txt"

echo "==========================================="
echo "SPESEMED Production Operations Runner"
echo "API_BASE: ${API_BASE:-<not provided>}"
echo "OUTPUT:   $OUTPUT_FILE"
echo "==========================================="
echo ""

# --- Pre-flight dep check --------------------------------------------------------
echo "[0/4] Verifica dipendenze..."
for cmd in curl python jq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "FAIL: '$cmd' non installato."
        case "$cmd" in
            jq)   echo "  Install:   brew install jq (macOS) | apt install jq (Debian/Ubuntu) | choco install jq (Windows)" ;;
            curl) echo "  Install:   https://curl.se" ;;
            python) echo "  Install:  https://python.org" ;;
        esac
        exit 3
    fi
done
echo "OK (curl + python + jq presenti)"
echo ""

# --- Step 1: Audit pre-go-live ----------------------------------------------------
echo "[1/4] Audit pre-go-live (migrations + .env allineamento)..."
if ! python tests/audit_pre_go_live.py 2>&1 | tee "$OUTPUT_DIR/AUDIT_OUTPUT.txt"; then
    echo ""
    echo "FAIL: audit pre-go-live ha rilevato problemi."
    echo "Vedi $OUTPUT_DIR/AUDIT_OUTPUT.txt per dettagli."
    exit 1
fi
echo ""

# --- Step 2: Pre-flight SMOKE_TEST.sh ----------------------------------------------
if [ -z "$API_BASE" ]; then
    echo "[2/4] SKIP: API_BASE non specificata. Usage: $0 https://api.tuodominio.it"
    echo ""
    API_BASE=""
fi

# --- Step 3: SMOKE_TEST.sh ---------------------------------------------------------
if [ -n "$API_BASE" ]; then
    echo "[3/4] Esecuzione SMOKE_TEST.sh contro $API_BASE..."
    echo ""
    mkdir -p "$OUTPUT_DIR"
    if ./deployment/SMOKE_TEST.sh "$API_BASE" 2>&1 | tee "$OUTPUT_FILE"; then
        echo ""
        echo "OK: smoke test PASS. Output salvato in $OUTPUT_FILE."
    else
        EXIT_CODE=$?
        echo ""
        echo "FAIL: smoke test fallito con exit code $EXIT_CODE."
        echo "Vedi $OUTPUT_FILE per dettagli."
        exit 2
    fi
    echo ""
else
    echo "[3/4] SKIP: SMOKE_TEST.sh non eseguito (manca API_BASE)."
    echo "Esegui manualmente: ./deployment/SMOKE_TEST.sh https://api.tuodominio.it"
    echo ""
fi

# --- Step 4: post-verifica -------------------------------------------------------
echo "[4/4] Post-verifica checklist..."

# Genera metadata.json con SHA256 output SMOKE_TEST se esiste.
if [ -f "$OUTPUT_FILE" ]; then
    SMOKE_SHA=$(sha256sum "$OUTPUT_FILE" | cut -d' ' -f1)
    echo "  - SMOKE_TEST_OUTPUT.txt sha256: $SMOKE_SHA"
    echo "    (aggiungi questo valore a evidence/metadata.json: smoke_output_sha256)"
fi

if [ -f migration ] || [ -d migrations ]; then
    MIGRATION_SHA=$(sha256sum migrations/002_rls_policies.sql | cut -d' ' -f1)
    echo "  - migration 002 sha256:        $MIGRATION_SHA"
fi

GIT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "<not-a-git-repo>")
echo "  - git commit:                   $GIT_SHA"
echo "    (aggiungi a evidence/metadata.json: git_commit)"

echo ""
echo "==========================================="
echo "Operazioni completate."
echo ""
echo "NEXT STEPS manuali nel tuo browser:"
echo "  1. Apri deployment/VERIFY_RLS.md ed esegui §0-§10 step-by-step su Supabase."
echo "  2. Cattura 8 screenshot in evidence/ + popola evidence/metadata.json."
echo "  3. Bundle: tar -czf evidence_$(date -u +%Y%m%d_%H%M%S).tgz evidence/"
echo "  4. Consegna al pen-tester insieme a SECURITY.md."
echo "==========================================="

#!/usr/bin/env bash
# =============================================================================
# SPESEMED - Generate Production Secrets
# =============================================================================
# Genera 4 secrets URL-safe (32+ chars base64url):
#   1. ADMIN_TOKEN (per endpoint /admin/auth/reset-jwks-cache)
#   2-4. Token di rotazione (usa in ordine se ADMIN_TOKEN viene compromesso)
#
# Output: stampa su stdout + scrive in deployment/SECRETS_BUNDLE.txt
#         chmod 600 (owner read/write only).
#
# Usage:
#   chmod +x deployment/GENERATE_SECRETS.sh
#   ./deployment/GENERATE_SECRETS.sh
#
# SECURITY:
#   - NON eseguire in CI/CD con output visibile nei logs (usa secrets manager).
#   - NON includere output in git commit message.
#   - Copia il valore ADMIN_TOKEN in vault/secrets manager SUBITO.
#   - Cancella SECRETS_BUNDLE.txt dopo averlo trasferito al vault.
# =============================================================================
set -euo pipefail

OUTFILE="deployment/SECRETS_BUNDLE.txt"
echo "===========================================" >&2
echo "SPESEMED - Production Secrets Generator" >&2
echo "===========================================" >&2
echo "" >&2

# Genera 4 token (32 bytes = 43 chars base64url dopo encoding).
TOKEN1=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
TOKEN2=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
TOKEN3=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
TOKEN4=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

NOW_UTC=$(python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")

# Scrivi su file con permessi stretti (owner read/write only).
cat > "$OUTFILE" <<EOF
# SPESEMED - Production Secrets Bundle
# Generated: $NOW_UTC
# Treat as CONFIDENTIAL. Delete after transferring to secrets manager.

ADMIN_TOKEN=$TOKEN1
ROTATION_TOKEN_1=$TOKEN2
ROTATION_TOKEN_2=$TOKEN3
ROTATION_TOKEN_3=$TOKEN4
EOF
chmod 600 "$OUTFILE"

echo "OK: secrets generati e salvati in $OUTFILE (chmod 600)" >&2
echo "" >&2
echo "===========================================" >&2
echo "ADMIN_TOKEN (CURRENT):" >&2
echo "$TOKEN1" >&2
echo "===========================================" >&2
echo "" >&2
echo "Copia ADMIN_TOKEN nel tuo secrets manager (vault, AWS Secrets Manager," >&2
echo "HashiCorp Vault, ecc.) e imposta come env var ADMIN_TOKEN su produzione." >&2
echo "" >&2
echo "Per cancellare il file bundle dopo il trasferimento:" >&2
echo "  shred -u $OUTFILE         # Linux" >&2
echo "  rm -P $OUTFILE             # macOS (3-pass overwrite)" >&2
echo "  Remove-Item $OUTFILE -Force # Windows PowerShell" >&2

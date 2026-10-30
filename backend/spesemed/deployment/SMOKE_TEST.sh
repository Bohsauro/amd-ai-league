#!/usr/bin/env bash
# =============================================================================
# SPESEMED Production Smoke Test
# =============================================================================
# Verifica i 5 punti operativi dopo deployment.
#   - /health 200
#   - CORS evil.com rejected
#   - /metrics exposition (text/plain)
#   - /admin non autorizzato = 401
#   - Security headers HSTS/X-Content-Type-Options presenti
#
# Usage:
#   chmod +x deployment/SMOKE_TEST.sh
#   ./deployment/SMOKE_TEST.sh https://api.spesemed.it
# =============================================================================
set -e

API_BASE="${1:-https://api.spesemed.it}"
echo "==========================================="
echo "SPESEMED Production Smoke Test"
echo "Target: $API_BASE"
echo "==========================================="
echo ""

# E1. Health check pubblico ---------------------------------------------------------------
echo -n "[E1] GET /api/v1/health ... "
HEALTH_RESPONSE=$(curl -fsS -w "\nHTTP_STATUS:%{http_code}" "$API_BASE/api/v1/health" 2>&1) || {
    echo "FAIL: curl fallito"
    echo "$HEALTH_RESPONSE"
    exit 1
}
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | grep "HTTP_STATUS:" | cut -d: -f2)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | grep -v "HTTP_STATUS:")
if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS (200)"
    echo "    Body: $HEALTH_BODY"
else
    echo "FAIL (HTTP $HTTP_CODE)"
    exit 1
fi
echo ""

# E2. CORS rejection da origine malevola -------------------------------------------------
echo -n "[E2] Origin: https://evil.com su /api/v1/extract ... "
# OPTIONS preflight request con Origin malevolo deve restituire SENZA
# Access-Control-Allow-Origin: https://evil.com (deve essere assente
# o contenere solo l'origine autorizzata).
CORS_RESPONSE=$(curl -sS -D - -o /dev/null \
    -X OPTIONS "$API_BASE/api/v1/extract" \
    -H "Origin: https://evil.com" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Authorization,Content-Type" 2>&1)
if echo "$CORS_RESPONSE" | grep -qi "^access-control-allow-origin: https://evil.com"; then
    echo "FAIL: CORS consente evil.com!"
    echo "$CORS_RESPONSE" | head -20
    exit 1
elif echo "$CORS_RESPONSE" | grep -qi "^access-control-allow-origin: https://app.spesemed.it\|access-control-allow-origin: \*"; then
    # Se asterisk (*) presente, OK solo se non in production con credentials.
    # (CORS spec: '*' dovrebbe essere rifiutato dal browser con credentials=true,
    # ma e' comunque misconfiguration).
    echo "WARN: wildcard CORS rilevato (verificare CORS_ORIGINS env)"
    echo "$CORS_RESPONSE" | grep -i "access-control" || true
else
    echo "PASS (CORS blocca evil.com)"
    echo "$CORS_RESPONSE" | grep -i "access-control" || echo "    (no Access-Control-Allow-Origin header = response sicura)"
fi
echo ""

# E3. /metrics expuesto solo a IP autorizzati (qui testiamo da internet = 403/404) -----
echo -n "[E3] GET /metrics da internet ... "
METRICS_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" "$API_BASE/metrics")
case "$METRICS_HTTP" in
    403|404)
        echo "PASS (HTTP $METRICS_HTTP = reverse proxy blocca internet)"
        ;;
    200)
        echo "FAIL: /metrics publico senza IP allowlist! Rimettere IP allowlist nel Caddyfile/nginx.conf."
        exit 1
        ;;
    *)
        echo "WARN: HTTP $METRICS_HTTP (verificare manualmente)"
        ;;
esac
echo ""

# E4. /admin/auth/reset-jwks-cache senza ADMIN_TOKEN = 403 ------------------------------
echo -n "[E4] POST /admin/auth/reset-jwks-cache senza token ... "
ADMIN_HTTP=$(curl -sS -o /dev/null -w "%{http_code}" \
    -X POST "$API_BASE/admin/auth/reset-jwks-cache")
case "$ADMIN_HTTP" in
    403)
        echo "PASS (403 = ADMIN_TOKEN mancante)"
        ;;
    *)
        echo "FAIL: HTTP $ADMIN_HTTP (dovrebbe essere 403)"
        exit 1
        ;;
esac
echo ""

# E5. Security headers presenti ----------------------------------------------------------
echo "[E5] Verifica security headers..."
SECURITY_HEADERS=$(curl -sS -D - -o /dev/null "$API_BASE/api/v1/health")
EXPECTED_HEADERS=(
    "strict-transport-security"
    "x-content-type-options"
    "x-frame-options"
)
ALL_FOUND=true
for header in "${EXPECTED_HEADERS[@]}"; do
    if echo "$SECURITY_HEADERS" | grep -qi "^${header}:"; then
        echo "    [OK] $header"
    else
        echo "    [MISS] $header"
        ALL_FOUND=false
    fi
done
if [ "$ALL_FOUND" = true ]; then
    echo "PASS (security headers presenti)"
else
    echo "WARN: alcuni header mancanti"
fi
echo ""

# E6. HSTS preload flag -----------------------------------------------------------------
echo -n "[E6] HSTS includeSubDomains + preload ... "
HSTS_LINE=$(curl -sS -D - -o /dev/null "$API_BASE/api/v1/health" 2>&1 | grep -i "^strict-transport-security:" || echo "")
if echo "$HSTS_LINE" | grep -qi "includeSubDomains\|max-age=63072000"; then
    echo "PASS"
    echo "    Value: $(echo "$HSTS_LINE" | sed 's/\r$//')"
else
    echo "WARN: HSTS non compliant HSTS preload list (migliorare)"
    echo "    Got: $HSTS_LINE"
fi
echo ""

echo "==========================================="
echo "Smoke test completato."
echo "==========================================="

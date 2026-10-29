# SPESEMED — Piano implementativo Fase 4C (Redis, Prometheus, Stripe)

> Issue: BOH-13 · Autore: agent-po · Data: ott 2026
> Esegue: agent-core-dev (backend) + agent-ui-ux (solo task 4C-C9 frontend)
> Prerequisito: leggere `01-gap-analysis.md` (stessa cartella) per i dettagli.
> Regola ferrea: test offline con mock, MAI secrets reali nel workspace.
> Alla fine: `python -m pytest -q` in `backend/spesemed/` deve restare **verde**
> (oggi 141/141 — misura riproducibile: `141 passed` nell'ultima riga di pytest)
> e il backend live :8000 NON va mai toccato.

---

## Goal

Chiudere la Fase 4C: (a) rate-limit Redis condiviso multi-worker verificato,
(b) metriche Prometheus HTTP application-level, (c) billing Stripe con kill-switch
`BILLING_ENABLED=false` che non altera il comportamento attuale, (d) script E2E
pronto per l'esecuzione del proprietario.

## Architettura

- **Redis**: già dockerizzato; si aggiungono test automatici del path `redis://`,
  readiness check in lifespan e (opzionale) campi /health. Nessun cambio di storage
  per default.
- **Prometheus**: middleware HTTP leggero in `main.py` + metriche bounded
  (method+status) in `metrics_http.py`; niente label path/user (cardinality).
- **Stripe**: wrapper DI-friendly `billing_client.py` (pattern = `supabase_client.py`),
  migration `004_billing.sql`, 3 route (`/billing/checkout`, `/billing/webhook`,
  `/billing/status`), gating 402 su `/extract`, tutto dietro `BILLING_ENABLED`.

## Tech stack

FastAPI · slowapi/limits (redis) · prometheus-client · stripe (nuova) ·
supabase-py · pytest (mock) · docker compose (redis reale, solo task manuale A3).

---

# Task 4C-A — Redis rate-limit storage (verifica + readiness)

## Task 4C-A1: Unit test del path Redis per `_build_storage_uri`

**Obiettivo:** provare che la configurazione Redis venga tradotta in storage URI corretto.

**Files:**
- Create: `backend/spesemed/tests/test_rate_limit.py`
- Read-only: `backend/spesemed/src/spesemed/api/rate_limit.py:33-101`

**Step 1 — scrivere i test:**

```python
"""SPESEMED - Test rate-limit storage URI resolution (Fase 4C)."""
from spesemed.api.rate_limit import _build_storage_uri


def test_memory_backend_default(monkeypatch):
    monkeypatch.setattr("spesemed.api.rate_limit.settings.rate_limit_storage_backend", "memory")
    assert _build_storage_uri() == "memory://"


def test_redis_backend_uses_redis_url(monkeypatch):
    monkeypatch.setattr("spesemed.api.rate_limit.settings.rate_limit_storage_backend", "redis")
    monkeypatch.setattr("spesemed.api.rate_limit.settings.redis_url", "redis://redis:6379/0")
    assert _build_storage_uri() == "redis://redis:6379/0"


def test_redis_uri_passthrough(monkeypatch):
    monkeypatch.setattr("spesemed.api.rate_limit.settings.rate_limit_storage_backend", "redis://redis:6379/0")
    assert _build_storage_uri() == "redis://redis:6379/0"


def test_redis_uri_password_redacted(monkeypatch):
    uri = "redis://:s3cret@redis:6379/0"
    monkeypatch.setattr("spesemed.api.rate_limit.settings.rate_limit_storage_backend", uri)
    result = _build_storage_uri()
    assert "s3cret" not in result
    assert ":***@" in result
```

**Step 2 — eseguire e verificare FAIL prima della fix** (se `_build_storage_uri`
non gestisce già `"redis"` come alias): `pytest tests/test_rate_limit.py -v`
→ atteso: i test falliscono o passano per il passthrough già esistente.

**Step 3 — implementare/adattare** `_build_storage_uri` in `rate_limit.py`
per gestire `backend == "redis"` → `redis_url`; se `redis_url` vuoto →
`logger.error(...)` e fallback `memory://` (mai crashare al boot).

**Step 4 — eseguire verifica:** `pytest tests/test_rate_limit.py -v` → 4 passed.

**Criterio di accettazione:** 4 test verdi; nessuna modifica al comportamento
con default `memory`.

---

## Task 4C-A2: Readiness check Redis in lifespan

**Obiettivo:** se `RATE_LIMIT_STORAGE_BACKEND=redis` è configurato ma Redis è
irraggiungibile, l'app deve loggare un errore chiaro AL BOOT (non 500 randomici
al primo 429).

**Files:**
- Modify: `backend/spesemed/src/spesemed/api/main.py` (lifespan, dopo `_warn_if_multi_worker_memory_rate_limit()` ~riga 210)
- Create: `backend/spesemed/tests/test_rate_limit_redis_readiness.py` (o estendere `test_rate_limit.py`)

**Step 1 — test:**

```python
def test_redis_backend_reports_error_when_unreachable(monkeypatch, caplog):
    import logging
    from spesemed.api.main import _check_redis_readiness
    monkeypatch.setattr("spesemed.api.main.settings.rate_limit_storage_backend", "redis")
    monkeypatch.setattr("spesemed.api.main.settings.redis_url", "redis://localhost:6399/0")  # porta chiusa
    with caplog.at_level(logging.ERROR, logger="spesemed.api"):
        ok = _check_redis_readiness()
    assert ok is False
    assert any("Redis" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)
```

**Step 2 — implementare:**

```python
def _check_redis_readiness() -> bool:
    """Ping Redis se configurato come storage rate-limit. True = ok / non richiesto."""
    backend = settings.rate_limit_storage_backend.strip()
    if backend in ("", "memory"):
        logger.debug("Redis readiness: storage memory, skip")
        return True
    url = settings.redis_url if backend == "redis" else backend
    try:
        import redis as redis_lib
        client = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        logger.info("Redis readiness OK (%s)", url.split("@")[-1])
        return True
    except Exception as e:
        logger.error("Redis NON raggiungibile (%s): %s. Rate-limit multi-worker non garantito.", url.split("@")[-1], e)
        return False
```

Chiamarla nel lifespan e loggare il risultato (WARNING/ERROR); NON crashare il boot
(decisione di resilienza: l'app parte, ma i limiti possono degradare — il log è
esplicito e SMOKE_TEST può alertare).

**Step 3 — verifica:** `pytest tests/test_rate_limit_redis_readiness.py -v` → pass.
Poi `python -m pytest -q` completo → 141+ verdi (il gate è "nessun test rotto";
il numero è la misura attuale, verificarla con l'ultima riga di pytest).

**Criterio di accettazione:** boot con Redis down → ERROR nei log entro 5s; boot
con memory → nessun log Redis; test offline verdi senza Redis.

---

## Task 4C-A3 (manuale, proprietario): verifica con docker compose

**Obiettivo:** provare la catena reale (non mock) una tantum.

**Files:** nessuno — comandi da eseguire da `backend/spesemed/` con `.env` locale.

**Step 1 — avviare lo stack dev con Redis:**

```bash
cd backend/spesemed
docker compose up -d --build
# atteso: redis healthy + api healthy; log api contiene "Redis readiness OK"
docker compose logs api | grep -i redis
```

**Step 2 — verificare rate-limit condiviso (2 worker):**

```bash
# in .env: API_WORKERS=2, RATE_LIMIT_STORAGE_BACKEND=redis, REDIS_URL=redis://redis:6379/0
docker compose restart api
for i in $(seq 1 7); do
  curl -sS -o /dev/null -w "[$i] HTTP %{http_code}\n" -X POST \
    http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"a@b.c","password":"validpass1"}'
done
# atteso: 5x 401/200 poi 429 dal 6° (limite condiviso tra worker, NON 10)
```

**Step 3 — spegnere:** `docker compose down` (preserva volume redis-data).

**Criterio di accettazione:** 429 arriva esattamente dopo 5 richieste con
API_WORKERS=2 (senza Redis sarebbe 10) — evidenza che lo storage è condiviso.

---

# Task 4C-B — Prometheus metriche HTTP

## Task 4C-B1: Modulo `api/metrics_http.py`

**Obiettivo:** definire Counter + Histogram con label bounded (method, status).

**Files:**
- Create: `backend/spesemed/src/spesemed/api/metrics_http.py`

**Step 1 — test:**

```python
def test_http_metrics_labels_bounded():
    from spesemed.api.metrics_http import http_requests_total, http_request_duration_seconds
    http_requests_total.labels(method="GET", status="200").inc()
    assert http_requests_total.labels(method="GET", status="200")._value.get() == 1.0
    # status come stringa (3 cifre) per cardinality bassa e label stabile
```

**Step 2 — implementare:**

```python
"""SPESEMED API - Metriche HTTP Prometheus (Fase 4C).

DESIGN CARDINALITA':
  Label SOLO method (bounded: GET/POST/PUT/DELETE/PATCH/OPTIONS/HEAD) e status
  (3 cifre come stringa). NIENTE path/user per evitare OOM Prometheus.
"""
from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "spesemed_http_requests_total",
    "Richieste HTTP totali per method e status code.",
    labelnames=("method", "status"),
)
http_request_duration_seconds = Histogram(
    "spesemed_http_request_duration_seconds",
    "Latenza delle richieste HTTP in secondi per method (buckets 10ms..10s).",
    labelnames=("method",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
```

**Step 3 — verifica:** `pytest tests/test_metrics_http.py -v` (nuovo file test) → pass.

**Criterio di accettazione:** moduli importabili, label corrette, cardinalità
documentata nel docstring.

---

## Task 4C-B2: Middleware HTTP in `main.py`

**Obiettivo:** registrare `http_requests_total` e `http_request_duration_seconds`
su ogni richiesta; escludere `/metrics` dalla duration (self-scrape noise).

**Files:**
- Modify: `backend/spesemed/src/spesemed/api/main.py` (dopo CORS/SlowAPI middleware, ~riga 277)

**Step 1 — test** (in `tests/test_metrics_http.py`):

```python
def test_health_hit_increments_http_metrics(monkeypatch):
    from spesemed.api.main import app
    from spesemed.api.metrics_http import http_requests_total
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        client.get("/api/v1/health")
    assert http_requests_total.labels(method="GET", status="200")._value.get() >= 1.0


def test_not_found_increments_404(monkeypatch):
    from spesemed.api.main import app
    from spesemed.api.metrics_http import http_requests_total
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert http_requests_total.labels(method="GET", status="404")._value.get() >= 1.0
```

**Step 2 — implementare:**

```python
from .metrics_http import http_requests_total, http_request_duration_seconds

@app.middleware("http")
async def http_metrics_middleware(request: Request, call_next):
    import time
    start = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        status_label = str(response.status_code) if "response" in locals() else "500"
        method = request.method.upper() if request.method else "UNKNOWN"
        http_requests_total.labels(method=method, status=status_label).inc()
        if request.url.path != "/metrics":
            http_request_duration_seconds.labels(method=method).observe(time.perf_counter() - start)
```

(Nota: in un `finally` con `call_next` async, la variabile `response` va gestita
con cura; l'implementatore userà un pattern try/except/finally con `response`
inizializzato a None ed eccezioni che mappano a "500".)

**Step 3 — verifica:** `pytest tests/test_metrics_http.py -v` → pass; poi
`pytest tests/test_metrics.py -v` → regressioni ACL/metrics verdi; poi `pytest` completo.

**Criterio di accettazione:** ogni richiesta incrementa il counter; risposte 4xx/5xx
registrate correttamente; /metrics escluso dalla duration; nessuna label path.

---

## Task 4C-B3: Sample config Prometheus + doc

**Obiettivo:** dare all'operatore un punto di partenza per lo scraper.

**Files:**
- Create: `backend/spesemed/deployment/prometheus.yml`

**Step 1 — creare:**

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: spesemed-api
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]   # nome servizio docker-compose
    # NB: aggiungere l'IP del runner all'allowlist in .env:
    # METRICS_IP_ALLOWLIST=["127.0.0.1","::1","<IP_PROMETHEUS>"]
```

**Step 2 — verificare la sintassi** con `promtool check config deployment/prometheus.yml`
(se disponibile; altrimenti verifica visiva).

**Criterio di accettazione:** file presente; istruzioni per l'allowlist nel commento.

---

# Task 4C-C — Stripe billing

> Tutti i task offline con mock: `monkeypatch` di `stripe.*` e
> `supabase_client.*` (stesso pattern DI di `tests/conftest.py`).
> `BILLING_ENABLED` default `false` → nessun cambio comportamento esistente.

## Task 4C-C1: Dipendenza + env + config

**Files:**
- Modify: `backend/spesemed/pyproject.toml` + `backend/spesemed/requirements.txt` (aggiungere `stripe>=9.0.0,<11.0.0`)
- Modify: `backend/spesemed/src/spesemed/api/config.py` (nuovi campi Settings)
- Modify: `specs/spesemed/.env.example` (sezione Billing)

**Step 1 — test config:**

```python
def test_billing_settings_defaults():
    from spesemed.api.config import settings
    assert settings.billing_enabled is False
    assert settings.stripe_secret_key == ""
    assert settings.stripe_webhook_secret == ""
    assert settings.stripe_price_id == ""
    assert settings.stripe_currency == "eur"
    assert settings.billing_extractions_limit == 100
```

**Step 2 — implementare i campi:**

```python
    # =====================================================================
    # Billing (Fase 4C Stripe) — kill switch: default OFF (nessun cambio)
    # =====================================================================
    billing_enabled: bool = Field(
        default=False,
        description="Abilita Stripe billing e gating su /extract. Default False (nessun cambio comportamento).",
    )
    stripe_secret_key: str = Field(default="", description="Chiave segreta Stripe (sk_test_/sk_live_). Mai loggare.")
    stripe_webhook_secret: str = Field(default="", description="Webhook signing secret (whsec_...).")
    stripe_price_id: str = Field(default="", description="Price ID del piano Pro (price_...).")
    stripe_currency: str = Field(default="eur", description="Valuta per Checkout (default eur).")
    stripe_mode: str = Field(default="test", description="test|live — per log/etichette.")
    billing_extractions_limit: int = Field(default=100, ge=1, le=100000, description="Estrazioni mensili incluse nel piano Pro.")
    billing_success_url: str = Field(default="", description="Redirect post-checkout. Vuoto = da APP_URL.")
    billing_cancel_url: str = Field(default="", description="Redirect se annulla. Vuoto = da APP_URL.")
```

**Step 3 — WARNING startup** in `main.py` (dentro lifespan): se `billing_enabled`
e (`stripe_secret_key` o `stripe_webhook_secret` o `stripe_price_id` vuoti) →
`logger.error` chiaro.

**Step 4 — verifica:** `pytest tests/test_billing.py -v` (nuovo file) → pass.

**Criterio di accettazione:** default OFF; test verdi; `.env.example` documentata;
WARNING startup se config incompleta.

---

## Task 4C-C2: Migration `004_billing.sql`

**Files:**
- Create: `backend/spesemed/migrations/004_billing.sql` (SQL completo in `01-gap-analysis.md` §3.3 GAP-3.2)

**Step 1 — test syntax** (estensione di `tests/audit_pre_go_live.py` o tool `psql --dry-run`
non disponibile offline): riusare il pattern dell'audit esistente (parens bilanciati,
parole chiave) per `004_billing.sql`; almeno verificare `IF NOT EXISTS` e policy RLS presenti.

**Step 2 — applicazione a Supabase** = azione del proprietario tramite SQL Editor
(non dal workspace; nessun comando qui).

**Criterio di accettazione:** migration idempotente; RLS service_role-only su
entrambe le tabelle; audit script esteso passa.

---

## Task 4C-C3: Wrapper `api/billing_client.py`

**Files:**
- Create: `backend/spesemed/src/spesemed/api/billing_client.py`

**Step 1 — test** (in `tests/test_billing.py`): mockare `stripe.checkout.Session.create`
e `stripe.Webhook.construct_event` con `monkeypatch`; verificare:
- `is_billing_configured()` False senza chiavi, True con chiavi,
- `create_checkout_session(...)` passa `client_reference_id=user_id` e `metadata` e ritorna `{checkout_url, session_id}`,
- `parse_webhook_event(payload, sig)` invalida → solleva (e la route mappa a 400),
- `map_event_to_entitlement(checkout.session.completed)` produce dict di upsert corretto.

**Step 2 — implementare** (schema, firmato con `stripe`):

```python
"""SPESEMED API - Wrapper Stripe DI-friendly (Fase 4C).

Pattern: identico a supabase_client.py — import modulare per monkeypatch pulito.
Mai loggare chiavi o payload webhook interi (PII)."""
from __future__ import annotations
import logging
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)


def is_billing_configured() -> bool:
    return bool(
        settings.billing_enabled
        and settings.stripe_secret_key
        and settings.stripe_webhook_secret
        and settings.stripe_price_id
    )


def create_checkout_session(user_id: str, email: str) -> dict:
    import stripe
    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=email,
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        client_reference_id=user_id,
        metadata={"user_id": user_id},
        success_url=settings.billing_success_url or f"{settings.app_url}/app/profilo?billing=success",
        cancel_url=settings.billing_cancel_url or f"{settings.app_url}/app/profilo?billing=cancel",
    )
    return {"checkout_url": session.url, "session_id": session.id}


def parse_webhook_event(payload: bytes, sig_header: str):
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def map_event_to_entitlement(event) -> Optional[dict]:
    """Traduce un evento Stripe in riga di upsert `entitlements` (o None se ignorato)."""
    etype = event.get("type") if hasattr(event, "get") else event.type if hasattr(event, "type") else None
    data = event["data"]["object"] if isinstance(event, dict) else event.data.object
    user_id = (data.get("client_reference_id") or (data.get("metadata") or {}).get("user_id"))
    if not user_id:
        return None
    if etype == "checkout.session.completed":
        return {
            "user_id": user_id,
            "plan": "pro",
            "status": "trialing" if data.get("subscription_status") == "trialing" else "active",
            "current_period_start": now_iso(), "current_period_end": later_iso(),
            "extractions_limit": settings.billing_extractions_limit,
            "extractions_used": 0,
            "stripe_customer_id": data.get("customer"),
            "stripe_subscription_id": data.get("subscription"),
        }
    if etype == "customer.subscription.updated":
        status = data.get("status", "active")
        if status in ("active", "trialing", "past_due"):
            return {..., "status": status, "current_period_end": period_end(data)}
        if status in ("canceled", "unpaid", "incomplete_expired"):
            return {..., "status": "none", "extractions_limit": 0}
    if etype == "invoice.paid":
        return {..., "extractions_used": 0, "current_period_end": period_end(data)}
    return None


def upsert_entitlement(client, mapping: dict) -> None:
    client.table("entitlements").upsert(mapping, on_conflict="user_id").execute()
```

(Il codice completo con helper `now_iso`/`period_end` è a cura dell'implementatore;
qui lo schema contrattuale e i campi chiave.)

**Step 3 — verifica:** `pytest tests/test_billing.py -v` → pass (nessuna chiamata
di rete reale: tutto monkeypatch).

**Criterio di accettazione:** wrapper mockabile; nessun secret loggato;
`is_billing_configured()` coerente col kill switch.

---

## Task 4C-C4: Route `POST /api/v1/billing/checkout`

**Files:**
- Create: `backend/spesemed/src/spesemed/api/routes/billing.py` (router con le 3 route billing)
- Modify: `backend/spesemed/src/spesemed/api/main.py` (`include_router(billing.router, prefix="/api/v1")`)
- Modify: `backend/spesemed/src/spesemed/api/schemas.py` (CheckoutResponse, BillingStatusResponse)

**Step 1 — test:**

```python
def test_checkout_requires_auth(monkeypatch):
    # senza Bearer/X-User-Id dev → 401
def test_checkout_disabled_returns_503(monkeypatch):
    # billing_enabled=False → 503
def test_checkout_returns_url(monkeypatch, mock_supabase):
    # billing_enabled=True + mock stripe.create_checkout_session → 200 {checkout_url, session_id, mode}
```

**Step 2 — schema:**

```python
class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    mode: str = "test"
```

**Step 3 — route:**

```python
@router.post("/billing/checkout", response_model=CheckoutResponse, status_code=200)
@limiter.limit("10/minute")
async def billing_checkout(
    response: Response, request: Request, user_id: str = Depends(get_current_user),
):
    if not billing_client.is_billing_configured():
        raise HTTPException(503, detail="Billing non configurato sul server.")
    # email: leggere dall'utente Supabase (client.auth.get_user) o campo opzionale in body
    ...
    return CheckoutResponse(checkout_url=..., session_id=..., mode=settings.stripe_mode)
```

**Step 4 — verifica:** `pytest tests/test_billing.py -v` → pass; `pytest` completo verde.

**Criterio di accettazione:** 503 se kill switch off; 401 senza auth; 200 con URL
di checkout; nessun redirect controllato dal client.

---

## Task 4C-C5: Route `POST /api/v1/billing/webhook`

**Files:**
- Modify: `backend/spesemed/src/spesemed/api/routes/billing.py`

**Step 1 — test** (mock `supabase_client` + firma locale):

```python
def test_webhook_invalid_signature_400(monkeypatch):
    # construct_event solleva → 400, nessun upsert
def test_webhook_valid_event_200_and_upsert(monkeypatch, mock_supabase):
    # build evento dict checkout.session.completed, monkeypatch parse_webhook_event → evento
    # → 200, entitlements.upsert chiamato con on_conflict user_id
def test_webhook_replay_idempotent(monkeypatch, mock_supabase):
    # stripe_events contiene già event_id → 200 senza secondo upsert
```

**Step 2 — implementare:**

```python
@router.post("/billing/webhook", status_code=200)
@limiter.limit("60/minute")
async def billing_webhook(request: Request, response: Response):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not billing_client.is_billing_configured():
        raise HTTPException(503, detail="Billing non configurato.")
    try:
        event = billing_client.parse_webhook_event(payload, sig)
    except Exception:
        logger.warning("Webhook firma invalida")
        raise HTTPException(400, detail="Firma webhook non valida.")
    # Idempotenza: INSERT ON CONFLICT DO NOTHING su stripe_events
    client = supabase_client.get_supabase_client()
    inserted = client.table("stripe_events").upsert(
        {"event_id": event.id, "type": event.type}, on_conflict="event_id"
    ).execute()
    if gia_processato: return {"status": "ok", "replayed": True}
    mapping = billing_client.map_event_to_entitlement(event)
    if mapping:
        billing_client.upsert_entitlement(client, mapping)
    return {"status": "ok", "type": event.type}
```

**Step 3 — verifica:** 3 test verdi; `pytest` completo.

**Criterio di accettazione:** firma invalida → 400 fail-closed; replay → 200 senza
doppio upsert; eventi fuori scope ignorati (200); evento valido aggiorna
`entitlements`; mai log del payload.

---

## Task 4C-C6: Route `GET /api/v1/billing/status`

**Files:**
- Modify: `backend/spesemed/src/spesemed/api/routes/billing.py`, `schemas.py`

**Step 1 — test:**

```python
def test_billing_status_disabled(monkeypatch):
    # billing_enabled=False → 200 {"billing_enabled": False}
def test_billing_status_active(monkeypatch, mock_supabase):
    # entitlements row attiva → 200 con plan/status/period_end/usage
def test_billing_status_no_row(monkeypatch, mock_supabase):
    # nessuna row → 200 free/limit 0
```

**Step 2 — schema + route:**

```python
class BillingStatusResponse(BaseModel):
    billing_enabled: bool = False
    plan: str = "free"
    status: str = "none"
    period_end: Optional[str] = None
    extractions_limit: int = 0
    extractions_used: int = 0
```

**Step 3 — verifica:** test verdi; `pytest` completo.

**Criterio di accettazione:** mai 5xx; `billing_enabled=false` non rompe il client;
dati letti per `user_id` dal token.

> NOTA CONTRATTO: **non** esiste un endpoint pubblico `GET /api/v1/billing/plan`.
> L'unico contratto billing letto dal client è `GET /api/v1/billing/status` (auth).
> L'E2E (03-e2e-plan.md + script) usa `billing/status` — nessuna route extra.

---

## Task 4C-C7: Gating su `POST /api/v1/extract` (402)

**Files:**
- Modify: `backend/spesemed/src/spesemed/api/routes/extract.py` (dopo i check 503, ~riga 172)
- Modify: `backend/spesemed/src/spesemed/api/routes/../worker.py` (bump usage per job async, solo se fattibile in MVP)

**Step 1 — test** (in `tests/test_billing.py`):

```python
def test_extract_gated_402_when_billing_enabled_and_no_entitlement(monkeypatch, mock_supabase):
    # billing_enabled=True, entitlements query → [] → POST /extract (1 file finto) → 402 code=payment_required
def test_extract_not_gated_when_billing_disabled(monkeypatch, mock_supabase):
    # billing_enabled=False → comportamento attuale (senza OPENROUTER_API_KEY → 503, MAI 402)
def test_extract_ok_when_entitlement_active(monkeypatch, mock_supabase):
    # billing_enabled=True + entitlements attiva (limit 100, used 0) → passa al flusso estrattivo
```

**Step 2 — implementare** in `routes/extract.py`:

```python
async def _user_has_entitlement(user_id: str) -> bool:
    """True se billing disabilitato o utente con entitlement attivo e quota residua."""
    if not settings.billing_enabled:
        return True
    client = supabase_client.get_supabase_client()
    if client is None:
        return False
    rows = await asyncio.to_thread(
        lambda: client.table("entitlements")
        .select("*").eq("user_id", user_id).limit(1).execute()
    )
    row = (rows.data or [{}])[0]
    if not row or row.get("status") not in ("active", "trialing"):
        return False
    import datetime
    end = row.get("current_period_end")
    if end and end < datetime.datetime.now(datetime.timezone.utc).isoformat():
        return False
    return int(row.get("extractions_used", 0)) < int(row.get("extractions_limit", 0))
```

e nel handler `extract`, dopo il check Supabase:

```python
    if not await _user_has_entitlement(user_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Piano gratuito esaurito o abbonamento non attivo. Abbonati per continuare.",
        )
```

Bump usage su estrazione riuscita **solo se non cache hit**:

```python
    client.table("entitlements").update(
        {"extractions_used": existing + 1}
    ).eq("user_id", user_id).execute()
```

(oppure UPDATE atomico SQL `SET extractions_used = extractions_used + 1` via RPC —
l'implementatore sceglie il pattern più testabile; criterio: nessun double-count su
cache hit.)

**Step 3 — verifica:** 3 test nuovi verdi; tutti i test esistenti di extract/worker
verdi (default `billing_enabled=false` → nessuna regressione); `pytest` completo.

**Criterio di accettazione:** kill switch off = comportamento identico; kill switch
on = 402 per utenti senza quota; cache hit non consuma quota; 402 in formato
ErrorResponse.

---

## Task 4C-C8: Docs + README + runbook

**Files:**
- Modify: `specs/spesemed/PROJECT_STATUS.md` (Fase 4C → done quando i task verdi)
- Modify: `specs/spesemed/GO_LIVE_RUNBOOK.md` (sezione Stripe: creare price/dashboard,
  webhook endpoint, eventi da iscrivere; Redis: nota readiness)
- Modify: `specs/spesemed/.env.example` (sezione Billing già in C1; accordo finale)

**Criterio di accettazione:** chiunque può configurare billing seguendo il runbook
senza chiedere chiarimenti; `.env.example` e `config.py` allineati (audit pre-go-live).

---

## Task 4C-C9 (frontend, agent-ui-ux): Profilo piano + 402

**Files:**
- Modify: `frontend/spesemed/frontend-app/src/pages/app/ProfilePage.tsx` (sezione Piano)
- Modify: `frontend/spesemed/frontend-app/src/lib/api.ts` (`billingCheckout`, `billingStatus`)
- Modify: `frontend/spesemed/frontend-app/src/pages/app/UploadPage.tsx` (gestione 402)

**Requisiti (contratto):**
- `GET /api/v1/billing/status` → mostra piano/stato/uso;
- bottone "Abbonati" → `POST /billing/checkout` → `window.location = checkout_url`;
- su 402 da `/extract`: messaggio calmo in italiano + link al Profilo;
- nessuna chiave Stripe nel bundle; hit target ≥44px; microcopy "Verde Calma".

**Criterio di accettazione:** `npm run build` senza errori; nessun token/chiave
stampato; design tokens rispettati.

---

## Ordine e dipendenze

```
4C-A1 → 4C-A2 → (4C-A3 manuale proprietario, può essere parallelo)
4C-B1 → 4C-B2 → 4C-B3

4C-C1 → 4C-C2 → 4C-C3 → 4C-C4 ─┐
                └───→ 4C-C5 ────┼→ 4C-C7 → 4C-C8
                └───→ 4C-C6 ────┘
4C-C9 (frontend) può partire dopo 4C-C4+4C-C6 (contratto API stabile)
```

Dipendenze forti: C7 richiede C3 (wrapper) e C2 (tabella entitlements);
C5 richiede C3; C6 richiede C2+C3. A e B sono indipendenti e paralleli.

## Matrice test offline (nessun secret)

| Comando | Atteso |
|---|---|
| `cd backend/spesemed && python -m pytest tests/test_rate_limit.py -v` | 4 passed |
| `python -m pytest tests/test_rate_limit_redis_readiness.py -v` | 1 passed |
| `python -m pytest tests/test_metrics_http.py -v` | 3-5 passed |
| `python -m pytest tests/test_metrics.py -v` | 20 passed (no regressione) |
| `python -m pytest tests/test_billing.py -v` | ≥10 passed (mock stripe+supabase) |
| `python -m pytest` (intero) | ≥150 passed, 0 failed |
| `python -m compileall src tests` | nessun errore |

## Rischi residui e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Bump usage race su 2 worker | UPDATE atomico `extractions_used = extractions_used + 1`; test con run concorrenti (pytest-xdist opzionale) |
| Webhook Stripe mai ricevuto (network) | Checkout redirect con `?billing=success` + client che polla `/billing/status`; runbook consiglia retry manuale dall'event log Stripe |
| Stripe API version drift | Pin `stripe>=9,<11`; test con mock che riflettono lo schema attuale; aggiornare pin solo con test verdi |
| Rate-limit 429 sui test E2E ripetuti | Script E2E usa email random e rispetta `2/hour` signup (vedi 03-e2e-plan) |
| Backend live :8000 del proprietario | Nessun comando di scrittura/riavvio; i test girano offline o su docker-compose dev separato |
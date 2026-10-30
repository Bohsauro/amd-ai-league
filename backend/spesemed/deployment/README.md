# SPESEMED — Deployment e osservabilità

Questa cartella raccoglie i file operativi per il deploy del backend SPESEMED
(`Caddyfile`, `nginx.conf`, script di smoke test/rotazione secret, esempi env).

## Prometheus: esposizione di `/metrics` e scraping

### Cosa espone il backend

- Endpoint: `GET /metrics` (formato Prometheus exposition).
- Kill switch: `PROMETHEUS_METRICS_ENABLED=false` → `/metrics` risponde `404`.
- Metriche HTTP (Fase 4C):
  - `spesemed_http_requests_total{method,status_class}` — richieste per metodo e
    classe di status (`2xx`, `3xx`, `4xx`, `5xx`).
  - `spesemed_http_request_duration_seconds` — latenza delle richieste
    (Histogram, senza label).
- Metriche auth/JWT già esistenti (`spesemed_jwt_*`).

### Allowlist: chi può scrapare

`/metrics` è protetto su due livelli:

1. **Edge** — reverse proxy (`Caddyfile` / `nginx.conf`) con allowlist IP.
2. **Applicativo** — `METRICS_IP_ALLOWLIST` in `.env` (IP singoli o CIDR,
   IPv4/IPv6). Default: `["127.0.0.1","::1"]`.

Regole operative:

- Se Prometheus gira su un host/container diverso dall'API, aggiungere il suo
  IP o la subnet Docker (es. `172.18.0.0/16`) a `METRICS_IP_ALLOWLIST`.
- Con Prometheus nella stessa rete Docker Compose, l'API vede l'IP del
  container Prometheus: non basta `127.0.0.1`.
- Lista vuota + `API_ENV=production` → fail-closed (`403`). In sviluppo → fail-open.
- `METRICS_TRUST_XFF=true` solo se il peer TCP diretto (reverse proxy) è già
  in allowlist; altrimenti un header `X-Forwarded-For` spoofato aggirerebbe l'ACL.
- In produzione, con allowlist composta solo da loopback, il backend logga un
  `WARNING` all'avvio: significa che uno scraper remoto riceverà `403`.

Esempio `.env` (nessun secret in questo file):

```dotenv
PROMETHEUS_METRICS_ENABLED=true
METRICS_IP_ALLOWLIST=["127.0.0.1","::1","10.0.0.5"]
METRICS_TRUST_XFF=false
```

### Config di scraping

Il file `prometheus.yml` in questa cartella è un esempio pronto:

```yaml
scrape_configs:
  - job_name: spesemed-api
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
```

Il target `api:8000` funziona se Prometheus è nella stessa rete Docker Compose
del servizio `api`. Altrimenti usare `<host-api>:8000` oppure l'URL HTTPS del
reverse proxy (con `scheme: https`).

Esempio di servizio Prometheus da aggiungere al compose (stessa rete):

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.0.0
    volumes:
      - ./deployment/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    networks:
      - spesemed-net
```

### Verifica

```bash
# Sintassi della config (se promtool è installato)
promtool check config deployment/prometheus.yml

# Dalla rete/container autorizzato: deve tornare 200
curl -sS -o /dev/null -w '%{http_code}\n' http://api:8000/metrics

# Da un IP non in allowlist: deve tornare 403
curl -sS -o /dev/null -w '%{http_code}\n' http://api:8000/metrics
```

Poi controllare in Prometheus: **Status → Targets** deve mostrare
`spesemed-api` come `UP`. Se è `DOWN` con `403`, manca l'IP dello scraper in
`METRICS_IP_ALLOWLIST` (o nell'allowlist edge).

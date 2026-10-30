# =============================================================================
# SPESEMED API - Dockerfile (PRODUZIONE Fase 3)
# =============================================================================
# Build:    docker build -t spesemed-api:0.3.0 .
# Dev run:  docker compose up --build
# Prod run: docker compose -f docker-compose.prod.yml up -d
# =============================================================================

# --- Stage 1: builder ----------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Dipendenze di build (wheel, eventuali dev libs per compilazione)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

# Venv isolato che verra' copiato nello stage runtime
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir .

# --- Stage 2: runtime ----------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="SPESEMED API" \
      org.opencontainers.image.description="OCR per ricevute mediche italiane (Fase 3: rate-limit + auth completa)" \
      org.opencontainers.image.source="https://github.com/spesemed/spesemed" \
      org.opencontainers.image.licenses="Proprietary"

# Dipendenze di sistema: poppler (per pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Utente non-root (security best practice)
RUN useradd --create-home --shell /bin/bash --uid 1000 spesemed

WORKDIR /app

# Copia venv dal builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    # Default env vars (override in production via env_file)
    API_ENV=production \
    API_WORKERS=2

# Copia codice sorgente
COPY --chown=spesemed:spesemed src ./src
COPY --chown=spesemed:spesemed pyproject.toml ./
# NB: la landing statica e' opzionale (main.py monta /landing solo se il
# directory esiste). Non e' versionata: il build non deve fallire se assente.

USER spesemed

EXPOSE 8000

# Health check (richiede uvicorn sul 8000)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health', timeout=3).raise_for_status()" || exit 1

# Default CMD: usa gunicorn con uvicorn worker (multi-worker per produzione).
# Override con `command:` in docker-compose se serve dev (uvicorn --reload).
# Formula workers: 2 * CPU + 1 (vedi gunicorn docs). API_WORKERS env sovrascrive.
CMD ["sh", "-c", "exec gunicorn spesemed.api.main:app \
    --workers ${API_WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --timeout 120 \
    --graceful-timeout 30"]

"""SPESEMED API — Access Control List per l'endpoint `/metrics`.

SECURITY (FIX M6 audit 2025 — defense-in-depth per [E3] smoke test):
    Il reverse proxy (Caddyfile / nginx.conf) e' la protezione primaria
    di /metrics. Tuttavia, se il proxy viene bypassato, dimenticato in
    deployment lab/preview, o semplicemente non ancora deployato,
    l'endpoint Prometheus resterebbe raggiungibile da internet. Questo
    modulo implementa un filtro IP/CIDR in-process per chiudere quel gap.

Design:
    - Permette IP singoli ("10.0.0.5") o CIDR ("10.0.0.0/24"), IPv4 + IPv6.
    - Loopback (127.0.0.1 e ::1) sono ammessi di default (vedi config.py).
    - X-Forwarded-For viene onorato SOLO se la connessione diretta (peer
      TCP, ossia il reverse proxy) e' gia' whitelistata e il flag
      `metrics_trust_xff=True` e' attivo. Senza questa protezione,
      uno spoof X-Forwarded-For = 127.0.0.1 bypasserebbe ogni ACL.
    - Lista vuota + api_env="production" => fail-closed (403 sicuro).
    - Lista vuota + api_env="development" => fail-open (warning log).
    - IPv4-mapped IPv6 (es. `::ffff:127.0.0.1`) viene normalizzato a forma
      IPv4 per il match (gestione realistica di socket dual-stack).

Logging:
    - Denial: WARNING con messaggio GENERICO (no IP nel messaggio
      principale, evita reflection in log aggregati pubblici).
    - IP bloccato: solo a livello DEBUG (no leakage in INFO+).
"""
from __future__ import annotations

import ipaddress
import logging
from typing import List, Optional, Union

from fastapi import HTTPException, Request, status

from .config import settings

logger = logging.getLogger(__name__)

# Public types for IPv4/IPv6 addresses.
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _normalize_ip(raw_ip: Optional[str]) -> Optional[IPAddress]:
    """Converte stringa in oggetto ipaddress, gestendo IPv4/IPv6 + casi None.

    NB: `::ffff:127.0.0.1` (IPv4-mapped IPv6) viene convertito a
    `127.0.0.1` (IPv4) per match trasparente contro entry IPv4 in
    allowlist (`ipaddress.ip_network("127.0.0.0/8")` non contiene IPv4-mapped
    IPv6 per default). Casi malformati / None => None (fail-closed).
    """
    if not raw_ip:
        return None
    try:
        ip = ipaddress.ip_address(raw_ip.strip())
    except (ValueError, AttributeError):
        return None
    # Se e' un IPv4-mapped IPv6 (es. ::ffff:127.0.0.1), estrai la v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _ip_in_allowlist(client_ip: Optional[IPAddress], allowlist: List[str]) -> bool:
    """True se `client_ip` matcha almeno una entry dell'allowlist.

    Supporta IP singoli e CIDR ("10.0.0.0/24"). Entry malformate
    vengono ignorate silenziosamente.
    """
    if client_ip is None:
        return False
    for entry in allowlist:
        try:
            net = ipaddress.ip_network(entry, strict=False)
            if client_ip in net:
                return True
        except (ValueError, TypeError):
            # CIDR/IP malformato — skip con debug.
            logger.debug("Entry ACL ignorata (non valida): %r", entry)
    return False


def _extract_client_ip(request: Request) -> str:
    """Determina l'IP del client secondo la policy XFF trust.

    Regole (in ordine):
        1. Se metrics_trust_xff=True E peer TCP (`request.client.host`)
           matcha l'allowlist => usa il primo IP di X-Forwarded-For.
        2. Altrimenti usa il peer TCP diretto.
    """
    peer_ip_raw = request.client.host if request.client else ""
    peer_ip = _normalize_ip(peer_ip_raw)

    xff_header = request.headers.get("x-forwarded-for")

    if settings.metrics_trust_xff and xff_header and peer_ip is not None:
        # Solo se la connessione diretta e' autorizzata (proxy trusted).
        if _ip_in_allowlist(peer_ip, settings.metrics_ip_allowlist):
            # X-Forwarded-For is a comma-separated list: client, proxy1, proxy2.
            first_xff = xff_header.split(",")[0].strip()
            xff_ip = _normalize_ip(first_xff)
            if xff_ip is not None:
                return first_xff
            # Se XFF malformato, fallback al peer (fail-closed su spoof).
            logger.debug("X-Forwarded-For malformato, fallback a peer IP.")
            return peer_ip_raw
    return peer_ip_raw


def check_metrics_authorization(request: Request) -> None:
    """Verifica che il client possa accedere a GET /metrics.

    Solleva HTTPException(403) se:
        - Allowlist vuota + production (fail-closed).
        - IP del client non matcha l'allowlist.

    NB: questa funzione NON verifica `prometheus_metrics_enabled`:
    quel check precede questo (404 se disabilitato). Questa funzione
    gestisce SOLO il layer IP-allowlist.
    """
    allowlist = settings.metrics_ip_allowlist

    # Lista vuota: fail-closed in production, fail-open in development.
    if not allowlist:
        if settings.api_env == "production":
            logger.warning(
                "Metrics /metrics blocked: allowlist vuota in production (fail-closed)."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Metrics access denied (production requires allowlist).",
            )
        logger.debug(
            "Metrics allowlist vuota: fail-open in development (api_env=%s).",
            settings.api_env,
        )
        return

    client_ip_raw = _extract_client_ip(request)
    client_ip = _normalize_ip(client_ip_raw)

    if not _ip_in_allowlist(client_ip, allowlist):
        # Messaggio generico nel WARNING (no IP riflesso).
        logger.warning("Metrics /metrics access denied (IP non autorizzato).")
        # IP specifico solo a DEBUG (per non leakare in INFO+/stdout publico).
        logger.debug(
            "Metrics denial: client_ip=%s allowlist=%s trust_xff=%s api_env=%s",
            client_ip_raw,
            allowlist,
            settings.metrics_trust_xff,
            settings.api_env,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics access denied.",
        )

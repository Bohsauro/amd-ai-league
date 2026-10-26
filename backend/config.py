from __future__ import annotations

TOP_K = 6
EXPAND_K = 8
TOP_K_MIN = 5
TOP_K_MAX = 8

GUARD_THRESHOLD = 0.60
MAX_EXPANSIONS = 1

GEN_MIN_SOURCES = 2
GEN_MAX_SOURCES = 3
GEN_TOKEN_BUDGET = 1500
GEN_TIMEOUT_S = 20.0

E2E_BUDGET_MS = 1200.0

NOUL_DROP_TARGET = (0.60, 0.70)

RELIABILITY_WEIGHTS = {
    "authority": 0.50,
    "recency": 0.25,
    "consistency": 0.25,
}

AUTHORITY = {
    "official": 1.00,
    "report": 0.85,
    "press": 0.70,
    "blog": 0.35,
    "noise": 0.00,
    "unknown": 0.50,
}

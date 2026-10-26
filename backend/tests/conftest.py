"""Test suite della pipeline AMD AI League.

I moduli del backend usano import piatti (`from config import ...`), quindi la
directory `backend/` deve stare su sys.path: lo fa questo conftest, così i test
girano sia con `pytest backend/tests` sia da dentro `backend/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

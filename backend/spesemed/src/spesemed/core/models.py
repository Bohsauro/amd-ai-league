"""SPESEMED - Modelli Pydantic per l'output strutturato dell'AI.

Definisce lo schema `SpesaMedica` per validare l'output JSON del modello Vision
di OpenRouter.

Principi di design (importanti per le fasi successive):
    - **Robustezza > rigore**: i campi potenzialmente soggetti a errori OCR
      (data, codice fiscale, importo) sono `Optional` o accettano valori
      "raw" che l'utente può correggere manualmente in Fase 2.
    - **Mai bloccare l'estrazione**: se l'AI è incerta su un campo, il valore
      è `None` e l'utente provvede. L'estrazione non fallisce MAI per un
      singolo campo non letto.
    - **Tassonomia single-source-of-truth**: `CATEGORIE_SPESA` arriva da
      `prompts.py`; in models.py rimane solo il `Literal` per il type-check,
      e c'è un assert di import-time che verifica la coerenza.

Il modello prodotto da `extract_from_file()` è sempre serializzabile e
editabile dall'utente nella UI di Fase 2.
"""
from __future__ import annotations

import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Single-source-of-truth: l'elenco categorie vive in taxonomy.py.
# Importiamo direttamente (no re-export via prompts) per avere un'architettura
# a singolo hop e ridurre il rischio di circular import futuri.
from .taxonomy import CATEGORIE_SPESA


logger = logging.getLogger(__name__)


# =============================================================================
# Tassonomia categorie
# =============================================================================
# Manteniamo il Literal esplicito per type-checking statico (Pydantic v2 non
# supporta Literal[*tuple] su Python 3.10). L'assert sotto garantisce che
# rimanga sincronizzato con CATEGORIE_SPESA di taxonomy.py.
CategoriaSpesa = Literal[
    "Farmaci",
    "Visita Specialistica",
    "Dispositivo Medico",
    "Esami",
    "Altro",
]

assert set(CategoriaSpesa.__args__) == set(CATEGORIE_SPESA), (
    f"models.CategoriaSpesa {set(CategoriaSpesa.__args__)} deve matchare "
    f"taxonomy.CATEGORIE_SPESA {set(CATEGORIE_SPESA)}"
)


# =============================================================================
# Pattern tolleranti (accettano valori OCR-impuri, l'utente corregge in Fase 2)
# =============================================================================
_DATA_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Per il CF usiamo un check "strutturale" ma NON rifiutiamo valori che non
# rispettano il pattern: l'OCR può invertire 0/O, 1/I, ecc.
_CF_LENIEnt_PATTERN = re.compile(r"^[A-Z0-9]{16}$")


class SpesaMedica(BaseModel):
    """Schema di una spesa medica italiana estratta da una ricevuta.

    Tutti i campi ECCETTO `categoria_spesa` sono facoltativi e tolleranti:
    l'AI potrebbe non riuscire a leggerli correttamente, e in quel caso il
    valore è `None` o comunque mantenuto (con warning) per consentire la
    correzione manuale in Fase 2.

    `categoria_spesa` ha default "Altro" come fallback sicuro per fini fiscali.
    """

    data_spesa: Optional[str] = Field(
        default=None,
        description="Data della ricevuta in formato YYYY-MM-DD. None se illeggibile.",
        examples=["2024-03-15"],
    )
    esercente: Optional[str] = Field(
        default=None,
        description="Ragione sociale o nome dell'esercente (farmacia, ospedale, studio).",
        examples=["Farmacia Centrale di Rossi Mario & C."],
    )
    importo_totale: Optional[float] = Field(
        default=None,
        description="Importo totale pagato dal paziente in euro (float). None se illeggibile.",
        examples=[45.50],
        # NB: nessun `ge=0` qui: i valori negativi (possibili errori OCR tipo
        # "-45,50" su una riga sbagliata) vengono catturati e clampati a 0.0
        # dal field_validator `_arrotonda_importo`, con warning.
    )
    codice_fiscale_paziente: Optional[str] = Field(
        default=None,
        description="Codice fiscale del paziente (16 caratteri alfanumerici). "
                    "Può contenere errori OCR: l'utente lo corregge in Fase 2.",
    )
    categoria_spesa: CategoriaSpesa = Field(
        default="Altro",
        description="Categoria tassonomica della spesa medica. Default 'Altro' "
                    "se l'AI è incerta (l'utente può riclassificare in Fase 2).",
    )

    # -------------------------------------------------------------------------
    # Validatori: TOLLERANTI. Loggano warning ma MAI rifiutano il valore,
    # perché l'utente può correggerlo manualmente nell'interfaccia (Fase 2).
    # -------------------------------------------------------------------------
    @field_validator("data_spesa")
    @classmethod
    def _valida_data(cls, v: Optional[str]) -> Optional[str]:
        """Normalizza data; warning se non YYYY-MM-DD, ma MAI blocca."""
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not _DATA_PATTERN.match(v):
            logger.warning(
                "data_spesa '%s' non è in formato YYYY-MM-DD: "
                "mantengo il valore per correzione manuale utente.", v,
            )
            return v
        return v

    @field_validator("codice_fiscale_paziente")
    @classmethod
    def _normalizza_cf(cls, v: Optional[str]) -> Optional[str]:
        """Uppercase + strip + rimozione spazi/trattini; NON blocca se malformato."""
        if v is None:
            return None
        v_normalizzato = v.strip().upper()
        if v_normalizzato == "":
            return None
        # OCR-friendly cleanup: rimuovi spazi e trattini che il modello può inserire
        v_normalizzato = re.sub(r"[\s\-]", "", v_normalizzato)
        # Warning ma mai raise: l'utente corregge in Fase 2 (es. 0<->O, 1<->I).
        if not _CF_LENIEnt_PATTERN.match(v_normalizzato):
            logger.warning(
                "codice_fiscale '%s' non è 16 caratteri alfanumerici: "
                "lo mantengo per correzione manuale (possibile errore OCR).",
                v_normalizzato,
            )
        return v_normalizzato

    @field_validator("importo_totale")
    @classmethod
    def _arrotonda_importo(cls, v: Optional[float]) -> Optional[float]:
        """Arrotonda a 2 decimali. None resta None."""
        if v is None:
            return None
        if v < 0:
            logger.warning("importo_totale negativo (%s): lo azzero.", v)
            return 0.0
        return round(float(v), 2)

    @field_validator("esercente")
    @classmethod
    def _normalizza_esercente(cls, v: Optional[str]) -> Optional[str]:
        """Trim whitespace, gestisci stringa vuota come None."""
        if v is None:
            return None
        v = v.strip()
        return v if v else None

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Restituisce un dict pronto per JSON / DataFrame / Excel."""
        return self.model_dump()

    @property
    def is_complete(self) -> bool:
        """True se la spesa ha i dati minimi per essere processata (Fase 3)."""
        return (
            self.data_spesa is not None
            and self.importo_totale is not None
            and self.esercente is not None
        )

    @property
    def missing_fields(self) -> list[str]:
        """Lista dei nomi dei campi mancanti (per mostrare un warning in UI)."""
        campi = {
            "data_spesa": self.data_spesa,
            "esercente": self.esercente,
            "importo_totale": self.importo_totale,
            "codice_fiscale_paziente": self.codice_fiscale_paziente,
        }
        return [nome for nome, valore in campi.items() if valore is None]

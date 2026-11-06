"""Druckprüfung und Konstruktionsregeln für 3D-Druckteile (Bambu Lab P1P, FDM).

Einbindung in ``lager.druckteil``, ``RUN_END`` und MCP: siehe ``README.md`` in diesem Ordner.
"""

from typing import Any

from kevcad_kernel.druck.regeln import (
    MATERIALIEN,
    P1P,
    PASSUNGEN,
    Drucker,
    Material,
    bohrung_zugabe,
    einsatz,
    kernloch,
    material,
    muttertasche,
    schnapp_auslenkung,
)

__all__ = [
    "MATERIALIEN", "P1P", "PASSUNGEN", "SCHWEREN", "Drucker", "Material", "als_warnungen", "bohrung_zugabe",
    "einsatz", "kernloch", "material", "muttertasche", "pruefe_druckteil", "schnapp_auslenkung",
]


def __getattr__(name: str) -> Any:
    """Die Prüfung zieht build123d nach sich: erst laden, wenn sie gebraucht wird (V2-1b: Start des Kernels)."""
    if name in ("SCHWEREN", "als_warnungen", "pruefe_druckteil"):
        from kevcad_kernel.druck import pruefung

        return getattr(pruefung, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Zwangsbedingungen von Kev CAD (PLAN-BEDINGUNGEN.md): Bezüge, Bedingungen, Löser, Prüfung nach jedem Lauf.

API für model.py: ``kevcad.bedingungen``. Für das Zusammenführen mit dem Strang Prüfungen:

- ``pruefen(sammlung, formen, ...)`` liefert den Bericht (Nachricht CONSTRAINTS, MCP ``bedingungen``),
- ``befunde(bericht)`` die Befunde im gemeinsamen Format (``art: "bedingung"``, ``teile``, ``schwere``, ``wert``,
  ``ort``, ``loesung``, zusätzlich ``soll``, ``ist``, ``pruefung``: bedingung | parameter | widerspruch |
  freiheitsgrade | bewegungsraum | befestigung).
"""

from __future__ import annotations

from typing import Any

from .arten import BedingungsFehler
from .geometrie import BezugFehler
from .pruefung import pruefen
from .sammlung import Sammlung, aktive, sammeln

__all__ = ["BedingungsFehler", "BezugFehler", "Sammlung", "aktive", "befunde", "exportsperre", "pruefen", "sammeln"]


def befunde(bericht: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Befunde eines Berichts (für die gemeinsame Prüfung)."""
    return list((bericht or {}).get("befunde") or [])


def exportsperre(bericht: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Befunde, die den Export sperren (Schwere „fehler“)."""
    return [b for b in befunde(bericht) if b.get("schwere") == "fehler"]

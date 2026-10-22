"""Zeichnungs-Engine von Kev CAD (Phase 6, Strang P6-Z; Vertrag in DOKUMENTE.md).

Aus den Teilen eines Laufs entstehen normgerechte technische Zeichnungen: Ansichten nach Projektionsmethode 1 mit
sichtbaren und verdeckten Kanten (OCCT Hidden Line Removal), Mittellinien, Schnitte mit Schraffur, Einzelheiten,
Merkmalerkennung je Teil, automatische Bemaßung nach ISO 129-1, Platzierung ohne Überlappung, Blatt mit Rahmen und
Schriftfeld (ISO 5457, ISO 7200), stabile Bezüge über Läufe hinweg.

Bausteine (von unten nach oben):

| Modul | Inhalt |
|---|---|
| ``geo2d`` | 2D-Werkzeug: Rechtecke, Polylinien, Clipping, Schraffur, Textbreite |
| ``ansichten`` | Blickrichtungen (vorn, oben, links …, iso, Kamera) und Anordnung nach Projektionsmethode 1 |
| ``topologie`` | Flächen eines Teils mit Typ, Lage, Achse, Radius, Wölbung und Nachbarn |
| ``teilsystem`` | lokales System eines Teils (Hauptlage für die Zeichnung) |
| ``projektion`` | ``projiziere(formen, ansicht)`` → Linien je Linienart (öffentlich, auch für den Bauplan) |
| ``merkmale`` | ``erkenne(form)`` → Merkmale (Bohrungen, Lochbilder, Langlöcher, Taschen, Fasen, Radien, Stange …) |
| ``schnitt`` | Schnittansichten mit Schraffur (ISO 128-50) und Einzelheiten |
| ``bezuege`` | Bezüge mit Signatur, Neuzuordnung nach jedem Lauf, verwaiste Maße |
| ``bemassung`` | automatische Maße (ISO 129-1) aus Merkmalen und Ansichten |
| ``darstellung`` | Maß → fertige Darstellung (Linien, Pfeile, Text, Lage, Winkel, Wert) und Platzierung |
| ``blatt`` | Formate, Maßstäbe (ISO 5455), Rahmen, Schriftfeld, Tabellen, Positionsnummern |
| ``dokument`` | Blatt-JSON lesen, prüfen, schreiben; Bearbeitungs-Operationen |
| ``zeichner`` | ganzes Blatt rechnen: Blatt-JSON + Teile → Nachricht DRAWING |
| ``bild`` | DRAWING → SVG → PNG (``rsvg-convert``) zur Prüfung durch den Agenten |
| ``laufzeit`` | Anbindung an die Kernel-Laufzeit: Dateien, DOCS, DRAWING_REQ/EDIT, MCP-Methoden |

Öffentliche Schnittstelle für andere Stränge (Bauplan P6-B):

- ``projiziere(formen, ansicht, …) -> Projektion`` (``projektion.py``)
- ``erkenne(form, info=None) -> Merkmale`` (``merkmale.py``)
"""

from __future__ import annotations

from typing import Any

# Schwere Module (build123d, OCP) erst bei Bedarf laden: die Laufzeit bindet ``laufzeit`` beim Start ein
_OEFFENTLICH = {
    "BLICKE": "ansichten", "Blick": "ansichten", "blick": "ansichten",
    "LINIENARTEN": "projektion", "Projektion": "projektion", "projiziere": "projektion",
    "Merkmal": "merkmale", "Merkmale": "merkmale", "erkenne": "merkmale",
    "Teilsystem": "teilsystem",
}

__all__ = list(_OEFFENTLICH)


def __getattr__(name: str) -> Any:
    modul = _OEFFENTLICH.get(name)
    if modul is None:
        raise AttributeError(name)
    import importlib

    return getattr(importlib.import_module(f"{__name__}.{modul}"), name)

"""Benannte Bezugspunkte und Einbaupunkte (KATALOG.md): prüfen und als build123d-``Location`` bauen.

Für Zukaufteile (``lager.zukauf(...).bezugspunkt(name)``). Kameras, Objektive und Kamera-Zubehör (Phase 5,
``kevcad/kamera.py``: ``_local_point``, ``Kamera.bezugspunkt``, ``Zubehoer.bezugspunkt``; Prüfung in
``kevcad_kernel/optik.py``) schreiben ``pos`` gleich, deuten den Rest aber anders: dort gelten die Achsen der Kamera bzw.
des Teils (``richtung`` ist nur Angabe, ``von: "front"`` verschiebt x), hier ist ``richtung`` die Z-Achse der Location.
Eine gemeinsame Umsetzung würde das Setzen von Rig-Teilen ändern und ist deshalb nicht zusammengelegt.

Ein Punkt ist ``{"pos": [x, y, z], "richtung": [x, y, z], "hinweis": "..."}`` in mm im lokalen System des Teils:

- ``pos``: Ursprung der Location.
- ``richtung``: lokale Z-Achse der Location (Standard ``[0, 0, 1]``), etwa die Blickrichtung eines Bajonetts oder die
  Normale einer Auflagefläche.
- ``x_richtung`` (optional): legt die Verdrehung um ``richtung`` fest; ohne sie gilt die X-Achse, die build123d für
  ``Plane(z_dir=richtung)`` wählt (bei ``richtung`` = Z ist das +X).

Der ``einbaupunkt`` eines Zukaufteils ist ein Punkt im System der Quelle (Hersteller-CAD, Skript, Ersatzkörper): Er
wird beim Verbauen zum Ursprung, seine ``richtung`` zur +Z-Achse. ``bezugspunkte`` gelten im System des verbauten
Teils (also nach dem Einbaupunkt), damit ``Pos(...) * teil.bezugspunkt("oben")`` zum gezeigten Teil passt.

Leicht: build123d wird erst in ``location`` geladen (der Katalog prüft im Elternprozess).
"""

from __future__ import annotations

import math
from typing import Any

PUNKT_FELDER = ("pos", "richtung", "x_richtung", "hinweis")


def _vec(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            return None
        out.append(float(v))
    return out


def pruefen_punkt(punkt: Any, who: str) -> list[str]:
    """Fehler eines Punkts (leer = gültig)."""
    if not isinstance(punkt, dict):
        return [f"{who}: muss ein Objekt {{\"pos\": [x, y, z], \"richtung\": [x, y, z]}} sein"]
    errors: list[str] = []
    if "pos" in punkt and _vec(punkt.get("pos")) is None:
        errors.append(f"{who}: pos als [x, y, z] in mm angeben")
    for key in ("richtung", "x_richtung"):
        if key in punkt and punkt[key] is not None:
            v = _vec(punkt.get(key))
            if v is None:
                errors.append(f"{who}: {key} als [x, y, z] angeben")
            elif math.hypot(*v) < 1e-9:
                errors.append(f"{who}: {key} darf nicht [0, 0, 0] sein")
    r, x = _vec(punkt.get("richtung")), _vec(punkt.get("x_richtung"))
    if r and x and math.hypot(*r) > 1e-9 and math.hypot(*x) > 1e-9:
        cos = abs(sum(a * b for a, b in zip(r, x))) / (math.hypot(*r) * math.hypot(*x))
        if cos > 0.999:
            errors.append(f"{who}: x_richtung darf nicht parallel zu richtung sein")
    if punkt.get("hinweis") is not None and not isinstance(punkt.get("hinweis"), str):
        errors.append(f"{who}: hinweis muss Text sein")
    unknown = [k for k in punkt if k not in PUNKT_FELDER]
    if unknown:
        errors.append(f"{who}: unbekannte Felder {', '.join(unknown)} (erlaubt: {', '.join(PUNKT_FELDER)})")
    return errors


def pruefen_punkte(punkte: Any, who: str) -> list[str]:
    """Fehler eines Verzeichnisses benannter Punkte ``{"oben": {...}, ...}``."""
    if not isinstance(punkte, dict):
        return [f"{who}: bezugspunkte muss ein Objekt {{name: {{pos, richtung, hinweis}}}} sein"]
    errors: list[str] = []
    for name, punkt in punkte.items():
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{who}: Bezugspunkt ohne Namen")
            continue
        errors += pruefen_punkt(punkt, f"{who}, Bezugspunkt {name!r}")
    return errors


def location(punkt: dict[str, Any] | None):
    """build123d-``Location`` eines Punkts (fehlt er, die Identität)."""
    from build123d import Location, Plane

    punkt = punkt or {}
    pos = _vec(punkt.get("pos")) or [0.0, 0.0, 0.0]
    richtung = _vec(punkt.get("richtung")) or [0.0, 0.0, 1.0]
    x_richtung = _vec(punkt.get("x_richtung"))
    if x_richtung is None and all(abs(a - b) < 1e-12 for a, b in zip(richtung, (0.0, 0.0, 1.0))):
        return Location(tuple(pos))
    plane = Plane(origin=tuple(pos), x_dir=tuple(x_richtung) if x_richtung else None, z_dir=tuple(richtung))
    return Location(plane)


def einbau(punkt: dict[str, Any] | None):
    """Location, die den Einbaupunkt auf den Ursprung und seine Richtung auf +Z legt (Kehrwert von ``location``)."""
    return location(punkt).inverse()


def bezugspunkt(punkte: dict[str, Any] | None, name: str, who: str = "Teil"):
    """Location des benannten Punkts; unbekannt → ValueError mit den vorhandenen Namen."""
    import difflib

    punkte = punkte or {}
    if name not in punkte:
        names = sorted(punkte)
        close = difflib.get_close_matches(str(name), names, n=2, cutoff=0.5)
        raise ValueError(f"{who}: Bezugspunkt {name!r} gibt es nicht"
                         + (f"; meinten Sie {' oder '.join(repr(c) for c in close)}?" if close else "")
                         + (f" (vorhanden: {', '.join(names)})" if names else " (das Teil hat keine Bezugspunkte im "
                                                                              "Katalog)"))
    return location(punkte[name])

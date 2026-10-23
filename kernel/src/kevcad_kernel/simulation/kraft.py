"""Vom Klick zur Kraft (PLAN-SIMULATION.md, S4): Angriffsort aus der Auswahl im Viewer (Teil, Fläche, Punkt, Normale),
Richtung (entlang der Normale, entlang einer Achse oder frei) und Betrag (N oder kg) ergeben den Kraftvektor in N.

Rein und ohne Geometrie, damit App (Vorschau des Pfeils) und Kernel (gespeicherte Kraft) dasselbe rechnen; die App
spiegelt ``kraft_aus`` in ``SimulationModell.swift``. Einheiten: N, mm, Grad.

Richtung (``richtung``):

- ``{"art": "normale"}``: senkrecht auf die angeklickte Fläche, **in das Teil hinein** (drückt); mit ``"umkehren":
  true`` aus dem Teil heraus (zieht).
- ``{"art": "achse", "achse": "-z"}``: entlang einer Weltachse (``+x``, ``-x``, ``+y``, ``-y``, ``+z``, ``-z``).
- ``{"art": "frei", "vektor": [x, y, z]}`` oder ``{"art": "frei", "azimut": 30, "hoehe": -45}``: Azimut in der
  XY-Ebene ab +X gegen den Uhrzeigersinn, Höhe über der XY-Ebene (−90 = senkrecht nach unten).

Betrag: ``einheit`` ``"N"`` (Kraft) oder ``"kg"`` (Masse, F = m · 9,81 m/s², Richtung wie angegeben; ohne Richtung
nach unten).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

G = 9.81
ACHSEN = {"+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0), "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0),
          "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0)}
RICHTUNGSARTEN = ("normale", "achse", "frei")
EINHEITEN = ("N", "kg")


class KraftFehler(ValueError):
    pass


def achse(text: Any) -> np.ndarray:
    t = str(text or "").strip().lower().replace("−", "-")
    if t and t[0] not in "+-":
        t = "+" + t
    v = ACHSEN.get(t)
    if v is None:
        raise KraftFehler(f"Achse {text!r} unbekannt (+x, -x, +y, -y, +z, -z)")
    return np.array(v)


def vektor(v: Any, was: str = "vektor") -> np.ndarray:
    try:
        a = np.asarray([float(c) for c in v], dtype=float)
    except (TypeError, ValueError) as exc:
        raise KraftFehler(f"{was} ist kein Vektor (x, y, z)") from exc
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise KraftFehler(f"{was} braucht drei Zahlen (x, y, z)")
    return a


def einheit(v: Any, was: str = "Richtung") -> np.ndarray:
    a = vektor(v, was)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise KraftFehler(f"{was} (0, 0, 0) ist keine Richtung")
    return a / n


def aus_winkeln(azimut: float, hoehe: float) -> np.ndarray:
    """Richtung aus Azimut (Grad in der XY-Ebene ab +X) und Höhe (Grad über der XY-Ebene)."""
    a, h = math.radians(float(azimut)), math.radians(float(hoehe))
    return np.array([math.cos(h) * math.cos(a), math.cos(h) * math.sin(a), math.sin(h)])


def winkel_aus(d: Any) -> tuple[float, float]:
    """Azimut und Höhe (Grad) einer Richtung, Gegenstück zu ``aus_winkeln``."""
    v = einheit(d)
    hoehe = math.degrees(math.asin(max(-1.0, min(1.0, float(v[2])))))
    azimut = math.degrees(math.atan2(float(v[1]), float(v[0]))) if math.hypot(v[0], v[1]) > 1e-9 else 0.0
    return round(azimut, 6) + 0.0, round(hoehe, 6) + 0.0


def richtung_aus(richtung: dict[str, Any] | None, normale: Any = None, einheit_text: str = "N") -> np.ndarray:
    """Einheitsvektor der Kraft. ``normale``: Flächennormale (nach außen) der angeklickten Fläche."""
    r = dict(richtung or {})
    art = str(r.get("art") or ("achse" if einheit_text == "kg" else "normale"))
    if art not in RICHTUNGSARTEN:
        raise KraftFehler(f"Richtung {art!r} unbekannt ({', '.join(RICHTUNGSARTEN)})")
    if art == "normale":
        if normale is None:
            raise KraftFehler("Richtung „entlang der Normale“ braucht eine angeklickte Fläche mit Normale")
        d = -einheit(normale, "Normale")  # in das Teil hinein: die Kraft drückt auf die Fläche
        return -d if r.get("umkehren") else d
    if art == "achse":
        d = achse(r.get("achse") or "-z")
        return -d if r.get("umkehren") else d
    if r.get("vektor") is not None:
        d = einheit(r["vektor"], "Richtung")
    elif r.get("azimut") is not None or r.get("hoehe") is not None:
        d = aus_winkeln(float(r.get("azimut") or 0.0), float(r.get("hoehe") or 0.0))
    else:
        raise KraftFehler("Richtung „frei“ braucht vektor=[x, y, z] oder azimut und hoehe in Grad")
    return -d if r.get("umkehren") else d


def betrag_n(betrag: Any, einheit_text: str = "N") -> float:
    if einheit_text not in EINHEITEN:
        raise KraftFehler(f"Einheit {einheit_text!r} unbekannt (N oder kg)")
    try:
        b = float(betrag)
    except (TypeError, ValueError) as exc:
        raise KraftFehler(f"Betrag {betrag!r} ist keine Zahl") from exc
    if not math.isfinite(b) or b <= 0:
        raise KraftFehler("Betrag muss größer als 0 sein")
    if b > 1e7:
        raise KraftFehler("Betrag über 10 MN: bitte in N oder kg prüfen")
    return b * G if einheit_text == "kg" else b


def kraft_aus(richtung: dict[str, Any] | None, betrag: Any, einheit_text: str = "N", normale: Any = None
              ) -> np.ndarray:
    """Kraftvektor in N (Welt)."""
    return richtung_aus(richtung, normale, einheit_text) * betrag_n(betrag, einheit_text)


def kurz(kraft: Any) -> list[float]:
    return [round(float(c), 4) + 0.0 for c in kraft]

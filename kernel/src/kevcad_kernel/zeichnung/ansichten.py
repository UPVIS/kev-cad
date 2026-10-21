"""Blickrichtungen und Anordnung der Ansichten nach Projektionsmethode 1 (ISO 128-30, ISO 5456-2).

Vertrag (DOKUMENTE.md): ``vorn`` = Blick in +Y, ``oben`` = Blick in −Z, Achsen des Teils bzw. Modells, Z oben. Eine
Ansicht ist durch Blickrichtung ``richtung`` (vom Betrachter in die Szene) und die Blattachsen ``rechts`` und ``oben``
festgelegt; ein Punkt p erscheint auf dem Blatt bei (p · rechts, p · oben).

Projektionsmethode 1 (europäisch): Draufsicht unter der Vorderansicht, Seitenansicht von links rechts daneben,
Seitenansicht von rechts links daneben, Untersicht oben, Rückansicht ganz rechts. Die Blattachsen folgen daraus
(Klappen der Bildebenen um die Kanten der Vorderansicht).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

# Blickrichtung, Blatt-rechts, Blatt-oben (Teil- bzw. Modellachsen)
_TABELLE: dict[str, tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = {
    "vorn": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "hinten": ((0, -1, 0), (-1, 0, 0), (0, 0, 1)),
    "oben": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
    "unten": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "links": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "rechts": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
}

# Isometrische Ansichten: Betrachter vorn rechts oben (wie „iso“ in der App), dazu die übrigen Ecken
_ISO = {
    "iso": (1, -1, 1),
    "iso_vorn_links": (-1, -1, 1),
    "iso_hinten_rechts": (1, 1, 1),
    "iso_hinten_links": (-1, 1, 1),
}

ORTHO = tuple(_TABELLE)
ISO = tuple(_ISO)

# Lage im Raster der Projektionsmethode 1 relativ zur Vorderansicht (Spalte, Zeile; Zeile wächst nach unten)
RASTER: dict[str, tuple[int, int]] = {
    "vorn": (0, 0),
    "oben": (0, 1),
    "unten": (0, -1),
    "links": (1, 0),
    "rechts": (-1, 0),
    "hinten": (2, 0),
}

NAMEN = {"vorn": "Vorderansicht", "hinten": "Rückansicht", "oben": "Draufsicht", "unten": "Untersicht",
         "links": "Seitenansicht von links", "rechts": "Seitenansicht von rechts", "iso": "Isometrie",
         "iso_vorn_links": "Isometrie vorn links", "iso_hinten_rechts": "Isometrie hinten rechts",
         "iso_hinten_links": "Isometrie hinten links"}


def _einheit(v: Any) -> np.ndarray:
    a = np.asarray(v, dtype=float).reshape(3)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise ValueError("Richtung hat die Länge 0")
    return a / n


@dataclass(frozen=True)
class Blick:
    """Orthogonale Parallelprojektion: Blickrichtung und Blattachsen (Einheitsvektoren, rechtshändig)."""

    art: str
    richtung: tuple[float, float, float]
    rechts: tuple[float, float, float]
    oben: tuple[float, float, float]

    @property
    def matrix(self) -> np.ndarray:
        """2 × 3: Zeilen rechts und oben (Punkt → Blatt-x, Blatt-y vor dem Maßstab)."""
        return np.array([self.rechts, self.oben], dtype=float)

    @property
    def d(self) -> np.ndarray:
        return np.asarray(self.richtung, dtype=float)

    def projiziere(self, p: Any) -> np.ndarray:
        """Punkt(e) (…, 3) → (…, 2)."""
        return np.asarray(p, dtype=float) @ self.matrix.T

    def tiefe(self, p: Any) -> np.ndarray:
        """Abstand entlang der Blickrichtung (größer = weiter hinten)."""
        return np.asarray(p, dtype=float) @ self.d

    @property
    def orthogonal(self) -> bool:
        """Blick entlang einer Achse des Teils (Vorder-, Seiten-, Draufsicht …)."""
        return self.art in _TABELLE

    @property
    def schluessel(self) -> str:
        """Für Zwischenspeicher: Art plus gerundete Vektoren."""
        r = ",".join(f"{v:.6f}" for v in (*self.richtung, *self.rechts, *self.oben))
        return f"{self.art}:{r}"

    def als_dict(self) -> dict[str, Any]:
        return {"art": self.art, "richtung": list(self.richtung), "rechts": list(self.rechts), "oben": list(self.oben)}


def aus_richtung(richtung: Any, oben: Any = (0, 0, 1), art: str = "frei") -> Blick:
    """Blick entlang ``richtung`` mit ``oben`` als ungefährer Blatt-y-Achse (wird orthogonalisiert)."""
    d = _einheit(richtung)
    up = np.asarray(oben, dtype=float).reshape(3)
    rechts = np.cross(d, up)
    if np.linalg.norm(rechts) < 1e-9:  # Blick parallel zu oben: andere Hilfsachse
        rechts = np.cross(d, np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0]))
    rechts = _einheit(rechts)
    o = _einheit(np.cross(rechts, d))
    return Blick(art, tuple(float(x) for x in d), tuple(float(x) for x in rechts), tuple(float(x) for x in o))


def aus_quaternion(q: Any, art: str = "kamera") -> Blick:
    """Kamera der App (``rotation`` [x, y, z, w]): sie blickt entlang ihrer lokalen −Z-Achse, oben ist +Y."""
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    rot = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    d = -rot[:, 2]
    up = rot[:, 1]
    return aus_richtung(d, up, art)


def blick(ansicht: Any) -> Blick:
    """Blick aus einem Namen (``vorn``, ``oben``, ``iso`` …), einem ``Blick`` oder einem Wörterbuch
    (``{"richtung", "oben"}`` bzw. Kamera ``{"rotation": [x, y, z, w]}`` wie im Bauplan)."""
    if isinstance(ansicht, Blick):
        return ansicht
    if isinstance(ansicht, str):
        name = ansicht.strip().lower()
        alias = {"front": "vorn", "vorne": "vorn", "back": "hinten", "top": "oben", "bottom": "unten",
                 "left": "links", "right": "rechts", "iso_front_left": "iso_vorn_links",
                 "iso_back_right": "iso_hinten_rechts", "iso_back_left": "iso_hinten_links"}
        name = alias.get(name, name)
        if name in _TABELLE:
            d, r, o = _TABELLE[name]
            return Blick(name, tuple(float(v) for v in d), tuple(float(v) for v in r), tuple(float(v) for v in o))
        if name in _ISO:
            return aus_richtung(-np.asarray(_ISO[name], dtype=float), (0, 0, 1), name)
        raise ValueError(f"Ansicht {ansicht!r} unbekannt (vorn, hinten, oben, unten, links, rechts, iso, "
                         "iso_vorn_links, iso_hinten_rechts, iso_hinten_links)")
    if isinstance(ansicht, dict):
        if ansicht.get("rotation") is not None:
            return aus_quaternion(ansicht["rotation"], str(ansicht.get("art") or "kamera"))
        if ansicht.get("richtung") is not None:
            return aus_richtung(ansicht["richtung"], ansicht.get("oben") or (0, 0, 1), str(ansicht.get("art") or "frei"))
    raise ValueError(f"Ansicht {ansicht!r} nicht lesbar: Name, Blick oder {{'richtung', 'oben'}} bzw. "
                     "{'rotation': [x, y, z, w]}")


BLICKE: dict[str, Blick] = {name: blick(name) for name in (*ORTHO, *ISO)}


def gegenrichtung(art: str) -> str | None:
    return {"vorn": "hinten", "hinten": "vorn", "oben": "unten", "unten": "oben", "links": "rechts",
            "rechts": "links"}.get(art)

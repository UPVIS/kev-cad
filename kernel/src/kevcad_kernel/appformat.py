"""Zahlen und Einheiten genau wie die App (``KevFormat`` in ``app/KevCADCore/Sources/KevCADCore/Project/``).

Gebraucht, wo der Kernel Texte liefert, die byteweise gleich dem sein müssen, was die App zeigt oder teilt
(Einkaufsliste, Verschnitt; Strang „Material im Kernel angleichen“, 22.10.2026). Unterschiede zu ``bom.de_num``:
gerundet wird wie Swifts ``rounded()`` (halbe Werte von der Null weg, nicht zur geraden Ziffer), Nachkommastellen
bleiben stehen („1,0“), Tausender immer mit Punkt.

Ohne Abhängigkeiten, damit ``bom.py`` und ``bestand/`` es ohne Kreisimport laden.
"""

from __future__ import annotations

import math


def runden(x: float, digits: int = 0) -> float:
    """``(x * 10^digits).rounded() / 10^digits`` wie in Swift: halbe Werte von der Null weg; nie -0,0."""
    f = 10.0 ** max(0, digits)
    v = float(x) * f
    a = abs(v)
    r = math.floor(a)
    if a - r >= 0.5:
        r += 1.0
    out = math.copysign(r, v) / f
    return out + 0.0 if out != 0 else 0.0


def _gruppiert(ganz: int) -> str:
    return f"{ganz:,}".replace(",", ".")


def zahl(value: float | None, digits: int) -> str:
    """``KevFormat.number``: feste Nachkommastellen, Komma, Tausenderpunkt: zahl(1234.5, 1) → "1.234,5"."""
    if value is None or not math.isfinite(float(value)):
        return "–"
    digits = max(0, digits)
    r = runden(float(value), digits)
    text = f"{abs(r):.{digits}f}"
    ganz, _, frac = text.partition(".")
    return ("-" if r < 0 else "") + _gruppiert(int(ganz)) + ("," + frac if digits > 0 else "")


def ganzzahl(n: int) -> str:
    """``KevFormat.integer``: "12.480"."""
    return ("-" if n < 0 else "") + _gruppiert(abs(int(n)))


def anzahl(n: int, one: str, many: str) -> str:
    """``KevFormat.count``: "1 Teil", "7 Teile"."""
    return f"{ganzzahl(n)} {one if n == 1 else many}"


def kompakt(value: float | None, max_digits: int = 3) -> str:
    """``KevFormat.compact``: so wenige Nachkommastellen wie nötig: 33.7 → "33,7", 2 → "2", 6000 → "6.000"."""
    if value is None or not math.isfinite(float(value)):
        return "–"
    v = float(value)
    digits = 0
    while digits < max_digits:
        f = 10.0 ** digits
        if abs(runden(v * f) - v * f) < 1e-6:
            break
        digits += 1
    return zahl(v, digits)


def laenge(value: float) -> str:
    """``KevFormat.length``: "882 mm", "6.000 mm", "33,7 mm"."""
    return f"{kompakt(value, 1)} mm"


def euro(value: float) -> str:
    """``KevFormat.euro``: "1.234,50 €"."""
    return f"{zahl(value, 2)} €"


def masse_g(gramm: float) -> str:
    """``KevFormat.mass(grams:)``: unter 1.000 g in g, sonst kg ("7,25 g", "128,6 g", "1,30 kg", "24,5 kg")."""
    v = float(gramm)
    if not math.isfinite(v):
        return "–"
    if abs(v) < 1000:
        return f"{zahl(v, 2 if abs(v) < 10 else 1)} g"
    kg = v / 1000
    return f"{zahl(kg, 2 if abs(kg) < 10 else 1)} kg"


def csv_zahl(value: float | None) -> str:
    """``EinkaufslisteFormat.zahl``: ``String(format: "%.2f")`` mit Komma, ohne Tausenderpunkt."""
    if value is None or not math.isfinite(float(value)):
        return ""
    return f"{float(value):.2f}".replace(".", ",")


def csv_feld(text: str) -> str:
    """``EinkaufslisteFormat.feld``: in Anführungszeichen nur mit Semikolon, Anführungszeichen oder Zeilenumbruch."""
    if ";" not in text and '"' not in text and "\n" not in text:
        return text
    return '"' + text.replace('"', '""') + '"'

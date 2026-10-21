"""Zahlen und Texte der Bedingungen auf Deutsch (ohne die MCP-Pakete zu laden, läuft im Rechenprozess)."""

from __future__ import annotations

import math
from typing import Any


def zahl(value: Any, stellen: int = 3) -> str:
    """Zahl mit Dezimalkomma, Nullen am Ende gekürzt: 2.5 → "2,5", 0.1000 → "0,1"."""
    if value is None:
        return "–"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    x = float(value)
    if not math.isfinite(x):
        return str(x)
    text = f"{x:.{stellen}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text.replace(".", ",")


def mm(value: Any, stellen: int = 3) -> str:
    return f"{zahl(value, stellen)} mm"


def grad(value: Any, stellen: int = 2) -> str:
    return f"{zahl(value, stellen)}°"


def vektor(values: Any, stellen: int = 2) -> str:
    try:
        return "(" + "; ".join(zahl(float(v), stellen) for v in values) + ")"
    except TypeError:
        return str(values)


ACHSEN_NAMEN = {(1, 0, 0): "X", (-1, 0, 0): "−X", (0, 1, 0): "Y", (0, -1, 0): "−Y", (0, 0, 1): "Z", (0, 0, -1): "−Z"}


def richtung(values: Any) -> str:
    """Richtung als Achsname, wenn sie (fast) auf einer Weltachse liegt, sonst als Vektor."""
    try:
        v = [float(x) for x in values]
    except TypeError:
        return str(values)
    for key, name in ACHSEN_NAMEN.items():
        if sum((a - b) ** 2 for a, b in zip(v, key)) < 1e-6:
            return name
    return vektor(v, 3)


def mehrzahl(n: int, eins: str, viele: str) -> str:
    return f"{n} {eins if n == 1 else viele}"

"""Gewindemaße für Prüfung und Bedingungen: metrisches ISO-Regelgewinde und Unified-Zollgewinde (UNC, UNF).

Eine Tabelle für alle Stellen, die Nenndurchmesser, Steigung, Kernloch oder Durchgang brauchen (Gewindeeingriff in
der Prüfung, Schraubprüfung in ``verbinde``/``in_bohrung``). Kameras und Stative nutzen 1/4"-20 UNC und 3/8"-16 UNC.

Quellen:

- Metrisch: Steigung des Regelgewindes nach ISO 261, Kernlochbohrer nach DIN 336, Durchgangsbohrung „mittel“ nach
  ISO 273.
- Zoll: Nenndurchmesser (Basic Major Diameter) und Gänge je Zoll nach ASME B1.1-2019 „Unified Inch Screw Threads“
  (UN/UNR); Nummerngrößen #n = 0,060" + n · 0,013". Kernloch: Bohrer der üblichen Gewindebohrtabelle für etwa 75 %
  Gewindeüberdeckung (Machinery's Handbook, „Tap Drill Sizes“), Durchgang: „free fit“ derselben Tabellen; beide in mm
  umgerechnet (1" = 25,4 mm). Für Steigungen, die nicht in der Tabelle stehen, gilt Kernloch ≈ d − 0,975 · P
  (dieselbe Faustformel für 75 %).
- Gewindetiefe (radial, Außengewinde): h3 = 0,6134 · P, gleich für ISO und UN (gleiches 60°-Grundprofil, ISO 68-1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ZOLL_MM = 25.4
TIEFE_FAKTOR = 0.6134  # h3 / P


@dataclass(frozen=True)
class Gewinde:
    name: str  # "M6", "M8×1", "3/8\"-16 UNC", "#10-24 UNC"
    d: float  # Nenndurchmesser in mm
    steigung: float  # mm
    kernloch: float  # Kernlochbohrer in mm
    durchgang: float  # Durchgangsbohrung in mm (ISO 273 mittel bzw. free fit)
    reihe: str  # "M" (metrisch), "UNC", "UNF", "UN"

    @property
    def tiefe(self) -> float:
        """Radiale Tiefe des Außengewindes (Außen- bis Kerndurchmesser), h3 = 0,6134 · P."""
        return TIEFE_FAKTOR * self.steigung

    @property
    def zoll(self) -> bool:
        return self.reihe != "M"


# Metrisch: Nenndurchmesser → (Steigung ISO 261, Kernloch DIN 336, Durchgang mittel ISO 273)
_METRISCH: dict[float, tuple[float, float, float]] = {
    2: (0.4, 1.6, 2.4), 2.5: (0.45, 2.05, 2.9), 3: (0.5, 2.5, 3.4), 4: (0.7, 3.3, 4.5), 5: (0.8, 4.2, 5.5),
    6: (1.0, 5.0, 6.6), 8: (1.25, 6.8, 9.0), 10: (1.5, 8.5, 11.0), 12: (1.75, 10.2, 13.5), 14: (2.0, 12.0, 15.5),
    16: (2.0, 14.0, 17.5), 18: (2.5, 15.5, 20.0), 20: (2.5, 17.5, 22.0), 22: (2.5, 19.5, 24.0), 24: (3.0, 21.0, 26.0),
    27: (3.0, 24.0, 30.0), 30: (3.5, 26.5, 33.0),
}
METRISCH: dict[float, Gewinde] = {d: Gewinde(f"M{d:g}", float(d), p, k, dg, "M") for d, (p, k, dg) in _METRISCH.items()}

# Zoll: (Größe, Nenndurchmesser in Zoll, Gänge je Zoll, Kernlochbohrer in Zoll, Durchgang „free fit“ in Zoll)
_UNC = [
    ("#4", 0.112, 40, 0.0890, 0.1285), ("#6", 0.138, 32, 0.1065, 0.1495), ("#8", 0.164, 32, 0.1360, 0.1770),
    ("#10", 0.190, 24, 0.1495, 0.2010), ("1/4", 0.250, 20, 0.2010, 0.2660), ("5/16", 0.3125, 18, 0.2570, 0.3320),
    ("3/8", 0.375, 16, 0.3125, 0.3970), ("7/16", 0.4375, 14, 0.3680, 0.4688), ("1/2", 0.500, 13, 0.4219, 0.5312),
    ("5/8", 0.625, 11, 0.5312, 0.6562), ("3/4", 0.750, 10, 0.6562, 0.7812),
]
_UNF = [
    ("#4", 0.112, 48, 0.0935, 0.1285), ("#6", 0.138, 40, 0.1130, 0.1495), ("#8", 0.164, 36, 0.1360, 0.1770),
    ("#10", 0.190, 32, 0.1590, 0.2010), ("1/4", 0.250, 28, 0.2130, 0.2660), ("5/16", 0.3125, 24, 0.2720, 0.3320),
    ("3/8", 0.375, 24, 0.3320, 0.3970), ("7/16", 0.4375, 20, 0.3906, 0.4688), ("1/2", 0.500, 20, 0.4531, 0.5312),
    ("5/8", 0.625, 18, 0.5781, 0.6562), ("3/4", 0.750, 16, 0.6875, 0.7812),
]


def _zoll_name(groesse: str, tpi: int, reihe: str) -> str:
    return f"{groesse}-{tpi} {reihe}" if groesse.startswith("#") else f"{groesse}\"-{tpi} {reihe}"


def _zoll(groesse: str, d: float, tpi: int, kern: float, durch: float, reihe: str) -> Gewinde:
    return Gewinde(_zoll_name(groesse, tpi, reihe), round(d * ZOLL_MM, 4), ZOLL_MM / tpi,
                   round(kern * ZOLL_MM, 3), round(durch * ZOLL_MM, 3), reihe)


ZOLL: list[Gewinde] = [_zoll(*z, "UNC") for z in _UNC] + [_zoll(*z, "UNF") for z in _UNF]
UNC: dict[float, Gewinde] = {g.d: g for g in ZOLL if g.reihe == "UNC"}  # Grobgewinde je Nenndurchmesser (Standard)


# ---------------------------------------------------------------------------------------------------------------------
# Lesen


_METRISCH_RE = re.compile(r"^\s*M\s*(\d+(?:[.,]\d+)?)(?:\s*[-x×*]\s*(\d+(?:[.,]\d+)?))?", re.IGNORECASE)
_ZOLL_RE = re.compile(r"^\s*(?:(?:#|NO\.?|NR\.?)\s*(?P<nummer>\d+)|(?P<mass>\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+))"
                      r"\s*(?:-\s*(?P<tpi>\d+))?\s*(?P<reihe>UNC|UNF|UNEF|UN)?", re.IGNORECASE)


def _zahl(text: str) -> float:
    return float(text.replace(",", "."))


def aus_text(text: object) -> Gewinde | None:
    """Gewinde aus einer Größenangabe: "M6", "M8-1.25", "M8x1", "M4-0.7-8.1" (Einsatz mit Länge), "1/4-20",
    "3/8\"-16 UNC", "3⁄8 Zoll", "#10-24", "No. 10-32 UNF", "1/4 UNF". Ohne Gänge je Zoll gilt UNC (bzw. UNF, wenn
    genannt). None, wenn es keine Gewindeangabe ist."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = _METRISCH_RE.match(s)
    if m:
        d = _zahl(m.group(1))
        p = _zahl(m.group(2)) if m.group(2) else None
        regel = METRISCH.get(d)
        if regel is not None and (p is None or abs(p - regel.steigung) < 1e-6):
            return regel
        if p is None:  # unbekannter Nenndurchmesser ohne Steigung: Faustformel
            p = round(0.15 * d, 2)
        durch = regel.durchgang if regel is not None else round(1.1 * d, 1)
        return Gewinde(f"M{d:g}×{p:g}", d, p, round(d - p, 2), durch, "M")
    # Zoll: Schreibweisen vereinheitlichen
    z = (s.replace("⁄", "/").replace("″", "\"").replace("”", "\"").replace("''", "\"")
         .replace("Zoll", "\"").replace("zoll", "\"").replace(" in", "\"").replace("\"", " ").strip())
    z = re.sub(r"\s+-", "-", z)
    m = _ZOLL_RE.match(z)
    if not m:
        return None
    mass, tpi_text, reihe = m.group("mass"), m.group("tpi"), (m.group("reihe") or "").upper() or None
    nummer = m.group("nummer")
    if nummer is None and mass is not None and re.fullmatch(r"\d+", mass):
        if tpi_text is None and reihe is None:
            return None  # nackte Zahl: keine Gewindeangabe
        nummer = mass  # "10-24": Nummerngröße
    if nummer is not None:
        if int(nummer) > 12:
            return None
        groesse, d_zoll = f"#{int(nummer)}", 0.060 + 0.013 * int(nummer)
    else:
        assert mass is not None
        teile = mass.split()
        d_zoll = 0.0
        for t in teile:  # "1 1/4" = 1 + 1/4
            if "/" in t:
                a, b = t.split("/")
                d_zoll += float(a) / float(b)
            else:
                d_zoll += float(t)
        groesse = "-".join(teile)
    tpi = int(tpi_text) if tpi_text else None
    kandidaten = [g for g in ZOLL if abs(g.d - d_zoll * ZOLL_MM) < 0.02]
    if tpi is not None:
        treffer = [g for g in kandidaten if abs(g.steigung - ZOLL_MM / tpi) < 1e-4]
    else:
        treffer = [g for g in kandidaten if g.reihe == (reihe or "UNC")]
    if treffer:
        return treffer[0]
    if tpi is None:
        return None  # Zollmaß ohne bekannte Steigung
    d = round(d_zoll * ZOLL_MM, 4)
    p = ZOLL_MM / tpi
    frei = kandidaten[0].durchgang if kandidaten else round(1.06 * d, 2)
    return Gewinde(_zoll_name(groesse, tpi, reihe or "UN"), d, p, round(d - 0.975 * p, 3), frei, reihe or "UN")


def naechstes(d: float, toleranz: float = 0.3, steigung: float | None = None) -> Gewinde | None:
    """Gewinde, dessen Nenndurchmesser am nächsten an ``d`` (mm) liegt, höchstens ``toleranz`` entfernt (metrisch oder
    UNC; mit ``steigung`` zählt zuerst die passende Steigung, dann auch UNF); sonst None."""
    kandidaten = [g for g in [*METRISCH.values(), *(ZOLL if steigung is not None else UNC.values())]
                  if abs(g.d - float(d)) <= toleranz]
    if steigung is not None:
        passend = [g for g in kandidaten if abs(g.steigung - steigung) < 1e-3]
        kandidaten = passend or [g for g in kandidaten if g.reihe in ("M", "UNC")]
    return min(kandidaten, key=lambda g: abs(g.d - float(d)), default=None)


def bezeichnung(d: float, gewinde: Gewinde | None = None) -> str:
    """Name für Texte: das erkannte Gewinde oder "M<d>"."""
    if gewinde is not None:
        return gewinde.name
    g = naechstes(d, 0.01)
    return g.name if g is not None else f"M{d:g}"

"""Werkstoffe, Reibwerte und Querschnitte für die Statik (KATALOG.md, Abschnitt „Mechanik“).

Werkstoffkennwerte stehen je Material im Katalog unter ``mechanik`` (Normwerte oder Datenblatt, mit Quelle und Stand;
Schätzungen sind gekennzeichnet). Fehlt ``mechanik``, rechnet die Statik das Teil nicht nach und sagt es.

Querschnittswerte der Stangenware: Fläche und Flächenmomente aus der Kontur von ``profiles.querschnitt`` (exakt für die
gezeichnete Kontur samt Radien), Torsion geschlossen (Kreisring, dünnwandig geschlossen nach Bredt, Rechteck,
offene Profile Σ b·t³/3). Achsen: ``lang`` ist die Richtung der größeren Ausdehnung des Querschnitts, ``quer`` senkrecht
dazu; ``I_lang = ∫ l² dA`` (Biegung, deren Spannung sich entlang ``lang`` ändert), ``I_quer = ∫ q² dA``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

G = 9.81  # m/s²

# Spannungsquerschnitt As (mm²) metrischer Regelgewinde nach DIN EN ISO 898-1, Tabelle 4
SPANNUNGSQUERSCHNITT = {2: 2.07, 2.5: 3.39, 3: 5.03, 4: 8.78, 5: 14.2, 6: 20.1, 8: 36.6, 10: 58.0, 12: 84.3,
                        14: 115.0, 16: 157.0, 20: 245.0, 24: 353.0}


@dataclass
class Werkstoff:
    id: str | None
    name: str
    gruppe: str = ""
    dichte: float | None = None  # g/cm³
    E: float | None = None  # N/mm²
    G: float | None = None
    nu: float | None = None
    streckgrenze: float | None = None
    zug: float | None = None
    biege: float | None = None
    druck: float | None = None
    quer: float | None = None  # Druckteile: Anteil der Festigkeit quer zu den Schichten
    quelle: str = ""
    stand: str = ""
    geschaetzt: list[str] = field(default_factory=list)
    annahme: str = ""

    @property
    def holz(self) -> bool:
        return self.gruppe in ("Holz", "Holzwerkstoff")

    @property
    def sproede(self) -> bool:
        return self.streckgrenze is None and not self.holz

    @property
    def grenze(self) -> float | None:
        """Maßgebende Festigkeit für Normalspannung (Metall: Streckgrenze, spröde und Kunststoff: Zugfestigkeit, Holz:
        Biegefestigkeit)."""
        if self.holz:
            return self.biege or self.zug
        return self.streckgrenze or self.zug

    @property
    def schub(self) -> float:
        """Schubmodul: Katalog, sonst E / (2 (1 + ν)) (ν = 0,3 angenommen)."""
        if self.G:
            return float(self.G)
        nu = self.nu if self.nu is not None else 0.3
        return float(self.E or 0.0) / (2.0 * (1.0 + nu))

    def kurz(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "e_modul": self.E, "grenze": self.grenze, "quelle": self.quelle,
                "stand": self.stand, "geschaetzt": list(self.geschaetzt), "annahme": self.annahme or None}


def werkstoff_aus_eintrag(m: dict[str, Any] | None) -> Werkstoff | None:
    """Werkstoff aus einem Katalogmaterial; None ohne ``mechanik`` (oder ohne E-Modul)."""
    if not m or not isinstance(m.get("mechanik"), dict):
        return None
    me = m["mechanik"]

    def z(k: str) -> float | None:
        v = me.get(k)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    if not z("e_modul"):
        return None
    gesch = me.get("geschaetzt")
    gesch_liste = list(gesch) if isinstance(gesch, list) else (["alle"] if gesch is True else [])
    return Werkstoff(id=m.get("id"), name=str(m.get("name") or m.get("id") or "?"), gruppe=str(m.get("gruppe") or ""),
                     dichte=m.get("dichte"), E=z("e_modul"), G=z("schubmodul"), nu=z("querkontraktion"),
                     streckgrenze=z("streckgrenze"), zug=z("zugfestigkeit"), biege=z("biegefestigkeit"),
                     druck=z("druckfestigkeit"), quer=z("quer_zur_schicht"), quelle=str(me.get("quelle") or ""),
                     stand=str(me.get("stand") or ""), geschaetzt=gesch_liste, annahme=str(me.get("annahme") or ""))


def werkstoff(katalog: Any, material: Any) -> Werkstoff | None:
    """Werkstoff zu einer Material-id, einem Alias oder Namen aus dem Katalog."""
    if katalog is None or not material:
        return None
    try:
        m = katalog.material(material) if isinstance(material, str) else None
        if m is None:
            m = katalog.find_material(material, include_proposed=True)
    except Exception:  # noqa: BLE001
        return None
    return werkstoff_aus_eintrag(m)


def reibwert(katalog: Any, a: Any, b: Any) -> dict[str, Any] | None:
    if katalog is None or not hasattr(katalog, "reibwert"):
        return None
    try:
        return katalog.reibwert(a, b)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------------------------------------------------
# Querschnitte


@dataclass
class Querschnitt:
    art: str
    A: float  # mm²
    I_lang: float  # mm⁴, ∫ l² dA
    I_quer: float  # mm⁴, ∫ q² dA
    J: float  # mm⁴ Torsionsträgheitsmoment
    c_lang: float  # mm, größter Abstand vom Schwerpunkt entlang lang
    c_quer: float
    Wt: float  # mm³ Torsionswiderstandsmoment
    lang_2d: tuple[float, float] = (1.0, 0.0)  # Richtung lang im System der Profilkontur (profiles.querschnitt)
    isotrop: bool = False
    hinweis: str = ""

    @property
    def W_lang(self) -> float:
        return self.I_lang / self.c_lang if self.c_lang > 0 else 0.0

    @property
    def W_quer(self) -> float:
        return self.I_quer / self.c_quer if self.c_quer > 0 else 0.0

    @property
    def radius(self) -> float:
        """Halbe größte Ausdehnung (Darstellung)."""
        return max(self.c_lang, self.c_quer)

    def kurz(self) -> dict[str, Any]:
        return {"A": round(self.A, 2), "I_lang": round(self.I_lang, 1), "I_quer": round(self.I_quer, 1),
                "J": round(self.J, 1), "W_lang": round(self.W_lang, 2), "W_quer": round(self.W_quer, 2)}


def _num(masse: dict[str, Any], k: str, default: float | None = None) -> float | None:
    v = (masse or {}).get(k)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _torsion(art: str, m: dict[str, Any], A: float, c_max: float) -> tuple[float, float, str]:
    """(J, Wt, Hinweis) je Art, geschlossen."""
    if art == "rohr":
        d, s = _num(m, "d"), _num(m, "s")
        di = d - 2 * s
        J = math.pi / 32 * (d ** 4 - di ** 4)
        return J, J / (d / 2), ""
    if art == "rund":
        d = _num(m, "d")
        J = math.pi / 32 * d ** 4
        return J, J / (d / 2), ""
    if art in ("vierkantrohr", "rechteckrohr"):
        s = _num(m, "s")
        b = _num(m, "a") if art == "vierkantrohr" else _num(m, "b")
        h = _num(m, "a") if art == "vierkantrohr" else _num(m, "h")
        Am = (b - s) * (h - s)
        Um = 2 * ((b - s) + (h - s))
        return 4 * Am * Am * s / Um, 2 * Am * s, "Torsion nach Bredt (dünnwandig geschlossen)"
    if art in ("flach", "vierkant", "holz"):
        if art == "flach":
            b, h = _num(m, "b"), _num(m, "s")
        elif art == "vierkant":
            b = h = _num(m, "a")
        else:
            b, h = _num(m, "b"), _num(m, "h")
        b, h = max(b, h), min(b, h)
        r = h / b
        beta = (1 - 0.63 * r + 0.052 * r ** 5) / 3
        alpha = 1 / (3 + 1.8 * r)
        return beta * b * h ** 3, alpha * b * h * h, ""
    if art == "winkel":
        a, b, s = _num(m, "a"), _num(m, "b"), _num(m, "s")
        J = (a + b - s) * s ** 3 / 3
        return J, J / s, "offenes Profil (Σ b·t³/3)"
    if art == "u_profil":
        h, b, s, t = _num(m, "h"), _num(m, "b"), _num(m, "s"), _num(m, "t")
        J = (h * s ** 3 + 2 * b * t ** 3) / 3
        return J, J / max(s, t), "offenes Profil (Σ b·t³/3)"
    # Nutprofil und Unbekanntes: grob über das polare Moment (Schätzung)
    return 0.0, 0.0, "Torsion geschätzt"


@lru_cache(maxsize=512)
def _querschnitt_cached(art: str, masse_key: tuple) -> Querschnitt:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from kevcad_kernel.profiles import querschnitt as kontur

    masse = dict(masse_key)
    face = kontur(art, masse)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, props)
    A = float(props.Mass())
    c = props.CentreOfMass()
    M = props.MatrixOfInertia()
    Ixx = float(M.Value(1, 1))  # ∫ (y² + z²) dA = ∫ y² dA in der XY-Ebene
    Iyy = float(M.Value(2, 2))  # ∫ x² dA
    bb = face.bounding_box()
    cx, cy = float(c.X()), float(c.Y())
    ex_lo, ex_hi = float(bb.min.X) - cx, float(bb.max.X) - cx
    ey_lo, ey_hi = float(bb.min.Y) - cy, float(bb.max.Y) - cy
    breite_x, breite_y = float(bb.size.X), float(bb.size.Y)
    if breite_x >= breite_y:
        lang_2d, I_lang, I_quer = (1.0, 0.0), Iyy, Ixx
        c_lang, c_quer = max(-ex_lo, ex_hi), max(-ey_lo, ey_hi)
    else:
        lang_2d, I_lang, I_quer = (0.0, 1.0), Ixx, Iyy
        c_lang, c_quer = max(-ey_lo, ey_hi), max(-ex_lo, ex_hi)
    J, Wt, hinweis = _torsion(art, masse, A, max(c_lang, c_quer))
    if J <= 0:
        J = 0.3 * (I_lang + I_quer)
        Wt = J / max(c_lang, c_quer)
    isotrop = art in ("rohr", "rund", "vierkantrohr", "vierkant") or (
        art == "nutprofil" and abs(I_lang - I_quer) < 1e-3 * max(I_lang, I_quer))
    if art == "nutprofil":
        # Die gezeichnete Kontur ist voller als echte Profile: Fläche auf den Richtwert (profiles.flaeche_mm2) und die
        # Momente im selben Verhältnis verkleinern (40 × 40 leicht: rund 7,9 cm⁴, Herstellerwerte um 7 bis 8 cm⁴)
        from kevcad_kernel.profiles import flaeche_mm2

        f = flaeche_mm2(art, masse) / A if A > 0 else 1.0
        A, I_lang, I_quer, J, Wt = A * f, I_lang * f, I_quer * f, J * f, Wt * f
        hinweis = (hinweis + "; " if hinweis else "") + ("Querschnittswerte aus der vereinfachten Nutkontur, auf die "
                                                         "Richtwert-Fläche skaliert")
    if art == "winkel" or art == "u_profil":
        hinweis = (hinweis + "; " if hinweis else "") + "Biegung um die Achsen parallel zu den Schenkeln (vereinfacht)"
    return Querschnitt(art, A, I_lang, I_quer, J, c_lang, c_quer, Wt, lang_2d, isotrop, hinweis)


def querschnitt(art: str, masse: dict[str, Any]) -> Querschnitt:
    """Querschnittswerte eines Lagerteils (Stangenware) nach Art und Maßen (zwischengespeichert)."""
    key = tuple(sorted((k, v) for k, v in (masse or {}).items() if isinstance(v, (int, float, str))))
    return _querschnitt_cached(art, key)


def spannungsquerschnitt(d: float | None) -> float | None:
    if not d:
        return None
    k = min(SPANNUNGSQUERSCHNITT, key=lambda x: abs(x - float(d)))
    if abs(k - float(d)) > 0.6:
        return math.pi / 4 * (0.85 * float(d)) ** 2  # grob über den Kerndurchmesser
    return SPANNUNGSQUERSCHNITT[k]

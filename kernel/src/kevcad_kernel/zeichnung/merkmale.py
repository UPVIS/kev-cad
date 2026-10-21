"""Merkmalerkennung je Teil (öffentliche Schnittstelle, auch für den Bauplan): ``erkenne(form, info) -> Merkmale``.

Erkannt werden, alle Werte im lokalen System des Teils (teilsystem.py, mm, Ursprung in der Ecke des Hüllquaders):

| art | Kennung | werte (Auszug) |
|---|---|---|
| ``huelle`` | ``huelle`` | ``groesse`` [x, y, z] |
| ``seite`` | ``seite:x-`` … ``seite:z+`` | Ebene des Hüllquaders (Bezugskanten der Ansichten) |
| ``stange`` | ``stange`` | ``laenge`` (Zuschnitt an der längsten Kante), ``gehrung`` [a, b] in Grad, ``profil`` |
| ``bohrung`` | ``bohrung:1`` … | ``d``, ``tiefe`` (None = durch), ``durch``, ``eintritt``, ``achse``, ``senkung``, ``gegenbohrung``, ``gewinde``, ``fuer``, ``tropfen``, ``lage_mm``/``von`` bei Stangen, ``welt`` |
| ``einsatztasche`` | ``einsatztasche:1`` | wie Bohrung, dazu ``einsatz`` (z. B. „M4 × 8,1“) |
| ``muttertasche`` | ``muttertasche:1`` | ``sw`` (Schlüsselweite), ``tiefe``, ``gewinde`` |
| ``langloch`` | ``langloch:1`` | ``breite``, ``laenge``, ``mitten`` (zwei Punkte), ``tiefe``, ``durch`` |
| ``lochbild`` | ``lochbild:1`` | ``muster`` reihe/raster/kreis/paar, ``n``, ``d``, ``teilung``, ``tk_d`` … (``teile`` = Bohrungen) |
| ``tasche`` / ``absatz`` | ``tasche:1`` | ``tiefe`` bzw. ``hoehe``, ``boden`` (Ebene), ``ausdehnung`` |
| ``fase`` | ``fase:1`` | ``a``, ``b`` (Schenkel), ``winkel``, ``n`` (gleiche Fasen), ``text`` |
| ``radius`` | ``radius:1`` | ``r``, ``innen`` (Kehle), ``n`` (gleiche Radien) |

Jedes Merkmal hat eine ``signatur`` (DOKUMENTE.md, Bezüge): ``typ``, ``mitte``, ``richtung``, ``radius``, ``laenge``,
mit der Bezüge nach einem neuen Lauf wiedergefunden werden. Gewinde, Einsatz- und Muttertaschen erkennt Kev CAD aus
dem Zusammenbau (``umgebung``: Schrauben, Gewindestifte, Gewindeeinsätze und Muttern auf derselben Achse) und den
Tabellen für Kernloch, Durchgang und Einsätze; ohne Gegenstück nennt es nur den Durchmesser (lieber vorsichtig als
ein erfundenes Gewinde).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.teilsystem import Teilsystem, teilsystem
from kevcad_kernel.zeichnung.topologie import Flaeche, Topologie, analysiere

# Regelgewinde ISO 261: Steigung; Kernloch = d − P (ISO 2306, gerundet wie in den Bohrertabellen)
STEIGUNG = {2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5}
KERNLOCH = {2: 1.6, 2.5: 2.05, 3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 14: 12.0, 16: 14.0,
            20: 17.5}
DURCHGANG = {2: 2.4, 2.5: 2.9, 3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 14: 15.5, 16: 17.5,
             20: 22.0}  # ISO 273 mittel
EINSATZ_BOHRUNG = {2: 3.2, 2.5: 4.0, 3: 4.0, 4: 5.6, 5: 6.4, 6: 8.0, 8: 9.6, 10: 12.0}  # ruthex (3d-druck.md)
MUTTER_SW = {2: 4.0, 2.5: 5.0, 3: 5.5, 4: 7.0, 5: 8.0, 6: 10.0, 8: 13.0, 10: 16.0}  # ISO 4032

TOL_ACHSE = 0.02  # mm: koaxial
TOL_PARALLEL = 1e-5  # 1 − |cos|


def zahl(x: float, stellen: int = 2) -> str:
    """Deutsche Zahl für Maßtexte: 6.6 → „6,6“, 12.0 → „12“, 0.5 → „0,5“ (ISO 129-1: ohne überflüssige Nullen)."""
    v = round(float(x), stellen)
    if abs(v - round(v)) < 10 ** -(stellen + 1):
        s = str(int(round(v)))
    else:
        s = f"{v:.{stellen}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",").replace("-", "−") if s != "-0" else "0"


def gewinde_text(d: float) -> str:
    return f"M{zahl(d, 1)}"


def _r(v: Any, n: int = 4) -> Any:
    if v is None:
        return None
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_r(x, n) for x in v]
    x = round(float(v), n)
    return 0.0 if x == 0 else x


@dataclass
class Merkmal:
    id: str
    art: str
    signatur: dict[str, Any]
    werte: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    flaechen: list[int] = field(default_factory=list)
    teile: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        def clean(v: Any) -> Any:
            if isinstance(v, np.ndarray):
                return _r(v.tolist())
            if isinstance(v, dict):
                return {k: clean(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [clean(x) for x in v]
            if isinstance(v, (float, np.floating)):
                return _r(v)
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.bool_):
                return bool(v)
            return v

        return {"id": self.id, "art": self.art, "signatur": clean(self.signatur), "werte": clean(self.werte),
                "text": self.text, "flaechen": list(self.flaechen), "teile": list(self.teile)}


@dataclass
class Kante:
    """Kante des Teils (lokal) für Klicks und Bezüge ohne Merkmal."""

    index: int
    typ: str  # linie | kreis | andere
    mitte: np.ndarray
    richtung: np.ndarray | None
    radius: float | None
    laenge: float
    a: np.ndarray  # Anfang
    b: np.ndarray  # Ende
    punkte: np.ndarray  # Polylinie (n, 3) lokal


@dataclass
class Merkmale:
    teil: str
    system: Teilsystem
    liste: list[Merkmal]
    info: dict[str, Any] = field(default_factory=dict)
    kanten: list[Kante] = field(default_factory=list)
    punkte: list[np.ndarray] = field(default_factory=list)
    ms: float = 0.0

    def get(self, mid: str) -> Merkmal | None:
        return next((m for m in self.liste if m.id == mid), None)

    def von_art(self, *arten: str) -> list[Merkmal]:
        return [m for m in self.liste if m.art in arten]

    @property
    def groesse(self) -> np.ndarray:
        return np.asarray(self.system.groesse, dtype=float)

    def als_dict(self) -> dict[str, Any]:
        return {"teil": self.teil, "system": self.system.als_dict(), "info": self.info,
                "merkmale": [m.als_dict() for m in self.liste]}


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------------------------------------------------


def _koaxial(p1: np.ndarray, d1: np.ndarray, p2: np.ndarray, d2: np.ndarray, tol: float = TOL_ACHSE) -> bool:
    if abs(float(np.dot(d1, d2))) < 1 - TOL_PARALLEL:
        return False
    off = p2 - p1
    return float(np.linalg.norm(off - d1 * float(np.dot(off, d1)))) < tol


def _achse_positiv(d: np.ndarray) -> np.ndarray:
    i = int(np.argmax(np.abs(d)))
    return d if d[i] >= 0 else -d


def _solids(form: Any) -> list[Any]:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    shape = form.wrapped if hasattr(form, "wrapped") else form
    out = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(exp.Current())
        exp.Next()
    return out


class _Klassifizierer:
    """Punkt im Material? (BRepClass3d_SolidClassifier je Körper)"""

    def __init__(self, form: Any) -> None:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier

        self._cls = [BRepClass3d_SolidClassifier(s) for s in _solids(form)]

    def innen(self, p: np.ndarray, tol: float = 1e-4) -> bool:
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_IN

        pnt = gp_Pnt(float(p[0]), float(p[1]), float(p[2]))
        for c in self._cls:
            c.Perform(pnt, tol)
            if c.State() == TopAbs_IN:
                return True
        return False


def _norm_gewinde(text: Any) -> float | None:
    """„M6-1.0“, „M6“, „m4“ → 6.0."""
    if text is None:
        return None
    s = str(text).strip().upper().replace(",", ".")
    if not s.startswith("M"):
        return None
    num = ""
    for ch in s[1:]:
        if ch.isdigit() or ch == ".":
            num += ch
        else:
            break
    try:
        return float(num)
    except ValueError:
        return None


def _nahe(x: float, tab: dict[float, float], tol: float) -> float | None:
    best = None
    for k, v in tab.items():
        if abs(x - v) <= tol and (best is None or abs(x - v) < abs(x - tab[best])):
            best = k
    return best


# ---------------------------------------------------------------------------------------------------------------------
# Erkennung
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Ctx:
    form: Any
    top: Topologie
    sys: Teilsystem
    info: dict[str, Any]
    umgebung: list[dict[str, Any]]
    druckteil: bool
    benutzt: set[int] = field(default_factory=set)  # Flächen, die schon einem Merkmal gehören
    _cls: _Klassifizierer | None = None

    @property
    def cls(self) -> _Klassifizierer:
        if self._cls is None:
            self._cls = _Klassifizierer(self.form)
        return self._cls

    def lp(self, p: Any) -> np.ndarray:
        return self.sys.lokal(p)

    def ld(self, d: Any) -> np.ndarray:
        return self.sys.richtung_lokal(d)


def erkenne(form: Any, info: dict[str, Any] | None = None, *, name: str = "", system: Teilsystem | None = None,
            umgebung: list[dict[str, Any]] | None = None, kanten: bool = True) -> Merkmale:
    """Merkmale eines Teils (Modulbeschreibung). ``info``: Teilekopf-Felder ``stock``, ``druckteil``, ``material`` und
    ``katalog`` (Lagerteil-Eintrag); ``umgebung``: Verbindungsmittel in der Nähe (siehe ``verbindungsmittel``),
    Weltkoordinaten. ``system``: vorgegebenes lokales System (sonst die Hauptlage aus teilsystem.py)."""
    t0 = time.perf_counter()
    from build123d import Shape

    shape = form if isinstance(form, Shape) else Shape.cast(form)
    info = dict(info or {})
    top = analysiere(shape)
    sys = system or teilsystem(shape, info, top)
    druck = bool(info.get("druckteil")) or str(info.get("material") or "").lower() in ("petg", "pla", "asa", "abs")
    ctx = _Ctx(shape, top, sys, info, list(umgebung or []), druck)
    liste: list[Merkmal] = []
    liste += _huelle(ctx)
    stange = _stange(ctx)
    if stange is not None:
        liste.append(stange)
        liste += _stirnseiten(ctx)
    bohrungen, langloecher = _bohrungen(ctx)
    liste += bohrungen
    liste += langloecher
    liste += _muttertaschen(ctx)
    liste += _lochbilder(ctx, [m for m in bohrungen if m.art in ("bohrung", "einsatztasche")])
    liste += _taschen(ctx)
    liste += _fasen(ctx)
    liste += _radien(ctx)
    if stange is not None:
        _lage_ab_ende(stange, [m for m in liste if m.art in ("bohrung", "einsatztasche", "langloch")])
    out = Merkmale(name or str(getattr(shape, "label", "") or ""), sys, liste, _info_text(info, sys))
    if kanten:
        out.kanten, out.punkte = _kanten(ctx)
    out.ms = (time.perf_counter() - t0) * 1000.0
    return out


def _info_text(info: dict[str, Any], sys: Teilsystem) -> dict[str, Any]:
    st = info.get("stock") or {}
    kat = info.get("katalog") or {}
    out = {"art": sys.art, "lagerteil": st.get("id"), "halbzeug": kat.get("name") or st.get("name"),
           "lager_art": kat.get("art"), "druckteil": bool(info.get("druckteil")), "material": info.get("material")}
    return {k: v for k, v in out.items() if v not in (None, "")}


# -- Hülle und Seiten --------------------------------------------------------------------------------------------------


def _huelle(ctx: _Ctx) -> list[Merkmal]:
    g = np.asarray(ctx.sys.groesse, dtype=float)
    out = [Merkmal("huelle", "huelle", {"typ": "box", "mitte": g / 2, "richtung": None, "radius": None,
                                        "laenge": float(g.max())},
                   {"groesse": g}, f"{zahl(g[0])} × {zahl(g[1])} × {zahl(g[2])}")]
    namen = "xyz"
    for i in range(3):
        for s, zeichen in ((-1, "-"), (1, "+")):
            p = g / 2
            p = p.copy()
            p[i] = 0.0 if s < 0 else g[i]
            n = np.zeros(3)
            n[i] = s
            out.append(Merkmal(f"seite:{namen[i]}{zeichen}", "seite",
                               {"typ": "ebene", "mitte": p, "richtung": n, "radius": None, "laenge": None},
                               {"achse": i, "seite": s}))
    return out


# -- Stange -----------------------------------------------------------------------------------------------------------


def _stange(ctx: _Ctx) -> Merkmal | None:
    if ctx.sys.art != "stange":
        return None
    g = ctx.sys.groesse
    st = ctx.info.get("stock") or {}
    kat = ctx.info.get("katalog") or {}
    laenge = float(g[0])
    gehrung = [0.0, 0.0]
    flaechen = []
    # Stirnseiten: ebene Flächen an den Enden; Gehrung = Winkel der Normale zur Stangenachse
    for f in ctx.top.flaechen:
        if f.typ != "ebene" or f.n is None:
            continue
        n = ctx.ld(f.n)
        lo, hi = _lokal_box(ctx, f)
        if abs(n[0]) < 0.2:
            continue
        ende = 0 if n[0] < 0 else 1
        if (ende == 0 and lo[0] > 0.5 * g[0]) or (ende == 1 and hi[0] < 0.5 * g[0]):
            continue
        w = math.degrees(math.acos(min(1.0, abs(float(n[0])))))
        if w > abs(gehrung[ende]) + 1e-6:
            gehrung[ende] = round(w, 3)
        flaechen.append(f.index)
    profil = kat.get("name") or st.get("name") or ""
    werte = {"laenge": laenge, "gehrung": gehrung, "profil": profil, "lager_laenge": st.get("laenge"),
             "querschnitt": [float(g[1]), float(g[2])]}
    text = f"L = {zahl(laenge, 1)}"
    if any(abs(x) > 0.05 for x in gehrung):
        text += f", Gehrung {zahl(gehrung[0], 1)}° / {zahl(gehrung[1], 1)}°"
    return Merkmal("stange", "stange", {"typ": "linie", "mitte": g / 2, "richtung": np.array([1.0, 0.0, 0.0]),
                                        "radius": None, "laenge": laenge}, werte, text, flaechen)


def _stirnseiten(ctx: _Ctx) -> list[Merkmal]:
    """Stirnflächen an Ende A (x = 0) und Ende B (x = L): größte ebene Fläche je Ende, mit echter Normale (Gehrung)."""
    g = ctx.sys.groesse
    out = []
    for ende, s in (("a", -1.0), ("b", 1.0)):
        best = None
        for f in ctx.top.flaechen:
            if f.typ != "ebene" or f.n is None:
                continue
            n = ctx.ld(f.n)
            if n[0] * s < 0.2:
                continue
            lo, hi = _lokal_box(ctx, f)
            if (s < 0 and lo[0] > 0.5 * g[0]) or (s > 0 and hi[0] < 0.5 * g[0]):
                continue
            if best is None or f.flaeche > best[0].flaeche:
                best = (f, n)
        if best is None:
            continue
        f, n = best
        w = math.degrees(math.acos(min(1.0, abs(float(n[0])))))
        sig = {"typ": "ebene", "mitte": ctx.lp(f.punkt), "richtung": n, "radius": None, "laenge": None}
        out.append(Merkmal(f"ende:{ende}", "stirnseite", sig, {"gehrung": w, "ende": ende}, "", [f.index]))
    return out


def _lage_ab_ende(stange: Merkmal, merkmale: list[Merkmal]) -> None:
    """Bei Stangenware: Lage jedes Merkmals ab dem Ende A (x = 0, linkes Ende der Vorderansicht)."""
    for m in merkmale:
        c = np.asarray(m.signatur.get("mitte"), dtype=float)
        m.werte["lage_mm"] = [round(float(c[0]), 3)]
        m.werte["von"] = "Ende A (links)"
        if m.art == "langloch" and m.werte.get("mitten"):
            m.werte["lage_mm"] = [round(float(p[0]), 3) for p in m.werte["mitten"]]


def _lokal_box(ctx: _Ctx, f: Flaeche) -> tuple[np.ndarray, np.ndarray]:
    """Hüllquader einer Fläche im lokalen System (aus den Ecken des Welt-Quaders; achsparallel exakt)."""
    lo, hi = f.lo, f.hi
    ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    loc = ctx.lp(ecken)
    return loc.min(axis=0), loc.max(axis=0)


# -- Bohrungen, Einsatztaschen, Langlöcher ----------------------------------------------------------------------------


@dataclass
class _Abschnitt:
    r: float
    t0: float
    t1: float
    spanne: float
    flaechen: list[int]
    kegel: bool = False
    halbwinkel: float | None = None
    r1: float | None = None  # Kegel: Radius bei t0 und t1
    r2: float | None = None


def _bohrungen(ctx: _Ctx) -> tuple[list[Merkmal], list[Merkmal]]:
    """Koaxiale, nach innen gewölbte Zylinder- und Kegelflächen zu Bohrungen zusammenfassen."""
    gruppen: list[dict[str, Any]] = []  # {"p", "d", "flaechen": [Flaeche]}
    for f in ctx.top.flaechen:
        if f.typ not in ("zylinder", "kegel") or not f.innen or f.achse is None:
            continue
        d = _achse_positiv(f.achse / np.linalg.norm(f.achse))
        for g in gruppen:
            if _koaxial(g["p"], g["d"], f.punkt, d):
                g["flaechen"].append(f)
                break
        else:
            gruppen.append({"p": f.punkt, "d": d, "flaechen": [f]})
    bohrungen: list[dict[str, Any]] = []
    halbe: list[tuple[Flaeche, np.ndarray, np.ndarray]] = []  # Kandidaten für Langlöcher
    for g in gruppen:
        p0, d = g["p"], g["d"]
        abschnitte: list[_Abschnitt] = []
        for f in g["flaechen"]:
            off = float(np.dot(f.punkt - p0, d))
            s = 1.0 if float(np.dot(f.achse, d)) > 0 else -1.0
            t0, t1 = sorted((off + s * f.t[0], off + s * f.t[1]))
            if f.typ == "kegel":
                hw = float(f.halbwinkel or 0.0)
                ra, rb = f.radien or (float(f.radius or 0.0), float(f.radius or 0.0))
                if s < 0:
                    ra, rb = rb, ra
                abschnitte.append(_Abschnitt(max(ra, rb), t0, t1, f.spanne, [f.index], True, hw, ra, rb))
                continue
            for a in abschnitte:  # Nahtteilung: gleiche Fläche in zwei Hälften
                if not a.kegel and abs(a.r - f.radius) < 1e-4 and abs(a.t0 - t0) < 1e-3 and abs(a.t1 - t1) < 1e-3:
                    a.spanne += f.spanne
                    a.flaechen.append(f.index)
                    break
            else:
                abschnitte.append(_Abschnitt(float(f.radius), t0, t1, f.spanne, [f.index]))
        voll = [a for a in abschnitte if not a.kegel and a.spanne >= 359.0]
        teil = [a for a in abschnitte if not a.kegel and 175.0 <= a.spanne < 359.0]
        if not voll and not teil:
            for f in g["flaechen"]:
                if f.typ == "zylinder" and 170.0 <= f.spanne <= 190.0:
                    halbe.append((f, p0, d))
            continue
        # Halbe Zylinder (Spanne ≈ 180°) ohne Vollkreis gehören eher zu Langlöchern
        if not voll and all(170.0 <= a.spanne <= 190.0 for a in teil):
            for f in g["flaechen"]:
                if f.typ == "zylinder":
                    halbe.append((f, p0, d))
            continue
        if ctx.sys.art == "stange" and _profilbohrung(ctx, p0, d, abschnitte):
            continue  # Innenseite eines Rohrs: Profil, keine Bohrung
        bohrungen.append({"p": p0, "d": d, "abschnitte": sorted(abschnitte, key=lambda a: a.t0),
                          "flaechen": [f.index for f in g["flaechen"]]})
    merkmale = [_bohrung_merkmal(ctx, b) for b in bohrungen]
    merkmale = [m for m in merkmale if m is not None]
    # sortieren: x, dann z, dann y (lokal), Kennungen je Art durchzählen
    merkmale.sort(key=lambda m: tuple(round(float(v), 2) for v in (m.signatur["mitte"][0], m.signatur["mitte"][2],
                                                                    m.signatur["mitte"][1])))
    zaehler: dict[str, int] = {}
    for m in merkmale:
        zaehler[m.art] = zaehler.get(m.art, 0) + 1
        m.id = f"{m.art}:{zaehler[m.art]}"
        ctx.benutzt.update(m.flaechen)
    langloecher = _langloecher(ctx, halbe)
    return merkmale, langloecher


def _profilbohrung(ctx: _Ctx, p0: np.ndarray, d: np.ndarray, abschnitte: list[_Abschnitt]) -> bool:
    """Bohrung entlang der Stangenachse über (fast) die ganze Länge: die Innenkontur des Profils (Rohr)."""
    x = ctx.sys.achsen[0]
    if abs(float(np.dot(d, x))) < 1 - 1e-4:
        return False
    laenge = max(a.t1 for a in abschnitte) - min(a.t0 for a in abschnitte)
    return laenge >= 0.9 * float(ctx.sys.groesse[0])


def _bohrung_merkmal(ctx: _Ctx, b: dict[str, Any]) -> Merkmal | None:
    p0, d = b["p"], b["d"]
    ab: list[_Abschnitt] = b["abschnitte"]
    zyl = [a for a in ab if not a.kegel]
    if not zyl:
        return None
    t_lo = min(a.t0 for a in ab)
    t_hi = max(a.t1 for a in ab)
    eps = 0.05
    r_min = min(a.r for a in zyl)
    # offen an einem Ende, wenn der Punkt kurz dahinter auf der Achse nicht im Material liegt
    offen_lo = not ctx.cls.innen(p0 + d * (t_lo - eps))
    offen_hi = not ctx.cls.innen(p0 + d * (t_hi + eps))
    # Lücken (Querbohrung durch beide Rohrwände): Abschnitte ohne Überlappung
    luecken = []
    spans = sorted((a.t0, a.t1) for a in ab)
    ende = spans[0][1]
    for s0, s1 in spans[1:]:
        if s0 > ende + 1e-3:
            luecken.append((ende, s0))
        ende = max(ende, s1)
    durch = offen_lo and offen_hi
    # Eintritt (ISO-Angabe von der Seite, an der gebohrt wird): das offene Ende; bei Durchgang das Ende mit
    # Gegenbohrung, sonst mit echter Senkung (mehr als 0,8 mm über dem Bohrungsradius; kleinere Kegel sind Kantenfasen),
    # sonst das Ende auf der Seite des Betrachters der Vorder- bzw. Draufsicht
    def punkte(ende_lo: bool) -> int:
        t_end = t_lo if ende_lo else t_hi
        r_end = max((a.r for a in zyl if (a.t0 <= t_end + 1e-3 if ende_lo else a.t1 >= t_end - 1e-3)), default=r_min)
        kg = next((a for a in ab if a.kegel and (a.t0 <= t_end + 1e-3 if ende_lo else a.t1 >= t_end - 1e-3)), None)
        wert = 0
        if r_end > r_min + 0.05:
            wert = 3
        elif kg is not None and max(kg.r1 or 0, kg.r2 or 0) > r_min + 0.8:
            wert = 2
        return wert

    if offen_lo and not offen_hi:
        von_lo = True
    elif offen_hi and not offen_lo:
        von_lo = False
    elif punkte(True) != punkte(False):
        von_lo = punkte(True) > punkte(False)
    else:
        dl = ctx.ld(d)
        if abs(dl[1]) > 1e-6:
            von_lo = float(dl[1]) > 0  # Betrachter der Vorderansicht steht bei lokal −y
        elif abs(dl[2]) > 1e-6:
            von_lo = float(dl[2]) < 0  # Betrachter der Draufsicht steht oben (+z)
        else:
            von_lo = float(dl[0]) > 0
    richtung = d if von_lo else -d
    t_ein = t_lo if von_lo else t_hi

    # Abschnitte vom Eintritt aus sortieren
    reihe = sorted(ab, key=lambda a: a.t0 if von_lo else -a.t1)
    gegen = None
    senkung = None
    kantenfasen: list[float] = []
    for a in ab:  # Kegel an den Enden: Senkung (groß, am Eintritt) oder Kantenfase (klein)
        if not a.kegel or (a.halbwinkel or 0) < 20:
            continue
        r_aussen = max(a.r1 or 0, a.r2 or 0)
        am_eintritt = a is reihe[0]
        if am_eintritt and r_aussen > r_min + 0.8:
            senkung = {"d": 2 * r_aussen, "winkel": 2 * float(a.halbwinkel or 0)}
        elif r_aussen > r_min + 0.01 and (a.t0 <= t_lo + 1e-3 or a.t1 >= t_hi - 1e-3):
            kantenfasen.append(round(r_aussen - min(a.r1 or 0, a.r2 or 0), 3))
    zyl_reihe = [a for a in reihe if not a.kegel]
    if len(zyl_reihe) >= 2 and zyl_reihe[0].r > min(z.r for z in zyl_reihe) + 0.05 and not luecken:
        haupt = min(zyl_reihe, key=lambda a: a.r)
        g0 = zyl_reihe[0]
        gegen = {"d": 2 * g0.r, "tiefe": round(g0.t1 - g0.t0, 4)}
        r_haupt = haupt.r
    else:
        r_haupt = r_min
    d_haupt = 2 * r_haupt
    tiefe = None
    if not durch:
        # Tiefe bis zum Ende des zylindrischen Teils (ohne Bohrspitze), ab Eintritt
        if von_lo:
            tiefe = round(max(a.t1 for a in zyl) - t_lo, 4)
        else:
            tiefe = round(t_hi - min(a.t0 for a in zyl), 4)
    spitze = None
    letzt = reihe[-1]
    if not durch and letzt.kegel:
        spitze = round(2 * float(letzt.halbwinkel or 0), 1)
    tropfen = any(a.spanne < 359.0 for a in zyl)
    eintritt_w = p0 + d * t_ein
    eintritt = ctx.lp(eintritt_w)
    achse = ctx.ld(richtung)
    werte: dict[str, Any] = {"d": d_haupt, "tiefe": tiefe, "durch": durch, "eintritt": eintritt, "achse": achse,
                             "senkung": senkung, "gegenbohrung": gegen, "gewinde": None, "fuer": None,
                             "tropfen": tropfen, "spitze": spitze, "waende": len(luecken) + 1,
                             "kantenfasen": kantenfasen,
                             "laenge": round(t_hi - t_lo, 4),
                             "welt": {"mitte": eintritt_w, "richtung": richtung}}
    art = "bohrung"
    # Gegenstück im Zusammenbau: Schraube, Gewindestift, Einsatz, Mutter auf derselben Achse
    gegenstueck = _gegenstueck(ctx, p0, d, t_lo, t_hi)
    if gegenstueck is not None:
        g_art, g_d, g_text = gegenstueck["art"], float(gegenstueck.get("d") or 0), gegenstueck.get("text") or ""
        if g_art == "gewindeeinsatz":
            art = "einsatztasche"
            werte["einsatz"] = g_text or gewinde_text(g_d)
            werte["gewinde"] = gewinde_text(g_d)
        elif g_art in ("schraube", "gewindestift") and g_d > 0:
            kern = KERNLOCH.get(g_d) or g_d - STEIGUNG.get(g_d, 0.15 * g_d)
            if abs(d_haupt - kern) <= 0.25 or (ctx.druckteil and kern - 0.3 <= d_haupt < g_d - 0.05):
                werte["gewinde"] = gewinde_text(g_d)
                werte["gewinde_tiefe"] = tiefe
            elif d_haupt >= g_d - 0.05:
                werte["fuer"] = gewinde_text(g_d)
        elif g_art == "mutter" and g_d > 0 and d_haupt >= g_d - 0.05:
            werte["fuer"] = gewinde_text(g_d)
        werte["gegenstueck"] = gegenstueck.get("name")
    elif ctx.druckteil and not durch:
        groesse = _nahe(d_haupt, EINSATZ_BOHRUNG, 0.35)
        if groesse is not None and d_haupt >= EINSATZ_BOHRUNG[groesse] - 0.05:
            werte["einsatz_vermutlich"] = gewinde_text(groesse)
    radius = d_haupt / 2
    flaechen = list(b["flaechen"])
    r_max = max(a.r for a in ab)
    for k in list(flaechen):
        for nb in ctx.top.flaechen[k].nachbarn:
            f = ctx.top.flaechen[nb]
            if nb in flaechen or f.typ != "ebene" or f.n is None or abs(float(np.dot(f.n, d))) < 1 - 1e-6:
                continue
            off = f.punkt - p0
            quer = float(np.linalg.norm(off - d * float(np.dot(off, d))))
            t_f = float(np.dot(off, d))
            if quer <= r_max + 1e-3 and t_lo - 1e-3 <= t_f <= t_hi + 1e-3 and f.flaeche <= math.pi * r_max ** 2 * 1.01:
                flaechen.append(nb)  # Boden eines Sacklochs oder Stufe einer Gegenbohrung
    text = _bohrung_text(art, werte)
    sig = {"typ": "kreis", "mitte": eintritt, "richtung": achse, "radius": radius, "laenge": werte["laenge"]}
    return Merkmal("", art, sig, werte, text, flaechen)


def _bohrung_text(art: str, w: dict[str, Any], anzahl: int = 1) -> str:
    """Bohrungsangabe nach ISO 129-1 / ISO 6410 (Gewinde), ISO 15786 (vereinfachte Angabe von Senkungen)."""
    vor = f"{anzahl}× " if anzahl > 1 else ""
    if w.get("gewinde") and art != "einsatztasche":
        t = f"{vor}{w['gewinde']}"
        if not w.get("durch") and w.get("gewinde_tiefe"):
            t += f" × {zahl(w['gewinde_tiefe'], 1)}"
        return t
    t = f"{vor}Ø{zahl(w['d'])}"
    if not w.get("durch") and w.get("tiefe"):
        t += f" × {zahl(w['tiefe'], 1)} tief"
    if w.get("gegenbohrung"):
        g = w["gegenbohrung"]
        t += f", Senkung Ø{zahl(g['d'])} × {zahl(g['tiefe'], 1)} tief"
    if w.get("senkung"):
        s = w["senkung"]
        t += f", Senkung {zahl(s['winkel'], 0)}° Ø{zahl(s['d'])}"
    if art == "einsatztasche" and w.get("einsatz"):
        t += f" (Einsatz {w['einsatz']})"
    return t


def verbindungsmittel(name: str, form: Any, info: dict[str, Any]) -> dict[str, Any] | None:
    """Schraube, Gewindestift, Gewindeeinsatz oder Mutter als Gegenstück für die Gewindeerkennung (Weltkoordinaten):
    {"name", "art", "d" (Nenn-Ø), "text", "p", "a" (Achse), "t" (Ausdehnung entlang a ab p)} oder None."""
    kat = info.get("katalog") or {}
    st = info.get("stock") or {}
    sid = str(st.get("id") or kat.get("id") or "")
    art = str(kat.get("art") or "")
    masse = kat.get("masse") or {}
    low = (sid + " " + str(kat.get("name") or st.get("name") or "") + " " + name).lower()
    if "gewindeeinsatz" in low or "einsatz" in sid:
        g_art = "gewindeeinsatz"
    elif "gewindestift" in low:
        g_art = "gewindestift"
    elif art == "schraube" or "schraube" in low:
        g_art = "schraube"
    elif art == "mutter" or "mutter" in low:
        g_art = "mutter"
    else:
        return None
    d = _norm_gewinde(masse.get("groesse")) or _norm_gewinde(masse.get("gewinde"))
    if d is None:
        for tok in low.replace("×", " ").replace("x", " ").split():
            d = _norm_gewinde(tok)
            if d is not None:
                break
    if d is None:
        return None
    top = analysiere(form)
    # Achse: größte Zylinderfläche
    zyl = [f for f in top.flaechen if f.typ == "zylinder" and f.achse is not None]
    if not zyl:
        return None
    f = max(zyl, key=lambda x: x.flaeche)
    a = f.achse / np.linalg.norm(f.achse)
    ecken = np.array([[x, y, z] for x in (top.lo[0], top.hi[0]) for y in (top.lo[1], top.hi[1])
                      for z in (top.lo[2], top.hi[2])])
    ts = (ecken - f.punkt) @ a
    text = gewinde_text(d)
    if g_art == "gewindeeinsatz":
        laenge = masse.get("l") or masse.get("laenge")
        if laenge:
            text += f" × {zahl(float(laenge), 1)}"
        else:
            text += f" × {zahl(float(top.groesse.max()), 1)}"
    return {"name": name, "art": g_art, "d": d, "text": text, "p": f.punkt, "a": a,
            "t": (float(ts.min()), float(ts.max()))}


def _gegenstueck(ctx: _Ctx, p0: np.ndarray, d: np.ndarray, t0: float, t1: float) -> dict[str, Any] | None:
    best = None
    for g in ctx.umgebung:
        a, p = np.asarray(g["a"], dtype=float), np.asarray(g["p"], dtype=float)
        if not _koaxial(p0, d, p, a, tol=0.3):
            continue
        s = 1.0 if float(np.dot(a, d)) > 0 else -1.0
        off = float(np.dot(p - p0, d))
        g0, g1 = sorted((off + s * g["t"][0], off + s * g["t"][1]))
        ueber = min(t1, g1) - max(t0, g0)
        if ueber <= 0.1:
            continue
        # Einsatz vor Schraube (die Schraube steckt im Einsatz, nicht im Kunststoff)
        rang = {"gewindeeinsatz": 0, "mutter": 1, "gewindestift": 2, "schraube": 2}.get(g["art"], 3)
        if best is None or (rang, -ueber) < best[0]:
            best = ((rang, -ueber), g)
    return best[1] if best else None


def _langloecher(ctx: _Ctx, halbe: list[tuple[Flaeche, np.ndarray, np.ndarray]]) -> list[Merkmal]:
    out = []
    benutzt: set[int] = set()
    for i, (f1, p1, d1) in enumerate(halbe):
        if f1.index in benutzt:
            continue
        for f2, p2, d2 in halbe[i + 1:]:
            if f2.index in benutzt or abs(float(f1.radius) - float(f2.radius)) > 1e-3:
                continue
            if abs(float(np.dot(d1, d2))) < 1 - TOL_PARALLEL:
                continue
            off = p2 - p1
            quer = off - d1 * float(np.dot(off, d1))
            dist = float(np.linalg.norm(quer))
            if dist < 1e-3:
                continue
            # Die Bögen müssen voneinander weg zeigen (Mitte der Fläche liegt außerhalb der Verbindungsstrecke)
            m1 = f1.mitte - p1
            m2 = f2.mitte - p2
            if float(np.dot(m1, quer)) > 0 or float(np.dot(m2, -quer)) > 0:
                continue
            benutzt.update((f1.index, f2.index))
            r = float(f1.radius)
            c1 = p1 + d1 * float(np.dot((f1.mitte - p1), d1))
            c2 = c1 + quer
            mitte = (c1 + c2) / 2
            tiefe = float(max(f1.t) - min(f1.t))
            durch = not ctx.cls.innen(mitte + d1 * (max(f1.t) - float(np.dot(mitte - p1, d1)) + 0.05)) and \
                not ctx.cls.innen(mitte + d1 * (min(f1.t) - float(np.dot(mitte - p1, d1)) - 0.05))
            werte = {"breite": 2 * r, "laenge": dist + 2 * r, "mitten": [ctx.lp(c1), ctx.lp(c2)],
                     "achse": ctx.ld(d1), "tiefe": None if durch else tiefe, "durch": durch,
                     "richtung": ctx.ld(quer / dist)}
            text = f"Langloch {zahl(2 * r)} × {zahl(dist + 2 * r)}"
            if not durch:
                text += f" × {zahl(tiefe, 1)} tief"
            sig = {"typ": "langloch", "mitte": ctx.lp(mitte), "richtung": ctx.ld(quer / dist), "radius": r,
                   "laenge": dist + 2 * r}
            nachbarn = [n for n in f1.nachbarn | f2.nachbarn
                        if ctx.top.flaechen[n].typ == "ebene" and ctx.top.flaechen[n].n is not None
                        and abs(float(np.dot(ctx.top.flaechen[n].n, quer / dist))) < 1e-3
                        and abs(float(np.dot(ctx.top.flaechen[n].n, d1))) < 1e-3]
            out.append(Merkmal("", "langloch", sig, werte, text, [f1.index, f2.index, *nachbarn]))
            break
    out.sort(key=lambda m: tuple(round(float(v), 2) for v in m.signatur["mitte"]))
    for k, m in enumerate(out, 1):
        m.id = f"langloch:{k}"
        ctx.benutzt.update(m.flaechen)
    return out


# -- Muttertaschen (Sechskant) ----------------------------------------------------------------------------------------


def _muttertaschen(ctx: _Ctx) -> list[Merkmal]:
    """Sechs ebene Wände, deren äußere Normalen zur gemeinsamen Mitte zeigen, paarweise gegenüber im Abstand SW."""
    ebenen = [f for f in ctx.top.flaechen if f.typ == "ebene" and f.n is not None and f.index not in ctx.benutzt
              and f.flaeche < 2000]
    paare = []
    for i, a in enumerate(ebenen):
        for b in ebenen[i + 1:]:
            if float(np.dot(a.n, b.n)) > -1 + 1e-6:
                continue
            sw = float(np.dot(b.punkt - a.punkt, a.n))
            if sw <= 0.5 or sw > 60:  # Wände zeigen zueinander (Tasche): b liegt vor a
                continue
            paare.append((a, b, sw))
    out = []
    benutzt: set[int] = set()
    for i, (a1, b1, sw) in enumerate(paare):
        if a1.index in benutzt:
            continue
        gruppe = [(a1, b1)]
        mitte1 = (a1.punkt + b1.punkt) / 2
        for a2, b2, sw2 in paare[i + 1:]:
            if abs(sw2 - sw) > 0.02 or a2.index in benutzt or b2.index in benutzt:
                continue
            cos = abs(float(np.dot(a1.n, a2.n)))
            if abs(cos - 0.5) > 1e-3:
                continue
            gruppe.append((a2, b2))
            if len(gruppe) == 3:
                break
        if len(gruppe) < 3:
            continue
        achse = np.cross(gruppe[0][0].n, gruppe[1][0].n)
        achse = _achse_positiv(achse / np.linalg.norm(achse))
        # gemeinsame Mittelachse: Mitten der Paare liegen auf einer Geraden entlang achse
        mitten = [(a.punkt + b.punkt) / 2 for a, b in gruppe]
        ok = all(np.linalg.norm((m - mitte1) - achse * float(np.dot(m - mitte1, achse))) < 0.05 for m in mitten)
        if not ok:
            continue
        flaechen = [x.index for a, b in gruppe for x in (a, b)]
        benutzt.update(flaechen)
        lo = min(float(np.dot(ctx.top.flaechen[k].lo - mitte1, achse)) for k in flaechen)
        hi = max(float(np.dot(ctx.top.flaechen[k].hi - mitte1, achse)) for k in flaechen)
        ts = []
        for k in flaechen:
            fl = ctx.top.flaechen[k]
            for ecke in (fl.lo, fl.hi):
                ts.append(float(np.dot(ecke - mitte1, achse)))
        tiefe = max(ts) - min(ts)
        groesse = _nahe(sw, {k: v + 0.3 for k, v in MUTTER_SW.items()}, 0.35)
        werte = {"sw": sw, "tiefe": round(tiefe, 3), "achse": ctx.ld(achse), "gewinde": gewinde_text(groesse)
                 if groesse else None, "eckmass": sw / math.cos(math.radians(30))}
        text = f"Sechskant SW {zahl(sw)} × {zahl(tiefe, 1)} tief" + (f" (Mutter {werte['gewinde']})"
                                                                     if werte["gewinde"] else "")
        sig = {"typ": "sechskant", "mitte": ctx.lp(mitte1), "richtung": ctx.ld(achse), "radius": sw / 2,
               "laenge": tiefe}
        out.append(Merkmal("", "muttertasche", sig, werte, text, flaechen))
        _ = lo, hi
    for k, m in enumerate(out, 1):
        m.id = f"muttertasche:{k}"
        ctx.benutzt.update(m.flaechen)
    return out


# -- Lochbilder --------------------------------------------------------------------------------------------------------


def _lochbilder(ctx: _Ctx, bohrungen: list[Merkmal]) -> list[Merkmal]:
    """Gleiche Bohrungen (Art, Ø, Tiefe, Gewinde, Richtung) zu Reihe, Raster, Teilkreis oder Paar zusammenfassen."""
    gruppen: dict[tuple, list[Merkmal]] = {}
    for m in bohrungen:
        w = m.werte
        a = _achse_positiv(np.asarray(w["achse"], dtype=float))
        key = (m.art, round(float(w["d"]), 2), w.get("durch"), round(float(w.get("tiefe") or 0), 1), w.get("gewinde"),
               tuple(int(round(v)) for v in a * 1000))
        gruppen.setdefault(key, []).append(m)
    out = []
    for key, ms in gruppen.items():
        if len(ms) < 2:
            continue
        a = np.asarray(key[5], dtype=float) / 1000.0
        a = a / np.linalg.norm(a)
        # Ebene senkrecht zur Achse: zwei Achsen e1, e2 aus den lokalen Achsen
        achsen = [np.eye(3)[i] for i in range(3) if abs(float(np.dot(np.eye(3)[i], a))) < 0.5]
        if len(achsen) != 2:
            e1 = np.cross(a, [0, 0, 1.0]) if abs(a[2]) < 0.9 else np.cross(a, [1.0, 0, 0])
            e1 /= np.linalg.norm(e1)
            achsen = [e1, np.cross(a, e1)]
        e1, e2 = achsen
        pts = np.array([np.asarray(m.signatur["mitte"], dtype=float) for m in ms])
        uv = np.stack([pts @ e1, pts @ e2], axis=1)
        muster = _muster(uv)
        if muster is None:
            continue
        w0 = ms[0].werte
        werte = {"muster": muster["art"], "n": len(ms), "d": w0["d"], "achse": a, "e1": e1, "e2": e2, **muster}
        text = _bohrung_text(ms[0].art, w0, len(ms))
        mitte = pts.mean(axis=0)
        sig = {"typ": "muster", "mitte": mitte, "richtung": a, "radius": w0["d"] / 2, "laenge": float(len(ms))}
        out.append(Merkmal("", "lochbild", sig, werte, text, [f for m in ms for f in m.flaechen], [m.id for m in ms]))
    out.sort(key=lambda m: tuple(round(float(v), 2) for v in m.signatur["mitte"]))
    for k, m in enumerate(out, 1):
        m.id = f"lochbild:{k}"
    return out


def _muster(uv: np.ndarray, tol: float = 0.02) -> dict[str, Any] | None:
    n = len(uv)
    if n == 2:
        dd = uv[1] - uv[0]
        return {"art": "paar", "teilung": float(np.linalg.norm(dd)), "zeilen": 1, "spalten": 2}
    # Reihe: alle auf einer Geraden mit gleichem Abstand
    c = uv.mean(axis=0)
    u, s, vt = np.linalg.svd(uv - c)
    if s[1] < tol * max(1.0, s[0]) / 10 or s[1] < tol:
        r = vt[0]
        t = (uv - c) @ r
        order = np.argsort(t)
        ts = t[order]
        diffs = np.diff(ts)
        if np.all(np.abs(diffs - diffs.mean()) < tol):
            return {"art": "reihe", "teilung": float(diffs.mean()), "richtung2d": r, "zeilen": 1, "spalten": n}
        return {"art": "reihe_ungleich", "abstaende": [float(x) for x in diffs], "richtung2d": r, "zeilen": 1,
                "spalten": n}
    # Raster: eindeutige Werte je Achse decken alle Punkte ab
    us = _eindeutig(uv[:, 0], tol)
    vs = _eindeutig(uv[:, 1], tol)
    if len(us) * len(vs) == n and len(us) >= 2 and len(vs) >= 2:
        du, dv = np.diff(us), np.diff(vs)
        if np.all(np.abs(du - du.mean()) < tol) and np.all(np.abs(dv - dv.mean()) < tol):
            return {"art": "raster", "teilungen": [float(du.mean()), float(dv.mean())], "spalten": len(us),
                    "zeilen": len(vs)}
    # Teilkreis: alle gleich weit von der Mitte, gleiche Winkelteilung
    rr = np.linalg.norm(uv - c, axis=1)
    if n >= 3 and np.all(np.abs(rr - rr.mean()) < tol) and rr.mean() > tol:
        ang = np.sort(np.degrees(np.arctan2(uv[:, 1] - c[1], uv[:, 0] - c[0])) % 360)
        steps = np.diff(np.concatenate([ang, [ang[0] + 360]]))
        gleich = bool(np.all(np.abs(steps - 360 / n) < 0.1))
        return {"art": "kreis", "tk_d": float(2 * rr.mean()), "mitte2d": c, "gleich": gleich,
                "winkel0": float(ang[0]), "teilung_grad": 360.0 / n}
    return None


def _eindeutig(xs: np.ndarray, tol: float) -> np.ndarray:
    out: list[float] = []
    for x in sorted(float(v) for v in xs):
        if not out or abs(x - out[-1]) > tol:
            out.append(x)
    return np.array(out)


# -- Taschen und Absätze -----------------------------------------------------------------------------------------------


def _taschen(ctx: _Ctx) -> list[Merkmal]:
    """Ebene Flächen parallel zu einer Seite des Hüllquaders, die nicht auf ihm liegen: Taschenböden (ringsum Wände
    nach oben) oder Absätze (offen zu einer Seite)."""
    g = ctx.sys.groesse
    out = []
    for f in ctx.top.flaechen:
        if f.typ != "ebene" or f.n is None or f.index in ctx.benutzt:
            continue
        n = ctx.ld(f.n)
        i = int(np.argmax(np.abs(n)))
        if abs(n[i]) < 1 - 1e-6:
            continue
        s = 1.0 if n[i] > 0 else -1.0
        p = ctx.lp(f.punkt)
        rand = g[i] if s > 0 else 0.0
        abstand = (rand - p[i]) * s  # wie weit unter der Seite des Hüllquaders
        if abstand < 0.05 or f.flaeche < 1.0:
            continue
        # Boden nur, wenn der Weg von ihm entlang der Normale bis zur Seite des Hüllquaders frei ist (sonst ist die
        # Fläche eine Wand, die einer anderen Wand gegenübersteht)
        q = punkt_auf(f)
        if q is None or any(ctx.cls.innen(q + f.n * (abstand * k)) for k in (0.02, 0.35, 0.7, 0.98)):
            continue
        # Nachbarn: Wände über dem Boden (konkav) oder darunter (Kante nach außen)
        hoch, tief = 0, 0
        for k in f.nachbarn:
            nb = ctx.top.flaechen[k]
            c = ctx.lp(nb.mitte if nb.mitte is not None else nb.punkt)
            if (c[i] - p[i]) * s > 1e-3:
                hoch += 1
            elif (c[i] - p[i]) * s < -1e-3:
                tief += 1
        lo, hi = _lokal_box(ctx, f)
        ausd = [float(hi[j] - lo[j]) for j in range(3) if j != i]
        achsen = [j for j in range(3) if j != i]
        if hoch == 0:
            continue
        art = "tasche" if tief == 0 else "absatz"
        # Absätze: Höhe ab der Gegenseite (Funktionsmaß „wie hoch steht die Stufe“), Taschen: Tiefe ab der Seite
        werte = {"achse": i, "seite": s, "boden": p[i], "ausdehnung": ausd, "achsen": achsen,
                 "lo": lo, "hi": hi}
        if art == "tasche":
            werte["tiefe"] = round(float(abstand), 4)
            text = f"Tasche {zahl(ausd[0])} × {zahl(ausd[1])} × {zahl(abstand, 1)} tief"
        else:
            werte["hoehe"] = round(float(p[i] if s > 0 else g[i] - p[i]), 4)
            werte["tiefe"] = round(float(abstand), 4)
            text = f"Absatz {zahl(abstand, 1)}"
        sig = {"typ": "ebene", "mitte": p, "richtung": n, "radius": None, "laenge": float(abstand)}
        out.append(Merkmal("", art, sig, werte, text, [f.index]))
    out.sort(key=lambda m: (m.art, *(round(float(v), 2) for v in m.signatur["mitte"])))
    zaehler: dict[str, int] = {}
    for m in out:
        zaehler[m.art] = zaehler.get(m.art, 0) + 1
        m.id = f"{m.art}:{zaehler[m.art]}"
    return out


def punkt_auf(f: Flaeche) -> np.ndarray | None:
    """Ein Punkt sicher auf der (beschnittenen) Fläche, Welt."""
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Pnt2d
    from OCP.TopAbs import TopAbs_IN
    from OCP.TopoDS import TopoDS

    face = TopoDS.Face(f.form.wrapped)
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    surf = BRepAdaptor_Surface(face)
    cls = BRepClass_FaceClassifier()
    for fu, fv in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.75), (0.25, 0.75), (0.75, 0.25), (0.5, 0.15), (0.5, 0.85),
                   (0.15, 0.5), (0.85, 0.5), (0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1)):
        u, v = umin + (umax - umin) * fu, vmin + (vmax - vmin) * fv
        cls.Perform(face, gp_Pnt2d(u, v), 1e-7)
        if cls.State() == TopAbs_IN:
            p = surf.Value(u, v)
            return np.array([p.X(), p.Y(), p.Z()])
    return None


# -- Fasen -------------------------------------------------------------------------------------------------------------


def _fasen(ctx: _Ctx) -> list[Merkmal]:
    """Schmale ebene Flächen schräg zwischen zwei Flächen (Fase an Kanten) und schmale Kegelflächen (Fase an runden
    Kanten). Schenkel a, b aus Breite und Normalen der Nachbarn; gleiche Fasen werden gezählt."""
    roh: list[tuple[float, float, float, Flaeche, np.ndarray]] = []
    for f in ctx.top.flaechen:
        if f.index in ctx.benutzt:
            continue
        if f.typ == "ebene" and f.n is not None:
            n = ctx.ld(f.n)
            if np.max(np.abs(n)) > 1 - 1e-6:
                continue  # achsparallel: keine Fase
            gerade = [e for e in f.form.edges() if e.geom_type.name == "LINE"]
            if not gerade:
                continue
            lang = max(gerade, key=lambda e: e.length)
            laenge = float(lang.length)
            breite = f.flaeche / laenge if laenge > 0 else 0.0
            if breite <= 0 or breite > 0.35 * laenge or breite > 12:
                continue
            tv = lang.tangent_at(0.5)
            e_dir = np.array([tv.X, tv.Y, tv.Z], dtype=float)
            nb = [ctx.top.flaechen[k] for k in f.nachbarn]
            nb = [x for x in nb if x.typ == "ebene" and x.n is not None and abs(float(np.dot(x.n, e_dir))) < 1e-3]
            if len(nb) < 2:
                continue
            # die zwei Nachbarn, die mit der Fase den größten Winkel bilden (die ursprünglichen Kantenflächen)
            nb.sort(key=lambda x: float(np.dot(x.n, f.n)))
            n1, n2 = nb[0].n, nb[1].n
            if abs(float(np.dot(n1, n2))) > 0.2:  # nur Kanten zwischen etwa senkrechten Flächen
                continue
            a = breite * abs(float(np.dot(f.n, n1)))
            b = breite * abs(float(np.dot(f.n, n2)))
            roh.append((a, b, laenge, f, n))
        elif f.typ == "kegel" and f.halbwinkel is not None and 20 <= f.halbwinkel <= 70:
            laenge_achse = f.t[1] - f.t[0]
            schraeg = laenge_achse / math.cos(math.radians(f.halbwinkel))
            if schraeg > 6 or f.spanne < 359:
                continue
            a = laenge_achse
            b = laenge_achse * math.tan(math.radians(f.halbwinkel))
            roh.append((a, b, 2 * math.pi * float(f.radius or 0), f, ctx.ld(f.achse)))
    gruppen: list[list[Any]] = []
    for a, b, laenge, f, n in roh:
        lo, hi = sorted((a, b))
        for g in gruppen:
            if abs(g[0] - lo) < 0.01 and abs(g[1] - hi) < 0.01:
                g[2].append((f, n, laenge))
                break
        else:
            gruppen.append([lo, hi, [(f, n, laenge)]])
    out = []
    for lo, hi, flist in gruppen:
        gleich = abs(lo - hi) < 0.02
        winkel = 45.0 if gleich else math.degrees(math.atan2(hi, lo))
        text_einzel = f"{zahl(lo)} × 45°" if gleich else f"{zahl(lo)} × {zahl(hi)}"
        n = len(flist)
        text = (f"{n}× " if n > 1 else "") + "Fase " + text_einzel
        f0, n0, _ = flist[0]
        sig = {"typ": "ebene", "mitte": ctx.lp(f0.mitte), "richtung": n0, "radius": None, "laenge": lo}
        werte = {"a": lo, "b": hi, "winkel": winkel, "n": n, "gleich": gleich, "text_einzel": text_einzel,
                 "lagen": [ctx.lp(f.mitte) for f, _, _ in flist], "normalen": [nn for _, nn, _ in flist]}
        out.append(Merkmal("", "fase", sig, werte, text, [f.index for f, _, _ in flist]))
    out.sort(key=lambda m: (-m.werte["n"], m.werte["a"]))
    for k, m in enumerate(out, 1):
        m.id = f"fase:{k}"
        ctx.benutzt.update(m.flaechen)
    return out


# -- Radien ------------------------------------------------------------------------------------------------------------


def _radien(ctx: _Ctx) -> list[Merkmal]:
    """Rundungen: Zylinderteilflächen bis etwa 180° Spanne und Torusflächen, die noch keinem Merkmal gehören."""
    roh: list[tuple[float, bool, Flaeche]] = []
    for f in ctx.top.flaechen:
        if f.index in ctx.benutzt:
            continue
        if f.typ == "zylinder" and f.spanne < 181 and f.radius:
            roh.append((float(f.radius), bool(f.innen), f))
        elif f.typ == "torus" and f.radius2:
            roh.append((float(f.radius2), bool(f.innen), f))
    gruppen: dict[tuple[float, bool], list[Flaeche]] = {}
    for r, innen, f in roh:
        gruppen.setdefault((round(r, 2), innen), []).append(f)
    out = []
    for (r, innen), fl in sorted(gruppen.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
        zyl = [f for f in fl if f.typ == "zylinder"]
        n = max(1, len(zyl)) if zyl else len(fl)
        f0 = zyl[0] if zyl else fl[0]
        text = (f"{n}× " if n > 1 else "") + f"R{zahl(r)}"
        mitte = ctx.lp(f0.mitte) if f0.mitte is not None else ctx.lp(f0.punkt)
        achse = ctx.ld(f0.achse) if f0.achse is not None else None
        sig = {"typ": "bogen", "mitte": mitte, "richtung": achse, "radius": r,
               "laenge": float(f0.t[1] - f0.t[0]) if f0.typ == "zylinder" else None}
        werte = {"r": r, "innen": innen, "n": n,
                 "lagen": [ctx.lp(f.mitte) for f in zyl or fl if f.mitte is not None],
                 "achsen": [ctx.ld(f.achse) for f in zyl if f.achse is not None],
                 "zentren": [ctx.lp(f.punkt) for f in zyl if f.punkt is not None]}
        out.append(Merkmal("", "radius", sig, werte, text, [f.index for f in fl]))
    for k, m in enumerate(out, 1):
        m.id = f"radius:{k}"
        ctx.benutzt.update(m.flaechen)
    return out


# -- Kanten und Punkte (für Klicks) ------------------------------------------------------------------------------------


def _kanten(ctx: _Ctx) -> tuple[list[Kante], list[np.ndarray]]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_CurveType

    from kevcad_kernel.tessellate import edges_of, vertices_of

    kanten = []
    for i, e in enumerate(edges_of(ctx.form)):
        try:
            c = BRepAdaptor_Curve(e.wrapped)
            typ = c.GetType()
            n = 2 if typ == GeomAbs_CurveType.GeomAbs_Line else 24
            a, b = c.FirstParameter(), c.LastParameter()
            pts = np.array([[c.Value(a + (b - a) * k / (n - 1)).X(), c.Value(a + (b - a) * k / (n - 1)).Y(),
                             c.Value(a + (b - a) * k / (n - 1)).Z()] for k in range(n)])
        except Exception:  # noqa: BLE001
            continue
        loc = ctx.lp(pts)
        laenge = float(np.sum(np.linalg.norm(np.diff(loc, axis=0), axis=1)))
        if typ == GeomAbs_CurveType.GeomAbs_Line:
            d = loc[-1] - loc[0]
            dn = float(np.linalg.norm(d))
            kanten.append(Kante(i, "linie", (loc[0] + loc[-1]) / 2, d / dn if dn > 0 else None, None, laenge,
                                loc[0], loc[-1], loc))
        elif typ == GeomAbs_CurveType.GeomAbs_Circle:
            circ = c.Circle()
            mitte = ctx.lp([circ.Location().X(), circ.Location().Y(), circ.Location().Z()])
            ax = circ.Axis().Direction()
            kanten.append(Kante(i, "kreis", mitte, ctx.ld([ax.X(), ax.Y(), ax.Z()]), float(circ.Radius()), laenge,
                                loc[0], loc[-1], loc))
        else:
            kanten.append(Kante(i, "andere", loc.mean(axis=0), None, None, laenge, loc[0], loc[-1], loc))
    punkte = []
    for v in vertices_of(ctx.form):
        p = v.center() if hasattr(v, "center") else None
        if p is not None:
            punkte.append(ctx.lp([p.X, p.Y, p.Z]))
    return kanten, punkte

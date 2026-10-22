"""Projektion: Formen → Linien je Linienart in einer Parallelansicht (öffentliche Schnittstelle, auch für den Bauplan).

```python
from kevcad_kernel.zeichnung import projiziere
p = projiziere(teil, "vorn")                              # build123d-Form, TopoDS_Shape oder Liste davon
p = projiziere({"Rahmen": f1, "Rad": f2}, "iso", verdeckt=False, je_teil=True)
p = projiziere(formen, {"rotation": [x, y, z, w]})          # Kamera wie im Bauplan (blickt entlang lokal −Z, oben +Y)
p.linien["sichtbar"]                                       # Liste von Polylinien, je (n, 2) float, Modell-mm
p.teile["Rad"]["sichtbar"]                                 # mit je_teil=True: Linien je Teil (gemeinsame Verdeckung)
p.rahmen                                                   # (x0, y0, x1, y1) der sichtbaren Linien
```

Koordinaten: Blatt-x = p · rechts, Blatt-y = p · oben der Ansicht (ansichten.py), in Modell-mm vor dem Maßstab; der
Ursprung ist der Welt- bzw. Teilursprung. Linienarten (ISO 128-20): ``sichtbar`` (breite Volllinie: scharfe Kanten und
Umrisse), ``verdeckt`` (schmale Strichlinie), ``mitte`` (schmale Strichpunktlinie: Achsen, Mittelkreuze), ``duenn``
(schmale Volllinie: Lichtkanten an Rundungen), ``schnitt`` und ``schraffur`` (aus schnitt.py, hier leer).

Rechenweg (DOKUMENTE.md 1.1): Verdeckung auf dem Netz (HLRBRep_PolyAlgo), die vielen kurzen Netzstücke werden zu
Zügen verbunden und vereinfacht; auf Wunsch exakt (HLRBRep_Algo) in einem eigenen Prozess mit Zeitbudget
(``hlr_prozess.py``). Ergebnisse liegen in einem Zwischenspeicher je Formschlüssel, Ansicht und Optionen. Linienarten
zusätzlich ``nachbar`` (Strich-Zweipunkt: Nachbarteile, Endlagen) und ``bruch`` (Freihand: Bruchkanten verkürzter
Ansichten).
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.ansichten import Blick, blick

LINIENARTEN = ("sichtbar", "verdeckt", "mitte", "schnitt", "schraffur", "duenn", "nachbar", "bruch")
CACHE_GROESSE = 768

Polylinie = np.ndarray  # (n, 2)


@dataclass
class Projektion:
    blick: Blick
    linien: dict[str, list[Polylinie]] = field(default_factory=lambda: {a: [] for a in LINIENARTEN})
    teile: dict[str, dict[str, list[Polylinie]]] = field(default_factory=dict)
    rahmen: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    ms: float = 0.0
    exakt: bool = True
    aus_cache: bool = False

    def anzahl(self) -> dict[str, int]:
        return {a: len(self.linien.get(a) or []) for a in LINIENARTEN}

    def verschoben(self, dx: float, dy: float, faktor: float = 1.0) -> Projektion:
        """Kopie mit allen Linien um (dx, dy) verschoben nach Skalierung mit ``faktor`` (Blatt-mm)."""
        def f(ls: list[Polylinie]) -> list[Polylinie]:
            return [pl * faktor + np.array([dx, dy]) for pl in ls]

        out = Projektion(self.blick, {a: f(ls) for a, ls in self.linien.items()},
                         {n: {a: f(ls) for a, ls in d.items()} for n, d in self.teile.items()},
                         (self.rahmen[0] * faktor + dx, self.rahmen[1] * faktor + dy, self.rahmen[2] * faktor + dx,
                          self.rahmen[3] * faktor + dy), self.ms, self.exakt, self.aus_cache)
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Zwischenspeicher
# ---------------------------------------------------------------------------------------------------------------------


class _Cache:
    def __init__(self, groesse: int = CACHE_GROESSE) -> None:
        self._d: OrderedDict[str, Projektion] = OrderedDict()
        self._lock = threading.Lock()
        self.groesse = groesse
        self.treffer = 0
        self.fehlgriffe = 0

    def get(self, key: str) -> Projektion | None:
        with self._lock:
            p = self._d.get(key)
            if p is not None:
                self._d.move_to_end(key)
                self.treffer += 1
            else:
                self.fehlgriffe += 1
            return p

    def put(self, key: str, p: Projektion) -> None:
        with self._lock:
            self._d[key] = p
            self._d.move_to_end(key)
            while len(self._d) > self.groesse:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


CACHE = _Cache()


def form_schluessel(shape: Any) -> str:
    """Schlüssel einer Form aus ihrer BRep-Binärform (wenn der Aufrufer keinen eigenen hat)."""
    from kevcad_kernel.tessellate import serialize_shape

    topo = shape.wrapped if hasattr(shape, "wrapped") else shape
    return hashlib.sha1(serialize_shape(topo)).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------
# Eingaben
# ---------------------------------------------------------------------------------------------------------------------


def _formen(formen: Any) -> list[tuple[str, Any]]:
    """(Name, TopoDS_Shape) aus Form, Liste, Wörterbuch oder Liste von Paaren."""
    if isinstance(formen, dict):
        items = list(formen.items())
    elif isinstance(formen, (list, tuple)):
        items = []
        for i, f in enumerate(formen):
            if isinstance(f, tuple) and len(f) == 2 and isinstance(f[0], str):
                items.append(f)
            else:
                items.append((str(getattr(f, "label", "") or f"Teil {i + 1}"), f))
    else:
        items = [(str(getattr(formen, "label", "") or "Teil"), formen)]
    out = []
    for name, f in items:
        topo = f.wrapped if hasattr(f, "wrapped") else f
        if topo is None or topo.IsNull():
            continue
        out.append((name, topo))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Kanten → Polylinien
# ---------------------------------------------------------------------------------------------------------------------


def kante_polylinie(edge: Any, toleranz: float = 0.02) -> Polylinie | None:
    """Kante (TopoDS_Edge, in der Bildebene z = 0) → Polylinie (n, 2). Geraden mit zwei Punkten."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAbs import GeomAbs_CurveType
    from OCP.TopoDS import TopoDS

    e = TopoDS.Edge(edge)
    if BRep_Tool.Degenerated_s(e):
        return None
    try:
        c = BRepAdaptor_Curve(e)
    except Exception:  # noqa: BLE001
        return None
    a, b = c.FirstParameter(), c.LastParameter()
    if c.GetType() == GeomAbs_CurveType.GeomAbs_Line:
        p, q = c.Value(a), c.Value(b)
        pts = [(p.X(), p.Y()), (q.X(), q.Y())]
    else:
        try:
            disc = GCPnts_QuasiUniformDeflection(c, toleranz, a, b)
            n = disc.NbPoints() if disc.IsDone() else 0
        except Exception:  # noqa: BLE001
            n = 0
        if n >= 2:
            pts = [(disc.Value(i).X(), disc.Value(i).Y()) for i in range(1, n + 1)]
        else:
            k = 24
            pts = [(c.Value(a + (b - a) * i / k).X(), c.Value(a + (b - a) * i / k).Y()) for i in range(k + 1)]
    arr = np.asarray(pts, dtype=float)
    if len(arr) < 2 or float(np.max(np.ptp(arr, axis=0))) < 1e-9:
        return None
    return arr


def _kanten(compound: Any, toleranz: float) -> list[Polylinie]:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    out: list[Polylinie] = []
    if compound is None or compound.IsNull():
        return out
    exp = TopExp_Explorer(compound, TopAbs_EDGE)
    while exp.More():
        pl = kante_polylinie(exp.Current(), toleranz)
        if pl is not None:
            out.append(pl)
        exp.Next()
    return out


def verbinde(linien: list[Polylinie], tol: float = 1e-6) -> list[Polylinie]:
    """Polylinien mit gemeinsamen Endpunkten zu längeren Zügen verbinden (weniger Daten, durchgehende Strichmuster)."""
    if len(linien) < 2:
        return list(linien)
    rest = [np.asarray(pl, dtype=float) for pl in linien]
    scale = 1.0 / max(tol, 1e-12)

    def k(p: np.ndarray) -> tuple[int, int]:
        return (int(round(p[0] * scale)), int(round(p[1] * scale)))

    enden: dict[tuple[int, int], list[int]] = {}
    for i, pl in enumerate(rest):
        enden.setdefault(k(pl[0]), []).append(i)
        enden.setdefault(k(pl[-1]), []).append(i)
    benutzt = [False] * len(rest)
    out: list[Polylinie] = []
    for i in range(len(rest)):
        if benutzt[i]:
            continue
        benutzt[i] = True
        zug = [p for p in rest[i]]
        for richtung in (1, 0):  # erst am Ende verlängern, dann am Anfang
            while True:
                p = zug[-1] if richtung else zug[0]
                kand = [j for j in enden.get(k(p), []) if not benutzt[j]]
                if len(enden.get(k(p), [])) > 2 or not kand:  # Verzweigung: hier nicht verbinden
                    break
                j = kand[0]
                benutzt[j] = True
                pl = rest[j]
                if k(pl[0]) == k(p):
                    seg = list(pl[1:])
                else:
                    seg = list(pl[::-1][1:])
                if richtung:
                    zug += seg
                else:
                    zug = seg[::-1] + zug
        out.append(np.asarray(zug, dtype=float))
    return out


def ohne_ueberdeckte(verdeckt: list[Polylinie], sichtbar: list[Polylinie], tol: float) -> list[Polylinie]:
    """Verdeckte Linien, soweit sie nicht genau unter sichtbaren liegen (ISO 128: sichtbare Kante hat Vorrang; die
    Hinterkante eines Quaders deckt sich mit der Vorderkante). Geraden werden um überdeckte Stücke gekürzt, gekrümmte
    Linien fallen weg, wenn alle Punkte auf sichtbaren Linien liegen."""
    if not verdeckt or not sichtbar:
        return verdeckt
    segs = np.concatenate([np.stack([pl[:-1], pl[1:]], axis=1) for pl in sichtbar if len(pl) >= 2])  # (m, 2, 2)
    a, b = segs[:, 0], segs[:, 1]
    ab = b - a
    lab = np.einsum("ij,ij->i", ab, ab)
    lo = np.minimum(a, b) - tol
    hi = np.maximum(a, b) + tol

    def abstand(p: np.ndarray, idx: np.ndarray) -> np.ndarray:
        t = np.clip(np.einsum("ij,ij->i", p - a[idx], ab[idx]) / np.maximum(lab[idx], 1e-30), 0.0, 1.0)
        q = a[idx] + ab[idx] * t[:, None]
        return np.linalg.norm(q - p, axis=1)

    def nah(p: np.ndarray) -> bool:
        idx = np.nonzero(np.all((lo <= p) & (p <= hi), axis=1))[0]
        return bool(len(idx)) and float(abstand(p, idx).min()) <= tol

    out: list[Polylinie] = []
    for pl in verdeckt:
        if len(pl) == 2:
            p, q = pl[0], pl[1]
            d = q - p
            L = float(np.linalg.norm(d))
            if L < tol:
                continue
            u = d / L
            # sichtbare Strecken auf derselben Geraden: als Intervalle auf [0, L] abziehen
            n = np.array([-u[1], u[0]])
            da = (a - p) @ n
            db = (b - p) @ n
            kol = np.nonzero((np.abs(da) <= tol) & (np.abs(db) <= tol))[0]
            stuecke = [(0.0, L)]
            for i in kol:
                s0, s1 = sorted((float((a[i] - p) @ u), float((b[i] - p) @ u)))
                neu = []
                for x0, x1 in stuecke:
                    if s1 <= x0 + tol or s0 >= x1 - tol:
                        neu.append((x0, x1))
                        continue
                    if s0 > x0 + tol:
                        neu.append((x0, s0))
                    if s1 < x1 - tol:
                        neu.append((s1, x1))
                stuecke = neu
                if not stuecke:
                    break
            for x0, x1 in stuecke:
                if x1 - x0 > 10 * tol:
                    out.append(np.array([p + u * x0, p + u * x1]))
            continue
        probe = pl if len(pl) <= 12 else pl[np.linspace(0, len(pl) - 1, 12).astype(int)]
        if all(nah(pt) for pt in probe):
            continue
        out.append(pl)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Mittellinien
# ---------------------------------------------------------------------------------------------------------------------


def mittellinien(formen: list[tuple[str, Any]], b: Blick, ueberstand: float = 3.0,
                 mindest_spanne: float = 180.0) -> list[Polylinie]:
    """Achsen und Mittelkreuze runder Merkmale (Bohrungen, Wellen, Rohre) in der Ansicht ``b``.

    ISO 128-24: Strichpunktlinie, die das Merkmal um ``ueberstand`` (Modell-mm, der Aufrufer rechnet 2–3 mm auf dem Blatt
    um) überragt. Kreise in Blickrichtung bekommen ein Mittelkreuz, Zylinder quer zur Blickrichtung eine Achse; schräg
    gesehene Achsen (Isometrie) bekommen nichts. Koaxiale Flächen ergeben eine Linie."""
    from build123d import Shape

    from kevcad_kernel.zeichnung.topologie import analysiere

    d = b.d
    kreuze: list[list[Any]] = []  # [mitte2d, radius]
    achsen: list[list[Any]] = []  # [p3, a3, t0, t1]
    for _name, topo in formen:
        top = analysiere(Shape.cast(topo))
        for f in top.flaechen:
            if f.typ not in ("zylinder", "kegel") or f.achse is None or f.spanne < mindest_spanne:
                continue
            a = f.achse / np.linalg.norm(f.achse)
            cos = abs(float(np.dot(a, d)))
            r = float(f.radius or 0.0)
            if f.typ == "kegel" and f.halbwinkel is not None:
                tmax = max(abs(f.t[0]), abs(f.t[1]))
                r = abs(r) + tmax * math.tan(math.radians(f.halbwinkel))
            if cos > 1 - 1e-6:
                c = b.projiziere(f.punkt)
                for kk in kreuze:
                    if np.linalg.norm(kk[0] - c) < 1e-3:
                        kk[1] = max(kk[1], r)
                        break
                else:
                    kreuze.append([c, r])
            elif cos < 1e-6:
                p0 = f.punkt
                for ak in achsen:
                    off = p0 - ak[0]
                    if abs(float(np.dot(ak[1], a))) > 1 - 1e-6 and np.linalg.norm(off - ak[1] * float(np.dot(off, ak[1]))) < 1e-3:
                        s = float(np.dot(off, ak[1]))
                        sign = 1.0 if float(np.dot(ak[1], a)) > 0 else -1.0
                        lo, hi = s + sign * f.t[0], s + sign * f.t[1]
                        ak[2], ak[3] = min(ak[2], lo, hi), max(ak[3], lo, hi)
                        break
                else:
                    achsen.append([p0, a, min(f.t), max(f.t)])
    out: list[Polylinie] = []
    for c, r in kreuze:
        h = r + ueberstand
        out.append(np.array([[c[0] - h, c[1]], [c[0] + h, c[1]]]))
        out.append(np.array([[c[0], c[1] - h], [c[0], c[1] + h]]))
    for p0, a, t0, t1 in achsen:
        p = b.projiziere(p0 + a * (t0 - ueberstand))
        q = b.projiziere(p0 + a * (t1 + ueberstand))
        out.append(np.array([p, q]))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Projektion
# ---------------------------------------------------------------------------------------------------------------------


def _ax2(b: Blick) -> Any:
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    n = -b.d
    return gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*n), gp_Dir(*b.rechts))


def _rahmen(linien: list[Polylinie]) -> tuple[float, float, float, float]:
    if not linien:
        return (0.0, 0.0, 0.0, 0.0)
    pts = np.concatenate(linien)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))


def vereinfache(pl: Polylinie, tol: float) -> Polylinie:
    """Douglas-Peucker: kollineare Zwischenpunkte entfernen (das Netz liefert Geraden in vielen kurzen Stücken)."""
    if len(pl) <= 2:
        return pl
    behalten = np.zeros(len(pl), dtype=bool)
    behalten[0] = behalten[-1] = True
    stapel = [(0, len(pl) - 1)]
    while stapel:
        i, j = stapel.pop()
        if j <= i + 1:
            continue
        a, b = pl[i], pl[j]
        ab = b - a
        n = float(np.hypot(ab[0], ab[1]))
        seg = pl[i + 1:j]
        if n < 1e-12:
            d = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            d = np.abs((seg[:, 0] - a[0]) * ab[1] - (seg[:, 1] - a[1]) * ab[0]) / n
        k = int(np.argmax(d))
        if float(d[k]) > tol:
            m = i + 1 + k
            behalten[m] = True
            stapel += [(i, m), (m, j)]
    return pl[behalten]


def _strecken_vereinen(linien: list[Polylinie], tol: float) -> list[Polylinie]:
    """Polylinien in Strecken zerlegen, doppelte entfernen und kollineare, sich überlappende oder berührende Strecken
    zu einer vereinen (das Netz liefert Kanten in vielen kurzen und mehrfach übereinanderliegenden Stücken)."""
    segs = [np.stack([pl[:-1], pl[1:]], axis=1) for pl in linien if len(pl) >= 2]
    if not segs:
        return []
    S = np.concatenate(segs)
    d = S[:, 1] - S[:, 0]
    L = np.hypot(d[:, 0], d[:, 1])
    S, d, L = S[L > tol * 0.1], d[L > tol * 0.1], L[L > tol * 0.1]
    if len(S) == 0:
        return []
    u = d / L[:, None]
    # Richtung eindeutig (Winkel in [0, π)), Abstand der Geraden vom Ursprung
    flip = (u[:, 0] < -1e-12) | ((np.abs(u[:, 0]) <= 1e-12) & (u[:, 1] < 0))
    u[flip] *= -1
    a = np.where(flip[:, None], S[:, 1], S[:, 0])
    b = np.where(flip[:, None], S[:, 0], S[:, 1])
    winkel = np.round(np.arctan2(u[:, 1], u[:, 0]) / 1e-3).astype(np.int64)
    n = np.stack([-u[:, 1], u[:, 0]], axis=1)
    abst = np.round(np.einsum("ij,ij->i", a, n) / max(tol, 1e-9)).astype(np.int64)
    t0 = np.einsum("ij,ij->i", a, u)
    t1 = np.einsum("ij,ij->i", b, u)
    order = np.lexsort((t0, abst, winkel))
    out: list[Polylinie] = []
    i = 0
    N = len(order)
    while i < N:
        j = i
        w0, o0 = winkel[order[i]], abst[order[i]]
        while j < N and winkel[order[j]] == w0 and abst[order[j]] == o0:
            j += 1
        idx = order[i:j]
        uu = u[idx[0]]
        nn = n[idx[0]]
        off = float(np.mean(np.einsum("ij,j->i", a[idx], nn)))
        lo, hi = None, None
        for k in idx:
            s0, s1 = float(t0[k]), float(t1[k])
            if lo is None:
                lo, hi = s0, s1
            elif s0 <= hi + tol:
                hi = max(hi, s1)
            else:
                out.append(np.array([uu * lo + nn * off, uu * hi + nn * off]))
                lo, hi = s0, s1
        if lo is not None:
            out.append(np.array([uu * lo + nn * off, uu * hi + nn * off]))
        i = j
    return out


def _zusammenfassen(linien: list[Polylinie], tol: float, netz: bool = False) -> list[Polylinie]:
    if netz:
        linien = _strecken_vereinen(linien, tol)
    return [vereinfache(pl, tol) for pl in verbinde(linien, max(tol * 0.5, 1e-6))]


def projiziere(formen: Any, ansicht: Any = "vorn", *, verdeckt: bool = True, glatt: bool = True,
               mittel: bool = True, ueberstand: float = 3.0, toleranz: float = 0.02, je_teil: bool = False,
               exakt: bool | float = False, schluessel: str | dict[str, str] | None = None,
               cache: _Cache | None = CACHE) -> Projektion:
    """Formen in der Ansicht ``ansicht`` projizieren (Modulbeschreibung). ``glatt``: Lichtkanten (tangentiale
    Übergänge, etwa am Rand einer Rundung) als ``duenn``. ``mittel``: Mittellinien. ``schluessel``: Formschlüssel
    (ein Text für alle oder je Name), sonst aus der BRep gerechnet.

    ``exakt`` (DOKUMENTE.md 1.1, „Verdeckungsrechnung“): ``False`` (Vorgabe) rechnet auf dem Netz (HLRBRep_PolyAlgo,
    Segmente zusammengefasst); eine Zahl > 0 rechnet zusätzlich exakt (HLRBRep_Algo) in einem eigenen Prozess mit
    diesem Zeitbudget in Sekunden und nimmt das exakte Ergebnis nur, wenn es rechtzeitig fertig ist (die exakte
    Rechnung kann bei achsparallelen Ansichten verschmolzener Zylinder Minuten brauchen, unabhängig von der
    Flächenzahl). ``True`` rechnet exakt im aufrufenden Prozess ohne Budget (nur für Tests und bekannte Fälle)."""
    b = blick(ansicht)
    liste = _formen(formen)
    if isinstance(schluessel, dict):
        keys = [str(schluessel.get(n) or form_schluessel(s)) for n, s in liste]
    elif isinstance(schluessel, str):
        keys = [schluessel]
    else:
        keys = [form_schluessel(s) for _, s in liste] if cache is not None else []
    key = None
    budget = float(exakt) if (not isinstance(exakt, bool) and exakt) else 0.0
    if cache is not None:
        opts = f"{int(verdeckt)}{int(glatt)}{int(mittel)}{ueberstand:g}{toleranz:g}{int(je_teil)}{exakt is True}"
        names = "|".join(n for n, _ in liste) if je_teil else ""
        key = hashlib.sha1(("|".join(keys) + b.schluessel + opts + names).encode()).hexdigest()
        hit = cache.get(key)
        if hit is not None and (hit.exakt or not budget or key in _ZU_LANGSAM):
            return Projektion(hit.blick, hit.linien, hit.teile, hit.rahmen, hit.ms, hit.exakt, True)
    t0 = time.perf_counter()
    groesse = _groesse(liste)
    tol_netz = min(max(groesse * 0.0004, 0.005), 0.1)
    proj = Projektion(b, exakt=exakt is True)
    if liste:
        teile = None
        if budget > 0 and key is not None and key not in _ZU_LANGSAM:
            teile = EXAKT.rechne(liste, b, verdeckt=verdeckt, glatt=glatt, toleranz=toleranz, je_teil=je_teil,
                                 budget=budget)
            if teile is None:
                _ZU_LANGSAM.add(key)
            else:
                proj.exakt = True
        if teile is None:
            teile = _hlr(liste, b, verdeckt=verdeckt, glatt=glatt, toleranz=toleranz, exakt=exakt is True,
                         je_teil=je_teil, netz=tol_netz)
        if je_teil:
            proj.teile = teile
            for d in teile.values():
                for art, ls in d.items():
                    proj.linien.setdefault(art, []).extend(ls)
        else:
            proj.linien.update(teile["*"])
        if mittel:
            proj.linien["mitte"] = mittellinien(liste, b, ueberstand)
    tol_vereinfachen = 1e-4 if proj.exakt else tol_netz * 0.5
    if not proj.exakt:  # Netz: Stücke zuerst vereinen (aus Tausenden kurzer Strecken werden wenige)
        for d in [proj.linien, *proj.teile.values()]:
            for art in ("sichtbar", "verdeckt", "duenn"):
                if d.get(art):
                    d[art] = _strecken_vereinen(d[art], tol_vereinfachen)
    if proj.linien["verdeckt"]:
        g2 = max(1.0, *(abs(v) for v in _rahmen(proj.linien["sichtbar"])))
        tol_deck = max(1e-4 * g2, 0.0 if proj.exakt else tol_netz * 1.5)
        proj.linien["verdeckt"] = ohne_ueberdeckte(proj.linien["verdeckt"], proj.linien["sichtbar"], tol_deck)
        for d in proj.teile.values():
            d["verdeckt"] = ohne_ueberdeckte(d.get("verdeckt") or [], proj.linien["sichtbar"], tol_deck)
    netz = not proj.exakt
    for d in proj.teile.values():
        for art in ("sichtbar", "verdeckt", "duenn"):
            if d.get(art):
                d[art] = _zusammenfassen(d[art], tol_vereinfachen)
    for art in ("sichtbar", "verdeckt", "duenn"):
        if proj.teile:
            proj.linien[art] = [pl for d in proj.teile.values() for pl in d.get(art) or []]
        else:
            proj.linien[art] = _zusammenfassen(proj.linien[art], tol_vereinfachen)
    proj.rahmen = _rahmen(proj.linien["sichtbar"] or proj.linien["verdeckt"])
    proj.ms = (time.perf_counter() - t0) * 1000.0
    if cache is not None and key is not None:
        cache.put(key, proj)
    return proj


_ZU_LANGSAM: set[str] = set()  # Schlüssel, bei denen die exakte Rechnung das Budget überschritt (nicht wiederholen)
_NETZE: OrderedDict[tuple[int, float], tuple[Any, Any]] = OrderedDict()
_NETZE_LOCK = threading.Lock()


def _vernetzte_kopie(shape: Any, netz: float) -> Any:
    """Vernetzte Kopie der Form (die Form des Aufrufers bleibt unberührt: Vernetzen ändert Merker in der BRep und damit
    Formschlüssel); je Form und Netzfeinheit zwischengespeichert, solange die Form lebt."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    key = (hash(shape), round(netz, 6))
    with _NETZE_LOCK:
        hit = _NETZE.get(key)
        if hit is not None and hit[0].IsSame(shape) and hit[0].Location().IsEqual(shape.Location()):
            _NETZE.move_to_end(key)
            return hit[1]
    kopie = BRepBuilderAPI_Copy(shape, True, False).Shape()
    BRepMesh_IncrementalMesh(kopie, netz, False, 0.1, True)
    with _NETZE_LOCK:
        _NETZE[key] = (shape, kopie)  # die Originalform festhalten, damit ihr Hash nicht neu vergeben wird
        while len(_NETZE) > 600:
            _NETZE.popitem(last=False)
    return kopie


def _groesse(liste: list[tuple[str, Any]]) -> float:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    for _, s in liste:
        BRepBndLib.Add_s(s, box, False)
    if box.IsVoid():
        return 100.0
    a, b = box.CornerMin(), box.CornerMax()
    return max(b.X() - a.X(), b.Y() - a.Y(), b.Z() - a.Z(), 1e-3)


def _hlr(liste: list[tuple[str, Any]], b: Blick, *, verdeckt: bool, glatt: bool, toleranz: float, exakt: bool,
         je_teil: bool, netz: float = 0.05) -> dict[str, dict[str, list[Polylinie]]]:
    """Verdeckungsrechnung im aufrufenden Prozess: exakt (HLRBRep_Algo) oder auf dem Netz (HLRBRep_PolyAlgo mit
    Netzabweichung ``netz`` mm und 0,1 rad Winkel, damit Kreise auf dem Blatt rund wirken)."""
    from OCP.HLRAlgo import HLRAlgo_Projector

    projector = HLRAlgo_Projector(_ax2(b))
    if exakt:
        from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape

        algo = HLRBRep_Algo()
        for _, s in liste:
            algo.Add(s)
        algo.Projector(projector)
        algo.Update()
        algo.Hide()
        h = HLRBRep_HLRToShape(algo)
    else:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape

        algo = HLRBRep_PolyAlgo()
        kopien = []
        for name, s in liste:
            k = _vernetzte_kopie(s, netz)
            kopien.append((name, k))
            algo.Load(k)
        liste = kopien
        algo.Projector(projector)
        algo.Update()
        h = HLRBRep_PolyHLRToShape()
        h.Update(algo)

    def sammle(*args: Any) -> dict[str, list[Polylinie]]:
        d: dict[str, list[Polylinie]] = {a: [] for a in LINIENARTEN}
        d["sichtbar"] = _kanten(h.VCompound(*args), toleranz) + _kanten(h.OutLineVCompound(*args), toleranz)
        if verdeckt:
            d["verdeckt"] = _kanten(h.HCompound(*args), toleranz) + _kanten(h.OutLineHCompound(*args), toleranz)
        if glatt:
            d["duenn"] = _kanten(h.Rg1LineVCompound(*args), toleranz)
        return d

    if not je_teil:
        return {"*": sammle()}
    return {name: sammle(s) for name, s in liste}


# ---------------------------------------------------------------------------------------------------------------------
# Exakte Rechnung in einem eigenen Prozess (Zeitbudget, Abbruch durch Beenden)
# ---------------------------------------------------------------------------------------------------------------------


class _ExaktProzess:
    """Hält einen Hilfsprozess (``python -m kevcad_kernel.zeichnung.hlr_prozess``) für exakte Verdeckungsrechnungen.
    Überschreitet eine Rechnung ihr Budget, wird der Prozess beendet (OCP kann nicht abbrechen) und beim nächsten
    Bedarf neu gestartet."""

    START_S = 30.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Any = None
        self._antworten: Any = None
        self._ids = 0
        self.statistik = {"exakt": 0, "zu_langsam": 0, "fehler": 0}

    def _start(self) -> bool:
        import os
        import queue
        import subprocess
        import sys

        from kevcad_kernel.protocol import FrameReader

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        self._proc = subprocess.Popen([sys.executable, "-m", "kevcad_kernel.zeichnung.hlr_prozess"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      bufsize=0, env=env, close_fds=True)
        self._antworten = queue.Queue()
        proc, q = self._proc, self._antworten

        def lesen() -> None:
            reader = FrameReader()
            while True:
                try:
                    data = os.read(proc.stdout.fileno(), 1 << 20)
                except (OSError, ValueError):
                    break
                if not data:
                    break
                for kopf, nutz in reader.feed(data):
                    q.put((kopf, nutz))
            q.put(({"type": "ENDE"}, b""))

        threading.Thread(target=lesen, name="kevcad-hlr-exakt", daemon=True).start()
        try:
            kopf, _ = q.get(timeout=self.START_S)
        except Exception:  # noqa: BLE001
            self._stopp()
            return False
        return kopf.get("type") == "BEREIT"

    def _stopp(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(2)
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

    def rechne(self, liste: list[tuple[str, Any]], b: Blick, *, verdeckt: bool, glatt: bool, toleranz: float,
               je_teil: bool, budget: float) -> dict[str, dict[str, list[Polylinie]]] | None:
        import queue

        from kevcad_kernel.protocol import encode_frame
        from kevcad_kernel.tessellate import serialize_shape

        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                if not self._start():
                    self.statistik["fehler"] += 1
                    return None
            self._ids += 1
            rid = self._ids
            breps = [serialize_shape(s) for _, s in liste]
            kopf = {"type": "HLR", "id": rid, "blick": b.als_dict(), "verdeckt": verdeckt, "glatt": glatt,
                    "toleranz": toleranz, "je_teil": je_teil,
                    "teile": [{"name": n, "len": len(x)} for (n, _), x in zip(liste, breps)]}
            try:
                self._proc.stdin.write(encode_frame(kopf, b"".join(breps)))
                self._proc.stdin.flush()
            except (OSError, ValueError):
                self._stopp()
                self.statistik["fehler"] += 1
                return None
            ende = time.monotonic() + budget
            while True:
                rest = ende - time.monotonic()
                if rest <= 0:
                    self._stopp()
                    self.statistik["zu_langsam"] += 1
                    return None
                try:
                    antwort, nutz = self._antworten.get(timeout=rest)
                except queue.Empty:
                    continue
                if antwort.get("type") == "ENDE":
                    self._proc = None
                    self.statistik["fehler"] += 1
                    return None
                if antwort.get("id") != rid:
                    continue
                if not antwort.get("ok"):
                    self.statistik["fehler"] += 1
                    return None
                self.statistik["exakt"] += 1
                return lies_linien(antwort, nutz)

    def schliessen(self) -> None:
        with self._lock:
            self._stopp()


def lies_linien(kopf: dict[str, Any], daten: bytes) -> dict[str, dict[str, list[Polylinie]]]:
    """Antwort des Hilfsprozesses: je Teil, je Linienart u32 Anzahl, je Polylinie u32 Punktzahl und f64 x, y."""
    import struct

    out: dict[str, dict[str, list[Polylinie]]] = {}
    off = 0
    for name in kopf.get("teile") or []:
        d: dict[str, list[Polylinie]] = {a: [] for a in LINIENARTEN}
        for art in kopf.get("arten") or LINIENARTEN:
            (n,) = struct.unpack_from("<I", daten, off)
            off += 4
            for _ in range(n):
                (k,) = struct.unpack_from("<I", daten, off)
                off += 4
                d.setdefault(art, []).append(
                    np.frombuffer(daten, dtype="<f8", count=2 * k, offset=off).reshape(-1, 2).copy())
                off += 16 * k
        out[name] = d
    return out


def schreibe_linien(teile: dict[str, dict[str, list[Polylinie]]]) -> tuple[list[str], bytes]:
    import struct

    namen = list(teile)
    blobs = []
    for name in namen:
        for art in LINIENARTEN:
            ls = teile[name].get(art) or []
            blobs.append(struct.pack("<I", len(ls)))
            for pl in ls:
                arr = np.ascontiguousarray(pl, dtype="<f8").reshape(-1, 2)
                blobs.append(struct.pack("<I", len(arr)))
                blobs.append(arr.tobytes())
    return namen, b"".join(blobs)


EXAKT = _ExaktProzess()

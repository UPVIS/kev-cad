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

Rechenweg: OCCT Hidden Line Removal exakt auf der B-Rep (HLRBRep_Algo), ab ``POLY_AB_FLAECHEN`` Flächen auf dem Netz
(HLRBRep_PolyAlgo; Kevin hat dafür keine sichtbare Einbuße bei Zusammenbauten). Ergebnisse liegen in einem
Zwischenspeicher je Formschlüssel, Ansicht und Optionen.
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

LINIENARTEN = ("sichtbar", "verdeckt", "mitte", "schnitt", "schraffur", "duenn")
POLY_AB_FLAECHEN = 60000  # ab so vielen Flächen insgesamt rechnet die Verdeckung auf dem Netz
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


def _anzahl_flaechen(formen: list[tuple[str, Any]]) -> int:
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    n = 0
    for _, s in formen:
        exp = TopExp_Explorer(s, TopAbs_FACE)
        while exp.More():
            n += 1
            exp.Next()
    return n


def projiziere(formen: Any, ansicht: Any = "vorn", *, verdeckt: bool = True, glatt: bool = True,
               mittel: bool = True, ueberstand: float = 3.0, toleranz: float = 0.02, je_teil: bool = False,
               exakt: bool | None = None, schluessel: str | dict[str, str] | None = None,
               cache: _Cache | None = CACHE) -> Projektion:
    """Formen in der Ansicht ``ansicht`` projizieren (Modulbeschreibung). ``glatt``: Lichtkanten (tangentiale
    Übergänge, etwa am Rand einer Rundung) als ``duenn``. ``mittel``: Mittellinien. ``schluessel``: Formschlüssel
    (ein Text für alle oder je Name), sonst aus der BRep gerechnet. ``exakt``: None wählt nach Größe."""
    b = blick(ansicht)
    liste = _formen(formen)
    if isinstance(schluessel, dict):
        keys = [str(schluessel.get(n) or form_schluessel(s)) for n, s in liste]
    elif isinstance(schluessel, str):
        keys = [schluessel]
    else:
        keys = [form_schluessel(s) for _, s in liste] if cache is not None else []
    key = None
    if cache is not None:
        opts = f"{int(verdeckt)}{int(glatt)}{int(mittel)}{ueberstand:g}{toleranz:g}{int(je_teil)}{exakt}"
        names = "|".join(n for n, _ in liste) if je_teil else ""
        key = hashlib.sha1(("|".join(keys) + b.schluessel + opts + names).encode()).hexdigest()
        hit = cache.get(key)
        if hit is not None:
            out = Projektion(hit.blick, hit.linien, hit.teile, hit.rahmen, hit.ms, hit.exakt, True)
            return out
    t0 = time.perf_counter()
    if exakt is None:
        exakt = _anzahl_flaechen(liste) < POLY_AB_FLAECHEN
    proj = Projektion(b, exakt=bool(exakt))
    if liste:
        teile = _hlr(liste, b, verdeckt=verdeckt, glatt=glatt, toleranz=toleranz, exakt=bool(exakt), je_teil=je_teil)
        if je_teil:
            proj.teile = teile
            for d in teile.values():
                for art, ls in d.items():
                    proj.linien[art] += ls
        else:
            proj.linien.update(teile["*"])
        if mittel:
            proj.linien["mitte"] = mittellinien(liste, b, ueberstand)
    if proj.linien["verdeckt"]:
        groesse = max(1.0, *(abs(v) for v in _rahmen(proj.linien["sichtbar"])))
        proj.linien["verdeckt"] = ohne_ueberdeckte(proj.linien["verdeckt"], proj.linien["sichtbar"], 1e-4 * groesse)
        for d in proj.teile.values():
            d["verdeckt"] = ohne_ueberdeckte(d.get("verdeckt") or [], proj.linien["sichtbar"], 1e-4 * groesse)
    for art in ("sichtbar", "verdeckt", "duenn"):
        proj.linien[art] = verbinde(proj.linien[art])
    proj.rahmen = _rahmen(proj.linien["sichtbar"] or proj.linien["verdeckt"])
    proj.ms = (time.perf_counter() - t0) * 1000.0
    if cache is not None and key is not None:
        cache.put(key, proj)
    return proj


def _hlr(liste: list[tuple[str, Any]], b: Blick, *, verdeckt: bool, glatt: bool, toleranz: float, exakt: bool,
         je_teil: bool) -> dict[str, dict[str, list[Polylinie]]]:
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
        for _, s in liste:
            BRepMesh_IncrementalMesh(s, max(toleranz * 5, 0.05), False, 0.3, True)
            algo.Load(s)
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

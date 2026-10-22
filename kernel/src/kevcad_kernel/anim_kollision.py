"""Kollisionsprüfung bewegter Teile an Zeitschritten (Phase 5, Strang ANI, Entscheidung A3).

Bewusst eine kleine, eigenständige Funktion mit klarer Schnittstelle, damit sie beim Zusammenführen mit dem Strang
„Prüfungen“ (``kevcad_kernel/pruefung/kollision.py``) auf dessen gemeinsame Durchdringungsprüfung umgestellt werden
kann:

    pruefe_kollisionen(formen, lagen, zeiten, *, bilder, paare, huellen, kugeln, toleranz, min_volumen, sichtbar)
        -> (befunde: list[Befund], statistik: dict)

- ``formen``: Name → build123d-Form in Ruhelage (Weltkoordinaten wie in model.py).
- ``lagen``: Name → (N, 4, 4) Lage je Bild; fehlende Namen stehen still.
- ``zeiten``: (N,) Zeit je Bild in s; ``bilder``: zu prüfende Bildnummern (Vorgabe alle).
- ``paare``: zu prüfende Paare (Vorgabe: alle Paare, deren Lage zueinander sich ändert).
- ``huellen`` / ``kugeln`` (optional): Hüllquader bzw. Hüllkugeln in Ruhelage für die Vorprüfung.
- Ergebnis je Bild und Paar mit Durchdringung: ``Befund(zeit, bild, teile, volumen, tiefe, ort)``. Berührungen (Volumen
  unter ``min_volumen`` mm³ oder Dicke unter ``toleranz`` mm) gelten nicht als Durchdringung.

Ablauf je Paar und Bild: Hüllquader-Vorprüfung in der Lage des ersten Teils, dann exakt mit dem OCCT-Schnittvolumen
(BRepAlgoAPI_Common); gleiche relative Lagen werden nur einmal gerechnet. Die Eindringtiefe ist eine Näherung: die
kleinste Ausdehnung des Schnittkörpers.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np


_FEHLT = object()  # Marke für „nicht im Zwischenspeicher“ (None ist ein gültiges Ergebnis)


@dataclass
class Befund:
    zeit: float
    bild: int
    teile: tuple[str, str]
    volumen: float  # mm³ Schnittvolumen
    tiefe: float  # mm, kleinste Ausdehnung des Schnittkörpers (Näherung der Eindringtiefe)
    ort: tuple[float, float, float]  # Mitte des Schnittkörpers in Weltkoordinaten

    def as_dict(self) -> dict[str, Any]:
        return {"zeit": round(self.zeit, 4), "bild": self.bild, "teile": list(self.teile),
                "volumen": round(self.volumen, 3), "tiefe": round(self.tiefe, 3),
                "ort": [round(c, 3) for c in self.ort]}


def _orthonormal(m: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(m[:3, :3])
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    out = np.eye(4)
    out[:3, :3] = r
    out[:3, 3] = m[:3, 3]
    return out


def _trsf(m: np.ndarray):
    from OCP.gp import gp_Trsf

    m = _orthonormal(m)
    t = gp_Trsf()
    t.SetValues(*m[0, :4], *m[1, :4], *m[2, :4])
    return t


def _moved(shape: Any, m: np.ndarray):
    """OCCT-Form (TopoDS_Shape) mit Lage ``m`` (4 × 4), ohne Kopie der Geometrie."""
    from OCP.TopLoc import TopLoc_Location

    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    return wrapped.Moved(TopLoc_Location(_trsf(m)))


def _box_of(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    bb = shape.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


def _corners(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.array([[lo[0] if i & 1 == 0 else hi[0], lo[1] if i & 2 == 0 else hi[1], lo[2] if i & 4 == 0 else hi[2]]
                     for i in range(8)])


def _common(a: Any, b_moved: Any) -> tuple[float, np.ndarray, np.ndarray] | None:
    """Schnittkörper von ``a`` (Ruhelage) und ``b_moved``: (Volumen, min, max) oder None."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps

    wa = a.wrapped if hasattr(a, "wrapped") else a
    op = BRepAlgoAPI_Common(wa, b_moved)
    if not op.IsDone():
        return None
    res = op.Shape()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(res, props)
    vol = abs(props.Mass())
    if vol <= 0:
        return 0.0, np.zeros(3), np.zeros(3)
    box = Bnd_Box()
    BRepBndLib.Add_s(res, box)
    if box.IsVoid():
        return vol, np.zeros(3), np.zeros(3)
    lo, hi = box.CornerMin(), box.CornerMax()
    return vol, np.array([lo.X(), lo.Y(), lo.Z()]), np.array([hi.X(), hi.Y(), hi.Z()])


def rotationssymmetrisch(form: Any, punkt: Sequence[float], richtung: Sequence[float],
                         winkel: Sequence[float] = (23.0, 137.0), rel_tol: float = 2e-3,
                         achs_tol: float = 0.5) -> bool:
    """Ist ``form`` unter Drehung um die Achse (``punkt``, ``richtung``) unverändert (Rad, Rolle, Ring)? Dann ändert ihr
    Drehen um diese Achse nichts an der Kollision.

    Der Punkt stammt meist aus dem vernetzten Hüllquader und liegt etwas neben der wahren Achse; liegt der Schwerpunkt
    (der bei Drehsymmetrie auf der Achse liegt) näher als ``achs_tol`` mm an der Achse, wird durch ihn geprüft."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    from kevcad_kernel.animation import about, rotation3

    wrapped = form.wrapped if hasattr(form, "wrapped") else form
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(wrapped, props)
    vol = abs(props.Mass())
    if vol <= 0:
        return False
    p, d = np.asarray(punkt, float), np.asarray(richtung, float)
    d = d / np.linalg.norm(d)
    c = props.CentreOfMass()
    com = np.array([c.X(), c.Y(), c.Z()])
    off = com - p
    off_perp = off - np.dot(off, d) * d
    if np.linalg.norm(off_perp) > achs_tol:
        return False
    p = p + off_perp
    for w in winkel:
        m = about(p, rotation3(d, np.radians([w])))[0]
        res = _common(form, _moved(form, m))
        if res is None or res[0] < vol * (1.0 - rel_tol):
            return False
    return True


def huellkugel(punkte: np.ndarray, mitte: Sequence[float], zugabe: float = 0.2) -> tuple[np.ndarray, float]:
    """Hüllkugel um ``mitte`` aus den Netzpunkten eines Teils (mit ``zugabe`` für die Sehnenabweichung des Netzes)."""
    c = np.asarray(mitte, float)
    pts = np.asarray(punkte, float).reshape(-1, 3)
    r = float(np.max(np.linalg.norm(pts - c[None], axis=1))) if len(pts) else 0.0
    return c, r + zugabe


def _point_distance(point: np.ndarray, shape: Any) -> tuple[float, bool]:
    """(Abstand des Punkts zur Form, Punkt liegt innen)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    pnt = gp_Pnt(*[float(x) for x in point])
    v = BRepBuilderAPI_MakeVertex(pnt).Vertex()
    dist = BRepExtrema_DistShapeShape(v, wrapped)
    d = float(dist.Value()) if dist.IsDone() else 0.0
    inside = False
    try:
        cls = BRepClass3d_SolidClassifier(wrapped, pnt, 1e-6)
        inside = cls.State() == TopAbs_IN
    except Exception:  # noqa: BLE001
        inside = True
    return d, inside


def bewegte_paare(namen: Sequence[str], lagen: Mapping[str, np.ndarray], bilder: Sequence[int],
                  erlaubt: Callable[[str, str], bool] | None = None) -> list[tuple[str, str]]:
    """Paare, deren Lage zueinander sich über ``bilder`` ändert (starr verbundene Teile zählen nicht)."""
    moving = [n for n in namen if n in lagen]
    idx = list(bilder)
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for a in moving:
        ta = lagen[a][idx]
        for b in namen:
            if b == a:
                continue
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            if erlaubt is not None and erlaubt(a, b):
                continue
            tb = lagen[b][idx] if b in lagen else None
            if tb is None:
                rel = ta
            else:
                rel = np.linalg.inv(ta) @ tb
            if np.allclose(rel, rel[:1], atol=1e-4):
                continue  # starr: Lage zueinander bleibt gleich
            out.append(key)
    return out


def pruefe_kollisionen(formen: Mapping[str, Any], lagen: Mapping[str, np.ndarray], zeiten: Sequence[float], *,
                       bilder: Iterable[int] | None = None, paare: Iterable[tuple[str, str]] | None = None,
                       huellen: Mapping[str, tuple[Sequence[float], Sequence[float]]] | None = None,
                       kugeln: Mapping[str, tuple[Sequence[float], float]] | None = None,
                       toleranz: float = 0.05, min_volumen: float = 0.5,
                       sichtbar: Callable[[str, int], bool] | None = None,
                       zeitlimit_s: float | None = None, cache: MutableMapping[tuple, Any] | None = None,
                       schluessel: Mapping[str, str] | None = None,
                       abbrechen: Callable[[], None] | None = None) -> tuple[list[Befund], dict[str, Any]]:
    """Durchdringungen von Teilepaaren an Zeitschritten (siehe Moduldoku).

    ``kugeln`` (optional): Name → (Mitte, Radius) einer Hüllkugel in Ruhelage. Dreht sich ein Teil gegenüber dem
    anderen nur um diese Mitte (Kugel, die rollt), und berührt das andere Teil die Kugel nicht, ist das Paar für alle
    Bilder frei; das spart die teuren exakten Prüfungen.

    ``cache`` (optional): Zwischenspeicher über Aufrufe hinweg (z. B. über Läufe), Schlüssel aus ``schluessel``
    (Name → Geometrieschlüssel der Form in Ruhelage, sonst der Name) und der relativen Lage beider Teile.

    ``abbrechen`` (optional): wird vor jeder exakten Rechnung aufgerufen und darf mit einer Ausnahme unterbrechen
    (Bewegungsraum im Hintergrund: ein neuer Auftrag geht vor); was bis dahin gerechnet ist, steht im ``cache``."""
    t0 = time.perf_counter()
    zeiten = np.asarray(zeiten, dtype=float)
    frames = np.array(sorted(set(bilder)) if bilder is not None else range(len(zeiten)), dtype=int)
    namen = list(formen)
    pairs = list(paare) if paare is not None else bewegte_paare(namen, lagen, frames)
    boxes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for n in {x for p in pairs for x in p}:
        if huellen is not None and n in huellen:
            lo, hi = huellen[n]
            boxes[n] = (np.asarray(lo, float), np.asarray(hi, float))
        else:
            boxes[n] = _box_of(formen[n])
    eye = np.repeat(np.eye(4)[None], len(frames), axis=0)
    vis_cache: dict[str, np.ndarray] = {}

    def vis(name: str) -> np.ndarray:
        if name not in vis_cache:
            vis_cache[name] = (np.array([bool(sichtbar(name, int(k))) for k in frames]) if sichtbar is not None
                               else np.ones(len(frames), bool))
        return vis_cache[name]

    stats = {"paare": len(pairs), "bilder": int(len(frames)), "kandidaten": 0, "kugel_frei": 0, "exakt": 0,
             "zwischenspeicher": 0, "abgebrochen": False}
    befunde: list[Befund] = []
    if cache is None:
        cache = {}
    sk = schluessel or {}
    for a, b in pairs:
        if zeitlimit_s is not None and time.perf_counter() - t0 > zeitlimit_s:
            stats["abgebrochen"] = True
            break
        ta = lagen[a][frames] if a in lagen else eye
        tb = lagen[b][frames] if b in lagen else eye
        rel = np.linalg.solve(ta, tb)  # Lage von b im Ruhesystem von a, je Bild
        alo, ahi = boxes[a]
        pc = np.einsum("fij,kj->fki", rel[:, :3, :3], _corners(*boxes[b])) + rel[:, None, :3, 3]
        blo, bhi = pc.min(axis=1), pc.max(axis=1)
        mask = np.all(blo < ahi - toleranz, axis=1) & np.all(bhi > alo + toleranz, axis=1) & vis(a) & vis(b)
        if not mask.any():
            continue
        stats["kandidaten"] += 1
        if kugeln is not None and _sphere_free(a, b, rel[mask], formen, kugeln, toleranz):
            stats["kugel_frei"] += 1
            continue
        for i in np.nonzero(mask)[0]:
            if zeitlimit_s is not None and time.perf_counter() - t0 > zeitlimit_s:
                stats["abgebrochen"] = True
                break
            k = int(frames[i])
            key = (sk.get(a, a), sk.get(b, b), tuple(np.round(rel[i, :3, :].ravel(), 4)))
            hit = cache.get(key, _FEHLT)
            if hit is not _FEHLT:
                stats["zwischenspeicher"] += 1
                res = hit
            else:
                if abbrechen is not None:
                    abbrechen()
                stats["exakt"] += 1
                res = _common(formen[a], _moved(formen[b], rel[i]))
                cache[key] = res
            if res is None:
                continue
            vol, lo, hi = res
            if vol < min_volumen:
                continue
            depth = float(np.min(hi - lo))
            if depth < toleranz:
                continue
            center = ta[i, :3, :3] @ ((lo + hi) / 2.0) + ta[i, :3, 3]
            befunde.append(Befund(zeit=float(zeiten[k]), bild=k, teile=(a, b), volumen=float(vol), tiefe=depth,
                                  ort=tuple(float(c) for c in center)))
    stats["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return befunde, stats


def _sphere_free(a: str, b: str, rel: np.ndarray, formen: Mapping[str, Any],
                 kugeln: Mapping[str, tuple[Sequence[float], float]], toleranz: float) -> bool:
    """Dreht sich eines der Teile gegenüber dem anderen nur um die Mitte seiner Hüllkugel und liegt das andere ganz
    außerhalb dieser Kugel, kann es in keinem Bild eine Durchdringung geben."""
    if b in kugeln:  # Mitte von b im System von a
        c, r = kugeln[b]
        c = np.asarray(c, float)
        pts = rel[:, :3, :3] @ c + rel[:, :3, 3]
        if np.allclose(pts, pts[:1], atol=1e-3):
            d, inside = _point_distance(pts[0], formen[a])
            if not inside and d > r + toleranz:
                return True
    if a in kugeln:  # Mitte von a im System von b
        c, r = kugeln[a]
        c = np.asarray(c, float)
        inv = np.linalg.inv(rel)
        pts = inv[:, :3, :3] @ c + inv[:, :3, 3]
        if np.allclose(pts, pts[:1], atol=1e-3):
            d, inside = _point_distance(pts[0], formen[b])
            if not inside and d > r + toleranz:
                return True
    return False


def zusammenfassen(befunde: Sequence[Befund], bilder: Sequence[int]) -> list[dict[str, Any]]:
    """Befunde je Paar zu Zeitspannen zusammenfassen (aufeinanderfolgende geprüfte Bilder): von, bis, Zeit und Bild der
    größten Eindringtiefe, Tiefe, Volumen, Ort. Sortiert nach Beginn."""
    order = {k: i for i, k in enumerate(sorted(set(bilder)))}
    by_pair: dict[tuple[str, str], list[Befund]] = {}
    for b in befunde:
        by_pair.setdefault(b.teile, []).append(b)
    out: list[dict[str, Any]] = []
    for pair, items in by_pair.items():
        items.sort(key=lambda b: b.bild)
        run: list[Befund] = []
        for b in items + [None]:  # type: ignore[list-item]
            if b is not None and (not run or order.get(b.bild, -2) == order.get(run[-1].bild, -5) + 1):
                run.append(b)
                continue
            if run:
                worst = max(run, key=lambda x: x.tiefe)
                out.append({"teile": list(pair), "von": round(run[0].zeit, 4), "bis": round(run[-1].zeit, 4),
                            "zeit": round(worst.zeit, 4), "bild": worst.bild, "tiefe": round(worst.tiefe, 3),
                            "volumen": round(worst.volumen, 3), "ort": [round(c, 3) for c in worst.ort],
                            "bilder": [x.bild for x in run]})
            run = [b] if b is not None else []
    out.sort(key=lambda e: (e["von"], e["teile"]))
    return out

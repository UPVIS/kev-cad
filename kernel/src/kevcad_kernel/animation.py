"""Animation auswerten (Phase 5, Strang ANI): Spuren aus ``kevcad.bewegung`` → Lage jedes Teils je Bild.

Läuft im Rechenprozess direkt nach model.py (``runner.Runner.run``), braucht nur die Namen und Hüllquader der gezeigten
Teile und numpy. Ergebnis je Animation ist ein ``Auswertung`` mit den Matrizen (Bilder × Teile × 4 × 4), der Kamerafahrt,
den Sichtbarkeiten und den Angaben für die Kollisionsprüfung (Drehachsen, gewollte Berührungen).

Modell der Bewegung:

- Jedes Ziel einer Spur (Teil oder Baugruppenpräfix) ist ein *Objekt*. Ein Teil gehört zum genauesten Objekt, das es
  umfasst ("Wagen/Rad 1" vor "Wagen").
- Eltern eines Objekts: das nächste umfassende Objekt im Baum, oder ausdrücklich über ``folge``, ``rolle(auf=…)`` bzw.
  ``gelenk(eltern=…)`` (wenn das Elternteil nicht ohnehin im Baum darüber liegt).
- Lage = Eltern · Verschiebungen (bewege, pfad, Schubgelenk) · Drehungen (drehe, Drehgelenk) · Rollen. Drehachsen gelten
  in der Ruhelage (Koordinaten wie in model.py), jede Spur in der Reihenfolge, in der sie angelegt wurde.
- Rollen (A2): Drehwinkel = Strecke der Mitte / Radius, je Bildschritt aufsummiert. Mit fester Achse dreht sich die Achse
  mit dem Elternteil; ohne Achse rollt das Teil frei wie eine Kugel auf dem Boden (Normale +Z).

Protokoll (PROTOCOL.md, Abschnitt „Phase 5: Animation“): ``ANIM_DEF`` mit Nutzlast float32 Bilder × Teile × 12 (je
Matrix die oberen drei Zeilen spaltenweise), danach bei Kamerafahrt Bilder × 7 (Lage, Ziel, Bildwinkel oder 0).
"""

from __future__ import annotations

import difflib
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad.bewegung import Animation, AnimationError, Spur

ROLL_NORMAL = np.array([0.0, 0.0, 1.0])
MAX_FRAMES = 20_001
_TOL = 1e-9


# ---------------------------------------------------------------------------------------------------------------------
# Kleine Mathematik (vektorisiert über die Bilder)
# ---------------------------------------------------------------------------------------------------------------------


def kurve(u: np.ndarray, art: str) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    if art == "weich":
        return u * u * (3.0 - 2.0 * u)
    if art == "ein":
        return u * u
    if art == "aus":
        return 1.0 - (1.0 - u) ** 2
    return u


def fortschritt(t: np.ndarray, von: float, bis: float, art: str) -> np.ndarray:
    """Anteil 0…1 der Spur zur Zeit ``t``; bei von == bis ein Sprung."""
    if bis - von < _TOL:
        return (t >= von - _TOL).astype(float)
    return kurve((t - von) / (bis - von), art)


def eye(n: int) -> np.ndarray:
    return np.repeat(np.eye(4)[None], n, axis=0)


def translation(d: np.ndarray) -> np.ndarray:
    """(N, 3) → (N, 4, 4)."""
    m = eye(len(d))
    m[:, :3, 3] = d
    return m


def rotation3(axis: np.ndarray, ang: np.ndarray) -> np.ndarray:
    """Drehung um die Einheitsachse ``axis`` (3,) um ``ang`` (N,) Bogenmaß → (N, 3, 3), rechte Hand."""
    x, y, z = axis
    k = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    s, c = np.sin(ang)[:, None, None], np.cos(ang)[:, None, None]
    return np.eye(3)[None] + s * k[None] + (1.0 - c) * (k @ k)[None]


def about(point: np.ndarray, rot: np.ndarray) -> np.ndarray:
    """Drehung ``rot`` (N, 3, 3) um den Punkt ``point`` (3,) → (N, 4, 4)."""
    n = len(rot)
    m = eye(n)
    m[:, :3, :3] = rot
    m[:, :3, 3] = point[None] - rot @ point
    return m


def apply_point(m: np.ndarray, p: np.ndarray) -> np.ndarray:
    """(N, 4, 4) · Punkt (3,) → (N, 3)."""
    return m[:, :3, :3] @ p + m[:, :3, 3]


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.where(n > 1e-12, v / np.where(n > 1e-12, n, 1.0), 0.0)


# ---------------------------------------------------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------------------------------------------------


def sample_path(points: list[tuple[float, float, float]], spline: bool, per_segment: int = 32) -> np.ndarray:
    """Polylinie oder Catmull-Rom-Spline (zentripetal) durch alle Punkte, fein abgetastet → (M, 3)."""
    p = np.asarray(points, dtype=float)
    # aufeinanderfolgende doppelte Punkte entfernen
    keep = np.concatenate([[True], np.linalg.norm(np.diff(p, axis=0), axis=1) > 1e-9])
    p = p[keep]
    if not spline or len(p) < 3:
        return p
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = [p[:1]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0) ** 0.5, 1e-6)
        t2 = t1 + max(np.linalg.norm(p2 - p1) ** 0.5, 1e-6)
        t3 = t2 + max(np.linalg.norm(p3 - p2) ** 0.5, 1e-6)
        tt = np.linspace(t1, t2, per_segment + 1)[1:, None]
        a1 = (t1 - tt) / (t1 - t0) * p0 + (tt - t0) / (t1 - t0) * p1
        a2 = (t2 - tt) / (t2 - t1) * p1 + (tt - t1) / (t2 - t1) * p2
        a3 = (t3 - tt) / (t3 - t2) * p2 + (tt - t2) / (t3 - t2) * p3
        b1 = (t2 - tt) / (t2 - t0) * a1 + (tt - t0) / (t2 - t0) * a2
        b2 = (t3 - tt) / (t3 - t1) * a2 + (tt - t1) / (t3 - t1) * a3
        out.append((t2 - tt) / (t2 - t1) * b1 + (tt - t1) / (t2 - t1) * b2)
    return np.vstack(out)


class PathSampler:
    """Ort und Tangente auf einem abgetasteten Pfad nach Bogenlänge."""

    def __init__(self, pts: np.ndarray) -> None:
        self.pts = pts
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])

    def at(self, s: np.ndarray) -> np.ndarray:
        s = np.clip(s, 0.0, self.length)
        return np.stack([np.interp(s, self.cum, self.pts[:, i]) for i in range(3)], axis=1)

    def tangent(self, s: np.ndarray) -> np.ndarray:
        d = max(self.length * 1e-4, 1e-6)
        a = self.at(np.clip(s - d, 0.0, self.length - 2 * d))
        b = self.at(np.clip(s + d, 2 * d, self.length))
        return _unit(b - a)


def frame_from_tangent(t: np.ndarray) -> np.ndarray:
    """Spalten (Tangente, quer, oben) mit Z oben; senkrechte Tangenten nehmen Y als quer → (N, 3, 3)."""
    up = np.array([0.0, 0.0, 1.0])
    y = np.cross(up[None], t)
    bad = np.linalg.norm(y, axis=1) < 1e-6
    y[bad] = np.array([0.0, 1.0, 0.0])
    y = _unit(y)
    z = _unit(np.cross(t, y))
    return np.stack([t, y, z], axis=2)


# ---------------------------------------------------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class Objekt:
    key: str
    parts: list[str]
    center: np.ndarray
    size: np.ndarray
    spuren: list[Spur] = field(default_factory=list)
    eltern_explizit: str | None = None
    eltern_spur: Spur | None = None
    eltern: str | None = None
    rolle: Spur | None = None


@dataclass
class Auswertung:
    """Ergebnis einer Animation (siehe Moduldoku)."""

    name: str
    dauer: float
    fps: float
    times: np.ndarray  # (N,)
    teile: list[str]  # bewegte Teile, Reihenfolge wie gezeigt
    matrices: np.ndarray  # (N, P, 4, 4)
    kamera: np.ndarray | None  # (N, 7) Lage, Ziel, Bildwinkel (0 = unverändert)
    sichtbar: list[dict[str, Any]]
    warnungen: list[str]
    spins: dict[str, tuple[list[float], list[float]]]  # Teil → Drehachse (Punkt, Richtung) in Ruhelage
    nospin: dict[str, np.ndarray]  # Teil → (N, 4, 4) ohne die Drehung um die eigene Achse
    erlaubt: list[tuple[list[str], list[str]]]
    spuren: int
    line: int | None = None
    eval_ms: float = 0.0
    standard: bool = False

    @property
    def frames(self) -> int:
        return int(len(self.times))


def frame_times(dauer: float, fps: float) -> np.ndarray:
    n = int(round(dauer * fps)) + 1
    t = np.arange(n, dtype=float) / fps
    return np.minimum(t, dauer)


class _Eval:
    def __init__(self, anim: Animation, order: list[str], bboxes: dict[str, tuple[list[float], list[float]]]) -> None:
        self.anim = anim
        self.name = anim.name or "Animation"
        self.order = [n for n in order if n in bboxes]
        self.bboxes = bboxes
        self.nameset = set(self.order)
        self.times = frame_times(anim.dauer, anim.fps)
        self.n = len(self.times)
        self.objs: dict[str, Objekt] = {}
        self.warnungen: list[str] = []
        self.T: dict[str, np.ndarray] = {}
        self.base: dict[str, np.ndarray] = {}
        self.nospin_obj: dict[str, tuple[np.ndarray, list[float], list[float]]] = {}

    # -- Namen ---------------------------------------------------------------------------------------------------------

    def fail(self, spur: Spur | None, text: str) -> AnimationError:
        where = f"{spur.art}({spur.ziel!r})" if spur is not None and spur.ziel else (spur.art if spur else "")
        head = f"Animation {self.name!r}" + (f", {where}" if where else "")
        return AnimationError(f"{head}: {text}", spur.line if spur else self.anim.line,
                              spur.filename if spur else self.anim.filename)

    def resolve(self, target: str, spur: Spur | None) -> list[str]:
        if target in self.nameset:
            return [target]
        pre = target + "/"
        hits = [n for n in self.order if n.startswith(pre)]
        if hits:
            return hits
        candidates = list(dict.fromkeys(
            [n for n in self.order] + ["/".join(n.split("/")[:i]) for n in self.order for i in range(1, n.count("/") + 1)]))
        close = difflib.get_close_matches(target, candidates, n=3, cutoff=0.5)
        tip = f" Meinten Sie {', '.join(repr(c) for c in close)}?" if close else ""
        if not self.order:
            raise self.fail(spur, f"Teil oder Baugruppe {target!r} gibt es nicht: es sind keine Teile gezeigt.")
        groups = sorted({n.split("/")[0] for n in self.order})
        shown = ", ".join(groups[:10]) + (" …" if len(groups) > 10 else "")
        raise self.fail(spur, f"Teil oder Baugruppe {target!r} gibt es nicht.{tip} Gezeigt: {shown}")

    def obj(self, key: str, spur: Spur | None) -> Objekt:
        o = self.objs.get(key)
        if o is None:
            parts = self.resolve(key, spur)
            lo = np.min([self.bboxes[p][0] for p in parts], axis=0)
            hi = np.max([self.bboxes[p][1] for p in parts], axis=0)
            o = Objekt(key=key, parts=parts, center=(np.asarray(lo) + np.asarray(hi)) / 2.0,
                       size=np.asarray(hi) - np.asarray(lo))
            self.objs[key] = o
        return o

    @staticmethod
    def covers(key: str, name: str) -> bool:
        return name == key or name.startswith(key + "/")

    def owner(self, part: str) -> Objekt | None:
        best = None
        for o in self.objs.values():
            if self.covers(o.key, part) and (best is None or len(o.key) > len(best.key)):
                best = o
        return best

    # -- Aufbau --------------------------------------------------------------------------------------------------------

    def build(self) -> None:
        motion = ("bewege", "drehe", "pfad", "gelenk")
        for s in self.anim.spuren:
            if s.art in motion:
                self.obj(s.ziel, s).spuren.append(s)
            elif s.art == "rolle":
                o = self.obj(s.ziel, s)
                if o.rolle is not None:
                    raise self.fail(s, f"{s.ziel!r} rollt schon (Zeile {o.rolle.line}); je Teil eine rolle()")
                o.rolle = s
                if s.werte.get("auf"):
                    self.set_parent(o, self.obj(s.werte["auf"], s), s)
            elif s.art == "folge":
                o = self.obj(s.ziel, s)
                self.set_parent(o, self.obj(s.werte["eltern"], s), s)
            elif s.art in ("sichtbar", "erlaube"):
                self.resolve(s.ziel, s)
                if s.art == "erlaube":
                    self.resolve(s.werte["b"], s)
            elif s.art == "ansicht" and s.werte.get("mit"):
                self.resolve(s.werte["mit"], s)
        for s in self.anim.spuren:  # Gelenk-Eltern erst, wenn alle Objekte da sind
            if s.art == "gelenk" and s.werte.get("eltern"):
                self.set_parent(self.objs[s.ziel], self.obj(s.werte["eltern"], s), s)
        for o in self.objs.values():
            if o.eltern_explizit is not None:
                o.eltern = o.eltern_explizit
                continue
            best = None
            for q in self.objs.values():
                if q.key != o.key and o.key.startswith(q.key + "/") and (best is None or len(q.key) > len(best.key)):
                    best = q
            o.eltern = best.key if best is not None else None
        # Kreise
        for o in self.objs.values():
            seen = [o.key]
            cur = o.eltern
            while cur is not None:
                if cur in seen:
                    chain = " → ".join(seen + [cur])
                    raise self.fail(o.eltern_spur, f"die Eltern bilden einen Kreis: {chain}")
                seen.append(cur)
                cur = self.objs[cur].eltern

    def set_parent(self, o: Objekt, parent: Objekt, spur: Spur) -> None:
        if o.key == parent.key:
            raise self.fail(spur, f"{o.key!r} kann nicht sich selbst folgen")
        if o.key.startswith(parent.key + "/"):
            return  # liegt schon im Baum darunter
        if o.eltern_explizit is not None and o.eltern_explizit != parent.key:
            where = f" (Zeile {o.eltern_spur.line})" if o.eltern_spur and o.eltern_spur.line else ""
            raise self.fail(spur, f"{o.key!r} folgt schon {o.eltern_explizit!r}{where}")
        o.eltern_explizit = parent.key
        o.eltern_spur = spur

    # -- Spuren --------------------------------------------------------------------------------------------------------

    def axis_of(self, o: Objekt, achse: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        d = np.asarray(achse["richtung"], dtype=float)
        p = np.asarray(achse["punkt"], dtype=float) if achse.get("punkt") is not None else o.center.copy()
        return p, d / np.linalg.norm(d)

    def track_matrix(self, o: Objekt, s: Spur) -> tuple[str, np.ndarray, tuple[np.ndarray, np.ndarray] | None]:
        """(Art "P" oder "R", (N, 4, 4), Drehachse bei "R")."""
        w, t = s.werte, self.times
        if s.art == "bewege":
            f = fortschritt(t, w["von"], w["bis"], w["kurve"])
            return "P", translation(f[:, None] * np.asarray(w["nach"])[None]), None
        if s.art == "drehe":
            p, d = self.axis_of(o, w["achse"])
            ang = np.radians(w["winkel"]) * fortschritt(t, w["von"], w["bis"], w["kurve"])
            return "R", about(p, rotation3(d, ang)), (p, d)
        if s.art == "pfad":
            sampler = PathSampler(sample_path(w["punkte"], w["spline"]))
            sl = sampler.length * fortschritt(t, w["von"], w["bis"], w["kurve"])
            pos = sampler.at(sl)
            start = sampler.at(np.zeros(1))[0]
            ref = np.asarray(w["bezug"]) if w.get("bezug") is not None else start
            pivot = ref if w.get("bezug") is not None else o.center
            m = translation(pos - ref[None])
            if w["ausrichten"]:
                f0 = frame_from_tangent(sampler.tangent(np.zeros(1)))[0]
                fs = frame_from_tangent(sampler.tangent(sl))
                m = m @ about(pivot, fs @ f0.T)
            return "P", m, None
        if s.art == "gelenk":
            vals = self.joint_values(s)
            p, d = self.axis_of(o, w["achse"])
            if w["gelenk"] == "dreh":
                return "R", about(p, rotation3(d, np.radians(vals))), (p, d)
            return "P", translation(vals[:, None] * d[None]), None
        raise self.fail(s, f"unbekannte Spur {s.art}")

    def joint_values(self, s: Spur) -> np.ndarray:
        w, t = s.werte, self.times
        keys = w["werte"]
        kt = np.array([k[0] for k in keys])
        kv = np.array([k[1] for k in keys])
        vals = np.full(self.n, kv[0])
        for i in range(len(keys) - 1):
            seg = (t >= kt[i]) & (t <= kt[i + 1])
            u = kurve((t[seg] - kt[i]) / (kt[i + 1] - kt[i]), w["kurve"])
            vals[seg] = kv[i] + (kv[i + 1] - kv[i]) * u
        vals[t > kt[-1]] = kv[-1]
        lim = w.get("grenzen")
        if lim is not None:
            lo, hi = lim
            unit = "°" if w["gelenk"] == "dreh" else " mm"
            over, under = vals > hi + 1e-9, vals < lo - 1e-9
            if over.any():
                k = int(np.argmax(vals))
                self.warnungen.append(
                    f"Gelenk {s.ziel!r}{s.ort()}: {_de(vals[k])}{unit} bei {_de(t[k], 2)} s liegt über der Grenze "
                    f"{_de(hi)}{unit}, auf die Grenze begrenzt")
            if under.any():
                k = int(np.argmin(vals))
                self.warnungen.append(
                    f"Gelenk {s.ziel!r}{s.ort()}: {_de(vals[k])}{unit} bei {_de(t[k], 2)} s liegt unter der Grenze "
                    f"{_de(lo)}{unit}, auf die Grenze begrenzt")
            vals = np.clip(vals, lo, hi)
        return vals

    # -- Lagen ---------------------------------------------------------------------------------------------------------

    def transform(self, key: str) -> np.ndarray:
        if key in self.T:
            return self.T[key]
        o = self.objs[key]
        parent = self.transform(o.eltern) if o.eltern is not None else eye(self.n)
        P, R = eye(self.n), eye(self.n)
        axes: list[tuple[np.ndarray, np.ndarray]] = []
        for s in o.spuren:
            kind, m, axis = self.track_matrix(o, s)
            if kind == "P":
                P = m @ P
            else:
                R = m @ R
                axes.append(axis)  # type: ignore[arg-type]
        base = parent @ P @ R
        T = base
        if o.rolle is not None:
            roll, axis = self.roll(o, base)
            T = base @ roll
            if axis is not None:
                axes.append(axis)
            else:
                axes.append((np.zeros(3), np.zeros(3)))  # freies Rollen: keine feste Achse
        if axes and _same_line(axes):
            p, d = axes[0]
            self.nospin_obj[key] = (parent @ P, [float(x) for x in p], [float(x) for x in d])
        self.T[key] = T
        return T

    def roll(self, o: Objekt, base: np.ndarray) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray] | None]:
        s = o.rolle
        assert s is not None
        w = s.werte
        r = w.get("radius")
        if r is None:
            r = float(o.size[2]) / 2.0
            if r <= 1e-6:
                raise self.fail(s, "radius fehlt und das Teil hat keine Höhe; radius=… angeben")
        n = ROLL_NORMAL
        if w.get("achse") is not None:
            c, a = self.axis_of(o, w["achse"])
            q = apply_point(base, c)
            a_w = base[:, :3, :3] @ a
            roll_dir = np.cross(a_w, n[None])
            dq = np.diff(q, axis=0)
            dth = np.sum(dq * roll_dir[1:], axis=1) / r
            theta = np.concatenate([[0.0], np.cumsum(dth)])
            if np.allclose(theta, 0.0) and np.allclose(dq, 0.0):
                self.warnungen.append(f"rolle({o.key!r}){s.ort()}: das Teil bewegt sich nicht, es rollt also nicht")
            return about(c, rotation3(a, theta)), (c, a)
        c = o.center
        q = apply_point(base, c)
        brot = base[:, :3, :3]
        W = brot[0].copy()
        rr = np.empty((self.n, 3, 3))
        rr[0] = brot[0].T @ W
        moved = False
        for k in range(1, self.n):
            dq = q[k] - q[k - 1]
            dq_h = dq - np.dot(dq, n) * n
            d = float(np.linalg.norm(dq_h))
            if d > 1e-12:
                moved = True
                axis = np.cross(n, dq_h / d)
                W = rotation3(axis, np.array([d / r]))[0] @ W
            rr[k] = brot[k].T @ W
        if not moved:
            self.warnungen.append(f"rolle({o.key!r}){s.ort()}: das Teil bewegt sich nicht, es rollt also nicht")
        return about(c, rr), None

    def camera(self) -> np.ndarray | None:
        keys = sorted([s for s in self.anim.spuren if s.art == "ansicht"], key=lambda s: s.werte["zeit"])
        if not keys:
            return None
        for a, b in zip(keys, keys[1:]):
            if abs(a.werte["zeit"] - b.werte["zeit"]) < 1e-9:
                raise self.fail(b, f"zwei Schlüsselbilder der Ansicht bei {_de(a.werte['zeit'], 2)} s "
                                   f"(Zeilen {a.line} und {b.line})")
        t = self.times
        out = np.zeros((self.n, 7))
        for i, s in enumerate(keys):
            w = s.werte
            lage, ziel = np.asarray(w["lage"]), np.asarray(w["ziel"])
            if w.get("mit"):
                m = self.part_transform(w["mit"])
                lage_t, ziel_t = apply_point(m, lage), apply_point(m, ziel)
            else:
                lage_t, ziel_t = np.repeat(lage[None], self.n, 0), np.repeat(ziel[None], self.n, 0)
            fov = np.full(self.n, w["bildwinkel"] or 0.0)
            key = np.concatenate([lage_t, ziel_t, fov[:, None]], axis=1)
            if i == 0:
                out[:] = key
                prev = key
                prev_t = w["zeit"]
                continue
            seg = t > prev_t
            u = kurve((t[seg] - prev_t) / (w["zeit"] - prev_t), w["kurve"])[:, None]
            blend = prev[seg] + (key[seg] - prev[seg]) * u
            # Bildwinkel nur mischen, wenn beide ihn angeben
            both = (prev[seg, 6] > 0) & (key[seg, 6] > 0)
            blend[:, 6] = np.where(both, blend[:, 6], np.where(key[seg, 6] > 0, key[seg, 6], prev[seg, 6]))
            out[seg] = blend
            prev, prev_t = key, w["zeit"]
        return out

    def part_transform(self, name: str) -> np.ndarray:
        parts = self.resolve(name, None)
        o = self.owner(parts[0])
        return self.transform(o.key) if o is not None else eye(self.n)

    def visibility(self) -> list[dict[str, Any]]:
        events: dict[str, list[tuple[float, bool]]] = {}
        for s in self.anim.spuren:
            if s.art != "sichtbar":
                continue
            for p in self.resolve(s.ziel, s):
                events.setdefault(p, []).append((s.werte["zeit"], s.werte["an"]))
        groups: dict[tuple, list[str]] = {}
        for p in self.order:
            if p in events:
                ev = tuple(sorted(events[p], key=lambda e: e[0]))
                groups.setdefault(ev, []).append(p)
        return [{"teile": parts, "zeiten": [[round(t, 6), an] for t, an in ev]} for ev, parts in groups.items()]

    def run(self) -> Auswertung:
        t0 = time.perf_counter()
        self.build()
        for key in list(self.objs):
            self.transform(key)
        teile, mats = [], []
        spins: dict[str, tuple[list[float], list[float]]] = {}
        nospin: dict[str, np.ndarray] = {}
        for p in self.order:
            o = self.owner(p)
            if o is None:
                continue
            m = self.T[o.key]
            if np.allclose(m, np.eye(4)[None], atol=1e-9):
                continue
            teile.append(p)
            mats.append(m)
            ns = self.nospin_obj.get(o.key)
            if ns is not None and np.linalg.norm(ns[2]) > 0.5:
                spins[p] = (ns[1], ns[2])
                nospin[p] = ns[0]
        matrices = np.stack(mats, axis=1) if mats else np.zeros((self.n, 0, 4, 4))
        erlaubt = [(self.resolve(s.ziel, s), self.resolve(s.werte["b"], s)) for s in self.anim.spuren
                   if s.art == "erlaube"]
        cam = self.camera()
        vis = self.visibility()
        if not teile and cam is None and not vis:
            self.warnungen.append(f"Animation {self.name!r}: nichts bewegt sich (keine Spuren oder alle ohne Wirkung)")
        return Auswertung(name=self.name, dauer=self.anim.dauer, fps=self.anim.fps, times=self.times, teile=teile,
                          matrices=matrices, kamera=cam, sichtbar=vis, warnungen=self.warnungen, spins=spins,
                          nospin=nospin, erlaubt=erlaubt, spuren=len(self.anim.spuren), line=self.anim.line,
                          eval_ms=(time.perf_counter() - t0) * 1000.0)


def _same_line(axes: list[tuple[np.ndarray, np.ndarray]]) -> bool:
    """Liegen alle Drehachsen auf einer Geraden? (freies Rollen hat Richtung 0 und zählt nie)"""
    p0, d0 = axes[0]
    if np.linalg.norm(d0) < 0.5:
        return False
    for p, d in axes[1:]:
        if np.linalg.norm(d) < 0.5 or abs(abs(float(np.dot(d, d0))) - 1.0) > 1e-6:
            return False
        off = p - p0
        if np.linalg.norm(off - np.dot(off, d0) * d0) > 1e-4:
            return False
    return True


def _de(x: float, digits: int = 1) -> str:
    s = f"{float(x):.{digits}f}".rstrip("0").rstrip(".") if digits > 0 else f"{float(x):.0f}"
    return s.replace(".", ",")


def evaluate(anim: Animation, order: list[str], bboxes: dict[str, tuple[list[float], list[float]]]) -> Auswertung:
    """Wertet eine Animation gegen die gezeigten Teile aus (``order``: Namen in Zeigereihenfolge, ``bboxes``: Name →
    (min, max) in Weltkoordinaten). Fehler mit Zeile in model.py als ``AnimationError``."""
    if round(anim.dauer * anim.fps) + 1 > MAX_FRAMES:
        raise AnimationError(f"Animation {anim.name!r}: zu viele Bilder", anim.line, anim.filename)
    return _Eval(anim, order, bboxes).run()


def evaluate_all(anims: list[Animation], order: list[str],
                 bboxes: dict[str, tuple[list[float], list[float]]]) -> list[Auswertung]:
    out = [evaluate(a, order, bboxes) for a in anims]
    if out:
        out[0].standard = True
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------------------------------------------------


def pack_matrices(m: np.ndarray) -> bytes:
    """(N, P, 4, 4) → float32 LE, je Matrix die oberen drei Zeilen spaltenweise (12 Werte)."""
    if m.size == 0:
        return b""
    vals = m[:, :, :3, :].transpose(0, 1, 3, 2).reshape(m.shape[0], m.shape[1], 12)
    return np.ascontiguousarray(vals, dtype="<f4").tobytes()


def unpack_matrices(data: bytes, frames: int, parts: int) -> np.ndarray:
    """Gegenstück zu ``pack_matrices`` → (N, P, 4, 4) float64."""
    n = frames * parts * 12
    vals = np.frombuffer(data, dtype="<f4", count=n).astype(float).reshape(frames, parts, 4, 3)
    out = np.zeros((frames, parts, 4, 4))
    out[:, :, :3, :] = vals.transpose(0, 1, 3, 2)
    out[:, :, 3, 3] = 1.0
    return out


def def_header(a: Auswertung, run: int) -> dict[str, Any]:
    """Kopf von ANIM_DEF (ohne type/seq)."""
    return {"run": run, "name": a.name, "dauer": a.dauer, "fps": a.fps, "bilder": a.frames, "teile": list(a.teile),
            "kamera": a.kamera is not None, "sichtbar": a.sichtbar, "standard": a.standard,
            "warnungen": list(a.warnungen), "spuren": a.spuren}


def def_payload(a: Auswertung) -> bytes:
    out = pack_matrices(a.matrices)
    if a.kamera is not None:
        out += np.ascontiguousarray(a.kamera, dtype="<f4").tobytes()
    return out


def pack_anim_def(a: Auswertung, run: int) -> tuple[dict[str, Any], bytes]:
    return {"type": "ANIM_DEF", **def_header(a, run)}, def_payload(a)


def unpack_anim_def(header: dict[str, Any], payload: bytes) -> dict[str, Any]:
    """ANIM_DEF lesen (für Tests und die Laufzeit): {"matrices": (N, P, 4, 4), "kamera": (N, 7) | None, …Kopf}."""
    n, p = int(header["bilder"]), len(header["teile"])
    need = n * p * 12 * 4 + (n * 7 * 4 if header.get("kamera") else 0)
    if len(payload) < need:
        raise ValueError(f"ANIM_DEF: Nutzlast hat {len(payload)} Byte, erwartet {need}")
    out = dict(header)
    out["matrices"] = unpack_matrices(payload[: n * p * 48], n, p)
    out["kamera"] = (np.frombuffer(payload, dtype="<f4", count=n * 7, offset=n * p * 48).astype(float).reshape(n, 7)
                     if header.get("kamera") else None)
    return out


def worker_message(a: Auswertung, run: int) -> tuple[dict[str, Any], bytes]:
    """Nachricht ``ANIM`` vom Rechenprozess an die Laufzeit: ANIM_DEF plus die Angaben für die Kollisionsprüfung."""
    head, app_payload = pack_anim_def(a, run)
    head.pop("type")
    nospin_names = [p for p in a.teile if p in a.nospin]
    extra = pack_matrices(np.stack([a.nospin[p] for p in nospin_names], axis=1)) if nospin_names else b""
    msg = {"type": "ANIM", "run": run, "def": head, "app_len": len(app_payload),
           "spins": {p: [list(a.spins[p][0]), list(a.spins[p][1])] for p in nospin_names},
           "nospin": nospin_names, "erlaubt": [[list(x), list(y)] for x, y in a.erlaubt],
           "eval_ms": round(a.eval_ms, 2), "line": a.line}
    return msg, app_payload + extra

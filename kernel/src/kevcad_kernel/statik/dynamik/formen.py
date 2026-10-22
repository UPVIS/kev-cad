"""Kollisionsformen für S2: Kugel, Drehteil, konvexe Hülle oder CoACD-Zerlegung je Teil.

- **Kugel**: alle Punkte der Hülle im selben Abstand von der Mitte (Bowlingball) → Kugel-Grundform von MuJoCo, exakt und
  rollt glatt.
- **Drehteil**: Teile mit Drehachse (frei laufendes Drehgelenk, Rad der Animation), deren Umriss um die Achse
  rotationssymmetrisch ist (Laufrolle mit Einschnürung, Rad) → Stapel aus Kegelstümpfen entlang der Achse. Jeder Stumpf
  ist konvex, die Einschnürung bleibt erhalten (die konvexe Hülle wäre an der Einschnürung 6 mm zu dick).
- **Hülle**: konvexe Hülle des Netzes. Gegen den Boden ist sie exakt (der tiefste Punkt der Hülle ist der tiefste Punkt
  des Teils), gegen andere Körper reicht sie, solange nichts in eine Mulde des Teils ragt.
- **CoACD** (MIT, Wei et al. 2022): konvexe Zerlegung für Teile, in deren Hülle Punkte eines anderen Körpers liegen,
  obwohl sie das Teil selbst nicht berühren (Mulde, Schale, Gabel). Zwischengespeichert je Formschlüssel (Form ohne
  Lage) und Einstellung unter ``~/Library/Caches/de.upvis.kevcad/dynamik/coacd`` (``KEVCAD_DYNAMIK_CACHE``).

Alle Funktionen sind reine numpy/scipy-Rechnungen (CoACD erst beim Aufruf geladen); Einheiten mm.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

KUGEL_TOL = 0.006  # Kugel: Abstand der Hüllpunkte zur Mitte schwankt höchstens um 0,6 % des Radius
DREH_TOL = 0.025  # Drehteil: größter Radius je Scheibe schwankt über den Umfang höchstens um 2,5 %
DREH_SEGMENTE = 48  # Punkte je Kreis eines Kegelstumpfs
DREH_PROFIL_TOL = 0.05  # mm: Profil vereinfachen (Douglas-Peucker)
HUELLE_MAX = 192  # Punkte je Hülle (mehr kostet in GJK Zeit, ohne genauer zu werden)
COACD_SCHWELLE = 0.03  # Konkavität relativ zur Größe des Teils
COACD_MAX_TEILE = 24


def cache_ordner() -> Path:
    p = os.environ.get("KEVCAD_DYNAMIK_CACHE")
    return Path(p) if p else Path.home() / "Library" / "Caches" / "de.upvis.kevcad" / "dynamik"


# ---------------------------------------------------------------------------------------------------------------------
# Hülle


def huelle(punkte: np.ndarray, max_punkte: int = HUELLE_MAX) -> tuple[np.ndarray, np.ndarray]:
    """(Punkte der konvexen Hülle, Ebenen n·x + d ≤ 0 innen). Mehr als ``max_punkte``: die am weitesten verteilten
    (Farthest Point Sampling auf den Hüllpunkten), die Ebenen bleiben die der vollen Hülle."""
    from scipy.spatial import ConvexHull, QhullError

    P = np.unique(np.round(np.asarray(punkte, dtype=float).reshape(-1, 3), 4), axis=0)
    if len(P) < 4:
        return P, np.zeros((0, 4))
    try:
        h = ConvexHull(P)
    except (QhullError, ValueError):
        try:
            h = ConvexHull(P, qhull_options="QJ")
        except (QhullError, ValueError):
            return P, np.zeros((0, 4))
    v = P[h.vertices]
    if len(v) > max_punkte:
        v = fps(v, max_punkte)
    return v, h.equations


def fps(P: np.ndarray, n: int) -> np.ndarray:
    """Farthest Point Sampling: n gut verteilte Punkte aus P."""
    idx = [int(np.argmax(np.linalg.norm(P - P.mean(axis=0), axis=1)))]
    d = np.linalg.norm(P - P[idx[0]], axis=1)
    for _ in range(n - 1):
        i = int(np.argmax(d))
        idx.append(i)
        d = np.minimum(d, np.linalg.norm(P - P[i], axis=1))
    return P[idx]


def abstand_zur_huelle(ebenen: np.ndarray, punkte: np.ndarray) -> np.ndarray:
    """Vorzeichenbehafteter Abstand (mm) der Punkte zur Hülle: negativ = innen (Näherung über die Ebenen)."""
    if len(ebenen) == 0 or len(punkte) == 0:
        return np.full(len(punkte), np.inf)
    return np.max(punkte @ ebenen[:, :3].T + ebenen[:, 3], axis=1)


# ---------------------------------------------------------------------------------------------------------------------
# Kugel


def kugel(punkte_huelle: np.ndarray) -> tuple[np.ndarray, float] | None:
    """(Mitte, Radius), wenn die Hüllpunkte auf einer Kugel liegen (Mitte = Mitte des Hüllquaders)."""
    P = np.asarray(punkte_huelle, dtype=float)
    if len(P) < 12:
        return None
    lo, hi = P.min(axis=0), P.max(axis=0)
    ext = hi - lo
    if ext.max() < 1e-6 or (ext.max() - ext.min()) > KUGEL_TOL * ext.max():
        return None
    c = (lo + hi) / 2
    d = np.linalg.norm(P - c, axis=1)
    r = float(np.median(d))
    if r <= 0 or float(np.max(np.abs(d - r))) > KUGEL_TOL * r:
        return None
    return c, r


# ---------------------------------------------------------------------------------------------------------------------
# Drehteil


def _basis(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    return u, np.cross(d, u)


def _dp(t: np.ndarray, r: np.ndarray, tol: float) -> list[int]:
    """Douglas-Peucker auf dem Profil (t, r): Indizes der Stützstellen."""
    keep = [0, len(t) - 1]
    stack = [(0, len(t) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        tt, rr = t[i + 1:j], r[i + 1:j]
        if t[j] - t[i] < 1e-9:
            dev = np.abs(rr - r[i])
        else:
            rl = r[i] + (r[j] - r[i]) * (tt - t[i]) / (t[j] - t[i])
            dev = np.abs(rr - rl)
        k = int(np.argmax(dev))
        if dev[k] > tol:
            m = i + 1 + k
            keep.append(m)
            stack += [(i, m), (m, j)]
    return sorted(set(keep))


def drehprofil(punkte: np.ndarray, p: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Äußeres Profil (t, r) eines rotationssymmetrischen Teils um die Achse (p, d), oder None, wenn das Teil nicht
    rotationssymmetrisch ist. t entlang d ab p, r = größter Abstand zur Achse an dieser Stelle."""
    P = np.asarray(punkte, dtype=float)
    d = np.asarray(d, dtype=float) / np.linalg.norm(d)
    rel = P - np.asarray(p, dtype=float)
    t = rel @ d
    q = rel - np.outer(t, d)
    r = np.linalg.norm(q, axis=1)
    u, v = _basis(d)
    phi = np.arctan2(q @ v, q @ u)
    laenge = float(t.max() - t.min())
    rmax = float(r.max())
    if rmax < 1e-6 or laenge < 1e-6:
        return None
    # Symmetrie: je Scheibe (Breite 2 % der Länge) größter Radius in 8 Sektoren gleich
    nb = 40
    kante = np.linspace(t.min(), t.max() + 1e-9, nb + 1)
    bi = np.clip(np.searchsorted(kante, t, side="right") - 1, 0, nb - 1)
    si = ((phi + np.pi) / (2 * np.pi) * 8).astype(int) % 8
    grid = np.full((nb, 8), -1.0)
    np.maximum.at(grid, (bi, si), r)
    voll = np.all(grid > 0, axis=1)
    if voll.sum() < 2:  # mindestens zwei Ringe mit Punkten rundum (ein glatter Zylinder hat nur die beiden Kanten)
        return None
    g = grid[voll]
    if float(np.max((g.max(axis=1) - g.min(axis=1)) / rmax)) > DREH_TOL:
        return None
    # Profil an den Ringen der Vernetzung: eindeutige t (auf 0,02 mm), je t der größte Radius
    tr = np.round(t / 0.02) * 0.02
    ut, inv = np.unique(tr, return_inverse=True)
    ru = np.zeros(len(ut))
    np.maximum.at(ru, inv, r)
    # obere Hüllkurve (Bohrungen und Fasen innen fallen weg): r(t) monoton zwischen Nachbarn glätten
    idx = _dp(ut, ru, DREH_PROFIL_TOL)
    return ut[idx], ru[idx]


def drehteil_stuecke(profil: tuple[np.ndarray, np.ndarray], p: np.ndarray, d: np.ndarray,
                     segmente: int = DREH_SEGMENTE) -> list[np.ndarray]:
    """Kegelstümpfe zwischen den Stützstellen des Profils (je Stumpf zwei Kreise mit ``segmente`` Punkten, Welt)."""
    t, r = profil
    d = np.asarray(d, dtype=float) / np.linalg.norm(d)
    u, v = _basis(d)
    w = np.linspace(0, 2 * np.pi, segmente, endpoint=False)
    ring = np.outer(np.cos(w), u) + np.outer(np.sin(w), v)
    out = []
    for i in range(len(t) - 1):
        if t[i + 1] - t[i] < 0.05:
            continue
        a = np.asarray(p) + d * t[i] + ring * max(r[i], 0.05)
        b = np.asarray(p) + d * t[i + 1] + ring * max(r[i + 1], 0.05)
        out.append(np.vstack([a, b]))
    return out


def zylinder_aus_profil(profil: tuple[np.ndarray, np.ndarray]) -> tuple[float, float, float] | None:
    """(t_mitte, Radius, halbe Länge), wenn das Profil im Bereich des größten Radius flach ist (Lauffläche eines Rads):
    dann rollt eine Zylinder-Grundform glatt auf dem Boden. Sonst None."""
    t, r = profil
    rmax = float(r.max())
    flach = r >= rmax - max(0.2, 0.004 * rmax)
    # längster zusammenhängender flacher Abschnitt (benachbarte Stützstellen, beide am größten Radius)
    best, lauf = (0.0, 0.0), None
    for i in range(len(t) - 1):
        if flach[i] and flach[i + 1]:
            lauf = (lauf[0] if lauf else float(t[i]), float(t[i + 1]))
            if lauf[1] - lauf[0] > best[1] - best[0]:
                best = lauf
        else:
            lauf = None
    t0, t1 = best
    if t1 - t0 < 0.1 * rmax:
        return None
    return (t0 + t1) / 2, rmax, (t1 - t0) / 2


# ---------------------------------------------------------------------------------------------------------------------
# CoACD mit Zwischenspeicher


def coacd_schluessel(form: str, schwelle: float, max_teile: int) -> str:
    h = hashlib.sha1(f"{form}|{schwelle:.4f}|{max_teile}|v1".encode()).hexdigest()[:16]
    return f"{form[:16]}-{h}"


def coacd_im_cache(form: str, schwelle: float = COACD_SCHWELLE, max_teile: int = COACD_MAX_TEILE) -> bool:
    return (cache_ordner() / "coacd" / f"{coacd_schluessel(form, schwelle, max_teile)}.npz").exists()


def coacd_zerlegen(pos_lokal: np.ndarray, tri: np.ndarray, form: str, schwelle: float = COACD_SCHWELLE,
                   max_teile: int = COACD_MAX_TEILE) -> tuple[list[np.ndarray], dict[str, Any]]:
    """Konvexe Stücke (Punkte im Formsystem, mm) eines Netzes; aus dem Zwischenspeicher, sonst mit CoACD gerechnet und
    abgelegt. Liefert (Stücke, Angaben: aus_cache, ms, stuecke)."""
    ordner = cache_ordner() / "coacd"
    datei = ordner / f"{coacd_schluessel(form, schwelle, max_teile)}.npz"
    t0 = time.perf_counter()
    if datei.exists():
        try:
            with np.load(datei) as z:
                n = int(z["n"])
                stuecke = [z[f"s{i}"] for i in range(n)]
            return stuecke, {"aus_cache": True, "ms": round((time.perf_counter() - t0) * 1000, 1), "stuecke": n}
        except Exception:  # noqa: BLE001 - kaputte Datei: neu rechnen
            pass
    import coacd

    coacd.set_log_level("error")
    mesh = coacd.Mesh(np.asarray(pos_lokal, dtype=np.float64), np.asarray(tri, dtype=np.int64))
    teile = coacd.run_coacd(mesh, threshold=float(schwelle), max_convex_hull=int(max_teile), preprocess_mode="auto",
                            resolution=2000, mcts_iterations=60, mcts_max_depth=2, mcts_nodes=16, seed=1,
                            decimate=True, max_ch_vertex=96)
    stuecke = [np.asarray(v, dtype=float) for v, _f in teile if len(v) >= 4]
    ordner.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, n=len(stuecke), **{f"s{i}": s for i, s in enumerate(stuecke)})
    os.replace(tmp, datei)
    return stuecke, {"aus_cache": False, "ms": round((time.perf_counter() - t0) * 1000, 1), "stuecke": len(stuecke)}

"""Netz säubern und schreiben, Silhouetten-Masken, Flächenproben.

- ``groesste_komponente``: zusammenhängende Teile über gemeinsame Ecken, das größte (nach Fläche) bleibt.
- ``schreibe_obj``/``schreibe_ply``: OBJ wie kevcad-capture (``netz_mm.obj``, mm, Z oben), PLY mit Farben.
- ``silhouette``: Netz mit bekannter Kamera als weiche Maske (Unterpixel über 4-fache Auflösung).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def flaechen(P: np.ndarray, T: np.ndarray) -> np.ndarray:
    if not len(T):
        return np.zeros(0)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def normalen(P: np.ndarray, T: np.ndarray) -> np.ndarray:
    n = np.zeros_like(P)
    if len(T):
        a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        fn = np.cross(b - a, c - a)
        for k in range(3):
            np.add.at(n, T[:, k], fn)
    laenge = np.linalg.norm(n, axis=1, keepdims=True)
    return np.where(laenge > 1e-12, n / np.maximum(laenge, 1e-12), np.array([0.0, 0.0, 1.0]))


def komponenten(n_punkte: int, T: np.ndarray) -> np.ndarray:
    """Komponente je Dreieck (über gemeinsame Ecken)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    if not len(T):
        return np.zeros(0, np.int64)
    zeilen = np.concatenate([T[:, 0], T[:, 1], T[:, 2]])
    spalten = np.concatenate([T[:, 1], T[:, 2], T[:, 0]])
    g = coo_matrix((np.ones(len(zeilen), np.int8), (zeilen, spalten)), shape=(n_punkte, n_punkte))
    _, lab = connected_components(g, directed=False)
    return lab[T[:, 0]]


def aufraeumen(netz: dict[str, np.ndarray], nur_groesste: bool = True) -> tuple[dict[str, np.ndarray], dict]:
    """Größte Komponente (nach Fläche), ungenutzte Ecken weg. Rückgabe (Netz, Kennzahlen)."""
    P, T = netz["positions"], netz["triangles"]
    farbe = netz.get("colors")
    info = {"dreiecke_gesamt": int(len(T)), "komponenten": 0}
    if not len(T):
        info["dreiecke"] = 0
        return netz, info
    lab = komponenten(len(P), T)
    fl = flaechen(P, T)
    summe = np.bincount(lab, weights=fl)
    info["komponenten"] = int((summe > 0).sum())
    if nur_groesste:
        T = T[lab == int(np.argmax(summe))]
    benutzt = np.unique(T)
    neu = np.full(len(P), -1, np.int64)
    neu[benutzt] = np.arange(len(benutzt))
    out = {"positions": P[benutzt], "triangles": neu[T]}
    if farbe is not None and len(farbe) == len(P):
        out["colors"] = farbe[benutzt]
    info["dreiecke"] = int(len(T))
    info["flaeche_mm2"] = round(float(flaechen(out["positions"], out["triangles"]).sum()), 1)
    return out, info


def schreibe_obj(pfad: str | Path, P: np.ndarray, T: np.ndarray, kopf: str = "") -> None:
    pfad = Path(pfad)
    with open(pfad, "w", encoding="utf-8") as f:
        if kopf:
            for z in kopf.splitlines():
                f.write(f"# {z}\n")
        np.savetxt(f, P, fmt="v %.4f %.4f %.4f")
        np.savetxt(f, T + 1, fmt="f %d %d %d")


def schreibe_ply(pfad: str | Path, P: np.ndarray, T: np.ndarray | None = None, farbe: np.ndarray | None = None,
                 normale: np.ndarray | None = None) -> None:
    """Binäres PLY (little endian): Punkte mit optionalen Normalen und Farben, optional Dreiecke."""
    P = np.asarray(P, np.float32)
    felder = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if normale is not None:
        felder += [("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4")]
    if farbe is not None:
        felder += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    v = np.empty(len(P), dtype=felder)
    v["x"], v["y"], v["z"] = P[:, 0], P[:, 1], P[:, 2]
    if normale is not None:
        v["nx"], v["ny"], v["nz"] = normale[:, 0], normale[:, 1], normale[:, 2]
    if farbe is not None:
        farbe = np.asarray(farbe, np.uint8)
        v["red"], v["green"], v["blue"] = farbe[:, 0], farbe[:, 1], farbe[:, 2]
    kopf = ["ply", "format binary_little_endian 1.0", "comment Kev Scan, mm, Z oben", f"element vertex {len(P)}"]
    typ = {"<f4": "float", "u1": "uchar"}
    kopf += [f"property {typ[t]} {n}" for n, t in felder]
    if T is not None and len(T):
        kopf += [f"element face {len(T)}", "property list uchar int vertex_indices"]
    kopf.append("end_header")
    with open(pfad, "wb") as f:
        f.write(("\n".join(kopf) + "\n").encode("ascii"))
        f.write(v.tobytes())
        if T is not None and len(T):
            fl = np.empty(len(T), dtype=[("n", "u1"), ("i", "<i4", (3,))])
            fl["n"] = 3
            fl["i"] = np.asarray(T, np.int32)
            f.write(fl.tobytes())


def lies_obj(pfad: str | Path) -> tuple[np.ndarray, np.ndarray]:
    P, T = [], []
    with open(pfad, encoding="utf-8") as f:
        for z in f:
            if z.startswith("v "):
                P.append([float(x) for x in z.split()[1:4]])
            elif z.startswith("f "):
                ids = [int(x.split("/")[0]) - 1 for x in z.split()[1:]]
                for k in range(1, len(ids) - 1):
                    T.append([ids[0], ids[k], ids[k + 1]])
    return np.asarray(P, float).reshape(-1, 3), np.asarray(T, np.int64).reshape(-1, 3)


def silhouette(P: np.ndarray, T: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray, w: int, h: int,
               fein: int = 2) -> np.ndarray:
    """Weiche Maske (float32 0…1, h × w) des Netzes durch die Kamera (K für w × h, Pixel stetig wie fotomess).
    Vereinigung aller Dreiecke vor der Kamera, in ``fein``-facher Auflösung gezeichnet."""
    Xc = np.asarray(P, float) @ np.asarray(R, float).T + np.asarray(t, float)
    z = Xc[:, 2]
    vorne = z > 1.0
    uv = np.zeros((len(P), 2))
    uv[vorne, 0] = K[0, 0] * Xc[vorne, 0] / z[vorne] + K[0, 2]
    uv[vorne, 1] = K[1, 1] * Xc[vorne, 1] / z[vorne] + K[1, 2]
    ok = vorne[T].all(1)
    drin = ((uv[:, 0] > -w) & (uv[:, 0] < 2 * w) & (uv[:, 1] > -h) & (uv[:, 1] < 2 * h))[T].all(1)
    tri = uv[T[ok & drin]] * fein - 0.5  # stetige Pixel (i deckt [i, i+1]) -> Pixelmitten von OpenCV
    gross = np.zeros((h * fein, w * fein), np.uint8)
    if len(tri):
        pts = np.ascontiguousarray(np.rint(tri * 16).astype(np.int32).reshape(-1, 3, 1, 2))  # 4 Bit Unterpixel
        cv2.fillPoly(gross, pts, 255, lineType=cv2.LINE_8, shift=4)
    return cv2.resize(gross.astype(np.float32) / 255.0, (w, h), interpolation=cv2.INTER_AREA)


def flaechenproben(P: np.ndarray, T: np.ndarray, anzahl: int, rng: np.random.Generator | None = None
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Gleichmäßig verteilte Punkte auf dem Netz mit den Normalen ihrer Dreiecke."""
    rng = rng or np.random.default_rng(3)
    fl = flaechen(P, T)
    ok = fl > 1e-12
    if not ok.any():
        return np.zeros((0, 3)), np.zeros((0, 3))
    Tq = T[ok]
    wahl = rng.choice(len(Tq), size=anzahl, p=fl[ok] / fl[ok].sum())
    a, b, c = P[Tq[wahl, 0]], P[Tq[wahl, 1]], P[Tq[wahl, 2]]
    u, v = rng.random(anzahl), rng.random(anzahl)
    aussen = u + v > 1
    u[aussen], v[aussen] = 1 - u[aussen], 1 - v[aussen]
    X = a + u[:, None] * (b - a) + v[:, None] * (c - a)
    n = np.cross(b - a, c - a)
    return X, n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def grundriss(P: np.ndarray, z_von: float | None = None) -> dict[str, float]:
    """Kleinstes umschließendes Rechteck der Punkte (über ``z_von``) im Grundriss: Mitte, Länge ≥ Breite, Winkel der
    langen Seite gegen X (Grad)."""
    Q = P if z_von is None else P[P[:, 2] >= z_von]
    if len(Q) < 3:
        Q = P
    (cx, cy), (a, b), winkel = cv2.minAreaRect(Q[:, :2].astype(np.float32))
    if a < b:
        a, b = b, a
        winkel += 90.0
    winkel = (winkel + 90.0) % 180.0 - 90.0
    return {"mitte_x": float(cx), "mitte_y": float(cy), "laenge": float(a), "breite": float(b),
            "winkel_grad": float(winkel)}

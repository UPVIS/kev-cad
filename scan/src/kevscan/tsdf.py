"""Schlanke TSDF (abgeschnittene vorzeichenbehaftete Abstandsfunktion) mit numpy, Netz über marching cubes
(scikit-image). Open3D wäre ein schwerer Brocken (Dash, Plotly, Pandas …) für eine Funktion, die hier 100 Zeilen hat.

Welt in mm (Kev CAD, z oben). Je Bild: Voxelmitten in die Kamera, Tiefe am Bildpunkt (bilinear, nur wenn die vier
Nachbarn gemessen sind), Abstand d = D − z, abgeschnitten auf ±trunc, gewichtet mit der Konfidenz gemittelt. Voxel
weit hinter der Fläche (d < −trunc) bleiben unberührt, so wachsen keine Rückseiten zu.
"""

from __future__ import annotations

import numpy as np

MAX_VOXEL = 24_000_000


class TSDF:
    def __init__(self, lo, hi, voxel_mm: float, trunc_mm: float | None = None, farbe: bool = True) -> None:
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        ausdehnung = hi - lo
        v = float(voxel_mm)
        n = np.ceil(ausdehnung / v).astype(int)
        while int(np.prod(n)) > MAX_VOXEL:  # Speichergrenze: Voxel vergrößern
            v *= 1.1
            n = np.ceil(ausdehnung / v).astype(int)
        self.voxel = v
        self.trunc = float(trunc_mm or max(4.0 * v, 8.0))
        self.lo = lo
        self.n = n
        gx = lo[0] + (np.arange(n[0]) + 0.5) * v
        gy = lo[1] + (np.arange(n[1]) + 0.5) * v
        gz = lo[2] + (np.arange(n[2]) + 0.5) * v
        X, Y, Z = np.meshgrid(gx.astype(np.float32), gy.astype(np.float32), gz.astype(np.float32), indexing="ij")
        self.mitten = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1)
        self.wert = np.ones(len(self.mitten), np.float32)
        self.gewicht = np.zeros(len(self.mitten), np.float32)
        self.farbe = np.zeros((len(self.mitten), 3), np.float32) if farbe else None
        self.bilder = 0

    @property
    def form(self) -> tuple[int, int, int]:
        return tuple(int(x) for x in self.n)

    def integriere(self, tiefe_mm: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray,
                   konf: np.ndarray | None = None, farbe_rgb: np.ndarray | None = None, gewicht: float = 1.0) -> int:
        """Ein Tiefenbild (mm, K für genau diese Bildgröße, Kamera R, t: Welt -> OpenCV). Rückgabe: getroffene Voxel."""
        h, w = tiefe_mm.shape
        R = np.asarray(R, np.float32)
        Xc = self.mitten @ R.T + np.asarray(t, np.float32)
        z = Xc[:, 2]
        vorne = z > 1.0
        idx = np.flatnonzero(vorne)
        if not len(idx):
            return 0
        Xc, z = Xc[idx], z[idx]
        u = K[0, 0] * Xc[:, 0] / z + K[0, 2] - 0.5
        v = K[1, 1] * Xc[:, 1] / z + K[1, 2] - 0.5
        drin = (u >= 0) & (v >= 0) & (u < w - 1) & (v < h - 1)
        idx, u, v, z = idx[drin], u[drin], v[drin], z[drin]
        x0 = u.astype(np.int32)
        y0 = v.astype(np.int32)
        fx, fy = (u - x0).astype(np.float32), (v - y0).astype(np.float32)
        d00, d10 = tiefe_mm[y0, x0], tiefe_mm[y0, x0 + 1]
        d01, d11 = tiefe_mm[y0 + 1, x0], tiefe_mm[y0 + 1, x0 + 1]
        alle = (d00 > 0) & (d10 > 0) & (d01 > 0) & (d11 > 0)
        D = (d00 * (1 - fx) * (1 - fy) + d10 * fx * (1 - fy) + d01 * (1 - fx) * fy + d11 * fx * fy)
        # an Tiefensprüngen nicht mitteln (fliegende Punkte): Spannweite der vier Nachbarn begrenzen
        spanne = np.maximum.reduce([d00, d10, d01, d11]) - np.minimum.reduce([d00, d10, d01, d11])
        ok = alle & (spanne < np.maximum(self.trunc, 0.02 * D))
        d = D - z
        ok &= d > -self.trunc
        idx, d, x0, y0 = idx[ok], d[ok], x0[ok], y0[ok]
        if not len(idx):
            return 0
        neu = np.minimum(1.0, d / self.trunc).astype(np.float32)
        g = np.full(len(idx), float(gewicht), np.float32)
        if konf is not None:
            g *= konf[y0, x0]
        nutz = g > 0
        idx, neu, g, x0, y0 = idx[nutz], neu[nutz], g[nutz], x0[nutz], y0[nutz]
        alt_g = self.gewicht[idx]
        summe = alt_g + g
        self.wert[idx] = (self.wert[idx] * alt_g + neu * g) / summe
        if self.farbe is not None and farbe_rgb is not None:
            c = farbe_rgb[y0, x0].astype(np.float32)
            nah = np.abs(neu) < 0.5  # Farbe nur nah an der Fläche
            j = idx[nah]
            self.farbe[j] = (self.farbe[j] * alt_g[nah, None] + c[nah] * g[nah, None]) / summe[nah, None]
        self.gewicht[idx] = np.minimum(summe, 64.0)
        self.bilder += 1
        return int(len(idx))

    def netz(self, min_gewicht: float = 0.5) -> dict[str, np.ndarray]:
        """Dreiecksnetz der Nullfläche: positions (mm, Welt), triangles, colors (0…255) oder leer."""
        from skimage import measure

        vol = self.wert.reshape(self.form)
        maske = (self.gewicht >= min_gewicht).reshape(self.form)
        if not maske.any() or vol[maske].min() > 0 or vol[maske].max() < 0:
            return {"positions": np.zeros((0, 3)), "triangles": np.zeros((0, 3), np.int64),
                    "colors": np.zeros((0, 3), np.uint8)}
        verts, faces, _, _ = measure.marching_cubes(vol, level=0.0, spacing=(self.voxel,) * 3, mask=maske,
                                                    gradient_direction="ascent", allow_degenerate=False)
        P = verts + self.lo + 0.5 * self.voxel
        farben = np.zeros((len(P), 3), np.uint8)
        if self.farbe is not None and len(P):
            ijk = np.clip(np.rint(verts / self.voxel).astype(int), 0, np.array(self.form) - 1)
            flat = np.ravel_multi_index(ijk.T, self.form)
            farben = np.clip(self.farbe[flat], 0, 255).astype(np.uint8)
        return {"positions": P, "triangles": faces.astype(np.int64), "colors": farben}


def voxel_aus_box(groesse_mm, ziel_mm: float = 2.0) -> float:
    """Voxelgröße aus der Objektgröße: 2 mm bei Gegenständen bis etwa 40 cm, darüber so, dass die lange Seite rund
    200 Voxel hat (höchstens 10 mm)."""
    lang = float(max(groesse_mm))
    return float(min(10.0, max(ziel_mm, lang / 200.0)))


def trunc_fuer(voxel_mm: float, rauschen_mm: float = 3.0) -> float:
    return float(max(4.0 * voxel_mm, 3.0 * rauschen_mm, 8.0))

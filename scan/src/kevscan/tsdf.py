"""Schlanke TSDF (abgeschnittene vorzeichenbehaftete Abstandsfunktion) mit numpy, Netz über marching cubes
(scikit-image). Open3D wäre ein schwerer Brocken (Dash, Plotly, Pandas …) für eine Funktion, die hier 100 Zeilen hat.

Welt in mm (Kev CAD, z oben). Je Bild: Voxelmitten in die Kamera, Tiefe am Bildpunkt (bilinear, nur wenn die vier
Nachbarn gemessen sind), Abstand d = D − z, abgeschnitten auf ±trunc, gewichtet mit der Konfidenz gemittelt. Voxel
weit hinter der Fläche (d < −trunc) bleiben unberührt, so wachsen keine Rückseiten zu. Freier Raum weit vor der
gemessenen Fläche (d > ``frei_ab``) zählt nur mit ``frei_gewicht``: Mit 1 räumen Sichtstrahlen, die an dünnen Kanten
um ein LiDAR-Pixel danebenliegen und erst den Boden dahinter treffen, ganze Platten weg (Rollwagen, 4-mm-Platten,
23.10.2026); mit 0,1 setzt sich solcher freier Raum nur durch, wenn viele Bilder ihn sehen. Nah vor der Fläche
(trunc < d ≤ frei_ab) zählt er voll, sonst würden kompakte Teile durch Rauschen dicker.

Rechnet mit torch auf der GPU (MPS), wenn vorhanden (``geraet="auto"``), sonst mit numpy; beide Wege rechnen gleich.
Am echten Scan (7,7 Mio. Voxel) braucht numpy rund 0,9 s je Bild.
"""

from __future__ import annotations

import numpy as np

MAX_VOXEL = 24_000_000


class TSDF:
    def __init__(self, lo, hi, voxel_mm: float, trunc_mm: float | None = None, farbe: bool = True,
                 geraet: str | None = "auto", frei_gewicht: float = 1.0, frei_ab_mm: float | None = None) -> None:
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        ausdehnung = hi - lo
        v = float(voxel_mm)
        n = np.ceil(ausdehnung / v).astype(int)
        while int(np.prod(n)) > MAX_VOXEL:  # Speichergrenze: Voxel vergrößern
            v *= 1.1
            n = np.ceil(ausdehnung / v).astype(int)
        self.voxel = v
        self.trunc = float(trunc_mm or max(4.0 * v, 8.0))
        self.frei_gewicht = float(frei_gewicht)
        self.frei_ab = float(frei_ab_mm) if frei_ab_mm is not None else 2.0 * self.trunc
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
        self._torch = None
        if geraet:
            try:
                import torch

                dev = ("mps" if torch.backends.mps.is_available() else None) if geraet == "auto" else geraet
            except ImportError:
                dev = None
            if dev:
                self._torch, self._dev = torch, dev
                self._t_mitten = torch.from_numpy(self.mitten).to(dev)
                self._t_wert = torch.from_numpy(self.wert).to(dev)
                self._t_gewicht = torch.from_numpy(self.gewicht).to(dev)
                self._t_farbe = torch.from_numpy(self.farbe).to(dev) if self.farbe is not None else None
        self.geraet = self._dev if self._torch is not None else "numpy"

    @property
    def form(self) -> tuple[int, int, int]:
        return tuple(int(x) for x in self.n)

    def integriere(self, tiefe_mm: np.ndarray, K: np.ndarray, R: np.ndarray, t: np.ndarray,
                   konf: np.ndarray | None = None, farbe_rgb: np.ndarray | None = None, gewicht: float = 1.0) -> int:
        """Ein Tiefenbild (mm, K für genau diese Bildgröße, Kamera R, t: Welt -> OpenCV). Rückgabe: getroffene Voxel."""
        if self._torch is not None:
            return self._integriere_torch(tiefe_mm, K, R, t, konf, farbe_rgb, gewicht)
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
        g = np.where(d > self.frei_ab, float(gewicht) * self.frei_gewicht, float(gewicht)).astype(np.float32)
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

    def _integriere_torch(self, tiefe_mm, K, R, t, konf, farbe_rgb, gewicht) -> int:
        torch, dev = self._torch, self._dev
        f32 = torch.float32
        h, w = tiefe_mm.shape
        D = torch.from_numpy(np.ascontiguousarray(tiefe_mm, np.float32)).to(dev)
        Rt = torch.tensor(np.asarray(R, np.float32), device=dev)
        tt = torch.tensor(np.asarray(t, np.float32), device=dev)
        Xc = self._t_mitten @ Rt.T + tt
        z = Xc[:, 2]
        zs = torch.clamp(z, min=1.0)
        u = float(K[0, 0]) * Xc[:, 0] / zs + float(K[0, 2]) - 0.5
        v = float(K[1, 1]) * Xc[:, 1] / zs + float(K[1, 2]) - 0.5
        drin = (z > 1.0) & (u >= 0) & (v >= 0) & (u < w - 1) & (v < h - 1)
        idx = torch.nonzero(drin).squeeze(1)
        if idx.numel() == 0:
            return 0
        u, v, z = u[idx], v[idx], z[idx]
        x0, y0 = u.long(), v.long()
        fx, fy = u - x0.to(f32), v - y0.to(f32)
        d00, d10, d01, d11 = D[y0, x0], D[y0, x0 + 1], D[y0 + 1, x0], D[y0 + 1, x0 + 1]
        alle = (d00 > 0) & (d10 > 0) & (d01 > 0) & (d11 > 0)
        Dw = d00 * (1 - fx) * (1 - fy) + d10 * fx * (1 - fy) + d01 * (1 - fx) * fy + d11 * fx * fy
        st = torch.stack([d00, d10, d01, d11])
        spanne = st.amax(0) - st.amin(0)
        d = Dw - z
        ok = alle & (spanne < torch.clamp(0.02 * Dw, min=self.trunc)) & (d > -self.trunc)
        g = torch.where(d > self.frei_ab, float(gewicht) * self.frei_gewicht, float(gewicht)).to(f32)
        if konf is not None:
            g = g * torch.from_numpy(np.ascontiguousarray(konf, np.float32)).to(dev)[y0, x0]
        ok &= g > 0
        sel = torch.nonzero(ok).squeeze(1)
        if sel.numel() == 0:
            return 0
        idx, d, g, x0, y0 = idx[sel], d[sel], g[sel], x0[sel], y0[sel]
        neu = torch.clamp(d / self.trunc, max=1.0)
        alt_g = self._t_gewicht[idx]
        summe = alt_g + g
        self._t_wert[idx] = (self._t_wert[idx] * alt_g + neu * g) / summe
        if self._t_farbe is not None and farbe_rgb is not None:
            c = torch.from_numpy(np.ascontiguousarray(farbe_rgb, np.float32)).to(dev)[y0, x0]
            nah = torch.nonzero(neu.abs() < 0.5).squeeze(1)
            j = idx[nah]
            self._t_farbe[j] = (self._t_farbe[j] * alt_g[nah, None] + c[nah] * g[nah, None]) / summe[nah, None]
        self._t_gewicht[idx] = torch.clamp(summe, max=64.0)
        self.bilder += 1
        return int(idx.numel())

    def _zurueck(self) -> None:
        """Werte von der GPU zurück in die numpy-Felder (vor dem Netz)."""
        if self._torch is not None:
            self.wert = self._t_wert.cpu().numpy()
            self.gewicht = self._t_gewicht.cpu().numpy()
            if self._t_farbe is not None:
                self.farbe = self._t_farbe.cpu().numpy()

    def netz(self, min_gewicht: float = 0.5) -> dict[str, np.ndarray]:
        """Dreiecksnetz der Nullfläche: positions (mm, Welt), triangles, colors (0…255) oder leer."""
        from skimage import measure

        self._zurueck()

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
    """Voxelgröße aus der Objektgröße: 2 mm bei Gegenständen bis etwa 60 cm, darüber so, dass die lange Seite rund
    300 Voxel hat (höchstens 10 mm). Bis Build 491 waren es 200 Voxel; am Rollwagen (84 cm Box) wurden daraus 4 bis
    5 mm, zu grob für seine 4-mm-Platten."""
    lang = float(max(groesse_mm))
    return float(min(10.0, max(ziel_mm, lang / 300.0)))


def trunc_fuer(voxel_mm: float, rauschen_mm: float = 3.0) -> float:
    return float(max(4.0 * voxel_mm, 3.0 * rauschen_mm, 8.0))

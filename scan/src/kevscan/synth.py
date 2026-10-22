"""Synthetischer Scan nach SCAN.md für Proben ohne iPhone: Quader auf dem Boden, Fotos und Video mit bekannten
Kameras, LiDAR-Ersatz (gröber, verrauscht, Mischpixel an Kanten).

Gerendert wird mit Strahlverfolgung in numpy (Quader mit Drehung um Z, Boden als Scheibe mit Schachbrett, Licht
von schräg oben, 2 × 2 Überabtastung bei den Fotos). Die Welt von ARKit ist gegen Kev CAD gedreht und verschoben
(Boden bei y = −0,85 m), damit die Auswertung Boden und Lage selbst finden muss. ``wahrheit.json`` (nicht Teil des
Formats) hält Quader, Kameras und Rauschen fest.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from kevscan import geometrie as geo

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


class Szene:
    def __init__(self, groesse=(200.0, 100.0, 50.0), mitte=(35.0, -15.0), drehung_grad=20.0, boden_r=1200.0):
        self.L, self.B, self.H = (float(x) for x in groesse)
        self.mitte = np.array([mitte[0], mitte[1], 0.0])
        self.Rb = geo.rz(math.radians(drehung_grad))
        self.boden_r = boden_r
        self.licht = np.array([0.4, -0.3, 0.85]) / np.linalg.norm([0.4, -0.3, 0.85])

    def strahlen(self, C: np.ndarray, D: np.ndarray):
        """C (3,), D (n, 3) Richtungen mit Kamera-z = 1 -> t (Tiefe), Normale (n, 3), Treffer-Art (0 nichts, 1 Boden,
        2 Quader), lokale Koordinaten."""
        n = len(D)
        t = np.full(n, np.inf)
        art = np.zeros(n, np.int8)
        nrm = np.zeros((n, 3))
        # Boden
        dz = D[:, 2]
        tb = np.where(dz < -1e-9, -C[2] / np.where(dz < -1e-9, dz, -1), np.inf)
        p = C + tb[:, None] * D
        ok = np.isfinite(tb) & (tb > 0) & (np.hypot(p[:, 0], p[:, 1]) < self.boden_r)
        t[ok] = tb[ok]
        art[ok] = 1
        nrm[ok] = [0, 0, 1]
        # Quader (lokal: x in ±L/2, y in ±B/2, z in [0, H])
        pl = (C - self.mitte) @ self.Rb
        dl = D @ self.Rb
        lo = np.array([-self.L / 2, -self.B / 2, 0.0])
        hi = np.array([self.L / 2, self.B / 2, self.H])
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / np.where(np.abs(dl) < 1e-12, 1e-12, dl)
            t1 = (lo - pl) * inv
            t2 = (hi - pl) * inv
        tmin = np.minimum(t1, t2)
        tmax = np.maximum(t1, t2)
        t_ein = tmin.max(1)
        t_aus = tmax.min(1)
        hit = (t_aus >= t_ein) & (t_ein > 0) & (t_ein < t)
        achse = tmin.argmax(1)
        t[hit] = t_ein[hit]
        art[hit] = 2
        nl = np.zeros((n, 3))
        nl[np.arange(n), achse] = -np.sign(dl[np.arange(n), achse])
        nrm[hit] = nl[hit] @ self.Rb.T
        lokal = pl + t_ein[:, None] * dl
        return t, nrm, art, lokal, achse

    def farbe(self, C, D, t, nrm, art, lokal, achse) -> np.ndarray:
        n = len(D)
        rgb = np.zeros((n, 3))
        rgb[:] = [38, 40, 46]
        X = C + np.where(np.isfinite(t), t, 0)[:, None] * D
        licht = 0.35 + 0.65 * np.clip(nrm @ self.licht, 0, None)
        b = art == 1
        if b.any():
            xb, yb = X[b, 0], X[b, 1]
            karo = ((np.floor(xb / 60) + np.floor(yb / 60)) % 2).astype(float)
            maser = 0.06 * np.sin(xb * 0.11 + 0.7 * np.sin(yb * 0.031)) + 0.03 * np.sin(yb * 0.23)
            grund = np.where(karo[:, None] > 0, [176, 168, 156], [150, 142, 132])
            rgb[b] = grund * (1 + maser)[:, None] * licht[b, None]
        q = art == 2
        if q.any():
            ax = achse[q]
            lq = lokal[q]
            sign_n = (nrm[q] @ self.Rb)
            oben = (ax == 2) & (sign_n[:, 2] > 0)
            grund = np.where((ax == 0)[:, None], [92, 132, 172], np.where((ax == 1)[:, None], [152, 156, 166],
                                                                           [206, 176, 122]))
            grund = np.where(oben[:, None], [206, 176, 122], grund)
            muster = 1 + 0.05 * np.sin(lq[:, 0] * 0.35 + lq[:, 2] * 0.21) * np.sin(lq[:, 1] * 0.29 + lq[:, 2] * 0.17)
            rgb[q] = grund * muster[:, None] * licht[q, None]
        return np.clip(rgb, 0, 255)


def blick(C, ziel) -> np.ndarray:
    """OpenCV-Drehung (Welt -> Kamera) für eine Kamera in C, die auf ``ziel`` blickt (oben = +Z)."""
    f = np.asarray(ziel, float) - np.asarray(C, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 0.0, 1.0])
    r /= np.linalg.norm(r)
    d = np.cross(f, r)
    return np.vstack([r, d, f])


def rendere(szene: Szene, K: np.ndarray, R: np.ndarray, t: np.ndarray, w: int, h: int, fein: int = 1,
            zeilen: int = 240) -> tuple[np.ndarray, np.ndarray]:
    """Farbbild (h × w × 3, uint8, BGR) und z-Tiefe (h × w, mm, 0 = nichts) mit ``fein`` × ``fein`` Überabtastung."""
    C = geo.zentrum(R, t)
    bild = np.zeros((h, w, 3), np.float32)
    tiefe = np.zeros((h, w), np.float32)
    for y0 in range(0, h, zeilen):
        y1 = min(h, y0 + zeilen)
        acc = np.zeros((y1 - y0, w, 3))
        for sy in range(fein):
            for sx in range(fein):
                u = np.arange(w) + (sx + 0.5) / fein
                v = np.arange(y0, y1) + (sy + 0.5) / fein
                U, V = np.meshgrid(u, v)
                dc = np.stack([(U - K[0, 2]) / K[0, 0], (V - K[1, 2]) / K[1, 1], np.ones_like(U)], -1).reshape(-1, 3)
                D = dc @ R
                tt, nrm, art, lokal, achse = szene.strahlen(C, D)
                acc += szene.farbe(C, D, tt, nrm, art, lokal, achse).reshape(y1 - y0, w, 3)
                if sx == fein // 2 and sy == fein // 2:
                    tiefe[y0:y1] = np.where(np.isfinite(tt), tt, 0).reshape(y1 - y0, w)
        bild[y0:y1] = acc / (fein * fein)
    return cv2.cvtColor(bild.astype(np.uint8), cv2.COLOR_RGB2BGR), tiefe


def lidar(szene: Szene, K: np.ndarray, R: np.ndarray, t: np.ndarray, w: int, h: int, rng: np.random.Generator,
          lw: int = 256, lh: int = 192, rauschen_mm: float = 2.0, rauschen_rel: float = 0.004
          ) -> tuple[np.ndarray, np.ndarray]:
    """LiDAR-Ersatz: Tiefe in 2 × 2 Teilen gerendert und gemittelt (Mischpixel an Kanten), Rauschen, mm als uint16;
    Konfidenz 2 (glatt), 1 (Kante), 0 (nichts getroffen)."""
    K2 = K.copy()
    K2[0] *= 2 * lw / w
    K2[1] *= 2 * lh / h
    C = geo.zentrum(R, t)
    u = np.arange(2 * lw) + 0.5
    v = np.arange(2 * lh) + 0.5
    U, V = np.meshgrid(u, v)
    dc = np.stack([(U - K2[0, 2]) / K2[0, 0], (V - K2[1, 2]) / K2[1, 1], np.ones_like(U)], -1).reshape(-1, 3)
    tt, *_ = szene.strahlen(C, dc @ R)
    z = np.where(np.isfinite(tt), tt, 0).reshape(2 * lh, 2 * lw)
    teile = np.stack([z[0::2, 0::2], z[1::2, 0::2], z[0::2, 1::2], z[1::2, 1::2]])
    leer = (teile <= 0).any(0)
    mittel = teile.mean(0)
    spanne = teile.max(0) - teile.min(0)
    konf = np.where(leer, 0, np.where(spanne > 0.01 * np.maximum(mittel, 1), 1, 2)).astype(np.uint8)
    # langwelliger Versatz je Bild (± 1,5 mm) und Rauschen
    gy, gx = np.mgrid[0:lh, 0:lw]
    feld = 1.5 * np.sin(gx / lw * math.pi * rng.uniform(0.5, 1.5) + rng.uniform(0, 6)) * \
        np.cos(gy / lh * math.pi * rng.uniform(0.5, 1.5))
    d = mittel + feld + rng.normal(0, 1, mittel.shape) * (rauschen_mm + rauschen_rel * mittel)
    d = np.where(leer | (mittel > 5000), 0, d)
    konf = np.where(d <= 0, 0, konf)
    return np.clip(np.rint(d), 0, 65535).astype(np.uint16), konf


def erzeuge(ziel: str | Path, *, fotos: int = 10, video: int = 30, breite: int = 1920, hoehe: int = 1440,
            groesse=(200.0, 100.0, 50.0), mit_objekt: bool = False, saat: int = 7, zip_auch: bool = False,
            lage_rauschen_mm: float = 0.0, melde=None) -> Path:
    """Synthetischen Scan ``<ziel>/Quader.kevscan`` erzeugen; Rückgabe der Ordner (mit ``zip_auch`` auch ZIP).

    ``lage_rauschen_mm`` > 0: die geschriebenen Lagen weichen wie bei ARKit von den echten ab (gerendert wird mit den
    echten): je Bild zufällig um diesen Betrag (Sigma je Achse) und ein Zehntel davon in Grad, dazu eine Drift über
    die Aufnahme bis zum Dreifachen."""
    rng = np.random.default_rng(saat)
    ziel = Path(ziel)
    ordner = ziel / "Quader.kevscan"
    shutil.rmtree(ordner, ignore_errors=True)
    for d in ("depth", "confidence", "fotos"):
        (ordner / d).mkdir(parents=True, exist_ok=True)
    szene = Szene(groesse=groesse)
    K = np.array([[1500.0, 0, 957.3], [0, 1500.0, 722.1], [0, 0, 1]])
    K[0] *= breite / 1920
    K[1] *= hoehe / 1440
    ziel_punkt = szene.mitte + [0, 0, szene.H / 2]
    # ARKit-Welt: X_ar = G (X_kev - off) / 1000, gedreht um y und verschoben (Boden bei y = -0,85 m)
    G = _ry(math.radians(37.0)) @ geo.M_AR.T
    off = np.array([-300.0, 200.0, 850.0])

    def arkit_lage(R, t):
        R_cw = geo.F_CAM @ R @ G.T
        t_cw = geo.F_CAM @ (R @ off + t) / 1000.0
        return R_cw.T, -R_cw.T @ t_cw

    kameras = []
    for i in range(fotos):
        az = math.radians(10 + 360.0 * i / fotos)
        el = math.radians(28 if i % 2 == 0 else 48)
        r = 600 + rng.uniform(-50, 50)
        C = ziel_punkt + r * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        R = blick(C, ziel_punkt + rng.uniform(-10, 10, 3))
        kameras.append(("foto", i, R, -R @ C, 2.0 + 1.5 * i))
    for k in range(video):
        az = math.radians(-20 + 360.0 * k / max(1, video))
        el = math.radians(35 + 6 * math.sin(2 * math.pi * k / max(1, video)))
        C = ziel_punkt + 700 * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        R = blick(C, ziel_punkt)
        kameras.append(("video", k, R, -R @ C, 0.1 * k))

    fotos_json, odo = [], ["timestamp, frame, x, y, z, qx, qy, qz, qw"]
    drift = (rng.normal(0, 1, 3), rng.normal(0, 1, 3))  # Richtung der Drift (Ort, Drehung)
    with tempfile.TemporaryDirectory() as tmp:
        for j, (art, i, R, t, zeit) in enumerate(kameras):
            bild, _ = rendere(szene, K, R, t, breite, hoehe, fein=2 if art == "foto" else 1)
            bild = cv2.GaussianBlur(bild, (0, 0), 0.6)
            bild = np.clip(bild.astype(np.float32) + rng.normal(0, 2.0, bild.shape), 0, 255).astype(np.uint8)
            d, c = lidar(szene, K, R, t, breite, hoehe, rng)
            if lage_rauschen_mm > 0:
                R, t = _verrauscht(R, t, rng, lage_rauschen_mm, j / max(1, len(kameras) - 1), drift)
            R_wc, t_wc = arkit_lage(R, t)
            q = geo.matrix_zu_quat(R_wc)
            if art == "foto":
                name = f"{i:03d}"
                cv2.imwrite(str(ordner / "fotos" / f"{name}.jpg"), bild, [cv2.IMWRITE_JPEG_QUALITY, 95])
                cv2.imwrite(str(ordner / "fotos" / f"{name}_depth.png"), d)
                cv2.imwrite(str(ordner / "fotos" / f"{name}_confidence.png"), c)
                fotos_json.append({"datei": f"{name}.jpg", "zeit": zeit, "breite": breite, "hoehe": hoehe,
                                   "k": K.tolist(), "lage": {"t": t_wc.tolist(), "q": q},
                                   "tiefe": f"{name}_depth.png", "konfidenz": f"{name}_confidence.png",
                                   "belichtung_s": 0.01, "iso": 100, "tracking": "normal"})
            else:
                cv2.imwrite(str(Path(tmp) / f"{i:06d}.png"), bild)
                cv2.imwrite(str(ordner / "depth" / f"{i:06d}.png"), d)
                cv2.imwrite(str(ordner / "confidence" / f"{i:06d}.png"), c)
                odo.append(f"{zeit:.4f}, {i}, " + ", ".join(f"{x:.6f}" for x in t_wc) + ", "
                           + ", ".join(f"{x:.7f}" for x in q))
            if melde:
                melde(j + 1, len(kameras))
        if video:
            r = subprocess.run([FFMPEG, "-v", "error", "-y", "-framerate", "10", "-i", str(Path(tmp) / "%06d.png"),
                                "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", str(ordner / "rgb.mp4")],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg: {r.stderr[-400:]}")
    if video:
        (ordner / "odometry.csv").write_text("\n".join(odo) + "\n", encoding="utf-8")
        (ordner / "camera_matrix.csv").write_text("\n".join(",".join(f"{x:.6f}" for x in z) for z in K) + "\n",
                                                  encoding="utf-8")
    (ordner / "fotos.json").write_text(json.dumps({"fotos": fotos_json}, indent=1), encoding="utf-8")
    meta = {"format": "kevscan", "version": 1, "name": "Quader", "erstellt": "2026-10-22T21:10:00+02:00",
            "geraet": "synthetisch", "ios": "-", "app": "kevscan.synth", "hz": 10,
            "video": {"breite": breite, "hoehe": hoehe, "bilder": video, "codec": "h264"},
            "tiefe": {"breite": 256, "hoehe": 192, "einheit": "mm", "quelle": "sceneDepth"},
            "fotos": {"anzahl": fotos, "breite": breite, "hoehe": hoehe}, "notiz": "synthetisch", "objekt": mit_objekt}
    (ordner / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    if mit_objekt:
        m_ar = G @ (szene.mitte + [0, 0, szene.H / 2] - off) / 1000.0
        boden = G @ (szene.mitte - off) / 1000.0
        # Box achsparallel in ARKit bis auf die Drehung um y: Drehung des Quaders plus die der ARKit-Welt
        (ordner / "objekt.json").write_text(json.dumps({
            "box": {"mitte": m_ar.tolist(), "groesse": [(szene.L + 30) / 1000, (szene.H + 20) / 1000,
                                                        (szene.B + 30) / 1000],
                    "drehung_y_grad": 20.0 + 37.0},
            "boden": {"punkt": boden.tolist(), "normale": [0, 1, 0]}}, indent=1), encoding="utf-8")
    vorschau = cv2.resize(cv2.imread(str(ordner / "fotos" / "000.jpg")), (512, 384), interpolation=cv2.INTER_AREA) \
        if fotos else None
    if vorschau is not None:
        cv2.imwrite(str(ordner / "vorschau.jpg"), vorschau)
    wahrheit: dict[str, Any] = {"quader_mm": [szene.L, szene.B, szene.H], "mitte_kev": szene.mitte.tolist(),
                                "lage_rauschen_mm": lage_rauschen_mm,
                                "drehung_grad": 20.0, "lidar_rauschen": "2 mm + 0,4 % der Tiefe, ±1,5 mm Versatz",
                                "K": K.tolist(), "arkit_G": G.tolist(), "arkit_off_mm": off.tolist()}
    (ziel / "wahrheit.json").write_text(json.dumps(wahrheit, indent=1), encoding="utf-8")
    if zip_auch:
        shutil.make_archive(str(ziel / "Quader.kevscan"), "zip", root_dir=ziel, base_dir="Quader.kevscan")
    return ordner


def _verrauscht(R, t, rng, mm: float, anteil: float, drift) -> tuple[np.ndarray, np.ndarray]:
    """Lage wie von ARKit: Zufall plus Drift (Ort mm, Drehung ein Zehntel davon in Grad)."""
    C = geo.zentrum(R, t)
    dC = rng.normal(0, mm, 3) + 3 * mm * anteil * drift[0] / max(np.linalg.norm(drift[0]), 1e-9)
    w = np.radians(rng.normal(0, mm / 10, 3) + 3 * (mm / 10) * anteil * drift[1] / max(np.linalg.norm(drift[1]), 1e-9))
    th = float(np.linalg.norm(w))
    if th > 1e-12:
        k = w / th
        Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        E = np.eye(3) + math.sin(th) * Kx + (1 - math.cos(th)) * Kx @ Kx
    else:
        E = np.eye(3)
    R2 = E @ R
    C2 = C + dC
    return R2, -R2 @ C2


def _ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])

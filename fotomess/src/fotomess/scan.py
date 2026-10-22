"""Scan als Quelle (Kev Scan, SCAN.md): bekannte Kameras aus ARKit, gemessene Tiefe aus PromptDA, Masken aus dem Netz.

Die Auswertung (``scan/``, kevscan) liefert ``kameras.json`` im Kev-CAD-System des Scans (Boden z = 0, Mitte x = y = 0)
mit Tiefenbildern (mm) und Konfidenz je Bild. Hier entsteht daraus:

1. **Lage Scan -> Modell** (``anlegen``): Drehung um Z und Verschiebung, Punkt-zu-Ebene-ICP der Scanpunkte auf die
   Oberfläche des Modells, vier Startdrehungen (0, 90, 180, 270 Grad gegen die Hauptachsen), die beste gewinnt.
2. **Kameras** im Modellsystem als feste Startwerte (``Eingabe.kamera``, keine Grobsuche, Brennweite fest) und als
   weiche Bindung (``Bild.kamera_start``, ``Einstellungen.kamera_sigma_*``): sie werden nur fein nachgeführt.
3. **Tiefe** je Bild (``Bild.tiefe``, ``TiefenKarte``): in ``einpassen.Ausgleich`` die Bedingung „Tiefe des Modells
   gleich gemessener Tiefe“ (robust, Gewicht nach Konfidenz). Damit sind die Maße metrisch, ohne bekanntes Maß.

Nach dem ersten Durchgang legt ``kevcad.vermessen_kevcad`` den Scan an das eingepasste Modell neu an und rechnet ein
zweites Mal (die Lage hängt beim ersten Mal an den Startmaßen).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .kamera import Kamera


@dataclass
class TiefenKarte:
    """Gemessene Tiefe eines Bildes (mm) mit Konfidenz (0…1) und Gradient; sx, sy: Tiefenpixel je Bildpixel."""
    D: np.ndarray
    C: np.ndarray
    gx: np.ndarray
    gy: np.ndarray
    sx: float
    sy: float

    @classmethod
    def lade(cls, tiefe: Path, konf: Path | None, bild_w: int, bild_h: int, sprung_rel: float = 0.03) -> "TiefenKarte":
        D = cv2.imread(str(tiefe), cv2.IMREAD_UNCHANGED).astype(np.float32)
        C = np.ones_like(D) if konf is None or not Path(konf).is_file() else \
            cv2.imread(str(konf), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
        C = np.where(D > 0, C, 0.0).astype(np.float32)
        g = cv2.GaussianBlur(np.where(D > 0, D, 0), (0, 0), 0.8)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        # Sprünge und Ränder ohne Messung zählen nicht
        k = np.ones((5, 5), np.uint8)
        leer = cv2.dilate((D <= 0).astype(np.uint8), k) > 0
        hoch = cv2.dilate(D, k)
        tief = cv2.erode(np.where(D > 0, D, 1e9).astype(np.float32), k)
        sprung = (hoch - np.minimum(tief, hoch)) > sprung_rel * np.maximum(D, 1.0) + 2.0
        C = np.where(leer | sprung, 0.0, C).astype(np.float32)
        h, w = D.shape
        return cls(D=D, C=C, gx=gx, gy=gy, sx=w / float(bild_w), sy=h / float(bild_h))

    def abtasten(self, u: np.ndarray):
        """u (n, 2) in Bildpixeln (stetig) -> Tiefe, Gradient (mm je Tiefenpixel), Konfidenz, gültig."""
        h, w = self.D.shape
        x = u[:, 0] * self.sx - 0.5
        y = u[:, 1] * self.sy - 0.5
        ok = (x >= 0) & (y >= 0) & (x < w - 1) & (y < h - 1)
        x0 = np.clip(x.astype(np.int32), 0, w - 2)
        y0 = np.clip(y.astype(np.int32), 0, h - 2)
        fx = np.clip(x - x0, 0, 1).astype(np.float32)
        fy = np.clip(y - y0, 0, 1).astype(np.float32)

        def bi(A):
            return (A[y0, x0] * (1 - fx) * (1 - fy) + A[y0, x0 + 1] * fx * (1 - fy) + A[y0 + 1, x0] * (1 - fx) * fy
                    + A[y0 + 1, x0 + 1] * fx * fy)
        c = np.minimum.reduce([self.C[y0, x0], self.C[y0, x0 + 1], self.C[y0 + 1, x0], self.C[y0 + 1, x0 + 1]])
        ok &= c > 0
        return bi(self.D), bi(self.gx), bi(self.gy), np.where(ok, c, 0.0), ok


class Scan:
    """kameras.json einer Scan-Auswertung: Kameras (Scan-System), Tiefe, Masken, Oberflächenpunkte."""

    def __init__(self, angaben: dict):
        self.datei = Path(angaben["kameras"])
        self.ordner = self.datei.parent
        daten = json.loads(self.datei.read_text(encoding="utf-8"))
        self.eintraege = {e["name"]: e for e in daten.get("bilder") or []}
        netz = angaben.get("netz") or str(self.ordner / str(daten.get("netz") or "netz_mm.obj"))
        self.punkte = oberflaechenpunkte(Path(netz))

    def maske(self, name: str) -> Path | None:
        e = self.eintraege.get(name)
        if not e or not e.get("maske"):
            return None
        p = self.ordner / e["maske"]
        return p if p.is_file() else None

    def kamera(self, name: str) -> Kamera | None:
        e = self.eintraege.get(name)
        if not e:
            return None
        k = e["kamera"]
        return Kamera(R=np.array(k["R"], float), t=np.array(k["t"], float), f=float(k["f"]), w=int(k["w"]),
                      h=int(k["h"]), cx=float(k["cx"]), cy=float(k["cy"]), name=name)

    def tiefe(self, name: str) -> TiefenKarte | None:
        e = self.eintraege.get(name)
        if not e or not e.get("tiefe"):
            return None
        k = e["kamera"]
        konf = self.ordner / e["konfidenz"] if e.get("konfidenz") else None
        return TiefenKarte.lade(self.ordner / e["tiefe"], konf, int(k["w"]), int(k["h"]))

    def setze(self, bilder: list, lage: dict) -> int:
        """Je Bild (fotomess.bild.Bild, Name wie in kameras.json) Startkamera im Modellsystem und Tiefe anhängen.
        Rückgabe: Zahl der Bilder mit Kamera."""
        A, b = np.asarray(lage["A"], float), np.asarray(lage["b"], float)
        n = 0
        for bild in bilder:
            k = self.kamera(bild.name)
            if k is None:
                bild.kamera_start = None
                continue
            R2 = k.R @ A.T
            t2 = k.t - R2 @ b
            sx, sy = bild.breite / float(k.w), bild.hoehe / float(k.h)
            bild.kamera_start = Kamera(R=R2, t=t2, f=k.f * sx, w=int(bild.breite), h=int(bild.hoehe), cx=k.cx * sx,
                                       cy=k.cy * sy, name=bild.name)
            if getattr(bild, "tiefe", None) is None:
                tk = self.tiefe(bild.name)
                if tk is not None:
                    tk.sx /= sx  # Tiefenpixel je Pixel des Bildes in Originalgröße
                    tk.sy /= sy
                bild.tiefe = tk
            n += 1
        return n


def oberflaechenpunkte(obj: Path, anzahl: int = 12000) -> np.ndarray:
    """Punkte auf dem Scan-Netz (OBJ, mm), flächengleich verteilt."""
    P, T = [], []
    with open(obj, encoding="utf-8") as f:
        for z in f:
            if z.startswith("v "):
                P.append([float(x) for x in z.split()[1:4]])
            elif z.startswith("f "):
                ids = [int(x.split("/")[0]) - 1 for x in z.split()[1:]]
                for k in range(1, len(ids) - 1):
                    T.append([ids[0], ids[k], ids[k + 1]])
    P, T = np.asarray(P, float), np.asarray(T, np.int64)
    X, _ = _flaechenproben(P, T, anzahl, np.random.default_rng(13))
    return X


def _flaechenproben(V, T, anzahl, rng):
    a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(b - a, c - a)
    fl = np.linalg.norm(n, axis=1)
    ok = fl > 1e-9
    a, b, c, n, fl = a[ok], b[ok], c[ok], n[ok], fl[ok]
    wahl = rng.choice(len(fl), size=anzahl, p=fl / fl.sum())
    u, v = rng.random(anzahl), rng.random(anzahl)
    aussen = u + v > 1
    u[aussen], v[aussen] = 1 - u[aussen], 1 - v[aussen]
    X = a[wahl] + u[:, None] * (b[wahl] - a[wahl]) + v[:, None] * (c[wahl] - a[wahl])
    return X, n[wahl] / fl[wahl, None]


def _rz(w):
    c, s = math.cos(w), math.sin(w)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _icp(P0, baum, S, N, A, b, schritte=30, fang=(25.0, 3.0)):
    """Punkt-zu-Ebene, nur Drehung um Z und Verschiebung, gestutzt auf die besten 75 %."""
    rest = math.inf
    anteil = 0.0
    for i in range(schritte):
        f = fang[0] + (fang[1] - fang[0]) * i / max(1, schritte - 1)
        P = P0 @ A.T + b
        d, idx = baum.query(P, distance_upper_bound=f)
        ok = np.isfinite(d)
        if ok.sum() < 50:
            return A, b, math.inf, 0.0
        ok &= d <= np.quantile(d[ok], 0.75)
        p, s, n = P[ok], S[idx[ok]], N[idx[ok]]
        k = np.stack([-p[:, 1], p[:, 0], np.zeros(len(p))], 1)
        J = np.concatenate([(n * k).sum(1, keepdims=True), n], 1)
        e = (n * (p - s)).sum(1)
        try:
            x = np.linalg.solve(J.T @ J + 1e-6 * np.eye(4), -J.T @ e)
        except np.linalg.LinAlgError:
            break
        Rz = _rz(x[0])
        A, b = Rz @ A, Rz @ b + x[1:]
        rest = float(np.abs(e).mean())
        anteil = float(ok.mean())
        if abs(x[0]) < 1e-6 and np.linalg.norm(x[1:]) < 1e-3:
            break
    return A, b, rest, anteil


def anlegen(P_scan: np.ndarray, V: np.ndarray, T: np.ndarray, start: dict | None = None) -> dict:
    """Lage Scan -> Modell (X_modell = A X_scan + b, A Drehung um Z). Ohne ``start`` vier Startdrehungen gegen die
    Hauptachsen der Grundrisse; Bewertung: mittlerer Abstand Scan -> Modell plus Modell -> Scan (gestutzt)."""
    from scipy.spatial import cKDTree

    rng = np.random.default_rng(17)
    S, N = _flaechenproben(np.asarray(V, float), np.asarray(T, np.int64), 30000, rng)
    baum = cKDTree(S)
    P0 = P_scan if len(P_scan) <= 8000 else P_scan[rng.choice(len(P_scan), 8000, replace=False)]
    baum_scan = cKDTree(P0)

    def bewertung(A, b):
        d1, _ = baum.query(P0 @ A.T + b)
        Sq = S[:: max(1, len(S) // 8000)]
        d2, _ = baum_scan.query((Sq - b) @ A)  # Modellpunkte ins Scan-System
        return float(np.mean(np.minimum(d1, 30.0)) + np.mean(np.minimum(d2, 30.0)))

    if start is not None:
        A, b, rest, anteil = _icp(P0, baum, S, N, np.asarray(start["A"], float), np.asarray(start["b"], float),
                                  fang=(10.0, 2.0))
        return {"A": A, "b": b, "rest_mm": round(rest, 3), "anteil": round(anteil, 3), "wertung": bewertung(A, b)}

    def hauptachse(Q):
        Q2 = Q[:, :2] - Q[:, :2].mean(0)
        w, v = np.linalg.eigh(Q2.T @ Q2)
        a = v[:, int(np.argmax(w))]
        return math.atan2(a[1], a[0])

    oben_s = P0[P0[:, 2] > np.percentile(P0[:, 2], 15)]
    oben_m = S[S[:, 2] > np.percentile(S[:, 2], 15)]
    w0 = hauptachse(oben_m) - hauptachse(oben_s)
    beste = None
    for k in range(4):
        A = _rz(w0 + k * math.pi / 2)
        Q = P0 @ A.T
        b = np.array([(S[:, 0].min() + S[:, 0].max()) / 2 - (Q[:, 0].min() + Q[:, 0].max()) / 2,
                      (S[:, 1].min() + S[:, 1].max()) / 2 - (Q[:, 1].min() + Q[:, 1].max()) / 2,
                      S[:, 2].min() - Q[:, 2].min()])
        A, b, rest, anteil = _icp(P0, baum, S, N, A, b)
        w = bewertung(A, b)
        if beste is None or w < beste["wertung"]:
            beste = {"A": A, "b": b, "rest_mm": round(rest, 3), "anteil": round(anteil, 3), "wertung": w,
                     "start_grad": round(math.degrees(w0 + k * math.pi / 2), 1)}
    return beste


def lage_json(lage: dict, bilder: int) -> dict:
    A = np.asarray(lage["A"], float)
    return {"A": A.tolist(), "b": np.asarray(lage["b"], float).tolist(), "rest_mm": lage.get("rest_mm"),
            "anteil": lage.get("anteil"), "drehung_z": round(math.degrees(math.atan2(A[1, 0], A[0, 0])), 2),
            "bilder": int(bilder)}

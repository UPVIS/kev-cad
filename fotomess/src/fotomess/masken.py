"""Masken: Studiofoto auf Weiß, Apple Vision (Vordergrund, Neural Engine) und Farbe; Kombination für echte
Umgebungen.

- weiss: dunkelster Farbkanal unter 245, Löcher vom Rand her gefüllt (wie fotocad.masken).
- vision: VNGenerateForegroundInstanceMaskRequest über das Swift-Hilfsprogramm swift/fotomess_hilfe.swift (wird beim
  ersten Aufruf mit swiftc übersetzt und im Zwischenspeicher abgelegt). Etwa 40 ms je 4K-Bild nach dem ersten Aufruf.
  Die Ränder sind weich und um einige Pixel ungenau (die Maske entsteht in geringer Auflösung).
- farbe: HSV-Bereich (z. B. blauer Kunststoff), pixelgenau, aber nur für einfarbige Teile.
- kombiniert: Farbe, wo sie greift (genaue Ränder), Vision für den Rest (Rollen, Metall); Vision-Pixel dicht am
  Farbbereich, die wie Boden aussehen, fallen weg.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .modell import CACHE

HIER = Path(__file__).resolve().parent
SWIFT = HIER.parent.parent / "swift" / "fotomess_hilfe.swift"
HILFE = CACHE / "bin" / "fotomess-hilfe"


def hilfsprogramm():
    """Pfad zum übersetzten Swift-Hilfsprogramm (übersetzt bei Bedarf, wenn die Quelle neuer ist)."""
    if not HILFE.exists() or HILFE.stat().st_mtime < SWIFT.stat().st_mtime:
        HILFE.parent.mkdir(parents=True, exist_ok=True)
        # gemeinsame Build-Sperre mit VoiceBridge (16-GB-Mac fror unter parallelen Builds ein)
        subprocess.run(["lockf", "-k", "/tmp/vb-xcodebuild.lock", "swiftc", "-O", str(SWIFT), "-o", str(HILFE)],
                       check=True, capture_output=True)
    return HILFE


def weiss(bild, schwelle=245, fuellen=True):
    """Studiofoto auf reinem Weiß -> bool-Maske."""
    m = (bild.min(axis=2) < schwelle).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    if fuellen:
        hh, ww = m.shape
        flut = np.pad(m, 1)
        ff = np.zeros((hh + 4, ww + 4), np.uint8)
        cv2.floodFill(flut, ff, (0, 0), 2)
        m = (flut[1:-1, 1:-1] != 2).astype(np.uint8)
    return m > 0


def vision(pfade, ordner=None):
    """Vordergrund-Instanzen je Bild: {pfad: [float32-Maske 0..1, ...]} in voller Bildgröße."""
    ordner = Path(ordner or CACHE / "vision")
    ordner.mkdir(parents=True, exist_ok=True)
    pfade = [str(p) for p in pfade]
    erg = subprocess.run([str(hilfsprogramm()), "maske", str(ordner)] + pfade, check=True, capture_output=True, text=True)
    out = {}
    for zeile in erg.stdout.splitlines():
        d = json.loads(zeile)
        masken = []
        for name in d.get("instanzen", []):
            m = cv2.imread(str(ordner / name), cv2.IMREAD_GRAYSCALE)
            masken.append(m.astype(np.float32) / 255.0)
            (ordner / name).unlink()
        out[d["bild"]] = masken
    return out


def video_meta(pfad):
    erg = subprocess.run([str(hilfsprogramm()), "meta", str(pfad)], check=True, capture_output=True, text=True)
    return json.loads(erg.stdout.strip().splitlines()[-1])


def farbe(bild, h_bereich=(95, 130), s_min=70, v_min=25):
    """HSV-Bereich (OpenCV: H 0..180) -> bool-Maske, kleine Lücken geschlossen."""
    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
    m = (hsv[..., 0] >= h_bereich[0]) & (hsv[..., 0] <= h_bereich[1]) & (hsv[..., 1] >= s_min) & (hsv[..., 2] >= v_min)
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return m > 0


def kleine_loecher_fuellen(m, anteil):
    """Löcher (nicht mit dem Bildrand verbunden) unter anteil der Bildfläche schließen: Schatten und Glanz im
    Objekt, nicht aber echte Öffnungen."""
    zahl, lab, stat, _ = cv2.connectedComponentsWithStats((~m).astype(np.uint8), connectivity=4)
    grenze = anteil * m.size
    h, w = m.shape
    out = m.copy()
    for i in range(1, zahl):
        x, y, bw, bh, a = stat[i]
        if a < grenze and x > 0 and y > 0 and x + bw < w and y + bh < h:
            out[lab == i] = True
    return out


def instanz_waehlen(instanzen, hinweis=None):
    """Die Instanz mit der größten Überlappung mit dem Hinweis (z. B. Farbmaske), sonst die größte."""
    if not instanzen:
        return None
    if hinweis is not None and hinweis.any():
        werte = [float((m > 0.5)[hinweis].sum()) for m in instanzen]
    else:
        werte = [float((m > 0.5).sum()) for m in instanzen]
    return instanzen[int(np.argmax(werte))]


def kombiniert(bild, vision_maske, farb_maske, band=8):
    """Weiche Maske (0..1): Farbe mit genauen Rändern, Vision für nicht farbige Teile; Vision-Ränder dicht an der
    Farbe nur, wenn der Pixel nicht wie der Untergrund aussieht."""
    v = vision_maske > 0.5
    if farb_maske is None or not farb_maske.any():
        return vision_maske.astype(np.float32)
    f = farb_maske & cv2.dilate(v.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    nah = cv2.dilate(f.astype(np.uint8), np.ones((2 * band + 1, 2 * band + 1), np.uint8)).astype(bool) & ~f
    # Untergrund: Farbe der Pixel knapp außerhalb von Vision
    aussen = cv2.dilate(v.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool) & ~cv2.dilate(
        v.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    lab = cv2.cvtColor(bild, cv2.COLOR_BGR2LAB).astype(np.float32)
    if aussen.any():
        mu = np.median(lab[aussen], axis=0)
        sd = np.maximum(np.median(np.abs(lab[aussen] - mu), axis=0) * 1.5, 6.0)
        boden = (np.abs(lab - mu) / sd).max(axis=2) < 2.5
    else:
        boden = np.zeros(v.shape, bool)
    rest = v & ~f & ~(nah & boden)
    m = f | rest
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    m = kleine_loecher_fuellen(m, 0.002)
    weich = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.6)
    return weich

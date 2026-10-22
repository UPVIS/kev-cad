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


def farbbereich(bild, h_bereich, s_min, v_min):
    """HSV-Bereich (OpenCV: H 0..180) -> bool-Maske ohne Glättung. Ein Bereich mit Anfang über dem Ende läuft über
    0 hinweg (Rot: (168, 4) heißt H >= 168 oder H <= 4)."""
    hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0]
    lo, hi = h_bereich
    im_bereich = ((h >= lo) & (h <= hi)) if lo <= hi else ((h >= lo) | (h <= hi))
    return im_bereich & (hsv[..., 1] >= s_min) & (hsv[..., 2] >= v_min)


def farbe(bild, h_bereich=(95, 130), s_min=70, v_min=25):
    """HSV-Bereich (OpenCV: H 0..180, über 0 hinweg wie bei farbbereich) -> bool-Maske, kleine Lücken geschlossen."""
    m = farbbereich(bild, h_bereich, s_min, v_min)
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


def kombiniert(bild, vision_maske, farb_maske, band=8, ausschluss=None, umkreis=None, schliessen=0,
               loch_anteil=0.002, innen=None, aussen_oeffnen=0):
    """Weiche Maske (0..1): Farbe mit genauen Rändern, Vision für nicht farbige Teile; Vision-Ränder dicht an der
    Farbe nur, wenn der Pixel nicht wie der Untergrund aussieht.

    ausschluss: HSV-Bereich (h_bereich, s_min, v_min) einer Unterlage, die Vision mit zum Vordergrund zählt (Holzscheibe
    unter der Scarlett): solche Pixel zählen nur über die Farbe. umkreis: Vision-Pixel ohne Objektfarbe nur bis zu
    diesem Abstand (Pixel) von der Farbmaske (Blenden und Knöpfe sitzen am roten Gehäuse, die Unterlage reicht weiter).
    schliessen: Lücken bis zu dieser Breite (Pixel) schließen (Beschriftung und Spiegelungen auf schwarzen Blenden);
    loch_anteil: Löcher bis zu diesem Anteil der Bildfläche füllen (Gegenstände ohne echte Durchbrüche: größer).
    innen: bool-Maske, in der Vision ohne Farbprüfung gilt (konvexe Hülle eines Gehäuses, das schwarze Blenden
    einfasst; in den Blenden spiegelt sich die Unterlage). ausschluss, umkreis und die Untergrundprüfung gelten dann
    nur außerhalb. aussen_oeffnen: dort zusätzlich schmale Reste unter dieser Breite (Pixel) entfernen."""
    v = vision_maske > 0.5
    if farb_maske is None or not farb_maske.any():
        return vision_maske.astype(np.float32)
    drin = np.zeros(v.shape, bool) if innen is None else innen.astype(bool)
    va = v & ~drin
    if ausschluss is not None:
        va &= ~farbbereich(bild, *ausschluss)
    if umkreis:
        k = 2 * int(umkreis) + 1
        va &= cv2.dilate(farb_maske.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    if aussen_oeffnen:
        k = 2 * int(aussen_oeffnen) + 1
        va = cv2.morphologyEx(va.astype(np.uint8), cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    v = va | (v & drin)
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
    rest = v & ~f & ~(nah & boden & ~drin)
    m = f | rest
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    if schliessen:
        k = 2 * int(schliessen) + 1
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    m = kleine_loecher_fuellen(m, loch_anteil)
    if innen is not None and drin.any():
        # nur Teile, die am Innenbereich hängen (vereinzelte Reste der Unterlage fallen weg)
        zahl, lab = cv2.connectedComponents(m.astype(np.uint8))
        behalten = np.unique(lab[drin & m])
        m = np.isin(lab, behalten[behalten > 0])
    weich = cv2.GaussianBlur(m.astype(np.float32), (0, 0), 0.6)
    return weich


def gehaeuse_optionen(farb_maske, breite, ausschluss=None, umkreis_anteil=0.12):
    """Optionen für kombiniert bei einem farbigen Gehäuse, das andersfarbige Blenden rundum einfasst (Scarlett 2i2:
    rotes Rohr, schwarze Blenden, Knöpfe): Innenbereich = konvexe Hülle der größeren Farbflächen (kleine wie rote
    Kabel im Hintergrund zählen nicht), außerhalb nur Vision-Pixel bis umkreis_anteil der Gehäusegröße entfernt
    (Knöpfe), ohne die Farbe der Unterlage und ohne schmale Reste. breite: Bildbreite in Pixeln."""
    zahl, lab, stat, _ = cv2.connectedComponentsWithStats(farb_maske.astype(np.uint8))
    if zahl <= 1:
        return dict(ausschluss=ausschluss, umkreis=umkreis_anteil * breite * 0.2)
    flaeche = stat[1:, cv2.CC_STAT_AREA]
    gross = 1 + np.flatnonzero(flaeche >= 0.02 * flaeche.max())
    ys, xs = np.nonzero(np.isin(lab, gross))
    huelle = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
    innen = np.zeros(farb_maske.shape, np.uint8)
    cv2.fillConvexPoly(innen, huelle, 1)
    innen = cv2.erode(innen, np.ones((5, 5), np.uint8)) > 0
    groesse = float(max(xs.max() - xs.min(), ys.max() - ys.min()))
    return dict(ausschluss=ausschluss, umkreis=umkreis_anteil * groesse, innen=innen,
                aussen_oeffnen=max(3, round(0.0025 * breite)), schliessen=max(3, round(0.003 * breite)),
                loch_anteil=0.05)

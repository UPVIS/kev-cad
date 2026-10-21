"""Prüfdatensatz Rollwagen: Kevins Video IMG_5182.MOV (iPhone 15 Pro Max, 4K, echte Umgebung).

Bekannt: 610 x 410 mm, Räder Ø 100 mm (Hersteller). Gesucht: Bauhöhe der Rollen, Rahmenhöhe, Stegbreite und was
sonst gut bestimmbar ist. Das Video hat zwei Teile: zuerst steht der Wagen auf den Rollen, dann liegt er kopfüber.
Für die Messung ist das gleich (Kameras im Objektsystem), die Lenkrollen schwenken aber je Bild anders.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from .. import masken, video
from ..bild import Bild
from ..kamera import brennweite_aus_35mm
from ..modell import CACHE, baue_param_netz
from ..modelle import rollwagen as R

VIDEO = Path.home() / "Downloads/IMG_5182.MOV"
ABLAGE = CACHE / "rollwagen"
ARBEIT = 1080                      # Breite der Arbeitskopie (Original 2160 x 3840, Hochformat)
BLAU = ((95, 130), 70, 25)         # HSV-Bereich des Kunststoffs
ANNAHMEN = dict(rolle_h=128.0, rahmen_h=35.0, steg=45.0)       # Annahmen der Kev-CAD-Sitzung laut Auftrag
FREI = ["rolle_h", "rahmen_h", "steg", "rand_h", "oeff_fase", "schraube_rand", "nachlauf", "rad_b", "eck_fase"]
PRUEF_FREI = ["wagen_b", "rad_d"]   # Prüflauf: diese Herstellermaße mitmessen (nur 610 fest)
# Harte Grenzen: der Rand ist in jedem Bild deutlich zu sehen (mindestens 8 mm), sonst nur physikalisch sinnvoll.
# Ohne sie kann die Suche den Rand auf null drücken und seine Kanten auf die starke Außenkante legen.
GRENZEN = {"rolle_h": (80, 170), "rahmen_h": (12, 80), "steg": (25, 100), "rand_h": (8, 40), "oeff_fase": (50, 150),
           "schraube_rand": (35, 100), "nachlauf": (5, 60), "rad_b": (15, 60), "eck_fase": (3, 50), "wagen_b": (350, 470),
           "rad_d": (70, 130)}


def kennzahlen():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    datei = ABLAGE / "kennzahlen.json"
    if datei.exists():
        return json.loads(datei.read_text())
    k = video.bewerten(VIDEO, 6.0, 540, farbbereich=BLAU)
    datei.write_text(json.dumps(k))
    return k


def f_vorgabe():
    """Hauptkamera 24 mm KB-Äquivalent (QuickTime-Metadaten); 4K-Video mit Bildstabilisierung etwa 5 % enger."""
    try:
        m = masken.video_meta(VIDEO)
        f35 = float(m.get("mdta/com.apple.quicktime.camera.focal_length.35mm_equivalent", 24))
    except Exception:
        f35 = 24.0
    info = video.info(VIDEO)
    return brennweite_aus_35mm(f35, info["breite"], info["hoehe"], video_beschnitt=1.05), f35


def bilder(n, zeiten=None):
    """n automatisch gewählte Einzelbilder (oder feste Zeitpunkte) mit Masken. Rückgabe: Liste Bild."""
    if zeiten is None:
        k = kennzahlen()
        wahl = video.auswaehlen(k, n)
        zeiten = [k[i]["t"] for i in wahl]
    dateien = video.holen(VIDEO, zeiten, ABLAGE / "bilder")
    out = []
    fehlend = [d for d in dateien if not (ABLAGE / "masken" / (d.stem + ".npz")).exists()]
    vis = masken.vision(fehlend, ABLAGE / "vision") if fehlend else {}
    for d in dateien:
        ziel = ABLAGE / "masken" / (d.stem + ".npz")
        im = cv2.imread(str(d))
        h, w = im.shape[:2]
        if not ziel.exists():
            fm = masken.farbe(im, *BLAU)
            v = masken.instanz_waehlen(vis.get(str(d), []), fm)
            if v is None:
                v = fm.astype(np.float32)
            m = masken.kombiniert(im, v, fm)
            hk = round(h * ARBEIT / w)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(ziel, maske=cv2.resize(m, (ARBEIT, hk), interpolation=cv2.INTER_AREA).astype(np.float16),
                                vision=cv2.resize(v, (ARBEIT, hk), interpolation=cv2.INTER_AREA).astype(np.float16))
        z = np.load(ziel)
        farbe = cv2.resize(im, (ARBEIT, round(h * ARBEIT / w)), interpolation=cv2.INTER_AREA)
        b = Bild(farbe, d.stem, maske=z["maske"].astype(np.float32), ursprung=(w, h))
        b.vision = z["vision"].astype(np.float32)
        b.zeit = float(d.stem.rsplit("_", 1)[1])
        out.append(b)
    return out


def netz(p=None, frei=None, prozesse=4):
    p = dict(R.P, **(p or {}))
    frei = frei or FREI
    return baue_param_netz(R.DATEI, p, frei, {}, gelenke=R.gelenke(p), prozesse=prozesse,
                           datei_stand=Path(R.__file__).stat().st_mtime)


def eingaben(bilder_, f):
    from ..ablauf import Eingabe
    paare = [(e, 0.0) for e in range(10, 81, 10)] + [(-e, 180.0) for e in range(10, 81, 10)]
    out = []
    for b in bilder_:
        out.append(Eingabe(bild=b, netz="rollwagen", f=f, f_gruppe="iphone", winkel=(0.0, 0.0, 0.0, 0.0),
                           winkel_frei=(0, 1, 2, 3), paare=tuple(paare),
                           winkel_raster={g: list(np.arange(0, 360, 30.0)) for g in range(4)}))
    return out

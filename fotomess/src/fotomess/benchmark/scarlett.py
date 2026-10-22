"""Prüfdatensatz Scarlett 2i2 (4. Gen.): Kevins Video IMG_5186.MOV (iPhone 15 Pro Max, 4K quer, 39,7 s).

Das Interface liegt auf einer Holzscheibe auf Fliesenboden; die Kamera geht rundherum (vorn, hinten, flach,
steil von oben, Nahaufnahmen der Vorderseite). Bekannt (Hersteller): 180 x 117 x 47,5 mm; offen ist, ob Tiefe und
Höhe Knöpfe und Füße einschließen. Fest ist nur die Breite 180 (das Rohr hat seitlich keine Anbauten); gemessen
werden Gehäusetiefe, Gehäusehöhe, Kantenradius und die Überstände der Knöpfe.

Masken: rotes Aluminium über die Farbe (Rot läuft über H = 0), Blenden und Knöpfe über Apple Vision. Vision zählt
die Holzscheibe mit zum Vordergrund; Holzfarbe ist deshalb ausgeschlossen, und Vision-Pixel ohne Rot zählen nur in
der Nähe des Gehäuses (umkreis).
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
from ..modelle import scarlett as S

VIDEO = Path.home() / "Downloads/IMG_5186.MOV"
ABLAGE = CACHE / "scarlett"
ARBEIT = 1920                      # Breite der Arbeitskopie (Original 3840 x 2160, Querformat)
ROT = ((168, 4), 70, 25)           # HSV-Bereich des Gehäuses (über H = 0)
HOLZ = ((6, 24), 50, 45)           # Holzscheibe: aus der Vision-Maske nehmen
UMKREIS = 0.12                     # Vision ohne Rot nur bis 12 % der Gehäusegröße im Bild vom Rot entfernt
SOLL = dict(breite=180.0, tiefe=117.0, hoehe=47.5)       # Herstellerangaben
FREI = ["tiefe", "hoehe", "kanten_r", "knopf_h", "gross_h"]
# Harte Grenzen: nur physikalisch sinnvolle Bereiche (die Knöpfe sind in jeder Draufsicht deutlich zu sehen)
GRENZEN = {"tiefe": (80, 130), "hoehe": (35, 60), "kanten_r": (0.5, 15), "knopf_h": (4, 25), "gross_h": (4, 25),
           "breite": (150, 210)}
VORGABEN = {"tiefe": (110, 25), "hoehe": (46, 10), "kanten_r": (5, 5), "knopf_h": (12, 8), "gross_h": (12, 8),
            "breite": (180, 30)}


def kennzahlen():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    datei = ABLAGE / "kennzahlen.json"
    if datei.exists():
        return json.loads(datei.read_text())
    k = video.bewerten(VIDEO, 6.0, 640, farbbereich=ROT)
    datei.write_text(json.dumps(k))
    return k


def f_vorgabe():
    """Hauptkamera 24 mm KB (QuickTime-Metadaten); 4K-Video mit Bildstabilisierung etwa 5 % enger."""
    try:
        m = masken.video_meta(VIDEO)
        f35 = float(m.get("mdta/com.apple.quicktime.camera.focal_length.35mm_equivalent", 24))
    except Exception:
        f35 = 24.0
    info = video.info(VIDEO)
    return brennweite_aus_35mm(f35, info["breite"], info["hoehe"], video_beschnitt=1.05), f35


def maske(im, vis):
    """Weiche Maske aus Rot und Vision (Holz ausgeschlossen). Vision-Pixel ohne Rot zählen bis UMKREIS mal der
    Größe des roten Gehäuses davon entfernt (Knöpfe stehen bis 15 mm vor, ein Zwölftel der Breite). Rückgabe:
    Maske, Vision-Instanz, Farbmaske (rot)."""
    fm = masken.farbe(im, *ROT)
    v = masken.instanz_waehlen(vis, fm)
    if v is None:
        v = fm.astype(np.float32)
    return masken.kombiniert(im, v, fm, **masken.gehaeuse_optionen(fm, im.shape[1], ausschluss=HOLZ,
                                                                  umkreis_anteil=UMKREIS)), v, fm


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
        hk = round(h * ARBEIT / w)
        if not ziel.exists():
            m, v, fm = maske(im, vis.get(str(d), []))
            ziel.parent.mkdir(parents=True, exist_ok=True)
            klein = [cv2.resize(x.astype(np.float32), (ARBEIT, hk), interpolation=cv2.INTER_AREA).astype(np.float16)
                     for x in (m, v, fm)]
            np.savez_compressed(ziel, maske=klein[0], vision=klein[1], rot=klein[2])
        z = np.load(ziel)
        farbe = cv2.resize(im, (ARBEIT, hk), interpolation=cv2.INTER_AREA)
        b = Bild(farbe, d.stem, maske=z["maske"].astype(np.float32), ursprung=(w, h))
        b.vision = z["vision"].astype(np.float32)
        b.farbmaske = z["rot"].astype(np.float32)          # rotes Aluminium: Farbteil-Prüfung der Startlagen
        b.zeit = float(d.stem.rsplit("_", 1)[1])
        out.append(b)
    return out


def netz(p=None, frei=None, prozesse=4):
    p = dict(S.P, **(p or {}))
    frei = frei or FREI
    n = baue_param_netz(S.DATEI, p, frei, {}, prozesse=prozesse, datei_stand=Path(S.__file__).stat().st_mtime)
    n.farb_tris = S.rote_dreiecke(n)
    return n


def eingaben(bilder_, f):
    """Gegenstand liegt aufrecht: Grobsuche von flach (0 Grad) bis steil von oben (80 Grad), Kamera waagrecht."""
    from ..ablauf import Eingabe
    paare = [(e, 0.0) for e in range(0, 81, 10)]
    # vorn und hinten sehen gleich aus (rotes Rohr, schwarze Blende), nur die Knöpfe unterscheiden sie: zu jeder
    # Startlage auch die um die Hochachse um 180 Grad gedrehte prüfen
    zwilling = ((np.diag([-1.0, -1.0, 1.0]), np.zeros(3)),)
    return [Eingabe(bild=b, netz="scarlett", f=f, f_gruppe="iphone", paare=tuple(paare), zwillinge=zwilling)
            for b in bilder_]

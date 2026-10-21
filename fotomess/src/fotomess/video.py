"""Einzelbilder aus einem Handyvideo: schnell bewerten, wenige scharfe und verschiedene auswählen, in voller Größe holen.

1. Bewerten: ffmpeg dekodiert (Hardware, VideoToolbox) mit `bewerten_fps` Bildern je Sekunde in kleiner Größe; je
   Bild Schärfe (Varianz des Laplace-Bildes), Bewegung zum Vorgänger (mittlere Differenz nach Ausrichtung per
   Phasenkorrelation, als Maß für den Kameraweg) und optional der Anteil eines Farbbereichs (Objekt im Bild?) sowie
   ob das Objekt am Bildrand abgeschnitten ist.
2. Auswählen: der Kameraweg wird in n gleich lange Abschnitte geteilt (so verteilen sich die Bilder über die
   Blickwinkel, nicht über die Zeit); je Abschnitt das schärfste Bild mit vollständig sichtbarem Objekt. Optional
   prüft danach eine Grobsuche der Kameralage die Blickwinkel-Vielfalt (start.grobsuche, siehe ablauf.py).
3. Holen: die gewählten Zeitpunkte in voller Größe als JPEG (Qualität 95).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .modell import CACHE


def info(pfad):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", str(pfad)],
                       check=True, capture_output=True, text=True)
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s.get("codec_type") == "video")
    w, h = int(v["width"]), int(v["height"])
    drehung = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            drehung = int(sd["rotation"])
    if abs(drehung) % 180 == 90:
        w, h = h, w
    zaehler, nenner = v.get("avg_frame_rate", "30/1").split("/")
    return dict(breite=w, hoehe=h, fps=float(zaehler) / float(nenner), dauer=float(d["format"]["duration"]),
                bilder=int(v.get("nb_frames", 0)))


def bewerten(pfad, bewerten_fps=6.0, breite=540, farbbereich=None):
    """Kennzahlen je bewertetem Bild (Liste von dicts mit t, schaerfe, bewegung, anteil, rand)."""
    i = info(pfad)
    hoehe = round(i["hoehe"] * breite / i["breite"] / 2) * 2
    cmd = ["ffmpeg", "-v", "error", "-hwaccel", "videotoolbox", "-i", str(pfad), "-vf",
           f"fps={bewerten_fps},scale={breite}:{hoehe}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    groesse = breite * hoehe * 3
    out, vorher, k = [], None, 0
    while True:
        roh = proc.stdout.read(groesse)
        if len(roh) < groesse:
            break
        bild = np.frombuffer(roh, np.uint8).reshape(hoehe, breite, 3)
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        schaerfe = float(cv2.Laplacian(grau, cv2.CV_32F).var())
        klein = cv2.resize(grau, (breite // 4, hoehe // 4), interpolation=cv2.INTER_AREA).astype(np.float32)
        bewegung = 0.0
        if vorher is not None:
            (dx, dy), _ = cv2.phaseCorrelate(vorher, klein)
            M = np.float32([[1, 0, -dx], [0, 1, -dy]])
            ausgerichtet = cv2.warpAffine(klein, M, (klein.shape[1], klein.shape[0]), borderMode=cv2.BORDER_REPLICATE)
            bewegung = float(np.hypot(dx, dy) + np.abs(ausgerichtet - vorher).mean() * 0.5)
        vorher = klein
        e = dict(t=k / bewerten_fps, schaerfe=schaerfe, bewegung=bewegung)
        if farbbereich:
            from .masken import farbe
            m = farbe(bild, *farbbereich)
            e["anteil"] = float(m.mean())
            rand = np.concatenate([m[:3].ravel(), m[-3:].ravel(), m[:, :3].ravel(), m[:, -3:].ravel()])
            e["rand"] = float(rand.mean())
        out.append(e)
        k += 1
    proc.wait()
    return out


def auswaehlen(kennzahlen, n, min_anteil=0.04, max_rand=0.03, rand_gewicht=15.0, schaerfe_quantil=0.35):
    """n Zeitpunkte: Kameraweg in n gleiche Abschnitte, je Abschnitt das beste brauchbare Bild. Güte =
    log(Schärfe) - rand_gewicht * Randanteil (abgeschnittene Objekte verlieren), Mindestschärfe als Quantil."""
    t = np.array([e["t"] for e in kennzahlen])
    sch = np.array([e["schaerfe"] for e in kennzahlen])
    weg = np.cumsum([e["bewegung"] for e in kennzahlen])
    ok = np.ones(len(t), bool)
    guete = np.log(np.maximum(sch, 1e-6))
    if "anteil" in kennzahlen[0]:
        rand = np.array([e["rand"] for e in kennzahlen])
        ok &= np.array([e["anteil"] for e in kennzahlen]) >= min_anteil
        ok &= rand <= max_rand
        guete = guete - rand_gewicht * rand
    ok &= sch >= np.quantile(sch, schaerfe_quantil)
    if ok.sum() < n:
        ok = np.ones(len(t), bool)
    grenzen = np.linspace(weg[0], weg[-1] + 1e-9, n + 1)
    wahl = []
    for i in range(n):
        im = np.flatnonzero(ok & (weg >= grenzen[i]) & (weg < grenzen[i + 1]))
        if not len(im):
            continue
        wahl.append(int(im[np.argmax(guete[im])]))
    # leere Abschnitte: mit den besten übrigen auffüllen, mit Abstand im Weg
    for teiler in (3, 6, 12, 1e9):              # Mindestabstand im Weg schrittweise lockern
        rest = [j for j in np.argsort(-guete) if ok[j] and j not in wahl]
        for j in rest:
            if len(wahl) >= n:
                break
            if all(abs(weg[j] - weg[w]) > (weg[-1] - weg[0]) / (teiler * n) for w in wahl):
                wahl.append(int(j))
        if len(wahl) >= n:
            break
    return sorted(wahl)


def holen(pfad, zeiten, ziel=None, qualitaet=2):
    """Bilder zu den Zeitpunkten in voller Größe (JPEG). Rückgabe: Liste der Dateien."""
    ziel = Path(ziel or CACHE / "video" / Path(pfad).stem)
    ziel.mkdir(parents=True, exist_ok=True)
    dateien = []
    for t in zeiten:
        datei = ziel / f"{Path(pfad).stem}_{t:07.3f}.jpg"
        if not datei.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(pfad), "-frames:v", "1",
                            "-q:v", str(qualitaet), str(datei)], check=True)
        dateien.append(datei)
    return dateien

"""Bilder auswählen: alle Fotos, dazu Videobilder nach Abstand und Blickwinkel, unscharfe aussortiert.

- Schärfe je Videobild: Laplace-Varianz in 320 px Breite (ffmpeg dekodiert einmal das ganze Video in Graustufen).
- Auswahl: weitester Punkt im Raum der Kameralagen (Abstand der Zentren relativ zum Aufnahmeabstand plus Winkel der
  Blickrichtungen), ausgehend von den Fotos; danach je gewähltem Bild das schärfste der Nachbarn (±2 Bilder), wenn
  es kaum anders liegt. Bilder unter 40 % der mittleren Schärfe ihrer Umgebung fallen weg, ebenso Bilder, in denen
  der Fokuspunkt (Objekt) nicht im Bild liegt.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def schaerfe(grau: np.ndarray) -> float:
    return float(cv2.Laplacian(grau, cv2.CV_32F).var())


def video_schaerfe(video: Path, breite: int = 320) -> np.ndarray:
    """Laplace-Varianz je Videobild (Reihenfolge der Bilder im Video)."""
    probe = subprocess.run([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"scale={breite}:-2,format=gray",
                            "-f", "rawvideo", "-pix_fmt", "gray", "-frames:v", "1", "-"], capture_output=True)
    if probe.returncode != 0 or not probe.stdout:
        raise RuntimeError(f"ffmpeg kann {video.name} nicht lesen: {probe.stderr.decode(errors='replace')[-300:]}")
    n1 = len(probe.stdout)
    hoehe = n1 // breite
    # passthrough: die Zeitstempel im Video sind die von ARKit (nicht streng gleichmäßig); kein Bild doppelt oder weg
    proc = subprocess.Popen([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"scale={breite}:-2,format=gray",
                             "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                            stdout=subprocess.PIPE)
    werte = []
    assert proc.stdout is not None
    while True:
        roh = proc.stdout.read(n1)
        if len(roh) < n1:
            break
        werte.append(schaerfe(np.frombuffer(roh, np.uint8).reshape(hoehe, breite)))
    proc.wait()
    return np.asarray(werte, float)


def video_bilder(video: Path, indizes: list[int], ziel: Path, namen: list[str]) -> dict[int, Path]:
    """Videobilder (Index im Video) in voller Größe als JPEG nach ``ziel/<name>.jpg``."""
    ziel.mkdir(parents=True, exist_ok=True)
    out: dict[int, Path] = {}
    if not indizes:
        return out
    tmp = ziel / ".roh"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    ordnung = sorted(range(len(indizes)), key=lambda i: indizes[i])
    auswahl = "+".join(f"eq(n\\,{indizes[i]})" for i in ordnung)
    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"select='{auswahl}'", "-fps_mode",
                        "passthrough", "-q:v", "2", str(tmp / "%05d.jpg")], capture_output=True)
    if r.returncode != 0:
        r = subprocess.run([FFMPEG, "-v", "error", "-i", str(video), "-vf", f"select='{auswahl}'", "-vsync", "0",
                            "-q:v", "2", str(tmp / "%05d.jpg")], capture_output=True)
    dateien = sorted(tmp.glob("*.jpg"))
    for j, i in enumerate(ordnung):
        if j < len(dateien):
            d = ziel / f"{namen[i]}.jpg"
            dateien[j].replace(d)
            out[indizes[i]] = d
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def sichtbar(K: np.ndarray, R: np.ndarray, t: np.ndarray, w: int, h: int, X: np.ndarray, rand: float = 0.05) -> bool:
    Xc = R @ X + t
    if Xc[2] <= 1:
        return False
    u = K[0, 0] * Xc[0] / Xc[2] + K[0, 2]
    v = K[1, 1] * Xc[1] / Xc[2] + K[1, 2]
    return rand * w <= u <= (1 - rand) * w and rand * h <= v <= (1 - rand) * h


def waehlen(zentren: np.ndarray, richtungen: np.ndarray, ist_foto: np.ndarray, anzahl_video: int,
            schaerfe_video: np.ndarray | None, abstand_mm: float, gueltig: np.ndarray | None = None,
            min_winkel_grad: float = 4.0) -> list[int]:
    """Indizes (in die Gesamtliste) der gewählten Bilder: alle Fotos, dazu bis zu ``anzahl_video`` Videobilder.

    ``zentren``, ``richtungen``: je Bild Kamerazentrum (mm) und Blickrichtung; ``schaerfe_video``: je Bild (Fotos
    beliebig); ``abstand_mm``: typischer Aufnahmeabstand (Maßstab für den Ortsabstand)."""
    n = len(zentren)
    gueltig = np.ones(n, bool) if gueltig is None else gueltig.copy()
    video = np.flatnonzero(~ist_foto & gueltig)
    if schaerfe_video is not None and len(video):
        s = schaerfe_video[video]
        # relativ zur Umgebung: lokale Mittel über 15 Bilder
        k = 15
        pad = np.pad(s, (k // 2, k // 2), mode="edge")
        lokal = np.convolve(pad, np.ones(k) / k, mode="valid")[:len(s)]
        scharf = s >= 0.4 * lokal
        gueltig[video[~scharf]] = False
        video = video[scharf]
    gewaehlt = list(np.flatnonzero(ist_foto & gueltig))
    if anzahl_video <= 0 or not len(video):
        return gewaehlt
    d = richtungen / np.maximum(np.linalg.norm(richtungen, axis=1, keepdims=True), 1e-12)
    skala = max(0.15 * abstand_mm, 1.0)

    def abstand(i: int, j: np.ndarray) -> np.ndarray:
        ort = np.linalg.norm(zentren[j] - zentren[i], axis=1) / skala
        winkel = np.degrees(np.arccos(np.clip(d[j] @ d[i], -1, 1))) / 15.0
        return ort + winkel

    if gewaehlt:
        mind = np.min([abstand(i, video) for i in gewaehlt], axis=0)
    else:
        start = video[int(np.argmax(schaerfe_video[video]))] if schaerfe_video is not None else video[0]
        gewaehlt.append(int(start))
        mind = abstand(int(start), video)
    zahl_video = sum(1 for g in gewaehlt if not ist_foto[g])
    while zahl_video < anzahl_video:
        j = int(np.argmax(mind))
        if mind[j] < min_winkel_grad / 15.0:
            break
        i = int(video[j])
        # schärferen Nachbarn nehmen, wenn er kaum anders liegt
        if schaerfe_video is not None:
            nachbarn = [k for k in range(i - 2, i + 3) if 0 <= k < n and k in set(video.tolist())]
            besser = max(nachbarn, key=lambda k: schaerfe_video[k])
            if besser != i and float(abstand(i, np.array([besser]))[0]) < 0.3:
                i = besser
        gewaehlt.append(i)
        zahl_video += 1
        mind = np.minimum(mind, abstand(i, video))
        mind[video == i] = -math.inf
    return sorted(set(int(g) for g in gewaehlt))

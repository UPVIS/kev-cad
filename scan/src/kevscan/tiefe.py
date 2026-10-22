"""Tiefe je Bild mit Prompt Depth Anything: Farbbild plus LiDAR-Tiefe (256 × 192) -> metrische Tiefe in Bildauflösung.

- Gerät: MPS (Apple Silicon), sonst CPU. ``PYTORCH_ENABLE_MPS_FALLBACK=1`` lässt einzelne fehlende MPS-Operationen
  auf der CPU laufen.
- Gewichte: beim ersten Gebrauch von Hugging Face in ``~/Library/Caches/de.upvis.kevcad/promptda`` (oder
  ``KEVSCAN_GEWICHTE``), danach ohne Netz. Large (vitl, 1,4 GB) ist Standard, Small (vits, 100 MB) für die schnelle
  Vorschau.
- Prompt: LiDAR in Metern; Pixel ohne Messung (Konfidenz 0 oder Tiefe 0) werden vorher mit dem nächsten gemessenen
  Wert gefüllt, weil PromptDA den Prompt über Minimum und Maximum normiert. Im Ergebnis sind sie maskiert: Tiefe 0,
  Konfidenz 0.
- Bildgröße: lange Kante 1008 px, beide Kanten Vielfache von 14 (wie das Original, ``load_image``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

KONF_GEWICHT = np.array([0.0, 0.5, 1.0], np.float32)  # ARConfidenceLevel low, medium, high


def cache_ordner() -> Path:
    env = os.environ.get("KEVSCAN_GEWICHTE")
    return Path(env).expanduser() if env else Path.home() / "Library" / "Caches" / "de.upvis.kevcad" / "promptda"


def gewichte(modell: str = "large", laden: bool = True) -> Path | None:
    """Pfad zu model.ckpt (aus dem Zwischenspeicher; mit ``laden`` beim ersten Mal herunterladen)."""
    from huggingface_hub import hf_hub_download

    from kevscan.promptda import MODELLE

    _, repo = MODELLE[modell]
    try:
        return Path(hf_hub_download(repo, "model.ckpt", cache_dir=str(cache_ordner()), local_files_only=True))
    except Exception:  # noqa: BLE001 - noch nicht im Zwischenspeicher
        if not laden:
            return None
    return Path(hf_hub_download(repo, "model.ckpt", cache_dir=str(cache_ordner())))


def geraet_waehlen(wunsch: str | None = None) -> str:
    import torch

    if wunsch:
        return wunsch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def vielfaches(x: float, m: int = 14) -> int:
    return max(m, int(x // m * m))


def arbeitsgroesse(w: int, h: int, kante: int = 1008) -> tuple[int, int]:
    kante = kante // 14 * 14
    s = min(1.0, kante / max(w, h))
    return vielfaches(w * s), vielfaches(h * s)


def prompt_fuellen(tiefe_mm: np.ndarray, konf: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Pixel ohne Messung mit dem nächsten gemessenen Wert füllen. Rückgabe (gefüllt in mm, gültig)."""
    from scipy import ndimage

    gueltig = tiefe_mm > 0
    if konf is not None:
        gueltig &= konf > 0
    if not gueltig.any():
        return tiefe_mm, gueltig
    if gueltig.all():
        return tiefe_mm, gueltig
    _, (iy, ix) = ndimage.distance_transform_edt(~gueltig, return_indices=True)
    return tiefe_mm[iy, ix], gueltig


class Tiefenschaetzer:
    """PromptDA einmal laden, dann je Bild ``schaetze``. ``modell``: "large" | "small"."""

    def __init__(self, modell: str = "large", geraet: str | None = None, kante: int = 1008,
                 angleichen: bool = True) -> None:
        import torch

        from kevscan.promptda import MODELLE, PromptDA

        t0 = time.perf_counter()
        self.modell = modell
        self.kante = kante
        self.angleichen = angleichen
        self.faktor = 1.0
        encoder, _ = MODELLE[modell]
        pfad = gewichte(modell)
        self.geraet = geraet_waehlen(geraet)
        netz = PromptDA.aus_datei(pfad, encoder)
        try:
            self.netz = netz.to(self.geraet)
        except RuntimeError:  # MPS nicht nutzbar: CPU
            self.geraet = "cpu"
            self.netz = netz.to("cpu")
        self.torch = torch
        self.ladezeit_s = time.perf_counter() - t0

    def schaetze(self, bild_bgr: np.ndarray, lidar_mm: np.ndarray, konf: np.ndarray | None
                 ) -> tuple[np.ndarray, np.ndarray]:
        """Tiefe (mm, float32) und Konfidenz (0…1) in Arbeitsgröße (``arbeitsgroesse``). Konfidenz der LiDAR-Messung
        nächstgelegen hochgerechnet; ohne Messung 0 und Tiefe 0."""
        torch = self.torch
        h0, w0 = bild_bgr.shape[:2]
        w, h = arbeitsgroesse(w0, h0, self.kante)
        rgb = cv2.cvtColor(cv2.resize(bild_bgr, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        gefuellt, gueltig = prompt_fuellen(lidar_mm.astype(np.float32), konf)
        if not gueltig.any():
            return np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
        x = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1)[None].to(self.geraet)
        p = torch.from_numpy(gefuellt / 1000.0)[None, None].float().to(self.geraet)
        try:
            y = self.netz.predict(x, p)
        except RuntimeError:
            if self.geraet == "cpu":
                raise
            self.geraet = "cpu"  # Rückfall, etwa bei zu wenig Speicher auf der GPU
            self.netz = self.netz.to("cpu")
            y = self.netz.predict(x.cpu(), p.cpu())
        tiefe = y[0, 0].float().cpu().numpy() * 1000.0
        if konf is None:
            konf = np.where(lidar_mm > 0, 2, 0).astype(np.uint8)
        k = np.where(gueltig, np.clip(konf, 0, 2), 0).astype(np.uint8)
        self.faktor = 1.0
        if self.angleichen:
            self.faktor = massstab_an_lidar(tiefe, lidar_mm, k)
            tiefe = tiefe * self.faktor
        k_gross = KONF_GEWICHT[cv2.resize(k, (w, h), interpolation=cv2.INTER_NEAREST)]
        tiefe = np.where(k_gross > 0, tiefe, 0.0).astype(np.float32)
        return tiefe, k_gross.astype(np.float32)


def massstab_an_lidar(tiefe_mm: np.ndarray, lidar_mm: np.ndarray, konf: np.ndarray, grenze: float = 0.05) -> float:
    """Maßstab der vorhergesagten Tiefe gegen die LiDAR-Messung (Median der Verhältnisse an Pixeln hoher Konfidenz
    abseits von Tiefensprüngen, vorhergesagte Tiefe flächengemittelt auf LiDAR-Auflösung). Gekappt auf ±5 %; ohne
    genug Punkte 1. PromptDA lag an der synthetischen Probe 1,5 % zu weit (Large), die Form übernimmt es trotzdem."""
    h, w = lidar_mm.shape
    klein = cv2.resize(tiefe_mm, (w, h), interpolation=cv2.INTER_AREA)
    gx = cv2.Sobel(lidar_mm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lidar_mm, cv2.CV_32F, 0, 1, ksize=3)
    glatt = np.hypot(gx, gy) / 8.0 < 0.01 * np.maximum(lidar_mm, 1.0)
    ok = (konf >= 2) & (lidar_mm > 0) & (klein > 0) & glatt
    if ok.sum() < 200:
        return 1.0
    f = float(np.median(lidar_mm[ok] / klein[ok]))
    return float(min(1 + grenze, max(1 - grenze, f)))


def lidar_hochgerechnet(lidar_mm: np.ndarray, konf: np.ndarray | None, w: int, h: int
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Ohne PromptDA (Vergleich, Tests): LiDAR-Tiefe nächstgelegen auf w × h, Konfidenz wie oben."""
    k = np.where(lidar_mm > 0, 2 if konf is None else konf, 0).astype(np.uint8)
    t = cv2.resize(lidar_mm.astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST)
    kg = KONF_GEWICHT[cv2.resize(np.clip(k, 0, 2), (w, h), interpolation=cv2.INTER_NEAREST)]
    return np.where(kg > 0, t, 0.0).astype(np.float32), kg.astype(np.float32)

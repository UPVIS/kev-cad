"""Rendering „Foto“ mit Blender Cycles im Hintergrund (Phase 7, PLAN-PHASE7-RENDERINGS.md R1, R10).

Der Kernel schreibt die sichtbaren Teile (Netze aus PART_UPSERT, Lage aus der App) und die Szene nach
``szene.json`` in einen Arbeitsordner, startet Blender mit ``nice`` und Zeitlimit und liest den Fortschritt aus der
Ausgabe von Cycles („Sample n/m“). Das Skript für Blender liegt daneben (``blender_skript.py``). Nur ein Lauf zur Zeit
(16 GB, ein Cycles-Lauf belegt um 5 GB); der Arbeitsordner wird nach dem Lauf gelöscht.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.protocol import unpack_part
from kevcad_kernel.render.materialien import schluessel

SKRIPT = Path(__file__).resolve().parent / "blender_skript.py"
KANDIDATEN = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "~/Applications/Blender.app/Contents/MacOS/Blender",
)
_SAMPLE = re.compile(r"Sample (\d+)/(\d+)")
_SPEICHER = re.compile(r"free percentage:\s*(\d+)%")


def blender_pfad() -> Path | None:
    """Blender aus ``KEVCAD_BLENDER`` oder den üblichen Orten; None, wenn keins da ist."""
    env = os.environ.get("KEVCAD_BLENDER")
    for kand in ([env] if env else []) + list(KANDIDATEN):
        p = Path(kand).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def samples_fuer(breite: int, hoehe: int, wunsch: int | None = None) -> int:
    """Proben je Pixel: mit Rauschgrenze und Entrauschen reichen 128; große Bilder bekommen etwas weniger."""
    if wunsch:
        return max(8, min(int(wunsch), 4096))
    mpx = breite * hoehe / 1e6
    return 160 if mpx <= 2.5 else (128 if mpx <= 9 else 96)


def zeitlimit_s(breite: int, hoehe: int, samples: int, dreiecke: int) -> float:
    """Großzügiges Zeitlimit: Start und Aufbau plus etwa 1,5 s je Megapixel und 16 Proben, dazu die Netze."""
    return 120.0 + breite * hoehe / 1e6 * samples / 16 * 1.5 + dreiecke / 50_000 * 10


def freier_speicher_prozent() -> int | None:
    """„System-wide memory free percentage“ aus ``memory_pressure`` (macOS) oder None."""
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = _SPEICHER.search(out)
    return int(m.group(1)) if m else None


def _matrix(m: Any) -> np.ndarray | None:
    if not isinstance(m, list) or len(m) != 16:
        return None
    return np.asarray(m, dtype=np.float64).reshape(4, 4).T  # spaltenweise → Zeilenmatrix


def szene_schreiben(ordner: Path, *, teile: list[dict[str, Any]], kamera: dict[str, Any], szene: dict[str, Any],
                    breite: int, hoehe: int, samples: int, ausgabe: Path) -> tuple[Path, dict[str, Any]]:
    """Netze (npz) und ``szene.json`` schreiben. ``teile``: je ``name``, ``header``, ``payload``, ``matrix`` (16 Zahlen
    spaltenweise oder None) und ``pbr``. Gibt den Pfad der JSON und Kennzahlen zurück."""
    ordner.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    eintraege: list[dict[str, Any]] = []
    materialien: dict[str, dict[str, Any]] = {}
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    dreiecke = 0
    for i, t in enumerate(teile):
        arr = unpack_part(t["header"], t["payload"])
        pos = np.asarray(arr["positions"], dtype=np.float32).reshape(-1, 3)
        tri = np.asarray(arr["triangles"], dtype=np.uint32).reshape(-1, 3)
        if len(tri) == 0:
            continue
        arrays[f"p{i}"] = pos
        arrays[f"n{i}"] = np.asarray(arr["normals"], dtype=np.float32).reshape(-1, 3)
        arrays[f"t{i}"] = tri
        m = _matrix(t.get("matrix"))
        welt = pos.astype(np.float64)
        if m is not None:
            welt = welt @ m[:3, :3].T + m[:3, 3]
        lo = np.minimum(lo, welt.min(axis=0))
        hi = np.maximum(hi, welt.max(axis=0))
        key = schluessel(t["pbr"])
        materialien[key] = {k: v for k, v in t["pbr"].items() if k not in ("material", "quelle", "kulisse", "name")}
        eintraege.append({"name": t["name"], "netz": i, "matrix": t.get("matrix"), "material": key})
        dreiecke += len(tri)
    if not eintraege:
        raise ValueError("Keine sichtbaren Teile zum Rendern")
    netze = ordner / "netze.npz"
    np.savez(netze, **arrays)
    daten = {"breite": breite, "hoehe": hoehe, "samples": samples, "rauschgrenze": 0.02, "ausgabe": str(ausgabe),
             "netze": str(netze), "szene": szene, "kamera": kamera,
             "grenzen": {"min": [float(v) for v in lo], "max": [float(v) for v in hi]},
             "teile": eintraege, "materialien": materialien}
    pfad = ordner / "szene.json"
    pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    return pfad, {"teile": len(eintraege), "dreiecke": dreiecke, "materialien": len(materialien)}


class BlenderLauf:
    """Ein Blender-Prozess mit Fortschritt, Abbruch und Zeitlimit. ``fortschritt(anteil, text)`` wird höchstens alle
    0,4 s gerufen (aus dem Lesefaden)."""

    def __init__(self, szene_json: Path, *, zeitlimit: float, fortschritt: Callable[[float, str], None] | None = None,
                 blender: Path | None = None, prioritaet: int = 10) -> None:
        self.szene_json = szene_json
        self.zeitlimit = zeitlimit
        self.fortschritt = fortschritt
        self.blender = blender or blender_pfad()
        self.prioritaet = prioritaet
        self.proc: subprocess.Popen[str] | None = None
        self.abgebrochen: str | None = None
        self.zeilen: list[str] = []
        self.meldungen: dict[str, str] = {}
        self._letzte = 0.0

    def abbrechen(self, grund: str = "abgebrochen") -> None:
        self.abgebrochen = grund
        p = self.proc
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    def _melde(self, anteil: float, text: str, sofort: bool = False) -> None:
        jetzt = time.monotonic()
        if self.fortschritt is not None and (sofort or jetzt - self._letzte >= 0.4):
            self._letzte = jetzt
            try:
                self.fortschritt(anteil, text)
            except Exception:  # noqa: BLE001 - Fortschritt darf den Lauf nicht stören
                pass

    def laufen(self) -> dict[str, Any]:
        """Startet Blender und wartet. {"ok", "ms", "samples", "geraet", "fehler"?, "log" (letzte Zeilen)}"""
        if self.blender is None:
            return {"ok": False, "fehler": "Blender fehlt (erwartet unter /Applications/Blender.app oder in "
                                           "KEVCAD_BLENDER)"}
        cmd = ["nice", "-n", str(self.prioritaet), str(self.blender), "-b", "--factory-startup", "-noaudio",
               "--python", str(SKRIPT), "--", str(self.szene_json)]
        t0 = time.monotonic()
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)  # Blender bringt sein eigenes Python mit
        env.pop("PYTHONHOME", None)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     env=env, start_new_session=True)
        wache = threading.Timer(self.zeitlimit, lambda: self.abbrechen(f"Zeitlimit {self.zeitlimit:.0f} s"))
        wache.daemon = True
        wache.start()
        self._melde(0.02, "Blender startet", sofort=True)
        try:
            assert self.proc.stdout is not None
            for zeile in self.proc.stdout:
                zeile = zeile.rstrip()
                self.zeilen.append(zeile)
                if len(self.zeilen) > 400:
                    del self.zeilen[:200]
                if zeile.startswith("KEVCAD "):
                    teil = zeile[7:]
                    self.meldungen[teil.split(" ", 1)[0]] = teil
                    if teil.startswith("rendert"):
                        self._melde(0.08, "Cycles rendert", sofort=True)
                    continue
                m = _SAMPLE.search(zeile)
                if m:
                    n, g = int(m.group(1)), max(1, int(m.group(2)))
                    self._melde(0.08 + 0.88 * n / g, f"Probe {n} von {g}")
                elif "Denoising" in zeile or "Entrausch" in zeile:
                    self._melde(0.97, "entrauscht")
            rc = self.proc.wait()
        finally:
            wache.cancel()
        ms = int((time.monotonic() - t0) * 1000)
        out: dict[str, Any] = {"ok": rc == 0 and "fertig" in self.meldungen and not self.abgebrochen, "ms": ms,
                               "log": self.zeilen[-12:]}
        r = self.meldungen.get("rendert", "")
        m = re.search(r"samples (\d+) auf (.+)$", r)
        if m:
            out["samples"] = int(m.group(1))
            out["geraet"] = m.group(2)
        if self.abgebrochen:
            out["fehler"] = self.abgebrochen
        elif not out["ok"]:
            fehler = [z for z in self.zeilen if "Error" in z or "Traceback" in z or "error" in z.lower()]
            out["fehler"] = (fehler[-1] if fehler else f"Blender endete mit {rc}")[:400]
        return out


def arbeitsordner() -> Path:
    return Path(tempfile.mkdtemp(prefix="kevcad-render-"))


def aufraeumen(ordner: Path) -> None:
    shutil.rmtree(ordner, ignore_errors=True)

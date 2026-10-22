"""kevcad-capture (Apple Object Capture, tools/capture) als Unterprozess mit Fortschritt.

Der Kernel startet ``kevcad-capture lauf <video> --aus <referenz>/capture …`` und liest stdout zeilenweise (JSON, siehe
tools/capture/README.md, „Fortschritt“). Gewichtung für einen Gesamtbalken: Bilder 5 %, Rekonstruktion 93 %,
Nachbearbeitung 2 %. Zwischenstände von Object Capture löscht das Programm selbst.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kevcad_kernel.referenz.ablage import ReferenzFehler, capture_programm

GEWICHT = {"frames": (0.0, 0.05), "reconstruction": (0.05, 0.93), "post": (0.98, 0.02)}
STUFEN = {
    "pre_processing": "Vorbereitung", "image_alignment": "Bilder ausrichten",
    "point_cloud_generation": "Punktwolke", "mesh_generation": "Netz wird erzeugt",
    "texture_mapping": "Texturen", "optimization": "Optimierung",
}
EINSTELLUNGEN = {
    "schnell": {"bilder": 60, "kante": 1920, "detail": "reduced"},
    "genau": {"bilder": 120, "kante": 2880, "detail": "medium"},
}
MASZ_NAMEN = ("laenge", "breite", "hoehe", "grund_laenge", "grund_breite")
# Anteil der Dreiecke, die nach der Nachbearbeitung zum Gegenstand gehören; darunter hat Object Capture ihn nicht
# sauber freigestellt (Scarlett: gute Läufe 48 %, Rollwagen 41 %, ein misslungener 5 %)
MIN_OBJEKT_ANTEIL = 0.15


VERSUCHE = 3
MIN_AUSGERICHTET = 0.6  # Anteil der Bilder, die Object Capture ausrichtet (gute Läufe: 70 bis 100 %)


def zweifel(bericht: dict[str, Any] | None) -> str | None:
    """Grund, das Netz nicht zu trauen (dann rechnet der Kernel noch einmal), oder None."""
    anteil = objekt_anteil(bericht)
    if anteil is not None and anteil < MIN_OBJEKT_ANTEIL:
        return f"Object Capture hat den Gegenstand kaum freigestellt ({anteil * 100:.0f} % der Dreiecke)"
    rek = (bericht or {}).get("rekonstruktion") or {}
    try:
        bilder, posen = int(rek.get("images") or 0), int(rek.get("posed") or 0)
    except (TypeError, ValueError):
        return None
    if bilder and posen / bilder < MIN_AUSGERICHTET:
        return f"Object Capture hat nur {posen} von {bilder} Bildern ausgerichtet"
    return None


def objekt_anteil(bericht: dict[str, Any] | None) -> float | None:
    o = (bericht or {}).get("objekt") or {}
    try:
        gesamt = float(o.get("dreiecke_gesamt") or 0)
        return float(o.get("dreiecke") or 0) / gesamt if gesamt > 0 else None
    except (TypeError, ValueError):
        return None


def befehl(video: str, aus: Path, *, einstellung: str = "schnell", masz: dict[str, float] | None = None,
           auflage: bool = False, von: float | None = None, bis: float | None = None,
           bilder: int | None = None, kante: int | None = None, programm: Path | None = None) -> list[str]:
    """Befehlszeile für ``kevcad-capture lauf``. Bilder höchstens 150, lange Kante höchstens 2880."""
    prog = programm or capture_programm()
    if prog is None:
        raise ReferenzFehler("kevcad-capture fehlt: im Repo `swift build -c release --package-path tools/capture` "
                             "bzw. ./build.sh ausführen (das installierte Kev CAD bringt es unter install/bin mit).")
    e = dict(EINSTELLUNGEN.get(einstellung) or EINSTELLUNGEN["schnell"])
    if bilder:
        e["bilder"] = int(bilder)
    if kante:
        e["kante"] = int(kante)
    e["bilder"] = max(10, min(int(e["bilder"]), 150))
    e["kante"] = max(640, min(int(e["kante"]), 2880))
    cmd = [str(prog), "lauf", str(video), "--aus", str(aus), "--bilder", str(e["bilder"]), "--kante", str(e["kante"]),
           "--detail", str(e["detail"]), "--leise"]
    for name, mm in (masz or {}).items():
        key = str(name).lower().replace("ä", "ae").replace("ö", "oe")
        if key not in MASZ_NAMEN:
            raise ReferenzFehler(f"Maß {name!r} unbekannt (erlaubt: {', '.join(MASZ_NAMEN)})")
        if not (isinstance(mm, (int, float)) and mm > 0):
            raise ReferenzFehler(f"Maß {name}: positive Zahl in mm angeben")
        cmd += ["--masz", f"{key}={float(mm):g}"]
    if auflage:
        cmd.append("--auflage")
    if von is not None:
        cmd += ["--von", f"{float(von):g}"]
    if bis is not None:
        cmd += ["--bis", f"{float(bis):g}"]
    return cmd


def gesamt_anteil(ereignis: dict[str, Any]) -> float | None:
    """Gesamtfortschritt 0…1 aus einem ``progress``-Ereignis."""
    phase = ereignis.get("phase")
    if phase not in GEWICHT:
        return None
    start, breite = GEWICHT[phase]
    try:
        f = float(ereignis.get("fraction") or 0)
    except (TypeError, ValueError):
        return None
    return round(start + breite * max(0.0, min(1.0, f)), 4)


def text_zu(ereignis: dict[str, Any], stufe: str | None) -> str | None:
    """Kurzer Text für die Statusleiste: „Rekonstruktion: Netz wird erzeugt“."""
    phase = ereignis.get("phase")
    if phase == "frames":
        return "Bilder auswählen"
    if phase == "post":
        return "Nachbearbeitung"
    if phase == "reconstruction":
        return "Rekonstruktion" + (f": {STUFEN.get(stufe, stufe)}" if stufe else "")
    return None


class CaptureLauf:
    """Ein laufendes kevcad-capture. ``melde(zustand)`` bekommt bei jedem Ereignis ein Wörterbuch mit ``fortschritt``
    (0…1), ``text``, ``ereignis``; am Ende ``fertig`` (ok, bericht oder fehler)."""

    def __init__(self, cmd: list[str], melde: Callable[[dict[str, Any]], None], log: Callable[[str], None] | None = None
                 ) -> None:
        self.cmd = cmd
        self.melde = melde
        self.log = log or (lambda s: None)
        self.proc: subprocess.Popen | None = None
        self.fertig = threading.Event()
        self.ergebnis: dict[str, Any] = {}
        self.dateien: dict[str, str] = {}
        self.stufe: str | None = None
        self.anteil = 0.0
        self.warnungen: list[str] = []
        self._stderr: list[str] = []
        self._t0 = time.monotonic()
        self.abgebrochen = False

    def start(self) -> None:
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._lies_stderr, name="kevcad-capture-err", daemon=True).start()
        threading.Thread(target=self._lies, name="kevcad-capture", daemon=True).start()

    def abbrechen(self) -> None:
        self.abgebrochen = True
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()

    def _lies_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for zeile in self.proc.stderr:
            self._stderr.append(zeile.rstrip())
            del self._stderr[:-40]

    def _lies(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        fehler = None
        bericht = None
        for zeile in self.proc.stdout:
            zeile = zeile.strip()
            if not zeile.startswith("{"):
                continue
            try:
                e = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            art = e.get("event")
            if art == "progress":
                a = gesamt_anteil(e)
                if a is not None:
                    self.anteil = max(self.anteil, a)
                if e.get("stage"):
                    self.stufe = str(e["stage"])
                self.melde({"fortschritt": self.anteil, "text": text_zu(e, self.stufe), "ereignis": e})
            elif art == "stage":
                self.stufe = str(e.get("stage") or "")
                self.melde({"fortschritt": self.anteil, "text": text_zu({"phase": "reconstruction"}, self.stufe),
                            "ereignis": e})
            elif art == "file":
                self.dateien[str(e.get("kind"))] = str(e.get("path"))
                self.melde({"fortschritt": self.anteil, "datei": e.get("kind"), "ereignis": e})
            elif art == "warning":
                self.warnungen.append(str(e.get("message")))
            elif art == "error":
                fehler = str(e.get("message") or "Fehler")
            elif art == "done":
                bericht = e.get("summary")
        code = self.proc.wait()
        dauer = round(time.monotonic() - self._t0, 1)
        if code == 0 and fehler is None and not self.abgebrochen:
            self.ergebnis = {"ok": True, "bericht": bericht or {}, "dateien": dict(self.dateien), "dauer_s": dauer,
                             "warnungen": list(self.warnungen)}
        else:
            msg = "abgebrochen" if self.abgebrochen else (fehler or f"kevcad-capture endete mit Code {code}")
            tail = "\n".join(self._stderr[-6:])
            self.ergebnis = {"ok": False, "fehler": msg, "stderr": tail, "dauer_s": dauer,
                             "warnungen": list(self.warnungen)}
        self.fertig.set()
        try:
            self.melde({"fortschritt": 1.0 if self.ergebnis.get("ok") else self.anteil, "fertig": self.ergebnis})
        except Exception as exc:  # noqa: BLE001
            self.log(f"[referenz] Abschlussmeldung von kevcad-capture: {exc!r}")

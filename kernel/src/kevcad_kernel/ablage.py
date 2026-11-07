"""Projektablage (PLAN-IPAD.md, I-7): wo neue Projekte liegen und wie Projekte in der iCloud ihre internen Daten lokal halten.

**Projektordner.** ``KEVCAD_PROJECTS_DIR`` geht vor (Testvarianten, abnahme.sh). Sonst entscheidet der Schalter
``projektablage.json`` im Datenordner der App (``~/Library/Application Support/de.upvis.kevcad/``):

- fehlt die Datei, gilt ``~/Documents/Kev CAD`` (Vorgabe, wie bisher);
- ``{"ort": "icloud"}`` heißt ``iCloud Drive/Kev CAD`` (``~/Library/Mobile Documents/com~apple~CloudDocs/Kev CAD``);
- ``{"ordner": "/pfad"}`` nimmt einen eigenen Ordner.

Dieselbe Datei liest die Mac-App (``Projektablage.swift``), so legen App und Agent neue Projekte am selben Ort an.

**Projekte in der iCloud.** Der Spike vom 07.11.2026 (PLAN-IPAD.md, Abschnitt 6) zeigt: iCloud Drive lädt jede Datei
einzeln hoch, ohne Rücksicht auf Zusammenhänge. Ein Git-Repo, das Laufprotokoll und die Versionsbilder (``.kevcad/``)
würden so halb übertragen, auf einem zweiten Mac unvollständig ankommen und bei „Mac-Speicher optimieren“ ausgelagert.
Ordner mit der Endung ``.nosync`` lässt iCloud aus (gemessen: ``isExcludedFromSync``), einen symbolischen Link überträgt es
als Link. Liegt ein Projekt in der iCloud, wird ``.kevcad`` deshalb ein Link auf ``.kevcad.nosync`` daneben: Der übrige
Kernel arbeitet unverändert mit ``<projekt>/.kevcad``, die Daten bleiben auf diesem Mac. Ein zweiter Mac bekommt nur den
Link; fehlt das Ziel, legt ``lokale_daten_sicherstellen`` es an.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: Teil jedes Pfads, der in der iCloud liegt (iCloud Drive und Ordner von Apps, am Mac und auf dem iPad).
ICLOUD_MARKE = "/Library/Mobile Documents/"
#: iCloud Drive am Mac.
ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
#: Ordner der Projekte in iCloud Drive (in der Dateien-App und im Finder „iCloud Drive › Kev CAD“).
ICLOUD_ORDNER = ICLOUD_DRIVE / "Kev CAD"
LOKAL_ORDNER = Path.home() / "Documents" / "Kev CAD"
SCHALTER = "projektablage.json"
DATEN = ".kevcad"
DATEN_LOKAL = ".kevcad.nosync"


def _datenordner_app() -> Path:
    return Path.home() / "Library" / "Application Support" / "de.upvis.kevcad"


def schalter_lesen(ordner: Path | None = None) -> dict:
    """Inhalt von ``projektablage.json``; leer, wenn die Datei fehlt oder kaputt ist (dann gilt die Vorgabe)."""
    datei = (ordner or _datenordner_app()) / SCHALTER
    try:
        daten = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def projects_dir(ordner_app: Path | None = None) -> Path:
    """Ordner für neue Projekte und bloße Projektnamen (siehe Kopf der Datei)."""
    eigen = os.environ.get("KEVCAD_PROJECTS_DIR")
    if eigen:
        return Path(eigen).expanduser()
    schalter = schalter_lesen(ordner_app)
    if isinstance(schalter.get("ordner"), str) and schalter["ordner"].strip():
        return Path(schalter["ordner"]).expanduser()
    if schalter.get("ort") == "icloud":
        return ICLOUD_ORDNER
    return LOKAL_ORDNER


def _belegt(p: Path) -> bool:
    """Gibt es den Ordner schon mit Inhalt (oder als Datei)? Ein leerer Ordner taugt noch für ein neues Projekt."""
    if not p.exists():
        return False
    if not p.is_dir():
        return True
    return any(c.name != ".DS_Store" for c in p.iterdir())


def eindeutig(ziel: Path) -> Path:
    """Ordner für ein neues Projekt ohne Kollision: „Halter“, sonst „Halter 2“, „Halter 3“ … (wie
    ``ProjectLocator.uniqueFolder`` in der App)."""
    if not _belegt(ziel):
        return ziel
    n = 2
    while _belegt(ziel.with_name(f"{ziel.name} {n}")):
        n += 1
    return ziel.with_name(f"{ziel.name} {n}")


def aufloesen(pfad: str, neu: bool = False) -> str:
    """Pfad aus PROJECT_OPEN und PROJECT_NEW. Ein bloßer Name (relativ, ohne ``~``) meint den Projektordner dieses Mac
    (``projects_dir``): So legt das iPad ein Projekt dort an, wo es auch die Mac-App anlegen würde, ohne den Ort zu kennen.
    Bei ``neu`` bekommt der Name eine Nummer, wenn es den Ordner schon gibt. Absolute Pfade und ``~`` bleiben, wie sie
    sind."""
    text = (pfad or "").strip()
    if not text or text.startswith(("/", "~")):
        return pfad
    ziel = projects_dir() / text
    return str(eindeutig(ziel) if neu else ziel)


def in_icloud(pfad: str | Path) -> bool:
    """Liegt der Pfad in der iCloud (iCloud Drive oder Ordner einer App)?"""
    return ICLOUD_MARKE in str(Path(pfad).expanduser()) + "/"


def lokale_daten_sicherstellen(projekt: str | Path) -> str | None:
    """Für Projekte in der iCloud: ``.kevcad`` als Link auf ``.kevcad.nosync`` (siehe Kopf). Rückgabe: Hinweis für die
    Warnungen des Projekts oder ``None``. Projekte außerhalb der iCloud bleiben unberührt."""
    p = Path(projekt).expanduser()
    if not in_icloud(p) or not p.is_dir():
        return None
    link, ziel = p / DATEN, p / DATEN_LOKAL
    try:
        if link.is_symlink():
            ziel.mkdir(exist_ok=True)  # zweiter Mac: Link kam über die iCloud, das Ziel nicht
            return None
        if link.is_dir():
            if ziel.exists():
                return (f"{DATEN} und {DATEN_LOKAL} liegen beide im Projekt; {DATEN} bleibt in der iCloud. "
                        f"Bitte eines davon entfernen.")
            link.rename(ziel)  # vorhandene Versionen und Protokolle ziehen mit um
        else:
            ziel.mkdir(exist_ok=True)
        link.symlink_to(DATEN_LOKAL, target_is_directory=True)
    except OSError as exc:
        return f"Interne Daten ließen sich nicht lokal halten ({exc}); sie liegen in der iCloud."
    return None


def pycache_ordner() -> Path:
    """Zwischenspeicher für übersetzte Hilfsdateien neben model.py, wenn das Projekt in der iCloud liegt (sonst lägen
    ``__pycache__``-Ordner in der iCloud, je Python-Fassung andere)."""
    return Path.home() / "Library" / "Caches" / "de.upvis.kevcad" / "pycache"

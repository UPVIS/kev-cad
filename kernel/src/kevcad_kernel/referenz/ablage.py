"""Ablage der Referenzen: Ordner je Referenz, ``referenz.json`` und die beiden Werkzeuge (kevcad-capture, fotomess).

Die Werkzeuge liegen neben dem Kernel: im Repo unter ``tools/capture/.build/release/kevcad-capture`` und
``fotomess/`` (eigene uv-Umgebung ``fotomess/.venv``), in der installierten Kopie unter ``<install>/bin/`` und
``<install>/fotomess/`` (build.sh). Umgebungsvariablen ``KEVCAD_CAPTURE`` (Programm) und ``KEVCAD_FOTOMESS`` (Ordner
mit ``.venv``) gehen vor.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

REFERENZEN = "referenzen"
META = "referenz.json"
CAPTURE = "capture"
MESSUNG = "messung"
FOTOS = "fotos"
FORMAT = "kevcad-referenz"

VIDEO_ENDUNGEN = (".mov", ".mp4", ".m4v", ".avi", ".mkv")
FOTO_ENDUNGEN = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff")


class ReferenzFehler(ValueError):
    """Fehler, den Agent oder Kevin beheben können (Meldung auf Deutsch)."""


def wurzel() -> Path:
    """Ordner über ``kernel/`` (Repo oder Installation)."""
    import kevcad_kernel

    return Path(kevcad_kernel.__file__).resolve().parents[3]


def capture_programm() -> Path | None:
    """kevcad-capture: Umgebung, Installation, Repo-Bau; None, wenn keins da ist."""
    env = os.environ.get("KEVCAD_CAPTURE")
    kandidaten = [Path(env)] if env else []
    w = wurzel()
    kandidaten += [w / "bin" / "kevcad-capture", w / "tools" / "capture" / ".build" / "release" / "kevcad-capture"]
    for k in kandidaten:
        if k.is_file() and os.access(k, os.X_OK):
            return k
    return None


def fotomess_ordner() -> Path | None:
    """Ordner von fotomess mit eigener Umgebung (``.venv/bin/python``); None, wenn keine da ist."""
    env = os.environ.get("KEVCAD_FOTOMESS")
    kandidaten = [Path(env)] if env else []
    kandidaten.append(wurzel() / "fotomess")
    for k in kandidaten:
        if (k / ".venv" / "bin" / "python").exists() and (k / "src" / "fotomess").is_dir():
            return k
    return None


def lesbar(pfad: str | Path, warten_s: float = 6.0) -> None:
    """Prüft, ob die Datei wirklich lesbar ist. macOS fragt beim ersten Zugriff auf Wechselmedien, den Ordner
    Downloads, Schreibtisch oder Dokumente, ob Kev CAD darf; bis Kevin antwortet, hängt jeder Lesezugriff (auch der
    von ffprobe, ffmpeg und Object Capture). Dann lieber gleich mit einer klaren Meldung abbrechen."""
    import threading

    ergebnis: dict[str, Any] = {}

    def lies() -> None:
        try:
            with open(pfad, "rb") as f:
                f.read(1)
            ergebnis["ok"] = True
        except OSError as exc:
            ergebnis["fehler"] = exc

    t = threading.Thread(target=lies, daemon=True)
    t.start()
    t.join(warten_s)
    if t.is_alive():
        raise ReferenzFehler(f"Kein Zugriff auf {Path(pfad).name}: macOS fragt gerade, ob Kev CAD auf diesen Ort "
                             "zugreifen darf (Wechselmedium, Downloads o. ä.). Bitte in der Meldung „Erlauben“ wählen "
                             "und noch einmal versuchen, oder die Datei vorher in den Projektordner legen.")
    if "fehler" in ergebnis:
        exc = ergebnis["fehler"]
        hinweis = " (macOS hat den Zugriff verweigert: Systemeinstellungen › Datenschutz & Sicherheit › Dateien und " \
                  "Ordner)" if isinstance(exc, PermissionError) else ""
        raise ReferenzFehler(f"{Path(pfad).name} ist nicht lesbar: {exc}{hinweis}")


def ist_video(pfad: str | Path) -> bool:
    return Path(pfad).suffix.lower() in VIDEO_ENDUNGEN


def ist_foto(pfad: str | Path) -> bool:
    return Path(pfad).suffix.lower() in FOTO_ENDUNGEN


def sicherer_name(text: str) -> str:
    """Ordnername einer Referenz: Buchstaben, Ziffern, Leerzeichen, ``-_.``; anderes wird zu ``-``."""
    text = unicodedata.normalize("NFC", str(text or "").strip())
    text = re.sub(r"[^\w .\-äöüÄÖÜß]", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:60] or "Referenz"


def ordner_aller(projekt: Path) -> Path:
    return Path(projekt) / REFERENZEN


def ordner(projekt: Path, name: str) -> Path:
    return ordner_aller(projekt) / name


def freier_name(projekt: Path, wunsch: str) -> str:
    basis = sicherer_name(wunsch)
    name, i = basis, 2
    while ordner(projekt, name).exists():
        name = f"{basis} {i}"
        i += 1
    return name


def lese_meta(projekt: Path, name: str) -> dict[str, Any] | None:
    datei = ordner(projekt, name) / META
    try:
        d = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict):
        return None
    d["name"] = name
    return d


def schreibe_meta(projekt: Path, name: str, meta: dict[str, Any]) -> None:
    d = ordner(projekt, name)
    d.mkdir(parents=True, exist_ok=True)
    daten = {"format": FORMAT, **{k: v for k, v in meta.items() if k != "name"}}
    tmp = d / f".{META}.tmp"
    tmp.write_text(json.dumps(daten, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(d / META)


def namen(projekt: Path) -> list[str]:
    basis = ordner_aller(projekt)
    if not basis.is_dir():
        return []
    return sorted(p.name for p in basis.iterdir() if p.is_dir() and (p / META).is_file())


def jetzt() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def finde(projekt: Path, name: str | None) -> str:
    """Name einer vorhandenen Referenz (auch ohne Groß- und Kleinschreibung); Fehler mit Vorschlägen."""
    alle = namen(projekt)
    if not name:
        if len(alle) == 1:
            return alle[0]
        raise ReferenzFehler("Welche Referenz? " + (f"Vorhanden: {', '.join(alle)}." if alle else
                                                    "Im Projekt gibt es noch keine (referenz_video oder referenz_fotos)."))
    if name in alle:
        return name
    tief = {a.lower(): a for a in alle}
    if str(name).lower() in tief:
        return tief[str(name).lower()]
    import difflib

    nah = difflib.get_close_matches(str(name), alle, n=3, cutoff=0.5)
    raise ReferenzFehler(f"Referenz {name!r} gibt es nicht" + (f"; meinten Sie {', '.join(nah)}?" if nah else
                                                                (f" (vorhanden: {', '.join(alle)})." if alle else ".")))

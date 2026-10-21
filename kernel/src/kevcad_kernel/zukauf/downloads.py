"""CAD-Dateien aus dem Download-Ordner übernehmen (PLAN-PHASE3-ZUKAUF.md, Schritt 3, halbautomatisch).

- ``kandidaten``: neue ``.step``/``.stp``/``.zip`` der letzten Minuten (unfertige Downloads ausgenommen), neueste zuerst.
- ``waehlen``: die passende Datei, bevorzugt mit Herstellernummer oder id im Namen.
- ``uebernehmen``: Datei in den Zukauf-Ordner kopieren; ZIPs werden sicher entpackt (nur STEP, keine Pfade nach außen,
  Größenbegrenzung), bei mehreren STEP gewinnt die mit der Nummer im Namen, sonst die größte.

Der Ordner ist ``~/Downloads`` (für Tests ``KEVCAD_DOWNLOADS_DIR``). Leicht, ohne build123d.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

ENDUNGEN = (".step", ".stp", ".zip")
STEP_ENDUNGEN = (".step", ".stp")
UNFERTIG = (".crdownload", ".download", ".part", ".partial", ".tmp")
STANDARD_MINUTEN = 30
MAX_ZIP_BYTES = 2_000_000_000
MAX_ZIP_DATEIEN = 5000
ANDERE_CAD = (".igs", ".iges", ".x_t", ".x_b", ".sat", ".stl", ".dwg", ".dxf", ".sldprt", ".prt", ".ipt", ".3mf",
              ".obj", ".glb", ".catpart", ".jt")


class DownloadFehler(ValueError):
    """Keine passende Datei oder unbrauchbares Archiv."""


def downloads_dir() -> Path:
    env = os.environ.get("KEVCAD_DOWNLOADS_DIR")
    return Path(env).expanduser() if env else Path.home() / "Downloads"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def kandidaten(ordner: Path | None = None, minuten: float = STANDARD_MINUTEN, *, jetzt: float | None = None,
               extra: list[str] | None = None) -> list[Path]:
    """CAD-Dateien im Ordner (nicht rekursiv), die in den letzten ``minuten`` geändert wurden, neueste zuerst; dazu
    ``extra`` (z. B. von der App gemeldete Downloads), soweit sie noch da sind."""
    ordner = ordner or downloads_dir()
    jetzt = jetzt or time.time()
    grenze = jetzt - minuten * 60
    out: dict[str, tuple[float, Path]] = {}
    try:
        entries = list(ordner.iterdir())
    except OSError:
        entries = []
    for p in entries + [Path(e) for e in (extra or [])]:
        try:
            if p.name.startswith(".") or not p.is_file():
                continue
            low = p.name.lower()
            if low.endswith(UNFERTIG) or not low.endswith(ENDUNGEN):
                continue
            st = p.stat()
        except OSError:
            continue
        if st.st_size <= 0 or st.st_mtime < grenze:
            continue
        out[str(p.resolve())] = (st.st_mtime, p)
    return [p for _, p in sorted(out.values(), key=lambda t: -t[0])]


def waehlen(dateien: list[Path], entry: dict[str, Any]) -> Path | None:
    """Datei mit Herstellernummer, GTIN oder id im Namen, sonst die neueste."""
    if not dateien:
        return None
    keys = [k for k in (_norm(entry.get("mpn")), _norm(entry.get("shop_nr")), _norm(entry.get("gtin")),
                        _norm(entry.get("id"))) if len(k) >= 3]
    for p in dateien:
        n = _norm(p.stem)
        if any(k in n for k in keys):
            return p
    return dateien[0]


def _sicher(name: str) -> bool:
    parts = Path(name.replace("\\", "/")).parts
    return bool(parts) and not name.startswith(("/", "\\")) and ".." not in parts and ":" not in parts[0]


def _zip_entpacken(archiv: Path, ziel: Path, entry: dict[str, Any]) -> tuple[Path, list[str]]:
    hinweise: list[str] = []
    try:
        zf = zipfile.ZipFile(archiv)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DownloadFehler(f"{archiv.name} ist kein lesbares ZIP-Archiv ({exc})") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_DATEIEN:
            raise DownloadFehler(f"{archiv.name} enthält {len(infos)} Dateien: zu viele für ein CAD-Archiv")
        if sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise DownloadFehler(f"{archiv.name} ist entpackt größer als 2 GB")
        steps = [i for i in infos if i.filename.lower().endswith(STEP_ENDUNGEN) and _sicher(i.filename)
                 and not Path(i.filename).name.startswith((".", "__MACOSX"))
                 and "__MACOSX" not in i.filename]
        if not steps:
            andere = sorted({Path(i.filename).suffix.lower() for i in infos
                             if Path(i.filename).suffix.lower() in ANDERE_CAD})
            raise DownloadFehler(f"{archiv.name} enthält keine STEP-Datei"
                                 + (f" (nur {', '.join(andere)}): im Portal das Format STEP wählen" if andere else ""))
        keys = [k for k in (_norm(entry.get("mpn")), _norm(entry.get("shop_nr"))) if len(k) >= 3]
        mit_nummer = [i for i in steps if any(k in _norm(Path(i.filename).stem) for k in keys)]
        pool = mit_nummer or steps
        best = max(pool, key=lambda i: i.file_size)
        if len(steps) > 1:
            hinweise.append(f"{archiv.name} enthält {len(steps)} STEP-Dateien; übernommen: {Path(best.filename).name}")
        ziel.mkdir(parents=True, exist_ok=True)
        out = ziel / _dateiname(Path(best.filename).name)
        tmp = out.with_name(f".{out.name}.tmp")
        with zf.open(best) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(tmp, out)
    return out, hinweise


def _dateiname(name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem if dot else name).strip("._") or "cad"
    return f"{stem}.{ext.lower()}" if dot else stem


def uebernehmen(pfad: Path, ziel: Path, entry: dict[str, Any]) -> tuple[Path, list[str]]:
    """STEP-Datei (oder STEP aus einem ZIP) nach ``ziel`` kopieren. Rückgabe (Pfad der STEP-Datei, Hinweise)."""
    pfad = Path(pfad).expanduser()
    if not pfad.is_file():
        raise DownloadFehler(f"Datei {pfad} gibt es nicht")
    low = pfad.name.lower()
    if low.endswith(".zip"):
        return _zip_entpacken(pfad, ziel, entry)
    if not low.endswith(STEP_ENDUNGEN):
        hint = " (anderes CAD-Format: im Portal STEP wählen)" if pfad.suffix.lower() in ANDERE_CAD else ""
        raise DownloadFehler(f"{pfad.name} ist keine STEP- oder ZIP-Datei{hint}")
    with open(pfad, "rb") as fh:
        kopf = fh.read(64)
    if b"ISO-10303-21" not in kopf:
        raise DownloadFehler(f"{pfad.name} ist keine STEP-Datei (Kopf ISO-10303-21 fehlt)")
    ziel.mkdir(parents=True, exist_ok=True)
    out = ziel / _dateiname(pfad.name)
    if out.resolve() != pfad.resolve():
        tmp = out.with_name(f".{out.name}.tmp")
        shutil.copyfile(pfad, tmp)
        os.replace(tmp, out)
    return out, []

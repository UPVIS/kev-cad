"""Platten mit der Kommandozeile von Bambu Studio fertig slicen (``.gcode.3mf`` für den Druck), mit Zwischenspeicher.

Aufruf (lokal geprüft mit 02.07.01.62 am 22.10.2026)::

    BambuStudio --debug 1 --slice 0 --min-save [--arrange 1] [--orient 1]
                [--load-settings "maschine.json;prozess.json"] [--load-filaments "f1.json;…"]
                --outputdir <tmp> --export-3mf <name>.gcode.3mf <eingaben …>

- ``--slice 0`` = alle Platten; ``--min-save`` lässt die Objekte weg (``SaveStrategy::SkipModel``). Eine solche Datei
  öffnet Bambu Studio direkt in der Vorschau mit gültigem Slice-Ergebnis (Plater.cpp: ``model.objects.empty()`` →
  ``load_gcode_files``, „using exported file“), „Platte drucken“ ist sofort aktiv.
- ``HOME`` zeigt auf einen eigenen Ordner im Zwischenspeicher, damit die CLI nichts in Kevins Bambu-Studio-Ordner
  schreibt.
- Ergebnis je Platte aus ``Metadata/slice_info.config`` (Zeit ``prediction`` in s, Gewicht ``weight`` in g, Filament).
  Die CLI lässt ``printer_model_id`` leer; wir tragen ``C11`` (P1P) nach, damit die Datei auch auf der SD-Karte als
  P1P-Druck gilt. Der G-Code und seine MD5 bleiben unverändert.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kevcad_kernel.drucker.profile import BAMBU_APP, MODELL_ID_P1P

CACHE = Path.home() / "Library/Caches/de.upvis.kevcad/drucker"
ZEITLIMIT_S = 900.0
# Die Systemplatte ist knapp: nur die letzten Stände und höchstens rund 400 MB behalten
CACHE_BEHALTEN = 6
CACHE_MAX_BYTES = 400 * 1024 * 1024
NICHT_AUFRAEUMEN = ("home", "quelle")


class SlicenFehler(Exception):
    pass


class Abgebrochen(SlicenFehler):
    pass


@dataclass
class Platte:
    nr: int
    zeit_s: int
    g: float
    m: float
    material: str | None
    md5: str | None = None


@dataclass
class SliceErgebnis:
    datei: Path
    platten: list[Platte]
    version: str | None
    ms: int
    aus_zwischenspeicher: bool = False
    hinweise: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        return {"datei": str(self.datei), "version": self.version, "ms": self.ms,
                "aus_zwischenspeicher": self.aus_zwischenspeicher, "hinweise": list(self.hinweise),
                "platten": [{"nr": p.nr, "zeit_s": p.zeit_s, "g": p.g, "m": p.m, "material": p.material}
                            for p in self.platten]}


def programm(app: Path = BAMBU_APP) -> Path:
    return Path(app) / "Contents/MacOS/BambuStudio"


def vorhanden(app: Path = BAMBU_APP) -> bool:
    return os.access(programm(app), os.X_OK)


def version(app: Path = BAMBU_APP) -> str | None:
    try:
        with (Path(app) / "Contents/Info.plist").open("rb") as fh:
            info = plistlib.load(fh)
        return str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "") or None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def _hash_datei(h: "hashlib._Hash", p: Path) -> None:
    h.update(p.name.encode())
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)


def schluessel(eingaben: list[Path], einstellungen: list[Path], filamente: list[Path], schalter: list[str],
               app_version: str | None) -> str:
    h = hashlib.sha256()
    h.update(f"v1|{app_version}|{' '.join(schalter)}".encode())
    for p in [*eingaben, *einstellungen, *filamente]:
        _hash_datei(h, p)
    return h.hexdigest()[:24]


def platten_lesen(datei: Path) -> list[Platte]:
    """Platten aus ``Metadata/slice_info.config`` einer ``.gcode.3mf``."""
    try:
        with zipfile.ZipFile(datei) as z:
            info = z.read("Metadata/slice_info.config")
            md5s = {}
            for n in z.namelist():
                if n.startswith("Metadata/plate_") and n.endswith(".gcode.md5"):
                    md5s[n] = z.read(n).decode("ascii", "replace").strip()
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SlicenFehler(f"Ergebnis von Bambu Studio unlesbar: {exc}") from None
    out = []
    for plate in ET.fromstring(info).iter("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.iter("metadata")}
        nr = int(meta.get("index") or len(out) + 1)
        fil = plate.find("filament")
        g = float(meta.get("weight") or 0) if (meta.get("weight") or "").strip() else 0.0
        m = 0.0
        material = None
        if fil is not None:
            try:
                m = float(fil.get("used_m") or 0)
                g = g or float(fil.get("used_g") or 0)
            except ValueError:
                pass
            material = fil.get("type")
        out.append(Platte(nr=nr, zeit_s=int(float(meta.get("prediction") or 0)), g=round(g, 2), m=round(m, 2),
                          material=material, md5=md5s.get(f"Metadata/plate_{nr}.gcode.md5")))
    if not out:
        raise SlicenFehler("Bambu Studio hat keine Platte gesliced")
    return out


def modell_id_nachtragen(datei: Path, modell_id: str = MODELL_ID_P1P) -> bool:
    """``printer_model_id`` in ``slice_info.config`` setzen, wenn leer. True, wenn die Datei geändert wurde."""
    with zipfile.ZipFile(datei) as z:
        info = z.read("Metadata/slice_info.config").decode("utf-8")
        if f'key="printer_model_id" value=""' not in info:
            return False
        eintraege = [(i, z.read(i.filename)) for i in z.infolist()]
    neu = info.replace('key="printer_model_id" value=""', f'key="printer_model_id" value="{modell_id}"')
    tmp = datei.with_name(datei.name + ".tmp")
    with zipfile.ZipFile(tmp, "w") as out:
        for i, daten in eintraege:
            if i.filename == "Metadata/slice_info.config":
                daten = neu.encode("utf-8")
            out.writestr(i, daten, compress_type=i.compress_type)
    tmp.replace(datei)
    return True


def _groesse(p: Path) -> int:
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def _aufraeumen(cache: Path) -> None:
    """Nur die neuesten ``CACHE_BEHALTEN`` Stände und zusammen höchstens ``CACHE_MAX_BYTES`` behalten."""
    try:
        ordner = sorted((p for p in cache.iterdir() if p.is_dir() and p.name not in NICHT_AUFRAEUMEN
                         and not p.name.startswith("slicen-")),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    summe = 0
    for i, p in enumerate(ordner):
        summe += _groesse(p)
        if i >= CACHE_BEHALTEN or (i > 0 and summe > CACHE_MAX_BYTES):
            shutil.rmtree(p, ignore_errors=True)


def slicen(eingaben: list[Path], name: str, *, einstellungen: list[Path] | None = None,
           filamente: list[Path] | None = None, anordnen: bool = False, ausrichten: bool = False,
           app: Path = BAMBU_APP, cache: Path = CACHE, zeitlimit_s: float = ZEITLIMIT_S,
           abbruch: threading.Event | None = None, log: Callable[[str], None] | None = None) -> SliceErgebnis:
    """Alle Platten der Eingaben slicen; Ergebnis aus dem Zwischenspeicher, wenn Eingaben und Profile gleich sind."""
    log = log or (lambda _t: None)
    t0 = time.monotonic()
    exe = programm(app)
    if not vorhanden(app):
        raise SlicenFehler(f"Bambu Studio fehlt ({app}); ohne Bambu Studio kann Kev CAD nicht fertig slicen")
    eingaben = [Path(e) for e in eingaben]
    einstellungen = [Path(e) for e in (einstellungen or [])]
    filamente = [Path(f) for f in (filamente or [])]
    for p in [*eingaben, *einstellungen, *filamente]:
        if not p.exists():
            raise SlicenFehler(f"Datei fehlt: {p.name}")
    schalter = ["--slice", "0", "--min-save"]
    if anordnen:
        schalter += ["--arrange", "1"]
    if ausrichten:
        schalter += ["--orient", "1"]
    av = version(app)
    key = schluessel(eingaben, einstellungen, filamente, schalter, av)
    ziel_ordner = cache / key
    ziel = ziel_ordner / f"{name}.gcode.3mf"
    meta = ziel_ordner / "ergebnis.json"
    if ziel.exists() and meta.exists():
        try:
            platten = platten_lesen(ziel)
            os.utime(ziel_ordner)
            return SliceErgebnis(datei=ziel, platten=platten, version=av, ms=int((time.monotonic() - t0) * 1000),
                                 aus_zwischenspeicher=True)
        except SlicenFehler:
            shutil.rmtree(ziel_ordner, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    home = cache / "home"
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slicen-", dir=cache) as tmp_s:
        tmp = Path(tmp_s)
        aus = f"{name}.gcode.3mf"
        cmd = [str(exe), "--debug", "1", *schalter]
        if einstellungen:
            cmd += ["--load-settings", ";".join(str(p) for p in einstellungen)]
        if filamente:
            cmd += ["--load-filaments", ";".join(str(p) for p in filamente)]
        cmd += ["--outputdir", str(tmp), "--export-3mf", aus, *[str(e) for e in eingaben]]
        env = {**os.environ, "HOME": str(home)}
        log(f"[drucker] Bambu Studio slict {len(eingaben)} Datei(en)")
        try:
            proc = subprocess.Popen(cmd, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors="replace", start_new_session=True)
        except OSError as exc:
            raise SlicenFehler(f"Bambu Studio startet nicht: {exc}") from None
        ende = time.monotonic() + zeitlimit_s
        while True:
            try:
                ausgabe, _ = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                if (abbruch is not None and abbruch.is_set()) or time.monotonic() > ende:
                    proc.kill()
                    proc.communicate()
                    if abbruch is not None and abbruch.is_set():
                        raise Abgebrochen("Slicen abgebrochen") from None
                    raise SlicenFehler(f"Bambu Studio brauchte länger als {zeitlimit_s:g} s") from None
        ergebnis_json = tmp / "result.json"
        rc_info: dict[str, Any] = {}
        if ergebnis_json.exists():
            try:
                rc_info = json.loads(ergebnis_json.read_text(encoding="utf-8"))
            except ValueError:
                rc_info = {}
        datei = tmp / aus
        if proc.returncode != 0 or not datei.exists():
            text = str(rc_info.get("error_string") or "").strip()
            letzte = [z for z in (ausgabe or "").splitlines() if z.strip() and "[trace]" not in z][-3:]
            grund = text if text and text != "Success." else " / ".join(letzte)
            raise SlicenFehler(f"Bambu Studio konnte nicht slicen (Ausgang {proc.returncode}): {grund or 'ohne Meldung'}")
        modell_id_nachtragen(datei)
        platten = platten_lesen(datei)
        hinweise = []
        for sp in rc_info.get("sliced_plates") or []:
            w = str(sp.get("warning_message") or "").strip()
            if w:
                hinweise.append(f"Platte {sp.get('id')}: {w}")
        ziel_ordner.mkdir(parents=True, exist_ok=True)
        shutil.move(str(datei), ziel)
        meta.write_text(json.dumps({"version": av, "schalter": schalter, "eingaben": [e.name for e in eingaben],
                                    "hinweise": hinweise, "zeit": time.time()}, ensure_ascii=False),
                        encoding="utf-8")
    _aufraeumen(cache)
    return SliceErgebnis(datei=ziel, platten=platten, version=av, ms=int((time.monotonic() - t0) * 1000),
                         hinweise=hinweise)


def hat_projekt_einstellungen(datei: Path) -> bool:
    """True, wenn eine 3MF Bambu-Projekteinstellungen für den P1P mitbringt (dann lädt der Kernel keine eigenen)."""
    if datei.suffix.lower() != ".3mf":
        return False
    try:
        with zipfile.ZipFile(datei) as z:
            daten = json.loads(z.read("Metadata/project_settings.config"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return False
    return "P1P" in str(daten.get("printer_model") or daten.get("printer_settings_id") or "")


def platten_md5(datei: Path, nr: int) -> str:
    """MD5 des G-Codes einer Platte (für ``project_file``, Weg B)."""
    with zipfile.ZipFile(datei) as z:
        try:
            return z.read(f"Metadata/plate_{nr}.gcode.md5").decode("ascii").strip()
        except KeyError:
            return hashlib.md5(z.read(f"Metadata/plate_{nr}.gcode")).hexdigest()  # noqa: S324

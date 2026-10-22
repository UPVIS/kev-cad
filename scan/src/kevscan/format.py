"""Einen Scan nach SCAN.md lesen: Ordner oder ZIP, Kopf, Videobilder mit Lage, Fotos mit Lage, Objektbox.

Ein ZIP wird sicher entpackt (keine Pfade außerhalb des Ziels, keine Verknüpfungen, höchstens 4 GB entpackt). Der
Kern ist mit Stray Scanner verträglich: ``rgb.mp4``, ``depth/``, ``confidence/``, ``odometry.csv``,
``camera_matrix.csv``; dazu die Fotos (``fotos/``, ``fotos.json``) und ``objekt.json``.
"""

from __future__ import annotations

import csv
import json
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from kevscan.geometrie import quat_zu_matrix

FORMAT = "kevscan"
MAX_BYTES = 4 * 1024 ** 3
MAX_DATEIEN = 200_000


class ScanFehler(ValueError):
    """Fehler im Scan, den Kevin oder die App beheben können (Meldung auf Deutsch)."""


@dataclass
class Aufnahme:
    """Ein Bild mit Kamera: Foto oder Videobild. K gilt für w × h, Lage ARKit (Kamera -> Welt, Meter)."""
    name: str
    art: str                       # "foto" | "video"
    index: int                     # Videobild k bzw. Nummer des Fotos
    zeit: float
    w: int
    h: int
    K: np.ndarray
    R_wc: np.ndarray
    t_wc: np.ndarray
    datei: Path | None = None      # Foto (Videobilder holt auswahl.py)
    tiefe: Path | None = None
    konfidenz: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Scan:
    ordner: Path
    meta: dict[str, Any]
    fotos: list[Aufnahme]
    video: list[Aufnahme]
    video_datei: Path | None
    objekt: dict[str, Any] | None
    warnungen: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.ordner.stem.replace(".kevscan", ""))


def _sicherer_pfad(name: str) -> PurePosixPath | None:
    """Relativer Pfad ohne ``..``, ohne Laufwerk und ohne führenden Schrägstrich, sonst None."""
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or ":" in n.split("/")[0]:
        return None
    p = PurePosixPath(n)
    return None if ".." in p.parts else p


def entpacken(zip_pfad: str | Path, ziel: str | Path, max_bytes: int = MAX_BYTES) -> Path:
    """ZIP sicher nach ``ziel`` entpacken (Pfade geprüft, keine Verknüpfungen, Summe höchstens ``max_bytes``) und den
    Ordner mit meta.json liefern. __MACOSX und ._-Dateien fallen weg."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    wurzel = ziel.resolve()
    try:
        zf = zipfile.ZipFile(zip_pfad)
    except zipfile.BadZipFile as exc:
        raise ScanFehler(f"Kein gültiges ZIP: {exc}") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_DATEIEN:
            raise ScanFehler(f"ZIP hat zu viele Einträge ({len(infos)})")
        summe = sum(i.file_size for i in infos)
        if summe > max_bytes:
            raise ScanFehler(f"ZIP entpackt {summe / 1e9:.1f} GB, erlaubt sind {max_bytes / 1e9:.1f} GB")
        for info in infos:
            name = info.filename
            if name.startswith("__MACOSX/") or PurePosixPath(name).name.startswith("._"):
                continue
            rel = _sicherer_pfad(name)
            if rel is None:
                raise ScanFehler(f"Unzulässiger Pfad im ZIP: {name!r}")
            modus = (info.external_attr >> 16) & 0o170000
            if modus == stat.S_IFLNK:
                raise ScanFehler(f"Verknüpfung im ZIP nicht erlaubt: {name!r}")
            aus = (wurzel / rel).resolve()
            if aus != wurzel and wurzel not in aus.parents:
                raise ScanFehler(f"Pfad außerhalb des Ziels: {name!r}")
            if info.is_dir():
                aus.mkdir(parents=True, exist_ok=True)
                continue
            aus.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as quelle, open(aus, "wb") as senke:
                shutil.copyfileobj(quelle, senke, 1 << 20)
    return finde_wurzel(ziel)


def finde_wurzel(ordner: str | Path) -> Path:
    """Ordner mit meta.json: der Ordner selbst oder genau ein Unterordner (etwa ``Name.kevscan/``)."""
    ordner = Path(ordner)
    if (ordner / "meta.json").is_file():
        return ordner
    kandidaten = [p.parent for p in ordner.glob("*/meta.json")]
    kandidaten += [p.parent for p in ordner.glob("*/*/meta.json")]
    if len(kandidaten) == 1:
        return kandidaten[0]
    if not kandidaten:
        raise ScanFehler(f"Kein Scan in {ordner} (meta.json fehlt)")
    raise ScanFehler(f"Mehrere Scans in {ordner}: {', '.join(str(k.name) for k in kandidaten)}")


def oeffnen(pfad: str | Path, entpacken_nach: str | Path | None = None) -> Path:
    """Ordner oder ZIP -> Ordner mit meta.json (ZIP wird nach ``entpacken_nach`` bzw. neben das ZIP entpackt)."""
    pfad = Path(pfad).expanduser()
    if pfad.is_dir():
        return finde_wurzel(pfad)
    if pfad.is_file() and pfad.suffix.lower() == ".zip":
        ziel = Path(entpacken_nach) if entpacken_nach else pfad.with_name(pfad.name[:-4] + ".entpackt")
        try:
            return finde_wurzel(ziel)
        except ScanFehler:
            return entpacken(pfad, ziel)
    raise ScanFehler(f"{pfad} ist weder ein Scan-Ordner noch ein ZIP")


def _kamera_matrix(datei: Path) -> np.ndarray:
    zeilen = [z for z in datei.read_text(encoding="utf-8").strip().splitlines() if z.strip()]
    K = np.array([[float(x) for x in z.replace(";", ",").split(",")] for z in zeilen[:3]], float)
    if K.shape != (3, 3):
        raise ScanFehler(f"camera_matrix.csv: 3 × 3 erwartet, gefunden {K.shape}")
    return K


def _odometrie(datei: Path) -> list[dict[str, float]]:
    out = []
    with open(datei, encoding="utf-8") as f:
        leser = csv.reader(f)
        kopf = [k.strip().lower() for k in next(leser)]
        for zeile in leser:
            if not zeile or not "".join(zeile).strip():
                continue
            d = {k: float(v) for k, v in zip(kopf, zeile) if v.strip()}
            out.append(d)
    for k in ("x", "y", "z", "qx", "qy", "qz", "qw"):
        if out and k not in out[0]:
            raise ScanFehler(f"odometry.csv: Spalte {k} fehlt (Kopf {kopf})")
    return out


def lesen(ordner: str | Path) -> Scan:
    """Scan-Ordner nach SCAN.md lesen. Fehlt Video oder Fotos, ist das erlaubt (aber nicht beides)."""
    ordner = finde_wurzel(ordner)
    try:
        meta = json.loads((ordner / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScanFehler(f"meta.json nicht lesbar: {exc}") from exc
    warnungen = []
    if meta.get("format") not in (FORMAT, None):
        warnungen.append(f"meta.json: Format {meta.get('format')!r} statt {FORMAT!r}")
    if int(meta.get("version") or 1) > 1:
        warnungen.append(f"Scan-Format Version {meta.get('version')}: neuere Felder werden übergangen")

    video: list[Aufnahme] = []
    vdatei = ordner / "rgb.mp4"
    odo = ordner / "odometry.csv"
    if odo.is_file() and (ordner / "camera_matrix.csv").is_file():
        K = _kamera_matrix(ordner / "camera_matrix.csv")
        vm = meta.get("video") or {}
        w, h = int(vm.get("breite") or 1920), int(vm.get("hoehe") or 1440)
        for k, z in enumerate(_odometrie(odo)):
            nr = int(z.get("frame", k))
            tiefe = ordner / "depth" / f"{k:06d}.png"
            if not tiefe.is_file():
                tiefe = ordner / "depth" / f"{nr:06d}.png"
            konf = ordner / "confidence" / tiefe.name
            video.append(Aufnahme(
                name=f"video_{k:06d}", art="video", index=k, zeit=float(z.get("timestamp", k / 10.0)), w=w, h=h, K=K,
                R_wc=quat_zu_matrix((z["qx"], z["qy"], z["qz"], z["qw"])), t_wc=np.array([z["x"], z["y"], z["z"]]),
                tiefe=tiefe if tiefe.is_file() else None, konfidenz=konf if konf.is_file() else None))
        if not vdatei.is_file():
            warnungen.append("rgb.mp4 fehlt: nur Fotos")
            video = []

    fotos: list[Aufnahme] = []
    fj = ordner / "fotos.json"
    if fj.is_file():
        try:
            liste = json.loads(fj.read_text(encoding="utf-8")).get("fotos") or []
        except (OSError, json.JSONDecodeError) as exc:
            raise ScanFehler(f"fotos.json nicht lesbar: {exc}") from exc
        for i, e in enumerate(liste):
            datei = ordner / "fotos" / str(e.get("datei"))
            if not datei.is_file():
                warnungen.append(f"Foto {e.get('datei')} fehlt")
                continue
            lage = e.get("lage") or {}
            if "t" not in lage or "q" not in lage or "k" not in e:
                warnungen.append(f"Foto {e.get('datei')}: Lage oder Kameramatrix fehlt")
                continue
            tiefe = ordner / "fotos" / str(e.get("tiefe") or f"{datei.stem}_depth.png")
            konf = ordner / "fotos" / str(e.get("konfidenz") or f"{datei.stem}_confidence.png")
            fotos.append(Aufnahme(
                name=f"foto_{datei.stem}", art="foto", index=i, zeit=float(e.get("zeit") or 0.0),
                w=int(e.get("breite") or (meta.get("fotos") or {}).get("breite") or 4032),
                h=int(e.get("hoehe") or (meta.get("fotos") or {}).get("hoehe") or 3024),
                K=np.asarray(e["k"], float), R_wc=quat_zu_matrix(lage["q"]), t_wc=np.asarray(lage["t"], float),
                datei=datei, tiefe=tiefe if tiefe.is_file() else None, konfidenz=konf if konf.is_file() else None,
                extra={k: e.get(k) for k in ("belichtung_s", "iso", "tracking", "tiefe_quelle", "ausloeser") if k in e}))
    if not video and not fotos:
        raise ScanFehler("Der Scan enthält weder Video mit Lagen noch Fotos mit Lagen")
    objekt = None
    oj = ordner / "objekt.json"
    if oj.is_file():
        try:
            objekt = json.loads(oj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnungen.append(f"objekt.json nicht lesbar: {exc}")
    return Scan(ordner=ordner, meta=meta, fotos=fotos, video=video, video_datei=vdatei if video else None,
                objekt=objekt, warnungen=warnungen)


def lies_tiefe(pfad: Path | None) -> np.ndarray | None:
    """16-bit-PNG in mm -> float32 mm (0 = keine Messung)."""
    if pfad is None:
        return None
    import cv2

    d = cv2.imread(str(pfad), cv2.IMREAD_UNCHANGED)
    return None if d is None else d.astype(np.float32)


def lies_konfidenz(pfad: Path | None, form: tuple[int, int] | None = None) -> np.ndarray | None:
    """8-bit-PNG mit 0, 1, 2 -> uint8; fehlt die Datei, gilt überall 2 (wenn ``form`` bekannt ist)."""
    import cv2

    if pfad is not None:
        c = cv2.imread(str(pfad), cv2.IMREAD_UNCHANGED)
        if c is not None:
            if c.ndim == 3:
                c = c[..., 0]
            return c.astype(np.uint8)
    return np.full(form, 2, np.uint8) if form else None

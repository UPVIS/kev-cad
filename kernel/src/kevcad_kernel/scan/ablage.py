"""Ablage der empfangenen Scans und das Werkzeug ``kevscan``.

Ordner: ``KEVCAD_SCANS_DIR``, sonst bei Kevins App ``~/Documents/Kev CAD/Scans``, bei einer Testvariante (Socket in
``…/de.upvis.kevcad.test…/``) deren Datenordner ``…/Scans``. Je Scan ``<datum>_<name>/`` mit dem entpackten Inhalt
(meta.json …) und ``.kevcad-scan.json`` (Empfang, Referenzen, in die er übernommen wurde).

``kevscan``: ``KEVCAD_SCAN`` (Ordner mit ``.venv``), sonst ``<wurzel>/scan`` (Repo bzw. Installation, build.sh).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

PRODUKTION = "de.upvis.kevcad"
STATUS = ".kevcad-scan.json"
MAX_BYTES = 4 * 1024 ** 3
MAX_DATEIEN = 200_000


class ScanFehler(ValueError):
    """Fehler, den Agent, Kevin oder die iPhone-App beheben können (Meldung auf Deutsch)."""


def variante(socket_path: str | None) -> str | None:
    """Bundle-ID der laufenden Variante aus dem Socket-Pfad (``…/de.upvis.kevcad.test.ui/kernel.sock``) oder None
    (Tests, Kernel ohne App)."""
    if not socket_path:
        return None
    name = Path(socket_path).expanduser().parent.name
    return name if name.startswith(PRODUKTION) else None


def ist_testvariante(var: str | None) -> bool:
    return bool(var) and var != PRODUKTION


def anzeigename(var: str | None) -> str:
    """„Kev CAD“ bzw. „Kev CAD Test ui“."""
    if not var or var == PRODUKTION:
        return "Kev CAD"
    rest = var[len(PRODUKTION) + 1:].split(".")
    return "Kev CAD " + " ".join([rest[0].capitalize()] + rest[1:])


def scans_ordner(socket_path: str | None = None) -> Path:
    env = os.environ.get("KEVCAD_SCANS_DIR")
    if env:
        return Path(env).expanduser()
    var = variante(socket_path)
    if ist_testvariante(var):
        return Path(socket_path).expanduser().parent / "Scans"
    return Path.home() / "Documents" / "Kev CAD" / "Scans"


def wurzel() -> Path:
    import kevcad_kernel

    return Path(kevcad_kernel.__file__).resolve().parents[3]


def kevscan_ordner() -> Path | None:
    """Ordner der Umgebung ``scan/`` mit ``.venv/bin/python`` und ``src/kevscan``; None, wenn sie fehlt."""
    env = os.environ.get("KEVCAD_SCAN")
    kandidaten = [Path(env).expanduser()] if env else []
    kandidaten.append(wurzel() / "scan")
    for k in kandidaten:
        if (k / ".venv" / "bin" / "python").exists() and (k / "src" / "kevscan").is_dir():
            return k
    return None


def sicherer_name(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text or "").strip())
    text = re.sub(r"[^\w .\-äöüÄÖÜß]", "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:60] or "Scan"


def _sicherer_pfad(name: str) -> PurePosixPath | None:
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or ":" in n.split("/")[0]:
        return None
    p = PurePosixPath(n)
    return None if ".." in p.parts else p


def entpacken(zip_pfad: str | Path, ziel: str | Path, max_bytes: int = MAX_BYTES) -> None:
    """ZIP sicher nach ``ziel``: keine absoluten Pfade, kein ``..``, keine Verknüpfungen, entpackt höchstens
    ``max_bytes``; __MACOSX und ._-Dateien fallen weg."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    basis = ziel.resolve()
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
            if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise ScanFehler(f"Verknüpfung im ZIP nicht erlaubt: {name!r}")
            aus = (basis / rel).resolve()
            if aus != basis and basis not in aus.parents:
                raise ScanFehler(f"Pfad außerhalb des Ziels: {name!r}")
            if info.is_dir():
                aus.mkdir(parents=True, exist_ok=True)
                continue
            aus.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as quelle, open(aus, "wb") as senke:
                shutil.copyfileobj(quelle, senke, 1 << 20)


def finde_wurzel(ordner: str | Path) -> Path | None:
    """Ordner mit meta.json: der Ordner selbst oder ein Unterordner (``Name.kevscan/``); None, wenn keiner da ist."""
    ordner = Path(ordner)
    if (ordner / "meta.json").is_file():
        return ordner
    kand = sorted(p.parent for p in ordner.glob("*/meta.json"))
    return kand[0] if len(kand) == 1 else None


def aufnehmen(zip_pfad: str | Path, basis: Path, name: str | None, quelle: str = "wlan") -> Path:
    """Ein Scan-ZIP als ``<basis>/<datum>_<name>/`` ablegen (entpackt, geprüft); Rückgabe der Ordner."""
    basis.mkdir(parents=True, exist_ok=True)
    tmp = basis / f".entpacken-{os.getpid()}-{time.time_ns()}"
    try:
        entpacken(zip_pfad, tmp)
        kern = finde_wurzel(tmp)
        if kern is None:
            raise ScanFehler("Im ZIP fehlt meta.json (kein Kev-Scan)")
        meta = _meta(kern)
        if meta is None:
            raise ScanFehler("meta.json ist kein gültiges JSON")
        anzeigen = sicherer_name(name or meta.get("name") or Path(zip_pfad).stem.replace(".kevscan", ""))
        ziel = freier_ordner(basis, f"{time.strftime('%Y-%m-%d_%H%M%S')}_{anzeigen}")
        kern.rename(ziel)
        schreibe_status(ziel, {"empfangen": jetzt(), "quelle": quelle, "name": anzeigen, "referenzen": []})
        return ziel
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def freier_ordner(basis: Path, wunsch: str) -> Path:
    ziel, i = basis / wunsch, 2
    while ziel.exists():
        ziel = basis / f"{wunsch} {i}"
        i += 1
    return ziel


def jetzt() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _meta(ordner: Path) -> dict[str, Any] | None:
    try:
        d = json.loads((ordner / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def lese_status(ordner: Path) -> dict[str, Any]:
    try:
        d = json.loads((ordner / STATUS).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def schreibe_status(ordner: Path, daten: dict[str, Any]) -> None:
    tmp = ordner / f".{STATUS}.tmp"
    tmp.write_text(json.dumps(daten, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ordner / STATUS)


def referenz_merken(ordner: Path, projekt: Path, referenz: str, schnell: bool) -> None:
    st = lese_status(ordner)
    liste = [r for r in st.get("referenzen") or [] if not (r.get("projekt") == str(projekt)
                                                          and r.get("name") == referenz)]
    liste.append({"projekt": str(projekt), "name": referenz, "stand": jetzt(), "schnell": bool(schnell)})
    st["referenzen"] = liste
    schreibe_status(ordner, st)


def _zeilen(datei: Path) -> int:
    try:
        with open(datei, "rb") as f:
            return max(0, sum(1 for z in f if z.strip()) - 1)
    except OSError:
        return 0


def eintrag(ordner: Path) -> dict[str, Any] | None:
    """Ein Scan für ``scans``: Kopf, Zahlen, Zustand. None, wenn der Ordner kein Scan ist."""
    kern = finde_wurzel(ordner)
    if kern is None:
        return None
    meta = _meta(kern) or {}
    st = lese_status(ordner)
    try:
        fotos = len(json.loads((kern / "fotos.json").read_text(encoding="utf-8")).get("fotos") or [])
    except (OSError, ValueError, AttributeError):
        fotos = 0
    groesse = 0
    for p in ordner.rglob("*"):
        try:
            if p.is_file():
                groesse += p.stat().st_size
        except OSError:
            pass
    refs = st.get("referenzen") or []
    return {"id": ordner.name, "name": meta.get("name") or st.get("name") or ordner.name, "ordner": str(kern),
            "empfangen": st.get("empfangen"), "erstellt": meta.get("erstellt"), "geraet": meta.get("geraet"),
            "app": meta.get("app"), "fotos": fotos, "videobilder": _zeilen(kern / "odometry.csv"),
            "objekt": (kern / "objekt.json").is_file(), "notiz": meta.get("notiz") or None,
            "groesse_mb": round(groesse / 1e6, 1),
            "vorschau": str(kern / "vorschau.jpg") if (kern / "vorschau.jpg").is_file() else None,
            "referenzen": refs, "zustand": "uebernommen" if refs else "neu"}


def liste(basis: Path) -> list[dict[str, Any]]:
    """Alle Scans im Ordner, neueste zuerst."""
    if not basis.is_dir():
        return []
    out = []
    for p in basis.iterdir():
        if p.is_dir() and not p.name.startswith("."):
            e = eintrag(p)
            if e is not None:
                out.append(e)
    return sorted(out, key=lambda e: (e.get("empfangen") or e.get("erstellt") or "", e["id"]), reverse=True)


def finde(basis: Path, wunsch: str | None) -> Path:
    """Scan-Ordner zu ``wunsch``: Pfad (Ordner oder ZIP, ZIP wird aufgenommen), Kennung aus ``scans``, Name, oder
    None/„letzter“ für den neuesten."""
    if wunsch and (Path(str(wunsch)).expanduser().exists() or "/" in str(wunsch)):
        p = Path(str(wunsch)).expanduser()
        if p.is_dir():
            if finde_wurzel(p) is None:
                raise ScanFehler(f"{p} ist kein Scan (meta.json fehlt)")
            return p
        if p.is_file() and p.suffix.lower() == ".zip":
            return aufnehmen(p, basis, None, quelle="datei")
        raise ScanFehler(f"{p} gibt es nicht oder ist weder Ordner noch ZIP")
    alle = liste(basis)
    if not alle:
        raise ScanFehler(f"Noch keine Scans in {basis}. Kev Scan sendet per WLAN, oder scan_importieren mit dem "
                         "Pfad eines ZIPs (AirDrop, Downloads).")
    if not wunsch or str(wunsch).lower() in ("letzter", "neuester", "latest"):
        return basis / alle[0]["id"]
    w = str(wunsch)
    for e in alle:
        if w in (e["id"], e["name"]):
            return basis / e["id"]
    tief = [e for e in alle if w.lower() in (e["id"].lower(), str(e["name"]).lower())]
    if tief:
        return basis / tief[0]["id"]
    teil = [e for e in alle if w.lower() in e["id"].lower() or w.lower() in str(e["name"]).lower()]
    if len(teil) == 1:
        return basis / teil[0]["id"]
    raise ScanFehler(f"Scan {w!r} nicht gefunden; vorhanden: {', '.join(e['id'] for e in alle[:8])}")

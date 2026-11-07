"""I-8 Datei ans Gerät (PROTOCOL.md, Abschnitt „I-8 Datei ans Gerät“).

Das iPad hat die Dateien des Mac nicht: Exporte, 3MF, PDF, CSV, Videos und model.py schreibt der Kernel am Mac. Zum
Teilen holt das iPad eine Datei stückweise über seine App-Verbindung (DATEI_REQ, Antwort DATEI mit Nutzlast). Damit das
kein Weg in beliebige Dateien des Mac wird, liefert der Kernel nur gewöhnliche Dateien unter seinen Wurzeln: dem offenen
Projekt, dem Projektordner, dem Datenordner des Kernels (neben dem Socket) und dem Ordner der Scans. Verknüpfungen werden
vorher aufgelöst, damit keine aus einer Wurzel hinausführt.

Die Gegenrichtung (DATEI_HOCH): Das iPad wählt eine Referenz (Video, Fotos) oder eine CAD-Datei und schickt sie
stückweise an den Mac. Den Ort bestimmt der Kernel (``Eingang`` im Datenordner, eine der Wurzeln oben); danach nimmt die
App den Pfad am Mac für REF_ADD oder ZUKAUF_CAD wie die Mac-App den Pfad aus dem Dateidialog.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from kevcad_kernel.protocol import DATEI_STUECK_MAX, DATEI_STUECK_VORGABE, datei_antwort


def projekte_ordner() -> Path:
    """Projektordner wie für bloße Projektnamen (ablage.py, I-7: lokal, iCloud oder eigener Ordner)."""
    from kevcad_kernel.ablage import projects_dir

    return projects_dir()


def wurzeln(projekt: Path | None, socket_path: str | None) -> list[Path]:
    """Ordner, aus denen ein Gerät Dateien holen darf (aufgelöst)."""
    from kevcad_kernel.scan.ablage import scans_ordner

    kandidaten: list[Path] = [projekte_ordner()]
    if projekt is not None:
        kandidaten.append(Path(projekt))
    if socket_path:
        kandidaten.append(Path(socket_path).expanduser().parent)
        try:
            kandidaten.append(scans_ordner(socket_path))
        except Exception:  # noqa: BLE001 - ohne Scan-Ordner bleiben die anderen Wurzeln
            pass
    out: list[Path] = []
    for k in kandidaten:
        try:
            r = k.expanduser().resolve()
        except OSError:
            continue
        if r != Path("/") and r not in out:
            out.append(r)
    return out


def stueck(header: dict[str, Any], erlaubt: list[Path]) -> tuple[dict[str, Any], bytes] | str:
    """Antwort auf DATEI_REQ: (Kopf, Nutzlast) oder eine Fehlermeldung für ERROR."""
    roh = header.get("pfad")
    if not isinstance(roh, str) or not roh.startswith("/"):
        return "pfad ist kein absoluter Pfad"
    ab = header.get("ab", 0)
    mx = header.get("max") or DATEI_STUECK_VORGABE
    if not isinstance(ab, int) or isinstance(ab, bool) or ab < 0 or not isinstance(mx, int) or mx <= 0:
        return "ab und max müssen Zahlen sein"
    mx = min(mx, DATEI_STUECK_MAX)
    try:
        echt = Path(roh).resolve(strict=True)
    except (OSError, RuntimeError):
        return f"Die Datei gibt es nicht: {Path(roh).name}"
    if not any(echt == w or w in echt.parents for w in erlaubt):
        return f"Die Datei liegt nicht im Projekt und nicht bei Kev CAD: {Path(roh).name}"
    if not echt.is_file():
        return f"Das ist keine Datei: {echt.name}"
    try:
        st = echt.stat()
        if ab > st.st_size:
            return f"ab {ab} liegt hinter dem Dateiende ({st.st_size} Byte)"
        with echt.open("rb") as f:
            f.seek(ab)
            daten = f.read(mx)
    except OSError as e:
        return f"Datei nicht lesbar: {e.strerror or e}"
    kopf, nutz = datei_antwort(str(header.get("id") or ""), str(echt), st.st_size, ab, daten, st.st_mtime)
    return kopf, nutz


# --- Gegenrichtung: Datei vom Gerät an den Mac (DATEI_HOCH) ------------------------------------------------------------

#: größte Datei, die ein Gerät schicken darf (ein Handyvideo für eine Referenz passt hinein)
HOCH_MAX = 4 * 1024 * 1024 * 1024
_SITZUNG = re.compile(r"^[A-Za-z0-9-]{4,64}$")


def eingang(socket_path: str | None) -> Path:
    """Ordner für Dateien vom Gerät: ``Eingang`` im Datenordner des Kernels (eine der Wurzeln von DATEI_REQ)."""
    basis = Path(socket_path).expanduser().parent if socket_path else Path.home() / "Library" / "Caches" / "de.upvis.kevcad"
    return basis / "Eingang"


def _dateiname(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    n = Path(name.replace("\\", "/")).name.strip()
    if not n or n.startswith(".") or len(n) > 200 or n in (".", ".."):
        return None
    return n


def hoch_stueck(header: dict[str, Any], payload: bytes, ordner: Path) -> dict[str, Any] | str:
    """DATEI_HOCH: ein Stück anhängen. Antwort DATEI_HOCH_STAND (ohne type/reply_to) oder eine Fehlermeldung.

    Das Gerät wählt keinen Ort: Die Datei landet unter ``ordner/<sitzung>/<name>`` und wird erst nach dem letzten Stück
    sichtbar (vorher ``.<name>.teil``). Ein Stück muss genau dort ansetzen, wo das letzte endete."""
    sitzung = header.get("sitzung")
    name = _dateiname(header.get("name"))
    groesse, ab = header.get("groesse"), header.get("ab", 0)
    if not isinstance(sitzung, str) or not _SITZUNG.match(sitzung):
        return "sitzung fehlt oder ist ungültig"
    if name is None:
        return "name ist kein Dateiname"
    if not isinstance(groesse, int) or isinstance(groesse, bool) or not 0 <= groesse <= HOCH_MAX:
        return f"groesse fehlt oder liegt über {HOCH_MAX // (1024 ** 3)} GB"
    if not isinstance(ab, int) or isinstance(ab, bool) or ab < 0:
        return "ab ist keine Zahl ab 0"
    if len(payload) > DATEI_STUECK_MAX:
        return "Stück größer als erlaubt"
    if ab + len(payload) > groesse:
        return "Stück reicht über die angesagte Größe"
    ziel_ordner = ordner / sitzung
    teil = ziel_ordner / f".{name}.teil"
    try:
        if ab == 0:
            if ordner.is_dir():
                _aufraeumen(ordner)
            ziel_ordner.mkdir(parents=True, exist_ok=True)
            teil.write_bytes(b"")
        bisher = teil.stat().st_size if teil.exists() else -1
        if bisher != ab:
            return f"Stück passt nicht: erwartet ab {max(bisher, 0)}, gekommen ab {ab}"
        with teil.open("ab") as f:
            f.write(payload)
        empfangen = ab + len(payload)
        pfad = None
        if empfangen == groesse:
            fertig = ziel_ordner / name
            os.replace(teil, fertig)
            pfad = str(fertig.resolve())
    except OSError as e:
        return f"Datei nicht schreibbar: {e.strerror or e}"
    return {"sitzung": sitzung, "name": name, "groesse": groesse, "empfangen": empfangen, "pfad": pfad}


def _aufraeumen(ordner: Path, alter_s: float = 7 * 24 * 3600) -> None:
    """Eingänge, die älter als eine Woche sind, entfernen (die Dateien sind dann längst übernommen)."""
    import shutil
    import time

    grenze = time.time() - alter_s
    for d in ordner.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < grenze:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

"""I-8 Datei ans Gerät (PROTOCOL.md, Abschnitt „I-8 Datei ans Gerät“).

Das iPad hat die Dateien des Mac nicht: Exporte, 3MF, PDF, CSV, Videos und model.py schreibt der Kernel am Mac. Zum
Teilen holt das iPad eine Datei stückweise über seine App-Verbindung (DATEI_REQ, Antwort DATEI mit Nutzlast). Damit das
kein Weg in beliebige Dateien des Mac wird, liefert der Kernel nur gewöhnliche Dateien unter seinen Wurzeln: dem offenen
Projekt, dem Projektordner, dem Datenordner des Kernels (neben dem Socket) und dem Ordner der Scans. Verknüpfungen werden
vorher aufgelöst, damit keine aus einer Wurzel hinausführt.
"""

from __future__ import annotations

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

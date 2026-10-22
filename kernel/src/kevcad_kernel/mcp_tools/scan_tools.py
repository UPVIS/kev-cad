"""MCP-Werkzeuge für Scans vom iPhone (Kev Scan, SCAN.md): scans, scan_importieren.

Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit). Nur gegen ``KernelService``.
Ein importierter Scan ist danach eine Referenz wie ein Object-Capture-Video: ``referenzen`` zeigt den Fortschritt,
``referenz_vermessen`` misst die param()-Werte (mit bekannten Kameras und gemessener Tiefe), die Fotoansicht zeigt die
Bilder durch ihre Kamera.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

SCAN_TOOL_NAMES: tuple[str, ...] = ("scans", "scan_importieren")


def _mm(v: Any) -> str:
    return fmt.num(v, 1) if isinstance(v, (int, float)) else "–"


def scan_zeile(s: dict[str, Any]) -> str:
    teile = [f"{s.get('fotos', 0)} Fotos", f"{s.get('videobilder', 0)} Videobilder", f"{s.get('groesse_mb', 0)} MB"]
    if s.get("objekt"):
        teile.append("Box gesetzt")
    refs = s.get("referenzen") or []
    zustand = ("übernommen in " + ", ".join(f"{r.get('name')}" for r in refs)) if refs else "neu"
    return (f"- {s.get('id')} ({s.get('name')}, {s.get('geraet') or 'Gerät ?'}, empfangen "
            f"{s.get('empfangen') or '?'}): {', '.join(teile)}; {zustand}")


def bericht_text(b: dict[str, Any] | None) -> list[str]:
    if not b:
        return []
    zeilen = []
    hu = b.get("huellmass_mm") or {}
    gr = b.get("grundriss_mm") or {}
    bi = b.get("bilder") or {}
    t = b.get("tiefe") or {}
    z = b.get("zeiten") or {}
    g = (b.get("genauigkeit") or {}).get("tiefe_gegen_netz_mm") or {}
    if hu:
        zeilen.append(f"Netz: Hülle {_mm(hu.get('laenge'))} × {_mm(hu.get('breite'))} × {_mm(hu.get('hoehe'))} mm"
                      + (f", Grundriss {_mm(gr.get('laenge'))} × {_mm(gr.get('breite'))} mm" if gr else "")
                      + f", Voxel {_mm(b.get('voxel_mm'))} mm")
    if bi:
        zeilen.append(f"Bilder: {bi.get('fotos', 0)} Fotos und {bi.get('video', 0)} Videobilder, Tiefe "
                      f"{'PromptDA ' + str(t.get('modell')) if t.get('verfahren') == 'promptda' else 'nur LiDAR'}"
                      + (f" auf {t.get('geraet')}" if t.get("geraet") else ""))
    if g:
        zeilen.append(f"Streuung der Tiefe gegen das Netz: Median {_mm(g.get('median'))} mm, 90 % unter "
                      f"{_mm(g.get('p90'))} mm")
    if z:
        zeilen.append(f"Laufzeit {fmt.num(z.get('gesamt'), 0)} s (Tiefe {fmt.num(z.get('tiefe_je_bild'), 2)} s je Bild,"
                      f" TSDF {fmt.num(z.get('tsdf'), 1)} s)")
    for w in (b.get("warnungen") or [])[:5]:
        zeilen.append(f"Warnung: {w}")
    return zeilen


def register_scan_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Scan-Werkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""
    from .tools import ADDITIVE, READ_ONLY

    @tool("scans", "Scans vom iPhone",
          "Scans received from Kevin's iPhone app Kev Scan (LiDAR depth, ARKit camera poses, high-res photos), stored "
          "in ~/Documents/Kev CAD/Scans/<date>_<name>/: id, name, photo and video frame counts, size, whether a box "
          "was set, and the references they were imported into. Also the receiver state (port, Bonjour name). "
          "Next step: scan_importieren(id).", READ_ONLY)
    async def scans() -> CallToolResult:
        res = await t.work("liest die Scans", svc.scans)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        liste = res.get("scans") or []
        e = res.get("empfaenger") or {}
        kopf = (f"Empfänger läuft auf Port {e.get('port')} als {e.get('name')!r} ({e.get('dienst')})"
                if e.get("laeuft") else "Empfänger läuft nicht (nur Import aus Datei)")
        if not liste:
            return fmt.result(f"Keine Scans in {res.get('ordner')}. {kopf}. Kev Scan sendet per WLAN; ohne WLAN das ZIP "
                              "per AirDrop schicken und scan_importieren(pfad) aufrufen.", res)
        zeilen = [f"{fmt.plural(len(liste), 'Scan', 'Scans')} in {res.get('ordner')} (neueste zuerst). {kopf}."]
        zeilen += [scan_zeile(s) for s in liste]
        if not res.get("kevscan"):
            zeilen.append("Achtung: die Auswertung (Umgebung scan/) fehlt; ./build.sh richtet sie ein.")
        return fmt.result("\n".join(zeilen), res)

    @tool("scan_importieren", "Scan übernehmen",
          "Evaluate an iPhone scan and add it as a reference of the open project (<project>/referenzen/<name>/): "
          "picks all photos plus video frames by distance and angle, Prompt Depth Anything with the LiDAR depth as "
          "prompt per image (Large model; schnell=true uses the Small model and fewer frames as a quick preview), fuses "
          "them with the ARKit poses (TSDF, ~2 mm voxels) into a mesh in mm with Z up and the floor at z = 0, shown "
          "semi-transparent in the viewer like an Object Capture mesh. Runs in the background (Large: about 2 s per "
          "image on the M2 Pro, a typical scan 2 to 4 min; schnell: 1 to 2 min); warten_s waits for the "
          "result. scan: id or name from `scans`, 'letzter' / None for the newest, or a path to a scan folder or "
          ".kevscan.zip (AirDrop, Downloads). Afterwards referenz_vermessen(name) fits the param() dimensions with the "
          "known cameras and the measured depth (no known dimension needed: the scan is metric).", ADDITIVE)
    async def scan_importieren(
        scan: Annotated[str | None, Field(description="Scan id/name from `scans`, 'letzter', or a folder/ZIP path")]
        = None,
        name: Annotated[str | None, Field(description="Reference name (default: name of the scan)")] = None,
        schnell: Annotated[bool, Field(description="Quick preview: Small model, fewer frames")] = False,
        warten_s: Annotated[float, Field(ge=0, le=900, description="Wait up to this long for the result")] = 0,
    ) -> CallToolResult:
        res = await t.work("wertet den Scan aus", svc.scan_importieren, scan, name, schnell, warten_s)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Scan nicht übernommen: {err}", res)
        ref = res.get("referenz") or {}
        if ref.get("zustand") == "fertig":
            zeilen = [f"Scan {res.get('scan')} ist als Referenz {res.get('name')} im Projekt "
                      f"({'Vorschau, Small-Modell' if schnell else 'PromptDA Large'})."]
            zeilen += bericht_text(res.get("bericht"))
            zeilen.append(f"Weiter: referenz_vermessen(\"{res.get('name')}\", freie_masse=[…]) misst die Maße mit den "
                          "bekannten Kameras und der Tiefe.")
            return fmt.result("\n".join(zeilen), res)
        if ref.get("zustand") == "fehler":
            return fmt.error_result(f"Auswertung fehlgeschlagen: {ref.get('meldung')}", res)
        return fmt.result(f"Auswertung läuft für die Referenz {res.get('name')} (Scan {res.get('scan')}, "
                          f"{'schnell' if schnell else 'genau'}). Fortschritt sieht Kevin in der App; warten mit "
                          f"referenzen(\"{res.get('name')}\", warten_s=300).", res)

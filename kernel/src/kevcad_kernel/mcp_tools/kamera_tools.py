"""MCP-Werkzeuge für Kameras (Phase 5, Strang KAM): Liste, Einzelheiten, Blick durch die Kamera, Kamerabild, Katalog
und Vorschlag aus Kevins Ansicht. Kameras selbst entstehen in model.py (``lager.kamera(...)``), der Agent bearbeitet
dafür die Datei. Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from kevcad_kernel.kamera import camera_line
from kevcad_kernel.optik import blende_text, mm_text

from . import format as fmt

CAMERA_TOOL_NAMES: tuple[str, ...] = (
    "kamera_liste", "kamera_info", "kamera_ansicht", "kamera_bild", "kamera_katalog", "kamera_vorschlag_aus_ansicht",
)


def _dist(x: Any) -> str:
    return mm_text(float(x)) if isinstance(x, (int, float)) else "∞"


def camera_detail(c: dict[str, Any]) -> str:
    """Mehrzeilige Beschreibung einer Kamera für kamera_info."""
    kam = c.get("kamera") or {}
    obj = c.get("objektiv") or {}
    f = (c.get("format") or {})
    res = c.get("aufloesung") or ["?", "?"]
    sensor = c.get("sensor_mm") or [0, 0]
    lines = [
        f"{c.get('name')}: {kam.get('name')} mit {obj.get('name') or 'idealem Objektiv (ohne Katalogobjektiv)'}",
        f"Format: {f.get('name')} ({res[0]} × {res[1]} px, Sensorfläche {fmt.num(sensor[0], 2)} × "
        f"{fmt.num(sensor[1], 2)} mm, Seitenverhältnis {fmt.num(c.get('seitenverhaeltnis'), 3)}:1)",
        f"Brennweite {fmt.num(c.get('brennweite'), 1)} mm · Bildwinkel horizontal {fmt.num(c.get('bildwinkel_h'), 2)}°, "
        f"vertikal {fmt.num(c.get('bildwinkel_v'), 2)}°, diagonal {fmt.num(c.get('bildwinkel_d'), 2)}°",
        f"Blende {blende_text(float(c.get('blende') or 0), c.get('blendenart') or 'f')} · Fokus {_dist(c.get('fokus'))} "
        f"(ab Sensorebene) · Schärfe {_dist(c.get('schaerfe_nah'))} bis {_dist(c.get('schaerfe_fern'))} · hyperfokal "
        f"{_dist(c.get('hyperfokal'))} · Zerstreuungskreis {fmt.num(c.get('zerstreuungskreis'), 3)} mm",
        f"Sensormitte {fmt.vec(c.get('sensor_pos'), 1)} · Blick {fmt.vec(c.get('blick'), 3)} · oben "
        f"{fmt.vec(c.get('oben'), 3)} · Augpunkt {fmt.vec(c.get('auge'), 1)}",
    ]
    if c.get("teil"):
        lines.append(f"Hängt an Teil {c['teil']} (folgt ihm)")
    if c.get("ausblenden"):
        lines.append(f"Beim Blick durch die Kamera ausgeblendet: {', '.join(c['ausblenden'])}")
    if c.get("vignettierung"):
        lines.append("Achtung: Bildkreis des Objektivs kleiner als die Formatdiagonale, die Ecken vignettieren.")
    return "\n".join(lines)


def catalog_line(it: dict[str, Any]) -> str:
    art = it.get("art")
    if art == "kamera":
        formate = ", ".join(f"{f.get('id')} ({f.get('name')})" for f in it.get("formate") or [])
        return f"- {it.get('id')}: {it.get('name')} · Bajonett {it.get('bajonett')} · Formate: {formate}"
    if art == "objektiv":
        bw = it.get("brennweite")
        bw_text = f"{fmt.num(bw[0], 1)}–{fmt.num(bw[1], 1)} mm" if isinstance(bw, list) else f"{fmt.num(bw, 1)} mm"
        return (f"- {it.get('id')}: {it.get('name')} · {bw_text} "
                f"{blende_text(float(it.get('lichtstaerke') or 0), it.get('blendenart') or 'f')} · nah "
                f"{_dist(it.get('naheinstellgrenze'))} · Bildkreis {fmt.num(it.get('bildkreis'), 1)} mm · Länge "
                f"{fmt.num(it.get('laenge'), 1)} mm · {fmt.num(it.get('gewicht'), 0)} g")
    pts = ", ".join(sorted((it.get("bezugspunkte") or {}).keys()))
    return (f"- {it.get('id')}: {it.get('name')} · {it.get('typ')}"
            + (f" · {fmt.num(it.get('gewicht'), 0)} g" if it.get("gewicht") else "")
            + (f" · Bezugspunkte {pts}" if pts else ""))


def register_camera_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert die Kamerawerkzeuge über den ``tool``-Dekorator aus ``register_tools``."""
    READ_ONLY, VIEWER, ADDITIVE = annotations["read_only"], annotations["viewer"], annotations["additive"]

    @tool("kamera_liste", "Kameras",
          "Cameras defined in model.py with lager.kamera(...): camera body, lens, recording format, focal length, "
          "angle of view, aperture, focus distance and depth of field per camera, the part they are attached to, and "
          "pending position suggestions from Kevin (Ctrl+Alt+0 in the app).", READ_ONLY)
    async def kamera_liste() -> CallToolResult:
        res = await t.work("liest die Kameras", svc.cameras)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kameras nicht lesbar: {err}", res)
        cams = res.get("cameras") or []
        if not cams:
            return fmt.result("Keine Kameras im Modell. In model.py: fx6 = lager.kamera(\"sony-fx6\", objektiv=…, "
                              "format=…, blende=…, fokus=…).setzen(position, blick_auf=…); optional "
                              "show(fx6.koerper(), \"Kamera FX6\"); dann run.", res)
        lines = [f"{fmt.plural(len(cams), 'Kamera', 'Kameras')}:"] + [f"- {camera_line(c)}" for c in cams]
        return fmt.result("\n".join(lines), res)

    @tool("kamera_info", "Kamera",
          "Full details of one camera by name (e.g. 'FX6'): sensor area of the format, resolution, focal length, "
          "horizontal/vertical/diagonal angle of view, aperture, focus distance (from the sensor plane), near/far "
          "limit of sharpness, hyperfocal distance, circle of confusion, position (sensor center, view direction, "
          "up, eye point) and, if Kevin suggested a new position in the app, the model.py line for it.", READ_ONLY)
    async def kamera_info(
        name: Annotated[str, Field(description="Camera name as in lager.kamera(name=...), e.g. 'FX6'")] = "",
    ) -> CallToolResult:
        res = await t.work(f"liest Kamera {name}".strip(), svc.camera_info, name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        text = camera_detail(res.get("camera") or {})
        if res.get("vorschlag_code"):
            text += f"\nVorschlag aus Kevins Ansicht: {res['vorschlag_code']}"
        return fmt.result(text, res)

    @tool("kamera_ansicht", "Durch Kamera schauen",
          "Show Kevin the view through a camera in the viewer (like Blender numpad 0): exact angle of view, format "
          "frame with title and action safe areas, focal length, aperture, focus and depth of field. name=None or "
          "'aus' returns to the free view.", VIEWER)
    async def kamera_ansicht(
        name: Annotated[str | None, Field(description="Camera name, or None / 'aus' for the free view")] = None,
    ) -> CallToolResult:
        off = name is None or str(name).strip().lower() in ("aus", "off", "none", "")
        res = await t.work("schaut durch die Kamera" if not off else "verlässt die Kameraansicht", svc.camera_view,
                           None if off else name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kameraansicht nicht möglich: {err}", res)
        text = "Freie Ansicht." if off else f"Viewer zeigt den Blick durch {name}."
        if res.get("message"):
            text += f" ({res['message']})"
        return fmt.result(text, res)

    @tool("kamera_bild", "Kamerabild",
          "Render the image of a camera (its position, angle of view and aspect ratio of the format) and save it as "
          "PNG in <project>/output/kameras/. breite is the width in px (1920 = HD, 3840 = UHD 4K, 4096 = DCI 4K); "
          "the height follows from the format. By default only the file path is returned, not the image: Kevin "
          "does not want unnecessary screenshots. Set bild_zeigen=true only if Kevin asks to see it here or you "
          "really need to look at it. rahmen=true draws highlights and annotations into the image.", ADDITIVE)
    async def kamera_bild(
        name: Annotated[str, Field(description="Camera name, e.g. 'FX6'")] = "",
        breite: Annotated[int, Field(ge=64, le=8192, description="Image width in px")] = 1920,
        speichern: Annotated[bool, Field(description="Save the PNG under output/kameras/")] = True,
        bild_zeigen: Annotated[bool, Field(description="Also return the image to you (only when needed)")] = False,
        rahmen: Annotated[bool, Field(description="Include highlights and annotations")] = False,
    ) -> CallToolResult:
        res = await t.work(f"rendert das Kamerabild {name}".strip(), svc.camera_image, name, breite, speichern,
                           bild_zeigen, rahmen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kein Kamerabild: {err}", res)
        png = res.get("png") or b""
        cam = res.get("kamera") or {}
        what = (f"{res.get('name')}: {res.get('width')} × {res.get('height')} px, "
                f"{(cam.get('format') or {}).get('name')}, {fmt.num(cam.get('brennweite'), 1)} mm, Bildwinkel "
                f"{fmt.num(cam.get('bildwinkel_h'), 1)}° × {fmt.num(cam.get('bildwinkel_v'), 1)}°")
        text = f"Kamerabild {what}" + (f"\nGespeichert: {res['file']}" if res.get("file") else "")
        for w in res.get("warnings") or []:
            text += f"\nHinweis: {w}"
        data = {k: v for k, v in res.items() if k != "png"}
        extra = [fmt.image_block(png)] if png and bild_zeigen else None
        return fmt.result(text, data, extra=extra)

    @tool("kamera_katalog", "Kamerakatalog",
          "Cameras (with recording formats and sensor areas), lenses (focal length or zoom range, max aperture or "
          "T-stop, close focus, image circle, length, weight) and camera accessories (cage, baseplate, 15 mm rods, "
          "rosettes, V-mount plates and batteries with reference points) from Kevin's inventory. suche filters by "
          "text (e.g. 'sigma 35', 'cine zoom', 'v-mount'), art by kind. Use the ids in lager.kamera(...) and "
          "lager.kamerazubehoer(...).", READ_ONLY)
    async def kamera_katalog(
        suche: Annotated[str, Field(description="Search text")] = "",
        art: Annotated[Literal["kamera", "objektiv", "kamerazubehoer"] | None,
                       Field(description="Only this kind")] = None,
    ) -> CallToolResult:
        res = await t.work(f"sucht im Kamerakatalog „{suche}“" if suche else "liest den Kamerakatalog",
                           svc.camera_catalog, suche, art)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Katalog nicht lesbar: {err}", res)
        items = res.get("items") or []
        if not items:
            return fmt.result(f"Nichts gefunden für „{suche}“." if suche else "Keine Kameras im Katalog.", res)
        lines = [f"{fmt.plural(int(res.get('total', len(items))), 'Eintrag', 'Einträge')}:"]
        lines += [catalog_line(it) for it in items]
        lines.append("In model.py: lager.kamera(\"<kamera-id>\", objektiv=\"<objektiv-id>\", format=\"<format-id>\", "
                     "brennweite=…, blende=…, fokus=…); Zubehör: lager.kamerazubehoer(\"<id>\").verbauen(name, an=…, "
                     "bezug=…).")
        return fmt.result("\n".join(lines), res)

    @tool("kamera_vorschlag_aus_ansicht", "Kamera auf Ansicht",
          "Take Kevin's current viewer view as a new position for a camera (like Blender Ctrl+Alt+0) and return the "
          "model.py line (setzen(...)) that places the camera there. Does not change model.py: edit the file "
          "yourself if Kevin wants it, then run.", READ_ONLY)
    async def kamera_vorschlag_aus_ansicht(
        name: Annotated[str, Field(description="Camera name, e.g. 'FX6'")] = "",
    ) -> CallToolResult:
        res = await t.work("übernimmt die Ansicht als Kameravorschlag", svc.camera_suggestion, name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kein Vorschlag: {err}", res)
        return fmt.result(f"Vorschlag für {res.get('name')}: {res.get('code')}", res)

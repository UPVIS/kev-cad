"""MCP-Werkzeug ``render`` (Phase 7, PLAN-PHASE7-RENDERINGS.md): schöne Bilder der Konstruktion, schnell über die
App (RealityKit) oder fotorealistisch über Blender Cycles im Hintergrund. Beschreibung englisch (für das Modell),
Ergebnis deutsch (Kevin liest mit). Bilder bekommt der Agent nur mit ``bild_zeigen`` (Kevins Regel).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from kevcad_kernel.render import szenen as sz

from . import format as fmt

RENDER_TOOL_NAMES: tuple[str, ...] = ("render",)

_GROESSEN = ", ".join(f"{k} ({w}×{h})" for k, (w, h) in sz.GROESSEN.items())


def render_text(res: dict[str, Any]) -> str:
    """Kurzer deutscher Bericht über einen Auftrag."""
    z = res.get("zustand")
    kopf = (f"Rendering {res.get('auftrag')} ({res.get('szene_titel') or res.get('szene')}, "
            f"{'Foto (Blender Cycles)' if res.get('qualitaet') == 'foto' else 'schnell (RealityKit)'}, "
            f"{res.get('width')} × {res.get('height')} px, Ansicht {res.get('ansicht')}"
            + (f", Kamera {res.get('kamera')}" if res.get("kamera") else "") + ")")
    if z == "fertig":
        zeilen = [f"{kopf}: fertig in {fmt.num((res.get('ms') or 0) / 1000, 1)} s.", f"Datei: {res.get('pfad')}"]
        ph = res.get("phasen") or {}
        if ph:
            zeilen.append("Phasen: " + ", ".join(f"{k.removesuffix('_ms')} {fmt.num(v / 1000, 2)} s"
                                                 for k, v in ph.items() if isinstance(v, (int, float))))
        if res.get("samples") and res.get("qualitaet") == "foto":
            zeilen.append(f"{res.get('samples')} Proben je Pixel auf {res.get('geraet') or '?'}, "
                          f"{res.get('teile')} Teile, {res.get('dreiecke')} Dreiecke.")
        zeilen.append("Das Bild ist für Kevin; nur mit bild_zeigen=true selbst ansehen.")
        return "\n".join(zeilen)
    if z in ("wartet", "laeuft"):
        pct = int(round(float(res.get("fortschritt") or 0) * 100))
        return (f"{kopf}: {('läuft' if z == 'laeuft' else 'wartet')} ({pct} %, {res.get('text')}). Ziel: "
                f"{res.get('pfad')}. Stand später mit render(auftrag=\"{res.get('auftrag')}\") abfragen "
                f"(warten_s wartet), abbrechen mit abbrechen=true. Kevin sieht den Fortschritt in der App.")
    return f"{kopf}: {res.get('error') or z}"


def register_render_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert ``render`` über den ``tool``-Dekorator aus ``register_tools``."""
    from .tools import ADDITIVE

    @tool("render", "Rendern",
          "Render a beautiful image of the current model for Kevin (product shot, cover image for documents, image "
          "for customers or social media) into <project>/output/renders/. Uses what the viewer shows: visible parts, "
          "explosion and animation pose (no section, highlights or dimensions). Materials come from the catalog "
          "(field render: aluminium anodized/brushed, galvanized steel, stainless, PLA/PETG with layer lines, rubber, "
          "wood grain); a color set in show() wins over the catalog color. "
          "szene: studio (light background, soft shadow), werkstatt (dark hall with lamps, HDRI), draussen (garden "
          "daylight, HDRI), wohnraum (interior HDRI), freigestellt (transparent PNG with soft shadow); hintergrund "
          "overrides the background (weiss, hell, grau, dunkel, schwarz, transparent or #RRGGBB). "
          "ansicht: aktuell (Kevin's current view, default), produkt (3/4 view from slightly above, fitted), or a "
          "standard view (iso, iso_front_left, iso_back_right, iso_back_left, front, back, left, right, top); kamera: "
          "a camera from model.py (Phase 5), then its aspect ratio matters. "
          f"groesse: {_GROESSEN} or 'WxH'. "
          "qualitaet: schnell (RealityKit in the app, about 1-3 s, waits) or foto (Blender Cycles path tracing in "
          "the background, about 1-5 min: returns immediately with an auftrag id like R-3; query it later with "
          "render(auftrag='R-3', warten_s=...) or cancel with abbrechen=true). Only start foto when Kevin asks for a "
          "photorealistic image. By default you get only the path, not the image: set bild_zeigen=true only if Kevin "
          "asks you to look at it or you really need to check it.", ADDITIVE)
    async def render(
        szene: Annotated[str, Field(description="studio, werkstatt, draussen, wohnraum, freigestellt or the name "
                                                "of an own HDRI in the app data folder 'umgebungen'")] = "studio",
        ansicht: Annotated[str | None, Field(description="aktuell (default), produkt, iso, front, top, ...")] = None,
        kamera: Annotated[str | None, Field(description="Camera from model.py, e.g. 'FX6'")] = None,
        groesse: Annotated[str | None, Field(description="hd (default), 4k, quadrat, hochkant, story, deckblatt, "
                                                         "a4, vorschau or 'WxH'")] = None,
        qualitaet: Annotated[Literal["schnell", "foto"], Field(description="schnell or foto")] = "schnell",
        hintergrund: Annotated[str | None, Field(description="Override the background")] = None,
        umgebung: Annotated[str | None, Field(description="Own .hdr file (free license only)")] = None,
        ziel: Annotated[str | None, Field(description="File name or path; relative = in output/renders/")] = None,
        auftrag: Annotated[str | None, Field(description="Query (or cancel) an existing job, e.g. 'R-3'")] = None,
        abbrechen: Annotated[bool, Field(description="With auftrag: cancel the job")] = False,
        warten_s: Annotated[float | None, Field(ge=0, le=1800, description="foto/auftrag: wait up to this many "
                                                                           "seconds for the result")] = None,
        bild_zeigen: Annotated[bool, Field(description="Also return the image to you (only when needed)")] = False,
    ) -> CallToolResult:
        if auftrag:
            was = "bricht das Rendering ab" if abbrechen else f"fragt Rendering {auftrag} ab"
        else:
            was = f"rendert {'ein Foto' if qualitaet == 'foto' else 'ein Bild'} ({szene})"
        res = await t.work(was, svc.render, szene, ansicht, kamera, groesse, qualitaet, hintergrund, umgebung, ziel,
                           warten_s, auftrag, abbrechen, bild_zeigen)
        err = fmt.service_error(res)
        if err and not res.get("auftrag"):
            return fmt.error_result(f"Kein Rendering: {err}", res)
        png = res.get("png") or b""
        data = {k: v for k, v in res.items() if k not in ("png", "log")}
        if res.get("zustand") in ("fehler", "abgebrochen"):
            return fmt.error_result(render_text(res), data)
        extra = [fmt.image_block(png)] if png and bild_zeigen else None
        return fmt.result(render_text(res), data, extra=extra)

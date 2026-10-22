"""MCP-Werkzeuge der Prüfung: ``pruefen``, ``montage_reihenfolge``, ``ansichten`` (eigene Datei, damit die Stränge
beim Zusammenführen nicht in tools.py kollidieren)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult, TextContent
from pydantic import Field

from kevcad_kernel.service import KernelService

from . import format as fmt

StandardView = Literal[
    "top", "bottom", "front", "back", "left", "right", "iso", "iso_front_left", "iso_back_right", "iso_back_left"
]
Darstellung = Literal["shaded_edges", "shaded", "wireframe", "xray"]
PRUEF_ENDSTAND_S = 300.0  # so lange wartet pruefen(warten=true) auf das Fertigrechnen im Hintergrund
ANSICHT_NAMEN = {"top": "oben", "bottom": "unten", "front": "vorne", "back": "hinten", "left": "links",
                 "right": "rechts", "iso": "iso", "iso_front_left": "iso vorne links",
                 "iso_back_right": "iso hinten rechts", "iso_back_left": "iso hinten links"}


def bilder_bloecke(bilder: list[dict[str, Any]]) -> list[Any]:
    """Je Bild eine Beschriftung und das PNG."""
    out: list[Any] = []
    for i, b in enumerate(bilder, 1):
        hinweis = "" if b.get("ansicht_umgesetzt", True) else " (ältere App: Standardansicht ohne Ausrichtung)"
        out.append(TextContent(type="text", text=f"Bild {i}: {b.get('name')}{hinweis}"))
        out.append(fmt.image_block(b["png"]))
    return out


def register_pruef_tools(t: Any, svc: KernelService, tool: Callable[..., Any]) -> None:
    from .tools import ADDITIVE, READ_ONLY, ToolInputError, check_points, check_refs

    @tool("pruefen", "Prüfen",
          "Full result of the built-in check of the last run (it runs automatically after every run): all findings "
          "(interpenetration, floating, tipping, not assemblable, trapped, tool access, compliant parts, invalid "
          "declarations) with location, values and a fix each, plus stability per group and the assembly summary. "
          "bilder=true adds close-up offscreen images of the worst findings (2-3 directions, x-ray, red overlap "
          "volume) for your own analysis; Kevin's view does not change. Do not send these images to Kevin. If the "
          "range of motion of a run hit its time limit (state 'teilweise'), the kernel finishes it in the "
          "background; warten=true (default) waits for that final result, so call pruefen before reporting done. "
          "The same holds for the statics computed after a run (Ablauf, Festkörper): their findings statik_dyn_* and "
          "statik_festkoerper arrive later in the same check (warnings and notes only, never an export block).",
          READ_ONLY)
    async def pruefen(
        bilder: Annotated[bool, Field(description="Close-up images of up to 3 findings for your own analysis")] = False,
        hinweise: Annotated[bool, Field(description="Also list notes (schwere hinweis)")] = True,
        warten: Annotated[bool, Field(description=(
            "Wait for the final result when the range of motion is still being finished in the background "
            "(state 'teilweise', up to 5 minutes); false returns the current state at once"))] = True,
    ) -> CallToolResult:
        from kevcad_kernel.pruefung.dienst import ansicht_fuer_befund
        from kevcad_kernel.pruefung.text import pruef_text, stand_text

        if warten:
            res = await t.work("wartet auf das fertige Prüfergebnis", svc.pruefen, PRUEF_ENDSTAND_S, endstand=True)
        else:
            res = await t.work("liest das Prüfergebnis", svc.pruefen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        text, offen = pruef_text(res, max_befunde=60, hinweise=hinweise)
        teile = [text]
        st = stand_text(res)
        if st:
            teile.append(st)
        m = res.get("montage")
        if isinstance(m, dict):
            n = len(m.get("schritte") or [])
            teile.append(f"Montage: {n} Schritte" + (", vollständig" if m.get("vollstaendig") else
                                                     f", nicht einbaubar: {', '.join((m.get('offen') or [])[:6])}")
                         + " (Liste mit montage_reihenfolge).")
        if res.get("laeuft"):
            teile.append(f"Hinweis: eine neuere Prüfung (Lauf {res['laeuft']}) läuft noch.")
        if res.get("state") == "teilweise" and warten:
            if res.get("hintergrund") == res.get("run") or res.get("statik_hintergrund") == res.get("run"):
                teile.append("Nach 5 Minuten noch nicht fertig gerechnet (Bewegungsraum bzw. Statik im Hintergrund): "
                             "später erneut pruefen.")
            elif res.get("im_hintergrund") or not res.get("statik_im_hintergrund"):
                teile.append("Der Bewegungsraum dieses Laufs wurde nicht fertig gerechnet (neuerer Lauf oder "
                             "Rechenprozess neu gestartet): erneut run aufrufen.")
            else:
                teile.append("Ablauf bzw. Festkörper dieses Laufs wurden nicht fertig (neuerer Lauf oder abgebrochen): "
                             "statik() bzw. festigkeit() rechnen sie auf Wunsch.")
        extra: list[Any] = []
        if bilder:
            kandidaten = [b for b in res.get("befunde") or [] if b.get("ort") and b.get("schwere") != "hinweis"][:3]
            ansichten = [a for b in kandidaten for a in ansicht_fuer_befund(b)]
            if ansichten:
                bild = await t.work("rendert Nahansichten der Befunde", svc.ansichten, ansichten, 480, 320)
                if bild.get("ok"):
                    extra = bilder_bloecke(bild.get("bilder") or [])
                else:
                    teile.append(f"Keine Bilder: {bild.get('error')}")
        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result("\n\n".join(teile), data, error=offen, extra=extra)

    @tool("montage_reihenfolge", "Montagereihenfolge",
          "Assembly order of the last run from the built-in check (assembly by disassembly): one step per part or "
          "sub-assembly with insertion direction ('von oben', 'von -X her', …) and tool for fasteners, the base "
          "part first; lists parts that cannot be assembled. Design parts so that this order is sensible.", READ_ONLY)
    async def montage_reihenfolge() -> CallToolResult:
        from kevcad_kernel.pruefung.text import montage_text

        res = await t.work("liest die Montagereihenfolge", svc.pruefen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        m = res.get("montage")
        return fmt.result(montage_text(res), {"run": res.get("run"), "montage": m})

    @tool("ansichten", "Ansichten",
          "Several offscreen images in ONE call for your own analysis (not for Kevin): standard views (default iso, "
          "front, right, top) and/or free camera directions, small size by default (640 × 400). Optionally framed "
          "on parts (ziel) or on a point with radius, x-ray display to see hidden parts, parts highlighted in red, "
          "the red overlap volumes of the check shown. Kevin's camera and display stay unchanged. Use it when "
          "images lead to a better decision (overlaps, assemblability, proportions, comparison with reference "
          "photos), not after every step.", ADDITIVE)
    async def ansichten(
        views: Annotated[list[StandardView] | None, Field(description="Standard views, default iso, front, right, top")]
        = None,
        richtungen: Annotated[list[list[float]] | None,
                              Field(description="Extra free camera view directions [x, y, z] (camera looks along)")]
        = None,
        ziel: Annotated[list[str] | None, Field(description="Frame these parts (names or groups)")] = None,
        punkt: Annotated[list[float] | None, Field(description="Frame this point [x, y, z] (with radius)")] = None,
        radius: Annotated[float | None, Field(gt=0, description="Radius around punkt in mm")] = None,
        darstellung: Annotated[Darstellung, Field(description="Display style for these images")] = "shaded_edges",
        hervorheben: Annotated[list[str] | None, Field(description="Parts to tint red in these images")] = None,
        schnittkoerper: Annotated[bool, Field(description="Show the red overlap volumes of the check")] = True,
        width: Annotated[int, Field(ge=64, le=2048, description="Image width in px")] = 640,
        height: Annotated[int, Field(ge=64, le=2048, description="Image height in px")] = 400,
    ) -> CallToolResult:
        gemeinsam: dict[str, Any] = {"darstellung": darstellung, "schnittkoerper": bool(schnittkoerper)}
        if ziel:
            gemeinsam["ziel"] = check_refs(ziel)
        if punkt is not None:
            gemeinsam["punkt"] = check_points([punkt], 1)[0]
            gemeinsam["radius"] = float(radius or 50.0)
        if hervorheben:
            gemeinsam["hervorheben"] = check_refs(hervorheben)
        liste: list[dict[str, Any]] = []
        for v in views if views is not None else (["iso", "front", "right", "top"] if not richtungen else []):
            liste.append({**gemeinsam, "name": ANSICHT_NAMEN.get(v, v), "standard": v})
        for r in richtungen or []:
            d = check_points([r], 1)[0]
            if not any(d):
                raise ToolInputError("Eine Richtung darf nicht [0, 0, 0] sein.")
            liste.append({**gemeinsam, "name": "Richtung " + fmt.vec(d), "richtung": d})
        if not liste:
            raise ToolInputError("Mindestens eine Ansicht (views) oder Richtung angeben.")
        if len(liste) > 8:
            raise ToolInputError("Höchstens 8 Ansichten in einem Aufruf.")
        res = await t.work(f"rendert {len(liste)} Ansichten", svc.ansichten, liste, width, height)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Keine Ansichten: {err}")
        bilder = res.get("bilder") or []
        text = (f"{fmt.plural(len(bilder), 'Ansicht', 'Ansichten')} {width} × {height} px zur eigenen Analyse "
                "(Kevins Ansicht unverändert): " + ", ".join(str(b.get("name")) for b in bilder) + ".")
        data = {"bilder": [{k: v for k, v in b.items() if k != "png"} | {"bytes": len(b["png"])} for b in bilder]}
        return fmt.result(text, data, extra=bilder_bloecke(bilder))

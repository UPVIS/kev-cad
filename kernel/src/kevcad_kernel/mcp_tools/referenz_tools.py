"""MCP-Werkzeuge für Referenzen (Phase 4): referenzen, referenz_video, referenz_fotos, referenz_vermessen.

Wie die anderen Werkzeuge: Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit). Nur gegen
``KernelService``. Gemessene Maße schreibt kein Werkzeug in model.py: das macht Kevin mit „Maße übernehmen“ in der
App, oder der Agent ändert model.py selbst, wenn Kevin es ausdrücklich will.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

REFERENZ_TOOL_NAMES: tuple[str, ...] = ("referenzen", "referenz_video", "referenz_fotos", "referenz_vermessen")


def _mm(v: Any, nd: int = 1) -> str:
    return fmt.num(v, nd) if isinstance(v, (int, float)) else "–"


def _groesse(g: Any) -> str:
    if isinstance(g, dict):
        g = g.get("groesse") or [g.get("laenge"), g.get("breite"), g.get("hoehe")]
    if not isinstance(g, (list, tuple)):
        return "–"
    return " × ".join(_mm(x) for x in g if x is not None) + " mm"


def ergebnis_text(e: dict[str, Any]) -> str:
    """Messergebnis (REF_RESULT bzw. referenz_vermessen) als Text."""
    zeilen = [f"Referenz {e.get('referenz')}: {fmt.plural(int(e.get('bilder') or 0), 'Bild', 'Bilder')}"
              + (f", Überdeckung {fmt.num((e.get('ueberdeckung') or 0) * 100, 1)} %" if e.get("ueberdeckung") else "")
              + (f", {fmt.num(e.get('dauer_s'), 0)} s" if e.get("dauer_s") else "")]
    rows = [["Maß", "model.py", "gemessen", "± Sigma", "Änderung"]]
    for m in e.get("masse") or []:
        rows.append([m["name"], _mm(m.get("start")), _mm(m.get("wert")), _mm(m.get("sigma")),
                     (("+" if (m.get("aenderung") or 0) > 0 else "") + _mm(m.get("aenderung")))
                     if m.get("aenderung") is not None else "–"])
    zeilen.append(fmt.table(rows, right={1, 2, 3, 4}))
    if e.get("bekannt"):
        zeilen.append("Fest (Maßstab): " + ", ".join(f"{k} = {_mm(v)} mm" for k, v in e["bekannt"].items()))
    if e.get("huelle"):
        zeilen.append(f"Hülle mit Anbauten: {_groesse(e['huelle'])}")
    g = e.get("grundkoerper")
    if g:
        zeilen.append(f"Grundkörper {g.get('teil')}: {_groesse(g)}")
    for emp in e.get("empfehlungen") or []:
        zeilen.append(f"Hinweis: {emp.get('text')}")
    if e.get("lage_netz"):
        zeilen.append(e["lage_netz"])
    for w in (e.get("warnungen") or [])[:6]:
        zeilen.append(f"Warnung: {w}")
    if e.get("kontrollbilder"):
        zeilen.append(f"Kontrollbilder ({len(e['kontrollbilder'])}): grün Umriss, gelb innere Kanten, rot ohne "
                      f"Partner, blau Maskenrand; z. B. {e['kontrollbilder'][0]}")
    zeilen.append("Übernehmen: Kevin klickt in der App „Maße übernehmen“ (schreibt die param()-Werte in model.py).")
    return "\n".join(zeilen)


def eintrag_text(r: dict[str, Any]) -> str:
    z = r.get("zustand")
    kopf = f"- {r.get('name')} ({'Video' if r.get('art') == 'video' else 'Fotos'}: {r.get('quelle')}): "
    if z == "rechnet":
        kopf += (f"{'Object Capture' if r.get('laeuft') == 'capture' else 'Vermessen'} läuft, "
                 f"{fmt.num((r.get('fortschritt') or 0) * 100, 0)} %" + (f" ({r.get('text')})" if r.get("text") else ""))
    elif z == "fehler":
        kopf += f"Fehler: {r.get('meldung')}"
    elif z == "leer":
        kopf += "noch nichts gerechnet"
    else:
        teile = []
        if r.get("netz"):
            c = r.get("capture") or {}
            teile.append(f"Netz (Hülle {_groesse(c.get('huelle'))}, Grundkörper {_groesse(c.get('grundkoerper'))}"
                         + (f", {c.get('ausgerichtet')} von {c.get('bilder')} Bildern" if c.get("bilder") else "")
                         + ")")
        if r.get("messung"):
            teile.append(f"vermessen ({fmt.plural(int(r.get('fotos') or 0), 'Foto', 'Fotos')} mit Kamera)")
        kopf += ", ".join(teile) or "fertig"
    if r.get("lage"):
        kopf += f"; Netz am Modell angelegt ({r['lage'].get('drehung_z')}° um Z)"
    return kopf


def register_referenz_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Referenz-Werkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""
    from .tools import ADDITIVE, READ_ONLY

    @tool("referenzen", "Referenzen",
          "References of the open project (photos or phone videos of the real object in <project>/referenzen/): state "
          "and progress of Object Capture and measurements, reference mesh size, measured dimensions with sigma. "
          "name + warten_s waits until the running job of that reference is done (use it after referenz_video).",
          READ_ONLY)
    async def referenzen(
        name: Annotated[str | None, Field(description="Reference name (folder name), or None for all")] = None,
        warten_s: Annotated[float, Field(ge=0, le=900, description="Wait up to this long for a running job")] = 0,
    ) -> CallToolResult:
        res = await t.work("liest die Referenzen" if not warten_s else f"wartet auf die Referenz {name}",
                           svc.referenzen, name, warten_s)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        liste = res.get("referenzen") or []
        if not liste:
            return fmt.result("Keine Referenzen im Projekt. Video: referenz_video(pfad, masz={\"laenge\": …}); "
                              "Fotos: referenz_fotos(pfade); dann referenz_vermessen.", res)
        zeilen = [f"{fmt.plural(len(liste), 'Referenz', 'Referenzen')}:"] + [eintrag_text(r) for r in liste]
        for r in liste:
            if r.get("messung_ergebnis") and (name or len(liste) == 1):
                zeilen.append("")
                zeilen.append(ergebnis_text(r["messung_ergebnis"]))
        werkzeuge = res.get("werkzeuge") or {}
        fehlt = [n for n, k in (("kevcad-capture", "kevcad_capture"), ("fotomess", "fotomess")) if not werkzeuge.get(k)]
        if fehlt:
            zeilen.append(f"Achtung, es fehlt: {', '.join(fehlt)} (./build.sh baut und installiert beides).")
        return fmt.result("\n".join(zeilen), res)

    @tool("referenz_video", "Referenz aus Video",
          "Start Apple Object Capture on a phone video of the real object (kevcad-capture, in the background, about "
          "1 min for 'schnell': 60 frames, 1920 px; 'genau': 120 frames, 2880 px, ~3x longer). Result: a scaled "
          "reference mesh (mm, Z up) shown semi-transparent in the viewer next to/over the model, camera poses for "
          "the photo view, and a report (hull and main body size). Scale needs one known real dimension: masz "
          "{'laenge': mm} (longest horizontal extent), or 'breite', 'hoehe', 'grund_laenge', 'grund_breite'. "
          "auflage=true when the object lies on a support that ends up in the mesh (wooden disk, table). von/bis "
          "(seconds) use only a part of the video (e.g. before the object was turned over). Returns at once; then "
          "referenzen(name, warten_s=…) to wait. Object must stay still during the video.", ADDITIVE)
    async def referenz_video(
        pfad: Annotated[str, Field(description="Absolute path of the video (.mov/.mp4)")],
        masz: Annotated[dict[str, float] | None, Field(description="Known dimension for the scale, e.g. "
                                                                   "{\"laenge\": 180}")] = None,
        auflage: Annotated[bool, Field(description="Object lies on a support that is part of the mesh")] = False,
        von: Annotated[float | None, Field(ge=0, description="Start of the used section in seconds")] = None,
        bis: Annotated[float | None, Field(ge=0, description="End of the used section in seconds")] = None,
        name: Annotated[str | None, Field(description="Reference name (default: video file name)")] = None,
        einstellung: Annotated[Literal["schnell", "genau"], Field(description="Quality preset")] = "schnell",
        warten_s: Annotated[float, Field(ge=0, le=900, description="Wait up to this long for the result")] = 0,
    ) -> CallToolResult:
        res = await t.work("startet Object Capture", svc.referenz_video, pfad, name, masz, auflage, von, bis,
                           einstellung, warten_s)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Object Capture nicht gestartet: {err}", res)
        if res.get("referenz"):
            return fmt.result(eintrag_text(res["referenz"]), res)
        return fmt.result(f"Object Capture läuft für die Referenz {res.get('name')} (Ordner {res.get('ordner')}). "
                          f"Fortschritt sieht Kevin in der App; warten mit referenzen(\"{res.get('name')}\", "
                          "warten_s=300).", res)

    @tool("referenz_fotos", "Referenz aus Fotos",
          "Add photos of the real object as a reference (copied in working size to <project>/referenzen/<name>/fotos). "
          "Cameras and dimensions follow with referenz_vermessen (2 to 3 views about 90 degrees apart over a corner, "
          "plus one from higher or lower, are enough; studio photos on white are most precise).", ADDITIVE)
    async def referenz_fotos(
        pfade: Annotated[list[str], Field(description="Absolute paths of the photos (JPEG, PNG, HEIC)")],
        name: Annotated[str | None, Field(description="Reference name")] = None,
    ) -> CallToolResult:
        res = await t.work("legt Fotos als Referenz ab", svc.referenz_fotos, pfade, name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        return fmt.result(f"Referenz {res.get('name')}: {fmt.plural(len(res.get('fotos') or []), 'Foto', 'Fotos')} "
                          f"abgelegt. Weiter mit referenz_vermessen(\"{res.get('name')}\", freie_masse=[…]).", res)

    @tool("referenz_vermessen", "Maße aus Referenz",
          "Measure the free param() dimensions of model.py from a reference (video or photos) with fotomess: model.py "
          "is rebuilt with each free dimension changed (shown parts only, no Kulisse), the model edges are fitted "
          "to the images (cameras, focal length and dimensions together), then sigma per dimension and "
          "recommendations (which dimension to measure by hand, which extra view would help most). One dimension "
          "must stay fixed as the scale (bekannte_masse, e.g. {\"breite\": 180}). quelle: reference name or the path "
          "of a video (creates the reference). Optional model.py function messmodell() gives defaults (frei, "
          "bekannt, farbteile, zwillinge, maske, vorgaben, grenzen; see skill kev-cad). Takes 1 to 2 minutes; the "
          "photos with fitted cameras appear in the app's photo view. Does not change model.py: Kevin applies the "
          "values with 'Maße übernehmen'. Always check the control images (red points without partner = model "
          "error).", ADDITIVE)
    async def referenz_vermessen(
        quelle: Annotated[str | None, Field(description="Reference name or video path")] = None,
        freie_masse: Annotated[list[str] | None, Field(description="param() names to measure")] = None,
        bekannte_masse: Annotated[dict[str, float] | None, Field(description="Fixed known dimensions in mm "
                                                                             "(scale), e.g. {\"breite\": 180}")] = None,
        bilder: Annotated[int, Field(ge=1, le=24, description="Number of video frames to use (photos: all)")] = 8,
        vorgaben: Annotated[dict[str, list[float]] | None,
                            Field(description="Soft priors {name: [mean, sigma]} in mm")] = None,
        grenzen: Annotated[dict[str, list[float]] | None,
                           Field(description="Hard limits {name: [min, max]} in mm")] = None,
        maske: Annotated[dict[str, Any] | None,
                         Field(description="Mask options: maske ('vision+farbe' | 'vision' | 'weiss'), farbe_hsv "
                                           "[[h_lo, h_hi], s_min, v_min] (OpenCV H 0..180, may wrap over 0), "
                                           "ausschluss_hsv (support color to drop), gehaeuse (bool), umkreis")] = None,
        von: Annotated[float | None, Field(ge=0, description="Video section start in s")] = None,
        bis: Annotated[float | None, Field(ge=0, description="Video section end in s")] = None,
        kb_brennweite: Annotated[float | None, Field(gt=0, description="35 mm equivalent focal length if known")]
        = None,
    ) -> CallToolResult:
        res = await t.work("vermisst die Referenz", svc.referenz_vermessen, quelle, freie_masse, bekannte_masse, bilder,
                           vorgaben, grenzen, maske, von, bis, kb_brennweite)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Vermessen fehlgeschlagen: {err}", res)
        return fmt.result(ergebnis_text(res), res)

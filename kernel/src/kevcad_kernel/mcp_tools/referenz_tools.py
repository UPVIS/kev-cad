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

REFERENZ_TOOL_NAMES: tuple[str, ...] = ("referenzen", "referenz_video", "referenz_fotos", "referenz_vermessen",
                                        "referenz_fotoansicht", "referenz_abweichung", "referenz_massstab")


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


def _vz(v: Any) -> str:
    """Abweichung mit Vorzeichen: „+1,2“ / „−0,8“."""
    if not isinstance(v, (int, float)):
        return "–"
    return ("+" if v > 0 else "−" if v < 0 else "") + fmt.num(abs(v), 1)


def abweichung_text(a: dict[str, Any], name: str | None = None, alle: bool = True) -> list[str]:
    """Kennzahlen der Abweichung (positiv = Referenz außerhalb des Modells) als Tabelle je Teil."""
    if not a:
        return []
    if a.get("stand") != "done":
        return [f"Abweichung: {a.get('meldung') or a.get('stand')}"]
    teile = a.get("teile") or []
    zeilen = [f"Abweichung zum Referenznetz{(' ' + name) if name else ''} (Lauf {a.get('run')}, Punkte weiter als "
              f"{_mm(a.get('grenze_mm'), 0)} mm zählen als ohne Referenz; positiv = Referenz außerhalb des Modells):"]
    rows = [["Teil", "mittel", "95 %", "größte", "Versatz", "abgedeckt"]]
    for t in teile if alle else teile[:12]:
        rows.append([t["teil"], _mm(t.get("mittel_mm")), _mm(t.get("p95_mm")), _mm(t.get("max_mm")),
                     _vz(t.get("versatz_mm")), f"{fmt.num((t.get('abgedeckt') or 0) * 100, 0)} %"])
    r = a.get("referenz_netz") or a.get("referenz")  # MCP: referenz_netz; REF_LIST-Kurzfassung: referenz
    if isinstance(r, dict):
        rows.append(["(Referenznetz zum Modell)", _mm(r.get("mittel_mm")), _mm(r.get("p95_mm")), _mm(r.get("max_mm")),
                     _vz(r.get("versatz_mm")), f"{fmt.num((r.get('abgedeckt') or 0) * 100, 0)} %"])
    zeilen.append(fmt.table(rows, right={1, 2, 3, 4, 5}))
    groesst = max((t for t in teile if t.get("max_mm") is not None), key=lambda t: t["max_mm"], default=None)
    if groesst and groesst.get("ort_max"):
        o = groesst["ort_max"]
        zeilen.append(f"Größte Abweichung {_mm(groesst['max_mm'])} mm an {groesst['teil']} bei "
                      f"({fmt.num(o[0], 0)}; {fmt.num(o[1], 0)}; {fmt.num(o[2], 0)})")
    zeilen.append(f"Legende in der App: ±{_mm(a.get('skala_mm'))} mm"
                  + (" (fest)" if a.get("skala_fest") else " (automatisch)"))
    if a.get("angelegt") is False:
        zeilen.append("Achtung: Netz nicht am Modell angelegt, der Lagefehler steckt in den Zahlen (erst "
                      "referenz_vermessen).")
    return zeilen


def eintrag_text(r: dict[str, Any]) -> str:
    z = r.get("zustand")
    art = {"video": "Video", "scan": "Scan"}.get(str(r.get("art")), "Fotos")
    kopf = f"- {r.get('name')} ({art}: {r.get('quelle')}): "
    if z == "rechnet":
        lauf = ('Auswertung' if r.get('art') == 'scan' else 'Object Capture') if r.get('laeuft') == 'capture' \
            else 'Vermessen'
        kopf += (f"{lauf} läuft" + (f" ({r['phase']})" if r.get("phase") else "") + ", "
                 f"{fmt.num((r.get('fortschritt') or 0) * 100, 0)} %" + (f" ({r.get('text')})" if r.get("text") else ""))
    elif z == "fehler":
        kopf += f"Fehler: {r.get('meldung')}"
    elif z == "leer":
        kopf += "noch nichts gerechnet"
    else:
        teile = []
        if r.get("netz"):
            c = r.get("capture") or {}
            angaben = []
            if c.get("huelle"):
                angaben.append(f"Hülle mit Anbauten {_groesse(c['huelle'])}")
            if c.get("grundkoerper"):
                angaben.append(f"Grundkörper ohne Anbauten {_groesse(c['grundkoerper'])}")
            if c.get("bilder"):
                angaben.append(f"{c.get('ausgerichtet')} von {c.get('bilder')} Bildern")
            teile.append("Netz" + (f" ({', '.join(angaben)})" if angaben else ""))
        if r.get("messung"):
            teile.append(f"vermessen ({fmt.plural(int(r.get('fotos') or 0), 'Foto', 'Fotos')} mit Kamera)")
        kopf += ", ".join(teile) or "fertig"
    if r.get("lage"):
        kopf += f"; Netz am Modell angelegt ({r['lage'].get('drehung_z')}° um Z)"
    m = r.get("massstab")
    if m and m.get("faktor"):
        kopf += f"; Maßstab nachträglich gesetzt (Faktor {fmt.num(m['faktor'], 4)}, {_mm(m.get('mm'))} mm)"
    a = r.get("abweichung")
    if a and a.get("stand") == "done" and a.get("teile"):
        mittel = [t["mittel_mm"] for t in a["teile"] if t.get("mittel_mm") is not None]
        groesst = [t["max_mm"] for t in a["teile"] if t.get("max_mm") is not None]
        if mittel:
            kopf += (f"; Abweichung zum Modell im Mittel {_mm(sum(mittel) / len(mittel))} mm, größte "
                     f"{_mm(max(groesst))} mm")
    return kopf


def register_referenz_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Referenz-Werkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""
    from .tools import ADDITIVE, READ_ONLY, VIEWER

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
            if r.get("abweichung") and (name or len(liste) == 1):
                zeilen.append("")
                zeilen += abweichung_text(r["abweichung"], alle=bool(name))
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

    @tool("referenz_fotoansicht", "Fotoansicht",
          "Show Kevin a reference photo in the app's photo view: the photo seen through its fitted camera behind the "
          "current model (updates live after every run), with model opacity (deckkraft 0..1) and mode 'ueberlagern' "
          "(overlay) or 'differenz' (red = only in the photo, blue = only in the model; needs the mask from "
          "referenz_vermessen). foto: 1-based number or image name; satz 'messung' (fotomess, default) or 'capture' "
          "(Object Capture frames). Returns the silhouette overlap (IoU). bild_zeigen=true also returns the image to "
          "you (only when you need to look; Kevin does not want unnecessary screenshots). aus=true closes it.", VIEWER)
    async def referenz_fotoansicht(
        name: Annotated[str | None, Field(description="Reference name")] = None,
        foto: Annotated[int | str | None, Field(description="Photo number (1-based) or name")] = None,
        modus: Annotated[Literal["ueberlagern", "differenz"] | None, Field(description="Display mode")] = None,
        deckkraft: Annotated[float | None, Field(ge=0, le=1, description="Model opacity over the photo")] = None,
        satz: Annotated[Literal["messung", "capture"] | None, Field(description="Photo set")] = None,
        aus: Annotated[bool, Field(description="Close the photo view")] = False,
        bild_zeigen: Annotated[bool, Field(description="Also return the image to you")] = False,
    ) -> CallToolResult:
        res = await t.work("zeigt die Fotoansicht" if not aus else "schließt die Fotoansicht", svc.referenz_fotoansicht,
                           name, foto, satz, modus, deckkraft, aus, bild_zeigen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Fotoansicht nicht möglich: {err}", res)
        png = res.get("png") or b""
        text = str(res.get("message") or "")
        if res.get("bild_fehler"):
            text += f"\nKein Bild: {res['bild_fehler']}"
        data = {k: v for k, v in res.items() if k != "png"}
        return fmt.result(text, data, extra=[fmt.image_block(png)] if png else None)

    @tool("referenz_abweichung", "Abweichung zur Referenz",
          "Deviation between the model and a reference mesh (Object Capture or iPhone scan), per part: mean, 95 % and "
          "largest distance in mm, signed offset (positive = the real object sticks out beyond the model, the model "
          "is too small there; negative = the model is too big) and the covered share (points without reference "
          "within grenze_mm, e.g. the unseen bottom, do not count). The kernel recomputes it in the background after "
          "every run (about 1 s); this call waits for the current state. zeigen=true switches on the color map in "
          "Kevin's viewer (auf='modell': colors on the model parts, auf='referenz': colors on the reference mesh) "
          "with a legend in mm. skala_mm fixes the legend range, grenze_mm the coverage limit (0 = automatic again). "
          "Use it after referenz_vermessen (the mesh is then aligned to the model) to see where the model still "
          "differs from the real object.", VIEWER)
    async def referenz_abweichung(
        name: Annotated[str | None, Field(description="Reference name (default: the only one)")] = None,
        teile: Annotated[list[str] | None, Field(description="Only these parts or groups")] = None,
        zeigen: Annotated[bool, Field(description="Show the color map in the viewer")] = False,
        auf: Annotated[Literal["modell", "referenz"], Field(description="Color map on the model or on the mesh")]
        = "modell",
        skala_mm: Annotated[float | None, Field(ge=0, le=500, description="Legend range ± mm (0 = automatic)")] = None,
        grenze_mm: Annotated[float | None, Field(ge=0, le=500, description="Beyond this distance a point counts as "
                                                                          "without reference (0 = automatic)")]
        = None,
    ) -> CallToolResult:
        res = await t.work("vergleicht Modell und Referenz", svc.referenz_abweichung, name, teile, grenze_mm,
                           skala_mm, zeigen, auf)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Abweichung nicht gerechnet: {err}", res)
        zeilen = abweichung_text({**res, "stand": "done"}, res.get("referenz"))
        if res.get("ms") is not None:
            ms = float(res["ms"])
            zeilen.append(f"Gerechnet in {fmt.num(ms / 1000, 1)} s (im Hintergrund nach dem Lauf; unveränderte "
                          "Teile kommen aus dem Zwischenspeicher).")
        if res.get("gezeigt"):
            zeilen.append(f"Kevin sieht die Farbkarte {'auf dem Modell' if auf == 'modell' else 'auf dem Netz'} "
                          "(blau = Modell zu groß, grün = passt, rot = Modell zu klein, grau = ohne Referenz).")
        for h in res.get("hinweise") or []:
            zeilen.append(f"Hinweis: {h}")
        return fmt.result("\n".join(zeilen), res)

    @tool("referenz_massstab", "Maßstab der Referenz",
          "Set the scale of a reference afterwards from one known real dimension (Object Capture without LiDAR has no "
          "true scale): either two points on the reference mesh (world mm as shown in the viewer, e.g. from "
          "measure on the mesh or picked by Kevin; they are snapped to the mesh) or kante = 'laenge' | 'breite' | "
          "'hoehe' | 'grund_laenge' | 'grund_breite' (hull of the mesh) or the name of a measured param, plus the "
          "real distance mm. Mesh, point cloud, Object Capture cameras and report scale with it; the measurement "
          "scales too when kante names a measured dimension. Not for iPhone scans (already metric). Afterwards "
          "referenz_vermessen again if the model was measured against the old scale.", ADDITIVE)
    async def referenz_massstab(
        mm: Annotated[float, Field(gt=0, description="Real distance in mm")],
        name: Annotated[str | None, Field(description="Reference name (default: the only one)")] = None,
        punkte: Annotated[list[list[float]] | None, Field(description="Two points [[x, y, z], [x, y, z]] in mm on "
                                                                      "the mesh")] = None,
        kante: Annotated[str | None, Field(description="Named dimension instead of points")] = None,
    ) -> CallToolResult:
        res = await t.work("setzt den Maßstab der Referenz", svc.referenz_massstab, name, mm, punkte, kante)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Maßstab nicht gesetzt: {err}", res)
        zeilen = [str(res.get("text") or "")]
        if res.get("punkte_am_netz"):
            a, b = res["punkte_am_netz"]
            zeilen.append(f"Punkte am Netz: ({', '.join(fmt.num(x, 1) for x in a)}) und "
                          f"({', '.join(fmt.num(x, 1) for x in b)}) mm")
        if res.get("messung_skaliert"):
            zeilen.append("Die Vermessung ist mitskaliert; beim nächsten referenz_vermessen gilt das Maß als bekannt.")
        for h in res.get("hinweise") or []:
            zeilen.append(f"Hinweis: {h}")
        return fmt.result("\n".join(zeilen), res)

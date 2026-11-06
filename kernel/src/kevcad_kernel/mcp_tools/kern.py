"""Kernsatz der MCP-Werkzeuge (V2-2): die Werkzeuge der täglichen Arbeit.

``status`` (Lagebild), ``projekt``, ``modell``, ``run``, ``execute``, ``parts`` (samt Stückliste), ``measure`` (samt
Kevins Auswahl), ``view`` (Kamera, Darstellung, Fokus, Sichtbarkeit, Schnitt, Hervorheben, Anmerkungen), ``pruefen``
(samt Bedingungen und Montage), ``ansichten`` (samt Kevins Bild), ``katalog`` (Lagerteile und Materialien),
``export`` (samt PDF), ``feedback`` (Kevins Sprach-Feedback, feedback_tools.py). Die Fachbereiche haben je ein Werkzeug
mit ``aktion`` (fach.py).

Wo eine bisherige Funktion passt, rufen die Werkzeuge ihren Griff (griffe.py) und lassen den JSON-Block weg, den die
Griffe für Clients ohne ``structuredContent`` anhängen: Der Agent liest nur den Text, die Daten stehen weiter in
``structuredContent``. Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult
from pydantic import Field

from kevcad_kernel.service import KernelService

from . import format as fmt
from .feedback_tools import hintergrund_befehl, register_feedback_tool, stand_text
from .griffe import Griffe, ohne_json
from .laufbericht import Gedaechtnis, bericht, gruppe
from .tracking import claude_session

KERN_NAMEN: tuple[str, ...] = ("status", "projekt", "modell", "run", "execute", "parts", "measure", "view", "pruefen",
                               "ansichten", "katalog", "export", "feedback")

StandardView = Literal[
    "top", "bottom", "front", "back", "left", "right", "iso", "iso_front_left", "iso_back_right", "iso_back_left"
]
Projection = Literal["perspective", "orthographic"]
Display = Literal["shaded_edges", "shaded", "wireframe", "xray"]  # Bilder außerhalb des Fensters (ansichten)
ViewDisplay = Literal["solid", "material", "technical", "xray", "wireframe", "shaded_edges", "shaded"]
ExportFormat = Literal["step", "stl", "3mf", "glb", "bom_csv", "einkaufsliste_csv", "pdf"]
KatalogArt = Literal["rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil",
                     "nutprofil", "holz", "platte", "schraube", "mutter", "scheibe", "zukaufteil", "material"]
RUN_TIMEOUT_MAX_S = 900.0
KAMERA_ABFRAGE_S = 2.0  # status: so lange höchstens auf die Kameradaten der App warten
AUSWAHL_DETAILS = 4  # status: so viele ausgewählte Elemente mit Werten


def erster_text(res: CallToolResult) -> str:
    return next((b.text for b in res.content if getattr(b, "type", None) == "text"), "")


def kamera_text(cam: dict[str, Any] | None) -> str:
    """„Ansicht: iso, perspektivisch, Ziel (310; 0; 180), Abstand 2.100 mm“ aus den Kameradaten der App."""
    if not isinstance(cam, dict) or not cam:
        return ""
    from .tools import PROJECTION_NAMES, VIEW_NAMES

    bits = []
    if cam.get("view"):
        bits.append(VIEW_NAMES.get(cam["view"], cam["view"]))
    elif isinstance(cam.get("direction"), list):
        bits.append(f"Blick {fmt.vec(cam['direction'])}")
    if cam.get("projection"):
        bits.append(PROJECTION_NAMES.get(cam["projection"], cam["projection"]).split(" ")[0])
    if isinstance(cam.get("target"), list):
        bits.append(f"Ziel {fmt.vec(cam['target'], 0)}")
    if isinstance(cam.get("distance"), (int, float)) and cam.get("projection") != "orthographic":
        bits.append(f"Abstand {fmt.num(cam['distance'], 0)} mm")
    if isinstance(cam.get("ortho_height_mm"), (int, float)):
        bits.append(f"Bildhöhe {fmt.num(cam['ortho_height_mm'], 0)} mm")
    return "Ansicht: " + ", ".join(bits)


def lage_kamera(k: Any) -> dict[str, Any] | None:
    """Kamera aus dem Lagebild (LAGE, PROTOCOL.md) in den Feldern, die ``kamera_text`` und ``status`` kennen."""
    if not isinstance(k, dict) or not k:
        return None
    return {"view": k.get("ansicht"), "direction": k.get("richtung"), "projection": k.get("projektion"),
            "target": k.get("ziel"), "distance": k.get("abstand"), "ortho_height_mm": k.get("ortho_hoehe")}


def lage_zeilen(lage: dict[str, Any]) -> list[str]:
    """Was das Lagebild über die Kamera hinaus sagt: Blick durch eine Kamera, Teil unter der Maus, was vom Üblichen
    abweicht (Darstellung, Schnitt, Explosion, Animation)."""
    zeilen: list[str] = []
    kamera = lage.get("kamera") if isinstance(lage.get("kamera"), dict) else {}
    if kamera.get("durch"):
        zeilen.append(f"Blick durch {kamera['durch']}")
    maus = lage.get("maus") if isinstance(lage.get("maus"), dict) else None
    if maus:
        ort = f" bei {fmt.vec(maus['punkt'], 0)}" if isinstance(maus.get("punkt"), list) else ""
        zeilen.append(f"Maus auf {maus.get('ref') or maus.get('teil')}{ort}")
    anders: list[str] = []
    if lage.get("darstellung") not in (None, "shaded_edges"):
        anders.append(f"Darstellung {lage['darstellung']}")
    if lage.get("schnitt"):
        anders.append("Schnitt an")
    if isinstance(lage.get("explosion"), (int, float)) and lage["explosion"] > 0:
        anders.append(f"Explosion {fmt.num(lage['explosion'], 2)}")
    anim = lage.get("animation") if isinstance(lage.get("animation"), dict) else None
    if anim:
        anders.append(f"Animation {anim.get('name')}" + (" läuft" if anim.get("spielt") else ""))
    if anders:
        zeilen.append(" · ".join(anders))
    return zeilen


def teil_zeile(p: dict[str, Any], *, voll: bool = False) -> str:
    """Eine Zeile je Teil: Hüllmaß, Masse, Lager/Druck/Material, Mitte; ``voll`` mit Hüllquader, Volumen, Fläche."""
    bb = p.get("bbox") or {}
    bits = [fmt.size_text(bb)]
    if isinstance(p.get("mass"), (int, float)):
        bits.append(f"{fmt.num(p['mass'], 1)} g")
    stock = p.get("stock") if isinstance(p.get("stock"), dict) else None
    if stock and stock.get("id"):
        st = f"Lagerteil {stock['id']}"
        if isinstance(stock.get("laenge"), (int, float)):
            st += f" {fmt.num(stock['laenge'], 1)} mm"
        g = stock.get("gehrung") or []
        if any(isinstance(v, (int, float)) and v for v in g):
            st += f" Gehrung {fmt.num(g[0], 1)}°/{fmt.num(g[1], 1)}°"
        bits.append(st)
    elif isinstance(p.get("druckteil"), dict):
        bits.append("Druckteil " + str(p["druckteil"].get("material") or p.get("material") or ""))
    elif p.get("material"):
        bits.append(str(p["material"]))
    if p.get("inventar") == "fehlt":
        bits.append("NICHT AUS DEM INVENTAR")
    lo, hi = bb.get("min"), bb.get("max")
    if voll and isinstance(lo, list) and isinstance(hi, list):
        bits.append(f"von {fmt.vec(lo, 1)} bis {fmt.vec(hi, 1)}")
        if isinstance(p.get("volume"), (int, float)):
            bits.append(f"{fmt.num(p['volume'], 1)} mm³")
        if isinstance(p.get("area"), (int, float)):
            bits.append(f"{fmt.num(p['area'], 1)} mm²")
        bits.append(f"{p.get('faces', '?')} Flächen, {p.get('edges', '?')} Kanten")
    elif isinstance(lo, list) and isinstance(hi, list):
        bits.append("Mitte " + fmt.vec([(a + b) / 2 for a, b in zip(lo, hi)], 0))
    if p.get("visible") is False:
        bits.append("ausgeblendet")
    return f"- {p.get('name', '?')}: " + ", ".join(bits)


def register_kern_tools(mcp: MCPServer, t: Any, svc: KernelService, griffe: Griffe, gedaechtnis: Gedaechtnis,
                        hinzufuegen: Callable[..., Any]) -> None:
    """Registriert den Kernsatz. ``hinzufuegen(name, titel, beschreibung, annotations)`` ist der Dekorator, der ein
    Werkzeug mit Fehlerschutz und Sitzungstafel am Server anmeldet."""
    from .tools import ADDITIVE, READ_ONLY, VIEWER, WRITES, ToolInputError, check_refs, short_refs

    tool = hinzufuegen

    # ---------------------------------------------------------------------------------------------------- Lagebild

    @tool("status", "Lagebild",
          "Shared picture of the situation, call it first and whenever you lose track: open project and model.py "
          "path, kernel and app, last run in one line, open findings, Kevin's selection with values, his camera "
          "(named view or direction, target, distance) and what is hidden or isolated.", READ_ONLY)
    async def status() -> CallToolResult:
        res = await t.work("schaut auf den Stand", svc.status)
        project = res.get("project") or None
        zeilen: list[str] = []
        data: dict[str, Any] = {}
        if project:
            zeilen.append(f"Projekt {project.get('name', '?')} (model.py: {project.get('model', '?')})")
            data["projekt"] = {k: project.get(k) for k in ("name", "path", "model")}
        else:
            zeilen.append("Kein Projekt offen: projekt(pfad) öffnet eins, projekt(pfad, neu=true) legt eins an.")
        kernel = {"ready": "bereit", "busy": "rechnet", "error": "Fehler"}.get(res.get("kernel"), res.get("kernel"))
        app = bool(res.get("app_connected"))
        settings = res.get("settings") or {}
        nachricht = f" ({res['message']})" if res.get("kernel") != "ready" and res.get("message") else ""
        zeilen.append(f"Kernel {kernel}{nachricht}"
                      + f" · App {'verbunden' if app else 'nicht verbunden (Ansicht, Bilder, Auswahl gehen nicht)'}"
                      + (" · Auto-Lauf an" if settings.get("auto_run") else ""))
        data.update({"kernel": res.get("kernel"), "app": app, "auto_run": bool(settings.get("auto_run"))})
        feedback = res.get("feedback") if isinstance(res.get("feedback"), dict) else None
        if feedback:  # V2-6: Spricht Kevin gerade, wartet ein Paket?
            if text := stand_text(feedback):
                zeilen.append(text)
            if app:
                zeilen.append("Auf Kevin warten: feedback(); im Hintergrund, damit er dich weckt: "
                              + hintergrund_befehl(getattr(svc, "mcp_port", None)))
            data["feedback"] = {k: feedback.get(k) for k in ("stand", "offen", "name")}

        last = res.get("last_run") if isinstance(res.get("last_run"), dict) else None
        teile = list(last.get("parts") or []) if last else []
        if last:
            if last.get("ok") is False:
                err = last.get("error") if isinstance(last.get("error"), dict) else {"message": last.get("error")}
                zeilen.append(f"Letzter Lauf {last.get('run', '?')}: Fehler"
                              + (f" in Zeile {err.get('line')}" if err.get("line") else "") + f": {err.get('message')}")
            else:
                n_gruppen = len({gruppe(str(p.get("name"))) for p in teile})
                zeilen.append(f"Letzter Lauf {last.get('run', '?')}: ok, {fmt.plural(len(teile), 'Teil', 'Teile')}"
                              + (f" in {fmt.plural(n_gruppen, 'Baugruppe', 'Baugruppen')}"
                                 if 0 < n_gruppen < len(teile) else "")
                              + (f", {fmt.ms_text(last['duration_ms'])}" if last.get("duration_ms") is not None
                                 else ""))
            data["lauf"] = {"run": last.get("run"), "ok": last.get("ok"), "teile": len(teile)}
        elif project:
            zeilen.append("Noch kein Lauf: run aufrufen.")

        # Prüfung: Stand und die offenen Fehler mit Teilen
        pr = res.get("pruefung") if isinstance(res.get("pruefung"), dict) else None
        if pr is not None and project:
            z = pr.get("zaehler") or {}
            zahl = ", ".join(f"{z[k]} {n}" for k, n in (("fehler", "Fehler"), ("warnung", "Warnungen"),
                                                          ("hinweis", "Hinweise")) if z.get(k))
            text = f"Prüfung (Lauf {pr.get('run', '?')}): " + (zahl or "keine Befunde")
            if pr.get("laeuft"):
                text += f"; Prüfung für Lauf {pr['laeuft']} läuft"
            elif pr.get("state") == "teilweise" or pr.get("hintergrund") or pr.get("statik_hintergrund"):
                text += "; rechnet im Hintergrund weiter (pruefen wartet darauf)"
            zeilen.append(text)
            data["pruefung"] = {k: pr.get(k) for k in ("run", "state", "zaehler", "laeuft")}
            if z.get("fehler"):
                check = await t.work(None, svc.pruefen, 0.0)
                fehler = [b for b in (check or {}).get("befunde") or [] if b.get("schwere") == "fehler"]
                for b in fehler[:3]:
                    zeilen.append(f"- Offen: {b.get('art')}: {' ↔ '.join((b.get('teile') or [])[:3])}")
                if len(fehler) > 3:
                    zeilen.append(f"- … und {len(fehler) - 3} weitere (pruefen)")
        inv = res.get("inventar") if isinstance(res.get("inventar"), dict) else None
        if inv is not None and project:
            if not inv.get("regel", True):
                zeilen.append("Inventar-Regel: aus (von Kevin für dieses Projekt abgeschaltet)")
            elif inv.get("verstoesse"):
                bad = inv["verstoesse"]
                zeilen.append(f"Inventar-Regel: {fmt.plural(len(bad), 'Verstoß', 'Verstöße')}: {short_refs(bad, 6)}")

        # Kevins Auswahl mit Werten (gemessen im Kernel)
        sel = res.get("selection") or {}
        refs = list(sel.get("refs") or [])
        if refs:
            zeilen.append(f"Auswahl (Lauf {sel.get('run', '?')}):")
            details = await t.work(None, svc.selection)
            by_ref = {d["refs"][0]: d for d in (details or {}).get("details") or []
                      if isinstance(d, dict) and d.get("refs") and d.get("ok", True) is not False}
            for ref in refs[:AUSWAHL_DETAILS]:
                d = by_ref.get(ref)
                zeilen.append("- " + (fmt.measure_line(d) if d else ref))
            if len(refs) > AUSWAHL_DETAILS:
                zeilen.append(f"- … und {len(refs) - AUSWAHL_DETAILS} weitere (measure ohne refs zeigt alle)")
        else:
            zeilen.append("Auswahl: nichts")
        data["auswahl"] = refs

        # Was Kevin sieht: das Lagebild der App (lage-1, unter 50 ms). Ältere Apps nennen die Kamera nur mit einem Bild
        # (SCREENSHOT_RES.camera); dafür genügt ein winziges.
        lage: dict[str, Any] | None = None
        if app and project:
            lagebild = getattr(svc, "lagebild", None)
            antwort = await t.work(None, lagebild) if lagebild else None
            lage = antwort if isinstance(antwort, dict) and antwort.get("quelle") == "app" else None
            if lage:
                cam = lage_kamera(lage.get("kamera"))
            else:
                shot = await t.work(None, svc.screenshot, 16, 16, "current", None, True, KAMERA_ABFRAGE_S)
                cam = shot.get("camera") if isinstance(shot, dict) and shot.get("ok") else None
            text = kamera_text(cam)
            if text:
                zeilen.append(text)
                data["kamera"] = {k: cam.get(k) for k in ("view", "projection", "target", "direction", "distance",
                                                          "ortho_height_mm")}
            if lage:
                zeilen.extend(lage_zeilen(lage))
                data["maus"] = lage.get("maus")

        # Sichtbarkeit: vom Lagebild, sonst wie der Kernel sie kennt (Befehle über view; Klicks im Teilebaum fehlen dann)
        if teile:
            aktuell = await t.work(None, svc.parts)
            aktuell = aktuell if isinstance(aktuell, list) else teile
            if lage and isinstance(lage.get("verborgen"), list):
                weg = {str(n) for n in lage["verborgen"]}
                versteckt = [str(p.get("name")) for p in aktuell if str(p.get("name")) in weg]
                sichtbar = [str(p.get("name")) for p in aktuell if str(p.get("name")) not in weg]
            else:
                versteckt = [str(p.get("name")) for p in aktuell if p.get("visible") is False]
                sichtbar = [str(p.get("name")) for p in aktuell if p.get("visible") is not False]
            if not versteckt:
                zeilen.append(f"Sichtbar: alle {len(aktuell)} Teile")
            elif len(sichtbar) <= 6:
                zeilen.append(f"Sichtbar nur: {', '.join(sichtbar) or 'nichts'} ({len(versteckt)} ausgeblendet)")
            else:
                zeilen.append(f"Ausgeblendet: {short_refs(versteckt, 6)}")
            data["ausgeblendet"] = len(versteckt)
        return fmt.result("\n".join(zeilen), data, json_block=False)

    register_feedback_tool(tool, t, svc, READ_ONLY)

    # ----------------------------------------------------------------------------------------------- Projekt, Modell

    @tool("projekt", "Projekt",
          "Open an existing project folder (with model.py), or create one with neu=true (vorlage 'example' writes a "
          "small sample model, 'empty' only the imports). A bare name means ~/Documents/Kev CAD/<name>.", WRITES)
    async def projekt(
        pfad: Annotated[str, Field(description="Project folder: absolute path, ~/..., or a bare project name")],
        neu: Annotated[bool, Field(description="Create a new project instead of opening one")] = False,
        vorlage: Annotated[Literal["example", "empty"], Field(description="neu: starting content of model.py")]
        = "example",
    ) -> CallToolResult:
        if neu:
            res = await griffe.aufrufen("project_new", {"path": pfad, "template": vorlage}, aufruf="projekt")
        else:
            res = await griffe.aufrufen("project_open", {"path": pfad}, aufruf="projekt")
        if not res.is_error:
            gedaechtnis.vergessen(claude_session.get())  # anderes Projekt: der nächste Lauf ist wie der erste
        return ohne_json(res)

    @tool("modell", "model.py",
          "Read model.py of the open project, or overwrite it with code (complete new content). Prefer your own file "
          "tools when you have them; after writing call run.", WRITES)
    async def modell(
        code: Annotated[str | None, Field(description="Complete new content of model.py; omit to read it")] = None,
    ) -> CallToolResult:
        if code is None:
            return ohne_json(await griffe.aufrufen("model_read", {}, aufruf="modell"))
        return ohne_json(await griffe.aufrufen("model_write", {"code": code}, aufruf="modell"))

    # ---------------------------------------------------------------------------------------------------------- Lauf

    @tool("run", "Modell ausführen",
          "Execute model.py; parts stream live into Kevin's viewer. Returns what you need next: ok or the failing "
          "line with excerpt and hint (isError), new and changed parts with the difference to the last run you saw "
          "(unchanged ones only counted), new or changed findings first (known ones counted), check state and times. "
          "Change dimensions with params (no file edit, about 2 s): run(params={\"breite\": 140}). detail 'teile' "
          "adds every part, 'voll' everything. A run that changed a project file becomes a version; titel names it "
          "in Kevin's words.", ADDITIVE)
    async def run(
        params: Annotated[dict[str, float] | None,
                          Field(description="Overrides for param() values by name, e.g. {\"breite\": 140}")] = None,
        detail: Annotated[Literal["kurz", "teile", "voll"],
                          Field(description="kurz = changes only, teile = plus every part, voll = everything")]
        = "kurz",
        titel: Annotated[str | None, Field(max_length=160, description=(
            "Short German description of a larger change in Kevin's words; becomes the title of the new version"))]
        = None,
        slow_ms: Annotated[int, Field(ge=0, le=10000, description="Slow motion pause in ms per step, 0 = off")] = 0,
        timeout_s: Annotated[float | None, Field(ge=10, le=RUN_TIMEOUT_MAX_S, description=(
            "Time limit for model.py in seconds (default 120, at most 900); raise only after a time-limit failure"))]
        = None,
        warten_s: Annotated[float | None, Field(ge=0, le=120, description=(
            "Wait at most this long for the built-in check (default 3 s, 0 = not at all); if it still runs, call "
            "pruefen() before reporting done"))] = None,
    ) -> CallToolResult:
        activity = "führt model.py aus" + (" in Zeitlupe" if slow_ms else "")
        extra: dict[str, Any] = {}
        if titel and titel.strip():
            extra["titel"] = titel.strip()
        if timeout_s is not None:
            extra["timeout_s"] = float(timeout_s)
        if warten_s is not None:
            extra["warten_s"] = float(warten_s)
        res = await t.work(activity, svc.run, params, slow_ms, **extra)
        if isinstance(res, dict) and res.get("kevin_spricht"):  # V2-6: nichts gestartet
            return fmt.error_result(res["error"], {"kevin_spricht": True})
        sitzung = claude_session.get()
        text, data, fehler, stand = bericht(res, gedaechtnis.holen(sitzung), detail, params)
        if stand is not None:
            gedaechtnis.merken(sitzung, stand)
        return fmt.result(text, data, error=fehler, json_block=False)

    @tool("execute", "Python im Modell",
          "Run Python in the namespace of the last run (all model.py variables, build123d imported) to inspect "
          "geometry, e.g. `print(platte.bounding_box())`. Objects passed to show() appear as a translucent sketch. "
          "Returns stdout and the repr of the last expression; does not change model.py.", ADDITIVE)
    async def execute(
        code: Annotated[str, Field(description="Python code; the value of a final expression is returned")],
    ) -> CallToolResult:
        return ohne_json(await griffe.aufrufen("execute", {"code": code}))

    # ----------------------------------------------------------------------------------------- Teile und Stückliste

    @tool("parts", "Teile und Stückliste",
          "Parts of the last run. Without filter: every part in one line (size, mass, stock/print/material, centre); "
          "filter (part name or assembly prefix): those parts with bounding box, volume, area, faces and edges. "
          "stueckliste=true: bill of materials with positions, weight, guide prices, cut list per bar and the "
          "shopping list (format 'csv' as CSV). Use the names as references.", READ_ONLY)
    async def parts(
        filter: Annotated[str | None, Field(description="Part name or assembly prefix, e.g. 'Gestell'")] = None,
        stueckliste: Annotated[bool, Field(description="Bill of materials, cut list and shopping list instead")]
        = False,
        format: Annotated[Literal["text", "csv"], Field(description="stueckliste: text table or CSV")] = "text",
    ) -> CallToolResult:
        if stueckliste or format == "csv":
            res = ohne_json(await griffe.aufrufen("bom", {"format": format}, aufruf="parts(stueckliste=true)"))
            data = res.structured_content if isinstance(res.structured_content, dict) else {}
            kurz = {"run": data.get("run"), "totals": data.get("totals"), "positionen": len(data.get("lines") or []),
                    "warnings": data.get("warnings")}
            return CallToolResult(content=res.content, structured_content=kurz, is_error=res.is_error)
        res = await t.work("liest die Teileliste", svc.parts)
        if isinstance(res, dict):
            err = fmt.service_error(res)
            if err:
                return fmt.error_result(f"Teile nicht verfügbar: {err}")
            res = res.get("parts") or []
        items = [p for p in res or [] if isinstance(p, dict)]
        if not items:
            return fmt.result("Keine Teile. Erst run aufrufen (und in model.py show() benutzen).", {"teile": 0},
                              json_block=False)
        if filter:
            f = filter.strip().rstrip("/")
            treffer = [p for p in items if str(p.get("name")) == f or str(p.get("name")).startswith(f + "/")]
            if not treffer:
                namen = sorted({gruppe(str(p.get("name"))) for p in items})
                return fmt.error_result(f"Kein Teil und keine Baugruppe „{filter}“. Baugruppen: {', '.join(namen)}")
            zeilen = [f"{fmt.plural(len(treffer), 'Teil', 'Teile')} unter „{f}“:"]
            zeilen += [teil_zeile(p, voll=True) for p in sorted(treffer, key=lambda p: str(p.get("name")))]
            return fmt.result("\n".join(zeilen), {"teile": len(treffer), "namen": [p.get("name") for p in treffer]},
                              json_block=False)
        zeilen = [f"{fmt.plural(len(items), 'Teil', 'Teile')} (Details mit parts(filter=\"<Name oder Baugruppe>\")):"]
        zeilen += [teil_zeile(p) for p in sorted(items, key=lambda p: str(p.get("name")))]
        return fmt.result("\n".join(zeilen), {"teile": len(items)}, json_block=False)

    # ------------------------------------------------------------------------------------------- Messen und Auswahl

    @tool("measure", "Messen",
          "Exact measurement in the kernel (OCCT). Without refs: what Kevin has selected, with its values (use it "
          "when he says 'this', 'here', 'that hole'). One ref: its properties (face area/normal/radius, edge "
          "length/radius, vertex position, part bbox/volume/mass). Two refs: minimum distance with dx/dy/dz and both "
          "points, angle, distance of parallel faces or axes. show=true also draws it in the viewer.", ADDITIVE)
    async def measure(
        refs: Annotated[list[str] | None,
                        Field(description="One or two references of the current run; omit for Kevin's selection")]
        = None,
        show: Annotated[bool, Field(description="Draw the measurement in the viewer")] = True,
    ) -> CallToolResult:
        if not refs:
            res = await t.work("liest die Auswahl", svc.selection)
            err = fmt.service_error(res)
            if err:
                return fmt.error_result(f"Auswahl nicht lesbar: {err}")
            sel = list(res.get("refs") or [])
            if not sel:
                return fmt.result("Kevin hat nichts ausgewählt.", {"refs": []}, json_block=False)
            by_ref = {d["refs"][0]: d for d in res.get("details") or [] if isinstance(d, dict) and d.get("refs")}
            anzahl = fmt.plural(len(sel), "Element", "Elemente")
            zeilen = [f"Kevin hat {anzahl} ausgewählt (Lauf {res.get('run', '?')}):"]
            for ref in sel:
                d = by_ref.get(ref)
                zeilen.append("- " + (fmt.measure_line(d) if d else ref))
            return fmt.result("\n".join(zeilen), {"run": res.get("run"), "refs": sel}, json_block=False)
        refs = check_refs(refs, maximum=2)
        activity = f"misst Abstand {refs[0]} ↔ {refs[1]}" if len(refs) == 2 else f"misst {refs[0]}"
        res = await t.work(activity, svc.measure, refs, show)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Messung nicht möglich: {err}")
        text = fmt.measure_line(res)
        punkte = res.get("points") or []
        if len(refs) == 2 and len(punkte) == 2:
            text += f"\nPunkte: {fmt.vec(punkte[0])} ↔ {fmt.vec(punkte[1])}"
        if show:
            text += " (im Viewer eingeblendet)" if len(refs) == 1 else "\nIm Viewer eingeblendet."
        data = {k: res.get(k) for k in ("refs", "run", "kind", "values", "points", "annotation") if k in res}
        return fmt.result(text, data, json_block=False)

    # ------------------------------------------------------------------------------------------------------ Ansicht

    @tool("view", "Ansicht",
          "Control what Kevin sees, several things in one call (applied in this order): visibility (sichtbarkeit "
          "with teile), section, standard view, projection, display, fit, explode, camera focus on refs, highlight "
          "refs in a color with a label, draw an annotation, remove highlights and annotations. Omitted values stay. "
          "dauer_s shows a highlight or annotation only briefly, e.g. a dimension you mention while talking.",
          VIEWER)
    async def view(
        standard: Annotated[StandardView | None, Field(description="Standard view direction")] = None,
        projection: Annotated[Projection | None, Field(description="Camera projection")] = None,
        display: Annotated[ViewDisplay | None, Field(description=(
            "Display style in Kevin's viewer: solid, material (physically based), technical (white parts, outlines), "
            "xray, wireframe"))] = None,
        fit: Annotated[bool, Field(description="Zoom so that all visible parts fit")] = False,
        explode: Annotated[float | None, Field(ge=0, le=1, description="Explosion factor 0 (assembled) .. 1")] = None,
        focus: Annotated[list[str] | None, Field(description="Move the camera (animated) to these parts/elements")]
        = None,
        sichtbarkeit: Annotated[Literal["zeigen", "ausblenden", "isolieren", "alle"] | None, Field(
            description="Show, hide or isolate teile (isolieren = only these visible); alle = everything visible")]
        = None,
        teile: Annotated[list[str] | None, Field(description="Parts for sichtbarkeit")] = None,
        schnitt: Annotated[Literal["x", "y", "z", "aus"] | None, Field(
            description="Section plane normal to this axis (material on the positive side removed); aus removes it")]
        = None,
        schnitt_mm: Annotated[float, Field(description="Position of the section plane along its normal in mm")] = 0,
        schnitt_normale: Annotated[list[float] | None, Field(description="Custom section normal [x, y, z]")] = None,
        hervorheben: Annotated[list[str] | None, Field(
            description="Parts, faces, edges or vertices to highlight (earlier highlights are replaced)")] = None,
        farbe: Annotated[str | list[float] | None, Field(
            description="Highlight color: hex like '#FF8800', a name (red, orange, ...) or linear RGB 0..1")] = None,
        beschriftung: Annotated[str | None, Field(description="Short label next to the highlight")] = None,
        dazu: Annotated[bool, Field(description="hervorheben: keep earlier highlights instead of replacing them")]
        = False,
        anmerkung: Annotated[dict[str, Any] | None, Field(description=(
            "Draw {art: 'dimension'|'arrow'|'label', punkte: [[x,y,z], ...] in mm, text?, id?}; a dimension without "
            "text shows the distance"))] = None,
        entfernen: Annotated[bool | Literal["hervorhebungen", "anmerkungen"] | list[str], Field(description=(
            "First remove: true = highlights and annotations, 'hervorhebungen' or 'anmerkungen' only those, a list = "
            "these annotation ids"))] = False,
        dauer_s: Annotated[float | None, Field(gt=0, le=600, description=(
            "hervorheben, anmerkung: fade out after this many seconds"))] = None,
        animate: Annotated[bool, Field(description="Animate the focus move so Kevin can follow")] = True,
    ) -> CallToolResult:
        schritte: list[tuple[str, dict[str, Any]]] = []
        if entfernen:
            if isinstance(entfernen, list):
                schritte.append(("clear_annotations", {"ids": list(entfernen)}))
            else:
                if entfernen in (True, "hervorhebungen"):
                    schritte.append(("highlight", {"refs": [], "clear": True}))
                if entfernen in (True, "anmerkungen"):
                    schritte.append(("clear_annotations", {}))
        if sichtbarkeit is not None:
            modus = {"zeigen": "show", "ausblenden": "hide", "isolieren": "isolate", "alle": "show_all"}[sichtbarkeit]
            if modus != "show_all" and not teile:
                raise ToolInputError("sichtbarkeit braucht teile, z. B. teile=[\"Halter/Lasche\"].")
            schritte.append(("visibility", {"mode": modus, "refs": None if modus == "show_all" else teile}))
        elif teile:
            raise ToolInputError("teile gehört zu sichtbarkeit (zeigen, ausblenden, isolieren).")
        if schnitt is not None or schnitt_normale is not None:
            if schnitt == "aus":
                schritte.append(("section", {"enabled": False}))
            else:
                args: dict[str, Any] = {"enabled": True, "offset": float(schnitt_mm)}
                if schnitt_normale is not None:
                    args["normal"] = schnitt_normale
                else:
                    args["axis"] = schnitt
                schritte.append(("section", args))
        if standard is not None or projection is not None or display is not None or fit or explode is not None:
            schritte.append(("view", {k: v for k, v in (("standard", standard), ("projection", projection),
                                                         ("display", display), ("fit", fit), ("explode", explode))
                                      if v is not None and v is not False}))
        if focus:
            schritte.append(("focus", {"refs": focus, "animate": animate}))
        if hervorheben:
            schritte.append(("highlight", {"refs": hervorheben, "color": farbe, "label": beschriftung,
                                           "clear": not dazu, "dauer_s": dauer_s}))
        elif farbe is not None or beschriftung is not None:
            raise ToolInputError("farbe und beschriftung gehören zu hervorheben.")
        if anmerkung is not None:
            if not isinstance(anmerkung, dict) or "punkte" not in anmerkung:
                raise ToolInputError("anmerkung braucht {art, punkte, text?, id?}, z. B. {\"art\": \"dimension\", "
                                     "\"punkte\": [[0, 0, 0], [0, 0, 40]]}.")
            unbekannt = set(anmerkung) - {"art", "punkte", "text", "id"}
            if unbekannt:
                raise ToolInputError(f"anmerkung: {', '.join(sorted(unbekannt))} gibt es nicht "
                                     "(art, punkte, text, id).")
            punkte = anmerkung.get("punkte") or []
            art = anmerkung.get("art") or ("label" if len(punkte) == 1 else "dimension")
            schritte.append(("annotate", {"kind": art, "points": punkte, "text": anmerkung.get("text"),
                                          "id": anmerkung.get("id"), "dauer_s": dauer_s}))
        if dauer_s is not None and not hervorheben and anmerkung is None:
            raise ToolInputError("dauer_s gehört zu hervorheben oder anmerkung.")
        if not schritte:
            raise ToolInputError("Nichts zu tun: etwa standard, focus, sichtbarkeit, schnitt oder hervorheben angeben.")
        texte: list[str] = []
        daten: list[Any] = []
        for griff, args in schritte:
            res = await griffe.aufrufen(griff, {k: v for k, v in args.items() if v is not None or griff == "view"},
                                        aufruf=f"view ({griff})")
            if res.is_error:
                vorher = (" Davor erledigt: " + " ".join(texte)) if texte else ""
                return fmt.error_result(erster_text(res) + vorher)
            texte.append(erster_text(res))
            daten.append(res.structured_content)
        return fmt.result(" ".join(texte), {"befehle": daten}, json_block=False)

    # ------------------------------------------------------------------------------------------------------ Prüfen

    @tool("pruefen", "Prüfen",
          "Result of the built-in check of the last run (it runs after every run): every finding with location, "
          "values and a fix (interpenetration, floating, tipping, assembly, tool access, print, statics, constraints), "
          "stability per group, assembly summary. warten=true (default) waits for work still running in the "
          "background, so call it before reporting done. hinweise=true also lists notes; bilder=true adds close-up "
          "images of the worst findings for your own analysis (never send them to Kevin). thema 'bedingungen': "
          "constraints, degrees of freedom, fastening, range of motion (teil, alle); 'montage': assembly order.",
          READ_ONLY)
    async def pruefen(
        thema: Annotated[Literal["alles", "bedingungen", "montage"], Field(description="What to show")] = "alles",
        hinweise: Annotated[bool, Field(description="Also list notes (schwere hinweis)")] = False,
        bilder: Annotated[bool, Field(description="Close-up images of up to 3 findings for your own analysis")] = False,
        warten: Annotated[bool, Field(description="Wait for the final result (up to 5 minutes)")] = True,
        teil: Annotated[str | None, Field(description="bedingungen: only this part or assembly")] = None,
        alle: Annotated[bool, Field(description="bedingungen: list every constraint, also satisfied ones")] = False,
    ) -> CallToolResult:
        if thema == "bedingungen":
            return ohne_json(await griffe.aufrufen("bedingungen", {"part": teil, "alle": alle},
                                                   aufruf="pruefen(thema=\"bedingungen\")"))
        if thema == "montage":
            return ohne_json(await griffe.aufrufen("montage_reihenfolge", {}, aufruf="pruefen(thema=\"montage\")"))
        res = await griffe.aufrufen("pruefen", {"bilder": bilder, "hinweise": hinweise, "warten": warten})
        data = res.structured_content if isinstance(res.structured_content, dict) else {}
        befunde = [b for b in data.get("befunde") or [] if isinstance(b, dict)]
        if befunde:  # alles, was der Agent jetzt gelesen hat, gilt beim nächsten run als bekannt
            gezeigt = befunde if hinweise else [b for b in befunde if b.get("schwere") != "hinweis"]
            gedaechtnis.befunde_gesehen(claude_session.get(), gezeigt)
        kurz = {k: data.get(k) for k in ("run", "state", "zusammenfassung", "zaehler", "laeuft", "hintergrund",
                                         "statik_hintergrund") if data.get(k) is not None}
        kurz["befunde"] = [{k: b.get(k) for k in ("id", "art", "schwere", "teile", "ort")} for b in befunde]
        res = ohne_json(res)
        return CallToolResult(content=res.content, structured_content=kurz, is_error=res.is_error)

    # --------------------------------------------------------------------------------------------------- Ansichten

    @tool("ansichten", "Ansichten",
          "Images for your own analysis, several in one call (not for Kevin, he watches the viewer): standard views "
          "(default iso, front, right, top) and/or free view directions, small (640 × 400), optionally framed on parts "
          "or a point, x-ray, parts tinted red, the red overlap volumes of the check; Kevin's camera stays. kevin=true "
          "returns instead exactly Kevin's current view (only when he asks for an image).", ADDITIVE)
    async def ansichten(
        views: Annotated[list[StandardView] | None, Field(description="Standard views, default iso, front, right, top")]
        = None,
        richtungen: Annotated[list[list[float]] | None,
                              Field(description="Extra free view directions [x, y, z] (camera looks along)")] = None,
        ziel: Annotated[list[str] | None, Field(description="Frame these parts (names or groups)")] = None,
        punkt: Annotated[list[float] | None, Field(description="Frame this point [x, y, z] (with radius)")] = None,
        radius: Annotated[float | None, Field(gt=0, description="Radius around punkt in mm")] = None,
        darstellung: Annotated[Display, Field(description="Display style for these images")] = "shaded_edges",
        hervorheben: Annotated[list[str] | None, Field(description="Parts to tint red")] = None,
        schnittkoerper: Annotated[bool, Field(description="Show the red overlap volumes of the check")] = True,
        width: Annotated[int | None, Field(ge=64, le=4096, description="Image width in px (640, kevin: 1280)")] = None,
        height: Annotated[int | None, Field(ge=64, le=4096, description="Image height in px (400, kevin: 800)")]
        = None,
        kevin: Annotated[bool, Field(description="Exactly Kevin's current view instead")] = False,
        overlays: Annotated[bool, Field(description="kevin: with highlights, annotations and measurements")] = True,
    ) -> CallToolResult:
        if kevin:
            args = {"width": width or 1280, "height": height or 800, "source": "current", "hide_overlays": not overlays}
            return ohne_json(await griffe.aufrufen("screenshot", args, aufruf="ansichten(kevin=true)"))
        args = {"views": views, "richtungen": richtungen, "ziel": ziel, "punkt": punkt, "radius": radius,
                "darstellung": darstellung, "hervorheben": hervorheben, "schnittkoerper": schnittkoerper,
                "width": width or 640, "height": height or 400}
        return ohne_json(await griffe.aufrufen("ansichten", {k: v for k, v in args.items() if v is not None}))

    # ------------------------------------------------------------------------------------------------------ Katalog

    @tool("katalog", "Katalog",
          "Kevin's stock catalog (inventory rule: build only from it). suche finds stock items by text and dimensions "
          "('vierkantrohr 40x40x3', 'multiplex 18', 'm8', 'alutec 05200'); art filters by kind, art='material' lists "
          "materials instead (ids and aliases for show(material=...) and print parts). id returns one item with "
          "dimensions, kg/m, bar length, price and a usage example for model.py.", READ_ONLY)
    async def katalog(
        suche: Annotated[str, Field(description="Words and dimensions, e.g. 'rohr 42,4x2' or 'petg'")] = "",
        art: Annotated[KatalogArt | None, Field(description="Only this kind; 'material' for materials")] = None,
        id: Annotated[str | None, Field(description="Details of one stock item by id")] = None,
    ) -> CallToolResult:
        if id:
            return ohne_json(await griffe.aufrufen("stock_get", {"id": id}, aufruf="katalog(id=...)"))
        if art == "material":
            return ohne_json(await griffe.aufrufen("material_list", {"query": suche},
                                                   aufruf="katalog(art=\"material\")"))
        return ohne_json(await griffe.aufrufen("stock_search", {"query": suche, "art": art}, aufruf="katalog"))

    # ------------------------------------------------------------------------------------------------------- Export

    @tool("export", "Export",
          "Write files into <project>/output/: step, stl, 3mf, glb (parts limits them to these part names), bom_csv "
          "(bill of materials with cut list), einkaufsliste_csv (shopping list), pdf (the app builds one PDF from "
          "bausteine: deckblatt, produktbild, stueckliste, teileliste, einkaufsliste, zuschnitt, druck, zeichnungen, "
          "bauplan; empty = all; drucken=true opens the print dialog, only when Kevin explicitly asks). 3MF for "
          "printing with filament settings: druck(aktion=\"export\").", ADDITIVE)
    async def export(
        formats: Annotated[list[ExportFormat], Field(min_length=1, description="File formats to write")],
        parts: Annotated[list[str] | None, Field(description="3D formats: part names to export; omit for all")]
        = None,
        bausteine: Annotated[list[Any] | None, Field(description=(
            "pdf: building blocks in order (names or {art, spalten, auswahl}); empty = all"))] = None,
        ziel: Annotated[str | None, Field(description="pdf: target path (relative = inside output/)")] = None,
        drucken: Annotated[bool, Field(description="pdf: open the print dialog; only on Kevin's explicit wish")]
        = False,
    ) -> CallToolResult:
        dateien = [f for f in formats if f != "pdf"]
        texte: list[str] = []
        daten: dict[str, Any] = {}
        if dateien:
            res = await griffe.aufrufen("export", {"formats": dateien, "parts": parts}, aufruf="export")
            if res.is_error:
                return ohne_json(res)
            texte.append(erster_text(res))
            daten["dateien"] = res.structured_content
        if "pdf" in formats:
            res = await griffe.aufrufen("dokument_export", {"bausteine": bausteine, "ziel": ziel, "drucken": drucken},
                                        aufruf="export(pdf)")
            if res.is_error:
                vorher = ("\nSchon geschrieben: " + texte[0]) if texte else ""
                return fmt.error_result(erster_text(res) + vorher, res.structured_content)
            texte.append(erster_text(res))
            daten["pdf"] = res.structured_content
        elif bausteine or ziel or drucken:
            raise ToolInputError("bausteine, ziel und drucken gehören zum Format pdf.")
        return fmt.result("\n".join(texte), daten, json_block=False)

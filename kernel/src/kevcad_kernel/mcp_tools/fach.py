"""Fachwerkzeuge (V2-2): je Fachbereich ein MCP-Werkzeug mit ``aktion``.

Jede Aktion ruft genau einen Griff (griffe.py, die bisherigen Werkzeuge) mit denselben Parametern, die der Agent
oberhalb von ``aktion`` angibt: ``druck(aktion="export", filament={"petg": "<id>"})``. Die Beschreibung nennt je Aktion
die Parameter (aus der Signatur des Griffs, ``?`` = optional) und einen kurzen Zweck; ``aktion="hilfe"`` liefert die
ausführlichen Beschreibungen. Beschreibungen englisch (für das Modell), Ergebnisse deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp_types import CallToolResult, ToolAnnotations
from pydantic import ConfigDict

from . import format as fmt
from .griffe import Griffe, ohne_json
from .tracking import SessionBoard, claude_session

FACH_ANNOTATIONS = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                                   open_world_hint=False)


@dataclass(frozen=True)
class Aktion:
    name: str  # Name nach außen, z. B. "export"
    griff: str  # bisheriges Werkzeug, z. B. "druck_export"
    zweck: str  # eine kurze Zeile, englisch
    umbenennen: dict[str, str] = field(default_factory=dict)  # Parameter außen → innen
    fest: dict[str, Any] = field(default_factory=dict)  # feste Argumente des Griffs
    signatur: str | None = None  # eigene Kurzform der Parameter, sonst aus dem Griff


@dataclass(frozen=True)
class Fach:
    name: str
    titel: str
    kopf: str  # englisch: wofür, wichtige Regeln
    aktionen: tuple[Aktion, ...]


FAECHER: tuple[Fach, ...] = (
    Fach("lager", "Lager und Zukauf",
         "Changes to Kevin's stock catalog, releases and purchased parts (search and item details: katalog). "
         "Propose only when Kevin asks; a proposal is unusable until Kevin releases it by his click.",
         (Aktion("teil_vorschlagen", "stock_define", "propose a stock item (entry as in KATALOG.md)"),
          Aktion("material_vorschlagen", "material_define", "propose a material"),
          Aktion("loeschen", "catalog_delete", "delete a stock item or material, only on Kevin's request"),
          Aktion("freigabe", "freigabe_anfragen",
                 "open the release dialog in the project window and wait for Kevin's click; also when he writes "
                 "'freigegeben' in the chat; never releases anything itself"),
          Aktion("zukauf_anlegen", "zukauf_anlegen",
                 "purchased part from a shop link, mpn or gtin and the fields you read from the page"),
          Aktion("zukauf_html", "zukauf_html", "purchased part from the HTML of a shop page"),
          Aktion("cad_suchen", "cad_suchen", "links where Kevin downloads the manufacturer CAD"),
          Aktion("cad_uebernehmen", "cad_uebernehmen", "take over the downloaded STEP or ZIP (newest in ~/Downloads)"),
          Aktion("zukauf_liste", "zukauf_liste", "purchased parts with release and CAD state"))),
    Fach("bestand", "Bestand und Einkauf",
         "Stock on hand of the open project, shopping list and bookings. Enter only what Kevin told you (quote him in "
         "grund); book built or printed only on his explicit word; every booking can be undone.",
         (Aktion("liste", "bestand_liste", "stock on hand: bars, sheets, offcuts, pieces, filament spools"),
          Aktion("eintragen", "bestand_eintragen", "enter or change stock from Kevin's words"),
          Aktion("einkaufsliste", "einkaufsliste", "shopping list exactly as Kevin sees it in the app"),
          Aktion("gebaut", "gebaut_buchen", "book the project as built"),
          Aktion("gedruckt", "gedruckt_buchen", "book printed plates (filament) off"),
          Aktion("rueckgaengig", "buchung_rueckgaengig", "undo a booking"))),
    Fach("druck", "3D-Druck",
         "3D printing on Kevin's Bambu Lab P1P. Before any export or print question ask Kevin which filament is "
         "loaded (filamente lists his); the last choice is only a suggestion.",
         (Aktion("pruefung", "druckpruefung", "print check: orientation with reason, key figures, findings, settings"),
          Aktion("vorschau", "druckvorschau", "filament, time, plates, cost, recommended settings"),
          Aktion("einstellen", "druck_einstellen", "fix print settings of a part, only on Kevin's request"),
          Aktion("export", "druck_export", "print-ready 3MF plates for Bambu Studio; filament from Kevin required"),
          Aktion("filamente", "filament_liste", "Kevin's filaments, last choice of this project, spools in stock"),
          Aktion("filament_neu", "filament_define", "define a filament, only on Kevin's request"),
          Aktion("drucker", "drucker_status", "printer state and last job, read-only"),
          Aktion("drucken", "drucken", "open the print dialog; ONLY when Kevin explicitly asks to print"))),
    Fach("statik", "Statik und Simulation",
         "Statics computed after every run: load scenarios, motion (MuJoCo), solid FEM, contact and plasticity "
         "(CalculiX), the load cases of the app's Simulation area. Always state the simplifications; no substitute "
         "for a structural engineer on safety-relevant things.",
         (Aktion("ergebnis", "statik", "all scenarios with traffic light, or one in detail"),
          Aktion("szenario", "szenario_rechnen",
                 "answer 'does it hold if ...' in under a second without a new run, shown in the viewer"),
          Aktion("dynamik", "dynamik", "motion over time, e.g. push at 1 m/s and brake abruptly"),
          Aktion("grenze", "dynamik_grenze", "speed limit until a loose body jumps out or the group tips"),
          Aktion("festigkeit", "festigkeit",
                 "solid FEM of a part; verfahren='ccx' for contact, plasticity, load capacity, buckling"),
          Aktion("simulation", "simulation_liste", "load cases, forces and supports from the app"),
          Aktion("simulation_aendern", "simulation_aendern", "change them like Kevin's clicks, only on his request"),
          Aktion("simulation_rechnen", "simulation_rechnen", "run the buttons of the Simulation area"))),
    Fach("topologie", "Topologie",
         "Topology optimisation of a print part (saves material, runs about a minute in the background). Report "
         "before/after figures; approximation, no strength proof.",
         (Aktion("optimieren", "topologie_optimieren", "start or check an optimisation"),
          Aktion("ergebnis", "topologie_ergebnis", "result with figures before and after"),
          Aktion("uebernehmen", "topologie_uebernehmen", "take it over as a variant, only on Kevin's request"))),
    Fach("zeichnung", "Zeichnungen",
         "Workshop drawings (ISO 128/129-1) from the model, sheets in dokumente/zeichnungen/. Check every sheet "
         "yourself with bild; never send these images to Kevin.",
         (Aktion("liste", "zeichnungen", "sheets with their checks"),
          Aktion("erstellen", "zeichnung_erstellen", "drawings for manufactured parts plus the assembly sheet"),
          Aktion("bearbeiten", "zeichnung_bearbeiten", "edit dimensions, views, scale, format, notes (ops)"),
          Aktion("bild", "zeichnung_bild", "image of a sheet for your own check"))),
    Fach("bauplan", "Bauplan",
         "Step-by-step build instructions from the model (material, cutting, drilling, printing, assembly), every "
         "assembly step simulated. Numbers come from the kernel; fix problems in model.py, not in the text.",
         (Aktion("zeigen", "bauplan", "generate or show the build plan"),
          Aktion("bearbeiten", "bauplan_bearbeiten", "rewrite step texts, order, scope (ops)"),
          Aktion("pruefen", "bauplan_pruefen", "re-run the simulation of the assembly steps"))),
    Fach("referenz", "Referenzen und Scans",
         "Reference meshes from phone videos, photos and Kev Scan; measure param() values from them. Never edit "
         "model.py with measured values yourself (Kevin applies them); never send check images to Kevin.",
         (Aktion("liste", "referenzen", "references and their state; waits with warten_s"),
          Aktion("video", "referenz_video", "scaled reference mesh from a video (Object Capture, about 1 min)"),
          Aktion("fotos", "referenz_fotos", "reference from photos"),
          Aktion("vermessen", "referenz_vermessen", "measure free param() values from video, photos or scan"),
          Aktion("fotoansicht", "referenz_fotoansicht", "a photo through its fitted camera behind the model"),
          Aktion("abweichung", "referenz_abweichung", "deviation model to mesh per part, color map for Kevin"),
          Aktion("massstab", "referenz_massstab", "fix the scale of a reference afterwards"),
          Aktion("scans", "scans", "scans received from Kev Scan on the iPhone"),
          Aktion("scan_importieren", "scan_importieren", "evaluate a scan in the background and add it"))),
    Fach("kamera", "Kameras",
         "Film cameras from model.py (lager.kamera): angle of view, depth of field, view through the camera, images.",
         (Aktion("liste", "kamera_liste", "cameras with angle of view and depth of field"),
          Aktion("info", "kamera_info", "all values of one camera"),
          Aktion("ansicht", "kamera_ansicht", "Kevin's viewer looks through the camera; name 'aus' or none = back"),
          Aktion("bild", "kamera_bild", "PNG through the camera into output/kameras/, returns the path"),
          Aktion("katalog", "kamera_katalog", "cameras, lenses and rig accessories in the inventory"),
          Aktion("vorschlag", "kamera_vorschlag_aus_ansicht", "Kevin's current view as a setzen(...) line"))),
    Fach("animation", "Animation",
         "Animations from model.py (animation(...)): play, jump, render video, check collisions over time.",
         (Aktion("liste", "animation_liste", "animations with duration, moving parts and cameras"),
          Aktion("abspielen", "animation_abspielen", "play or stop in the app"),
          Aktion("springen", "animation_springen", "jump to a time"),
          Aktion("video", "animation_video", "MP4 into output/animationen/, optionally through a camera"),
          Aktion("aufbau", "aufbau_video",
                 "build-up video on request: parts appear one after another, orbit or several angles, optional "
                 "strokes; one MP4 per angle plus the timing for captions"),
          Aktion("kollision", "kollision_pruefen", "exact collision check every 3rd frame; solve every penetration"))),
    Fach("versionen", "Versionen",
         "Every successful run that changed a project file is a version V<n>. At the end of every task set a "
         "milestone; restore only when Kevin asks.",
         (Aktion("liste", "versionen", "history of versions and milestones"),
          Aktion("meilenstein", "meilenstein", "name the current version: short German title and a note"),
          Aktion("vergleichen", "versionen_vergleichen",
                 "parameters, parts, BOM, check and code diff, ghost in the viewer"),
          Aktion("wiederherstellen", "version_wiederherstellen", "go back to a version, only on Kevin's request"),
          Aktion("variante_liste", "variante", "variants of the project", fest={"aktion": "liste"}, signatur=""),
          Aktion("variante_anlegen", "variante", "create a variant (from a version) and switch to it",
                 fest={"aktion": "anlegen"}, signatur="name, von?"),
          Aktion("variante_wechseln", "variante", "switch to a variant ('Hauptstand' = main state)",
                 fest={"aktion": "wechseln"}, signatur="name"),
          Aktion("variante_umbenennen", "variante", "rename a variant", fest={"aktion": "umbenennen"},
                 signatur="name, neuer_name"))),
    Fach("render", "Renderings",
         "Beautiful images for Kevin (product image, cover, social media), only on his wish: the answer names the "
         "PNG in output/renders/. qualitaet 'schnell' in the app (seconds), 'foto' Blender Cycles in the background.",
         (Aktion("", "render", "render an image, check a job (auftrag) or cancel it"),)),
)


def faecher_nach_name() -> dict[str, Fach]:
    return {f.name: f for f in FAECHER}


def signatur(fach: Fach, aktion: Aktion, griffe: Griffe) -> str:
    if aktion.signatur is not None:
        return aktion.signatur
    griff = griffe[aktion.griff]
    innen = {v: k for k, v in aktion.umbenennen.items()}
    teile = []
    for n, pflicht, _ in griff.parameter():
        if n in aktion.fest:
            continue
        teile.append(innen.get(n, n) + ("" if pflicht else "?"))
    return ", ".join(teile)


def beschreibung(fach: Fach, griffe: Griffe) -> str:
    zeilen = [fach.kopf, "aktion and its parameters (pass them next to aktion; ? = optional):"]
    for a in fach.aktionen:
        zeilen.append(f"- {a.name}({signatur(fach, a, griffe)}): {a.zweck}")
    zeilen.append('aktion="hilfe" (optional zu="<aktion>") explains every parameter; daten=true adds the raw data as '
                  "JSON.")
    return "\n".join(zeilen)


def schema(fach: Fach) -> dict[str, Any]:
    namen = [a.name for a in fach.aktionen] + ["hilfe"]
    return {
        "type": "object",
        "properties": {
            "aktion": {"type": "string", "enum": namen, "description": "What to do; its parameters go next to it"},
        },
        "required": ["aktion"],
        "additionalProperties": True,
    }


def hilfe_text(fach: Fach, griffe: Griffe, zu: str | None) -> str:
    """Ausführliche Beschreibung je Aktion: Zweck aus dem bisherigen Werkzeug und jeder Parameter mit Typ."""
    aktionen = [a for a in fach.aktionen if zu in (None, "", a.name)]
    if not aktionen:
        return f"{fach.name}: Aktion {zu!r} gibt es nicht. Vorhanden: {', '.join(a.name for a in fach.aktionen)}."
    bloecke = []
    for a in aktionen:
        griff = griffe[a.griff]
        innen = {v: k for k, v in a.umbenennen.items()}
        zeilen = [f"{fach.name}(aktion=\"{a.name}\", {signatur(fach, a, griffe)})".replace(", )", ")"),
                  griff.beschreibung]
        for n, pflicht, s in griff.parameter():
            if n in a.fest:
                continue
            typ = _typ(s)
            vorgabe = "" if pflicht or "default" not in s else f" = {s['default']!r}"
            zeilen.append(f"  {innen.get(n, n)}: {typ}{vorgabe}{'' if pflicht else ' (optional)'}"
                          + (f" – {s['description']}" if s.get("description") else ""))
        bloecke.append("\n".join(zeilen))
    return "\n\n".join(bloecke)


def _typ(s: dict[str, Any]) -> str:
    if "enum" in s:
        return " | ".join(repr(v) for v in s["enum"])
    if "anyOf" in s:
        return " | ".join(_typ(x) for x in s["anyOf"] if x.get("type") != "null") or "null"
    t = s.get("type")
    if t == "array":
        return f"list[{_typ(s.get('items') or {})}]" if s.get("items") else "list"
    return str(t or "any")


def fach_werkzeuge(mcp: MCPServer, griffe: Griffe, board: SessionBoard,
                   guard: Callable[..., Any]) -> list[str]:
    """Registriert je Fach ein Werkzeug am Server; Rückgabe: die Namen."""
    from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase

    class Argumente(ArgModelBase):
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
        aktion: str

        def model_dump_one_level(self) -> dict[str, Any]:
            return {"aktion": self.aktion, "parameter": dict(self.model_extra or {})}

    namen = []
    for fach in FAECHER:
        fehlend = [a.griff for a in fach.aktionen if a.griff not in griffe]
        if fehlend:
            raise RuntimeError(f"Fach {fach.name}: Griffe fehlen: {', '.join(fehlend)}")
        if direkt(fach):  # eine einzige Funktion (render): ohne aktion, mit dem Schema des Griffs
            griff = griffe[fach.aktionen[0].griff]
            mcp.add_tool(guard(_durchreichen(fach, griffe, board)), name=fach.name, title=fach.titel,
                         description=fach.kopf, annotations=griff.annotations, structured_output=False)
            eintrag = mcp._tool_manager.get_tool(fach.name)
            eintrag.parameters = griff.werkzeug.parameters
            eintrag.fn_metadata.arg_model = _freies_modell()
            namen.append(fach.name)
            continue
        werkzeug = _dispatcher(fach, griffe, board)
        mcp.add_tool(guard(werkzeug), name=fach.name, title=fach.titel, description=beschreibung(fach, griffe),
                     annotations=FACH_ANNOTATIONS, structured_output=False)
        eintrag = mcp._tool_manager.get_tool(fach.name)  # Schema und Prüfmodell auf aktion + freie Parameter
        eintrag.parameters = schema(fach)
        eintrag.fn_metadata.arg_model = Argumente
        namen.append(fach.name)
    return namen


def direkt(fach: Fach) -> bool:
    """Ein Fach mit genau einer namenlosen Aktion ist ein gewöhnliches Werkzeug ohne ``aktion``."""
    return len(fach.aktionen) == 1 and not fach.aktionen[0].name


def _freies_modell() -> type:
    """Prüfmodell, das alle Argumente als ``parameter`` weiterreicht (geprüft wird im Griff)."""
    from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase

    class Frei(ArgModelBase):
        model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

        def model_dump_one_level(self) -> dict[str, Any]:
            return {"parameter": dict(self.model_extra or {})}

    return Frei


def _durchreichen(fach: Fach, griffe: Griffe, board: SessionBoard) -> Callable[..., Any]:
    a = fach.aktionen[0]

    async def werkzeug(parameter: dict[str, Any] | None = None) -> CallToolResult:
        parameter = dict(parameter or {})
        daten = bool(parameter.pop("daten", False))
        board.tool_called(claude_session.get(), not griffe[a.griff].lesend)
        res = await griffe.aufrufen(a.griff, parameter, aufruf=fach.name)
        return res if daten else ohne_json(res)

    werkzeug.__name__ = fach.name
    return werkzeug


def _dispatcher(fach: Fach, griffe: Griffe, board: SessionBoard) -> Callable[..., Any]:
    nach_name = {a.name: a for a in fach.aktionen}

    async def werkzeug(aktion: str, parameter: dict[str, Any] | None = None) -> CallToolResult:
        parameter = dict(parameter or {})
        daten = bool(parameter.pop("daten", False))
        if aktion == "hilfe":
            zu = parameter.pop("zu", None)
            return fmt.result(hilfe_text(fach, griffe, zu), None)
        a = nach_name.get(aktion)
        if a is None:
            return fmt.error_result(f"{fach.name}: Aktion {aktion!r} gibt es nicht. Vorhanden: "
                                    f"{', '.join(nach_name)} (oder hilfe).")
        doppelt = [k for k in parameter if k in a.fest]
        if doppelt:
            return fmt.error_result(f"{fach.name}(aktion=\"{a.name}\"): {', '.join(doppelt)} ist durch die Aktion "
                                    "festgelegt.")
        innen = {a.umbenennen.get(k, k): v for k, v in parameter.items()}
        innen.update(a.fest)
        board.tool_called(claude_session.get(), not griffe[a.griff].lesend)
        res = await griffe.aufrufen(a.griff, innen, aufruf=f'{fach.name}(aktion="{a.name}")', umbenennen=a.umbenennen)
        return res if daten else ohne_json(res)

    werkzeug.__name__ = fach.name
    return werkzeug

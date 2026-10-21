"""MCP-Werkzeuge des Bauplans (Phase 6, Strang P6-B): bauplan, bauplan_bearbeiten, bauplan_pruefen.

Sie rufen nur die Bauplan-Methoden von ``KernelService`` (service.py). Ergebnisse auf Deutsch, Beschreibungen englisch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from . import format as fmt

BAUPLAN_TOOL_NAMES = ("bauplan", "bauplan_bearbeiten", "bauplan_pruefen")

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

SCHREIBEN = (
    "Write the texts like a short workshop instruction: what to do, how (the hand movement), which tool, what to "
    "watch out for; one or two plain German sentences per step, no marketing, no filler. Add safety notes where they "
    "apply (pinch points at moving parts, sharp edges after sawing or drilling, hot soldering iron, eye protection). "
    "All numbers (lengths, diameters, positions, counts, torques of standard parts) come from the step data of the "
    "kernel, never invent or round them differently; if a number is missing, say what to measure instead. Never hide a "
    "problem of the model in the text: fix the model (model.py) and run again; the plan follows.")


def _befund_zeile(b: dict[str, Any]) -> str:
    return f"  ! {b.get('schwere')}: {b.get('text')} → {b.get('loesung')}"


def plan_text(plan: dict[str, Any], *, kurz: bool = False, max_schritte: int = 200) -> str:
    """Bauplan als Text: Abschnitte, Schritte (id, Titel, Text, Werkzeug, Hinweise), Befunde."""
    from kevcad_kernel.bauplan.datei import zusammenfassung

    z = zusammenfassung(plan) or {}
    zeilen = [f"Bauplan „{plan.get('titel')}“: {z.get('schritte', 0)} Schritte, "
              f"{fmt.plural(int(z.get('fehler') or 0), 'Fehler', 'Fehler')}, "
              f"{fmt.plural(int(z.get('probleme') or 0) - int(z.get('fehler') or 0), 'Warnung', 'Warnungen')}, "
              f"{fmt.plural(int(z.get('hinweise') or 0), 'Hinweis', 'Hinweise')} aus der Simulation."]
    stand = plan.get("stand") or {}
    ohne = stand.get("nicht_im_aufbau") or {}
    if ohne:
        zeilen.append("Nicht im Aufbau: " + "; ".join(f"{n} ({g})" for n, g in list(ohne.items())[:6]))
    if stand.get("verbinde") is False:
        zeilen.append("Modell ohne verbinde: Verbindungen und Werkzeug sind aus Kontakt und Normteilen geschätzt.")
    n = 0
    for a in plan.get("abschnitte") or []:
        schritte = a.get("schritte") or []
        zeilen.append(f"\n## {a.get('titel')} ({len(schritte)})")
        gruppe = object()
        for s in schritte:
            n += 1
            if n > max_schritte:
                zeilen.append("  …")
                break
            if a.get("art") == "montage" and s.get("baugruppe") != gruppe:
                gruppe = s.get("baugruppe")
                zeilen.append(f"### {'Vormontage ' + gruppe if gruppe else 'Hauptmontage'}")
            merk = "".join([" [fest]" if s.get("fest") else "", f" [{s.get('quelle')}]" if s.get("quelle") != "auto"
                            else "", " [verwaist]" if s.get("verwaist") else ""])
            zeilen.append(f"- {s.get('id')}: {s.get('titel')}{merk}")
            if not kurz:
                if s.get("text"):
                    zeilen.append(f"  {s['text']}")
                if s.get("material"):
                    zeilen.append("  Material: " + "; ".join(f"{m.get('menge')} × {m.get('benennung')}"
                                                             for m in s["material"][:12]))
                if s.get("werkzeug"):
                    zeilen.append("  Werkzeug: " + ", ".join(s["werkzeug"]))
                for h in s.get("hinweise") or []:
                    zeilen.append(f"  Hinweis: {h}")
            for b in s.get("pruefung") or []:
                if not kurz or b.get("schwere") != "hinweis":
                    zeilen.append(_befund_zeile(b))
    regeln = [r for r in plan.get("vorher") or [] if r.get("quelle") != "auto"]
    if regeln:
        zeilen.append("\nReihenfolgen von Agent/Kevin: " + "; ".join(f"{r['a']} vor {r['b']} ({r.get('grund')})"
                                                                     for r in regeln))
    return "\n".join(zeilen)


def kompakt(plan: dict[str, Any]) -> dict[str, Any]:
    """Schlanke Daten für den Agenten (ohne Bildparameter und Einbauwege)."""
    abschnitte = []
    for a in plan.get("abschnitte") or []:
        schritte = []
        for s in a.get("schritte") or []:
            x = {k: s.get(k) for k in ("id", "titel", "text", "quelle", "fest", "anzahl", "baugruppe", "werkzeug",
                                      "hinweise", "verbindungsmittel", "pruefung") if s.get(k) not in (None, [], "")}
            x["teile"] = len(s.get("teile") or [])
            if s.get("bohrbild"):
                x["bohrbild"] = [{k: e.get(k) for k in ("teil", "text", "durchmesser", "tiefe", "lage_mm", "von",
                                                        "gewinde", "senkung")} for e in s["bohrbild"]]
            if s.get("zuschnitt"):
                x["zuschnitt"] = s["zuschnitt"]
            if s.get("druck"):
                x["druck"] = s["druck"]
            if s.get("material"):
                x["material"] = s["material"]
            schritte.append(x)
        abschnitte.append({"art": a.get("art"), "titel": a.get("titel"), "schritte": schritte})
    return {"titel": plan.get("titel"), "abschnitte": abschnitte, "vorher": [r for r in plan.get("vorher") or []
                                                                             if r.get("quelle") != "auto"],
            "stand": plan.get("stand")}


def register_bauplan_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Werkzeuge über den ``tool``-Dekorator aus tools.register_tools."""

    @tool("bauplan", "Bauplan",
          "Step-by-step build plan (Bauplan) of the open project, generated from the model: sections Material "
          "(shopping list, stock), Zuschnitt (cut list per bar with miter), Bearbeiten (drill patterns per part with "
          "Ø and position from the reference edge or bar end, threads, countersinks, heat-set inserts, glued set "
          "screws), Drucken (print parts with material, orientation, hints) and Montage (sub-assemblies first, order "
          "from disassembly and the constraints, fasteners and tools from verbinde). Every assembly step is "
          "simulated: insertion path free, tool access to the fasteners, stability of the partial assembly, order, "
          "visibility of the new parts in the step image; findings come with a fix. Saved as "
          "<project>/dokumente/bauplan.json; steps with fest=true and texts from agent or Kevin survive new runs. "
          "After generating, rewrite the step texts with bauplan_bearbeiten (op 'text'). " + SCHREIBEN, ADDITIVE)
    async def bauplan(
        neu: Annotated[bool, Field(description="Regenerate even if the plan of this run exists (fixed steps and "
                                               "texts from agent/Kevin are kept)")] = False,
        kurz: Annotated[bool, Field(description="Only titles and problems, no step texts")] = False,
    ) -> CallToolResult:
        res = await t.work("erstellt den Bauplan", svc.bauplan, neu)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        plan = res.get("bauplan") or {}
        text = plan_text(plan, kurz=kurz)
        z = res.get("zusammenfassung") or {}
        zeiten = res.get("zeiten") or {}
        if zeiten:
            text += f"\n\nGerechnet in {fmt.num(float(zeiten.get('gesamt_ms', 0)) / 1000, 1)} s; Datei {res.get('datei')}"
        return fmt.result(text, {"datei": res.get("datei"), "zusammenfassung": z, "bauplan": kompakt(plan)},
                          error=int(z.get("fehler") or 0) > 0)

    @tool("bauplan_bearbeiten", "Bauplan bearbeiten",
          "Edit the build plan. ops (list, applied in order): {op:'text', schritt, titel?, text?, hinweise?: [..]} "
          "(sets quelle 'agent', survives new runs); {op:'fest', schritt, wert}; {op:'verschieben', schritt, nach: "
          "step id | null (first)} (the section order becomes fixed); {op:'zusammenfassen', schritte:[ids], titel?}; "
          "{op:'teilen', schritt, teile:[part names]}; {op:'bild', schritt, kamera?|explosion?|pfeile?|ansicht?}; "
          "{op:'werkzeug', schritt, werkzeug:[..]}; {op:'vorher', a, b, grund} (a before b, step ids or part names; "
          "use it when several orders are equally valid and Kevin decided); {op:'vorher_loeschen', index}; "
          "{op:'umfang', ohne:[part or group names], mit:[...]} (exclude environment or loose parts, regenerates). "
          "The simulation runs again afterwards and returns the findings. " + SCHREIBEN, ADDITIVE)
    async def bauplan_bearbeiten(
        ops: Annotated[list[dict[str, Any]], Field(description="Operations, see description")],
    ) -> CallToolResult:
        if not isinstance(ops, list) or not ops:
            return fmt.error_result("ops: Liste mit mindestens einer Operation angeben")
        res = await t.work("bearbeitet den Bauplan", svc.bauplan_bearbeiten, ops, "agent")
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        z = res.get("zusammenfassung") or {}
        zeilen = list(res.get("meldungen") or [])
        fehler = [b for b in res.get("befunde") or [] if b.get("schwere") in ("fehler", "warnung")]
        zeilen.append(f"Simulation: {fmt.plural(len(fehler), 'Problem', 'Probleme')}"
                      + (":" if fehler else "."))
        zeilen += [_befund_zeile(b) for b in fehler[:20]]
        return fmt.result("\n".join(zeilen), {"zusammenfassung": z, "befunde": res.get("befunde")},
                          error=int(z.get("fehler") or 0) > 0)

    @tool("bauplan_pruefen", "Bauplan prüfen",
          "Simulate the build plan again (all assembly steps or one): every new part moves along its insertion path "
          "from the exploded position to its place against everything mounted so far; tool access to each fastener "
          "(hex key straight above the head, spanner around the nut, fingers around a wing nut); stability of the "
          "partial assembly (centre of gravity over the footprint); order rules ('a before b'); visibility in the "
          "step image. Fix problems in the model or the order, not in the text.", READ_ONLY)
    async def bauplan_pruefen(
        schritt: Annotated[str | None, Field(description="Step id, empty = all steps")] = None,
        schwere: Annotated[Literal["alle", "probleme"], Field(description="'probleme' hides hints")] = "alle",
    ) -> CallToolResult:
        res = await t.work("prüft den Bauplan", svc.bauplan_pruefen, schritt or None)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        befunde = res.get("befunde") or []
        if schwere == "probleme":
            befunde = [b for b in befunde if b.get("schwere") in ("fehler", "warnung")]
        z = res.get("zusammenfassung") or {}
        kopf = (f"Simulation {'von ' + schritt if schritt else 'aller Montageschritte'}: "
                f"{fmt.plural(int(z.get('fehler') or 0), 'Fehler', 'Fehler')}, "
                f"{fmt.plural(len([b for b in befunde if b.get('schwere') == 'warnung']), 'Warnung', 'Warnungen')}, "
                f"{fmt.plural(len([b for b in befunde if b.get('schwere') == 'hinweis']), 'Hinweis', 'Hinweise')} "
                f"({fmt.num(float(res.get('ms') or 0) / 1000, 1)} s).")
        zeilen = [kopf] + [f"- {b.get('schritt')}: {b.get('schwere')} {b.get('art')}: {b.get('text')} → "
                           f"{b.get('loesung')}" for b in befunde[:40]]
        return fmt.result("\n".join(zeilen), {"zusammenfassung": z, "befunde": befunde},
                          error=int(z.get("fehler") or 0) > 0)

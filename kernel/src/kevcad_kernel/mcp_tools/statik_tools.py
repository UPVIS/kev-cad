"""MCP-Werkzeuge der Statik (PLAN-STATIK.md, Stufe 1): ``statik`` und ``szenario_rechnen``.

Eigene Datei, damit parallele Stränge nicht in dieselben Zeilen von tools.py schreiben. Beschreibung englisch (für das
Modell), Ergebnis deutsch (Kevin liest mit).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

STATIK_TOOL_NAMES: tuple[str, ...] = ("statik", "szenario_rechnen", "dynamik", "dynamik_grenze", "festigkeit")


def register_statik_tools(t: Any, svc: Any, tool: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Registriert ``statik`` und ``szenario_rechnen`` über den ``tool``-Dekorator aus ``register_tools``."""

    @tool("statik", "Statik",
          "Statics of the last run (computed automatically after every run, nothing is recomputed): for every "
          "scenario a traffic light (gruen/gelb/rot) with safety factor against the target (static 2, dynamic 3, 3D "
          "printed parts x2), deflection, buckling load factor, tipping reserve per direction, sliding reserve (friction "
          "from the catalog), rough screw loads and the frame (bars from stock tubes/profiles via PyNite: stresses, "
          "deflection, support forces, forces per connection of rigid connectors). Scenarios come from model.py "
          "(import kevcad.statik as st; st.szenario(...), st.last(teil, kraft=(fx, fy, fz) in N or kg=..., punkt=...,"
          " gegen=other part for an internal force pair)) plus defaults (Eigengewicht, Nutzlast from a "
          "param in kg, Bremsen on wheels). Also suggests lighter or stronger stock items ONLY from the inventory, and "
          "for printed parts loaded across the layers 'drehen oder verstärken'. Without szenario: all scenarios; with "
          "szenario: details (bars, supports, tipping per direction) and the viewer shows its utilization gradient. "
          "Results are simplified (linear-elastic beams, rigid connectors): always say so; no substitute for a "
          "structural engineer for safety-relevant things.", annotations["read_only"])
    async def statik(
        szenario: Annotated[str | None, Field(description="Scenario name for details, e.g. 'Eigengewicht' or "
                                                          "'Aufstützen 30 kg'; omit for the overview")] = None,
    ) -> CallToolResult:
        res = await t.work("liest die Statik", svc.statik, szenario)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Statik nicht verfügbar: {err}", res)
        from kevcad_kernel.statik.bericht import statik_text

        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(statik_text(res), data)

    @tool("szenario_rechnen", "Szenario rechnen",
          "Compute one load scenario on the statics model of the last run, without a new run, in well under a second, "
          "and show it in the viewer (utilization gradient on parts and bars, exaggerated deflection as ghost). Use it "
          "for questions like 'does the frame hold if I lean on it with 30 kg?': lasten=[{teil: 'Name or group/', "
          "kg: 30}] or kraft=[fx, fy, fz] in N, optional punkt=[x, y, z] in mm (world). beschleunigung=[ax, ay, az] "
          "in m/s² of the whole object (braking in +X travel: [-3, 0, 0]), neigung in degrees with richtung ('+x', "
          "'-y'), stoss = impact factor on the loads (dynamic target 3). Answer with traffic light, safety factor, "
          "stress, deflection, tipping reserve and the stated simplifications. To keep a scenario, write it into "
          "model.py with kevcad.statik.", annotations["additive"])
    async def szenario_rechnen(
        name: Annotated[str, Field(description="Scenario name, e.g. 'Aufstützen 30 kg'")],
        lasten: Annotated[list[dict[str, Any]] | None, Field(
            description="Loads: [{'teil': 'Kugelschieber/Querstange vorn (Rohr 3)', 'kg': 30}] or "
                        "[{'teil': 'Halter', 'kraft': [0, 0, -50], 'punkt': [120, 0, 40]}]. Internal force between "
                        "two parts of the design (e.g. the ball pressing on the catch roller): add "
                        "'gegen': 'Bowlingball' - the reaction -kraft acts on that part at the same point; the pair "
                        "cancels for tipping, sliding and lifting of the whole, but loads both parts")] = None,
        beschleunigung: Annotated[list[float] | None, Field(description="[ax, ay, az] in m/s²")] = None,
        neigung: Annotated[float | None, Field(description="Floor tilt in degrees")] = None,
        richtung: Annotated[str | None, Field(description="Downhill direction for neigung: '+x', '-y', …")] = None,
        stoss: Annotated[float | None, Field(description="Impact factor on all loads, e.g. 2")] = None,
        ziel: Annotated[float | None, Field(description="Own target safety factor (default 2 static, 3 dynamic)")]
        = None,
        beschreibung: Annotated[str | None, Field(description="Short description in Kevin's words")] = None,
        zeigen: Annotated[bool, Field(description="Show the scenario in the viewer")] = True,
        dynamik: Annotated[bool, Field(description="Also simulate the motion over time (S2, MuJoCo): needs "
                                                   "geschwindigkeit; same as the tool dynamik")] = False,
        geschwindigkeit: Annotated[float | None, Field(description="S2: pushing speed in m/s")] = None,
        bremsen: Annotated[float | str | None, Field(description="S2: deceleration in m/s² or 'abrupt' (stop in "
                                                                 "0.1 s) or 'anprall' (0.02 s)")] = None,
        dauer: Annotated[float | None, Field(description="S2: simulated time in s (default: until 1.2 s after the "
                                                         "stop)")] = None,
    ) -> CallToolResult:
        if dynamik or geschwindigkeit is not None or bremsen is not None:
            res = await t.work("rechnet einen Ablauf", svc.dynamik, name, geschwindigkeit, bremsen, dauer, neigung,
                               richtung, stoss, None, None, None, None, lasten, True, zeigen, beschreibung)
            return _dynamik_ergebnis(res)
        res = await t.work("rechnet ein Szenario", svc.szenario_rechnen, name, beschleunigung, neigung, richtung,
                           lasten, stoss, ziel, beschreibung, zeigen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Szenario nicht gerechnet: {err}", res)
        from kevcad_kernel.statik.bericht import szenario_text

        e = res.get("szenario") or {}
        text = szenario_text(e, detail=True)
        text += f"\n(gerechnet in {res.get('ms')} ms" + (", im Viewer gezeigt)" if res.get("gezeigt") else ")")
        if res.get("vereinfachungen"):
            text += "\nAnnahmen: " + "; ".join(res["vereinfachungen"][:6])
        if res.get("grenzen"):
            text += "\nGrenzen: " + " ".join(res["grenzen"])
        data = {k: v for k, v in res.items() if k != "ok"}
        return fmt.result(text, data)

    @tool("dynamik", "Ablauf simulieren",
          "Simulate a motion over time (statics stage S2, rigid bodies with MuJoCo in a separate process, a few "
          "seconds): 'what happens if I push at 1 m/s and brake abruptly?'. Built from the last run: bodies from "
          "parts fixed together (verbinde with screws, clamps …; joints with a range count as locked), free joints "
          "(joints without bereich, e.g. rollers on an axle), wheels rolling about the axle from the animation, loose "
          "bodies like a ball resting on the floor (verbinde … aufliegen). The pushed body follows the speed profile "
          "(guided at floor level, worst case for tipping forward) and may tip, lift and slide; friction per material "
          "pair from the catalog. Result: traffic light and numbers (tipping reserve = deceleration at which it "
          "lifts / scenario deceleration, lift in mm, tilt angle, ball displacement and rise, speed limit at which "
          "the ball jumps out, sliding limit with locked wheels mu*g, contact forces, hand check a = g*b/h), shown "
          "in the app's statics section and as animation 'Ablauf: <name>' in the timeline (animation_abspielen). "
          "geschwindigkeit in m/s, bremsen in m/s² or 'abrupt' (stop in 0.1 s) or 'anprall' (0.02 s); or "
          "animation='Fahrt' to take the speed profile from an animation. Always state the limits: rigid bodies, "
          "simplified friction, no deformation.", annotations["additive"])
    async def dynamik(
        name: Annotated[str, Field(description="Scenario name, e.g. 'Bremsen aus 1 m/s'")],
        geschwindigkeit: Annotated[float | None, Field(description="Pushing speed in m/s, e.g. 1")] = None,
        bremsen: Annotated[float | str | None, Field(description="Deceleration in m/s², 'abrupt' or 'anprall'; "
                                                                 "omit for constant speed")] = None,
        dauer: Annotated[float | None, Field(description="Simulated time in s")] = None,
        neigung: Annotated[float | None, Field(description="Floor tilt in degrees")] = None,
        richtung: Annotated[str | None, Field(description="Downhill direction for neigung: '+x', '-y'")] = None,
        stoss: Annotated[float | None, Field(description="Factor on the deceleration")] = None,
        animation: Annotated[str | None, Field(description="Take the speed profile from this animation")] = None,
        antrieb: Annotated[str | None, Field(description="Pushed part or group (default: heaviest body on "
                                                         "wheels)")] = None,
        angriff: Annotated[float | str | None, Field(description="Where the push/brake force acts: 'boden' "
                                                                 "(default) or height in mm above the floor")] = None,
        fahrtrichtung: Annotated[str | None, Field(description="Travel direction, default '+x'")] = None,
        suche: Annotated[bool, Field(description="Search the limits (speed at which the ball jumps out, deceleration "
                                                 "at which it lifts) with parallel rollouts")] = True,
        zeigen: Annotated[bool, Field(description="Show in the app (statics section and timeline)")] = True,
        beschreibung: Annotated[str | None, Field(description="Short description in Kevin's words")] = None,
    ) -> CallToolResult:
        res = await t.work("rechnet einen Ablauf", svc.dynamik, name, geschwindigkeit, bremsen, dauer, neigung,
                           richtung, stoss, animation, antrieb, angriff, fahrtrichtung, None, suche, zeigen,
                           beschreibung)
        return _dynamik_ergebnis(res)

    @tool("dynamik_grenze", "Grenzgeschwindigkeit",
          "'How fast may I push without the ball jumping out / the rig tipping?': searches the speed limit with "
          "parallel rollouts (MuJoCo, separate process) for a braking style (bremsen: 'abrupt' = stop in 0.1 s, "
          "'anprall', or m/s²), plus the deceleration at which the pushed body lifts and the hand check a = g*b/h. "
          "ohne: 'ball' (cargo jumps out), 'kippen' (rig lifts) or 'beides'. Shows the run at geschwindigkeit as "
          "animation like dynamik.", annotations["additive"])
    async def dynamik_grenze(
        ohne: Annotated[str, Field(description="'ball', 'kippen' or 'beides'")] = "beides",
        bremsen: Annotated[float | str, Field(description="Braking style: 'abrupt', 'anprall' or m/s²")] = "abrupt",
        geschwindigkeit: Annotated[float, Field(description="Speed for the shown run in m/s")] = 1.0,
        name: Annotated[str | None, Field(description="Scenario name")] = None,
    ) -> CallToolResult:
        res = await t.work("sucht die Grenzgeschwindigkeit", svc.dynamik_grenze, ohne, bremsen, geschwindigkeit, name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Grenze nicht gesucht: {err}", res)
        from kevcad_kernel.statik.bericht import ablauf_text
        from kevcad_kernel.statik.bewertung import z

        g = res.get("grenzen_suche") or {}
        zeilen = []
        for L in g.get("ladung") or []:
            if L.get("v_grenze") is not None:
                zeilen.append(f"{L['name']}: bleibt bis {z(L['v_grenze'], 2)} m/s im Schieber (bremsen {bremsen}).")
            elif L.get("nie_bis") is not None:
                zeilen.append(f"{L['name']}: bleibt bis mindestens {z(L['nie_bis'], 1)} m/s (bremsen {bremsen}).")
        k = g.get("kippen") or {}
        if k:
            zeilen.append(f"Kippen: hebt bei dieser Bremsart ab {z(k.get('v_abheben'), 2)} m/s ab; bei "
                          f"{z(geschwindigkeit, 2)} m/s ab {z(k.get('a_abheben'), 2)} m/s² Verzögerung. Ohne Ladung "
                          f"{z(k.get('a_abheben_ohne_ladung'), 2)} m/s², Handrechnung "
                          f"{z(k.get('a_kipp_hand'), 2)} m/s².")
        text = "\n".join(zeilen) + "\n" + ablauf_text(res.get("ablauf") or {})
        if res.get("grenzen"):
            text += "\nGrenzen: " + " ".join(res["grenzen"])
        return fmt.result(text, {k_: v for k_, v in res.items() if k_ != "ok"})

    @tool("festigkeit", "Festigkeit (FEM)",
          "Solid FEM (statics stage S3, a few seconds per part, separate process): stress and deformation of a part "
          "that the frame model treats as rigid or as a cantilever (3D printed holders, brackets, plates, "
          "connectors), with second-order tetrahedra (Gmsh, scikit-fem, pyamg). Supports are the contact faces to "
          "the carrying neighbours, loads come from the scenarios (st.last on the part, support forces of the bars "
          "from the frame model, own weight) or, with ablauf=true, the largest contact force from the motion "
          "simulation (dynamik) of that scenario (e.g. ball hitting the catch roller). 3D printed parts: stiffer "
          "and stronger within the layers; across the layers e_modul_z and quer_zur_schicht from the catalog, the "
          "layer interface criterion is checked against target 4 (static). Answer: per part safety factor, traffic "
          "light, governing criterion, location of the highest utilization, max deflection, safety in the other "
          "print orientations (evidence for 'drehen oder verstärken') and the cantilever result S0 for comparison. "
          "The viewer shows the stress (utilization) gradient on the part and the exaggerated deformation. Runs "
          "automatically in the background after every run for parts with load; call it for details, another "
          "scenario, a finer mesh (fein=true) or contact forces. Results are cached per part state and load case. "
          "Always state the limits (linear-elastic, supports fully clamped, full infill). abbrechen=true stops a "
          "running computation.", annotations["additive"])
    async def festigkeit(
        teil: Annotated[str | None, Field(description="Part or group, e.g. 'Wandhalter (Druck)'; omit for all parts "
                                                      "with load")] = None,
        szenario: Annotated[str | None, Field(description="Scenario name; omit for all scenarios with load")] = None,
        fein: Annotated[bool, Field(description="Finer mesh (about 5x the elements, slower) for stress peaks at "
                                                "holes and fillets")] = False,
        ablauf: Annotated[bool, Field(description="Use the largest contact force from the motion simulation of the "
                                                  "scenario as load on the part")] = False,
        zeigen: Annotated[bool, Field(description="Show the result in the viewer")] = True,
        abbrechen: Annotated[bool, Field(description="Only stop a running computation")] = False,
    ) -> CallToolResult:
        if abbrechen:
            res = await t.work("bricht die Festigkeit ab", svc.festigkeit_abbrechen)
            return fmt.result("Festkörper-Rechnung abgebrochen." if res.get("abgebrochen")
                              else "Es lief keine Festkörper-Rechnung.", {k: v for k, v in res.items() if k != "ok"})
        res = await t.work("rechnet die Festigkeit (FEM)", svc.festigkeit, teil, szenario, fein, ablauf, zeigen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Festigkeit nicht gerechnet: {err}", res)
        from kevcad_kernel.statik.bericht import festkoerper_text

        return fmt.result(festkoerper_text(res), {k: v for k, v in res.items() if k != "ok"})


def _dynamik_ergebnis(res: dict[str, Any]) -> CallToolResult:
    err = fmt.service_error(res)
    if err:
        return fmt.error_result(f"Ablauf nicht gerechnet: {err}", res)
    from kevcad_kernel.statik.bericht import ablauf_text, szenario_text

    text = ablauf_text(res.get("ablauf") or {})
    e = res.get("szenario") or {}
    rest = [u for u in e.get("urteile") or [] if not str(u.get("art", "")).startswith("dyn_")
            and u.get("ampel") in ("rot", "gelb")]
    if rest:
        text += "\nRuhende Ersatzlast (größte Verzögerung):\n" + szenario_text({**e, "urteile": rest, "kennzahlen": {}})
    ms = res.get("ms") or {}
    text += (f"\n(gesamt {ms.get('gesamt')} ms: Szene und Statik {ms.get('szene_und_statik')} ms, Ablauf-Prozess "
             f"{ms.get('prozess')} ms" + (", in der Zeitleiste gezeigt)" if res.get("gezeigt") else ")"))
    if res.get("vereinfachungen"):
        text += "\nAnnahmen: " + "; ".join(res["vereinfachungen"][:6])
    if res.get("grenzen"):
        text += "\nGrenzen: " + " ".join(res["grenzen"])
    return fmt.result(text, {k: v for k, v in res.items() if k != "ok"})

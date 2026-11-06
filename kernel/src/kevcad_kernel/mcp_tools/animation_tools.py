"""MCP-Werkzeuge der Animation (Phase 5, Strang ANI): animation_liste, animation_abspielen, animation_springen,
animation_video, kollision_pruefen, dazu aufbau_video (Aufbau-Videos, aufbau.py). Sie rufen nur Methoden von
``KernelService`` (service.py)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from . import format as fmt

ANIMATION_TOOL_NAMES = ("animation_liste", "animation_abspielen", "animation_springen", "animation_video",
                        "kollision_pruefen", "aufbau_video")
Blickwinkel = Literal["orbit", "schnitt", "iso", "vorne", "hinten", "rechts", "links", "oben", "iso_vorne_links",
                      "iso_hinten_rechts", "iso_hinten_links"]

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
VIEWER = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


def _sec(x: Any) -> str:
    return f"{fmt.num(float(x), 2)} s"


def anim_line(a: dict[str, Any]) -> str:
    text = (f"- {a.get('name')}: {_sec(a.get('dauer', 0))}, {fmt.num(a.get('fps', 30), 0)} fps "
            f"({fmt.plural(int(a.get('bilder', 0)), 'Bild', 'Bilder')}), "
            f"{fmt.plural(int(a.get('teile', 0)), 'bewegtes Teil', 'bewegte Teile')}")
    if a.get("kamerafahrt"):
        text += ", mit Kamerafahrt"
    if a.get("kameras"):
        text += ", " + ", ".join(f"Kamera {k}" for k in a["kameras"]) + " fährt mit"
    if a.get("kollisionen") is not None:
        n = int(a["kollisionen"])
        text += ", " + ("keine Kollision" if n == 0 else fmt.plural(n, "Kollision", "Kollisionen"))
    return text


def collision_line(c: dict[str, Any]) -> str:
    a, b = (c.get("teile") or ["?", "?"])[:2]
    span = _sec(c.get("von", 0)) if c.get("von") == c.get("bis") else f"{_sec(c.get('von', 0))} bis {_sec(c.get('bis', 0))}"
    return (f"- {span}: {a} ↔ {b}, Eindringtiefe {fmt.num(c.get('tiefe', 0), 2)} mm, "
            f"Schnittvolumen {fmt.num(c.get('volumen', 0), 1)} mm³ (am stärksten bei {_sec(c.get('zeit', 0))}, "
            f"Bild {c.get('bild')})")


def run_note(res: dict[str, Any]) -> list[str]:
    """Zeilen für die Zusammenfassung von run: welche Animationen der Lauf angelegt hat."""
    anims = res.get("animationen") or []
    if not anims:
        return []
    lines = [f"Animationen: {', '.join(str(a.get('name')) for a in anims)} (Zeitleiste in der App; "
             f"animation(aktion='abspielen'), "
             "animation(aktion='kollision'), animation(aktion='video'))"]
    for a in anims:
        for w in (a.get("warnungen") or [])[:5]:
            lines.append(f"Hinweis Animation: {w}")
    return lines


def register_animation_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Werkzeuge über den ``tool``-Dekorator aus tools.register_tools."""

    @tool("animation_liste", "Animationen",
          "List the animations of the last run (from animation(...) in model.py): name, duration, fps, frames, moved "
          "parts, camera move, number of collisions if checked, and the playback state in the app.", READ_ONLY)
    async def animation_liste() -> CallToolResult:
        res = await t.work("liest die Animationen", svc.animation_list)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Animationen nicht lesbar: {err}", res)
        anims = res.get("animationen") or []
        if not anims:
            return fmt.result(res.get("hinweis") or "Keine Animation im Projekt.", res)
        lines = [f"{fmt.plural(len(anims), 'Animation', 'Animationen')}:"] + [anim_line(a) for a in anims]
        state = res.get("stand") or {}
        if state.get("name"):
            lines.append(f"In der App: {state['name']} bei {_sec(state.get('zeit') or 0)}"
                         + (" (spielt)" if state.get("spielt") else " (angehalten)"))
        return fmt.result("\n".join(lines), res)

    @tool("animation_abspielen", "Animation abspielen",
          "Play (an=true) or pause (an=false) an animation in Kevin's viewer with the timeline. schleife repeats it, "
          "geschwindigkeit scales the speed (1 = real time), von_vorn starts at 0. Kevin can also use Space, the "
          "arrow keys and the timeline himself.", VIEWER)
    async def animation_abspielen(
        name: Annotated[str | None, Field(description="Animation name; omit for the current/first one")] = None,
        an: Annotated[bool, Field(description="true = play, false = pause")] = True,
        schleife: Annotated[bool, Field(description="Loop playback")] = False,
        geschwindigkeit: Annotated[float, Field(ge=0.05, le=8, description="Playback speed, 1 = real time")] = 1.0,
        von_vorn: Annotated[bool, Field(description="Start from the beginning")] = False,
    ) -> CallToolResult:
        res = await t.work("spielt die Animation ab" if an else "hält die Animation an", svc.animation_play, name, an,
                           schleife, geschwindigkeit, von_vorn)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Abspielen nicht möglich: {err}", res)
        if an:
            text = (f"Animation {res.get('name')} spielt ({_sec(res.get('dauer', 0))}"
                    + (", in Schleife" if schleife else "") + (f", {fmt.num(geschwindigkeit, 2)}×" if geschwindigkeit != 1
                                                               else "") + ").")
        else:
            text = f"Animation {res.get('name')} angehalten."
        return fmt.result(text, res)

    @tool("animation_springen", "Zu Zeitpunkt springen",
          "Jump the viewer to time zeit (seconds) of an animation, e.g. to look at the frame of a collision. Playback "
          "pauses there.", VIEWER)
    async def animation_springen(
        zeit: Annotated[float, Field(ge=0, description="Time in seconds")],
        name: Annotated[str | None, Field(description="Animation name; omit for the current/first one")] = None,
    ) -> CallToolResult:
        res = await t.work(f"springt zu {fmt.num(zeit, 2)} s", svc.animation_seek, zeit, name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Springen nicht möglich: {err}", res)
        return fmt.result(f"Animation {res.get('name')} bei {_sec(res.get('zeit', zeit))} (Bild {res.get('bild')}).",
                          res)

    @tool("animation_video", "Animation als Video",
          "Render an animation as video into <project>/output/animationen/ (H.264 MP4, or ProRes 422 .mov with "
          "format='prores'), frame by frame offscreen. Without kamera: from the viewer camera (or the camera move "
          "from anim.ansicht), 16:9. With kamera (name from kamera(aktion='liste'), e.g. 'FX6'): through that camera "
          "with its "
          "angle of view and the aspect ratio of its format; a camera attached with .an(part) rides along with the "
          "animated part. breite in px, fps defaults to the animation's. Returns the file path. Takes a while for long "
          "animations; progress shows in the app.", ADDITIVE)
    async def animation_video(
        name: Annotated[str | None, Field(description="Animation name; omit for the current/first one")] = None,
        breite: Annotated[int, Field(ge=64, le=7680, description="Video width in px")] = 1920,
        fps: Annotated[float | None, Field(ge=1, le=120, description="Frame rate; default from the animation")] = None,
        kamera: Annotated[str | None, Field(description="Camera name from kamera(aktion='liste') (e.g. 'FX6'); omit "
                                                        "for the "
                                                        "viewer camera")] = None,
        format: Annotated[Literal["mp4", "prores"], Field(description="mp4 = H.264, prores = ProRes 422")] = "mp4",  # noqa: A002
    ) -> CallToolResult:
        res = await t.work("rendert ein Video der Animation", svc.animation_video, name, breite, None, fps, kamera,
                           format)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Video nicht erstellt: {err}", res)
        text = (f"Video {res.get('path')} ({res.get('width')} × {res.get('height')} px, {fmt.num(res.get('fps', 0), 0)} "
                f"fps, {fmt.plural(int(res.get('bilder', 0)), 'Bild', 'Bilder')}, "
                f"{fmt.ms_text(int(res.get('ms') or 0))}).")
        if res.get("message"):
            text += f"\nHinweis: {res['message']}"
        return fmt.result(text, res)

    @tool("aufbau_video", "Aufbau-Video",
          "Build-up video on request: the model appears part by part (show() order, or schritte = part names, "
          "assembly prefixes or patterns with *), each step flies in, the camera orbits or holds a view with a slight "
          "drift. One MP4 per blickwinkel, all with the same timing, so they can be cut together like several "
          "cameras; 'schnitt' renders one video with hard cuts between the other angles (on parts appearing). "
          "zeichnen draws a stroke in Kevin's light blue before a step, as when he draws while speaking: "
          "[{vor: step or part, punkte: [[x,y,z], …] in mm, dauer_s?}]. Runs model.py once more (Kevin sees it), "
          "model.py stays unchanged. Returns the video paths and the timing (also as <name>_zeitplan.json next to the "
          "videos) for captions in an edit.", ADDITIVE)
    async def aufbau_video(
        dauer_s: Annotated[float, Field(ge=3, le=600, description="Length of each video in s")] = 20.0,
        blickwinkel: Annotated[list[Blickwinkel] | None, Field(description=(
            "One video per entry: orbit (circles once, see umdrehungen), iso, vorne, rechts, oben … (fixed view with "
            "slow drift), schnitt (one video cutting between the other entries)"))] = None,
        schritte: Annotated[list[str | dict[str, Any]] | None, Field(description=(
            "Order of the build: part names, assembly prefixes ('Drohne/Rahmen') or patterns ('Drohne/Motor *'), or "
            "{auf, landet: s} to land a step at a fixed time (on a beat of the music); steps without a time sit "
            "evenly between. Parts not named follow at the end. Default: show() order, parts of one assembly "
            "together"))] = None,
        einflug: Annotated[Literal["oben", "explosion", "keiner"], Field(description=(
            "How parts arrive: oben = drop in from above, explosion = from outside towards the centre, keiner = "
            "appear"))] = "oben",
        zeichnen: Annotated[list[dict[str, Any]] | None, Field(description=(
            "Strokes before steps: [{vor, punkte, dauer_s?, radius?, von?}]"))] = None,
        details: Annotated[list[dict[str, Any]] | None, Field(description=(
            "Extra close-up videos with the same timing: [{auf: part, assembly or pattern, richtung?: iso|vorne|…|"
            "orbit, titel?, rand? (1.3 = a little room around it)}], e.g. where a stroke is drawn"))] = None,
        umdrehungen: Annotated[float, Field(ge=-10, le=10, description="Orbit turns over the video")] = 1.0,
        hoehe_grad: Annotated[float, Field(ge=-60, le=89, description="Orbit elevation in degrees")] = 24.0,
        wechsel_s: Annotated[float, Field(ge=0.8, le=60, description="schnitt: seconds per angle")] = 3.0,
        halten_s: Annotated[float | None, Field(ge=0, le=120, description=(
            "Finished model at the end, default 12 % of dauer_s, at least 1.5 s"))] = None,
        einflug_s: Annotated[float | None, Field(ge=0, le=5, description=(
            "Seconds a part takes to fly in; default from the spacing of the steps (0.5 with fixed times)"))] = None,
        start_s: Annotated[float | None, Field(ge=0, le=30, description="Empty start before the first part")] = None,
        name: Annotated[str, Field(min_length=1, max_length=60, description="Name of the animations and files")]
        = "Aufbau",
        breite: Annotated[int, Field(ge=64, le=7680, description="Video width in px")] = 1920,
        hoehe: Annotated[int | None, Field(ge=16, le=7680, description=(
            "Video height in px; omit for 16:9. 9:16 for reels: breite 1080, hoehe 1920 (the camera frames for it)"))]
        = None,
        fps: Annotated[float, Field(ge=10, le=60, description="Frame rate")] = 30.0,
        format: Annotated[Literal["mp4", "prores"], Field(description="mp4 = H.264, prores = ProRes 422")] = "mp4",  # noqa: A002
    ) -> CallToolResult:
        wunsch: dict[str, Any] = {"name": name.strip(), "dauer": dauer_s, "fps": fps, "einflug": einflug,
                                  "blickwinkel": list(blickwinkel or ["orbit"]), "umdrehungen": umdrehungen,
                                  "hoehe_grad": hoehe_grad, "wechsel_s": wechsel_s}
        if schritte:
            wunsch["schritte"] = list(schritte)
        if zeichnen:
            wunsch["zeichnen"] = list(zeichnen)
        if details:
            wunsch["details"] = list(details)
        for key, wert in (("halten_s", halten_s), ("einflug_s", einflug_s), ("start_s", start_s)):
            if wert is not None:
                wunsch[key] = wert
        res = await t.work("rendert das Aufbau-Video", svc.aufbau_video, wunsch, breite, fps, format, hoehe)
        if not res.get("videos"):
            return fmt.error_result(f"Aufbau-Video nicht erstellt: {res.get('error') or 'unbekannter Fehler'}", res)
        plan = res.get("zeitplan") or {}
        zeilen = [f"Aufbau-Video aus Lauf {res.get('lauf')}: {len(plan.get('schritte') or [])} Schritte in "
                  f"{fmt.num(float(plan.get('dauer') or 0), 1)} s, Einflug {plan.get('einflug')}."]
        for v in res["videos"]:
            schnitte = v.get("schnitte") or []
            zusatz = f", Schnitte bei {', '.join(fmt.num(s, 2) + ' s' for s in schnitte)}" if schnitte else ""
            zeilen.append(f"- {v['titel']}: {v.get('path')} ({v.get('width')} × {v.get('height')} px{zusatz})")
        for s in (plan.get("schritte") or [])[:40]:
            zeilen.append(f"  {fmt.num(float(s['zeit']), 2)} s {s['titel']} ({len(s['teile'])} Teile)")
        if len(plan.get("schritte") or []) > 40:
            zeilen.append(f"  … {len(plan['schritte']) - 40} weitere Schritte im Zeitplan")
        for st in plan.get("striche") or []:
            zeilen.append(f"  Strich vor {st['schritt']}: {fmt.num(float(st['von']), 2)} bis "
                          f"{fmt.num(float(st['bis']), 2)} s")
        if res.get("zeitplan_datei"):
            zeilen.append(f"Zeitplan: {res['zeitplan_datei']}")
        if res.get("error"):
            zeilen.append(f"Hinweis: {res['error']}")
        return fmt.result("\n".join(zeilen), res)

    @tool("kollision_pruefen", "Kollisionen prüfen",
          "Check an animation for collisions: every schritt-th frame (and the last) all moving parts against all "
          "others with an OCCT intersection volume (bounding box pre-check; parts moving rigidly together and wanted "
          "contacts from anim.erlaube are skipped; touching is allowed). Returns time span, part pair, penetration "
          "depth and volume; the app marks them on the timeline and colors the pair red. Every penetration must be "
          "solved in model.py.", ADDITIVE)
    async def kollision_pruefen(
        name: Annotated[str | None, Field(description="Animation name; omit for the current/first one")] = None,
        schritt: Annotated[int, Field(ge=1, le=30, description="Check every n-th frame")] = 3,
    ) -> CallToolResult:
        res = await t.work("prüft Kollisionen der Animation", svc.collision_check, name, schritt)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Kollisionsprüfung nicht möglich: {err}", res)
        found = res.get("kollisionen") or []
        stats = res.get("geprueft") or {}
        head = (f"Animation {res.get('name')}: {fmt.plural(int(stats.get('geprueft_bilder', 0)), 'Bild', 'Bilder')} "
                f"geprüft (jedes {stats.get('schritt', schritt)}.), {fmt.plural(int(stats.get('paare', 0)), 'Paar', 'Paare')}"
                f" in Bewegung, {fmt.ms_text(int(stats.get('ms') or 0))}.")
        if not found:
            text = head + "\nKeine Kollision."
        else:
            text = head + f"\n{fmt.plural(len(found), 'Kollision', 'Kollisionen')} (jede muss gelöst werden):\n" + \
                "\n".join(collision_line(c) for c in found[:30])
            if len(found) > 30:
                text += f"\n… und {len(found) - 30} weitere"
        if stats.get("abgebrochen"):
            text += "\nHinweis: Zeitlimit erreicht, nicht alle Paare geprüft (schritt erhöhen)."
        return fmt.result(text, res, error=False)

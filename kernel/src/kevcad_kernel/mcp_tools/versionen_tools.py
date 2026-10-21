"""MCP-Werkzeuge der Versionen (PLAN-VERSIONEN.md, V8): versionen, version_wiederherstellen, versionen_vergleichen,
meilenstein, variante. Sie rufen nur die Versionsmethoden von ``KernelService`` (service.py). Beschreibungen englisch
(für das Modell), Ergebnisse deutsch (Kevin liest mit)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from . import format as fmt

VERSIONEN_TOOL_NAMES: tuple[str, ...] = (
    "versionen", "version_wiederherstellen", "versionen_vergleichen", "meilenstein", "variante",
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


def _zeit(v: dict[str, Any]) -> str:
    z = str(v.get("zeit") or "")
    return z.replace("T", " ")[:16] if z else "?"


def kennzahlen_text(k: dict[str, Any] | None) -> str:
    if not k:
        return "Kennzahlen offen"
    bits = [fmt.plural(int(k.get("teile") or 0), "Teil", "Teile")]
    if k.get("masse_kg") is not None:
        bits.append(f"{fmt.num(k['masse_kg'], 3)} kg")
    if k.get("kosten") is not None:
        bits.append(fmt.money(k["kosten"]))
    if k.get("fehler"):
        bits.append(fmt.plural(int(k["fehler"]), "Prüffehler", "Prüffehler"))
    return ", ".join(bits)


def version_zeile(v: dict[str, Any]) -> str:
    ms = v.get("meilenstein") or {}
    titel = f"★ {ms['titel']}" if ms.get("titel") else v.get("titel") or ""
    text = f"- V{v.get('nr')} · {_zeit(v)} · {v.get('wer_text') or v.get('wer')} · {titel} · " \
           f"{kennzahlen_text(v.get('kennzahlen'))}"
    if v.get("aktuell"):
        text += " · aktuell"
    if ms.get("notiz"):
        text += f"\n  Notiz: {ms['notiz']}"
    return text


def liste_text(res: dict[str, Any], limit: int) -> str:
    vs = res.get("versionen") or []
    gruppen = {g["id"]: g for g in res.get("gruppen") or []}
    varianten = res.get("varianten") or []
    aktuelle_var = next((v["name"] for v in varianten if v.get("aktuell")), "Hauptstand")
    head = f"{fmt.plural(int(res.get('anzahl') or len(vs)), 'Version', 'Versionen')} in {aktuelle_var}"
    if res.get("meilensteine"):
        head += f", {fmt.plural(int(res['meilensteine']), 'Meilenstein', 'Meilensteine')}"
    lines = [head + ":"]
    if res.get("ungesichert"):
        lines.append("- Ungesicherte Änderungen (noch kein erfolgreicher Lauf seit der letzten Änderung)")
    gezeigt = set()
    for v in vs[:limit]:
        g = v.get("gruppe")
        if g and g in gruppen:
            if g in gezeigt:
                continue
            gezeigt.add(g)
            gr = gruppen[g]
            lines.append(f"- V{gr['aelteste']}–V{gr['neueste']}: {gr['text']} (bis {_zeit({'zeit': v.get('zeit')})})")
            continue
        lines.append(version_zeile(v))
    if len(vs) > limit:
        lines.append("… ältere Versionen mit versionen(limit=…) abrufen")
    if len(varianten) > 1:
        lines.append("Varianten: " + ", ".join(f"{v['name']}{' (aktuell)' if v.get('aktuell') else ''}"
                                             for v in varianten))
    return "\n".join(lines)


def _kompakt(v: dict[str, Any]) -> dict[str, Any]:
    out = {k: v.get(k) for k in ("nr", "zeit", "wer", "wer_text", "titel", "quelle", "aktuell", "gruppe", "aus")}
    if v.get("meilenstein"):
        out["meilenstein"] = {k: v["meilenstein"].get(k) for k in ("titel", "notiz")}
    if v.get("kennzahlen"):
        out["kennzahlen"] = v["kennzahlen"]
    if v.get("params"):
        out["params"] = v["params"]
    return out


def register_versionen_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Werkzeuge über den ``tool``-Dekorator aus tools.register_tools."""

    @tool("versionen", "Versionen",
          "Version history of the open project (like Onshape/Fusion): every successful run that changed a project "
          "file is a version V<n> with time, who made it (Kevin or an agent), parts, mass, cost, check result and "
          "parameters; named milestones; variants (branches). Dense series of runs are summarized. Use the V numbers "
          "with version_wiederherstellen, versionen_vergleichen and meilenstein.", READ_ONLY)
    async def versionen(
        limit: Annotated[int, Field(ge=1, le=500, description="Show at most this many newest versions")] = 30,
        variante: Annotated[str | None, Field(description="Variant name; omit for the current one")] = None,
    ) -> CallToolResult:
        res = await t.work("liest die Versionen", svc.versionen, limit, variante)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Versionen nicht lesbar: {err}", res)
        if not res.get("verfuegbar", True):
            return fmt.error_result(res.get("meldung") or "Versionen nicht verfügbar", res)
        data = {"variante": res.get("variante"), "varianten": res.get("varianten"), "anzahl": res.get("anzahl"),
                "ungesichert": res.get("ungesichert"), "gruppen": res.get("gruppen"),
                "versionen": [_kompakt(v) for v in (res.get("versionen") or [])[:limit]]}
        return fmt.result(liste_text(res, limit), data)

    @tool("version_wiederherstellen", "Version wiederherstellen",
          "Restore all project files (model.py, helper modules, geometrie/, bewegungen.json, katalog.json, "
          "kevcad.json, zukauf/) to version V<n> and re-run. Never destructive: unsaved changes are saved as a "
          "version first, and the restore itself becomes a new version 'Wiederhergestellt aus V<n>', so going back "
          "forward is another restore. Returns the new version and the run result. Only on Kevin's request.",
          ADDITIVE)
    async def version_wiederherstellen(
        version: Annotated[str, Field(description="Version: number like 'V12' or '12', or a milestone title")],
    ) -> CallToolResult:
        res = await t.work(f"stellt {version} wieder her", svc.version_wiederherstellen, version)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Nicht wiederhergestellt: {err}", res)
        if res.get("unveraendert"):
            text = f"Der aktuelle Stand entspricht schon V{res.get('aus')}; nichts geändert."
        else:
            text = f"V{res.get('aus')} wiederhergestellt als neue Version V{res.get('version')} ({res.get('titel')})."
        if res.get("gesichert"):
            text += f"\nUngesicherte Änderungen vorher als V{res['gesichert']} gesichert."
        lauf = res.get("lauf") or {}
        if lauf:
            if lauf.get("ok"):
                text += f"\nNeu gerechnet: {fmt.plural(int(lauf.get('teile') or 0), 'Teil', 'Teile')}"
                pr = lauf.get("pruefung") or {}
                if pr.get("zusammenfassung"):
                    text += f", Prüfung: {pr['zusammenfassung']}"
                text += "."
            else:
                text += f"\nLauf fehlgeschlagen: {lauf.get('error')}"
        return fmt.result(text, res, error=bool(lauf) and not lauf.get("ok", True))

    @tool("versionen_vergleichen", "Versionen vergleichen",
          "Compare version a with b (b omitted = the current state): changed parameters, parts (new, removed, "
          "changed shape/position/color/material), bill of materials lines (new, removed, changed), check result, "
          "mass, cost and the code diff of all project files. With zeigen=true (default, b = current) Kevin's viewer "
          "overlays the old version as translucent ghost bodies, colors changed parts orange and new parts green and "
          "shows removed parts in red. Old versions without cached data are re-run in the background first.",
          ADDITIVE)
    async def versionen_vergleichen(
        a: Annotated[str, Field(description="Older version: 'V12', '12' or a milestone title")],
        b: Annotated[str | None, Field(description="Newer version; omit for the current state")] = None,
        zeigen: Annotated[bool, Field(description="Show the comparison in Kevin's viewer")] = True,
        code_zeilen: Annotated[int, Field(ge=0, le=4000, description="Max lines of code diff in the result")] = 150,
    ) -> CallToolResult:
        res = await t.work(f"vergleicht {a} mit {b or 'dem aktuellen Stand'}", svc.versionen_vergleichen, a, b,
                           zeigen=zeigen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Vergleich nicht möglich: {err}", res)
        from kevcad_kernel.versionen.vergleich import text as vergleich_text

        kopf_b = res.get("b") or {}
        ziel = f"V{kopf_b['nr']}" if kopf_b.get("nr") else "aktueller Stand"
        lines = [f"V{(res.get('a') or {}).get('nr')} → {ziel}:", vergleich_text(res)]
        code = res.get("code") or {}
        dateien = code.get("dateien") or []
        if dateien:
            lines.append("Dateien: " + ", ".join(
                f"{d['pfad']} ({'binär' if d.get('binaer') else '+' + str(d.get('plus')) + ' −' + str(d.get('minus'))})"
                for d in dateien[:20]))
            diff = (code.get("diff") or "").splitlines()
            if code_zeilen and diff:
                lines.append("```diff\n" + "\n".join(diff[:code_zeilen]) + "\n```")
                if len(diff) > code_zeilen:
                    lines.append(f"… {len(diff) - code_zeilen} weitere Zeilen (code_zeilen erhöhen)")
        else:
            lines.append("Code: keine Unterschiede")
        if res.get("geister") and zeigen:
            lines.append(f"Im Viewer: {fmt.plural(len(res['geister']), 'Geisterkörper', 'Geisterkörper')} der alten "
                         f"Version, geänderte Teile orange, neue grün.")
        for h in res.get("hinweise") or []:
            lines.append(f"Hinweis: {h}")
        data = {k: v for k, v in res.items() if k != "code"}
        data["code"] = {"dateien": dateien, "gekuerzt": code.get("gekuerzt"), "zeilen": code.get("zeilen")}
        return fmt.result("\n".join(lines), data)

    @tool("meilenstein", "Meilenstein setzen",
          "Mark a version as a named milestone with a short note (default: the current state; unsaved changes "
          "become a version first). Rule: at the end of every task, after the last successful run, set a milestone "
          "with a short German title and a note describing what was done, so Kevin finds the state again.",
          ADDITIVE)
    async def meilenstein(
        titel: Annotated[str, Field(description="Short German title, e.g. 'Stangenhalter mit Gewindeeinsätzen'")],
        notiz: Annotated[str, Field(description="One or two sentences: what changed and why")] = "",
        version: Annotated[str | None, Field(description="Version to mark; omit for the current state")] = None,
    ) -> CallToolResult:
        res = await t.work("setzt einen Meilenstein", svc.meilenstein, titel, notiz, version)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Meilenstein nicht gesetzt: {err}", res)
        text = f"Meilenstein „{titel}“ an V{res.get('version')} gesetzt."
        if res.get("warnung"):
            text += f"\nAchtung: {res['warnung']}"
        return fmt.result(text, res)

    @tool("variante", "Varianten",
          "Variants are named branches of the project to try an idea without touching the main state "
          "(Hauptstand). aktion 'liste' lists them; 'anlegen' creates variant name from version von (default the "
          "current state) and switches to it; 'wechseln' switches to variant name (unsaved changes are saved as a "
          "version first) and re-runs; 'umbenennen' renames it to neuer_name. Each variant has its own version "
          "history. There is no merging: Kevin picks a variant and continues there.", ADDITIVE)
    async def variante(
        aktion: Annotated[Literal["liste", "anlegen", "wechseln", "umbenennen"],
                          Field(description="What to do")] = "liste",
        name: Annotated[str | None, Field(description="Variant name (e.g. 'Leichtbau'); 'Hauptstand' is the "
                                                      "main state")] = None,
        von: Annotated[str | None, Field(description="anlegen: start version, e.g. 'V12'")] = None,
        neuer_name: Annotated[str | None, Field(description="umbenennen: new name")] = None,
    ) -> CallToolResult:
        res = await t.work("arbeitet mit Varianten", svc.variante, aktion, name, von, neuer_name)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Variante: {err}", res)
        varianten = res.get("varianten") or []
        liste = ", ".join(f"{v['name']}{' (aktuell)' if v.get('aktuell') else ''} ({v.get('versionen', 0)} V.)"
                          for v in varianten)
        if aktion == "liste":
            text = f"Varianten: {liste}"
        elif aktion == "anlegen":
            text = f"Variante „{res.get('name')}“ von V{res.get('von')} angelegt und aktiv."
        elif aktion == "wechseln":
            text = f"Zu Variante „{res.get('name')}“ gewechselt."
        else:
            text = f"Variante heißt jetzt „{res.get('name')}“."
        if res.get("gesichert"):
            text += f" Ungesicherte Änderungen vorher als V{res['gesichert']} gesichert."
        lauf = res.get("lauf") or {}
        if lauf and not lauf.get("ok", True):
            text += f"\nLauf fehlgeschlagen: {lauf.get('error')}"
        if aktion != "liste":
            text += f"\nVarianten: {liste}"
        return fmt.result(text, res)

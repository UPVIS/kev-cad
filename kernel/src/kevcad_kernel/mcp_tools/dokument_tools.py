"""MCP-Werkzeug ``dokument_export`` (Phase 6, Strang P6-A2; DOKUMENTE.md, Anhang „Export“): Die App baut ein PDF aus
Bausteinen (Deckblatt, Stückliste, Teileliste, Einkaufsliste, Zuschnitt, Zeichnungen, Bauplan) und öffnet auf Wunsch
den Druckdialog. Beschreibung englisch (für das Modell), Ergebnis deutsch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from kevcad_kernel.dokument_export import BAUSTEIN_TITEL, BAUSTEINE

from . import format as fmt

DOKUMENT_TOOL_NAMES: tuple[str, ...] = ("dokument_export",)

WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def export_text(res: dict[str, Any]) -> str:
    seiten = int(res.get("seiten") or 0)
    teile = []
    for b in res.get("bausteine") or []:
        titel = BAUSTEIN_TITEL.get(str(b.get("art")), str(b.get("art")))
        n = int(b.get("seiten") or 0)
        teile.append(f"{titel} {fmt.plural(n, 'Seite', 'Seiten')}" if n else f"{titel} (leer)")
    zeilen = []
    if res.get("pfad"):
        zeilen.append(f"PDF mit {fmt.plural(seiten, 'Seite', 'Seiten')}: {res['pfad']}")
    else:
        zeilen.append(f"Dokument mit {fmt.plural(seiten, 'Seite', 'Seiten')} gebaut (ohne Datei).")
    if teile:
        zeilen.append("Inhalt: " + "; ".join(teile))
    formate = res.get("formate") or {}
    if formate:
        zeilen.append("Formate: " + ", ".join(f"{k} {fmt.plural(int(v), 'Seite', 'Seiten')}" for k, v in formate.items()))
    if res.get("gedruckt"):
        zeilen.append(f"Druck: {res['gedruckt']}")
    for h in res.get("hinweise") or []:
        zeilen.append(f"Hinweis: {h}")
    if res.get("ms"):
        namen = {"bauplan_ms": "Bauplan", "blaetter_ms": "Blätter", "bilder_ms": "Bilder", "seiten_ms": "Seiten",
                 "pdf_ms": "PDF"}
        teile_zeit = [f"{namen.get(k, k)} {fmt.num(float(v) / 1000, 1)} s" for k, v in (res.get("phasen") or {}).items()
                      if v and float(v) >= 50]
        zeilen.append(f"Gebaut in {fmt.num(float(res['ms']) / 1000, 1)} s"
                      + (f" ({', '.join(teile_zeit)})." if teile_zeit else "."))
    return "\n".join(zeilen)


def register_dokument_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert das Werkzeug über den ``tool``-Dekorator aus tools.register_tools."""

    @tool("dokument_export", "Dokumente exportieren",
          "Have the app build one vector PDF from building blocks, the same pages as the app's export dialog "
          f"(Dokumente exportieren …): {', '.join(BAUSTEINE)}. Every page has header and footer (project, version, "
          "page x/y); tables break between rows and repeat their header; drawing sheets keep their scale (A4 and A3 "
          "mixed in one file). bausteine: list of names in the wanted order, or objects {art, spalten?: [column ids], "
          "auswahl?: [sheet ids] (only zeichnungen)}; empty or 'alle' = everything in the standard order; "
          "'vorlage:<name>' uses a template Kevin saved in the dialog; {format: 'A4'|'A3', ausrichtung: 'hoch'|'quer'} "
          "sets the paper of the report pages. ziel: path of the .pdf (relative = inside <project>/output/); default "
          "<project>/output/<project>-dokumente.pdf. drucken=true additionally opens the macOS print dialog (one job "
          "per paper size, 1:1 without scaling): only when Kevin explicitly asks to print, never on your own. "
          "Check the PDF yourself if needed, but do not send page images to Kevin.", WRITES)
    async def dokument_export(
        bausteine: Annotated[list[Any] | None, Field(
            description="Building blocks in order: names (deckblatt, stueckliste, teileliste, einkaufsliste, "
                        "zuschnitt, zeichnungen, bauplan) or objects {art, spalten, auswahl}; empty = all")] = None,
        ziel: Annotated[str | None, Field(description="Target .pdf path; empty = <project>/output/<name>-dokumente.pdf")]
        = None,
        drucken: Annotated[bool, Field(description="Open the print dialog. Only if Kevin explicitly asked to print.")]
        = False,
    ) -> CallToolResult:
        res = await t.work("exportiert Dokumente" + (" und öffnet den Druckdialog" if drucken else ""),
                           svc.dokument_export, bausteine, ziel, drucken)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, res)
        return fmt.result(export_text(res), {k: res.get(k) for k in ("pfad", "seiten", "bausteine", "formate",
                                                                    "gedruckt", "hinweise", "ms", "phasen", "vorlage")})

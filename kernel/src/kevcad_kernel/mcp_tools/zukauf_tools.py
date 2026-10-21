"""MCP-Werkzeuge für Zukaufteile (Phase 3): zukauf_anlegen, zukauf_html, cad_suchen, cad_uebernehmen, zukauf_liste.

Wie die anderen Werkzeuge: Beschreibungen englisch (für das Modell), Ergebnisse deutsch. Nur gegen ``KernelService``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp_types import CallToolResult
from pydantic import Field

from . import format as fmt

Ebene = Literal["projekt", "eigen"]


def _links_text(links: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {link.get('titel')}: {link.get('url')}" for link in links or [])


def _pruefung_text(pr: dict[str, Any] | None) -> list[str]:
    if not pr:
        return []
    out = []
    korr = pr.get("korrigiert")
    if korr:
        out.append("Hüllmaß " + " × ".join(fmt.num(v, 1) for v in korr) + " mm"
                   + (f" (Katalog {' × '.join(fmt.num(v, 1) for v in pr['soll'])} mm)" if pr.get("soll") else ""))
    return out


def zukauf_tabelle(items: list[dict[str, Any]]) -> str:
    rows = [["id", "Name", "Hersteller", "Nummer", "Maße", "Preis", "CAD", "Ebene", "Status"]]
    from kevcad_kernel.zukauf.eintrag import masse_text

    for it in items:
        preis = it.get("preis") if isinstance(it.get("preis"), dict) else {}
        p = fmt.money(preis.get("je_stueck")) if preis.get("je_stueck") is not None else ""
        if p and preis.get("brutto") is not None:
            p += " brutto" if preis["brutto"] else " netto"
        cad = it.get("cad_art") or ""
        if it.get("cad_datei_fehlt"):
            cad = "Datei fehlt"
        elif it.get("zustand") == "wartet_auf_cad":
            cad = "wartet auf CAD"
        rows.append([str(it.get("id", "")), str(it.get("name", "")), str(it.get("hersteller") or ""),
                     str(it.get("mpn") or it.get("shop_nr") or ""), masse_text(it.get("masse")) if it.get("masse")
                     else "", p, cad, str(it.get("ebene", "")), fmt.status_text(it)])
    return fmt.table(rows)


def register_zukauf_tools(tool: Callable[..., Any], t: Any, svc: Any) -> None:
    """Registriert die Zukauf-Werkzeuge mit dem ``tool``-Dekorator aus ``register_tools``."""
    from .tools import ADDITIVE, READ_ONLY, WRITES, ToolInputError

    @tool("zukauf_anlegen", "Zukaufteil anlegen",
          "Add a purchased part (Zukaufteil: drawer slide, hinge, castor, trolley, camera accessory …) to the catalog "
          "from a shop link, manufacturer part number (mpn) or EAN/GTIN. Kev CAD never loads shop pages itself: read "
          "the page with your own tools first and pass what you found in felder (name, hersteller, mpn, gtin, url, "
          "bild, preis {je_stueck, waehrung, brutto, stand}, masse {l, b, h} or {d, l} in mm, gewicht in g, material, "
          "einbaupunkt, bezugspunkte) – or pass the page HTML to zukauf_html instead. Standard parts like 'ISO 4762 "
          "M6x20' are redirected to the stock catalog (no purchased part). The entry is a proposal (status "
          "'vorgeschlagen') until Kevin releases it in the stock catalog; ebene 'projekt' (default) or 'eigen' for "
          "parts used in many projects. Without CAD it appears as a simplified box/cylinder; next call cad_suchen.",
          WRITES)
    async def zukauf_anlegen(
        url: Annotated[str | None, Field(description="Product page URL")] = None,
        mpn: Annotated[str | None, Field(description="Manufacturer part number (or a standard part text)")] = None,
        gtin: Annotated[str | None, Field(description="EAN/GTIN, 8 to 14 digits")] = None,
        felder: Annotated[dict[str, Any] | None, Field(description="Fields as in KATALOG.md (Zukaufteil)")] = None,
        ebene: Annotated[Ebene, Field(description="projekt = this project, eigen = Kevin's own catalog")] = "projekt",
    ) -> CallToolResult:
        if not (url or mpn or gtin or felder):
            raise ToolInputError("url, mpn, gtin oder felder angeben.")
        what = mpn or gtin or (felder or {}).get("name") or url or "Teil"
        res = await t.work(f"legt Zukaufteil {what} an", svc.zukauf_anlegen, url, mpn, gtin, felder, ebene)
        err = fmt.service_error(res)
        if err:
            lines = [f"Zukaufteil nicht angelegt:\n{err}"]
            if res.get("zu_pruefen"):
                lines.append("Fehlt oder unsicher: " + ", ".join(res["zu_pruefen"]))
            return fmt.error_result("\n".join(lines), res)
        if res.get("normteil"):
            text = res.get("text", "Normteil")
            if res.get("beispiel"):
                text += f"\nIn model.py:\n{res['beispiel']}"
            if res.get("vorschlag"):
                text += "\nVorschlag für stock_define (nur auf Kevins Wunsch) in \"vorschlag\"."
            return fmt.result(text, res)
        if not res.get("angelegt"):
            return fmt.result(res.get("text", "Nicht angelegt."), res)
        item = res.get("item") or {}
        lines = [res.get("text") or f"{item.get('id')} angelegt", f"Datei: {res.get('datei')}"]
        if item.get("status") == "vorgeschlagen":
            lines.append("Es wartet auf Kevins Freigabe im Lagerkatalog; bis dahin lässt es sich nicht verbauen. "
                         "Kevin Bescheid geben.")
        if res.get("zu_pruefen"):
            lines.append("Von Kevin bestätigen lassen: " + ", ".join(res["zu_pruefen"]))
        for note in res.get("hinweise") or []:
            lines.append(f"Hinweis: {note}")
        lines.append(f"In model.py: lager.zukauf({item.get('id')!r}).verbauen(\"{item.get('name')}\"). Ohne CAD "
                     f"erscheint es vereinfacht; cad_suchen(\"{item.get('id')}\") sucht das Hersteller-Modell.")
        return fmt.result("\n".join(lines), res)

    @tool("zukauf_html", "Shop-Seite auswerten",
          "Extract product data from the HTML of a shop page that YOU fetched (browser or web fetch tool): JSON-LD, "
          "Microdata, RDFa and Open Graph give name, brand, mpn, EAN, price (gross/net), image, dimensions and weight. "
          "Returns the fields and a draft entry plus what Kevin must confirm. anlegen=true also creates the proposal "
          "(same as zukauf_anlegen). Kev CAD does not fetch pages and does not bypass bot protection.", ADDITIVE)
    async def zukauf_html(
        url: Annotated[str | None, Field(description="URL of the page the HTML comes from")],
        html: Annotated[str, Field(description="Full HTML source of the product page")],
        anlegen: Annotated[bool, Field(description="Create the purchased part right away")] = False,
        ebene: Annotated[Ebene, Field(description="Catalog level when anlegen=true")] = "projekt",
    ) -> CallToolResult:
        if not html or not html.strip():
            raise ToolInputError("html ist leer: den Quelltext der Produktseite übergeben.")
        res = await t.work("wertet eine Shop-Seite aus", svc.zukauf_html, url, html, anlegen, ebene)
        err = fmt.service_error(res)
        felder = res.get("felder") or {}
        lines = []
        if res.get("quellen"):
            lines.append("Gelesen aus " + ", ".join(res["quellen"]) + ":")
        else:
            lines.append("Keine strukturierten Produktdaten gefunden.")
        for key, label in (("name", "Name"), ("hersteller", "Hersteller"), ("mpn", "Herstellernummer"),
                           ("gtin", "EAN"), ("shop_nr", "Shop-Nummer"), ("bild", "Bild")):
            if felder.get(key):
                lines.append(f"- {label}: {felder[key]}")
        entwurf = res.get("entwurf") or {}
        if entwurf.get("masse"):
            from kevcad_kernel.zukauf.eintrag import masse_text

            lines.append(f"- Maße: {masse_text(entwurf['masse'])}")
        preis = entwurf.get("preis") or {}
        if preis.get("je_stueck") is not None:
            art = {True: " brutto", False: " netto"}.get(preis.get("brutto"), " (brutto/netto unklar)")
            lines.append(f"- Preis: {fmt.money(preis['je_stueck'])}{art}, Stand {preis.get('stand')}")
        if felder.get("gewicht"):
            lines.append(f"- Gewicht: {fmt.num(felder['gewicht'], 0)} g")
        if res.get("normteil"):
            lines.append(res.get("text", ""))
        if res.get("zu_pruefen"):
            lines.append("Von Kevin bestätigen lassen: " + ", ".join(res["zu_pruefen"]))
        for note in res.get("hinweise") or []:
            lines.append(f"Hinweis: {note}")
        created = res.get("angelegt")
        if isinstance(created, dict) and created.get("ok") and created.get("angelegt"):
            item = created.get("item") or {}
            lines.append(f"Angelegt als {item.get('id')} (Vorschlag, wartet auf Kevins Freigabe). Weiter mit "
                         f"cad_suchen(\"{item.get('id')}\").")
        elif isinstance(created, dict) and created.get("text"):
            lines.append(created["text"])
        elif not anlegen and not res.get("normteil"):
            lines.append("Felder prüfen, fehlende ergänzen und mit zukauf_anlegen(url, felder=…) anlegen.")
        if err:
            return fmt.error_result("\n".join(lines + [f"Nicht angelegt: {err}"]), res)
        return fmt.result("\n".join(lines), res)

    @tool("cad_suchen", "CAD suchen",
          "Find the manufacturer CAD model (STEP) for a purchased part. With Kevin's TraceParts API key it is fetched "
          "and imported automatically (show 'powered by TraceParts'). Otherwise it returns links (product page, "
          "manufacturer portal like MISUMI, item, igus, McMaster, TraceParts, 3Dfindit/CADENAS, web search): ask "
          "Kevin to download the STEP or ZIP with his account, then call cad_uebernehmen. The app watches ~/Downloads "
          "meanwhile.", ADDITIVE)
    async def cad_suchen(
        id: Annotated[str, Field(description="Zukaufteil id")],
    ) -> CallToolResult:
        res = await t.work(f"sucht CAD für {id}", svc.cad_suchen, id)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"CAD-Suche fehlgeschlagen: {err}", res)
        lines = [res.get("text") or ""]
        if res.get("zustand") == "importiert" and res.get("powered_by"):
            lines.append(f"Quelle: TraceParts ({res['powered_by']}).")
            lines += _pruefung_text(res.get("pruefung"))
        if res.get("zustand") == "wartet_auf_cad":
            lines.append("Links zum Herunterladen (Kevin mit seinem Konto):")
            lines.append(_links_text(res.get("cad_links") or []))
            lines.append(f"Kevin bitten, die STEP-Datei (oder ein ZIP mit STEP) herunterzuladen; danach "
                         f"cad_uebernehmen(\"{id}\") ohne Pfad.")
        for note in res.get("hinweise") or []:
            lines.append(f"Hinweis: {note}")
        return fmt.result("\n".join(x for x in lines if x), res)

    @tool("cad_uebernehmen", "CAD übernehmen",
          "Import the CAD file for a purchased part: pfad, or without pfad the newest matching .step/.stp/.zip from "
          "~/Downloads of the last minuten (ZIP is unpacked, the STEP with the part number wins). Units (inch, cm, m) "
          "and up axis (Y up) are checked against the catalog dimensions and corrected; a model that does not match "
          "is rejected with the reason (erzwingen=true takes it anyway). The file is stored in the project folder "
          "zukauf/<id>/ (never in git) and the catalog entry gets cad.quelle/datei. Then run again.", WRITES)
    async def cad_uebernehmen(
        id: Annotated[str, Field(description="Zukaufteil id")],
        pfad: Annotated[str | None, Field(description="CAD file path; omit to take the newest download")] = None,
        minuten: Annotated[float, Field(ge=1, le=1440, description="How far back to look in ~/Downloads")] = 30,
        erzwingen: Annotated[bool, Field(description="Accept even if the size does not match the catalog")] = False,
    ) -> CallToolResult:
        res = await t.work(f"übernimmt CAD für {id}", svc.cad_uebernehmen, id, pfad, minuten, erzwingen)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"CAD nicht übernommen: {err}", res)
        lines = [res.get("text") or "CAD übernommen"]
        lines += _pruefung_text(res.get("pruefung"))
        if res.get("grob"):
            lines.append(f"Großes Modell ({fmt.num(res.get('flaechen'), 0)} Flächen): wird grob tesselliert.")
        lines.append(f"Datei: {res.get('datei')}")
        item = res.get("item") or {}
        if item.get("status") == "vorgeschlagen":
            lines.append("Das Teil wartet noch auf Kevins Freigabe im Lagerkatalog.")
        lines.append("Jetzt run aufrufen; das Teil erscheint mit dem Hersteller-Modell.")
        return fmt.result("\n".join(lines), res)

    @tool("zukauf_liste", "Zukaufteile",
          "List purchased parts in the catalog (all levels): id, name, manufacturer, part number, dimensions, price "
          "with gross/net, CAD state (hersteller / skript / vereinfacht / waiting for CAD) and release status. query "
          "filters by text.", READ_ONLY)
    async def zukauf_liste(
        query: Annotated[str, Field(description="Filter text, e.g. 'alutec' or '05200'")] = "",
    ) -> CallToolResult:
        res = await t.work("listet Zukaufteile", svc.zukauf_liste, query)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(f"Zukaufteile nicht lesbar: {err}", res)
        items = res.get("items") or []
        if not items:
            return fmt.result("Keine Zukaufteile" + (f" für „{query}“." if query else " im Katalog.")
                              + " Neue mit zukauf_anlegen (oder zukauf_html).", res)
        text = f"{fmt.plural(len(items), 'Zukaufteil', 'Zukaufteile')}:\n{zukauf_tabelle(items)}"
        text += "\nIn model.py: lager.zukauf(\"<id>\").verbauen(\"Name\")."
        return fmt.result(text, res)

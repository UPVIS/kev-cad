"""MCP-Werkzeug ``feedback`` (V2-6): Kevins Sprach-Feedback abwarten und als knappen Text mit Bild zurückgeben.

Der Text entsteht hier aus dem Paket ``kevcad-feedback/1`` (PROTOCOL.md); Einzelheiten stehen in der JSON-Datei daneben,
deren Pfad das Ergebnis nennt. Das Warten läuft in einem Worker-Faden und holt nichts ab: Bricht der Agent ab, bleibt das
Paket offen.
"""

from __future__ import annotations

import base64
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import anyio
from mcp_types import CallToolResult, ImageContent
from pydantic import Field

from kevcad_kernel.protocol import FEEDBACK_WARTEN_MAX_S, FEEDBACK_WARTEN_S
from kevcad_kernel.service import KernelService

from . import format as fmt

ZEIGER_JE_ZEILE = 3


def hintergrund_befehl(port: int | None) -> str:
    """Befehl für eine Hintergrund-Shell: endet, sobald Feedback da ist."""
    programm = Path(sys.executable).with_name("kevcad-feedback")
    return f'"{programm}"' + (f" --port {port}" if port else "")


def zeit_text(t: Any) -> str:
    """Sekunden als „0:07“."""
    s = int(t) if isinstance(t, (int, float)) else 0
    return f"{s // 60}:{s % 60:02d}"


def _bezug_text(b: dict[str, Any], striche: dict[Any, dict[str, Any]]) -> str:
    if b.get("art") == "strich":
        s = striche.get(b.get("strich")) or {}
        teile = ", ".join(b.get("teile") or [])
        ort = f"auf {teile}" if teile else "in der Bildebene"
        return f"Strich {b.get('strich')} {ort}, {fmt.num(s.get('laenge_mm'), 0)} mm"
    wort = f"„{b['wort']}“ = " if b.get("wort") else ""
    ort = f" bei {fmt.vec(b['punkt'], 0)}" if isinstance(b.get("punkt"), list) else ""
    return f"{wort}{b.get('ref') or b.get('teil')}{ort}"


def feedback_text(paket: dict[str, Any], aktueller_lauf: int | None = None) -> str:
    """Knapper Text für den Agenten: je Satz die Worte und worauf Kevin dabei gezeigt hat."""
    saetze = paket.get("saetze") or []
    striche = {s.get("nr"): s for s in paket.get("striche") or []}
    kopf = (f"Kevin ist fertig: {fmt.plural(len(saetze), 'Satz', 'Sätze')}, "
            f"{fmt.plural(len(striche), 'Strich', 'Striche')}, {zeit_text(paket.get('dauer_s'))} "
            f"({paket.get('name')}, Lauf {paket.get('run')})")
    zeilen = [kopf]
    for s in saetze:
        hinweis = " (noch nicht endgültig erkannt)" if s.get("vorlaeufig") else ""
        zeilen.append(f"{s.get('nr')}. [{zeit_text(s.get('von'))}] „{s.get('text')}“{hinweis}")
        bezuege = [_bezug_text(b, striche) for b in s.get("bezuege") or []]
        if bezuege:
            zeilen.append("   → " + "; ".join(bezuege))
        refs = (s.get("auswahl") or {}).get("refs") or []
        if refs:
            zeilen.append("   ausgewählt: " + ", ".join(refs[:ZEIGER_JE_ZEILE])
                          + (f" und {len(refs) - ZEIGER_JE_ZEILE} weitere" if len(refs) > ZEIGER_JE_ZEILE else ""))
    if not saetze:
        zeilen.append("Gesprochen hat er nichts.")
    frei = [s for nr, s in striche.items() if not any(
        b.get("strich") == nr for satz in saetze for b in satz.get("bezuege") or [])]
    for s in frei:
        zeilen.append("Ohne Satz: " + _bezug_text({"art": "strich", "strich": s.get("nr"), "teile": s.get("teile")},
                                                  striche))
    ende = paket.get("ende") if isinstance(paket.get("ende"), dict) else {}
    sichtbar = ende.get("sichtbar")
    if isinstance(sichtbar, list):
        verborgen = ende.get("verborgen") or []
        zeilen.append(f"Im Bild: {fmt.plural(len(sichtbar), 'Teil', 'Teile')}"
                      + (f", {len(verborgen)} ausgeblendet" if verborgen else ""))
    if aktueller_lauf is not None and aktueller_lauf != paket.get("run"):
        zeilen.append(f"Refs gelten für Lauf {paket.get('run')}, aktuell ist Lauf {aktueller_lauf}: Teilnamen bleiben, "
                      "Flächen und Kanten neu suchen.")
    return "\n".join(zeilen)


def stand_text(stand: dict[str, Any]) -> str:
    """Eine Zeile für ``status`` und den Zeitablauf; leer, wenn nichts los ist."""
    teile = []
    if stand.get("stand") == "spricht":
        teile.append(f"Kevin spricht gerade (seit {fmt.num(stand.get('seit_s'), 0)} s): nichts Neues starten, "
                     "feedback() wartet, bis er fertig ist")
    elif stand.get("stand") == "pause":
        teile.append("Kevin hat eine Sprachsitzung offen (Pause)")
    if stand.get("offen"):
        teile.append(f"{fmt.plural(int(stand['offen']), 'Feedback', 'Feedbacks')} wartet: feedback() holt es")
    return " · ".join(teile)


def register_feedback_tool(tool: Callable[..., Any], t: Any, svc: KernelService, read_only: Any) -> None:
    """``tool(name, titel, beschreibung, annotations)`` meldet das Werkzeug am Server an (kern.py)."""

    @tool("feedback", "Kevins Feedback",
          "Wait until Kevin has finished speaking and return his voice feedback: his sentences with what he pointed "
          "at (part, face, 3D point) or drew at that moment, plus an image with his strokes. Returns at once if a "
          "package is waiting, else waits up to warten_s. Time running out is no error: it says what he is doing. "
          "nochmal=true returns the last package again.", read_only)
    async def feedback(
        warten_s: Annotated[float, Field(ge=0, le=FEEDBACK_WARTEN_MAX_S, description=(
            "Seconds to wait for Kevin; 0 only looks"))] = FEEDBACK_WARTEN_S,
        nochmal: Annotated[bool, Field(description="Return the last fetched package again")] = False,
    ) -> CallToolResult:
        if not nochmal:
            abbruch = threading.Event()
            try:
                stand = await t.work("wartet auf Kevin", svc.feedback_warten, warten_s, abbruch)
            except anyio.get_cancelled_exc_class():
                abbruch.set()
                raise
            if not stand.get("da"):
                return _zeitablauf(stand, warten_s, svc)
        res = await t.work(None, svc.feedback_holen, nochmal)
        err = fmt.service_error(res)
        if err:
            return fmt.error_result(err, {k: v for k, v in res.items() if k != "bild"})
        if res.get("leer"):
            return fmt.result("Noch nichts abgeholt, es gibt kein früheres Feedback.", {"leer": True}, json_block=False)
        paket = res["paket"]
        text = feedback_text(paket, await t.work(None, _aktueller_lauf, svc))
        if res.get("offen"):
            text += f"\nDanach wartet noch {fmt.plural(int(res['offen']), 'Feedback', 'Feedbacks')}: feedback()."
        text += f"\nEinzelheiten (Wörter, Mausweg, Striche): {res.get('json_pfad')}"
        extra: list[Any] = []
        if res.get("bild"):
            extra.append(ImageContent(type="image", data=base64.b64encode(res["bild"]).decode("ascii"),
                                      mime_type="image/jpeg"))
        return fmt.result(text, {"name": res.get("name"), "saetze": len(paket.get("saetze") or []),
                                 "striche": len(paket.get("striche") or []), "datei": res.get("json_pfad"),
                                 "bild": res.get("bild_pfad"), "offen": res.get("offen")},
                          json_block=False, extra=extra)


def _aktueller_lauf(svc: KernelService) -> int | None:
    try:
        last = svc.status().get("last_run")
        return last.get("run") if isinstance(last, dict) else None
    except Exception:  # noqa: BLE001 - nur ein Hinweis im Text
        return None


def _zeitablauf(stand: dict[str, Any], warten_s: float, svc: KernelService) -> CallToolResult:
    wo = {"spricht": "Kevin spricht noch.", "pause": "Kevin hat die Sitzung noch offen (Pause)."}
    text = f"Noch kein Feedback nach {fmt.num(warten_s, 0)} s. " + wo.get(str(stand.get("stand")), "Kevin spricht nicht.")
    text += (" Nochmal feedback() aufrufen oder den Zug beenden; zum Aufwecken vorher als Hintergrund-Befehl starten: "
             + hintergrund_befehl(getattr(svc, "mcp_port", None)))
    return fmt.result(text, {"da": False, "stand": stand.get("stand")}, json_block=False)

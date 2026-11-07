"""``kevcad-feedback``: endet genau dann, wenn Kevin mit dem Sprechen fertig ist (V2-6, PROTOCOL.md).

Ein Agent ist nur aktiv, solange er eine Runde läuft. Er startet diesen Befehl als Hintergrund-Shell und beendet seinen
Zug; endet der Befehl, weckt das den Agenten, und ``feedback()`` holt das Paket ab. Der Befehl holt selbst nichts ab und
braucht nur die Standardbibliothek. Neustarts von Kev CAD übersteht er.

Ausgang 0: Feedback ist da. 2: ``--warten-s`` abgelaufen.

``--zuhoerer`` fragt nur, ob gerade jemand auf Kevin wartet (Ausgang 0 ja, 1 niemand, 3 Kev CAD nicht erreichbar oder
keine App verbunden). ``--stop-hook`` ist der Stop-Hook für Claude Code (Kevin, 07.11.2026: „der MCP-Server hört einfach
irgendwann auf zuzuhören … Das muss also explizit funktionieren“): Will ein Agent seine Runde beenden, nachdem er seit
Kevins letzter eigener Nachricht mit Kev CAD gearbeitet hat (oder sein Zuhörer gerade geendet hat), während die App
verbunden ist und niemand zuhört, hält ihn der Hook einmal an und nennt den Befehl. So reißt das Zuhören weder nach einem
Feedback noch nach dem Ablauf der Zeitgrenze einer Hintergrund-Shell ab. Als Kev-CAD-Arbeit zählen nur echte Aufrufe im
Transkript: Die Werkzeugliste darin nennt die Werkzeuge von Kev CAD in jeder Sitzung, auch in solchen, die sie nie
benutzen.
"""

from __future__ import annotations

import argparse
import json
import mmap
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

DEFAULT_PORT = 47823
ANFRAGE_S = 300.0  # eine Anfrage, gleich dem Höchstwert des Kernels
ERNEUT_S = 2.0  # so lange wartet er, wenn Kev CAD gerade nicht läuft
# Claude Code beendet Hintergrund-Shells nach der Zeitgrenze des Aufrufs (Vorgabe 30 min, höchstens 2 h); deshalb immer
# den Höchstwert mitgeben und danach neu starten.
ZEITGRENZE_MS = 7_200_000
PROGRAMM = "kevcad-feedback"
KEVCAD_WERKZEUGE = "mcp__kevcad__"
TRANSKRIPT_ENDE = 4_000_000  # so viele Bytes vom Ende des Transkripts liest der Stop-Hook
HOECHSTENS_MELDUNGEN = 5  # so viele Meldungen fertiger Hintergrundbefehle sieht er nach


def befehl(port: int | None) -> str:
    """Der Hintergrundbefehl, wie ihn status und feedback() nennen."""
    programm = Path(sys.executable).with_name(PROGRAMM)
    return f'"{programm}"' + (f" --port {port}" if port and port != DEFAULT_PORT else "")


def warten(port: int, warten_s: float | None, *, erneut_s: float = ERNEUT_S) -> dict | None:
    """Gibt die Antwort des Kernels zurück, sobald ein Paket offen ist, sonst None nach ``warten_s``."""
    ende = None if warten_s is None else time.monotonic() + warten_s
    while True:
        rest = ANFRAGE_S if ende is None else min(ANFRAGE_S, ende - time.monotonic())
        if rest <= 0:
            return None
        url = f"http://127.0.0.1:{port}/feedback/warten?warten_s={rest:.1f}"
        try:
            with urllib.request.urlopen(url, timeout=rest + 10) as antwort:  # noqa: S310 - nur localhost
                daten = json.load(antwort)
            if daten.get("da"):
                return daten
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(erneut_s)  # Kev CAD läuft nicht oder startet gerade neu


def stand(port: int, timeout_s: float = 1.5) -> dict | None:
    """Stand des Feedbacks ohne zu warten (``zuhoerer``, ``app``, ``offen``); None, wenn Kev CAD nicht antwortet."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/feedback/warten?warten_s=0",  # noqa: S310
                                    timeout=timeout_s) as antwort:
            daten = json.load(antwort)
        return daten if isinstance(daten, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _ende_lesen(transkript: str) -> bytes:
    """Die letzten ``TRANSKRIPT_ENDE`` Bytes des Transkripts (JSON je Zeile)."""
    with open(transkript, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - TRANSKRIPT_ENDE))
        return f.read()


def _eintraege_rueckwaerts(daten: bytes) -> Iterator[dict]:
    """Einträge vom Ende her."""
    for zeile in reversed(daten.splitlines()):
        try:
            eintrag = json.loads(zeile)
        except ValueError:
            continue  # etwa die angeschnittene erste Zeile
        if isinstance(eintrag, dict):
            yield eintrag


def _aufrufe(eintrag: dict) -> list[dict]:
    """Die Werkzeugaufrufe einer Antwort des Agenten."""
    inhalt = (eintrag.get("message") or {}).get("content") if eintrag.get("type") == "assistant" else None
    return [b for b in inhalt if isinstance(b, dict) and b.get("type") == "tool_use"] if isinstance(inhalt, list) else []


def _kevcad_aufruf(aufruf: dict) -> bool:
    """Ein Werkzeug von Kev CAD oder der Zuhörer im Hintergrund (eine Suche nach dem Namen zählt nicht)."""
    if str(aufruf.get("name") or "").startswith(KEVCAD_WERKZEUGE):
        return True
    eingabe = aufruf.get("input")
    return (isinstance(eingabe, dict) and eingabe.get("run_in_background") is True
            and PROGRAMM in str(eingabe.get("command") or ""))


def _kevin_schreibt(eintrag: dict) -> bool:
    """Eine Nachricht von Kevin selbst: keine Werkzeugantwort, kein eingeschobener Hinweis."""
    if eintrag.get("type") != "user" or eintrag.get("isMeta"):
        return False
    inhalt = (eintrag.get("message") or {}).get("content")
    return isinstance(inhalt, str) or (isinstance(inhalt, list) and any(
        isinstance(b, dict) and b.get("type") == "text" for b in inhalt))


def _meldung(eintrag: dict) -> str | None:
    """Werkzeugaufruf, dessen Hintergrundbefehl die Meldung betrifft (die Meldung weckt den Agenten)."""
    anhang = eintrag.get("attachment") if eintrag.get("type") == "attachment" else None
    if not isinstance(anhang, dict) or anhang.get("type") != "queued_command":
        return None
    treffer = re.search(r"<tool-use-id>([^<\s]+)</tool-use-id>", str(anhang.get("prompt") or ""))
    return treffer.group(1) if treffer else None


def _aufruf_suchen(daten, muster: bytes, kennung: str) -> dict | None:
    """Der Werkzeugaufruf mit dieser Kennung in ``daten`` (bytes oder mmap); jede Fundstelle gibt eine ganze Zeile."""
    stelle = daten.find(muster)
    while stelle != -1:
        anfang = daten.rfind(b"\n", 0, stelle) + 1
        ende = daten.find(b"\n", stelle)
        ende = len(daten) if ende == -1 else ende
        try:
            eintrag = json.loads(daten[anfang:ende])
        except ValueError:
            eintrag = None
        if isinstance(eintrag, dict):
            for aufruf in _aufrufe(eintrag):
                if aufruf.get("id") == kennung:
                    return aufruf
        stelle = daten.find(muster, ende)
    return None


def _war_zuhoerer(transkript: str, ende: bytes, kennung: str) -> bool:
    """War der Hintergrundbefehl zu diesem Aufruf der Zuhörer? Erst im schon gelesenen Ende, dann im ganzen Transkript
    (der Aufruf kann Stunden alt sein); dort zuerst genau als Aufruf geschrieben, das überspringt Antworten und Meldungen."""
    aufruf = _aufruf_suchen(ende, kennung.encode(), kennung)
    if aufruf is None:
        with open(transkript, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as alles:
            aufruf = (_aufruf_suchen(alles, f'"id":"{kennung}"'.encode(), kennung)
                      or _aufruf_suchen(alles, kennung.encode(), kennung))
    return aufruf is not None and _kevcad_aufruf(aufruf)


def kevcad_runde(transkript: str | None) -> bool:
    """Hat der Agent seit Kevins letzter eigener Nachricht mit Kev CAD gearbeitet, oder hat ihn gerade das Ende seines
    Zuhörers geweckt? Nur echte Aufrufe zählen, nicht die Werkzeugliste, die jedes Transkript mitführt. Wer früher in der
    Sitzung einmal auf Kev CAD geschaut hat und jetzt anderes tut, wird nicht angehalten."""
    if not transkript:
        return False
    meldungen: list[str] = []
    try:
        ende = _ende_lesen(transkript)
        for eintrag in _eintraege_rueckwaerts(ende):
            if any(_kevcad_aufruf(a) for a in _aufrufe(eintrag)):
                return True
            if _kevin_schreibt(eintrag):
                break
            kennung = _meldung(eintrag)
            if kennung:
                meldungen.append(kennung)
        return any(_war_zuhoerer(transkript, ende, k) for k in meldungen[:HOECHSTENS_MELDUNGEN])
    except (OSError, ValueError):  # ValueError: mmap einer leeren Datei
        return False


def stop_hook_antwort(eingabe: dict, port: int, *, stand_holen=stand) -> dict | None:
    """Antwort des Stop-Hooks: {"decision": "block", "reason": …} oder None (Runde darf enden)."""
    if eingabe.get("stop_hook_active"):
        return None  # schon einmal angehalten: keine Schleife
    if not kevcad_runde(eingabe.get("transcript_path")):
        return None
    s = stand_holen(port)
    if not s or not s.get("app") or int(s.get("zuhoerer") or 0) > 0:
        return None
    grund = ("Kev CAD: Gerade hört niemand auf Kevins Sprach-Feedback. Starte vor dem Ende diesen Befehl als "
             f"Hintergrund-Shell mit der längsten Zeitgrenze (run_in_background, timeout {ZEITGRENZE_MS}): "
             f"{befehl(port)}")
    if s.get("offen"):
        grund += f" Es wartet schon Feedback ({s.get('name')}): zuerst feedback() aufrufen."
    grund += " Arbeitest du nur am Code von Kev CAD und nicht für Kevin im Viewer, beende die Runde einfach."
    return {"decision": "block", "reason": grund}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kevcad-feedback", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("KEVCAD_PORT") or DEFAULT_PORT))
    parser.add_argument("--warten-s", type=float, default=None, help="höchstens so lange warten (Vorgabe: unbegrenzt)")
    parser.add_argument("--zuhoerer", action="store_true", help="nur fragen, ob gerade jemand auf Kevin wartet")
    parser.add_argument("--stop-hook", action="store_true", help="Stop-Hook für Claude Code (Eingabe als JSON)")
    args = parser.parse_args(argv)
    if args.stop_hook:
        try:
            eingabe = json.load(sys.stdin)
        except (ValueError, OSError):
            return 0  # ohne lesbare Eingabe nie eine Runde festhalten
        antwort = stop_hook_antwort(eingabe if isinstance(eingabe, dict) else {}, args.port)
        if antwort:
            print(json.dumps(antwort, ensure_ascii=False))
        return 0
    if args.zuhoerer:
        s = stand(args.port)
        if not s or not s.get("app"):
            print("Kev CAD nicht erreichbar oder keine App verbunden.")
            return 3
        n = int(s.get("zuhoerer") or 0)
        print(f"{n} hört zu." if n else "Niemand hört zu.")
        return 0 if n else 1
    try:
        daten = warten(args.port, args.warten_s)
    except KeyboardInterrupt:
        return 130
    if daten is None:
        print(f"Kein Feedback nach {args.warten_s:g} s.")
        return 2
    print(f"Kevin ist fertig: {daten.get('name')}, {daten.get('saetze')} Sätze, {daten.get('striche')} Striche. "
          "feedback() holt es ab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

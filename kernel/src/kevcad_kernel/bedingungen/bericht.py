"""Texte zum Bericht der Bedingungen: Kurzfassung für ``run``, Ausgabe des MCP-Werkzeugs ``bedingungen``.

Ohne schwere Importe (nur Text), damit die MCP-Seite es laden kann.
"""

from __future__ import annotations

from typing import Any

from .text import mehrzahl, zahl

MAX_RUN_BEFUNDE = 12

STAND = {"erfuellt": "erfüllt", "verletzt": "verletzt", "ungeprueft": "nicht geprüft"}
TEIL_STAND = {"bestimmt": "bestimmt", "unterbestimmt": "unterbestimmt", "widerspruch": "Widerspruch",
              "bezug": "Bezugsteil"}


def kurzbericht(rep: dict[str, Any]) -> dict[str, Any]:
    """Was ``run`` vom Bericht mitliefert (die vollständige Fassung gibt ``bedingungen``)."""
    befunde = list(rep.get("befunde") or [])
    return {
        "summe": dict(rep.get("summe") or {}),
        "befunde": befunde[:MAX_RUN_BEFUNDE],
        "befunde_gesamt": len(befunde),
        "pruef_ms": rep.get("pruef_ms"),
        "loese_ms": rep.get("loese_ms"),
        "unterbestimmt": [{"name": t["name"], "frei": t.get("frei", 0)} for t in rep.get("teile") or []
                          if t.get("frei")],
        "bewegungen": [{k: b.get(k) for k in ("name", "art", "von", "bis", "frei", "teilweise")}
                       for b in rep.get("bewegungen") or []],
    }


def fehler_anzahl(rep: dict[str, Any] | None) -> int:
    if not rep:
        return 0
    s = rep.get("summe") or {}
    if "fehler" in s:
        return int(s.get("fehler") or 0)
    return sum(1 for b in rep.get("befunde") or [] if b.get("schwere") == "fehler")


def befund_zeile(b: dict[str, Any]) -> str:
    schwere = {"fehler": "Fehler", "warnung": "Warnung", "hinweis": "Hinweis"}.get(b.get("schwere"), b.get("schwere"))
    out = f"{schwere}: {b.get('text', '')}"
    if b.get("soll") and b.get("ist") and b.get("pruefung") not in ("befestigung",):
        out += f" (Soll {b['soll']}, Ist {b['ist']})"
    if b.get("zeile"):
        out += f" [Zeile {b['zeile']}]"
    if b.get("loesung"):
        out += f" → {b['loesung']}"
    return out


def summen_zeile(s: dict[str, Any], ms: Any = None) -> str:
    gesamt = int(s.get("gesamt") or 0)
    teile = [f"{mehrzahl(gesamt, 'Bedingung', 'Bedingungen')}" if gesamt else "keine Bedingungen"]
    if gesamt:
        teile.append(f"{s.get('erfuellt', 0)} erfüllt")
        if s.get("verletzt"):
            teile.append(f"{s['verletzt']} verletzt")
        if s.get("ungeprueft"):
            teile.append(f"{s['ungeprueft']} nicht geprüft")
    if s.get("bewegungen"):
        teile.append(f"{mehrzahl(int(s['bewegungen']), 'Bewegungsweg', 'Bewegungswege')} geprüft")
    text = ", ".join(teile)
    if ms is not None:
        text += f" ({zahl(ms, 0)} ms)"
    return text


def run_zeilen(kurz: dict[str, Any] | None, befunde: bool = True) -> tuple[list[str], bool]:
    """Zeilen für die Zusammenfassung von ``run`` und ob Fehler dabei sind (dann isError). ``befunde=False``: nur die
    Summe (die Befunde stehen dann im Ergebnis der gemeinsamen Prüfung)."""
    if not kurz:
        return [], False
    s = kurz.get("summe") or {}
    zeilen = ["Bedingungen: " + summen_zeile(s, kurz.get("pruef_ms"))
              + ("" if befunde or not s.get("fehler") else f", {s['fehler']} Fehler (siehe Prüfung)")]
    if not befunde:
        return zeilen, int(s.get("fehler") or 0) > 0
    befunde = kurz.get("befunde") or []
    for b in befunde:
        if b.get("schwere") in ("fehler", "warnung"):
            zeilen.append("- " + befund_zeile(b))
    hinweise = [b for b in befunde if b.get("schwere") == "hinweis"]
    if hinweise:
        zeilen.append(f"- {mehrzahl(len(hinweise), 'Hinweis', 'Hinweise')} (Freiheitsgrade, ungeprüft): mit "
                      "bedingungen ansehen")
    rest = int(kurz.get("befunde_gesamt") or 0) - len(befunde)
    if rest > 0:
        zeilen.append(f"- und {rest} weitere Befunde (bedingungen)")
    return zeilen, int(s.get("fehler") or 0) > 0


def bericht_text(rep: dict[str, Any], teil: str | None = None, alle: bool = False) -> str:
    """Ausgabe des MCP-Werkzeugs ``bedingungen``."""
    zeilen = [f"Lauf {rep.get('run', '?')}: " + summen_zeile(rep.get("summe") or {}, rep.get("pruef_ms"))
              + (f", Lösen {zahl(rep.get('loese_ms'), 1)} ms" if rep.get("loese_ms") else "")]
    items = list(rep.get("items") or [])
    if teil:
        items = [i for i in items if any(t == teil or t.startswith(teil.rstrip("/") + "/") for t in i.get("teile") or [])]
    zeige = items if (alle or teil) else [i for i in items if i.get("stand") != "erfuellt"]
    if zeige:
        zeilen.append("Bedingungen:" if (alle or teil) else "Nicht erfüllt:")
        for i in zeige:
            z = f"- {i.get('id')} {i.get('art')}: {i.get('text')} – {STAND.get(i.get('stand'), i.get('stand'))}"
            if i.get("soll") or i.get("ist"):
                z += f" (Soll {i.get('soll') or '–'}, Ist {i.get('ist') or '–'})"
            if i.get("zeile"):
                z += f" [Zeile {i['zeile']}]"
            if i.get("loesung"):
                z += f" → {i['loesung']}"
            if i.get("hinweis"):
                z += f" ({i['hinweis']})"
            zeilen.append(z)
    teile = list(rep.get("teile") or [])
    if teil:
        teile = [t for t in teile if t["name"] == teil or t["name"].startswith(teil.rstrip("/") + "/")]
    if teile:
        zeilen.append("Freiheitsgrade und Befestigung je Teil:")
        for t in teile:
            z = f"- {t['name']}: {TEIL_STAND.get(t.get('stand'), t.get('stand'))}"
            if t.get("frei"):
                frei = [f["text"] for f in t.get("freiheitsgrade") or [] if not f.get("gelenk") and
                        not f.get("unkritisch")]
                z += f", {mehrzahl(int(t['frei']), 'Freiheitsgrad', 'Freiheitsgrade')} frei ({'; '.join(frei)})"
            if t.get("gelenke"):
                z += f", Gelenk: {'; '.join(t['gelenke'])}"
            if "befestigt" in t:
                z += ", befestigt" if t.get("befestigt") else ", NICHT befestigt"
                if t.get("befestigt") and not t.get("am_boden"):
                    z += " (hängt nicht am Boden)"
                if t.get("verbindungen"):
                    z += f" ({', '.join(t['verbindungen'])})"
            zeilen.append(z)
    for b in rep.get("bewegungen") or []:
        e = "°" if b.get("art") == "drehen" else " mm"
        frei = ", ".join(f"{zahl(a, 1)}…{zahl(c, 1)}{e}" for a, c in b.get("frei") or []) or "nirgends"
        z = f"Bewegungsraum {b.get('name')}: {zahl(b.get('von'), 1)}…{zahl(b.get('bis'), 1)}{e}, frei {frei}"
        if b.get("kollisionen"):
            z += "; stößt an " + ", ".join(k["gegen"] for k in b["kollisionen"])
        if b.get("teilweise"):
            z += " (nur teilweise geprüft)"
        zeilen.append(z)
    befunde = [b for b in rep.get("befunde") or [] if not teil or any(
        t == teil or t.startswith(teil.rstrip("/") + "/") for t in b.get("teile") or [])]
    if befunde:
        zeilen.append("Befunde:")
        for b in befunde[:40]:
            zeilen.append("- " + befund_zeile(b))
        if len(befunde) > 40:
            zeilen.append(f"- und {len(befunde) - 40} weitere")
    elif not zeige:
        zeilen.append("Keine Befunde: alle Bedingungen erfüllt.")
    return "\n".join(zeilen)

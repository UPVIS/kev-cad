"""Texte der Prüfung für die MCP-Werkzeuge (deutsch, Kevin liest mit) und die Export-Sperre."""

from __future__ import annotations

from typing import Any

from kevcad_kernel.pruefung.befund import zusammenfassung

SCHWERE_TEXT = {"fehler": "Fehler", "warnung": "Warnung", "hinweis": "Hinweis"}


def export_sperre(offen: list[dict[str, Any]], laeuft: bool = False) -> str | None:
    """Meldung, wenn offene Befunde (schwere "fehler") den Export sperren; sonst None."""
    if not offen:
        return None
    text = "Export verweigert. Prüfung: " + (zusammenfassung(offen) or f"{len(offen)} offene Befunde")
    namen = []
    for b in offen[:4]:
        namen.append(" ↔ ".join(b.get("teile") or [])[:120])
    text += " (" + "; ".join(namen) + (" …" if len(offen) > 4 else "") + ")."
    text += " Erst die Befunde beheben (siehe run oder pruefen), dann exportieren."
    if laeuft:
        text += " Eine neuere Prüfung läuft noch."
    return text


def befund_zeile(b: dict[str, Any], mit_loesung: bool = True) -> str:
    zeile = f"- [{SCHWERE_TEXT.get(b.get('schwere'), b.get('schwere'))}] {b.get('text', '')}"
    if mit_loesung and b.get("loesung"):
        zeile += f"\n  Lösung: {b['loesung']}"
    return zeile


def pruef_text(check: dict[str, Any] | None, max_befunde: int = 25, hinweise: bool = True) -> tuple[str, bool]:
    """Abschnitt „Prüfung“ für run und pruefen: (Text, offen?). offen = Befunde mit schwere "fehler"."""
    if not check:
        return "", False
    state = check.get("state")
    if state == "running":
        return ("Prüfung: läuft noch (" + (check.get("message") or "") + "); Ergebnis mit pruefen abrufen."), False
    if state == "cancelled":
        return "Prüfung: abgebrochen, weil ein neuerer Lauf kam.", False
    if state == "failed":
        return f"Prüfung fehlgeschlagen: {check.get('message') or 'ohne Meldung'}", False
    befunde = list(check.get("befunde") or [])
    fehler = [b for b in befunde if b.get("schwere") == "fehler"]
    zeigen = [b for b in befunde if hinweise or b.get("schwere") != "hinweis"]
    zusammen = check.get("zusammenfassung") or zusammenfassung(befunde)
    if not fehler and not [b for b in befunde if b.get("schwere") == "warnung"]:
        kopf = "Prüfung: in Ordnung, keine Befunde"
        n_gew = len(check.get("gewinde") or [])
        n_erl = len(check.get("erlaubt") or [])
        extra = []
        if n_gew:
            extra.append(f"{n_gew} Gewindeeingriff{'e' if n_gew != 1 else ''}")
        if n_erl:
            extra.append(f"{n_erl} erlaubte Überlappung{'en' if n_erl != 1 else ''}")
        if extra:
            kopf += " (" + ", ".join(extra) + " zählen nicht)"
        zeilen = [kopf + "."]
    else:
        zeilen = [f"Prüfung: {zusammen}" + (" – Fehler, Export gesperrt. Jeden Befund beheben (Lösung je Befund):"
                                             if fehler else ".")]
    for b in zeigen[:max_befunde]:
        if b.get("schwere") == "hinweis" and not hinweise:
            continue
        zeilen.append(befund_zeile(b))
    if len(zeigen) > max_befunde:
        zeilen.append(f"… und {len(zeigen) - max_befunde} weitere (pruefen zeigt alle).")
    if check.get("druck"):  # Druckprüfung: Summen und Ausrichtung (druck/bericht.py)
        from kevcad_kernel.druck.bericht import druck_zeilen

        zeilen += druck_zeilen(check["druck"])
    if fehler:
        zeilen.append("Gewollte Überlappungen (Presspassung, Schaum) nur nach Rückfrage bei Kevin mit "
                      "erlaubt_ueberlappung(a, b, grund=\"…\") in model.py erklären; Gewindeeingriff erkennt die "
                      "Prüfung selbst.")
    return "\n".join(zeilen), bool(fehler)

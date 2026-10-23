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
    if state == "teilweise":  # Bewegungsraum rechnet im Hintergrund: ausblenden, was nur „noch offen“ sagt
        befunde = [b for b in befunde if not _nur_offen(b)]
    fehler = [b for b in befunde if b.get("schwere") == "fehler"]
    zeigen = [b for b in befunde if hinweise or b.get("schwere") != "hinweis"]
    zusammen = check.get("zusammenfassung") or zusammenfassung(befunde)
    if not fehler and not [b for b in befunde if b.get("schwere") == "warnung"]:
        kopf = "Prüfung: bisher keine Befunde" if state == "teilweise" else "Prüfung: in Ordnung, keine Befunde"
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
    if state == "teilweise":
        zeilen.insert(1, hintergrund_text(check))
    if check.get("druck"):  # Druckprüfung: Summen und Ausrichtung (druck/bericht.py)
        from kevcad_kernel.druck.bericht import druck_zeilen

        zeilen += druck_zeilen(check["druck"])
    arten = {b.get("art") for b in fehler}
    if "durchdringung" in arten:
        zeilen.append("Gewollte Überlappungen (Presspassung, Schaum) nur nach Rückfrage bei Kevin mit "
                      "erlaubt_ueberlappung(a, b, grund=\"…\") in model.py erklären; Gewindeeingriff erkennt die "
                      "Prüfung selbst.")
    if arten & {"nicht_einbaubar", "nur_baugruppe", "eingesperrt", "einfuehren", "werkzeug"}:
        zeilen.append("Einbaubarkeit: Teile so konstruieren, dass sie sich nacheinander einsetzen lassen. Erklärungen "
                      "nur, wo sie stimmen: Zukaufteil montage(\"Gruppe\", baugruppe=True), Clip montage(teil, "
                      "schnappt=True), beim Druck eingelegte Mutter montage(teil, eingedruckt=True); "
                      "montage_reihenfolge zeigt die Reihenfolge.")
    return "\n".join(zeilen), bool(fehler)


def _nur_offen(b: dict[str, Any]) -> bool:
    """Hinweis des Bewegungsraums, dass ein Weg noch im Hintergrund gerechnet wird (steht im Text darüber)."""
    return b.get("art") == "bewegungsraum" and b.get("schwere") == "hinweis" and "im Hintergrund" in str(
        b.get("text") or "")


def hintergrund_text(check: dict[str, Any]) -> str:
    """„Bewegungsraum: 2 Gelenke noch nicht geprüft (Zeitlimit), wird im Hintergrund fertig gerechnet; …“ und/oder
    „Statik: Festkörper „Bremsen“ rechnet im Hintergrund, seine Befunde kommen nach; …“ (T34)."""
    offen = list(check.get("im_hintergrund") or [])
    statik = list(check.get("statik_im_hintergrund") or [])
    zeilen = []
    if offen:
        n = len(offen)
        namen = ", ".join(o.split(" ", 1)[-1].rsplit("/", 1)[-1] for o in offen[:4]) + (" …" if len(offen) > 4 else "")
        zeilen.append(f"Bewegungsraum: {n} {'Gelenk' if n == 1 else 'Gelenke'} noch nicht geprüft (Zeitlimit), wird "
                      f"im Hintergrund fertig gerechnet; bedingungen() bzw. pruefen() zeigt den Endstand"
                      + (f" ({namen})" if namen else "") + ". Erst danach fertig melden.")
    elif not statik or check.get("message"):  # Fertigrechnen gescheitert: es kommt nichts mehr nach
        zeilen.append(f"Bewegungsraum nicht vollständig geprüft: "
                      f"{check.get('message') or 'Fertigrechnen abgebrochen'}.")
    if statik:
        zeilen.append(f"Statik: {', '.join(statik[:4])}{' …' if len(statik) > 4 else ''} "
                      f"{'rechnet' if len(statik) == 1 else 'rechnen'} im Hintergrund, die Befunde (Warnungen und "
                      "Hinweise, kein Exportverbot) kommen nach; pruefen() wartet darauf.")
    return "\n".join(zeilen)


def montage_text(check: dict[str, Any] | None, max_schritte: int = 200) -> str:
    """Montagereihenfolge als Liste: „3. Deckel – von oben (Innensechskant 6)“."""
    m = (check or {}).get("montage")
    if not isinstance(m, dict):
        return "Keine Montagereihenfolge: die Prüfung lief ohne Montage (oder es gab noch keinen Lauf)."
    schritte = list(m.get("schritte") or [])
    zeilen = [f"Montagereihenfolge, {len(schritte)} Schritte" + (" (vollständig):" if m.get("vollstaendig") else ":")]
    for s in schritte[:max_schritte]:
        teile = s.get("teile") or []
        extra = ""
        if s.get("gruppe") and len(teile) > 1:
            namen = ", ".join(t.rsplit("/", 1)[-1] for t in teile[:4]) + (" …" if len(teile) > 4 else "")
            extra = f" [{len(teile)} Teile: {namen}]"
        wz = f" ({s['werkzeug']})" if s.get("werkzeug") else ""
        zeilen.append(f"{s.get('nr')}. {s.get('name')} – {s.get('richtung_text')}{wz}{extra}")
    if len(schritte) > max_schritte:
        zeilen.append(f"… und {len(schritte) - max_schritte} weitere")
    if m.get("offen"):
        zeilen.append("Nicht einbaubar: " + ", ".join(m["offen"][:12]) + (" …" if len(m["offen"]) > 12 else ""))
    if m.get("abgebrochen"):
        zeilen.append(f"Abgebrochen: {m['abgebrochen']}")
    return "\n".join(zeilen)


def stand_text(check: dict[str, Any] | None) -> str:
    """Kurz: Gruppen auf dem Boden mit Masse und Kippwinkel."""
    from kevcad_kernel.bom import de_num

    st = (check or {}).get("stand")
    if not isinstance(st, dict):
        return ""
    zeilen = []
    for g in st.get("gruppen") or []:
        teile = g.get("teile") or []
        name = teile[0] if len(teile) == 1 else f"{teile[0].split('/')[0]} und weitere ({len(teile)} Teile)"
        if g.get("befestigt"):
            zustand = "befestigt"
        elif g.get("schwebt"):
            zustand = "schwebt"
        elif g.get("kippwinkel") is not None:
            zustand = f"Kippwinkel {de_num(g['kippwinkel'], 1)}°"
        else:
            zustand = ""
        zeilen.append(f"- {name}: {de_num(g.get('masse_kg') or 0, 2)} kg, {zustand}")
    if not zeilen:
        return ""
    rest = f"\n… und {len(zeilen) - 12} weitere Gruppen" if len(zeilen) > 12 else ""
    return f"Stand (Boden z = {de_num(st.get('boden_z') or 0, 1)}):\n" + "\n".join(zeilen[:12]) + rest

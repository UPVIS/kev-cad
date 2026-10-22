"""Befunde der Prüfung: ein allgemeines Format, das auch andere Prüfungen (etwa die Druckprüfung) benutzen können.

Ein Befund ist ein JSON-taugliches Wörterbuch:

| Feld | Bedeutung |
|---|---|
| ``id`` | eindeutig im Ergebnis, z. B. ``d1`` (Durchdringung 1) |
| ``art`` | ``durchdringung``, ``verformt``, ``schwebt``, ``kippt``, ``standsicherheit``, ``nicht_einbaubar``, ``eingesperrt``, ``einfuehren``, ``werkzeug``, ``nur_baugruppe``, ``annahme``, ``erklaerung`` (andere Prüfungen dürfen eigene Arten ergänzen) |
| ``teile`` | betroffene Teile (Namen aus show), das erste ist das Hauptteil |
| ``schwere`` | ``fehler`` (Lauf gilt als fehlerhaft, Export gesperrt), ``warnung``, ``hinweis`` |
| ``wert`` | Zahlen zum Befund, z. B. ``{"volumen": 12.3, "tiefe": 1.2}`` (mm³, mm) |
| ``ort`` | Punkt [x, y, z] in mm oder null |
| ``text`` | kurze Beschreibung auf Deutsch |
| ``loesung`` | konkreter Vorschlag, wie es sich beheben lässt |
| ``geometrie`` | Index in der Liste der Schnittkörper oder null |
"""

from __future__ import annotations

from typing import Any

from kevcad_kernel.bom import de_num

# Toleranzen (mm)
BERUEHR_TOL = 0.5  # Abstand bis hierhin gilt als Verbindung (Auflage, Führung mit Spiel)
BERUEHRT_TOL = 0.05  # bis hierhin „berührt“, darüber bis BERUEHR_TOL „Spielpassung“
BODEN_TOL = 0.5  # so nah am Boden gilt als aufliegend
TIEFE_MIN = 0.01  # Durchdringungen ab dieser Tiefe …
VOLUMEN_MIN = 0.001  # … und diesem Volumen (mm³) zählen; Berühren ist kein Befund
SPIEL_VORSCHLAG = 0.2  # Spiel, das Lösungsvorschläge dazugeben
NACHGIEBIG_ANTEIL = 0.5  # nachgiebige Teile dürfen bis zu diesem Anteil ihrer Dicke zusammengedrückt werden
KIPP_WARNUNG_GRAD = 3.0  # Kippwinkel darunter: Standsicherheit knapp
DICHTE_ANNAHME = 1.0  # g/cm³ für Teile ohne Material

SCHWEREN = ("fehler", "warnung", "hinweis")

# Bezeichnungen für die Zusammenfassung: art → (Einzahl, Mehrzahl)
ART_TEXT: dict[str, tuple[str, str]] = {
    "durchdringung": ("Durchdringung", "Durchdringungen"),
    "verformt": ("nachgiebiges Teil verformt", "nachgiebige Teile verformt"),
    "schwebt": ("Teil schwebt", "Teile schweben"),
    "kippt": ("Gruppe kippt", "Gruppen kippen"),
    "standsicherheit": ("Standsicherheit knapp", "Standsicherheit knapp"),
    "nicht_einbaubar": ("Teil nicht einbaubar", "Teile nicht einbaubar"),
    "eingesperrt": ("Teil eingesperrt", "Teile eingesperrt"),
    "einfuehren": ("Schraube nicht einführbar", "Schrauben nicht einführbar"),
    "werkzeug": ("Werkzeug kommt nicht hin", "Werkzeug kommt nicht hin"),
    "nur_baugruppe": ("nur als Baugruppe einbaubar", "nur als Baugruppen einbaubar"),
    "annahme": ("Annahme", "Annahmen"),
    "erklaerung": ("Erklärung ungültig", "Erklärungen ungültig"),
    "gedruckt_geaendert": ("gedrucktes Teil geändert", "gedruckte Teile geändert"),  # druck/gedruckt.py
}
# Reihenfolge in der Zusammenfassung
ART_ORDNUNG = ("durchdringung", "schwebt", "kippt", "nicht_einbaubar", "eingesperrt", "einfuehren", "werkzeug",
               "nur_baugruppe", "standsicherheit", "verformt", "erklaerung", "annahme")
# Arten, bei denen „Teile“ gezählt werden statt Befunde
TEILE_ZAEHLEN = ("schwebt", "nicht_einbaubar", "eingesperrt", "nur_baugruppe")


def befund(art: str, teile: list[str], schwere: str, text: str, loesung: str = "", *, wert: dict | None = None,
           ort: Any = None, geometrie: int | None = None) -> dict[str, Any]:
    if schwere not in SCHWEREN:
        raise ValueError(f"schwere {schwere!r} unbekannt")
    return {
        "id": "",
        "art": art,
        "teile": list(teile),
        "schwere": schwere,
        "wert": dict(wert or {}),
        "ort": [round(float(c), 3) for c in ort] if ort is not None else None,
        "text": text,
        "loesung": loesung,
        "geometrie": geometrie,
    }


def nummerieren(befunde: list[dict[str, Any]]) -> None:
    """``id`` je Befund: Anfangsbuchstabe der Art und laufende Nummer (d1, d2, s1 …), stabil sortiert."""
    zaehler: dict[str, int] = {}
    for b in befunde:
        k = b["art"][:2]
        zaehler[k] = zaehler.get(k, 0) + 1
        b["id"] = f"{k}{zaehler[k]}"


def sortieren(befunde: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rang = {s: i for i, s in enumerate(SCHWEREN)}
    art = {a: i for i, a in enumerate(ART_ORDNUNG)}
    return sorted(befunde, key=lambda b: (rang.get(b["schwere"], 9), art.get(b["art"], 99), b["teile"]))


def zaehler(befunde: list[dict[str, Any]]) -> dict[str, int]:
    out = {s: 0 for s in SCHWEREN}
    for b in befunde:
        out[b["schwere"]] = out.get(b["schwere"], 0) + 1
    return out


def zusammenfassung(befunde: list[dict[str, Any]], schweren: tuple[str, ...] = ("fehler", "warnung")) -> str:
    """„2 Durchdringungen · 1 Teil nicht einbaubar“ (nur Fehler und Warnungen); leer, wenn nichts offen ist."""
    teile: dict[str, set[str]] = {}
    anzahl: dict[str, int] = {}
    for b in befunde:
        if b["schwere"] not in schweren:
            continue
        anzahl[b["art"]] = anzahl.get(b["art"], 0) + 1
        teile.setdefault(b["art"], set()).update(b["teile"][:1] if b["art"] != "schwebt" else b["teile"])
    stuecke = []
    for art in list(ART_ORDNUNG) + sorted(set(anzahl) - set(ART_ORDNUNG)):
        if art not in anzahl:
            continue
        n = len(teile[art]) if art in TEILE_ZAEHLEN else anzahl[art]
        one, many = ART_TEXT.get(art, (art, art))
        stuecke.append(f"{n} {one if n == 1 else many}")
    return " · ".join(stuecke)


def offen(befunde: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Befunde, die den Lauf zum Fehler machen und den Export sperren."""
    return [b for b in befunde if b.get("schwere") == "fehler"]


# ---------------------------------------------------------------------------------------------------------------------
# Texte


def mm(x: float, digits: int = 1) -> str:
    return f"{de_num(x, digits)} mm"


def punkt(p: Any) -> str:
    return "(" + "; ".join(de_num(float(c), 1) for c in p) + ")"


ACHSEN = ((0, "X"), (1, "Y"), (2, "Z"))


def richtung_text(d: Any) -> str:
    """Bewegungsrichtung als Text: (0, 0, -1) → „−Z“, schräg → „(0,71; 0; −0,71)“."""
    v = [float(c) for c in d]
    for i, name in ACHSEN:
        if abs(abs(v[i]) - 1) < 1e-6:
            return ("+" if v[i] > 0 else "−") + name
    return "(" + "; ".join(de_num(c, 2) for c in v) + ")"


def einfuehr_text(d: Any) -> str:
    """Einführrichtung (Bewegung beim Einbau) als Text: (0, 0, -1) → „von oben“."""
    v = [float(c) for c in d]
    if abs(v[2] + 1) < 1e-6:
        return "von oben"
    if abs(v[2] - 1) < 1e-6:
        return "von unten"
    for i, name in ACHSEN[:2]:
        if abs(abs(v[i]) - 1) < 1e-6:
            return f"von {'−' if v[i] > 0 else '+'}{name} her"
    return "entlang " + richtung_text(v)

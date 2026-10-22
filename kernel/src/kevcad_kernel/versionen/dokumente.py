"""Änderungen an den Dokumenten (Blätter und Bauplan, DOKUMENTE.md) für Vergleich und Titel der Versionen.

Blätter (``dokumente/zeichnungen/<id>.json``) und Bauplan (``dokumente/bauplan.json``) gehören zu den Projektdateien und
damit zu den Versionen. Für Kevin sind sie kein Code: Der Vergleich nennt sie als eigene Gruppe, der Titel einer
Version, die nur sie ändert, sagt, was sich am Dokument geändert hat (titel.py), zum Beispiel
„Zeichnung Seitenstange: 2 Maße geändert“ oder „Bauplan: Schritt 7 umformuliert“.

Eingabe sind die Dateiänderungen aus ``Versionsarchiv.aenderungen`` (je Datei ``pfad``, ``status`` A/M/D, ``alt`` und
``neu`` als Text oder None, ``binaer``). Ausgabe je Datei mit inhaltlicher Änderung::

    {"pfad", "art": "zeichnung" | "bauplan" | "datei", "name", "status": "A" | "M" | "D", "punkte": [str], "text": str}

Nur umformatierte Dateien (gleicher JSON-Inhalt) fallen weg.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

PRAEFIX = "dokumente/"
ZEICHNUNGEN = "dokumente/zeichnungen/"
BAUPLAN = "dokumente/bauplan.json"
DATEI_NAMEN = {"dokumente/hausregeln.json": "Hausregeln", "dokumente/vorlagen.json": "Export-Vorlagen"}
SCHRIFTFELD_NAMEN = {"benennung": "Benennung", "zeichnungsnummer": "Sachnummer", "werkstoff": "Werkstoff",
                     "halbzeug": "Halbzeug", "masse_g": "Masse", "allgemeintoleranz": "Allgemeintoleranz",
                     "projekt": "Projekt", "version": "Version", "datum": "Datum", "gezeichnet": "Erstellt",
                     "notiz": "Notiz", "dokumentart": "Dokumentart", "blatt_nr": "Blattnummer",
                     "blatt_anzahl": "Blattanzahl", "eigentuemer": "Eigentümer", "freigegeben": "Freigegeben",
                     "stueckzahl": "Stückzahl"}
MAX_NUMMERN = 3  # mehr Schrittnummern: nur die Anzahl


def ist_dokument(pfad: str) -> bool:
    return str(pfad or "").startswith(PRAEFIX)


def _json(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _anzahl(n: int, eins: str, mehr: str) -> str:
    return eins if n == 1 else f"{n} {mehr}"


def _nach_id(liste: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for x in liste or []:
        if isinstance(x, dict) and x.get("id") is not None:
            out.setdefault(str(x["id"]), x)
    return out


def _ohne(d: dict[str, Any], *schluessel: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in schluessel}


# =====================================================================================================================
# Blätter
# =====================================================================================================================


def _masse_punkte(alt: Any, neu: Any) -> list[str]:
    a, b = _nach_id(alt), _nach_id(neu)
    hinzu = [k for k in b if k not in a]
    weg = [k for k in a if k not in b]
    verwaist = wieder = geaendert = 0
    for k in (k for k in b if k in a):
        ma, mb = a[k], b[k]
        if bool(mb.get("verwaist")) and not ma.get("verwaist"):
            verwaist += 1
        elif bool(ma.get("verwaist")) and not mb.get("verwaist"):
            wieder += 1
        elif _ohne(ma, "verwaist") != _ohne(mb, "verwaist"):
            geaendert += 1
    out = []
    if hinzu:
        out.append(_anzahl(len(hinzu), "Maß neu", "Maße neu"))
    if geaendert:
        out.append(_anzahl(geaendert, "Maß geändert", "Maße geändert"))
    if verwaist:
        out.append(_anzahl(verwaist, "Maß verwaist", "Maße verwaist"))
    if wieder:
        out.append(_anzahl(wieder, "Maß wieder zugeordnet", "Maße wieder zugeordnet"))
    if weg:
        out.append(_anzahl(len(weg), "Maß gelöscht", "Maße gelöscht"))
    return out


def _ansichten_punkte(alt: Any, neu: Any) -> list[str]:
    a, b = _nach_id(alt), _nach_id(neu)
    hinzu = [k for k in b if k not in a]
    weg = [k for k in a if k not in b]
    verschoben = geaendert = 0
    for k in (k for k in b if k in a):
        if a[k] == b[k]:
            continue
        if _ohne(a[k], "lage") == _ohne(b[k], "lage"):
            verschoben += 1
        else:
            geaendert += 1
    out = []
    if hinzu:
        out.append(_anzahl(len(hinzu), "Ansicht neu", "Ansichten neu"))
    if verschoben:
        out.append(_anzahl(verschoben, "Ansicht verschoben", "Ansichten verschoben"))
    if geaendert:
        out.append(_anzahl(geaendert, "Ansicht geändert", "Ansichten geändert"))
    if weg:
        out.append(_anzahl(len(weg), "Ansicht gelöscht", "Ansichten gelöscht"))
    return out


def _notizen_punkte(alt: Any, neu: Any) -> list[str]:
    a, b = _nach_id(alt), _nach_id(neu)
    hinzu = [k for k in b if k not in a]
    weg = [k for k in a if k not in b]
    geaendert = sum(1 for k in b if k in a and a[k] != b[k])
    out = []
    if hinzu:
        out.append(_anzahl(len(hinzu), "Notiz neu", "Notizen neu"))
    if geaendert:
        out.append(_anzahl(geaendert, "Notiz geändert", "Notizen geändert"))
    if weg:
        out.append(_anzahl(len(weg), "Notiz gelöscht", "Notizen gelöscht"))
    return out


def blatt_punkte(alt: dict[str, Any], neu: dict[str, Any]) -> list[str]:
    """Was sich an einem Blatt geändert hat, wichtigstes zuerst (leer = inhaltlich gleich)."""
    if alt == neu:
        return []
    out: list[str] = []
    out += _masse_punkte(alt.get("masse"), neu.get("masse"))
    if (alt.get("format"), alt.get("ausrichtung")) != (neu.get("format"), neu.get("ausrichtung")):
        out.append(f"{alt.get('format')} {alt.get('ausrichtung')} → {neu.get('format')} {neu.get('ausrichtung')}")
    if alt.get("massstab") != neu.get("massstab"):
        out.append(f"Maßstab {alt.get('massstab')} → {neu.get('massstab')}")
    out += _ansichten_punkte(alt.get("ansichten"), neu.get("ansichten"))
    out += _notizen_punkte(alt.get("notizen"), neu.get("notizen"))
    if alt.get("titel") != neu.get("titel") and alt.get("titel"):
        out.append(f"umbenannt (vorher „{alt.get('titel')}“)")
    sa, sb = alt.get("schriftfeld") or {}, neu.get("schriftfeld") or {}
    felder = [k for k in dict.fromkeys(list(sb) + list(sa)) if sa.get(k) != sb.get(k)]
    if felder:
        namen = [SCHRIFTFELD_NAMEN.get(k, k) for k in felder]
        out.append("Schriftfeld: " + ", ".join(namen) if len(namen) <= 2 else "Schriftfeld geändert")
    if alt.get("inhalt") != neu.get("inhalt"):
        out.append("Inhalt geändert")
    if alt.get("unterdrueckt") != neu.get("unterdrueckt"):
        out.append("unterdrückte Maße geändert")
    if alt.get("tabellen") != neu.get("tabellen"):
        out.append("Tabellen geändert")
    if alt.get("allgemein") != neu.get("allgemein"):
        out.append("Allgemeinangaben geändert")
    bekannt = {"masse", "format", "ausrichtung", "massstab", "ansichten", "notizen", "titel", "schriftfeld", "inhalt",
               "unterdrueckt", "tabellen", "allgemein"}
    if not out and any(alt.get(k) != neu.get(k) for k in set(alt) | set(neu) if k not in bekannt):
        out.append("Einstellungen geändert")
    return out or ["geändert"]


# =====================================================================================================================
# Bauplan
# =====================================================================================================================


def _schritte(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in plan.get("abschnitte") or []:
        if isinstance(a, dict):
            out += [s for s in a.get("schritte") or [] if isinstance(s, dict)]
    return out


def _nummern(nrs: list[int], eins: str, mehr: str, anzahl: str) -> str:
    """„Schritt 7 umformuliert“, „Schritte 2, 7 umformuliert“, „5 Schritte umformuliert“ (``{}`` = Nummern)."""
    if len(nrs) == 1:
        return eins.format(nrs[0])
    if len(nrs) <= MAX_NUMMERN:
        return mehr.format(", ".join(str(n) for n in nrs))
    return anzahl.format(len(nrs))


def bauplan_punkte(alt: dict[str, Any], neu: dict[str, Any]) -> list[str]:
    """Was sich am Bauplan geändert hat (Schritte nach ihrer Nummer im neuen Plan, entfernte nach Titel)."""
    if alt == neu:
        return []
    sa, sb = _schritte(alt), _schritte(neu)
    a = {str(s.get("id")): s for s in sa}
    nr = {str(s.get("id")): i for i, s in enumerate(sb, 1)}
    hinzu = [nr[str(s.get("id"))] for s in sb if str(s.get("id")) not in a]
    weg = [s for s in sa if str(s.get("id")) not in nr]
    text, fest, geloest, bild, befunde, sonst = [], [], [], [], [], []
    for s in sb:
        sid = str(s.get("id"))
        if sid not in a or a[sid] == s:
            continue
        alt_s, n = a[sid], nr[sid]
        if any(alt_s.get(k) != s.get(k) for k in ("titel", "text", "hinweise")):
            text.append(n)
        if bool(alt_s.get("fest")) != bool(s.get("fest")):
            (fest if s.get("fest") else geloest).append(n)
        if alt_s.get("bild") != s.get("bild"):
            bild.append(n)
        if alt_s.get("pruefung") != s.get("pruefung"):
            befunde.append(n)
        rest = ("titel", "text", "hinweise", "fest", "bild", "pruefung", "quelle")
        if _ohne(alt_s, *rest) != _ohne(s, *rest):
            sonst.append(n)
    out = []
    if hinzu:
        out.append(_nummern(hinzu, "Schritt {} neu", "Schritte {} neu", "{} Schritte neu"))
    if weg:
        out.append(f"Schritt „{weg[0].get('titel') or weg[0].get('id')}“ entfernt" if len(weg) == 1
                   else f"{len(weg)} Schritte entfernt")
    if text:
        out.append(_nummern(text, "Schritt {} umformuliert", "Schritte {} umformuliert", "{} Schritte umformuliert"))
    if fest:
        out.append(_nummern(fest, "Schritt {} festgehalten", "Schritte {} festgehalten", "{} Schritte festgehalten"))
    if geloest:
        out.append(_nummern(geloest, "Schritt {} freigegeben", "Schritte {} freigegeben", "{} Schritte freigegeben"))
    if sonst:
        out.append(_nummern(sonst, "Schritt {} geändert", "Schritte {} geändert", "{} Schritte geändert"))
    gemeinsam_alt = [str(s.get("id")) for s in sa if str(s.get("id")) in nr]
    gemeinsam_neu = [str(s.get("id")) for s in sb if str(s.get("id")) in a]
    if gemeinsam_alt != gemeinsam_neu:
        out.append("Schritte umgestellt")
    if (alt.get("vorher") or []) != (neu.get("vorher") or []):
        out.append("Reihenfolge-Regeln geändert")
    if bild:
        out.append(_nummern(bild, "Bild zu Schritt {} angepasst", "Bilder zu Schritt {} angepasst",
                            "{} Bilder angepasst"))
    if befunde:
        out.append(_nummern(befunde, "Befunde zu Schritt {} geändert", "Befunde zu Schritt {} geändert",
                            "Befunde zu {} Schritten geändert"))
    if alt.get("titel") != neu.get("titel"):
        out.append("Titel geändert")
    if alt.get("umfang") != neu.get("umfang"):
        out.append("Umfang geändert")
    return out or ["geändert"]


# =====================================================================================================================
# Alle Dokumente
# =====================================================================================================================


def _eintrag(a: dict[str, Any]) -> dict[str, Any] | None:
    pfad = str(a.get("pfad") or "")
    status = str(a.get("status") or "M")
    alt, neu = _json(a.get("alt")), _json(a.get("neu"))
    lesbar = not a.get("binaer") and (status == "A" or isinstance(alt, dict)) and (status == "D"
                                                                                   or isinstance(neu, dict))
    if pfad.startswith(ZEICHNUNGEN):
        art = "zeichnung"
        name = str(((neu if isinstance(neu, dict) else None) or (alt if isinstance(alt, dict) else None)
                    or {}).get("titel") or PurePosixPath(pfad).stem)
        kopf = f"Zeichnung {name}"
    elif pfad == BAUPLAN:
        art, name, kopf = "bauplan", "Bauplan", "Bauplan"
    else:
        art = "datei"
        name = DATEI_NAMEN.get(pfad, PurePosixPath(pfad).name)
        kopf = name
    e: dict[str, Any] = {"pfad": pfad, "art": art, "name": name, "status": status, "punkte": []}
    if status == "A":
        e["text"] = f"{kopf} neu"
    elif status == "D":
        e["text"] = f"{kopf} entfernt"
    elif not lesbar:
        e["text"] = f"{kopf} geändert"
    else:
        if alt == neu:
            return None  # nur umformatiert
        if art == "zeichnung":
            e["punkte"] = blatt_punkte(alt, neu)
        elif art == "bauplan":
            e["punkte"] = bauplan_punkte(alt, neu)
        else:
            e["punkte"] = ["geändert"]
        e["text"] = f"{kopf} geändert" if e["punkte"] == ["geändert"] else f"{kopf}: {', '.join(e['punkte'])}"
    return e


ART_FOLGE = {"zeichnung": 0, "bauplan": 1, "datei": 2}


def vergleiche_dokumente(aenderungen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inhaltliche Änderungen je Dokument (siehe Modulbeschreibung), Blätter vor Bauplan vor sonstigen Dateien."""
    out = [e for e in (_eintrag(a) for a in aenderungen if ist_dokument(a.get("pfad"))) if e is not None]
    out.sort(key=lambda e: (ART_FOLGE.get(e["art"], 9), e["pfad"]))
    return out


def zusammenfassung(eintraege: list[dict[str, Any]], max_eintraege: int = 3) -> str:
    """Eine Zeile für die Zusammenfassung des Vergleichs."""
    texte = [e["text"] for e in eintraege[:max_eintraege]]
    rest = len(eintraege) - len(texte)
    return " · ".join(texte) + (f" · {rest} weitere Dokumente" if rest > 1 else
                                f" · {eintraege[-1]['text']}" if rest == 1 else "")


__all__ = ["BAUPLAN", "ZEICHNUNGEN", "bauplan_punkte", "blatt_punkte", "ist_dokument", "vergleiche_dokumente",
           "zusammenfassung"]

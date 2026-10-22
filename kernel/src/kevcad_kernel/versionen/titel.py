"""Automatische Titel der Versionen (PLAN-VERSIONEN.md, Abschnitt „Titel“).

Der Titel einer Version sagt in höchstens etwa 60 Zeichen, was sich gegenüber ihrer Vorgängerversion geändert hat.
Er entsteht aus dem Vergleich der beiden Stände (``daten`` aus schnappschuss.py, vergleich.py) und dem Unterschied der
Dateien. Regeln mit Vorrang von oben nach unten; Höherrangiges bekommt den Platz zuerst, was nicht mehr in die Zeile
passt, entfällt:

1. **Geänderte Parameter:** ``breite 120 → 140``, neue ``hub = 30 neu``, entfernte ``hub entfernt`` (viele davon
   als ``27 Parameter entfernt``).
2. **Neue und entfernte Teile:** ``+ Flügelschraube M4 (4×)``, ``− Klotz``. Ist eine ganze Baugruppe neu oder weg,
   steht sie für ihre Teile (``+ Lenkrolle 1–4``).
3. **Geänderte Teile:** ``Rahmen, Schlitten geändert``, nur verschobene ``… verschoben``, nur umgefärbte
   ``… umgefärbt``. Entfällt neben geänderten Parametern (die Teile ändern sich dann als deren Folge). Ohne Änderung
   an Teilen die Zeilen der Stückliste: ``Stückliste + Rillenkugellager 61801-2RS (4×)``.
4. **Neue step()-Abschnitte:** ``neuer Schritt „Bohrungen“``, danach entfernte.
5. **Ohne Wirkung auf Parameter, Teile und Stückliste:** nur Kommentare, Docstrings oder Formatierung geändert
   (Python-Syntaxbaum bzw. JSON gleich): ``Code aufgeräumt (ohne Wirkung)``. Sonst was und wo im Code: das Thema
   aus den Aufrufen von Kev CAD (Bedingungen, Montage, Druckausrichtung, Animation, Kamera, erlaubte Überlappung)
   und die Stelle (Funktion, Abschnitt ab dem letzten ``step()`` davor, Konstante im Kopf, Hilfsdatei):
   ``Bedingungen in klemme() geändert, Teile gleich``, ``Code in „Kamera: Kameraträger“ geändert, Teile gleich``.
6. **Zuletzt die Dateien**, deren Inhalt sich nicht lesen lässt (binär, sehr groß): ``Geändert: teil.step``.
7. **Dokumente** (``dokumente/``: Blätter, Bauplan, dokumente.py) sind kein Code. Sie kommen nur in den Titel, wenn
   sich sonst nichts mit Wirkung geändert hat (neben einer Modelländerung sind neu zugeordnete Maße deren Folge):
   ``Zeichnung Seitenstange: 2 Maße geändert``, ``Bauplan: Schritt 7 umformuliert``, ``Zeichnungen Platte, Wange
   neu``.

Teilnamen: nach dem letzten ``/``, ohne Klammerzusatz (``(Druck)``) und Lagewörter (vorn, links …). Gleiches wird
zusammengefasst, mit Anzahl (``Gewindestift M4x35 (4×)``) oder als Nummernbereich (``Lenkrolle 1–4``); wird es zu
lang, gröber (``Flügelschraube M4 (12×)``, dann nur das erste Wort), dann ``und 3 weitere`` oder ``…`` und zuletzt
nur die Zahl (``+ 16 Teile``).

Fehlen die Daten eines der beiden Stände (noch nicht nachgerechnet oder nicht rechenbar), kommen Parameter und
Schritte aus dem Code (``param("breite", 120)``, ``step("…")``); über Teile sagt der Titel dann nichts.

``REGEL`` zählt die Fassung dieser Regeln: Wird sie erhöht, rechnet der Kernel die automatischen Titel aller Versionen
beim nächsten Öffnen neu (Titel stehen in den Metadaten, nicht in der Git-Geschichte).
"""

from __future__ import annotations

import ast
import difflib
import functools
import io
import json
import re
import tokenize
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from kevcad_kernel.versionen.dokumente import ist_dokument, vergleiche_dokumente
from kevcad_kernel.versionen.vergleich import _num, vergleiche, vergleiche_params

REGEL = 2  # 2: Dokumente (dokumente/) als eigene Regel statt „Code in zusammenbau.json geändert“
MAX_LAENGE = 60
TRENNER = " · "
OHNE_WIRKUNG = "Code aufgeräumt (ohne Wirkung)"
DOKUMENTE_OHNE_WIRKUNG = "Dokumente neu geschrieben (ohne Wirkung)"
ERSTER = "Erster Stand"
OHNE_AENDERUNG = "Ohne Dateiänderung"
TEILE_GLEICH = ", Teile gleich"
MINUS = "−"
LAGEWOERTER = frozenset({"vorn", "vorne", "hinten", "links", "rechts", "oben", "unten", "mitte", "mittig", "innen",
                         "außen", "aussen"})
DATEI_NAMEN = {"kevcad.json": "Projekteinstellungen", "katalog.json": "Projektkatalog",
               "bewegungen.json": "Bewegungen"}
# Themen aus den Aufrufen von Kev CAD in geänderten Zeilen (Zeichen der Zeile durch Leerzeichen getrennt)
THEMEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Bedingungen", re.compile(r"\bbed \. \w+|\b(?:bedingungen|drehgelenk|schiebegelenk|zylindergelenk|kugelgelenk|"
                               r"verbinde|in_bohrung|konzentrisch|buendig|platziere|min_abstand|min_wand) \(")),
    ("Montage", re.compile(r"\bmontage \(")),
    ("Druckausrichtung", re.compile(r"\bausrichtung\b|\bDRUCKLAGE\b")),
    ("Animation", re.compile(r"\banimation \(|\bbewegung\b")),
    ("Kamera", re.compile(r"\bkamera \(")),
    ("erlaubte Überlappung", re.compile(r"\berlaubt_ueberlappung \(")),
)

_KLAMMER = re.compile(r"\s*\([^()]*\)\s*$")
_NUMMER = re.compile(r"^(.*\S)\s+(\d+)$")
_MASS = re.compile(r"^(M\d+(?:[.,]\d+)?)(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?$", re.I)
_KONSTANTE = re.compile(r"^[A-Z][A-Z0-9_]+(?:, [A-Z][A-Z0-9_]+)*(?: …)?$")  # NORMTEIL_LAGER, KERN_M4, KERN_M6


def dateien_titel(dateien: list[str]) -> str:
    """Regel 6: nur die Dateinamen."""
    if not dateien:
        return OHNE_AENDERUNG
    namen = dateien[:3]
    rest = len(dateien) - len(namen)
    return "Geändert: " + ", ".join(namen) + (f" und {rest} weitere" if rest > 0 else "")


# =====================================================================================================================
# Zusammensetzen
# =====================================================================================================================


class Fassungen(list):
    """Fassungen einer Aufzählung (bevorzugte zuerst); ``voll`` sind die ohne Auslassung („…“, „und n weitere“)."""

    voll: set[str]


# Rang der Regeln: Segmente gleichen Rangs teilen sich den Platz, ein niedrigerer Rang kommt erst dazu, wenn alles
# Höhere vollständig dasteht
RANG = {"parameter": 1, "teile_neu": 2, "teile_weg": 2, "teile_geaendert": 3, "teile_verschoben": 3,
        "teile_umgefaerbt": 3, "stueckliste_neu": 3, "stueckliste_weg": 3, "stueckliste_geaendert": 3,
        "schritte_neu": 4, "schritte_weg": 4, "code_stellen": 5, "dateien": 6, "dokumente": 7,
        "code_aufgeraeumt": 8}


@dataclass
class Segment:
    """Ein Teil des Titels: Fassungen mit Namen von ausführlich (bevorzugt) bis knapp, dazu notfalls nur die Zahl."""

    regel: str
    optionen: list[str]
    zahl: str | None = None
    voll: set[str] | None = None  # Fassungen ohne Auslassung; None: alle mit Namen

    def __post_init__(self) -> None:
        if self.voll is None and isinstance(self.optionen, Fassungen):
            self.voll = set(self.optionen.voll)

    @property
    def alle(self) -> list[str]:
        return list(self.optionen) + ([self.zahl] if self.zahl else [])

    def ist_voll(self, text: str) -> bool:
        return text != self.zahl and (self.voll is None or text in self.voll)


def zusammensetzen(segmente: list[Segment], max_laenge: int = MAX_LAENGE) -> str:
    return _zusammensetzen(segmente, max_laenge)[0]


def _zusammensetzen(segmente: list[Segment], max_laenge: int) -> tuple[str, list[str]]:
    """Rang für Rang (``RANG``): die Segmente eines Rangs kommen mit ihrer knappsten Fassung mit Namen dazu, solange
    Platz ist (sonst wenigstens als Zahl), dann bekommt jedes Segment in Vorrangfolge die ausführlichste Fassung, die
    passt. Ein niedrigerer Rang kommt nur dazu, wenn alles Bisherige ohne Auslassung dasteht. Das erste Segment steht
    immer da (notfalls nur als Zahl oder gekürzt)."""
    segmente = [s for s in segmente if s.alle]
    if not segmente:
        return "", []

    def text_von(wahl: dict[int, str]) -> str:
        return TRENNER.join(wahl[i] for i in sorted(wahl))

    def passt(wahl: dict[int, str]) -> bool:
        return len(text_von(wahl)) <= max_laenge

    def ausbauen() -> None:  # ausführlichste Fassung, die passt, in Vorrangfolge
        for i in sorted(wahl):
            for opt in segmente[i].alle:
                if passt({**wahl, i: opt}):
                    wahl[i] = opt
                    break

    erstes = segmente[0]
    kurz0 = min(erstes.optionen, key=len) if erstes.optionen else erstes.zahl or ""
    if len(kurz0) > max_laenge and erstes.zahl:
        kurz0 = erstes.zahl
    wahl = {0: kurz0}
    raenge: list[list[int]] = []
    for i, s in enumerate(segmente):
        r = RANG.get(s.regel, 9)
        if raenge and RANG.get(segmente[raenge[-1][0]].regel, 9) == r:
            raenge[-1].append(i)
        else:
            raenge.append([i])
    for gruppe in raenge:
        for i in gruppe:
            s = segmente[i]
            if i not in wahl and s.optionen and passt({**wahl, i: min(s.optionen, key=len)}):
                wahl[i] = min(s.optionen, key=len)
        ausbauen()
        for i in gruppe:  # was im Rang keinen Platz mit Namen hatte, wenigstens als Zahl
            s = segmente[i]
            if i not in wahl and s.zahl and passt({**wahl, i: s.zahl}):
                wahl[i] = s.zahl
        ausbauen()
        if not all(segmente[i].ist_voll(t) for i, t in wahl.items()) or any(i not in wahl for i in gruppe):
            break
    text = text_von(wahl)
    if len(text) > max_laenge:
        text = text[:max_laenge - 1].rstrip(" ,·") + "…"
    return text, [segmente[i].regel for i in sorted(wahl)]


def _aufzaehlung(namen: list[str], rest: int) -> str:
    """rest > 0: „und n weitere“, rest < 0: „…“."""
    text = ", ".join(namen)
    if rest > 0:
        return f"{text} und {rest} weitere"
    if rest < 0:
        return f"{text} …"
    return text


Stufe = list[tuple[str, int]]  # (Text, wie viele Teile er abdeckt)


def _optionen(stufen: list[Stufe], form: Callable[[list[str], int], str]) -> Fassungen:
    """Fassungen einer Aufzählung: alle Namen je Stufe (fein → grob), dann Teilaufzählungen („und n weitere“, „…“),
    die mit den meisten erfassten Teilen und der feineren Stufe zuerst."""
    stufen = [s for s in stufen if s]
    out = Fassungen()
    out.voll = set()
    if not stufen:
        return out
    voll = [form([t for t, _ in s], 0) for s in stufen]
    teil: list[tuple[tuple[int, int, int], str]] = []
    for i, s in enumerate(stufen):
        for m in range(len(s) - 1, 0, -1):
            abgedeckt = sum(n for _, n in s[:m])
            namen = [t for t, _ in s[:m]]
            if len(s) - m > 1:  # „und 1 weitere“ nie, dann lieber „…“
                teil.append(((-abgedeckt, i, 0), form(namen, len(s) - m)))
            teil.append(((-abgedeckt, i, 1), form(namen, -1)))
    out.extend(dict.fromkeys(voll + [t for _, t in sorted(teil, key=lambda x: x[0])]))
    out.voll = set(voll)
    return out


def _einfach(namen: list[str]) -> list[Stufe]:
    return [[(n, 1) for n in namen]]


def _teile_text(n: int) -> str:
    return f"{n} Teil" if n == 1 else f"{n} Teile"


# =====================================================================================================================
# Teilnamen kürzen und zusammenfassen
# =====================================================================================================================


def kurzname(name: str) -> str:
    return name.rsplit("/", 1)[-1].strip() or name


def ohne_klammer(text: str) -> str:
    vorher = None
    while vorher != text:
        vorher, text = text, _KLAMMER.sub("", text)
    return text.strip() or (vorher or "").strip()


def stamm(kurz: str) -> tuple[str, int | None]:
    """Name ohne Klammerzusatz und Lagewörter, eine Nummer am Ende getrennt: „Lenkrolle 3“ → („Lenkrolle“, 3)."""
    text = ohne_klammer(kurz)
    woerter = [w for w in text.split() if w.lower() not in LAGEWOERTER]
    if woerter:
        text = " ".join(woerter)
    m = _NUMMER.match(text)
    if m:
        return m.group(1), int(m.group(2))
    return text, None


def _grob(s: str, stufe: int) -> str:
    """Stufe 1: erstes Wort und Gewindegröße („Flügelschraube M4x20 Schieber“ → „Flügelschraube M4“), Stufe 2: nur
    das erste Wort."""
    woerter = s.split()
    if not woerter:
        return s
    if stufe >= 2:
        return woerter[0]
    for w in woerter[1:]:
        m = _MASS.match(w)
        if m:
            return f"{woerter[0]} {m.group(1)}"
    return woerter[0]


def _gruppen(einheiten: list[str], stufe: int, anzahl: bool, gewicht: dict[str, int] | None = None) -> Stufe:
    reihe: dict[str, list[tuple[str, int | None, int]]] = {}
    for name in einheiten:
        kurz = kurzname(name)
        s, nr = stamm(kurz)
        reihe.setdefault(s if stufe == 0 else _grob(s, stufe), []).append((kurz, nr, (gewicht or {}).get(name, 1)))
    out: dict[str, int] = {}
    for key, glieder in reihe.items():
        n = len(glieder)
        teile = sum(g for _, _, g in glieder)
        if n == 1:
            text = ohne_klammer(glieder[0][0]) if stufe == 0 else key
        else:
            nrs = sorted(nr for _, nr, _ in glieder if nr is not None)
            if stufe == 0 and len(nrs) == n and nrs == list(range(nrs[0], nrs[0] + n)):
                text = f"{key} {nrs[0]}–{nrs[-1]}"
            else:
                text = f"{key} ({n}×)" if anzahl else key
        out[text] = out.get(text, 0) + teile
    return list(out.items())


def gruppen(einheiten: list[str], stufe: int = 0, *, anzahl: bool = True) -> list[str]:
    """Namen (Pfade) zusammengefasst, in der Reihenfolge ihres ersten Auftretens."""
    return [t for t, _ in _gruppen(einheiten, stufe, anzahl)]


def _praefixe(name: str) -> list[str]:
    teile = name.split("/")
    return ["/".join(teile[:i]) for i in range(1, len(teile) + 1)]


def neue_einheiten(namen: list[str], andere: list[str]) -> list[str]:
    """Für jedes Teil, das es in ``andere`` nicht gibt, die kürzeste Baugruppe (Pfad), die dort ganz fehlt."""
    bekannt = {p for n in andere for p in _praefixe(n)}
    out: list[str] = []
    for n in namen:
        for p in _praefixe(n):
            if p not in bekannt:
                if p not in out:
                    out.append(p)
                break
    return out


def geaenderte_einheiten(geaendert: list[str], alle: list[str]) -> list[str]:
    """Geänderte Teile; eine Baugruppe, deren Teile (mindestens zwei) sich alle geändert haben, steht für sie."""
    g = set(geaendert)
    unter: dict[str, list[str]] = {}
    for n in alle:
        for p in _praefixe(n)[:-1]:
            unter.setdefault(p, []).append(n)
    out: list[str] = []
    for n in geaendert:
        einheit = n
        for p in _praefixe(n)[:-1]:
            kinder = unter.get(p, [])
            if len(kinder) >= 2 and all(k in g for k in kinder):
                einheit = p
                break
        if einheit not in out:
            out.append(einheit)
    return out


def _gewicht(einheiten: list[str], namen: list[str]) -> dict[str, int]:
    """Wie viele Teile eine Einheit (Teil oder Baugruppe) umfasst."""
    return {e: sum(1 for n in namen if n == e or n.startswith(e + "/")) or 1 for e in einheiten}


# =====================================================================================================================
# Segmente aus den Daten
# =====================================================================================================================


def _param_segment(params: list[dict[str, Any]]) -> Segment | None:
    geaendert = [f"{p['name']} {_num(p['alt'], 4)} → {_num(p['neu'], 4)}" for p in params if p["art"] == "geaendert"]
    neu = [f"{p['name']} = {_num(p['neu'], 4)} neu" for p in params if p["art"] == "neu"]
    weg = [f"{p['name']} entfernt" for p in params if p["art"] == "weg"]
    if not (geaendert or neu or weg):
        return None
    kurz = list(geaendert)
    if neu:
        kurz += neu if len(neu) <= 2 else [f"{len(neu)} Parameter neu"]
    if weg:
        kurz += weg if len(weg) <= 2 else [f"{len(weg)} Parameter entfernt"]
    alle = _aufzaehlung(geaendert + neu + weg, 0)
    knapp = _optionen(_einfach(kurz), _aufzaehlung)
    n = len(geaendert) + len(neu) + len(weg)
    return Segment("parameter", list(dict.fromkeys([alle] + knapp)), f"{n} Parameter geändert" if n > 1 else None,
                   voll={alle} | knapp.voll)


def _teile_segment(regel: str, einheiten: list[str], namen: list[str], zeichen: str) -> Segment | None:
    if not einheiten:
        return None
    gewicht = _gewicht(einheiten, namen)
    stufen = [_gruppen(einheiten, s, True, gewicht) for s in (0, 1, 2)]
    return Segment(regel, _optionen(stufen, lambda n, r: f"{zeichen} " + _aufzaehlung(n, r)),
                   f"{zeichen} {_teile_text(len(namen))}")


def _geaendert_segment(regel: str, einheiten: list[str], namen: list[str], wort: str) -> Segment | None:
    if not einheiten:
        return None
    gewicht = _gewicht(einheiten, namen)
    stufen = [_gruppen(einheiten, s, False, gewicht) for s in (0, 1, 2)]
    return Segment(regel, _optionen(stufen, lambda n, r: _aufzaehlung(n, r) + f" {wort}"),
                   f"{_teile_text(len(namen))} {wort}")


def _bom_name(benennung: Any) -> str:
    text = str(benennung or "").split(",")[0].strip()
    return ohne_klammer(text) or str(benennung or "?")


def _bom_items(zeilen: list[dict[str, Any]]) -> list[str]:
    summe: dict[str, int] = {}
    for ln in zeilen:
        name = _bom_name(ln.get("benennung"))
        try:
            n = int(ln.get("anzahl") or 1)
        except (TypeError, ValueError):
            n = 1
        summe[name] = summe.get(name, 0) + n
    return [f"{k} ({n}×)" if n > 1 else k for k, n in summe.items()]


def _stueckliste_segmente(s: dict[str, Any]) -> list[Segment]:
    out = []
    for regel, zeilen, zeichen in (("stueckliste_neu", s.get("neu") or [], "+"),
                                   ("stueckliste_weg", s.get("weg") or [], MINUS)):
        items = _bom_items(zeilen)
        if items:
            out.append(Segment(regel, _optionen(_einfach(items),
                                                lambda n, r, z=zeichen: f"Stückliste {z} " + _aufzaehlung(n, r)),
                               f"Stückliste {zeichen} {len(items)} Positionen" if len(items) > 1 else None))
    items = []
    for ln in s.get("geaendert") or []:
        name = _bom_name(ln.get("benennung"))
        alt_m, neu_m = ln.get("alt_masse_text"), ln.get("masse_text")
        if alt_m and neu_m and alt_m != neu_m:
            items.append(f"{name} {alt_m} → {neu_m}")
        elif ln.get("alt_anzahl") != ln.get("neu_anzahl"):
            items.append(f"{name} {ln.get('alt_anzahl')}× → {ln.get('neu_anzahl')}×")
        else:
            items.append(f"{name} Preis")
    if items:
        out.append(Segment("stueckliste_geaendert",
                           _optionen(_einfach(items), lambda n, r: "Stückliste: " + _aufzaehlung(n, r)),
                           f"Stückliste: {len(items)} Positionen geändert" if len(items) > 1 else None))
    return out


def _schritt_segmente(alt: list[str], neu: list[str]) -> list[Segment]:
    a, b = set(alt), set(neu)
    hinzu = list(dict.fromkeys(x for x in neu if x not in a))
    weg = list(dict.fromkeys(x for x in alt if x not in b))
    out = []
    if hinzu:
        def form_neu(namen: list[str], rest: int) -> str:
            kopf = "neuer Schritt " if len(namen) == 1 and not rest else "neue Schritte "
            return kopf + _aufzaehlung([f"„{x}“" for x in namen], rest)

        out.append(Segment("schritte_neu", _optionen(_einfach(hinzu), form_neu),
                           f"{len(hinzu)} neue Schritte" if len(hinzu) > 1 else None))
    if weg:
        def form_weg(namen: list[str], rest: int) -> str:
            kopf = "Schritt " if len(namen) == 1 and not rest else "Schritte "
            return kopf + _aufzaehlung([f"„{x}“" for x in namen], rest) + " entfernt"

        out.append(Segment("schritte_weg", _optionen(_einfach(weg), form_weg),
                           f"{len(weg)} Schritte entfernt" if len(weg) > 1 else None))
    return out


def _code_segment(themen: dict[str, list[str]], orte: list[str], teile_gleich: bool,
                  allein: bool) -> Segment | None:
    """Regel 5: was (Thema, mit den Stellen, an denen es vorkommt) und sonst wo (Stellen) sich der Code geändert hat,
    ohne dass sich an den Teilen etwas zeigt."""
    nach = TEILE_GLEICH if teile_gleich else ""
    was = ", ".join(themen) if themen else "Code"
    if themen:
        orte = list(dict.fromkeys(o for liste in themen.values() for o in liste))
    opts = _optionen(_einfach(orte), lambda n, r: f"{was} in {_aufzaehlung(n, r)} geändert{nach}") if orte else []
    zahl = None
    if themen:
        opts.append(f"{was} geändert{nach}")
        if len(themen) > 1:
            opts.append(f"{next(iter(themen))} … geändert{nach}")
    elif len(orte) > 1:
        zahl = f"Code an {len(orte)} Stellen geändert{nach}"
    elif allein or not orte:
        zahl = f"Code geändert{nach}" if allein else None
    if not opts and not zahl:
        return None
    return Segment("code_stellen", list(dict.fromkeys(opts)), zahl)


def _punkte_fassungen(kopf: str, punkte: list[str]) -> Fassungen:
    """„Zeichnung Platte: 2 Maße geändert, Ansicht verschoben“, dann mit weniger Punkten („…“), zuletzt „… geändert“."""
    out = Fassungen()
    out.voll = set()
    if punkte and punkte != ["geändert"]:
        voll = f"{kopf}: {', '.join(punkte)}"
        out.append(voll)
        out.voll.add(voll)
        for m in range(len(punkte) - 1, 0, -1):
            out.append(f"{kopf}: {', '.join(punkte[:m])} …")
    out.append(f"{kopf} geändert")
    if not punkte or punkte == ["geändert"]:
        out.voll.add(f"{kopf} geändert")
    return out


def _dokumente_segmente(eintraege: list[dict[str, Any]]) -> list[Segment]:
    """Regel 7: Blätter (neu, geändert, entfernt), Bauplan, übrige Dateien in ``dokumente/``."""
    out: list[Segment] = []
    blaetter = [e for e in eintraege if e["art"] == "zeichnung"]
    for status, wort in (("A", "neu"), ("M", None), ("D", "entfernt")):
        gruppe = [e for e in blaetter if e["status"] == status]
        if not gruppe:
            continue
        if wort is None and len(gruppe) == 1:
            out.append(Segment("dokumente", _punkte_fassungen(f"Zeichnung {gruppe[0]['name']}", gruppe[0]["punkte"])))
            continue
        namen = [e["name"] for e in gruppe]
        wort = wort or "geändert"

        def form(n: list[str], r: int, w: str = wort) -> str:
            kopf = "Zeichnung " if len(n) == 1 and not r else "Zeichnungen "
            return kopf + _aufzaehlung(n, r) + f" {w}"

        out.append(Segment("dokumente", _optionen(_einfach(namen), form),
                           f"{len(namen)} Zeichnungen {wort}" if len(namen) > 1 else None))
    for e in eintraege:
        if e["art"] == "bauplan":
            if e["status"] == "M":
                out.append(Segment("dokumente", _punkte_fassungen("Bauplan", e["punkte"])))
            else:
                out.append(Segment("dokumente", [e["text"]]))
    sonst = [e for e in eintraege if e["art"] == "datei"]
    if sonst:
        out.append(Segment("dokumente", _optionen(_einfach([e["text"] for e in sonst]), _aufzaehlung),
                           f"{len(sonst)} Dokumente geändert" if len(sonst) > 1 else None))
    return out


def _dokumente_titel(aenderungen: list[dict[str, Any]], basis: str, max_laenge: int,
                     code_aufgeraeumt: bool) -> dict[str, Any]:
    segmente = _dokumente_segmente(vergleiche_dokumente(aenderungen))
    if not segmente:
        return {"titel": OHNE_WIRKUNG if code_aufgeraeumt else DOKUMENTE_OHNE_WIRKUNG, "basis": basis,
                "regeln": ["ohne_wirkung"]}
    if code_aufgeraeumt:
        segmente.append(Segment("code_aufgeraeumt", ["Code aufgeräumt"]))
    titel, regeln = _zusammensetzen(segmente, max_laenge)
    return {"titel": titel, "basis": basis, "regeln": regeln}


# =====================================================================================================================
# Code lesen (Python, JSON)
# =====================================================================================================================


@dataclass(frozen=True)
class PyInfo:
    dump: str  # Syntaxbaum ohne Docstrings und Kommentare (Vergleich „ohne Wirkung“)
    params: dict[str, Any]  # param("name", wert) mit festem Wert
    schritte: tuple[str, ...]  # step("…") außerhalb von Funktionen, in Reihenfolge
    logisch: tuple[tuple[int, str], ...]  # logische Zeilen (Startzeile, Text ohne Kommentar), ohne Docstrings
    anweisungen: tuple[tuple[int, int, str, str], ...]  # oberste Anweisungen: (von, bis, Art, Name)
    schritt_zeilen: tuple[tuple[int, str], ...]
    erster_schritt: int

    def ort(self, zeile: int) -> str | None:
        """Wo im Modell die Zeile steht: Funktion, Klasse, Importe und Konstanten im Kopf, sonst der Abschnitt ab dem
        letzten step() davor."""
        starts = [a[0] for a in self.anweisungen]
        i = bisect_right(starts, zeile) - 1
        if i < 0 or zeile > self.anweisungen[i][1]:
            return None
        von, _, art, name = self.anweisungen[i]
        if art == "def":
            return f"{name}()"
        if art == "class":
            return name
        if art == "import" and von < self.erster_schritt:
            return "Importe"
        if art == "zuweisung" and name and (von < self.erster_schritt or _KONSTANTE.match(name)):
            return name
        zeilen = [z for z, _ in self.schritt_zeilen]
        j = bisect_right(zeilen, zeile) - 1
        return f"„{self.schritt_zeilen[j][1]}“" if j >= 0 else "Kopf von model.py"


def _text_wert(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        teile = []
        for v in node.values:
            teile.append(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "…")
        text = "".join(teile)
        return text if re.search(r"[A-Za-zÄÖÜäöüß]{2}", text) else None
    return None


def _aufruf_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _ziel_namen(stmt: ast.stmt) -> str:
    ziele: list[ast.AST] = []
    if isinstance(stmt, ast.Assign):
        ziele = list(stmt.targets)
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        ziele = [stmt.target]
    namen: list[str] = []
    for z in ziele:
        elemente = z.elts if isinstance(z, (ast.Tuple, ast.List)) else [z]
        for e in elemente:
            if not isinstance(e, ast.Name):
                return ""
            namen.append(e.id)
    namen = list(dict.fromkeys(namen))
    return ", ".join(namen[:2]) + (" …" if len(namen) > 2 else "")


def _ist_text_ausdruck(stmt: Any) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


class _OhneTexte(ast.NodeTransformer):
    """Entfernt alleinstehende Zeichenketten (Docstrings): sie haben keine Wirkung."""

    def generic_visit(self, node: ast.AST) -> ast.AST:
        for feld in ("body", "orelse", "finalbody"):
            liste = getattr(node, feld, None)
            if isinstance(liste, list):
                setattr(node, feld, [s for s in liste if not _ist_text_ausdruck(s)])
        return super().generic_visit(node)


def _logische_zeilen(text: str) -> list[tuple[int, str]]:
    """Logische Zeilen ohne Kommentare, Leerzeilen und Docstrings; Einrückungstiefe vorn, Zeichen durch Leerzeichen
    getrennt (Umbrüche und Abstände ändern nichts)."""
    out: list[tuple[int, str]] = []
    toks: list[tokenize.TokenInfo] = []
    tiefe = 0
    start = 0
    ueberspringen = {tokenize.COMMENT, tokenize.NL, tokenize.ENCODING, tokenize.ENDMARKER}
    texte = {tokenize.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, name):
            texte.add(getattr(tokenize, name))

    def abschliessen() -> None:
        if toks and not all(t.type in texte for t in toks):
            out.append((start, f"{tiefe}|" + " ".join(t.string for t in toks)))

    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in ueberspringen:
                continue
            if tok.type == tokenize.INDENT:
                tiefe += 1
                continue
            if tok.type == tokenize.DEDENT:
                tiefe -= 1
                continue
            if tok.type == tokenize.NEWLINE:
                abschliessen()
                toks = []
                continue
            if not toks:
                start = tok.start[0]
            toks.append(tok)
        abschliessen()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [(i, z.strip()) for i, z in enumerate(text.splitlines(), 1)
                if z.strip() and not z.strip().startswith("#")]
    return out


@functools.lru_cache(maxsize=32)
def py_info(text: str) -> PyInfo | None:
    try:
        baum = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    params: dict[str, Any] = {}
    for node in ast.walk(baum):
        if isinstance(node, ast.Call) and _aufruf_name(node) == "param" and node.args:
            name = node.args[0]
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                continue
            wert_node = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "default"), None)
            if wert_node is None:
                continue
            try:
                wert = ast.literal_eval(wert_node)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue
            if isinstance(wert, (int, float)) and not isinstance(wert, bool):
                params.setdefault(name.value, wert)
    anweisungen = []
    schritt_zeilen = []
    for stmt in baum.body:
        von, bis = stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anweisungen.append((von, bis, "def", stmt.name))
            continue
        if isinstance(stmt, ast.ClassDef):
            anweisungen.append((von, bis, "class", stmt.name))
            continue
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            anweisungen.append((von, bis, "import", ""))
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            anweisungen.append((von, bis, "zuweisung", _ziel_namen(stmt)))
        else:
            anweisungen.append((von, bis, "sonst", ""))
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and _aufruf_name(node) == "step" and node.args:
                t = _text_wert(node.args[0])
                if t:
                    schritt_zeilen.append((node.lineno, t))
    schritt_zeilen.sort()
    dump = ast.dump(_OhneTexte().visit(baum), include_attributes=False)
    return PyInfo(dump=dump, params=params, schritte=tuple(t for _, t in schritt_zeilen),
                  logisch=tuple(_logische_zeilen(text)), anweisungen=tuple(anweisungen),
                  schritt_zeilen=tuple(schritt_zeilen),
                  erster_schritt=schritt_zeilen[0][0] if schritt_zeilen else 10 ** 9)


def geaenderte_zeilen(a: PyInfo, b: PyInfo) -> list[tuple[str, str]]:
    """(Stelle, Text) der logischen Zeilen, die sich unterscheiden (alte nach ``a`` verortet, neue nach ``b``)."""
    sa = [t for _, t in a.logisch]
    sb = [t for _, t in b.logisch]
    out: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for i in range(i1, i2):
            out.append((a.ort(a.logisch[i][0]) or "", a.logisch[i][1]))
        for j in range(j1, j2):
            out.append((b.ort(b.logisch[j][0]) or "", b.logisch[j][1]))
    return out


def themen(texte: list[str]) -> list[str]:
    """Themen von Kev CAD in geänderten Zeilen, in der Reihenfolge ihres ersten Auftretens."""
    return list(themen_orte([("", t) for t in texte]))


def themen_orte(zeilen: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Thema → Stellen, an denen es in geänderten Zeilen vorkommt (Reihenfolge des ersten Auftretens)."""
    out: dict[str, list[str]] = {}
    for ort, text in zeilen:
        for name, muster in THEMEN:
            if muster.search(text):
                orte = out.setdefault(name, [])
                if ort and ort not in orte:
                    orte.append(ort)
    return out


def datei_label(pfad: str) -> str:
    return DATEI_NAMEN.get(pfad, PurePosixPath(pfad).name)


@dataclass
class CodeBefund:
    params_alt: dict[str, Any] = field(default_factory=dict)
    params_neu: dict[str, Any] = field(default_factory=dict)
    schritte_alt: list[str] = field(default_factory=list)
    schritte_neu: list[str] = field(default_factory=list)
    orte: list[str] = field(default_factory=list)
    themen: dict[str, list[str]] = field(default_factory=dict)  # Thema → Stellen
    ohne_wirkung: bool = True
    binaer: list[str] = field(default_factory=list)

    def ort(self, o: str) -> None:
        if o and o not in self.orte:
            self.orte.append(o)


def code_befund(aenderungen: list[dict[str, Any]]) -> CodeBefund:
    """Was der Unterschied der Dateien hergibt. ``aenderungen``: je Datei ``pfad``, ``status`` (A, M, D), ``alt``,
    ``neu`` (Text oder None), ``binaer``."""
    b = CodeBefund()
    texte: list[tuple[str, str]] = []  # (Stelle, Text) geänderter Zeilen für die Themen
    for a in aenderungen:
        pfad = str(a.get("pfad") or "")
        label = datei_label(pfad)
        alt_t, neu_t = a.get("alt"), a.get("neu")
        if a.get("binaer") or (alt_t is None and neu_t is None):
            b.binaer.append(pfad)
            b.ohne_wirkung = False
            continue
        if alt_t is None or neu_t is None:
            b.ohne_wirkung = False
            b.ort(f"{label} (neu)" if alt_t is None else f"{label} (entfernt)")
            continue
        if pfad.endswith(".py"):
            ia, ib = py_info(alt_t), py_info(neu_t)
            if ia is None or ib is None:
                b.ohne_wirkung = False
                b.ort(label)
                continue
            if pfad == "model.py":
                b.params_alt, b.params_neu = dict(ia.params), dict(ib.params)
                b.schritte_alt, b.schritte_neu = list(ia.schritte), list(ib.schritte)
            if ia.dump != ib.dump:
                b.ohne_wirkung = False
                zeilen = geaenderte_zeilen(ia, ib)
                if pfad != "model.py":
                    zeilen = [(label, t) for _, t in zeilen]
                texte += zeilen
                for o, _ in zeilen:
                    b.ort(o)
                if not zeilen:
                    b.ort(label)
        elif pfad.endswith(".json"):
            try:
                gleich = json.loads(alt_t) == json.loads(neu_t)
            except ValueError:
                gleich = False
            if not gleich:
                b.ohne_wirkung = False
                b.ort(label)
                if pfad == "bewegungen.json":
                    texte.append((label, "bewegung"))
        elif alt_t != neu_t:
            b.ohne_wirkung = False
            b.ort(label)
    b.themen = themen_orte(texte)
    return b


# =====================================================================================================================
# Titel
# =====================================================================================================================


def auto_titel(aenderungen: list[dict[str, Any]], alt: dict[str, Any] | None, neu: dict[str, Any] | None, *,
               erster: bool = False, max_laenge: int = MAX_LAENGE) -> dict[str, Any]:
    """Titel aus dem Vergleich mit der Vorgängerversion. Rückgabe: ``titel``, ``basis`` („daten“: beide Stände
    gerechnet, sonst „code“), ``regeln`` (welche Regeln den Titel bilden)."""
    if erster:
        return {"titel": ERSTER, "basis": "daten" if neu is not None else "code", "regeln": ["erster"]}
    if not aenderungen:
        return {"titel": OHNE_AENDERUNG, "basis": "code", "regeln": ["ohne_aenderung"]}
    alle = aenderungen
    dokumente = [a for a in aenderungen if ist_dokument(str(a.get("pfad") or ""))]
    aenderungen = [a for a in aenderungen if not ist_dokument(str(a.get("pfad") or ""))]
    mit_daten = alt is not None and neu is not None
    basis = "daten" if mit_daten else "code"
    code = code_befund(aenderungen)
    segmente: list[Segment] = []
    daten_geaendert = False
    if mit_daten:
        v = vergleiche(alt, neu)
        params = v["params"]
        t = v["teile"]
        neu_namen = [x["name"] for x in neu.get("teile") or []]
        alt_namen = [x["name"] for x in alt.get("teile") or []]
        kandidaten = [
            _param_segment(params),
            _teile_segment("teile_neu", neue_einheiten(t["neu"], alt_namen), t["neu"], "+"),
            _teile_segment("teile_weg", neue_einheiten(t["weg"], neu_namen), t["weg"], MINUS),
        ]
        if not params:  # neben Parametern sind geänderte Teile deren Folge
            lage = [g["name"] for g in t["geaendert"] if g["arten"] == ["lage"]]
            farbe = [g["name"] for g in t["geaendert"] if set(g["arten"]) == {"farbe"}]
            form = [g["name"] for g in t["geaendert"] if g["name"] not in set(lage) | set(farbe)]
            kandidaten += [
                _geaendert_segment("teile_geaendert", geaenderte_einheiten(form, neu_namen), form, "geändert"),
                _geaendert_segment("teile_verschoben", geaenderte_einheiten(lage, neu_namen), lage, "verschoben"),
                _geaendert_segment("teile_umgefaerbt", geaenderte_einheiten(farbe, neu_namen), farbe, "umgefärbt"),
            ]
        segmente = [s for s in kandidaten if s]
        if not t["neu"] and not t["weg"] and not t["geaendert"]:
            segmente += _stueckliste_segmente(v["stueckliste"])
        daten_geaendert = bool(segmente) or bool(t["geaendert"])
    else:
        seg = _param_segment(vergleiche_params(code.params_alt, code.params_neu))
        if seg:
            segmente.append(seg)
    if mit_daten and "schritte" in alt and "schritte" in neu:
        schritte = _schritt_segmente(list(alt["schritte"] or []), list(neu["schritte"] or []))
    else:
        schritte = _schritt_segmente(code.schritte_alt, code.schritte_neu)
    if not daten_geaendert:
        if code.ohne_wirkung and not segmente and not schritte:
            if dokumente:  # Regel 7: nur Dokumente geändert (und höchstens Code ohne Wirkung)
                return _dokumente_titel(dokumente, basis, max_laenge, code_aufgeraeumt=bool(aenderungen))
            return {"titel": OHNE_WIRKUNG, "basis": basis, "regeln": ["ohne_wirkung"]}
        code_param = bool(segmente)  # Parameter aus dem Code: ihre Zeilen sind damit schon genannt
        segmente += schritte
        if not code_param:
            seg = _code_segment(code.themen, code.orte, teile_gleich=mit_daten,
                                allein=not segmente and not code.binaer)
            if seg:
                segmente.append(seg)
    else:
        segmente += schritte
    if code.binaer:
        segmente.append(Segment("dateien", [dateien_titel(code.binaer)]))
    titel, regeln = _zusammensetzen(segmente, max_laenge)
    if not titel:
        titel, regeln = dateien_titel([str(a.get("pfad")) for a in alle]), ["dateien"]
    return {"titel": titel, "basis": basis, "regeln": regeln}


__all__ = ["ERSTER", "MAX_LAENGE", "OHNE_AENDERUNG", "OHNE_WIRKUNG", "REGEL", "Segment", "auto_titel", "code_befund",
           "dateien_titel", "gruppen", "kurzname", "neue_einheiten", "py_info", "stamm", "themen", "zusammensetzen"]

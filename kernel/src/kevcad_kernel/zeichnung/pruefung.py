"""Prüfung eines gerechneten Blatts (RECHERCHE-PHASE6.md 2.5, Punkte 5 und 7): Befunde im gemeinsamen Format.

- **Bemaßungsgraph je Achse:** Knoten sind die Koordinaten der Bezüge entlang einer Achse des Teils, Kanten die Maße.
  Bezug ist die Seite des Hüllquaders (Koordinate 0). Ein Maß, das zwei schon verbundene Knoten verbindet, ist eine
  Überbemaßung (Kreis); ein Merkmal, dessen Lage nicht mit dem Bezug verbunden ist, ist ein fehlendes Lagemaß. Symmetrie
  (Lage auf der Mittellinie, symmetrisch bemaßte Paare) und gleichmäßige Lochbilder verbinden ihre Knoten selbst.
- **Vollständigkeit:** Jede Bohrung, Einsatz- und Muttertasche hat eine Größenangabe.
- **Darstellung:** Maß ragt aus der Zeichenfläche, Texte überlappen sich, Maß doppelt, Maß verwaist.

Befund: ``{"art": "bemassung", "pruefung", "schwere" (warnung | hinweis), "text", "masse" [ids], "merkmal"}``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.geo2d import Rechteck
from kevcad_kernel.zeichnung.merkmale import Merkmale, zahl

TOL = 0.01


class _Knoten:
    """Union-Find über gerundete Koordinaten."""

    def __init__(self) -> None:
        self.eltern: dict[float, float] = {}

    def _k(self, x: float) -> float:
        return round(float(x) / TOL) * TOL

    def finde(self, x: float) -> float:
        x = self._k(x)
        self.eltern.setdefault(x, x)
        while self.eltern[x] != x:
            self.eltern[x] = self.eltern[self.eltern[x]]
            x = self.eltern[x]
        return x

    def verbinde(self, a: float, b: float) -> bool:
        """False, wenn a und b schon verbunden waren (Kreis)."""
        ra, rb = self.finde(a), self.finde(b)
        if ra == rb:
            return False
        self.eltern[ra] = rb
        return True

    def verbunden(self, a: float, b: float) -> bool:
        return self.finde(a) == self.finde(b)


def _koordinate(merk: Merkmale, b: dict[str, Any], achse: int) -> float | None:
    m = merk.get(str(b.get("merkmal") or ""))
    if m is None:
        return None
    sub = b.get("element")
    if sub and m.art in ("tasche", "absatz"):
        j = int(sub[2:])
        if j != achse:
            return None
        return float(np.asarray(m.werte["lo" if sub.startswith("lo") else "hi"])[j])
    if m.art == "seite":
        if int(m.werte["achse"]) != achse:
            return None
        return 0.0 if int(m.werte["seite"]) < 0 else float(merk.groesse[achse])
    if m.art == "stirnseite":
        return 0.0 if m.werte.get("ende") == "a" else float(merk.groesse[0]) if achse == 0 else None
    mitte = m.signatur.get("mitte")
    if mitte is None:
        return None
    if m.art in ("tasche", "absatz") and int(m.werte["achse"]) == achse:
        return float(np.asarray(mitte)[achse])
    return float(np.asarray(mitte)[achse])


def _achse_des_masses(merk: Merkmale, m: dict[str, Any], blicke: dict[str, Any]) -> int | None:
    b = blicke.get(m.get("ansicht"))
    r = m.get("_richtung") or m.get("richtung")
    if b is None or r not in ("x", "y"):
        return None
    v = np.asarray(b.rechts if r == "x" else b.oben, dtype=float)
    i = int(np.argmax(np.abs(v)))
    return i if abs(v[i]) > 1 - 1e-6 else None


def ohne_ueberbemassung(masse: list[dict[str, Any]], merk: Merkmale, blicke: dict[str, Any],
                        symmetrie: set[int]) -> list[dict[str, Any]]:
    """Automatische lineare Maße, die einen Kreis im Bemaßungsgraphen schließen würden, weglassen (ISO 129-1: jedes
    Maß einmal). Reihenfolge: Hüllmaße zuerst (Gesamtmaße sind Funktionsmaße), danach nach Priorität."""
    graphen = [_Knoten(), _Knoten(), _Knoten()]
    g = merk.groesse
    for i in range(3):
        graphen[i].finde(0.0)
        if i in symmetrie:
            graphen[i].verbinde(0.0, g[i] / 2)
    behalten: list[dict[str, Any]] = []
    reihenfolge = sorted(masse, key=lambda m: (0 if str(m.get("schluessel", "")).startswith("huelle") else 1,
                                               int(m.get("_prio") or 50)))
    weg: set[int] = set()
    for m in reihenfolge:
        if m.get("art") not in ("linear", "bezugskette"):
            continue
        i = _achse_des_masses(merk, m, blicke)
        if i is None:
            continue
        koords = [_koordinate(merk, b, i) for b in m.get("bezuege") or []]
        if any(c is None for c in koords) or len(koords) < 2:
            continue
        schluessel = str(m.get("schluessel") or "")
        if schluessel.startswith("sym:"):
            for c in koords:
                graphen[i].verbinde(g[i] / 2, c)
            continue
        if schluessel.startswith("teilung:"):
            teile = schluessel.split(":")
            lb = merk.get(f"{teile[1]}:{teile[2]}")
            if lb is not None:
                for t in lb.teile:
                    c = _koordinate(merk, {"merkmal": t}, i)
                    if c is not None:
                        graphen[i].verbinde(koords[0], c)
            continue
        neu = [c for c in koords[1:] if graphen[i].verbinde(koords[0], c)]
        if not neu and not schluessel.startswith("huelle"):
            weg.add(id(m))
    for m in masse:
        if id(m) not in weg:
            behalten.append(m)
    return behalten


def pruefe(blatt: dict[str, Any], merk: Merkmale | None, ansichten: dict[str, Any], grafiken: list[tuple[dict, Any]],
           texte: list[dict[str, Any]], flaeche: Rechteck | None) -> list[dict[str, Any]]:
    befunde: list[dict[str, Any]] = []

    def befund(pruefung: str, schwere: str, text: str, masse: list[str] | None = None, merkmal: str | None = None) \
            -> None:
        befunde.append({"art": "bemassung", "pruefung": pruefung, "schwere": schwere, "text": text,
                        "masse": masse or [], "merkmal": merkmal})

    for m in blatt["masse"]:
        if m.get("verwaist"):
            befund("verwaist", "warnung", f"Maß {m['id']} ist verwaist (Bezug nach der Änderung nicht mehr gefunden): "
                                          "löschen oder neu beziehen", [m["id"]])
    # Darstellung: außerhalb, Überlappung
    boxen: list[tuple[str, Rechteck]] = []
    for m, g in grafiken:
        if g is None:
            continue
        for r in g.rechtecke():
            if flaeche is not None and not flaeche.erweitert(0.5).enthaelt(r):
                befund("ausserhalb", "warnung", f"Maß {m['id']} ({g.text}) ragt aus der Zeichenfläche", [m["id"]])
            boxen.append((m["id"], r))
    gemeldet: set[tuple[str, str]] = set()
    for i, (a, ra) in enumerate(boxen):
        for b, rb in boxen[i + 1:]:
            if a != b and ra.erweitert(-0.4).schneidet(rb.erweitert(-0.4)) and (a, b) not in gemeldet:
                gemeldet.add((a, b))
                befund("ueberlappung", "hinweis", f"Texte der Maße {a} und {b} überlappen sich", [a, b])
    # doppelte Maße (gleiche Art, gleiche Bezüge, gleiche Richtung)
    gesehen: dict[tuple, str] = {}
    for m in blatt["masse"]:
        k = (m.get("art"), m.get("_richtung") or m.get("richtung"),
             tuple(sorted((x.get("teil") or "", x.get("merkmal") or x.get("ref") or "", x.get("element") or "")
                          for x in m.get("bezuege") or [])))
        if k in gesehen and m.get("art") not in ("bohrung", "merkmal", "fase", "radius"):
            befund("doppelt", "warnung", f"Maß {m['id']} wiederholt Maß {gesehen[k]}", [gesehen[k], m["id"]])
        else:
            gesehen[k] = m["id"]
    if merk is None or blatt["inhalt"]["art"] != "teil":
        return befunde
    # Bemaßungsgraph je Achse
    blicke = {vid: v.blick for vid, v in ansichten.items()}
    graphen = [_Knoten(), _Knoten(), _Knoten()]
    g = merk.groesse
    symmetrie_achsen: set[int] = set()
    for vid, v in ansichten.items():
        for r in v.e.get("_symmetrie") or []:
            # Symmetrielinie entlang Blatt-x bedeutet: Lagen entlang Blatt-y sind symmetrisch
            vec = np.asarray(v.blick.oben if r == "x" else v.blick.rechts, dtype=float)
            i = int(np.argmax(np.abs(vec)))
            symmetrie_achsen.add(i)
    if merk.system.art == "stange":
        symmetrie_achsen |= {1, 2}  # quer zur Stange: Lage zur Stangenachse
    for i in range(3):
        graphen[i].finde(0.0)
        if i in symmetrie_achsen:
            graphen[i].verbinde(0.0, g[i] / 2)  # Mittellinie als Bezug
    for m in blatt["masse"]:
        if m.get("art") == "koordinaten" and not m.get("verwaist"):
            for b in (m.get("bezuege") or [])[2:]:
                f = merk.get(str(b.get("merkmal") or ""))
                if f is None:
                    continue
                for i in range(3):
                    if abs(float(np.asarray(f.werte.get("achse"), dtype=float)[i])) < 0.5:
                        graphen[i].verbinde(0.0, float(np.asarray(f.signatur["mitte"])[i]))
            continue
        if m.get("verwaist") or m.get("art") not in ("linear", "bezugskette"):
            continue
        i = _achse_des_masses(merk, m, blicke)
        if i is None:
            continue
        koords = [_koordinate(merk, b, i) for b in m.get("bezuege") or []]
        if any(c is None for c in koords) or len(koords) < 2:
            continue
        schluessel = str(m.get("schluessel") or "")
        if schluessel.startswith("sym:"):
            # symmetrisches Paar: beide Lagen hängen über die Mittellinie am Bezug
            for c in koords:
                graphen[i].verbinde(g[i] / 2, c)
            continue
        if schluessel.startswith("teilung:"):
            lb = merk.get(schluessel.split(":")[1] + ":" + schluessel.split(":")[2])
            if lb is not None:  # gleichmäßige Teilung: alle Glieder an der ersten Lage
                cs = [_koordinate(merk, {"merkmal": t}, i) for t in lb.teile]
                for c in cs:
                    if c is not None:
                        graphen[i].verbinde(koords[0], c)
                continue
        basis = koords[0]
        for c in koords[1:]:
            if not graphen[i].verbinde(basis, c):
                befund("ueberbemasst", "warnung", f"Maß {m['id']} ({zahl(abs(c - basis))} entlang {'xyz'[i]}) ist "
                                                  "überzählig: die Lage ist schon durch andere Maße bestimmt", [m["id"]])
    # Vollständigkeit der Merkmale
    angaben: set[str] = set()
    for m in blatt["masse"]:
        for b in m.get("bezuege") or []:
            if m.get("art") in ("bohrung", "gewinde", "durchmesser", "merkmal", "koordinaten"):
                angaben.add(str(b.get("merkmal")))
    lochbild_von = {t: lb for lb in merk.von_art("lochbild") for t in lb.teile}
    for f in merk.von_art("bohrung", "einsatztasche", "muttertasche", "langloch"):
        lb = lochbild_von.get(f.id)
        if f.id not in angaben and (lb is None or not any(t in angaben for t in lb.teile)):
            befund("fehlend", "warnung", f"{f.id} ({f.text}) hat keine Größenangabe", merkmal=f.id)
        achse = np.asarray(f.werte.get("achse"), dtype=float)
        for i in range(3):
            if abs(float(achse[i])) > 0.5:
                continue
            c = float(np.asarray(f.signatur["mitte"])[i]) if f.art != "langloch" else None
            if c is None:
                continue
            if not graphen[i].verbunden(0.0, c) and not (abs(c - g[i] / 2) < TOL and i in symmetrie_achsen):
                befund("fehlend", "hinweis", f"Lage von {f.id} entlang {'xyz'[i]} ({zahl(c)} ab Bezug) ist nicht "
                                             "bemaßt", merkmal=f.id)
    return befunde

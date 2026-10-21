"""Automatische Bemaßung nach ISO 129-1 aus den Merkmalen eines Teils.

Ergebnis sind Maße im Format des Blatts (DOKUMENTE.md, ``masse``) mit ``quelle: "auto"`` und einem stabilen
``schluessel``, über den Kev CAD sie bei jedem Lauf wiedererkennt (Lage, die Kevin gesetzt hat, bleibt; gelöschte
automatische Maße stehen in ``auto.unterdrueckt`` und kommen nicht wieder).

Regeln (begründet):

1. **Ansichten so wenige wie möglich** (ISO 128-30): Vorderansicht immer; Draufsicht bzw. Seitenansicht nur, wenn ein
   Merkmal erst dort als wahre Gestalt erscheint (Bohrung mit Achse in z bzw. x, Tasche mit Boden in dieser Richtung)
   oder wenn die dritte Hüllabmessung sonst fehlte. Platten bekommen statt einer Seitenansicht die Angabe der Dicke,
   Stangenware statt einer Profilansicht das Halbzeug im Schriftfeld (beides Norm-Praxis).
2. **Jedes Maß einmal** und dort, wo das Merkmal als wahre Gestalt erscheint: Bohrungen mit Ø und Lage in der Ansicht,
   in der sie als Kreis erscheinen; Tiefen in der Bohrungsangabe; Taschen mit Umriss in der Draufsicht auf den Boden
   und Tiefe in einer Ansicht, in der der Boden als Kante erscheint.
3. **Funktionsbezug:** Lagen von einer Bezugskante je Ansicht (links und unten im Blatt, bei Stangen das Ende A);
   liegen alle Lagen auf einer Achse symmetrisch zur Mitte, wird symmetrisch von Merkmal zu Merkmal bemaßt
   (Mittellinie als Bezug); ab vier Lagen auf einer Achse steigende Bemaßung statt einer Treppe aus Parallelmaßen.
4. **Lochbilder zusammenfassen:** eine Angabe „n× Ø d“ an einem Loch, Reihen und Raster mit erster Lage und Teilung
   „(n−1) × t (= L)“, Teilkreise mit Mittelpunkt und „auf TK Ø D“.
5. **Ø, R, Fase, Gewinde normgerecht:** „Ø6,6“, „R3“, „0,5 × 45°“, „M6 × 12“ (ISO 6410), Senkungen ausgeschrieben.
6. **Hüllmaße außen** (größte Maße am weitesten weg vom Körper, damit sich Maß- und Hilfslinien nicht kreuzen).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.ansichten import Blick, blick
from kevcad_kernel.zeichnung.bezuege import aus_merkmal
from kevcad_kernel.zeichnung.merkmale import Merkmal, Merkmale, zahl

TOL = 0.01


def _achse(v: np.ndarray) -> tuple[int, int] | None:
    """Lokale Achse (Index, Vorzeichen) zu einem Vektor, falls achsparallel."""
    v = np.asarray(v, dtype=float)
    i = int(np.argmax(np.abs(v)))
    if abs(v[i]) < 1 - 1e-6:
        return None
    return i, (1 if v[i] > 0 else -1)


def _parallel(a: Any, b: Any) -> bool:
    return abs(float(np.dot(np.asarray(a, dtype=float), np.asarray(b, dtype=float)))) > 1 - 1e-6


def _senkrecht(a: Any, b: Any) -> bool:
    return abs(float(np.dot(np.asarray(a, dtype=float), np.asarray(b, dtype=float)))) < 1e-6


# ---------------------------------------------------------------------------------------------------------------------
# Ansichten planen
# ---------------------------------------------------------------------------------------------------------------------


def ansichten_planen(merk: Merkmale, art: str = "teil") -> list[dict[str, Any]]:
    """Ansichten eines Einzelteils (Regel 1). Baugruppen und Zusammenbau: Vorderansicht, Draufsicht, Isometrie."""
    if art != "teil":
        return [{"id": "v1", "art": "vorn", "lage": None, "massstab": None, "verdeckt": False, "mittellinien": False},
                {"id": "v2", "art": "oben", "lage": None, "massstab": None, "verdeckt": False, "mittellinien": False},
                {"id": "v3", "art": "iso", "lage": None, "massstab": None, "verdeckt": False, "mittellinien": False}]
    sysart = merk.system.art
    achsen_bohr = []
    for m in merk.von_art("bohrung", "einsatztasche", "muttertasche", "langloch"):
        a = _achse(np.asarray(m.werte.get("achse") if m.art != "muttertasche" else m.werte.get("achse"), dtype=float))
        if a is not None:
            achsen_bohr.append(a[0])
    boden = [int(m.werte["achse"]) for m in merk.von_art("tasche")]
    braucht_oben = 2 in achsen_bohr or 2 in boden
    braucht_seite = 0 in achsen_bohr or 0 in boden
    views = [{"id": "v1", "art": "vorn", "lage": None, "massstab": None, "verdeckt": True, "mittellinien": True}]
    if sysart == "stange":
        # Profil nur, wenn es nicht rund ist oder Merkmale quer dazu liegen
        lager_art = str(merk.info.get("lager_art") or "")
        if braucht_oben:
            views.append({"id": "v2", "art": "oben", "lage": None, "massstab": None, "verdeckt": True,
                          "mittellinien": True})
        if braucht_seite or lager_art not in ("rohr", "rund", ""):
            views.append({"id": f"v{len(views) + 1}", "art": "links", "lage": None, "massstab": None,
                          "verdeckt": True, "mittellinien": True})
        return views
    if sysart == "platte":
        if braucht_oben:
            views.append({"id": "v2", "art": "oben", "lage": None, "massstab": None, "verdeckt": True,
                          "mittellinien": True})
        if braucht_seite:
            views.append({"id": f"v{len(views) + 1}", "art": "links", "lage": None, "massstab": None,
                          "verdeckt": True, "mittellinien": True})
        return views
    # allgemein: dritte Abmessung braucht eine zweite Ansicht
    if not braucht_oben and not braucht_seite:
        braucht_oben = True
    if braucht_oben:
        views.append({"id": "v2", "art": "oben", "lage": None, "massstab": None, "verdeckt": True,
                      "mittellinien": True})
    if braucht_seite:
        views.append({"id": f"v{len(views) + 1}", "art": "links", "lage": None, "massstab": None, "verdeckt": True,
                      "mittellinien": True})
    views.append({"id": f"v{len(views) + 1}", "art": "iso", "lage": None, "massstab": None, "verdeckt": False,
                  "mittellinien": False, "optional": True})
    return views


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen für Bezüge
# ---------------------------------------------------------------------------------------------------------------------


class _Kontext:
    def __init__(self, merk: Merkmale, teil: str, ansichten: list[dict[str, Any]]) -> None:
        self.merk = merk
        self.teil = teil
        self.ansichten = [a for a in ansichten if a.get("art") not in ("iso", "iso_vorn_links", "iso_hinten_rechts",
                                                                       "iso_hinten_links", "einzelheit")]
        self.blicke = {a["id"]: blick(a["art"] if a.get("art") != "schnitt" else _schnitt_blick(a, ansichten))
                       for a in self.ansichten}
        self.masse: list[dict[str, Any]] = []
        self.allgemein: list[str] = []
        self.symmetrien: list[tuple[str, str]] = []  # (Ansicht, Linie entlang x oder y)
        self.g = merk.groesse

    def bezug(self, mid: str, element: str | None = None) -> dict[str, Any]:
        m = self.merk.get(mid)
        assert m is not None, mid
        b = aus_merkmal(self.teil, m)
        if element:
            b["element"] = element
        return b

    def seite(self, i: int, s: int) -> dict[str, Any]:
        return self.bezug(f"seite:{'xyz'[i]}{'-' if s < 0 else '+'}")

    def mass(self, schluessel: str, art: str, ansicht: str, bezuege: list[dict[str, Any]], richtung: str | None,
             prio: int, text: str | None = None, seite: str | None = None, **extra: Any) -> None:
        if any(m["schluessel"] == schluessel for m in self.masse):
            return
        eintrag = {"id": None, "art": art, "ansicht": ansicht, "bezuege": bezuege, "richtung": richtung,
                   "versatz": None, "text": text, "toleranz": None, "quelle": "auto", "fest": False,
                   "verwaist": False, "schluessel": schluessel, "_prio": prio}
        if seite:
            eintrag["seite"] = seite
        eintrag.update(extra)
        self.masse.append(eintrag)

    def symmetrie(self, vid: str, richtung: str) -> None:
        """Symmetrielinie der Ansicht senkrecht zu ``richtung`` (Lagen sind symmetrisch zur Mitte bemaßt)."""
        if self.merk.system.art == "stange":
            return  # die Stangenachse ist schon Mittellinie
        eintrag = (vid, "y" if richtung == "x" else "x")
        if eintrag not in self.symmetrien:
            self.symmetrien.append(eintrag)

    def ansicht_mit_kreis(self, achse: np.ndarray) -> str | None:
        """Ansicht, in der eine Achse als Punkt erscheint (Bohrung als Kreis)."""
        for a in self.ansichten:
            if _parallel(self.blicke[a["id"]].d, achse):
                return a["id"]
        return None

    def ansicht_seitlich(self, achse: np.ndarray) -> str | None:
        for a in self.ansichten:
            if _senkrecht(self.blicke[a["id"]].d, achse):
                return a["id"]
        return None

    def blattachsen(self, vid: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        b = self.blicke[vid]
        return _achse(np.asarray(b.rechts)), _achse(np.asarray(b.oben))


def _schnitt_blick(a: dict[str, Any], alle: list[dict[str, Any]]) -> str:
    return str((a.get("schnitt") or {}).get("blick") or "vorn")


# ---------------------------------------------------------------------------------------------------------------------
# Automatische Maße
# ---------------------------------------------------------------------------------------------------------------------


def auto_masse(merk: Merkmale, teil: str, ansichten: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Automatische Maße und allgemeine Angaben eines Einzelteils (Modulbeschreibung). Symmetrielinien stehen danach
    in ``ansichten[i]["_symmetrie"]`` (Liste aus "x"/"y": Linie entlang Blatt-x bzw. -y durch die Mitte)."""
    k = _Kontext(merk, teil, ansichten)
    if not k.ansichten:
        return [], []
    _huellmasse(k)
    _stange(k)
    _bohrungen(k)
    _taschen(k)
    _fasen_radien(k)
    for a in ansichten:
        a["_symmetrie"] = [r for vid, r in k.symmetrien if vid == a.get("id")]
    # jedes Maß einmal: Maße weglassen, die einen Kreis im Bemaßungsgraphen schließen (RECHERCHE-PHASE6.md 2.5)
    from kevcad_kernel.zeichnung.pruefung import ohne_ueberbemassung

    sym: set[int] = set()
    if merk.system.art == "stange":
        sym |= {1, 2}
    for vid, r in k.symmetrien:
        b = k.blicke.get(vid)
        if b is not None:
            v = np.asarray(b.oben if r == "x" else b.rechts, dtype=float)
            sym.add(int(np.argmax(np.abs(v))))
    for m in k.masse:  # Messrichtung für die Prüfung
        m.setdefault("_richtung", m.get("richtung"))
    return ohne_ueberbemassung(k.masse, merk, k.blicke, sym), k.allgemein


def _huellmasse(k: _Kontext) -> None:
    """Gesamtmaße: jede Achse einmal, in der ersten Ansicht, in der sie in der Blattebene liegt (Regel 6: außen)."""
    sysart = k.merk.system.art
    erledigt: set[int] = set()
    for a in k.ansichten:
        if a.get("art") == "schnitt":
            continue
        vid = a["id"]
        ax, ay = k.blattachsen(vid)
        for achse, richtung in ((ax, "x"), (ay, "y")):
            if achse is None or achse[0] in erledigt:
                continue
            i = achse[0]
            if sysart == "stange" and i != 0:
                continue  # Profil: Halbzeug im Schriftfeld
            if sysart == "platte" and i == 1:
                continue  # Dicke als Angabe
            erledigt.add(i)
            seite = "unten" if richtung == "x" else "rechts"
            k.mass(f"huelle:{'xyz'[i]}", "linear", vid, [k.seite(i, -1), k.seite(i, 1)], richtung, 100, seite=seite)
    if sysart == "platte":
        k.allgemein.append(f"t = {zahl(k.g[1])} (Plattendicke)")
    if sysart == "stange":
        st = k.merk.get("stange")
        if st is not None and st.werte.get("profil"):
            k.allgemein.append(f"Halbzeug: {st.werte['profil']}")
    info = k.merk.info or {}
    if info.get("druckteil"):
        k.allgemein.append("Nicht bemaßte Maße nach 3D-Modell")
    elif sysart in ("stange", "platte") and info.get("lager_art") != "holz":
        k.allgemein.append("Werkstückkanten ISO 13715 −0,3 (entgratet)")


def _stange(k: _Kontext) -> None:
    st = k.merk.get("stange")
    if st is None:
        return
    geh = st.werte.get("gehrung") or [0, 0]
    for ende, w in zip(("a", "b"), geh):
        if abs(float(w)) > 0.05 and k.merk.get(f"ende:{ende}") is not None:
            vid = k.ansichten[0]["id"]
            k.mass(f"gehrung:{ende}", "winkel", vid, [k.bezug("stange"), k.bezug(f"ende:{ende}")], "frei", 60)


def _punkte_je_achse(k: _Kontext, vid: str, merkmale: list[Merkmal]) -> None:
    """Lagen der Merkmale in einer Ansicht entlang Blatt-x und Blatt-y (Regeln 3 und 4)."""
    ax, ay = k.blattachsen(vid)
    stange = k.merk.system.art == "stange"
    for achse, richtung in ((ax, "x"), (ay, "y")):
        if achse is None:
            continue
        i, s = achse
        W = float(k.g[i])
        # Bezugskante: links bzw. unten im Blatt → lokale Seite mit Vorzeichen −s
        datum = (i, -s)
        werte: list[tuple[float, str, Merkmal, str | None]] = []  # (Lage ab Bezug, Schlüsselteil, Merkmal, Element)
        teilungen: list[tuple[Merkmal, list[str], float]] = []
        for m in merkmale:
            if m.art == "lochbild":
                continue
            p = np.asarray(m.signatur["mitte"], dtype=float)
            v = float(p[i]) if s > 0 else W - float(p[i])
            werte.append((v, m.id, m, None))
        # Lochbilder: Reihe und Raster entlang dieser Achse auf erste Lage + Teilung zurückführen
        for lb in k.merk.von_art("lochbild"):
            ids = list(lb.teile)
            if not ids or not any(w[1] in ids for w in werte):
                continue
            mitglieder = [w for w in werte if w[1] in ids]
            vals = sorted({round(w[0], 3) for w in mitglieder})
            if len(vals) >= 3:
                diffs = np.diff(vals)
                if np.all(np.abs(diffs - diffs.mean()) < 0.02):
                    erst = min(mitglieder, key=lambda w: w[0])
                    letzt = max(mitglieder, key=lambda w: w[0])
                    werte = [w for w in werte if w[1] not in ids] + [erst]
                    teilungen.append((lb, [erst[1], letzt[1]], float(diffs.mean())))
                    continue
            if lb.werte.get("muster") == "kreis":
                werte = [w for w in werte if w[1] not in ids]
                p = np.asarray(lb.signatur["mitte"], dtype=float)
                werte.append((float(p[i]) if s > 0 else W - float(p[i]), lb.id, lb, None))
        # gleiche Lagen zusammenfassen
        einzig: list[tuple[float, str, Merkmal, str | None]] = []
        for w in sorted(werte, key=lambda t: t[0]):
            if not einzig or abs(w[0] - einzig[-1][0]) > TOL:
                einzig.append(w)
        einzig = [w for w in einzig if w[0] > TOL and w[0] < W - TOL or (stange and w[0] > TOL)]
        if not einzig and not teilungen:
            continue
        mitte_ok = all(abs(w[0] - W / 2) < TOL for w in einzig)
        quer = stange and i != 0  # Stangenware quer zur Achse: Lage zur Stangenachse
        platte = k.merk.system.art == "platte"  # Zuschnitt: alle Lagen ab der Ecke unten links, keine Symmetrie
        symmetrisch = (not stange or quer) and not platte and _symmetrisch([w[0] for w in einzig], W)
        if mitte_ok and (not stange or quer) and not platte and not teilungen:
            k.symmetrie(vid, richtung)
            continue  # alles auf der Mittellinie: Lage durch die Symmetrie bestimmt
        if symmetrisch and not teilungen:
            k.symmetrie(vid, richtung)
            paare = _paare(einzig, W)
            for a, b in paare:
                k.mass(f"sym:{a[1]}:{b[1]}:{richtung}", "linear", vid, [k.bezug(a[1]), k.bezug(b[1])], richtung, 20,
                       seite="oben" if richtung == "x" else "links")
            continue
        db = k.seite(datum[0], datum[1])
        seite = ("oben" if richtung == "x" else "links")
        if len(einzig) >= (3 if platte else 4):  # Zuschnitt: steigende Bemaßung ab drei Lagen
            k.mass(f"kette:{vid}:{richtung}", "bezugskette", vid, [db] + [k.bezug(w[1]) for w in einzig], richtung,
                   30, seite=seite)
        else:
            for n, w in enumerate(einzig):
                k.mass(f"lage:{w[1]}:{richtung}", "linear", vid, [db, k.bezug(w[1])], richtung, 20 + n, seite=seite)
        for lb, (a, b), t in teilungen:
            n = len(lb.teile)
            reihe = [w for w in werte if w[1] in lb.teile]
            n_achse = len({round(float(np.asarray(k.merk.get(x).signatur["mitte"])[i]), 3) for x in lb.teile})
            text = f"{n_achse - 1} × {zahl(t)} (= {zahl(t * (n_achse - 1))})"
            k.mass(f"teilung:{lb.id}:{richtung}", "linear", vid, [k.bezug(a), k.bezug(b)], richtung, 25, text=text,
                   seite=seite)
            _ = n, reihe


def _symmetrisch(vals: list[float], W: float) -> bool:
    if not vals:
        return False
    rest = list(vals)
    while rest:
        v = rest.pop(0)
        if abs(v - W / 2) < TOL:
            continue
        gegen = next((x for x in rest if abs(x - (W - v)) < TOL), None)
        if gegen is None:
            return False
        rest.remove(gegen)
    return True


def _paare(werte: list[tuple[float, str, Merkmal, str | None]], W: float) -> list[tuple[Any, Any]]:
    out = []
    rest = [w for w in werte if abs(w[0] - W / 2) >= TOL]
    while rest:
        a = rest.pop(0)
        b = next((x for x in rest if abs(x[0] - (W - a[0])) < TOL), None)
        if b is None:
            continue
        rest.remove(b)
        out.append((a, b) if a[0] < b[0] else (b, a))
    return out


def _bohrungen(k: _Kontext) -> None:
    """Angaben und Lagen der Bohrungen, Einsatz- und Muttertaschen, Langlöcher (Regeln 2–5)."""
    bohr = k.merk.von_art("bohrung", "einsatztasche", "muttertasche", "langloch")
    if not bohr:
        return
    in_ansicht: dict[str, list[Merkmal]] = {}
    for m in bohr:
        a = np.asarray(m.werte.get("achse"), dtype=float)
        vid = k.ansicht_mit_kreis(a)
        if vid is None:
            vid = k.ansicht_seitlich(a)
        if vid is None:
            continue
        in_ansicht.setdefault(vid, []).append(m)
    lochbild_von = {mid: lb for lb in k.merk.von_art("lochbild") for mid in lb.teile}
    for vid, ms in in_ansicht.items():
        angegeben: set[str] = set()
        for m in ms:
            lb = lochbild_von.get(m.id)
            if lb is not None:
                if lb.id in angegeben:
                    continue
                angegeben.add(lb.id)
                text = lb.text
                if lb.werte.get("muster") == "kreis":
                    text += f" auf TK Ø{zahl(lb.werte['tk_d'])}"
                k.mass(f"angabe:{lb.id}", "bohrung", vid, [k.bezug(lb.teile[0])], None, 10, text=text)
            else:
                k.mass(f"angabe:{m.id}", "bohrung" if m.art != "langloch" else "merkmal", vid, [k.bezug(m.id)], None,
                       10, text=m.text)
        _punkte_je_achse(k, vid, ms + [lb for lb in k.merk.von_art("lochbild")
                                       if any(t in [x.id for x in ms] for t in lb.teile)])


def _taschen(k: _Kontext) -> None:
    """Taschen: Tiefe, Umriss, Lage. Absätze: Höhe ab der Gegenseite, aber jede Höhe nur einmal (Regel 2: jedes Maß
    einmal; zwei Stufen auf gleicher Höhe oder symmetrisch gleich weit von beiden Seiten brauchen nur ein Maß) und nur
    für Absätze, deren Boden mindestens 2 % der Seitenfläche ausmacht (kleinere Stufen regelt die Angabe „nach
    3D-Modell“ bzw. die Allgemeintoleranz)."""
    belegt: set[tuple[str, str, float]] = set()
    for m in k.merk.von_art("tasche", "absatz"):
        i = int(m.werte["achse"])
        s = int(m.werte["seite"])
        n = np.zeros(3)
        n[i] = 1.0
        if m.art == "absatz":
            a, b = [j for j in range(3) if j != i]
            ausd = m.werte.get("ausdehnung") or [0, 0]
            if float(ausd[0]) * float(ausd[1]) < 0.02 * float(k.g[a]) * float(k.g[b]):
                continue
        # Tiefe bzw. Höhe in einer Ansicht, in der der Boden als Kante erscheint
        vid = k.ansicht_seitlich(n)
        if vid is not None:
            richtung = _richtung_fuer(k, vid, i)
            wert = float(m.werte.get("tiefe") if m.art == "tasche" else m.werte.get("hoehe") or 0.0)
            schluessel = (vid, richtung, round(wert, 1))
            if schluessel in belegt or any(abs(wert - w) < 0.3 and (v, r) == (vid, richtung) for v, r, w in belegt):
                continue
            belegt.add(schluessel)
            if m.art == "tasche":
                k.mass(f"tiefe:{m.id}", "linear", vid, [k.seite(i, s), k.bezug(m.id)], richtung, 40)
            else:
                k.mass(f"hoehe:{m.id}", "linear", vid, [k.seite(i, -s), k.bezug(m.id)], richtung, 40)
        if m.art != "tasche":
            continue
        # Umriss und Lage in der Ansicht auf den Boden
        vid = k.ansicht_mit_kreis(n)
        if vid is None:
            continue
        ax, ay = k.blattachsen(vid)
        for achse, richtung in ((ax, "x"), (ay, "y")):
            if achse is None:
                continue
            j = achse[0]
            if j == i:
                continue
            k.mass(f"breite:{m.id}:{richtung}", "linear", vid,
                   [k.bezug(m.id, f"lo{j}"), k.bezug(m.id, f"hi{j}")], richtung, 35)
            lo = float(np.asarray(m.werte["lo"])[j])
            W = float(k.g[j])
            hi = float(np.asarray(m.werte["hi"])[j])
            if abs(lo - (W - hi)) < TOL:
                continue  # mittig
            sx = achse[1]
            k.mass(f"lage:{m.id}:{richtung}", "linear", vid,
                   [k.seite(j, -sx), k.bezug(m.id, f"lo{j}" if sx > 0 else f"hi{j}")], richtung, 22)


def _richtung_fuer(k: _Kontext, vid: str, i: int) -> str:
    ax, ay = k.blattachsen(vid)
    return "x" if ax is not None and ax[0] == i else "y"


def _fasen_radien(k: _Kontext) -> None:
    for m in k.merk.von_art("fase"):
        n = np.asarray(m.signatur.get("richtung"), dtype=float)
        # Ansicht, in der die Fase als Linie erscheint: Blick entlang der Kante (senkrecht zur Normale, achsparallel)
        vid = None
        for a in k.ansichten:
            d = k.blicke[a["id"]].d
            if _senkrecht(d, n) and _achse(d) is not None:
                vid = a["id"]
                break
        if vid is None:
            k.allgemein.append(f"Fasen {m.werte['text_einzel']}" + (f" ({m.werte['n']}×)" if m.werte["n"] > 1 else ""))
            continue
        text = (f"{m.werte['n']}× " if m.werte["n"] > 1 else "") + m.werte["text_einzel"]
        k.mass(f"angabe:{m.id}", "fase", vid, [k.bezug(m.id)], None, 12, text=text)
    for m in k.merk.von_art("radius"):
        achsen = m.werte.get("achsen") or []
        if not achsen:
            continue
        vid = k.ansicht_mit_kreis(np.asarray(achsen[0], dtype=float))
        if vid is None:
            if m.werte["n"] >= 2:
                k.allgemein.append(f"Nicht bemaßte Radien R{zahl(m.werte['r'])}")
            continue
        k.mass(f"angabe:{m.id}", "radius", vid, [k.bezug(m.id)], None, 12, text=m.text)


# ---------------------------------------------------------------------------------------------------------------------
# Baugruppen und Zusammenbau
# ---------------------------------------------------------------------------------------------------------------------


def auto_masse_gruppe(merk: Merkmale, teil: str, ansichten: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hauptmaße (Länge, Breite, Höhe) einer Baugruppe in Vorderansicht und Draufsicht."""
    k = _Kontext(merk, teil, ansichten)
    _huellmasse(k)
    return k.masse


def blick_von(ansicht: dict[str, Any]) -> Blick:
    return blick(ansicht.get("art") if ansicht.get("art") not in ("schnitt", "einzelheit") else "vorn")

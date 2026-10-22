"""Montagefolge für den Bauplan: Montage durch Demontage.

Eigene, bewusst getrennte Funktion, bis die Einbaubarkeit der Prüfung (Strang „Prüfung Stufe 2“,
``pruefung/montage.py``) auf main ist; dann wird ``plane`` auf deren Ergebnis umgestellt. Schnittstelle:

    plane(eingang, wegpruefer) -> Folge
        Folge.haupt: [Einbau]                  Hauptmontage in Einbaureihenfolge
        Folge.vormontagen: {Baugruppe: [Einbau]}  Unterbaugruppen, vor der Hauptmontage
        Folge.befunde: [Befund]                nicht einbaubar, eingesperrt

    Einbau.einheit (Name, Teile, Art), Einbau.richtung (Einführrichtung oder None beim Grundteil),
    Einbau.erzwungen / Einbau.sperrer (Teil steckt fest, trotzdem eingeplant)

Ablauf je Ebene (Hauptmontage oder eine Unterbaugruppe):

1. Einheiten: ein Teil mit seinen eingeschmolzenen Einsätzen und eingeklebten Stiften; vorhandene Einheiten
   (Zukauf) als Ganzes; jedes Verbindungsmittel einzeln; Unterbaugruppen aus dem Namensbaum („Kugelschieber/…“) als
   eine Einheit, wenn sie mindestens zwei Teile haben und keine Einheit über ihre Grenze reicht. Verbindungsmittel,
   die eine Unterbaugruppe mit Teilen außerhalb verbinden, gehören zur Ebene darüber.
2. Grundteil: in der Hauptmontage das schwerste Teil am Boden, in einer Unterbaugruppe das größte.
3. Ausbau, bis nur das Grundteil übrig ist: zuerst die Teile, die am weitesten vom Grundteil entfernt sind (Abstand
   im Verbindungsgraphen), bei Gleichstand das höhere und kleinere; vor jedem Teil seine Verbindungsmittel. Ein Teil
   kommt heraus, wenn eine Richtung frei ist (wege.py: ±Z, ±X, ±Y, Zylinderachsen; Verbindungsmittel entlang ihrer
   Achse).
4. Steckt alles fest: erst Unterbaugruppen auflösen, dann das Teil mit den wenigsten Sperren erzwingen (Befund).
5. Umgekehrt ist das die Einbaureihenfolge mit Einführrichtung je Einheit.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.bauplan.eingang import Eingang, montage_wirt
from kevcad_kernel.bauplan.wege import WegPruefer, richtung_text

ACHSEN = [np.array(v, dtype=float) for v in ((0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, -1))]
ZEITLIMIT_S = 90.0


@dataclass
class Einheit:
    name: str
    teile: list[str]
    art: str  # "teil" | "zukauf" | "vm" | "gruppe" | "kauf"
    haupt: str  # Hauptteil (für Lage, Achsen, Text)
    gruppe: Any = None  # bei art "gruppe": der Knoten

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Einheit) and other.name == self.name


@dataclass
class Weg:
    """Ausbauweg: um ``s`` mm entlang ``d1``, dann (zweistufig) entlang ``d2`` ins Freie, sonst weiter entlang d1."""

    d1: np.ndarray
    s: float
    d2: np.ndarray | None = None
    boden: float = 0.0  # so viele mm müsste das Teil unter den Boden (Baugruppe aufbocken oder umdrehen)


@dataclass
class Einbau:
    einheit: Einheit
    richtung: np.ndarray | None  # Einführrichtung (letzter Abschnitt); None = Grundteil
    ebene: str | None  # Unterbaugruppe oder None (Hauptmontage)
    erzwungen: bool = False
    sperrer: list[str] = field(default_factory=list)
    nr: int = 0
    weg: float = 0.0  # Länge des letzten Abschnitts (mm)
    zuerst: np.ndarray | None = None  # zweistufig: erst in diese Richtung heranführen
    aufbocken: float = 0.0  # mm unter dem Boden (Hinweis „aufbocken oder umdrehen“)
    mit_vm: list[str] = field(default_factory=list)  # lose vormontierte Verbindungsmittel (Einheiten-Namen)

    @property
    def richtung_text(self) -> str:
        if self.richtung is None:
            return "Grundteil"
        if self.zuerst is not None:
            return f"{richtung_text(self.zuerst)} heranführen, dann {round(self.weg):d} mm {richtung_text(self.richtung)}"
        return richtung_text(self.richtung)


@dataclass
class Knoten:
    name: str  # "" = Hauptmontage
    einheiten: list[Einheit] = field(default_factory=list)
    kinder: list[Knoten] = field(default_factory=list)

    def alle_teile(self) -> list[str]:
        out = [t for e in self.einheiten for t in e.teile]
        for k in self.kinder:
            out += k.alle_teile()
        return out


@dataclass
class Folge:
    haupt: list[Einbau] = field(default_factory=list)
    vormontagen: dict[str, list[Einbau]] = field(default_factory=dict)
    befunde: list[dict[str, Any]] = field(default_factory=list)
    statistik: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------------------------
# Einheiten und Namensbaum


def einheiten(ein: Eingang) -> list[Einheit]:
    """Montage-Einheiten aus den Teilen des Aufbaus."""
    sammeln: dict[str, list[str]] = {}
    art: dict[str, str] = {}
    for t in ein.aufbau():
        if t.rolle == "zukauf" and t.einheit:
            key = t.einheit
            art[key] = "zukauf"
        else:
            key = montage_wirt(ein, t.name)
            w = ein.teile.get(key)
            if w is not None and w.rolle == "zukauf" and w.einheit:
                key = w.einheit
                art[key] = "zukauf"
            elif key == t.name:
                art.setdefault(key, "vm" if t.rolle == "vm" else ("kauf" if t.rolle == "kauf" else "teil"))
        sammeln.setdefault(key, []).append(t.name)
    out = []
    for key, teile in sammeln.items():
        if key in ein.teile and art.get(key) != "zukauf":
            h = key
        else:  # Zukauf: das größte Teil
            h = max(teile, key=lambda n: ein.teile[n].volumen)
        a = art.get(key, "teil")
        if a == "vm" and len(teile) > 1:
            a = "teil"
        out.append(Einheit(key, teile, a, h))
    return out


def _unter(name: str, prefix: str) -> bool:
    return prefix == "" or name.startswith(prefix + "/")


def baum(ein: Eingang, units: list[Einheit]) -> Knoten:
    """Namensbaum mit Unterbaugruppen (siehe Moduldoku)."""
    von: dict[str, Einheit] = {t: e for e in units for t in e.teile}
    praefixe: set[str] = set()
    for e in units:
        for t in e.teile:
            stuecke = t.split("/")
            for i in range(1, len(stuecke)):
                praefixe.add("/".join(stuecke[:i]))
    gueltig: dict[str, list[Einheit]] = {}
    for p in sorted(praefixe, key=lambda s: (s.count("/"), s)):
        drin: list[Einheit] = []
        ok = True
        for e in units:
            innen = [t for t in e.teile if _unter(t, p)]
            if not innen:
                continue
            if len(innen) != len(e.teile):
                ok = False
                break
            drin.append(e)
        if not ok:
            continue
        # Verbindungsmittel, die nach außen verbinden, gehören eine Ebene höher
        innen_teile = {t for e in drin for t in e.teile}
        kern = []
        for e in drin:
            if e.art == "vm":
                aussen = [n for t in e.teile for n in ein.nachbarn(t, kontakt=True) if n in von and n not in innen_teile]
                if aussen:
                    continue
            kern.append(e)
        if sum(1 for e in kern if e.art != "vm") >= 2 and len(kern) < len(units):
            gueltig[p] = kern
    wurzel = Knoten("")
    knoten: dict[str, Knoten] = {"": wurzel}
    zugeordnet: dict[str, str] = {e.name: "" for e in units}
    for p in sorted(gueltig, key=lambda s: (s.count("/"), s)):
        eltern = ""
        for q in knoten:
            if q and _unter(p, q) and q != p and len(q) > len(eltern):
                eltern = q
        # nur Einheiten, die bisher zur Elternebene gehören
        kern = [e for e in gueltig[p] if zugeordnet.get(e.name) == eltern]
        if sum(1 for e in kern if e.art != "vm") < 2:
            continue
        if len(kern) == sum(1 for e in units if zugeordnet.get(e.name) == eltern):
            continue  # ganze Elternebene: keine eigene Unterbaugruppe
        k = Knoten(p)
        knoten[p] = k
        knoten[eltern].kinder.append(k)
        for e in kern:
            zugeordnet[e.name] = p
    for e in units:
        knoten[zugeordnet[e.name]].einheiten.append(e)
    return wurzel


def montage_name(von: dict[str, Einheit], teil: str) -> str:
    e = von.get(teil)
    return e.name if e else teil


# ---------------------------------------------------------------------------------------------------------------------
# Planung


@dataclass
class _Ebene:
    knoten: Knoten
    items: list[Einheit]  # Einheiten und Unterbaugruppen (art "gruppe")


class Planer:
    def __init__(self, ein: Eingang, wp: WegPruefer, zeitlimit_s: float = ZEITLIMIT_S) -> None:
        self.ein = ein
        self.wp = wp
        self.t0 = time.perf_counter()
        self.zeitlimit = zeitlimit_s
        self.befunde: list[dict[str, Any]] = []
        self.boden = ein.boden_z()
        self.boden_ebene = self.boden
        self.abgebrochen = False

    # -- Richtungen ------------------------------------------------------------------------------------------------

    def richtungen(self, e: Einheit) -> list[np.ndarray]:
        """Ausbaurichtungen in Reihenfolge der Vorliebe."""
        if e.art == "vm":
            t = self.ein.teile[e.haupt]
            achse = t.vm.get("achse")
            if achse is not None:
                a = np.asarray(achse, dtype=float)
                kopf = t.vm.get("kopf")
                if kopf is not None:  # Schraube: Kopf voran heraus
                    k = np.asarray(kopf, dtype=float)
                    return [k, -k]
                # Mutter, Scheibe: weg vom geklemmten Teil zuerst (nach oben bevorzugt)
                return [a, -a] if a[2] >= 0 else [-a, a]
        out = list(ACHSEN)
        h = self.ein.teile.get(e.haupt)
        if h is not None:
            for ax in h.koerper.zylinder_achsen(limit=2):
                for s in (1.0, -1.0):
                    v = s * ax
                    if all(abs(float(np.dot(v, w))) < 0.999 or float(np.dot(v, w)) < 0 for w in out):
                        out.insert(len(out) - 1, v)
        return out

    def sperren(self, e: Einheit, d: np.ndarray, rest: set[str], weg: float | None = None,
                versatz: Any = None) -> set[str]:
        """Teile aus ``rest``, die die Einheit entlang d sperren (bis ins Freie oder um ``weg``, ab ``versatz``)."""
        out: set[str] = set()
        gegen = [n for n in rest if n not in e.teile]
        for t in e.teile:
            out |= set(self.wp.sperrer(t, d, gegen=gegen, weg=weg, versatz=versatz))
        return out

    def _boden(self, e: Einheit, w: Weg) -> float:
        """mm, die die Einheit auf ihrem Weg unter die Aufstandsfläche müsste (Boden oder Werkbank der Ebene)."""
        zmin = min(float(self.ein.teile[t].bmin[2]) for t in e.teile)
        zmax = max(float(self.ein.teile[t].bmax[2]) for t in e.teile)
        tief = zmin + min(0.0, float(w.d1[2])) * w.s
        if w.d2 is not None and float(w.d2[2]) < -0.1:
            tief -= zmax - zmin  # danach weiter nach unten: einmal die eigene Höhe
        return max(0.0, self.boden_ebene - tief - 0.5)

    def _flucht(self, e: Einheit, d: np.ndarray, gegen: list[str]) -> list[float]:
        """Mögliche Wege für den ersten Abschnitt: erst bis die berührten Teile frei sind, dann bis alles frei ist."""
        nah = {n for t in e.teile for n in self.nb(t)} & set(gegen)
        klein = self.wp.fluchtweg(e.teile, d, sorted(nah)) if nah else self.wp.fluchtweg(e.teile, d, [])
        gross = self.wp.fluchtweg(e.teile, d, gegen)
        return sorted({klein, gross})

    def frei(self, e: Einheit, rest: set[str], boden: bool = True) -> Weg | None:
        """Erster freier Ausbauweg: gerade bis ins Freie, sonst zweistufig (erst um den Fluchtweg, dann quer).
        Zuerst ohne Weg unter die Aufstandsfläche, dann mit (Hinweis aufbocken)."""
        gegen = [n for n in rest if n not in e.teile]
        kandidaten: list[Weg] = []
        for d in self.richtungen(e):
            if not self.sperren(e, d, rest):
                w = Weg(d, self._flucht(e, d, gegen)[0])
                w.boden = self._boden(e, w) if boden else 0.0
                if w.boden <= 0:
                    return w
                kandidaten.append(w)
        for d in self.richtungen(e):  # zweistufig (Mutter erst über das Stiftende, dann zur Seite)
            for s in self._flucht(e, d, gegen):
                if self.sperren(e, d, rest, weg=s):
                    continue
                gefunden = None
                for d2 in ACHSEN:
                    if abs(float(np.dot(d2, d))) > 0.99:
                        continue
                    if not self.sperren(e, d2, rest, versatz=d * s):
                        gefunden = Weg(d, s, d2)
                        gefunden.boden = self._boden(e, gefunden) if boden else 0.0
                        if gefunden.boden <= 0:
                            return gefunden
                        kandidaten.append(gefunden)
                        break
                if gefunden is not None:
                    break
        if kandidaten:
            return min(kandidaten, key=lambda w: w.boden)
        return None

    # -- Ebene -----------------------------------------------------------------------------------------------------

    def _abstaende(self, items: list[Einheit], basis: Einheit) -> tuple[dict[str, int], dict[str, set[str]]]:
        von = {t: i.name for i in items for t in i.teile}
        nachbar: dict[str, set[str]] = {i.name: set() for i in items}
        for i in items:
            for t in i.teile:
                for n in self.nb(t):
                    j = von.get(n)
                    if j and j != i.name:
                        nachbar[i.name].add(j)
                        nachbar[j].add(i.name)
        dist = {basis.name: 0}
        q = deque([basis.name])
        while q:
            x = q.popleft()
            for y in nachbar[x]:
                if y not in dist:
                    dist[y] = dist[x] + 1
                    q.append(y)
        weit = max(dist.values(), default=0) + 1
        return {i.name: dist.get(i.name, weit) for i in items}, nachbar

    def _vm_rang(self, e: Einheit) -> int:
        typ = str(self.ein.teile[e.haupt].vm.get("typ") or "")
        return 0 if typ in ("HexNut", "WingNut", "DomedCapNut") else 1 if typ == "PlainWasher" else 2

    def _haelt_noch(self, v: Einheit, offen: list[Einheit]) -> bool:
        """Eine Schraube (ein Stift) kommt erst heraus, wenn Mutter und Scheibe auf ihrer Achse ab sind."""
        if self._vm_rang(v) < 2:
            return False
        t = self.ein.teile[v.haupt]
        a, m = t.vm.get("achse"), t.vm.get("mitte")
        if a is None or m is None:
            return False
        a, m = np.asarray(a, float), np.asarray(m, float)
        for o in offen:
            if o is v or self._vm_rang(o) == 2:
                continue
            u = self.ein.teile[o.haupt]
            b, mu = u.vm.get("achse"), u.vm.get("mitte")
            if b is None or mu is None:
                continue
            off = np.asarray(mu, float) - m
            if abs(float(np.dot(a, np.asarray(b, float)))) > 0.99 and \
                    float(np.linalg.norm(off - a * float(np.dot(off, a)))) < 1.0:
                return True
        return False

    def nb(self, teil: str) -> set[str]:
        """Nachbarn eines Teils; bei Verbindungsmitteln immer auch die geometrischen Kontakte (Scheibe am Stift)."""
        t = self.ein.teile.get(teil)
        return self.ein.nachbarn(teil, kontakt=True if t is not None and t.rolle == "vm" else None)

    def _basis(self, items: list[Einheit], haupt: bool, nachbar: dict[str, set[str]] | None = None) -> Einheit:
        kern = [i for i in items if i.art != "vm"] or items

        def masse(i: Einheit) -> float:
            return sum(self.ein.teile[t].masse_g for t in i.teile)

        def groesse(i: Einheit) -> float:
            lo = np.min([self.ein.teile[t].bmin for t in i.teile], axis=0)
            hi = np.max([self.ein.teile[t].bmax for t in i.teile], axis=0)
            return float(np.linalg.norm(hi - lo))

        if haupt:
            am_boden = [i for i in kern if min(float(self.ein.teile[t].bmin[2]) for t in i.teile) <= self.boden + 0.5]
            if am_boden:  # das Teil am Boden, an dem am meisten hängt (nicht der lose Ball daneben)
                return max(am_boden, key=lambda i: (len((nachbar or {}).get(i.name, ())), masse(i)))
        return max(kern, key=lambda i: (groesse(i), masse(i)))

    def _lage(self, i: Einheit) -> tuple[float, float]:
        zs = [float(self.ein.teile[t].bmax[2]) for t in i.teile]
        vol = sum(self.ein.teile[t].volumen for t in i.teile)
        return max(zs), vol

    def plane_ebene(self, knoten: Knoten, haupt: bool) -> tuple[list[Einbau], dict[str, list[Einbau]]]:
        """Einbaureihenfolge einer Ebene; Unterbaugruppen werden vorher selbst geplant."""
        vormontagen: dict[str, list[Einbau]] = {}
        items: list[Einheit] = list(knoten.einheiten)
        for k in knoten.kinder:
            seq, vm = self.plane_ebene(k, False)
            vormontagen.update(vm)
            vormontagen[k.name] = seq
            items.append(Einheit(k.name, k.alle_teile(), "gruppe", seq[0].einheit.haupt if seq else k.alle_teile()[0],
                                 gruppe=k))
        ebene = knoten.name or None
        teile_z = [float(self.ein.teile[t].bmin[2]) for i in items for t in i.teile]
        while True:
            self.boden_ebene = self.boden if haupt else (min(teile_z) if teile_z else self.boden)
            ausbau, aufgeloest = self._ausbau(items, haupt, ebene)
            if aufgeloest is None:
                break
            # Unterbaugruppe auflösen: ihre Einheiten kommen auf diese Ebene
            items = [i for i in items if i.name != aufgeloest.name]
            items += self._aufloesen(aufgeloest)
            for name in list(vormontagen):
                if name == aufgeloest.name or name.startswith(aufgeloest.name + "/"):
                    vormontagen.pop(name, None)
        einbau = list(reversed(ausbau))
        for e in einbau:
            e.ebene = ebene
        return einbau, vormontagen

    def _aufloesen(self, g: Einheit) -> list[Einheit]:
        out = list(g.gruppe.einheiten)
        for k in g.gruppe.kinder:
            out += self._aufloesen(Einheit(k.name, k.alle_teile(), "gruppe", k.alle_teile()[0], gruppe=k))
        return out

    def _ausbau(self, items: list[Einheit], haupt: bool, ebene: str | None) -> tuple[list[Einbau], Einheit | None]:
        """Ausbaureihenfolge (letzte = Grundteil). Zweiter Wert: aufzulösende Unterbaugruppe (dann neu planen)."""
        if not items:
            return [], None
        _, nachbar = self._abstaende(items, items[0])
        basis = self._basis(items, haupt, nachbar)
        dist, nachbar = self._abstaende(items, basis)
        rest_items: dict[str, Einheit] = {i.name: i for i in items}
        rest: set[str] = {t for i in items for t in i.teile}
        ausbau: list[Einbau] = []

        def entferne(i: Einheit, w: Weg, erzwungen: bool = False, sperrer: list[str] | None = None) -> None:
            ausbau.append(Einbau(i, -w.d1, ebene, erzwungen, sorted(sperrer or []), weg=w.s,
                                 zuerst=None if w.d2 is None else -w.d2, aufbocken=round(w.boden, 1)))
            rest_items.pop(i.name, None)
            rest.difference_update(i.teile)

        while len(rest_items) > 1 or (len(rest_items) == 1 and basis.name not in rest_items):
            if time.perf_counter() - self.t0 > self.zeitlimit:
                self.abgebrochen = True
                for i in sorted(rest_items.values(), key=lambda i: -self._lage(i)[0]):
                    if i.name != basis.name:
                        entferne(i, Weg(ACHSEN[0], 50.0), True, ["Zeitlimit"])
                break
            kandidaten = [i for i in rest_items.values() if i.name != basis.name and i.art != "vm"]
            kandidaten.sort(key=lambda i: (-dist.get(i.name, 0), -self._lage(i)[0], self._lage(i)[1], i.name))

            def haelt_zusammen(i: Einheit) -> bool:
                """Bleibt ohne i alles Übrige mit dem Grundteil verbunden? Im Einbau heißt das: jedes neue Teil hängt
                gleich an etwas Montiertem (kein Halter, der in der Luft schwebt, bis die Stange kommt)."""
                uebrig = {n for n in rest_items if n != i.name and rest_items[n].art != "vm"}
                if basis.name not in uebrig:
                    return True
                gesehen, stapel = {basis.name}, [basis.name]
                while stapel:
                    x = stapel.pop()
                    for y in nachbar.get(x, ()):
                        if y in uebrig and y not in gesehen:
                            gesehen.add(y)
                            stapel.append(y)
                        elif y in rest_items and rest_items[y].art == "vm" and y != i.name:
                            for z in nachbar.get(y, ()):  # über Verbindungsmittel hinweg
                                if z in uebrig and z not in gesehen:
                                    gesehen.add(z)
                                    stapel.append(z)
                return gesehen >= uebrig

            kandidaten.sort(key=lambda i: not haelt_zusammen(i))  # stabil: erst die, die nichts abtrennen
            erfolg = False
            for i in kandidaten:
                vms = [rest_items[j] for j in nachbar.get(i.name, ()) if j in rest_items and rest_items[j].art == "vm"]
                # alle Verbindungsmittel des Teils zuerst heraus (auch Muttern auf Muttern), dann das Teil
                probe_rest = set(rest)
                weg_vm: list[tuple[Einheit, Weg]] = []
                offen = list(vms)
                gesehen = {v.name for v in offen}
                k = 0
                while k < len(offen):  # Verbindungsmittel an Verbindungsmitteln (Scheibe unter der Mutter) mitnehmen
                    for j in nachbar.get(offen[k].name, ()):
                        if j in rest_items and rest_items[j].art == "vm" and j not in gesehen:
                            gesehen.add(j)
                            offen.append(rest_items[j])
                    k += 1
                offen.sort(key=self._vm_rang)
                geaendert = True
                while geaendert and offen:
                    geaendert = False
                    for v in list(offen):
                        if self._haelt_noch(v, offen):
                            continue
                        d = self.frei(v, probe_rest)
                        if d is not None:
                            weg_vm.append((v, d))
                            probe_rest.difference_update(v.teile)
                            offen.remove(v)
                            geaendert = True
                d = self.frei(i, probe_rest) if not offen else None
                if d is not None:
                    for v, dv in weg_vm:
                        entferne(v, dv)
                    entferne(i, d)
                    erfolg = True
                    break
                # Klemme: Verbindungsmittel, die nur dieses Teil halten (Flügelschraube und Scheibe der Klemmbacke),
                # wandern lose vormontiert mit; so schiebt man die Klemme mit loser Schraube auf die Stange
                eigene = [v for v in vms if all(j == i.name or (j in rest_items and rest_items[j].art == "vm")
                                                for j in nachbar.get(v.name, ()) if j in rest_items)]
                eigene_namen = {v.name for v in eigene}
                for v in list(eigene):  # dazu Scheiben und Muttern auf diesen Verbindungsmitteln
                    for j in nachbar.get(v.name, ()):
                        if j in rest_items and rest_items[j].art == "vm" and j not in eigene_namen:
                            eigene.append(rest_items[j])
                            eigene_namen.add(j)
                if not eigene:
                    continue
                mit = Einheit(i.name, list(i.teile) + [t for v in eigene for t in v.teile], i.art, i.haupt, i.gruppe)
                ohne_eigene = set(rest)
                d = self.frei(mit, ohne_eigene)
                if d is None:
                    continue
                entferne(mit, d)
                ausbau[-1].mit_vm = sorted(eigene_namen)
                for v in eigene:
                    rest_items.pop(v.name, None)
                erfolg = True
                break
            if erfolg:
                continue
            # übrige Verbindungsmittel, die frei sind
            for v in sorted((i for i in rest_items.values() if i.art == "vm"), key=lambda i: -self._lage(i)[0]):
                d = self.frei(v, rest)
                if d is not None:
                    entferne(v, d)
                    erfolg = True
                    break
            if erfolg:
                continue
            gruppen = [i for i in rest_items.values() if i.art == "gruppe"]
            if gruppen:
                return ausbau, max(gruppen, key=lambda g: len(g.teile))
            # erzwingen: wenigste Sperren
            bestes: tuple[int, Einheit, np.ndarray, set[str]] | None = None
            for i in rest_items.values():
                if i.name == basis.name:
                    continue
                for d in self.richtungen(i):
                    s = self.sperren(i, d, rest)
                    if bestes is None or len(s) < bestes[0]:
                        bestes = (len(s), i, d, s)
            if bestes is None:
                break
            _, i, d, s = bestes
            self._befund_fest(i, d, s, ebene)
            entferne(i, Weg(d, self.wp.fluchtweg(i.teile, d, [n for n in rest if n not in i.teile])), True, sorted(s))
        if basis.name in rest_items:
            ausbau.append(Einbau(basis, None, ebene))
        return ausbau, None

    def _befund_fest(self, i: Einheit, d: np.ndarray, sperrer: set[str], ebene: str | None) -> None:
        namen = sorted(sperrer)
        wo = f" (Unterbaugruppe {ebene})" if ebene else ""
        self.befunde.append({
            "art": "einfuehrweg", "teile": [i.haupt, *namen[:4]], "schwere": "fehler",
            "text": f"{i.name} lässt sich in keiner Richtung einbauen{wo}: am wenigsten sperrt "
                    f"{', '.join(namen[:4])}{' …' if len(namen) > 4 else ''} beim Einführen {richtung_text(-d)}.",
            "loesung": "Konstruktion ändern: Teil teilen, Spiel oder Einführschräge vorsehen, Bohrung oder Schlitz "
                       "für den Weg, oder das sperrende Teil später einbauen (Reihenfolge, verschraubt statt fest).",
            "ort": [round(float(c), 1) for c in self.ein.teile[i.haupt].zentrum]})


def plane(ein: Eingang, wp: WegPruefer, zeitlimit_s: float = ZEITLIMIT_S) -> Folge:
    t0 = time.perf_counter()
    units = einheiten(ein)
    wurzel = baum(ein, units)
    p = Planer(ein, wp, zeitlimit_s)
    haupt, vormontagen = p.plane_ebene(wurzel, True)
    for nr, e in enumerate(haupt, 1):
        e.nr = nr
    for seq in vormontagen.values():
        for nr, e in enumerate(seq, 1):
            e.nr = nr
    return Folge(haupt=haupt, vormontagen=vormontagen, befunde=p.befunde,
                 statistik={"einheiten": len(units), "unterbaugruppen": len(vormontagen),
                            "tests": wp.tests, "strahlen": wp.strahlen, "abgebrochen": p.abgebrochen,
                            "ms": round((time.perf_counter() - t0) * 1000, 1)})


def einbau_liste(folge: Folge) -> list[dict[str, Any]]:
    """Montagereihenfolge im Format von ``pruefung.montage.MontageErgebnis.einbau()`` (Strang Prüfung Stufe 2)."""
    out = []
    for nr, e in enumerate(folge.haupt, 1):
        out.append({"nr": nr, "teile": list(e.einheit.teile), "name": e.einheit.name,
                    "gruppe": e.einheit.art == "gruppe",
                    "richtung": None if e.richtung is None else [round(float(c), 4) for c in e.richtung],
                    "richtung_text": e.richtung_text})
    return out

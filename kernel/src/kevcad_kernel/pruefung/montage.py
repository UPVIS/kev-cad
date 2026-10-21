"""Einbaubarkeit: Montage durch Demontage.

Wiederholt werden Teile (oder erklärte Baugruppen) gesucht, die sich entlang einer Richtung kollisionsfrei aus dem Rest
herausziehen lassen (±X, ±Y, ±Z, Achsen der größten Zylinderflächen, Schraubenachsen, in model.py erklärte
Richtungen), bis alles zerlegt ist. Umgekehrt ist das die Montagereihenfolge mit Einführrichtung je Teil.

- Durchdringende Paare (eigener Befund), erlaubte Überlappungen und nachgiebige Teile behindern sich nicht.
- Schrauben dürfen nur entlang ihrer Achse heraus (Kopf voran), Muttern und Scheiben nur entlang der Achse.
- Steckt alles fest: erst eingesperrte Teile suchen (ein Teil sperrt es in jeder Richtung ein und umschließt es),
  dann Baugruppen nach dem Namensbaum („Rollwagen/Lenkrolle 1/…“), dann zusammenhängende Teile. Lässt sich eine
  Gruppe nur als Ganzes einbauen, ist das ein Befund (Zukaufteile als Baugruppe erklären). Was danach noch steckt, ist
  nicht einbaubar, mit den blockierenden Teilen je Richtung.
- Werkzeugzugang wird für jedes Verbindungselement zu dem Zeitpunkt geprüft, an dem es eingesetzt wird.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.pruefung.befund import BODEN_TOL, befund, einfuehr_text, richtung_text
from kevcad_kernel.pruefung.koerper import Koerper, basis, einheit, richtung_schluessel
from kevcad_kernel.pruefung.kollision import PaarCache, _rel_schluessel
from kevcad_kernel.pruefung.pruefer import Abgebrochen, PruefKontext, passt, registriere
from kevcad_kernel.pruefung.raster import blockiert

ACHSEN = [np.array(v, dtype=np.float64) for v in ((0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                                                  (0, 0, -1))]
ZEITLIMIT_S = 60.0


@dataclass
class Einheit:
    name: str
    teile: list[str]
    richtungen: list[np.ndarray]
    erklaert: bool = False  # Richtungen aus model.py
    gruppe: bool = False  # mehrere Teile als eine Einheit
    erklaerte_gruppe: bool = False
    verbindung: bool = False  # Schraube, Mutter, Scheibe


@dataclass
class Schritt:
    """Ein Ausbauschritt (umgekehrt: Einbau)."""

    einheit: Einheit
    richtung: np.ndarray  # Ausbaurichtung
    runde: int
    automatisch_gruppe: bool = False


@dataclass
class MontageErgebnis:
    schritte: list[Schritt] = field(default_factory=list)  # Ausbaureihenfolge
    offen: list[Einheit] = field(default_factory=list)  # stecken fest
    befunde: list[dict[str, Any]] = field(default_factory=list)
    sperren: dict[str, dict[str, str]] = field(default_factory=dict)  # Teil → Richtungstext → blockierendes Teil
    tests: int = 0
    abgebrochen: str | None = None

    def einbau(self) -> list[dict[str, Any]]:
        """Montagereihenfolge (Einbau) für Protokoll und Text."""
        out = []
        for nr, s in enumerate(reversed(self.schritte), 1):
            ein = -s.richtung
            erstes = nr == 1
            out.append({
                "nr": nr,
                "teile": list(s.einheit.teile),
                "name": s.einheit.name,
                "gruppe": s.einheit.gruppe,
                "richtung": None if erstes else [round(float(c), 4) for c in ein],
                "richtung_text": "Grundteil" if erstes else einfuehr_text(ein),
            })
        return out


class Planer:
    def __init__(self, koerper: dict[str, Koerper], *, ausschluss: set[frozenset[str]] | None = None,
                 nachgiebig: set[str] | None = None, erklaerungen: list[dict[str, Any]] | None = None,
                 kontakte: list[tuple[str, str]] | None = None, cache: PaarCache | None = None,
                 zeitlimit_s: float = ZEITLIMIT_S, abbrechen: Callable[[], None] | None = None,
                 boden: set[str] | None = None) -> None:
        self.k = koerper
        self.reihenfolge = list(koerper)
        self.ausschluss = ausschluss or set()
        self.nachgiebig = nachgiebig or set()
        self.erklaerungen = erklaerungen or []
        self.kontakte = kontakte or []
        self.cache = cache if cache is not None else PaarCache()
        self.ende = time.monotonic() + zeitlimit_s
        self.zeitlimit_s = zeitlimit_s
        self._abbrechen = abbrechen or (lambda: None)
        self.tests = 0
        self.nach: dict[str, set[str]] = {}  # Teil → Teile, die vorher eingebaut sein müssen
        self.befunde: list[dict[str, Any]] = []
        self._idx = {n: i for i, n in enumerate(self.reihenfolge)}
        self._dirs: dict[tuple, tuple] = {}
        self._rel: dict[tuple[str, str], tuple] = {}
        self.schnappt: dict[str, set[str]] = {}  # Teil → Teile, über die es beim Einbau schnappt
        # Boden für die Reihenfolge: Teile, die auf dem Boden stehen oder befestigt sind
        self.boden: set[str] = set(boden or ())
        if not self.boden and koerper:
            bz = min(float(k.bmin[2]) for k in koerper.values())
            self.boden = {n for n, k in koerper.items() if float(k.bmin[2]) <= bz + 0.5}
        self._nachbarn: dict[str, set[str]] = {}
        for a, b in self.kontakte:
            self._nachbarn.setdefault(a, set()).add(b)
            self._nachbarn.setdefault(b, set()).add(a)
        self._getragen0: set[str] = set()
        self._getragen0 = self._erreichbar(set(koerper))

    # -- Sperren ------------------------------------------------------------------------------------------------------

    def _pruefe_zeit(self) -> None:
        self._abbrechen()
        if time.monotonic() > self.ende:
            raise Abgebrochen(f"Zeitlimit von {self.zeitlimit_s:g} s erreicht")

    def sperrt(self, p: str, q: str, d: np.ndarray) -> bool:
        """Stößt p beim Herausziehen entlang d an q? (zwischengespeichert nach Form und relativer Lage)"""
        if frozenset((p, q)) in self.ausschluss or q in self.nachgiebig:
            return False
        if q in self.schnappt.get(p, ()):  # schnappt über q (montage(..., schnappt=True))
            return False
        kp, kq = self.k[p], self.k[q]
        # Vorfilter: q muss in der Bildebene überlappen und vor dem hintersten Punkt von p liegen
        umin, umax, wmin, wmax = self._richtung(d)
        i, j = self._idx[p], self._idx[q]
        if wmax[j] <= wmin[i] + 0.02:
            return False
        if np.any(np.minimum(umax[i], umax[j]) - np.maximum(umin[i], umin[j]) <= 0):
            return False
        rel = self._rel.get((p, q))
        if rel is None:
            rel = self._rel[(p, q)] = _rel_schluessel(kp.lage, kq.lage)
        d_lokal = d @ kp.lage[:3, :3]  # Richtung im System von p
        ck = ("sperre", kp.form, kq.form, rel, richtung_schluessel(d_lokal))
        hit = self.cache.get(ck)
        if hit is None:
            self._pruefe_zeit()
            self.tests += 1
            hit = bool(blockiert(kp, kq, d).blockiert)
            self.cache.put(ck, hit)
        return hit

    def _richtung(self, d: np.ndarray) -> tuple:
        """Hüllrechtecke und Tiefen aller Teile in Richtung d (zwischengespeichert)."""
        key = (round(float(d[0]), 9), round(float(d[1]), 9), round(float(d[2]), 9))
        hit = self._dirs.get(key)
        if hit is None:
            R = basis(d)
            key2 = richtung_schluessel(R[2])
            P = [self.k[n].projektion(R, key2) for n in self.reihenfolge]
            hit = (np.array([p.uv_min for p in P]).reshape(-1, 2), np.array([p.uv_max for p in P]).reshape(-1, 2),
                   np.array([p.w_min for p in P]), np.array([p.w_max for p in P]))
            self._dirs[key] = hit
        return hit

    def kandidaten(self, teile: list[str], rest: list[str], d: np.ndarray) -> list[str]:
        """Mögliche Hindernisse für die Teile entlang d, wahrscheinlichste zuerst (große Überdeckung)."""
        umin, umax, wmin, wmax = self._richtung(d)
        maske = np.zeros(len(self.reihenfolge), dtype=bool)
        maske[[self._idx[n] for n in rest]] = True
        best = np.zeros(len(self.reihenfolge))
        for p in teile:
            i = self._idx[p]
            ov = np.minimum(umax[i], umax) - np.maximum(umin[i], umin)
            ok = np.all(ov > 0, axis=1) & (wmax > wmin[i] + 0.02) & maske
            best = np.maximum(best, np.where(ok, ov[:, 0] * ov[:, 1], 0.0))
        order = np.argsort(-best, kind="stable")
        return [self.reihenfolge[j] for j in order if best[j] > 0]

    def frei(self, e: Einheit, rest: list[str]) -> tuple[np.ndarray | None, dict[str, str]]:
        """Erste freie Ausbaurichtung der Einheit gegen ``rest`` und je Richtung das erste Hindernis."""
        sperren: dict[str, str] = {}
        for d in e.richtungen:
            hindernis = None
            for q in self.kandidaten(e.teile, rest, d):
                if any(self.sperrt(p, q, d) for p in e.teile):
                    hindernis = q
                    break
            if hindernis is None:
                return d, sperren
            sperren[richtung_text(d)] = hindernis
        return None, sperren

    # -- Einheiten ----------------------------------------------------------------------------------------------------

    def richtungen_fuer(self, teile: list[str], erklaert: list[np.ndarray] | None = None) -> tuple[list[np.ndarray],
                                                                                                    bool]:
        if erklaert:
            return [einheit(-d) for d in erklaert], True  # erklärt ist die Einbaurichtung
        if len(teile) == 1:
            k = self.k[teile[0]]
            if k.ist_verbindungselement and k.info.get("achse") is not None:
                a = einheit(k.info["achse"])
                return ([a] if k.art == "schraube" else [a, -a]), False
        out: list[np.ndarray] = [ACHSEN[0]]
        groesster = max(teile, key=lambda n: self.k[n].volumen)
        for ax in self.k[groesster].zylinder_achsen():
            for s in (ax, -ax):
                if not any(float(np.dot(s, o)) > 0.996 for o in out + ACHSEN):
                    out.append(s)
        out += [a for a in ACHSEN[1:]]
        return out, False

    def einheiten(self) -> list[Einheit]:
        """Teile und erklärte Baugruppen; Richtungen und Reihenfolge aus den Erklärungen."""
        frei = list(self.reihenfolge)
        out: list[Einheit] = []
        spec: dict[str, dict[str, Any]] = {}
        for e in self.erklaerungen:
            teile = [n for n in self.reihenfolge if passt(n, e.get("teile") or [])]
            if not teile:
                continue
            richt = [np.asarray(r, dtype=np.float64) for r in (e.get("richtung") or [])]
            nach = [n for n in self.reihenfolge if passt(n, e.get("nach") or [])]
            if e.get("baugruppe"):
                gname = (e.get("teile") or ["Baugruppe"])[0].rstrip("/")
                mitglieder = [n for n in teile if n in frei]
                if not mitglieder:
                    continue
                for n in mitglieder:
                    frei.remove(n)
                r, erk = self.richtungen_fuer(mitglieder, richt or None)
                out.append(Einheit(gname, mitglieder, r, erklaert=erk, gruppe=True, erklaerte_gruppe=True))
                for n in mitglieder:
                    self.nach.setdefault(n, set()).update(nach)
                continue
            for n in teile:
                s = spec.setdefault(n, {"richtung": [], "nach": set()})
                s["richtung"] += richt
                s["nach"].update(nach)
                if e.get("schnappt"):  # Schnappverbindung: darf sich über die berührten Teile hinwegbiegen
                    for a, b in self.kontakte:
                        if n in (a, b):
                            q = b if a == n else a
                            self.schnappt.setdefault(n, set()).add(q)
                            self.schnappt.setdefault(q, set()).add(n)
        # beim Druck eingelegte Teile reisen mit dem Teil, das sie umschließt (größter Kontaktpartner)
        mit: dict[str, list[str]] = {}
        for e in self.erklaerungen:
            if not e.get("eingedruckt"):
                continue
            for n in [x for x in self.reihenfolge if passt(x, e.get("teile") or [])]:
                if n not in frei:
                    continue
                partner = [b if a == n else a for a, b in self.kontakte if n in (a, b)]
                partner = [q for q in partner if q in frei and q != n
                           and np.all(self.k[n].bmin >= self.k[q].bmin - 0.5)
                           and np.all(self.k[n].bmax <= self.k[q].bmax + 0.5)]
                if partner:
                    huelle = max(partner, key=lambda q: self.k[q].volumen)
                    mit.setdefault(huelle, []).append(n)
                    frei.remove(n)
        for n in frei:
            s = spec.get(n, {})
            teile = [n] + mit.get(n, [])
            r, erk = self.richtungen_fuer(teile, s.get("richtung") or None)
            name = n if len(teile) == 1 else f"{n} mit {', '.join(x.rsplit('/', 1)[-1] for x in teile[1:])}"
            out.append(Einheit(name, teile, r, erklaert=erk, gruppe=len(teile) > 1,
                               verbindung=len(teile) == 1 and self.k[n].ist_verbindungselement))
            for x in teile:
                self.nach.setdefault(x, set()).update(s.get("nach") or set())
        for n, vor in self.nach.items():
            vor.discard(n)
        return out

    def _reihenfolge_ok(self, e: Einheit, uebrig: set[str]) -> bool:
        """Ausbau: e darf erst heraus, wenn alle Teile, die nach e eingebaut werden, schon heraus sind."""
        for n in uebrig:
            if n in e.teile:
                continue
            if self.nach.get(n, set()) & set(e.teile):
                return False
        return True

    # -- Plan ---------------------------------------------------------------------------------------------------------

    def plane(self) -> MontageErgebnis:
        erg = MontageErgebnis()
        einheiten = self.einheiten()
        runde = 0
        try:
            while einheiten:
                runde += 1
                uebrig = {n for e in einheiten for n in e.teile}
                frei: list[tuple[Einheit, np.ndarray]] = []
                letzte_sperren: dict[str, dict[str, str]] = {}
                for e in sorted(einheiten, key=self._prio):
                    if not self._reihenfolge_ok(e, uebrig):
                        continue
                    rest = [n for n in self.reihenfolge if n in uebrig and n not in e.teile]
                    d, sp = self.frei(e, rest)
                    if d is not None:
                        frei.append((e, d))
                    else:
                        letzte_sperren[e.name] = sp
                auswahl = self._auswahl(frei, uebrig) if frei else []
                if auswahl:
                    for e, d in auswahl:
                        einheiten.remove(e)
                        erg.schritte.append(Schritt(e, d, runde))
                    continue
                # Was steckt, zusammenlegen (eingesperrte Teile, Vormontagen, Baugruppen); erst wenn das nichts bringt,
                # freie Teile auch dann herausnehmen, wenn der Rest dadurch nicht mehr getragen ist
                freie = {id(e) for e, _ in frei}
                stecken = [e for e in einheiten if id(e) not in freie]
                # gibt es freie Teile, nur Vormontagen aus zwei Teilen versuchen (sonst entstünden große Gruppen, nur
                # damit die Reihenfolge schöner wird); steckt alles, auch Baugruppen
                neu = (self._loesen(einheiten, stecken, letzte_sperren, erg, runde, nur_paare=bool(frei))
                       if stecken else None)
                if neu is not None:
                    einheiten = neu
                    continue
                if frei:
                    oben = [(e, d) for e, d in frei if d[2] > 0.999]
                    for e, d in (oben or frei):
                        einheiten.remove(e)
                        erg.schritte.append(Schritt(e, d, runde))
                    continue
                erg.offen = list(einheiten)
                erg.sperren = letzte_sperren
                break
        except Abgebrochen as exc:
            erg.abgebrochen = str(exc)
            erg.offen = list(einheiten)
        erg.tests = self.tests
        erg.befunde = self.befunde + self._offen_befunde(erg)
        return erg

    def _erreichbar(self, rest: set[str]) -> set[str]:
        start = [n for n in rest if n in self.boden]
        seen = set(start)
        while start:
            n = start.pop()
            for m in self._nachbarn.get(n, ()):
                if m in rest and m not in seen:
                    seen.add(m)
                    start.append(m)
        return seen

    def _getragen(self, rest: set[str]) -> bool:
        """Bleibt nach dem Ausbau alles getragen, was im fertigen Modell getragen ist (Kontaktweg zum Boden)?"""
        seen = self._erreichbar(rest)
        return all(n in seen for n in rest if n in self._getragen0)

    def _auswahl(self, frei: list[tuple[Einheit, np.ndarray]], uebrig: set[str]) -> list[tuple[Einheit, np.ndarray]]:
        """Welche freien Einheiten in dieser Runde herauskommen: bevorzugt nach oben (Einbau von unten nach oben) und
        so, dass der Rest getragen bleibt (eingebaut wird nur auf schon Getragenes). Geht das nicht, alle freien."""
        oben = [(e, d) for e, d in frei if d[2] > 0.999]
        for kandidaten in (oben, frei):
            if not kandidaten:
                continue
            aktuell = set(uebrig)
            gewaehlt = []
            for e, d in kandidaten:
                rest = aktuell - set(e.teile)
                if self._getragen(rest):
                    gewaehlt.append((e, d))
                    aktuell = rest
            if gewaehlt:
                return gewaehlt
        return []

    def _prio(self, e: Einheit) -> tuple:
        # oben liegende Teile zuerst (Ausbau von oben nach unten), dann Reihenfolge im Modell
        top = max(float(self.k[n].bmax[2]) for n in e.teile)
        return (-top, self.reihenfolge.index(e.teile[0]))

    def _loesen(self, einheiten: list[Einheit], stecken: list[Einheit], sperren: dict[str, dict[str, str]],
                erg: MontageErgebnis, runde: int, nur_paare: bool = False) -> list[Einheit] | None:
        """Steckende Einheiten zusammenlegen, damit die Zerlegung weitergeht. None: nichts mehr zu machen."""
        uebrig = [n for e in einheiten for n in e.teile]
        alle_teile = set(uebrig)
        by_teil = {n: e for e in stecken for n in e.teile}
        stecken_teile = list(by_teil)
        # 1. eingesperrt: q umschließt p und sperrt es in allen sechs Achsrichtungen
        for e in sorted([] if nur_paare else stecken, key=lambda e: self.k[e.teile[0]].volumen):
            if len(e.teile) != 1 or self.k[e.teile[0]].nachgiebig:
                continue
            p = e.teile[0]
            kp = self.k[p]
            for q in uebrig:
                if q == p or (by_teil.get(q) is e):
                    continue
                kq = self.k[q]
                if np.any(kp.bmin < kq.bmin - 0.5) or np.any(kp.bmax > kq.bmax + 0.5):
                    continue
                if all(self.sperrt(p, q, d) for d in ACHSEN):
                    self.befunde.append(befund(
                        "eingesperrt", [p, q], "fehler",
                        f"{p} ist in {q} eingesperrt: es lässt sich in keiner Richtung hinein- oder herausbewegen.",
                        f"{q} teilen (Deckel, zwei Schalen) oder eine Öffnung vorsehen, durch die {p} passt; {p} "
                        "vor dem Schließen einsetzen und den Deckel lösbar verbinden.",
                        ort=(kp.bmin + kp.bmax) / 2))
                    huelle = next(x for x in einheiten if q in x.teile)
                    return self._zusammen(einheiten, [e, huelle], automatisch=True, melden=False)
        # 2. Paare, die sich berühren (Vormontage: Klemme mit ihrem Bolzen), kleinste zuerst
        kandidaten: list[tuple[int, float, str, list[Einheit]]] = []
        gesehen: set[tuple[str, ...]] = set()
        for a, b in self.kontakte:
            ea, eb = by_teil.get(a), by_teil.get(b)
            if ea is None or eb is None or ea is eb:
                continue
            mit = [ea, eb]
            schluessel = tuple(sorted(x.name for x in mit))
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            vol = sum(self.k[n].volumen for x in mit for n in x.teile)
            kandidaten.append((0, vol, "", mit))
        # 3. Baugruppen aus dem Namensbaum, kleinste zuerst
        for n in ([] if nur_paare else stecken_teile):
            teile = n.split("/")
            for i in range(len(teile) - 1, 0, -1):
                pre = "/".join(teile[:i])
                mit = [x for x in stecken if any(t == pre or t.startswith(pre + "/") for t in x.teile)]
                schluessel = tuple(sorted(x.name for x in mit))
                if len(mit) < 2 or schluessel in gesehen:
                    continue
                gesehen.add(schluessel)
                kandidaten.append((1, sum(len(x.teile) for x in mit), pre, mit))
        # 4. zusammenhängende Teile (Kontakte)
        for gruppe in ([] if nur_paare else self._kontaktgruppen(stecken_teile)):
            mit = list({id(by_teil[n]): by_teil[n] for n in gruppe}.values())
            schluessel = tuple(sorted(x.name for x in mit))
            if len(mit) >= 2 and schluessel not in gesehen:
                gesehen.add(schluessel)
                kandidaten.append((2, sum(len(x.teile) for x in mit), "", mit))
        kandidaten.sort(key=lambda c: (c[0], c[1]))
        for _, _, pre, mit in kandidaten:
            teile = [n for x in mit for n in x.teile]
            name = pre or (f"{mit[0].name} mit {mit[1].name.rsplit('/', 1)[-1]}" if len(mit) == 2
                           else f"{mit[0].name} und {len(mit) - 1} weitere")
            g = Einheit(name, teile, self.richtungen_fuer(teile)[0], gruppe=True)
            if not self._reihenfolge_ok(g, alle_teile):
                continue
            rest = [n for n in self.reihenfolge if n in alle_teile and n not in teile]
            d, _ = self.frei(g, rest)
            if d is not None:
                return self._zusammen(einheiten, mit, name=g.name, automatisch=True)
        return None

    def _kontaktgruppen(self, teile: list[str]) -> list[list[str]]:
        from kevcad_kernel.pruefung.stand import Gruppen

        uf = Gruppen(teile)
        s = set(teile)
        for a, b in self.kontakte:
            if a in s and b in s:
                uf.union(a, b)
        return sorted(uf.gruppen(), key=len)

    def _zusammen(self, einheiten: list[Einheit], mit: list[Einheit], name: str | None = None,
                  automatisch: bool = False, melden: bool = True) -> list[Einheit]:
        teile = [n for x in mit for n in x.teile]
        name = name or mit[0].name
        g = Einheit(name, teile, self.richtungen_fuer(teile)[0], gruppe=True)
        if melden:
            self._gruppen_befund(g)
        return [x for x in einheiten if x not in mit] + [g]

    def _gruppen_befund(self, g: Einheit) -> None:
        """Welche Teile der Gruppe lassen sich einzeln nicht einbauen? (Zerlegung nur innerhalb der Gruppe)"""
        innen = Planer({n: self.k[n] for n in g.teile}, ausschluss=self.ausschluss, nachgiebig=self.nachgiebig,
                       kontakte=self.kontakte, cache=self.cache,
                       erklaerungen=[e for e in self.erklaerungen if not e.get("baugruppe")],
                       zeitlimit_s=max(1.0, self.ende - time.monotonic()), abbrechen=self._abbrechen)
        einh = innen.einheiten()
        innen.nach = {n: v & set(g.teile) for n, v in self.nach.items() if n in g.teile}
        sperren: dict[str, dict[str, str]] = {}
        while einh:
            uebrig = {n for e in einh for n in e.teile}
            frei = []
            sperren = {}
            for e in sorted(einh, key=innen._prio):
                rest = [n for n in innen.reihenfolge if n in uebrig and n not in e.teile]
                d, sp = innen.frei(e, rest)
                if d is not None:
                    frei.append(e)
                else:
                    sperren[e.name] = sp
            if not frei:
                break
            for e in frei:
                einh.remove(e)
        self.tests += innen.tests
        stecken = [n for e in einh for n in e.teile]
        if not stecken:
            return
        name = g.name
        liste = ", ".join(n.rsplit("/", 1)[-1] for n in stecken[:5]) + (" …" if len(stecken) > 5 else "")
        details = []
        for n in stecken[:3]:
            nach_q: dict[str, list[str]] = {}
            for rtext, q in (sperren.get(n) or {}).items():
                nach_q.setdefault(q.rsplit("/", 1)[-1], []).append(rtext)
            if nach_q:
                details.append(f"{n.rsplit('/', 1)[-1]}: " + "; ".join(f"{q} {', '.join(r)}" for q, r in nach_q.items()))
        hindernisse = details
        alle_frei = all(not self.k[n].info.get("lager") for n in g.teile)
        loesung = (f"Ist {name} ein Zukaufteil (fertig montiert geliefert), als Baugruppe erklären: "
                   f"montage(\"{name}\", baugruppe=True). Sonst lösbar konstruieren: Achse oder Bolzen als eigenes "
                   "Teil, Teilung, Öffnung oder Spiel vorsehen, damit sich jedes Teil einzeln einsetzen lässt.")
        if not alle_frei:
            loesung = ("Lösbar konstruieren: Achse oder Bolzen als eigenes Teil, Teilung, Öffnung oder Spiel vorsehen, "
                       f"damit sich jedes Teil einzeln einsetzen lässt; nur wenn {name} fertig montiert geliefert "
                       f"wird: montage(\"{name}\", baugruppe=True).")
        k0 = self.k[stecken[0]]
        self.befunde.append(befund(
            "nur_baugruppe", stecken, "fehler",
            f"{liste} {'lässt' if len(stecken) == 1 else 'lassen'} sich einzeln nicht einbauen, nur zusammen als "
            f"{name}" + (f". Blockiert – {' | '.join(hindernisse)}" if hindernisse else "") + ".",
            loesung, wert={"gruppe": name, "teile_gruppe": len(g.teile), "sperren": sperren},
            ort=(k0.bmin + k0.bmax) / 2))

    def _offen_befunde(self, erg: MontageErgebnis) -> list[dict[str, Any]]:
        out = []
        for e in erg.offen:
            sp = erg.sperren.get(e.name, {})
            nach_hindernis: dict[str, list[str]] = {}
            for rtext, q in sp.items():
                nach_hindernis.setdefault(q, []).append(rtext)
            sperr_text = "; ".join(f"{q} ({', '.join(r)})" for q, r in nach_hindernis.items()) or "keine Angabe"
            k0 = self.k[e.teile[0]]
            ort = (k0.bmin + k0.bmax) / 2
            weich = all(n in self.nachgiebig for n in e.teile)
            if erg.abgebrochen:
                continue
            if e.verbindung and k0.art == "schraube":
                out.append(befund(
                    "einfuehren", e.teile, "fehler",
                    f"{e.name} lässt sich nicht entlang ihrer Achse einführen: blockiert von {sperr_text}.",
                    "Durchgangsbohrung bis zum Kopf durchgehend vorsehen (ISO 273 mittel, z. B. M8 Ø 9), Schraube von "
                    "der anderen Seite einsetzen oder das blockierende Teil später montieren "
                    "(montage(teil, nach=...)).", wert={"sperren": sp}, ort=ort))
                continue
            out.append(befund(
                "nicht_einbaubar", e.teile, "warnung" if weich else "fehler",
                f"{e.name} lässt sich nicht einbauen: in jeder geprüften Richtung blockiert, von {sperr_text}.",
                "Reihenfolge ändern (blockierendes Teil später montieren, montage(teil, nach=...)), Teil teilen, "
                "lösbare Verbindung statt Formschluss, Öffnung oder mehr Spiel vorsehen. Nur wenn es schräg "
                "eingesetzt wird: Einführrichtung erklären (montage(teil, richtung=(x, y, z)))."
                + (" Nachgiebiges Teil: lässt sich nur verformt einsetzen." if weich else ""),
                wert={"sperren": sp}, ort=ort))
        if erg.abgebrochen:
            out.append(befund("nicht_einbaubar", [e.teile[0] for e in erg.offen][:1] or ["Modell"], "warnung",
                              f"Montageprüfung abgebrochen ({erg.abgebrochen}); "
                              f"{len(erg.offen)} Einheiten nicht geprüft.",
                              "Mit pruefen erneut prüfen; bei sehr vielen Teilen Baugruppen erklären "
                              "(montage(\"Gruppe\", baugruppe=True))."))
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Werkzeugzugang nach der Reihenfolge


def werkzeug_befunde(koerper: dict[str, Koerper], erg: MontageErgebnis,
                     erklaert: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Freiraum für das Werkzeug je Verbindungselement, gegen die Teile, die beim Einsetzen schon verbaut sind.
    Liefert Befunde und je Teil den Werkzeugtext für die Montageliste."""
    from kevcad_kernel.pruefung.werkzeug import kopfmasse, pruefe_zugang, werkzeug_aus_text, werkzeug_fuer

    erklaert = erklaert or {}
    # verbaut vor einem Teil = alles, was in der Ausbaufolge später herauskommt (oder offen ist)
    vorher: dict[str, list[str]] = {}
    offen = [n for e in erg.offen for n in e.teile]
    spaeter: list[str] = list(offen)
    for s in reversed(erg.schritte):
        for n in s.einheit.teile:
            vorher[n] = [x for x in spaeter]
        spaeter += s.einheit.teile
    for n in offen:
        vorher[n] = [x for x in koerper if x != n]
    befunde, texte = [], {}
    for n, k in koerper.items():
        kopfmasse(k)
        w = werkzeug_aus_text(erklaert[n], float(k.info.get("d") or 6)) if n in erklaert else werkzeug_fuer(k.info)
        if w is None:
            continue
        andere = [koerper[x] for x in vorher.get(n, list(koerper)) if x in koerper and x != n]
        z = pruefe_zugang(k, w, andere)
        if z is None:
            continue
        texte[n] = w.name
        ort = k.info.get("ursprung")
        if not z.ok:
            befunde.append(befund(
                "werkzeug", [n] + z.blockiert[:3], "fehler",
                f"{n}: {w.text} kommt nicht hin, im Weg: {', '.join(z.blockiert[:4])}.",
                "Durchgang für das Werkzeug vorsehen (Bohrung im Weg), Schraube von der anderen Seite oder vor dem "
                "blockierenden Teil einsetzen (montage(teil, nach=...)), längere Schraube mit Distanzhülse, oder "
                "Sechskantschraube, die sich mit dem Gabelschlüssel von der Seite anziehen lässt.",
                wert={"werkzeug": w.name, "durchmesser": round(w.durchmesser, 1), "laenge": round(w.laenge, 1)},
                ort=ort))
        elif z.nur_seitlich:
            texte[n] = w.name.replace("Steckschlüssel", "Gabelschlüssel") + " von der Seite"
            befunde.append(befund(
                "werkzeug", [n], "hinweis",
                f"{n}: über die Achse kein Platz für den {w.name}, nur mit dem Gabelschlüssel von der Seite.",
                "In Ordnung, wenn das genügt; für den Steckschlüssel Freiraum über dem Kopf schaffen.",
                wert={"werkzeug": w.name}, ort=ort))
    return befunde, texte


# ---------------------------------------------------------------------------------------------------------------------
# Prüffunktion


def pruefe_montage(ctx: PruefKontext) -> list[dict[str, Any]]:
    if not ctx.optionen.get("montage", True):
        return []
    t0 = time.perf_counter()
    bz = (ctx.ergebnis.get("stand") or {}).get("boden_z")
    boden = set(ctx.befestigt())
    if bz is not None:
        boden |= {n for n, k in ctx.koerper.items() if float(k.bmin[2]) <= float(bz) + BODEN_TOL}
    planer = Planer(ctx.koerper, ausschluss=ctx.ausschluss() | _erlaubte_paare(ctx), nachgiebig=ctx.nachgiebig,
                    erklaerungen=ctx.erklaerungen.get("montage") or [], kontakte=ctx.kontakte, cache=ctx.cache,
                    zeitlimit_s=float(ctx.optionen.get("zeitlimit_s") or 60), abbrechen=ctx.abbrechen,
                    boden=boden or None)
    erg = planer.plane()
    ctx.zeiten["montage"] = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    erklaert_wz = {}
    for e in ctx.erklaerungen.get("montage") or []:
        if e.get("werkzeug"):
            for n in ctx.koerper:
                if passt(n, e.get("teile") or []):
                    erklaert_wz[n] = str(e["werkzeug"])
    wz_befunde, wz_texte = werkzeug_befunde(ctx.koerper, erg, erklaert_wz)
    ctx.zeiten["werkzeug"] = (time.perf_counter() - t1) * 1000
    schritte = erg.einbau()
    for s in schritte:
        wz = [wz_texte[n] for n in s["teile"] if n in wz_texte]
        s["werkzeug"] = wz[0] if wz else None
    ctx.ergebnis["montage"] = {
        "vollstaendig": not erg.offen and not erg.abgebrochen,
        "schritte": schritte,
        "offen": [n for e in erg.offen for n in e.teile],
        "tests": erg.tests,
        "abgebrochen": erg.abgebrochen,
    }
    return erg.befunde + wz_befunde


def _erlaubte_paare(ctx: PruefKontext) -> set[frozenset[str]]:
    return {k for k, p in ctx.paare.items() if p.durchdringt and ctx.erlaubt(p.a, p.b)}


registriere("montage", pruefe_montage)

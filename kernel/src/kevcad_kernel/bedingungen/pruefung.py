"""Prüfung nach jedem Lauf: alle Bedingungen gegen die gezeigte Geometrie, Freiheitsgrade, Bewegungsraum, Befestigung.

``pruefen(sammlung, formen, ...)`` läuft im Rechenprozess direkt nach model.py. Bezüge werden in der Szene
wiedergefunden (``TeilIndex``): über die gemeinsame OCCT-Geometrie (Partner) der gezeigten Form, bei mehreren Treffern
die Lage, die zur Gegenseite passt; wurde das Teil nach dem Bezug noch verändert (Bohrung, Verrundung), über die
Geometrie selbst (Fläche oder Achse an derselben Stelle). Ergebnis ist der Bericht für das Protokoll (Nachricht
CONSTRAINTS) und für MCP, mit Befunden im gemeinsamen Format der Prüfung (``befunde``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .arten import (
    Bedingung,
    Ergebnis,
    Gelenk,
    Gleich,
    InBohrung,
    Konzentrisch,
    MinWand,
    Verbindung,
)
from .geometrie import Bezug, form_matrix, linien_winkel, transform_abstand
from .loeser import Freiheit, Platzierung, _Aufgabe, freiheitsgrade
from .sammlung import Sammlung
from .text import mehrzahl, mm, zahl

MAX_BEFUNDE = 200


def _r(v: Any, n: int = 4) -> Any:
    if v is None:
        return None
    if isinstance(v, np.ndarray):
        return [round(float(x), n) for x in v]
    if isinstance(v, (list, tuple)):
        return [_r(x, n) for x in v]
    if isinstance(v, (float, np.floating)):
        return round(float(v), n)
    return v


# ---------------------------------------------------------------------------------------------------------------------
# Bezüge in der Szene wiederfinden


@dataclass
class _Eintrag:
    name: str
    form: Any
    wrapped: Any
    koerper: list[tuple[Any, np.ndarray]]
    M: np.ndarray
    bbox: tuple[np.ndarray, np.ndarray]


def huellquader(form: Any) -> tuple[np.ndarray, np.ndarray]:
    bb = form.bounding_box()
    return np.array([bb.min.X, bb.min.Y, bb.min.Z]), np.array([bb.max.X, bb.max.Y, bb.max.Z])


class TeilIndex:
    """Die gezeigten Teile eines Laufs mit ihren OCCT-Formen, Körpern und Lagen."""

    def __init__(self, formen: dict[str, Any], boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None) -> None:
        self.formen = formen
        self.eintraege: list[_Eintrag] = []
        for name, form in formen.items():
            w = getattr(form, "wrapped", None)
            if w is None:
                continue
            try:
                koerper = [(s.wrapped, form_matrix(s.wrapped)) for s in form.solids()]
            except Exception:  # noqa: BLE001
                koerper = []
            if boxen is not None and name in boxen:
                lo, hi = boxen[name]
            else:
                lo, hi = huellquader(form)
            self.eintraege.append(_Eintrag(name, form, w, koerper, form_matrix(w), (lo, hi)))
        self._cache: dict[int, list[tuple[str, np.ndarray]]] = {}

    def kandidaten(self, b: Bezug) -> list[tuple[str, np.ndarray]]:
        """(Name, Lageänderung seit dem Bezug) aller gezeigten Teile mit derselben Geometrie wie die Quelle."""
        if b.quelle is None:
            return []
        key = id(b.quelle)
        if key in self._cache:
            return self._cache[key]
        out: list[tuple[str, np.ndarray]] = []
        Mq_inv = np.linalg.inv(b.M_q) if b.M_q is not None else np.eye(4)
        quell_koerper = [(q, form_matrix(q)) for q in b.quelle_koerper]
        for e in self.eintraege:
            if e.wrapped.IsPartner(b.quelle):
                out.append((e.name, e.M @ Mq_inv))
                continue
            found = None
            for s, Ms in e.koerper:
                for q, Mq in quell_koerper:
                    if s.IsPartner(q):
                        found = Ms @ np.linalg.inv(Mq)
                        break
                if found is not None:
                    break
            if found is not None:
                out.append((e.name, found))
        self._cache[key] = out
        return out

    def geometrisch(self, b: Bezug) -> str | None:
        """Gezeigtes Teil, an dem die Geometrie des Bezugs unverändert liegt (Teil nach dem Bezug noch gebohrt oder
        verrundet): Ebenen über gleich gerichtete Flächen in derselben Ebene, die die Bezugsflächen berühren; Achsen
        über Zylinderflächen gleichen Radius auf derselben Achse; Punkte über den Abstand."""
        if b.quelle is None or b.art == "teil":
            return None
        if b.art == "ebene" and b.flaechen:
            treffer = self._ebene(b)
        elif b.art == "achse" and b.r is not None and b.d is not None:
            treffer = self._zylinder(b)
        else:
            treffer = self._punkt(b.p)
        if len(treffer) == 1:
            return treffer[0]
        if len(treffer) > 1 and b.label:
            passend = [t for t in treffer if t == b.label or t.endswith("/" + b.label)]
            if len(passend) == 1:
                return passend[0]
        return None

    def _nahe(self, lo: np.ndarray, hi: np.ndarray, tol: float = 0.01) -> list[_Eintrag]:
        return [e for e in self.eintraege if np.all(e.bbox[0] <= hi + tol) and np.all(e.bbox[1] >= lo - tol)]

    def _ebene(self, b: Bezug) -> list[str]:
        from build123d import Face, GeomType
        from OCP.BRep import BRep_Builder
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.TopoDS import TopoDS_Compound

        def compound(faces: list[Any]) -> Any:
            comp = TopoDS_Compound()
            builder = BRep_Builder()
            builder.MakeCompound(comp)
            for f in faces:
                builder.Add(comp, f)
            return comp

        faces = b.flaechen_welt()
        mine = compound(faces)
        flaeche = sum(float(Face(f).area) for f in faces)
        pts = np.array([[v.X, v.Y, v.Z] for f in faces for v in Face(f).vertices()] or [b.p])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        treffer = []
        for e in self._nahe(lo, hi):
            gleich, summe = [], 0.0
            for f in e.form.faces():
                if f.geom_type != GeomType.PLANE:
                    continue
                fn = np.array(tuple(f.normal_at()))
                if float(np.dot(fn, b.d)) < 1 - 1e-6:
                    continue
                c = np.array(tuple(f.center()))
                if abs(float(np.dot(b.d, c - b.p))) > 0.01:
                    continue
                gleich.append(f.wrapped)
                summe += float(f.area)
            # dieselbe Fläche (höchstens gebohrt oder ergänzt), nicht nur eine andere Fläche in derselben Ebene
            if not gleich or not (0.5 * flaeche <= summe <= 2.0 * flaeche + 1e-6):
                continue
            d = BRepExtrema_DistShapeShape(mine, compound(gleich))
            if d.IsDone() and d.Value() <= 0.01:
                treffer.append(e.name)
        return treffer

    def _zylinder(self, b: Bezug) -> list[str]:
        from build123d import GeomType

        from .geometrie import _flaeche_daten

        assert b.d is not None and b.r is not None
        lo = b.mitte() - float(b.r) - 0.01
        hi = b.mitte() + float(b.r) + 0.01
        treffer = []
        for e in self._nahe(lo, hi, tol=abs((b.t or (0, 0))[1] - (b.t or (0, 0))[0]) + 0.01):
            for f in e.form.faces():
                if f.geom_type != GeomType.CYLINDER:
                    continue
                i = _flaeche_daten(f)
                off = i["p0"] - b.p
                if abs(i["r"] - b.r) < 0.01 and linien_winkel(i["d"], b.d) < 0.01 and \
                        np.linalg.norm(off - b.d * float(np.dot(off, b.d))) < 0.01:
                    treffer.append(e.name)
                    break
        return treffer

    def _punkt(self, p: np.ndarray) -> list[str]:
        from build123d import Vertex

        treffer = []
        for e in self._nahe(p, p):
            try:
                if e.form.distance_to(Vertex(*map(float, p))) <= 0.01:
                    treffer.append(e.name)
            except Exception:  # noqa: BLE001
                continue
        return treffer


@dataclass
class Aufgeloest:
    bezug: Bezug
    ok: bool
    hinweis: str | None = None


def _waehle(kand: list[tuple[str, np.ndarray]], gegen: np.ndarray | None) -> tuple[str, np.ndarray, bool]:
    """(Name, Lageänderung, eindeutig)."""
    if len(kand) == 1:
        return kand[0][0], kand[0][1], True
    gleich = [k for k in kand if np.allclose(k[1], np.eye(4), atol=1e-9)]
    if len(gleich) == 1:
        return gleich[0][0], gleich[0][1], True
    if gegen is not None:
        rang = sorted(kand, key=lambda k: transform_abstand(k[1], gegen))
        return rang[0][0], rang[0][1], True
    rang = sorted(kand, key=lambda k: _naehe(k[1]))  # sonst: am liebsten nur verschoben, dann am wenigsten
    return rang[0][0], rang[0][1], _naehe(rang[0][1]) < _naehe(rang[1][1])


def _naehe(M: np.ndarray) -> tuple[float, float]:
    """Rangfolge für Lageänderungen ohne weitere Information: ungedreht vor gedreht, dann kleinste Verschiebung."""
    return round(float(np.linalg.norm(M[:3, :3] - np.eye(3))), 6), round(float(np.linalg.norm(M[:3, 3])), 6)


def aufloesen(index: TeilIndex, b: Bezug, gegen: np.ndarray | None = None) -> tuple[Aufgeloest, np.ndarray | None]:
    """Bezug in der gezeigten Lage. ``gegen``: Lageänderung der Gegenseite (für mehrfach gezeigte Teile)."""
    if b.welt:
        return Aufgeloest(b, True), None
    kand = index.kandidaten(b) if b.quelle is not None else []
    if not kand and b.per_name:  # Bezug über den Namen: an der zuletzt gezeigten Form neu auswerten
        form = index.formen.get(b.per_name)
        if form is None:
            return Aufgeloest(b, False, f"Teil {b.per_name!r} ist nicht gezeigt"), None
        from .geometrie import bezug as neu

        args = tuple(b.auswahl_args or ()) + (None, None, None, False, None)[len(b.auswahl_args or ()):]
        try:
            out = neu(form, args[0], args[1], nahe=args[2], umkehren=args[3], richtung=args[4])
        except Exception as exc:  # noqa: BLE001
            return Aufgeloest(b, False, f"Bezug an {b.per_name}: {exc}"), None
        return Aufgeloest(_szene_form(out, b.per_name, form), True), np.eye(4)
    if kand:
        name, M, eindeutig = _waehle(kand, gegen)
        out = _szene_form(b.bewegt(M), name, index.formen.get(name))
        hinweis = None if eindeutig else (f"{b.anzeigename()} ist {len(kand)}-mal gezeigt; Bezug am gezeigten Teil "
                                          "nehmen (gleiches Objekt wie in show)")
        return Aufgeloest(out, True, hinweis), M
    versuche = ([gegen] if gegen is not None else []) + [np.eye(4)]  # erst die Lage der Gegenseite
    if b.M_platziert is not None:  # platziert und danach noch gebohrt: erst die Lage aus platziere
        versuche = [v @ b.M_platziert for v in versuche] + versuche
    eindeutig: list[np.ndarray] = []
    for v in versuche:
        if not any(np.allclose(v, w) for w in eindeutig):
            eindeutig.append(v)
    for M in eindeutig:
        name = index.geometrisch(b.bewegt(M))
        if name is not None:
            out = _szene_form(b.bewegt(M), name, index.formen.get(name))
            return Aufgeloest(out, True), M
    return Aufgeloest(b, False, _nicht_gefunden(b)), None


def _nicht_gefunden(b: Bezug) -> str:
    return (f"Teil zu {b.anzeigename()} nicht gefunden: nicht gezeigt oder nach dem Bezug noch verändert und "
            "verschoben (Bezug nach der letzten Änderung nehmen oder das Teil über seinen Namen angeben)")


def aufloesen_paar(index: TeilIndex, a: Bezug, b: Bezug) -> tuple[Aufgeloest, Aufgeloest, np.ndarray | None]:
    """Beide Bezüge einer Bedingung zusammen auflösen: bei mehrfach gezeigten Teilen das Paar, dessen Lageänderungen
    zusammenpassen (gleich verschobene Baugruppe); fehlt die Geometrie einer Seite (danach gebohrt), wird sie in der
    Lage der Gegenseite gesucht. Liefert auch die Lageänderung von A."""
    ka = index.kandidaten(a) if a.quelle is not None and not a.welt else []
    kb = index.kandidaten(b) if b.quelle is not None and not b.welt else []
    if ka and kb:
        _, ia, ib = min(((transform_abstand(Ma, Mb) + 1e-3 * transform_abstand(Ma, np.eye(4)), ia, ib)
                         for ia, (_, Ma) in enumerate(ka) for ib, (_, Mb) in enumerate(kb)), key=lambda t: t[0])
        A0, MA = aufloesen(index, a, gegen=ka[ia][1])
        B0, _ = aufloesen(index, b, gegen=kb[ib][1])
        return A0, B0, MA
    if ka:
        A0, MA = aufloesen(index, a)
        B0, _ = aufloesen(index, b, gegen=MA)
        return A0, B0, MA
    if kb:
        for _, Mb in sorted(kb, key=lambda k: _naehe(k[1])):
            A0, MA = aufloesen(index, a, gegen=Mb)
            if A0.ok:
                B0, _ = aufloesen(index, b, gegen=Mb)
                return A0, B0, MA
        B0, MB = aufloesen(index, b)
        A0, MA = aufloesen(index, a, gegen=MB)
        return A0, B0, MA
    A0, MA = aufloesen(index, a)
    B0, _ = aufloesen(index, b, gegen=MA)
    if not A0.ok and B0.ok:
        A0, MA = aufloesen(index, a, gegen=_lage(index, b, B0))
    return A0, B0, MA


def _szene_form(b: Bezug, name: str, form: Any) -> Bezug:
    """Bezug mit Namen und der gezeigten Form als Teilform (liegt schon richtig, keine weitere Lageänderung)."""
    b.teilname = name
    if form is not None:
        b.teil_form = form
        b.M_form = None
    return b


def aufloesen_an(b: Bezug, teil: Any) -> Bezug:
    """Bezug an einer bestimmten Form (für als_joints): gleiche Geometrie, Lage dieser Form."""
    if b.welt:
        return b
    idx = TeilIndex({"_": teil})
    kand = idx.kandidaten(b)
    if not kand:
        return b
    return b.bewegt(kand[0][1])


# ---------------------------------------------------------------------------------------------------------------------
# Bericht


def _befund(*, pruefung: str, teile: list[str], schwere: str, text: str, soll: str = "", ist: str = "",
            wert: float | None = None, einheit: str = "mm", ort: Any = None, loesung: str | None = None,
            bedingung: str | None = None, art: str | None = None, zeile: int | None = None) -> dict[str, Any]:
    return {"art": "bedingung", "pruefung": pruefung, "teile": teile, "schwere": schwere, "text": text,
            "soll": soll, "ist": ist, "wert": _r(wert), "einheit": einheit, "ort": _r(ort, 3), "loesung": loesung,
            "bedingung": bedingung, "unterart": art, "zeile": zeile}


def _teile(*bs: Bezug) -> list[str]:
    out = []
    for b in bs:
        n = b.teilname or (b.name if b.welt else None) or b.label
        if n and n not in out:
            out.append(n)
    return out


def _item(c: Bedingung, text: str, teile: list[str], erg: Ergebnis) -> dict[str, Any]:
    item = {"id": c.id, "art": c.art, "gruppe": c.gruppe, "symbol": c.symbol, "text": text, "teile": teile,
            "stand": erg.stand, "soll": erg.soll, "ist": erg.ist, "abweichung": _r(erg.abweichung),
            "einheit": erg.einheit, "punkte": [_r(p, 3) for p in erg.punkte if p is not None][:2],
            "zeile": c.zeile, "datei": c.datei, "loesung": erg.loesung if erg.stand == "verletzt" else None}
    if erg.stand == "verletzt":
        item["schwere"] = erg.schwere
    if erg.hinweis:
        item["hinweis"] = erg.hinweis
    item.update(c.info())
    return item


def _befunde_aus(c: Bedingung, text: str, teile: list[str], erg: Ergebnis) -> list[dict[str, Any]]:
    out = []
    if erg.stand == "verletzt":
        for e in [erg, *erg.weitere]:
            out.append(_befund(pruefung="bedingung", teile=teile, schwere=e.schwere, text=f"{text}: {e.ist}",
                               soll=e.soll, ist=e.ist, wert=e.abweichung, einheit=e.einheit,
                               ort=e.ort if e.ort is not None else (e.punkte[0] if e.punkte else None),
                               loesung=e.loesung, bedingung=c.id, art=c.art, zeile=c.zeile))
    elif erg.stand == "ungeprueft":
        out.append(_befund(pruefung="bedingung", teile=teile, schwere="hinweis",
                           text=f"{text}: nicht geprüft ({erg.hinweis or 'unbekannt'})", bedingung=c.id, art=c.art,
                           zeile=c.zeile, loesung=erg.hinweis))
    return out


def pruefen(sammlung: Sammlung, formen: dict[str, Any], *, netze: dict[str, Any] | None = None,
            schluessel: dict[str, str] | None = None, projekt: str | Path | None = None,
            boxen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
            zeitlimit_s: float = 5.0, bewegungsraum: bool = True, kulisse: set[str] | None = None) -> dict[str, Any]:
    """Prüft alle Bedingungen des Laufs gegen die gezeigten Formen (Name → build123d-Form) und liefert den Bericht.
    ``netze``: Name → (Punkte, Dreiecke, Normalen) für min_wand; ``schluessel``: Name → Geometrieschlüssel (für den
    Zwischenspeicher des Bewegungsraums); ``boxen``: Name → Hüllquader (spart das Neuberechnen); ``kulisse``: Namen
    der Kulissenteile (Umgebung: keine Befestigungspflicht, zählen aber als Boden)."""
    t0 = time.perf_counter()
    formen = {n: f for n, f in formen.items() if not n.startswith("Skizze/")}
    index = TeilIndex(formen, boxen) if (sammlung.bedingungen or sammlung.platzierungen) else None
    items: list[dict[str, Any]] = []
    befunde: list[dict[str, Any]] = []
    beteiligt: dict[str, list[str]] = {}
    aufgeloest: dict[str, tuple[Bezug, Bezug]] = {}

    def merke(teile: list[str], cid: str) -> None:
        for t in teile:
            if t in formen:
                beteiligt.setdefault(t, []).append(cid)

    # Parametergrenzen
    for g in sammlung.grenzen:
        wert = g.wert
        teile: list[str] = []
        soll = " … ".join(x for x in (f"≥ {zahl(g.min)}" if g.min is not None else "",
                                       f"≤ {zahl(g.max)}" if g.max is not None else "") if x)
        ok = isinstance(wert, (int, float)) and (g.min is None or wert >= g.min) and (g.max is None or wert <= g.max)
        item = {"id": f"p:{g.name}", "art": "param", "gruppe": "mass", "symbol": "param",
                "text": f"Parameter {g.name}", "teile": teile, "stand": "erfuellt" if ok else "verletzt",
                "soll": soll, "ist": zahl(wert) if isinstance(wert, (int, float)) else str(wert), "abweichung": None,
                "einheit": "", "punkte": [], "zeile": g.zeile, "datei": g.datei, "loesung": None}
        if not ok:
            grenze = g.min if (g.min is not None and isinstance(wert, (int, float)) and wert < g.min) else g.max
            richtung = "mindestens" if grenze == g.min else "höchstens"
            item["schwere"] = "fehler"
            item["abweichung"] = _r(float(wert) - float(grenze)) if isinstance(wert, (int, float)) else None
            item["loesung"] = (f"{g.name} {richtung} {zahl(grenze)} wählen (Grenze in "
                               f"{'Zeile ' + str(g.zeile) if g.zeile else 'model.py'})")
            befunde.append(_befund(pruefung="parameter", teile=[], schwere="fehler",
                                   text=f"Parameter {g.name} = {item['ist']} außerhalb {soll}", soll=soll,
                                   ist=item["ist"], wert=item["abweichung"], einheit="", loesung=item["loesung"],
                                   bedingung=item["id"], art="param", zeile=g.zeile))
        items.append(item)

    # Bedingungen (Verbindungen prüft befestigung.py)
    for c in sammlung.bedingungen:
        if isinstance(c, Verbindung):
            continue
        try:
            if isinstance(c, Gleich):
                bez = [aufloesen(index, b)[0].bezug for b in c.bezuege] if index else list(c.bezuege)
                text, erg = c.pruefe_werte(sammlung.params, bez)
                teile = _teile(*bez)
            elif isinstance(c, MinWand):
                A = aufloesen(index, c.a)[0] if index else Aufgeloest(c.a, False)
                teile = _teile(A.bezug)
                text = c.beschreibung_teil(A.bezug)
                name = A.bezug.teilname
                netz = (netze or {}).get(name) if name else None
                erg = c.pruefe_netz(A.bezug, netz) if A.ok else Ergebnis("ungeprueft", hinweis=A.hinweis)
            else:
                assert index is not None
                A0, B0, _ = aufloesen_paar(index, c.a, c.b)
                A, B = A0.bezug, B0.bezug
                teile = _teile(A, B)
                text = c.beschreibung(A, B)
                if not (A0.ok and B0.ok):
                    erg = Ergebnis("ungeprueft", hinweis=A0.hinweis or B0.hinweis)
                else:
                    erg = c.pruefe(A, B)
                    hinweis = A0.hinweis or B0.hinweis
                    if hinweis and not erg.hinweis:
                        erg.hinweis = hinweis
                    aufgeloest[c.id] = (A, B)
                    if isinstance(c, Gelenk) and B.d is not None:
                        c.achse_welt = (B.p.copy(), B.d.copy())
        except Exception as exc:  # noqa: BLE001 - eine kaputte Bedingung darf die anderen nicht verhindern
            text, teile = f"{c.art} ({c.id})", []
            erg = Ergebnis("ungeprueft", hinweis=f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}")
        item = _item(c, text, teile, erg)
        if isinstance(c, Gelenk) and c.achse_welt is not None:
            item["achse"] = {"p": _r(c.achse_welt[0], 3), "d": _r(c.achse_welt[1], 6)}
            item["anim_art"] = c.anim_art
        items.append(item)
        befunde.extend(_befunde_aus(c, text, teile, erg))
        merke(teile, c.id)

    # Platzierungen: Teilname, Widerspruch, Freiheitsgrade
    teile_info: dict[str, dict[str, Any]] = {}
    loese_ms = 0.0
    for pl in sammlung.platzierungen:
        loese_ms += pl.ms
        name = _platzierung_name(index, pl) if index else None
        if name is None:  # danach noch gebohrt: Name über die aufgelösten Bezüge am Teil
            for c, k in zip(pl.bedingungen, pl.bewegt):
                if c.id in aufgeloest and aufgeloest[c.id][k].teilname:
                    name = aufgeloest[c.id][k].teilname
                    break
        pl.teilname = name
        anzeige = name or pl.label or "Teil"
        if pl.widerspruch:
            ids = ", ".join(f"{c.id} ({c.art})" for c in pl.widerspruch)
            befunde.append(_befund(pruefung="widerspruch", teile=[n for n in [name] if n], schwere="fehler",
                                   text=f"Widerspruch beim Platzieren von {anzeige}: {ids} passen nicht zusammen "
                                        f"(Rest {mm(pl.rest)})",
                                   soll="alle Bedingungen erfüllbar", ist=f"Rest {mm(pl.rest)}", wert=pl.rest,
                                   loesung="eine der genannten Bedingungen entfernen oder ihre Werte angleichen",
                                   zeile=pl.zeile))
        frei = [f for f in pl.frei if not f.gelenk and not _unkritisch(f, pl)]
        info = teile_info.setdefault(name or anzeige, {"name": name or anzeige, "platziert": True})
        info["frei"] = len(frei)
        info["freiheitsgrade"] = [{**f.als_dict(), "unkritisch": _unkritisch(f, pl)} for f in pl.frei]
        info["gelenke"] = [f.text() for f in pl.frei if f.gelenk]
        info["loese_ms"] = pl.ms
        info["stand"] = "widerspruch" if pl.widerspruch else ("unterbestimmt" if frei else "bestimmt")
        if frei:
            befunde.append(_befund(pruefung="freiheitsgrade", teile=[n for n in [name] if n], schwere="hinweis",
                                   text=f"{anzeige} ist unterbestimmt: {mehrzahl(len(frei), 'Freiheitsgrad', 'Freiheitsgrade')}"
                                        f" frei ({'; '.join(f.text() for f in frei)})",
                                   soll="0 freie Freiheitsgrade (außer Gelenken)", ist=f"{len(frei)} frei",
                                   wert=float(len(frei)), einheit="", ort=pl.zentrum,
                                   loesung=_dof_tipp(frei), zeile=pl.zeile))
        for g in pl.blockiert:
            befunde.append(_befund(pruefung="freiheitsgrade", teile=[n for n in [name] if n], schwere="warnung",
                                   text=f"{g} von {anzeige} ist blockiert: andere Bedingungen sperren seinen "
                                        "Freiheitsgrad", loesung="die zusätzliche Bedingung entfernen oder das Gelenk "
                                                                 "durch fest(…) ersetzen", zeile=pl.zeile))
        if name:
            for c in pl.bedingungen:
                if c.id and c.id not in beteiligt.get(name, []):
                    beteiligt.setdefault(name, []).append(c.id)

    # Freiheitsgrade deklarierter (nicht platzierter) Teile: erster Bezug = das Teil, das sich anpasst
    if index is not None:
        _deklarierte_freiheit(sammlung, aufgeloest, teile_info)

    # Bewegungsraum (B8): im Lauf über die Prüfung nach RUN_DONE (anbindung.py), sonst gleich hier
    sammlung.aufgeloest = aufgeloest
    bewegungen: list[dict[str, Any]] = []
    if bewegungsraum:
        rest_s = max(0.0, zeitlimit_s - (time.perf_counter() - t0))
        from .bewegungsraum import bewegungen_pruefen

        bewegungen, bew_befunde = bewegungen_pruefen(sammlung, aufgeloest, formen, schluessel=schluessel or {},
                                                     projekt=projekt, zeitlimit_s=rest_s, boxen=boxen)
        befunde.extend(bew_befunde)

    # Befestigung (B9)
    from .befestigung import befestigung_pruefen

    bef_items, bef_befunde, bef_teile = befestigung_pruefen(sammlung, aufgeloest, formen, index, beteiligt,
                                                            {i["id"]: i for i in items}, boxen, kulisse=kulisse)
    items.extend(bef_items)
    befunde.extend(bef_befunde)

    # Teile mit Bedingungen
    for name, ids in beteiligt.items():
        info = teile_info.setdefault(name, {"name": name, "platziert": False})
        info["bedingungen"] = sorted(set(ids), key=lambda s: (len(s), s))
        info.setdefault("stand", "bezug")
        info.setdefault("frei", 0)
    for name, b in bef_teile.items():
        info = teile_info.setdefault(name, {"name": name, "platziert": False, "frei": 0, "stand": "bezug",
                                            "bedingungen": []})
        info.update(b)
    for it in items:
        if it.get("stand") == "verletzt":
            for t in it.get("teile") or []:
                if t in teile_info:
                    teile_info[t]["verletzt"] = teile_info[t].get("verletzt", 0) + 1
    rang = {"fehler": 0, "warnung": 1, "hinweis": 2}
    befunde.sort(key=lambda b: rang.get(b["schwere"], 3))
    summe = {
        "gesamt": len(items),
        "erfuellt": sum(1 for i in items if i["stand"] == "erfuellt"),
        "verletzt": sum(1 for i in items if i["stand"] == "verletzt"),
        "ungeprueft": sum(1 for i in items if i["stand"] == "ungeprueft"),
        "fehler": sum(1 for b in befunde if b["schwere"] == "fehler"),
        "warnungen": sum(1 for b in befunde if b["schwere"] == "warnung"),
        "hinweise": sum(1 for b in befunde if b["schwere"] == "hinweis"),
        "bewegungen": len(bewegungen),
    }
    return {
        "items": items,
        "teile": sorted(teile_info.values(), key=lambda t: t["name"]),
        "befunde": befunde[:MAX_BEFUNDE],
        "bewegungen": bewegungen,
        "summe": summe,
        "loese_ms": round(loese_ms, 2),
        "pruef_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


def _lage(index: TeilIndex, b: Bezug, aufg: Aufgeloest) -> np.ndarray | None:
    for name, M in index.kandidaten(b):
        if name == aufg.bezug.teilname:
            return M
    return None


def _platzierung_name(index: TeilIndex, pl: Platzierung) -> str | None:
    hits = []
    for e in index.eintraege:
        if e.wrapped.IsPartner(pl.quelle):
            hits.append(e)
    if not hits:
        return None
    gleich = [e for e in hits if e.wrapped.IsSame(pl.quelle)]
    return (gleich or hits)[0].name


def _unkritisch(f: Freiheit, pl: Platzierung) -> bool:
    """Drehung um die eigene Achse runder Verbindungen (Schraube in Bohrung, Bolzen in Buchse) ist unkritisch."""
    if f.art != "drehung" or f.punkt is None:
        return False
    for c in pl.bedingungen:
        if isinstance(c, (InBohrung, Konzentrisch)):
            b = c.bezuege[1]
            if b.d is None:
                continue
            ax = b.bewegt(np.eye(4))
            if linien_winkel(f.richtung, ax.d) < 0.5:
                off = f.punkt - ax.p
                if np.linalg.norm(off - ax.d * float(np.dot(off, ax.d))) < 0.5:
                    return True
    return False


def _dof_tipp(frei: list[Freiheit]) -> str:
    from .text import richtung

    tipps = []
    for f in frei:
        if f.art == "verschiebung":
            tipps.append(f"Lage entlang {richtung(f.richtung)} festlegen (abstand, mittig, auf, konzentrisch)")
        else:
            tipps.append(f"Drehung um {richtung(f.richtung)} sperren (zweite Achse konzentrisch, parallel, fest)")
    return "; ".join(dict.fromkeys(tipps))


def _deklarierte_freiheit(sammlung: Sammlung, aufgeloest: dict[str, tuple[Bezug, Bezug]],
                          teile_info: dict[str, dict[str, Any]]) -> None:
    gruppen: dict[str, list[tuple[Bedingung, Bezug, Bezug]]] = {}
    for c in sammlung.bedingungen:
        if c.gruppe not in ("montage", "gelenk") or c.platzierung is not None or c.id not in aufgeloest:
            continue
        A, B = aufgeloest[c.id]
        if A.teilname and A.teilname != B.teilname:
            gruppen.setdefault(A.teilname, []).append((c, A, B))
    for name, liste in gruppen.items():
        if name in teile_info:
            continue
        auf = _Aufgabe.__new__(_Aufgabe)
        auf.form = None
        auf.bed = [c for c, _, _ in liste]
        auf.bewegt = [0] * len(liste)
        auf.zentrum = np.mean([A.p for _, A, _ in liste], axis=0)
        auf.L = 100.0
        paare = [(A, B) for _, A, B in liste]

        def seiten(M: np.ndarray, paare: list = paare, liste: list = liste) -> list:
            return [(c, A.bewegt(M), B, 0) for (c, _, _), (A, B) in zip(liste, paare)]

        auf.seiten = seiten  # type: ignore[method-assign]
        try:
            frei, blockiert = freiheitsgrade(auf, np.eye(4))
        except Exception:  # noqa: BLE001
            continue
        unerklaert = [f for f in frei if not f.gelenk]
        teile_info[name] = {"name": name, "platziert": False, "frei": len(unerklaert),
                            "freiheitsgrade": [f.als_dict() for f in frei],
                            "gelenke": [f.text() for f in frei if f.gelenk],
                            "stand": "unterbestimmt" if unerklaert else "bestimmt"}
        _ = blockiert

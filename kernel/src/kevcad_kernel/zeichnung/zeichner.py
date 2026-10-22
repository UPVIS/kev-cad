"""Ein Blatt rechnen: Blatt-JSON + Szene → fertige Zeichnung (Nachricht DRAWING, DOKUMENTE.md).

Ablauf: Teile und Bezugssystem bestimmen → Ansichten planen (falls automatisch) → projizieren → automatische Maße
erzeugen und mit Kevins/Agent-Maßen zusammenführen → Bezüge neu zuordnen (verwaiste markieren) → Maßstab und Format
wählen, Ansichten nach Projektionsmethode 1 anordnen (mit Platz für die Maße) → Maße in Reihen packen, Hinweislinien
kollisionsfrei setzen → Rahmen, Schriftfeld, Stückliste, Positionsnummern → Nutzlast.

Alle Koordinaten der Ausgabe in Blatt-mm (Ursprung links unten, y oben).
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung import bezuege as bz
from kevcad_kernel.zeichnung import blatt as bl
from kevcad_kernel.zeichnung import darstellung as dr
from kevcad_kernel.zeichnung import dokument as dok
from kevcad_kernel.zeichnung.ansichten import NAMEN, RASTER, Blick, blick
from kevcad_kernel.zeichnung.bemassung import ansichten_planen, auto_masse, auto_masse_gruppe
from kevcad_kernel.zeichnung.geo2d import Belegung, Rechteck, clip_bereiche, rechteck_von, textbox, textbreite
from kevcad_kernel.zeichnung.hausregeln import Hausregeln, aktiv, setze, zuruecksetzen
from kevcad_kernel.zeichnung.merkmale import Merkmale, zahl
from kevcad_kernel.zeichnung.projektion import LINIENARTEN, Projektion, mittellinien, projiziere
from kevcad_kernel.zeichnung.szene import Szene, Teil, gruppen_merkmale
from kevcad_kernel.zeichnung.teilsystem import Teilsystem

LINIEN_REIHENFOLGE = LINIENARTEN
ABSTAND_ANSICHTEN = 8.0  # mindestens zwischen den Platzbedarfen benachbarter Ansichten
RAND_ANSICHT = 4.0  # Platz um eine Ansicht ohne Maße
LUECKE_BRUCH = 8.0  # Blatt-mm für eine Unterbrechung
EXAKT_BUDGET_S = 1.5
FORMAT_RANG = {"A4": 0, "A3": 1, "A2": 2, "A1": 3, "A0": 4}  # Zeitbudget der exakten Verdeckungsrechnung je Einzelteil-Ansicht


@dataclass
class Ergebnis:
    blatt: dict[str, Any]
    kopf: dict[str, Any]  # DRAWING ohne type/seq/reply_to
    nutzlast: bytes
    geaendert: bool = False  # Blatt-Datei muss neu geschrieben werden
    ms: float = 0.0
    hinweise: list[str] = field(default_factory=list)
    ansichten: dict[str, Any] = field(default_factory=dict)  # id → _Ansicht (für Klicks)
    system: Teilsystem | None = None
    merkmale: dict[str, Merkmale] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------------------------
# Ansicht auf dem Blatt
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Ansicht:
    e: dict[str, Any]
    blick: Blick
    proj: Projektion
    s: float = 1.0
    brueche: list[tuple[float, float]] = field(default_factory=list)
    mitte: np.ndarray = field(default_factory=lambda: np.zeros(2))
    titel: str | None = None
    mitte_linien: list[np.ndarray] = field(default_factory=list)  # Modell-2D, nach der Maßstabswahl
    zusatz: dict[str, list[np.ndarray]] = field(default_factory=dict)  # Modell-2D je Linienart (Schnittverlauf …)
    schraffur_ringe: list[list[np.ndarray]] = field(default_factory=list)  # Schnittflächen je Teil (Modell-2D)

    @property
    def id(self) -> str:
        return str(self.e["id"])

    @property
    def art(self) -> str:
        return str(self.e.get("art"))

    @property
    def rahmen_m(self) -> tuple[float, float, float, float]:
        r = self.proj.rahmen
        if r[2] - r[0] < 1e-6 and r[3] - r[1] < 1e-6:
            return (r[0] - 1, r[1] - 1, r[2] + 1, r[3] + 1)
        return r

    def gx(self, x: Any) -> Any:
        """Modell-x nach Unterbrechungen (Modell-mm, Lücke = LUECKE_BRUCH auf dem Blatt)."""
        x = np.asarray(x, dtype=float)
        out = x.copy()
        L = LUECKE_BRUCH / self.s
        for a, b in self.brueche:
            out = np.where(x >= b, out - ((b - a) - L), out)
            inn = (x > a) & (x < b)
            out = np.where(inn, out - (x - a) + L * (x - a) / (b - a), out)
        return out

    @property
    def groesse(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.rahmen_m
        return (float(self.gx(x1) - self.gx(x0)) * self.s, (y1 - y0) * self.s)

    def blatt(self, xy: Any) -> np.ndarray:
        p = np.asarray(xy, dtype=float)
        x0, y0, x1, y1 = self.rahmen_m
        cx = (float(self.gx(x0)) + float(self.gx(x1))) / 2
        cy = (y0 + y1) / 2
        if p.ndim == 1:
            return np.array([self.mitte[0] + self.s * (float(self.gx(p[0])) - cx), self.mitte[1] + self.s * (p[1] - cy)])
        return np.stack([self.mitte[0] + self.s * (self.gx(p[:, 0]) - cx), self.mitte[1] + self.s * (p[:, 1] - cy)],
                        axis=1)

    def blatt3(self, p_lokal: Any) -> np.ndarray:
        return self.blatt(self.blick.projiziere(p_lokal))

    @property
    def rahmen(self) -> Rechteck:
        w, h = self.groesse
        return Rechteck(self.mitte[0] - w / 2, self.mitte[1] - h / 2, self.mitte[0] + w / 2, self.mitte[1] + h / 2)

    def linien_blatt(self) -> dict[str, list[np.ndarray]]:
        out: dict[str, list[np.ndarray]] = {a: [] for a in LINIENARTEN}
        quellen = {a: list(self.proj.linien.get(a) or []) for a in LINIENARTEN}
        quellen["mitte"] = list(self.mitte_linien) or quellen["mitte"]
        x0, y0, x1, y1 = self.rahmen_m
        ue = 3.0 / self.s
        for r in self.e.get("_symmetrie") or []:
            if r == "x":
                ym = (y0 + y1) / 2
                quellen["mitte"].append(np.array([[x0 - ue, ym], [x1 + ue, ym]]))
            else:
                xm = (x0 + x1) / 2
                quellen["mitte"].append(np.array([[xm, y0 - ue], [xm, y1 + ue]]))
        for a, ls in self.zusatz.items():
            quellen.setdefault(a, []).extend(ls)
        for art, ls in quellen.items():
            for pl in ls:
                for stueck in clip_bereiche(pl, self.brueche, 0):
                    out[art].append(self.blatt(stueck))
        if self.schraffur_ringe:
            from kevcad_kernel.zeichnung.schnitt import schraffur_linien

            out["schraffur"] += schraffur_linien(self)
        # Bruchlinien (ISO 128-24: schmale Freihandlinie) an beiden Rändern jeder Unterbrechung
        if self.brueche:
            x0, y0, x1, y1 = self.rahmen_m
            ys = np.linspace(y0 - 1.5 / self.s, y1 + 1.5 / self.s, 25)
            amp = 0.8 / self.s
            for a, b in self.brueche:
                for x in (a, b):
                    wellen = x + amp * np.sin((ys - ys[0]) / (ys[-1] - ys[0] + 1e-9) * 2 * math.pi * 2)
                    pts = np.stack([wellen, ys], axis=1)
                    mapped = self.blatt(np.stack([np.full_like(ys, x), ys], axis=1))
                    mapped[:, 0] += (wellen - x) * self.s
                    out["bruch"].append(mapped)
                    _ = pts
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------------------------------------------------


def rechne(blatt_in: dict[str, Any], szene: Szene, *, stand_extra: str = "",
           regeln: Hausregeln | None = None) -> Ergebnis:
    """Blatt rechnen (Modulbeschreibung). ``regeln``: Hausregeln des Projekts (sonst Standard)."""
    token = setze(regeln) if regeln is not None else None
    try:
        return _rechne(blatt_in, szene, stand_extra)
    finally:
        if token is not None:
            zuruecksetzen(token)


def _rechne(blatt_in: dict[str, Any], szene: Szene, stand_extra: str) -> Ergebnis:
    t0 = time.perf_counter()
    blatt = dok.normalisiere(json.loads(json.dumps(blatt_in, default=_json_default)))
    vorher = json.dumps(dok.zum_speichern(blatt), sort_keys=True, ensure_ascii=False, default=_json_default)
    hinweise: list[str] = []
    inhalt = blatt["inhalt"]
    art = inhalt["art"]
    teile = szene.auswahl(inhalt["teile"])
    if art == "zusammenbau" and not inhalt["teile"]:
        teile = [t for t in szene.teile.values() if not _umgebung(t.name)]
    if art == "zusammenbau":
        teile = [t for t in teile if not _umgebung(t.name)]
    merkmale: dict[str, Merkmale] = {}
    if art == "teil":
        teile = teile[:1]
        if teile:
            m = szene.merkmale(teile[0].name)
            if m is not None:
                merkmale[teile[0].name] = m
        system = merkmale[teile[0].name].system if teile and teile[0].name in merkmale else Teilsystem(
            np.eye(3), np.zeros(3), np.ones(3), "welt")
        gruppe = None
    else:
        gruppe = gruppen_merkmale(teile, inhalt["teile"][0] if inhalt["teile"] else "Zusammenbau")
        system = gruppe.system
        merkmale[""] = gruppe
        for t in teile:  # Bezüge auf Einzelteile (Kevins Maße im Zusammenbau)
            if any(any(b.get("teil") == t.name for b in m.get("bezuege") or []) for m in blatt["masse"]):
                mm = szene.merkmale(t.name)
                if mm is not None:
                    merkmale[t.name] = mm
    if not teile:
        hinweise.append("Kein Teil des Blatts ist im aktuellen Lauf vorhanden: "
                        + ", ".join(inhalt["teile"] or ["(leer)"]))
    # Schriftfeld aus Projekt, Stückliste, Material
    _schriftfeld_fuellen(blatt, szene, teile, art)
    # Ansichten
    if blatt["auto"]["ansichten"] and not blatt["ansichten"]:
        plan = ansichten_planen(merkmale[teile[0].name], "teil") if art == "teil" and teile and \
            teile[0].name in merkmale else ansichten_planen(gruppe or merkmale.get(""), art) if teile else []
        blatt["ansichten"] = plan
    ansichten = _projektionen(blatt, teile, system, art)
    # Maße
    if blatt["auto"]["masse"] and teile:
        if art == "teil" and teile[0].name in merkmale:
            neu, allgemein = auto_masse(merkmale[teile[0].name], teile[0].name, blatt["ansichten"])
        else:
            neu, allgemein = auto_masse_gruppe(gruppe, "", blatt["ansichten"]), []  # type: ignore[arg-type]
        _auto_zusammenfuehren(blatt, neu)
        blatt["allgemein"] = allgemein
    elif not blatt["auto"]["masse"]:
        pass
    _neu_zuordnen(blatt, merkmale, teile, art)
    # Maßstab, Format, Anordnung
    hauptmerk = merkmale.get(teile[0].name) if art == "teil" and teile else gruppe
    arbeit = _vorbereiten(blatt, ansichten, merkmale, system, art, teile)
    lage = _anordnen(blatt, ansichten, arbeit, hauptmerk, art, szene, teile, hinweise)
    # Maße zeichnen
    beleg = Belegung()
    beleg.grenze = lage.get("flaeche")
    for r in lage["reserviert"]:
        beleg.rechteck(r, "tabelle")
    for v in ansichten.values():
        lin = v.linien_blatt()
        beleg.strecken(lin["sichtbar"], "geo")
        beleg.strecken(lin["verdeckt"], "verdeckt")
    grafiken = _masse_zeichnen(blatt, ansichten, arbeit, beleg, system)
    # Blatt: Rahmen, Schriftfeld, Tabellen, Positionsnummern, Ansichtstitel, Notizen
    deko = _dekoration(blatt, ansichten, szene, teile, art, lage, beleg, system)
    kopf, nutzlast = _ausgabe(blatt, ansichten, grafiken, deko, lage, szene, teile, stand_extra)
    kopf["hinweise"] = hinweise + lage.get("hinweise", [])
    from kevcad_kernel.zeichnung.pruefung import pruefe

    kopf["pruefung"] = pruefe(blatt, hauptmerk if art == "teil" else None, ansichten, grafiken, deko.texte,
                              lage.get("flaeche"))
    nachher = json.dumps(dok.zum_speichern(blatt), sort_keys=True, ensure_ascii=False, default=_json_default)
    ms = (time.perf_counter() - t0) * 1000.0
    kopf["ms"] = round(ms, 1)
    return Ergebnis(blatt, kopf, nutzlast, vorher != nachher, ms, kopf["hinweise"], ansichten, system, merkmale)


def _json_default(o: Any) -> Any:
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o).__name__)


def kurznamen(namen: list[str]) -> list[str]:
    """Kürzeste eindeutige Namensenden: „Lenkrolle 1/Lenksperre (Druck)“ statt viermal „Lenksperre (Druck)“."""
    teile = [n.split("/") for n in namen]
    for k in range(1, max(len(t) for t in teile) + 1):
        kurz = ["/".join(t[-k:]) for t in teile]
        if len(set(kurz)) == len(kurz):
            return kurz
    return list(namen)


def _umgebung(name: str) -> bool:
    """Umgebung und Hilfsgeometrie gehören nicht in den Zusammenbau (Boden, Wände der Szene, Skizzen)."""
    kopf = name.split("/", 1)[0].lower()
    return kopf in ("umgebung", "skizze", "hilfe", "hilfsgeometrie")


# ---------------------------------------------------------------------------------------------------------------------
# Schriftfeld
# ---------------------------------------------------------------------------------------------------------------------


def _schriftfeld_fuellen(blatt: dict[str, Any], szene: Szene, teile: list[Teil], art: str) -> None:
    """Werte, die Kev CAD kennt, ergänzen (Kevins Einträge bleiben): Projekt, Version, Werkstoff, Halbzeug, Masse,
    Stückzahl, Zeichnungsnummer."""
    sf = blatt["schriftfeld"]
    proj = szene.projekt or {}
    auto = blatt.setdefault("_sf_auto", {})
    gesetzt = set(blatt.get("schriftfeld_fest") or [])

    def setze(feld: str, wert: Any) -> None:
        if feld in gesetzt:
            return
        if wert is None or wert == "":
            return
        sf[feld] = wert

    setze("projekt", proj.get("name"))
    setze("version", proj.get("version"))
    if not sf.get("zeichnungsnummer"):
        kurz = "".join(w[0] for w in str(proj.get("name") or "KC").split() if w)[:4].upper() or "KC"
        sf["zeichnungsnummer"] = f"{kurz}-{blatt['id'][:24].upper()}"
    if art == "teil" and teile:
        t = teile[0]
        ln = szene.bom_zeile(t.name)
        st = t.kopf.get("stock") or {}
        mat = (ln or {}).get("material") or t.kopf.get("material")
        if t.kopf.get("druckteil"):
            dt = t.kopf["druckteil"]
            mat = (ln or {}).get("material") or str(dt.get("material") or "").upper()
            setze("halbzeug", "3D-Druck (" + ("Harzdruck" if dt.get("verfahren") == "harzdruck" else "FDM") + ")")
        elif st:
            setze("halbzeug", (t.katalog or {}).get("name") or st.get("name"))
        setze("werkstoff", mat)
        setze("masse_g", round(t.masse_g, 1) if t.masse_g is not None else None)
        n = len(szene.gleiche_teile(t.name))
        setze("stueckzahl", n)
    else:
        masse = [t.masse_g for t in teile if t.masse_g is not None]
        setze("masse_g", round(sum(masse), 1) if masse else None)
        setze("stueckzahl", 1)
    _ = auto


# ---------------------------------------------------------------------------------------------------------------------
# Projektionen
# ---------------------------------------------------------------------------------------------------------------------


def _projektionen(blatt: dict[str, Any], teile: list[Teil], system: Teilsystem, art: str) -> dict[str, _Ansicht]:
    out: dict[str, _Ansicht] = {}
    if not teile:
        return out
    formen = {}
    schluessel = {}
    for t in teile:
        formen[t.name] = system.form_lokal(t.form)
        schluessel[t.name] = f"{t.key}|{system.schluessel}"
    einzel = art == "teil"
    for e in blatt["ansichten"]:
        if e["art"] in ("schnitt", "einzelheit"):
            continue
        b = blick(e["art"])
        verdeckt = bool(e.get("verdeckt", einzel)) and einzel and b.orthogonal
        # Einzelteile: exakt mit Zeitbudget im Hilfsprozess, sonst Netz (DOKUMENTE.md 1.1); Zusammenbau: Netz
        p = projiziere(formen, b, verdeckt=verdeckt, glatt=einzel, mittel=False, je_teil=not einzel,
                       schluessel=schluessel, exakt=EXAKT_BUDGET_S if einzel else False)
        out[e["id"]] = _Ansicht(e, b, p, titel=e.get("titel"))
    # Schnitte und Einzelheiten
    from kevcad_kernel.zeichnung.schnitt import einzelheit, schnittansicht

    for e in blatt["ansichten"]:
        if e["art"] == "schnitt":
            v = schnittansicht(e, formen, schluessel, out)
            if v is not None:
                out[e["id"]] = v
        elif e["art"] == "einzelheit":
            v = einzelheit(e, out)
            if v is not None:
                out[e["id"]] = v
    _ = Projektion
    return out


def _mittellinien(v: _Ansicht, teile: list[Teil], system: Teilsystem) -> None:
    if not v.e.get("mittellinien", True) or not v.blick.orthogonal or v.art in ("schnitt", "einzelheit"):
        v.mitte_linien = []
        return
    formen = [(t.name, system.form_lokal(t.form).wrapped) for t in teile]
    v.mitte_linien = mittellinien(formen, v.blick, ueberstand=2.5 / v.s)


# ---------------------------------------------------------------------------------------------------------------------
# Maße: zusammenführen und neu zuordnen
# ---------------------------------------------------------------------------------------------------------------------


def _auto_zusammenfuehren(blatt: dict[str, Any], neu: list[dict[str, Any]]) -> None:
    from kevcad_kernel.zeichnung.bearbeiten import passt_unterdrueckt

    alt = blatt["masse"]
    unterdrueckt = list(blatt.get("unterdrueckt") or [])
    neu = [n for n in neu if not any(passt_unterdrueckt(u, n) for u in unterdrueckt)]
    weg: set[str] = set()
    alt_auto = {m["schluessel"]: m for m in alt if m.get("quelle") == "auto" and m.get("schluessel")}
    ids = {m.get("id") for m in alt if m.get("id")}
    erg: list[dict[str, Any]] = []
    neu_nach = {n["schluessel"]: n for n in neu if n["schluessel"] not in weg}
    for m in alt:
        if m.get("quelle") == "auto" and m.get("schluessel"):
            n = neu_nach.pop(m["schluessel"], None)
            if n is None:
                if m.get("fest"):
                    erg.append(m)  # Kevin hat es verschoben: bleibt, auch wenn das Merkmal fehlt (dann verwaist)
                else:
                    ids.discard(m.get("id"))
                continue
            n = dict(n)
            n["id"] = m["id"]
            if m.get("fest"):
                for k in ("versatz", "text_versatz", "seite", "fest", "text", "toleranz"):
                    if k in m:
                        n[k] = m[k]
            if m.get("anker"):
                n["anker"] = m["anker"]
            erg.append(n)
        else:
            erg.append(m)
    for n in neu_nach.values():
        n = dict(n)
        n["id"] = dok.naechste("m", ids)
        ids.add(n["id"])
        erg.append(n)
    blatt["masse"] = erg


def _neu_zuordnen(blatt: dict[str, Any], merkmale: dict[str, Merkmale], teile: list[Teil], art: str) -> None:
    namen = {t.name for t in teile}
    haupt = teile[0].name if art == "teil" and teile else ""
    for m in blatt["masse"]:
        ok = True
        neu = []
        for b in m.get("bezuege") or []:
            teil = b.get("teil") if b.get("teil") is not None else haupt
            if art == "teil" and teil != haupt and teil in ("", None):
                teil = haupt
            mm = merkmale.get(teil if teil in merkmale else ("" if art != "teil" else haupt))
            if teil and teil not in namen and teil not in merkmale:
                ok = False
                neu.append(b)
                continue
            nb, treffer = bz.zuordnen(b, mm)
            if nb is None:
                ok = False
                neu.append(b)
            else:
                neu.append(nb)
        m["bezuege"] = neu
        m["verwaist"] = not ok or not neu
    for n in blatt["notizen"]:
        z = n.get("zeiger")
        if isinstance(z, dict) and z.get("teil") is not None:
            mm = merkmale.get(z.get("teil") or haupt)
            nb, _ = bz.zuordnen(z, mm)
            n["verwaist"] = nb is None
            if nb is not None:
                n["zeiger"] = nb


# ---------------------------------------------------------------------------------------------------------------------
# Vorbereitung der Maße (Elemente auflösen, Art der Darstellung)
# ---------------------------------------------------------------------------------------------------------------------


@dataclass
class _Arbeit:
    m: dict[str, Any]
    v: _Ansicht | None
    els: list[bz.Element | None]
    form: str  # linear | kette | hinweis | winkel | text | verwaist
    seite: str | None = None
    versatz: float | None = None
    grafik: dr.MassGrafik | None = None


def _element(b: dict[str, Any], merkmale: dict[str, Merkmale], haupt: str, art: str) -> bz.Element | None:
    teil = b.get("teil") if b.get("teil") is not None else haupt
    mm = merkmale.get(teil) if teil in merkmale else merkmale.get("" if art != "teil" else haupt)
    if mm is None:
        return None
    _, treffer = bz.zuordnen(b, mm)
    if treffer is None:
        return None
    el = bz.element(treffer, mm, teil or "")
    sub = b.get("element")
    if el is not None and sub and el.merkmal is not None and el.merkmal.art in ("tasche", "absatz"):
        w = el.merkmal.werte
        j = int(sub[2:])
        lo, hi = np.asarray(w["lo"], dtype=float), np.asarray(w["hi"], dtype=float)
        x = lo[j] if sub.startswith("lo") else hi[j]
        i = int(w["achse"])
        rest = [k for k in range(3) if k not in (i, j)]
        ecken = []
        for z in (lo[i], hi[i]):
            for r in (lo[rest[0]], hi[rest[0]]):
                p = np.zeros(3)
                p[j], p[i], p[rest[0]] = x, z, r
                ecken.append(p)
        n = np.zeros(3)
        n[j] = -1.0 if sub.startswith("lo") else 1.0
        sysw = mm.system
        ecken_w = sysw.welt(np.array(ecken))
        el = bz.Element("ebene", teil or "", ecken_w.mean(axis=0), sysw.richtung_welt(n), None, ecken_w, el.merkmal)
    return el


def _vorbereiten(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], merkmale: dict[str, Merkmale],
                 system: Teilsystem, art: str, teile: list[Teil]) -> list[_Arbeit]:
    haupt = teile[0].name if art == "teil" and teile else ""
    out = []
    for m in blatt["masse"]:
        v = ansichten.get(str(m.get("ansicht")))
        els = [_element(b, merkmale, haupt, art) for b in m.get("bezuege") or []]
        if v is None or m.get("verwaist") or any(e is None for e in els) or not els:
            out.append(_Arbeit(m, v, els, "verwaist"))
            continue
        a = m["art"]
        if a in ("linear",) or (a in ("durchmesser",) and len(els) == 2):
            form = "linear"
        elif a == "bezugskette":
            form = "kette"
        elif a == "winkel":
            form = "winkel"
        elif a == "koordinaten":
            form = "text"
        else:
            form = "hinweis"
        if form == "linear" and len(els) < 2:
            form = "hinweis"
        out.append(_Arbeit(m, v, els, form, seite=m.get("seite"), versatz=m.get("versatz")))
    return out


def _richtung3(v: _Ansicht, richtung: str, system: Teilsystem) -> np.ndarray:
    """Weltrichtung der Blatt-x- bzw. -y-Achse einer Ansicht."""
    d = np.asarray(v.blick.rechts if richtung == "x" else v.blick.oben, dtype=float)
    return system.richtung_welt(d)


def _ankerpunkte(el: bz.Element, v: _Ansicht, system: Teilsystem) -> np.ndarray:
    pts = el.ecken if el.ecken is not None and el.typ in ("ebene", "linie", "box") else np.array([el.p])
    return v.blatt3(system.lokal(np.asarray(pts, dtype=float).reshape(-1, 3)))


def _anker(el: bz.Element, v: _Ansicht, system: Teilsystem, richtung: str, seite: str) -> np.ndarray:
    P = _ankerpunkte(el, v, system)
    k = 1 if richtung == "x" else 0  # Koordinate quer zur Messrichtung
    if seite in ("unten", "links"):
        return P[int(np.argmin(P[:, k]))]
    return P[int(np.argmax(P[:, k]))]


def _wert_linear(e1: bz.Element, e2: bz.Element, v: _Ansicht, system: Teilsystem, richtung: str) -> float:
    if richtung in ("x", "y"):
        u = _richtung3(v, richtung, system)
        return abs(float((e2.p - e1.p) @ u))
    a = v.blick.projiziere(system.lokal(e1.p))
    b = v.blick.projiziere(system.lokal(e2.p))
    return float(np.linalg.norm(b - a))


def _masstext(m: dict[str, Any], wert: float | None, vorsatz: str = "") -> str:
    t = m.get("text")
    w = "" if wert is None else vorsatz + zahl(wert, 2)
    if t:
        t = str(t).replace("<>", w)
    else:
        t = w
    tol = m.get("toleranz")
    if tol:
        t = f"{t} {tol}"
    return t


def _richtung_auto(m: dict[str, Any], els: list[bz.Element], v: _Ansicht, system: Teilsystem) -> str:
    r = m.get("richtung")
    if r in ("x", "y", "frei"):
        return r
    a = v.blatt3(system.lokal(els[0].p))
    b = v.blatt3(system.lokal(els[1].p))
    d = np.abs(b - a)
    return "x" if d[0] >= d[1] else "y"


# ---------------------------------------------------------------------------------------------------------------------
# Packen der linearen Maße in Reihen je Seite einer Ansicht
# ---------------------------------------------------------------------------------------------------------------------


def _seite_waehlen(a: _Arbeit, system: Teilsystem, richtung: str) -> str:
    if a.seite in ("unten", "oben", "links", "rechts"):
        s = a.seite
        if richtung == "x" and s in ("links", "rechts"):
            s = "unten"
        if richtung == "y" and s in ("unten", "oben"):
            s = "links"
        return s
    v = a.v
    assert v is not None
    r = v.rahmen
    pts = np.array([v.blatt3(system.lokal(e.p)) for e in a.els if e is not None])
    if richtung == "x":
        return "oben" if float(pts[:, 1].mean()) > (r.y0 + r.y1) / 2 + 1e-6 else "unten"
    return "rechts" if float(pts[:, 0].mean()) > (r.x0 + r.x1) / 2 + 1e-6 else "links"


def _packen(arbeit: list[_Arbeit], ansichten: dict[str, _Ansicht], system: Teilsystem) -> dict[str, dict[str, float]]:
    """Reihen je Seite: kurze Maße nah am Körper, lange außen; Intervalle einer Reihe überlappen sich nicht. Liefert je
    Ansicht den Platzbedarf je Seite (Blatt-mm ab Rahmen)."""
    bedarf: dict[str, dict[str, float]] = {vid: {"unten": 0.0, "oben": 0.0, "links": 0.0, "rechts": 0.0}
                                          for vid in ansichten}
    gruppen: dict[tuple[str, str], list[tuple[_Arbeit, float, float, float, str]]] = {}
    for a in arbeit:
        if a.form not in ("linear", "kette") or a.v is None:
            continue
        v = a.v
        richtung = _richtung_auto(a.m, a.els, v, system) if a.form == "linear" else (a.m.get("richtung") or "x")
        if richtung == "frei":
            continue
        a.m["_richtung"] = richtung
        seite = _seite_waehlen(a, system, richtung)
        a.seite = seite
        k = 0 if richtung == "x" else 1
        pts = [_anker(e, v, system, richtung, seite) for e in a.els]
        lo = min(float(p[k]) for p in pts)
        hi = max(float(p[k]) for p in pts)
        if a.form == "kette":
            texte = [zahl(_wert_linear(a.els[0], e, v, system, richtung)) for e in a.els[1:]]
            tiefe = max((textbreite(t, aktiv().schrifthoehe) for t in texte), default=5.0) + 3.0
        else:
            wert = _wert_linear(a.els[0], a.els[1], v, system, richtung)
            text = _masstext(a.m, wert, "Ø" if a.m["art"] == "durchmesser" else "")
            tw = textbreite(text, aktiv().schrifthoehe)
            if hi - lo < 2 * aktiv().pfeil_laenge + tw + 2.0:
                hi += aktiv().pfeil_laenge + tw + 6.0  # Zahl außen
            tiefe = 0.0
        prio = int(a.m.get("_prio") or (100 if str(a.m.get("schluessel", "")).startswith("huelle") else 50))
        gruppen.setdefault((v.id, seite), []).append((a, lo - 1.5, hi + 1.5, tiefe, str(prio)))
    for (vid, seite), liste in gruppen.items():
        v = ansichten[vid]
        r = v.rahmen
        # feste Maße (Versatz gesetzt) zuerst als belegt, die übrigen sortiert: Priorität, dann Spannweite
        reihen: list[list[tuple[float, float]]] = []
        reihen_tiefe: list[float] = []
        frei = [x for x in liste if x[0].versatz is None or not (x[0].m.get("fest") or x[0].m.get("quelle") != "auto")]
        fest = [x for x in liste if x not in frei]
        frei.sort(key=lambda x: (int(x[4]), x[2] - x[1]))
        for a, lo, hi, tiefe, _ in frei:
            for t, reihe in enumerate(reihen):
                if all(hi <= x0 or lo >= x1 for x0, x1 in reihe) and reihen_tiefe[t] == 0.0 and tiefe == 0.0:
                    reihe.append((lo, hi))
                    a.m["_reihe"] = t
                    break
            else:
                reihen.append([(lo, hi)])
                reihen_tiefe.append(tiefe)
                a.m["_reihe"] = len(reihen) - 1
        # Abstand je Reihe
        abst = []
        d = aktiv().erste
        for t in range(len(reihen)):
            abst.append(d)
            d += aktiv().weitere + (reihen_tiefe[t] if t < len(reihen_tiefe) else 0.0)
        for a, lo, hi, tiefe, _ in frei:
            t = a.m["_reihe"]
            off = abst[t]
            richtung = a.m["_richtung"]
            p1 = _anker(a.els[0], v, system, richtung, seite)
            if seite == "unten":
                a.versatz = (r.y0 - off) - float(p1[1])
            elif seite == "oben":
                a.versatz = (r.y1 + off) - float(p1[1])
            elif seite == "links":
                a.versatz = (r.x0 - off) - float(p1[0])
            else:
                a.versatz = (r.x1 + off) - float(p1[0])
            a.m["_relativ"] = off
        rand = (abst[-1] + aktiv().schrifthoehe + 2.5 + (reihen_tiefe[-1] if reihen_tiefe else 0.0)) if reihen else 0.0
        for a, lo, hi, tiefe, _ in fest:
            richtung = a.m["_richtung"]
            p1 = _anker(a.els[0], v, system, richtung, seite)
            pos = float(p1[1] if richtung == "x" else p1[0]) + float(a.versatz or 0.0)
            ausserhalb = {"unten": r.y0 - pos, "oben": pos - r.y1, "links": r.x0 - pos, "rechts": pos - r.x1}[seite]
            rand = max(rand, ausserhalb + aktiv().schrifthoehe + 2.5)
        bedarf[vid][seite] = max(bedarf[vid][seite], rand)
    return bedarf


# ---------------------------------------------------------------------------------------------------------------------
# Maßstab, Format, Anordnung
# ---------------------------------------------------------------------------------------------------------------------


def _brueche_planen(v: _Ansicht, merk: Merkmale | None, verfuegbar: float) -> None:
    """Unterbrochene Ansicht für Stangenware (ISO 128-30: lange, gleichförmige Teile verkürzt darstellen): Bereiche um
    Merkmale und Enden bleiben, lange Abschnitte dazwischen entfallen, die Maße zeigen die wahre Länge."""
    v.brueche = []
    if merk is None or merk.system.art != "stange" or v.art not in ("vorn", "oben", "hinten", "unten"):
        return
    x0, y0, x1, y1 = v.rahmen_m
    L = x1 - x0
    if L * v.s <= verfuegbar:
        return
    quer = max(y1 - y0, 1.0)
    rand = max(1.5 * quer, 12.0 / v.s)
    lagen = [x0, x1]
    for m in merk.von_art("bohrung", "einsatztasche", "langloch", "muttertasche", "tasche", "absatz"):
        lagen.append(float(np.asarray(m.signatur["mitte"])[0]))
    bereiche = sorted((max(x0, p - rand), min(x1, p + rand)) for p in lagen)
    behalten: list[list[float]] = []
    for a, b in bereiche:
        if behalten and a <= behalten[-1][1] + 2 * rand:
            behalten[-1][1] = max(behalten[-1][1], b)
        else:
            behalten.append([a, b])
    v.brueche = [(behalten[i][1], behalten[i + 1][0]) for i in range(len(behalten) - 1)
                 if behalten[i + 1][0] - behalten[i][1] > 3 * LUECKE_BRUCH / v.s]


def _verfuegbar(fmt: str, ausr: str, reserviert: list[Rechteck]) -> tuple[float, float, Rechteck]:
    W, H = bl.blattgroesse(fmt, ausr)
    z = bl.zeichenflaeche(W, H)
    return W, H, z


def _anordnen(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], arbeit: list[_Arbeit], merk: Merkmale | None,
              art: str, szene: Szene, teile: list[Teil], hinweise: list[str]) -> dict[str, Any]:
    """Maßstab und Format wählen (falls automatisch), Ansichten anordnen. Liefert Blattgröße, reservierte Bereiche
    (Schriftfeld, Tabellen), Maßstab."""
    system = merk.system if merk is not None else Teilsystem(np.eye(3), np.zeros(3), np.ones(3), "welt")
    auto_ms = bool(blatt["auto"].get("massstab", True))
    auto_fmt = bool(blatt["auto"].get("format", True))
    kandidaten_fmt = [(blatt["format"], blatt["ausrichtung"])]
    if auto_fmt:
        kandidaten_fmt = [("A4", "quer"), ("A4", "hoch"), ("A3", "quer"), ("A2", "quer"), ("A1", "quer")]
    if auto_ms:
        groesse = float(np.max(merk.groesse)) if merk is not None and len(merk.groesse) else 100.0
        kleinst = _kleinstes_merkmal(merk)
        # Vergrößern nur, bis das Teil etwa 50 mm groß ist oder kleine Merkmale lesbar werden (ISO 5455: natürliche
        # Größe bevorzugt)
        s_max = 1.0
        for m in ("2:1", "5:1", "10:1", "20:1"):
            f = bl.massstab_faktor(m)
            if groesse * s_max < 50 or (kleinst is not None and kleinst * s_max < 2.0 and groesse * f < 150):
                s_max = f
            else:
                break
        massstaebe = [bl.massstab_faktor(m) for m in bl.MASSSTAEBE if bl.massstab_faktor(m) <= s_max + 1e-9]
    else:
        massstaebe = [bl.massstab_faktor(blatt["massstab"])]
    stueckliste = art in ("zusammenbau", "baugruppe")
    beste = None
    versuche = []
    for fmt, ausr in kandidaten_fmt:
        for s in massstaebe:
            erg = _versuch(blatt, ansichten, arbeit, merk, system, art, szene, teile, fmt, ausr, s, stueckliste)
            if erg is not None:
                versuche.append((fmt, ausr, s, erg))
                break
        if versuche and not auto_fmt:
            break
    if versuche:
        # Format: A4 bevorzugt; A3 nur, wenn es mindestens den doppelten Maßstab erlaubt und A4 sonst klein wird
        a4 = [x for x in versuche if x[0] == "A4"]
        groessere = [x for x in versuche if x[0] != "A4"]
        if a4:
            # gleicher Maßstab: die Ausrichtung, die zum Seitenverhältnis der Ansichten passt (lange Teile quer)
            beste = max(a4, key=lambda x: (x[2], (x[1] == "quer") == x[3]["breiter"]))
            if groessere:
                # A3 statt A4, wenn das Teil auf A4 klein würde (größte Abmessung unter 80 mm auf dem Blatt) oder
                # kleine Merkmale unlesbar (unter 1,5 mm) und A3 einen größeren Maßstab erlaubt
                g = min((x for x in groessere if x[2] > beste[2] + 1e-9), key=lambda x: FORMAT_RANG[x[0]],
                        default=None)
                kleinst = _kleinstes_merkmal(merk)
                gross = float(np.max(merk.groesse)) if merk is not None and len(merk.groesse) else 100.0
                if g is not None and (gross * beste[2] < 80.0 or (kleinst is not None and kleinst * beste[2] < 1.5)):
                    beste = g
        else:
            beste = max(groessere, key=lambda x: x[2]) if groessere else None
    if beste is None:
        # Notlösung: kleinster Maßstab auf dem größten Format, auch wenn es eng wird
        fmt, ausr = kandidaten_fmt[-1]
        s = massstaebe[-1]
        erg = _versuch(blatt, ansichten, arbeit, merk, system, art, szene, teile, fmt, ausr, s, stueckliste,
                       erzwingen=True)
        beste = (fmt, ausr, s, erg)
        hinweise.append("Ansichten passen nicht ohne Überlappung auf das Blatt; Maßstab oder Format von Hand wählen.")
    fmt, ausr, s, erg = beste
    if auto_fmt:
        blatt["format"], blatt["ausrichtung"] = fmt, ausr
    if auto_ms:
        blatt["massstab"] = bl.massstab_text(s)
    # Endgültig: Lage übernehmen, Mittellinien, Maße packen mit endgültigen Lagen
    for vid, (mitte, vs) in erg["lagen"].items():
        v = ansichten[vid]
        v.s = vs
        v.mitte = np.asarray(mitte, dtype=float)
    for vid, v in ansichten.items():
        e = v.e
        e["lage"] = [round(float(v.mitte[0]), 2), round(float(v.mitte[1]), 2)]
        if vid in erg.get("brueche", {}):
            v.brueche = erg["brueche"][vid]
        e["_brueche"] = v.brueche
        _mittellinien(v, teile, system)
    for vid in erg.get("weggelassen", []):
        ansichten.pop(vid, None)
    _packen(arbeit, ansichten, system)
    W, H = bl.blattgroesse(blatt["format"], blatt["ausrichtung"])
    return {"breite": W, "hoehe": H, "reserviert": erg["reserviert"], "massstab": s, "tabellen": erg["tabellen"],
            "hinweise": [], "weggelassen": erg.get("weggelassen", []), "flaeche": erg.get("flaeche")}


def _kleinstes_merkmal(merk: Merkmale | None) -> float | None:
    if merk is None:
        return None
    werte = []
    for m in merk.liste:
        if m.art in ("bohrung", "einsatztasche"):
            werte.append(float(m.werte["d"]))
        elif m.art == "fase":
            werte.append(float(m.werte["a"]) * 4)
        elif m.art == "radius":
            werte.append(float(m.werte["r"]) * 2)
    return min(werte) if werte else None


def _versuch(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], arbeit: list[_Arbeit], merk: Merkmale | None,
             system: Teilsystem, art: str, szene: Szene, teile: list[Teil], fmt: str, ausr: str, s: float,
             stueckliste: bool, erzwingen: bool = False) -> dict[str, Any] | None:
    W, H = bl.blattgroesse(fmt, ausr)
    z = bl.zeichenflaeche(W, H)
    sf = bl.schriftfeld_rechteck(W, H)
    reserviert = [sf.erweitert(1.0)]
    zeilen_ag = list(blatt.get("allgemein") or [])
    if blatt["schriftfeld"].get("notiz"):
        zeilen_ag = [str(blatt["schriftfeld"]["notiz"])] + zeilen_ag
    if art == "teil" and teile and len(szene.gleiche_teile(teile[0].name)) > 1 and not blatt["schriftfeld"].get("notiz"):
        zeilen_ag = ["gilt für: " + ", ".join(kurznamen(szene.gleiche_teile(teile[0].name)))] + zeilen_ag
    r_ag = bl.allgemeinangaben_rechteck(W, H, zeilen_ag)
    if r_ag is not None:
        reserviert.append(r_ag.erweitert(1.0))
    tabellen = []
    oben_rand = max(r.y1 for r in reserviert if r.x1 >= sf.x1 - 2)
    if stueckliste and szene.bom:
        positionen = _positionen(szene, teile)
        zeilen = bl.stueckliste_zeilen(szene.bom, positionen)
        hoehe = (len(zeilen) + 1) * 5.5
        if oben_rand + hoehe > z.y1:
            if not erzwingen:
                return None
        r = Rechteck(sf.x1 - sum(sp.breite for sp in bl.STUECKLISTE_SPALTEN), oben_rand, sf.x1, oben_rand + hoehe)
        reserviert.append(r.erweitert(1.0))
        tabellen.append({"art": "stueckliste", "rechteck": r, "zeilen": zeilen})
    # Bohrungstabelle bei vielen Bohrungen (Einzelteile)
    # Ansichten: Maßstab setzen, Brüche, Platzbedarf je Seite
    lagen: dict[str, tuple[tuple[float, float], float]] = {}
    brueche: dict[str, list[tuple[float, float]]] = {}
    for v in ansichten.values():
        v.s = s * _eigener_faktor(v, s)
        v.mitte = np.zeros(2)
        _brueche_planen(v, merk, z.breite - 60)
        brueche[v.id] = list(v.brueche)
    bedarf = _packen(arbeit, ansichten, system)
    # Hinweislinien brauchen etwas Platz außen
    hinweis_platz: dict[str, float] = {}
    for a in arbeit:
        if a.form == "hinweis" and a.v is not None:
            tw = max(textbreite(t, aktiv().schrifthoehe) for t in _hinweistext(a, system))
            w, h = a.v.groesse
            if min(w, h) >= 2.2 * (tw + 10.0):
                continue  # große Ansicht: die Angabe findet innen Platz
            hinweis_platz[a.v.id] = max(hinweis_platz.get(a.v.id, 0.0), tw + 14.0)
    raster = [v for v in ansichten.values() if v.art in RASTER and not v.e.get("fest")]
    frei = [v for v in ansichten.values() if v not in raster]

    def platz(v: _Ansicht) -> tuple[float, float, float, float]:
        if stueckliste and v.art.startswith("iso"):
            return (26.0, 26.0, 26.0, 26.0)  # Ring für die Positionsnummern
        b = bedarf.get(v.id, {})
        hp = hinweis_platz.get(v.id, 0.0)
        # Hinweislinien: Platz für den längsten Text rechts neben der Ansicht (außerhalb der Maßreihen), damit Angaben
        # nicht in der Geometrie stehen müssen
        return (max(b.get("links", 0.0), RAND_ANSICHT), max(b.get("rechts", 0.0) + (hp * 0.75 if hp else 0.0),
                                                              RAND_ANSICHT),
                max(b.get("unten", 0.0), RAND_ANSICHT), max(b.get("oben", 0.0), RAND_ANSICHT, 10.0 if hp else 0.0))

    # Raster der Projektionsmethode 1
    spalten: dict[int, list[_Ansicht]] = {}
    zeilen_: dict[int, list[_Ansicht]] = {}
    for v in raster:
        c, r_ = RASTER[v.art]
        spalten.setdefault(c, []).append(v)
        zeilen_.setdefault(r_, []).append(v)
    sp_geo = {}
    x = 0.0
    for c in sorted(spalten):
        vs = spalten[c]
        L = max(platz(v)[0] for v in vs)
        R = max(platz(v)[1] for v in vs)
        w = max(v.groesse[0] for v in vs)
        sp_geo[c] = x + L + w / 2
        x += L + w + R + ABSTAND_ANSICHTEN
    block_w = x - ABSTAND_ANSICHTEN if spalten else 0.0
    ze_geo = {}
    y = 0.0
    for r_ in sorted(zeilen_):  # von oben nach unten
        vs = zeilen_[r_]
        T = max(platz(v)[3] for v in vs)
        B = max(platz(v)[2] for v in vs)
        h = max(v.groesse[1] for v in vs)
        ze_geo[r_] = -(y + T + h / 2)
        y += T + h + B + ABSTAND_ANSICHTEN
    block_h = y - ABSTAND_ANSICHTEN if zeilen_ else 0.0
    blocks: list[tuple[str, Rechteck, dict[str, tuple[float, float]]]] = []
    if raster:
        rel = {v.id: (sp_geo[RASTER[v.art][0]], ze_geo[RASTER[v.art][1]]) for v in raster}
        blocks.append(("raster", Rechteck(0, -block_h, block_w, 0), rel))
    belegt = list(reserviert)
    platzierte: dict[str, tuple[float, float]] = {}
    # Raster: in der freien Fläche oben links bzw. mittig über dem Schriftfeld
    rand = 4.0
    flaeche = Rechteck(z.x0 + rand, z.y0 + rand, z.x1 - rand, z.y1 - rand)
    if blocks:
        _, rb, rel = blocks[0]
        pos = _finde_platz(rb, flaeche, belegt, bevorzugt="mitte_oben")
        if pos is None:
            if not erzwingen:
                return None
            pos = (flaeche.x0 - rb.x0, flaeche.y1 - rb.y1)
        dx, dy = pos
        belegt.append(rb.verschoben(dx, dy).erweitert(2.0))
        for vid, (cx, cy) in rel.items():
            platzierte[vid] = (cx + dx, cy + dy)
    weggelassen = []
    # feste Ansichten (Kevin hat sie gesetzt) und freie Ansichten (Isometrie, Schnitt, Einzelheit)
    for v in sorted(frei, key=lambda v: (bool(v.e.get("optional")), -v.groesse[0] * v.groesse[1])):
        L_, R_, B_, T_ = platz(v)
        w, h = v.groesse
        titel_h = 8.0 if (v.titel or v.art in ("schnitt", "einzelheit") or abs(v.s - s) > 1e-9) else 0.0
        rb = Rechteck(-w / 2 - L_, -h / 2 - B_, w / 2 + R_, h / 2 + T_ + titel_h)
        if v.e.get("fest") and v.e.get("lage"):
            cx, cy = float(v.e["lage"][0]), float(v.e["lage"][1])
            platzierte[v.id] = (cx, cy)
            belegt.append(rb.verschoben(cx, cy).erweitert(2.0))
            continue
        pos = _finde_platz(rb, flaeche, belegt, bevorzugt="rechts_oben")
        if pos is None and v.e.get("optional"):
            # kleinerer Maßstab für die Isometrie, sonst weglassen
            ok = False
            for f in (0.5, 0.4, 0.25, 0.2, 0.1):
                v.s = s * f
                w, h = v.groesse
                rb = Rechteck(-w / 2 - RAND_ANSICHT, -h / 2 - RAND_ANSICHT, w / 2 + RAND_ANSICHT,
                              h / 2 + RAND_ANSICHT + 8.0)
                pos = _finde_platz(rb, flaeche, belegt, bevorzugt="rechts_oben")
                if pos is not None and min(w, h) >= 15:
                    ok = True
                    break
            if not ok:
                weggelassen.append(v.id)
                v.s = s
                continue
        if pos is None:
            if not erzwingen:
                return None
            pos = (flaeche.x1 - rb.x1, flaeche.y1 - rb.y1)
        cx, cy = pos
        platzierte[v.id] = (cx, cy)
        belegt.append(rb.verschoben(cx, cy).erweitert(2.0))
    for vid, mitte in platzierte.items():
        lagen[vid] = (mitte, ansichten[vid].s)
    gesamt = sum(r.breite * r.hoehe for r in belegt)
    breiter = (block_w >= block_h) if raster else True
    return {"lagen": lagen, "reserviert": reserviert, "tabellen": tabellen, "brueche": brueche,
            "weggelassen": weggelassen, "fuellung": gesamt / (flaeche.breite * flaeche.hoehe), "breiter": breiter,
            "flaeche": flaeche}


def _eigener_faktor(v: _Ansicht, s: float) -> float:
    ms = v.e.get("massstab")
    if ms:
        return bl.massstab_faktor(ms) / s
    if v.art == "einzelheit":
        return float((v.e.get("einzelheit") or {}).get("faktor") or 2.0)
    return 1.0


def _finde_platz(r: Rechteck, flaeche: Rechteck, belegt: list[Rechteck], bevorzugt: str) -> tuple[float, float] | None:
    """Verschiebung (dx, dy), mit der das Rechteck ``r`` in ``flaeche`` liegt, ohne ``belegt`` zu schneiden."""
    if r.breite > flaeche.breite or r.hoehe > flaeche.hoehe:
        return None
    schritt = 3.0
    xs = np.arange(flaeche.x0 - r.x0, flaeche.x1 - r.x1 + 1e-6, schritt)
    ys = np.arange(flaeche.y1 - r.y1, flaeche.y0 - r.y0 - 1e-6, -schritt)
    if len(xs) == 0 or len(ys) == 0:
        return None
    kandidaten = []
    cx_f, cy_f = flaeche.mitte
    for dy in ys:
        for dx in xs:
            rr = r.verschoben(float(dx), float(dy))
            if any(rr.schneidet(b) for b in belegt):
                continue
            mx, my = rr.mitte
            if bevorzugt == "mitte_oben":
                kosten = abs(mx - cx_f) * 0.6 + (flaeche.y1 - rr.y1) * 1.0
            else:
                kosten = (flaeche.x1 - rr.x1) * 0.5 + (flaeche.y1 - rr.y1) * 1.0
            kandidaten.append((kosten, float(dx), float(dy)))
    if not kandidaten:
        return None
    kandidaten.sort()
    return kandidaten[0][1], kandidaten[0][2]


def _positionen(szene: Szene, teile: list[Teil]) -> list[int]:
    namen = {t.name for t in teile}
    out = []
    for ln in (szene.bom or {}).get("lines") or []:
        if any(n in namen for n in ln.get("teile") or []):
            out.append(ln.get("pos"))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Maße zeichnen
# ---------------------------------------------------------------------------------------------------------------------


def _hinweistext(a: _Arbeit, system: Teilsystem) -> list[str]:
    m = a.m
    el = a.els[0] if a.els else None
    text = m.get("text")
    if not text and el is not None and el.merkmal is not None:
        text = el.merkmal.text
    if not text and el is not None:
        if m["art"] == "durchmesser" and el.r:
            text = "Ø" + zahl(2 * el.r)
        elif m["art"] == "radius" and el.r:
            text = "R" + zahl(el.r)
    text = str(text or "")
    if m.get("toleranz"):
        text = f"{text} {m['toleranz']}"
    teile = [t.strip() for t in text.split(", ")]
    return teile if teile else [""]


def _masse_zeichnen(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], arbeit: list[_Arbeit],
                    beleg: Belegung, system: Teilsystem) -> list[tuple[dict[str, Any], dr.MassGrafik | None]]:
    out: list[tuple[dict[str, Any], dr.MassGrafik | None]] = []
    # 1. lineare Maße und Ketten (Lage aus dem Packen)
    for a in arbeit:
        if a.form not in ("linear", "kette") or a.v is None or a.v.id not in ansichten:
            continue
        v = a.v
        richtung = a.m.get("_richtung") or _richtung_auto(a.m, a.els, v, system)
        if richtung == "frei":
            p1 = v.blatt3(system.lokal(a.els[0].p))
            p2 = v.blatt3(system.lokal(a.els[1].p))
            seite = "frei"
        else:
            seite = a.seite or _seite_waehlen(a, system, richtung)
            p1 = _anker(a.els[0], v, system, richtung, seite)
            p2 = _anker(a.els[-1], v, system, richtung, seite)
        versatz = a.versatz if a.versatz is not None else (8.0 if seite in ("oben", "rechts", "frei") else -8.0)
        if a.form == "linear":
            wert = _wert_linear(a.els[0], a.els[1], v, system, richtung)
            text = _masstext(a.m, wert, "Ø" if a.m["art"] == "durchmesser" else "")
            g = dr.linear(a.m["id"], p1, p2, richtung, versatz, text, wert, a.m.get("text_versatz"))
        else:
            punkte = [_anker(e, v, system, richtung, seite) for e in a.els[1:]]
            werte = [_wert_linear(a.els[0], e, v, system, richtung) for e in a.els[1:]]
            g = dr.kette(a.m["id"], p1, punkte, [zahl(w) for w in werte], richtung, versatz, werte)
        a.grafik = g
        a.m["versatz"] = round(float(versatz), 3)
        a.m["anker"] = [[round(float(p1[0] - v.mitte[0]), 3), round(float(p1[1] - v.mitte[1]), 3)],
                        [round(float(p2[0] - v.mitte[0]), 3), round(float(p2[1] - v.mitte[1]), 3)]]
        _belege(beleg, g)
    # 2. Winkel
    for a in arbeit:
        if a.form != "winkel" or a.v is None or a.v.id not in ansichten:
            continue
        g = _winkel(a, system)
        if g is not None:
            a.grafik = g
            _belege(beleg, g)
    # 3. Hinweislinien: freie Lage suchen
    hinweise = [a for a in arbeit if a.form == "hinweis" and a.v is not None and a.v.id in ansichten]
    hinweise.sort(key=lambda a: int(a.m.get("_prio") or 50))
    for a in hinweise:
        g = _hinweis(a, system, beleg)
        if g is not None:
            a.grafik = g
            _belege(beleg, g)
    # 4. verwaiste Maße an der letzten bekannten Stelle
    for a in arbeit:
        if a.form == "verwaist":
            v = ansichten.get(str(a.m.get("ansicht")))
            anker = a.m.get("anker")
            if v is not None and anker and len(anker) >= 2:
                p1 = np.asarray(anker[0], dtype=float) + v.mitte
                p2 = np.asarray(anker[1], dtype=float) + v.mitte
                r = a.m.get("_richtung") or a.m.get("richtung") or "x"
                text = (a.m.get("text") or "?") + " (verwaist)"
                if r in ("x", "y", "frei"):
                    a.grafik = dr.linear(a.m["id"], p1, p2, r, float(a.m.get("versatz") or -8.0), text, None)
            elif v is not None:
                a.grafik = dr.textmass(a.m["id"], (float(v.rahmen.x0), float(v.rahmen.y1 + 4)),
                                       f"verwaist: {a.m.get('text') or a.m['art']}")
    for a in arbeit:
        out.append((a.m, a.grafik))
    return out


def _belege(beleg: Belegung, g: dr.MassGrafik) -> None:
    beleg.strecken(g.linien, "mass")
    for r in g.rechtecke():
        beleg.rechteck(r, "text")


def _hinweis(a: _Arbeit, system: Teilsystem, beleg: Belegung) -> dr.MassGrafik | None:
    v = a.v
    assert v is not None
    el = a.els[0]
    zeilen = _hinweistext(a, system)
    text, zweite = zeilen[0], zeilen[1:]
    c = v.blatt3(system.lokal(el.p))
    kreis = el.typ in ("kreis", "bogen") and el.d is not None and abs(
        float(np.dot(system.richtung_lokal(el.d), v.blick.d))) > 1 - 1e-6
    r_blatt = float(el.r or 0.0) * v.s if kreis else 0.0
    rahmen = v.rahmen
    mitte = np.array(rahmen.mitte)
    tv = a.m.get("text_versatz")
    kandidaten = []
    erlaubt = None  # Bogen: nur in Richtung des Bogens (Ziel muss auf ihm liegen)
    if el.typ == "bogen" and kreis and el.ecken is not None and len(el.ecken):
        bp = v.blatt3(system.lokal(np.asarray(el.ecken[0], dtype=float)))
        if np.linalg.norm(bp - c) > 1e-6:
            erlaubt = math.degrees(math.atan2(bp[1] - c[1], bp[0] - c[0]))
    elif el.typ == "bogen" and not kreis:
        kreis = False
    if isinstance(tv, (list, tuple)) and len(tv) == 2:
        kandidaten = [(0.0, np.asarray(tv, dtype=float))]
    else:
        raus = c - mitte
        grund = math.degrees(math.atan2(raus[1], raus[0])) if np.linalg.norm(raus) > 1e-6 else 45.0
        if erlaubt is not None:
            grund = erlaubt
        winkel = sorted({45, 135, 225, 315, 30, 60, 120, 150, 210, 240, 300, 330},
                        key=lambda w: abs(((w - grund + 180) % 360) - 180))
        if erlaubt is not None:
            winkel = [w for w in winkel if abs(((w - erlaubt + 180) % 360) - 180) <= 35] or [round(erlaubt)]
        for laenge in (10.0, 14.0, 19.0, 25.0, 32.0, 40.0, 50.0, 62.0, 75.0):
            for w in winkel:
                d = np.array([math.cos(math.radians(w)), math.sin(math.radians(w))])
                kandidaten.append((laenge + 0.02 * abs(((w - grund + 180) % 360) - 180), d * (laenge + r_blatt)))
        kandidaten.sort(key=lambda k: k[0])
    beste = None
    notbest: tuple[float, Any] | None = None
    for rang, off in kandidaten:
        d = off / (np.linalg.norm(off) or 1.0)
        ziel = c + d * r_blatt if kreis else c
        knick = c + off
        g = dr.hinweis(a.m["id"], ziel, (c - knick) if kreis else None, knick, text, None, zweiter=zweite)
        if tv is not None:
            beste = g
            break
        schulter = Rechteck(min(knick[0], g.linien[0][-1][0]), knick[1] - 0.3, max(knick[0], g.linien[0][-1][0]),
                            knick[1] + 0.3)
        kosten = sum(beleg.kosten(r) for r in g.rechtecke()) + (0.0 if beleg.strecke_frei(ziel, knick) else 8.0) \
            + (0.0 if beleg.frei(schulter, ohne=("geo", "verdeckt")) else 4.0)
        if kosten == 0.0:
            beste = g
            break
        if notbest is None or kosten + 0.05 * rang < notbest[0]:
            notbest = (kosten + 0.05 * rang, g)
    if beste is None:
        if notbest is not None:
            beste = notbest[1]
        else:
            off = np.array([20.0, 20.0])
            beste = dr.hinweis(a.m["id"], c, None, c + off, text, None, zweiter=zweite)
    a.m["anker"] = [[round(float(c[0] - v.mitte[0]), 3), round(float(c[1] - v.mitte[1]), 3)]]
    return beste


def _linie_blatt(el: bz.Element, v: _Ansicht, system: Teilsystem) -> tuple[np.ndarray, np.ndarray] | None:
    """Gerade eines Elements in der Ansicht: (Punkt, Richtung) auf dem Blatt."""
    p = v.blatt3(system.lokal(el.p))
    if el.typ == "linie" and el.d is not None:
        q = v.blatt3(system.lokal(el.p + el.d))
        d = q - p
    elif el.typ == "ebene" and el.d is not None:
        n2 = v.blick.projiziere(system.richtung_lokal(el.d))
        d = np.array([-n2[1], n2[0]])
    else:
        return None
    n = float(np.linalg.norm(d))
    if n < 1e-9:
        return None
    return p, d / n


def _winkel(a: _Arbeit, system: Teilsystem) -> dr.MassGrafik | None:
    v = a.v
    assert v is not None
    l1 = _linie_blatt(a.els[0], v, system)
    l2 = _linie_blatt(a.els[1], v, system)
    if l1 is None or l2 is None:
        return None
    (p1, d1), (p2, d2) = l1, l2
    A = np.array([d1, -d2]).T
    if abs(np.linalg.det(A)) < 1e-9:
        return None
    t = np.linalg.solve(A, p2 - p1)
    s = p1 + d1 * t[0]
    # Schenkel ins Teil hinein: Richtung zur Teilmitte
    mitte = np.array(v.rahmen.mitte)
    if float((mitte - s) @ d1) < 0:
        d1 = -d1
    if float((mitte - s) @ d2) < 0:
        d2 = -d2
    wert = math.degrees(math.acos(max(-1.0, min(1.0, float(d1 @ d2)))))
    text = _masstext(a.m, None) or (zahl(wert, 1) + "°")
    if not a.m.get("text"):
        text = zahl(wert, 1) + "°"
    return dr.winkel(a.m["id"], s, d1, d2, 14.0, text, wert)


# ---------------------------------------------------------------------------------------------------------------------
# Blatt: Rahmen, Schriftfeld, Tabellen, Positionsnummern, Notizen
# ---------------------------------------------------------------------------------------------------------------------


def _dekoration(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], szene: Szene, teile: list[Teil], art: str,
                lage: dict[str, Any], beleg: Belegung, system: Teilsystem) -> bl.Grafik:
    W, H = lage["breite"], lage["hoehe"]
    g = bl.rahmen(W, H)
    sf = dict(blatt["schriftfeld"])
    if art == "teil" and teile:
        gleich = szene.gleiche_teile(teile[0].name)
        if len(gleich) > 1 and not sf.get("notiz"):
            sf["notiz"] = "gilt für: " + ", ".join(kurznamen(gleich))
    g.dazu(bl.schriftfeld(W, H, sf, blatt["massstab"], f"{blatt['format']} {blatt['ausrichtung']}"))
    zeilen = list(blatt.get("allgemein") or [])
    if sf.get("notiz"):
        zeilen = [str(sf["notiz"])] + zeilen
    ag, _ = bl.allgemeinangaben(W, H, zeilen)
    sf.pop("notiz", None)
    g.dazu(ag)
    for t in lage.get("tabellen") or []:
        if t["art"] == "stueckliste":
            r = t["rechteck"]
            tg, _ = bl.tabelle(r.x0, r.y0, bl.STUECKLISTE_SPALTEN, t["zeilen"])
            g.dazu(tg)
    # Ansichtstitel: Schnitte, Einzelheiten, eigener Maßstab
    s_blatt = bl.massstab_faktor(blatt["massstab"])
    for v in ansichten.values():
        titel = v.titel
        if v.art == "schnitt":
            titel = titel or f"{(v.e.get('schnitt') or {}).get('name', 'A')}–{(v.e.get('schnitt') or {}).get('name', 'A')}"
        elif v.art == "einzelheit":
            titel = titel or f"{(v.e.get('einzelheit') or {}).get('name', 'B')}"
        if abs(v.s - s_blatt) > 1e-9:
            titel = (titel + " " if titel else "") + f"({bl.massstab_text(v.s)})"
        if titel:
            r = v.rahmen
            tb_y = r.y1 + 4.0
            g.text(titel, (r.x0 + r.x1) / 2, tb_y, aktiv().schrifthoehe, "mitte", art="ansicht")
            beleg.rechteck(textbox(titel, ((r.x0 + r.x1) / 2, tb_y), aktiv().schrifthoehe), "text")
    # Schnittverlauf und Einzelheiten in der Ausgangsansicht beschriften
    for v in ansichten.values():
        for sv in v.e.get("_schnittverlauf") or []:
            a, b = v.blatt(np.asarray(sv["a"])), v.blatt(np.asarray(sv["b"]))
            pf = np.asarray(sv["pfeil"], dtype=float)
            pf = pf / (np.linalg.norm(pf) or 1.0)
            u = (b - a) / (np.linalg.norm(b - a) or 1.0)
            for p, s_ in ((a, -1.0), (b, 1.0)):
                ende = p + u * s_ * 0.0
                g.linie("sichtbar", tuple(ende - u * s_ * 6.0), tuple(ende))
                spitze = ende + pf * 6.0
                g.linie("duenn", tuple(ende), tuple(spitze))
                g.flaechen.append(np.array(dr.pfeil(spitze, pf)["polygon"]))
                lage = spitze + pf * 2.0 + np.array([0.0, -aktiv().schrifthoehe / 2])
                g.text(str(sv["name"]), float(lage[0]), float(lage[1]), aktiv().schrifthoehe + 1.5, "mitte", art="schnitt")
        for mk in v.e.get("_einzelheit_marke") or []:
            c = v.blatt(np.asarray(mk["mitte"]))
            r = float(mk["radius"]) * v.s
            g.text(str(mk["name"]), float(c[0] + r * 0.75 + 2), float(c[1] + r * 0.75 + 1), aktiv().schrifthoehe + 1.5,
                   "links", art="einzelheit")
    # Positionsnummern im Zusammenbau (ISO 6433)
    if art in ("zusammenbau", "baugruppe") and szene.bom:
        fehlen = _positionsnummern(g, ansichten, szene, teile, beleg)
        if fehlen:
            lage.setdefault("hinweise", []).append("Positionsnummern ohne Platz: " + ", ".join(str(x) for x in fehlen))
    # Notizen
    for n in blatt.get("notizen") or []:
        lage_n = n.get("lage") or [30, 30]
        g.text(str(n.get("text") or ""), float(lage_n[0]), float(lage_n[1]), bl.TEXT_KLEIN, art="notiz")
        z = n.get("zeiger")
        if isinstance(z, dict) and z.get("punkt") and not z.get("teil"):
            g.linie("duenn", (float(lage_n[0]), float(lage_n[1])), tuple(z["punkt"]))
    return g


def _positionsnummern(g: bl.Grafik, ansichten: dict[str, _Ansicht], szene: Szene, teile: list[Teil],
                      beleg: Belegung) -> list[Any]:
    iso = next((v for v in ansichten.values() if v.art.startswith("iso")), None)
    if iso is None or not iso.proj.teile:
        return []
    namen = {t.name for t in teile}
    rahmen = iso.rahmen
    mitte = np.array(rahmen.mitte)
    ziele = []
    for ln in (szene.bom or {}).get("lines") or []:
        kandidaten = [n for n in ln.get("teile") or [] if n in namen and n in iso.proj.teile]
        best = None
        for n in kandidaten:
            ls = iso.proj.teile[n].get("sichtbar") or []
            laenge = sum(float(np.sum(np.linalg.norm(np.diff(pl, axis=0), axis=1))) for pl in ls)
            if laenge > 0 and (best is None or laenge > best[0]):
                best = (laenge, n, ls)
        if best is None:
            continue
        _, n, ls = best
        # Ansatzpunkt: Mitte der längsten sichtbaren Strecke des Teils
        pl = max(ls, key=lambda p: float(np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1))))
        punkt = iso.blatt(pl[len(pl) // 2] if len(pl) > 2 else (pl[0] + pl[-1]) / 2)
        ziele.append((ln.get("pos"), punkt, n))
    if not ziele:
        return []
    # Nummern um die Ansicht, nach Winkel sortiert; je Nummer die günstigste freie Lage (kurze Hinweislinie, nah am
    # eigenen Winkel, keine Kreuzung mit schon gesetzten Hinweislinien, innerhalb der Zeichenfläche)
    ziele.sort(key=lambda z: math.atan2(z[1][1] - mitte[1], z[1][0] - mitte[0]))
    gesetzt: list[tuple[np.ndarray, np.ndarray]] = []  # (Kreismitte, Spitze)
    belegt: list[Rechteck] = []
    nicht_gesetzt = []
    for pos, punkt, _name in ziele:
        p = np.asarray(punkt, dtype=float)
        w0 = math.atan2(p[1] - mitte[1], p[0] - mitte[0])
        beste = None
        for abstand in (10.0, 16.0, 22.0, 30.0, 40.0, 52.0):
            for dw in (0.0, 0.15, -0.15, 0.3, -0.3, 0.5, -0.5, 0.8, -0.8, 1.2, -1.2):
                ww = w0 + dw
                # Strahl aus der Ansichtsmitte: Punkt knapp außerhalb des Rahmens plus Abstand
                d = np.array([math.cos(ww), math.sin(ww)])
                tx = (rahmen.breite / 2) / abs(d[0]) if abs(d[0]) > 1e-9 else 1e9
                ty = (rahmen.hoehe / 2) / abs(d[1]) if abs(d[1]) > 1e-9 else 1e9
                c = mitte + d * (min(tx, ty) + abstand)
                r = Rechteck(c[0] - 4.8, c[1] - 4.8, c[0] + 4.8, c[1] + 4.8)
                if any(r.schneidet(b, 1.0) for b in belegt) or not beleg.frei(r, ohne=("geo", "verdeckt")):
                    continue
                kreuzt = sum(1 for c2, p2 in gesetzt if _schneiden(c, p, c2, p2))
                kosten = float(np.linalg.norm(c - p)) + 25.0 * abs(dw) + 60.0 * kreuzt
                if beste is None or kosten < beste[0]:
                    beste = (kosten, c, r)
            if beste is not None and beste[0] < abstand + 40:
                break
        if beste is None:
            nicht_gesetzt.append(pos)
            continue
        _, c, r = beste
        belegt.append(r)
        gesetzt.append((c, p))
        beleg.rechteck(r, "text")
        bl.positionsnummer(g, pos, (float(c[0]), float(c[1])), (float(p[0]), float(p[1])))
    return nicht_gesetzt


def _schneiden(a1: np.ndarray, a2: np.ndarray, b1: np.ndarray, b2: np.ndarray) -> bool:
    def kreuz(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
        return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))

    d1, d2 = kreuz(b1, b2, a1), kreuz(b1, b2, a2)
    d3, d4 = kreuz(a1, a2, b1), kreuz(a1, a2, b2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


# ---------------------------------------------------------------------------------------------------------------------
# Ausgabe: Kopf und Nutzlast der Nachricht DRAWING
# ---------------------------------------------------------------------------------------------------------------------


def nutzlast(gruppen: list[dict[str, list[np.ndarray]]]) -> tuple[bytes, list[dict[str, int]]]:
    """Polylinien-Nutzlast (Referenz: protocol.pack_polylinien)."""
    from kevcad_kernel.protocol import pack_polylinien

    return pack_polylinien(gruppen)


def lies_nutzlast(kopf: dict[str, Any], daten: bytes) -> list[dict[str, list[np.ndarray]]]:
    """Gegenstück zu ``nutzlast`` (protocol.unpack_polylinien), als float64."""
    from kevcad_kernel.protocol import unpack_polylinien

    return [{k: [np.asarray(pl, dtype=float) for pl in v] for k, v in g.items()}
            for g in unpack_polylinien(kopf, daten)]


def _ausgabe(blatt: dict[str, Any], ansichten: dict[str, _Ansicht], grafiken: list[tuple[dict[str, Any], Any]],
             deko: bl.Grafik, lage: dict[str, Any], szene: Szene, teile: list[Teil], stand_extra: str) \
        -> tuple[dict[str, Any], bytes]:
    gruppen = []
    geo = []
    for vid in [a["id"] for a in blatt["ansichten"] if a["id"] in ansichten]:
        v = ansichten[vid]
        lin = v.linien_blatt()
        gruppen.append(lin)
        geo.append({"id": vid, "art": v.art, "rahmen": v.rahmen.liste(), "massstab": bl.massstab_text(v.s),
                    "titel": v.titel})
    W, H = lage["breite"], lage["hoehe"]
    gruppen.append({"sichtbar": deko.linien.get("sichtbar", []), "duenn": deko.linien.get("duenn", []),
                    "mitte": deko.linien.get("mitte", [])})
    geo.append({"id": "blatt", "art": "blatt", "rahmen": [0.0, 0.0, W, H], "massstab": None, "titel": None})
    daten, zaehler = nutzlast(gruppen)
    for g, z in zip(geo, zaehler):
        g["linien"] = z
    masse = []
    for m, gr in grafiken:
        if gr is None:
            masse.append({"id": m["id"], "linien": [], "pfeile": [], "text": m.get("text") or "", "text_lage": None,
                          "text_winkel": 0.0, "wert": None, "ansicht": m.get("ansicht"), "art": m.get("art"),
                          "quelle": m.get("quelle"), "fest": bool(m.get("fest")), "verwaist": True})
            continue
        d = gr.als_dict()
        d.update({"ansicht": m.get("ansicht"), "art": m.get("art"), "quelle": m.get("quelle"),
                  "fest": bool(m.get("fest")), "verwaist": bool(m.get("verwaist"))})
        masse.append(d)
    stand = hashlib.sha1((json.dumps(dok.zum_speichern(blatt), sort_keys=True, ensure_ascii=False,
                                     default=_json_default) + "|" + "|".join(sorted(t.key for t in teile))
                          + stand_extra).encode()).hexdigest()[:16]
    kopf = {"blatt": dok.zum_speichern(blatt), "blattgroesse": [W, H], "linien_reihenfolge": list(LINIEN_REIHENFOLGE),
            "geometrie": geo, "masse": masse, "texte": deko.texte,
            "gefuellt": [[[round(float(x), 3), round(float(y), 3)] for x, y in pl] for pl in deko.flaechen],
            "stand": stand, "run": szene.run}
    return kopf, daten


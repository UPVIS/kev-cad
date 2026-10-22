"""Gerüst des Bauplans aus den Daten des Laufs: Material, Zuschnitt, Bearbeiten, Drucken, Montage.

Jeder Schritt hat die Felder aus DOKUMENTE.md (Abschnitt „Bauplan“) und einige additive:

| Feld | Bedeutung |
|---|---|
| ``anzahl`` | so oft gleich (4× gleich: Lenksperre einsetzen) |
| ``hinweise`` | worauf achten, Sicherheit (Liste kurzer Sätze) |
| ``material`` | Materialabschnitt: Liste ``{benennung, menge, einheit, quelle, preis}`` |
| ``einbau`` | Montage: je Einheit ``{name, teile, richtung, zuerst, weg, aufbocken, grundteil, erzwungen}`` |
| ``geschaetzt`` | Verbindung nur aus Kontakt und Normteilen geschätzt (Modell ohne ``verbinde``) |

Texte sind kurz und sachlich; der Agent formuliert sie danach werkstattgerecht (``bauplan_bearbeiten``).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, OrderedDict
from typing import Any

import numpy as np

from kevcad_kernel.bauplan import werkstatt as ws
from kevcad_kernel.bauplan.eingang import Eingang
from kevcad_kernel.bauplan.montagefolge import Einbau, Folge
from kevcad_kernel.bom import de_num, gehrung_text

ABSCHNITTE = (("material", "Material"), ("zuschnitt", "Zuschnitt"), ("bearbeiten", "Bearbeiten"),
              ("drucken", "Drucken"), ("montage", "Montage"))
VERBINDUNG_TEXT = {"schraube": "verschrauben", "klemmung": "klemmen", "steck": "stecken", "formschluss": "einsetzen",
                   "kleben": "kleben", "aufliegen": "auflegen", "drehgelenk": "drehbar lagern",
                   "schiebegelenk": "aufschieben", "zylindergelenk": "aufschieben", "kugelgelenk": "einsetzen",
                   "fest": "fest verbinden"}


def sid(*teile: Any) -> str:
    h = hashlib.sha1("|".join(str(t) for t in teile).encode("utf-8")).hexdigest()[:10]
    return h


def schritt(abschnitt: str, schluessel: str, titel: str, text: str = "", **felder: Any) -> dict[str, Any]:
    s = {"id": f"{abschnitt[0]}-{sid(abschnitt, schluessel)}", "titel": titel, "text": text, "quelle": "auto",
         "fest": False, "teile": [], "neu": [], "baugruppe": None, "verbindungsmittel": [], "werkzeug": [],
         "bohrbild": [], "zuschnitt": [], "druck": None, "bild": None, "pruefung": [], "anzahl": 1, "hinweise": []}
    s.update(felder)
    return s


def _anzahl_text(n: int) -> str:
    return f"{n}× " if n > 1 else ""


def _r(v: Any, n: int = 3) -> Any:
    if v is None:
        return None
    if isinstance(v, dict):  # Signaturen der Bohrbild-Bezüge (sonst blieben ndarrays im Plan, BAUPLAN scheiterte)
        return {k: _r(x, n) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_r(x, n) for x in v]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, float, np.floating, np.integer)):
        x = round(float(v), n)
        return 0.0 if x == 0 else x
    return v


# ---------------------------------------------------------------------------------------------------------------------
# Material


def material(ein: Eingang) -> list[dict[str, Any]]:
    bom = ein.bom or {}
    out: list[dict[str, Any]] = []
    linien = bom.get("lines") or []
    cuts = {c.get("stock_id"): c for c in bom.get("cuts") or []}
    einkauf = bom.get("einkaufsliste")  # Bestand (BESTAND.md), wenn vorhanden
    if einkauf:
        liste = [{"benennung": e.get("benennung"), "menge": e.get("menge"), "einheit": e.get("einheit"),
                  "preis": e.get("preis"), "quelle": "kaufen", "hinweis": e.get("hinweis")} for e in einkauf]
        out.append(schritt("material", "einkauf", "Einkaufsliste", "Was nach Abzug des Projektbestands fehlt.",
                           material=liste))
    # Stangen und Platten
    halbzeug = []
    teile: list[str] = []
    for c in bom.get("cuts") or []:
        n = len(c.get("stangen") or [])
        quellen = c.get("quellen")
        if quellen:
            kaufen = sum(1 for q in quellen if q.get("art") == "kaufen")
            bestand = len(quellen) - kaufen
            menge_text = f"{n} (davon {bestand} aus dem Bestand, {kaufen} kaufen)"
        else:
            menge_text = str(n)
        halbzeug.append({"benennung": c.get("benennung"), "menge": n, "einheit":
                         f"Stange {de_num(c.get('stangenlaenge'))} mm", "preis": c.get("preis_stangen"),
                         "quelle": "kaufen oder Bestand", "text": f"{menge_text} × {c.get('benennung')}, Stange "
                                                                  f"{de_num(c.get('stangenlaenge'))} mm"})
    for line in linien:
        if line.get("art") == "platte":
            halbzeug.append({"benennung": line.get("benennung"), "menge": line.get("anzahl"),
                             "einheit": line.get("masse_text"), "preis": line.get("preis"),
                             "quelle": "kaufen oder Bestand"})
        if line.get("art") in ("platte",) or line.get("stock_id") in cuts:
            teile += list(line.get("teile") or [])
    if halbzeug:
        out.append(schritt("material", "halbzeug", "Stangen und Platten",
                           "Halbzeug besorgen bzw. aus dem Bestand nehmen.", material=halbzeug, teile=teile))
    # Normteile und Kleinteile (Katalog) und am Namen erkannte Kaufteile
    klein = []
    teile = []
    for line in linien:
        if line.get("art") in ("schraube", "mutter", "scheibe"):
            klein.append({"benennung": f"{line.get('benennung')}"
                          + (f", {line.get('masse_text')}" if line.get("masse_text") and
                             str(line.get("masse_text")) not in str(line.get("benennung")) else ""),
                          "menge": line.get("anzahl"), "einheit": "Stück", "preis": line.get("preis"),
                          "quelle": "kaufen oder Bestand", "id": line.get("stock_id")})
            teile += list(line.get("teile") or [])
    # Kleinteile ohne Lagerteil, die auch kein Zukaufteil sind: Zukaufteile (Flügelschraube DIN 316, Rillenkugellager,
    # Senkschraube aus dem Shop) stehen mit voller Benennung nur unter „Zukaufteile bestellen“
    zukauf_teile = {t for line in linien if line.get("art") == "zukaufteil" for t in line.get("teile") or []}
    ohne = [t for t in ein.aufbau() if t.rolle in ("vm", "einsatz") and not t.stock and not t.kopf.get("zukauf")
            and t.name not in zukauf_teile]
    for name, n in Counter(ws.stueck_name(t.name) for t in ohne).items():
        klein.append({"benennung": f"{name} (nicht im Katalog)", "menge": n, "einheit": "Stück", "preis": None,
                      "quelle": "kaufen"})
    teile += [t.name for t in ohne]
    if klein:
        out.append(schritt("material", "kleinteile", "Normteile und Kleinteile",
                           "Schrauben, Muttern, Scheiben und Einsätze abzählen.", material=klein, teile=teile))
    # Filament
    fil: dict[str, float] = {}
    teile = []
    for t in ein.aufbau():
        if t.rolle == "druck":
            m = str((t.druck or {}).get("material") or "petg")
            fil[m] = fil.get(m, 0.0) + float((t.druck or {}).get("kg") or t.masse_g / 1000.0)
            teile.append(t.name)
    if fil:
        liste = [{"benennung": f"Filament {ws.druck_info(m).get('name', m.upper())}", "menge": round(kg * 1.1, 3),
                  "einheit": "kg (mit 10 % Zugabe für Brim und Fehldruck)", "preis": None, "quelle": "Bestand"}
                 for m, kg in fil.items()]
        out.append(schritt("material", "filament", "Filament", "Reicht die Spule?", material=liste, teile=teile))
    # Vorhandenes und Hilfsstoffe
    vorhanden = OrderedDict()
    for t in ein.aufbau():
        if t.kopf.get("zukauf"):
            continue  # steht bei den Zukaufteilen
        if t.rolle == "zukauf" and t.einheit:
            vorhanden.setdefault(t.einheit, []).append(t.name)
        elif t.rolle == "kauf":
            vorhanden.setdefault(t.name, []).append(t.name)
    hilf = []
    aufbau = {t.name for t in ein.aufbau()}
    verb = [v for v in ein.verbindungen if all(n in aufbau for n in v.teile)]
    if any(v.art == "kleben" and v.quelle == "verbinde" and any(ein.teile.get(n) is not None and
                                                                 ein.teile[n].rolle == "vm" for n in v.teile)
           for v in verb):
        hilf.append({"benennung": "Schraubensicherung mittelfest", "menge": 1, "einheit": "Flasche",
                     "quelle": "Bestand"})
    if any(v.art == "kleben" and v.quelle == "verbinde" and not any(ein.teile.get(n) is not None and
                                                                     ein.teile[n].rolle == "vm" for n in v.teile)
           for v in verb):
        hilf.append({"benennung": "Kleber passend zu den Werkstoffen (Schätzung)", "menge": 1, "einheit": "Tube",
                     "quelle": "Bestand"})
    zukauf = [line for line in linien if line.get("art") == "zukaufteil"
              and any(ein.teile.get(t) is not None and ein.teile[t].rolle != "ohne" for t in line.get("teile") or [])]

    def zk_name(line: dict[str, Any]) -> str:
        b = str(line.get("benennung") or "")
        h = str(line.get("hersteller") or "")
        if h and not h.lower().startswith(("normteil", "unbekannt")) and h.lower() not in b.lower():
            b += f" ({h} {line.get('mpn') or ''})".rstrip()
        return b

    if zukauf:
        liste = [{"benennung": zk_name(line), "menge": line.get("anzahl"), "einheit": "Stück",
                  "preis": line.get("preis"), "quelle": "kaufen", "url": line.get("url"),
                  "teile": list(line.get("teile") or [])} for line in zukauf]
        out.append(schritt("material", "zukauf", "Zukaufteile bestellen",
                           "Zukaufteile beim Händler bestellen (Link und Preis aus dem Katalog, Richtpreise).",
                           material=liste, teile=[t for line in zukauf for t in line.get("teile") or []]))
        for line in zukauf:
            for t in line.get("teile") or []:
                vorhanden.pop(t, None)
    if vorhanden or hilf:
        liste = [{"benennung": k, "menge": 1, "einheit": "vorhanden", "quelle": "vorhanden", "teile": v}
                 for k, v in vorhanden.items()] + hilf
        hinweise = [f"Nicht Teil des Aufbaus: {n} ({g})" for n, g in list(ein.ohne.items())[:6]]
        out.append(schritt("material", "vorhanden", "Vorhandenes und Hilfsstoffe bereitlegen",
                           "Zukaufteile und vorhandene Baugruppen prüfen, Hilfsstoffe bereitstellen.", material=liste,
                           teile=[n for v in vorhanden.values() for n in v], hinweise=hinweise))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Zuschnitt


def zuschnitt(ein: Eingang) -> list[dict[str, Any]]:
    bom = ein.bom or {}
    out: list[dict[str, Any]] = []
    linien = bom.get("lines") or []
    for c in bom.get("cuts") or []:
        sid_ = c.get("stock_id")
        stange_l = float(c.get("stangenlaenge") or 0)
        frei: dict[float, list[str]] = {}
        gehr: dict[float, list[float]] = {}
        material = None
        for line in linien:
            if line.get("stock_id") != sid_ or line.get("laenge") is None:
                continue
            frei.setdefault(float(line["laenge"]), []).extend(line.get("teile") or [])
            gehr[float(line["laenge"])] = list(line.get("gehrung") or [0, 0])
            material = line.get("material")
        art = ein.katalog.item(sid_).get("art") if ein.katalog is not None and ein.katalog.item(sid_) else None
        gruppen: OrderedDict[tuple, list[int]] = OrderedDict()
        for i, bar in enumerate(c.get("stangen") or [], 1):
            gruppen.setdefault(tuple(float(x) for x in bar), []).append(i)
        for bar, nummern in gruppen.items():
            n = len(nummern)
            teile: list[str] = []
            for _ in nummern:
                for L in bar:
                    lst = frei.get(L) or []
                    if lst:
                        teile.append(lst.pop(0))
            rest = stange_l - sum(bar) - float(c.get("saegeschnitt") or 3) * max(0, len(bar) - (0 if sum(bar) < stange_l
                                                                                                  else 1))
            stuecke = Counter(bar)
            zs = [{"stock_id": sid_, "laenge": L, "gehrung": gehr.get(L, [0, 0]), "anzahl": k * n}
                  for L, k in stuecke.items()]
            nr = f"Stange {nummern[0]}" if n == 1 else f"Stangen {nummern[0]}–{nummern[-1]}"
            if len(bar) == 1 and abs(bar[0] - stange_l) < 0.5:
                titel = f"{nr}: ganze Stange, {de_num(stange_l)} mm"
                text = "Nicht ablängen; Enden auf Rechtwinkligkeit und Grat prüfen."
            else:
                folge = " + ".join(de_num(x) for x in bar)
                titel = f"{nr}: {folge} mm"
                text = (f"{c.get('benennung')} ({de_num(stange_l)} mm) ablängen: {folge} mm, Sägeschnitt "
                        f"{de_num(c.get('saegeschnitt') or 3)} mm; Rest {de_num(max(rest, 0))} mm.")
            hinweise = ["Längstes Stück zuerst schneiden, Maß immer ab frischer Schnittkante nehmen"]
            for L in stuecke:
                g = gehr.get(L, [0, 0])
                if any(abs(float(x)) > 1e-6 for x in g):
                    hinweise.append(f"{de_num(L)} mm mit Gehrung {gehrung_text(g)} (Maß an der langen Kante, "
                                    "Gehrungen gegengleich anzeichnen)")
            hinweise.append("Schutzbrille tragen, Werkstück fest spannen, Schnittkanten entgraten")
            out.append(schritt("zuschnitt", f"{sid_}|{bar}", titel, text, anzahl=n, teile=teile, zuschnitt=zs,
                               werkzeug=["Maßband oder Anschlag", "Anreißwinkel", *ws.saege(material, art)],
                               hinweise=hinweise))
    for line in linien:  # Platten ohne Zuschnittplan
        if line.get("art") != "platte":
            continue
        n = int(line.get("anzahl") or 1)
        out.append(schritt("zuschnitt", f"platte|{line.get('stock_id')}|{line.get('masse_text')}",
                           f"Platte {line.get('masse_text')}", f"{line.get('benennung')}: {_anzahl_text(n)}"
                           f"{line.get('masse_text')} zuschneiden.", anzahl=n, teile=list(line.get("teile") or []),
                           zuschnitt=[{"stock_id": line.get("stock_id"), "laenge": None, "masse": line.get("masse_text"),
                                       "anzahl": n}],
                           werkzeug=ws.saege(line.get("material"), "platte"),
                           hinweise=["Faserrichtung bzw. Sichtseite beachten", "Kanten brechen"]))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Merkmale (Bohrungen) über die Merkmalerkennung von P6-Z


def merkmale_fuer(ein: Eingang, namen: list[str]) -> dict[str, Any]:
    """Merkmale je Teil (zeichnung.erkenne) mit den Verbindungsmitteln des Aufbaus als Umgebung."""
    from kevcad_kernel.zeichnung import erkenne
    from kevcad_kernel.zeichnung.merkmale import verbindungsmittel

    umgebung = []
    for t in ein.teile.values():
        if t.rolle in ("vm", "einsatz", "zukauf"):
            try:
                g = verbindungsmittel(t.name, t.koerper.shape, _info(ein, t))
            except Exception:  # noqa: BLE001
                g = None
            if g is not None:
                umgebung.append(g)
    out = {}
    for n in namen:
        t = ein.teile.get(n)
        if t is None:
            continue
        lo, hi = t.bmin - 2.0, t.bmax + 2.0
        nah = [g for g in umgebung if g["name"] != n and _nahe(g, lo, hi)]
        try:
            out[n] = erkenne(t.koerper.shape, _info(ein, t), name=n, umgebung=nah, kanten=False)
        except Exception:  # noqa: BLE001 - ein Teil ohne Merkmale ist kein Grund, den Bauplan abzubrechen
            out[n] = None
    return out


def _nahe(g: dict[str, Any], lo: np.ndarray, hi: np.ndarray) -> bool:
    p, a = np.asarray(g["p"], float), np.asarray(g["a"], float)
    t0, t1 = g["t"]
    pts = np.array([p + a * t0, p + a * t1])
    return bool(np.all(pts.max(axis=0) >= lo) and np.all(pts.min(axis=0) <= hi))


def _info(ein: Eingang, t: Any) -> dict[str, Any]:
    return {"stock": t.stock, "druckteil": t.druck, "material": t.kopf.get("material"), "katalog": t.item}


def _bohrungen(ein: Eingang, t: Any, m: Any) -> list[Any]:
    """Zu bearbeitende Merkmale eines Teils: bei Lagerteilen alle Bohrungen und Langlöcher, bei vorhandenen Teilen
    nur die, durch die ein eigenes Verbindungsmittel geht."""
    if m is None:
        return []
    arten = ("bohrung", "langloch")
    out = []
    for mk in m.von_art(*arten):
        if t.rolle in ("stange", "platte"):
            out.append(mk)
            continue
        g = (mk.werte or {}).get("gegenstueck")
        gt = ein.teile.get(g) if g else None
        if gt is not None and gt.rolle in ("vm", "einsatz") and not (gt.rolle == "zukauf"):
            if t.einheit is None or gt.einheit != t.einheit:
                out.append(mk)
    return out


KANTEN = {0: ("linker Kante", "rechter Kante"), 1: ("vorderer Kante", "hinterer Kante"),
          2: ("Unterkante", "Oberkante")}


def _lage_welt(t: Any, w: dict[str, Any], system: Any) -> tuple[list[float] | None, str]:
    """Lage einer Bohrung quer zu ihrer Achse ab den Außenkanten des Teils (Welt-Achsen, wenn die Bohrung achsparallel
    ist: x ab linker, y ab vorderer Kante, z ab Unterkante), sonst im Teilsystem ab der Bezugsecke."""
    welt = w.get("welt") or {}
    mitte, richtung = welt.get("mitte"), welt.get("richtung")
    if mitte is not None and richtung is not None:
        d = np.abs(np.asarray(richtung, dtype=float))
        i = int(np.argmax(d))
        if d[i] > 0.999:
            achsen = [k for k in range(3) if k != i]
            m = np.asarray(mitte, dtype=float)
            werte = [round(float(m[k] - t.bmin[k]), 1) for k in achsen]
            namen = [("x", "y", "z")[k] + " ab " + KANTEN[k][0] for k in achsen]
            return werte, ", ".join(namen)
    e = w.get("eintritt")
    a = w.get("achse")
    if e is None:
        return None, ""
    achsen = [0, 1, 2]
    if a is not None:
        achsen.remove(int(np.argmax(np.abs(np.asarray(a, dtype=float)))))
    return [round(float(e[k]), 1) for k in achsen[:2]], "Bezugsecke (Teilsystem)"


def _bohr_eintrag(t: Any, mk: Any, system: Any) -> dict[str, Any]:
    w = mk.werte or {}
    lage = w.get("lage_mm")
    if lage is None:
        lage, von = _lage_welt(t, w, system)
    else:
        lage = [round(float(x), 1) for x in (lage if isinstance(lage, (list, tuple)) else [lage])]
        von = w.get("von") or "Ende A"
    senk = w.get("senkung") or w.get("gegenbohrung")
    return {"teil": t.name,
            "bezug": {"teil": t.name, "art": "bohrung" if mk.art == "bohrung" else "merkmal",
                      "signatur": _r(mk.signatur), "merkmal": mk.id, "ref": None},
            "durchmesser": _r(w.get("d") or w.get("breite"), 2), "tiefe": _r(w.get("tiefe"), 2),
            "lage_mm": lage, "von": von, "senkung": _r(senk), "gewinde": w.get("gewinde"),
            "fuer": w.get("fuer"), "text": mk.text, "art": mk.art,
            "richtung": _r(system.richtung_welt(w["achse"]) if w.get("achse") is not None and system is not None
                           else None, 4)}


def _bohr_text(eintraege: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Kurztext und Werkzeugliste für ein Bohrbild."""
    gruppen: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for e in eintraege:
        gruppen.setdefault(str(e.get("text")), []).append(e)
    teile = []
    werkzeug: list[str] = []
    for text, es in gruppen.items():
        lagen = [e["lage_mm"] for e in es if e.get("lage_mm") is not None]
        if lagen and len(lagen[0]) == 1:
            wo = "bei " + ", ".join(de_num(x[0]) for x in sorted(lagen)) + f" mm ab {es[0].get('von')}"
        elif lagen:
            wo = "bei " + "; ".join(f"{de_num(x[0])} / {de_num(x[1])}" for x in sorted(lagen)[:6]) + \
                 (" …" if len(lagen) > 6 else "") + f" mm ({es[0].get('von')})"
        else:
            wo = ""
        teile.append(f"{len(es)}× {text} {wo}".strip())
        e0 = es[0]
        if e0.get("gewinde"):
            d = ws.KERNLOCH.get(_nenn(e0["gewinde"]) or 0)
            if d:
                werkzeug.append(ws.bohrer_text(d))
            werkzeug.append(f"Gewindebohrer {e0['gewinde']} (Satz)")
            werkzeug.append("Windeisen")
        elif e0.get("durchmesser"):
            werkzeug.append(ws.bohrer_text(float(e0["durchmesser"])))
        if e0.get("senkung"):
            s = e0["senkung"]
            if "winkel" in s:
                werkzeug.append(f"Kegelsenker {de_num(s.get('winkel'), 0)}°")
            else:
                werkzeug.append(f"Flachsenker Ø {de_num(s.get('d'))}")
    werkzeug += ["Körner", "Entgrater"]
    return "; ".join(teile), list(dict.fromkeys(werkzeug))


def _nenn(text: Any) -> float | None:
    m = re.search(r"M(\d+(?:[.,]\d+)?)", str(text or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def bearbeiten(ein: Eingang, merk: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # Bohren (Lagerteile und vorhandene Teile mit eigenen Verbindungsmitteln)
    gruppen: OrderedDict[tuple, list[tuple[Any, list[dict[str, Any]]]]] = OrderedDict()
    for t in ein.aufbau():
        if t.rolle not in ("stange", "platte", "zukauf", "kauf", "eigen"):
            continue
        m = merk.get(t.name)
        mks = _bohrungen(ein, t, m)
        if not mks:
            continue
        eintraege = [_bohr_eintrag(t, mk, m.system if m else None) for mk in mks]
        eintraege.sort(key=lambda e: tuple(e.get("lage_mm") or [0]))
        sig = (t.stock.get("id") if t.stock else t.name, round(float((t.stock or {}).get("laenge") or 0), 1),
               tuple((e["text"], tuple(round(x, 0) for x in (e.get("lage_mm") or []))) for e in eintraege))
        gruppen.setdefault(sig, []).append((t, eintraege))
    for sig, mitglieder in gruppen.items():
        t0, ein0 = mitglieder[0]
        n = len(mitglieder)
        text, werkzeug = _bohr_text(ein0)
        namen = [t.name for t, _ in mitglieder]
        kurz = t0.kurz if n == 1 else ws.stueck_name(t0.name)
        titel = f"{_anzahl_text(n)}{kurz}: {len(ein0)} {'Bohrung' if len(ein0) == 1 else 'Bohrungen'}"
        hinweise = []
        h = ws.bohr_hinweis(t0.material)
        if h:
            hinweise.append(h)
        if t0.rolle == "stange":
            hinweise.append("Rohr im Prisma oder Maschinenschraubstock spannen, Lage ab Ende A anreißen")
            werkzeug = ["Bohrständer oder Säulenbohrmaschine", *werkzeug]
        if t0.rolle in ("zukauf", "kauf", "eigen"):
            hinweise.append("Vorhandenes Teil: Lage am Gegenstück anzeichnen oder Bohrschablone drucken, dann bohren")
        if any(e.get("gewinde") for e in ein0):
            hinweise.append("Gewinde: Kernloch bohren, mit Schneidöl in drei Gängen schneiden, Späne ausblasen")
        hinweise.append("Schutzbrille; Werkstück spannen, nicht von Hand halten")
        bohrbild = [e for _, es in mitglieder for e in es]
        out.append(schritt("bearbeiten", "bohren|" + "|".join(namen), titel,
                           f"Anreißen, körnen, bohren: {text}. Danach entgraten.", anzahl=n, teile=namen,
                           bohrbild=bohrbild, werkzeug=werkzeug, hinweise=hinweise))
    # Gewindeeinsätze einschmelzen und Stifte einkleben (je Wirtsteil, gleiche zusammengefasst)
    wirte: OrderedDict[str, list[Any]] = OrderedDict()
    lager: OrderedDict[str, list[Any]] = OrderedDict()
    for t in ein.aufbau():
        if t.rolle == "einsatz" and t.wirt:
            (lager if t.vm.get("typ") == "Bearing" else wirte).setdefault(t.wirt, []).append(t)
    sammel_l: OrderedDict[tuple, list[tuple[str, list[Any]]]] = OrderedDict()
    for w, ls in lager.items():
        typen = tuple(sorted(Counter(ws.stueck_name(e.name) for e in ls).items()))
        sammel_l.setdefault((ws.stueck_name(w), round(ein.teile[w].volumen, -1), typen), []).append((w, ls))
    for (wname, _, typen), mitglieder in sammel_l.items():
        n = len(mitglieder)
        inhalt = ", ".join(f"{k} × {name}" for name, k in typen)
        teile = [w for w, _ in mitglieder] + [e.name for _, ls in mitglieder for e in ls]
        out.append(schritt("bearbeiten", "lager|" + "|".join(teile), f"{_anzahl_text(n)}{wname}: Lager einpressen",
                           f"In {wname} je {inhalt} gerade einpressen, bis es anliegt; nur über den Außenring drücken.",
                           anzahl=n, teile=teile, neu=[e.name for _, ls in mitglieder for e in ls],
                           werkzeug=["Schraubstock mit Schonbacken oder Einpresswerkzeug", "passende Nuss als Druckstück"],
                           hinweise=["Nicht schlagen; Druckteil vorher entgraten, Sitz bei Bedarf leicht nacharbeiten",
                                     "Lager muss sich danach frei drehen"]))
    sammel: OrderedDict[tuple, list[tuple[str, list[Any]]]] = OrderedDict()
    for w, es in wirte.items():
        wt = ein.teile[w]
        typen = tuple(sorted(Counter(ws.stueck_name(e.name) for e in es).items()))
        sammel.setdefault((ws.stueck_name(w), round(wt.volumen, -1), typen), []).append((w, es))
    for (wname, _, typen), mitglieder in sammel.items():
        n = len(mitglieder)
        wt = ein.teile[mitglieder[0][0]]
        mat = str((wt.druck or {}).get("material") or wt.material or "")
        temp = ws.druck_info(mat).get("einsatz")
        inhalt = ", ".join(f"{k} × {name}" for name, k in typen)
        text = (f"In {wname} je {inhalt} einschmelzen"
                + (f": Lötkolben mit Einsatzspitze auf {temp} °C ({ws.druck_info(mat).get('name', mat)})" if temp
                   else "") + ", senkrecht ansetzen, 90 % einschmelzen, Rest mit einer flachen Platte bündig "
                              "eindrücken, abkühlen lassen.")
        teile = [w for w, _ in mitglieder] + [e.name for _, es in mitglieder for e in es]
        out.append(schritt("bearbeiten", "einsatz|" + "|".join(teile), f"{_anzahl_text(n)}{wname}: Gewindeeinsätze "
                           "einschmelzen", text, anzahl=n, teile=teile, neu=[e.name for _, es in mitglieder for e in es],
                           werkzeug=["Lötkolben mit Einsatzspitze", "flache Metallplatte zum Eindrücken"],
                           hinweise=["Lötspitze und Einsatz sind heiß: Ablage nutzen, nicht anfassen",
                                     "Einsatz gerade halten, nicht verkanten (sonst Gewinde schief)"]))
    # eingeklebte Gewindestifte
    stifte: OrderedDict[tuple, list[Any]] = OrderedDict()
    for t in ein.aufbau():
        if t.rolle == "vm" and t.wirt:
            stifte.setdefault((ws.stueck_name(t.name), round(float(t.vm.get("laenge") or 0), 1),
                               ws.stueck_name(_wirt_teil(ein, t.name))), []).append(t)
    for (sname, laenge, wname), ts in stifte.items():
        n = len(ts)
        einschraub = _einschraubtiefe(ein, ts[0])
        text = (f"{sname} mit Schraubensicherung mittelfest in {'die Einsätze' if n > 1 else 'den Einsatz'} von {wname} "
                f"drehen" + (f", Einschraubtiefe etwa {de_num(einschraub, 0)} mm" if einschraub else "")
                + "; Überstand wie gezeichnet, aushärten lassen (etwa 24 h).")
        werkzeug = ws.werkzeug_vm(ts[0].vm, ts[0].name) + ["Schraubensicherung mittelfest"]
        out.append(schritt("bearbeiten", "stift|" + "|".join(t.name for t in ts), f"{_anzahl_text(n)}{sname} "
                           "einkleben", text, anzahl=n, teile=[t.name for t in ts],
                           neu=[t.name for t in ts], werkzeug=werkzeug,
                           hinweise=["Klebstoff nur auf den eingeschraubten Teil, Überstand sauber halten"]))
    return out


def _wirt_teil(ein: Eingang, name: str) -> str:
    seen = set()
    while name not in seen:
        seen.add(name)
        t = ein.teile.get(name)
        if t is None or not t.wirt:
            return name
        name = t.wirt
    return name


def _einschraubtiefe(ein: Eingang, stift: Any) -> float | None:
    w = ein.teile.get(stift.wirt or "")
    a = stift.vm.get("achse")
    if w is None or a is None:
        return None
    a = np.asarray(a, dtype=float)
    ts = stift.koerper.pos @ a
    tw = w.koerper.pos @ a
    ueber = min(ts.max(), tw.max()) - max(ts.min(), tw.min())
    return float(ueber) if ueber > 0 else None


# ---------------------------------------------------------------------------------------------------------------------
# Drucken


SEITEN = {(0, 0, -1): ("Seite −Z (wie modelliert)", [0, 0, 0]), (0, 0, 1): ("Seite +Z", [180, 0, 0]),
          (1, 0, 0): ("Seite +X", [0, 90, 0]), (-1, 0, 0): ("Seite −X", [0, -90, 0]), (0, 1, 0): ("Seite +Y", [-90, 0, 0]),
          (0, -1, 0): ("Seite −Y", [90, 0, 0])}


def ausrichtung(t: Any) -> dict[str, Any]:
    """Druckausrichtung (Schätzung): die Seite mit der größten ebenen Auflage aufs Bett, bei Gleichstand die
    niedrigere."""
    pos = t.koerper.pos
    best = None
    for g, (name, rot) in SEITEN.items():
        gv = np.asarray(g, dtype=float)
        ext = float((pos @ gv).max()) if len(pos) else 0.0
        flaeche = 0.0
        for f in t.koerper.flaechen:
            if f.get("t") != "plane" or not f.get("n") or not f.get("c"):
                continue
            n = np.asarray(f["n"], dtype=float)
            if float(np.dot(n, gv)) > 0.999 and abs(float(np.dot(np.asarray(f["c"], float), gv)) - ext) < 0.05:
                flaeche += float(f.get("a") or 0.0)
        groesse = t.bmax - t.bmin
        hoehe = float(abs(np.dot(groesse, gv)))
        key = (round(flaeche, 0), -hoehe, g == (0, 0, -1))
        if best is None or key > best[0]:
            best = (key, name, rot, flaeche, hoehe, gv)
    _, name, rot, flaeche, hoehe, gv = best
    groesse = t.bmax - t.bmin
    quer = sorted(float(x) for i, x in enumerate(groesse) if abs(gv[i]) < 0.5)
    return {"unten": name, "drehung": rot, "auflage_mm2": round(flaeche, 1), "hoehe_mm": round(hoehe, 1),
            "grundriss_mm": [round(x, 1) for x in quer], "geschaetzt": True}


def drucken(ein: Eingang) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    linien = [ln for ln in (ein.bom or {}).get("lines") or [] if ln.get("art") == "druckteil"]
    erfasst: set[str] = set()
    gruppen: list[list[str]] = []
    gedruckt = {n for n, t in ein.teile.items() if t.rolle == "druck" and (t.druck or {}).get("gedruckt")}
    for line in linien:
        if line.get("gedruckt"):  # schon gedruckt (Strang „Feinschliff 2“): kein Druckschritt
            gedruckt.update(line.get("teile") or [])
            continue
        namen = [n for n in line.get("teile") or [] if n in ein.teile and ein.teile[n].rolle == "druck"
                 and n not in gedruckt]
        if namen:
            gruppen.append(namen)
            erfasst.update(namen)
    for t in ein.aufbau():  # Druckteile ohne Stücklistenzeile
        if t.rolle == "druck" and t.name not in erfasst and t.name not in gedruckt:
            gruppen.append([t.name])
    for namen in gruppen:
        t = ein.teile[namen[0]]
        n = len(namen)
        mat = str((t.druck or {}).get("material") or "petg")
        info = ws.druck_info(mat)
        a = ausrichtung(t)
        dp = ((ein.check or {}).get("druck") or {}).get("teile", {}).get(namen[0])  # Druckprüfung (main)
        hinweise = []
        if dp:  # Ausrichtung, Kennzahlen und Hinweise aus der Druckprüfung statt der eigenen Schätzung
            ar = dp.get("ausrichtung") or {}
            kz = dp.get("kennzahlen") or {}
            a = {"unten": ar.get("text") or a["unten"], "drehung": ar.get("drehung") or a["drehung"],
                 "auflage_mm2": kz.get("auflageflaeche_mm2", a["auflage_mm2"]),
                 "hoehe_mm": kz.get("hoehe_mm", a["hoehe_mm"]), "grundriss_mm": a["grundriss_mm"], "geschaetzt": False,
                 "begruendung": ar.get("begruendung"), "stuetzflaeche_mm2": kz.get("stuetzflaeche_mm2")}
            mi = (((ein.check or {}).get("druck") or {}).get("materialien") or {}).get(str(dp.get("material"))) or {}
            hinweise += [str(h) for h in (mi.get("druckhinweise") or [])[:2]]
            for b in (ein.check or {}).get("befunde") or []:
                if str(b.get("art", "")).startswith("druck_") and namen[0] in (b.get("teile") or []) \
                        and b.get("schwere") in ("fehler", "warnung", "hinweis"):
                    hinweise.append(f"{b.get('text')} → {b.get('loesung')}".strip(" →"))
            if a.get("stuetzflaeche_mm2"):
                hinweise.append(f"Stützen nötig: etwa {de_num(a['stuetzflaeche_mm2'], 0)} mm² (laut Druckprüfung)")
            info = {}
        if info:
            hinweise.append(f"{info.get('name')}: Düse {info.get('duese')} °C, Bett {info.get('bett')} °C"
                            + (f"; {info['hinweis']}" if info.get("hinweis") else ""))
        if a["auflage_mm2"] > 0 and a["hoehe_mm"] > 10 * math.sqrt(a["auflage_mm2"]):
            hinweise.append("Schlankes Teil: Brim 5 mm gegen Kippen")
        if a["auflage_mm2"] < 25:
            hinweise.append("Kleine Auflage: Brim oder andere Seite aufs Bett")
        g = a["grundriss_mm"]
        if len(g) == 2 and (g[1] > ws.BAURAUM[0] or a["hoehe_mm"] > ws.BAURAUM[2]):
            hinweise.append(f"Passt so nicht in den Bauraum ({de_num(ws.BAURAUM[0])} × {de_num(ws.BAURAUM[1])} × "
                            f"{de_num(ws.BAURAUM[2])} mm): anders legen oder teilen")
        if any(e.rolle == "einsatz" and e.wirt in namen for e in ein.teile.values()):
            hinweise.append("Taschen für Gewindeeinsätze maßhaltig drucken (keine Elefantenfuß-Korrektur dort)")
        if not dp:
            hinweise.append("Ausrichtung ist eine Schätzung (größte ebene Auflage); Druckprüfung im Slicer ansehen")
        elif a.get("begruendung"):
            hinweise.append(f"Ausrichtung: {a['begruendung']}")
        kg = float((t.druck or {}).get("kg") or t.masse_g / 1000.0)
        text = (f"{_anzahl_text(n)}{ws.stueck_name(t.name)} drucken, {a['unten']} aufs Bett "
                f"(Höhe {de_num(a['hoehe_mm'])} mm), je etwa {de_num(kg * 1000, 0)} g "
                f"{ws.druck_info(mat).get('name', mat.upper())}.")
        out.append(schritt("drucken", "|".join(namen), f"{_anzahl_text(n)}{ws.stueck_name(t.name)}", text,
                           anzahl=n, teile=namen,
                           druck={"teil": namen[0], "material": mat, "ausrichtung": a["drehung"],
                                  "seite": a["unten"], "hoehe_mm": a["hoehe_mm"], "auflage_mm2": a["auflage_mm2"],
                                  "masse_g": round(kg * 1000, 1), "hinweise": list(hinweise),
                                  "geschaetzt": not dp, "quelle": "druckpruefung" if dp else "schaetzung"},
                           werkzeug=["Bambu Lab P1P", "Spachtel", "Entgrater"], hinweise=hinweise))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Montage


def kurzname(t: Any) -> str:
    """„Linsenkopfschraube ISO 7380-1 M6 × 16“ aus dem Katalognamen (ohne Festigkeit und Oberfläche)."""
    if t.item and t.item.get("name"):
        n = re.split(r",\s", str(t.item["name"]))[0].strip()
        if not re.search(r"\bM\d", n) and t.vm.get("d"):
            n += f" M{de_num(t.vm['d'])}"
        if t.stock and t.stock.get("laenge") and t.rolle == "vm":
            n += f" × {de_num(t.stock['laenge'])}"
        return n
    return ws.stueck_name(t.name)


def _vm_eintraege(ein: Eingang, namen: list[str]) -> list[dict[str, Any]]:
    gruppen: OrderedDict[tuple, int] = OrderedDict()
    info: dict[tuple, dict[str, Any]] = {}
    for n in namen:
        t = ein.teile.get(n)
        if t is None or t.rolle != "vm":
            continue
        key = (t.stock.get("id") if t.stock else ws.stueck_name(n), (t.stock or {}).get("laenge"))
        gruppen[key] = gruppen.get(key, 0) + 1
        info[key] = {"id": key[0], "benennung": kurzname(t), "laenge": (t.stock or {}).get("laenge"),
                     "geschaetzt": t.stock is None}
    return [{**info[k], "anzahl": v} for k, v in gruppen.items()]


def _name(n: str) -> str:
    """Teilname ohne Baugruppe und ohne Klammerzusatz: „Seitenstange links“."""
    kurz = n.rsplit("/", 1)[-1]
    return re.sub(r"\s*\((?:Druck|Rohr \d+)\)\s*", " ", kurz).strip()


def _bezeichnung(ein: Eingang, e: Einbau, mehrere: bool = False) -> str:
    u = e.einheit
    if u.art == "gruppe":
        return f"Unterbaugruppe {u.name.rsplit('/', 1)[-1]}"
    if u.art in ("zukauf",):
        return u.name.rsplit("/", 1)[-1]
    t = ein.teile.get(u.haupt)
    if u.art == "vm" and t is not None:
        return kurzname(t)
    return ws.stueck_name(u.haupt) if mehrere else _name(u.haupt)


def _verbindungen_text(ein: Eingang, neu: set[str], montiert: set[str]) -> tuple[list[str], list[str], bool]:
    """Sätze zu den Verbindungen der neuen Teile mit dem schon Montierten (ohne Verbindungsmittel, ohne Verbindungen
    innerhalb der neuen Teile); Werkzeug; geschätzt?"""
    saetze: list[str] = []
    werkzeug: list[str] = []
    gesehen = set()
    for v in ein.verbindungen:
        if v.quelle not in ("verbinde", "gelenk") or v.b is None:
            continue
        if v.a in neu and v.b in montiert:
            teil, gegen = v.a, v.b
        elif v.b in neu and v.a in montiert:
            teil, gegen = v.b, v.a
        else:
            continue
        tt, gt = ein.teile.get(teil), ein.teile.get(gegen)
        if tt is None or gt is None or tt.rolle in ("vm", "einsatz") or gt.rolle in ("vm", "einsatz"):
            continue
        key = (v.art, ws.stueck_name(gegen))
        if key in gesehen:
            continue
        gesehen.add(key)
        g = _name(gegen)
        if v.art == "klemmung":
            saetze.append(f"an {g} klemmen")
        elif v.art in ("schiebegelenk", "zylindergelenk"):
            saetze.append(f"auf {g} schieben (muss leicht gleiten)")
        elif v.art == "drehgelenk":
            saetze.append(f"auf {g} stecken (muss sich frei drehen)")
        elif v.art == "kleben":
            saetze.append(f"mit {g} verkleben")
            werkzeug.append("Kleber (Schätzung)")
        elif v.art == "schraube":
            saetze.append(f"an {g} verschrauben")
        elif v.art == "steck":
            saetze.append(f"in {g} stecken")
        elif v.art == "formschluss":
            saetze.append(f"formschlüssig an {g} anlegen")
        elif v.art == "aufliegen":
            saetze.append(f"auf {g} legen")
        else:
            saetze.append(f"{VERBINDUNG_TEXT.get(v.art, v.art)} an {g}")
    return saetze, werkzeug, not ein.hat_verbinde


def _lage_auf_stange(ein: Eingang, neu: list[str], montiert: set[str], merk: dict[str, Any]) -> list[str]:
    """„Mitte auf 312 mm ab Ende A von Seitenstange links“ für Teile, die auf einer schon liegenden Stange sitzen."""
    out = []
    for v in ein.verbindungen:
        if v.art not in ("klemmung", "steck", "schiebegelenk", "zylindergelenk") or v.b is None:
            continue
        for teil, stange in ((v.a, v.b), (v.b, v.a)):
            st = ein.teile.get(stange)
            if teil not in neu or st is None or st.rolle != "stange" or (stange not in montiert and stange not in neu):
                continue
            m = merk.get(stange)
            if m is None or m.system.art != "stange":
                continue
            x = float(m.system.lokal(ein.teile[teil].zentrum)[0])
            laenge = float(m.system.groesse[0])
            if x < 1.0 or x > laenge - 1.0:
                continue  # sitzt am Ende: nichts zu messen
            out.append(f"{_name(teil)}: Mitte auf {de_num(x, 0)} mm ab Ende A von {_name(stange)}")
    return list(dict.fromkeys(out))


def _signatur(ein: Eingang, elemente: list[Einbau]) -> tuple:
    def art(n: str) -> tuple:
        t = ein.teile[n]
        if t.stock:
            return ("s", t.stock.get("id"), round(float(t.stock.get("laenge") or 0), 0))
        return (t.rolle, round(t.volumen, -1), tuple(sorted(np.round(t.bmax - t.bmin, 0).tolist())))

    out = []
    for e in elemente:
        r = None if e.richtung is None else ("z" if abs(float(e.richtung[2])) > 0.9 else "h")
        out.append((e.einheit.art, tuple(sorted(art(n) for n in e.einheit.teile)), r, e.zuerst is not None))
    return tuple(out)


def montage(ein: Eingang, folge: Folge, merk: dict[str, Any]) -> list[dict[str, Any]]:
    """Vormontagen in der Reihenfolge, in der die Hauptmontage ihre Unterbaugruppen braucht (innere zuerst), dann die
    Hauptmontage."""
    out: list[dict[str, Any]] = []
    erledigt: set[str] = set()

    def vor(seq: list[Einbau]) -> None:
        for e in seq:
            if e.einheit.art == "gruppe" and e.einheit.name in folge.vormontagen and e.einheit.name not in erledigt:
                erledigt.add(e.einheit.name)
                vor(folge.vormontagen[e.einheit.name])
                out.extend(_montage_ebene(ein, folge.vormontagen[e.einheit.name], e.einheit.name, merk))

    vor(folge.haupt)
    for name, seq in folge.vormontagen.items():  # übrige (sollte es nicht geben)
        if name not in erledigt:
            out.extend(_montage_ebene(ein, seq, name, merk))
    out += _montage_ebene(ein, folge.haupt, None, merk)
    return out


def _stangen_von(ein: Eingang, e: Einbau) -> set[str]:
    out = set()
    for t in e.einheit.teile:
        for n in ein.nachbarn(t):
            if ein.teile.get(n) is not None and ein.teile[n].rolle == "stange" and n not in e.einheit.teile:
                out.add(n)
    return out


def _gleiche_stange(ein: Eingang, a: list[Einbau], b: list[Einbau]) -> bool:
    """Schritt b nach a: gleiche Einführrichtung, b ist ein Teil (plus Verbindungsmittel) auf einer Stange, auf der
    auch das letzte Teil von a sitzt (Stellring, Rolle, Stellring nacheinander)."""
    ka, kb = [e for e in a if e.einheit.art != "vm"], [e for e in b if e.einheit.art != "vm"]
    if len(kb) != 1 or not ka or any(e.richtung is None for e in ka + kb) or kb[0].einheit.art == "gruppe":
        return False
    if any(ein.teile[e.einheit.haupt].rolle == "stange" for e in ka + kb if e.einheit.haupt in ein.teile):
        return False  # nur kleine Teile auf einer Stange, nicht die Stangen selbst
    if ka[-1].zuerst is not None or kb[0].zuerst is not None:
        return False
    if float(np.dot(ka[-1].richtung, kb[0].richtung)) < 0.999:
        return False
    return bool(_stangen_von(ein, ka[-1]) & _stangen_von(ein, kb[0]))


def _montage_ebene(ein: Eingang, seq: list[Einbau], baugruppe: str | None, merk: dict[str, Any]) -> list[dict]:
    # 1. Einbauten zu Schritten: ein Teil (oder Grundteil) mit den Verbindungsmitteln, die direkt danach kommen
    rohschritte: list[list[Einbau]] = []
    for e in seq:
        if e.einheit.art == "vm" and rohschritte:
            letzte = rohschritte[-1]
            teile = {n for x in letzte for n in x.einheit.teile}
            nb = {m for n in e.einheit.teile for m in ein.nachbarn(n, kontakt=True)}
            if nb & teile:
                letzte.append(e)
                continue
        rohschritte.append([e])
    # 2. kleine Teile nacheinander auf dieselbe Stange (Stellring, Rolle, Stellring) zu einem Schritt
    zusammen: list[list[Einbau]] = []
    for r in rohschritte:
        if zusammen and len([e for e in zusammen[-1] if e.einheit.art != "vm"]) < 4 \
                and _gleiche_stange(ein, zusammen[-1], r):
            zusammen[-1] += r
        else:
            zusammen.append(list(r))
    # 3. gleiche Schritte direkt hintereinander zusammenfassen (4× gleich)
    gruppen: list[list[list[Einbau]]] = []
    for r in zusammen:
        if gruppen and r[0].richtung is not None and gruppen[-1][0][0].richtung is not None \
                and _signatur(ein, gruppen[-1][0]) == _signatur(ein, r):
            gruppen[-1].append(r)
        else:
            gruppen.append([r])
    out = []
    montiert: set[str] = set()
    for g in gruppen:
        n = len(g)
        alle = [e for r in g for e in r]
        haupt = g[0][0]
        neu = [t for e in alle for t in e.einheit.teile]
        vm_namen = [t for e in alle if e.einheit.art == "vm" for t in e.einheit.teile]
        lose = [t for e in alle if e.mit_vm for t in e.einheit.teile
                if ein.teile.get(t) is not None and ein.teile[t].rolle == "vm" and not ein.teile[t].wirt]
        vm_namen += lose
        kern = [e for e in g[0] if e.einheit.art != "vm"] or [g[0][0]]
        namen_kern = [_bezeichnung(ein, e, n > 1) for e in kern]
        bez = namen_kern[0] if len(namen_kern) == 1 else ", ".join(namen_kern[:-1]) + " und " + namen_kern[-1]
        grund = haupt.richtung is None
        if grund:
            if haupt.einheit.art == "gruppe":
                titel = f"Vormontierte {bez} bereitstellen"
                text = f"{bez} aus der Vormontage als Grundteil hinstellen."
            elif haupt.einheit.art in ("zukauf", "kauf"):
                titel = f"{bez} bereitstellen"
                text = f"{bez} (vorhanden) als Grundteil hinstellen und prüfen."
            else:
                titel = f"{bez} als Grundteil auflegen"
                text = f"{bez} als Grundteil auf die Werkbank legen."
        else:
            verb = "anbringen" if haupt.einheit.art == "vm" else "einbauen"
            titel = f"{_anzahl_text(n)}{bez} {verb}"
            if haupt.einheit.art == "vm":  # nur Verbindungsmittel: woran?
                ziel = [m for t in neu for m in ein.nachbarn(t, kontakt=True)
                        if m in montiert and ein.teile.get(m) is not None and ein.teile[m].rolle not in ("vm", "einsatz")]
                if ziel:
                    namen_vm = list(dict.fromkeys(_bezeichnung(ein, e, n > 1) for r in g for e in r))
                    bez = " und ".join(namen_vm[:2])
                    titel = f"{_anzahl_text(n)}{bez} an {_name(ziel[0])} anbringen"
            satz, _, _ = _verbindungen_text(ein, set(neu), montiert)
            nacheinander = " nacheinander" if len(kern) > 1 else ""
            text = f"{bez}{nacheinander} {haupt.richtung_text} einsetzen"
            if satz:
                text += ", " + ", ".join(satz[:3])
            text += "."
        vm = _vm_eintraege(ein, vm_namen)
        if lose:
            lv = _vm_eintraege(ein, lose)
            text += (" Vorher " + " und ".join(x["benennung"] for x in lv) + " lose in die Klemme drehen; nach dem "
                     "Ausrichten anziehen.")
        if vm and haupt.einheit.art == "vm" and not grund:
            text = text.rstrip(".").replace(" einsetzen", " ansetzen") + " und anziehen."
        elif vm and not lose:
            je = " je Stelle" if n > 1 else ""
            text += " " + ", ".join(f"{x['anzahl'] // n if n > 1 else x['anzahl']} × {x['benennung']}" for x in vm) + \
                f"{je} ansetzen und anziehen."
        werkzeug: list[str] = []
        for t in vm_namen:
            werkzeug += ws.werkzeug_vm(ein.teile[t].vm, t)
        _, wz2, geschaetzt = _verbindungen_text(ein, set(neu), montiert)
        werkzeug += wz2
        werkzeug = list(dict.fromkeys(werkzeug))
        hinweise = []
        if haupt.einheit.art != "gruppe":
            lage = _lage_auf_stange(ein, neu, montiert, merk)
            if lage:
                hinweise.append("Lage: " + "; ".join(lage[:4]) + (" …" if len(lage) > 4 else ""))
        for e in alle:
            if e.aufbocken > 0 and e.einheit.art != "vm":
                hinweise.append(f"Einbau von unten: Baugruppe mindestens {de_num(math.ceil(e.aufbocken / 10) * 10, 0)}"
                                " mm aufbocken oder auf den Kopf stellen")
                break
        if not grund and any(v.art in ("drehgelenk", "schiebegelenk", "zylindergelenk") and v.quelle == "gelenk"
                             and not (ein.teile.get(v.a) and ein.teile[v.a].rolle == "vm")
                             and ((v.a in neu and v.b in montiert) or (v.b in neu and v.a in montiert))
                             for v in ein.verbindungen):
            hinweise.append("Bewegliches Teil: Finger aus dem Bewegungsbereich, Quetschstellen beachten")
        if "von Hand" in werkzeug:
            hinweise.append("Flügelmuttern nur handfest anziehen")
        if geschaetzt and not grund:
            hinweise.append("Verbindung geschätzt (Modell ohne verbinde): Befestigung prüfen")
        einbau = []
        for e in alle:
            einbau.append({"name": e.einheit.name, "art": e.einheit.art, "teile": list(e.einheit.teile),
                           "mit_vm": list(e.mit_vm),
                           "haupt": e.einheit.haupt, "richtung": _r(e.richtung, 4), "zuerst": _r(e.zuerst, 4),
                           "weg": _r(e.weg, 1), "aufbocken": _r(e.aufbocken, 1), "grundteil": e.richtung is None,
                           "erzwungen": e.erzwungen, "sperrer": list(e.sperrer)})
        key = (baugruppe or "") + "|" + "|".join(sorted(neu))
        s = schritt("montage", key, titel, text, anzahl=n, teile=neu, neu=neu, baugruppe=baugruppe,
                    verbindungsmittel=vm, werkzeug=werkzeug, hinweise=hinweise, einbau=einbau,
                    geschaetzt=bool(geschaetzt))
        out.append(s)
        montiert.update(neu)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Ganzes Gerüst


def geruest(ein: Eingang, folge: Folge) -> dict[str, Any]:
    namen = [t.name for t in ein.aufbau() if t.rolle in ("stange", "platte", "zukauf", "kauf", "eigen", "druck")]
    merk = merkmale_fuer(ein, namen)
    abschnitte = []
    inhalt = {"material": material(ein), "zuschnitt": zuschnitt(ein), "bearbeiten": bearbeiten(ein, merk),
              "drucken": drucken(ein), "montage": montage(ein, folge, merk)}
    for art, titel in ABSCHNITTE:
        abschnitte.append({"art": art, "titel": titel, "schritte": inhalt[art]})
    return {"version": 1, "titel": ein.titel, "abschnitte": abschnitte}

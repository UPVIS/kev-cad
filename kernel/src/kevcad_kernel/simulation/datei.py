"""``<projekt>/simulation.json``: Lastfälle, Lasten, Lager und Topologie-Einstellungen aus der App (und vom Agenten über
MCP ``simulation_aendern``), Vorbild ist ``druck.json`` (DRUCKVORSCHAU.md): eine Projektdatei neben model.py, die Läufe
überlebt, zu den Versionen gehört und bei jedem Lauf zusätzlich zu den Szenarien aus model.py geladen wird. Gleicher
Name wie ein Szenario aus model.py: die Fassung aus der App gewinnt (mit Hinweis).

Format (``version`` 1)::

    {"version": 1, "stand": 7, "geaendert": "2026-10-23T14:02:11", "von": "kevin",
     "lastfaelle": [{"name": "Aufstützen 30 kg", "art": "statisch", "beschreibung": "", "kopie_von": null,
                     "neigung": {"grad": 10, "richtung": "+y"}, "beschleunigung": [-3, 0, 0],
                     "fahrt": {"geschwindigkeit": 1.0, "bremsen": "abrupt", "dauer": null, "animation": null,
                               "angriff": "boden", "fahrtrichtung": "+x", "antrieb": null},
                     "stoss": 2.0, "untergrund": "holz", "ziel": {"sicherheit": 2.5, "durchbiegung": 300},
                     "lasten": [{"id": "L1", "teil": "Rahmen/Rohr", "gegen": null,
                                 "ort": {"flaeche": 12, "punkt": [250, 0, 30], "normale": [0, 0, 1],
                                         "signatur": {"t": "plane", "a": 200.0, "n": [0, 0, 1], "c": [250, 0, 30]}},
                                 "richtung": {"art": "normale"}, "betrag": 30, "einheit": "kg",
                                 "kraft": [0, 0, -294.3]}]}],
     "lager": [{"id": "A1", "teil": "Halter", "art": "fest", "ort": {"flaeche": 3, "punkt": null, …},
                "szenarien": null},
               {"id": "A2", "teil": "Schlitten", "art": "gleitend", "ort": {"flaeche": 5, …},
                "gleiten": {"art": "richtung", "richtung": [1, 0, 0], "quelle": "kante", "kante": 7},
                "szenarien": ["Aufstützen 30 kg"]}],
     "abgeleitet_aus": ["boden:Rahmen/Fuß links"],
     "topologie": {"Halter": {"szenario": "Bolzen 50 N", "behalten": 0.42, "ueberhang": false, "fein": false,
                              "steg": 6, "bohrungen": true, "einsaetze": true, "kontakt": true, "bett": false,
                              "lager": "kontakt", "schutz": [{"art": "index", "index": 7}]}}}

- ``stand`` zählt jede Änderung (App und Agent); eine Änderung mit veraltetem ``basis`` lehnt die Laufzeit ab.
- Lasten und Lager beziehen sich auf **Teilnamen** aus ``show()`` und **Flächen-Referenzen** (Nummer wie im Viewer plus
  ``signatur`` wie ``PART_UPSERT.faces[i]``). Nach Modelländerungen ordnet ``zuordnung.py`` sie neu zu oder markiert
  sie als „nicht mehr zuordenbar“; die Datei bleibt dabei unverändert.
- ``kraft`` (N, Welt) rechnet der Kernel aus Richtung und Betrag (``kraft.py``) und nach einer Neuzuordnung neu.
- Lager gelten für alle Lastfälle (``szenarien`` fehlt oder null) oder nur für die genannten (``szenarien``: Namen von
  Lastfällen der App oder Szenarien aus model.py; ``[]`` = in keinem, also aus). Ein gleitendes Lager gleitet in der
  Fläche (``gleiten`` fehlt oder ``{"art": "flaeche"}``: hält nur senkrecht zur Fläche, die Normale genau, nicht auf eine
  Achse gerundet) oder nur entlang einer Richtung (``{"art": "richtung", "richtung": [x, y, z]}``: Schiene, hält quer
  dazu in beide Richtungen; ``quelle`` achse, kante oder frei, ``kante`` die angeklickte Kante). ``abgeleitet_aus``
  schaltet von selbst abgeleitete Lager aus (``boden:<teil>`` = steht auf dem Boden bzw. der Kulisse,
  ``kontakt:<teil>|<nachbar>`` = Kontakt trägt im Bauteil-Nachweis und in der FEM).
- Eine Last greift am Klickpunkt an (``verteilung`` fehlt oder ``punkt``; in der FEM im Umkreis verteilt) oder
  gleichmäßig auf der ganzen angeklickten Fläche (``verteilung`` ``flaeche``), dort auch als Druck (``einheit`` ``N/mm2``,
  senkrecht auf die Fläche, Kraft = Druck × Fläche).

Änderungen kommen als Liste von Operationen (``anwenden``), aus der App (``SIM_EDIT``) und vom Agenten gleich.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.simulation import kraft as kr

DATEI = "simulation.json"
VERSION = 1
ARTEN = ("statisch", "dynamisch")
LAGERARTEN = ("fest", "gelenkig", "gleitend")
LAGER_AUF = ("flaeche", "punkt", "teil")  # Lagerfläche: ganze Fläche, Umkreis eines Punkts, ganzes Teil
GLEITEN = ("flaeche", "richtung")  # gleitendes Lager: in der Fläche oder nur entlang einer Richtung (Schiene)
GLEIT_QUELLEN = ("achse", "kante", "frei")
VERTEILUNGEN = ("punkt", "flaeche")  # Last am Klickpunkt (im Umkreis) oder gleichmäßig auf der ganzen Fläche
BREMSARTEN = ("abrupt", "anprall")
RICHTUNGEN_TEXT = ("+x", "-x", "+y", "-y")
TOPO_SCHLUESSEL = ("szenario", "behalten", "ueberhang", "fein", "steg", "bett", "bohrungen", "einsaetze", "kontakt",
                   "lager", "schutz")
OPS = ("lastfall_neu", "lastfall_setzen", "lastfall_kopieren", "lastfall_umbenennen", "lastfall_loeschen",
       "last_setzen", "last_loeschen", "lager_setzen", "lager_loeschen", "abgeleitet", "topologie")
LASTFALL_FELDER = ("art", "beschreibung", "neigung", "beschleunigung", "fahrt", "stoss", "untergrund", "ziel")
NAME_MAX = 80


class SimulationFehler(ValueError):
    pass


def pfad(projekt: str | Path) -> Path:
    return Path(projekt) / DATEI


def leer() -> dict[str, Any]:
    return {"version": VERSION, "stand": 0, "lastfaelle": [], "lager": [], "abgeleitet_aus": [], "topologie": {}}


def lies(projekt: str | Path | None) -> dict[str, Any]:
    """Inhalt der Datei (fehlt sie, ein leeres Dokument). Kaputte Dateien gelten als leer, mit ``fehler``."""
    if projekt is None:
        return leer()
    p = pfad(projekt)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return leer()
    except (OSError, ValueError) as exc:
        return {**leer(), "fehler": f"simulation.json nicht lesbar: {exc}"}
    if not isinstance(d, dict):
        return {**leer(), "fehler": "simulation.json muss ein Objekt {\"version\": 1, …} sein"}
    out = leer()
    out.update({k: v for k, v in d.items() if k in ("version", "stand", "geaendert", "von")})
    for k, typ in (("lastfaelle", list), ("lager", list), ("abgeleitet_aus", list), ("topologie", dict)):
        v = d.get(k)
        if isinstance(v, typ):
            out[k] = v
    out["lastfaelle"] = [l for l in out["lastfaelle"] if isinstance(l, dict) and str(l.get("name") or "").strip()]
    for l in out["lastfaelle"]:
        l.setdefault("lasten", [])
        l["lasten"] = [x for x in l["lasten"] if isinstance(x, dict) and x.get("teil")]
    out["lager"] = [x for x in out["lager"] if isinstance(x, dict) and x.get("teil")]
    try:
        out["stand"] = int(out.get("stand") or 0)
    except (TypeError, ValueError):
        out["stand"] = 0
    return out


def schreibe(projekt: str | Path, doc: dict[str, Any], von: str = "kevin") -> dict[str, Any]:
    """Atomar schreiben (neuer ``stand``); ein leeres Dokument löscht die Datei nicht, damit die Versionen die
    Änderung sehen."""
    d = {k: v for k, v in doc.items() if k != "fehler"}
    d["version"] = VERSION
    d["stand"] = int(doc.get("stand") or 0) + 1
    d["geaendert"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    d["von"] = von
    p = pfad(projekt)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return d


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen und vereinheitlichen


def _zahl(v: Any, was: str, lo: float | None = None, hi: float | None = None, null_ok: bool = True) -> float | None:
    if v is None or v == "":
        if null_ok:
            return None
        raise SimulationFehler(f"{was} fehlt")
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise SimulationFehler(f"{was} {v!r} ist keine Zahl") from exc
    if not math.isfinite(x):
        raise SimulationFehler(f"{was} ist keine endliche Zahl")
    if lo is not None and x < lo or hi is not None and x > hi:
        raise SimulationFehler(f"{was} {x:g} liegt außerhalb von {lo:g} bis {hi:g}")
    return x


def _name(n: Any, was: str = "Name") -> str:
    t = str(n or "").strip()
    if not t:
        raise SimulationFehler(f"{was} fehlt")
    if len(t) > NAME_MAX:
        raise SimulationFehler(f"{was} ist länger als {NAME_MAX} Zeichen")
    return t


def _vec(v: Any, was: str) -> list[float] | None:
    if v is None:
        return None
    try:
        return [round(float(c), 6) + 0.0 for c in kr.vektor(v, was)]
    except kr.KraftFehler as exc:
        raise SimulationFehler(str(exc)) from exc


def _richtung_text(r: Any) -> Any:
    if isinstance(r, str):
        t = r.strip().lower().replace("−", "-")
        if t and t[0] not in "+-":
            t = "+" + t
        if t not in RICHTUNGEN_TEXT:
            raise SimulationFehler(f"Richtung {r!r} unbekannt (+x, -x, +y, -y oder Vektor)")
        return t
    v = _vec(r, "Richtung")
    if v is None or math.hypot(v[0], v[1]) < 1e-9:
        raise SimulationFehler("Richtung muss waagrecht sein (x, y, 0)")
    n = math.hypot(v[0], v[1])
    for t, (x, y) in (("+x", (1, 0)), ("-x", (-1, 0)), ("+y", (0, 1)), ("-y", (0, -1))):
        if abs(v[0] / n - x) < 1e-6 and abs(v[1] / n - y) < 1e-6:
            return t
    return v


def pruefe_lastfall(l: dict[str, Any]) -> dict[str, Any]:
    """Felder eines Lastfalls vereinheitlichen (ohne Lasten)."""
    out: dict[str, Any] = {}
    if "art" in l:
        a = str(l.get("art") or "statisch")
        if a not in ARTEN:
            raise SimulationFehler(f"Art {a!r} unbekannt (statisch oder dynamisch)")
        out["art"] = a
    if "beschreibung" in l:
        out["beschreibung"] = str(l.get("beschreibung") or "")[:400]
    if "neigung" in l:
        n = l.get("neigung")
        if n in (None, {}, 0, 0.0):
            out["neigung"] = None
        else:
            if isinstance(n, (int, float)):
                n = {"grad": n}
            g = _zahl(n.get("grad"), "Neigung", 0.0, 60.0, null_ok=False)
            out["neigung"] = None if not g else {"grad": g, "richtung": _richtung_text(n.get("richtung") or "+x")}
    if "beschleunigung" in l:
        b = _vec(l.get("beschleunigung"), "Beschleunigung")
        if b is not None and max(abs(c) for c in b) > 100:
            raise SimulationFehler("Beschleunigung über 100 m/s²: bitte prüfen")
        out["beschleunigung"] = None if b is None or not any(abs(c) > 1e-12 for c in b) else b
    if "fahrt" in l:
        f = l.get("fahrt")
        if not f:
            out["fahrt"] = None
        else:
            v = _zahl(f.get("geschwindigkeit"), "Geschwindigkeit", 0.0, 20.0)
            if (v is None or v <= 0) and not f.get("animation"):
                raise SimulationFehler("Fahrt braucht eine Geschwindigkeit (m/s) oder eine Animation als Antrieb")
            br = f.get("bremsen")
            if isinstance(br, str) and br not in BREMSARTEN:
                br = _zahl(br, "Bremsen (m/s²)", 0.05, 100.0)
            elif br is not None and not isinstance(br, str):
                br = _zahl(br, "Bremsen (m/s²)", 0.05, 100.0)
            ang = f.get("angriff")
            if ang not in (None, "boden"):
                ang = _zahl(ang, "Angriffshöhe (mm)", 0.0, 5000.0)
            fr = f.get("fahrtrichtung")
            out["fahrt"] = {"geschwindigkeit": v, "bremsen": br, "dauer": _zahl(f.get("dauer"), "Dauer", 0.1, 30.0),
                            "animation": (str(f["animation"]) if f.get("animation") else None),
                            "angriff": ang or "boden", "fahrtrichtung": _richtung_text(fr) if fr else "+x",
                            "antrieb": str(f["antrieb"]) if f.get("antrieb") else None}
    if "stoss" in l:
        s = _zahl(l.get("stoss"), "Stoßfaktor", 1.0, 10.0)
        out["stoss"] = None if s is None or abs(s - 1.0) < 1e-9 else s
    if "untergrund" in l:
        u = l.get("untergrund")
        out["untergrund"] = str(u).strip() if u else None
    if "ziel" in l:
        z = l.get("ziel") or {}
        if not isinstance(z, dict):
            z = {"sicherheit": z}
        sich = _zahl(z.get("sicherheit"), "Ziel-Sicherheit", 1.0, 20.0)
        db = z.get("durchbiegung")
        if isinstance(db, str):
            db = db.replace("L/", "").strip() or None
        db = _zahl(db, "Durchbiegung (L/…)", 20.0, 5000.0)
        out["ziel"] = None if sich is None and db is None else {"sicherheit": sich, "durchbiegung": db}
    return out


def pruefe_ort(o: Any) -> dict[str, Any]:
    o = dict(o or {})
    out: dict[str, Any] = {"flaeche": None, "punkt": _vec(o.get("punkt"), "Punkt"),
                           "normale": _vec(o.get("normale"), "Normale"), "signatur": None}
    if o.get("flaeche") is not None:
        try:
            i = int(o["flaeche"])
        except (TypeError, ValueError) as exc:
            raise SimulationFehler(f"Fläche {o['flaeche']!r} ist keine Nummer") from exc
        if i < 0:
            raise SimulationFehler("Fläche: Nummer ab 0")
        out["flaeche"] = i
    if isinstance(o.get("signatur"), dict):
        s = o["signatur"]
        sig: dict[str, Any] = {"t": str(s.get("t") or "other")}
        for k in ("a", "r", "r2", "ang"):
            if s.get(k) is not None:
                sig[k] = round(float(s[k]), 4)
        for k in ("n", "c", "ax"):
            if s.get(k) is not None:
                sig[k] = _vec(s[k], k)
        out["signatur"] = sig
    if out["normale"] is not None:
        try:
            out["normale"] = [round(float(c), 6) + 0.0 for c in kr.einheit(out["normale"], "Normale")]
        except kr.KraftFehler as exc:
            raise SimulationFehler(str(exc)) from exc
    return out


def pruefe_last(x: dict[str, Any], alt: dict[str, Any] | None = None) -> dict[str, Any]:
    """Last vereinheitlichen und die Kraft aus Richtung und Betrag rechnen (``kraft.py``)."""
    base = dict(alt or {})
    base.update({k: v for k, v in x.items() if k != "kraft"})
    teil = _name(base.get("teil"), "Teil der Last")
    gegen = str(base.get("gegen")).strip() if base.get("gegen") else None
    if gegen == teil:
        raise SimulationFehler("Kraftpaar: das Gegenstück muss ein anderes Teil sein als das belastete")
    ort = pruefe_ort(base.get("ort"))
    einh = kr.einheit_text(base.get("einheit"))
    verteilung = str(base.get("verteilung") or "punkt")
    if verteilung not in VERTEILUNGEN:
        raise SimulationFehler(f"Verteilung {verteilung!r} unbekannt (punkt oder flaeche)")
    if verteilung == "flaeche" and ort.get("flaeche") is None:
        raise SimulationFehler("Last auf der ganzen Fläche: eine Fläche anklicken")
    richtung = dict(base.get("richtung") or {"art": "achse" if einh == "kg" else "normale"})
    if einh == kr.DRUCK:
        if verteilung != "flaeche":
            raise SimulationFehler("Druck (N/mm²) wirkt auf die ganze Fläche: Verteilung „ganze Fläche“ wählen")
        if (richtung.get("art") or "normale") != "normale":
            raise SimulationFehler("Druck (N/mm²) wirkt senkrecht auf die Fläche (Richtung „Normale“, umkehren zieht); "
                                   "für eine andere Richtung die Gesamtkraft in N angeben")
    flaeche_mm2 = (ort.get("signatur") or {}).get("a")
    try:
        F = kr.kraft_aus(richtung, base.get("betrag"), einh, ort.get("normale"), flaeche_mm2=flaeche_mm2)
    except kr.KraftFehler as exc:
        raise SimulationFehler(str(exc)) from exc
    r = {"art": richtung.get("art") or "normale"}
    if r["art"] == "achse":
        r["achse"] = str(richtung.get("achse") or "-z")
    elif r["art"] == "frei":
        if richtung.get("vektor") is not None:
            r["vektor"] = _vec(richtung["vektor"], "Richtung")
        else:
            r["azimut"] = float(richtung.get("azimut") or 0.0)
            r["hoehe"] = float(richtung.get("hoehe") or 0.0)
    if richtung.get("umkehren"):
        r["umkehren"] = True
    out = {"id": str(base.get("id") or ""), "teil": teil, "gegen": gegen, "ort": ort, "richtung": r,
           "betrag": float(base["betrag"]), "einheit": einh, "kraft": kr.kurz(F)}
    if verteilung != "punkt":
        out["verteilung"] = verteilung
    return out


def pruefe_lager(x: dict[str, Any], alt: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(alt or {})
    base.update(x)
    teil = _name(base.get("teil"), "Teil des Lagers")
    art = str(base.get("art") or "fest")
    if art not in LAGERARTEN:
        raise SimulationFehler(f"Lagerart {art!r} unbekannt (fest, gelenkig, gleitend)")
    ort = pruefe_ort(base.get("ort"))
    auf = str(base.get("auf") or ("flaeche" if ort.get("flaeche") is not None else
                                  ("punkt" if ort.get("punkt") is not None else "teil")))
    if auf not in LAGER_AUF:
        raise SimulationFehler(f"Lager auf {auf!r}? (flaeche, punkt oder teil)")
    if auf == "flaeche" and ort.get("flaeche") is None:
        raise SimulationFehler("Lager auf einer Fläche: Fläche anklicken")
    if auf == "punkt" and ort.get("punkt") is None:
        raise SimulationFehler("Lager an einem Punkt: Punkt anklicken")
    gleiten = pruefe_gleiten(base.get("gleiten")) if art == "gleitend" else None
    if art == "gleitend" and gleiten is None and ort.get("normale") is None \
            and (ort.get("signatur") or {}).get("n") is None:
        raise SimulationFehler("Ein gleitendes Lager braucht eine Fläche mit Normale (es hält nur senkrecht dazu) "
                               "oder eine Gleitrichtung (Achse, Kante)")
    out = {"id": str(base.get("id") or ""), "teil": teil, "art": art, "auf": auf, "ort": ort,
           "szenarien": pruefe_szenarien(base.get("szenarien"))}
    if gleiten is not None:
        out["gleiten"] = gleiten
    return out


def pruefe_szenarien(v: Any) -> list[str] | None:
    """Lastfälle eines Lagers: None = alle, sonst Namen (ohne Doppelte, Reihenfolge bleibt); [] = in keinem."""
    if v is None or v == "alle":
        return None
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        raise SimulationFehler("szenarien: Liste von Lastfällen oder null (= alle Lastfälle)")
    out: list[str] = []
    for n in v:
        t = _name(n, "Lastfall des Lagers")
        if t not in out:
            out.append(t)
    return out


def pruefe_gleiten(g: Any) -> dict[str, Any] | None:
    """Gleitrichtung eines gleitenden Lagers: None (in der Fläche, ``{"art": "flaeche"}`` ebenso) oder {"art":
    "richtung", "richtung": [x, y, z] bzw. "+x", "quelle": "achse" | "kante" | "frei", "kante": n}."""
    if g is None or g == "flaeche":
        return None
    if isinstance(g, (str, list, tuple)):
        g = {"art": "richtung", "richtung": g}
    if not isinstance(g, dict):
        raise SimulationFehler('gleiten: {"art": "flaeche"} oder {"art": "richtung", "richtung": [x, y, z]}')
    art = str(g.get("art") or ("richtung" if g.get("richtung") is not None else "flaeche"))
    if art not in GLEITEN:
        raise SimulationFehler(f"gleiten {art!r} unbekannt (flaeche oder richtung)")
    if art == "flaeche":
        return None
    r = g.get("richtung")
    quelle = str(g.get("quelle") or ("achse" if isinstance(r, str) else "frei"))
    if quelle not in GLEIT_QUELLEN:
        raise SimulationFehler(f"gleiten.quelle {quelle!r} unbekannt (achse, kante, frei)")
    try:
        d = kr.achse(r) if isinstance(r, str) else kr.einheit(r, "Gleitrichtung")
    except kr.KraftFehler as exc:
        raise SimulationFehler(str(exc)) from exc
    out: dict[str, Any] = {"art": "richtung", "richtung": [round(float(c), 6) + 0.0 for c in d], "quelle": quelle}
    if g.get("kante") is not None:
        out["kante"] = int(g["kante"])
    return out


def pruefe_topologie(e: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (e or {}).items():
        if k not in TOPO_SCHLUESSEL or v is None:
            continue
        if k == "behalten":
            out[k] = _zahl(v, "Behalten", 0.05, 0.95)
        elif k == "steg":
            out[k] = _zahl(v, "Mindeststeg (Linienbreiten)", 2.0, 40.0)
        elif k in ("ueberhang", "fein", "bett", "bohrungen", "einsaetze", "kontakt"):
            out[k] = bool(v)
        elif k == "lager":
            out[k] = "bohrungen" if str(v) == "bohrungen" else "kontakt"
        elif k == "szenario":
            out[k] = str(v)
        elif k == "schutz":
            zonen = []
            for z in v or []:
                if not isinstance(z, dict) or z.get("art") != "index" or z.get("index") is None:
                    raise SimulationFehler("Schutzzone: {\"art\": \"index\", \"index\": Flächennummer} erwartet")
                zonen.append({"art": "index", "index": int(z["index"]),
                              **({"signatur": pruefe_ort({"signatur": z["signatur"]})["signatur"]}
                                 if isinstance(z.get("signatur"), dict) else {})})
            out[k] = zonen
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Operationen


def _lastfall(doc: dict[str, Any], name: str) -> dict[str, Any]:
    for l in doc["lastfaelle"]:
        if l.get("name") == name:
            return l
    raise SimulationFehler(f"Lastfall {name!r} gibt es in der App nicht"
                           + (f" (vorhanden: {', '.join(repr(x['name']) for x in doc['lastfaelle'])})"
                              if doc["lastfaelle"] else ""))


def _neue_id(vorhanden: set[str], praefix: str) -> str:
    i = 1
    while f"{praefix}{i}" in vorhanden:
        i += 1
    return f"{praefix}{i}"


def _alle_last_ids(doc: dict[str, Any]) -> set[str]:
    return {str(x.get("id")) for l in doc["lastfaelle"] for x in l.get("lasten") or []}


def neuer_lastfall(name: str, felder: dict[str, Any] | None = None) -> dict[str, Any]:
    l: dict[str, Any] = {"name": name, "art": "statisch", "beschreibung": "", "kopie_von": None, "neigung": None,
                         "beschleunigung": None, "fahrt": None, "stoss": None, "untergrund": None, "ziel": None,
                         "lasten": []}
    l.update(pruefe_lastfall(felder or {}))
    if l.get("fahrt") and "art" not in (felder or {}):
        l["art"] = "dynamisch"
    return l


def aus_szenario_kurz(name: str, kurz: dict[str, Any], von: str) -> dict[str, Any]:
    """App-Lastfall aus der Kurzfassung eines Szenarios (``Szenario.kurz``, aus model.py oder Standard): Neigung,
    Beschleunigung, Fahrt, Stoß, Ziel und Lasten (Punkt und Kraft, Richtung frei)."""
    l = neuer_lastfall(name)
    l["kopie_von"] = von
    l["beschreibung"] = str(kurz.get("beschreibung") or "")
    l["art"] = "dynamisch" if kurz.get("art") == "dynamisch" else "statisch"
    ab = kurz.get("ablauf") if isinstance(kurz.get("ablauf"), dict) else None
    b = kurz.get("beschleunigung")
    if b and any(abs(float(c)) > 1e-9 for c in b) and not ab:
        l["beschleunigung"] = [float(c) for c in b]
    ng = kurz.get("neigung")
    if isinstance(ng, dict) and ng.get("grad"):
        r = ng.get("richtung") or [1.0, 0, 0]
        l["neigung"] = {"grad": float(ng["grad"]), "richtung": _richtung_text([float(r[0]), float(r[1]), 0.0])}
    if kurz.get("stossfaktor"):
        l["stoss"] = float(kurz["stossfaktor"])
    # Ziel: die Kurzfassung nennt nur das wirksame Ziel; eigene Ziele aus st.ziel() gelten für die Kopie weiter
    if ab:
        l["fahrt"] = pruefe_lastfall({"fahrt": {k: ab.get(k) for k in ("geschwindigkeit", "bremsen", "dauer",
                                                                        "animation", "angriff", "antrieb")}
                                      | {"fahrtrichtung": ab.get("fahrtrichtung")}})["fahrt"]
    ids: set[str] = set()
    for x in kurz.get("lasten") or []:
        teile = x.get("teile") or []
        if not teile:
            continue
        F = [float(c) for c in x.get("kraft") or (0, 0, 0)]
        betrag = math.sqrt(sum(c * c for c in F))
        if betrag < 1e-9:
            continue
        kg = x.get("kg")
        unten = abs(F[0]) < 1e-9 and abs(F[1]) < 1e-9 and F[2] < 0
        last = {"id": _neue_id(ids, "L"), "teil": teile[0], "gegen": (x.get("gegen") or [None])[0],
                "ort": {"punkt": x.get("punkt")},
                "richtung": {"art": "achse", "achse": "-z"} if unten else {"art": "frei", "vektor": F},
                "betrag": float(kg) if kg and unten else betrag, "einheit": "kg" if kg and unten else "N"}
        ids.add(last["id"])
        l["lasten"].append(pruefe_last(last))
    return l


def anwenden(doc: dict[str, Any], ops: list[dict[str, Any]], modell_szenarien: dict[str, dict[str, Any]] | None = None
             ) -> tuple[dict[str, Any], list[str]]:
    """Operationen auf eine Kopie des Dokuments anwenden; Fehler in einer Operation verwirft alle (SimulationFehler).
    Rückgabe (neues Dokument, Meldungen)."""
    d = copy.deepcopy(doc)
    d.setdefault("lastfaelle", [])
    d.setdefault("lager", [])
    d.setdefault("abgeleitet_aus", [])
    d.setdefault("topologie", {})
    meldungen: list[str] = []
    if not isinstance(ops, list) or not ops:
        raise SimulationFehler("Keine Änderung angegeben (ops: Liste von Operationen)")
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise SimulationFehler(f"Operation {i + 1}: {op.get('op') if isinstance(op, dict) else op!r} unbekannt "
                                   f"(erlaubt: {', '.join(OPS)})")
        try:
            meldungen.append(_eine(d, op, modell_szenarien or {}))
        except SimulationFehler as exc:
            raise SimulationFehler(f"{op['op']}: {exc}") from exc
    return d, meldungen


def _eine(d: dict[str, Any], op: dict[str, Any], modell: dict[str, dict[str, Any]]) -> str:
    art = op["op"]
    namen = {l["name"] for l in d["lastfaelle"]}
    if art == "lastfall_neu":
        name = _name(op.get("name"), "Name des Lastfalls")
        if name in namen:
            raise SimulationFehler(f"Lastfall {name!r} gibt es schon")
        d["lastfaelle"].append(neuer_lastfall(name, {k: op[k] for k in LASTFALL_FELDER if k in op}))
        return f"Lastfall „{name}“ angelegt"
    if art == "lastfall_setzen":
        l = _lastfall(d, _name(op.get("name")))
        felder = op.get("felder") if isinstance(op.get("felder"), dict) else {k: op[k] for k in LASTFALL_FELDER
                                                                               if k in op}
        l.update(pruefe_lastfall(felder))
        return f"Lastfall „{l['name']}“ geändert"
    if art == "lastfall_kopieren":
        von = _name(op.get("von"), "Vorlage")
        name = _name(op.get("name") or f"{von} (Kopie)", "Name der Kopie")
        if name in namen:
            raise SimulationFehler(f"Lastfall {name!r} gibt es schon")
        if von in namen:
            neu = copy.deepcopy(_lastfall(d, von))
            neu["name"] = name
            neu["kopie_von"] = von
        elif von in modell:
            neu = aus_szenario_kurz(name, modell[von], von)
        else:
            raise SimulationFehler(f"Vorlage {von!r} gibt es nicht (weder in der App noch in model.py)")
        d["lastfaelle"].append(neu)
        return f"„{von}“ als „{name}“ kopiert"
    if art == "lastfall_umbenennen":
        alt = _name(op.get("name"))
        neu_name = _name(op.get("neu"), "Neuer Name")
        l = _lastfall(d, alt)
        if neu_name != alt and neu_name in namen:
            raise SimulationFehler(f"Lastfall {neu_name!r} gibt es schon")
        l["name"] = neu_name
        for t in d["topologie"].values():
            if t.get("szenario") == alt:
                t["szenario"] = neu_name
        for x in d["lager"]:  # Lager je Lastfall folgen dem neuen Namen
            if isinstance(x.get("szenarien"), list):
                x["szenarien"] = [neu_name if n == alt else n for n in x["szenarien"]]
        return f"„{alt}“ heißt jetzt „{neu_name}“"
    if art == "lastfall_loeschen":
        name = _name(op.get("name"))
        _lastfall(d, name)
        d["lastfaelle"] = [l for l in d["lastfaelle"] if l["name"] != name]
        leer = []
        for x in d["lager"]:  # Lager nur für diesen Lastfall: gelten danach in keinem (bleiben sichtbar)
            if isinstance(x.get("szenarien"), list) and name in x["szenarien"]:
                x["szenarien"] = [n for n in x["szenarien"] if n != name]
                if not x["szenarien"]:
                    leer.append(str(x.get("id")))
        return f"Lastfall „{name}“ gelöscht" + (f" (Lager {', '.join(leer)} gilt jetzt in keinem Lastfall)"
                                                 if leer else "")
    if art == "last_setzen":
        l = _lastfall(d, _name(op.get("lastfall"), "Lastfall"))
        x = op.get("last") if isinstance(op.get("last"), dict) else None
        if x is None:
            raise SimulationFehler("last={…} fehlt")
        lid = str(x.get("id") or "")
        alt = next((y for y in l["lasten"] if y.get("id") == lid), None) if lid else None
        neu = pruefe_last(x, alt)
        if not neu["id"]:
            neu["id"] = _neue_id(_alle_last_ids(d), "L")
        if alt is not None:
            l["lasten"][l["lasten"].index(alt)] = neu
            return f"Last {neu['id']} in „{l['name']}“ geändert"
        l["lasten"].append(neu)
        return f"Last {neu['id']} auf {neu['teil']} in „{l['name']}“ ({_kraft_text(neu)})"
    if art == "last_loeschen":
        l = _lastfall(d, _name(op.get("lastfall"), "Lastfall"))
        lid = str(op.get("id") or "")
        if not any(y.get("id") == lid for y in l["lasten"]):
            raise SimulationFehler(f"Last {lid!r} gibt es in „{l['name']}“ nicht")
        l["lasten"] = [y for y in l["lasten"] if y.get("id") != lid]
        return f"Last {lid} aus „{l['name']}“ gelöscht"
    if art == "lager_setzen":
        x = op.get("lager") if isinstance(op.get("lager"), dict) else None
        if x is None:
            raise SimulationFehler("lager={…} fehlt")
        lid = str(x.get("id") or "")
        alt = next((y for y in d["lager"] if y.get("id") == lid), None) if lid else None
        neu = pruefe_lager(x, alt)
        bekannt = set(namen) | set(modell)
        unbekannt = [n for n in neu.get("szenarien") or [] if n not in bekannt]
        if unbekannt and modell:  # ohne Lauf sind die Szenarien aus model.py noch nicht bekannt
            raise SimulationFehler(f"Lastfall {unbekannt[0]!r} gibt es nicht (vorhanden: "
                                   f"{', '.join(repr(n) for n in sorted(bekannt))})")
        if not neu["id"]:
            neu["id"] = _neue_id({str(y.get("id")) for y in d["lager"]}, "A")
        if alt is not None:
            d["lager"][d["lager"].index(alt)] = neu
            return f"Lager {neu['id']} geändert"
        d["lager"].append(neu)
        return f"Lager {neu['id']} ({neu['art']}) an {neu['teil']}{gilt_text(neu.get('szenarien'))}"
    if art == "lager_loeschen":
        lid = str(op.get("id") or "")
        if not any(y.get("id") == lid for y in d["lager"]):
            raise SimulationFehler(f"Lager {lid!r} gibt es nicht")
        d["lager"] = [y for y in d["lager"] if y.get("id") != lid]
        return f"Lager {lid} gelöscht"
    if art == "abgeleitet":
        lid = _name(op.get("id"), "Lager")
        if not (lid.startswith("boden:") or lid.startswith("kontakt:")):
            raise SimulationFehler(f"{lid!r} ist kein abgeleitetes Lager (boden:… oder kontakt:…)")
        aus = [x for x in d["abgeleitet_aus"] if x != lid]
        if not bool(op.get("aktiv", True)):
            aus.append(lid)
        d["abgeleitet_aus"] = sorted(set(aus))
        return f"{lid}: {'an' if op.get('aktiv', True) else 'aus'}"
    if art == "topologie":
        teil = _name(op.get("teil"), "Druckteil")
        e = op.get("einstellungen") if isinstance(op.get("einstellungen"), dict) else {}
        if e is None or op.get("zuruecksetzen"):
            d["topologie"].pop(teil, None)
            return f"Topologie {teil}: Einstellungen zurückgesetzt"
        alt = dict(d["topologie"].get(teil) or {})
        alt.update(pruefe_topologie(e))
        d["topologie"][teil] = alt
        return f"Topologie {teil}: Einstellungen gespeichert"
    raise SimulationFehler(f"Operation {art!r} unbekannt")  # pragma: no cover


def gilt_text(szenarien: list[str] | None) -> str:
    """Zusatz für Meldungen: „, nur in „A“, „B““ bzw. „, in keinem Lastfall“; leer für alle."""
    if szenarien is None:
        return ""
    if not szenarien:
        return ", in keinem Lastfall"
    return ", nur in " + ", ".join(f"„{n}“" for n in szenarien)


def _kraft_text(last: dict[str, Any]) -> str:
    F = last.get("kraft") or [0, 0, 0]
    b = math.sqrt(sum(float(c) ** 2 for c in F))
    if last.get("einheit") == kr.DRUCK:
        return f"{last['betrag']:g} N/mm² auf die ganze Fläche = {b:.0f} N"
    t = f"{b:.0f} N" if last.get("einheit") != "kg" else f"{last['betrag']:g} kg = {b:.0f} N"
    return t + (" auf die ganze Fläche" if last.get("verteilung") == "flaeche" else "")

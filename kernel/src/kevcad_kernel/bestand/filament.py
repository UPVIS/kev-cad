"""Filament im Bestand (Strang „Bestand Stufe 2“, 22.10.2026; PLAN-BESTAND.md S2, BESTAND.md „Filament“).

Ein Projekt führt Filament, sobald ``bestand.json`` die Liste ``filament`` hat (auch leer): Spulen je Material und
Farbe mit Gramm übrig, Gramm voll, Hersteller, Name, Kennung (``S-0001``) und optional Lagerort.

- **Planung** (``bom_bestand``): je Material der Druckteile und der Spulen ``BOM.filament_bestand`` mit Gramm im
  Bestand, Spulenzahl, Spulengröße (``spule_g`` aus dem Katalog, sonst 1 kg) und Preis je Spule. Die Einkaufsliste
  (``einkauf.filament_kauf`` im Kernel, ``FilamentBestand.kauf`` in der App) rechnet daraus mit der Druckvorschau
  desselben Laufs die Fehlmenge und rundet auf ganze Spulen.
- **Abbuchen** (``verbrauch_aenderungen``): „Gedruckt“ und „Gebaut“ buchen das Filament der Druckvorschau ab:
  angebrochene Spulen zuerst (die mit dem wenigsten Filament), dann volle; reicht der Bestand nicht, gilt der Rest als
  von gekauften Spulen gedruckt, und was von der letzten gekauften Spule übrig bleibt, kommt als neue Spule in den
  Bestand (wie neue Reste aus gekauften Stangen).

Farben (Strang „Rest Druck“): Haben Druckteile eine Farbe (``lager.druckteil(…, farbe=…)``), trägt die Druckvorschau
je Platte die Farbe; Bedarf und Abbuchen gelten dann je Material und Farbe: Spulen derselben Farbe zuerst, für Teile
ohne Farbe jede Spule des Materials. Ohne Farben wie bisher je Material über alle Farben. Welche Spule benutzt wurde,
kann Kevin beim Buchen angeben (``spule``), sonst gilt die Reihenfolge oben.
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.catalog import number

from .datei import SPULE_STANDARD_G, spulen, zahl

MIN_REST_G = 0.5  # kleinere Reste einer gekauften Spule kommen nicht in den Bestand


def _material_eintrag(katalog: Any, mid_oder_name: str | None) -> dict[str, Any] | None:
    """Katalogmaterial zu einer id oder einem Namen der Stückliste („PETG“)."""
    if not mid_oder_name or katalog is None:
        return None
    try:
        m = katalog.material(mid_oder_name)
        if m is None and hasattr(katalog, "find_material"):
            m = katalog.find_material(mid_oder_name, include_proposed=True)
            if isinstance(m, dict) and m.get("id"):
                m = katalog.material(m["id"]) or m  # derselbe Eintrag wie über die id
        if m is None:
            m = katalog.material(str(mid_oder_name).lower())
    except Exception:  # noqa: BLE001 - ohne Katalog kein Abgleich
        return None
    return m if isinstance(m, dict) else None


def farbe_von(spule_oder_text: Any) -> str | None:
    """Farbe zum Vergleichen (klein, Leerzeichen zusammengefasst) einer Spule oder eines Texts; None ohne Farbe."""
    t = spule_oder_text.get("farbe") if isinstance(spule_oder_text, dict) else spule_oder_text
    t = " ".join(str(t or "").split()).lower()
    return t or None


def spule_g(material: dict[str, Any] | None) -> float:
    """Kaufspule in g: ``spule_g`` des Materials im Katalog, sonst 1 kg."""
    g = number((material or {}).get("spule_g"))
    return float(g) if g is not None and g > 0 else SPULE_STANDARD_G


def bom_bestand(bestand: dict[str, Any] | None, lines: list[dict[str, Any]], katalog: Any) -> list[dict[str, Any]]:
    """``BOM.filament_bestand``: je Material der zu druckenden Druckteile (Reihenfolge der Stückliste) und dann je
    weiterem Material der Spulen: ``material``, ``name``, ``gramm`` (alle Spulen), ``spulen``, ``kennungen``,
    ``spule_g``, ``preis_je_spule``, ``preis_stand``."""
    reihenfolge: list[str] = []
    eintraege: dict[str, dict[str, Any] | None] = {}
    for ln in lines:
        if ln.get("art") != "druckteil" or ln.get("eigenteil") is True or ln.get("gedruckt") is True:
            continue
        m = _material_eintrag(katalog, ln.get("material"))
        mid = (m or {}).get("id")
        if mid and mid not in eintraege:
            reihenfolge.append(mid)
            eintraege[mid] = m
    sp = spulen(bestand)
    for s in sp:
        mid = str(s.get("material") or "")
        if mid and mid not in eintraege:
            reihenfolge.append(mid)
            eintraege[mid] = _material_eintrag(katalog, mid)
    out = []
    for mid in reihenfolge:
        m = eintraege.get(mid) or {}
        eigene = [s for s in sp if s.get("material") == mid]
        g = spule_g(m)
        je_kg = number(m.get("preis_je_kg"))
        eintrag = {"material": mid, "name": m.get("name") or mid.upper(),
                   "gramm": zahl(sum(float(number(s.get("gramm")) or 0) for s in eigene)),
                   "spulen": len(eigene), "kennungen": [s.get("kennung") for s in eigene],
                   "spule_g": zahl(g),
                   "preis_je_spule": round(float(je_kg) * g / 1000.0, 2) if je_kg is not None else None,
                   "preis_stand": m.get("preis_stand")}
        if any(farbe_von(s) for s in eigene):  # additiv (Strang „Rest Druck“): Spulen je Farbe
            farben: dict[Any, dict[str, Any]] = {}
            for s in eigene:
                f = farben.setdefault(farbe_von(s), {"farbe": farbe_von(s), "gramm": 0.0, "spulen": 0,
                                                     "kennungen": []})
                f["gramm"] += float(number(s.get("gramm")) or 0)
                f["spulen"] += 1
                f["kennungen"].append(s.get("kennung"))
            eintrag["farben"] = [{**f, "gramm": zahl(f["gramm"])} for f in farben.values()]
        out.append(eintrag)
    return out


def gebaut_vorschau(run: int | None, ops: list[dict[str, Any]], info: list[dict[str, Any]],
                    bestand: dict[str, Any] | None, dv: Any, platten_buchen: list[int], schon: dict[int, str],
                    ganz: str | None, hinweis: str | None = None,
                    material_name: Any = None) -> dict[str, Any]:
    """Was „Gebaut“ jetzt vom Filament abbuchen würde, für die App (BESTAND ``gebaut_filament``, Dialog „Gebaut“):
    je Spule Gramm vorher, weg, nachher und ob sie leer wird, neue Spulen aus dem Rest gekaufter, was als gekauft
    vorausgesetzt ist, und je Platte der Druckvorschau, ob sie jetzt gebucht wird oder schon als gedruckt gebucht ist."""
    name = material_name or (lambda mid: mid)
    by_k = {s.get("kennung"): s for s in spulen(bestand)}
    entfernt = {op.get("kennung") for op in ops if op.get("op") == "spule" and op.get("nachher") is None}
    verbrauch = []
    for op in ops:
        if op.get("op") != "spule_gramm":
            continue
        s = by_k.get(op.get("kennung")) or {}
        vorher = float(number(s.get("gramm")) or 0)
        delta = float(op.get("delta") or 0)
        verbrauch.append({"kennung": op.get("kennung"), "material": op.get("material"),
                          "name": s.get("name"), "farbe": s.get("farbe"), "gramm": zahl(-delta),
                          "vorher": zahl(vorher), "nachher": zahl(max(0.0, vorher + delta)),
                          "leer": op.get("kennung") in entfernt})
    neue = [{"kennung": op["nachher"].get("kennung"), "material": op["nachher"].get("material"),
             "gramm": op["nachher"].get("gramm"), "gramm_voll": op["nachher"].get("gramm_voll")}
            for op in ops if op.get("op") == "spule" and op.get("vorher") is None and op.get("nachher")]
    gekauft = [{"material": i["material"], "gramm": i["gekauft"], **({"farbe": i["farbe"]} if i.get("farbe") else {})}
               for i in info if float(i.get("gekauft") or 0) > 0]
    v = _vorschau(dv)
    platten = []
    if v is not None and run is not None and int(number(v.get("run")) or 0) == int(run):
        for p in v.get("platten") or []:
            if not isinstance(p, dict) or number(p.get("nr")) is None:
                continue
            nr = int(p["nr"])
            platten.append({"nr": nr, "material": [{"material": m.get("material"), "g": zahl(number(m.get("g")) or 0)}
                                                    for m in p.get("material") or [] if isinstance(m, dict)],
                            "gebucht": schon.get(nr) or ganz, "buchen": bool(ops) and nr in platten_buchen,
                            **({"farbe": p["farbe"]} if p.get("farbe") else {})})
    mats = sorted({x["material"] for x in verbrauch + neue + gekauft if x.get("material")}
                  | {m["material"] for p in platten for m in p["material"] if m.get("material")})
    return {"run": run, "platten": platten, "ganz_gebucht": ganz, "spulen": verbrauch, "neue_spulen": neue,
            "gekauft": gekauft, "materialien": {m: name(m) for m in mats}, "hinweis": hinweis}


def _vorschau(dv: Any) -> dict[str, Any] | None:
    if not isinstance(dv, dict):
        return None
    return dv["druckvorschau"] if isinstance(dv.get("druckvorschau"), dict) else dv


def bedarf(dv: Any, run: int | None, platten: list[int] | None = None) -> dict[str, float]:
    """Filament je Material (g) aus der Druckvorschau des Laufs ``run``: alle Platten (``summe.material``) oder nur die
    genannten Platten (``platten[].material``). Leer, wenn die Vorschau zu einem anderen Lauf gehört."""
    v = _vorschau(dv)
    if v is None or (run is not None and int(number(v.get("run")) or 0) != int(run)):
        return {}
    out: dict[str, float] = {}
    if platten:
        wahl = {int(p) for p in platten}
        for p in v.get("platten") or []:
            if isinstance(p, dict) and int(number(p.get("nr")) or 0) in wahl:
                for m in p.get("material") or []:
                    if isinstance(m, dict) and m.get("material"):
                        out[str(m["material"])] = out.get(str(m["material"]), 0.0) + float(number(m.get("g")) or 0)
        return out
    summe = v.get("summe") if isinstance(v.get("summe"), dict) else {}
    for m in summe.get("material") or []:
        if isinstance(m, dict) and m.get("material"):
            out[str(m["material"])] = out.get(str(m["material"]), 0.0) + float(number(m.get("g")) or 0)
    return out


def bedarf_farben(dv: Any, run: int | None, platten: list[int] | None = None) -> dict[tuple[str, str | None], float]:
    """Wie ``bedarf``, aber je (Material, Farbe) aus den Farben der Platten (Strang „Rest Druck“); Platten ohne Farbe
    unter (Material, None). Leer, wenn die Vorschau zu einem anderen Lauf gehört."""
    v = _vorschau(dv)
    if v is None or (run is not None and int(number(v.get("run")) or 0) != int(run)):
        return {}
    wahl = {int(p) for p in platten} if platten else None
    out: dict[tuple[str, str | None], float] = {}
    for p in v.get("platten") or []:
        if not isinstance(p, dict) or (wahl is not None and int(number(p.get("nr")) or 0) not in wahl):
            continue
        for m in p.get("material") or []:
            if isinstance(m, dict) and m.get("material"):
                k = (str(m["material"]), farbe_von(p.get("farbe")))
                out[k] = out.get(k, 0.0) + float(number(m.get("g")) or 0)
    return out


def _reihenfolge(eigene: list[dict[str, Any]], vorzug: str | None) -> list[dict[str, Any]]:
    """Welche Spule zuerst: die genannte, dann angebrochene mit wenig Filament, dann volle (nach Kennung)."""

    def key(s: dict[str, Any]) -> tuple:
        g = float(number(s.get("gramm")) or 0)
        voll = number(s.get("gramm_voll"))
        angebrochen = voll is None or g < float(voll) - 0.05
        return (s.get("kennung") != vorzug, not angebrochen, g, str(s.get("kennung")))

    return sorted(eigene, key=key)


def verbrauch_aenderungen(verbrauch: dict[Any, float], bestand: dict[str, Any], kennungen: Any, datum: str,
                          katalog: Any = None, vorzug: str | None = None) -> tuple[list[dict[str, Any]],
                                                                                    list[dict[str, Any]]]:
    """Änderungen, die ``verbrauch`` (g je Material) von den Spulen abbuchen, und je Material eine Übersicht
    ``{"material", "gramm", "aus_bestand", "gekauft", "spulen": [kennung, …], "neue_spule"}``.

    Je Spule ``spule_gramm`` (Delta); eine leere Spule wird danach mit ``spule`` entfernt. Reicht der Bestand nicht,
    stammt der Rest aus gekauften Spulen (Größe aus dem Katalog bzw. 1 kg); was von der letzten übrig bleibt, wird eine
    neue Spule."""
    ops: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    alle = spulen(bestand)
    entnommen: dict[Any, float] = {}  # je Spule schon abgebucht (mehrere Farben eines Materials nacheinander)
    # Schlüssel: Material oder (Material, Farbe); benannte Farben zuerst, dann ohne Farbe (darf jede Spule nehmen)
    reihe = sorted(verbrauch.items(), key=lambda kv: (isinstance(kv[0], tuple) and kv[0][1] is None,))
    for schluessel, g in reihe:
        mid, farbe = schluessel if isinstance(schluessel, tuple) else (schluessel, None)
        rest = float(g)
        if rest <= 0.05:
            continue
        eintrag = {"material": mid, "gramm": zahl(rest), "aus_bestand": 0.0, "gekauft": 0.0, "spulen": [],
                   "neue_spule": None}
        if farbe:
            eintrag["farbe"] = farbe
        kandidaten = [s for s in alle if s.get("material") == mid and (not farbe or farbe_von(s) == farbe)]
        for s in _reihenfolge(kandidaten, vorzug):
            if rest <= 0.05:
                break
            hat = float(number(s.get("gramm")) or 0) - entnommen.get(s.get("kennung"), 0.0)
            if hat <= 0.05:
                continue
            nimm = min(hat, rest)
            delta = zahl(-nimm)
            ops.append({"op": "spule_gramm", "kennung": s.get("kennung"), "material": mid, "delta": delta})
            entnommen[s.get("kennung")] = entnommen.get(s.get("kennung"), 0.0) - float(delta)
            eintrag["spulen"].append(s.get("kennung"))
            eintrag["aus_bestand"] += nimm
            rest -= nimm
            danach = zahl(max(0.0, hat + float(delta)))  # genau wie datei.anwenden
            if float(danach) <= 0.05:
                ops.append({"op": "spule", "kennung": s.get("kennung"), "vorher": {**s, "gramm": danach},
                            "nachher": None})
        if rest > 0.05:
            groesse = spule_g(_material_eintrag(katalog, mid))
            n = math.ceil(rest / groesse - 1e-9)
            uebrig = n * groesse - rest
            eintrag["gekauft"] = zahl(rest)
            if uebrig >= MIN_REST_G:
                neu = {"kennung": kennungen.spule(), "material": mid, "gramm": zahl(uebrig),
                       "gramm_voll": zahl(groesse), "name": None, "hersteller": None, "farbe": farbe, "ort": None,
                       "seit": datum}
                ops.append({"op": "spule", "kennung": neu["kennung"], "vorher": None, "nachher": neu})
                eintrag["neue_spule"] = neu["kennung"]
        eintrag["aus_bestand"] = zahl(eintrag["aus_bestand"])
        info.append(eintrag)
    return ops, info

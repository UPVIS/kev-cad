"""Schnelle Schätzung von Filament und Druckzeit je Druckteil (Druckvorschau V1/V2, DRUCKVORSCHAU.md).

Ein einfaches Modell wie im Slicer, nur aus Kennzahlen des Netzes (``druck/vorschau_geo.py``):

- **Material:** Wände (Seitenfläche × Wandstärke aus Bahnbreite und Wandzahl), Decken und Böden (waagrechte Flächen ×
  Schichten), Füllung (Rest des Volumens × Anteil), Stützen grob (Stützfläche der Druckprüfung × mittlere Höhe der
  Überhänge × Stützdichte), Brim (Umfang des Grundrisses × Brimbreite × erste Schicht).
- **Zeit:** Bahnlängen je Merkmal durch wirksame Geschwindigkeiten (P1P-Profil „0.20mm Standard“, gedeckelt durch den
  größten Volumenstrom des Filaments), dazu je Schicht ein fester Anteil und je weitere Wandschleife (Loch, Bohrung,
  Innenkontur) ein Zuschlag, die erste Schicht langsam und der Start der Platte; Mindestschichtzeit des Filaments
  (Kühlung) je Höhenband.
- **Abgleich (V2):** Faktoren ``zeit`` und ``material`` je Drucker, Prozess und Material in
  ``~/Library/Application Support/de.upvis.kevcad/druck/abgleich.json`` (``KEVCAD_DRUCK_ABGLEICH`` übersteuert). Nach
  jedem Slicer-Ergebnis zieht ``abgleich_nachfuehren`` den Faktor zum Verhältnis Slicer / Rohschätzung (gleitend).
  Startwerte ``START`` aus dem ersten Abgleich am 22.10.2026 (Bambu Studio 02.07.01.62, Prüfteile und Kugelschieber).

Reine Rechnung ohne OCCT, wenige Mikrosekunden je Teil.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CM3_JE_M = math.pi * 0.0875 ** 2 * 100   # Filament 1,75 mm: 2,405 cm³ je Meter
SCHICHT_ERSTE = 0.2
BRIM_BREITE = 5.0


@dataclass(frozen=True)
class Filament:
    """Was die Schätzung vom Filament braucht (aus den Bambu-Studio-Profilen, BS-F)."""

    dichte: float          # g/cm³ (Kev-CAD-Katalog)
    q_max: float           # mm³/s größter Volumenstrom (filament_max_volumetric_speed)
    schicht_min_s: float   # Mindestschichtzeit (slow_down_layer_time)
    v_min: float           # langsamste Geschwindigkeit beim Kühlen (slow_down_min_speed)


FILAMENT: dict[str, Filament] = {
    "pla": Filament(1.24, 21.0, 8.0, 20.0),
    "petg": Filament(1.27, 15.0, 12.0, 10.0),
    "tpu-95a": Filament(1.21, 3.6, 8.0, 10.0),
    "abs": Filament(1.04, 20.0, 12.0, 20.0),
    "asa": Filament(1.07, 18.0, 12.0, 20.0),
    "pc-filament": Filament(1.20, 16.0, 12.0, 20.0),
    "pa": Filament(1.14, 14.0, 12.0, 20.0),
    "pa-cf": Filament(1.20, 8.0, 12.0, 20.0),
    "pla-cf": Filament(1.26, 15.0, 8.0, 20.0),
}


@dataclass(frozen=True)
class Modell:
    """Wirksame Geschwindigkeiten (mm/s) und Zeiten (s) – Beschleunigung, kurze Wege und Wenden eingerechnet. Grundlage
    Profil „0.20mm Standard @BBL P1P“ (Außenwand 200, Innenwand 300, Füllung 270 mm/s); die Werte sind am ersten
    Abgleich angepasst (22.10.2026, 88 Slicer-Läufe: 11 Prüfteile × 4 Einstellungen × PETG und PLA, Bambu Studio
    02.07.01.62): Zeit im Mittel ±9 % (größter Ausreißer 26 % bei vielen kleinen Löchern), Material ±4 %. Seit dem
    Strang „Feinschliff 2“ mit Wandschleifen je Schicht (``s_loch``, Umrisse aus ``schleifen_baender``): Zeit im Mittel
    4,9 %, Lochscheibe höchstens 8,5 % daneben (vorher 26 %)."""

    v_aussen: float = 263.0
    p0_aussen: float = 400.0        # mm Umfang je Schicht, bei dem die Außenwand halb so schnell ist (kurze Wege)
    v_innen: float = 242.0
    p0_innen: float = 52.0
    q_fest: float = 10.36           # mm³/s Böden, Decken, innere Vollflächen und Brücken zusammen
    a0_fest: float = 360.0          # mm² waagrechte Fläche, bei der die Vollflächen halb so schnell sind
    v_stuetz: float = 29.6          # Stützen samt ihren Leerwegen
    s_schicht: float = 2.90         # je Schicht: Wechsel, Naht, Leerwege
    s_umfang: float = 0.00021       # je Schicht und mm Umfang
    s_flaeche: float = 0.0000041    # je Schicht und mm² Querschnitt
    s_start: float = 35.0           # Start der Platte im Slicer (Reinigungslinie, „Custom“)
    v_erste: float = 50.0           # erste Schicht (Brim)
    stuetz_dichte: float = 0.088    # Anteil Material unter Überhängen (Baum)
    stuetz_dichte_normal: float = 0.15
    k_wand: float = 0.942           # Materialfaktoren je Merkmal (Überlappung der Bahnen)
    k_fuell: float = 0.978
    breite_aussen: float = 0.42
    breite_innen: float = 0.45
    # Strang „Feinschliff 2“, Punkt 5: jede weitere Wandschleife je Schicht (Loch, Bohrung, Innenkontur) kostet Naht,
    # Rückzug, Leerweg und Anfahren. Am Abgleich (88 Slicer-Läufe von V-K) gemessen: 0,40 s je Schicht und Schleife;
    # die Lochscheibe (12 Löcher) lag vorher 17 bis 26 % zu tief, jetzt −8,5 bis +1,0 %, im Mittel aller Teile 4,9 %
    # statt 6,3 %. Eine eigene Verlangsamung der Wand je Loch (wie p0_aussen) brachte am Abgleich nichts dazu.
    s_loch: float = 0.40            # s je Schicht und weiterer Schleife


# Füllung je Muster: Geschwindigkeit (mm/s) vor dem Volumenstrom-Deckel; Gyroid und Waben sind durch die
# Beschleunigung begrenzt (im Abgleich bei PLA und PETG gleich schnell)
MUSTER_V = {"gyroid": 85.0, "grid": 251.0, "cubic": 190.0, "honeycomb": 60.0, "rectilinear": 240.0, "zigzag": 240.0,
            "line": 251.0, "concentric": 140.0, "triangles": 190.0, "crosshatch": 140.0, "lightning": 190.0}
MODELL = Modell()

# Startwerte der Faktoren je Prozess und Material (erster Abgleich, siehe Moduldoku); fehlt ein Eintrag: 1,0
START: dict[str, dict[str, float]] = {}
START_STANDARD = {"zeit": 1.0, "material": 1.0}


def wandstaerke(waende: int, schicht: float, m: Modell = MODELL) -> float:
    n = max(1, int(waende))
    return m.breite_aussen + (n - 1) * (m.breite_innen - schicht * (1 - math.pi / 4))


def schaetze(geo: dict[str, Any], einstellungen: dict[str, Any], material: str,
             faktoren: dict[str, float] | None = None, dichte: float | None = None, m: Modell = MODELL,
             mit_start: bool = False) -> dict[str, Any]:
    """Ein Stück: {"g", "m", "zeit_s", "volumen_cm3", "stuetzen_g", "roh": {"zeit_s", "volumen_cm3"}, "anteile"}.
    ``faktoren`` aus dem Abgleich (``zeit``, ``material``); ``mit_start`` zählt den Start der Platte mit."""
    fil = FILAMENT.get(material, FILAMENT["pla"])
    rho = float(dichte or fil.dichte)
    e = einstellungen
    h = float(e.get("schicht_mm") or 0.2)
    n = int(e.get("waende") or 2)
    decken = int(e.get("decken") or 5)
    boeden = int(e.get("boeden") or 3)
    fuellung = max(0.0, min(1.0, float(e.get("fuellung") if e.get("fuellung") is not None else 0.15)))
    muster = str(e.get("muster") or "grid")
    stuetzen = str(e.get("stuetzen") or "keine")
    brim = bool(e.get("brim"))
    gr = geo.get("groesse") or [0, 0, 0]
    hoehe = float(gr[2]) if len(gr) > 2 else 0.0
    schichten = max(1, math.ceil(hoehe / h - 1e-6))
    V = max(0.0, float(geo.get("volumen") or 0.0))
    seite = float(geo.get("seite") or 0.0)
    oben = float(geo.get("oben") or 0.0)
    unten = float(geo.get("unten") or 0.0) + float(geo.get("auflage") or 0.0)
    umfang = seite / hoehe if hoehe > 1e-9 else 0.0          # Wandumfang je Schicht
    querschnitt = V / hoehe if hoehe > 1e-9 else 0.0
    # Material (mm³)
    v_aussen = seite * m.breite_aussen
    v_wand = seite * wandstaerke(n, h, m)
    v_dach = oben * decken * h + unten * boeden * h
    v_fest = min(V, v_wand + v_dach)
    k = v_fest / (v_wand + v_dach) if v_wand + v_dach > 1e-9 else 1.0   # dünnes Teil: anteilig kürzen
    v_wand, v_dach = v_wand * k, v_dach * k
    v_innen = max(0.0, v_wand - v_aussen * k)
    v_fuell = (V - v_fest) * fuellung
    stuetz_fl = float(geo.get("stuetzflaeche") or 0.0) if stuetzen != "keine" else 0.0
    dichte_st = m.stuetz_dichte_normal if stuetzen == "normal" else m.stuetz_dichte
    v_stuetz = stuetz_fl * max(float(geo.get("ueberhang_hoehe") or 0.0), h) * dichte_st
    v_brim = float(geo.get("umriss_umfang") or 0.0) * BRIM_BREITE * SCHICHT_ERSTE if brim else 0.0
    v_ges = (v_wand * m.k_wand + v_dach) + v_fuell * m.k_fuell + v_stuetz + v_brim
    # Zeit (s): Bahnlänge / wirksame Geschwindigkeit, gedeckelt durch den Volumenstrom
    q_max = fil.q_max

    def v_eff(v: float, breite: float, schicht: float = h) -> float:
        return min(v, q_max / (breite * schicht)) if q_max > 0 else v

    l_aussen = v_aussen * k / (m.breite_aussen * h)
    l_innen = v_innen / ((m.breite_innen - h * (1 - math.pi / 4)) * h)
    l_fest = v_dach / (m.breite_aussen * h)
    l_fuell = v_fuell / (m.breite_innen * h)
    l_stuetz = v_stuetz / (m.breite_aussen * h)
    # weitere Wandschleifen je Schicht (Löcher, Innenkonturen), gemittelt nach Seitenfläche der Höhenbänder
    schl = [float(x) for x in geo.get("schleifen_baender") or []]
    sb = [float(x) for x in geo.get("seite_baender") or []]
    if schl and len(schl) == len(sb) and sum(sb) > 0:
        extra = sum(max(0.0, n - 1) * w for n, w in zip(schl, sb)) / sum(sb)
    else:
        extra = 0.0
    t_aussen = l_aussen / (v_eff(m.v_aussen, m.breite_aussen) * umfang / (umfang + m.p0_aussen)) if l_aussen else 0.0
    t_innen = l_innen / (v_eff(m.v_innen, m.breite_innen) * umfang / (umfang + m.p0_innen)) if l_innen else 0.0
    waag_fl = oben + unten
    t_fest = v_dach / min(m.q_fest * waag_fl / (waag_fl + m.a0_fest), q_max or 1e9) if v_dach > 0 else 0.0
    t_fuell = l_fuell / v_eff(MUSTER_V.get(muster, 200.0), m.breite_innen)
    t_stuetz = l_stuetz / v_eff(m.v_stuetz, m.breite_aussen)
    t_brim = (v_brim / (0.5 * SCHICHT_ERSTE)) / m.v_erste
    t_leer = schichten * (m.s_schicht + m.s_umfang * umfang + m.s_flaeche * querschnitt + m.s_loch * extra)
    t_var = t_aussen + t_innen + t_fest + t_fuell + t_stuetz
    l_ges = l_aussen + l_innen + l_fest + l_fuell + l_stuetz
    # Kühlung je Höhenband: kurze Schichten werden bis zur Mindestschichtzeit gestreckt, aber nicht langsamer als v_min
    baender = [float(x) for x in geo.get("seite_baender") or []]
    waag = [float(x) for x in geo.get("waag_baender") or []] or [0.0] * len(baender)
    t_kuehl = 0.0
    if baender and schichten > 1:
        sw, sh = sum(baender) or 1.0, sum(waag) or 1.0
        nb = schichten / len(baender)
        anteil_w = (t_aussen + t_innen + t_fuell + t_stuetz) / (t_var or 1.0)
        for bw, bh in zip(baender, waag):
            teil = anteil_w * bw / sw + (1 - anteil_w) * (bh / sh if sum(waag) else bw / sw)
            t_b = t_var * teil + t_leer / len(baender)
            l_b = l_ges * teil
            ziel = min(nb * fil.schicht_min_s, l_b / fil.v_min) if fil.v_min > 0 else nb * fil.schicht_min_s
            if t_b < ziel:
                t_kuehl += ziel - t_b
    roh_zeit = t_var + t_brim + t_leer + t_kuehl
    t_wand = t_aussen + t_innen
    t_schicht = t_leer
    t_erste = 0.0
    f = faktoren or {}
    fz, fm = float(f.get("zeit") or 1.0), float(f.get("material") or 1.0)
    zeit = roh_zeit * fz + (m.s_start if mit_start else 0.0)
    vol_cm3 = v_ges / 1000 * fm
    g = vol_cm3 * rho
    v_fest = v_wand + v_dach
    return {
        "g": round(g, 2), "m": round(vol_cm3 / CM3_JE_M, 3), "zeit_s": round(zeit, 1), "volumen_cm3": round(vol_cm3, 4),
        "stuetzen_g": round(v_stuetz / 1000 * fm * rho, 2), "schichten": schichten,
        "roh": {"zeit_s": round(roh_zeit, 2), "volumen_cm3": round(v_ges / 1000, 5)},
        "anteile": {"wand_s": round(t_wand, 1), "fest_s": round(t_fest, 1), "fuell_s": round(t_fuell, 1),
                    "stuetz_s": round(t_stuetz, 1), "schicht_s": round(t_schicht, 1), "kuehl_s": round(t_kuehl, 1),
                    "erste_s": round(t_erste + t_brim, 1), "fest_mm3": round(v_fest, 1),
                    "fuell_mm3": round(v_fuell, 1), "stuetz_mm3": round(v_stuetz, 1), "brim_mm3": round(v_brim, 1)},
    }


# ---------------------------------------------------------------------------------------------------------------------
# Abgleich (V2)

ALPHA = 0.35          # Gewicht eines neuen Abgleichs (gleitend)
GRENZEN = (0.4, 2.5)  # Faktoren bleiben in diesem Bereich
_LOCK = threading.Lock()


def abgleich_datei() -> Path:
    p = os.environ.get("KEVCAD_DRUCK_ABGLEICH")
    if p:
        return Path(p)
    return Path.home() / "Library/Application Support/de.upvis.kevcad/druck/abgleich.json"


def abgleich_schluessel(drucker: str, prozess: str, material: str) -> str:
    return f"{drucker}|{prozess}|{material}"


def lies_abgleich() -> dict[str, Any]:
    try:
        d = json.loads(abgleich_datei().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def faktoren(abgleich: dict[str, Any], drucker: str, prozess: str, material: str) -> dict[str, float]:
    e = (abgleich.get("faktoren") or {}).get(abgleich_schluessel(drucker, prozess, material))
    if isinstance(e, dict):
        return {"zeit": float(e.get("zeit") or 1.0), "material": float(e.get("material") or 1.0),
                "n": int(e.get("n") or 0)}
    s = START.get(f"{prozess}|{material}") or START.get(material) or START_STANDARD
    return {"zeit": float(s["zeit"]), "material": float(s["material"]), "n": 0}


def abgleich_nachfuehren(drucker: str, prozess: str, material: str, roh: dict[str, float],
                         slicer: dict[str, float], speichern: bool = True) -> dict[str, Any]:
    """Faktoren zum Verhältnis Slicer / Rohschätzung ziehen. ``roh`` und ``slicer`` je ``zeit_s`` (ohne Start der
    Platte) und ``volumen_cm3``. Liefert die neuen Faktoren und die Abweichung der bisherigen Schätzung."""
    with _LOCK:
        d = lies_abgleich()
        alt = faktoren(d, drucker, prozess, material)
        out: dict[str, Any] = {"vorher": {"zeit": alt["zeit"], "material": alt["material"]}}
        neu = dict(alt)
        for key, rk, sk in (("zeit", "zeit_s", "zeit_s"), ("material", "volumen_cm3", "volumen_cm3")):
            r, s = float(roh.get(rk) or 0.0), float(slicer.get(sk) or 0.0)
            if r <= 1e-9 or s <= 1e-9:
                continue
            ziel = s / r
            a = 1.0 / (alt["n"] + 1) if alt["n"] < 2 else ALPHA
            wert = alt[key] + a * (ziel - alt[key])
            neu[key] = round(min(GRENZEN[1], max(GRENZEN[0], wert)), 4)
        neu["n"] = alt["n"] + 1
        out["nachher"] = {"zeit": neu["zeit"], "material": neu["material"], "n": neu["n"]}
        if speichern:
            d.setdefault("version", 1)
            d.setdefault("faktoren", {})[abgleich_schluessel(drucker, prozess, material)] = {
                "zeit": neu["zeit"], "material": neu["material"], "n": neu["n"],
                "stand": time.strftime("%Y-%m-%dT%H:%M:%S")}
            p = abgleich_datei()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(p)
        return out

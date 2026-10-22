"""Empfohlene Druckeinstellungen und Hinweise je Druckteilgruppe (Druckvorschau V4/V5, DRUCKVORSCHAU.md).

Grundlage sind Kevins Druckregeln (``skill/kev-cad/3d-druck.md``, Abschnitte 3, 5, 11–13) und die Material- und
Druckerdaten aus ``druck/regeln.py``:

- Funktionsteile 3–4 Wände (1,2–1,6 mm) und 20–40 % Gyroid statt Standard 2 Wände / 15 % Grid; Profil „Strength“
  6 Wände / 25 % (Abschnitt 13).
- Decken mindestens 1 mm, Böden mindestens 0,6 mm (Profil „0.20mm Standard“: 5 bzw. 3 Schichten).
- Feinere Schicht (0,12–0,16) für Details und glatte Flächen, gröbere (0,24–0,28) für große einfache Teile.
- Auflage unter ca. 25 mm² oder schlanke Teile (Höhe > 10 · √Auflage): Brim; ABS/ASA/PC/PA nur mit Einhausung und
  Brim; PLA/PETG ohne Brim (Abschnitt 5 und 13).
- Hauptlast in die Schichtebene legen; die Prüfung kennt die Lastrichtung nicht (Abschnitt 3).

Ohne ``zweck`` gilt ``funktion`` als Schätzung (``zweck_geschaetzt``). Feste Vorgaben (``druck.json``) gehen vor.
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.druck import druckfertig as df
from kevcad_kernel.druck.regeln import MATERIALIEN, P1P

ZWECKE = ("zier", "funktion", "tragend", "bewegt", "aussen")
ZWECK_STANDARD = "funktion"

# Grundwerte je Zweck: Schicht, Wände, Decken, Böden, Füllung, Muster, Text der Begründung
ZWECK_WERTE: dict[str, dict[str, Any]] = {
    "zier": {"schicht_mm": 0.16, "waende": 2, "decken": 5, "boeden": 3, "fuellung": 0.15, "muster": "grid",
             "text": "zier: 2 Wände, 15 % Grid, 0,16 mm für glattere Sichtflächen (Standardprofil reicht)"},
    "funktion": {"schicht_mm": 0.2, "waende": 3, "decken": 5, "boeden": 3, "fuellung": 0.2, "muster": "gyroid",
                 "text": "funktion: 3 Wände (1,2 mm), 20 % Gyroid (Kevins Regel: Funktionsteile 3–4 Wände, "
                         "20–40 % Füllung)"},
    "tragend": {"schicht_mm": 0.2, "waende": 4, "decken": 5, "boeden": 4, "fuellung": 0.25, "muster": "gyroid",
                "text": "tragend: 4 Wände (1,6 mm), 25 % Gyroid – Wände tragen mehr als Füllung"},
    "bewegt": {"schicht_mm": 0.16, "waende": 4, "decken": 6, "boeden": 4, "fuellung": 0.3, "muster": "gyroid",
               "text": "bewegt: 4 Wände und 30 % Gyroid für verschleißfeste Lauf- und Gleitflächen, 0,16 mm für "
                       "glattere Flächen"},
    "aussen": {"schicht_mm": 0.2, "waende": 4, "decken": 6, "boeden": 4, "fuellung": 0.25, "muster": "gyroid",
               "text": "aussen: 4 Wände, 6 Decken (dicht gegen Wasser), 25 % Gyroid"},
}
AUFLAGE_MIN = 25.0       # mm² (3d-druck.md Abschnitt 5, EW)
SCHLANK = 10.0           # Höhe > 10 · √Auflage wackelt (EW)
STUETZ_AB = 25.0         # mm² Stützfläche der Druckprüfung, ab der Stützen empfohlen werden
STUETZ_NORMAL_AB = 600.0  # große ebene Unterseiten eher normale Stützen


def _z(x: float, nd: int = 1) -> str:
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".") if nd else f"{x:.0f}"
    return s.replace(".", ",")


def material_info(material: str):
    return MATERIALIEN.get(material)


def empfehle(geo: dict[str, Any], material: str, zweck: str | None, vorgaben: dict[str, Any] | None = None,
             pruefung: dict[str, Any] | None = None) -> dict[str, Any]:
    """Einstellungen, Begründung und feste Vorgaben einer Gruppe.

    ``geo``: Kennzahlen der Form (vorschau_geo), ``pruefung``: Teil aus ``druck.teile`` der Druckprüfung,
    ``vorgaben``: feste Werte aus druck.json (Teilmenge der Einstellungen). Rückgabe {"einstellungen", "begruendung",
    "fest", "zweck", "zweck_geschaetzt"}."""
    vorgaben = dict(vorgaben or {})
    geschaetzt = zweck is None
    z = zweck if zweck in ZWECKE else ZWECK_STANDARD
    w = ZWECK_WERTE[z]
    mat = material_info(material)
    e: dict[str, Any] = {k: w[k] for k in ("schicht_mm", "waende", "decken", "boeden", "fuellung", "muster")}
    begr: list[str] = []
    if geschaetzt:
        begr.append("Zweck nicht angegeben, geschätzt als funktion (in model.py lager.druckteil(…, zweck=…) "
                    "angeben): " + w["text"].split(": ", 1)[1])
    else:
        begr.append(w["text"])
    if material == "tpu-95a":
        e.update(waende=3, fuellung=min(e["fuellung"], 0.2), muster="gyroid")
        begr.append("TPU: 3 Wände, Füllung bestimmt die Härte (15–20 % Gyroid weich, mehr Füllung härter)")
    gr = geo.get("groesse") or [0, 0, 0]
    hoehe = float(gr[2]) if len(gr) > 2 else 0.0
    if z in ("funktion", "tragend") and max(gr[:2] or [0]) > 150 and hoehe > 60 and "schicht_mm" not in vorgaben:
        e["schicht_mm"] = 0.24
        begr.append("großes einfaches Teil: 0,24 mm Schicht spart Zeit (Kevins Regel: 0,24–0,28 für große Teile)")
    # Stützen aus der Druckprüfung
    stuetz = float(geo.get("stuetzflaeche") or 0.0)
    if stuetz >= STUETZ_AB:
        e["stuetzen"] = "normal" if stuetz >= STUETZ_NORMAL_AB and float(geo.get("ueberhang_hoehe") or 0) < 15 \
            else "baum"
        begr.append(f"Stützen ({'Baum' if e['stuetzen'] == 'baum' else 'normal'}): ca. {_z(stuetz, 0)} mm² "
                    "Überhang steiler als das Material erlaubt (Druckprüfung)")
    else:
        e["stuetzen"] = "keine"
    # Brim
    auflage = float(geo.get("auflage_pruefung") or geo.get("auflage") or 0.0)
    gruende = []
    if auflage < AUFLAGE_MIN:
        gruende.append(f"kleine Auflage ({_z(auflage, 0)} mm²)")
    if auflage > 0 and hoehe > SCHLANK * math.sqrt(auflage):
        gruende.append(f"schlank ({_z(hoehe, 0)} mm hoch auf {_z(auflage, 0)} mm²)")
    if mat is not None and (mat.einhausung or mat.verzug >= 2):
        gruende.append(f"{mat.name} verzieht sich")
    diag = math.hypot(float(gr[0]), float(gr[1])) if len(gr) > 1 else 0.0
    if mat is not None and mat.verzug_laenge and diag >= mat.verzug_laenge and not mat.einhausung:
        gruende.append(f"lange Auflage ({_z(diag, 0)} mm)")
    e["brim"] = bool(gruende)
    if gruende:
        begr.append("Brim 5 mm: " + ", ".join(gruende))
    # Ausrichtung aus der Druckprüfung
    text = geo.get("ausrichtung_text") or "wie modelliert"
    auf = geo.get("liegt_auf")
    e["ausrichtung"] = text + (f", {auf} liegt auf" if auf else "")
    a = (pruefung or {}).get("ausrichtung") or {}
    if a.get("begruendung"):
        begr.append("Ausrichtung: " + str(a["begruendung"]).rstrip("."))
    if z in ("tragend", "bewegt"):
        begr.append("Last längs der Schichten: Zug, Biegung und Haken in die Schichtebene legen; die Druckprüfung "
                    "kennt die Lastrichtung nicht, sonst ausrichtung= in druckteil vorgeben")
    # Schalen: Decken ≥ 1 mm, Böden ≥ 0,6 mm
    h = float(e["schicht_mm"])
    e["decken"] = max(int(e["decken"]), math.ceil(1.0 / h - 1e-6))
    e["boeden"] = max(int(e["boeden"]), math.ceil(0.6 / h - 1e-6))
    # Paket B: vollständiger, begründeter Satz je Objekt (druck/druckfertig.py)
    begr_je: dict[str, str] = {}
    vorher = dict(e)
    df.ergaenze(e, begr_je, geo, material, z, pruefung)
    for k in ("waende", "fuellung"):  # Anhebungen für Bohrungen und Einsätze auch in der Liste der Gründe
        if e.get(k) != vorher.get(k) and begr_je.get(k):
            begr.append(begr_je[k])
    for k in ("stuetzen_nur_platte", "stuetzen_abstand_mm", "brim_mm", "naht", "buegeln"):
        if k in begr_je and (k != "stuetzen_nur_platte" or e.get("stuetzen") != "keine") and \
                (k != "brim_mm" or e.get("brim")) and (k != "buegeln" or e.get("buegeln")):
            begr.append(begr_je[k])
    # feste Vorgaben gehen vor (auch vor Paket B)
    fest = []
    for k, v in vorgaben.items():
        if k in e and v is not None:
            e[k] = v
            fest.append(k)
            begr_je[k] = "fest vorgegeben (druck.json): " + _feld_text(k, v)
    # Begründungen, die zur festen Vorgabe nicht mehr passen, als Empfehlung kennzeichnen (sonst stünde etwa
    # „kein Brim: …“ neben „fest vorgegeben: Brim an“)
    for k in fest:
        for r in VERWANDT.get(k, ()):
            if r in begr_je and r not in fest:
                begr_je[r] = "ohne Vorgabe wäre die Empfehlung: " + begr_je[r]
    if "brim" in fest and e.get("brim") and not e.get("brim_mm"):
        e["brim_mm"] = df.BRIM_MM["schlank"]
        begr_je["brim_mm"] = (f"Brim {_z(e['brim_mm'], 0)} mm, weil Brim fest vorgegeben ist; "
                              + begr_je.get("brim_mm", ""))
    if fest:
        begr.append("Fest vorgegeben: " + ", ".join(_feld_text(k, e[k]) for k in fest))
    return {"einstellungen": e, "begruendung": begr, "fest": fest, "zweck": z, "zweck_geschaetzt": geschaetzt,
            "begruendung_je": begr_je}


# Begründungen, die von einer festen Vorgabe abhängen (Schlüssel der Vorgabe → abhängige Begründungen)
VERWANDT: dict[str, tuple[str, ...]] = {"brim": ("brim_mm",), "stuetzen": ("stuetzen_nur_platte", "stuetzen_abstand_mm")}


def _feld_text(k: str, v: Any) -> str:
    if k == "fuellung":
        return f"Füllung {_z(float(v) * 100, 0)} %"
    if k == "schicht_mm":
        return f"Schicht {_z(float(v), 2)} mm"
    namen = {"waende": "Wände", "decken": "Decken", "boeden": "Böden", "muster": "Muster", "stuetzen": "Stützen",
             "brim": "Brim", "ausrichtung": "Ausrichtung", "stuetzen_nur_platte": "Stützen nur von der Platte",
             "stuetzen_abstand_mm": "Stützabstand oben", "brim_mm": "Brim-Breite", "naht": "Naht", "buegeln": "Bügeln",
             "oberflaeche": "Oberseite", "loch_kompensation_mm": "Lochkompensation",
             "kontur_kompensation_mm": "Konturkompensation", "elefantenfuss_mm": "Elefantenfuß"}
    if k == "brim":
        return "Brim " + ("an" if v else "aus")
    return f"{namen.get(k, k)} {v}"


def risiko(geo: dict[str, Any], einstellungen: dict[str, Any], material: str, zeit_s: float) -> tuple[float, list[str]]:
    """Wahrscheinlichkeit eines Fehldrucks (grob, EW) und ihre Gründe."""
    mat = material_info(material)
    r, gruende = 0.02, []
    if einstellungen.get("stuetzen") not in (None, "keine"):
        r += 0.05
        gruende.append("Stützen")
    gr = geo.get("groesse") or [0, 0, 0]
    auflage = float(geo.get("auflage_pruefung") or geo.get("auflage") or 0.0)
    if auflage < AUFLAGE_MIN:
        r += 0.05
        gruende.append("kleine Auflage")
    if auflage > 0 and len(gr) > 2 and gr[2] > SCHLANK * math.sqrt(auflage):
        r += 0.05
        gruende.append("hohe schlanke Form")
    if mat is not None:
        if mat.einhausung and not P1P.geschlossen:
            r += 0.15
            gruende.append(f"{mat.name} offen gedruckt")
        elif mat.verzug >= 1:
            r += 0.01 * mat.verzug
        if material == "tpu-95a":
            r += 0.05
            gruende.append("TPU")
    stunden = zeit_s / 3600
    if stunden > 6:
        r += min(0.08, (stunden - 6) * 0.01)
        gruende.append(f"lange Druckzeit ({_z(stunden, 0)} h)")
    return round(min(0.6, r), 3), gruende


def hinweise(geo: dict[str, Any], einstellungen: dict[str, Any], material: str, zweck: str, je_stueck: dict[str, Any],
             anzahl: int, risiko_wert: float, risiko_gruende: list[str],
             stuetz_flaechen: list[str] | None = None) -> list[dict[str, Any]]:
    """Druckpraxis je Gruppe: Trocknen, Verzug, Brim, Stützen-Nacharbeit, Düse, Material und Zweck, Erfolgsrisiko."""
    mat = material_info(material)
    out: list[dict[str, Any]] = []
    if mat is not None:
        if mat.trocknen and material in ("petg", "tpu-95a", "pa", "pa-cf", "pc-filament", "abs", "asa"):
            pflicht = "Pflicht" in mat.trocknen
            out.append({"schwere": "warnung" if pflicht else "hinweis", "art": "trocknen",
                        "text": f"{mat.name} vorher trocknen ({mat.trocknen.replace(' (Pflicht)', '')})"
                                + (" – Pflicht, sonst Fäden und Blasen." if pflicht else ".")})
        if mat.einhausung and not P1P.geschlossen:
            out.append({"schwere": "warnung", "art": "verzug",
                        "text": f"{mat.name} auf dem offenen P1P verzieht sich und reißt zwischen den Schichten: nur "
                                "mit Einhausung (Enclosure Kit oder Druckbox) und Brim, sonst PLA oder PETG."})
        if mat.gehaertete_duese and not P1P.duese_gehaertet:
            out.append({"schwere": "warnung", "art": "duese",
                        "text": f"{mat.name} ist abrasiv: die Edelstahldüse des P1P verschleißt (gehärtete Düse, "
                                "HRC 40, nachrüsten oder Material ohne Faser)."})
        if zweck == "aussen" and material in ("pla", "pla-cf"):
            out.append({"schwere": "warnung", "art": "material",
                        "text": "PLA wird ab ca. 55 °C weich und verträgt keine Sonne: für draußen PETG nehmen "
                                "(ASA nur mit Einhausung)."})
        if zweck in ("bewegt", "tragend") and material == "pla":
            out.append({"schwere": "hinweis", "art": "material",
                        "text": "PLA ist spröde: für Schnapphaken, Clips und Teile unter Last ist PETG zäher."})
    if einstellungen.get("brim"):
        out.append({"schwere": "hinweis", "art": "brim",
                    "text": "Brim 5 mm einschalten (kleine Auflage, schlankes Teil oder Verzug); nach dem Druck "
                            "abziehen und die Unterkante entgraten."})
    st = einstellungen.get("stuetzen")
    if st not in (None, "keine"):
        fl = f" an {', '.join(stuetz_flaechen[:4])}" if stuetz_flaechen else ""
        g = float(je_stueck.get("stuetzen_g") or 0.0)
        out.append({"schwere": "warnung", "art": "stuetzen",
                    "text": f"Braucht Stützen{fl} (ca. {_z(float(geo.get('stuetzflaeche') or 0), 0)} mm²): "
                            f"Nacharbeit, die Flächen darüber werden rau; ca. {_z(g, 1)} g Stützmaterial je Stück. "
                            "Besser: Überhang auf 45° fasen oder Ausrichtung ändern."})
    if zweck in ("tragend", "bewegt"):
        out.append({"schwere": "hinweis", "art": "festigkeit",
                    "text": "Quer zu den Schichten hält das Teil nur etwa die Hälfte: Hauptlast in die "
                            "Schichtebene legen (Ausrichtung prüfen)."})
    if risiko_wert >= 0.12:
        out.append({"schwere": "warnung" if risiko_wert >= 0.25 else "hinweis", "art": "risiko",
                    "text": f"Erfolgsrisiko: etwa {_z(risiko_wert * 100, 0)} % Fehldrucke"
                            + (f" ({', '.join(risiko_gruende)})" if risiko_gruende else "")
                            + ("; erst ein Stück drucken, dann die übrigen." if anzahl > 1 else ".")})
    return out


def globale_hinweise(materialien: list[str], gramm_je_material: dict[str, float], platten: list[dict[str, Any]],
                     nicht_passend: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    namen = [MATERIALIEN[m].name if m in MATERIALIEN else m for m in materialien]
    if len(materialien) > 1:
        out.append({"schwere": "hinweis", "art": "ams",
                    "text": f"{len(materialien)} Materialien ({', '.join(namen)}): je Material eigene Platten; ohne "
                            "AMS die Spule zwischen den Platten wechseln. Mit AMS auf einer Platte kostet jeder "
                            "Wechsel Spülmenge (ca. 0,1–0,6 g je Wechsel und Schicht, Prime Tower)."})
    for m, g in gramm_je_material.items():
        if g > 900:
            out.append({"schwere": "hinweis", "art": "material",
                        "text": f"{MATERIALIEN[m].name if m in MATERIALIEN else m}: {_z(g / 1000, 2)} kg – mehr als "
                                "eine Spule (1 kg); Restmenge vor dem Druck prüfen."})
    for p in platten:
        if float(p.get("zeit_s") or 0) > 12 * 3600:
            out.append({"schwere": "hinweis", "art": "platte",
                        "text": f"Platte {p['nr']} druckt über {_z(p['zeit_s'] / 3600, 0)} h: Spule reicht? Den "
                                "Druck nicht unbeaufsichtigt über Nacht starten, wenn er nicht getestet ist."})
    for n in nicht_passend:
        out.append({"schwere": "fehler", "art": "bauraum",
                    "text": f"{n} passt nicht auf die Platte des P1P (256 × 256 mm, vorn links 18 × 28 mm frei): "
                            "teilen oder anders ausrichten (Druckprüfung)."})
    return out

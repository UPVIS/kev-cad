"""Druckfertige Einstellungen je Objekt (Strang „Druckexport 2“, Paket B, 22.10.2026; DRUCKVORSCHAU.md
„Druckfertig je Objekt“).

Kevin: „Grundsätzlich alle Drucksettings immer automatisch einstellen, auch für die einzelnen Objekte, auch wenn sie
sich unterscheiden, so dass alles komplett druckfertig voreingestellt ist.“ ``empfehlung.empfehle`` setzt Schicht,
Wände, Decken, Böden, Füllung, Muster, Stützen und Brim; ``ergaenze`` macht daraus einen vollständigen, begründeten
Satz je Objekt aus Geometrie (Vorschau-Geometrie und Druckprüfung), Zweck, Material und den Druckregeln
(``druck/regeln.py``, ``skill/kev-cad/3d-druck.md``):

1. Stützen nur bei Überhängen über der Grenze (Druckprüfung); Baumstützen nur von der Platte (sie wachsen um das Teil
   herum), normale überall; PETG mit größerem Abstand oben (haftet an Stützen). Sonst ausdrücklich aus.
2. Haftung: Brim nach Auflage zu Höhe und Material, Breite begründet (3, 5 oder 8 mm). Platte und Betttemperatur
   kommen aus dem Preset des Filaments.
3. Passungen: Bohrungen bekommen mindestens 3 Wände; X-Y-Loch- und Konturkompensation ausdrücklich 0, denn die
   Zugabe (Spieltabelle, Tropfenbohrung) steckt schon im Modell.
4. Gewindeeinsätze (Bohrung wie in ``GEWINDEEINSAETZE``): Wände nach der Mindestwand des Herstellers (höchstens 6),
   Füllung mindestens 30 %. Kernlöcher für Schrauben direkt ins Teil: 4 Wände.
5. Optik: Naht hinten bei Zier- und Außenteilen, sonst ausgerichtet (Bambu-Standard); Bügeln nur bei Zierteilen mit
   ebener Oberseite; Oberseite monoton; Elefantenfuß-Kompensation wie im P1P-Profil (0,15 mm).
6. Festigkeit: Ausrichtung aus der Druckprüfung, Wände und Füllung nach Zweck (``empfehlung``).
7. Tempo und Kühlung aus dem Preset des Filaments; kleine Querschnitte bremst dessen Mindestschichtzeit selbst.
8. Jede Einstellung trägt eine Begründung (``begruendung_je``).
10. Kevins feste Vorgaben (``druck.json``) gehen vor; ``empfehle`` setzt sie nach ``ergaenze``.
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.druck.regeln import GEWINDEEINSAETZE, MATERIALIEN

# Zusätzliche Einstellungen je Objekt (Schlüssel wie DRUCK_EINSTELLUNGEN; Bambu-Schlüssel in slicer.prozess_einstellungen)
ERWEITERT: tuple[str, ...] = ("stuetzen_nur_platte", "stuetzen_abstand_mm", "brim_mm", "naht", "buegeln",
                              "oberflaeche", "loch_kompensation_mm", "kontur_kompensation_mm", "elefantenfuss_mm")
NAHT = ("hinten", "ausgerichtet", "nah", "zufall")
OBERFLAECHE = ("monoton", "monoton_linie", "linie", "konzentrisch")
LINIE_MM = 0.42
BUEGELN_AB_MM2 = 300.0      # ebene Oberseite, ab der Bügeln lohnt (EW)
ELEFANTENFUSS_P1P = 0.15    # mm, Bambu-Profil „0.20mm Standard @BBL P1P“ (BS-P)
PETG_STUETZ_ABSTAND = 0.25  # mm oben, PETG haftet an Stützen (EW, Bambu-Profil 0,2)
BRIM_MM = {"klein": 3.0, "schlank": 5.0, "verzug": 8.0}
SCHMAL = 8.0                # Höhe über 8 × kleinste Breite der Auflage: Brim (EW, 3d-druck.md Abschnitt 5)


def _z(x: float, nd: int = 1) -> str:
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".") if nd else f"{x:.0f}"
    return s.replace(".", ",")


def einsatz_fuer(d: float, toleranz: float = 0.06) -> tuple[str, str, dict[str, Any]] | None:
    """Gewindeeinsatz, dessen Bohrung (Nennmaß oder Nennmaß + 0,2) dem Durchmesser entspricht. Nur bis M6 (Bohrung bis
    9 mm): größere Bohrungen sind eher Passungen für Rohre und Wellen (Ø 12,2 für ein Alurohr Ø 12, nicht M10)."""
    treffer = []
    for hersteller, tab in GEWINDEEINSAETZE.items():
        for groesse, e in tab.items():
            b = float(e["bohrung"] or 0)
            if b > 9.0:
                continue
            if abs(d - b) <= toleranz or abs(d - (b + 0.2)) <= toleranz:
                treffer.append((hersteller, groesse, e))
    if not treffer:
        return None
    # Ø 4,0 passt zu M2.5 und M3: die größere Mindestwand gilt, bei gleicher die übliche Größe (ohne Kommastelle)
    return max(treffer, key=lambda t: (float(t[2]["wand_min"] or 0), "." not in t[1] and "-" not in t[1]))


KERNLOCH = {2.5: "M3", 2.2: "M2.5", 3.4: "M4"}  # selbstschneidend direkt ins Teil (regeln, B-BT), senkrecht


def ergaenze(e: dict[str, Any], begr_je: dict[str, str], geo: dict[str, Any], material: str, zweck: str,
             pruefung: dict[str, Any] | None = None) -> None:
    """Ergänzt ``e`` (Einstellungen aus ``empfehle``) um die Einstellungen der Liste oben und schreibt je Schlüssel
    eine Begründung nach ``begr_je``. ``geo``: Vorschau-Geometrie der Form, ``pruefung``: Teil aus ``druck.teile``."""
    mat = MATERIALIEN.get(material)
    gr = geo.get("groesse") or [0, 0, 0]
    hoehe = float(gr[2]) if len(gr) > 2 else 0.0
    kz = (pruefung or {}).get("kennzahlen") or {}
    bohrungen = [b for b in (kz.get("bohrungen") or []) if isinstance(b, dict)]

    # 1. Stützen
    if e.get("stuetzen") in (None, "keine"):
        e["stuetzen"] = "keine"
        begr_je.setdefault("stuetzen", "keine Stützen: die Druckprüfung findet keine Überhänge über der Grenze")
        e["stuetzen_nur_platte"] = False
        begr_je["stuetzen_nur_platte"] = "entfällt: das Teil braucht keine Stützen"
    else:
        flaeche = float(geo.get("stuetzflaeche") or 0.0)
        begr_je.setdefault("stuetzen", f"{'Baumstützen' if e['stuetzen'] == 'baum' else 'normale Stützen'}: ca. "
                                       f"{_z(flaeche, 0)} mm² Überhang steiler als das Material erlaubt (Druckprüfung)")
        nur_platte = e["stuetzen"] == "baum"
        e["stuetzen_nur_platte"] = nur_platte
        begr_je["stuetzen_nur_platte"] = (
            "nur von der Platte: Baumstützen wachsen um das Teil herum und hinterlassen keine Narben auf dem Teil"
            if nur_platte else "überall: normale Stützen unter großen ebenen Unterseiten brauchen auch Halt auf dem "
                               "Teil")
        if material == "petg":
            e["stuetzen_abstand_mm"] = PETG_STUETZ_ABSTAND
            begr_je["stuetzen_abstand_mm"] = (f"Abstand oben {_z(PETG_STUETZ_ABSTAND, 2)} mm statt 0,2: PETG haftet "
                                              "stark an Stützen (EW)")

    # 2. Haftung: Brim-Breite; schmale hohe Stege (Höhe über 8 × kleinste Breite) kippen auch bei genug Fläche
    auflage = float(geo.get("auflage_pruefung") or geo.get("auflage") or 0.0)
    breite = min(float(gr[0]), float(gr[1])) if len(gr) > 1 else 0.0
    steg = breite > 0 and hoehe > SCHMAL * breite
    if steg and not e.get("brim"):
        e["brim"] = True
    if e.get("brim") and steg and not (mat is not None and (mat.einhausung or mat.verzug >= 2)):
        e["brim_mm"] = BRIM_MM["schlank"]
        begr_je["brim_mm"] = (f"Brim 5 mm: schmaler hoher Steg ({_z(hoehe, 0)} mm hoch auf {_z(breite, 1)} mm "
                              "Breite) kippt sonst")
    elif e.get("brim"):
        schlank = auflage > 0 and hoehe > 15.0 * math.sqrt(auflage)
        verzug = mat is not None and (mat.einhausung or mat.verzug >= 2)
        art = "verzug" if verzug else "schlank" if schlank or (auflage > 0 and hoehe > 10 * math.sqrt(auflage)) \
            else "klein"
        e["brim_mm"] = BRIM_MM[art]
        begr_je["brim_mm"] = {
            "klein": f"Brim 3 mm: kleine Auflage ({_z(auflage, 0)} mm²) bei {_z(hoehe, 0)} mm Höhe",
            "schlank": f"Brim 5 mm: schlankes Teil ({_z(hoehe, 0)} mm hoch auf {_z(auflage, 0)} mm²) kippt sonst",
            "verzug": f"Brim 8 mm: {mat.name if mat else material} verzieht sich auf dem offenen P1P"}[art]
    else:
        e["brim_mm"] = 0.0
        begr_je["brim_mm"] = (f"kein Brim: Auflage {_z(auflage, 0)} mm² trägt {_z(hoehe, 0)} mm Höhe"
                              + (f", {mat.name} verzieht sich kaum" if mat is not None else ""))

    # 3. Passungen und 4. Einsätze, Schrauben
    einsaetze = []
    kernloecher = []
    for b in bohrungen:
        d = float(b.get("d") or 0)
        if b.get("waagrecht"):
            continue
        ein = einsatz_fuer(d)
        if ein is not None:
            einsaetze.append((d, ein))
        elif any(abs(d - k) <= 0.06 for k in KERNLOCH):
            kernloecher.append(d)
    waende = int(e.get("waende") or 2)
    if bohrungen and waende < 3:
        e["waende"] = 3
        begr_je["waende"] = (f"3 Wände (1,26 mm) statt {waende}: {len(bohrungen)} Bohrung"
                             f"{'en' if len(bohrungen) != 1 else ''} mit Passung, die Bohrungswand soll aus "
                             "Perimetern bestehen")
    if einsaetze:
        wand = max(float(ein[2]["wand_min"] or 0) for _, ein in einsaetze)
        noetig = min(6, max(4, math.ceil(wand / LINIE_MM - 1e-6)))
        if int(e.get("waende") or 0) < noetig:
            e["waende"] = noetig
        d0, (herst, groesse, _) = einsaetze[0]
        begr_je["waende"] = (f"{e['waende']} Wände: Gewindeeinsatz {groesse} ({herst}, Bohrung Ø {_z(d0, 2)}) braucht "
                             f"{_z(wand, 1)} mm Wand ringsum (Herstellerangabe)"
                             + ("; höchstens 6 Wände je Objekt, mehr nur mit Modifier" if wand / LINIE_MM > 6 else ""))
        if float(e.get("fuellung") or 0) < 0.3:
            e["fuellung"] = 0.3
            begr_je["fuellung"] = "30 % Füllung: der Einsatz braucht Material unter und neben sich"
    elif kernloecher and int(e.get("waende") or 0) < 4:
        e["waende"] = 4
        begr_je["waende"] = (f"4 Wände: Kernloch Ø {_z(kernloecher[0], 1)} für eine Schraube direkt ins Teil, das "
                             "Gewinde schneidet in die Wände (B-BT)")
    e["loch_kompensation_mm"] = 0.0
    e["kontur_kompensation_mm"] = 0.0
    zugabe = "Zugabe steckt im Modell (Spieltabelle, Tropfenbohrung, Bohrungs-Untermaß; 3d-druck.md Abschnitt 6)"
    begr_je["loch_kompensation_mm"] = "X-Y-Lochkompensation 0: " + zugabe
    begr_je["kontur_kompensation_mm"] = "X-Y-Konturkompensation 0: Außenmaße wie konstruiert"

    # 5. Optik und Funktion
    sichtbar = zweck in ("zier", "aussen")
    e["naht"] = "hinten" if sichtbar else "ausgerichtet"
    begr_je["naht"] = ("Naht hinten: Sichtteil, die Naht liegt auf der Rückseite" if sichtbar
                       else "Naht ausgerichtet (Bambu-Standard): eine gerade Naht, stört bei Funktionsteilen nicht")
    oben = float(geo.get("oben") or 0.0)
    e["buegeln"] = zweck == "zier" and oben >= BUEGELN_AB_MM2
    begr_je["buegeln"] = (f"Bügeln: Zierteil mit {_z(oben, 0)} mm² ebener Oberseite" if e["buegeln"] else
                          "nicht bügeln: " + ("nur für sichtbare Oberseiten von Zierteilen" if zweck != "zier" else
                                              f"Oberseite zu klein ({_z(oben, 0)} mm²)"))
    e["oberflaeche"] = "monoton_linie"
    begr_je["oberflaeche"] = "Oberseite monoton (Bambu-Standard): gleichmäßiger Glanz ohne Ansatzlinien"
    e["elefantenfuss_mm"] = ELEFANTENFUSS_P1P
    begr_je["elefantenfuss_mm"] = ("Elefantenfuß-Kompensation 0,15 mm wie im P1P-Profil; die Bettfase im Modell (0,5 mm, "
                                   "3d-druck.md) nimmt den Rest")

    # 6. Festigkeit: Ausrichtung aus der Druckprüfung beibehalten, Wände und Füllung nach Zweck (empfehle)
    quer = mat.z_festigkeit if mat is not None else 0.5
    begr_je.setdefault("ausrichtung", f"{e.get('ausrichtung') or 'wie modelliert'}: Ausrichtung der Druckprüfung "
                                      f"bleibt; quer zur Schicht trägt {mat.name if mat else material} nur etwa "
                                      f"{_z(quer * 100, 0)} % (Statik Stufe 1 rechnet damit)")

    # 7. Tempo und Kühlung
    begr_je.setdefault("tempo", "Tempo und Kühlung aus dem Preset des Filaments; dessen Mindestschichtzeit bremst kleine "
                                "Querschnitte selbst")

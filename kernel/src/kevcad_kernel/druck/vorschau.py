"""Druckvorschau aus dem Ergebnis der Druckprüfung bauen (DRUCKVORSCHAU.md, Ergebnis ``druckvorschau``).

Reine Rechnung in der Laufzeit (ohne Formen): Gruppen gleicher Teile, Empfehlung je Gruppe (``empfehlung.py``),
Schätzung je Stück (``schaetzung.py``), schnelles Anordnen (``anordnen.py``), Summen mit Kosten. Liegen Ergebnisse des
Slicers vor (``SlicerStand``), ersetzen sie die Schätzung je Gruppe, die Anordnung je Material und die Zeiten je Platte;
``stand`` sagt, woher jeder Wert kommt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kevcad_kernel.druck import anordnen as ao
from kevcad_kernel.druck import empfehlung as em
from kevcad_kernel.druck import schaetzung as sz
from kevcad_kernel.druck import signatur as sg
from kevcad_kernel.druck import slicer as sl
from kevcad_kernel.druck.vorgaben import von_je_schluessel
from kevcad_kernel.druck.vorschau_geo import teil_mit_form

DRUCKER_ID = "p1p-0.4"
DRUCKER_NAME = "Bambu Lab P1P 0.4"
STANDARD = {"drucker": DRUCKER_ID, "strompreis_kwh": 0.32, "leistung_w": 150.0, "plattenwechsel_s": 120,
            "slicer": True, "platte": sl.PLATTE_STANDARD}
STUETZ_ARTEN = ("ueberhang", "freie_unterseite", "kragarm", "bruecke")
SCHLUESSEL_VERSION = "v1"


def projekt_einstellungen(settings: dict[str, Any] | None) -> dict[str, Any]:
    """``kevcad.json`` → ``"druck"`` mit Vorgaben ergänzt (unbekannte Schlüssel bleiben erhalten). ``platte``
    (Druckplatte, Bambu-Name wie „Textured PEI Plate“ oder kurz „texturiert“, „glatt“, „cool“, „engineering“)
    wird vereinheitlicht; unbekannt: Texturplatte und ``platte_fehler``."""
    d = dict(STANDARD)
    roh = (settings or {}).get("druck") if isinstance(settings, dict) else None
    if isinstance(roh, dict):
        for k, v in roh.items():
            if v is not None:
                d[k] = v
    if d.get("drucker") not in sl.DRUCKER:
        d["drucker"] = DRUCKER_ID
    try:
        d["platte"] = sl.platte_name(d.get("platte"))
    except sl.SlicerFehler as exc:
        d["platte_fehler"] = str(exc)
        d["platte"] = sl.PLATTE_STANDARD
    return d


@dataclass
class Gruppe:
    id: str
    name: str
    teile: list[str]
    anzahl: int
    material: str
    zweck: str
    zweck_geschaetzt: bool
    geo: dict[str, Any]
    einstellungen: dict[str, Any]
    fest: list[str]
    begruendung: list[str]
    prozess: str
    filament: str | None
    schluessel: str
    vorgaben: dict[str, Any] = field(default_factory=dict)
    # Spiegelbild einer anderen Gruppe (id), erkannt an der Signatur (Strang „Feinschliff 2“); sonst None
    gespiegelt_von: str | None = None
    pruefung: dict[str, Any] = field(default_factory=dict)
    stuetz_flaechen: list[str] = field(default_factory=list)
    fest_von: dict[str, str] = field(default_factory=dict)


@dataclass
class SlicerStand:
    """Was der Slicer schon weiß: je Gruppe (Schlüssel) das Ergebnis eines Stücks, je Material die genaue Anordnung,
    je Anordnung die Platten. Wird vom Hintergrund gefüllt und liegt zusätzlich im Zwischenspeicher."""

    gruppen: dict[str, dict[str, Any]] = field(default_factory=dict)
    anordnung: dict[str, dict[str, Any]] = field(default_factory=dict)
    platten: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    zustand: str = "aus"
    fertig: int = 0
    gesamt: int = 0
    meldung: str | None = None
    version: str | None = None
    ms: float = 0.0


def _gruppen_name(namen: list[str]) -> str:
    letzte = [n.rsplit("/", 1)[-1] for n in namen]
    if len(set(letzte)) == 1:
        return letzte[0]
    worte = [n.split() for n in letzte]
    anfang: list[str] = []
    for teil in zip(*worte):
        if len(set(teil)) != 1:
            break
        anfang.append(teil[0])
    ende = []
    for teil in zip(*(list(reversed(w)) for w in worte)):
        if len(set(teil)) != 1 or len(anfang) + len(ende) >= min(len(w) for w in worte):
            break
        ende.insert(0, teil[0])
    if not anfang:  # nichts Gemeinsames vorn (Schieberolle, Fangrolle): die Namen aufzählen statt nur „(Druck)“
        koepfe = list(dict.fromkeys(" ".join(w[:len(w) - len(ende)]) for w in worte))
        erste = list(dict.fromkeys(w[0] for w in worte if len(w) > len(ende)))
        if 1 < len(erste) < len(koepfe):  # „Schieberschlitten links/rechts, Fängerschlitten …“ → nur die Arten
            koepfe = erste
        if len(koepfe) > 1:
            liste = (", ".join(koepfe[:-1]) + " und " + koepfe[-1]) if len(koepfe) <= 3 else \
                f"{koepfe[0]}, {koepfe[1]} u. a."
            return (liste + " " + " ".join(ende)).strip()
    name = " ".join(anfang + ende).strip()
    return name or letzte[0]


def _filament_wunsch(projekt: dict[str, Any], material: str) -> str | None:
    f = projekt.get("filament")
    return str(f.get(material)) if isinstance(f, dict) and f.get(material) else None


def _filament(projekt: dict[str, Any], material: str) -> str | None:
    """Name des Bambu-Studio-Filamentprofils (ohne Bambu Studio: Wunsch oder erster Vorschlag)."""
    wunsch = _filament_wunsch(projekt, material)
    if sl.system_ordner().is_dir():
        try:
            return sl.filament_name(material, wunsch, str(projekt.get("drucker") or DRUCKER_ID))
        except sl.SlicerFehler:
            return None
    return wunsch or (sl.FILAMENTE.get(material) or (None,))[0]


def gruppen(druck: dict[str, Any], befunde: list[dict[str, Any]], vorgaben: dict[str, Any],
            projekt: dict[str, Any]) -> tuple[list[Gruppe], list[str]]:
    """Gruppen gleicher Teile (Form samt Druckausrichtung, Material, Zweck, Vorgaben) in der Reihenfolge des ersten
    Auftretens; dazu die Namen ohne Vorschau-Geometrie. Gleiche Form heißt seit dem Strang „Feinschliff 2“: dieselbe
    Gleichteil-Klasse aus dem Rechenprozess (``vorschau_geo.gleichteile``: gleiche Signatur in Druckausrichtung, dann
    genau verglichen), sonst gleiche Signatur (``signatur.vergleich``); unabhängig von der Lage im Modell.
    Spiegelbilder bilden eine eigene Gruppe „(gespiegelt)“, außer die Form ist symmetrisch. Ohne Signatur (ältere
    Prüfergebnisse) wie bisher Formschlüssel und Hüllmaß in Druckausrichtung."""
    vorschau = druck.get("vorschau") or {}
    teile_info = druck.get("teile") or {}
    vt = vorgaben.get("teile") if isinstance(vorgaben.get("teile"), dict) else {}
    roh: dict[Any, dict[str, Any]] = {}
    ohne: list[str] = list((vorschau.get("fehler") or {}).keys())
    for name in teile_info:
        geo = teil_mit_form(vorschau, name)
        if geo is None:
            if name not in ohne:
                ohne.append(name)
            continue
        if geo.get("gedruckt"):  # schon gedruckt (druck/gedruckt.py): nicht in der Vorschau
            continue
        v = vt.get(name) if isinstance(vt.get(name), dict) else {}
        zweck = v.get("zweck") or geo.get("zweck")
        e_vorgabe = {k: x for k, x in (v.get("einstellungen") or {}).items() if x is not None}
        # gleiche Form (ohne Lage) in gleicher Lage auf dem Bett: Hüllmaß in Druckausrichtung statt der Drehungen, damit
        # gleiche Teile in verschiedener Einbaulage (gedreht, andere Rahmenlage) eine Gruppe bleiben
        lage_bett = tuple(round(float(x), 1) for x in (geo.get("groesse") or [])) + \
            (round(float(geo.get("auflage") or 0.0)),)
        basis = (geo.get("material"), zweck, json.dumps(e_vorgabe, sort_keys=True))
        sig = geo.get("signatur") if isinstance(geo.get("signatur"), dict) else None
        key: Any = (geo.get("form"), lage_bett, *basis)
        gespiegelt_von = None
        gt = geo.get("gleichteil") if isinstance(geo.get("gleichteil"), dict) else None
        if gt is not None:  # genau verglichen im Rechenprozess (vorschau_geo.gleichteile)
            gesp = bool(gt.get("gespiegelt"))
            key = ("gleichteil", gt.get("fid"), gesp, *basis)
            if gesp and ("gleichteil", gt.get("fid"), False, *basis) in roh:
                gespiegelt_von = ("gleichteil", gt.get("fid"), False, *basis)
        elif sig is not None:
            key = None
            for k_, kand in roh.items():
                if kand["basis"] != basis or kand["sig"] is None:
                    continue
                gleich, gespiegelt = sg.vergleich(kand["sig"], sig)
                if gleich and not gespiegelt:
                    key = k_
                    break
                if gleich and gespiegelt and gespiegelt_von is None:
                    gespiegelt_von = k_
            if key is None:
                key = ("sig", len(roh))
        g = roh.setdefault(key, {"namen": [], "stuecke": {}, "geo": geo, "zweck": zweck, "vorgaben": e_vorgabe,
                                 "zweck_fest": bool(v.get("zweck")), "pruefung": teile_info.get(name) or {},
                                 "von": {}, "basis": basis, "sig": sig, "gespiegelt_von": gespiegelt_von})
        for k_, w_ in von_je_schluessel(v).items():
            g["von"].setdefault(k_, w_)
        g["namen"].append(name)
        st = int(geo.get("stueck") or 0) or -len(g["stuecke"]) - 1
        s = g["stuecke"].setdefault(st, {"gezeigt": 0, "anzahl": 0})
        s["gezeigt"] += 1
        s["anzahl"] = max(s["anzahl"], int(geo.get("anzahl") or 0))
    out: list[Gruppe] = []
    stuetz: dict[str, list[str]] = {}
    for b in befunde or []:
        w = b.get("wert") or {}
        if w.get("pruefung") == "druck" and w.get("druckart") in STUETZ_ARTEN and b.get("teile"):
            n = b["teile"][0]
            stuetz.setdefault(n, []).extend(f"{n}#f{f}" for f in w.get("flaechen") or [])
    version = sl.version() or "-"
    ids = {k_: f"g{i}" for i, k_ in enumerate(roh, start=1)}
    for i, g in enumerate(roh.values(), start=1):
        geo = g["geo"]
        mat = str(geo.get("material") or "pla")
        emp = em.empfehle(geo, mat, g["zweck"], g["vorgaben"], g["pruefung"])
        fest = list(emp["fest"]) + (["zweck"] if g["zweck_fest"] else [])
        fest_von = {k: g["von"].get(k, "kevin") for k in fest}
        anzahl = sum(max(s["gezeigt"], s["anzahl"]) for s in g["stuecke"].values())
        prozess = sl.prozess_name(float(emp["einstellungen"]["schicht_mm"]))
        filament = _filament(projekt, mat)
        e_slicer = {k: v for k, v in emp["einstellungen"].items() if k != "ausrichtung"}
        schl = sl.schluessel(SCHLUESSEL_VERSION, geo.get("form"), geo.get("form_matrix"), e_slicer, prozess,
                             filament, projekt.get("drucker"), version, projekt.get("platte"))
        name_g = _gruppen_name(g["namen"]) + (" (gespiegelt)" if g["gespiegelt_von"] is not None else "")
        out.append(Gruppe(id=f"g{i}", name=name_g, teile=g["namen"], anzahl=anzahl, material=mat,
                          zweck=emp["zweck"], zweck_geschaetzt=emp["zweck_geschaetzt"], geo=geo,
                          einstellungen=emp["einstellungen"], fest=fest, begruendung=emp["begruendung"],
                          prozess=prozess, filament=filament, schluessel=schl, vorgaben=g["vorgaben"],
                          pruefung=g["pruefung"], stuetz_flaechen=sorted(set(stuetz.get(g["namen"][0], []))),
                          fest_von=fest_von,
                          gespiegelt_von=ids.get(g["gespiegelt_von"]) if g["gespiegelt_von"] is not None else None))
    return out, ohne


def anordnung_schluessel(material: str, gr: list[Gruppe]) -> str:
    return sl.schluessel(SCHLUESSEL_VERSION, "anordnung", material,
                         [(g.schluessel, g.anzahl, bool(g.einstellungen.get("brim"))) for g in gr if g.material == material])


def stuecke(gr: list[Gruppe]) -> list[ao.Stueck]:
    out: list[ao.Stueck] = []
    for g in gr:
        out += ao.stuecke_aus_gruppe(g.id, g.material, g.geo, g.teile, g.anzahl, bool(g.einstellungen.get("brim")))
    return out


def _platten_aus_slicer(a: dict[str, Any], gr: list[Gruppe]) -> list[ao.Platte]:
    """Genaue Anordnung (Slicer) als Platten: Objekte heißen „<gruppe>_<n>“ (STL-Stamm = Gruppen-id)."""
    nach_id = {g.id: g for g in gr}
    st = {g.id: ao.stuecke_aus_gruppe(g.id, g.material, g.geo, g.teile, g.anzahl, bool(g.einstellungen.get("brim")))
          for g in gr}
    benutzt = {gid: 0 for gid in st}
    platten = []
    for p in a.get("platten") or []:
        platte = ao.Platte(str(a.get("material")))
        for o in p.get("objekte") or []:
            gid = str(o.get("gruppe") or "")
            if gid not in nach_id or benutzt[gid] >= len(st[gid]):
                continue
            s = st[gid][benutzt[gid]]
            benutzt[gid] += 1
            platte.lagen.append(ao.Lage(s, float(o["x"]), float(o["y"]), int(round(float(o.get("drehung") or 0)))))
        if platte.lagen:
            platten.append(platte)
    if any(benutzt[g] < len(st[g]) for g in st):
        return []  # passt nicht zur aktuellen Gruppenlage: dann die schnelle Anordnung
    return platten


def platten_schluessel(material: str, platte: ao.Platte, gr: dict[str, Gruppe]) -> str:
    return sl.schluessel(SCHLUESSEL_VERSION, "platte", material,
                         [(gr[l_.stueck.gruppe].schluessel, round(l_.x, 1), round(l_.y, 1), l_.drehung)
                          for l_ in platte.lagen])


def baue(run: int, druck: dict[str, Any] | None, befunde: list[dict[str, Any]], vorgaben: dict[str, Any],
         settings: dict[str, Any] | None, material_info: Callable[[str], dict[str, Any] | None],
         stand: SlicerStand | None = None, abgleich: dict[str, Any] | None = None,
         regler: bool = False) -> tuple[dict[str, Any], list[Gruppe], list[tuple[str, ao.Platte]]]:
    """(Druckvorschau wie im Vertrag, Gruppen, Platten mit Material). ``material_info(id)`` liefert den Katalogeintrag
    (dichte, preis_je_kg, preis_stand, name)."""
    t0 = time.perf_counter()
    projekt = projekt_einstellungen(settings)
    stand = stand or SlicerStand()
    abgleich = abgleich if abgleich is not None else sz.lies_abgleich()
    gr, ohne = gruppen(druck or {}, befunde, vorgaben or {}, projekt)
    drucker = str(projekt["drucker"])
    teile_out: list[dict[str, Any]] = []
    je: dict[str, dict[str, Any]] = {}      # je Gruppe: Werte eines Stücks (Zeit ohne Start der Platte)
    preise: dict[str, dict[str, Any]] = {}
    for g in gr:
        info = material_info(g.material) or {}
        preise[g.material] = info
        dichte = float(info.get("dichte") or sz.FILAMENT.get(g.material, sz.FILAMENT["pla"]).dichte)
        fk = sz.faktoren(abgleich, drucker, g.prozess, g.material)
        est = sz.schaetze(g.geo, g.einstellungen, g.material, fk, dichte)
        s = stand.gruppen.get(g.schluessel)
        if s is not None:
            vol = float(s.get("volumen_cm3") or 0.0)
            zeit = max(0.0, float(s.get("zeit_s") or 0.0) - float(s.get("start_s") or 0.0))
            werte = {"g": round(vol * dichte, 2), "m": round(vol / sz.CM3_JE_M, 3), "zeit_s": round(zeit, 1),
                     "stuetzen_g": est["stuetzen_g"], "stand": "slicer", "abweichung": s.get("abweichung"),
                     "abweichung_material": s.get("abweichung_material")}
        else:
            werte = {"g": est["g"], "m": est["m"], "zeit_s": est["zeit_s"], "stuetzen_g": est["stuetzen_g"],
                     "stand": "schaetzung", "abweichung": None, "abweichung_material": None}
        werte["roh"] = est["roh"]
        werte["schaetzung"] = {"g": est["g"], "zeit_s": est["zeit_s"], "volumen_cm3": est["volumen_cm3"]}
        je[g.id] = werte
        r, gruende = em.risiko(g.geo, g.einstellungen, g.material, werte["zeit_s"])
        preis_kg = float(info.get("preis_je_kg") or 0.0)
        kosten = round(werte["g"] * g.anzahl / 1000 * preis_kg, 2)
        hw = em.hinweise(g.geo, g.einstellungen, g.material, g.zweck, werte, g.anzahl, r, gruende, g.stuetz_flaechen)
        teile_out.append({
            "gruppe": g.id, "name": g.name, "teile": list(g.teile), "anzahl": g.anzahl, "material": g.material,
            "zweck": g.zweck, "zweck_geschaetzt": g.zweck_geschaetzt,
            "g": round(werte["g"] * g.anzahl, 1), "m": round(werte["m"] * g.anzahl, 2),
            "zeit_s": int(round(werte["zeit_s"] * g.anzahl)), "kosten": kosten, "stand": werte["stand"],
            "abweichung": werte["abweichung"], "abweichung_material": werte["abweichung_material"],
            "je_stueck": {"g": round(werte["g"], 2), "m": round(werte["m"], 3), "zeit_s": int(round(werte["zeit_s"]))},
            "stuetzen_g": round(werte["stuetzen_g"] * g.anzahl, 1),
            "einstellungen": dict(g.einstellungen), "fest": list(g.fest), "fest_von": dict(g.fest_von),
            "profil": {"prozess": g.prozess, "filament": g.filament}, "risiko": r,
            "begruendung": list(g.begruendung), "hinweise": hw,
            **({"gespiegelt_von": g.gespiegelt_von} if g.gespiegelt_von else {}),
        })
    # Platten: je Material genau (Slicer) oder schnell
    nach_id = {g.id: g for g in gr}
    materialien: list[str] = []
    for g in gr:
        if g.material not in materialien:
            materialien.append(g.material)
    platten: list[tuple[str, ao.Platte, str]] = []
    nicht_passend: list[str] = []
    for mat in materialien:
        gm = [g for g in gr if g.material == mat]
        a = stand.anordnung.get(anordnung_schluessel(mat, gr))
        genau = _platten_aus_slicer(a, gm) if a else []
        if genau:
            platten += [(mat, p, "slicer") for p in genau]
        else:
            for p in ao.anordne(stuecke(gm)):
                platten.append((mat, p, "schnell"))
                if p.passt_nicht:
                    nicht_passend += [l_.stueck.name for l_ in p.lagen]
    platten_out: list[dict[str, Any]] = []
    start_s = sz.MODELL.s_start
    for nr, (mat, p, art) in enumerate(platten, start=1):
        info = preise.get(mat) or {}
        dichte = float(info.get("dichte") or sz.FILAMENT.get(mat, sz.FILAMENT["pla"]).dichte)
        zeit = start_s + sum(je[l_.stueck.gruppe]["zeit_s"] for l_ in p.lagen)
        g_sum = sum(je[l_.stueck.gruppe]["g"] for l_ in p.lagen)
        staende = {je[l_.stueck.gruppe]["stand"] for l_ in p.lagen}
        pstand = "slicer" if staende == {"slicer"} else ("schaetzung" if staende == {"schaetzung"} else "gemischt")
        ps = stand.platten.get(platten_schluessel(mat, p, nach_id)) if art == "slicer" else None
        if ps:
            zeit = float(ps[0].get("zeit_s") or zeit)
            g_sum = float(ps[0].get("volumen_cm3") or 0.0) * dichte or g_sum
            pstand = "slicer"
        preis_kg = float(info.get("preis_je_kg") or 0.0)
        platten_out.append({
            "nr": nr, "zeit_s": int(round(zeit)), "stand": pstand, "anordnung": art,
            "material": [{"material": mat, "g": round(g_sum, 1), "m": round(g_sum / dichte / sz.CM3_JE_M, 2),
                          "kosten": round(g_sum / 1000 * preis_kg, 2)}],
            "kosten": round(g_sum / 1000 * preis_kg, 2),
            "hoehe_mm": round(max((l_.stueck.hoehe for l_ in p.lagen), default=0.0), 2),
            "teile": [l_.eintrag() for l_ in p.lagen], "auslastung": p.auslastung(),
            "passt_nicht": bool(p.passt_nicht),
        })
    # Summen
    material_out = []
    for mat in materialien:
        info = preise.get(mat) or {}
        dichte = float(info.get("dichte") or sz.FILAMENT.get(mat, sz.FILAMENT["pla"]).dichte)
        g_mat = sum(pp["material"][0]["g"] for pp in platten_out if pp["material"][0]["material"] == mat)
        st = {pp["stand"] for pp in platten_out if pp["material"][0]["material"] == mat}
        preis_kg = float(info.get("preis_je_kg") or 0.0)
        material_out.append({"material": mat, "name": info.get("name") or mat, "g": round(g_mat, 1),
                             "m": round(g_mat / dichte / sz.CM3_JE_M, 2), "kosten": round(g_mat / 1000 * preis_kg, 2),
                             "preis_kg": preis_kg or None, "preis_stand": info.get("preis_stand"),
                             "preis_quelle": info.get("preis_quelle"),
                             "stand": st.pop() if len(st) == 1 else "gemischt"})
    zeit_s = sum(pp["zeit_s"] for pp in platten_out)
    wechsel = int(projekt.get("plattenwechsel_s") or 0)
    mit_wechsel = zeit_s + max(0, len(platten_out) - 1) * wechsel
    filament_eur = round(sum(m["kosten"] for m in material_out), 2)
    strom = round(zeit_s / 3600 * float(projekt.get("leistung_w") or 0) / 1000 * float(projekt.get("strompreis_kwh")
                                                                                       or 0), 2)
    anteil_strom = strom / zeit_s if zeit_s else 0.0
    risiko_eur = round(sum(t["risiko"] * (t["kosten"] + t["zeit_s"] * anteil_strom) for t in teile_out), 2)
    staende = {t["stand"] for t in teile_out} | {p["stand"] for p in platten_out}
    gesamt_stand = "schaetzung" if not staende or staende == {"schaetzung"} else (
        "slicer" if staende == {"slicer"} else "gemischt")
    gramm = {m["material"]: m["g"] for m in material_out}
    hinweise = em.globale_hinweise(materialien, gramm, platten_out, sorted(set(nicht_passend)))
    if projekt.get("platte_fehler"):
        hinweise.append({"schwere": "warnung", "art": "platte",
                         "text": f"kevcad.json druck.platte: {projekt['platte_fehler']}; genommen: Texturplatte."})
    if sl.system_ordner().is_dir():
        for mat in materialien:
            fil = next((g.filament for g in gr if g.material == mat and g.filament), None)
            if fil and not sl.platte_passt(fil, str(projekt.get("platte"))):
                hinweise.append({"schwere": "fehler", "art": "platte",
                                 "text": f"{fil} geht nicht auf der {projekt.get('platte')} (Bambu Studio bricht ab): "
                                         "andere Platte in kevcad.json druck.platte, etwa „Textured PEI Plate“."})
    for n in ohne:
        hinweise.append({"schwere": "hinweis", "art": "slicer",
                         "text": f"{n}: keine Vorschau (Geometrie in Druckausrichtung fehlt, Druckprüfung ansehen)."})
    slicer_info = {"zustand": stand.zustand, "fertig": stand.fertig, "gesamt": stand.gesamt, "meldung": stand.meldung,
                   "version": stand.version, "ms": round(stand.ms, 1)}
    if regler and stand.zustand in ("aus", "wartet"):
        slicer_info["zustand"] = "aus"
        slicer_info["meldung"] = ("Reglerstand: nur Schätzung, nichts gespeichert (Slicer erst nach einem Lauf ohne "
                                  "überschriebene Parameter).")
    out = {
        "run": int(run), "stand": gesamt_stand, "drucker": DRUCKER_NAME if drucker == DRUCKER_ID else drucker,
        "summe": {"platten": len(platten_out), "zeit_s": int(zeit_s), "zeit_mit_wechsel_s": int(mit_wechsel),
                  "kosten": round(filament_eur + strom + risiko_eur, 2),
                  "kosten_teile": {"filament": filament_eur, "strom": strom, "risiko": risiko_eur},
                  "material": material_out},
        "platten": platten_out, "teile": teile_out, "hinweise": hinweise, "slicer": slicer_info,
        "einstellungen": {k: projekt.get(k) for k in ("drucker", "strompreis_kwh", "leistung_w", "plattenwechsel_s",
                                                      "slicer", "platte")},
        "regler": bool(regler),
    }
    gedruckt = gedruckte_teile(druck)
    if gedruckt:  # additiv (Strang „Feinschliff 2“): schon gedruckt, vorhanden; nicht in Platten, Summe, Filament
        out["gedruckt"] = gedruckt
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out, gr, [(m, p) for m, p, _ in platten]


def gedruckte_teile(druck: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Als gedruckt markierte Teile (``lager.druckteil(…, gedruckt=True)``): Name, Material, Stand der Form
    (``gleich`` | ``geaendert`` | ``neu`` (eben festgeschrieben) | ``neu_drucken``) und Unterschiede."""
    vorschau = (druck or {}).get("vorschau") or {}
    stand = (druck or {}).get("gedruckt") or {}
    out = []
    for name, t in (vorschau.get("teile") or {}).items():
        if not t.get("gedruckt"):
            continue
        s = stand.get(name) or {}
        out.append({"name": name, "material": t.get("material"), "form": s.get("status") or "neu",
                    "unterschiede": list(s.get("unterschiede") or []), "seit": s.get("seit")})
    return out


def leer(run: int, meldung: str = "Keine Druckteile im Modell.", regler: bool = False) -> dict[str, Any]:
    return {"run": int(run), "stand": "schaetzung", "drucker": DRUCKER_NAME,
            "summe": {"platten": 0, "zeit_s": 0, "zeit_mit_wechsel_s": 0, "kosten": 0.0,
                      "kosten_teile": {"filament": 0.0, "strom": 0.0, "risiko": 0.0}, "material": []},
            "platten": [], "teile": [], "hinweise": [],
            "slicer": {"zustand": "aus", "fertig": 0, "gesamt": 0, "meldung": meldung}, "regler": bool(regler),
            "ms": 0.0}


def kurz(vorschau: dict[str, Any]) -> dict[str, Any]:
    """Ohne Umrisse (MCP ohne ``detail``)."""
    out = dict(vorschau)
    out["platten"] = [{**p, "teile": [{k: v for k, v in t.items() if k != "umriss"} for t in p.get("teile") or []]}
                      for p in vorschau.get("platten") or []]
    return out

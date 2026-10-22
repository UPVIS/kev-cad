"""Urteile, Ampel und Texte (T5, T7) sowie leichtere oder stärkere Lagerteile aus dem Inventar.

Ampel (T5), überall gleich gerechnet über die **Ausnutzung** a = Zielsicherheit / vorhandene Sicherheit:

| Ampel | Festigkeit, Knicken, Schrauben, Bauteile | Kippen, Rutschen (Reserve ν) | Durchbiegung δ / δzul |
|---|---|---|---|
| grün | a ≤ 1 (Sicherheit ≥ Ziel) | ν ≥ 1,5 | ≤ 1 (höchstens L/200) |
| gelb | 1 < a ≤ 2 | 1 ≤ ν < 1,5 | ≤ 2 |
| rot | a > 2 (Sicherheit unter dem halben Ziel, bei Ziel 2: unter 1) | ν < 1: kippt bzw. rutscht | > 2 |

Zielsicherheit: statisch 2, dynamisch 3, Druckteile das Doppelte. „Überdimensioniert“ ab Sicherheit 10 in allen
Lastszenarien (nicht beim reinen Eigengewicht): Kev CAD sucht im Katalog (Inventar, nur freigegeben) das leichteste
Lagerteil derselben Art, mit dem alle Lastszenarien grün bleiben, und nennt die Ersparnis in kg und €.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.bom import de_num
from kevcad_kernel.statik.szenario import UEBERDIMENSIONIERT, Szenario

ZIEL_KIPPEN = 1.5
ZIEL_RUTSCHEN = 1.5
RANG = {"rot": 3, "gelb": 2, "gruen": 1, "grau": 0}
GRENZEN = [
    "Vereinfacht gerechnet: Stäbe als Balken, linear-elastisch, kleine Verformungen, keine Plastizität.",
    "Verbinder (Druckteile, Platten, Zukaufteile) gelten im Stabwerk als starr; Schweißnähte und Schrauben "
    "vereinfacht, Schrauben ohne Vorspannung und ohne Gewindeauszug im Kunststoff.",
    "Werkstoffwerte und Reibwerte sind Richtwerte aus dem Katalog (Norm-Mindestwerte bzw. Datenblatt); Druckteile mit "
    "voller Füllung gerechnet.",
    "Kein Ersatz für einen Statiker bei sicherheitsrelevanten Dingen (Personen, Lasten über Kopf, Fahrzeuge).",
]


def ampel_a(a: float | None) -> str:
    if a is None or not math.isfinite(a):
        return "grau" if a is None else "gruen"
    if a <= 1.0:
        return "gruen"
    return "gelb" if a <= 2.0 else "rot"


def ampel_reserve(r: float | None, ziel: float) -> str:
    if r is None:
        return "gruen"
    if r < 1.0:
        return "rot"
    return "gelb" if r < ziel else "gruen"


def schlechteste(ampeln: list[str]) -> str:
    return max(ampeln, key=lambda a: RANG.get(a, 0)) if ampeln else "grau"


def z(x: float | None, n: int = 2) -> str:
    if x is None:
        return "–"
    if not math.isfinite(x):
        return "∞"
    return de_num(x, n)


def _sf(x: float | None) -> str:
    if x is None:
        return "–"
    if not math.isfinite(x) or x > 999:
        return "über 999"
    return z(x, 2 if x < 10 else 1)


def urteil(art: str, teil: str | None, ampel: str, text: str, loesung: str = "", **zahlen: Any) -> dict[str, Any]:
    return {"art": art, "teil": teil, "ampel": ampel, "text": text, "loesung": loesung,
            **{k: v for k, v in zahlen.items() if v is not None}}


# ---------------------------------------------------------------------------------------------------------------------
# Szenario bewerten


def bewerte(sz: Szenario, s0: dict[str, Any], s1: Any, bauteile: list[dict[str, Any]], modell: Any) -> dict[str, Any]:
    """Ergebnis eines Szenarios: Urteile, Ampel, Kennzahlen, Darstellung je Teil und Stab."""
    ur: list[dict[str, Any]] = []
    ziel = sz.ziel_fuer(False)
    teile_anz: dict[str, dict[str, Any]] = {}
    staebe_anz: list[dict[str, Any]] = []
    stabwerte: list[dict[str, Any]] = []
    sicherheiten: list[float] = []
    durchb = durchb_grenze = None
    verform = 0.0
    knick = None
    # S1: Stäbe
    if s1 is not None and getattr(s1, "ok", False):
        for name, r in s1.staebe.items():
            sf = r.sicherheit
            a = ziel / sf if sf and math.isfinite(sf) else 0.0
            sicherheiten.append(sf)
            st = modell.staebe[name]
            vmax = max((float(np.linalg.norm(v)) for v in r.verschiebung), default=0.0)
            verform = max(verform, vmax)
            amp = ampel_a(a)
            if amp != "gruen":
                ort = st.punkt(r.ort_t)
                ur.append(urteil("festigkeit", name, amp,
                                 f"{name} {'hält nicht' if amp == 'rot' else 'hält knapp'}: Sicherheit {_sf(sf)} "
                                 f"(Ziel {z(ziel, 0)}), Spannung {z(r.spannung_max, 0)} N/mm² bei {z(r.ort_t, 0)} mm "
                                 f"(Grenze {z(st.werkstoff.grenze, 0)} N/mm², {st.werkstoff.name}).",
                                 "Stärkeres Profil aus dem Lager, kürzer auskragen oder abstützen.",
                                 sicherheit=round(sf, 3), ziel=ziel, ausnutzung=round(a, 3),
                                 spannung=r.spannung_max, ort=[round(float(c), 1) for c in ort]))
            dz = r.durchbiegung / r.grenze_durchbiegung if r.grenze_durchbiegung > 0 else 0.0
            if durchb is None or r.durchbiegung > durchb:
                durchb, durchb_grenze = r.durchbiegung, r.grenze_durchbiegung
            amp_d = ampel_a(dz)
            if amp_d != "gruen":
                ur.append(urteil("durchbiegung", name, amp_d,
                                 f"{name} biegt sich {z(r.durchbiegung, 1)} mm durch (zulässig {z(r.grenze_durchbiegung, 1)}"
                                 f" mm: Feld/{z(sz.durchbiegung, 0)}, Kragarm 2 · Länge/{z(sz.durchbiegung, 0)}).",
                                 "Steiferes Profil (höher), kürzere Spannweite oder zusätzliche Stütze.",
                                 durchbiegung=r.durchbiegung, grenze=r.grenze_durchbiegung))
            stabwerte.append({"name": name, "sicherheit": round(sf, 3) if math.isfinite(sf) else None,
                              "spannung_max": r.spannung_max, "ort_mm": r.ort_t, "durchbiegung_mm": r.durchbiegung,
                              "durchbiegung_grenze_mm": r.grenze_durchbiegung, "knicken": r.knicken,
                              "druckkraft_n": r.normalkraft_min, "profil": st.item.get("name") or st.stock_id,
                              "werkstoff": st.werkstoff.name})
            a_st = [round(float(u) * ziel, 4) for u in r.ausnutzung]
            staebe_anz.append({"name": name, "punkte": r.punkte, "ausnutzung": a_st, "verschiebung": r.verschiebung,
                               "radius": round(float(st.q.radius), 2), "sicherheit": round(sf, 3) if math.isfinite(sf)
                               else None, "ampel": amp})
            teile_anz[name] = {"name": name, "ausnutzung": round(a, 4), "ampel": schlechteste([amp, amp_d]),
                               "verformung_mm": round(vmax, 3), "sicherheit": round(sf, 3) if math.isfinite(sf) else None}
        if s1.knicken is not None:
            knick = s1.knicken
            a = ziel / knick
            amp = ampel_a(a)
            if amp != "gruen":
                ur.append(urteil("knicken", s1.knick_stab, amp,
                                 f"{s1.knick_stab} knickt beim {z(knick, 2)}-Fachen der Last (Ziel {z(ziel, 0)}).",
                                 "Knicklänge verkürzen (Zwischenstütze), dickeres oder steiferes Profil.",
                                 sicherheit=knick, ziel=ziel))
                if s1.knick_stab in teile_anz:
                    t = teile_anz[s1.knick_stab]
                    t["ampel"] = schlechteste([t["ampel"], amp])
                    t["ausnutzung"] = max(t["ausnutzung"], round(a, 4))
    # Bauteile (Kragträger, Druckteile)
    for b in bauteile:
        if b.get("sicherheit") is None:
            ur.append(urteil("bauteil", b["teil"], "grau", b.get("text") or f"{b['teil']}: nicht nachgewiesen"))
            continue
        zb = b["ziel"]
        sf = b["sicherheit"]
        sicherheiten.append(sf)
        a = zb / sf if sf and math.isfinite(sf) else 0.0
        amp = ampel_a(a)
        schicht = (f", quer zur Schicht (nur {z(b['schichtfaktor'] * 100, 0)} % der Festigkeit)"
                   if b.get("quer_zur_schicht") else "")
        lager = f" als Lager von {b['aus_lager']}" if b.get("aus_lager") else ""
        text = (f"{b['teil']}{lager} {'hält nicht' if amp == 'rot' else ('hält knapp' if amp == 'gelb' else 'hält')}"
                f": Sicherheit {_sf(sf)} (Ziel {z(zb, 0)}{', Druckteil' if b.get('druckteil') else ''}), "
                f"{z(b['spannung'], 1)} N/mm² an der Einspannung (Hebel {z(b['hebel_mm'], 0)} mm){schicht}.")
        loesung = b.get("vorschlag") or ""
        if amp != "gruen" or (b.get("quer_zur_schicht") and not b.get("aus_lager")):
            ur.append(urteil("bauteil", b["teil"], amp, text, loesung, sicherheit=sf, ziel=zb, ausnutzung=round(a, 3),
                             schichtfaktor=b.get("schichtfaktor"), quer_zur_schicht=b.get("quer_zur_schicht"),
                             ort=b.get("einspannung")))
        teile_anz[b["teil"]] = {"name": b["teil"], "ausnutzung": round(a, 4), "ampel": amp, "verformung_mm": None,
                                "sicherheit": sf}
    # S0: Kippen, Rutschen, lose Teile, Schrauben
    kipp = None
    for k in s0.get("kippen") or []:
        r = k.get("reserve")
        if r is not None:
            kipp = r if kipp is None else min(kipp, r)
        amp = ampel_reserve(r, ZIEL_KIPPEN)
        if amp != "gruen" and not sz.nur_eigengewicht:  # im Ruhezustand meldet das die Prüfung „stand“ schon
            name = k.get("name") or k["teile"][0]
            richtung = f" nach {k['richtung_text']}" if k.get("richtung_text") else ""
            ur.append(urteil("kippen", k["teile"][0], amp,
                             f"{name} {'kippt' if amp == 'rot' else 'steht knapp'}{richtung}: Kippreserve {z(r, 2)} "
                             f"(Ziel {z(ZIEL_KIPPEN, 1)}; Standmoment durch Kippmoment um die Kante der Standfläche).",
                             "Standfläche in Kipprichtung verbreitern, Schwerpunkt senken oder Last näher an die "
                             "Mitte.", reserve=r, ziel=ZIEL_KIPPEN, kante=k.get("kante")))
    rutsch = None
    for r_ in s0.get("rutschen") or []:
        r = r_.get("reserve")
        if r is not None:
            rutsch = r if rutsch is None else min(rutsch, r)
        amp = ampel_reserve(r, ZIEL_RUTSCHEN)
        if amp != "gruen":
            rollen = " (auf Rollen: gilt gebremst; ungebremst rollt es weg)" if r_.get("auf_rollen") else ""
            ur.append(urteil("rutschen", r_["teile"][0], amp,
                             f"Rutscht {'' if amp == 'rot' else 'fast '}auf dem Boden: nötig μ = {z(r_['mu_erf'], 2)}, "
                             f"vorhanden μ = {z(r_['mu_vorh'], 2)} ({r_['teil'].rsplit('/', 1)[-1]} auf "
                             f"{r_['untergrund']}){rollen}.",
                             "Rutschfeste Füße (Gummi), Gewicht tiefer, Feststeller oder befestigen.",
                             reserve=r, mu_erf=r_["mu_erf"], mu_vorh=r_["mu_vorh"]))
    for l in s0.get("lose") or []:
        r = l.get("reserve")
        amp = "rot" if l.get("hebt_ab") else ampel_reserve(r, ZIEL_RUTSCHEN)
        if amp != "gruen":
            ur.append(urteil("rutschen", l["teil"], amp,
                             f"{l['teil']} liegt lose auf {l['auf']} und "
                             f"{'hebt ab' if l.get('hebt_ab') else ('rutscht' if amp == 'rot' else 'rutscht fast')}"
                             + ("" if l.get("hebt_ab") else f": nötig μ = {z(l['mu_erf'], 2)}, vorhanden "
                                                            f"{z(l['mu_vorh'], 2)}") + ".",
                             "Befestigen (verbinde mit Schraube oder Klemmung) oder Anschlag vorsehen.", reserve=r))
    schr_min = None
    for s in s0.get("schrauben") or []:
        sf = s.get("sicherheit")
        if sf is None:
            continue
        schr_min = sf if schr_min is None else min(schr_min, sf)
        a = ziel / sf
        amp = ampel_a(a)
        if amp != "gruen":
            ur.append(urteil("schraube", s["teile"][2] if len(s["teile"]) > 2 else s["teile"][0], amp,
                             f"Schrauben {s['verbindung']} ({s['schrauben']} × {s['gewinde']}): Sicherheit {_sf(sf)} "
                             f"(Ziel {z(ziel, 0)}), je Schraube {z(s['kraft_axial'], 0)} N Zug, {z(s['kraft_quer'], 0)} N "
                             "quer (grob).",
                             "Mehr oder dickere Schrauben, größerer Abstand zwischen den Schrauben, Last näher an die "
                             "Verbindung.", sicherheit=sf, ziel=ziel))
        elif s.get("druckteil") and not sz.nur_eigengewicht and s["kraft_axial"] > 50:
            ur.append(urteil("schraube", s["druckteil"][0], "grau",
                             f"Schrauben {s['verbindung']}: je Schraube {z(s['kraft_axial'], 0)} N Zug; im Druckteil "
                             f"{s['druckteil'][0]} trägt das der Gewindeeinsatz (Auszug nicht nachgewiesen).",
                             "Auszugkraft des Einsatzes beim Hersteller nachsehen.", sicherheit=sf))
    sicherheit = min(sicherheiten) if sicherheiten else None
    amp = schlechteste([u["ampel"] for u in ur] + (["gruen"] if (sicherheiten or kipp or rutsch) else ["grau"]))
    return {"name": sz.name, "szenario": sz.kurz(), "ampel": amp, "ziel": ziel, "urteile": ur,
            "kennzahlen": {"sicherheit": None if sicherheit is None or not math.isfinite(sicherheit)
                           else round(sicherheit, 3),
                           "knicken": knick, "kippreserve": kipp, "rutschreserve": rutsch,
                           "schrauben_sicherheit": schr_min,
                           "durchbiegung_mm": durchb, "durchbiegung_grenze_mm": durchb_grenze,
                           "verformung_max_mm": round(verform, 3)},
            "teile": sorted(teile_anz.values(), key=lambda t: -t["ausnutzung"]), "staebe": staebe_anz,
            "stabwerte": stabwerte, "bauteile": bauteile,
            "auflager": list(getattr(s1, "auflager", []) or []) if s1 is not None else [],
            "s0": s0, "s1": {"ok": bool(getattr(s1, "ok", False)), "meldung": getattr(s1, "meldung", ""),
                             "ms": getattr(s1, "ms", None)} if s1 is not None else None}


def kurztext(e: dict[str, Any]) -> str:
    """„Aufstützen 30 kg: rot – Seitenstange links hält nicht (Sicherheit 0,18)“."""
    worte = {"gruen": "grün", "gelb": "gelb", "rot": "rot", "grau": "nicht gerechnet"}
    kz = e.get("kennzahlen") or {}
    teile = []
    schlimm = sorted((u for u in e.get("urteile") or [] if u["ampel"] in ("rot", "gelb")),
                     key=lambda u: -RANG[u["ampel"]])
    if schlimm:
        teile.append(schlimm[0]["text"].split(":")[0] + (f" (Sicherheit {_sf(schlimm[0].get('sicherheit'))})"
                                                          if schlimm[0].get("sicherheit") is not None else ""))
    else:
        if kz.get("sicherheit") is not None:
            teile.append(f"Sicherheit {_sf(kz['sicherheit'])}")
        if kz.get("kippreserve") is not None:
            teile.append(f"Kippreserve {z(kz['kippreserve'], 1)}")
    return f"{e['name']}: {worte.get(e['ampel'], e['ampel'])}" + (" – " + ", ".join(teile) if teile else "")


# ---------------------------------------------------------------------------------------------------------------------
# Leichter oder stärker aus dem Inventar


def _kandidaten(katalog: Any, stab: Any, leichter: bool) -> list[tuple[float, dict[str, Any]]]:
    from kevcad_kernel.catalog import is_free
    from kevcad_kernel.profiles import kg_je_m

    out = []
    if katalog is None:
        return out
    mat0 = katalog.material(stab.material_id) if stab.material_id else None
    kg0 = kg_je_m(stab.item, mat0) or 0.0
    for it in katalog.items(stab.art):
        if not is_free(it) or it.get("id") == stab.stock_id or it.get("material") != stab.material_id:
            continue  # nur derselbe Werkstoff: Fügen, Schweißen und Optik bleiben gleich
        mat = katalog.material(it.get("material")) if it.get("material") else None
        if not mat or not isinstance(mat.get("mechanik"), dict):
            continue
        kg = kg_je_m(it, mat)
        if kg is None:
            continue
        if (leichter and kg < kg0 - 1e-6) or (not leichter and kg > kg0 + 1e-6):
            out.append((kg, it))
    out.sort(key=lambda x: x[0])
    return out


def _preis_je_m(it: dict[str, Any]) -> float | None:
    p = (it.get("preis") or {}).get("je_m")
    try:
        return float(p) if p is not None else None
    except (TypeError, ValueError):
        return None


def _schaetzung(staebe: list[Any], szenarien: list[Szenario], ergebnisse: dict[str, Any] | None, q: Any, w: Any
                ) -> bool:
    """Reicht der Kandidat voraussichtlich? Skaliert die vorhandenen Ergebnisse mit Widerstandsmoment, Fläche,
    Steifigkeit und Festigkeit (ohne Umlagerung, darum mit 10 % Spielraum). Ohne Ergebnisse: ja."""
    if not ergebnisse:
        return True
    for sz in szenarien:
        e = ergebnisse.get(sz.name)
        if e is None or not getattr(e, "ok", False):
            return True
        ziel = sz.ziel_fuer(False)
        for s in staebe:
            r = e.staebe.get(s.name)
            if r is None:
                continue
            q0, w0 = s.q, s.werkstoff
            f = min(min(q.W_lang, q.W_quer) / max(min(q0.W_lang, q0.W_quer), 1e-9), q.A / max(q0.A, 1e-9))
            fest = float(w.grenze or 0) / max(float(w0.grenze or 1), 1e-9)
            steif = (float(w.E) * min(q.I_lang, q.I_quer)) / max(float(w0.E) * min(q0.I_lang, q0.I_quer), 1e-9)
            if math.isfinite(r.sicherheit) and r.sicherheit * f * fest < 0.9 * ziel:
                return False
            if r.durchbiegung / max(steif, 1e-9) > 1.1 * r.grenze_durchbiegung:
                return False
        if e.knicken is not None and e.knick_stab in {s.name for s in staebe}:
            q0, w0 = staebe[0].q, staebe[0].werkstoff
            steif = (float(w.E) * min(q.I_lang, q.I_quer)) / max(float(w0.E) * min(q0.I_lang, q0.I_quer), 1e-9)
            if e.knicken * steif < 0.9 * sz.ziel_fuer(False):
                return False
    return True


def alternative(modell: Any, szenarien: list[Szenario], katalog: Any, stock_id: str, leichter: bool,
                ergebnisse: dict[str, Any] | None = None, max_pruefen: int = 4) -> dict[str, Any] | None:
    """Leichtestes Lagerteil derselben Art (leichter: leichter als jetzt; sonst schwerer), mit dem alle Stäbe dieses
    Lagerteils in allen Szenarien grün sind (Festigkeit, Knicken, Durchbiegung). Erst geschätzt (Skalierung der
    vorhandenen Ergebnisse), dann die aussichtsreichsten ``max_pruefen`` mit dem ganzen Stabwerk nachgerechnet."""
    from kevcad_kernel.profiles import kg_je_m
    from kevcad_kernel.statik.stabwerk import rechne
    from kevcad_kernel.statik.werkstoff import querschnitt, werkstoff_aus_eintrag

    staebe = [s for s in modell.staebe.values() if s.stock_id == stock_id]
    if not staebe or not szenarien:
        return None
    s0 = staebe[0]
    laenge_m = sum(s.laenge for s in staebe) / 1000.0
    geprueft = 0
    for kg, it in _kandidaten(katalog, s0, leichter):
        if geprueft >= max_pruefen:
            break
        mat = katalog.material(it["material"])
        w = werkstoff_aus_eintrag(mat)
        try:
            q = querschnitt(it["art"], it.get("masse") or {})
        except Exception:  # noqa: BLE001
            continue
        if w is None or not _schaetzung(staebe, szenarien, ergebnisse, q, w):
            continue
        geprueft += 1
        erg = rechne(modell, szenarien, knicken=True, ersatz={s.name: (q, w) for s in staebe})
        gut = True
        sf_min = math.inf
        for sz in szenarien:
            e = erg.get(sz.name)
            if e is None or not e.ok:
                gut = False
                break
            ziel = sz.ziel_fuer(False)
            for s in staebe:
                r = e.staebe.get(s.name)
                if r is None or r.sicherheit < ziel or r.durchbiegung > r.grenze_durchbiegung:
                    gut = False
                    break
                sf_min = min(sf_min, r.sicherheit)
            if gut and e.knicken is not None and e.knicken < ziel:
                gut = False
            if not gut:
                break
        if not gut:
            continue
        mat0 = katalog.material(s0.material_id) if s0.material_id else None
        kg0 = kg_je_m(s0.item, mat0) or 0.0
        p0, p1 = _preis_je_m(s0.item), _preis_je_m(it)
        return {"stock_id": it["id"], "name": it.get("name") or it["id"], "statt": s0.item.get("name") or stock_id,
                "staebe": [s.name for s in staebe], "laenge_m": round(laenge_m, 3),
                "kg_je_m": round(kg, 3), "kg_je_m_alt": round(kg0, 3),
                "ersparnis_kg": round((kg0 - kg) * laenge_m, 3),
                "ersparnis_eur": round((p0 - p1) * laenge_m, 2) if p0 is not None and p1 is not None else None,
                "sicherheit": round(sf_min, 2) if math.isfinite(sf_min) else None, "geprueft": geprueft}
    return None


def ueberdimensioniert(modell: Any, szenarien: list[Szenario], ergebnisse: dict[str, Any], katalog: Any
                       ) -> list[dict[str, Any]]:
    """Urteile „überdimensioniert“ je Lagerteil (alle Stäbe dieses Lagerteils in allen Lastszenarien ≥ 10)."""
    last = [sz for sz in szenarien if sz.hat_lasten]
    if not last:
        return []
    out = []
    gruppen: dict[str, list[str]] = {}
    for s in modell.staebe.values():
        if s.stock_id:
            gruppen.setdefault(s.stock_id, []).append(s.name)
    for sid, namen in gruppen.items():
        sf_min = math.inf
        ok = True
        for sz in last:
            e = ergebnisse.get(sz.name)
            if e is None or not e.ok:
                ok = False
                break
            for n in namen:
                sf_min = min(sf_min, e.staebe[n].sicherheit)
            if e.knicken is not None and e.knick_stab in namen:
                sf_min = min(sf_min, e.knicken)
        if not ok or sf_min < UEBERDIMENSIONIERT:
            continue
        alt = alternative(modell, last, katalog, sid, leichter=True, ergebnisse=ergebnisse)
        statt = modell.staebe[namen[0]].item.get("name") or sid
        if alt:
            eur = (f" und {z(alt['ersparnis_eur'], 2)} €" if alt.get("ersparnis_eur") else "")
            text = (f"{statt} ist überdimensioniert (Sicherheit {_sf(sf_min)}): {alt['name']} aus dem Lager reicht "
                    f"(Sicherheit {_sf(alt['sicherheit'])}), spart {z(alt['ersparnis_kg'], 2)} kg{eur}.")
            loesung = (f"In model.py lager.teil(\"{alt['stock_id']}\") statt \"{sid}\" verbauen (Anschlüsse und "
                       "Bohrungen an das kleinere Profil anpassen).")
        else:
            text = f"{statt} ist überdimensioniert (Sicherheit {_sf(sf_min)}); im Lager gibt es nichts Leichteres, das reicht."
            loesung = ""
        out.append(urteil("ueberdimensioniert", namen[0], "gruen", text, loesung, sicherheit=round(sf_min, 2),
                          staebe=namen, alternative=alt))
    return out


def staerker(modell: Any, szenarien: list[Szenario], ergebnisse: dict[str, Any], katalog: Any
             ) -> dict[str, dict[str, Any]]:
    """Je Lagerteil mit rotem Stab: das leichteste stärkere Lagerteil derselben Art, das in allen Szenarien reicht."""
    rot = set()
    for sz in szenarien:
        e = ergebnisse.get(sz.name)
        if e is None or not e.ok:
            continue
        for n, r in e.staebe.items():
            if r.sicherheit < sz.ziel_fuer(False) or r.durchbiegung > r.grenze_durchbiegung:
                rot.add(modell.staebe[n].stock_id)
    out = {}
    for sid in rot:
        if not sid:
            continue
        alt = alternative(modell, szenarien, katalog, sid, leichter=False, ergebnisse=ergebnisse)
        if alt:
            out[sid] = alt
    return out

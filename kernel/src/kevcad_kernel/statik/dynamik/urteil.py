"""Urteile des Ablaufs (S2) im Format der Stufe 1 (``bewertung.urteil``): Ampel, Text, Lösung, Zahlen.

| Urteil | grün | gelb | rot |
|---|---|---|---|
| ``dyn_kippen`` (Kippreserve ν = Verzögerung, ab der es abhebt / Verzögerung im Szenario) | ν ≥ 1,5 | 1 ≤ ν < 1,5 | ν < 1: hebt ab (und fällt zurück oder kippt um) |
| ``dyn_ladung`` (Ladung wie der Ball) | bleibt, Grenze ≥ 1,5 × v | bleibt knapp (Grenze unter 1,5 × v oder hebt über 10 mm) | springt heraus |
| ``dyn_rutschen`` (Bremsen über blockierte Räder: a_rutsch = μ · g) | ν ≥ 1,5 | ν < 1,5 (rutscht statt zu bremsen) | – |

Dazu die Handrechnung zum Kippen nach vorn: a = g · b / h (b waagrechter Abstand Schwerpunkt bis vordere Aufstandslinie,
h Höhe des Schwerpunkts über dem Boden), verglichen mit der Simulation ohne Ladung bei anhaltender Verzögerung.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.statik.bewertung import RANG, schlechteste, urteil, z

G = 9.81
ZIEL = 1.5  # Reserve wie Kippen und Rutschen in Stufe 1


def ampel_reserve(r: float | None) -> str:
    if r is None or not math.isfinite(r):
        return "gruen"
    if r < 1.0:
        return "rot"
    return "gelb" if r < ZIEL else "gruen"


def handrechnung(meta: dict[str, Any], mo: Any) -> dict[str, Any] | None:
    """Kippen nach vorn ohne Ladung: a = g · b / h über die vordere Aufstandslinie in Antriebsrichtung."""
    from kevcad_kernel.statik.dynamik.ablauf import teilbaum

    an = meta.get("antrieb")
    if an is None:
        return None
    K = {k["id"]: k for k in meta["koerper"]}
    tb = teilbaum(meta, an)
    m = sum(K[x]["masse"] for x in tb)
    c = sum(K[x]["masse"] * np.asarray(K[x]["schwerpunkt"], float) for x in tb) / max(m, 1e-9)
    d = np.asarray(mo.richtung, float)
    punkte = []
    for f in mo.fuss:
        if f["art"] == "achse":
            punkte.append(np.asarray(f["punkt"], float))
        else:
            kol = meta["kollision"].get(f.get("teil"))
            if kol and kol["art"] == "kugel":
                punkte.append(np.asarray(kol["mitte"], float))
    for kid in tb:
        for n in K[kid]["boden"]:
            kol = meta["kollision"].get(n)
            if kol and kol["art"] not in ("kugel", "drehteil"):
                punkte.append((np.asarray(K[kid]["bmin"]) + np.asarray(K[kid]["bmax"])) / 2)
    if not punkte:
        return None
    vorn = max(float((p - c) @ d) for p in punkte)
    h = float(c[2] - meta["boden_z"])
    if h <= 1e-6:
        return None
    a = G * vorn / h
    return {"b_mm": vorn, "h_mm": h, "masse": m, "a_kipp": a, "kippwinkel": math.degrees(math.atan2(vorn, h)),
            "text": f"a = g · b / h = 9,81 · {z(vorn, 0)} / {z(h, 0)} = {z(a, 1)} m/s² (ohne Ladung, b bis zur "
                    f"vorderen Achse, h Höhe des Schwerpunkts)"}


def _ms(x: float | None, n: int = 1) -> str:
    return "–" if x is None else z(x, n)


def bewerte(sz: dict[str, Any], meta: dict[str, Any], mo: Any, auf: Any, suche: dict[str, Any],
            hand: dict[str, Any] | None, mu_rad: float | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """(Urteile, Kennzahlen) eines Ablaufs."""
    from kevcad_kernel.statik.dynamik.ablauf import ladung_verloren

    K = {k["id"]: k for k in meta["koerper"]}
    b = auf.bewertung
    v = float(sz["v"])
    a = float(sz["a"])
    ur: list[dict[str, Any]] = []
    kz: dict[str, Any] = {"geschwindigkeit": v, "verzoegerung": a, "kippwinkel_max": round(b.kipp_max, 2),
                          "kippwinkel_hinten": round(b.kipp_min, 2), "seitlich_max": round(b.roll_max, 2),
                          "abheben_max_mm": round(b.abheben_max, 1), "abheben_wo": b.abheben_wo,
                          "abheben_t": b.abheben_t, "weg_m": round(b.weg, 3)}
    an = meta.get("antrieb")
    name_an = K[an]["name"] if an else "Der Aufbau"
    kurz_an = name_an.split(" mit ")[0].split(" (")[0]
    # Kippen -----------------------------------------------------------------------------------------------------
    ab_a = (suche.get("kippen_a") or {})
    a_ab = ab_a.get("wert")
    if ab_a.get("nie_bis_hi"):
        a_ab = math.inf
    reserve = (a_ab / a) if (a_ab is not None and a > 0) else None
    if reserve is None and a > 0 and b.abheben_max > 1.0:
        reserve = 0.0
    kipp_grenze = hand["kippwinkel"] if hand else None
    kippt_um = bool(kipp_grenze is not None and b.kipp_max > kipp_grenze)
    kz.update({"a_abheben": None if a_ab is None or not math.isfinite(a_ab) else round(a_ab, 2),
               "kippreserve": None if reserve is None or not math.isfinite(reserve) else round(reserve, 2),
               "kippt_um": kippt_um, "kippwinkel_grenze": None if kipp_grenze is None else round(kipp_grenze, 1)})
    v_kipp = (suche.get("kippen_v") or {}).get("wert")
    kz["v_abheben"] = None if v_kipp is None else round(v_kipp, 2)
    ohne = (suche.get("kippen_ohne_ladung") or {})
    if ohne:
        kz["a_abheben_ohne_ladung"] = None if ohne.get("wert") is None else round(ohne["wert"], 2)
        if reserve is None and ohne.get("wert") and a > 0:  # Sollbahn aus einer Animation: gegen anhaltendes Bremsen
            reserve = float(ohne["wert"]) / a
            kz["kippreserve"] = round(reserve, 2)
            a_ab = float(ohne["wert"])
            kz["a_abheben"] = round(a_ab, 2)
    if hand:
        kz["a_kipp_hand"] = round(hand["a_kipp"], 2)
    from kevcad_kernel.statik.dynamik.ablauf import ABHEBEN_MM

    hebt = b.abheben_max > ABHEBEN_MM
    aufsetzen = _aufsetzer(auf, meta, an)
    if hebt or kippt_um:
        amp = "rot"
        wo = f" ({b.abheben_wo.split(' (')[0]})" if b.abheben_wo else ""
        if kippt_um:
            text = f"{kurz_an} kippt um: Kippwinkel {z(b.kipp_max, 1)}° über der Kippgrenze {z(kipp_grenze, 0)}°."
            kurz = f"{kurz_an} kippt um"
        else:
            text = (f"{kurz_an} kippt nach vorn: hebt hinten {z(b.abheben_max, 0)} mm ab{wo}, "
                    f"{z(b.kipp_max, 1)}°, fällt zurück")
            text += (f"; {aufsetzen} setzt auf dem Boden auf." if aufsetzen else ".")
            kurz = f"{kurz_an} kippt nach vorn (hebt {z(b.abheben_max, 0)} mm ab)"
        if a_ab is not None and math.isfinite(a_ab):
            text += f" Hebt schon ab {z(a_ab, 1)} m/s² ab (Kippreserve {z(reserve, 2)})."
        if v_kipp:
            text += f" Bei dieser Bremsart ab {z(v_kipp, 2)} m/s."
        loesung = ("Sanfter bremsen oder langsamer schieben, Schwerpunkt senken (Kamera tiefer), Achsabstand nach vorn "
                   "vergrößern oder die Last vorn (Ball, Fangrolle) näher an die Vorderachse.")
    else:
        amp = ampel_reserve(reserve)
        if reserve is None or not math.isfinite(reserve):
            text = f"{kurz_an} kippt nicht (größter Kippwinkel {z(b.kipp_max, 2)}°)."
            kurz = f"{kurz_an} kippt nicht"
        else:
            text = (f"{kurz_an} {'steht knapp' if amp == 'gelb' else 'kippt nicht'}: Kippreserve {z(reserve, 2)} "
                    f"(hebt erst ab {z(a_ab, 1)} m/s² ab, gebremst wird mit {z(a, 1)} m/s²).")
            kurz = f"{kurz_an} {'steht knapp' if amp == 'gelb' else 'kippt nicht'} (Kippreserve {z(reserve, 2)})"
        loesung = "" if amp == "gruen" else "Sanfter bremsen oder Schwerpunkt senken."
    ur.append(urteil("dyn_kippen", None, amp, text, loesung, reserve=kz["kippreserve"], ziel=ZIEL,
                     ort=_ort_vorn(meta, mo) if amp != "gruen" else None, kurz=kurz))
    # Ladung (Ball) ---------------------------------------------------------------------------------------------------
    ladungen = []
    for kid in mo.ladung:
        L = b.ladung.get(kid)
        if L is None:
            continue
        name = K[kid]["name"]
        kurz = name.rsplit("/", 1)[-1].split(" (")[0]
        weg = ladung_verloren(b, kid)
        vg = (suche.get(f"ladung_v:{kid}") or {})
        v_grenze = vg.get("wert")
        if vg.get("nie_bis_hi"):
            v_grenze = math.inf
        eintrag = {"koerper": kid, "name": name, "versatz_max_mm": round(L["versatz"], 1),
                   "hebt_max_mm": round(L["hebt"], 1), "ende_mm": round(L["ende"], 1), "bleibt": not weg,
                   "v_grenze": None if v_grenze is None or not math.isfinite(v_grenze) else round(v_grenze, 2),
                   "v_grenze_nie": bool(vg.get("nie_bis_hi")), "v_grenze_bis": vg.get("ab")}
        ladungen.append(eintrag)
        if weg:
            amp = "rot"
            text = (f"{kurz} springt heraus: {z(L['versatz'], 0)} mm weg, {z(L['hebt'], 0)} mm hoch "
                    f"({z(L['versatz_t'], 2)} s)")
            if v_grenze is not None and math.isfinite(v_grenze):
                text += f"; bleibt nur bis {z(v_grenze, 2)} m/s"
            text += "."
            kurz_l = f"{kurz} springt heraus"
            loesung = "Langsamer schieben oder sanfter bremsen; Fangrolle höher setzen oder näher an den Ball."
        else:
            knapp = (v_grenze is not None and math.isfinite(v_grenze) and v_grenze < ZIEL * v) or L["hebt"] > 10.0
            amp = "gelb" if knapp else "gruen"
            text = f"{kurz} bleibt im Schieber: größter Versatz {z(L['versatz'], 0)} mm"
            if L["hebt"] > 1.0:
                text += f", steigt {z(L['hebt'], 0)} mm hoch"
            if v_grenze is not None and math.isfinite(v_grenze):
                text += f"; springt bei dieser Bremsart ab {z(v_grenze, 2)} m/s heraus"
            elif vg.get("nie_bis_hi"):
                text += f"; bleibt bis mindestens {z(vg.get('ab'), 1)} m/s"
            text += "."
            kurz_l = f"{kurz} bleibt" + (f" knapp (springt ab {z(v_grenze, 2)} m/s heraus)" if knapp and v_grenze
                                         and math.isfinite(v_grenze) else (" knapp" if knapp else ""))
            loesung = "Langsamer schieben oder sanfter bremsen; Fangrolle höher setzen." if knapp else ""
        ur.append(urteil("dyn_ladung", name, amp, text, loesung, reserve=(v_grenze / v) if v_grenze and v > 0
                         and math.isfinite(v_grenze) else None, ziel=ZIEL, kurz=kurz_l))
    kz["ladung"] = ladungen
    # Rutschen über blockierte Räder ----------------------------------------------------------------------------------
    if mu_rad is not None and a > 0:
        a_r = mu_rad * G
        r = a_r / a
        kz.update({"mu_rad": round(mu_rad, 2), "rutschgrenze": round(a_r, 2), "rutschreserve": round(r, 2)})
        amp = "gruen" if r >= ZIEL else "gelb"
        if amp == "gelb":
            text = (f"Mit blockierten Rädern rutscht {kurz_an} ab {z(a_r, 1)} m/s² (μ = {z(mu_rad, 2)}); "
                    f"{z(a, 1)} m/s² bremst nur, wer festhält.")
        else:
            text = f"Rutschgrenze {z(a_r, 1)} m/s² (μ = {z(mu_rad, 2)}), Reserve {z(r, 2)}."
        ur.append(urteil("dyn_rutschen", None, amp, text, "" if amp == "gruen" else
                         "Beim Bremsen am Wagen festhalten statt nur die Räder zu blockieren.", reserve=round(r, 2),
                         ziel=ZIEL, kurz=f"rutscht mit blockierten Rädern ab {z(a_r, 1)} m/s²"))
    # Kräfte -----------------------------------------------------------------------------------------------------------
    namen = {k["id"]: k["name"] for k in meta["koerper"]}
    namen["boden"] = "Boden"
    kraefte = []
    for key, reihe in auf.paar_kraft.items():
        a_, b_ = key.split("|")
        if float(reihe.max()) < 1.0:
            continue
        kraefte.append({"paar": [namen.get(a_, a_), namen.get(b_, b_)], "max_n": round(float(reihe.max()), 1)})
    kraefte.sort(key=lambda k: -k["max_n"])
    kz["kontaktkraefte"] = kraefte[:8]
    kz["fuehrungskraft_max_n"] = round(float(np.abs(auf.fuehrung).max()), 1) if len(auf.fuehrung) else None
    if aufsetzen:
        kz["setzt_auf"] = aufsetzen
    return ur, kz


def _aufsetzer(auf: Any, meta: dict[str, Any], an: str | None) -> str | None:
    """Teil des geschobenen Körpers, das ohne Rad den Boden berührt (Fangrolle, Stange), mit der größten Kraft."""
    if an is None:
        return None
    from kevcad_kernel.statik.dynamik.ablauf import teilbaum

    tb = teilbaum(meta, an)
    K = {k["id"]: k for k in meta["koerper"]}
    best, kraft = None, 1.0
    for key, reihe in auf.paar_kraft.items():
        a_, b_ = key.split("|")
        x = b_ if a_ == "boden" else (a_ if b_ == "boden" else None)
        if x is None or x not in tb or K[x]["boden"]:
            continue
        if float(reihe.max()) > kraft:
            best, kraft = K[x]["name"], float(reihe.max())
    if best is None:
        return None
    return best.split(" (")[0].rsplit("/", 1)[-1] if " mit " not in best else best.split(" mit ")[0]


def _ort_vorn(meta: dict[str, Any], mo: Any) -> list[float] | None:
    an = meta.get("antrieb")
    if an is None:
        return None
    K = {k["id"]: k for k in meta["koerper"]}
    c = np.asarray(K[an]["schwerpunkt"], float)
    return [round(float(x), 1) for x in c]


def kurztext(name: str, urteile: list[dict[str, Any]], ampel: str) -> str:
    """„Bremsen aus 1 m/s: rot – Rollwagen kippt nach vorn (hebt 17 mm ab), Bowlingball bleibt knapp (…)“."""
    worte = {"gruen": "grün", "gelb": "gelb", "rot": "rot", "grau": "nicht gerechnet"}
    teile = []
    reihe = {"dyn_kippen": 0, "dyn_ladung": 1}
    for u in sorted(urteile, key=lambda u: (reihe.get(u["art"], 2), -RANG.get(u["ampel"], 0))):
        if u["art"] in reihe or u["ampel"] in ("rot", "gelb"):
            k = u.get("kurz") or u["text"].split(":")[0].split(";")[0]
            teile.append(k)
    return f"{name}: {worte.get(ampel, ampel)}" + (" – " + ", ".join(dict.fromkeys(teile)) if teile else "")


def einbauen(e: dict[str, Any], ablauf: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis des Ablaufs in das Szenario der Stufe 1 einbauen: Kippen und Rutschen aus S0 (quasistatisch) weichen
    den Urteilen des Ablaufs, Festigkeit und Bauteile bleiben (mit der größten Verzögerung als ruhende Last)."""
    e = dict(e)
    e["ablauf"] = ablauf
    if ablauf.get("stand") != "done":
        return e
    alt = [u for u in e.get("urteile") or [] if u.get("art") not in ("kippen", "rutschen")]
    e["urteile"] = alt + list(ablauf.get("urteile") or [])
    e["ampel"] = schlechteste([u["ampel"] for u in e["urteile"]] + ["gruen"])
    kz = dict(e.get("kennzahlen") or {})
    akz = ablauf.get("kennzahlen") or {}
    kz["kippreserve"] = akz.get("kippreserve")
    kz["rutschreserve"] = akz.get("rutschreserve")
    kz["kippwinkel_max"] = akz.get("kippwinkel_max")
    kz["abheben_max_mm"] = akz.get("abheben_max_mm")
    e["kennzahlen"] = kz
    e["text"] = kurztext(e.get("name") or "", list(ablauf.get("urteile") or []) + alt, e["ampel"])
    return e

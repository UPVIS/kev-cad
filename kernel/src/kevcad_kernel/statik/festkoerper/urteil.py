"""Urteile des Festkörpers (S3) und Einbau ins Szenario (Laufzeit).

Ein gerechneter Fall ersetzt im Szenario den Kragträger-Nachweis (Urteil ``bauteil``) desselben Teils durch ein Urteil
``festkoerper`` mit derselben Ampel-Rechnung (T9: Ausnutzung = Ziel / Sicherheit, Ziel bei Druckteilen 4 statisch).
Für Druckteile bleibt der Hinweis „drehen oder verstärken“, jetzt mit FEM-Beleg: Die Sicherheit in den anderen
Drucklagen kommt aus demselben Spannungsfeld (Schichtkriterium mit der anderen Schichtnormalen).
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.statik.bewertung import _sf, ampel_a, schlechteste, urteil, z

BESSER = 1.2  # andere Drucklage erst ab 20 % mehr Sicherheit vorschlagen


def _ort(p: Any) -> str:
    return "(" + "; ".join(z(c, 0) for c in p) + ")" if p else ""


def teil_kurz(r: dict[str, Any]) -> dict[str, Any]:
    """Kurzfassung eines gerechneten Falls für STATICS (``festkoerper.teile[i]``)."""
    if r.get("stand") != "done":
        return {"teil": r.get("teil"), "stand": r.get("stand") or "failed", "meldung": r.get("meldung")}
    sf = r.get("sicherheit")
    ziel = float(r.get("ziel") or 2.0)
    a = ziel / sf if sf else math.inf
    alt = r.get("ausrichtungen") or {}
    beste = max(alt, key=lambda k: alt[k]) if alt else None
    s0 = (r.get("s0") or {}).get("sicherheit")
    netz = r.get("netz") or {}
    out = {"teil": r["teil"], "stand": "done", "ampel": ampel_a(a), "sicherheit": sf, "ziel": ziel,
           "ausnutzung": round(a, 4) if math.isfinite(a) else None, "spannung_max": r.get("spannung_max"),
           "kriterium": r.get("kriterium"), "ort": r.get("ort"), "sicherheit_lagerrand": r.get("sicherheit_lagerrand"),
           "verformung_max_mm": r.get("verformung_max_mm"), "kragtraeger": s0,
           "druckteil": r.get("q") is not None, "q": r.get("q"), "ausrichtungen": alt,
           "ausrichtung_beste": beste if beste and sf and alt[beste] >= BESSER * sf else None,
           "netz": {k: netz.get(k) for k in ("tetraeder", "freiheitsgrade", "h_mm", "fein")},
           "ms": (r.get("ms") or {}).get("teil"), "feld": r.get("schluessel"), "aus_speicher": r.get("aus_speicher"),
           "lager": r.get("lager"), "lagerflaeche_mm2": r.get("lagerflaeche_mm2"), "kraft_n": r.get("kraft_n"),
           "loeser": r.get("loeser"), "hinweise": r.get("hinweise") or []}
    out["text"] = text(out)
    return out


def text(t: dict[str, Any]) -> str:
    amp = t["ampel"]
    wort = "hält nicht" if amp == "rot" else ("hält knapp" if amp == "gelb" else "hält")
    quer = ""
    if t.get("kriterium") == "schicht":
        quer = f", Schichtfuge maßgebend (nur {z((t.get('q') or 0) * 100, 0)} % der Festigkeit quer zur Schicht)"
    elif t.get("kriterium") == "quer_unbekannt":
        quer = f", Drucklage unbekannt: überall mit {z((t.get('q') or 0) * 100, 0)} % gerechnet"
    s0 = f"; Kragträger S0: {_sf(t['kragtraeger'])}" if t.get("kragtraeger") is not None else ""
    return (f"{t['teil']} {wort} (Festkörper-FEM): Sicherheit {_sf(t.get('sicherheit'))} (Ziel {z(t['ziel'], 0)}"
            f"{', Druckteil' if t.get('druckteil') else ''}), {z(t.get('spannung_max'), 1)} N/mm² von Mises, "
            f"größte Ausnutzung bei {_ort(t.get('ort'))}{quer}{s0}.")


def loesung(t: dict[str, Any]) -> str:
    teile = []
    sf, ziel = t.get("sicherheit") or 0.0, t.get("ziel") or 2.0
    beste = t.get("ausrichtung_beste")
    if beste:
        s_b = t["ausrichtungen"][beste]
        teile.append(f"drehen: mit lager.druckteil(…, ausrichtung=\"{beste}\") Sicherheit {_sf(s_b)} statt {_sf(sf)} "
                     "(FEM, gleiche Last)")
    if sf and sf < ziel and not (beste and t["ausrichtungen"][beste] >= ziel):
        h = math.sqrt(ziel / sf) - 1
        teile.append(f"{'oder ' if teile else ''}verstärken: bei {_ort(t.get('ort'))} in Lastrichtung um etwa "
                     f"{z(h * 100, 0)} % höher machen")
    s = "; ".join(teile)
    return s[:1].upper() + s[1:] if s else ""


def urteil_fuer(t: dict[str, Any]) -> dict[str, Any] | None:
    if t.get("stand") != "done":
        if t.get("stand") == "failed":
            return urteil("festkoerper", t.get("teil"), "grau", f"{t.get('teil')}: Festkörper nicht gerechnet "
                                                                f"({t.get('meldung') or '?'})")
        return None
    quer = t.get("kriterium") == "schicht"
    if t.get("verfahren") == "ccx":  # Stufe 4 (CalculiX): eigene Lösungstexte (Klemmkraft, drehen, verstärken)
        from kevcad_kernel.statik.ccx.urteil import loesung as loesung_s4

        return urteil("festkoerper", t["teil"], t["ampel"], t["text"], loesung_s4(t), sicherheit=t.get("sicherheit"),
                      ziel=t.get("ziel"), ausnutzung=t.get("ausnutzung"), ort=t.get("ort"),
                      schichtfaktor=t.get("q") if quer else None, quer_zur_schicht=quer or None)
    return urteil("festkoerper", t["teil"], t["ampel"], t["text"], loesung(t), sicherheit=t.get("sicherheit"),
                  ziel=t.get("ziel"), ausnutzung=t.get("ausnutzung"), ort=t.get("ort"),
                  schichtfaktor=t.get("q") if quer else None, quer_zur_schicht=quer or None)


def einbauen(e: dict[str, Any], fk: dict[str, Any]) -> dict[str, Any]:
    """Festkörper in ein Szenario einbauen: ``fk`` = {stand, fortschritt, text, meldung, teile}. Gerechnete Teile
    ersetzen den Kragträger-Nachweis (Urteil ``bauteil``) und ihre Ausnutzung in ``teile``."""
    e = dict(e)
    e["festkoerper"] = fk
    fertig = {t["teil"]: t for t in fk.get("teile") or [] if t.get("stand") in ("done", "failed")}
    if not fertig:
        return e
    done = {n for n, t in fertig.items() if t.get("stand") == "done"}
    ur = [u for u in e.get("urteile") or [] if not (u.get("art") == "bauteil" and u.get("teil") in done)
          and not (u.get("art") == "festkoerper" and u.get("teil") in fertig)]
    for n, t in fertig.items():
        u = urteil_fuer(t)
        if u is None:
            continue
        if u["ampel"] != "gruen" or u.get("quer_zur_schicht"):
            ur.append(u)
    e["urteile"] = ur
    teile = {t["name"]: dict(t) for t in e.get("teile") or []}
    for n in done:
        t = fertig[n]
        teile[n] = {"name": n, "ausnutzung": t.get("ausnutzung") or 0.0, "ampel": t["ampel"],
                    "verformung_mm": t.get("verformung_max_mm"), "sicherheit": t.get("sicherheit"), "fem": True}
    e["teile"] = sorted(teile.values(), key=lambda t: -(t.get("ausnutzung") or 0.0))
    kz = dict(e.get("kennzahlen") or {})
    sicher = [t.get("sicherheit") for t in e["teile"] if t.get("sicherheit") is not None]
    if sicher:
        kz["sicherheit"] = round(min(sicher), 3)
    e["kennzahlen"] = kz
    e["ampel"] = schlechteste([u["ampel"] for u in ur] + ([e["ablauf"]["ampel"]] if isinstance(e.get("ablauf"), dict)
                                                         and e["ablauf"].get("ampel") else []) + ["gruen"])
    from kevcad_kernel.statik.bewertung import kurztext

    e["text"] = kurztext(e)
    return e

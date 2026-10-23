"""Texte der Statik für MCP (``statik``, ``szenario_rechnen``) und das Laufergebnis: deutsch, knapp, Zahlen mit Komma."""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.statik.bewertung import _sf, z

AMPEL = {"gruen": "grün", "gelb": "gelb", "rot": "rot", "grau": "nicht gerechnet"}


def _kennzahlen(kz: dict[str, Any]) -> str:
    teile = []
    if kz.get("sicherheit") is not None:
        teile.append(f"Sicherheit {_sf(kz['sicherheit'])}")
    if kz.get("knicken") is not None:
        teile.append(f"Knicken bei {_sf(kz['knicken'])}-facher Last")
    if kz.get("durchbiegung_mm") is not None:
        teile.append(f"Durchbiegung {z(kz['durchbiegung_mm'], 1)} mm (zulässig {z(kz.get('durchbiegung_grenze_mm'), 1)})")
    if kz.get("verformung_max_mm"):
        teile.append(f"größte Verschiebung {z(kz['verformung_max_mm'], 1)} mm")
    if kz.get("kippreserve") is not None:
        teile.append(f"Kippreserve {z(kz['kippreserve'], 2)}")
    if kz.get("rutschreserve") is not None:
        teile.append(f"Rutschreserve {z(kz['rutschreserve'], 2)}")
    return ", ".join(teile)


def szenario_text(e: dict[str, Any], detail: bool = False) -> str:
    zeilen = [f"{e.get('name')}: {AMPEL.get(e.get('ampel'), e.get('ampel'))}"
              + (f" (Ziel {z(e.get('ziel'), 0)})" if e.get("ziel") else "")]
    kz = _kennzahlen(e.get("kennzahlen") or {})
    if kz:
        zeilen.append("  " + kz)
    for u in e.get("urteile") or []:
        if u.get("ampel") == "gruen" and u.get("art") != "ueberdimensioniert":
            continue
        zeilen.append(f"  - [{AMPEL.get(u['ampel'], u['ampel'])}] {u['text']}")
        if u.get("loesung"):
            zeilen.append(f"    Lösung: {u['loesung']}")
    ab = e.get("ablauf")
    if isinstance(ab, dict) and ab.get("stand") != "done":
        zeilen.append("  " + ablauf_text(ab))
    fk = e.get("festkoerper")
    if isinstance(fk, dict):
        zeilen += ["  " + z_ for z_ in festkoerper_zeilen(fk, detail=detail)]
    elif isinstance(ab, dict) and detail:
        zeilen += ablauf_text(ab, urteile=False).split("\n")[1:]
    if detail:
        for k in e.get("kippen") or []:
            jr = k.get("je_richtung") or {}
            if jr:
                zeilen.append("  Kippen je Richtung (Neigung bzw. Beschleunigung, bei der es kippt): "
                              + ", ".join(f"{r} {z(v['kippwinkel'], 1)}° / {z(v['a_kipp'], 1)} m/s²"
                                          for r, v in jr.items()))
        for s in e.get("stabwerte") or []:
            zeilen.append(f"  Stab {s['name']} ({s.get('profil')}): Sicherheit {_sf(s.get('sicherheit'))}, "
                          f"{z(s.get('spannung_max'), 0)} N/mm² bei {z(s.get('ort_mm'), 0)} mm, Durchbiegung "
                          f"{z(s.get('durchbiegung_mm'), 1)} mm von {z(s.get('durchbiegung_grenze_mm'), 1)}"
                          + (f", knickt bei {_sf(s['knicken'])}-facher Last" if s.get("knicken") else ""))
        for a in e.get("auflager") or []:
            f = a.get("kraft") or [0, 0, 0]
            zeilen.append(f"  Lager {a.get('teil')} an {a.get('stab')}: Kraft ({'; '.join(z(c, 1) for c in f)}) N")
        zeilen += verbinder_zeilen(e.get("verbinder") or [])
        zeilen += lasten_zeilen(e.get("lasten") or [])
    return "\n".join(zeilen)


def _vek(v: Any, n: int = 1) -> str:
    return "(" + "; ".join(z(c, n) for c in v) + ")"


def _kurz(name: str) -> str:
    return str(name).rsplit("/", 1)[-1]


def _betrag(v: Any) -> float:
    return math.sqrt(sum(float(c) ** 2 for c in v or (0, 0, 0)))


def verbinder_zeilen(verbinder: list[dict[str, Any]]) -> list[str]:
    """Kräfte der Stäbe auf Verbinder (S1, je Anschluss, statisch unbestimmt verteilt, T31): eine Zeile je Verbinder."""
    je: dict[str, list[dict[str, Any]]] = {}
    for v in verbinder:
        je.setdefault(v["teil"], []).append(v)
    out = []
    for teil, vs in je.items():
        if max(_betrag(v.get("kraft")) for v in vs) < 0.5:
            continue
        out.append(f"  Verbinder {teil}: "
                   + ", ".join(f"{_kurz(v['stab'])} {z(_betrag(v['kraft']), 1)} N {_vek(v['kraft'])}" for v in vs)
                   + " (Kräfte der Stäbe aus dem Stabwerk)")
    return out


def lasten_zeilen(lasten: list[dict[str, Any]]) -> list[str]:
    """Lasten des Szenarios; Kraftpaare mit Gegenseite (innere Kraft, T32)."""
    out = []
    for l in lasten:
        teile = ", ".join(_kurz(t) for t in l.get("teile") or [])
        if l.get("paar"):
            gegen = ", ".join(_kurz(t) for t in l.get("gegen") or [])
            out.append(f"  Kraftpaar: {_vek(l['kraft'])} N auf {teile}, Gegenkraft auf {gegen}, bei "
                       f"{_vek(l['punkt'], 0)} (innere Kraft: zählt nicht beim Kippen, Rutschen und Abheben)")
        else:
            out.append(f"  Last: {_vek(l['kraft'])} N auf {teile} bei {_vek(l['punkt'], 0)}")
    return out


def statik_text(res: dict[str, Any]) -> str:
    """Text für MCP ``statik`` (alle Szenarien oder eines)."""
    zeilen = []
    if res.get("szenario"):
        zeilen.append(szenario_text(res["szenario"], detail=True))
    else:
        szen = res.get("szenarien") or []
        zeilen.append(f"Statik von Lauf {res.get('run')}: {len(szen)} Szenarien"
                      + (f" ({z(res.get('ms'), 0)} ms)" if res.get("ms") is not None else ""))
        for e in szen:
            zeilen.append(szenario_text(e))
    for u in res.get("ueberdimensioniert") or []:
        if not res.get("szenario"):
            zeilen.append(f"Überdimensioniert: {u['text']}" + (f" {u['loesung']}" if u.get("loesung") else ""))
    if res.get("vereinfachungen"):
        zeilen.append("Annahmen: " + "; ".join(res["vereinfachungen"][:8]))
    if res.get("grenzen"):
        zeilen.append("Grenzen: " + " ".join(res["grenzen"]))
    return "\n".join(zeilen)


def lauf_zeile(kurz: dict[str, Any] | None) -> str | None:
    """Eine Zeile für das Laufergebnis: „Statik: Eigengewicht grün · Aufstützen 30 kg rot (Sicherheit 0,2)“."""
    if not kurz or not kurz.get("szenarien"):
        return None
    teile = []
    for e in kurz["szenarien"]:
        kz = e.get("kennzahlen") or {}
        extra = f" (Sicherheit {_sf(kz['sicherheit'])})" if e.get("ampel") in ("rot", "gelb") and \
            kz.get("sicherheit") is not None else ""
        teile.append(f"{e.get('name')} {AMPEL.get(e.get('ampel'), e.get('ampel'))}{extra}")
    return "Statik: " + " · ".join(teile)


def ablauf_text(ab: dict[str, Any], urteile: bool = True) -> str:
    """Text für MCP ``dynamik``: Urteil, Antrieb, Kippen mit Handrechnung, Ladung, Rutschen, Kräfte, Rechenzeit."""
    if not ab:
        return ""
    if ab.get("stand") == "laeuft":
        return "Ablauf wird gerechnet (eigener Prozess)."
    if ab.get("stand") != "done":
        return f"Ablauf nicht gerechnet: {ab.get('meldung') or '?'}"
    kz = ab.get("kennzahlen") or {}
    an = ab.get("antrieb") or {}
    z_ = [ab.get("text") or ""]
    for u in (ab.get("urteile") or []) if urteile else []:
        z_.append(f"  - [{AMPEL.get(u['ampel'], u['ampel'])}] {u['text']}")
        if u.get("loesung") and u["ampel"] != "gruen":
            z_.append(f"    Lösung: {u['loesung']}")
    z_.append(f"  Antrieb: {an.get('koerper')}, {z(an.get('geschwindigkeit'), 2)} m/s, bremsen {an.get('bremsen')} "
              f"({z(an.get('verzoegerung'), 1)} m/s²), Führung am "
              f"{'Boden' if an.get('angriff') in (None, 'boden') else an.get('angriff')}")
    kipp = [f"größter Kippwinkel {z(kz.get('kippwinkel_max'), 2)}°", f"Abheben {z(kz.get('abheben_max_mm'), 1)} mm"]
    if kz.get("a_abheben") is not None:
        kipp.append(f"hebt ab {z(kz['a_abheben'], 2)} m/s² ab (Kippreserve {z(kz.get('kippreserve'), 2)})")
    if kz.get("v_abheben") is not None:
        animiert = str(an.get("bremsen") or "").startswith("wie die Animation")
        kipp.append(f"bei dieser Fahrt ab {z(kz['v_abheben'], 2)} m/s Höchstgeschwindigkeit" if animiert
                    else f"bei dieser Bremsart ab {z(kz['v_abheben'], 2)} m/s")
    z_.append("  Kippen: " + ", ".join(kipp))
    h = ab.get("handrechnung") or {}
    if h and kz.get("a_abheben_ohne_ladung") is not None:
        ohne = kz.get("a_abheben_ohne_ladung")
        abw = (f", Abweichung {z(100 * (ohne - h['a_kipp']) / h['a_kipp'], 1)} %" if ohne and h.get("a_kipp")
               else "")
        z_.append(f"  Plausibilität: Handrechnung {h.get('text')}; Simulation ohne Ladung hebt ab "
                  f"{z(ohne, 2)} m/s² ab{abw}")
    for L in kz.get("ladung") or []:
        grenze = (f", springt ab {z(L['v_grenze'], 2)} m/s heraus" if L.get("v_grenze") is not None else
                  (f", bleibt bis mindestens {z(L.get('v_grenze_bis'), 1)} m/s" if L.get("v_grenze_nie") else ""))
        z_.append(f"  {L['name']}: {'bleibt' if L.get('bleibt') else 'springt heraus'}, Versatz "
                  f"{z(L.get('versatz_max_mm'), 0)} mm, hebt {z(L.get('hebt_max_mm'), 0)} mm{grenze}")
    if kz.get("rutschgrenze") is not None:
        z_.append(f"  Rutschgrenze (blockierte Räder): {z(kz['rutschgrenze'], 1)} m/s² (μ = {z(kz.get('mu_rad'), 2)}), "
                  f"Rutschreserve {z(kz.get('rutschreserve'), 2)}"
                  + (f", Rutschweg {z(kz['rutschweg_mm'], 0)} mm über den Bremsweg von "
                     f"{z(kz.get('bremsweg_mm'), 0)} mm hinaus" if kz.get("rutschweg_mm") else ""))
    if kz.get("kontaktkraefte"):
        z_.append("  Größte Kontaktkräfte: " + "; ".join(f"{k['paar'][0]} ↔ {k['paar'][1]} {z(k['max_n'], 0)} N"
                                                        for k in kz["kontaktkraefte"][:5]))
    ms = ab.get("ms") or {}
    if ms:
        schritte = (f", {ms['schritte']} Schritte à {z(ms.get('zeitschritt_ms'), 1)} ms" if ms.get("schritte")
                    else "")
        z_.append(f"  Rechenzeit: Ablauf {z(ms.get('ablauf'), 0)} ms ({z(ab.get('dauer'), 2)} s simuliert{schritte})"
                  + (f", Suche {ms.get('varianten')} Varianten in {z(ms.get('suche'), 0)} ms" if ms.get("varianten")
                     else ""))
    if ab.get("animation"):
        z_.append(f"  Zeitleiste: Animation „{ab['animation']}“ ({ab.get('bilder')} Bilder, {z(ab.get('fps'), 0)} fps)")
    return "\n".join(z_)


def _ort(p: Any) -> str:
    return "(" + "; ".join(z(c, 0) for c in p) + ")" if p else "?"


def festkoerper_zeilen(fk: dict[str, Any], detail: bool = False) -> list[str]:
    """Festkörper (S3) eines Szenarios: Stand, je Teil Sicherheit, Kriterium, Ort, Drucklagen, Netz und Zeit."""
    st = fk.get("stand")
    if st == "laeuft":
        return [f"Festkörper (FEM) läuft: {z(100 * float(fk.get('fortschritt') or 0), 0)} % – {fk.get('text') or ''}"]
    if st == "abgebrochen":
        return ["Festkörper (FEM) abgebrochen."]
    if st == "failed":
        return [f"Festkörper (FEM) nicht gerechnet: {fk.get('meldung') or '?'}"]
    out = []
    for t in fk.get("teile") or []:
        if t.get("stand") != "done":
            out.append(f"Festkörper {t.get('teil')}: nicht gerechnet ({t.get('meldung') or '?'})")
            continue
        out.append(f"Festkörper [{AMPEL.get(t['ampel'], t['ampel'])}] {t.get('text')}")
        if detail:
            alt = t.get("ausrichtungen") or {}
            if alt:
                out.append("  Sicherheit je Drucklage (ausrichtung): " + ", ".join(
                    f"{k} {_sf(v)}" for k, v in sorted(alt.items(), key=lambda kv: -kv[1])))
            n = t.get("netz") or {}
            lr = t.get("sicherheit_lagerrand")
            out.append(f"  Verschiebung höchstens {z(t.get('verformung_max_mm'), 2)} mm; Netz {n.get('tetraeder')} "
                       f"Tetraeder ({'C3D10' if t.get('verfahren') == 'ccx' else 'P2'}, {n.get('freiheitsgrade')} "
                       f"Freiheitsgrade, h {z(n.get('h_mm'), 1)} mm"
                       f"{', fein' if n.get('fein') else ''}); {z(t.get('ms'), 0)} ms"
                       + (" (Zwischenspeicher)" if t.get("aus_speicher") else "")
                       + (f"; am Rand der Einspannung rechnerisch {_sf(lr)} (Spitze der starren Einspannung, nicht "
                          "gewertet)" if lr is not None and t.get("sicherheit") and lr < 0.9 * t["sicherheit"]
                          else ""))
    return out


def festkoerper_text(res: dict[str, Any]) -> str:
    """Text für MCP ``festigkeit``."""
    zeilen = []
    for t in res.get("teile") or []:
        if t.get("stand") != "done":
            zeilen.append(f"{t.get('teil')}: nicht gerechnet ({t.get('meldung') or '?'})")
            continue
        sz = next((f.get("szenario") for f in res.get("faelle") or [] if f.get("teil") == t.get("teil")
                   and f.get("schluessel") == t.get("feld")), None)
        zeilen.append(f"[{AMPEL.get(t['ampel'], t['ampel'])}]" + (f" {sz}:" if sz else "") + f" {t.get('text')}")
        from kevcad_kernel.statik.festkoerper.urteil import loesung

        if t.get("verfahren") == "ccx":  # Stufe 4: Lösung und Zusatzzeilen (Kontakt, Werkstoff, Traglast)
            from kevcad_kernel.statik.ccx.urteil import loesung as loesung_s4, zeilen as zeilen_s4

            l = loesung_s4(t)
            zusatz = zeilen_s4(t)
        else:
            l = loesung(t)
            zusatz = []
        if l and t.get("ampel") != "gruen":
            zeilen.append(f"  Lösung: {l}")
        zeilen += ["  " + x for x in zusatz]
        zeilen += ["  " + x for x in festkoerper_zeilen({"stand": "done", "teile": [t]}, detail=True)[1:]]
    for h in res.get("hinweise") or []:
        zeilen.append(f"Hinweis: {h}")
    ms = res.get("ms") or {}
    wer = "CalculiX-Prozess" if res.get("verfahren") == "ccx" else "FEM-Prozess"
    zeilen.append(f"(gesamt {z(ms.get('gesamt'), 0)} ms, {wer} {z(ms.get('prozess'), 0)} ms"
                  + (", im Viewer gezeigt: Farbverlauf der Ausnutzung und überhöhte Verformung)" if res.get("gezeigt")
                     else ")"))
    if res.get("grenzen"):
        zeilen.append("Grenzen: " + " ".join(res["grenzen"]))
    return "\n".join(zeilen)

"""Texte der Statik für MCP (``statik``, ``szenario_rechnen``) und das Laufergebnis: deutsch, knapp, Zahlen mit Komma."""

from __future__ import annotations

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
    return "\n".join(zeilen)


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

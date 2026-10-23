"""Urteile der Stufe 4 (Laufzeit): Kurzfassung je Teil für STATICS, Text, Ampel.

Ein Fall der Stufe 4 ersetzt im Szenario das Ergebnis der Stufe 3 desselben Teils (Urteil ``festkoerper``, gleiche
Ampel-Rechnung T9). Die Sicherheit ist der **Traglastfaktor**, wenn er gerechnet ist (Last bis zur Grenzdehnung, zum
Bruch der Schichtfuge, zum Rutschen oder Kollaps), sonst die Sicherheit unter Last aus den elastisch-plastischen
Spannungen mit Kontakt; ein Beulfaktor darunter zählt. Zusätzlich:

- fließt das Teil schon unter der Last bleibend (plastische Dehnung über 0,2 %), ist es mindestens gelb; erreicht es
  unter der Last die Grenzdehnung, rot;
- rutscht ein Kontaktpartner schon unter der Last (die Halte-Federn tragen), ist es rot: Die Klemmung hält nicht.
"""

from __future__ import annotations

import math
from typing import Any

from kevcad_kernel.statik.bewertung import _sf, ampel_a, schlechteste, z

PLAST_GELB = 0.002  # 0,2 % bleibende Dehnung


def _ort(p: Any) -> str:
    return "(" + "; ".join(z(c, 0) for c in p) + ")" if p else ""


def teil_kurz(r: dict[str, Any]) -> dict[str, Any]:
    """Kurzfassung wie ``festkoerper.urteil.teil_kurz`` plus Kontakt, Plastizität, Traglast, Beulen."""
    from kevcad_kernel.statik.festkoerper.urteil import teil_kurz as kurz_s3

    out = kurz_s3(r)
    if r.get("stand") != "done":
        return out
    out["verfahren"] = "ccx"
    out["sicherheit_last"] = r.get("sicherheit_last")
    k = r.get("kontakt") or {}
    if k:
        out["kontakt"] = {"paare": [{x: p.get(x) for x in ("mit", "rolle", "reibwert", "druck_max", "kraft_n",
                                                          "traegt_mm2", "anteil_traegt", "klaffen_max_mm",
                                                          "schlupf_max_mm", "reibung_ausnutzung", "gleitet_anteil",
                                                          "quelle")} for p in k.get("paare") or []],
                          "klemmungen": [{x: c.get(x) for x in ("schraube", "kraft_n", "quelle")}
                                         for c in k.get("klemmungen") or []]}
    if r.get("plastisch"):
        out["plastisch"] = {x: r["plastisch"].get(x) for x in ("dehnung_max", "bleibend_mm", "fliesst", "grenzdehnung",
                                                              "fliessgrenze", "modell", "ort")}
    if r.get("traglast"):
        t = r["traglast"]
        out["traglast"] = {x: t.get(x) for x in ("faktor", "kriterium", "text", "lastfaktor_max", "erreicht")}
    if r.get("beulen"):
        out["beulen"] = {"faktor": r["beulen"].get("faktor")}
    out["rutscht"] = bool(r.get("rutscht"))
    out["zusatz_max"] = r.get("zusatz_max")
    ampeln = [out["ampel"]]
    pl = out.get("plastisch") or {}
    if pl.get("dehnung_max") is not None:
        if pl["dehnung_max"] >= float(pl.get("grenzdehnung") or 0.05):
            ampeln.append("rot")
        elif pl["dehnung_max"] > PLAST_GELB:
            ampeln.append("gelb")
    if out["rutscht"]:
        ampeln.append("rot")
    out["ampel"] = schlechteste(ampeln)
    out["text"] = text(out)
    return out


def text(t: dict[str, Any]) -> str:
    amp = t["ampel"]
    wort = "hält nicht" if amp == "rot" else ("hält knapp" if amp == "gelb" else "hält")
    teile = [f"{t['teil']} {wort} (CalculiX, S4):"]
    tr = t.get("traglast") or {}
    if tr.get("faktor") is not None:
        if tr.get("kriterium") == "nicht_erreicht":
            teile.append(f"Traglast über dem {z(tr.get('lastfaktor_max'), 1)}-Fachen der Last")
        else:
            teile.append(f"Traglast beim {z(tr['faktor'], 2)}-Fachen der Last ({tr.get('text')})")
    sl = t.get("sicherheit_last")
    if sl is not None:
        teile.append(f"unter Last Sicherheit {_sf(sl)} ({z(t.get('spannung_max'), 1)} N/mm² von Mises)")
    teile.append(f"Ziel {z(t['ziel'], 0)}{', Druckteil' if t.get('druckteil') else ''}")
    if t.get("kriterium") == "schicht":
        teile.append("Schichtfuge maßgebend")
    pl = t.get("plastisch") or {}
    if pl.get("fliesst"):
        teile.append(f"fließt: plastische Dehnung {z(100 * pl['dehnung_max'], 2)} %, bleibend "
                     f"{z(pl.get('bleibend_mm'), 3)} mm")
    elif pl:
        teile.append("bleibt elastisch")
    for p in (t.get("kontakt") or {}).get("paare") or []:
        s = (f"Kontakt mit {p['mit'].rsplit('/', 1)[-1]}: Druck bis {z(p.get('druck_max'), 1)} N/mm², trägt auf "
             f"{z(100 * (p.get('anteil_traegt') or 0), 0)} % der Fläche")
        if (p.get("klaffen_max_mm") or 0) > 0.001:
            s += f", klafft bis {z(p['klaffen_max_mm'], 3)} mm"
        if (p.get("schlupf_max_mm") or 0) > 0.001:
            s += f", gleitet bis {z(p['schlupf_max_mm'], 3)} mm"
        teile.append(s)
    if t.get("rutscht"):
        teile.append("ein Kontaktpartner rutscht schon unter der Last")
    b = (t.get("beulen") or {}).get("faktor")
    if b is not None:
        teile.append(f"Beulen beim {z(b, 1)}-Fachen")
    return teile[0] + " " + "; ".join(teile[1:]) + "."


def loesung(t: dict[str, Any]) -> str:
    from kevcad_kernel.statik.festkoerper.urteil import loesung as l_s3

    out = []
    if t.get("rutscht") or (t.get("traglast") or {}).get("kriterium") == "rutschen":
        out.append("Klemmkraft erhöhen (größere Schraube, fester anziehen) oder Formschluss vorsehen")
    s = l_s3(t)
    if s:
        out.append(s)
    return "; ".join(out)


def zeilen(t: dict[str, Any]) -> list[str]:
    """Zusatzzeilen für den Bericht (MCP ``festigkeit``)."""
    out = []
    for c in (t.get("kontakt") or {}).get("klemmungen") or []:
        out.append(f"Klemmkraft {z(c.get('kraft_n'), 0)} N ({c.get('schraube') or 'Schraube'}, {c.get('quelle')})")
    for p in (t.get("kontakt") or {}).get("paare") or []:
        out.append(f"Kontakt {p['mit']} (μ {z(p.get('reibwert'), 2)}, {p.get('quelle')}): Kraft "
                   f"{z(p.get('kraft_n'), 1)} N, Druck bis {z(p.get('druck_max'), 2)} N/mm², trägt "
                   f"{z(p.get('traegt_mm2'), 0)} mm², Reibung zu {z(100 * (p.get('reibung_ausnutzung') or 0), 0)} % "
                   f"genutzt, gleitet auf {z(100 * (p.get('gleitet_anteil') or 0), 0)} % der tragenden Fläche")
    pl = t.get("plastisch") or {}
    if pl:
        out.append(f"Werkstoff: {pl.get('modell')}; Grenzdehnung {z(100 * (pl.get('grenzdehnung') or 0), 1)} %")
    tr = t.get("traglast") or {}
    if tr:
        out.append(f"Traglast: {tr.get('text')} beim {z(tr.get('faktor'), 3)}-Fachen (gerechnet bis "
                   f"{z(tr.get('erreicht'), 2)}, höchstens {z(tr.get('lastfaktor_max'), 1)})")
    return out


def ampel_von(t: dict[str, Any]) -> str:
    sf = t.get("sicherheit")
    a = (float(t.get("ziel") or 2.0) / sf) if sf else math.inf
    return ampel_a(a)

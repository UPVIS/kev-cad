"""„Grenze suchen“ im Bereich Simulation: wie viel Last, wie steil (Rechenprozess, mit dem Modell des letzten Laufs).

Gesucht wird je Kriterium der Wert, bei dem das Szenario gerade noch hält, mit S0 und S1 (Millisekunden je Rechnung,
Halbierung des Intervalls):

- ``last``: Faktor λ auf alle Einzellasten des Lastfalls (Eigengewicht bleibt). Festigkeit: größte Ausnutzung der
  Teile und Stäbe (Ziel / Sicherheit) erreicht 1, also das Ziel; „bricht“: Sicherheit 1 (Ausnutzung = Ziel). Kippen und
  Rutschen: Reserve 1.
- ``neigung``: größte Neigung des Bodens in der Richtung des Lastfalls (sonst +X), bei der nichts kippt, rutscht oder
  das Ziel verfehlt.

„Wie schnell“ (Geschwindigkeit) sucht der Ablauf (S2) selbst mit Rollouts; das macht die Laufzeit
(``simulation/laufzeit.py``). Die Festkörper-FEM (S3) rechnet hier nicht mit (zu langsam für eine Suche); ein Hinweis
steht dabei.
"""

from __future__ import annotations

import copy
import math
import time
from typing import Any, Callable

import numpy as np

LAMBDA_MAX = 1000.0
NEIGUNG_MAX = 60.0
SCHRITTE = 14


def _bewerten(st: Any, sz: Any) -> dict[str, float]:
    """Kennwerte eines Szenarios: größte Ausnutzung, kleinste Sicherheit / Ziel, Kipp- und Rutschreserve."""
    from kevcad_kernel.statik.rechnen import rechne_alles

    erg = rechne_alles(st.modell, [sz], st.katalog, st.koerper, alternativen=False, aktiv=sz.name)
    e = next((x for x in erg.get("szenarien") or [] if x.get("name") == sz.name), {})
    a = max([float(t.get("ausnutzung") or 0.0) for t in e.get("teile") or []] + [0.0])
    s0 = e.get("s0") or {}
    kipp = [float(k["reserve"]) for k in s0.get("kippen") or [] if k.get("reserve") is not None]
    rutsch = [float(r["reserve"]) for r in s0.get("rutschen") or [] if r.get("reserve") is not None]
    massgebend = (e.get("teile") or [{}])[0].get("name") if e.get("teile") else None
    return {"ausnutzung": a, "ziel": float(e.get("ziel") or sz.ziel_fuer(False)),
            "kippen": min(kipp) if kipp else math.inf, "rutschen": min(rutsch) if rutsch else math.inf,
            "massgebend": massgebend}


def _halbieren(ok: Callable[[float], bool], lo: float, hi: float, schritte: int = SCHRITTE) -> float | None:
    """Größtes x in [lo, hi] mit ok(x) (ok monoton fallend); None, wenn schon lo nicht ok ist; hi, wenn hi ok ist."""
    if not ok(lo):
        return None
    # erst einklammern (verdoppeln ab 1), dann halbieren: genau auch bei großen Grenzen
    b = min(max(lo * 2, 1.0), hi)
    while b < hi and ok(b):
        lo, b = b, min(b * 2, hi)
    if b >= hi and ok(hi):
        return hi
    hi = b
    for _ in range(schritte):
        mitte = (lo + hi) / 2
        if ok(mitte):
            lo = mitte
        else:
            hi = mitte
    return lo


def suche(st: Any, lastfall: str, art: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    if st.modell is None:
        raise ValueError("Noch kein Statikmodell: erst model.py laufen lassen.")
    sz0 = next((s for s in st.szenarien if s.name == lastfall), None)
    if sz0 is None:
        raise ValueError(f"Lastfall {lastfall!r} gibt es im letzten Lauf nicht")
    zaehler = {"n": 0}
    cache: dict[float, dict[str, float]] = {}

    def werte(x: float, mach: Callable[[Any, float], None]) -> dict[str, float]:
        key = round(x, 9)
        if key not in cache:
            sz = copy.deepcopy(sz0)
            mach(sz, x)
            zaehler["n"] += 1
            cache[key] = _bewerten(st, sz)
        return cache[key]

    out: list[dict[str, Any]] = []
    if art == "last":
        if not sz0.lasten:
            raise ValueError(f"„{lastfall}“ hat keine Einzellast: erst eine Kraft setzen")

        def skaliere(sz: Any, lam: float) -> None:
            for l in sz.lasten:
                l.kraft = np.asarray(l.kraft, float) * lam

        basis = werte(1.0, skaliere)
        ziel = basis["ziel"]
        for krit, einheit, ok in (
                ("Ziel-Sicherheit", "×", lambda x: werte(x, skaliere)["ausnutzung"] <= 1.0),
                ("Bruch (Sicherheit 1)", "×", lambda x: werte(x, skaliere)["ausnutzung"] <= ziel),
                ("Kippen", "×", lambda x: werte(x, skaliere)["kippen"] >= 1.0),
                ("Rutschen", "×", lambda x: werte(x, skaliere)["rutschen"] >= 1.0)):
            g = _halbieren(ok, 0.0, LAMBDA_MAX)
            if g is None:
                out.append({"kriterium": krit, "grenze": 0.0, "einheit": einheit,
                            "text": f"{krit}: schon ohne Last nicht erfüllt"})
            elif g >= LAMBDA_MAX:
                continue  # dieses Kriterium begrenzt nicht
            else:
                out.append({"kriterium": krit, "grenze": round(g, 3), "einheit": einheit,
                            "massgebend": werte(g * 1.02, skaliere).get("massgebend"),
                            "text": f"{krit}: bis zum {g:.2f}-fachen der Lasten".replace(".", ",")})
        betrag = sum(float(np.linalg.norm(l.kraft)) for l in sz0.lasten)
        for w in out:
            w["last_n"] = round(betrag * float(w["grenze"]), 1)
        out.sort(key=lambda w: w["grenze"])
        text = (f"„{lastfall}“ hält bis zum {out[0]['grenze']:.2f}-fachen ({out[0]['last_n']:.0f} N statt "
                f"{betrag:.0f} N), begrenzt durch {out[0]['kriterium']}").replace(".", ",") if out else \
            f"„{lastfall}“: bis zum {LAMBDA_MAX:.0f}-fachen der Lasten nichts kritisch"
    elif art == "neigung":
        richtung = np.asarray(sz0.neigung_richtung if sz0.neigung_grad else [1.0, 0.0, 0.0], float)

        def neige(sz: Any, grad: float) -> None:
            sz.neigung_grad = float(grad)
            sz.neigung_richtung = richtung

        werte(0.0, neige)
        ziel = cache[0.0]["ziel"]
        for krit, ok in (("Kippen", lambda x: werte(x, neige)["kippen"] >= 1.0),
                         ("Rutschen", lambda x: werte(x, neige)["rutschen"] >= 1.0),
                         ("Ziel-Sicherheit", lambda x: werte(x, neige)["ausnutzung"] <= 1.0),
                         ("Bruch (Sicherheit 1)", lambda x: werte(x, neige)["ausnutzung"] <= ziel)):
            g = _halbieren(ok, 0.0, NEIGUNG_MAX)
            if g is None:
                out.append({"kriterium": krit, "grenze": 0.0, "einheit": "°",
                            "text": f"{krit}: schon auf ebenem Boden nicht erfüllt"})
            elif g < NEIGUNG_MAX:
                out.append({"kriterium": krit, "grenze": round(g, 2), "einheit": "°",
                            "text": f"{krit}: ab {g:.1f}° Neigung".replace(".", ",")})
        out.sort(key=lambda w: w["grenze"])
        r = "".join(("+" if c > 0 else "−") + "XYZ"[i] for i, c in enumerate(richtung) if abs(c) > 0.5) or "schräg"
        text = (f"„{lastfall}“ hält bis {out[0]['grenze']:.1f}° Neigung (abwärts {r}), begrenzt durch "
                f"{out[0]['kriterium']}").replace(".", ",") if out else \
            f"„{lastfall}“: bis {NEIGUNG_MAX:.0f}° Neigung nichts kritisch"
    else:
        raise ValueError(f"Grenze {art!r} unbekannt (last, neigung; Geschwindigkeit über den Ablauf)")
    return {"art": art, "lastfall": lastfall, "werte": out, "text": text, "rechnungen": zaehler["n"],
            "hinweis": "gesucht mit S0 und S1 (ohne Festkörper-FEM)",
            "ms": round((time.perf_counter() - t0) * 1000, 1)}

"""Ablauf-Prozess (S2): ``python -m kevcad_kernel.statik.dynamik.prozess <auftrag.json>``.

Läuft getrennt vom Rechenprozess von model.py und von der Laufzeit; MuJoCo und CoACD werden nur hier geladen. Auftrag
(JSON): ``szene`` (Datei aus ``szene.schreibe``), ``ausgabe`` (Ergebnis JSON), ``lagen`` (Ergebnis npz: Lagen je Bild
und Teil für die Zeitleiste), ``szenarien`` (je ``name``, ``geschwindigkeit`` m/s, ``bremsen`` m/s² | "abrupt" |
"anprall", ``stoss`` Faktor auf die Verzögerung, ``dauer`` s, ``fahrtrichtung``, ``angriff`` "boden" | Höhe mm | Punkt,
``neigung`` Grad, ``neigung_richtung``, ``bahn`` {zeiten, weg_m} aus einer Animation, ``suche`` bool), ``fps``,
``faeden`` (höchstens 4).

Ergebnis je Szenario: ``ablauf`` (Kennzahlen, Urteile, Handrechnung, Verlauf, Kontaktpfeile, Grenzen, Rechenzeiten).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from typing import Any

import numpy as np

from kevcad_kernel.statik.dynamik import GRENZEN_S2
from kevcad_kernel.statik.dynamik import ablauf as ab
from kevcad_kernel.statik.dynamik import formen as fm
from kevcad_kernel.statik.dynamik import mjcf, szene
from kevcad_kernel.statik.dynamik import urteil as ut

FPS = 50.0
PFEILE = 8


def _r(x: Any, n: int = 2) -> Any:
    if isinstance(x, np.ndarray):
        return [_r(v, n) for v in x.tolist()]
    if isinstance(x, (list, tuple)):
        return [_r(v, n) for v in x]
    if isinstance(x, (float, np.floating)):
        f = float(x)
        return round(f, n) if math.isfinite(f) else None
    return x


def coacd_stuecke(meta: dict[str, Any], felder: dict[str, np.ndarray]) -> tuple[dict[str, list[np.ndarray]], dict]:
    out: dict[str, list[np.ndarray]] = {}
    info = {"teile": len(meta.get("coacd") or []), "aus_cache": 0, "gerechnet": 0, "ms": 0.0}
    for n in meta.get("coacd") or []:
        c = meta["kollision"][n]
        try:
            st, i = fm.coacd_zerlegen(felder.get(f"n:{n}", np.zeros((0, 3))), felder.get(f"t:{n}", np.zeros((0, 3))),
                                      c["form"])
        except Exception as exc:  # noqa: BLE001 - dann eben die Hülle
            info.setdefault("fehler", []).append(f"{n}: {type(exc).__name__}: {exc}")
            continue
        out[n] = st
        info["aus_cache" if i["aus_cache"] else "gerechnet"] += 1
        info["ms"] += i["ms"]
    return out, info


def _mu_rad(meta: dict[str, Any], tb: set[str]) -> float | None:
    """Reibwert der Räder (bzw. Füße) des geschobenen Teilbaums gegen den Boden (kleinster)."""
    K = {k["id"]: k for k in meta["koerper"]}
    werte = []
    for n, mu in zip(meta["boden_paare"], meta["boden_mu"]):
        kid = meta["kollision"][n]["koerper"]
        if kid in tb and n in K[kid]["boden"]:
            werte.append(mu)
    return min(werte) if werte else None


def rechne_szenario(meta: dict[str, Any], formen: dict[str, Any], sz: dict[str, Any], fps: float = FPS
                    ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Ein Szenario: Ablauf mit Aufzeichnung, Suche nach den Grenzen, Urteile. Liefert (ablauf, Felder für die
    Zeitleiste)."""
    t0 = time.perf_counter()
    richtung = np.asarray(sz.get("fahrtrichtung") or (1.0, 0.0, 0.0), float)
    angriff = sz.get("angriff") or "boden"
    neigung = float(sz.get("neigung") or 0.0)
    nr = sz.get("neigung_richtung") or richtung
    mo = ab.baue_modell(meta, formen, richtung=richtung, angriff=angriff, neigung=neigung, neigung_richtung=nr)
    v = float(sz.get("geschwindigkeit") or 0.0)
    stoss = float(sz.get("stoss") or 1.0)
    a, btext = ab.bremszeit(sz.get("bremsen"), v)
    a *= stoss
    if sz.get("bahn"):
        bahn = sz["bahn"]
        pr = ab.profil_aus_bahn(np.asarray(bahn["zeiten"], float), np.asarray(bahn["weg_m"], float),
                                text=f"wie die Animation {bahn.get('name', '')}".strip())
        v = float(np.max(np.abs(pr.v)))
        a = float(pr.a_brems)
    else:
        pr = ab.profil(v, a, dauer=sz.get("dauer"), text=btext)
    t_modell = (time.perf_counter() - t0) * 1000
    auf = ab.rechne(mo, pr, fps=fps)
    t_ablauf = auf.ms
    hand = ut.handrechnung(meta, mo)
    suche: dict[str, Any] = {}
    suche_info: dict[str, Any] = {}
    t1 = time.perf_counter()
    brems_arg = sz.get("bremsen")
    if sz.get("suche", True) and mo.zuordnung.get("antrieb") and sz.get("bahn") and a > 0:
        # Sollbahn aus einer Animation: dieselbe Fahrt schneller abspielen (Zeit / τ): Beschleunigungen × f, Tempo ×
        # √f. Gesucht wird f, ab dem der Aufbau abhebt bzw. die Ladung herausspringt (mit Ladung, wie animiert).
        bahn = sz["bahn"]
        zt, weg = np.asarray(bahn["zeiten"], float), np.asarray(bahn["weg_m"], float)

        def schneller(f: float) -> ab.Profil:
            return ab.profil_aus_bahn(zt / math.sqrt(f), weg)

        krit = {"kippen_f": lambda b: b.abheben_max > ab.ABHEBEN_MM}
        for kid in mo.ladung:
            krit[f"ladung_f:{kid}"] = (lambda k: (lambda b: ab.ladung_verloren(b, k)))(kid)
        erg, info = ab.grenzen(mo, schneller, krit, lo=1.0, hi=400.0)
        suche_info["animation"] = info
        for k, e in erg.items():
            f = e.get("wert")
            if k == "kippen_f":
                suche["kippen_a"] = {**e, "wert": None if f is None else f * a}
                suche["kippen_v"] = {**e, "wert": None if f is None else v * math.sqrt(f)}
            else:
                suche["ladung_v:" + k.split(":", 1)[1]] = {**e, "wert": None if f is None else v * math.sqrt(f),
                                                           "ab": v * math.sqrt(e["ab"]) if e.get("ab") else None}
    if sz.get("suche", True) and mo.zuordnung.get("antrieb") and not sz.get("bahn"):
        # 1) Verzögerung, ab der der Aufbau abhebt, bei dieser Geschwindigkeit (mit Ladung)
        if v > 0:
            erg, info = ab.grenzen(mo, lambda x: ab.profil(v, x), {"kippen_a": lambda b: b.abheben_max > ab.ABHEBEN_MM},
                                   lo=0.5, hi=60.0)
            suche.update(erg)
            suche_info["kippen_a"] = info
        # 2) Geschwindigkeit, ab der die Ladung herausspringt bzw. der Aufbau abhebt (Bremsart wie im Szenario)
        if v > 0 and brems_arg is not None:
            def erzeuge(x: float) -> ab.Profil:
                ax, _ = ab.bremszeit(brems_arg, x)
                return ab.profil(x, ax * stoss)

            krit: dict[str, Any] = {"kippen_v": lambda b: b.abheben_max > ab.ABHEBEN_MM}
            for kid in mo.ladung:
                krit[f"ladung_v:{kid}"] = (lambda k: (lambda b: ab.ladung_verloren(b, k)))(kid)
            erg, info = ab.grenzen(mo, erzeuge, krit, lo=0.1, hi=6.0)
            suche.update(erg)
            suche_info["geschwindigkeit"] = info
    if sz.get("suche", True) and mo.zuordnung.get("antrieb"):
        # 3) Plausibilität: ohne Ladung bei anhaltender Verzögerung (0,4 s) gegen die Handrechnung a = g·b/h
        if mo.zuordnung.get("antrieb"):
            mo0 = ab.baue_modell(meta, formen, richtung=richtung, angriff=angriff, neigung=neigung,
                                 neigung_richtung=nr, ohne_ladung=True)
            erg, info = ab.grenzen(mo0, lambda x: ab.profil(0.4 * x, x),
                                   {"kippen_ohne_ladung": lambda b: b.abheben_max > ab.ABHEBEN_MM}, lo=0.5, hi=60.0)
            suche.update(erg)
            suche_info["ohne_ladung"] = info
    t_suche = (time.perf_counter() - t1) * 1000
    tb = ab.teilbaum(meta, mo.zuordnung["antrieb"]) if mo.zuordnung.get("antrieb") else set()
    sz_eff = {"v": v, "a": a, "bahn": bool(sz.get("bahn"))}
    urteile, kz = ut.bewerte(sz_eff, meta, mo, auf, suche, hand, _mu_rad(meta, tb))
    ampel = ut.schlechteste([u["ampel"] for u in urteile] + ["gruen"])
    # Verlauf (je Bild) und Kontaktpfeile
    K = {k["id"]: k for k in meta["koerper"]}
    r = auf.reihen
    verlauf: dict[str, Any] = {"zeit": _r(auf.zeiten, 3), "kipp": _r(r.get("kipp", []), 3),
                               "abheben": _r(r.get("abheben", []), 2), "weg": _r(r.get("weg", []), 4),
                               "fuehrung": _r(auf.fuehrung, 1), "ladung": {}, "kraefte": {}}
    for kid in mo.ladung:
        verlauf["ladung"][K[kid]["name"]] = {"laengs": _r(r.get(f"laengs:{kid}", []), 1),
                                             "hebt": _r(r.get(f"hebt:{kid}", []), 1)}
    namen = {k["id"]: k["name"] for k in meta["koerper"]}
    namen["boden"] = "Boden"
    for key, reihe in auf.paar_kraft.items():
        if float(reihe.max()) < 1.0:
            continue
        a_, b_ = key.split("|")
        verlauf["kraefte"][f"{namen.get(a_, a_)} ↔ {namen.get(b_, b_)}"] = _r(reihe, 1)
    pfeile = [[{"punkt": _r(p["punkt"], 1), "kraft": _r(p["kraft"], 1), "paar": [namen.get(x, x) for x in p["paar"]]}
               for p in bild[:PFEILE] if float(np.linalg.norm(p["kraft"])) >= 1.0] for bild in auf.kontakte]
    # Lagen je Teil für die Zeitleiste (nur Körper, die sich bewegen)
    teile, spalten = [], []
    for i, kid in enumerate(auf.koerper):
        L = auf.lagen[:, i]
        if np.allclose(L, np.eye(4)[None], atol=1e-6):
            continue
        for n in K[kid]["teile"]:
            teile.append(n)
            spalten.append(i)
    lagen = auf.lagen[:, spalten] if spalten else np.zeros((len(auf.zeiten), 0, 4, 4))
    vereinfacht = []
    if meta.get("reibung_angenommen"):
        vereinfacht.append("Reibwert angenommen (μ = 0,3, nicht im Katalog): " + ", ".join(meta["reibung_angenommen"]))
    angenommen = [n for k in meta["koerper"] for n in k.get("masse_angenommen") or []]
    if angenommen:
        vereinfacht.append(f"Masse ohne Material angenommen (1 g/cm³): {', '.join(angenommen[:6])}"
                           + (" …" if len(angenommen) > 6 else ""))
    for h in meta.get("hinweise") or []:
        vereinfacht.append(h)
    an = mo.zuordnung.get("antrieb")
    ablauf = {
        "stand": "done", "ampel": ampel, "animation": f"Ablauf: {sz['name']}", "dauer": round(float(auf.zeiten[-1]), 4),
        "fps": ab.bild_fps(fps)[1], "bilder": int(len(auf.zeiten)),
        "antrieb": {"koerper": K[an]["name"] if an else None, "geschwindigkeit": round(v, 3),
                    "verzoegerung": round(a, 3), "bremsen": pr.text, "stoss": stoss if stoss != 1.0 else None,
                    "angriff": angriff if isinstance(angriff, str) else _r(angriff, 1),
                    "richtung": _r(mo.richtung, 3), "t_brems": pr.t_brems, "t_steht": _r(pr.t_steht, 3),
                    "neigung": neigung or None},
        "kennzahlen": kz, "urteile": urteile, "handrechnung": hand,
        "suche": {k: {kk: _r(vv, 3) for kk, vv in x.items()} for k, x in suche.items()},
        "verlauf": verlauf, "pfeile": pfeile,
        "koerper": [{"id": k["id"], "name": k["name"], "art": k["art"], "masse": round(k["masse"], 3),
                     "teile": len(k["teile"]), "gelenk": (k.get("gelenk") or {}).get("quelle")}
                    for k in meta["koerper"]],
        "grenzen": list(GRENZEN_S2), "vereinfachungen": vereinfacht,
        "ms": {"modell": round(t_modell, 1), "ablauf": round(t_ablauf, 1),
               "suche": round(t_suche, 1), "varianten": sum(x.get("varianten", 0) for x in suche_info.values()),
               "gesamt": round((time.perf_counter() - t0) * 1000, 1), "schritte": auf.schritte,
               "zeitschritt_ms": mjcf.ZEITSCHRITT * 1000},
    }
    ablauf["text"] = ut.kurztext(sz["name"], urteile, ampel)
    return ablauf, {"teile": np.frombuffer(json.dumps(teile).encode(), dtype=np.uint8),
                    "zeiten": auf.zeiten.astype(np.float64), "lagen": lagen.astype(np.float64)}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("Aufruf: python -m kevcad_kernel.statik.dynamik.prozess auftrag.json", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    auftrag = json.loads(open(argv[0], encoding="utf-8").read())
    out: dict[str, Any] = {"stand": "done", "szenarien": [], "pid": os.getpid()}
    felder_aus: dict[str, np.ndarray] = {}
    try:
        meta, felder = szene.lese(auftrag["szene"])
        coacd, cinfo = coacd_stuecke(meta, felder)
        out["coacd"] = cinfo
        formen = mjcf.formen_je_teil(meta, felder, coacd)
        fps = float(auftrag.get("fps") or FPS)
        for i, sz in enumerate(auftrag.get("szenarien") or []):
            try:
                abl, f = rechne_szenario(meta, formen, sz, fps)
            except Exception as exc:  # noqa: BLE001 - ein Szenario darf die anderen nicht verhindern
                abl = {"stand": "failed", "meldung": f"Ablauf nicht gerechnet: {type(exc).__name__}: {exc}",
                       "traceback": traceback.format_exc(limit=8)}
                f = {}
            out["szenarien"].append({"name": sz["name"], "ablauf": abl})
            for k, v in f.items():
                felder_aus[f"{k}_{i}"] = v
        out["szene"] = {"koerper": len(meta["koerper"]), "kollision": len(meta["kollision"]),
                        "paare": len(meta["paare"]), "boden_paare": len(meta["boden_paare"]),
                        "szene_ms": meta.get("ms")}
    except Exception as exc:  # noqa: BLE001
        out = {"stand": "failed", "meldung": f"Ablauf fehlgeschlagen: {type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc(limit=8)}
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if auftrag.get("lagen") and felder_aus:
        np.savez(auftrag["lagen"], **felder_aus)
    tmp = auftrag["ausgabe"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, auftrag["ausgabe"])
    return 0 if out.get("stand") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())

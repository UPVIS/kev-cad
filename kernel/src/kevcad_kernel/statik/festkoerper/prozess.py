"""FEM-Prozess (S3): ``python -m kevcad_kernel.statik.festkoerper.prozess <auftrag.json> <ergebnis.json>``.

Läuft getrennt vom Rechenprozess von model.py und von der Laufzeit; Gmsh, scikit-fem und pyamg werden nur hier
geladen (und nur, wenn etwas zu rechnen ist). Fortschritt als JSON-Zeilen auf stdout (``{"fortschritt": 0.4,
"text": "…"}``), Ergebnis als Datei; die Laufzeit bricht durch Beenden des Prozesses ab.

Je Teil: Netz (Zwischenspeicher je Teilstand und Netzeinstellung), Steifigkeit einmal, Lagerflächen je Nachbar, dann
je Lagerung alle Lastfälle mit einer Zerlegung bzw. einem AMG-Aufbau. Ergebnis je Fall (Zwischenspeicher je Schlüssel,
siehe ``auftrag``): Sicherheit, maßgebendes Kriterium, Ort, Verformung, Sicherheit in den anderen Drucklagen und das
Oberflächennetz mit Ausnutzung, von-Mises-Spannung und Verschiebung je Punkt (für STATICS_FIELD).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.statik.festkoerper import GRENZEN_S3, VERSION

LAST_RADIUS = (0.1, 3.0, 25.0)  # Lastfläche um einen Punkt: Anteil der Teilgröße, mindestens, höchstens (mm)


def speicher() -> Path:
    p = os.environ.get("KEVCAD_FESTKOERPER_CACHE")
    if p:
        return Path(p)
    bundle = os.environ.get("KEVCAD_APP_BUNDLE_ID") or "de.upvis.kevcad"
    return Path.home() / "Library" / "Caches" / bundle / "festkoerper"


def melde(fortschritt: float, text: str) -> None:
    print(json.dumps({"fortschritt": round(max(0.0, min(1.0, fortschritt)), 3), "text": text}, ensure_ascii=False),
          flush=True)


def _schreibe_npz(pfad: Path, **felder: Any) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, **felder)
    os.replace(tmp, pfad)


def lies_fall(pfad: Path) -> dict[str, Any] | None:
    """Fall aus dem Zwischenspeicher: Kurzfassung (``info``) und Felder."""
    try:
        with np.load(pfad) as z:
            info = json.loads(bytes(z["info"]).decode("utf-8"))
            info["_felder"] = {k: z[k] for k in z.files if k != "info"}
        return info
    except Exception:  # noqa: BLE001 - kaputter Eintrag: neu rechnen
        return None


def _netz(T: dict[str, Any], fein: bool, ablage: Path) -> tuple[dict[str, Any], bool]:
    from kevcad_kernel.statik.festkoerper import netz

    key = hashlib.sha1(json.dumps({"v": VERSION, "teil": T["schluessel_teil"], "fein": fein, "h": T.get("h_mm"),
                                   "max": [netz.MAX_TET, netz.MAX_TET_FEIN, netz.WAND_ANTEIL, netz.KRUEMMUNG]},
                                  sort_keys=True).encode()).hexdigest()[:20]
    pfad = ablage / "netze" / f"{key}.npz"
    if pfad.exists():
        try:
            with np.load(pfad) as z:
                return {k: z[k] for k in z.files} | {"h": float(z["h"]), "ms": 0.0}, True
        except Exception:  # noqa: BLE001
            pass
    n = netz.vernetze(T["brep"], fein=fein, h_vorgabe=T.get("h_mm"))
    _schreibe_npz(pfad, p=n["p"], t=n["t"], rand=n["rand"], flaeche=n["flaeche"], h=np.float64(n["h"]))
    return n, False


def _lastflaeche(N: Any, punkt: np.ndarray, groesse: float, h: float) -> np.ndarray:
    """Randdreiecke um den Punkt: auf derselben B-Rep-Fläche wie das nächste Randdreieck, im Umkreis r."""
    d = np.linalg.norm(N.rand_mitte - punkt[None, :], axis=1)
    j0 = int(np.argmin(d))
    anteil, rmin, rmax = LAST_RADIUS
    r = min(max(anteil * groesse, rmin, 2 * h), rmax)
    for _ in range(4):
        nah = d <= d[j0] + r
        if N.rand_brep[j0] >= 0:
            sel = np.where(nah & (N.rand_brep == N.rand_brep[j0]))[0]
        else:
            sel = np.where(nah & (N.rand_normale @ N.rand_normale[j0] > 0.7))[0]
        if N.rand_flaeche_mm2[sel].sum() >= 1.0:
            return sel
        r *= 2
    return np.array([j0])


def _bewerten(N: Any, u: np.ndarray, C: np.ndarray, T: dict[str, Any], fall: dict[str, Any], fest_knoten: np.ndarray
              ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    w = T["werkstoff"]
    s = N.spannung(u, C)
    vm = wk.mises(s)
    i_m, i_s = wk.index(s, w["f"], w.get("q"), T.get("schicht") if T["druckteil"] else None)
    if T["druckteil"] and i_s is None:  # Drucklage unbekannt: überall wie quer zur Schicht (wie S0)
        idx = i_m / float(w.get("q") or 0.5)
        krit = np.full(len(idx), 2)
    elif i_s is not None:
        idx = np.maximum(i_m, i_s)
        krit = np.where(i_s > i_m, 1, 0)
    else:
        idx = i_m
        krit = np.zeros(len(idx), dtype=np.int64)
    # Auf der Lagerfläche selbst ist die Spannung eine Folge der starren Einspannung (Querdehnung behindert, Kante
    # singulär): gewertet wird ab dem ersten Knoten neben der Lagerfläche, die Spitze am Lagerrand steht daneben.
    frei = np.ones(N.n, dtype=bool)
    frei[fest_knoten] = False
    if not frei.any():
        frei[:] = True
    kandidaten = np.where(frei)[0]
    k = int(kandidaten[np.argmax(idx[kandidaten])])
    k_rand = int(np.argmax(idx))
    sicherheit = 1.0 / float(idx[k]) if idx[k] > 0 else math.inf
    v = N.verschiebung(u)
    vb = np.linalg.norm(v, axis=1)
    ziel = float(fall["ziel"])
    alt = {}
    if T["druckteil"]:
        for name, n in (T.get("ausrichtungen") or {}).items():
            a_m, a_s = wk.index(s, w["f"], w.get("q"), np.asarray(n))
            alt[name] = round(1.0 / float(np.max(np.maximum(a_m, a_s)[kandidaten])), 3)
    sv = np.unique(N.rand)
    remap = np.full(N.n, -1, dtype=np.int64)
    remap[sv] = np.arange(len(sv))
    info = {
        "sicherheit": round(sicherheit, 3) if math.isfinite(sicherheit) else None, "ziel": ziel,
        "ausnutzung": round(ziel / sicherheit, 4) if sicherheit > 0 else None,
        "spannung_max": round(float(vm[kandidaten].max()), 3), "spannung_ort": round(float(vm[k]), 3),
        "index_mises": round(float(i_m[k]), 4), "index_schicht": None if i_s is None else round(float(i_s[k]), 4),
        "kriterium": ("schicht" if krit[k] == 1 else ("quer_unbekannt" if krit[k] == 2 else "mises")),
        "ort": [round(float(c), 2) for c in N.p[k]],
        "sicherheit_lagerrand": round(1.0 / float(idx[k_rand]), 3) if idx[k_rand] > 0 else None,
        "ort_lagerrand": [round(float(c), 2) for c in N.p[k_rand]],
        "verformung_max_mm": round(float(vb.max()), 5),
        "verformung_ort": [round(float(c), 2) for c in N.p[int(np.argmax(vb))]],
        "festigkeit": w["f"], "q": w.get("q"), "werkstoff": w.get("name"),
        "ausrichtungen": alt,
    }
    felder = {"punkte": N.p[sv].astype(np.float32), "dreiecke": remap[N.rand].astype(np.uint32),
              "ausnutzung": (ziel * idx[sv]).astype(np.float32), "spannung": vm[sv].astype(np.float32),
              "verschiebung": v[sv].astype(np.float32)}
    return info, felder


def rechne_teil(T: dict[str, Any], fein: bool, ablage: Path, von: float, bis: float) -> list[dict[str, Any]]:
    """Alle Fälle eines Teils; Ergebnisse aus dem Zwischenspeicher, wo vorhanden."""
    t0 = time.perf_counter()
    kurz = T["name"].rsplit("/", 1)[-1]
    out: list[dict[str, Any]] = []
    offen = []
    for f in T["faelle"]:
        alt = lies_fall(ablage / "faelle" / f"{f['schluessel']}.npz")
        if alt is not None:
            out.append({**alt, "id": f["id"], "aus_speicher": True})
        else:
            offen.append(f)
    if not offen:
        melde(bis, f"{kurz}: aus dem Zwischenspeicher")
        return out
    from kevcad_kernel.statik.festkoerper import kontakt, loeser
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    def schritt(anteil: float, text: str) -> None:
        melde(von + (bis - von) * anteil, f"{kurz}: {text}")

    schritt(0.02, "vernetzen")
    n, netz_gemerkt = _netz(T, fein, ablage)
    t_netz = (time.perf_counter() - t0) * 1000
    N = loeser.Netz(n["p"], n["t"], n["rand"], n["flaeche"])
    schritt(0.3, f"{len(N.t)} Tetraeder, {N.N} Freiheitsgrade")
    w = T["werkstoff"]
    C = wk.steifigkeit(w["E"], w["nu"], w.get("E_z") if T["druckteil"] else None,
                       T.get("schicht") if T["druckteil"] else None)
    t1 = time.perf_counter()
    K = N.steifigkeit(C)
    t_k = (time.perf_counter() - t1) * 1000
    schritt(0.45, "Steifigkeit aufgebaut")
    groesse = float(np.max(np.asarray(T["bmax"]) - np.asarray(T["bmin"])))
    duenn = groesse / max(2.0 * T["volumen"] / max(float(N.rand_flaeche_mm2.sum()), 1e-9), 1e-9) > 25
    # Kontaktflächen je Nachbar (Lager und Lasteinleitung)
    beruehrt: dict[str, np.ndarray] = {}
    for x, nb in T["nachbarn"].items():
        with np.load(nb["datei"]) as z:
            d = kontakt.abstand(N.rand_mitte, z["pos"], z["tri"], float(nb["tol"]))
        beruehrt[x] = np.where(np.isfinite(d))[0]
    gruppen: dict[tuple, list[dict[str, Any]]] = {}
    for f in offen:
        gruppen.setdefault(tuple(sorted(f["lager"])), []).append(f)
    erledigt = 0
    V = float(N.vol.sum())
    for lager, fs in gruppen.items():
        fest = np.unique(np.concatenate([beruehrt.get(x, np.zeros(0, dtype=np.int64)) for x in lager])) \
            if lager else np.zeros(0, dtype=np.int64)
        if len(fest) == 0:
            for f in fs:
                out.append({"id": f["id"], "stand": "failed", "meldung": f"keine Lagerfläche zu {', '.join(lager)} "
                                                                        "gefunden (berühren sie sich?)"})
            continue
        # Teile des Netzes ohne Lager (lose Stücke) würden das System singulär machen: weglassen
        komp = loeser.komponenten(N.t, N.n)
        mit_lager = np.unique(komp[np.unique(N.rand[fest])])
        lose = ~np.isin(komp[N.t[:, 0]], mit_lager)
        if lose.any():
            for f in fs:
                f.setdefault("hinweise", []).append(f"{int(lose.sum())} Tetraeder ohne Verbindung zum Lager "
                                                    "weggelassen")
        fest_dofs = N.feste_dofs(fest)
        if lose.any():
            weg_knoten = np.unique(N.t[lose])
            weg_knoten = weg_knoten[~np.isin(weg_knoten, np.unique(N.t[~lose]))]
            fest_dofs = np.union1d(fest_dofs, N.basis.nodal_dofs[:, weg_knoten].reshape(-1))
            weg_kanten = np.unique(N.kante[:, lose])
            weg_kanten = weg_kanten[~np.isin(weg_kanten, np.unique(N.kante[:, ~lose]))]
            fest_dofs = np.union1d(fest_dofs, N.basis.edge_dofs[:, weg_kanten].reshape(-1))
        vektoren, details = [], []
        for f in fs:
            lv = np.zeros(N.N)
            summe = np.zeros(3)
            lastflaechen = []
            for last in f["lasten"]:
                F = np.asarray(last["kraft"], float)
                M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
                P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
                summe += F
                if last.get("kontakt_mit"):
                    sel = beruehrt.get(last["kontakt_mit"], np.zeros(0, dtype=np.int64))
                    if len(sel) == 0 and P is not None:
                        sel = _lastflaeche(N, P, groesse, n["h"])
                    lv += N.last_flaeche(sel, F, M, P)
                    lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
                elif P is not None:
                    sel = _lastflaeche(N, P, groesse, n["h"])
                    lv += N.last_flaeche(sel, F, M, P)
                    lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
                else:  # am Schwerpunkt: gleichmäßig über das Volumen
                    lv += N.last_volumen(F / V)
                    if M is not None and np.any(M):
                        lv += N.last_flaeche(np.arange(len(N.rand)), np.zeros(3), M, None)
                    lastflaechen.append(None)
            g = np.asarray(f.get("feld") or (0, 0, 0), float) * (T["masse_kg"] / max(T["volumen"], 1e-9))
            lv += N.last_volumen(g)
            summe += g * V
            kontrolle = np.array([lv[N.basis.nodal_dofs[c]].sum() + lv[N.basis.edge_dofs[c]].sum() for c in range(3)])
            vektoren.append(lv)
            details.append({"lastflaechen_mm2": lastflaechen, "kraft_n": [round(float(c), 3) for c in summe],
                            "gleichgewicht_n": round(float(np.linalg.norm(kontrolle - summe)), 6),
                            "eigengewicht_n": [round(float(c), 4) for c in g * V]})
        schritt(0.5 + 0.4 * erledigt / max(len(offen), 1), f"lösen ({len(fs)} Lastfälle)")
        t2 = time.perf_counter()
        us, info = N.loese(K, fest_dofs, vektoren, duenn=duenn)
        t_loesen = (time.perf_counter() - t2) * 1000
        fest_knoten = np.unique(N.rand[fest])
        for i, (f, u, det) in enumerate(zip(fs, us, details)):
            t3 = time.perf_counter()
            kurzinfo, felder = _bewerten(N, u, C, T, f, fest_knoten)
            kurzinfo.update(det)
            kurzinfo.update({
                "stand": "done", "szenario": f["szenario"], "teil": T["name"], "schluessel": f["schluessel"],
                "lager": list(lager), "lager_aus_last": f.get("lager_aus_last"),
                "lagerflaeche_mm2": round(float(N.rand_flaeche_mm2[fest].sum()), 1),
                "lasten": [{k: v for k, v in l.items()} for l in f["lasten"]], "s0": f.get("s0"),
                "hinweise": f.get("hinweise") or [],
                "netz": {"knoten": int(N.n), "tetraeder": int(len(N.t)), "freiheitsgrade": int(N.N),
                         "h_mm": round(float(n["h"]), 2), "fein": fein, "aus_speicher": netz_gemerkt,
                         "duenn": bool(duenn)},
                "loeser": {"verfahren": info["verfahren"][i], "iterationen": info["iterationen"][i],
                           "residuum": info["residuum"][i]},
                "ms": {"netz": round(t_netz, 1), "steifigkeit": round(t_k, 1), "loesen": round(t_loesen, 1),
                       "auswerten": round((time.perf_counter() - t3) * 1000, 1),
                       "teil": round((time.perf_counter() - t0) * 1000, 1)},
            })
            _schreibe_npz(ablage / "faelle" / f"{f['schluessel']}.npz",
                          info=np.frombuffer(json.dumps(kurzinfo, ensure_ascii=False).encode("utf-8"), dtype=np.uint8),
                          **felder)
            out.append({**kurzinfo, "id": f["id"], "aus_speicher": False, "_felder": felder})
            erledigt += 1
        schritt(0.5 + 0.45 * erledigt / max(len(offen), 1), f"{erledigt} von {len(offen)} Lastfällen fertig")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("Aufruf: python -m kevcad_kernel.statik.festkoerper.prozess auftrag.json ergebnis.json",
              file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    auftrag = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    ablage = speicher()
    out: dict[str, Any] = {"stand": "done", "faelle": [], "pid": os.getpid(), "grenzen": list(GRENZEN_S3)}
    teile = auftrag.get("teile") or []
    melde(0.0, f"{len(teile)} Teile")
    for i, T in enumerate(teile):
        von, bis = i / max(len(teile), 1), (i + 1) / max(len(teile), 1)
        try:
            for r in rechne_teil(T, bool(auftrag.get("fein")), ablage, von, bis):
                felder = r.pop("_felder", None)
                if felder is not None and r.get("stand") == "done":
                    r["feld"] = str(ablage / "faelle" / f"{r['schluessel']}.npz")
                out["faelle"].append(r)
        except Exception as exc:  # noqa: BLE001 - ein Teil darf die anderen nicht verhindern
            for f in T["faelle"]:
                out["faelle"].append({"id": f["id"], "stand": "failed", "szenario": f["szenario"], "teil": T["name"],
                                      "meldung": f"nicht gerechnet: {type(exc).__name__}: {exc}",
                                      "traceback": traceback.format_exc(limit=6)})
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    melde(1.0, "fertig")
    tmp = argv[1] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

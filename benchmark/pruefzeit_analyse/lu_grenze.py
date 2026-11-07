"""A3 (PLAN-PRUEFUNG-INKREMENTELL.md): direkte Zerlegung (SuperLU) gegen AMG bei steigender Zahl freier
Freiheitsgrade, Zeit und Speicher.

    PYTHONPATH=<worktree>/kernel/src <venv>/bin/python -u lu_grenze.py <auftrag-ordner> <teil-index> <faktoren> <ablage>

``<auftrag-ordner>``: gesicherter FEM-Auftrag (``auftrag.json`` mit BREP und Nachbarnetzen, etwa aus ``KCZ_FEM_KOPIE``),
``<faktoren>``: Netzgröße relativ zur Vorgabe des Teils (Komma, etwa ``1,0.9,0.8,0.72``). Je Faktor und Löser ein
frischer Prozess (saubere Speicherspitze): Netz, Steifigkeit, Lager des ersten Falls, alle Fälle des Teils. Gemessen:
freie Freiheitsgrade, Zeit der Zerlegung bzw. des AMG-Aufbaus, Lösungen, Speicher vor und nach der Zerlegung, Spitze
des Prozesses, Einträge der Faktoren; dazu je Fall Sicherheit und größte Verschiebung beider Löser.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / (1 << 20)


def ein_versuch(ordner: Path, idx: int, faktor: float, loeser_art: str, ablage: Path) -> dict:
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(ablage)
    import resource

    import numpy as np
    import scipy.sparse.linalg as spla

    from kevcad_kernel.statik.festkoerper import loeser, netz, prozess

    a = json.loads((ordner / "auftrag.json").read_text(encoding="utf-8"))
    T = a["teile"][idx]
    T["brep"] = str(ordner / Path(T["brep"]).name)
    for nb in T["nachbarn"].values():
        nb["datei"] = str(ordner / Path(nb["datei"]).name)
    # Vorgabe-Netzgröße des Teils wie netz.vernetze, dann skaliert
    import gmsh

    netz.gmsh_starten()
    try:
        gmsh.model.add("m")
        gmsh.model.occ.importShapes(T["brep"], highestDimOnly=True)
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        V = sum(gmsh.model.occ.getMass(3, t) for _, t in vols)
        A = sum(gmsh.model.occ.getMass(2, t) for _, t in gmsh.model.getEntities(2))
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for _, t in vols:
            b = gmsh.model.getBoundingBox(3, t)
            lo, hi = np.minimum(lo, b[:3]), np.maximum(hi, b[3:])
    finally:
        gmsh.finalize()
    h0 = netz.netzgroesse(V, A, float(np.max(hi - lo)))
    T["h_mm"] = round(h0 * faktor, 4)
    T["schluessel_teil"] = f"{T['schluessel_teil']}-lu-{faktor}"
    if loeser_art == "lu":
        loeser.LU_KLEIN = 10 ** 9
    else:
        loeser.LU_KLEIN = 0
    mess: dict = {"splu_s": None, "amg_s": None, "loesen_s": [], "rss_vor_mb": None, "rss_nach_mb": None, "nnz": None}
    o_splu = spla.splu

    def splu(*aa, **kw):
        mess["rss_vor_mb"] = round(rss_mb(), 1)
        t = time.perf_counter()
        z = o_splu(*aa, **kw)
        mess["splu_s"] = round(time.perf_counter() - t, 3)
        mess["rss_nach_mb"] = round(rss_mb(), 1)
        mess["nnz"] = int(z.nnz) if hasattr(z, "nnz") else None
        o_solve = z.solve

        class Z:
            nnz = getattr(z, "nnz", None)

            def solve(self, b, *x, **y):
                t1 = time.perf_counter()
                r = o_solve(b, *x, **y)
                mess["loesen_s"].append(round(time.perf_counter() - t1, 4))
                return r

        return Z()

    spla.splu = splu
    import pyamg

    o_sa = pyamg.smoothed_aggregation_solver

    def sa(*aa, **kw):
        mess["rss_vor_mb"] = round(rss_mb(), 1)
        t = time.perf_counter()
        ml = o_sa(*aa, **kw)
        mess["amg_s"] = round(time.perf_counter() - t, 3)
        mess["rss_nach_mb"] = round(rss_mb(), 1)
        o_s = ml.solve

        def solve(b, *x, **y):
            t1 = time.perf_counter()
            r = o_s(b, *x, **y)
            mess["loesen_s"].append(round(time.perf_counter() - t1, 4))
            return r

        ml.solve = solve
        return ml

    pyamg.smoothed_aggregation_solver = sa
    for f in T["faelle"]:
        f["schluessel"] = f"{f['schluessel']}-{loeser_art}-{faktor}-{time.time_ns()}"
    t0 = time.perf_counter()
    out = prozess.rechne_teil(T, False, ablage, 0.0, 1.0)
    dt = time.perf_counter() - t0
    faelle = []
    for r in out:
        felder = r.pop("_felder", None) or {}
        faelle.append({"szenario": r.get("szenario"), "sicherheit": r.get("sicherheit"),
                       "verformung_max_mm": r.get("verformung_max_mm"), "spannung_max": r.get("spannung_max"),
                       "loeser": r.get("loeser"), "netz": r.get("netz"),
                       "verschiebung": felder["verschiebung"].astype(float).tolist() if "verschiebung" in felder
                       else None})
    spitze = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20)
    return {"teil": T["name"], "faktor": faktor, "h_mm": T["h_mm"], "loeser": loeser_art, "s": round(dt, 3),
            "spitze_mb": round(spitze, 1), **mess, "faelle": faelle}


def main() -> int:
    if sys.argv[1] == "--einzeln":
        ordner, idx, faktor, art, ablage = Path(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], \
            Path(sys.argv[6])
        print(json.dumps(ein_versuch(ordner, idx, faktor, art, ablage)), flush=True)
        return 0
    ordner, idx, faktoren, ablage = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    ablage.mkdir(parents=True, exist_ok=True)
    zeilen = []
    for faktor in [float(x) for x in faktoren.split(",")]:
        paar = {}
        for art in ("lu", "amg"):
            r = subprocess.run([sys.executable, "-u", __file__, "--einzeln", str(ordner), str(idx), str(faktor), art,
                                str(ablage)], capture_output=True, text=True, env=dict(os.environ, OMP_NUM_THREADS="4"))
            if r.returncode != 0:
                print(f"{faktor} {art}: Fehler {r.stderr[-1500:]}", flush=True)
                continue
            paar[art] = json.loads(r.stdout.strip().splitlines()[-1])
        if "lu" not in paar or "amg" not in paar:
            continue
        import numpy as np

        lu, amg = paar["lu"], paar["amg"]
        abw = []
        for fl, fa in zip(lu["faelle"], amg["faelle"]):
            if fl["verschiebung"] is None or fa["verschiebung"] is None:
                continue
            x, y = np.asarray(fl["verschiebung"]), np.asarray(fa["verschiebung"])
            abw.append(float(np.max(np.abs(x - y)) / max(float(np.max(np.abs(x))), 1e-300)))
        frei = (lu["faelle"][0]["netz"] or {}).get("freiheitsgrade")
        z = {"faktor": faktor, "h_mm": lu["h_mm"], "freiheitsgrade": frei,
             "lu": {k: lu[k] for k in ("s", "splu_s", "loesen_s", "rss_vor_mb", "rss_nach_mb", "nnz", "spitze_mb")},
             "amg": {k: amg[k] for k in ("s", "amg_s", "loesen_s", "rss_vor_mb", "rss_nach_mb", "spitze_mb")}
             | {"iterationen": [f["loeser"]["iterationen"] for f in amg["faelle"]]},
             "sicherheit": [(fl["sicherheit"], fa["sicherheit"]) for fl, fa in zip(lu["faelle"], amg["faelle"])],
             "verformung": [(fl["verformung_max_mm"], fa["verformung_max_mm"])
                            for fl, fa in zip(lu["faelle"], amg["faelle"])],
             "verschiebung_rel_max": max(abw) if abw else None}
        zeilen.append(z)
        print(json.dumps(z, ensure_ascii=False), flush=True)
    (ablage / "lu_grenze.json").write_text(json.dumps(zeilen, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

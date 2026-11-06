"""FEM-Versuche an einem gesicherten Auftrag (Analyse „Prüfung inkrementell“, nicht Teil des Repos).

    PYTHONPATH=<worktree>/kernel/src <venv>/bin/python -u fem_versuch.py <auftrag_ordner> <arbeitsordner> MODUS

MODUS:
- seq     wie der FEM-Prozess heute: Teile nacheinander, Zeiten je Teil und je Phase (Zerlegung, AMG-Aufbau, Lösen je
          Lastfall), Ergebnisse je Fall (Sicherheit, größte Verschiebung)
- lu      wie seq, aber immer SuperLU (LU_KLEIN hoch gesetzt)
- par4    wie seq, aber vier Prozesse (je Teil einer), Wanduhr gesamt
Die Netze kommen aus <arbeitsordner>/netze (vorher dorthin kopiert), die Fälle werden nicht aus dem Speicher gelesen.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def _instrumentieren(protokoll: list) -> None:
    import pyamg
    import scipy.sparse.linalg as spla

    o_splu = spla.splu

    def splu(*a, **kw):
        t = time.perf_counter()
        z = o_splu(*a, **kw)
        dt = time.perf_counter() - t
        protokoll.append(("splu", dt, a[0].shape[0]))
        o_solve = z.solve

        class Z:
            def solve(self, b, *aa, **kk):
                t1 = time.perf_counter()
                x = o_solve(b, *aa, **kk)
                protokoll.append(("lu_solve", time.perf_counter() - t1, len(b)))
                return x

        return Z()

    spla.splu = splu
    o_sa = pyamg.smoothed_aggregation_solver

    def sa(*a, **kw):
        t = time.perf_counter()
        ml = o_sa(*a, **kw)
        protokoll.append(("amg_aufbau", time.perf_counter() - t, a[0].shape[0]))
        o_s = ml.solve

        def solve(b, *aa, **kk):
            t1 = time.perf_counter()
            x = o_s(b, *aa, **kk)
            protokoll.append(("amg_solve", time.perf_counter() - t1, len(kk.get("residuals") or [])))
            return x

        ml.solve = solve
        return ml

    pyamg.smoothed_aggregation_solver = sa


def ein_teil(args: tuple) -> dict:
    T, fein, ablage, modus = args
    os.environ["KEVCAD_FESTKOERPER_CACHE"] = ablage
    from kevcad_kernel.statik.festkoerper import loeser, prozess

    if modus == "lu":
        loeser.LU_KLEIN = 10**9
    protokoll: list = []
    _instrumentieren(protokoll)
    t0 = time.perf_counter()
    # Fälle nicht aus dem Speicher: Schlüssel verfälschen
    for f in T["faelle"]:
        f["schluessel"] = f["schluessel"] + f"-{modus}-{os.getpid()}-{time.time_ns()}"
    out = prozess.rechne_teil(T, fein, Path(ablage), 0.0, 1.0)
    dt = time.perf_counter() - t0
    faelle = []
    for r in out:
        felder = r.pop("_felder", None) or {}
        vmax = None
        if "verschiebung" in felder:
            import numpy as np

            vmax = float(np.max(np.linalg.norm(felder["verschiebung"], axis=1)))
        faelle.append({"szenario": r.get("szenario"), "sicherheit": r.get("sicherheit"),
                       "vmax": vmax, "loeser": r.get("loeser"), "ms": r.get("ms"),
                       "dof": (r.get("netz") or {}).get("freiheitsgrade")})
    return {"teil": T["name"], "s": round(dt, 3), "phasen": [(p, round(t, 3), n) for p, t, n in protokoll],
            "faelle": faelle}


def main() -> int:
    ordner, arbeit, modus = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    auftrag = json.loads((ordner / "auftrag.json").read_text(encoding="utf-8"))
    # Pfade im Auftrag zeigen auf den alten Temp-Ordner: auf die Kopie umbiegen
    alt = None
    for T in auftrag["teile"]:
        alt = str(Path(T["brep"]).parent)
        T["brep"] = str(ordner / Path(T["brep"]).name)
        for nb in T["nachbarn"].values():
            nb["datei"] = str(ordner / Path(nb["datei"]).name)
    ablage = str(arbeit)
    (arbeit / "faelle").mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    jobs = [(T, bool(auftrag.get("fein")), ablage, modus) for T in auftrag["teile"]]
    if modus == "par4":
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing as mp

        with ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context("spawn")) as ex:
            erg = list(ex.map(ein_teil, jobs))
    else:
        erg = [ein_teil(j) for j in jobs]
    gesamt = time.perf_counter() - t0
    print(json.dumps({"modus": modus, "gesamt_s": round(gesamt, 2), "teile": erg}, ensure_ascii=False))
    shutil.rmtree(arbeit / "faelle", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

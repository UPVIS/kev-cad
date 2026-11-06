"""Stufe A für große Modelle: Wie lange braucht die Prüfung nach einer Änderung, und welcher Teil davon?

Anlass: Beim Kugelschieber (t7) wartete der Agent 30 bis 48 s auf ``pruefen()``, der Lauf selbst brauchte 5 bis 7 s.
Ohne Sprachmodell und ohne App, an einer Kopie von Kevins Projekt:

    kernel/.venv/bin/python -u benchmark/pruefzeit.py [--kernel-src …] [--param laufrolle_l=90]

Misst je Schritt Lauf und Prüfung bis zum Endstand: kalt, dieselbe Änderung wie t7 (``run(params=…)``), dieselbe
Änderung noch einmal (nichts neu), und gibt die Zeiten aus, die die Prüfung selbst meldet (Statik je Szenario).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

import lauf  # noqa: E402


def zeiten(check: dict[str, Any]) -> dict[str, Any]:
    """Zeitangaben aus dem Prüfergebnis, so weit vorhanden (Gesamt, Statik je Szenario)."""
    out: dict[str, Any] = {"duration_ms": check.get("duration_ms"), "state": check.get("state"),
                           "zusammenfassung": check.get("zusammenfassung")}
    stat = check.get("statistik")
    if isinstance(stat, dict):  # Zeiten je Teilprüfung (pruefung/pruefer.py, ctx.zeiten) und Zahl der Paare
        out["zeiten_ms"] = stat.get("zeiten_ms")
        out["paare"] = stat.get("paare")
    statik = check.get("statik")
    if isinstance(statik, dict):
        out["statik_keys"] = sorted(statik)[:20]
        for k in ("ms", "zeiten_ms", "dienst_ms", "rechnen_ms"):
            if statik.get(k) is not None:
                out[f"statik_{k}"] = statik[k]
        szen = statik.get("szenarien")
        if isinstance(szen, list):
            out["szenarien"] = [{k: s.get(k) for k in ("name", "ms", "zeiten_ms", "ampel", "aus_gedaechtnis")
                                 if k in s} for s in szen]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel-src", default=None)
    ap.add_argument("--param", default="laufrolle_l=90")
    args = ap.parse_args()
    lauf._kernel_src_einsetzen(args.kernel_src)
    from aufgaben import KUGEL  # noqa: PLC0415
    from kevcad_kernel.runtime import KernelRuntime  # noqa: PLC0415

    name, _, wert = args.param.partition("=")
    params = {name: float(wert)}
    ablage = Path.home() / "Library/Caches/de.upvis.kevcad-bench" / f"{time.strftime('%Y%m%d-%H%M%S')}-pruefzeit"
    arbeit, projekte = lauf.arbeitsordner(ablage, "pruefzeit")
    projekt = projekte / "kugelschieber"
    shutil.copytree(KUGEL, projekt, ignore=shutil.ignore_patterns(
        ".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp", "*.stl", "__pycache__", ".DS_Store",
        "dokumente"))
    rt = KernelRuntime(str(arbeit / "k.sock"), lauf.MCP_HELLO_PORT, auto_run=False, run_timeout_s=900,
                       log=lambda line: None)
    schritte = []
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        rt.project_open(str(projekt))
        for titel, p in (("kalt", None), ("Änderung wie t7", params), ("dieselbe Änderung noch einmal", params),
                         ("zurück auf die Datei", None)):
            t0 = time.monotonic()
            res = rt.run(params=p, timeout_s=900)
            t_run = time.monotonic() - t0
            t1 = time.monotonic()
            check = rt.pruefen(warten_s=600, endstand=True)
            t_pruef = time.monotonic() - t1
            eintrag = {"schritt": titel, "run_s": round(t_run, 2), "pruefen_s": round(t_pruef, 2),
                       "ok": res.get("ok", True), **zeiten(check)}
            schritte.append(eintrag)
            print(json.dumps(eintrag, ensure_ascii=False), flush=True)
    finally:
        rt.close()
        pool = getattr(rt, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=True)
        (ablage / "pruefzeit.json").write_text(json.dumps(schritte, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Ergebnis: {ablage / 'pruefzeit.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Detailmessung der Prüfzeit am Kugelschieber (Analyse „Prüfung inkrementell“, nicht Teil des Repos).

Wie benchmark/pruefzeit.py, aber mit Zeitstempeln je Ereignis in Laufzeit, Rechenprozess und FEM-Prozess. Aufruf:

    PYTHONPATH=<instrument>:<worktree>/kernel/src KCZ_PROTOKOLL=<ablage>/protokoll.jsonl \
        <venv>/bin/python -u pruefzeit_detail.py --ablage <ordner> [--schritte "kalt;laufrolle_l=90;…"]

Arbeitsordner (Katalog, Projekte, Druck- und FEM-Zwischenspeicher, TMPDIR) liegen unter --ablage.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import sitecustomize as sc  # Messhülle (instrument/sitecustomize.py)

KUGEL = Path.home() / "Documents" / "Kev CAD" / "Kugelschieber Variante B"
KATALOG = Path.home() / "Library/Application Support/de.upvis.kevcad/katalog"
MCP_HELLO_PORT = 47995


def log(e: str, **kw: Any) -> None:
    sc.log(e, **kw)


def arbeitsordner(ablage: Path) -> tuple[Path, Path]:
    arbeit = ablage / "arbeit"
    katalog = arbeit / "katalog"
    shutil.copytree(KATALOG, katalog)
    projekte = arbeit / "projekte"
    projekte.mkdir()
    druck = arbeit / "druck"
    tmp = ablage / "tmp"
    tmp.mkdir()
    os.environ.update({
        "KEVCAD_CATALOG_DIR": str(katalog), "KEVCAD_PROJECTS_DIR": str(projekte),
        "KEVCAD_DRUCK_CACHE": str(druck / "cache"), "KEVCAD_DRUCK_ABGLEICH": str(druck / "abgleich.json"),
        "KEVCAD_BAMBU_APP": str(druck / "kein-bambu-studio.app"), "KEVCAD_FESTKOERPER_CACHE": str(druck / "festkoerper"),
        "KEVCAD_FILAMENTE": str(druck / "filamente.json"), "KEVCAD_DRUCKER_SSDP": "0", "TMPDIR": str(tmp),
    })
    import tempfile

    tempfile.tempdir = str(tmp)
    return arbeit, projekte


def instrumentieren() -> None:
    from kevcad_kernel.pruefung.anbindung import PruefStand
    from kevcad_kernel.runtime import KernelRuntime

    o_msg = KernelRuntime._on_worker_message

    def on_msg(self, gen, header, payload):
        kind = header.get("type")
        t0 = time.time()
        if kind in ("CHECK_DONE", "RUN_DONE", "RUN_FAILED", "EXEC_RES"):
            app = header.get("app") or {}
            stat = app.get("statistik") or {}
            log("rt_ein", kind=kind, run=header.get("run") or app.get("run"), state=app.get("state"),
                offen=app.get("im_hintergrund"), zeiten=stat.get("zeiten_ms"), paare=stat.get("paare"),
                dauer_ms=app.get("duration_ms"))
        try:
            return o_msg(self, gen, header, payload)
        finally:
            if kind == "CHECK_DONE":
                log("rt_checkdone_verarbeitet", run=(header.get("app") or {}).get("run"), s=round(time.time() - t0, 3))

    KernelRuntime._on_worker_message = on_msg

    o_fertig = PruefStand.fertig

    def fertig(self, header, payload):
        log("stand_fertig", run=header.get("run"), state=header.get("state"),
            statik_offen=header.get("statik_im_hintergrund"), offen=header.get("im_hintergrund"),
            zusammenfassung=header.get("zusammenfassung"))
        return o_fertig(self, header, payload)

    PruefStand.fertig = fertig

    def umhuelle(name: str, details=None):
        o = getattr(KernelRuntime, name)

        def f(self, *a, **kw):
            t0 = time.time()
            log(f"{name}_start", args=[str(x)[:120] for x in a][:3])
            try:
                out = o(self, *a, **kw)
                extra = details(out) if details is not None else {}
                log(f"{name}_ende", s=round(time.time() - t0, 3), **extra)
                return out
            except BaseException as exc:
                log(f"{name}_fehler", s=round(time.time() - t0, 3), fehler=repr(exc))
                raise

        setattr(KernelRuntime, name, f)

    def fk_exec_details(job):
        return {"faelle": [(f.get("szenario"), f.get("teil"), f.get("schluessel")) for f in job.get("faelle") or []],
                "nicht": job.get("nicht"), "ms": job.get("ms")}

    def fk_prozess_details(out):
        return {"prozess_ms": out.get("prozess_ms"), "ms": out.get("ms"),
                "faelle": [{"szenario": r.get("szenario"), "teil": r.get("teil"), "stand": r.get("stand"),
                            "aus_speicher": r.get("aus_speicher"), "ms": r.get("ms"),
                            "sicherheit": r.get("sicherheit"), "schluessel": r.get("schluessel")}
                           for r in out.get("faelle") or []]}

    o_fkp = KernelRuntime._fk_prozess

    def fk_prozess_kopie(self, job, *a, **kw):
        ziel = os.environ.get("KCZ_FEM_KOPIE")
        if ziel:
            n = len(list(Path(ziel).glob("*"))) if Path(ziel).exists() else 0
            try:
                shutil.copytree(job["ordner"], Path(ziel) / f"{n:02d}-run{job.get('run')}")
            except Exception as exc:  # noqa: BLE001
                log("fem_kopie_fehler", fehler=repr(exc))
        return o_fkp(self, job, *a, **kw)

    KernelRuntime._fk_prozess = fk_prozess_kopie
    umhuelle("_festkoerper_hintergrund")
    umhuelle("_fk_exec", fk_exec_details)
    umhuelle("_fk_prozess", fk_prozess_details)
    umhuelle("_dynamik_hintergrund")
    umhuelle("_topologie_nach_lauf")
    umhuelle("_statik_pruefung_nachtragen", lambda out: {"neu": out})
    umhuelle("_versionen_pruefung")
    umhuelle("_gedruckt_check")
    umhuelle("_druckvorschau_pruefung")
    umhuelle("_statik_senden")
    umhuelle("_simulation_nach_lauf")

    o_exec = KernelRuntime.execute

    def execute(self, code, *a, **kw):
        t0 = time.time()
        kurz = str(code)[:140]
        log("rt_exec_start", code=kurz)
        try:
            return o_exec(self, code, *a, **kw)
        finally:
            log("rt_exec_ende", code=kurz, s=round(time.time() - t0, 3))

    KernelRuntime.execute = execute


def teile_schluessel(rt: Any) -> dict[str, str]:
    return {r.name: r.key for r in rt.scene.records()}


def statik_kurz(check: dict[str, Any]) -> Any:
    st = check.get("statik")
    if not isinstance(st, dict):
        return None
    return [{k: s.get(k) for k in ("name", "ampel", "aus_gedaechtnis") if k in s} for s in st.get("szenarien") or []]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablage", required=True)
    ap.add_argument("--schritte", default="kalt;laufrolle_l=90;laufrolle_l=90;-;laufrolle_l=95")
    ap.add_argument("--nachlauf-s", type=float, default=3.0, help="nach dem Endstand so lange weiter protokollieren")
    args = ap.parse_args()
    ablage = Path(args.ablage)
    ablage.mkdir(parents=True, exist_ok=True)
    arbeit, projekte = arbeitsordner(ablage)
    projekt = projekte / "kugelschieber"
    shutil.copytree(KUGEL, projekt, ignore=shutil.ignore_patterns(
        ".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp", "*.stl", "__pycache__", ".DS_Store",
        "dokumente"))
    instrumentieren()
    import kevcad_kernel
    from kevcad_kernel.runtime import KernelRuntime

    log("treiber", kernel=kevcad_kernel.__file__, pid=os.getpid())

    def rtlog(line: str) -> None:
        log("rt_log", text=str(line)[:300])

    rt = KernelRuntime(str(arbeit / "k.sock"), MCP_HELLO_PORT, auto_run=False, run_timeout_s=900, log=rtlog)
    schritte_out = []
    vorher: dict[str, str] = {}
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        rt.project_open(str(projekt))
        for i, s in enumerate(args.schritte.split(";")):
            s = s.strip()
            if s in ("kalt", "-", ""):
                params = None
            else:
                name, _, wert = s.partition("=")
                params = {name: float(wert)}
            titel = f"{i}:{s}"
            log("schritt_start", schritt=titel, params=params, last=os.getloadavg())
            t0 = time.monotonic()
            res = rt.run(params=params, timeout_s=900)
            t_run = time.monotonic() - t0
            log("schritt_run_zurueck", schritt=titel, s=round(t_run, 3), ok=res.get("ok", True),
                zeiten=res.get("zeiten_ms"), pruefung_state=(res.get("pruefung") or {}).get("state"))
            t1 = time.monotonic()
            check = rt.pruefen(warten_s=600, endstand=True)
            t_pruef = time.monotonic() - t1
            log("schritt_endstand", schritt=titel, s=round(t_pruef, 3), state=check.get("state"),
                statik_hintergrund=check.get("statik_hintergrund"), hintergrund=check.get("hintergrund"))
            jetzt = teile_schluessel(rt)
            geaendert = sorted(n for n, k in jetzt.items() if vorher.get(n) != k) if vorher else None
            weg = sorted(n for n in vorher if n not in jetzt) if vorher else None
            vorher = jetzt
            stat = check.get("statistik") or {}
            eintrag = {"schritt": titel, "run_s": round(t_run, 2), "pruefen_s": round(t_pruef, 2),
                       "bis_endstand_s": round(t_run + t_pruef, 2), "state": check.get("state"),
                       "duration_ms": check.get("duration_ms"), "zeiten_ms": stat.get("zeiten_ms"),
                       "paare": stat.get("paare"), "teile": len(jetzt),
                       "geaendert": geaendert, "weg": weg, "statik": statik_kurz(check),
                       "zusammenfassung": check.get("zusammenfassung"), "lauf_zeiten": res.get("zeiten_ms")}
            schritte_out.append(eintrag)
            print(json.dumps({k: v for k, v in eintrag.items() if k != "geaendert"}, ensure_ascii=False), flush=True)
            print(f"  geändert ({len(geaendert or [])}): {geaendert}", flush=True)
            time.sleep(args.nachlauf_s)  # was nach dem Endstand noch läuft (Topologie, STATICS …)
            log("schritt_ende", schritt=titel)
    finally:
        rt.close()
        pool = getattr(rt, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=True)
        (ablage / "schritte.json").write_text(json.dumps(schritte_out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Ergebnis: {ablage / 'schritte.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

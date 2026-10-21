"""Durchdringungen in einem Projekt finden (Behelf, bis die Prüfung im Kernel bei jedem Lauf mitläuft).

Rechnet das Projekt auf einer Kopie in einer eigenen Kernel-Laufzeit (das Original und die laufende App bleiben
unberührt), nimmt die exakten Formen aller gezeigten Teile und prüft jedes Paar: Vorfilter über die Hüllquader, dann
das Schnittvolumen mit OCCT. Berühren ist erlaubt; gemeldet wird jedes Paar mit Schnittvolumen über der Schwelle, mit
Volumen, Ausdehnung und Mittelpunkt der Überlappung.

Aufruf:  .venv/bin/python tools/check_interference.py <Projektordner> [--schwelle 0.001] [--json]
Exit-Code 1, wenn es Durchdringungen gibt.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app_testutil import FakeApp  # noqa: E402
from build123d import Shape  # noqa: E402
from kevcad_kernel.runtime import KernelRuntime  # noqa: E402

KLEINTEIL = ("schraube", "scheibe", "mutter", "bolzen", "stift", "niete", "m3", "m4", "m5", "m6", "m8", "m10", "m12")


def overlaps(a, b, tol: float = 1e-6) -> bool:
    amin, amax, bmin, bmax = tuple(a.min), tuple(a.max), tuple(b.min), tuple(b.max)
    return all(amin[i] < bmax[i] - tol and bmin[i] < amax[i] - tol for i in range(3))


def check(project: Path, threshold: float) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="kcint", dir="/tmp"))
    copy = tmp / project.name
    shutil.copytree(project, copy, ignore=shutil.ignore_patterns(".kevcad", "output", "__pycache__"))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 0, auto_run=False, run_timeout_s=300)
    try:
        if not rt.wait_worker_ready(240):
            raise RuntimeError("Rechenprozess nicht bereit")
        app = FakeApp(sock)
        app.wait_for(lambda h: h["type"] == "HELLO")
        if not rt.project_open(str(copy)).get("ok"):
            raise RuntimeError("Projekt lässt sich nicht öffnen")
        res = rt.run(timeout_s=300)
        if not res.get("ok"):
            raise RuntimeError(f"Lauf fehlgeschlagen: {res.get('error')}")
        records = rt.scene.records()
        shapes = {r.name: Shape.cast(r.shape) if not isinstance(r.shape, Shape) else r.shape for r in records}
        app.close()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)

    t0 = time.perf_counter()
    names = sorted(shapes)
    boxes = {n: shapes[n].bounding_box() for n in names}
    befunde = []
    candidates = 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not overlaps(boxes[a], boxes[b]):
                continue
            candidates += 1
            common = shapes[a] & shapes[b]
            vol = common.volume if common is not None else 0.0
            if vol > threshold:
                bb = common.bounding_box()
                klein = any(k in (a + " " + b).lower() for k in KLEINTEIL)
                befunde.append({"teile": [a, b], "volumen_mm3": round(vol, 4),
                                "ausdehnung_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
                                "mitte": [round(bb.center().X, 2), round(bb.center().Y, 2), round(bb.center().Z, 2)],
                                "verbindungselement": klein})
    befunde.sort(key=lambda f: -f["volumen_mm3"])
    return {"teile": len(names), "paare_geprueft": candidates, "dauer_s": round(time.perf_counter() - t0, 2),
            "durchdringungen": befunde}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--schwelle", type=float, default=0.001, help="kleinstes gemeldetes Schnittvolumen in mm³")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = check(args.project.resolve(), args.schwelle)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"{out['teile']} Teile, {out['paare_geprueft']} Paare mit überlappenden Hüllquadern, "
              f"{len(out['durchdringungen'])} Durchdringungen ({out['dauer_s']} s)")
        for f in out["durchdringungen"]:
            a, b = f["teile"]
            sx, sy, sz = f["ausdehnung_mm"]
            print(f"- {a} ↔ {b}: {f['volumen_mm3']:.3f} mm³, Ausdehnung {sx} × {sy} × {sz} mm, Mitte {f['mitte']}")
    return 1 if out["durchdringungen"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

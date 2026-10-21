"""Durchdringungen in einem Projekt finden, mit derselben Prüfung wie bei jedem Lauf.

Rechnet das Projekt auf einer Kopie in einer eigenen Kernel-Laufzeit (das Original und die laufende App bleiben
unberührt) und nimmt das Ergebnis der eingebauten Prüfung (``kevcad_kernel.pruefung``): dieselbe Kollisionsfunktion,
dieselben Schwellen (Schnittvolumen über 0,001 mm³ und Tiefe über 0,01 mm, Berühren ist erlaubt), derselbe
Gewindeeingriff (Schraube in Mutter, Einsatz oder Kernloch, metrisch und UNC/UNF) und dieselben Erklärungen aus
model.py (``erlaubt_ueberlappung``). Das Werkzeug meldet also genau, was auch ``run`` meldet, nur ohne App.

Mit `--kontakte` zusätzlich der Kontaktgraph: Teile ohne jeden Kontakt und Gruppen ohne Verbindung zum Boden (schweben).
Mit `--gewinde` die erkannten Gewindeeingriffe und erlaubten Überlappungen einzeln.

Aufruf:  .venv/bin/python tools/check_interference.py <Projektordner> [--kontakte] [--gewinde] [--json]
Exit-Code 1, wenn es Durchdringungen oder schwebende Teile gibt.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app_testutil import FakeApp  # noqa: E402
from build123d import Shape  # noqa: E402
from kevcad_kernel.runtime import KernelRuntime  # noqa: E402

PRUEF_WARTEN_S = 900.0  # so lange wird auf die Prüfung nach dem Lauf gewartet


def overlaps(a, b, tol: float = 1e-6) -> bool:
    amin, amax, bmin, bmax = tuple(a.min), tuple(a.max), tuple(b.min), tuple(b.max)
    return all(amin[i] < bmax[i] - tol and bmin[i] < amax[i] - tol for i in range(3))


def load_project(project: Path) -> tuple[dict[str, Shape], dict[str, Any]]:
    """Projekt auf einer Kopie in einer eigenen Laufzeit rechnen: (exakte Formen aller gezeigten Teile, Ergebnis der
    eingebauten Prüfung wie im Ergebnis von ``run``)."""
    tmp = Path(tempfile.mkdtemp(prefix="kcint", dir="/tmp"))
    copy = tmp / project.name
    shutil.copytree(project, copy, ignore=shutil.ignore_patterns(".kevcad", "output", "__pycache__"))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 0, auto_run=False, run_timeout_s=300)
    rt.pruef_warten_s = PRUEF_WARTEN_S
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
        pruefung = dict(res.get("pruefung") or {})
        app.close()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return shapes, pruefung


def load_shapes(project: Path) -> dict[str, Shape]:
    """Nur die Formen (für check_motion.py)."""
    return load_project(project)[0]


def near(a, b, tol: float) -> bool:
    amin, amax, bmin, bmax = tuple(a.min), tuple(a.max), tuple(b.min), tuple(b.max)
    return all(amin[i] <= bmax[i] + tol and bmin[i] <= amax[i] + tol for i in range(3))


def contacts(shapes: dict, boxes: dict, tol: float, intersecting: set) -> dict:
    """Kontaktgraph: Teile berühren sich, wenn ihr Abstand höchstens `tol` ist (Durchdringungen zählen mit). Teile, die
    die tiefste Ebene der ganzen Baugruppe berühren, stehen auf dem Boden. Gemeldet werden Teile ohne jeden Kontakt und
    Gruppen ohne Verbindung zum Boden (schweben)."""
    names = sorted(shapes)
    z0 = min(boxes[n].min.Z for n in names)
    grounded = {n for n in names if boxes[n].min.Z <= z0 + tol}
    graph: dict[str, set] = {n: set() for n in names}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not near(boxes[a], boxes[b], tol):
                continue
            if (a, b) in intersecting or (b, a) in intersecting or shapes[a].distance_to(shapes[b]) <= tol:
                graph[a].add(b)
                graph[b].add(a)
    seen: set = set()
    groups = []
    for n in names:
        if n in seen:
            continue
        stack, group = [n], set()
        while stack:
            m = stack.pop()
            if m in group:
                continue
            group.add(m)
            stack.extend(graph[m] - group)
        seen |= group
        groups.append(group)
    floating = [sorted(g) for g in groups if not (g & grounded)]
    return {"boden_z": round(z0, 3), "auf_dem_boden": sorted(grounded),
            "ohne_kontakt": [n for n in names if not graph[n] and n not in grounded],
            "schwebende_gruppen": floating}


def auswerten(pruefung: dict[str, Any]) -> dict[str, Any]:
    """Durchdringungen, nachgiebige Verformungen, Gewindeeingriffe und erlaubte Überlappungen aus dem Ergebnis der
    eingebauten Prüfung (``run``-Ergebnis, Feld ``pruefung``)."""
    if pruefung.get("state") != "done":
        raise RuntimeError(f"Prüfung nicht fertig ({pruefung.get('state')}): {pruefung.get('message') or ''}")

    def eintrag(b: dict[str, Any]) -> dict[str, Any]:
        w = b.get("wert") or {}
        return {"teile": list(b["teile"][:2]), "volumen_mm3": w.get("volumen"), "tiefe_mm": w.get("tiefe"),
                "ort": b.get("ort"), "schwere": b.get("schwere"), "text": b.get("text"), "loesung": b.get("loesung")}

    befunde = pruefung.get("befunde") or []
    durch = sorted((eintrag(b) for b in befunde if b.get("art") == "durchdringung"),
                   key=lambda f: -(f["volumen_mm3"] or 0.0))
    verformt = [eintrag(b) for b in befunde if b.get("art") == "verformt"]
    stat = pruefung.get("statistik") or {}
    return {"teile": stat.get("teile"), "paare_geprueft": (stat.get("paare") or {}).get("geprueft"),
            "durchdringungen": durch, "verformt": verformt, "gewinde": list(pruefung.get("gewinde") or []),
            "erlaubt": list(pruefung.get("erlaubt") or []), "zusammenfassung": pruefung.get("zusammenfassung") or "",
            "pruef_ms": pruefung.get("duration_ms")}


def check(project: Path, kontakt_tol: float | None = None) -> dict:
    t0 = time.perf_counter()
    shapes, pruefung = load_project(project)
    out = auswerten(pruefung)
    if kontakt_tol is not None:
        boxes = {n: shapes[n].bounding_box() for n in shapes}
        out["kontakte"] = contacts(shapes, boxes, kontakt_tol, {tuple(f["teile"]) for f in out["durchdringungen"]})
    out["dauer_s"] = round(time.perf_counter() - t0, 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--kontakte", nargs="?", const=0.5, type=float, metavar="TOL",
                    help="zusätzlich Kontaktgraph: Teile ohne Kontakt und schwebende Gruppen (Toleranz mm, Standard 0,5: Spielpassungen zählen als Verbindung)")
    ap.add_argument("--gewinde", action="store_true", help="Gewindeeingriffe und erlaubte Überlappungen einzeln zeigen")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = check(args.project.resolve(), args.kontakte)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"{out['teile']} Teile, {out['paare_geprueft']} Paare mit Kontakt oder Überlappung, "
              f"{len(out['durchdringungen'])} Durchdringungen, {len(out['gewinde'])} Gewindeeingriffe, "
              f"{len(out['erlaubt'])} erlaubte Überlappungen (eingebaute Prüfung, {out['dauer_s']} s)")
        for f in out["durchdringungen"]:
            a, b = f["teile"]
            print(f"- {a} ↔ {b}: {f['volumen_mm3']} mm³, Tiefe {f['tiefe_mm']} mm, bei {f['ort']}")
            if f.get("loesung"):
                print(f"  Lösung: {f['loesung']}")
        for f in out["verformt"]:
            print(f"- nachgiebig ({f['schwere']}): {f['text']}")
        if args.gewinde:
            for g in out["gewinde"]:
                print(f"- Gewinde: {g.get('text')}")
            for e in out["erlaubt"]:
                print(f"- erlaubt: {' ↔ '.join(e.get('teile') or [])} ({e.get('grund')})")
        k = out.get("kontakte")
        if k is not None:
            print(f"Boden bei z = {k['boden_z']} mm, {len(k['auf_dem_boden'])} Teile stehen darauf")
            for n in k["ohne_kontakt"]:
                print(f"- ohne Kontakt zu irgendetwas: {n}")
            for g in k["schwebende_gruppen"]:
                print(f"- schwebt (keine Verbindung zum Boden): {', '.join(g[:6])}{' …' if len(g) > 6 else ''}")
    bad = out["durchdringungen"] or (out.get("kontakte") or {}).get("schwebende_gruppen")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

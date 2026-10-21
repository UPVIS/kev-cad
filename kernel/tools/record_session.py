"""Einen echten Lauf aufzeichnen, so wie die App ihn vom Kernel bekommt (für VoiceBridge und den Spiegel-Simulator).

Kopiert das Projekt in einen Temp-Ordner (das Original bleibt unberührt), startet eine eigene Kernel-Laufzeit an einem
eigenen Socket, verbindet sich als Test-App, öffnet das Projekt, rechnet einmal und schreibt alle empfangenen Rahmen
hintereinander in eine Datei. Format je Rahmen wie im Kernel-Protokoll (u32 LE Kopf, JSON, u32 LE Nutzlast, Nutzlast);
jeder Kopf trägt zusätzlich `rec_t_ms`, die Empfangszeit in ms seit dem Verbinden.

Aufruf:  .venv/bin/python tools/record_session.py <Projektordner> <Ausgabe.kcadrec> [--slow-ms 0]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app_testutil import FakeApp  # noqa: E402
from kevcad_kernel.protocol import encode_frame  # noqa: E402
from kevcad_kernel.runtime import KernelRuntime  # noqa: E402


def record(project: Path, out: Path, slow_ms: int = 0) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="kcrec", dir="/tmp"))
    copy = tmp / project.name
    shutil.copytree(project, copy, ignore=shutil.ignore_patterns(".kevcad", "output", "__pycache__"))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 0, auto_run=False, run_timeout_s=300)
    try:
        if not rt.wait_worker_ready(240):
            raise RuntimeError("Rechenprozess nicht bereit")
        app = FakeApp(sock)
        t0 = time.perf_counter()
        app.wait_for(lambda h: h["type"] == "HELLO")
        res = rt.project_open(str(copy))
        if not res.get("ok"):
            raise RuntimeError(f"Projekt lässt sich nicht öffnen: {res}")
        start = app.mark()
        res = rt.run(slow_ms=slow_ms, timeout_s=300)
        if not res.get("ok"):
            raise RuntimeError(f"Lauf fehlgeschlagen: {res.get('error')}")
        app.wait_for(lambda h: h["type"] == "RUN_END", start=start, timeout=300)
        try:  # die Stückliste kommt gleich nach RUN_END
            app.wait_for(lambda h: h["type"] == "BOM", start=start, timeout=5)
        except AssertionError:
            pass
        time.sleep(0.3)
        with app.cond:
            frames = list(app.frames)
        app.close()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        for t, header, payload in frames:
            f.write(encode_frame({**header, "rec_t_ms": round((t - t0) * 1000.0, 1)}, payload))
    parts = [h for _, h, _ in frames if h["type"] == "PART_UPSERT"]
    return {"frames": len(frames), "parts": len({h["name"] for h in parts}),
            "triangles": sum(h["counts"]["tri"] for h in parts), "bytes": out.stat().st_size}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--slow-ms", type=int, default=0, help="Zeitlupe je show() in ms (0 = normal)")
    args = ap.parse_args()
    info = record(args.project.resolve(), args.out.resolve(), args.slow_ms)
    print(f"{args.out.name}: {info['frames']} Rahmen, {info['parts']} Teile, {info['triangles']} Dreiecke, "
          f"{info['bytes'] / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

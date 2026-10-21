"""Leistungstest mit der Beelonia-Outdoorküche über die volle Laufzeit (als slow markiert).

Ein temporäres model.py lädt ``kueche.py`` per sys.path, baut ``kueche(P, True, "winkel")`` und zeigt alle Blätter
mit show(). Gemessen werden der erste Lauf, das Neu-Rechnen ohne Änderung (Zwischenspeicher) und die Zeit bis zum
ersten Teil in der App. Auslassen mit ``pytest -m "not slow"``.
"""

import shutil
import tempfile
import time
import warnings
from pathlib import Path

import pytest

from app_testutil import FakeApp

from kevcad_kernel.runtime import KernelRuntime

with warnings.catch_warnings():  # Markierung ohne Eintrag in pyproject.toml (gehört allen Strängen)
    warnings.simplefilter("ignore")
    slow = pytest.mark.slow

KUECHE = Path("/Users/kevinschwed/Code Experiments/Beelonia/cad/outdoor-kueche")

MODEL = f'''import sys
sys.path.insert(0, {str(KUECHE)!r})
import kueche
from kevcad import show, step

step("Küche bauen")
k = kueche.kueche(kueche.P, True, "winkel")
step("Teile zeigen")
gesehen = {{}}
for blatt in k.leaves:
    name = "/".join((n.label or "Teil").replace("/", "-") for n in blatt.path[1:])
    gesehen[name] = gesehen.get(name, 0) + 1
    show(blatt, name if gesehen[name] == 1 else f"{{name}} {{gesehen[name]}}")
'''


@slow
@pytest.mark.skipif(not (KUECHE / "kueche.py").exists(), reason="Beelonia-Küche nicht vorhanden")
def test_kueche_performance(record_property):
    tmp = Path(tempfile.mkdtemp(prefix="kc"))
    sock = str(tmp / "k.sock")
    rt = KernelRuntime(sock, 0, auto_run=False, run_timeout_s=170)
    try:
        assert rt.wait_worker_ready(240)
        app = FakeApp(sock)
        app.wait_for(lambda h: h["type"] == "HELLO")
        assert rt.project_new(str(tmp / "Kueche"), "empty")["ok"]
        # Nachbau aus Fotos: Kevin schaltet die Inventar-Regel für solche Projekte ab
        (tmp / "Kueche" / "kevcad.json").write_text('{"version": 1, "inventar_regel": false}')
        assert rt.model_write(MODEL)["ok"]

        start = app.mark()
        t0 = time.perf_counter()
        first = rt.run(timeout_s=170)
        t_first = time.perf_counter() - t0
        assert first["ok"], first.get("error")
        _, t_start, _, _ = app.wait_for(lambda h: h["type"] == "RUN_START", start=start)
        _, t_part, _, _ = app.wait_for(lambda h: h["type"] == "PART_UPSERT", start=start)
        _, t_build, _, _ = app.wait_for(lambda h: h["type"] == "STEP" and h["text"] == "Teile zeigen", start=start)
        _, t_end, end, _ = app.wait_for(lambda h: h["type"] == "RUN_END", start=start)

        t0 = time.perf_counter()
        second = rt.run(timeout_s=170)
        t_second = time.perf_counter() - t0
        assert second["ok"]

        parts = first["parts"]
        stats = {
            "teile": len(parts),
            "dreiecke": sum(p["triangles"] for p in parts),
            "flaechen": sum(p["faces"] for p in parts),
            "kanten": sum(p["edges"] for p in parts),
            "lauf1_s": round(t_first, 2),
            "lauf1_tess_s": round(first["tess_ms"] / 1000, 2),
            "modell_bauen_s": round(t_build - t_start, 2),
            "erstes_teil_nach_bauen_ms": round((t_part - t_build) * 1000, 1),
            "teile_streamen_s": round(t_end - t_build, 2),
            "lauf2_s": round(t_second, 2),
            "lauf2_tess_s": round(second["tess_ms"] / 1000, 3),
            "lauf2_aus_zwischenspeicher": f"{second['cached_parts']}/{len(second['parts'])}",
        }
        for k, v in stats.items():
            record_property(k, v)
        print("\nKüche:", stats)

        assert len(parts) >= 59
        assert end["parts"] == len(parts) and end["triangles"] == stats["dreiecke"]
        assert second["cached_parts"] == len(second["parts"])
        assert second["tess_ms"] < first["tess_ms"] / 5
        # Nummerierung im Elternprozess (Referenzen) passt zu den Zählern aus der Tessellierung, für jedes Teil
        for rec in rt.scene.records():
            assert len(rec.elements("f")) == rec.counts["face"], rec.name
            assert len(rec.elements("e")) == rec.counts["edge"], rec.name
            assert len(rec.elements("v")) == rec.counts["vtx"], rec.name
        app.close()
    finally:
        rt.close()
        shutil.rmtree(tmp, ignore_errors=True)

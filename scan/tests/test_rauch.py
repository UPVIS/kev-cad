"""Rauchtests von kevscan: synthetischer Scan (klein) bis Netz, ZIP-Prüfung, PromptDA Small (wenn geladen)."""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from kevscan import format as fmt


def test_synth_bis_netz_ohne_promptda(tmp_path):
    from kevscan.auswerten import Auswertung
    from kevscan.synth import erzeuge

    erzeuge(tmp_path, fotos=4, video=10, breite=640, hoehe=480, zip_auch=True)
    ereignisse = []
    bericht = Auswertung(tmp_path / "Quader.kevscan.zip", tmp_path / "aus", ohne_promptda=True,
                         melde=ereignisse.append).lauf()
    b = json.loads(bericht.read_text())
    assert abs(b["grundriss_mm"]["laenge"] - 200) < 12 and abs(b["grundriss_mm"]["breite"] - 100) < 12
    assert abs(b["huellmass_mm"]["hoehe"] - 50) < 8
    assert b["bilder"]["fotos"] == 4 and b["bilder"]["gesamt"] >= 6
    kam = json.loads((tmp_path / "aus" / "kameras.json").read_text())
    assert len(kam["bilder"]) == b["bilder"]["gesamt"]
    for e in kam["bilder"]:
        assert (tmp_path / "aus" / e["bild"]).is_file() and (tmp_path / "aus" / e["maske"]).is_file()
    posen = json.loads((tmp_path / "aus" / "poses.json").read_text())
    assert posen["format"] == "kevcad-capture/poses" and "opencv" in posen["cameras"][0]["aligned"]
    assert ereignisse[-1]["gesamt"] == 1.0 and all(e["event"] == "progress" for e in ereignisse)


def test_zip_mit_pfad_nach_aussen(tmp_path):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("x.kevscan/meta.json", "{}")
        z.writestr("../raus.txt", "x")
    (tmp_path / "a.zip").write_bytes(puffer.getvalue())
    with pytest.raises(fmt.ScanFehler):
        fmt.entpacken(tmp_path / "a.zip", tmp_path / "ziel")
    assert not (tmp_path / "raus.txt").exists()


def test_promptda_small(tmp_path):
    from kevscan.tiefe import Tiefenschaetzer, gewichte

    if gewichte("small", laden=False) is None:
        pytest.skip("Gewichte von PromptDA Small nicht im Zwischenspeicher")
    s = Tiefenschaetzer("small")
    bild = (np.random.default_rng(1).random((480, 640, 3)) * 255).astype(np.uint8)
    lidar = np.full((192, 256), 800, np.uint16)
    lidar[:, 128:] = 1200
    konf = np.full((192, 256), 2, np.uint8)
    konf[:10] = 0
    tiefe, k = s.schaetze(bild, lidar, konf)
    assert tiefe.shape == (476, 630) and k.shape == tiefe.shape
    assert (k[:20] == 0).all() and (tiefe[:20] == 0).all()  # Konfidenz 0 maskiert
    mitte = tiefe[200:300]
    assert 700 < np.median(mitte[:, :250]) < 900 and 1100 < np.median(mitte[:, 400:]) < 1300

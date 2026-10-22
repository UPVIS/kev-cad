"""CAD-Quellen der Zukaufteile ohne Netz: Deep-Links (keine automatische Quelle, die TraceParts-API ist seit dem
22.10.2026 stillgelegt), Downloads-Ordner und ZIP (Temp-Ordner statt ~/Downloads)."""

import os
import time
import zipfile
from pathlib import Path

import pytest

from kevcad_kernel.zukauf import downloads as dl
from kevcad_kernel.zukauf import quellen

STEP_KOPF = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def test_cad_links():
    links = quellen.cad_links({"hersteller": "igus", "mpn": "GFM-1012-10", "url": "https://www.igus.example/p/gfm"})
    titles = [link["titel"] for link in links]
    assert titles[0] == "Produktseite (CAD-Download oft dort)" and titles[1].startswith("igus: CAD zu GFM-1012-10")
    assert any(t.startswith("3Dfindit") for t in titles)
    assert not any("traceparts" in (link["titel"] + link["url"]).lower() for link in links)
    assert links[-1]["url"].startswith("https://duckduckgo.com/?q=igus+GFM-1012-10+STEP")
    mc = quellen.cad_links({"hersteller": "McMaster-Carr", "mpn": "91251A540"})
    assert mc[0]["url"] == "https://www.mcmaster.com/91251A540/"


# ------------------------------------------------------------------------------------------------------ Downloads


def _datei(path: Path, inhalt: bytes, alter_s: float = 0) -> Path:
    path.write_bytes(inhalt)
    t = time.time() - alter_s
    os.utime(path, (t, t))
    return path


def test_downloads_kandidaten_und_wahl(tmp_path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    monkeypatch.setenv("KEVCAD_DOWNLOADS_DIR", str(d))
    _datei(d / "alt.step", STEP_KOPF, alter_s=3600)
    _datei(d / "05200_rollwagen.STEP", STEP_KOPF, alter_s=60)
    _datei(d / "anderes.stp", STEP_KOPF, alter_s=10)
    _datei(d / "halb.step.crdownload", STEP_KOPF)
    _datei(d / "bild.png", b"png")
    files = dl.kandidaten(dl.downloads_dir(), 30)
    assert [p.name for p in files] == ["anderes.stp", "05200_rollwagen.STEP"]
    assert dl.waehlen(files, {"id": "alutec-05200", "mpn": "05200"}).name == "05200_rollwagen.STEP"
    assert dl.waehlen(files, {"id": "x", "mpn": "999"}).name == "anderes.stp"  # sonst die neueste
    out, _ = dl.uebernehmen(files[1], tmp_path / "ziel", {"mpn": "05200"})
    assert out.name == "05200_rollwagen.step" and out.read_bytes() == STEP_KOPF
    with pytest.raises(dl.DownloadFehler, match="keine STEP-Datei"):
        dl.uebernehmen(_datei(d / "falsch.step", b"kein step"), tmp_path / "ziel", {})


def test_zip_sicher_entpacken(tmp_path):
    z = tmp_path / "cad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "x")
        zf.writestr("models/klein.step", STEP_KOPF)
        zf.writestr("models/ALUTEC_05200.stp", STEP_KOPF + b"x" * 10)
        zf.writestr("../../boese.step", STEP_KOPF + b"y" * 100)
        zf.writestr("__MACOSX/models/._ALUTEC_05200.stp", b"mac")
    out, hinweise = dl.uebernehmen(z, tmp_path / "ziel", {"mpn": "05200"})
    assert out == tmp_path / "ziel" / "ALUTEC_05200.stp" and out.is_file()
    assert hinweise == ["cad.zip enthält 2 STEP-Dateien; übernommen: ALUTEC_05200.stp"]
    assert not (tmp_path / "boese.step").exists() and not list(tmp_path.glob("**/boese.step"))
    nur_iges = tmp_path / "iges.zip"
    with zipfile.ZipFile(nur_iges, "w") as zf:
        zf.writestr("teil.igs", "x")
    with pytest.raises(dl.DownloadFehler, match=r"keine STEP-Datei \(nur \.igs\): im Portal das Format STEP"):
        dl.uebernehmen(nur_iges, tmp_path / "ziel", {})

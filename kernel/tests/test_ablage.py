"""Projektablage (PLAN-IPAD.md, I-7): Schalter für den Projektordner und interne Daten lokal bei Projekten in der iCloud.

Die iCloud wird nur nachgestellt: Ein Ordner mit „/Library/Mobile Documents/“ im Pfad unter tmp_path gilt als iCloud.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kevcad_kernel import ablage
from kevcad_kernel.project import new_project, open_project
from kevcad_kernel.versionen.git import GitRepo


@pytest.fixture
def wolke(tmp_path: Path) -> Path:
    ordner = tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Kev CAD"
    ordner.mkdir(parents=True)
    return ordner


def test_projects_dir_umgebung_geht_vor(tmp_path, monkeypatch):
    (tmp_path / ablage.SCHALTER).write_text(json.dumps({"ort": "icloud"}), encoding="utf-8")
    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(tmp_path / "eigen"))
    assert ablage.projects_dir(tmp_path) == tmp_path / "eigen"


def test_projects_dir_schalter(tmp_path, monkeypatch):
    monkeypatch.delenv("KEVCAD_PROJECTS_DIR", raising=False)
    assert ablage.projects_dir(tmp_path) == ablage.LOKAL_ORDNER  # ohne Datei: wie bisher
    (tmp_path / ablage.SCHALTER).write_text(json.dumps({"ort": "icloud"}), encoding="utf-8")
    assert ablage.projects_dir(tmp_path) == ablage.ICLOUD_ORDNER
    (tmp_path / ablage.SCHALTER).write_text(json.dumps({"ordner": str(tmp_path / "x")}), encoding="utf-8")
    assert ablage.projects_dir(tmp_path) == tmp_path / "x"
    (tmp_path / ablage.SCHALTER).write_text("kaputt", encoding="utf-8")
    assert ablage.projects_dir(tmp_path) == ablage.LOKAL_ORDNER


def test_in_icloud():
    assert ablage.in_icloud(ablage.ICLOUD_ORDNER / "Wandhalter")
    assert ablage.in_icloud("~/Library/Mobile Documents/iCloud~de~upvis~kevcad/Documents/A")
    assert not ablage.in_icloud(ablage.LOKAL_ORDNER / "Wandhalter")


def test_neues_projekt_in_der_icloud_haelt_daten_lokal(wolke):
    proj = new_project(wolke / "Halter")
    link = proj.path / ".kevcad"
    assert link.is_symlink() and link.resolve() == (proj.path / ".kevcad.nosync").resolve()
    assert (proj.path / ".kevcad.nosync" / "log").is_dir()  # Kernel schreibt wie gewohnt über .kevcad/
    assert not proj.warnings


def test_vorhandene_daten_ziehen_mit_um(wolke):
    p = wolke / "Alt"
    (p / ".kevcad" / "log").mkdir(parents=True)
    (p / ".kevcad" / "log" / "runs.jsonl").write_text("{}\n", encoding="utf-8")
    (p / "model.py").write_text("x = 1\n", encoding="utf-8")
    open_project(p)
    assert (p / ".kevcad").is_symlink()
    assert (p / ".kevcad.nosync" / "log" / "runs.jsonl").read_text(encoding="utf-8") == "{}\n"
    open_project(p)  # zweites Öffnen ändert nichts
    assert (p / ".kevcad").is_symlink()


def test_zweiter_mac_bekommt_nur_den_link(wolke):
    p = wolke / "Geteilt"
    p.mkdir()
    (p / "model.py").write_text("x = 1\n", encoding="utf-8")
    (p / ".kevcad").symlink_to(".kevcad.nosync", target_is_directory=True)  # so kommt es aus der iCloud an
    open_project(p)
    assert (p / ".kevcad" / ".").is_dir()


def test_beide_ordner_vorhanden_gibt_hinweis(wolke):
    p = wolke / "Doppelt"
    (p / ".kevcad").mkdir(parents=True)
    (p / ".kevcad.nosync").mkdir()
    (p / "model.py").write_text("x = 1\n", encoding="utf-8")
    proj = open_project(p)
    assert any(".kevcad.nosync" in w for w in proj.warnings)
    assert (p / ".kevcad").is_dir() and not (p / ".kevcad").is_symlink()


def test_projekt_ausserhalb_der_icloud_bleibt_wie_es_ist(tmp_path):
    proj = new_project(tmp_path / "Lokal")
    assert (proj.path / ".kevcad").is_dir() and not (proj.path / ".kevcad").is_symlink()
    assert not (proj.path / ".kevcad.nosync").exists()


def test_versionen_erfassen_link_und_lokale_daten_nicht(wolke):
    proj = new_project(wolke / "Versioniert")
    repo = GitRepo(proj.path)
    repo.init()
    pfade = {p for _, p in repo.status()}
    assert "model.py" in pfade
    assert not any(p.startswith(".kevcad") for p in pfade), pfade


def test_blosser_name_landet_im_projektordner(tmp_path, monkeypatch):
    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(tmp_path))
    assert ablage.aufloesen("Halter") == str(tmp_path / "Halter")
    (tmp_path / "Halter").mkdir()
    assert ablage.aufloesen("Halter", neu=True) == str(tmp_path / "Halter")  # leerer Ordner taugt
    (tmp_path / "Halter" / "model.py").write_text("x = 1\n", encoding="utf-8")
    assert ablage.aufloesen("Halter", neu=True) == str(tmp_path / "Halter 2")
    assert ablage.aufloesen("Halter") == str(tmp_path / "Halter")  # Öffnen nimmt den Namen, wie er ist
    assert ablage.aufloesen("~/x") == "~/x" and ablage.aufloesen("/a/b") == "/a/b"


def test_neues_projekt_vom_ipad_ueber_den_kernel(tmp_path, monkeypatch):
    """PROJECT_NEW mit bloßem Namen (vom iPad): Ordner im Projektordner des Mac, bei Kollision mit Nummer."""
    from types import SimpleNamespace

    from kevcad_kernel.runtime import KernelRuntime

    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(tmp_path))
    rt = SimpleNamespace(_set_project=lambda proj, reply_to: None)
    a = KernelRuntime.project_new(rt, "Strebe", "empty", reply_to="r1")
    b = KernelRuntime.project_new(rt, "Strebe", "empty", reply_to="r2")
    assert a["ok"] and b["ok"], (a, b)
    assert Path(a["path"]).name == "Strebe" and Path(b["path"]).name == "Strebe 2"
    assert KernelRuntime.project_open(rt, "Strebe 2", reply_to="r3")["ok"]


def _mit_versionen(p: Path) -> GitRepo:
    repo = GitRepo(p)
    repo.init()
    for i in range(3):
        (p / "model.py").write_text(f"x = {i}\n", encoding="utf-8")
        repo.bereite_vor()
        repo.commit(f"Stand {i}")
    index = p / ".kevcad" / "versionen" / "index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('{"versionen": {"3": {"meilenstein": {"titel": "Fertig"}}}}', encoding="utf-8")
    return repo


def test_meilenstein_sichert_vorschau_und_versionen(wolke, tmp_path):
    proj = new_project(wolke / "Gesichert")
    repo = _mit_versionen(proj.path)
    bild = tmp_path / "3.png"
    bild.write_bytes(b"\x89PNG-test")
    assert ablage.icloud_sichern(proj.path, bild) == [ablage.VORSCHAU, ablage.BUNDLE]
    assert (proj.path / ablage.VORSCHAU).read_bytes() == b"\x89PNG-test"
    assert (proj.path / ablage.BUNDLE).stat().st_size > 0
    assert not list(proj.path.glob(".*.tmp"))
    assert not any(p.startswith(("vorschau", "versionen")) for _, p in repo.status())  # nicht in den Versionen

    # Ein anderer Mac bekommt aus der iCloud nur Dateien, den Link und die Sicherung, nicht .kevcad.nosync
    anders = wolke / "Anderer Mac" / "Gesichert"
    anders.mkdir(parents=True)
    for name in ("model.py", "kevcad.json", ablage.VORSCHAU, ablage.BUNDLE):
        (anders / name).write_bytes((proj.path / name).read_bytes())
    (anders / ".kevcad").symlink_to(".kevcad.nosync", target_is_directory=True)
    neu = open_project(anders)
    assert not neu.warnings, neu.warnings
    zurueck = GitRepo(anders)
    assert zurueck.head() == repo.head()
    assert zurueck.zweig() == repo.zweig()
    assert len(zurueck.log(repo.zweig())) == len(repo.log(repo.zweig()))
    assert "Fertig" in (anders / ".kevcad" / "versionen" / "index.json").read_text(encoding="utf-8")
    assert zurueck.status() == []  # Index passt zu den Dateien im Projekt


def test_kopie_ohne_kevcad_holt_versionen_aus_der_sicherung(wolke, tmp_path):
    proj = new_project(wolke / "Quelle")
    repo = _mit_versionen(proj.path)
    ablage.icloud_sichern(proj.path)
    kopie = wolke / "Kopie"
    kopie.mkdir()
    for name in ("model.py", "kevcad.json", ablage.BUNDLE):
        (kopie / name).write_bytes((proj.path / name).read_bytes())
    open_project(kopie)  # kein .kevcad: Link und lokale Daten entstehen, Versionen aus der Sicherung
    assert GitRepo(kopie).head() == repo.head()


def test_lokales_projekt_bleibt_ohne_sicherung(tmp_path):
    proj = new_project(tmp_path / "Lokal")
    _mit_versionen(proj.path)
    bild = tmp_path / "1.png"
    bild.write_bytes(b"png")
    assert ablage.icloud_sichern(proj.path, bild) == []
    assert not (proj.path / ablage.VORSCHAU).exists() and not (proj.path / ablage.BUNDLE).exists()


def test_meilenstein_ruft_die_sicherung(wolke):
    """Laufzeit: Nach dem Vorschaubild des Meilensteins sichert sie Projekte in der iCloud (Fehler nur ins Protokoll)."""
    import threading
    from types import SimpleNamespace

    from kevcad_kernel.versionen.laufzeit import VersionenRuntimeMixin

    proj = new_project(wolke / "Laufzeit")
    _mit_versionen(proj.path)
    ordner = proj.path / ".kevcad" / "versionen"
    (ordner / "bilder").mkdir(parents=True, exist_ok=True)
    (ordner / "bilder" / "3.png").write_bytes(b"bild")
    protokoll: list[str] = []
    selbst = SimpleNamespace(_log=protokoll.append)
    archiv = SimpleNamespace(projekt=proj.path, ordner=ordner, lock=threading.RLock())
    VersionenRuntimeMixin._icloud_sichern(selbst, archiv, SimpleNamespace(nr=3))
    assert (proj.path / ablage.VORSCHAU).read_bytes() == b"bild"
    assert any("versionen.bundle" in z for z in protokoll), protokoll

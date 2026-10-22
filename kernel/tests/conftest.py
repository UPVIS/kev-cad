"""Gemeinsame Einstellungen für alle Kernel-Tests.

Der eigene Katalog (sonst ``~/Library/Application Support/de.upvis.kevcad/katalog``) zeigt in allen Tests auf einen
leeren Temp-Ordner, damit kein Test Kevins Katalog liest oder schreibt. Wird vor dem Sammeln der Tests gesetzt, also
auch für Rechenprozesse, die Tests starten.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_OWN = Path(tempfile.mkdtemp(prefix="kc-katalog-"))
os.environ["KEVCAD_CATALOG_DIR"] = str(_OWN)

TEST_CATALOG = Path(__file__).resolve().parent / "katalog_test"

# Druckvorschau (DRUCKVORSCHAU.md): Zwischenspeicher und Abgleich in einem Temp-Ordner, Bambu Studio im Hintergrund aus,
# damit kein Test Kevins abgleich.json schreibt oder nebenbei slict; test_druck_slicer.py schaltet es selbst ein.
_DRUCK = Path(tempfile.mkdtemp(prefix="kc-druck-"))
os.environ["KEVCAD_DRUCK_CACHE"] = str(_DRUCK / "cache")
os.environ["KEVCAD_DRUCK_ABGLEICH"] = str(_DRUCK / "abgleich.json")
os.environ["KEVCAD_BAMBU_APP"] = str(_DRUCK / "kein-bambu-studio.app")
# Statik Stufe 3: Zwischenspeicher der Festkörper-FEM (Netze, Fälle) nie in Kevins ~/Library/Caches
os.environ["KEVCAD_FESTKOERPER_CACHE"] = str(_DRUCK / "festkoerper")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_OWN, ignore_errors=True)
    shutil.rmtree(_DRUCK, ignore_errors=True)


@pytest.fixture
def own_catalog_dir(tmp_path, monkeypatch):
    """Eigener Katalog in einem frischen Temp-Ordner (je Test)."""
    d = tmp_path / "eigen"
    d.mkdir()
    monkeypatch.setenv("KEVCAD_CATALOG_DIR", str(d))
    return d

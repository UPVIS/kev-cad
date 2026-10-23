"""Hilfsmodule neben model.py werden vor jedem Lauf neu geladen, auch in Paketen ohne __init__.py (KevCup, 23.10.2026)."""

from __future__ import annotations

import importlib
import sys

from kevcad_kernel.runner import _purge_user_modules


def _schreibe(pfad, text):
    pfad.write_text(text, encoding="utf-8")
    importlib.invalidate_caches()


def test_namespace_paket_wird_neu_geladen(tmp_path):
    (tmp_path / "geometrie").mkdir()
    datei = tmp_path / "geometrie" / "teil_ns.py"
    _schreibe(datei, "A = 1\n")
    sys.path.insert(0, str(tmp_path))
    try:
        from geometrie import teil_ns  # noqa: PLC0415 - Import gehört zum Test
        assert teil_ns.A == 1 and not hasattr(teil_ns, "FK_H")
        _schreibe(datei, "A = 1\nFK_H = 42.0  # neue Funktion bzw. Konstante\n")
        _purge_user_modules()
        assert "geometrie" not in sys.modules and "geometrie.teil_ns" not in sys.modules
        from geometrie import teil_ns as neu  # noqa: PLC0415
        assert neu.FK_H == 42.0
    finally:
        sys.path.remove(str(tmp_path))
        for n in [n for n in sys.modules if n == "geometrie" or n.startswith("geometrie.")]:
            sys.modules.pop(n, None)


def test_bibliotheken_bleiben_geladen():
    import build123d  # noqa: F401, PLC0415

    _purge_user_modules()
    assert "build123d" in sys.modules

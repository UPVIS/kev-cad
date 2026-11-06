"""Keine Textdatei und keine Prozessausgabe ohne feste Kodierung (V2-8).

lib3mf stellt beim Schreiben einer 3MF den ganzen Prozess auf die Locale ``C`` um (build123d, Mesher). Danach liest
Python alles ohne ``encoding`` als ASCII: So scheiterten am 05.11.2026 im vollen Testlauf am MacBook 16 CalculiX-Tests an
einem ``UnicodeDecodeError``, nachdem ein Drucktest eine 3MF geschrieben hatte. Einzeln liefen sie durch, und auf dem Mac
mini setzt ``tools/fern/mini.sh`` ``PYTHONUTF8=1``. Der Kernel soll sich nicht auf die Umgebung verlassen."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUELLEN = [REPO / "kernel/src", REPO / "kernel/tools", REPO / "fotomess/src", REPO / "scan/src"]
# Module, die `open` anbieten und selbst Binärdaten liefern
FREMD = {"os", "Image", "gzip", "tarfile", "zipfile", "webbrowser", "io", "zf"}


def verstoesse(text: str) -> list[int]:
    """Zeilen, in denen Text ohne ``encoding`` gelesen oder geschrieben wird."""
    zeilen = []
    for n in ast.walk(ast.parse(text)):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        kw = {k.arg: k.value for k in n.keywords}
        if "encoding" in kw:
            continue
        if name == "read_text" and not n.args or name == "write_text" and len(n.args) == 1:
            zeilen.append(n.lineno)
        elif name == "open" and not (isinstance(f, ast.Attribute) and getattr(f.value, "id", "") in FREMD):
            modus = kw.get("mode", (n.args[1] if len(n.args) >= 2 else None) if isinstance(f, ast.Name)
                           else (n.args[0] if n.args else None))
            wert = modus.value if isinstance(modus, ast.Constant) else ("r" if modus is None else None)
            if wert is not None and "b" not in wert:
                zeilen.append(n.lineno)
        elif name in ("run", "Popen", "check_output", "check_call"):
            text_an = kw.get("text") or kw.get("universal_newlines")
            if text_an is not None and not (isinstance(text_an, ast.Constant) and text_an.value is False):
                zeilen.append(n.lineno)
    return zeilen


def test_erkennt_fehlende_kodierung():
    assert verstoesse('open("a")\nPath("b").read_text()\nsubprocess.run(["x"], text=True)\n') == [1, 2, 3]
    assert verstoesse('open("a", "rb")\nPath("b").read_text(encoding="utf-8")\nzf.open("c")\n') == []


@pytest.mark.parametrize("wurzel", QUELLEN, ids=lambda p: str(p.relative_to(REPO)))
def test_feste_kodierung_in_allen_quellen(wurzel):
    offen = [f"{p.relative_to(REPO)}:{z}" for p in sorted(wurzel.rglob("*.py")) if ".venv" not in p.parts
             for z in verstoesse(p.read_text(encoding="utf-8"))]
    assert not offen, "ohne encoding: " + ", ".join(offen)

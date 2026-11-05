"""Schreibt skill/kev-cad/werkzeuge.md aus den Werkzeugen selbst (Kernsatz mit Parametern, Fachwerkzeuge mit Aktionen,
Zuordnung der bisherigen Namen). Aufruf aus dem Repo: kernel/.venv/bin/python kernel/tools/skill_werkzeuge.py"""

from __future__ import annotations

import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parents[2] / "skill" / "kev-cad" / "werkzeuge.md"


def main() -> int:
    from kevcad_kernel.mcp_tools.zuordnung import werkzeuge_md

    text = werkzeuge_md()
    ZIEL.write_text(text, encoding="utf-8")
    print(f"{ZIEL}: {len(text)} Zeichen")
    return 0


if __name__ == "__main__":
    sys.exit(main())

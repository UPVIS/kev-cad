"""Sammelt die Bedingungen eines Laufs (Rechenprozess) und findet die Zeile in model.py, in der sie entstanden.

Der Lauf (runner.py) legt je Lauf eine ``Sammlung`` an und hängt sie als ``kevcad._hooks["bedingungen"]`` ein. Jede
Bedingung, jede Platzierung und jede Parametergrenze meldet sich dort an. Außerhalb des Kernels (Python direkt, Tests)
gibt es keine Sammlung; ``sammeln()`` stellt eine bereit.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_EIGENE = tuple(os.path.realpath(p) for p in (
    os.path.join(os.path.dirname(__file__), ".."),  # kevcad_kernel
    os.path.join(os.path.dirname(__file__), "..", "..", "kevcad"),
))


def _eigen(dateiname: str) -> bool:
    real = os.path.realpath(dateiname)
    return any(real.startswith(d + os.sep) for d in _EIGENE)


def aufrufstelle() -> tuple[str | None, int | None]:
    """(Dateiname, Zeile) des ersten Aufrufers außerhalb von kevcad und kevcad_kernel (meist model.py)."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if not name.startswith("<") and not _eigen(name) and "/build123d/" not in name:
            return os.path.basename(name), frame.f_lineno
        if name.startswith("<execute>") or name.startswith("<string>"):
            return name, frame.f_lineno
        frame = frame.f_back
    return None, None


@dataclass
class ParamGrenze:
    name: str
    wert: Any
    min: float | None
    max: float | None
    datei: str | None = None
    zeile: int | None = None


@dataclass
class Sammlung:
    bedingungen: list[Any] = field(default_factory=list)
    platzierungen: list[Any] = field(default_factory=list)
    grenzen: list[ParamGrenze] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    gezeigt: dict[str, Any] = field(default_factory=dict)  # Name → Form oder (Form, Vernetzung), vom Lauf gefüllt
    aufgeloest: dict[str, Any] = field(default_factory=dict)  # Bedingung → (A, B) in der gezeigten Lage (Prüfung)

    def gezeigte_form(self, name: str) -> Any:
        """Zuletzt gezeigte Form unter diesem Namen (für Bezüge über den Namen) oder None."""
        eintrag = self.gezeigt.get(name)
        if isinstance(eintrag, tuple):
            return eintrag[0]
        return eintrag

    def neu(self, bedingung: Any) -> None:
        bedingung.id = f"b{len(self.bedingungen) + 1}"
        self.bedingungen.append(bedingung)

    def platzierung(self, pl: Any) -> None:
        self.platzierungen.append(pl)

    def param_grenze(self, name: str, wert: Any, min: Any, max: Any, datei: str | None = None,  # noqa: A002
                     zeile: int | None = None) -> None:
        self.params[name] = wert
        if min is None and max is None:
            return
        for g in self.grenzen:
            if g.name == name:  # derselbe Parameter zweimal: die letzte Angabe gilt
                g.wert, g.min, g.max, g.datei, g.zeile = wert, min, max, datei, zeile
                return
        self.grenzen.append(ParamGrenze(name, wert, min, max, datei, zeile))

    @property
    def leer(self) -> bool:
        return not self.bedingungen and not self.grenzen and not self.platzierungen


def aktive() -> Sammlung | None:
    import kevcad

    s = kevcad._hooks.get("bedingungen")
    return s if isinstance(s, Sammlung) else None


@contextlib.contextmanager
def sammeln() -> Iterator[Sammlung]:
    """Sammelt Bedingungen außerhalb eines Laufs (Tests, Skripte): ``with sammeln() as s: ...``."""
    import kevcad

    alt = kevcad._hooks.get("bedingungen")
    s = Sammlung()
    kevcad._hooks["bedingungen"] = s
    try:
        yield s
    finally:
        if alt is None:
            kevcad._hooks.pop("bedingungen", None)
        else:
            kevcad._hooks["bedingungen"] = alt

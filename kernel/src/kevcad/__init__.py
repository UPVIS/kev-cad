"""API für model.py: ``from kevcad import show, step, param, lager``.

Die Funktionen werden vom Rechenprozess des Kernels mit Leben gefüllt (``kevcad_kernel.runner``). Außerhalb des
Kernels (etwa beim direkten Ausführen von model.py mit Python) tun sie nichts Schädliches: ``param`` liefert den
Vorgabewert, ``show`` und ``step`` werden ignoriert.

- ``show(obj, name, color=None, material=None)``: zeigt das Teil sofort im Viewer, noch während das Skript läuft.
  ``obj`` darf Part, Compound, Solid, ein Builder (BuildPart/BuildSketch/BuildLine), Sketch/Face oder Kanten
  (ShapeList, Liste) sein. Ein Compound mit benannten Kindern (``label``) erscheint als Baum "Name/Kind".
  Gleicher Name im selben Lauf ersetzt das Teil. ``color``: "#RRGGBB", Farbname ("red") oder Tupel (0…1 oder 0…255).
  ``material``: Material aus dem Katalog von Kev CAD (id oder Alias, z. B. "stahl-s235", "multiplex-birke"); damit
  kennt der Kernel Dichte, Masse, Farbe und Preis. Mit Inventar-Regel (Standard) nur freigegebene Katalogmaterialien,
  sonst bricht der Lauf ab. Ist die Regel im Projekt abgeschaltet, gelten auch Namen aus build123d ("aluminum",
  "stainless", "oak", ...) oder deutsch ("aluminium", "edelstahl", "messing", "eiche", ...).
- ``step(text)``: Bauschritt, erscheint in der Statusleiste der App.
- ``param(name, default, min=None, max=None)``: benannter Parameter in mm; Vorgabe oder Wert aus ``run(params=...)``.
- ``lager``: Lagerteile aus dem Katalog verbauen (``lager.teil(...).verbauen(...)``) und 3D-Druckteile kennzeichnen
  (``lager.druckteil(...)``), siehe ``kevcad.lager``. Mit Inventar-Regel muss jedes gezeigte Teil daher stammen.
  Kameras mit Objektiv und Format: ``lager.kamera(...)``, Rig-Zubehör: ``lager.kamerazubehoer(...)`` (``kevcad.kamera``).
"""

from __future__ import annotations

from typing import Any

__all__ = ["show", "step", "param", "lager"]

_hooks: dict[str, Any] = {}


def show(obj: Any, name: str | None = None, color: str | tuple | None = None, material: str | None = None) -> Any:
    """Zeigt ``obj`` sofort im Viewer an. Ein Teil mit gleichem Namen wird ersetzt; ``/`` im Namen bildet den Baum.
    Gibt ``obj`` unverändert zurück."""
    hook = _hooks.get("show")
    if hook is not None:
        hook(obj, name, color=color, material=material)
    return obj


def step(text: str) -> None:
    """Markiert einen Bauschritt; erscheint in der Statusleiste der App."""
    hook = _hooks.get("step")
    if hook is not None:
        hook(text)


def param(name: str, default: float, min: float | None = None, max: float | None = None) -> float:  # noqa: A002
    """Benannter Parameter in mm; liefert den Vorgabewert oder den Wert aus ``run(params=...)``."""
    hook = _hooks.get("param")
    if hook is not None:
        return hook(name, default, min=min, max=max)
    return default


from kevcad import lager  # noqa: E402 - braucht _hooks

"""API für model.py: ``from kevcad import show, step, param``.

Die Funktionen werden vom Rechenprozess des Kernels mit Leben gefüllt. Außerhalb des Kernels (etwa beim
direkten Ausführen von model.py mit Python) tun sie nichts Schädliches: ``param`` liefert den Vorgabewert,
``show`` und ``step`` werden ignoriert.
"""

from __future__ import annotations

from typing import Any

_hooks: dict[str, Any] = {}


def show(obj: Any, name: str, color: str | tuple | None = None, material: str | None = None) -> None:
    """Zeigt ``obj`` sofort im Viewer an. Ein Teil mit gleichem Namen wird ersetzt; ``/`` im Namen bildet den Baum."""
    hook = _hooks.get("show")
    if hook is not None:
        hook(obj, name, color=color, material=material)


def step(text: str) -> None:
    """Markiert einen Bauschritt; erscheint in der Statusleiste der App."""
    hook = _hooks.get("step")
    if hook is not None:
        hook(text)


def param(name: str, default: float, min: float | None = None, max: float | None = None) -> float:
    """Benannter Parameter in mm; liefert den Vorgabewert oder den Wert aus ``run(params=...)``."""
    hook = _hooks.get("param")
    if hook is not None:
        return hook(name, default, min=min, max=max)
    return default

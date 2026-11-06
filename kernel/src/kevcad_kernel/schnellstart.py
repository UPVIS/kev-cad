"""Schneller Start (V2-1b): build123d ohne das schwere sklearn laden.

``import build123d`` braucht rund 2 s, davon 0,8 s für ``sklearn.cluster`` (mit scipy.stats und pandas). build123d nutzt
daraus nur ``DBSCAN`` in ``brep_from_stl`` (Netz in B-Rep). Der Stellvertreter lädt sklearn beim ersten Aufruf und liefert
die echte Klasse; danach ist alles wie immer. Während des Imports stehen zwei leere Module in ``sys.modules``, danach
nicht mehr: ``import sklearn`` in model.py bekommt das echte Paket.
"""

from __future__ import annotations

import sys
import types
from typing import Any


class _DBSCAN:
    """Stellvertreter für ``sklearn.cluster.DBSCAN``: Aufruf wie dort, Ergebnis ist die echte Klasse."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        from sklearn.cluster import DBSCAN

        return DBSCAN(*args, **kwargs)


def build123d_laden() -> Any:
    """``import build123d`` ohne sklearn; das Modul. Kommt es anders (andere Fassung, sklearn schon geladen), wie immer."""
    if "build123d" in sys.modules or "sklearn" in sys.modules:
        import build123d

        return build123d
    paket, cluster = types.ModuleType("sklearn"), types.ModuleType("sklearn.cluster")
    cluster.DBSCAN = _DBSCAN  # type: ignore[attr-defined]
    paket.cluster = cluster  # type: ignore[attr-defined]
    sys.modules["sklearn"], sys.modules["sklearn.cluster"] = paket, cluster
    try:
        import build123d
    except ImportError:  # braucht diese Fassung mehr daraus: Stellvertreter weg, dann mit dem echten Paket
        for name in ("sklearn", "sklearn.cluster"):
            sys.modules.pop(name, None)
        import build123d
    finally:
        for name in ("sklearn", "sklearn.cluster"):
            if sys.modules.get(name) in (paket, cluster):
                del sys.modules[name]
    return build123d

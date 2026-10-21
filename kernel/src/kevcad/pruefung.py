"""Erklärungen für die eingebaute Prüfung in model.py: ``from kevcad import montage, erlaubt_ueberlappung``.

Kev CAD prüft jeden Lauf von selbst auf Durchdringungen, schwebende und kippende Teile und Einbaubarkeit
(Montagereihenfolge, Werkzeugzugang, eingesperrte Teile). Diese Aufrufe sind nur Hilfen, wo die Prüfung etwas nicht
selbst wissen kann:

```python
montage(deckel, richtung="-z")                     # Einbaurichtung (Bewegung beim Einsetzen): von oben
montage("Halter/Stift", richtung=(0, 0.7, -0.7))   # schräg eingesetzt
montage(mutter, nach=[schraube, platte])          # erst nach Schraube und Platte
montage(bolzen, werkzeug="inbus 6")               # Werkzeug für ein eigenes Verbindungsteil
montage("Rollwagen/Lenkrolle 1", baugruppe=True)   # Zukaufteil, wird fertig montiert eingesetzt
montage(clip, richtung="+z", schnappt=True)        # Schnappverbindung, biegt sich beim Aufstecken auf
montage(mutter, eingedruckt=True)                 # beim 3D-Druck eingelegt (Druckpause), steckt im Druckteil
erlaubt_ueberlappung(schraube, platte, grund="Gewinde im Kernloch")   # gewollte Überlappung
befestigt(halter, grund="an der Wand verschraubt")  # hängt nicht am Boden, sondern an der Umgebung
boden(0)                                           # Bodenebene (sonst: tiefster Punkt des Modells)
```

- Teile als Name aus ``show()`` (auch eine Gruppe wie "Rollwagen/Lenkrolle 1"), als Form oder als Liste davon.
- ``richtung``: Bewegungsrichtung beim Einbau als Vektor (x, y, z), als Achse "+x", "-z" … oder "von oben"/"von unten";
  mehrere als Liste. Erklärte Richtungen ersetzen die Suche für dieses Teil.
- Eine Erlaubnis ohne Grund gilt nicht. Erlaubnisse und ``befestigt`` nur nach Rückfrage bei Kevin setzen.

Außerhalb des Kernels tun die Funktionen nichts.
"""

from __future__ import annotations

import math
import sys
from typing import Any

__all__ = ["montage", "erlaubt_ueberlappung", "befestigt", "boden"]

_ACHSEN = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
_WORTE = {"von oben": (0.0, 0.0, -1.0), "oben": (0.0, 0.0, -1.0), "von unten": (0.0, 0.0, 1.0),
          "unten": (0.0, 0.0, 1.0)}


def _melde(art: str, daten: dict[str, Any]) -> None:
    import kevcad

    hook = kevcad._hooks.get("pruefung")
    if hook is None:
        return
    frame = sys._getframe(2)
    daten["zeile"] = frame.f_lineno if frame.f_code.co_filename.endswith("model.py") else None
    hook(art, daten)


def _eine_richtung(r: Any) -> tuple[float, float, float]:
    if isinstance(r, str):
        t = r.strip().lower().replace("−", "-")
        if t in _WORTE:
            return _WORTE[t]
        sign = -1.0 if t.startswith("-") else 1.0
        t = t.lstrip("+-")
        if t in _ACHSEN:
            return tuple(sign * c for c in _ACHSEN[t])  # type: ignore[return-value]
        raise ValueError(f"montage: Richtung {r!r} unbekannt (z. B. \"-z\", \"+x\", \"von oben\" oder (x, y, z))")
    d = getattr(r, "direction", None)  # build123d Axis
    if d is not None:
        r = d
    if all(hasattr(r, a) for a in ("X", "Y", "Z")):  # build123d Vector
        v = (float(r.X), float(r.Y), float(r.Z))
    else:
        try:
            v = tuple(float(c) for c in r)
        except TypeError as exc:
            raise ValueError(f"montage: Richtung {r!r} ist kein Vektor (x, y, z)") from exc
    if len(v) != 3:
        raise ValueError(f"montage: Richtung {r!r} braucht drei Zahlen (x, y, z)")
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-9:
        raise ValueError("montage: Richtung (0, 0, 0) ist keine Richtung")
    return tuple(c / n for c in v)  # type: ignore[return-value]


def _richtungen(richtung: Any) -> list[tuple[float, float, float]]:
    if richtung is None:
        return []
    if isinstance(richtung, str) or hasattr(richtung, "X") or hasattr(richtung, "direction"):
        return [_eine_richtung(richtung)]
    seq = list(richtung)
    if len(seq) == 3 and all(isinstance(c, (int, float)) for c in seq):
        return [_eine_richtung(seq)]
    return [_eine_richtung(r) for r in seq]


def _liste(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        return list(x)
    return [x]


def montage(teil: Any, richtung: Any = None, nach: Any = None, werkzeug: str | None = None,
            baugruppe: bool = False, schnappt: bool = False, eingedruckt: bool = False) -> None:
    """Wie ein Teil (oder eine Baugruppe) eingebaut wird: Einbaurichtung, Teile, die vorher drin sein müssen,
    Werkzeug, ``baugruppe=True`` für Zukaufteile, die fertig montiert eingesetzt werden, ``schnappt=True`` für
    Schnappverbindungen (Clip, Rasthaken), die sich beim Einsetzen über die berührten Teile biegen,
    ``eingedruckt=True`` für Teile, die beim 3D-Druck eingelegt werden (Mutter in geschlossener Tasche, Druckpause)."""
    if werkzeug is not None and not isinstance(werkzeug, str):
        raise ValueError("montage: werkzeug als Text angeben, z. B. \"inbus 6\", \"torx t30\", \"gabel 13\"")
    _melde("montage", {"teile": _liste(teil), "richtung": _richtungen(richtung), "nach": _liste(nach),
                       "werkzeug": werkzeug, "baugruppe": bool(baugruppe), "schnappt": bool(schnappt),
                       "eingedruckt": bool(eingedruckt)})


def erlaubt_ueberlappung(a: Any, b: Any, grund: str | None = None) -> None:
    """Gewollte Überlappung zweier Teile (Gewinde im Kernloch, Presspassung). Gilt nur mit Grund und nur nach
    Rückfrage bei Kevin."""
    _melde("erlaubt", {"a": _liste(a), "b": _liste(b), "grund": (grund or "").strip()})


def befestigt(teil: Any, grund: str | None = None) -> None:
    """Teil ist an der Umgebung befestigt (Wand, Decke, verschraubt): zählt als getragen. Nur mit Grund."""
    _melde("befestigt", {"teile": _liste(teil), "grund": (grund or "").strip()})


def boden(z: float = 0.0) -> None:
    """Bodenebene auf Höhe z (mm). Ohne Angabe gilt der tiefste Punkt des Modells als Boden."""
    _melde("boden", {"z": float(z)})

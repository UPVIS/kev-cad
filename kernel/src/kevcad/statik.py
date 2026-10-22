"""Statik in model.py: ``import kevcad.statik as st`` (PLAN-STATIK.md, T3).

Kev CAD rechnet nach jedem Lauf von selbst: Eigengewicht, auf Rollen das Bremsen, eine Nutzlast aus einem Parameter
(``param("nutzlast", 30)`` in kg). Eigene Lastfälle beschreibt man so:

```python
import kevcad.statik as st

st.szenario("Aufstützen", beschreibung="Kevin stützt sich mit 30 kg auf den Rahmen")
st.last("Kugelschieber/Querstange vorn (Rohr 3)", kg=30)                 # senkrecht nach unten, Mitte des Teils
st.last(halter, kraft=(0, 0, -50), punkt=(120, 0, 40))                   # Kraft in N an einem Punkt (mm, Welt)

st.szenario("Bremsen", beschleunigung=(-3, 0, 0))                         # m/s² des ganzen Gegenstands
st.szenario("Schräge", neigung=10, richtung="+y")                         # Boden 10° geneigt, abwärts nach +Y
st.szenario("Anstoßen", stoss=2)                                          # Stoßfaktor auf die Lasten des Szenarios
st.last("Regal/Fach 2", kg=20, szenario="Anstoßen")

st.untergrund("holz")                                                     # Boden zum Rutschen (Standard Beton)
st.ziel(sicherheit=2.5, durchbiegung="L/300")                             # eigene Ziele statt T5
```

- ``szenario`` legt ein Szenario an (oder ergänzt das gleichnamige); ``last``, ``stoss``, ``neigung`` ohne
  ``szenario=`` gehören zum zuletzt angelegten. Lasten ganz ohne Szenario landen im Szenario „Nutzlast“.
- Teile als Name aus ``show()``, als Gruppe ("Kugelschieber/") oder als gezeigte Form. Kraft in N als (fx, fy, fz),
  ``kg=`` für Gewichtskraft senkrecht nach unten. ``punkt`` in mm (Welt); ohne Punkt die Mitte (Stab: Mitte der
  Achse).
- Ziele (T5): statisch 2, dynamisch (Beschleunigung, Stoß) 3, Druckteile das Doppelte; Durchbiegung L/200.
- Außerhalb des Kernels tun die Funktionen nichts.

Ergebnis: MCP ``statik`` und ``szenario_rechnen``, in der App der Abschnitt „Statik“ mit Ampel und Farbverlauf.
"""

from __future__ import annotations

import math
import sys
from typing import Any

__all__ = ["szenario", "last", "neigung", "beschleunigung", "stoss", "untergrund", "ziel", "Szenario"]

G = 9.81
_stand: dict[str, Any] = {"hook": None, "aktuell": None}


def _hook() -> Any:
    import kevcad

    hook = kevcad._hooks.get("pruefung")
    if hook is not _stand["hook"]:  # neuer Lauf: kein aktuelles Szenario mehr
        _stand["hook"], _stand["aktuell"] = hook, None
    return hook


def _zeile() -> int | None:
    frame = sys._getframe(2)
    while frame is not None and frame.f_code.co_filename.endswith("statik.py"):
        frame = frame.f_back
    return frame.f_lineno if frame is not None and frame.f_code.co_filename.endswith("model.py") else None


def _melde(daten: dict[str, Any]) -> None:
    hook = _hook()
    if hook is None:
        return
    daten["zeile"] = _zeile()
    hook("statik", daten)


def _vec(v: Any, was: str) -> list[float] | None:
    if v is None:
        return None
    if all(hasattr(v, a) for a in ("X", "Y", "Z")):
        return [float(v.X), float(v.Y), float(v.Z)]
    try:
        out = [float(c) for c in v]
    except TypeError as exc:
        raise ValueError(f"statik: {was} {v!r} ist kein Vektor (x, y, z)") from exc
    if len(out) != 3:
        raise ValueError(f"statik: {was} braucht drei Zahlen (x, y, z)")
    return out


def _teile(teil: Any) -> list[Any]:
    if teil is None:
        return []
    return list(teil) if isinstance(teil, (list, tuple, set)) else [teil]


class Szenario:
    """Ein Szenario aus model.py; Methoden hängen Lasten an genau dieses Szenario."""

    def __init__(self, name: str) -> None:
        self.name = name

    def last(self, teil: Any, kraft: Any = None, punkt: Any = None, kg: float | None = None) -> Szenario:
        last(teil, kraft=kraft, punkt=punkt, kg=kg, szenario=self.name)
        return self

    def stoss(self, teil: Any = None, kraft: Any = None, faktor: float = 2.0, **kw: Any) -> Szenario:
        stoss(teil, kraft=kraft, faktor=faktor, szenario=self.name, **kw)
        return self

    def __repr__(self) -> str:
        return f"Szenario({self.name!r})"


def szenario(name: str, beschleunigung: Any = None, neigung: float | None = None, richtung: Any = "+x",
             stoss: float | None = None, ziel: float | None = None, beschreibung: str | None = None) -> Szenario:
    """Neues Szenario (folgende ``last``-Aufrufe gehören dazu). ``beschleunigung`` in m/s² (z. B. (-3, 0, 0) beim
    Bremsen in Fahrtrichtung +X), ``neigung`` in Grad mit ``richtung`` (abwärts), ``stoss`` als Faktor auf alle Lasten,
    ``ziel`` als eigene Zielsicherheit."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("statik.szenario: Namen angeben, z. B. st.szenario(\"Bremsen\", beschleunigung=(-3, 0, 0))")
    d: dict[str, Any] = {"was": "szenario", "name": name.strip(), "beschreibung": beschreibung}
    if beschleunigung is not None:
        d["beschleunigung"] = _vec(beschleunigung, "beschleunigung")
    if neigung is not None:
        d["neigung"] = {"grad": float(neigung), "richtung": richtung if isinstance(richtung, str)
                        else _vec(richtung, "richtung")}
    if stoss is not None:
        d["stoss"] = {"faktor": float(stoss)}
    if ziel is not None:
        d["ziel"] = float(ziel)
    _melde(d)
    _stand["aktuell"] = name.strip()
    return Szenario(name.strip())


def last(teil: Any, kraft: Any = None, punkt: Any = None, kg: float | None = None, szenario: str | None = None) -> None:
    """Last auf ein Teil (oder eine Gruppe): ``kraft`` in N als (fx, fy, fz) oder ``kg`` (senkrecht nach unten),
    ``punkt`` in mm (Welt)."""
    if kraft is None and kg is None:
        raise ValueError("statik.last: kraft=(fx, fy, fz) in N oder kg=… angeben")
    k = _vec(kraft, "kraft") if kraft is not None else [0.0, 0.0, -float(kg) * G]
    if any(not math.isfinite(c) for c in k):
        raise ValueError("statik.last: kraft enthält ungültige Zahlen")
    _hook()
    _melde({"was": "last", "teile": _teile(teil), "kraft": k, "punkt": _vec(punkt, "punkt"),
            "kg": float(kg) if kg is not None else None, "szenario": szenario or _stand["aktuell"]})


def neigung(grad: float, richtung: Any = "+x", szenario: str | None = None) -> None:
    """Boden um ``grad`` geneigt, abwärts in ``richtung`` ("+x", "-y" oder (x, y, 0))."""
    _hook()
    _melde({"was": "neigung", "grad": float(grad), "richtung": richtung if isinstance(richtung, str)
            else _vec(richtung, "richtung"), "szenario": szenario or _stand["aktuell"] or f"Schräglage {grad:g}°"})


def beschleunigung(a: Any, szenario: str | None = None) -> None:
    """Beschleunigung des ganzen Gegenstands in m/s² (Anfahren, Bremsen, Kurve)."""
    _hook()
    _melde({"was": "beschleunigung", "a": _vec(a, "beschleunigung"), "szenario": szenario or _stand["aktuell"]})


def stoss(teil: Any = None, kraft: Any = None, faktor: float = 2.0, masse: float | None = None,
          geschwindigkeit: float | None = None, weg: float | None = None, punkt: Any = None,
          szenario: str | None = None) -> None:
    """Stoß als ruhende Ersatzlast: ``kraft`` × ``faktor`` (plötzlich aufgebracht: 2), oder aus ``masse`` (kg),
    ``geschwindigkeit`` (m/s) und Bremsweg ``weg`` (mm): F = m·v² / (2·s), in Richtung ``kraft`` (sonst nach unten).
    Ohne Teil gilt ``faktor`` für alle Lasten des Szenarios."""
    _hook()
    d: dict[str, Any] = {"was": "stoss", "faktor": float(faktor), "szenario": szenario or _stand["aktuell"]}
    if teil is not None:
        richtung = _vec(kraft, "kraft") if kraft is not None else [0.0, 0.0, -1.0]
        if masse is not None and geschwindigkeit is not None and weg:
            betrag = float(masse) * float(geschwindigkeit) ** 2 / (2 * float(weg) / 1000.0)
            n = math.sqrt(sum(c * c for c in richtung)) or 1.0
            richtung = [c / n * betrag for c in richtung]
            d["faktor"] = 1.0
        elif kraft is None:
            raise ValueError("statik.stoss: kraft=(fx, fy, fz) oder masse, geschwindigkeit und weg angeben")
        d.update({"teile": _teile(teil), "kraft": richtung, "punkt": _vec(punkt, "punkt")})
    _melde(d)


def untergrund(material: str) -> None:
    """Material des Bodens für das Rutschen (Katalog, z. B. "beton", "eiche"); Standard Beton."""
    _hook()
    _melde({"was": "untergrund", "material": str(material)})


def ziel(sicherheit: float | None = None, durchbiegung: str | float | None = None) -> None:
    """Eigene Ziele für alle Szenarien: Sicherheit (statisch; dynamisch × 1,5) und Durchbiegung ("L/300")."""
    _hook()
    _melde({"was": "ziel", "sicherheit": sicherheit, "durchbiegung": durchbiegung})

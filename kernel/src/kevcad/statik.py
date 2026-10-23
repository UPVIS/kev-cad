"""Statik in model.py: ``import kevcad.statik as st`` (PLAN-STATIK.md, T3).

Kev CAD rechnet nach jedem Lauf von selbst: Eigengewicht, auf Rollen das Bremsen, eine Nutzlast aus einem Parameter
(``param("nutzlast", 30)`` in kg). Eigene Lastfälle beschreibt man so:

```python
import kevcad.statik as st

st.szenario("Aufstützen", beschreibung="Kevin stützt sich mit 30 kg auf den Rahmen")
st.last("Kugelschieber/Querstange vorn (Rohr 3)", kg=30)                 # senkrecht nach unten, Mitte des Teils
st.last(halter, kraft=(0, 0, -50), punkt=(120, 0, 40))                   # Kraft in N an einem Punkt (mm, Welt)

st.szenario("Ball drückt 100 N auf den Fänger")                           # innere Kraft zwischen zwei Teilen:
st.last("Kugelschieber/Querstange vorn (Rohr 3)", kraft=(100, 0, 0),     # Kraft auf die Querstange,
        punkt=(700, 0, 60), gegen="Bowlingball")                          # Gegenkraft auf den Ball
st.kraftpaar("Kugelschieber/Querstange vorn (Rohr 3)", "Bowlingball", kraft=(100, 0, 0))  # dasselbe

st.szenario("Bremsen", beschleunigung=(-3, 0, 0))                         # m/s² des ganzen Gegenstands
st.szenario("Schräge", neigung=10, richtung="+y")                         # Boden 10° geneigt, abwärts nach +Y
st.szenario("Anstoßen", stoss=2)                                          # Stoßfaktor auf die Lasten des Szenarios
st.last("Regal/Fach 2", kg=20, szenario="Anstoßen")

st.szenario("Bremsen aus 1 m/s", geschwindigkeit=1, bremsen="abrupt")    # Ablauf (S2): schieben, abrupt bremsen
st.szenario("Fahrt", animation="Fahrt", bremsen=4)                        # Sollbahn aus der Animation „Fahrt“

st.untergrund("holz")                                                     # Boden zum Rutschen (Standard Beton)
st.ziel(sicherheit=2.5, durchbiegung="L/300")                             # eigene Ziele statt T5

# Stufe 4 (CalculiX): Kontakt statt fester Einspannung, Plastizität, Traglast, Beulen
st.kontakt("Kugelschieber/Stangenhalter vorn links (Druck)", "Kugelschieber/Seitenstange links (Rohr 1)",
           reibwert=0.3, klemmkraft=500)                                  # Paar hebt ab und gleitet
st.festigkeit("Kugelschieber/Stangenhalter vorn links (Druck)", kontakt=True, plastisch=True)
```

- ``szenario`` legt ein Szenario an (oder ergänzt das gleichnamige); ``last``, ``stoss``, ``neigung`` ohne
  ``szenario=`` gehören zum zuletzt angelegten. Lasten ganz ohne Szenario landen im Szenario „Nutzlast“.
- **Kraftpaar** (innere Kraft, ``last(…, gegen=…)`` oder ``kraftpaar(a, b, kraft)``): Die Kraft wirkt auf ``a``, die
  Gegenkraft am selben Punkt auf ``b`` (etwa der Ball gegen die Fangrolle). Beim Kippen, Rutschen und Abheben des
  Ganzen heben sich beide auf; Stabwerk, Bauteile und Festkörper bekommen jede Seite auf ihre Teile.
- Teile als Name aus ``show()``, als Gruppe ("Kugelschieber/") oder als gezeigte Form. Kraft in N als (fx, fy, fz),
  ``kg=`` für Gewichtskraft senkrecht nach unten. ``punkt`` in mm (Welt); ohne Punkt die Mitte (Stab: Mitte der
  Achse).
- Ziele (T5): statisch 2, dynamisch (Beschleunigung, Stoß) 3, Druckteile das Doppelte; Durchbiegung L/200.
- Ablauf (S2, Dynamik mit MuJoCo): ``geschwindigkeit`` (m/s), ``bremsen`` (m/s², ``"abrupt"`` = Stillstand in 0,1 s,
  ``"anprall"`` = in 0,02 s), ``dauer`` (s), ``animation`` (Sollbahn des geschobenen Teils aus einer Animation),
  ``antrieb`` (geschobenes Teil oder Gruppe, sonst der schwerste Körper auf Rädern), ``angriff`` (``"boden"``, Höhe in
  mm oder Punkt), ``fahrtrichtung`` (``"+x"``). Kev CAD rechnet den Ablauf nach jedem Lauf im Hintergrund in einem
  eigenen Prozess: Kippen, Abheben, Ladung (Ball springt heraus?), Grenzgeschwindigkeit; die Zeitleiste spielt ihn als
  Animation „Ablauf: <Name>“ ab.
- Außerhalb des Kernels tun die Funktionen nichts.

- Stufe 4 (CalculiX, eigener Prozess): ``kontakt(a, b, reibwert=, klemmkraft=, spiel=)`` macht aus der Verbindung
  zweier Teile ein Kontaktpaar (abheben, gleiten; ohne Reibwert der Haftreibwert der Paarung aus reibwerte.json, ohne
  Klemmkraft „handfest“ angenommen); ``festigkeit(teil, kontakt=True, plastisch=False, traglast=None, beulen=False)``
  rechnet das Teil nach jedem Lauf im Hintergrund mit CalculiX nach (Kontaktdruck, Klaffen, Schlupf, plastische
  Dehnung, bleibende Verformung, Traglast, Beulfaktor). Ohne ``st.festigkeit`` gelten die Kontaktpaare, sobald der
  Agent ``festigkeit(…, verfahren="ccx")`` aufruft.

Ergebnis: MCP ``statik`` und ``szenario_rechnen``, in der App der Abschnitt „Statik“ mit Ampel und Farbverlauf.
"""

from __future__ import annotations

import math
import sys
from typing import Any

__all__ = ["szenario", "last", "kraftpaar", "neigung", "beschleunigung", "stoss", "untergrund", "ziel", "kontakt",
           "festigkeit",
           "Szenario"]

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

    def last(self, teil: Any, kraft: Any = None, punkt: Any = None, kg: float | None = None,
             gegen: Any = None) -> Szenario:
        last(teil, kraft=kraft, punkt=punkt, kg=kg, szenario=self.name, gegen=gegen)
        return self

    def kraftpaar(self, teil: Any, gegen: Any, kraft: Any = None, punkt: Any = None,
                  kg: float | None = None) -> Szenario:
        kraftpaar(teil, gegen, kraft=kraft, punkt=punkt, kg=kg, szenario=self.name)
        return self

    def stoss(self, teil: Any = None, kraft: Any = None, faktor: float = 2.0, **kw: Any) -> Szenario:
        stoss(teil, kraft=kraft, faktor=faktor, szenario=self.name, **kw)
        return self

    def __repr__(self) -> str:
        return f"Szenario({self.name!r})"


def szenario(name: str, beschleunigung: Any = None, neigung: float | None = None, richtung: Any = "+x",
             stoss: float | None = None, ziel: float | None = None, beschreibung: str | None = None,
             geschwindigkeit: float | None = None, bremsen: Any = None, dauer: float | None = None,
             animation: str | None = None, antrieb: Any = None, angriff: Any = None,
             fahrtrichtung: Any = None) -> Szenario:
    """Neues Szenario (folgende ``last``-Aufrufe gehören dazu). ``beschleunigung`` in m/s² (z. B. (-3, 0, 0) beim
    Bremsen in Fahrtrichtung +X), ``neigung`` in Grad mit ``richtung`` (abwärts), ``stoss`` als Faktor auf alle Lasten
    (im Ablauf auf die Verzögerung), ``ziel`` als eigene Zielsicherheit. Mit ``geschwindigkeit`` (m/s), ``bremsen``
    (m/s², "abrupt", "anprall") oder ``animation`` wird es ein Ablauf (S2, Dynamik), siehe Moduldoku."""
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
    if geschwindigkeit is not None or bremsen is not None or animation is not None:
        ab: dict[str, Any] = {"geschwindigkeit": None if geschwindigkeit is None else float(geschwindigkeit),
                              "bremsen": bremsen if isinstance(bremsen, str) or bremsen is None else float(bremsen),
                              "dauer": None if dauer is None else float(dauer), "animation": animation}
        if antrieb is not None:
            ab["antrieb"] = antrieb if isinstance(antrieb, str) else _teile(antrieb)[0]
        if angriff is not None:
            ab["angriff"] = angriff if isinstance(angriff, (str, int, float)) else _vec(angriff, "angriff")
        if fahrtrichtung is not None:
            ab["fahrtrichtung"] = fahrtrichtung if isinstance(fahrtrichtung, str) else _vec(fahrtrichtung,
                                                                                            "fahrtrichtung")
        d["ablauf"] = ab
    _melde(d)
    _stand["aktuell"] = name.strip()
    return Szenario(name.strip())


def last(teil: Any, kraft: Any = None, punkt: Any = None, kg: float | None = None, szenario: str | None = None,
         gegen: Any = None) -> None:
    """Last auf ein Teil (oder eine Gruppe): ``kraft`` in N als (fx, fy, fz) oder ``kg`` (senkrecht nach unten),
    ``punkt`` in mm (Welt). Mit ``gegen`` (Teil, Gruppe oder Form) ist es ein Kraftpaar: die Gegenkraft wirkt am selben
    Punkt auf ``gegen`` (innere Kraft, etwa der Ball gegen die Fangrolle; zählt nicht beim Kippen und Rutschen)."""
    if kraft is None and kg is None:
        raise ValueError("statik.last: kraft=(fx, fy, fz) in N oder kg=… angeben")
    k = _vec(kraft, "kraft") if kraft is not None else [0.0, 0.0, -float(kg) * G]
    if any(not math.isfinite(c) for c in k):
        raise ValueError("statik.last: kraft enthält ungültige Zahlen")
    _hook()
    d = {"was": "last", "teile": _teile(teil), "kraft": k, "punkt": _vec(punkt, "punkt"),
         "kg": float(kg) if kg is not None else None, "szenario": szenario or _stand["aktuell"]}
    if gegen is not None:
        if not _teile(gegen):
            raise ValueError("statik.last: gegen= braucht ein Teil (Name aus show(), Gruppe oder Form)")
        d["gegen"] = _teile(gegen)
    _melde(d)


def kraftpaar(teil: Any, gegen: Any, kraft: Any = None, punkt: Any = None, kg: float | None = None,
              szenario: str | None = None) -> None:
    """Innere Kraft zwischen zwei Teilen der Konstruktion: ``kraft`` (N) auf ``teil``, die Gegenkraft am selben
    ``punkt`` auf ``gegen``. Gleich wie ``last(teil, kraft, punkt, gegen=gegen)``."""
    if gegen is None:
        raise ValueError("statik.kraftpaar: gegen= (das Teil, das die Gegenkraft aufnimmt) angeben")
    last(teil, kraft=kraft, punkt=punkt, kg=kg, szenario=szenario, gegen=gegen)


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


def kontakt(teil: Any, gegen: Any, reibwert: float | None = None, klemmkraft: float | None = None,
            spiel: float | None = None) -> None:
    """Stufe 4: Die Verbindung von ``teil`` und ``gegen`` ist ein Kontakt (heben ab, gleiten mit ``reibwert``) statt
    einer festen Einspannung. ``klemmkraft`` in N für Klemmschrauben an ``teil`` (sonst „handfest“ angenommen),
    ``spiel`` in mm als Anfangsspalt (sonst aus der Geometrie)."""
    if not _teile(teil) or not _teile(gegen):
        raise ValueError("statik.kontakt: zwei Teile angeben, z. B. st.kontakt(\"Halter\", \"Rohr\")")
    for name, wert in (("reibwert", reibwert), ("klemmkraft", klemmkraft), ("spiel", spiel)):
        if wert is not None and (not isinstance(wert, (int, float)) or not math.isfinite(float(wert)) or wert < 0):
            raise ValueError(f"statik.kontakt: {name} muss eine Zahl ≥ 0 sein")
    _melde({"was": "kontakt", "teile": _teile(teil), "gegen": _teile(gegen),
            "reibwert": None if reibwert is None else float(reibwert),
            "klemmkraft": None if klemmkraft is None else float(klemmkraft),
            "spiel": None if spiel is None else float(spiel)})


def festigkeit(teil: Any, kontakt: bool = True, plastisch: bool = False, traglast: bool | None = None,
               beulen: bool = False, klemmkraft: float | None = None, reibwert: float | None = None,
               szenario: str | None = None) -> None:
    """Stufe 4: ``teil`` (Name, Gruppe oder Form) nach jedem Lauf im Hintergrund mit CalculiX nachrechnen: Kontakt mit
    Abheben und Gleiten (``kontakt``), elastisch-plastisch (``plastisch``), Traglast (``traglast``, Standard: mit
    Kontakt oder Plastizität), Beulfaktor (``beulen``). ``szenario``: nur dieses (sonst alle mit Last)."""
    if not _teile(teil):
        raise ValueError("statik.festigkeit: Teil angeben")
    _melde({"was": "festigkeit", "teile": _teile(teil), "kontakt": bool(kontakt), "plastisch": bool(plastisch),
            "traglast": None if traglast is None else bool(traglast), "beulen": bool(beulen),
            "klemmkraft": None if klemmkraft is None else float(klemmkraft),
            "reibwert": None if reibwert is None else float(reibwert), "szenario": szenario})

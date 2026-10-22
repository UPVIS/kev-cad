"""Szenarien (PLAN-STATIK.md, T3): Lastfälle aus model.py (``kevcad.statik``), vom Agenten (MCP ``szenario_rechnen``)
oder von selbst je Gegenstand.

Ein Szenario ist ein Beschleunigungsfeld (Schwerkraft, geneigter Boden, Anfahren und Bremsen) plus Einzellasten. In
einem Szenario rechnet alles quasistatisch: Trägheitskräfte als Kräfte (d'Alembert), ein Stoß als ruhende Ersatzlast
(Stoßfaktor). Einheiten: Beschleunigung m/s², Kraft N, Punkte mm (Welt).

Zielsicherheiten (T5): statisch 2, dynamisch 3; Druckteile das Doppelte (4 bzw. 6) wegen der Schichten.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.statik.werkstoff import G

ZIEL_STATISCH = 2.0
ZIEL_DYNAMISCH = 3.0
FAKTOR_DRUCK = 2.0  # Druckteile: Zielsicherheit × 2 (statisch 4, T5)
DURCHBIEGUNG = 200.0  # zulässig L/200
UEBERDIMENSIONIERT = 10.0  # Sicherheitsfaktor ab 10 in allen Lastszenarien: überdimensioniert (T5)
NUTZLAST_PARAM = re.compile(r"(nutz|zu|trag|fach|sitz)last|zuladung|last_kg|traglast", re.IGNORECASE)
RAD_WORTE = ("rad", "rolle", "lenkrolle", "wheel", "caster")


@dataclass
class Last:
    teile: list[str]
    kraft: np.ndarray  # N, Welt
    punkt: np.ndarray | None = None  # mm, Welt; None: Mitte des Teils (Stab: Mitte der Achse)
    kg: float | None = None
    zeile: int | None = None
    text: str = ""

    def kurz(self) -> dict[str, Any]:
        return {"teile": list(self.teile), "kraft": [round(float(c), 2) for c in self.kraft],
                "punkt": None if self.punkt is None else [round(float(c), 2) for c in self.punkt],
                "kg": self.kg, "zeile": self.zeile}


@dataclass
class Szenario:
    name: str
    beschleunigung: np.ndarray = field(default_factory=lambda: np.zeros(3))  # m/s² des ganzen Gegenstands
    neigung_grad: float = 0.0
    neigung_richtung: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))  # abwärts
    lasten: list[Last] = field(default_factory=list)
    stoss_faktor: float = 1.0
    dynamisch: bool = False
    ziel: float | None = None  # eigene Zielsicherheit (sonst T5)
    durchbiegung: float = DURCHBIEGUNG
    quelle: str = "modell"  # modell | standard | agent
    beschreibung: str = ""
    zeile: int | None = None
    ablauf: dict[str, Any] | None = None  # S2 (Dynamik): geschwindigkeit, bremsen, dauer, animation, antrieb, …

    @property
    def feld(self) -> np.ndarray:
        """Beschleunigungsfeld je kg (m/s²) im System des Gegenstands: Schwerkraft (bei Neigung schräg) minus die
        Beschleunigung des Gegenstands (Trägheit)."""
        t = math.radians(self.neigung_grad)
        h = np.asarray(self.neigung_richtung, dtype=float)
        h = h - np.array([0, 0, 1.0]) * h[2]
        n = float(np.linalg.norm(h))
        h = h / n if n > 1e-9 else np.array([1.0, 0, 0])
        g = G * (math.sin(t) * h - math.cos(t) * np.array([0, 0, 1.0]))
        return g - np.asarray(self.beschleunigung, dtype=float)

    @property
    def nur_eigengewicht(self) -> bool:
        return not self.lasten and not np.any(np.abs(self.beschleunigung) > 1e-9) and abs(self.neigung_grad) < 1e-9

    @property
    def hat_lasten(self) -> bool:
        return bool(self.lasten) or not self.nur_eigengewicht

    def ziel_fuer(self, druckteil: bool = False) -> float:
        z = self.ziel if self.ziel else (ZIEL_DYNAMISCH if self.dynamisch else ZIEL_STATISCH)
        return z * (FAKTOR_DRUCK if druckteil else 1.0)

    def kraefte(self) -> list[Last]:
        """Einzellasten mit Stoßfaktor."""
        if abs(self.stoss_faktor - 1.0) < 1e-12:
            return list(self.lasten)
        return [Last(l.teile, l.kraft * self.stoss_faktor, l.punkt, l.kg, l.zeile, l.text) for l in self.lasten]

    def kurz(self) -> dict[str, Any]:
        return {"name": self.name, "art": "dynamisch" if self.dynamisch else "statisch", "quelle": self.quelle,
                "beschleunigung": [round(float(c), 3) for c in self.beschleunigung],
                "neigung": {"grad": self.neigung_grad, "richtung": [round(float(c), 3) for c in self.neigung_richtung]}
                if self.neigung_grad else None,
                "stossfaktor": self.stoss_faktor if self.stoss_faktor != 1.0 else None,
                "lasten": [l.kurz() for l in self.lasten], "ziel": self.ziel_fuer(False),
                "ziel_druck": self.ziel_fuer(True), "durchbiegung": f"L/{self.durchbiegung:g}",
                "beschreibung": self.beschreibung or None, "zeile": self.zeile,
                **({"ablauf": dict(self.ablauf)} if self.ablauf else {})}


# ---------------------------------------------------------------------------------------------------------------------
# Aus model.py und vom Agenten


def _vec(v: Any, n: int = 3) -> np.ndarray | None:
    if v is None:
        return None
    try:
        a = np.asarray([float(c) for c in v], dtype=float)
    except (TypeError, ValueError):
        return None
    return a if a.shape == (n,) else None


def _richtung(r: Any) -> np.ndarray:
    if isinstance(r, str):
        t = r.strip().lower().replace("−", "-")
        s = -1.0 if t.startswith("-") else 1.0
        t = t.lstrip("+-")
        ach = {"x": (1.0, 0, 0), "y": (0, 1.0, 0), "z": (0, 0, 1.0)}.get(t)
        if ach is None:
            raise ValueError(f"Richtung {r!r} unbekannt (\"x\", \"-y\" oder (x, y, z))")
        return s * np.array(ach)
    v = _vec(r)
    if v is None or float(np.linalg.norm(v)) < 1e-9:
        raise ValueError(f"Richtung {r!r} ist kein Vektor (x, y, z)")
    return v / float(np.linalg.norm(v))


def szenario_aus(d: dict[str, Any], quelle: str = "agent") -> Szenario:
    """Szenario aus einem Wörterbuch (MCP ``szenario_rechnen`` oder Ereignis aus model.py)."""
    name = str(d.get("name") or "").strip()
    if not name:
        raise ValueError("Szenario braucht einen Namen")
    s = Szenario(name=name, quelle=quelle, beschreibung=str(d.get("beschreibung") or ""), zeile=d.get("zeile"))
    b = d.get("beschleunigung")
    if b is not None:
        v = _vec(b)
        if v is None:
            raise ValueError("beschleunigung als (ax, ay, az) in m/s² angeben, z. B. (-3, 0, 0) beim Bremsen")
        s.beschleunigung = v
        s.dynamisch = True
    n = d.get("neigung")
    if n is not None:
        if isinstance(n, (int, float)):
            s.neigung_grad = float(n)
        else:
            s.neigung_grad = float(n.get("grad") or 0.0)
            if n.get("richtung") is not None:
                s.neigung_richtung = _richtung(n.get("richtung"))
    st = d.get("stoss")
    if st is not None:
        s.stoss_faktor = float(st.get("faktor") if isinstance(st, dict) else st) or 1.0
        s.dynamisch = True
    if d.get("dynamisch") is not None:
        s.dynamisch = bool(d["dynamisch"])
    if d.get("ziel"):
        s.ziel = float(d["ziel"])
    if d.get("durchbiegung"):
        s.durchbiegung = float(str(d["durchbiegung"]).replace("L/", "") or DURCHBIEGUNG)
    for l in d.get("lasten") or []:
        s.lasten.append(last_aus(l))
    ab = ablauf_aus(d)
    if ab:
        s.ablauf = ab
        s.dynamisch = True
        if b is None:  # S0/S1 rechnen mit der größten Verzögerung als ruhender Last (d'Alembert)
            s.beschleunigung = -float(ab.get("verzoegerung") or 0.0) * np.asarray(ab["fahrtrichtung"], dtype=float)
    return s


ABLAUF_SCHLUESSEL = ("geschwindigkeit", "bremsen", "dauer", "animation", "antrieb", "angriff", "fahrtrichtung")


def ablauf_aus(d: dict[str, Any]) -> dict[str, Any] | None:
    """Angaben für den Ablauf (S2) aus einem Szenario: ``geschwindigkeit`` (m/s), ``bremsen`` (m/s², "abrupt",
    "anprall"), ``dauer`` (s), ``animation`` (Sollbahn aus einer Animation), ``antrieb`` (geschobenes Teil),
    ``angriff`` ("boden", Höhe in mm oder Punkt), ``fahrtrichtung`` ("+x" oder Vektor). Ohne Geschwindigkeit,
    Bremsen und Animation: None (kein Ablauf)."""
    quelle = d.get("ablauf") if isinstance(d.get("ablauf"), dict) else d
    if not any(quelle.get(k) is not None for k in ("geschwindigkeit", "bremsen", "animation")):
        return None
    out: dict[str, Any] = {}
    v = quelle.get("geschwindigkeit")
    if v is not None:
        v = float(v)
        if not 0 < v <= 20:
            raise ValueError(f"geschwindigkeit {v:g} m/s: zwischen 0 und 20 m/s angeben")
        out["geschwindigkeit"] = v
    elif quelle.get("animation") is None:
        raise ValueError("Ablauf braucht geschwindigkeit=… (m/s) oder animation=\"Name\"")
    br = quelle.get("bremsen")
    if br is not None and not isinstance(br, (str, int, float)):
        raise ValueError("bremsen als Zahl in m/s², \"abrupt\" oder \"anprall\" angeben")
    out["bremsen"] = br
    for k in ("dauer", "animation", "antrieb", "angriff"):
        if quelle.get(k) is not None:
            out[k] = quelle[k]
    if out.get("dauer") is not None and not 0 < float(out["dauer"]) <= 30:
        raise ValueError("dauer zwischen 0 und 30 s angeben")
    out["fahrtrichtung"] = _richtung(quelle.get("fahrtrichtung") or "+x").tolist()
    stoss = d.get("stoss")
    faktor = float(stoss.get("faktor") if isinstance(stoss, dict) else stoss) if stoss else 1.0
    if faktor != 1.0:
        out["stoss"] = faktor
    from kevcad_kernel.statik.dynamik.ablauf import bremszeit

    a, text = bremszeit(br, float(v or 0.0))
    out["verzoegerung"] = a * faktor
    out["bremsart"] = text
    return out


def last_aus(l: dict[str, Any]) -> Last:
    teile = l.get("teile") if l.get("teile") is not None else l.get("teil")
    teile = [teile] if isinstance(teile, str) else list(teile or [])
    if not teile:
        raise ValueError("Last braucht ein Teil (teil=\"Name aus show()\")")
    kraft = _vec(l.get("kraft"))
    kg = l.get("kg")
    if kraft is None and kg is not None:
        kraft = np.array([0.0, 0.0, -float(kg) * G])
    if kraft is None:
        raise ValueError("Last braucht kraft=(fx, fy, fz) in N oder kg=… (senkrecht nach unten)")
    faktor = l.get("stoss")
    if faktor:
        kraft = kraft * float(faktor)
    return Last([str(t) for t in teile], kraft, _vec(l.get("punkt")), float(kg) if kg is not None else None,
                l.get("zeile"), str(l.get("text") or ""))


def aus_modell(ereignisse: list[dict[str, Any]]) -> tuple[list[Szenario], dict[str, Any]]:
    """Szenarien und Einstellungen (Untergrund, Ziele) aus den Ereignissen von ``kevcad.statik`` (Reihenfolge wie in
    model.py). Lasten ohne Szenario landen im Szenario „Nutzlast“."""
    szen: dict[str, Szenario] = {}
    einstellungen: dict[str, Any] = {"warnungen": []}
    for e in ereignisse or []:
        was = e.get("was")
        try:
            if was == "szenario":
                s = szenario_aus(e, "modell")
                alt = szen.get(s.name)
                if alt is not None:  # gleicher Name: Angaben ergänzen
                    s.lasten = alt.lasten + s.lasten
                szen[s.name] = s
            elif was in ("last", "stoss", "neigung", "beschleunigung"):
                name = str(e.get("szenario") or "Nutzlast")
                s = szen.get(name)
                if s is None:
                    s = szen[name] = Szenario(name=name, quelle="modell", zeile=e.get("zeile"))
                if was == "last":
                    s.lasten.append(last_aus(e))
                elif was == "stoss":
                    if e.get("teile") or e.get("teil"):
                        l = last_aus({**e, "stoss": None})
                        l.kraft = l.kraft * float(e.get("faktor") or 1.0)
                        s.lasten.append(l)
                    elif e.get("faktor"):
                        s.stoss_faktor = float(e["faktor"])
                    s.dynamisch = True
                elif was == "neigung":
                    s.neigung_grad = float(e.get("grad") or 0.0)
                    if e.get("richtung") is not None:
                        s.neigung_richtung = _richtung(e["richtung"])
                elif was == "beschleunigung":
                    v = _vec(e.get("a"))
                    if v is not None:
                        s.beschleunigung = v
                        s.dynamisch = True
            elif was == "untergrund":
                einstellungen["untergrund"] = e.get("material")
            elif was == "ziel":
                einstellungen["ziel"] = {k: e.get(k) for k in ("sicherheit", "durchbiegung") if e.get(k) is not None}
        except ValueError as exc:
            einstellungen["warnungen"].append({"text": f"statik ({was}): {exc}", "zeile": e.get("zeile")})
    ziel = einstellungen.get("ziel") or {}
    for s in szen.values():
        if ziel.get("sicherheit") and not s.ziel:
            s.ziel = float(ziel["sicherheit"]) * (ZIEL_DYNAMISCH / ZIEL_STATISCH if s.dynamisch else 1.0)
        if ziel.get("durchbiegung"):
            s.durchbiegung = float(str(ziel["durchbiegung"]).replace("L/", ""))
    return list(szen.values()), einstellungen


# ---------------------------------------------------------------------------------------------------------------------
# Standardszenarien (T3)


def nutzlast_param(params: dict[str, Any] | None) -> tuple[str, float] | None:
    for k, v in (params or {}).items():
        if NUTZLAST_PARAM.search(str(k)) and isinstance(v, (int, float)) and v > 0:
            return str(k), float(v)
    return None


def standard(eigene: list[Szenario], params: dict[str, Any] | None, auf_rollen: bool,
             oben: list[tuple[str, np.ndarray]] | None = None) -> list[Szenario]:
    """Szenarien, die Kev CAD von selbst rechnet: immer das Eigengewicht; ohne eigene Lasten die Nutzlast aus einem
    Parameter (``nutzlast``, ``zuladung``, ``traglast`` … in kg) auf den obersten Teilen; auf Rollen das Bremsen."""
    namen = {s.name for s in eigene}
    out: list[Szenario] = []
    if "Eigengewicht" not in namen:
        out.append(Szenario("Eigengewicht", quelle="standard", beschreibung="nur das eigene Gewicht"))
    hat_lasten = any(s.lasten for s in eigene)
    nl = nutzlast_param(params)
    if nl and not hat_lasten and oben and "Nutzlast" not in namen:
        k, kg = nl
        je = kg / len(oben)
        s = Szenario("Nutzlast", quelle="standard", beschreibung=f"{kg:g} kg aus param {k!r} auf den obersten Teilen")
        for name, p in oben:
            s.lasten.append(Last([name], np.array([0.0, 0.0, -je * G]), p, je, text=f"Anteil von {k}"))
        out.append(s)
    if auf_rollen and not any(s.dynamisch for s in eigene) and "Bremsen" not in namen:
        out.append(Szenario("Bremsen", beschleunigung=np.array([-3.0, 0.0, 0.0]), dynamisch=True, quelle="standard",
                            beschreibung="auf Rollen: Bremsen mit 3 m/s² in −X (Schieben in +X); Lasten aus der "
                                         "Trägheit"))
    return out

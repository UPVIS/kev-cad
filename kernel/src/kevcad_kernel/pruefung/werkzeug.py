"""Werkzeugzugang für Schrauben und Muttern.

Freiraum je Antrieb als Zylinder entlang der Schraubenachse über dem Kopf (Bit, Schraubendreher, Steckschlüssel); für
Sechskante zusätzlich ein Gabel- oder Ringschlüssel von der Seite. Maße nach ISO 4762/7380/10642 (Innensechskant)
und ISO 4014/4017/4032 (Schlüsselweite), Freiräume als Faustwerte für gängige Werkzeuge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from kevcad_kernel.pruefung.koerper import Koerper

# Schlüsselweite Innensechskant je Nenndurchmesser (ISO 4762)
INNEN_4762 = {2: 1.5, 2.5: 2, 3: 2.5, 4: 3, 5: 4, 6: 5, 8: 6, 10: 8, 12: 10, 14: 12, 16: 14, 20: 17, 24: 19}
# Linsen- und Senkkopf (ISO 7380, ISO 10642)
INNEN_FLACH = {3: 2, 4: 2.5, 5: 3, 6: 4, 8: 5, 10: 6, 12: 8, 16: 10}
# Schlüsselweite Außensechskant (ISO 4014/4017/4032)
AUSSEN_SW = {2: 4, 2.5: 5, 3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18, 14: 21, 16: 24, 20: 30, 24: 36}
TORX = {3: "T10", 4: "T20", 5: "T25", 6: "T30", 8: "T40", 10: "T50", 12: "T55"}

INNEN_TYPEN = ("SocketHeadCapScrew", "ButtonHeadScrew", "CounterSunkScrew", "LowHeadSocketScrew", "SetScrew")
AUSSEN_TYPEN = ("HexHeadScrew", "HexNut", "DomedCapNut", "HexNutWithFlange", "SquareNut", "HeatSetNut")


@dataclass
class Werkzeug:
    name: str  # „Innensechskant 6“, „Steckschlüssel SW 13“
    durchmesser: float  # Freiraum-Ø über dem Kopf
    laenge: float  # Freiraum-Länge entlang der Achse
    sw: float | None = None  # Schlüsselweite für den seitlichen Gabelschlüssel
    seitlich: bool = False  # Gabel- oder Ringschlüssel von der Seite möglich

    @property
    def text(self) -> str:
        from kevcad_kernel.bom import de_num

        return f"{self.name} (Freiraum Ø {de_num(self.durchmesser, 1)} × {de_num(self.laenge, 0)} mm)"


def _nenn(info: dict[str, Any]) -> float:
    d = info.get("d")
    if d:
        return float(d)
    m = re.match(r"[Mm](\d+(?:[.,]\d+)?)", str(info.get("groesse") or ""))
    return float(m.group(1).replace(",", ".")) if m else 6.0


def _naechster(tab: dict[float, float], d: float) -> float:
    k = min(tab, key=lambda x: abs(x - d))
    return tab[k]


def werkzeug_fuer(info: dict[str, Any]) -> Werkzeug | None:
    """Werkzeug für ein Verbindungselement aus dem Lager (``info`` aus dem Lauf) oder None (Scheibe, unbekannt)."""
    art, typ = info.get("art"), str(info.get("typ") or "")
    if art not in ("schraube", "mutter"):
        return None
    d = _nenn(info)
    dk = float(info.get("kopf_d") or 1.6 * d + 1)
    if typ in INNEN_TYPEN or (art == "schraube" and typ not in AUSSEN_TYPEN):
        tab = INNEN_4762 if typ == "SocketHeadCapScrew" else INNEN_FLACH
        s = float(info.get("schluessel") or _naechster(tab, d))
        s = round(s * 2) / 2
        return Werkzeug(f"Innensechskant {str(s).rstrip('0').rstrip('.').replace('.', ',')}", max(dk + 2, s + 6),
                        max(30.0, 5 * d))
    s = float(info.get("schluessel") or _naechster(AUSSEN_SW, d))
    return Werkzeug(f"Steckschlüssel SW {str(s).rstrip('0').rstrip('.').replace('.', ',')}", 1.6 * s + 4,
                    max(40.0, 3 * s), sw=s, seitlich=True)


def werkzeug_aus_text(text: str, d: float = 6.0) -> Werkzeug | None:
    """Erklärtes Werkzeug aus model.py: „inbus 6“, „torx t30“, „gabel 13“, „ring 13“, „nuss 13“, „hand“."""
    t = str(text or "").strip().lower().replace("schlüssel", "schluessel")
    if not t or t in ("hand", "keins", "kein", "ohne"):
        return None
    zahl = re.search(r"(\d+(?:[.,]\d+)?)", t)
    n = float(zahl.group(1).replace(",", ".")) if zahl else None
    if t.startswith(("inbus", "innensechskant", "imbus", "hex")):
        s = n or _naechster(INNEN_4762, d)
        return Werkzeug(f"Innensechskant {str(s).rstrip('0').rstrip('.')}", max(2.2 * s + 2, s + 6), max(30.0, 6 * s))
    if t.startswith(("torx", "tx")):
        s = n or 30
        return Werkzeug(f"Torx T{int(s)}", max(10.0, 0.25 * s + 6), 40.0)
    if t.startswith(("gabel", "maul", "ring")):
        s = n or _naechster(AUSSEN_SW, d)
        return Werkzeug(f"{'Ringschlüssel' if t.startswith('ring') else 'Gabelschlüssel'} SW {s:g}", 1.6 * s + 4,
                        max(40.0, 3 * s), sw=s, seitlich=True)
    if t.startswith(("nuss", "steck", "knarre", "ratsche")):
        s = n or _naechster(AUSSEN_SW, d)
        return Werkzeug(f"Steckschlüssel SW {s:g}", 1.6 * s + 4, max(40.0, 3 * s), sw=s, seitlich=True)
    if t.startswith(("schraubendreher", "schlitz", "kreuz", "ph", "pz")):
        return Werkzeug("Schraubendreher", 8.0, 80.0)
    return Werkzeug(text, 12.0, 50.0)


# ---------------------------------------------------------------------------------------------------------------------
# Freiraum prüfen


def _zylinder(start: np.ndarray, achse: np.ndarray, r: float, h: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, start)), gp_Dir(*map(float, achse))), r, h).Shape()


def _quader(zentrum: np.ndarray, ex: np.ndarray, ey: np.ndarray, ez: np.ndarray, gx: float, gy: float,
            gz: float) -> Any:
    """Quader mit Mitte und Achsen (ex, ey, ez), Kantenlängen gx, gy, gz."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    ecke = zentrum - ex * gx / 2 - ey * gy / 2 - ez * gz / 2
    ax = gp_Ax2(gp_Pnt(*map(float, ecke)), gp_Dir(*map(float, ez)), gp_Dir(*map(float, ex)))
    return BRepPrimAPI_MakeBox(ax, gx, gy, gz).Shape()


def _box_von(shape: Any) -> tuple[np.ndarray, np.ndarray]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    bb = Bnd_Box()
    BRepBndLib.Add_s(shape, bb)
    lo, hi = bb.CornerMin(), bb.CornerMax()
    return np.array([lo.X(), lo.Y(), lo.Z()]), np.array([hi.X(), hi.Y(), hi.Z()])


def im_weg(werkzeugkoerper: Any, andere: list[Koerper], min_volumen: float = 0.5) -> list[str]:
    """Namen der Teile, die den Werkzeugkörper durchdringen."""
    from kevcad_kernel.pruefung.kollision import schnittmenge, volumen_und_achsen

    lo, hi = _box_von(werkzeugkoerper)
    out = []
    for q in andere:
        if np.any(np.minimum(hi, q.bmax) - np.maximum(lo, q.bmin) <= 0):
            continue
        c = schnittmenge(werkzeugkoerper, q.shape)
        if c is None:
            continue
        vol, _, _ = volumen_und_achsen(c)
        if vol > min_volumen:
            out.append(q.name)
    return out


def senkrechte(achse: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(achse[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(achse, a)
    u /= np.linalg.norm(u)
    return u, np.cross(achse, u)


@dataclass
class Zugang:
    ok: bool
    werkzeug: Werkzeug
    seite: str  # „von oben“ …, für den Text
    blockiert: list[str]
    nur_seitlich: bool = False


def kopfmasse(k: Koerper) -> None:
    """Kopf oben/unten (entlang der Achse ab dem Ursprung) und Kopfdurchmesser aus dem Netz, falls sie fehlen."""
    info = k.info
    if info.get("achse") is None or info.get("ursprung") is None or not len(k.pos):
        return
    a = np.asarray(info["achse"], dtype=np.float64)
    a /= np.linalg.norm(a)
    rel = k.pos - np.asarray(info["ursprung"], dtype=np.float64)
    t = rel @ a
    r = np.linalg.norm(rel - np.outer(t, a), axis=1)
    info.setdefault("kopf_oben", float(t.max()))
    # Kopf unten: Mutter ihre Unterseite, Schrauben z = 0 (nur für den Gabelschlüssel am Sechskant gebraucht)
    info.setdefault("kopf_unten", float(t.min()) if info.get("art") == "mutter" else 0.0)
    info.setdefault("kopf_d", float(2 * r.max()))


def pruefe_zugang(k: Koerper, w: Werkzeug, andere: list[Koerper]) -> Zugang | None:
    """Freiraum für ``w`` an Verbindungselement k. ``andere`` sind die Teile, die beim Anziehen schon da sind."""
    info = k.info
    achse = info.get("achse")
    ursprung = info.get("ursprung")
    if achse is None or ursprung is None:
        return None
    kopfmasse(k)
    a = np.asarray(achse, dtype=np.float64)
    a /= np.linalg.norm(a)
    o = np.asarray(ursprung, dtype=np.float64)
    andere = [q for q in andere if q.name != k.name]
    seiten: list[tuple[np.ndarray, float]] = []  # (Richtung, Startabstand auf der Achse)
    if info.get("art") == "schraube":
        seiten.append((a, float(info.get("kopf_oben") or 0.0)))
    else:  # Mutter: von beiden Seiten möglich
        seiten.append((a, float(info.get("kopf_oben") or 0.0)))
        seiten.append((-a, -float(info.get("kopf_unten") or 0.0)))
    alle_blocker: list[str] = []
    for richtung, start in seiten:
        p0 = o + a * start + richtung * 0.05
        zyl = _zylinder(p0, richtung, w.durchmesser / 2, w.laenge)
        blocker = im_weg(zyl, andere)
        if not blocker:
            from kevcad_kernel.pruefung.befund import richtung_text

            return Zugang(True, w, "entlang " + richtung_text(richtung), [])
        alle_blocker += [b for b in blocker if b not in alle_blocker]
    if w.seitlich and w.sw:
        # Gabelschlüssel von der Seite: Maul um den Sechskant, Griff radial nach außen
        h_lo = float(info.get("kopf_unten") or 0.0) + 0.1
        h_hi = float(info.get("kopf_oben") or 0.0) - 0.1
        if h_hi > h_lo:
            u, v = senkrechte(a)
            for i in range(8):
                ang = i * np.pi / 4
                rad = np.cos(ang) * u + np.sin(ang) * v
                quer = np.cross(a, rad)
                laenge = 4 * w.sw
                mitte = o + a * (h_lo + h_hi) / 2 + rad * (w.sw * 0.25 + laenge / 2)
                box = _quader(mitte, rad, quer, a, laenge, 2.2 * w.sw, h_hi - h_lo)
                if not im_weg(box, andere):
                    return Zugang(True, w, "seitlich", [], nur_seitlich=True)
    return Zugang(False, w, "", alle_blocker)

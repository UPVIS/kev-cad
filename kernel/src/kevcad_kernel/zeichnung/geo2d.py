"""2D-Werkzeug für das Blatt: Rechtecke, Textbreiten, Kollisionen, Clipping, Schraffur."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

# Breite je Zeichen relativ zur Versalhöhe (ISO 3098 Schriftform B ≈ Helvetica: Ziffern 0,56 h/0,72 …). Die Werte
# sind bewusst etwas großzügig, damit Texte in der App sicher nicht überlappen.
_SCHMAL = set("il.,;:!|'` ")
_BREIT = set("MWmw@%Ø×")


def textbreite(text: str, hoehe: float) -> float:
    w = 0.0
    for ch in str(text):
        if ch in _SCHMAL:
            w += 0.36
        elif ch in _BREIT:
            w += 1.08
        elif ch.isupper():
            w += 0.86
        else:
            w += 0.74
    return w * hoehe


@dataclass
class Rechteck:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def breite(self) -> float:
        return self.x1 - self.x0

    @property
    def hoehe(self) -> float:
        return self.y1 - self.y0

    @property
    def mitte(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    def schneidet(self, o: Rechteck, abstand: float = 0.0) -> bool:
        return not (self.x1 + abstand <= o.x0 or o.x1 + abstand <= self.x0 or self.y1 + abstand <= o.y0
                    or o.y1 + abstand <= self.y0)

    def enthaelt(self, o: Rechteck, tol: float = 1e-6) -> bool:
        return o.x0 >= self.x0 - tol and o.x1 <= self.x1 + tol and o.y0 >= self.y0 - tol and o.y1 <= self.y1 + tol

    def erweitert(self, d: float) -> Rechteck:
        return Rechteck(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def verschoben(self, dx: float, dy: float) -> Rechteck:
        return Rechteck(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)

    def vereint(self, o: Rechteck) -> Rechteck:
        return Rechteck(min(self.x0, o.x0), min(self.y0, o.y0), max(self.x1, o.x1), max(self.y1, o.y1))

    def liste(self) -> list[float]:
        return [round(self.x0, 3), round(self.y0, 3), round(self.x1, 3), round(self.y1, 3)]


def rechteck_von(punkte: Any) -> Rechteck:
    p = np.asarray(punkte, dtype=float).reshape(-1, 2)
    return Rechteck(float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()))


def textbox(text: str, lage: tuple[float, float], hoehe: float, winkel: float = 0.0, anker: str = "mitte",
            rand: float = 0.6) -> Rechteck:
    """Hüllrechteck eines Textes (Ankerpunkt auf der Grundlinie, Winkel 0 oder 90 Grad, sonst Hülle der Drehung)."""
    w = textbreite(text, hoehe)
    x0 = {"links": 0.0, "mitte": -w / 2, "rechts": -w}.get(anker, -w / 2)
    ecken = np.array([[x0 - rand, -rand - 0.25 * hoehe], [x0 + w + rand, -rand - 0.25 * hoehe],
                      [x0 + w + rand, hoehe + rand], [x0 - rand, hoehe + rand]])
    a = math.radians(winkel)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    pts = ecken @ rot.T + np.asarray(lage, dtype=float)
    return rechteck_von(pts)


# ---------------------------------------------------------------------------------------------------------------------
# Kollisionen: Rasterindex über Strecken und Rechtecke
# ---------------------------------------------------------------------------------------------------------------------


def _seg_rect(a: np.ndarray, b: np.ndarray, r: Rechteck) -> bool:
    """Schneidet die Strecke ab das Rechteck? (Liang-Barsky)"""
    x0, y0 = float(a[0]), float(a[1])
    dx, dy = float(b[0]) - x0, float(b[1]) - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r.x0), (dx, r.x1 - x0), (-dy, y0 - r.y0), (dy, r.y1 - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


class Belegung:
    """Belegte Fläche des Blatts: Strecken (Geometrie, Maßlinien) und Rechtecke (Texte, Tabellen)."""

    def __init__(self, zelle: float = 6.0) -> None:
        self.zelle = zelle
        self._segs: dict[tuple[int, int], list[tuple[np.ndarray, np.ndarray, str]]] = {}
        self._rects: dict[tuple[int, int], list[tuple[Rechteck, str]]] = {}
        self.grenze: Rechteck | None = None  # Texte nur innerhalb (Zeichenfläche)

    def _zellen(self, x0: float, y0: float, x1: float, y1: float) -> Iterable[tuple[int, int]]:
        z = self.zelle
        for i in range(int(math.floor(x0 / z)), int(math.floor(x1 / z)) + 1):
            for j in range(int(math.floor(y0 / z)), int(math.floor(y1 / z)) + 1):
                yield (i, j)

    def strecken(self, polylinien: Iterable[np.ndarray], art: str = "geo") -> None:
        for pl in polylinien:
            pl = np.asarray(pl, dtype=float)
            for a, b in zip(pl[:-1], pl[1:]):
                for c in self._zellen(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])):
                    self._segs.setdefault(c, []).append((a, b, art))

    def rechteck(self, r: Rechteck, art: str = "text") -> None:
        for c in self._zellen(r.x0, r.y0, r.x1, r.y1):
            self._rects.setdefault(c, []).append((r, art))

    def frei(self, r: Rechteck, ohne: tuple[str, ...] = ()) -> bool:
        if self.grenze is not None and not self.grenze.enthaelt(r):
            return False
        for c in self._zellen(r.x0, r.y0, r.x1, r.y1):
            for a, b, art in self._segs.get(c, ()):
                if art not in ohne and _seg_rect(a, b, r):
                    return False
            for o, art in self._rects.get(c, ()):
                if art not in ohne and r.schneidet(o):
                    return False
        return True

    GEWICHT = {"text": 10.0, "tabelle": 50.0, "mass": 4.0, "geo": 3.0, "verdeckt": 1.0}

    def kosten(self, r: Rechteck) -> float:
        """Gewichtete Zahl der Kollisionen (Texte über Texten wiegen schwer, über verdeckten Kanten leicht)."""
        if self.grenze is not None and not self.grenze.enthaelt(r):
            return 1000.0
        k = 0.0
        gesehen: set[int] = set()
        for c in self._zellen(r.x0, r.y0, r.x1, r.y1):
            for a, b, art in self._segs.get(c, ()):
                if id(a) in gesehen:
                    continue
                if _seg_rect(a, b, r):
                    gesehen.add(id(a))
                    k += self.GEWICHT.get(art, 2.0)
            for o, art in self._rects.get(c, ()):
                if id(o) in gesehen:
                    continue
                if r.schneidet(o):
                    gesehen.add(id(o))
                    k += self.GEWICHT.get(art, 5.0)
        return k

    def strecke_frei(self, a: Any, b: Any, ohne: tuple[str, ...] = ("geo",)) -> bool:
        """Kreuzt die Strecke ein Rechteck (Text)? Geometrie zählt standardmäßig nicht (Hinweislinien dürfen über
        Kanten gehen)."""
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        for c in self._zellen(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])):
            for o, art in self._rects.get(c, ()):
                if art not in ohne and _seg_rect(a, b, o):
                    return False
        return True


# ---------------------------------------------------------------------------------------------------------------------
# Clipping
# ---------------------------------------------------------------------------------------------------------------------


def clip_kreis(pl: np.ndarray, mitte: Any, radius: float) -> list[np.ndarray]:
    """Teile der Polylinie innerhalb des Kreises (für Einzelheiten)."""
    c = np.asarray(mitte, dtype=float)
    out: list[np.ndarray] = []
    aktuell: list[np.ndarray] = []

    def innen(p: np.ndarray) -> bool:
        return float(np.linalg.norm(p - c)) <= radius

    def schnitt(p: np.ndarray, q: np.ndarray) -> np.ndarray:
        d = q - p
        f = p - c
        a = float(d @ d)
        b = 2 * float(f @ d)
        cc = float(f @ f) - radius * radius
        disc = max(0.0, b * b - 4 * a * cc)
        s = math.sqrt(disc)
        for t in sorted(((-b - s) / (2 * a), (-b + s) / (2 * a))):
            if 0 <= t <= 1:
                return p + d * t
        return p

    pts = np.asarray(pl, dtype=float)
    # fein unterteilen, damit lange Geraden richtig geschnitten werden
    for p, q in zip(pts[:-1], pts[1:]):
        ip, iq = innen(p), innen(q)
        if ip and iq:
            if not aktuell:
                aktuell.append(p)
            aktuell.append(q)
        elif ip and not iq:
            if not aktuell:
                aktuell.append(p)
            aktuell.append(schnitt(p, q))
            out.append(np.array(aktuell))
            aktuell = []
        elif not ip and iq:
            aktuell = [schnitt(q, p), q]
        else:
            # beide außen: Sehne durch den Kreis?
            d = q - p
            a = float(d @ d)
            if a < 1e-18:
                continue
            t = float(np.clip((c - p) @ d / a, 0, 1))
            if float(np.linalg.norm(p + d * t - c)) < radius:
                e = schnitt(p, q)
                f = schnitt(q, p)
                out.append(np.array([e, f]))
    if len(aktuell) >= 2:
        out.append(np.array(aktuell))
    return out


def clip_bereiche(pl: np.ndarray, bereiche: list[tuple[float, float]], achse: int = 0) -> list[np.ndarray]:
    """Teile der Polylinie außerhalb der Intervalle ``bereiche`` (für unterbrochene Ansichten)."""
    if not bereiche:
        return [pl]
    stuecke = [np.asarray(pl, dtype=float)]
    for lo, hi in bereiche:
        neu = []
        for s in stuecke:
            neu += _ohne_intervall(s, lo, hi, achse)
        stuecke = neu
    return [s for s in stuecke if len(s) >= 2]


def _ohne_intervall(pl: np.ndarray, lo: float, hi: float, achse: int) -> list[np.ndarray]:
    """Polylinie ohne den Teil, dessen Koordinate ``achse`` strikt zwischen lo und hi liegt."""
    out: list[np.ndarray] = []
    akt: list[np.ndarray] = []
    for p, q in zip(pl[:-1], pl[1:]):
        vp, vq = float(p[achse]), float(q[achse])
        ts = [0.0, 1.0]
        if abs(vq - vp) > 1e-12:
            for g in (lo, hi):
                t = (g - vp) / (vq - vp)
                if 0.0 < t < 1.0:
                    ts.append(t)
        ts.sort()
        for t0, t1 in zip(ts[:-1], ts[1:]):
            a, b = p + (q - p) * t0, p + (q - p) * t1
            mitte = vp + (vq - vp) * (t0 + t1) / 2
            if lo < mitte < hi:
                if len(akt) >= 2:
                    out.append(np.array(akt))
                akt = []
                continue
            if not akt:
                akt = [a]
            elif float(np.linalg.norm(akt[-1] - a)) > 1e-9:
                if len(akt) >= 2:
                    out.append(np.array(akt))
                akt = [a]
            akt.append(b)
    if len(akt) >= 2:
        out.append(np.array(akt))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Schraffur (ISO 128-50)
# ---------------------------------------------------------------------------------------------------------------------


def schraffur(ringe: list[np.ndarray], winkel: float = 45.0, abstand: float = 2.5) -> list[np.ndarray]:
    """Parallele Strecken im Inneren der Fläche aus geschlossenen Ringen (gerade-ungerade-Regel, also auch mit
    Löchern). Winkel in Grad gegen die x-Achse, Abstand in Blatt-mm."""
    segs = [np.stack([r[:-1], r[1:]], axis=1) for r in ringe if len(r) >= 3]
    if not segs:
        return []
    S = np.concatenate(segs)
    a = math.radians(winkel)
    u = np.array([math.cos(a), math.sin(a)])  # Linienrichtung
    n = np.array([-u[1], u[0]])  # Normale: Lage der Linien
    s0 = S[:, 0] @ n
    s1 = S[:, 1] @ n
    lo, hi = float(min(s0.min(), s1.min())), float(max(s0.max(), s1.max()))
    out: list[np.ndarray] = []
    k0 = math.ceil(lo / abstand)
    for k in range(k0, int(math.floor(hi / abstand)) + 1):
        c = k * abstand
        m = ((s0 - c) * (s1 - c)) < 0
        if not np.any(m):
            continue
        t = (c - s0[m]) / (s1[m] - s0[m])
        P = S[m, 0] + (S[m, 1] - S[m, 0]) * t[:, None]
        tt = np.sort(P @ u)
        for i in range(0, len(tt) - 1, 2):
            if tt[i + 1] - tt[i] > 1e-6:
                out.append(np.array([u * tt[i] + n * c, u * tt[i + 1] + n * c]))
    return out


def ringe_aus_strecken(linien: list[np.ndarray], tol: float = 1e-4) -> list[np.ndarray]:
    """Geschlossene Ringe aus Polylinien mit gemeinsamen Endpunkten (für die Schraffur von Schnittflächen)."""
    from kevcad_kernel.zeichnung.projektion import verbinde

    out = []
    for pl in verbinde(linien, tol):
        if len(pl) >= 3 and float(np.linalg.norm(pl[0] - pl[-1])) <= max(tol * 10, 1e-3):
            out.append(pl)
    return out

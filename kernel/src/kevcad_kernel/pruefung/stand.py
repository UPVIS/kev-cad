"""Schweben und Standsicherheit.

Kontaktgraph: Teile, die sich berühren oder durchdringen (Abstand bis ``BERUEHR_TOL``, also auch Spiel in einer
Bohrung), hängen zusammen; Verbindungselemente berühren beide Partner und verbinden sie damit. Boden ist die erklärte
Bodenebene (``boden(z)``) oder die tiefste Stelle des Modells. Eine Gruppe ohne Weg zum Boden und ohne ``befestigt``
schwebt. Für jede Gruppe auf dem Boden: Masse (Materialdichte, sonst Annahme), Schwerpunkt, Standfläche (konvexe Hülle
der Bodenkontakte), Abstand des Schwerpunkts zum Rand und Kippwinkel.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.bom import de_num
from kevcad_kernel.pruefung.befund import (
    BODEN_TOL,
    DICHTE_ANNAHME,
    KIPP_WARNUNG_GRAD,
    befund,
    mm,
    punkt,
)
from kevcad_kernel.pruefung.koerper import Koerper
from kevcad_kernel.pruefung.pruefer import PruefKontext, registriere
from kevcad_kernel.pruefung.raster import luecke

Z = np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------------------------------------------------------------
# Hilfen


class Gruppen:
    """Union-Find über Teilenamen."""

    def __init__(self, namen: list[str]) -> None:
        self.p = {n: n for n in namen}

    def find(self, n: str) -> str:
        while self.p[n] != n:
            self.p[n] = self.p[self.p[n]]
            n = self.p[n]
        return n

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def gruppen(self) -> list[list[str]]:
        out: dict[str, list[str]] = {}
        for n in self.p:
            out.setdefault(self.find(n), []).append(n)
        return list(out.values())


def huelle(pts: np.ndarray) -> np.ndarray:
    """Konvexe Hülle (gegen den Uhrzeigersinn) von 2D-Punkten, monotone Kette."""
    p = np.unique(np.round(pts, 4), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list[np.ndarray] = []
    for q in p[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def _abstand_segment(c: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = 0.0 if not np.any(ab) else float(np.clip(np.dot(c - a, ab) / np.dot(ab, ab), 0, 1))
    return float(np.linalg.norm(c - (a + t * ab)))


def rand_abstand(c: np.ndarray, poly: np.ndarray) -> tuple[float, int]:
    """Abstand von c zum Rand der Standfläche: positiv innen, negativ außen; dazu der Index der nächsten Kante."""
    n = len(poly)
    if n == 0:
        return -math.inf, -1
    if n == 1:
        return -float(np.linalg.norm(c - poly[0])), 0
    if n == 2:
        return -_abstand_segment(c, poly[0], poly[1]), 0
    area = 0.5 * sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    if area < 1.0:  # entartet (Linie): wie eine Kante behandeln
        i, j = np.argmin(poly[:, 0] + poly[:, 1]), np.argmax(poly[:, 0] + poly[:, 1])
        return -_abstand_segment(c, poly[i], poly[j]), 0
    best, best_i, inside = math.inf, -1, True
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = b - a
        # links der Kante = innen (gegen den Uhrzeigersinn)
        side = e[0] * (c[1] - a[1]) - e[1] * (c[0] - a[0])
        if side < 0:
            inside = False
        d = _abstand_segment(c, a, b)
        if d < best:
            best, best_i = d, i
    return (best if inside else -best), best_i


def bodenkontakte(k: Koerper, boden_z: float, cache: dict | None = None) -> np.ndarray:
    """xy-Punkte, mit denen k auf dem Boden steht: Schnitt mit einer flachen Schicht über dem Boden (exakt), sonst
    die Netzpunkte in der Schicht."""
    key = ("boden", k.key, round(boden_z, 4))
    if cache is not None and key in cache:
        return cache[key]
    pts = np.zeros((0, 2))
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt

        from kevcad_kernel.pruefung.kollision import schnittmenge, vernetzen

        lo = gp_Pnt(float(k.bmin[0]) - 1, float(k.bmin[1]) - 1, boden_z - 1.0)
        hi = gp_Pnt(float(k.bmax[0]) + 1, float(k.bmax[1]) + 1, boden_z + BODEN_TOL)
        schicht = BRepPrimAPI_MakeBox(lo, hi).Shape()
        common = schnittmenge(k.shape, schicht)
        if common is not None:
            p3, _, _ = vernetzen(common, 0.05)
            if len(p3):
                pts = p3[:, :2].astype(np.float64)
    except Exception:  # noqa: BLE001 - dann eben das Netz
        pts = np.zeros((0, 2))
    if not len(pts):
        p3 = k.punkte_unter(boden_z + BODEN_TOL)
        pts = p3[:, :2] if len(p3) else np.zeros((0, 2))
    if cache is not None:
        cache[key] = pts
    return pts


# ---------------------------------------------------------------------------------------------------------------------
# Prüfung


@dataclass
class StandErgebnis:
    befunde: list[dict[str, Any]] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    gruppen: list[list[str]] = field(default_factory=list)


def masse_von(k: Koerper) -> tuple[float, bool]:
    """Masse in g und ob sie angenommen ist."""
    if k.masse_g is not None:
        return float(k.masse_g), False
    return k.volumen * DICHTE_ANNAHME * 1e-3, True


def pruefe_stand(koerper: list[Koerper], kontakte: list[tuple[str, str]], befestigt: dict[str, str],
                 boden_z: float | None = None, cache: dict | None = None) -> StandErgebnis:
    out = StandErgebnis()
    if not koerper:
        return out
    by = {k.name: k for k in koerper}
    erklaert = boden_z is not None
    bz = float(boden_z) if erklaert else float(min(k.bmin[2] for k in koerper))
    uf = Gruppen(list(by))
    for a, b in kontakte:
        if a in by and b in by:
            uf.union(a, b)
    gruppen = sorted(uf.gruppen(), key=lambda g: (-len(g), sorted(g)[0]))
    out.gruppen = gruppen
    am_boden = {n for n, k in by.items() if k.bmin[2] <= bz + BODEN_TOL}
    annahmen: list[str] = []
    info_gruppen = []
    for g in gruppen:
        g_sorted = sorted(g, key=lambda n: list(by).index(n))
        fest = [n for n in g_sorted if n in befestigt]
        auf = [n for n in g_sorted if n in am_boden]
        massen = [masse_von(by[n]) for n in g_sorted]
        m_ges = sum(m for m, _ in massen)
        annahmen += [n for n, (_, ann) in zip(g_sorted, massen) if ann]
        sp = (sum(m * by[n].zentrum for n, (m, _) in zip(g_sorted, massen)) / m_ges if m_ges > 0
              else np.mean([by[n].zentrum for n in g_sorted], axis=0))
        eintrag: dict[str, Any] = {"teile": g_sorted, "masse_kg": round(m_ges / 1000.0, 4),
                                   "schwerpunkt": [round(float(c), 2) for c in sp]}
        if fest:
            eintrag["befestigt"] = {n: befestigt[n] for n in fest}
            info_gruppen.append(eintrag)
            continue
        if not auf:
            out.befunde.append(_schwebt(g_sorted, by, bz, erklaert))
            eintrag["schwebt"] = True
            info_gruppen.append(eintrag)
            continue
        pts = np.vstack([bodenkontakte(by[n], bz, cache) for n in auf] + [np.zeros((0, 2))])
        poly = huelle(pts) if len(pts) else np.zeros((0, 2))
        rand, kante = rand_abstand(sp[:2], poly)
        h = max(float(sp[2]) - bz, 1e-6)
        winkel = math.degrees(math.atan2(rand, h))
        eintrag.update(stuetzpolygon=[[round(float(x), 2), round(float(y), 2)] for x, y in poly],
                       rand_abstand=round(rand, 2), kippwinkel=round(winkel, 2))
        if len(poly) >= 2 and kante >= 0:
            a, b = poly[kante], poly[(kante + 1) % len(poly)]
            eintrag["kante"] = [[round(float(a[0]), 2), round(float(a[1]), 2)],
                                [round(float(b[0]), 2), round(float(b[1]), 2)]]
        info_gruppen.append(eintrag)
        name = _gruppen_name(g_sorted)
        ort = [float(sp[0]), float(sp[1]), bz]
        if rand < -0.05:
            out.befunde.append(befund(
                "kippt", g_sorted, "fehler",
                f"{name} kippt: der Schwerpunkt ({punkt(sp)}) liegt {mm(-rand)} außerhalb der Standfläche "
                f"(Gesamtmasse {_kg(m_ges)}).",
                "Standfläche verbreitern (Füße oder Räder weiter außen), Schwerpunkt senken oder zur Mitte bringen, "
                "Gegengewicht vorsehen oder die Gruppe befestigen (befestigt(teil, grund=...) nach Rückfrage bei Kevin).",
                wert={"rand_abstand": round(rand, 2), "kippwinkel": round(winkel, 2), "masse_kg": round(m_ges / 1000, 3)},
                ort=ort))
        elif len(g_sorted) > 1 and winkel < KIPP_WARNUNG_GRAD:
            out.befunde.append(befund(
                "standsicherheit", g_sorted, "warnung",
                f"{name} steht knapp: kippt schon bei {de_num(winkel, 1)}° Neigung (Schwerpunkt {mm(rand)} vom Rand der "
                "Standfläche).",
                "Standfläche verbreitern oder Schwerpunkt senken.",
                wert={"rand_abstand": round(rand, 2), "kippwinkel": round(winkel, 2)}, ort=ort))
    if annahmen:
        n = len(annahmen)
        liste = ", ".join(annahmen[:6]) + (" …" if n > 6 else "")
        out.befunde.append(befund(
            "annahme", annahmen, "hinweis",
            f"Masse von {n} {'Teil' if n == 1 else 'Teilen'} ohne Material angenommen mit "
            f"{str(DICHTE_ANNAHME).replace('.', ',')} g/cm³: {liste}.",
            "Material aus dem Katalog angeben (show(..., material=...) oder Lagerteil verbauen), dann stimmen "
            "Masse, Schwerpunkt und Kippwinkel."))
    out.info = {"boden_z": round(bz, 3), "boden_erklaert": erklaert, "gruppen": info_gruppen}
    return out


def _kg(g: float) -> str:
    from kevcad_kernel.bom import de_num

    return f"{de_num(g / 1000.0, 2)} kg" if g >= 1000 else f"{de_num(g, 0)} g"


def _gruppen_name(namen: list[str]) -> str:
    if len(namen) == 1:
        return namen[0]
    pre = namen[0].split("/")[0]
    if all(n.split("/")[0] == pre for n in namen) and "/" in namen[0]:
        return f"Baugruppe {pre} ({len(namen)} Teile)"
    return f"Die Gruppe aus {namen[0]} und {len(namen) - 1} weiteren Teilen"


def _schwebt(gruppe: list[str], by: dict[str, Koerper], bz: float, erklaert: bool) -> dict[str, Any]:
    """Befund für eine schwebende Gruppe: wie weit sie fallen würde und worauf."""
    tief = min(gruppe, key=lambda n: by[n].bmin[2])
    fall_boden = float(by[tief].bmin[2]) - bz
    fall, auf = fall_boden, "den Boden"
    andere = [k for n, k in by.items() if n not in gruppe]
    for n in gruppe:
        c = by[n]
        for q in andere:
            # nur Teile, die unter c etwas haben und sich in der Draufsicht mit c überdecken
            if q.bmin[2] >= c.bmin[2] or np.any(np.minimum(c.bmax[:2], q.bmax[:2])
                                                 - np.maximum(c.bmin[:2], q.bmin[:2]) <= 0):
                continue
            try:
                d = luecke(c, q, -Z)
            except Exception:  # noqa: BLE001
                d = None
            if d is not None and d < fall:
                fall, auf = d, q.name
    name = gruppe[0] if len(gruppe) == 1 else f"{gruppe[0]} und {len(gruppe) - 1} weitere"
    verb = "schwebt" if len(gruppe) == 1 else "schweben"
    ort = [float((by[tief].bmin[0] + by[tief].bmax[0]) / 2), float((by[tief].bmin[1] + by[tief].bmax[1]) / 2),
           float(by[tief].bmin[2])]
    return befund(
        "schwebt", gruppe, "fehler",
        f"{name} {verb}: keine Verbindung zum Boden oder zu einem tragenden Teil; fiele etwa {mm(fall)} auf {auf}.",
        f"Um {mm(fall)} absenken (z − {mm(fall)}), bis es auf {auf} aufliegt, oder mit einem tragenden Teil verbinden "
        "(Halter, Schraube, Auflage). Ist es an einer Wand oder Decke befestigt: befestigt(teil, grund=...) nach "
        "Rückfrage bei Kevin.",
        wert={"fallweg": round(fall, 2), "auf": auf}, ort=ort)


# ---------------------------------------------------------------------------------------------------------------------
# Prüffunktion


def pruefe_standsicherheit(ctx: PruefKontext) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    boden = ctx.erklaerungen.get("boden")
    bz = float(boden["z"]) if isinstance(boden, dict) and boden.get("z") is not None else None
    erg = pruefe_stand(list(ctx.koerper.values()), ctx.kontakte, ctx.befestigt(), bz, ctx.stand_cache)
    ctx.ergebnis["stand"] = erg.info
    ctx.zeiten["stand"] = (time.perf_counter() - t0) * 1000
    return erg.befunde


registriere("stand", pruefe_standsicherheit)

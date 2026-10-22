"""Geometrische Signatur eines Druckteils, unabhängig von seiner Lage (Strang „Feinschliff 2“, Punkt 3).

Gleiche Teile erkannte die Druckvorschau bisher am Formschlüssel. Teile, die einzeln in Weltlage gebaut sind (die vier
Lenksperren und vier Stangenhalter des Kugelschiebers), haben aber je einen eigenen Formschlüssel, obwohl sie
deckungsgleich oder gespiegelt sind: 15 Gruppen für 15 Teile. Die Signatur beschreibt die Form in Druckausrichtung
(Druckkoordinaten, Auflage bei z = 0, Hüllrechteck achsparallel) mit Größen, die Lage und Drehung um Z nicht ändern:

- ``v``: Volumen (mm³), ``a``: Oberfläche (mm²), aus dem Netz;
- ``m``: Hauptträgheitsmomente als Eigenwerte der Kovarianz des Vollkörpers (mm², absteigend);
- ``g``: Hüllmaße in Druckausrichtung (lange Seite X, Höhe Z);
- ``h``: Flächenhistogramm der Normalen nach ihrer Z-Komponente (9 Klassen, Anteile der Oberfläche);
- ``k``: dritte und vierte Momente der Oberfläche im rechtshändigen Hauptachsensystem (25 Werte, normiert), ``e``: die
  Hauptmomente fallen fast zusammen (Achsen nicht fest). Daran unterscheidet ``vergleich`` deckungsgleich (passt mit
  einer Drehung) von gespiegelt (passt nur mit einer Spiegelung); symmetrische Formen passen beides und gelten als
  gleich.

``vergleich(a, b)`` sagt mit Toleranz (das Netz zweier deckungsgleicher Teile ist nicht Punkt für Punkt gleich), ob
zwei Formen gleich sind und ob die eine das Spiegelbild der anderen ist. Auch Punkt 7 („gedruckt“) nutzt sie.
"""

from __future__ import annotations

from typing import Any

import numpy as np

KLASSEN = 9
TOLERANZ = {"v": 0.01, "a": 0.015, "m": 0.02, "g_mm": 0.3, "g": 0.01, "h": 0.04, "k": 0.05}
ENTARTET = 0.02  # Hauptmomente, die so nah beieinander liegen, haben keine festen Achsen


def berechnen(P: np.ndarray, tri: np.ndarray, groesse: list[float] | None = None) -> dict[str, Any]:
    """Signatur aus dem Netz in Druckkoordinaten (``P`` (n, 3), ``tri`` (m, 3))."""
    return mit_deckung(P, tri, groesse)[0]


def mit_deckung(P: np.ndarray, tri: np.ndarray,
                groesse: list[float] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Signatur und, für den genauen Vergleich (``deckung``), Schwerpunkt, Hauptachsen und eine feste Stichprobe von
    Punkten der Oberfläche (nur im Rechenprozess, nicht im JSON)."""
    P = np.asarray(P, dtype=np.float64)
    tri = np.asarray(tri, dtype=np.int64)
    a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    kreuz = np.cross(b - a, c - a)
    dop = np.linalg.norm(kreuz, axis=1)
    flaeche = dop / 2
    A = float(flaeche.sum())
    # Vollkörper über Tetraeder vom Ursprung (Ursprung nahe der Mitte, Druckkoordinaten)
    o = P.mean(axis=0)
    a0, b0, c0 = a - o, b - o, c - o
    vol = np.einsum("ij,ij->i", a0, np.cross(b0, c0)) / 6.0
    V = float(vol.sum())
    umgedreht = V < 0  # Netz andersherum orientiert (Normalen nach innen)
    if umgedreht:
        vol, V = -vol, -V
    leer = {"v": 0.0, "a": round(A, 3), "m": [0.0, 0.0, 0.0], "g": [round(float(x), 3) for x in (groesse or [])],
            "h": [0.0] * KLASSEN, "k": [], "e": True}
    if V <= 1e-9:
        return leer, None
    s = a0 + b0 + c0
    mitte = (vol[:, None] * s).sum(axis=0) / (4 * V)
    M2 = np.zeros((3, 3))
    for v_ in (a0, b0, c0):
        M2 += np.einsum("i,ij,ik->jk", vol, v_, v_)
    M2 += np.einsum("i,ij,ik->jk", vol, s, s)
    M2 /= 20.0
    C = M2 / V - np.outer(mitte, mitte)
    C = (C + C.T) / 2
    lam, achsen = np.linalg.eigh(C)
    ordnung = np.argsort(lam)[::-1]
    lam, achsen = lam[ordnung], achsen[:, ordnung]
    if np.linalg.det(achsen) < 0:  # rechtshändiges Hauptachsensystem: Spiegelbilder unterscheiden sich dann im Vorzeichen
        achsen[:, 2] = -achsen[:, 2]
    # Flächenhistogramm nach der Z-Komponente der Normalen; Klassenmitten bei −1, −0,75 … 1 (senkrechte und waagrechte
    # Flächen liegen mitten in einer Klasse, nicht auf einer Grenze)
    ok = dop > 1e-12
    nz = np.zeros(len(tri))
    nz[ok] = kreuz[ok, 2] / dop[ok]
    if umgedreht:
        nz = -nz
    klasse = np.clip(np.rint((nz + 1) * (KLASSEN - 1) / 2).astype(int), 0, KLASSEN - 1)
    h = np.bincount(klasse, weights=flaeche, minlength=KLASSEN) / max(A, 1e-12)
    l0 = max(float(lam[0]), 1e-12)
    entartet = bool(lam[0] - lam[1] < ENTARTET * l0 or lam[1] - lam[2] < ENTARTET * l0)
    sig = {"v": round(V, 3), "a": round(A, 3), "m": [round(float(x), 4) for x in lam],
           "g": [round(float(x), 3) for x in (groesse or [])], "h": [round(float(x), 5) for x in h],
           "k": [round(float(x), 5) for x in _momente(a, b, c, flaeche, mitte + o, lam, achsen)], "e": entartet}
    extra = {"mitte": mitte + o, "achsen": achsen, "punkte": stichprobe(a, b, c, flaeche), "flaeche": A, "k": sig["k"]}
    return sig, extra


PUNKTE_DICHTE_MM2 = 0.5  # eine Stichprobe je so viel Fläche
PUNKTE_MIN, PUNKTE_MAX = 3000, 10000


def stichprobe(a: np.ndarray, b: np.ndarray, c: np.ndarray, flaeche: np.ndarray) -> np.ndarray:
    """Gleichmäßig über die Oberfläche verteilte Punkte, immer gleich gezogen (fester Startwert)."""
    A = float(flaeche.sum())
    n = int(np.clip(A / PUNKTE_DICHTE_MM2, PUNKTE_MIN, PUNKTE_MAX))
    rng = np.random.default_rng(0)
    idx = rng.choice(len(flaeche), size=n, p=flaeche / A) if A > 0 else np.zeros(0, dtype=int)
    u, v = rng.random(n), rng.random(n)
    aussen = u + v > 1
    u[aussen], v[aussen] = 1 - u[aussen], 1 - v[aussen]
    return a[idx] + u[:, None] * (b[idx] - a[idx]) + v[:, None] * (c[idx] - a[idx])


def _momente(a: np.ndarray, b: np.ndarray, c: np.ndarray, flaeche: np.ndarray, mitte: np.ndarray,
             lam: np.ndarray, achsen: np.ndarray) -> list[float]:
    """Dritte und vierte Momente der Oberfläche im rechtshändigen Hauptachsensystem, normiert mit der Wurzel des
    größten Hauptmoments. Ein Vorzeichenwechsel der Achsen ändert je Komponente nur das Vorzeichen; ``vergleich``
    probiert alle durch. Deckungsgleiche Teile passen mit einer Drehung (gerade Zahl von Wechseln), Spiegelbilder nur
    mit einer Spiegelung (ungerade Zahl)."""
    d = ((a + b + c) / 3 - mitte) @ achsen / float(np.sqrt(max(float(lam[0]), 1e-12)))
    w = flaeche / max(float(flaeche.sum()), 1e-12)
    out: list[float] = []
    for idx in _INDIZES:
        out.append(float((w * np.prod(d[:, list(idx)], axis=1)).sum()))
    return out


_INDIZES: list[tuple[int, ...]] = [(i, j, k) for i in range(3) for j in range(i, 3) for k in range(j, 3)] + \
    [(i, j, k, l_) for i in range(3) for j in range(i, 3) for k in range(j, 3) for l_ in range(k, 3)]
_WECHSEL = [np.array(s) for s in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1),
                                  (-1, 1, 1), (1, -1, 1), (1, 1, -1), (-1, -1, -1))]


def _abstand(ka: list[float], kb: list[float], gespiegelt: bool) -> float:
    """Kleinster relativer Abstand der Momente über die Vorzeichenwechsel (Drehung bzw. Spiegelung)."""
    va, vb = np.asarray(ka, dtype=np.float64), np.asarray(kb, dtype=np.float64)
    norm = max(float(np.linalg.norm(va)), float(np.linalg.norm(vb)), 1e-9)
    beste = float("inf")
    for s in _WECHSEL[4:] if gespiegelt else _WECHSEL[:4]:
        faktor = np.array([float(np.prod(s[list(idx)])) for idx in _INDIZES])
        beste = min(beste, float(np.linalg.norm(va * faktor - vb)) / norm)
    return beste


def _nah(x: float, y: float, rel: float, absolut: float = 0.0) -> bool:
    return abs(x - y) <= max(rel * max(abs(x), abs(y)), absolut)


def vergleich(s: dict[str, Any] | None, t: dict[str, Any] | None) -> tuple[bool, bool]:
    """(gleich, gespiegelt): gleiche Form im Rahmen der Toleranz; gespiegelt, wenn die eine nur als Spiegelbild der
    anderen passt (symmetrische Formen passen auch gedreht und gelten als gleich)."""
    if not s or not t:
        return False, False
    tol = TOLERANZ
    if not _nah(float(s["v"]), float(t["v"]), tol["v"]) or not _nah(float(s["a"]), float(t["a"]), tol["a"]):
        return False, False
    ms, mt = s.get("m") or [], t.get("m") or []
    if len(ms) != 3 or len(mt) != 3:
        return False, False
    boden = 0.05 * max(float(ms[0]), float(mt[0]))
    if any(not _nah(float(x), float(y), tol["m"], tol["m"] * boden) for x, y in zip(ms, mt)):
        return False, False
    gs, gt = s.get("g") or [], t.get("g") or []
    if len(gs) == len(gt) == 3 and any(not _nah(float(x), float(y), tol["g"], tol["g_mm"]) for x, y in zip(gs, gt)):
        return False, False
    hs, ht = s.get("h") or [], t.get("h") or []
    if len(hs) == len(ht) and sum(abs(float(x) - float(y)) for x, y in zip(hs, ht)) > tol["h"]:
        return False, False
    ks, kt = s.get("k") or [], t.get("k") or []
    if s.get("e") or t.get("e") or len(ks) != len(_INDIZES) or len(kt) != len(_INDIZES):
        return True, False  # Achsen nicht fest (drehsymmetrisch) oder ältere Signatur: gleich
    if _abstand(ks, kt, False) <= TOLERANZ["k"]:
        return True, False
    if _abstand(ks, kt, True) <= TOLERANZ["k"]:
        return True, True
    return False, False


def gleich_skalar(s: dict[str, Any] | None, t: dict[str, Any] | None) -> bool:
    """Volumen, Oberfläche, Hauptmomente, Hüllmaße und Flächenhistogramm stimmen (ohne Händigkeit)."""
    if not s or not t:
        return False
    return vergleich({**s, "k": []}, {**t, "k": []})[0]


ABWEICHUNG_ANTEIL = 0.004  # so viele Punkte dürfen weiter als die Grenze vom anderen Teil liegen


def deckung(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """Genauer Vergleich zweier Formen mit gleicher Signatur über ihre Punkte: im Hauptachsensystem aufeinander gelegt,
    je Vorzeichenwechsel der Achsen (vier Drehungen, vier Spiegelungen) der Anteil der Punkte, die weiter als die
    Grenze von der anderen Form liegen (in beide Richtungen). „gleich“, wenn eine Drehung passt; „gespiegelt“, wenn nur
    eine Spiegelung passt; sonst None."""
    from scipy.spatial import cKDTree

    xa = (a["punkte"] - a["mitte"]) @ a["achsen"]
    xb = (b["punkte"] - b["mitte"]) @ b["achsen"]
    if len(xa) == 0 or len(xb) == 0:
        return None
    # Grenze: deutlich über dem mittleren Abstand der Stichprobe (bei 20.000 Punkten auf großen Teilen größer)
    dichte = max(PUNKTE_DICHTE_MM2, a.get("flaeche", 0.0) / max(len(xa), 1), b.get("flaeche", 0.0) / max(len(xb), 1))
    abstand = max(2.5 * float(np.sqrt(dichte)), 1.0)
    baum_b = cKDTree(xb)

    def passt(sv: np.ndarray) -> float:
        ya = xa * sv
        d1, _ = baum_b.query(ya, distance_upper_bound=abstand)
        hin = float(np.mean(~np.isfinite(d1)))
        if hin > ABWEICHUNG_ANTEIL:
            return hin
        d2, _ = cKDTree(ya).query(xb, distance_upper_bound=abstand)
        return max(hin, float(np.mean(~np.isfinite(d2))))

    # Wechsel nach dem Abstand der Momente geordnet: meist passt schon der erste
    ka, kb = a.get("k"), b.get("k")

    def reihenfolge(wechsel: list[np.ndarray]) -> list[np.ndarray]:
        if not ka or not kb or len(ka) != len(_INDIZES) or len(kb) != len(_INDIZES):
            return wechsel
        return sorted(wechsel, key=lambda sv: _abstand_wechsel(ka, kb, sv))

    if any(passt(sv) <= ABWEICHUNG_ANTEIL for sv in reihenfolge(_WECHSEL[:4])):
        return "gleich"
    if any(passt(sv) <= ABWEICHUNG_ANTEIL for sv in reihenfolge(_WECHSEL[4:])):
        return "gespiegelt"
    return None


def _abstand_wechsel(ka: list[float], kb: list[float], sv: np.ndarray) -> float:
    faktor = np.array([float(np.prod(sv[list(idx)])) for idx in _INDIZES])
    return float(np.linalg.norm(np.asarray(ka) * faktor - np.asarray(kb)))


def unterschiede(alt: dict[str, Any], neu: dict[str, Any]) -> list[str]:
    """Was sich zwischen zwei Signaturen geändert hat, als kurze Texte („Volumen +3 %“, „Höhe 18 → 20 mm“)."""
    out: list[str] = []

    def prozent(x: float, y: float) -> str:
        p = (y - x) / x * 100 if x else 0.0
        return f"{'+' if p >= 0 else '−'}{abs(p):.1f} %".replace(".", ",")

    def mm(x: float) -> str:
        return f"{x:.1f}".replace(".", ",").replace(",0", "")

    if not _nah(float(alt.get("v") or 0), float(neu.get("v") or 0), TOLERANZ["v"]):
        out.append(f"Volumen {prozent(float(alt['v']), float(neu['v']))}")
    ga, gn = alt.get("g") or [], neu.get("g") or []
    for i, wort in enumerate(("Länge", "Breite", "Höhe")):
        if i < len(ga) and i < len(gn) and not _nah(float(ga[i]), float(gn[i]), TOLERANZ["g"], TOLERANZ["g_mm"]):
            out.append(f"{wort} {mm(float(ga[i]))} → {mm(float(gn[i]))} mm")
    if not out and not _nah(float(alt.get("a") or 0), float(neu.get("a") or 0), TOLERANZ["a"]):
        out.append(f"Oberfläche {prozent(float(alt['a']), float(neu['a']))}")
    if not out:
        gleich, gesp = vergleich(alt, neu)
        out.append("gespiegelt" if gleich and gesp else "Form innen geändert (Bohrungen, Taschen, Verteilung)")
    return out

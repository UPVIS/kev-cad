"""Drehfedern an festen Anschlüssen von Stäben an Druckteile (PLAN-STATIK.md T35).

Ein Rohr in einem gedruckten Halter ist nicht starr eingespannt: Der Halter gibt nach. Starr gerechnet (T30, T11)
nimmt ein Halter das ganze Kragmoment einer auskragenden Stange, obwohl er viel weicher ist als das Rohr; real teilt
sich das Moment nach Steifigkeit zwischen Halter und dem weiterlaufenden Rohr. Deshalb bekommt jeder feste Anschluss
(Klemmung, Steck, Spiel, festgestelltes Gelenk, Schraube) eines Stabs an ein Druckteil im Stabwerk eine Drehfeder für
die beiden Drehungen quer zum Stab; Verschiebungen und die Drehung um die Stabachse bleiben starr (die Klemmung hält
sie über Reibung).

Steifigkeit aus Geometrie und E-Modul des Druckteils, zwei Nachgiebigkeiten in Reihe:

1. **Bettung in der Bohrung:** Das Rohr kippt in der Bohrung der Länge L_b und drückt die Wand an beiden Enden ein.
   Mit einer Bettung k_w = E / d (Wand etwa so dick wie das Rohr, angenommen) wird p(z) = k_w · θ · z über die Länge,
   das Moment M = k_w · d · θ · L_b³ / 12, also k_Bohrung = E · L_b³ / 12 (unabhängig vom Durchmesser).
2. **Biegung und Torsion des Teils** von der Bohrung bis zu seinem Lager (Mitte der Berührung mit den Teilen, die es
   tragen, wie beim Kragträger in ``bauteil.py``): an denselben Schnitten durch das echte Teil die Flächenmomente; je
   Abschnitt Δs eine Nachgiebigkeit Δs / (E · I) für Biegung und Δs / (G · I_t) für Torsion mit
   I_t ≈ A⁴ / (40 · I_p) (Saint-Venant für gedrungene Querschnitte). Quer zur Schicht gedruckt zählt ``e_modul_z``.
   Hängt das Teil zwischen mehreren Stäben (Verbinder, Schlitten), bekommt jeder Anschluss den Anteil 1 / n, damit
   die Federn in Reihe die Nachgiebigkeit des Teils zwischen den Bohrungen ergeben.

Im Stabwerk sitzt die Feder als zwei kurze Glieder (``stabwerk.FEDER_L``) längs der beiden Hauptachsen quer zum
Stab, starr bis auf die Torsion (G · J / L = k). Die Lagerkraft samt Moment, die durch die Feder geht, bekommen
Kragträger und Festkörper des Halters (``rechnen._lagerteile``, T26): das Moment passt damit zur Steifigkeit.

Linear, ohne Spiel: Eine Bohrung mit Spiel lässt das Rohr erst um Spiel / L_b kippen, bevor der Halter trägt; das
rechnet die Statik nicht (ehrliche Grenze, PLAN-STATIK.md).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.statik.modell import Anschluss, StatikModell

BOHRUNG_RAND = 2.5  # mm über den Stabradius hinaus: Netzpunkte des Halters, die zur Bohrung gehören
K_MAX = 1e12  # Nmm/rad, steifer zählt als starr


def _plane(e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    u = np.cross(e, [0, 0, 1.0]) if abs(e[2]) < 0.9 else np.cross(e, [1.0, 0, 0])
    u /= np.linalg.norm(u)
    return u, np.cross(e, u)


def bohrungslaenge(k: Any, stab: Any, radius: float) -> float:
    """Länge der Berührung des Teils ``k`` (Körper der Prüfung) mit dem Stab längs der Stabachse: Ausdehnung der
    Netzpunkte, die höchstens ``radius`` + ``BOHRUNG_RAND`` von der Achse liegen, soweit der Stab dort ist (endet er in
    der Bohrung, zählt nur das Stück bis zu seinem Ende); ohne solche Punkte 0."""
    P = np.asarray(k.pos, dtype=float).reshape(-1, 3)
    if not len(P):
        return 0.0
    a = stab.achse
    d = P - stab.p0
    t = d @ a
    q = np.linalg.norm(d - np.outer(t, a), axis=1)
    nah = q <= radius + BOHRUNG_RAND
    if int(nah.sum()) < 2:
        return 0.0
    tt = np.clip(t[nah], 0.0, stab.laenge)
    return float(np.ptp(tt))


def nachgiebigkeit_teil(k: Any, R: np.ndarray, P: np.ndarray, E: float, G: float) -> tuple[np.ndarray, int]:
    """Nachgiebigkeit (3 × 3, rad/(N·mm)) des Teils für ein Moment am Punkt ``P`` gegen sein Lager in ``R``: Summe über
    die Schnitte (``bauteil.schnitte``) aus Biegung und Torsion. Liefert (Matrix, Zahl der Schnitte)."""
    from kevcad_kernel.statik.bauteil import schnitte

    r = P - R
    L = float(np.linalg.norm(r))
    C = np.zeros((3, 3))
    if L < 2.0:
        return C, 0
    e = r / L
    u, v = _plane(e)
    ss = sorted(schnitte(k, R, P), key=lambda s: s["s"])
    ss = [s for s in ss if s["A"] > 1e-6]
    if not ss:
        return C, 0
    f = [s["s"] for s in ss]
    grenzen = [0.0] + [(a + b) / 2 for a, b in zip(f[:-1], f[1:])] + [L]
    Q = np.stack([u, v], axis=1)  # 3 × 2
    for s, lo, hi in zip(ss, grenzen[:-1], grenzen[1:]):
        ds = max(hi - lo, 0.0)
        J = np.asarray(s["J"], dtype=float)
        B = Q.T @ J @ Q  # Flächenmomente um die Achsen in der Schnittebene (wie der Trägheitstensor)
        try:
            Binv = np.linalg.inv(B)
        except np.linalg.LinAlgError:
            continue
        Ip = float(e @ J @ e)
        It = (s["A"] ** 4) / (40.0 * max(Ip, 1e-9))
        C += ds * (Q @ Binv @ Q.T / E + np.outer(e, e) / (G * max(It, 1e-9)))
    return C, len(ss)


def drehfeder(m: StatikModell, koerper: dict[str, Any], a: Anschluss) -> dict[str, Any] | None:
    """Drehfeder eines festen Anschlusses an ein Druckteil (oder None): ``achsen`` (zwei Einheitsvektoren quer zum Stab),
    ``k`` (Nmm/rad je Achse), Bohrungslänge, Hebel bis zum Lager und die Teile der Rechnung."""
    if a.art != "fest" or a.partner[0] == "boden":
        return None
    name = a.teile[1]
    t = m.teile.get(name)
    k = koerper.get(name)
    s = m.staebe.get(a.stab)
    if t is None or k is None or s is None or not t.druckteil or name in m.staebe:
        return None
    w = t.werkstoff
    if w is None or not w.E:
        return None
    from kevcad_kernel.statik.bauteil import tragende_nachbarn

    E = float(w.E)
    nu = float(w.nu if w.nu is not None else 0.35)
    P = s.punkt(a.t)
    ax = s.achse
    radius = float(s.q.radius)
    Lb = bohrungslaenge(k, s, radius)
    C = np.zeros((3, 3))
    teile_text = []
    if Lb > 0.5:
        C += (12.0 / (E * Lb ** 3)) * (np.eye(3) - np.outer(ax, ax))
        teile_text.append(f"Bettung in der Bohrung (Länge {Lb:.0f} mm)")
    # Biegung des Teils bis zu seinem Lager; bei Verbindern zwischen Stäben anteilig je Anschluss
    staebe = sorted({x.stab for x in m.anschluesse if x.teile[1] == name})
    R, nachbarn = tragende_nachbarn(m, name, koerper, ohne={a.stab})
    hebel = None
    if R is not None:
        r = P - R
        hebel = float(np.linalg.norm(r))
        E_b = E
        if t.druck_oben is not None and hebel > 1e-6 and w.E_z and abs(float(np.dot(r / hebel, t.druck_oben))) > 0.7:
            E_b = float(w.E_z)  # Biegespannung quer zu den Schichten
        Ct, n = nachgiebigkeit_teil(k, R, P, E_b, E_b / (2 * (1 + nu)))
        if n:
            anteil = 1.0
            kid = m.teil_koerper.get(name)
            if kid is not None and not m.koerper[kid].geerdet and len(staebe) > 1:
                anteil = 1.0 / len(staebe)
            C += anteil * Ct
            teile_text.append(f"Biegung des Teils bis zum Lager ({hebel:.0f} mm{', anteilig' if anteil < 1 else ''})")
    # quer zum Stab: Hauptachsen der Nachgiebigkeit
    u, v = _plane(ax)
    Q = np.stack([u, v], axis=1)
    Cq = Q.T @ C @ Q
    if not np.all(np.isfinite(Cq)) or float(np.trace(Cq)) <= 0:
        return None
    lam, W = np.linalg.eigh(Cq)
    achsen, ks = [], []
    for i in range(2):
        k_i = 1.0 / lam[i] if lam[i] > 1.0 / K_MAX else K_MAX
        achsen.append([round(float(c), 9) for c in Q @ W[:, i]])
        ks.append(float(min(k_i, K_MAX)))
    return {"achsen": achsen, "k": [round(x, 1) for x in ks], "bohrung_mm": round(Lb, 1),
            "hebel_mm": None if hebel is None else round(hebel, 1), "lager": nachbarn, "teil": name,
            "werkstoff": w.id, "quelle": " + ".join(teile_text) or "nur Bettung"}


def setze(m: StatikModell, koerper: dict[str, Any] | None) -> int:
    """Drehfedern an alle passenden Anschlüsse des Modells (einmal je Lauf, vor dem Stabwerk). Liefert ihre Zahl."""
    if not koerper:
        return 0
    n = 0
    for a in m.anschluesse:
        if a.feder is None:  # {} = schon gerechnet, keine Feder (starr); bleibt bis zum nächsten Lauf
            try:
                a.feder = drehfeder(m, koerper, a) or {}
            except Exception as exc:  # noqa: BLE001 - dann eben starr
                a.feder = {}
                m.hinweise.append(f"{a.teile[1]}: Drehfeder nicht berechnet ({type(exc).__name__}), starr gerechnet")
        if a.feder:
            n += 1
    text = (f"{n} {'Anschluss' if n == 1 else 'Anschlüsse'} an Druckteilen mit Drehfeder aus Geometrie und E-Modul "
            "(Bettung in der Bohrung, Biegung des Teils; ohne Spiel, T35)")
    if n and text not in m.hinweise:
        m.hinweise.append(text)
    return n


def federmoment(feder: dict[str, Any], drehung: np.ndarray) -> float:
    """Betrag des Moments (Nmm), das die Feder bei der Drehung ``drehung`` (rad, Welt) überträgt."""
    M = [k * float(np.dot(np.asarray(u, float), drehung)) for u, k in zip(feder["achsen"], feder["k"])]
    return math.hypot(*M)

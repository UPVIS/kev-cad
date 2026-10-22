"""Stufe S1: Stabwerk mit PyNite (T-B).

Aus dem Statikmodell entsteht ein räumliches Stabwerk:

- je Stab Knoten an den Enden, an jedem Anschluss und an Lastpunkten, dazwischen geteilt (mindestens acht Glieder je
  Stab, für Knicken und Darstellung); Querschnitt aus dem Katalog, Hauptachsen nach der Lage des Profils;
- jeder Starrkörper (nicht geerdet, mindestens zwei Anschlüsse) als Knoten in seinem Schwerpunkt, mit starren Gliedern
  zu seinen Anschlüssen;
- ein Gelenk sitzt in einem kurzen Gelenkglied (10 mm, quer zum Stab, lokale z-Achse längs des Stabs) mit Freigaben:
  gelenkig = beide Biegedrehungen frei (die Verdrehung um die Stabachse bleibt gekoppelt, sonst wäre der Stab drehbar),
  Drehgelenk = Drehung um die nächste der drei Achsen frei, Schiebegelenk = Verschiebung längs der Achse frei;
- Anschlüsse an geerdete Starrkörper und den Boden sind feste Lager (hinter dem Gelenkglied).

Lastfälle: je Szenario Eigengewicht der Stäbe als Streckenlast im Beschleunigungsfeld, Starrkörper und Anbauteile mit
ihrer Masse, Einzellasten (Stoßfaktor eingerechnet). Ergebnis je Szenario: Verschiebung und Ausnutzung an jedem
Stabknoten, Sicherheit je Stab (von Mises, Holz mit Interaktion), Durchbiegung, Auflagerkräfte, Knicken als
Lastfaktor aus dem linearen Eigenwertproblem (K + λ·Kg) φ = 0. Linear-elastisch, kleine Verformungen (T7).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kevcad_kernel.statik.modell import Anschluss, Stab, StatikModell
from kevcad_kernel.statik.szenario import Szenario
from kevcad_kernel.statik.werkstoff import Querschnitt, Werkstoff

GLIEDER_MIN = 8  # Glieder je Stab mindestens
GELENK_L = 10.0  # mm, Länge des Gelenkglieds
STARR = 1e3  # Starre Glieder: so viel steifer als das steifste Stabglied gleicher Länge (je Glied nach Länge bemessen,
# sonst wird das Gleichungssystem schlecht konditioniert und der Löser hält das Stabwerk für beweglich)
L_BEZUG_MIN = 20.0  # mm, kürzeste Bezugslänge der Stabglieder
E_STARR = 210000.0


@dataclass
class StabErgebnis:
    name: str
    t: list[float]  # Stationen entlang des Stabs
    punkte: list[list[float]]
    verschiebung: list[list[float]]
    ausnutzung: list[float]  # Spannung / Grenze je Station (1 = versagt)
    sicherheit: float  # kleinste Sicherheit gegen die Festigkeit
    spannung_max: float  # MPa (Vergleichsspannung)
    ort_t: float  # Station der größten Ausnutzung
    durchbiegung: float  # mm, quer zur Achse gegenüber der Ruhelage
    grenze_durchbiegung: float
    knicken: float | None = None  # Lastfaktor des maßgebenden Knickfalls, wenn dieser Stab dabei am stärksten ausweicht
    normalkraft_min: float = 0.0  # N, größte Druckkraft (negativ)


@dataclass
class S1Ergebnis:
    szenario: str
    ok: bool
    staebe: dict[str, StabErgebnis] = field(default_factory=dict)
    knicken: float | None = None  # kleinster Lastfaktor (alle Stäbe)
    knick_stab: str | None = None
    auflager: list[dict[str, Any]] = field(default_factory=list)
    koerper_kraefte: dict[str, list[float]] = field(default_factory=dict)  # Starrkörper: Summe der Gliedkräfte
    meldung: str = ""
    ms: float = 0.0


# ---------------------------------------------------------------------------------------------------------------------
# Achsen wie PyNite (Member3D.T ohne Drehung), damit sich die Profillage über ``rotation`` einstellen lässt


def pynite_achsen(pi: np.ndarray, pj: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    d = pj - pi
    L = float(np.linalg.norm(d))
    x = d / L
    if math.isclose(pi[0], pj[0], abs_tol=1e-9) and math.isclose(pi[2], pj[2], abs_tol=1e-9):
        y = np.array([-1.0, 0, 0]) if pj[1] > pi[1] else np.array([1.0, 0, 0])
        z = np.array([0.0, 0, 1])
    elif math.isclose(pi[1], pj[1], abs_tol=1e-9):
        y = np.array([0.0, 1, 0])
        z = np.cross(x, y)
        z /= np.linalg.norm(z)
    else:
        proj = np.array([d[0], 0.0, d[2]])
        z = np.cross(proj, x) if pj[1] > pi[1] else np.cross(x, proj)
        z /= np.linalg.norm(z)
        y = np.cross(z, x)
        y /= np.linalg.norm(y)
    return x, y, z


def drehung_fuer(pi: np.ndarray, pj: np.ndarray, y_soll: np.ndarray | None = None,
                 z_soll: np.ndarray | None = None) -> float:
    """Winkel (Grad) für PyNites ``rotation``, damit die lokale y-Achse (oder z-Achse) in Richtung ``*_soll`` zeigt."""
    _, y, z = pynite_achsen(pi, pj)
    if y_soll is not None:
        return math.degrees(math.atan2(float(np.dot(y_soll, z)), float(np.dot(y_soll, y))))
    if z_soll is not None:
        return math.degrees(math.atan2(-float(np.dot(z_soll, y)), float(np.dot(z_soll, z))))
    return 0.0


# ---------------------------------------------------------------------------------------------------------------------
# Aufbau


class _Aufbau:
    """Baut das PyNite-Modell und merkt sich, welcher Knoten wohin gehört."""

    def __init__(self, m: StatikModell, ersatz: dict[str, tuple[Querschnitt, Werkstoff]] | None = None) -> None:
        from Pynite import FEModel3D

        self.m = m
        self.fe = FEModel3D()
        self.ersatz = ersatz or {}
        self.stationen: dict[str, list[tuple[float, str]]] = {}
        self.glieder: dict[str, list[tuple[str, float, float]]] = {}  # Stab → (Glied, t_i, t_j)
        self.knoten_pos: dict[str, np.ndarray] = {}
        self.k_knoten: dict[str, str] = {}  # Starrkörper → Knoten
        self.starr_glieder: dict[str, list[str]] = {}  # Starrkörper → seine Glieder (Kraftfluss)
        self.lager: list[tuple[str, Anschluss]] = []  # (Knoten, Anschluss)
        self.summe: dict[str, np.ndarray] = {}  # Szenario → Summe aller aufgebrachten Kräfte (Gleichgewichtsprobe)
        self.anbau: dict[str, Anschluss] = {}
        self._n = 0
        self.vereinfacht: list[str] = []

    def q_w(self, s: Stab) -> tuple[Querschnitt, Werkstoff]:
        return self.ersatz.get(s.name) or (s.q, s.werkstoff)

    def knoten(self, p: np.ndarray, praefix: str = "N") -> str:
        self._n += 1
        name = f"{praefix}{self._n}"
        self.fe.add_node(name, float(p[0]), float(p[1]), float(p[2]))
        self.knoten_pos[name] = np.asarray(p, dtype=float)
        return name

    def baue(self, szenarien: list[Szenario]) -> None:
        m, fe = self.m, self.fe
        staebe = list(m.staebe.values())
        # Starre Glieder: Bezug sind die Steifigkeiten (je Länge) des steifsten Stabs
        self.ea = max(float(self.q_w(s)[1].E) * self.q_w(s)[0].A for s in staebe)
        self.ei = max(float(self.q_w(s)[1].E) * max(self.q_w(s)[0].I_lang, self.q_w(s)[0].I_quer) for s in staebe)
        self.gj = max(float(self.q_w(s)[1].schub) * self.q_w(s)[0].J for s in staebe)
        fe.add_material("Starr", E_STARR, E_STARR / 2.6, 0.3, 0.0)
        self._starr_q: dict[float, str] = {}
        # Lastpunkte auf Stäben
        lastpunkte: dict[str, list[float]] = {}
        for sz in szenarien:
            for last in sz.lasten:
                for teil in last.teile:
                    for n in m.aufloesen(teil):
                        s = m.staebe.get(n)
                        if s is not None:
                            lastpunkte.setdefault(n, []).append(
                                s.t_von(last.punkt) if last.punkt is not None else s.laenge / 2)
        for s in staebe:
            q, w = self.q_w(s)
            fe.add_material(f"W:{s.name}", float(w.E), float(w.schub), float(w.nu if w.nu is not None else 0.3), 0.0)
            # PyNite: Iy um die lokale y-Achse (= lang), Iz um z; Biegung um z ändert die Spannung entlang y
            fe.add_section(f"Q:{s.name}", q.A, q.I_quer, q.I_lang, q.J)
            ts = {0.0, s.laenge}
            ts.update(a.t for a in m.anschluesse if a.stab == s.name)
            ts.update(a.partner[2] for a in m.anschluesse if a.partner[0] == "stab" and a.partner[1] == s.name)
            ts.update(lastpunkte.get(s.name, []))
            for k in range(1, GLIEDER_MIN):
                ts.add(s.laenge * k / GLIEDER_MIN)
            liste = sorted(ts)
            rein: list[float] = []
            for t in liste:
                if not rein or t - rein[-1] > 1.0:
                    rein.append(t)
                elif t == s.laenge:
                    rein[-1] = t
            st = [(t, self.knoten(s.punkt(t), "S")) for t in rein]
            self.stationen[s.name] = st
            e_lang = s.e_lang
            gl = []
            for (ti, ni), (tj, nj) in zip(st[:-1], st[1:]):
                pi, pj = self.knoten_pos[ni], self.knoten_pos[nj]
                rot = 0.0 if q.isotrop else drehung_fuer(pi, pj, y_soll=e_lang)
                gname = f"G:{s.name}:{len(gl)}"
                fe.add_member(gname, ni, nj, f"W:{s.name}", f"Q:{s.name}", rotation=rot)
                gl.append((gname, ti, tj))
            self.glieder[s.name] = gl
        # Starrkörper mit mindestens zwei Anschlüssen
        for kid, k in m.koerper.items():
            if k.geerdet:
                continue
            ans = m.anschluesse_von(kid)
            if len(ans) == 1:
                self.anbau[kid] = ans[0]
            elif len(ans) >= 2:
                p = np.array(k.schwerpunkt, dtype=float)
                if min(float(np.linalg.norm(p - self.knoten_pos[self.station(a.stab, a.t)])) for a in ans) < 1.0:
                    p = p + np.array([0.0, 0.0, 1.0])
                self.k_knoten[kid] = self.knoten(p, "K")
        # Anschlüsse
        for a in m.anschluesse:
            self._anschluss(a)

    def starr_querschnitt(self, L: float) -> str:
        """Querschnitt eines starren Glieds der Länge L: STARR-mal so steif wie das steifste Stabglied der Länge
        max(L, L_BEZUG_MIN) (axial, Biegung, Torsion)."""
        L = max(round(float(L), 1), 0.1)
        name = self._starr_q.get(L)
        if name is None:
            Lb = max(L, L_BEZUG_MIN)
            A = STARR * self.ea / Lb * L / E_STARR
            I = STARR * self.ei / Lb ** 3 * L ** 3 / E_STARR
            J = STARR * self.gj / Lb * L / (E_STARR / 2.6)
            name = f"Starr:{L:g}"
            self.fe.add_section(name, A, I, I, J)
            self._starr_q[L] = name
        return name

    def station(self, stab: str, t: float) -> str:
        return min(self.stationen[stab], key=lambda x: abs(x[0] - t))[1]

    def _starr(self, a: str, b: str, wer: str | None = None) -> str | None:
        if float(np.linalg.norm(self.knoten_pos[a] - self.knoten_pos[b])) < 1e-6:
            return None
        self._n += 1
        g = f"R{self._n}"
        L = float(np.linalg.norm(self.knoten_pos[a] - self.knoten_pos[b]))
        self.fe.add_member(g, a, b, "Starr", self.starr_querschnitt(L))
        if wer:
            self.starr_glieder.setdefault(wer, []).append(g)
        return g

    def _anschluss(self, a: Anschluss) -> None:
        m, fe = self.m, self.fe
        s = m.staebe[a.stab]
        n = self.station(a.stab, a.t)
        partner = a.partner
        kid = partner[1] if partner[0] == "koerper" else None
        if kid is not None and kid in self.anbau:
            return  # Anbauteil: nur Last
        if kid is not None and kid not in self.k_knoten and not m.koerper[kid].geerdet:
            return
        geerdet = partner[0] == "boden" or (kid is not None and m.koerper[kid].geerdet)
        # Gelenkglied quer zum Stab, lokale z längs des Stabs
        ziel = None
        if partner[0] == "stab":
            ziel = self.station(partner[1], partner[2])
        elif kid is not None and not geerdet:
            ziel = self.k_knoten[kid]
        frei = self._freigaben(a, s)
        knoten = n
        if any(frei.values()):
            richtung = (self.knoten_pos[ziel] - self.knoten_pos[n]) if ziel is not None else np.array([0, 0, -1.0])
            quer = richtung - s.achse * float(np.dot(richtung, s.achse))
            if float(np.linalg.norm(quer)) < 1e-6:
                quer = np.cross(s.achse, [0, 0, 1.0]) if abs(s.achse[2]) < 0.9 else np.cross(s.achse, [1.0, 0, 0])
            quer = quer / float(np.linalg.norm(quer))
            g_knoten = self.knoten(self.knoten_pos[n] + quer * GELENK_L, "J")
            self._n += 1
            g = f"J{self._n}"
            pi, pj = self.knoten_pos[n], self.knoten_pos[g_knoten]
            fe.add_member(g, n, g_knoten, "Starr", self.starr_querschnitt(GELENK_L),
                          rotation=drehung_fuer(pi, pj, z_soll=s.achse))
            fe.def_releases(g, Dxi=frei.get("Dx", False), Dyi=frei.get("Dy", False), Dzi=frei.get("Dz", False),
                            Rxi=frei.get("Rx", False), Ryi=frei.get("Ry", False), Rzi=frei.get("Rz", False))
            if kid is not None:
                self.starr_glieder.setdefault(kid, []).append(g)
            knoten = g_knoten
        if geerdet:
            fe.def_support(knoten, True, True, True, True, True, True)
            self.lager.append((knoten, a))
        elif ziel is not None:
            self._starr(knoten, ziel, kid)

    def _freigaben(self, a: Anschluss, s: Stab) -> dict[str, bool]:
        """Freigaben am Gelenkglied (lokal: x quer, z längs des Stabs, y quer)."""
        if a.art == "fest":
            return {}
        if a.art == "gelenkig":
            return {"Rx": True, "Ry": True}
        achse = a.achse if a.achse is not None else s.achse
        achse = np.asarray(achse, dtype=float) / max(float(np.linalg.norm(achse)), 1e-12)
        laengs = abs(float(np.dot(achse, s.achse)))
        if a.art in ("dreh", "zylinder"):
            out = {"Rz": True} if laengs > 0.7 else {"Rx": True, "Ry": True}
            if laengs <= 0.7:
                self.vereinfacht.append(f"{a.teile[1]}: Drehgelenk quer zum Stab als gelenkig gerechnet")
            if a.art == "zylinder" and laengs > 0.7:
                out["Dz"] = True
            return out
        if a.art == "schiebe":
            if laengs > 0.7:
                return {"Dz": True}
            self.vereinfacht.append(f"{a.teile[1]}: Schiebegelenk quer zum Stab als fest gerechnet")
            return {}
        return {}

    # -- Lasten --------------------------------------------------------------------------------------------------------

    def lasten(self, sz: Szenario) -> None:
        m, fe = self.m, self.fe
        f = sz.feld
        case = sz.name
        richt = ("FX", "FY", "FZ")
        for s in m.staebe.values():
            q, w = self.q_w(s)
            masse = s.masse_kg if s.name not in self.ersatz else q.A * float(w.dichte or 0) * 1e-6 * s.laenge
            w_je = masse / s.laenge * f  # N/mm
            self.summe[case] = self.summe.get(case, np.zeros(3)) + w_je * s.laenge
            for g, _, _ in self.glieder[s.name]:
                for i in range(3):
                    if abs(w_je[i]) > 1e-12:
                        fe.add_member_dist_load(g, richt[i], float(w_je[i]), float(w_je[i]), case=case)
        # Starrkörper und Anbauteile: Gewicht, Trägheit und Lasten
        kraefte: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        for kid, k in m.koerper.items():
            if k.geerdet:
                continue
            kraefte.setdefault(kid, []).append((k.masse_kg * f, np.asarray(k.schwerpunkt, dtype=float)))
        for last in sz.kraefte():
            teile = [n for t in last.teile for n in m.aufloesen(t)]
            if not teile:
                continue
            anteil = last.kraft / len(teile)
            for n in teile:
                s = m.staebe.get(n)
                if s is not None:
                    t = s.t_von(last.punkt) if last.punkt is not None else s.laenge / 2
                    kn = self.station(n, t)
                    self._knotenlast(kn, anteil, last.punkt, case)
                    continue
                kid = m.teil_koerper.get(n)
                if kid is None or m.koerper[kid].geerdet:
                    continue
                p = last.punkt if last.punkt is not None else m.teile[n].schwerpunkt
                kraefte.setdefault(kid, []).append((anteil, np.asarray(p, dtype=float)))
        for kid, liste in kraefte.items():
            if kid in self.k_knoten:
                for F, p in liste:
                    self._knotenlast(self.k_knoten[kid], F, p, case)
            elif kid in self.anbau:
                a = self.anbau[kid]
                kn = self.station(a.stab, a.t)
                for F, p in liste:
                    self._knotenlast(kn, F, p if a.art == "fest" else None, case)

    def _knotenlast(self, knoten: str, F: np.ndarray, p: np.ndarray | None, case: str) -> None:
        self.summe[case] = self.summe.get(case, np.zeros(3)) + np.asarray(F, dtype=float)
        richt = ("FX", "FY", "FZ")
        mom = ("MX", "MY", "MZ")
        for i in range(3):
            if abs(F[i]) > 1e-12:
                self.fe.add_node_load(knoten, richt[i], float(F[i]), case=case)
        if p is not None:
            M = np.cross(np.asarray(p, dtype=float) - self.knoten_pos[knoten], F)
            for i in range(3):
                if abs(M[i]) > 1e-9:
                    self.fe.add_node_load(knoten, mom[i], float(M[i]), case=case)


# ---------------------------------------------------------------------------------------------------------------------
# Rechnen


def rechne(m: StatikModell, szenarien: list[Szenario], knicken: bool = True,
           ersatz: dict[str, tuple[Querschnitt, Werkstoff]] | None = None) -> dict[str, S1Ergebnis]:
    """Alle Szenarien in einem Modell (ein Gleichungssystem, je Szenario ein Lastfall)."""
    t0 = time.perf_counter()
    out: dict[str, S1Ergebnis] = {}
    if not m.staebe or not szenarien:
        return out
    b = _Aufbau(m, ersatz)
    try:
        b.baue(szenarien)
        if not b.lager:
            for sz in szenarien:
                out[sz.name] = S1Ergebnis(sz.name, False, meldung="Stabwerk ohne Lager: kein Stab hängt an einem Teil, "
                                                                  "das auf dem Boden steht")
            return out
        for sz in szenarien:
            b.lasten(sz)
            b.fe.add_load_combo(sz.name, {sz.name: 1.0})
        # Dichter Löser bis 2400 Freiheitsgrade (robust bei den sehr steifen Gliedern); die Stabilität prüft
        # ``_gleichgewicht`` (PyNites Restprüfung schlägt bei schlecht konditionierten, aber stabilen Modellen an)
        b.fe.analyze_linear(check_stability=False, check_statics=False, sparse=len(b.fe.nodes) * 6 > 2400)
        beweglich = _gleichgewicht(b, szenarien)
        if beweglich:
            raise RuntimeError(beweglich)
    except Exception as exc:  # noqa: BLE001 - Mechanismus oder Aufbaufehler: S1 entfällt, S0 bleibt
        text = str(exc)
        if any(w in text.lower() for w in ("unstable", "singular", "gleichgewicht")):
            text = ("Stabwerk ist beweglich (Mechanismus): ein Stab oder Starrkörper ist nicht in allen Richtungen "
                    "gehalten. Verbindungen prüfen (verbinde, Gelenke); " + text[:200])
        for sz in szenarien:
            out[sz.name] = S1Ergebnis(sz.name, False, meldung=f"Stabwerk nicht gerechnet: {text}")
        return out
    for sz in szenarien:
        t1 = time.perf_counter()
        e = _auswerten(b, sz)
        if knicken:
            try:
                _knicken(b, sz, e)
            except Exception as exc:  # noqa: BLE001
                e.meldung = (e.meldung + "; " if e.meldung else "") + f"Knicken nicht gerechnet ({type(exc).__name__})"
        e.ms = (time.perf_counter() - t1) * 1000
        out[sz.name] = e
    gesamt = (time.perf_counter() - t0) * 1000
    for e in out.values():
        e.ms = round(gesamt / max(1, len(out)), 1)
    if b.vereinfacht:
        for e in out.values():
            e.meldung = (e.meldung + "; " if e.meldung else "") + "; ".join(sorted(set(b.vereinfacht)))
    return out


def _gleichgewicht(b: _Aufbau, szenarien: list[Szenario]) -> str | None:
    """Stimmen Auflagerkräfte und Lasten überein (und sind alle Verschiebungen endlich)? Sonst ist das Stabwerk
    beweglich: Meldung, sonst None."""
    fe = b.fe
    for sz in szenarien:
        R = np.zeros(3)
        for kn, _ in b.lager:
            node = fe.nodes[kn]
            R += [node.RxnFX[sz.name], node.RxnFY[sz.name], node.RxnFZ[sz.name]]
        F = b.summe.get(sz.name, np.zeros(3))
        groesse = max(float(np.linalg.norm(F)), 1e-6)
        if not np.all(np.isfinite(R)) or float(np.linalg.norm(R + F)) > 1e-3 * groesse + 1e-6:
            return (f"Gleichgewicht verletzt im Szenario „{sz.name}“ (Lasten {np.round(F, 2).tolist()} N, Lager "
                    f"{np.round(R, 2).tolist()} N)")
        for node in fe.nodes.values():
            d = (node.DX[sz.name], node.DY[sz.name], node.DZ[sz.name])
            if not all(math.isfinite(c) for c in d) or max(abs(c) for c in d) > 1e7:
                return f"Verschiebung unbeschränkt an {node.name} im Szenario „{sz.name}“"
    return None


def _spannung(N: float, My: float, Mz: float, T: float, q: Querschnitt, w: Werkstoff) -> tuple[float, float]:
    """(Vergleichsspannung MPa, Ausnutzung = Spannung / Grenze)."""
    sN = abs(N) / q.A
    sM = abs(My) / max(q.W_quer, 1e-9) + abs(Mz) / max(q.W_lang, 1e-9)
    tau = abs(T) / max(q.Wt, 1e-9)
    if w.holz:
        fa = (w.zug if N >= 0 else (w.druck or w.zug)) or w.grenze or 1.0
        fm = w.biege or w.grenze or 1.0
        return sN + sM, sN / fa + sM / fm  # Holz: lineare Interaktion, Schub nicht nachgewiesen
    sig = math.sqrt((sN + sM) ** 2 + 3 * tau * tau)
    return sig, sig / float(w.grenze or 1.0)


def _auswerten(b: _Aufbau, sz: Szenario) -> S1Ergebnis:
    m, fe = b.m, b.fe
    combo = sz.name
    e = S1Ergebnis(sz.name, True)
    for s in m.staebe.values():
        q, w = b.q_w(s)
        st = b.stationen[s.name]
        ts = [t for t, _ in st]
        u_stat = [0.0] * len(st)
        sig_stat = [0.0] * len(st)
        n_min = 0.0
        for k, (g, _, _) in enumerate(b.glieder[s.name]):
            mem = fe.members[g]
            f = np.asarray(mem.f(combo)).reshape(12)
            for ende, idx in ((0, k), (6, k + 1)):
                N = f[ende + 0] * (-1 if ende == 0 else 1)
                sig, u = _spannung(N, f[ende + 4], f[ende + 5], f[ende + 3], q, w)
                if u > u_stat[idx]:
                    u_stat[idx], sig_stat[idx] = u, sig
                n_min = min(n_min, N)
            # Mitte des Glieds (Streckenlast): Moment aus PyNite
            L = mem.L()
            try:
                Mz = mem.moment("Mz", L / 2, combo)
                My = mem.moment("My", L / 2, combo)
                Nm = mem.axial(L / 2, combo)
                Tm = mem.torque(L / 2, combo)
                sig, u = _spannung(Nm, My, Mz, Tm, q, w)
                for idx in (k, k + 1):
                    if u > u_stat[idx]:
                        u_stat[idx], sig_stat[idx] = u, sig
            except Exception:  # noqa: BLE001
                pass
        versch = []
        for _, kn in st:
            node = fe.nodes[kn]
            d = np.array([node.DX[combo], node.DY[combo], node.DZ[combo]], dtype=float)
            versch.append([round(float(c), 4) for c in d])
        quer_max, grenze_d = _durchbiegung(b, s, combo, sz)
        i_max = int(np.argmax(u_stat))
        u_max = float(u_stat[i_max])
        e.staebe[s.name] = StabErgebnis(
            s.name, [round(t, 2) for t in ts], [[round(float(c), 2) for c in s.punkt(t)] for t in ts], versch,
            [round(float(u), 4) for u in u_stat], (1.0 / u_max) if u_max > 1e-12 else math.inf,
            round(float(sig_stat[i_max]), 3), round(ts[i_max], 1), round(quer_max, 4),
            round(grenze_d, 3), None, round(n_min, 3))
    # Auflagerkräfte
    for kn, a in b.lager:
        node = fe.nodes[kn]
        F = [node.RxnFX[combo], node.RxnFY[combo], node.RxnFZ[combo]]
        M = [node.RxnMX[combo], node.RxnMY[combo], node.RxnMZ[combo]]
        e.auflager.append({"stab": a.stab, "teil": a.teile[1], "punkt": [round(float(c), 1) for c in b.knoten_pos[kn]],
                           "kraft": [round(float(c), 2) for c in F], "moment": [round(float(c), 1) for c in M],
                           "art": a.art})
    # Kräfte in die Starrkörper (Summe der Gliedkräfte am Starrkörperknoten, grob)
    for kid, kn in b.k_knoten.items():
        node = fe.nodes[kn]
        e.koerper_kraefte[kid] = [round(float(node.DX[combo]), 4), round(float(node.DY[combo]), 4),
                                  round(float(node.DZ[combo]), 4)]
    return e


def _durchbiegung(b: _Aufbau, s: Stab, combo: str, sz: Szenario) -> tuple[float, float]:
    """(Durchbiegung mm, zulässig mm) des maßgebenden Felds: zwischen zwei Stützstellen gegen die Sehne (zulässig
    Feldlänge / n), am Kragarm gegen die starre Fortsetzung an der Stützstelle (zulässig 2 · Kraglänge / n). Stützstellen
    sind Lager (Boden, geerdete Teile); hat der Stab keine, alle Anschlüsse. Starre Bewegungen des ganzen Stabs zählen
    so nicht als Durchbiegung."""
    m, fe = b.m, b.fe
    st = b.stationen[s.name]
    lager = sorted({a.t for a in m.anschluesse if a.stab == s.name and (
        a.partner[0] == "boden" or (a.partner[0] == "koerper" and m.koerper[a.partner[1]].geerdet))})
    if not lager:
        lager = sorted({a.t for a in m.anschluesse if a.stab == s.name}
                       | {a.partner[2] for a in m.anschluesse if a.partner[0] == "stab" and a.partner[1] == s.name})
    stuetz: list[float] = []
    for t in lager:
        if not stuetz or t - stuetz[-1] > 1.0:
            stuetz.append(t)
    if not stuetz:
        return 0.0, s.laenge / sz.durchbiegung

    def zustand(t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        kn = min(st, key=lambda x: abs(x[0] - t))[1]
        node = fe.nodes[kn]
        u = np.array([node.DX[combo], node.DY[combo], node.DZ[combo]], dtype=float)
        r = np.array([node.RX[combo], node.RY[combo], node.RZ[combo]], dtype=float)
        return u, r, b.knoten_pos[kn]

    def quer(v: np.ndarray) -> float:
        return float(np.linalg.norm(v - s.achse * float(np.dot(v, s.achse))))

    best = (0.0, 0.0, s.laenge / sz.durchbiegung)  # (Verhältnis, mm, zulässig)
    for a, c in zip(stuetz[:-1], stuetz[1:]):
        ua, _, _ = zustand(a)
        uc, _, _ = zustand(c)
        zul = (c - a) / sz.durchbiegung
        for t, kn in st:
            if a < t < c:
                u, _, _ = zustand(t)
                d = quer(u - (ua + (uc - ua) * (t - a) / (c - a)))
                if zul > 0 and d / zul > best[0]:
                    best = (d / zul, d, zul)
    for anker, ende in ((stuetz[0], 0.0), (stuetz[-1], s.laenge)):
        kraglaenge = abs(ende - anker)
        if kraglaenge < 1.0:
            continue
        u0, r0, p0 = zustand(anker)
        zul = 2 * kraglaenge / sz.durchbiegung
        for t, kn in st:
            if (ende < t < anker) or (anker < t <= ende) or (ende <= t < anker):
                u, _, p = zustand(t)
                d = quer(u - (u0 + np.cross(r0, p - p0)))
                if d / zul > best[0]:
                    best = (d / zul, d, zul)
    if len(stuetz) == 1 and best[0] == 0.0:
        best = (0.0, 0.0, 2 * max(stuetz[0], s.laenge - stuetz[0]) / sz.durchbiegung)
    return best[1], best[2]


def _knicken(b: _Aufbau, sz: Szenario, e: S1Ergebnis) -> None:
    """Kleinster Lastfaktor λ mit (K + λ Kg) φ = 0 (nur wenn ein Stab auf Druck steht)."""
    if not any(r.normalkraft_min < -1e-3 for r in e.staebe.values()):
        return
    import scipy.sparse as sps
    from Pynite.Analysis import _partition_D

    fe = b.fe
    combo = sz.name
    K = fe.Ke(combo, sparse=True, check_stability=False).tocsr()
    Kg = fe.Kg(combo, sparse=True, first_step=False).tocsr()
    D1, _, _ = _partition_D(fe)
    D1 = np.asarray(D1, dtype=int)
    K11 = K[D1][:, D1]
    G11 = -Kg[D1][:, D1]
    n = K11.shape[0]
    lam, phi = None, None
    try:
        from scipy.sparse.linalg import eigsh

        w, v = eigsh(sps.csc_matrix(K11), k=min(6, n - 2), M=sps.csc_matrix(G11), sigma=1e-3, which="LM",
                     mode="buckling")
        pos = [(float(x), v[:, i]) for i, x in enumerate(w) if x > 1e-9]
        if pos:
            lam, phi = min(pos, key=lambda p: p[0])
    except Exception:  # noqa: BLE001 - kleine Modelle dicht
        if n <= 900:
            import scipy.linalg as sla

            w, v = sla.eig(K11.toarray(), G11.toarray())
            pos = [(float(x.real), v[:, i].real) for i, x in enumerate(w)
                   if np.isfinite(x) and abs(x.imag) < 1e-9 and x.real > 1e-9]
            if pos:
                lam, phi = min(pos, key=lambda p: p[0])
    if lam is None:
        return
    e.knicken = round(lam, 4)
    # Stab mit der größten Auslenkung im Knickfall
    voll = np.zeros(len(fe.nodes) * 6)
    voll[D1] = phi
    best, best_v = None, -1.0
    for s_name, st in b.stationen.items():
        amp = 0.0
        for _, kn in st:
            i = fe.nodes[kn].ID * 6
            amp = max(amp, float(np.linalg.norm(voll[i:i + 3])))
        if amp > best_v:
            best, best_v = s_name, amp
    e.knick_stab = best
    if best is not None:
        e.staebe[best].knicken = e.knicken

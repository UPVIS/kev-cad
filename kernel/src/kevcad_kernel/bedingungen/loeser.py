"""Platzieren durch Lösen: ``platziere(teil, *bedingungen)`` berechnet die Lage des Teils aus seinen Bedingungen.

Ablauf (PLAN-BEDINGUNGEN.md, B4/B5):

1. Drehung geschlossen aus den Richtungspaaren (eine Richtung: kleinste Drehung, die die modellierte Lage sonst behält;
   zwei oder mehr: Kabsch/SVD).
2. Verschiebung geschlossen aus den linearen Gleichungen (kleinste Quadrate, kleinste Verschiebung bei freien
   Richtungen: das Teil bleibt so nah wie möglich an seiner modellierten Lage).
3. Bleibt ein Rest (Winkel, Tangenten, Abstände zu Achsen), kleinste Quadrate über alle sechs Freiheitsgrade (scipy).
4. Widerspruch: Rest über der Toleranz; beteiligt sind die Bedingungen, ohne die der Rest verschwindet.
5. Freiheitsgrade: Rang der Jacobi-Matrix der Reste; freie Bewegungen, die kein Gelenk erklärt, sind „unterbestimmt“.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .arten import Bedingung, BedingungsFehler, Gelenk
from .geometrie import (
    Bezug,
    als_form,
    drehvektor_matrix,
    einheit,
    matrix_location,
    minimale_drehung,
    pose,
    v3,
)
from .sammlung import aktive, aufrufstelle
from .text import richtung, vektor


@dataclass
class Freiheit:
    """Eine freie Bewegung: Drehung um eine Achse (Punkt, Richtung) oder Verschiebung entlang einer Richtung."""

    art: str  # drehung | verschiebung | schraubung
    richtung: np.ndarray
    punkt: np.ndarray | None = None
    gelenk: bool = False  # gewollt (Gelenk)

    def __post_init__(self) -> None:
        k = int(np.argmax(np.abs(self.richtung)))
        if self.richtung[k] < 0:  # Vorzeichen egal: größter Anteil positiv (X statt −X)
            self.richtung = -self.richtung

    def text(self) -> str:
        if self.art == "verschiebung":
            return f"Verschiebung entlang {richtung(self.richtung)}"
        wo = f" durch {vektor(self.punkt, 1)}" if self.punkt is not None else ""
        return f"Drehung um {richtung(self.richtung)}{wo}"

    def als_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"art": self.art, "richtung": [round(float(c), 6) for c in self.richtung],
                               "text": self.text(), "gelenk": self.gelenk}
        if self.punkt is not None:
            out["punkt"] = [round(float(c), 4) for c in self.punkt]
        return out


@dataclass
class Platzierung:
    """Ergebnis von ``platziere``: Lageänderung, Freiheitsgrade, Widerspruch."""

    quelle: Any  # TopoDS der zurückgegebenen Form
    M: np.ndarray
    bedingungen: list[Bedingung]
    frei: list[Freiheit] = field(default_factory=list)
    blockiert: list[str] = field(default_factory=list)  # Gelenke, deren Freiheitsgrad andere Bedingungen sperren
    rest: float = 0.0
    widerspruch: list[Bedingung] = field(default_factory=list)
    rest_je: dict[str, float] = field(default_factory=dict)
    ms: float = 0.0
    datei: str | None = None
    zeile: int | None = None
    label: str = ""
    teilname: str | None = None
    zentrum: np.ndarray | None = None  # Mitte der bewegten Bezüge nach dem Platzieren
    bewegt: list[int] = field(default_factory=list)  # je Bedingung: Index des Bezugs am platzierten Teil


def _gehoert(b: Bezug, form: Any) -> bool:
    """Gehört der Bezug zu dieser Form (gleiche OCCT-Geometrie, egal wo sie liegt)?"""
    if b.quelle is None:
        return False
    w = form.wrapped
    if w.IsPartner(b.quelle):
        return True
    try:
        mine = [s.wrapped for s in form.solids()]
    except Exception:  # noqa: BLE001
        mine = []
    return any(m.IsPartner(q) for m in mine for q in b.quelle_koerper)


def _kabsch(paare: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    H = sum(np.outer(u, v) for u, v in paare)
    U, _, Vt = np.linalg.svd(H)
    D = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0)])
    return Vt.T @ D @ U.T


def drehung_aus(paare: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Drehung, die die Richtungen u auf v bringt (siehe Moduldoku)."""
    paare = [(einheit(u), einheit(v)) for u, v in paare]
    if not paare:
        return np.eye(3)
    u0 = paare[0][0]
    unabhaengig = [p for p in paare[1:] if np.linalg.norm(np.cross(p[0], u0)) > 1e-6]
    if not unabhaengig:
        return minimale_drehung(*paare[0])
    return _kabsch(paare)


class _Aufgabe:
    """Ein Platzierungsproblem: bewegte Bezüge (Index je Bedingung) und das Zentrum der Drehung."""

    def __init__(self, form: Any, bedingungen: list[Bedingung]) -> None:
        self.form = form
        self.bed = bedingungen
        self.bewegt: list[int] = []  # Index des Bezugs am bewegten Teil je Bedingung
        for c in bedingungen:
            if len(c.bezuege) < 2:
                raise BedingungsFehler(f"{c.art} ({c.id or 'ohne Nummer'}) ist eine Maßbedingung und setzt kein Teil; "
                                       "nur Montagebedingungen und Gelenke an platziere übergeben")
            own = [_gehoert(b, form) for b in c.bezuege[:2]]
            if own[0] and own[1]:
                raise BedingungsFehler(f"{c.art}: beide Bezüge gehören zum zu platzierenden Teil "
                                       f"({c.bezuege[0].anzeigename()}, {c.bezuege[1].anzeigename()})")
            if not any(own):
                raise BedingungsFehler(f"{c.art} ({c.bezuege[0].anzeigename()} / {c.bezuege[1].anzeigename()}) betrifft "
                                       "das zu platzierende Teil nicht: Bezug am Teil selbst nehmen, z. B. "
                                       "bezug(teil, \"unten\")")
            if isinstance(c, Gelenk) and own[1]:
                raise BedingungsFehler(f"{c.art}: der erste Bezug gehört zum bewegten Teil, der zweite zum festen "
                                       "(Reihenfolge tauschen)")
            self.bewegt.append(0 if own[0] else 1)
        pts = [c.bezuege[i].p for c, i in zip(bedingungen, self.bewegt)]
        bb = form.bounding_box()
        self.zentrum = np.mean(pts, axis=0) if pts else (v3(bb.min) + v3(bb.max)) / 2
        self.L = max(float(bb.diagonal), 10.0)

    def seiten(self, M: np.ndarray) -> list[tuple[Bedingung, Bezug, Bezug, int]]:
        """(Bedingung, A, B, bewegt) mit dem bewegten Bezug in Lage M; A/B in der Reihenfolge der Bedingung."""
        out = []
        for c, i in zip(self.bed, self.bewegt):
            a, b = c.bezuege[0], c.bezuege[1]
            if i == 0:
                a = a.bewegt(M)
            else:
                b = b.bewegt(M)
            out.append((c, a, b, i))
        return out

    def residuen(self, M: np.ndarray) -> np.ndarray:
        parts = [c.residuen(A, B, self.L) for c, A, B, _ in self.seiten(M)]
        return np.concatenate(parts) if parts else np.zeros(0)

    def rest_je(self, M: np.ndarray) -> dict[int, float]:
        return {k: float(np.max(np.abs(c.residuen(A, B, self.L)))) if len(c.residuen(A, B, self.L)) else 0.0
                for k, (c, A, B, _) in enumerate(self.seiten(M))}


def _verschiebung(aufgabe: _Aufgabe, M0: np.ndarray) -> np.ndarray:
    rows, rhs = [], []
    for c, A, B, i in aufgabe.seiten(M0):
        for n, qa, qb, s in c.zeilen(A, B):
            # n · (qA − qB) = s; verschoben wird die bewegte Seite um t
            if i == 0:
                rows.append(n)
                rhs.append(s - float(np.dot(n, qa - qb)))
            else:
                rows.append(-n)
                rhs.append(s - float(np.dot(n, qa - qb)))
    if not rows:
        return np.zeros(3)
    t, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=1e-9)
    return t


def _param_pose(aufgabe: _Aufgabe, M: np.ndarray, x: np.ndarray) -> np.ndarray:
    c = M[:3, :3] @ aufgabe.zentrum + M[:3, 3]
    return pose(drehvektor_matrix(x[:3] / aufgabe.L), c, x[3:]) @ M


def _verfeinern(aufgabe: _Aufgabe, M: np.ndarray, toleranz: float) -> np.ndarray:
    from scipy.optimize import least_squares

    def f(x: np.ndarray) -> np.ndarray:
        r = aufgabe.residuen(_param_pose(aufgabe, M, x))
        return np.concatenate([r, 1e-6 * x])  # bleibt nahe am Startwert, wo das System frei ist

    res = least_squares(f, np.zeros(6), method="lm" if len(f(np.zeros(6))) >= 6 else "trf", xtol=1e-12,
                        ftol=1e-12, gtol=1e-12, max_nfev=400)
    return _param_pose(aufgabe, M, res.x)


def jacobi(aufgabe: _Aufgabe, M: np.ndarray, h: float = 1e-4) -> np.ndarray:
    n = len(aufgabe.residuen(M))
    J = np.zeros((n, 6))
    for k in range(6):
        e = np.zeros(6)
        e[k] = h
        J[:, k] = (aufgabe.residuen(_param_pose(aufgabe, M, e)) - aufgabe.residuen(_param_pose(aufgabe, M, -e))) / (2 * h)
    return J


def freiheitsgrade(aufgabe: _Aufgabe, M: np.ndarray) -> tuple[list[Freiheit], list[str]]:
    """Freie Bewegungen nach dem Lösen (ungewollte zuerst) und blockierte Gelenke."""
    J = jacobi(aufgabe, M)
    c = M[:3, :3] @ aufgabe.zentrum + M[:3, 3]
    L = aufgabe.L
    if J.size:
        _, s, Vt = np.linalg.svd(J)
        rang = int(np.sum(s > 1e-6 * max(1.0, float(s[0]))))
        N = Vt[rang:].T  # 6 × k
    else:
        N = np.eye(6)
    # gewollte Bewegungen der Gelenke als Vektoren (L·ω, t) um das Zentrum c
    gewollt: list[tuple[str, np.ndarray, str, np.ndarray, np.ndarray]] = []
    for cc, A, B, _ in aufgabe.seiten(M):
        for art, p, d in cc.freie_bewegungen(A, B):
            if art == "drehung":
                vec = np.concatenate([L * d, np.cross(d, c - p)])
            else:
                vec = np.concatenate([np.zeros(3), d])
            gewollt.append((cc.art, vec, art, p, d))
    frei: list[Freiheit] = []
    blockiert: list[str] = []
    G = np.array([g[1] for g in gewollt]).T if gewollt else np.zeros((6, 0))
    for name, g, art, p, d in gewollt:
        if N.shape[1] == 0 or np.linalg.norm(g - N @ (N.T @ g)) > 1e-6 * max(1.0, np.linalg.norm(g)):
            blockiert.append(name)
        else:
            frei.append(Freiheit(art, d, p if art == "drehung" else None, gelenk=True))
    if N.shape[1]:
        if G.shape[1]:
            Q, _ = np.linalg.qr(G)
            rest = N - Q @ (Q.T @ N)
        else:
            rest = N
        U, s, _ = np.linalg.svd(rest, full_matrices=False)
        for k in range(int(np.sum(s > 1e-6))):
            v = U[:, k]
            w, t = v[:3] / L, v[3:]
            if np.linalg.norm(w) < 1e-9:
                frei.append(Freiheit("verschiebung", einheit(t)))
            else:
                dw = einheit(w)
                punkt = c + np.cross(w, t) / float(np.dot(w, w))
                frei.append(Freiheit("drehung", dw, punkt))
    frei.sort(key=lambda f: f.gelenk)
    return frei, blockiert


def platziere(teil: Any, *bedingungen: Any, toleranz: float | None = None) -> Any:
    """Lage von ``teil`` aus den Bedingungen (Montagebedingungen und Gelenke, Bezüge am Teil und an festen Teilen).
    Liefert das verschobene/gedrehte Teil (wie ``Pos(...) * teil``); das Original bleibt unverändert."""
    t0 = time.perf_counter()
    form = als_form(teil)
    if form is None or getattr(form, "wrapped", None) is None:
        raise BedingungsFehler("platziere: erstes Argument muss ein Teil sein (build123d-Form)")
    bed: list[Bedingung] = []
    for c in bedingungen:
        if isinstance(c, (list, tuple)):
            bed.extend(c)
        else:
            bed.append(c)
    for c in bed:
        if not isinstance(c, Bedingung):
            raise BedingungsFehler(f"platziere: {type(c).__name__} ist keine Bedingung (auf(…), konzentrisch(…), …)")
    if not bed:
        raise BedingungsFehler("platziere: mindestens eine Bedingung angeben")
    aufgabe = _Aufgabe(form, bed)
    tol = min([c.toleranz for c in bed] + ([toleranz] if toleranz is not None else []))

    # 1. Drehung
    paare = []
    for c, A, B, i in aufgabe.seiten(np.eye(4)):
        for u, v in c.richtungen(A, B):
            paare.append((u, v) if i == 0 else (v, u))
    R = drehung_aus(paare)
    M = pose(R, aufgabe.zentrum, np.zeros(3))
    # 2. Verschiebung
    t = _verschiebung(aufgabe, M)
    M = pose(R, aufgabe.zentrum, t)
    # 3. Rest
    r = aufgabe.residuen(M)
    if len(r) and float(np.max(np.abs(r))) > tol * 0.1:
        M = _verfeinern(aufgabe, M, tol)
        r = aufgabe.residuen(M)
    # Gelenke merken sich die Bezugslage, dann ihre Werte setzen
    for c, A, B, _ in aufgabe.seiten(M):
        c.vor_platzieren(A, B)
    for c, A, B, _ in aufgabe.seiten(M):
        extra = c.nachdrehung(A, B)
        if extra is not None:
            M = extra @ M
    rest = float(np.max(np.abs(r))) if len(r) else 0.0
    je = aufgabe.rest_je(M)
    widerspruch: list[Bedingung] = []
    if rest > tol:
        widerspruch = _widerspruch(aufgabe, bed, tol)
    frei, blockiert = freiheitsgrade(aufgabe, M)
    out = matrix_location(M) * form
    datei, zeile = aufrufstelle()
    pl = Platzierung(out.wrapped, M, bed, frei, blockiert, rest, widerspruch,
                     {bed[k].id or str(k): v for k, v in je.items()}, round((time.perf_counter() - t0) * 1000, 2),
                     datei, zeile, label=str(getattr(form, "label", "") or ""),
                     zentrum=M[:3, :3] @ aufgabe.zentrum + M[:3, 3], bewegt=list(aufgabe.bewegt))
    for c, i in zip(bed, aufgabe.bewegt):
        c.platzierung = pl
        c.bezuege[i].M_platziert = M
    s = aktive()
    if s is not None:
        s.platzierung(pl)
    return out


def _widerspruch(aufgabe: _Aufgabe, bed: list[Bedingung], tol: float) -> list[Bedingung]:
    """Bedingungen, ohne die der Rest verschwindet (sonst alle mit Rest über der Toleranz)."""
    kandidaten = []
    if len(bed) > 1:
        for k in range(len(bed)):
            ohne = [c for j, c in enumerate(bed) if j != k]
            try:
                sub = _Aufgabe(aufgabe.form, ohne)
                R = drehung_aus([(u, v) if i == 0 else (v, u) for c, A, B, i in sub.seiten(np.eye(4))
                                 for u, v in c.richtungen(A, B)])
                M = pose(R, sub.zentrum, np.zeros(3))
                M = pose(R, sub.zentrum, _verschiebung(sub, M))
                r = sub.residuen(M)
                if len(r) and float(np.max(np.abs(r))) > tol * 0.1:
                    M = _verfeinern(sub, M, tol)
                    r = sub.residuen(M)
                if not len(r) or float(np.max(np.abs(r))) <= tol:
                    kandidaten.append(bed[k])
            except Exception:  # noqa: BLE001
                continue
    if kandidaten:
        return kandidaten
    return list(bed)

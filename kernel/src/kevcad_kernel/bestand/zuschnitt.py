"""Zuschnitt mit Bestand (BESTAND.md, Abschnitt „Zuschnitt mit Bestand“).

Stangen (1D): Stücke absteigend; jedes zuerst in den kleinsten passenden Rest, dann in ganze Stangen aus dem Bestand
(angefangene zuerst), dann in neu zu kaufende. Danach ein kleines gemischt-ganzzahliges Problem mit
``scipy.optimize.milp`` (Zeitlimit 200 ms); es ersetzt die Näherung nur, wenn es nach derselben Bewertung besser ist.

Bewertung (kleiner ist besser), in dieser Rangfolge:

1. neu zu kaufende Stangen bzw. Platten (Gewicht größer als alles andere zusammen),
2. Verschnitt in mm (Reste unter dem Mindestrest) bzw. mm² (Platten, samt Sägefugen),
3. Anzahl der Reste danach (lieber wenige lange als viele kurze; ein aufgebrauchter Rest zählt als gewonnen),
4. angebrochene ganze Stangen bzw. Platten aus dem Bestand (Reste zuerst).

Sägeblatt: Jedes Stück kostet seine Länge plus eine Schnittbreite; passt das letzte Stück genau auf das Ende, entfällt
der letzte Schnitt. Rest einer Stange = Länge − Stücke − Schnitte (nie negativ).

Platten (2D): Guillotine-Schnitte (durchgehende Schnitte wie an der Kreissäge) mit freien Rechtecken; mehrere Varianten
(Sortierung, Wahl des freien Rechtecks, Schnittrichtung) im Zeitlimit, die beste nach derselben Bewertung gilt.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

EPS = 1e-6
ZEITLIMIT_S = 0.2


def vorladen() -> bool:
    """scipy.optimize laden (der erste Import dauert bis zu einer Sekunde und zählt nicht zum Zeitlimit)."""
    try:
        from scipy.optimize import milp  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


# ---------------------------------------------------------------------------------------------------------------------
# Stangen


@dataclass
class Quelle:
    art: str  # "rest" | "bestand" | "kaufen"
    kennung: str | None
    laenge: float


@dataclass
class Belegung:
    quelle: Quelle
    stuecke: list[float] = field(default_factory=list)

    def frei(self, s: float) -> float:
        """Längstes Stück, das noch hinpasst."""
        return self.quelle.laenge - sum(self.stuecke) - s * len(self.stuecke)

    def rest(self, s: float) -> float:
        return max(0.0, self.frei(s))


@dataclass
class Plan1D:
    belegungen: list[Belegung]  # nur benutzte Quellen, Reihenfolge: Reste, Bestand, kaufen
    zu_lang: list[float]
    verfahren: str  # "naeherung" | "milp"
    dauer_ms: float
    bewertung: float
    milp_status: str | None = None


def _gewichte(quellen_laengen: list[float], m: float) -> tuple[float, float, float]:
    p_rest = 0.5 * m if m > 0 else 1.0
    p_ganz = m if m > 0 else 2.0
    w_kauf = sum(quellen_laengen) + (p_rest + p_ganz) * (len(quellen_laengen) + 1) + 1.0
    return w_kauf, p_rest, p_ganz


def bewertung_1d(belegungen: list[Belegung], s: float, m: float, w: tuple[float, float, float]) -> float:
    w_kauf, p_rest, p_ganz = w
    score = 0.0
    for b in belegungen:
        if not b.stuecke:
            continue
        r = b.rest(s)
        kurz = r < m - EPS
        if kurz:
            score += r
        if b.quelle.art == "kaufen":
            score += w_kauf
        if b.quelle.art == "bestand":
            score += p_ganz
        # Reste danach: ein neuer Rest +1, ein aufgebrauchter Rest −1
        score += p_rest * ((0 if kurz else 1) - (1 if b.quelle.art == "rest" else 0))
    return score


def naeherung_1d(stuecke: list[float], reste: list[tuple[str, float]], ganze_anzahl: int, ganze_laenge: float | None,
                 kauf_laenge: float | None, s: float) -> tuple[list[Belegung], list[float]]:
    """Die Näherung aus dem Vertrag. ``reste``: (Kennung, Länge). Rückgabe (benutzte Belegungen, zu lange Stücke)."""
    rest_b = [Belegung(Quelle("rest", k, float(L))) for k, L in reste]
    bestand_b: list[Belegung] = []
    kauf_b: list[Belegung] = []
    frei_ganze = int(ganze_anzahl)
    zu_lang: list[float] = []

    def best(cands: list[Belegung], p: float) -> Belegung | None:
        fit = [b for b in cands if b.frei(s) >= p - EPS]
        return min(fit, key=lambda b: b.frei(s)) if fit else None

    for p in sorted((float(x) for x in stuecke), reverse=True):
        b = best(rest_b, p) or best(bestand_b, p)
        if b is None and frei_ganze > 0 and ganze_laenge and ganze_laenge >= p - EPS:
            b = Belegung(Quelle("bestand", None, float(ganze_laenge)))
            bestand_b.append(b)
            frei_ganze -= 1
        if b is None:
            b = best(kauf_b, p)
        if b is None and kauf_laenge and kauf_laenge >= p - EPS:
            b = Belegung(Quelle("kaufen", None, float(kauf_laenge)))
            kauf_b.append(b)
        if b is None:
            zu_lang.append(p)
            continue
        b.stuecke.append(p)
    used = [b for b in rest_b if b.stuecke] + bestand_b + kauf_b
    return used, zu_lang


def _milp_1d(stuecke: list[float], quellen: list[Quelle], s: float, m: float, w: tuple[float, float, float],
             zeitlimit_s: float) -> tuple[list[Belegung] | None, str]:
    """Zuordnung als MILP. Variablen je Quelle j: x[t,j] (Stücke vom Typ t), y[j] benutzt, v[j] Rest ist Verschnitt,
    z[j] Verschnitt in mm."""
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except Exception as exc:  # noqa: BLE001 - ohne scipy bleibt die Näherung
        return None, f"scipy fehlt ({exc})"
    w_kauf, p_rest, p_ganz = w
    typen = sorted(Counter(stuecke).items(), key=lambda kv: -kv[0])
    T, J = len(typen), len(quellen)
    if T == 0 or J == 0:
        return None, "leer"
    nx = T * J
    iy, iv, iz = nx, nx + J, nx + 2 * J
    n = nx + 3 * J

    def xi(t: int, j: int) -> int:
        return t * J + j

    c = np.zeros(n)
    lb = np.zeros(n)
    ub = np.zeros(n)
    integ = np.ones(n)
    for j, q in enumerate(quellen):
        for t, (p, cnt) in enumerate(typen):
            ub[xi(t, j)] = min(cnt, int((q.laenge + s + EPS) // (p + s))) if p <= q.laenge + EPS else 0
        ub[iy + j] = ub[iv + j] = 1
        ub[iz + j] = q.laenge
        integ[iz + j] = 0
        c[iz + j] = 1.0
        c[iv + j] = -p_rest
        c[iy + j] = {"rest": 0.0, "bestand": p_ganz + p_rest, "kaufen": w_kauf + p_rest}[q.art]
    rows: list[tuple[dict[int, float], float, float]] = []
    for t, (p, cnt) in enumerate(typen):
        rows.append(({xi(t, j): 1.0 for j in range(J)}, cnt, cnt))
    for j, q in enumerate(quellen):
        use = {xi(t, j): p + s for t, (p, _) in enumerate(typen)}
        L = q.laenge
        # Kapazität: Σ(p+s)x ≤ (L+s)·y
        rows.append(({**use, iy + j: -(L + s)}, -np.inf, 0.0))
        # Rest r = L·y − Σ(p+s)x; Verschnitt z ≥ r − L·(1−v)  ⇔  −z + L·y − Σ(p+s)x + L·v ≤ L
        rows.append(({**{k: -v for k, v in use.items()}, iz + j: -1.0, iy + j: L, iv + j: L}, -np.inf, L))
        # Kein Verschnitt ⇒ Rest ≥ Mindestrest:  r − m·y + (m+s)·v ≥ 0
        rows.append(({**{k: -v for k, v in use.items()}, iy + j: L - m, iv + j: m + s}, 0.0, np.inf))
        # v ≤ y
        rows.append(({iv + j: 1.0, iy + j: -1.0}, -np.inf, 0.0))
    # Gleiche Stangen: Symmetrie brechen (y_j ≥ y_{j+1})
    for j in range(J - 1):
        a, b = quellen[j], quellen[j + 1]
        if a.art == b.art and a.art in ("bestand", "kaufen") and abs(a.laenge - b.laenge) < EPS:
            rows.append(({iy + j: 1.0, iy + j + 1: -1.0}, 0.0, np.inf))
    A = lil_matrix((len(rows), n))
    lo = np.empty(len(rows))
    hi = np.empty(len(rows))
    for r, (coefs, l_, h_) in enumerate(rows):
        for k, v in coefs.items():
            A[r, k] = v
        lo[r], hi[r] = l_, h_
    res = milp(c, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=integ, bounds=Bounds(lb, ub),
               options={"time_limit": max(0.01, zeitlimit_s), "disp": False})
    if res.x is None:
        return None, f"ohne Lösung ({res.message})"
    x = np.rint(res.x[:nx]).astype(int)
    out: list[Belegung] = []
    for j, q in enumerate(quellen):
        pieces = [p for t, (p, _) in enumerate(typen) for _ in range(int(x[xi(t, j)]))]
        if pieces:
            b = Belegung(q, sorted(pieces, reverse=True))
            if sum(pieces) + s * (len(pieces) - 1) > q.laenge + 1e-3:
                return None, "Rundungsfehler"
            out.append(b)
    got = Counter(p for b in out for p in b.stuecke)
    if got != Counter(stuecke):
        return None, "unvollständig"
    status = "optimal" if res.status == 0 else ("Zeitlimit" if res.status == 1 else str(res.status))
    return out, status


def _ordnen(belegungen: list[Belegung]) -> list[Belegung]:
    rang = {"rest": 0, "bestand": 1, "kaufen": 2}
    for b in belegungen:
        b.stuecke.sort(reverse=True)
    return sorted(belegungen, key=lambda b: (rang[b.quelle.art], b.quelle.kennung or "", -sum(b.stuecke)))


def plane_1d(stuecke: list[float], reste: list[tuple[str, float]], ganze_anzahl: int, ganze_laenge: float | None,
             kauf_laenge: float | None, s: float = 3.0, m: float = 100.0, *, zeitlimit_s: float = ZEITLIMIT_S,
             optimieren: bool = True) -> Plan1D:
    """Zuschnitt einer Stangenware aus Resten, ganzen Stangen und Kauf (siehe Moduldoku)."""
    if optimieren:
        vorladen()
    t0 = time.perf_counter()
    stuecke = [float(x) for x in stuecke if float(x) > 0]
    used, zu_lang = naeherung_1d(stuecke, reste, ganze_anzahl, ganze_laenge, kauf_laenge, s)
    # zu lange Stücke nehmen an der Verbesserung nicht teil
    rest_count = Counter(stuecke)
    rest_count.subtract(Counter(zu_lang))
    plan_stuecke = [p for p, k in rest_count.items() for _ in range(max(0, k))]
    kmin = min(plan_stuecke) if plan_stuecke else 0.0
    n_kauf = sum(1 for b in used if b.quelle.art == "kaufen")
    quellen: list[Quelle] = [Quelle("rest", k, float(L)) for k, L in reste if float(L) >= kmin - EPS]
    if ganze_laenge:
        quellen += [Quelle("bestand", None, float(ganze_laenge))
                    for _ in range(min(int(ganze_anzahl), len(plan_stuecke)))]
    if kauf_laenge:
        quellen += [Quelle("kaufen", None, float(kauf_laenge)) for _ in range(n_kauf)]
    w = _gewichte([q.laenge for q in quellen], m)
    best, verfahren, status = used, "naeherung", None
    score = bewertung_1d(used, s, m, w)
    if optimieren and plan_stuecke:
        left = zeitlimit_s - (time.perf_counter() - t0)
        sol, status = _milp_1d(plan_stuecke, quellen, s, m, w, left)
        if sol is not None:
            sc = bewertung_1d(sol, s, m, w)
            if sc < score - 1e-6:
                best, verfahren, score = sol, "milp", sc
    return Plan1D(_ordnen(best), sorted(zu_lang, reverse=True), verfahren,
                  round((time.perf_counter() - t0) * 1000, 2), round(score, 3), status)


# ---------------------------------------------------------------------------------------------------------------------
# Platten


@dataclass
class PlattenQuelle:
    art: str  # "rest" | "bestand" | "kaufen"
    kennung: str | None
    b: float
    h: float


@dataclass
class Rechteck:
    x: float
    y: float
    b: float
    h: float

    @property
    def flaeche(self) -> float:
        return self.b * self.h


@dataclass
class Platzierung:
    nr: int  # Index des Stücks in der Eingabe
    b: float  # wie gelegt (entlang x)
    h: float  # wie gelegt (entlang y)
    x: float
    y: float
    gedreht: bool


@dataclass
class PlattenBelegung:
    quelle: PlattenQuelle
    stuecke: list[Platzierung] = field(default_factory=list)
    frei: list[Rechteck] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.frei and not self.stuecke:
            self.frei = [Rechteck(0.0, 0.0, self.quelle.b, self.quelle.h)]

    def reste(self, m: float) -> list[Rechteck]:
        return [r for r in self.frei if min(r.b, r.h) >= m - EPS]

    def verschnitt(self, m: float) -> float:
        used = sum(p.b * p.h for p in self.stuecke)
        return self.quelle.b * self.quelle.h - used - sum(r.flaeche for r in self.reste(m))


@dataclass
class Plan2D:
    belegungen: list[PlattenBelegung]
    zu_gross: list[tuple[float, float]]
    verfahren: str
    dauer_ms: float
    bewertung: float
    varianten: int = 0


def _passt(fr: Rechteck, b: float, h: float) -> bool:
    return b <= fr.b + EPS and h <= fr.h + EPS


def _wahl(fr: Rechteck, b: float, h: float, regel: str) -> float:
    if regel == "flaeche":
        return fr.flaeche - b * h
    if regel == "kurz":
        return min(fr.b - b, fr.h - h)
    return max(fr.b - b, fr.h - h)  # "lang"


def _setzen(bel: PlattenBelegung, nr: int, b: float, h: float, s: float, drehen: bool, regel: str,
            schnitt: str) -> bool:
    best = None
    for i, fr in enumerate(bel.frei):
        for bb, hh, rot in ((b, h, False), (h, b, True)) if drehen and abs(b - h) > EPS else ((b, h, False),):
            if _passt(fr, bb, hh):
                key = (_wahl(fr, bb, hh, regel), fr.y, fr.x)
                if best is None or key < best[0]:
                    best = (key, i, bb, hh, rot)
    if best is None:
        return False
    _, i, bb, hh, rot = best
    fr = bel.frei.pop(i)
    bel.stuecke.append(Platzierung(nr, bb, hh, fr.x, fr.y, rot))
    rb, rh = fr.b - bb - s, fr.h - hh - s  # Breite rechts, Höhe oben nach der Sägefuge
    if schnitt == "flaeche":  # Schnitt so, dass das größere freie Rechteck möglichst groß bleibt
        oben, rechts = max(rh, 0.0), max(rb, 0.0)
        horizontal = max(fr.b * oben, rechts * hh) >= max(rechts * fr.h, bb * oben)
    elif schnitt == "kurz":
        horizontal = (fr.b - bb) < (fr.h - hh)
    else:
        horizontal = (fr.b - bb) >= (fr.h - hh)
    if horizontal:  # oben über die ganze Breite, rechts nur neben dem Stück
        neu = [Rechteck(fr.x, fr.y + hh + s, fr.b, rh), Rechteck(fr.x + bb + s, fr.y, rb, hh)]
    else:  # rechts über die ganze Höhe, oben nur über dem Stück
        neu = [Rechteck(fr.x + bb + s, fr.y, rb, fr.h), Rechteck(fr.x, fr.y + hh + s, bb, rh)]
    bel.frei += [r for r in neu if r.b > EPS and r.h > EPS]
    return True


def bewertung_2d(belegungen: list[PlattenBelegung], m: float, w: tuple[float, float, float]) -> float:
    w_kauf, p_rest, p_ganz = w
    score = 0.0
    for bel in belegungen:
        if not bel.stuecke:
            continue
        score += bel.verschnitt(m)
        score += p_rest * (len(bel.reste(m)) - (1 if bel.quelle.art == "rest" else 0))
        if bel.quelle.art == "kaufen":
            score += w_kauf
        elif bel.quelle.art == "bestand":
            score += p_ganz
    return score


def _naeherung_2d(stuecke: list[tuple[float, float]], reste: list[PlattenQuelle], ganze_anzahl: int,
                  ganze: tuple[float, float] | None, kauf: tuple[float, float] | None, s: float, drehen: bool,
                  sortierung: str, regel: str, schnitt: str) -> tuple[list[PlattenBelegung], list[int]]:
    rest_b = [PlattenBelegung(q) for q in sorted(reste, key=lambda q: q.b * q.h)]
    bestand_b: list[PlattenBelegung] = []
    kauf_b: list[PlattenBelegung] = []
    frei_ganze = int(ganze_anzahl)
    zu_gross: list[int] = []
    keys = {"flaeche": lambda i: -(stuecke[i][0] * stuecke[i][1]),
            "seite": lambda i: -max(stuecke[i]),
            "umfang": lambda i: -(stuecke[i][0] + stuecke[i][1])}
    order = sorted(range(len(stuecke)), key=lambda i: (keys[sortierung](i), i))

    def fits_plate(b: float, h: float, pb: float, ph: float) -> bool:
        return (b <= pb + EPS and h <= ph + EPS) or (drehen and h <= pb + EPS and b <= ph + EPS)

    for i in order:
        b, h = stuecke[i]
        placed = False
        for group in (rest_b, bestand_b):
            if any(_setzen(bel, i, b, h, s, drehen, regel, schnitt) for bel in group):
                placed = True
                break
        if not placed and frei_ganze > 0 and ganze and fits_plate(b, h, *ganze):
            bel = PlattenBelegung(PlattenQuelle("bestand", None, *ganze))
            bestand_b.append(bel)
            frei_ganze -= 1
            placed = _setzen(bel, i, b, h, s, drehen, regel, schnitt)
        if not placed:
            placed = any(_setzen(bel, i, b, h, s, drehen, regel, schnitt) for bel in kauf_b)
        if not placed:
            # ohne Standardformat: genau dieses Stück als Zuschnitt kaufen
            fmt = kauf if kauf else (b, h)
            if fits_plate(b, h, *fmt):
                bel = PlattenBelegung(PlattenQuelle("kaufen", None, *fmt))
                kauf_b.append(bel)
                placed = _setzen(bel, i, b, h, s, drehen, regel, schnitt)
        if not placed:
            zu_gross.append(i)
    used = [bel for bel in rest_b if bel.stuecke] + bestand_b + kauf_b
    return used, zu_gross


def plane_2d(stuecke: list[tuple[float, float]], reste: list[tuple[str, float, float]], ganze_anzahl: int,
             ganze: tuple[float, float] | None, kauf: tuple[float, float] | None, s: float = 3.0, m: float = 100.0,
             *, drehen: bool = True, zeitlimit_s: float = ZEITLIMIT_S) -> Plan2D:
    """Plattenzuschnitt mit Guillotine-Schnitten aus Resten, ganzen Platten und Kauf. ``stuecke``: (b, h) je Stück;
    ``reste``: (Kennung, b, h); ``kauf``: Standardformat oder None (dann wird jedes Stück als Zuschnitt gekauft)."""
    t0 = time.perf_counter()
    rq = [PlattenQuelle("rest", k, float(b), float(h)) for k, b, h in reste]
    flaechen = [q.b * q.h for q in rq] + ([ganze[0] * ganze[1]] * int(ganze_anzahl) if ganze else [])
    flaechen += [(kauf[0] * kauf[1]) if kauf else b * h for b, h in stuecke]
    p_rest = 0.5 * m * m if m > 0 else 1.0
    p_ganz = m * m if m > 0 else 2.0
    w = (sum(flaechen) + (p_rest + p_ganz) * (len(flaechen) + 1) + 1.0, p_rest, p_ganz)
    best: tuple[float, list[PlattenBelegung], list[int], str] | None = None
    varianten = 0
    combos = [(so, re, sc) for so in ("flaeche", "seite", "umfang") for re in ("flaeche", "kurz", "lang")
              for sc in ("flaeche", "lang", "kurz")]
    for k, (so, re, sc) in enumerate(combos):
        if k > 0 and time.perf_counter() - t0 > zeitlimit_s:
            break
        used, zu = _naeherung_2d(stuecke, rq, ganze_anzahl, ganze, kauf, s, drehen, so, re, sc)
        varianten += 1
        score = bewertung_2d(used, m, w) + w[0] * 10 * len(zu)
        if best is None or score < best[0] - 1e-6:
            best = (score, used, zu, f"guillotine {so}/{re}/{sc}")
    assert best is not None
    score, used, zu, name = best
    rang = {"rest": 0, "bestand": 1, "kaufen": 2}
    used = sorted(used, key=lambda bel: rang[bel.quelle.art])
    return Plan2D(used, [stuecke[i] for i in zu], name if varianten > 1 else "naeherung",
                  round((time.perf_counter() - t0) * 1000, 2), round(score, 3), varianten)


def platzierungen(bel: PlattenBelegung) -> list[dict[str, Any]]:
    return [{"b": p.b, "h": p.h, "x": p.x, "y": p.y, "gedreht": p.gedreht} for p in bel.stuecke]

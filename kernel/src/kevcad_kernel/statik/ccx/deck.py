"""CalculiX-Eingabe (``.inp``) aus Körpern mit Tetraedern zweiter Ordnung (C3D10), nur im S4-Prozess.

Ein ``Deck`` sammelt Körper (Knoten, Elemente, Werkstoff), feste Knoten, Kontaktpaare (Fläche zu Fläche, Strafverfahren,
Coulomb-Reibung), weiche Halte-Federn gegen Starrkörperbewegungen und Schritte mit Knotenkräften. ``schreibe`` erzeugt
die Datei; Knoten und Elemente werden über alle Körper fortlaufend nummeriert (ab 1).

Knotenfolge C3D10 (wie Abaqus/CalculiX): Ecken 1–4, dann die Kantenmitten 1-2, 2-3, 3-1, 1-4, 2-4, 3-4; die Ecken
positiv orientiert (det[x2−x1, x3−x1, x4−x1] > 0). Flächen eines Tetraeders: S1 = 1-2-3, S2 = 1-4-2, S3 = 2-4-3,
S4 = 3-4-1 (die Fläche ohne Ecke 4, 3, 1 bzw. 2).

Werkstoff je Körper: isotrop (``E``, ``nu``) oder quer zur Schicht weicher (``E_z`` und ``normale``: technische
Konstanten mit eigener Orientierung, wie S3), dazu auf Wunsch Plastizität (``plastisch``: Fließkurve als
[(Spannung, plastische Dehnung), …], isotrope Verfestigung nach von Mises).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

KANTEN = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))  # Kantenmitten in der Reihenfolge von C3D10
UMDREHEN = np.array([1, 0, 2, 3, 4, 6, 5, 8, 7, 9])  # Ecken 1 und 2 tauschen (Orientierung), Mitten folgen
FLAECHE_OHNE = {3: 1, 2: 2, 0: 3, 1: 4}  # fehlende Ecke (Position) -> Flächennummer S1..S4


@dataclass
class Koerper:
    name: str
    knoten: np.ndarray  # (n, 3) mm
    elemente: np.ndarray  # (m, 10) Indizes in knoten, C3D10-Folge
    werkstoff: dict[str, Any]  # E, nu, optional E_z + normale, plastisch [(sigma, eps_p)]
    offset_k: int = 0  # wird beim Hinzufügen gesetzt (Knotennummer = offset_k + Index + 1)
    offset_e: int = 0

    def __post_init__(self) -> None:
        X = self.knoten[self.elemente[:, :4]]
        det = np.einsum("ij,ij->i", np.cross(X[:, 1] - X[:, 0], X[:, 2] - X[:, 0]), X[:, 3] - X[:, 0])
        neg = det < 0
        if neg.any():
            self.elemente = self.elemente.copy()
            self.elemente[neg] = self.elemente[neg][:, UMDREHEN]

    def flaechen(self, element: np.ndarray, ecken: np.ndarray) -> np.ndarray:
        """Flächennummer (1..4) je (Element, Dreieck aus drei Ecken-Indizes)."""
        E = self.elemente[element, :4]  # (k, 4)
        drin = (E[:, :, None] == ecken[:, None, :]).any(axis=2)  # (k, 4)
        fehlt = np.argmin(drin, axis=1)
        return np.array([FLAECHE_OHNE[int(i)] for i in fehlt], dtype=np.int64)


@dataclass
class Kontakt:
    name: str
    slave: tuple[int, np.ndarray, np.ndarray]  # (Körper, Elemente, Flächennummern)
    master: tuple[int, np.ndarray, np.ndarray]
    reibwert: float
    steifigkeit: float  # N/mm³, Druck je mm Durchdringung (Strafverfahren)
    haft_steifigkeit: float  # N/mm³, Schub je mm Gleiten im Haften
    spiel: float | None = None  # mm, Anfangsspalt (*CLEARANCE), None = aus der Geometrie


@dataclass
class Schritt:
    name: str
    kraefte: np.ndarray | None = None  # (n_ges, 3) Knotenkräfte, global nummeriert (Index = Knotennummer − 1)
    art: str = "statisch"  # statisch | beulen
    zeit: tuple[float, float, float, float] = (0.1, 1.0, 1e-5, 0.25)  # Anfangsschritt, Dauer, kleinster, größter
    max_inkremente: int = 200
    beulfaktoren: int = 4
    ausgabe: tuple[str, ...] = ("U", "S", "PEEQ", "KONTAKT")
    halten: bool = True  # Kräfte der vorigen Schritte bleiben (CalculiX: *CLOAD ohne OP=NEW ergänzt)
    frequenz: int = 1  # Ergebnisse jedes n-ten Inkrements (das letzte des Schritts immer)
    kontakt_frequenz: int | None = None


@dataclass
class Deck:
    koerper: list[Koerper] = field(default_factory=list)
    fest: list[np.ndarray] = field(default_factory=list)  # globale Knotennummern (1-basiert), alle drei Richtungen
    fest_richtung: list[tuple[np.ndarray, tuple[int, ...]]] = field(default_factory=list)  # (Knoten, Richtungen 1..3)
    federn: list[tuple[np.ndarray, float]] = field(default_factory=list)  # (globale Knoten, Steifigkeit N/mm)
    kontakte: list[Kontakt] = field(default_factory=list)
    schritte: list[Schritt] = field(default_factory=list)
    nlgeom: bool = False
    ausgabe_knoten: np.ndarray | None = None  # globale Knoten für U, S, PEEQ (sonst alle)
    _n: int = 0
    _m: int = 0

    def add(self, k: Koerper) -> int:
        k.offset_k, k.offset_e = self._n, self._m
        self._n += len(k.knoten)
        self._m += len(k.elemente)
        self.koerper.append(k)
        return len(self.koerper) - 1

    @property
    def knotenzahl(self) -> int:
        return self._n

    def global_knoten(self, ki: int, idx: np.ndarray) -> np.ndarray:
        return self.koerper[ki].offset_k + np.asarray(idx, dtype=np.int64) + 1

    def schreibe(self, pfad: str) -> None:
        z: list[str] = ["*HEADING", "Kev CAD Statik Stufe 4 (CalculiX)"]
        z.append("*NODE, NSET=NALL")
        for k in self.koerper:
            for i, p in enumerate(k.knoten):
                z.append(f"{k.offset_k + i + 1}, {p[0]:.9g}, {p[1]:.9g}, {p[2]:.9g}")
        for ki, k in enumerate(self.koerper):
            z.append(f"*ELEMENT, TYPE=C3D10, ELSET=K{ki}")
            el = k.elemente + k.offset_k + 1
            for j, e in enumerate(el):
                z.append(f"{k.offset_e + j + 1}, " + ", ".join(str(int(v)) for v in e[:8]) + ",")
                z.append(", ".join(str(int(v)) for v in e[8:]))
        # Werkstoffe und Querschnitte
        for ki, k in enumerate(self.koerper):
            w = k.werkstoff
            z.append(f"*MATERIAL, NAME=W{ki}")
            ez, n = w.get("E_z"), w.get("normale")
            orient = None
            if ez and n is not None and not w.get("plastisch") and abs(float(ez) - float(w["E"])) > 1e-6 * float(w["E"]):
                E, nu, Ez = float(w["E"]), float(w["nu"]), float(ez)
                G, Gz = E / (2 * (1 + nu)), Ez / (2 * (1 + nu))
                # lokal 1, 2 in der Schicht, 3 quer dazu; ν_31 = ν_32 = ν (wie S3), also ν_13 = ν E / E_z
                nu13 = nu * E / Ez
                z.append("*ELASTIC, TYPE=ENGINEERING CONSTANTS")
                z.append(f"{E:.6g}, {E:.6g}, {Ez:.6g}, {nu:.6g}, {nu13:.6g}, {nu13:.6g}, {G:.6g}, {Gz:.6g},")
                z.append(f"{Gz:.6g}, 0.")
                a, b = _basis(np.asarray(n, float))
                orient = f"O{ki}"
                z.append(f"*ORIENTATION, NAME={orient}, SYSTEM=RECTANGULAR")
                z.append(", ".join(f"{c:.9g}" for c in (*a, *b)))
            else:
                z.append("*ELASTIC")
                z.append(f"{float(w['E']):.6g}, {float(w['nu']):.6g}")
            if w.get("plastisch"):
                z.append("*PLASTIC")
                for s, e in w["plastisch"]:
                    z.append(f"{float(s):.6g}, {float(e):.6g}")
            z.append(f"*SOLID SECTION, ELSET=K{ki}, MATERIAL=W{ki}" + (f", ORIENTATION={orient}" if orient else ""))
        # feste Knoten
        alle_fest = np.unique(np.concatenate(self.fest)) if self.fest else np.zeros(0, dtype=np.int64)
        if len(alle_fest):
            z.append("*NSET, NSET=FEST")
            z += _zeilen(alle_fest)
        # Halte-Federn (eine Feder je Knoten und Richtung gegen den Boden)
        nr = self._m
        for fi, (kn, k) in enumerate(self.federn):
            for r in (1, 2, 3):
                z.append(f"*ELEMENT, TYPE=SPRING1, ELSET=F{fi}R{r}")
                for g in kn:
                    nr += 1
                    z.append(f"{nr}, {int(g)}")
                z.append(f"*SPRING, ELSET=F{fi}R{r}")
                z.append(f"{r}")
                z.append(f"{float(k):.6g}")
        # Kontakt
        for c in self.kontakte:
            for rolle, (ki, el, fl) in (("S", c.slave), ("M", c.master)):
                z.append(f"*SURFACE, NAME={c.name}{rolle}, TYPE=ELEMENT")
                off = self.koerper[ki].offset_e + 1
                for e, f in zip(el, fl):
                    z.append(f"{int(e) + off}, S{int(f)}")
            z.append(f"*SURFACE INTERACTION, NAME={c.name}I")
            z.append("*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR")
            z.append(f"{c.steifigkeit:.6g}")
            if c.reibwert > 0:
                z.append("*FRICTION")
                z.append(f"{c.reibwert:.6g}, {c.haft_steifigkeit:.6g}")
            z.append(f"*CONTACT PAIR, INTERACTION={c.name}I, TYPE=SURFACE TO SURFACE")
            z.append(f"{c.name}S, {c.name}M")
            if c.spiel is not None:
                z.append(f"*CLEARANCE, MASTER={c.name}M, SLAVE={c.name}S, VALUE={c.spiel:.6g}")
        nset = ""
        if self.ausgabe_knoten is not None and len(self.ausgabe_knoten):
            z.append("*NSET, NSET=AUSGABE")
            z += _zeilen(np.unique(self.ausgabe_knoten))
            nset = ", NSET=AUSGABE"
        if len(alle_fest) or self.fest_richtung:
            z.append("*BOUNDARY")
        if len(alle_fest):
            z.append("FEST, 1, 3")
        for kn, richtungen in self.fest_richtung:
            for g in kn:
                for r in richtungen:
                    z.append(f"{int(g)}, {int(r)}, {int(r)}")
        vorher: np.ndarray | None = None
        for s in self.schritte:
            if s.art == "beulen":
                z.append("*STEP")
                z.append("*BUCKLE")
                z.append(f"{int(s.beulfaktoren)}")
            else:
                z.append(f"*STEP, INC={int(s.max_inkremente)}" + (", NLGEOM" if self.nlgeom else ""))
                z.append("*STATIC")
                z.append(", ".join(f"{v:.6g}" for v in s.zeit))
            if s.kraefte is not None:
                F = np.asarray(s.kraefte, float)
                z.append("*CLOAD, OP=NEW")
                nz = np.where(np.any(np.abs(F) > 0, axis=1))[0]
                for i in nz:
                    for r in range(3):
                        if F[i, r] != 0.0:
                            z.append(f"{i + 1}, {r + 1}, {F[i, r]:.9g}")
                vorher = F
            elif vorher is not None and not s.halten:
                z.append("*CLOAD, OP=NEW")
            if "U" in s.ausgabe:
                z.append(f"*NODE FILE, FREQUENCY={int(s.frequenz)}{nset}")
                z.append("U")
            el = [x for x in ("S", "PEEQ") if x in s.ausgabe]
            if el and s.art != "beulen":
                z.append(f"*EL FILE, FREQUENCY={int(s.frequenz)}{nset}")
                z.append(", ".join(el))
            if "KONTAKT" in s.ausgabe and self.kontakte and s.art != "beulen":
                z.append(f"*CONTACT FILE, FREQUENCY={int(s.kontakt_frequenz or s.frequenz)}")
                z.append("CDIS, CSTR")
            if len(alle_fest) and s.art != "beulen":
                z.append("*NODE PRINT, NSET=FEST, TOTALS=ONLY")
                z.append("RF")
            z.append("*END STEP")
        with open(pfad, "w", encoding="ascii") as fh:
            fh.write("\n".join(z) + "\n")


def _zeilen(werte: np.ndarray, je: int = 12) -> list[str]:
    w = [str(int(v)) for v in werte]
    return [", ".join(w[i:i + je]) + ("," if i + je < len(w) else "") for i in range(0, len(w), je)]


def _basis(n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Zwei Punkte a, b der Orientierung (SYSTEM=RECTANGULAR): lokal 1 = a, lokal 2 in der Ebene von a und b, lokal 3 =
    Schichtnormale n."""
    n = n / float(np.linalg.norm(n))
    h = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    a = np.cross(n, h)
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    return a, b

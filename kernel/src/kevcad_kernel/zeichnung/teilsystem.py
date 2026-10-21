"""Lokales System eines Teils: die Hauptlage, in der es gezeichnet wird.

Ein Teil steht im Zusammenbau beliebig im Raum (ein Rohr senkrecht, eine Platte gekippt). Auf der Werkstattzeichnung
liegt es in seiner Hauptlage: Stangenware waagrecht mit der Länge entlang x (Vorderansicht zeigt die Bohrungen als
Kreise), Platten mit der großen Fläche in der Vorderansicht, übrige Teile aufrecht wie eingebaut, von der Seite mit den
meisten Merkmalen. Das System bestimmt auch, worauf sich Signaturen der Bezüge beziehen (DOKUMENTE.md: „im lokalen System
des Teils“): Ursprung ist die Ecke des Hüllquaders mit den kleinsten Koordinaten, alle lokalen Werte sind ≥ 0.

Regeln (begründet):

- Hauptrichtungen aus den Flächen: Normalen der Ebenen und Achsen der Zylinder, gewichtet mit dem Flächeninhalt. Die
  schwerste Richtung und die schwerste dazu senkrechte spannen das System auf; Richtungen nahe einer Weltachse werden
  auf sie gerundet (Teile aus Kev CAD stehen fast immer achsparallel).
- Stangenware: x = Stangenachse (größte Ausdehnung). Blickrichtung der Vorderansicht y = Richtung der meisten
  Querbohrungen, damit sie als Kreise mit ihrer Lage ab dem Rohrende erscheinen; ohne Bohrungen die flachere Seite.
- Platten: y = Dickenrichtung, x = längere Kante.
- Sonst: z bleibt die Welt-Hochachse (Druckteile und Eigenteile so, wie sie konstruiert sind); vorn ist die waagrechte
  Richtung, aus der die meisten Bohrungen und Taschen als wahre Gestalt zu sehen sind, bei Gleichstand die breitere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung.topologie import Topologie, analysiere

STANGENWARE = ("rohr", "vierkantrohr", "rechteckrohr", "flach", "rund", "vierkant", "winkel", "u_profil", "nutprofil",
               "holz")
WINKEL_TOL = 1e-3  # |cos| für parallel/senkrecht (≈ 0,06°)


@dataclass
class Teilsystem:
    """Zeilen von ``achsen`` sind die lokalen Achsen x, y, z in Weltkoordinaten; lokal = achsen · (welt − ursprung)."""

    achsen: np.ndarray  # (3, 3)
    ursprung: np.ndarray  # (3,) Welt
    groesse: np.ndarray  # (3,) Ausdehnung entlang der lokalen Achsen
    art: str = "allgemein"  # stange | platte | allgemein | welt

    def lokal(self, p: Any) -> np.ndarray:
        return (np.asarray(p, dtype=float) - self.ursprung) @ self.achsen.T

    def richtung_lokal(self, d: Any) -> np.ndarray:
        return np.asarray(d, dtype=float) @ self.achsen.T

    def welt(self, p: Any) -> np.ndarray:
        return np.asarray(p, dtype=float) @ self.achsen + self.ursprung

    def richtung_welt(self, d: Any) -> np.ndarray:
        return np.asarray(d, dtype=float) @ self.achsen

    def trsf(self) -> Any:
        """gp_Trsf Welt → lokal (für das Umsetzen der Form vor der Projektion)."""
        from OCP.gp import gp_Trsf

        R = self.achsen
        t = -R @ self.ursprung
        trsf = gp_Trsf()
        trsf.SetValues(R[0, 0], R[0, 1], R[0, 2], t[0],
                       R[1, 0], R[1, 1], R[1, 2], t[1],
                       R[2, 0], R[2, 1], R[2, 2], t[2])
        return trsf

    def form_lokal(self, form: Any) -> Any:
        """Kopie der Form im lokalen System (build123d-Shape)."""
        from build123d import Shape
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform

        shape = form.wrapped if hasattr(form, "wrapped") else form
        op = BRepBuilderAPI_Transform(shape, self.trsf(), False)
        return Shape.cast(op.Shape())

    @property
    def schluessel(self) -> str:
        return ",".join(f"{v:.5f}" for v in (*self.achsen.ravel(), *self.ursprung))

    def als_dict(self) -> dict[str, Any]:
        return {"achsen": [[round(float(v), 6) for v in row] for row in self.achsen],
                "ursprung": [round(float(v), 4) for v in self.ursprung],
                "groesse": [round(float(v), 4) for v in self.groesse], "art": self.art}


def welt(lo: Any = (0, 0, 0), hi: Any = (0, 0, 0)) -> Teilsystem:
    """System der Baugruppen und Zusammenbauten: Weltachsen, Ursprung 0."""
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    return Teilsystem(np.eye(3), np.zeros(3), hi - lo, "welt")


def _rund_auf_weltachse(d: np.ndarray) -> np.ndarray:
    i = int(np.argmax(np.abs(d)))
    if abs(d[i]) > 1 - 1e-5:
        e = np.zeros(3)
        e[i] = 1.0 if d[i] > 0 else -1.0
        return e
    return d / np.linalg.norm(d)


def _richtungen(top: Topologie) -> list[tuple[np.ndarray, float]]:
    """Gewichtete Hauptrichtungen (bis aufs Vorzeichen zusammengefasst), schwerste zuerst."""
    gruppen: list[list[Any]] = []  # [richtung, gewicht]
    for f in top.flaechen:
        if f.typ == "ebene" and f.n is not None:
            d, w = f.n, f.flaeche
        elif f.typ in ("zylinder", "kegel") and f.achse is not None:
            d, w = f.achse, f.flaeche
        else:
            continue
        d = _rund_auf_weltachse(np.asarray(d, dtype=float))
        for g in gruppen:
            if abs(float(np.dot(g[0], d))) > 1 - 1e-4:
                g[1] += w
                break
        else:
            gruppen.append([d if d[int(np.argmax(np.abs(d)))] > 0 else -d, w])
    gruppen.sort(key=lambda g: -g[1])
    return [(g[0], g[1]) for g in gruppen]


def _ausdehnung(form: Any, achsen: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Hüllquader der Form im System ``achsen`` (Ursprung Welt-Null): lokale Min- und Max-Ecke."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf

    trsf = gp_Trsf()
    R = achsen
    trsf.SetValues(R[0, 0], R[0, 1], R[0, 2], 0.0, R[1, 0], R[1, 1], R[1, 2], 0.0, R[2, 0], R[2, 1], R[2, 2], 0.0)
    shape = form.wrapped if hasattr(form, "wrapped") else form
    moved = BRepBuilderAPI_Transform(shape, trsf, False).Shape()
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(moved, box, False, False)
    a, b = box.CornerMin(), box.CornerMax()
    return np.array([a.X(), a.Y(), a.Z()]), np.array([b.X(), b.Y(), b.Z()])


def _bohrachsen(top: Topologie) -> list[np.ndarray]:
    """Achsen voller, nach innen gewölbter Zylinder (Bohrungen), je Bohrung einmal."""
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for f in top.flaechen:
        if f.typ != "zylinder" or not f.innen or f.spanne < 180 or f.achse is None:
            continue
        for d, p in out:
            off = f.punkt - p
            if abs(float(np.dot(d, f.achse))) > 1 - 1e-6 and np.linalg.norm(off - d * float(np.dot(off, d))) < 1e-3:
                break
        else:
            out.append((f.achse, f.punkt))
    return [d for d, _ in out]


def _boeden(top: Topologie) -> list[np.ndarray]:
    """Normalen von Taschenböden und Absätzen (ebene Flächen, die nicht auf dem Hüllquader liegen)."""
    out = []
    for f in top.flaechen:
        if f.typ != "ebene" or f.n is None:
            continue
        n = _rund_auf_weltachse(f.n)
        i = int(np.argmax(np.abs(n)))
        if abs(n[i]) < 1 - 1e-6:
            continue
        rand = top.hi[i] if n[i] > 0 else top.lo[i]
        if abs(float(f.punkt[i]) - rand) > 0.05:
            out.append(n)
    return out


def teilsystem(form: Any, info: dict[str, Any] | None = None, top: Topologie | None = None) -> Teilsystem:
    """Hauptlage eines Teils. ``info``: Felder des Teilekopfs (``stock``, ``druckteil``) und ``katalog`` (Eintrag des
    Lagerteils mit ``art``); ohne Angaben entscheidet die Form."""
    info = info or {}
    top = top or analysiere(form)
    art_lager = str(((info.get("katalog") or {}).get("art")) or "")
    if not art_lager and info.get("stock"):
        sid = str((info.get("stock") or {}).get("id") or "")
        art_lager = next((a for a in STANGENWARE if sid.startswith(a)), "platte" if sid.startswith("platte") else "")
    richtungen = _richtungen(top)
    if richtungen:
        a1 = richtungen[0][0]
        a2 = next((d for d, _ in richtungen[1:] if abs(float(np.dot(d, a1))) < WINKEL_TOL), None)
    else:
        a1, a2 = np.array([0.0, 0.0, 1.0]), None
    if a2 is None:  # nur eine Richtung (Rundstab, Kugel): die Weltachse, die am wenigsten parallel ist
        welt_achsen = np.eye(3)
        w = welt_achsen[int(np.argmin(np.abs(welt_achsen @ a1)))]
        a2 = w - a1 * float(np.dot(w, a1))
        a2 = _rund_auf_weltachse(a2 / np.linalg.norm(a2))
    a3 = np.cross(a1, a2)
    basis = np.array([a1, a2, a3])
    lo, hi = _ausdehnung(form, basis)
    ext = hi - lo
    bohr = _bohrachsen(top)

    def zaehle(d: np.ndarray, achsen: list[np.ndarray]) -> int:
        return sum(1 for a in achsen if abs(float(np.dot(a, d))) > 1 - 1e-4)

    if art_lager in STANGENWARE or (not art_lager and _stangenartig(ext, top)):
        art = "stange"
        ix = int(np.argmax(ext))
        x = basis[ix]
        rest = [i for i in range(3) if i != ix]
        # Blickrichtung: Achse der meisten Querbohrungen, sonst die schmalere Seite
        rest.sort(key=lambda i: (-zaehle(basis[i], bohr), ext[i]))
        y = basis[rest[0]]
        x = _positiv(x)
        y = _positiv(y)
    elif art_lager == "platte" or (not art_lager and _plattenartig(ext)):
        art = "platte"
        iy = int(np.argmin(ext))
        rest = sorted((i for i in range(3) if i != iy), key=lambda i: -ext[i])
        x, y = _positiv(basis[rest[0]]), _positiv(basis[iy])
        if abs(float(y[2])) > 1 - 1e-6:  # liegende Platte: von oben ansehen (Blick nach −Z wie eine Draufsicht)
            y = np.array([0.0, 0.0, -1.0])
        z = np.cross(x, y)
        if z[int(np.argmax(np.abs(z)))] < 0:  # Platte nicht auf den Kopf stellen: z möglichst nach oben
            x = -x
    else:
        art = "allgemein"
        # z = Welt-Hochachse, falls sie eine Hauptrichtung ist; sonst die Richtung, die ihr am nächsten kommt
        zw = np.array([0.0, 0.0, 1.0])
        iz = int(np.argmax(np.abs(basis @ zw)))
        z = basis[iz] * (1.0 if float(np.dot(basis[iz], zw)) >= 0 else -1.0)
        quer = [basis[i] for i in range(3) if i != iz]
        boeden = _boeden(top)
        kandidaten = []
        for q in quer:
            for s in (1.0, -1.0):
                y = q * s
                x = np.cross(y, z)
                # Merkmale, die aus dieser Richtung als wahre Gestalt zu sehen sind (von vorn, Blick entlang +y)
                punkte = zaehle(y, bohr) + sum(1 for b in boeden if float(np.dot(b, -y)) > 1 - 1e-4)
                breite = float(abs(ext @ np.abs(basis @ x)))
                vorzug = 1 if float(np.dot(y, [0, 1, 0])) > 1 - 1e-6 else 0  # Gleichstand: wie im Modell von vorn
                kandidaten.append((punkte, breite, vorzug, x, y))
        kandidaten.sort(key=lambda k: (-k[0], -round(k[1], 3), -k[2]))
        _, _, _, x, y = kandidaten[0]
    if art != "allgemein":
        z = np.cross(x, y)
    else:
        x = np.cross(y, z)
    achsen = np.array([x, y, z], dtype=float)
    lo, hi = _ausdehnung(form, achsen)
    ursprung = lo @ achsen  # lokale Min-Ecke in Welt
    return Teilsystem(achsen, ursprung, hi - lo, art)


def _positiv(d: np.ndarray) -> np.ndarray:
    i = int(np.argmax(np.abs(d)))
    return d if d[i] >= 0 else -d


def _stangenartig(ext: np.ndarray, top: Topologie) -> bool:
    """Lang und schlank mit gleichbleibendem Querschnitt (ohne Katalogangabe nur bei Verhältnis ≥ 8)."""
    s = sorted(float(v) for v in ext)
    return s[2] >= 8 * max(s[1], 1e-6)


def _plattenartig(ext: np.ndarray) -> bool:
    s = sorted(float(v) for v in ext)
    return s[0] <= 0.15 * s[1] and s[0] <= 30

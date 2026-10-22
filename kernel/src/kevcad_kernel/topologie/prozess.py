"""Topo-Prozess: ``python -m kevcad_kernel.topologie.prozess <auftrag.json> <ergebnis.json>``.

Läuft getrennt von model.py und der Laufzeit (Gmsh nur hier, wie beim Festkörper). Fortschritt als JSON-Zeilen auf
stdout (``{"fortschritt": 0.4, "text": "…", "phase": "optimieren", "iteration": 12, "dichte": "<npz>"}``), Ergebnis
als Datei; die Laufzeit bricht durch Beenden des Prozesses ab. Ablauf:

1. **Gitter:** Teil in Drucklage, Kante h aus der Voxelzahl (60 000, fein 180 000 im Teil), innen/außen je Zelle.
2. **Lager und Lasten** auf die Randknoten des Gitters: Lager an den tragenden Nachbarn (Abstand ≤ Toleranz + 0,9 h),
   Lasten wie ein RBE3 verteilt (Kontaktfläche zum Nachbarn oder Fläche um den Punkt auf derselben B-Rep-Fläche).
3. **Schutzzonen** (bleiben 1): Bohrungen mit Wandring max(Steg, 0,6 r), Gewindeeinsätze mit 1,5 × Mindestwand,
   Last- und Klemmflächen mit einer Haut max(Steg, 1,5 h), unterste Schicht (Bett), Formen und Flächen aus model.py.
4. **Vorher:** Festkörper-FEM des Ausgangsteils.
5. **SIMP** (``simp.Optimierer``), Zwischenstände der Dichte als Netz für den Viewer.
6. **Oberfläche:** Schwelle so, dass ``behalten`` stimmt, lose Inseln weg, Feld max(Abstand zum Teil, Dichte) auf einem
   halb so großen Gitter, Marching Cubes, Glätten der neuen Schnittflächen (die Flächen des Teils bleiben), Ausdünnen
   (Quadrik-Fehler), Körper (B-Rep aus Dreiecksflächen) in Teilkoordinaten.
7. **Nachher:** Festkörper-FEM am Ergebnis mit denselben Lagern und Lastflächen, Druckprüfung und Schätzung von
   Filament und Zeit vorher und nachher, dünnster Steg.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.topologie import GRENZEN, LINIENBREITE, VERSION, einstellungen

VOXEL = 60_000
VOXEL_FEIN = 180_000
LAST_RADIUS = (0.1, 3.0, 25.0)  # wie der Festkörper: Anteil der Teilgröße, mindestens, höchstens (mm)
ZIEL_DREIECKE = 8_000
ZIEL_DREIECKE_FEIN = 16_000
ZEIT_S = 150.0  # Zeitgrenze der Iterationen
BILD_S = 1.0  # Zwischenstand der Dichte höchstens so oft


def speicher() -> Path:
    p = os.environ.get("KEVCAD_TOPOLOGIE_CACHE")
    if p:
        return Path(p)
    bundle = os.environ.get("KEVCAD_APP_BUNDLE_ID") or "de.upvis.kevcad"
    return Path.home() / "Library" / "Caches" / bundle / "topologie"


def melde(fortschritt: float, text: str, **extra: Any) -> None:
    d = {"fortschritt": round(max(0.0, min(1.0, fortschritt)), 3), "text": text}
    d.update({k: v for k, v in extra.items() if v is not None})
    print(json.dumps(d, ensure_ascii=False, default=float), flush=True)


def _npz(pfad: Path, **felder: Any) -> str:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(pfad.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, **felder)
    os.replace(tmp, pfad)
    return str(pfad)


# -- Hilfen ---------------------------------------------------------------------------------------------------------


def verteile(X: np.ndarray, F: np.ndarray, M: np.ndarray | None, P: np.ndarray | None) -> np.ndarray:
    """Kraft F und Moment M (am Punkt P) gleich gewichtet auf die Punkte X wie ein RBE3: Summe und Moment genau."""
    n = len(X)
    c = X.mean(axis=0)
    r = X - c
    J = np.eye(3) * float((r * r).sum()) - r.T @ r
    Mc = np.zeros(3) if M is None else np.asarray(M, float).copy()
    if P is not None:
        Mc = Mc + np.cross(np.asarray(P, float) - c, F)
    om = np.linalg.lstsq(J, Mc, rcond=1e-12)[0] if np.any(np.abs(Mc) > 0) else np.zeros(3)
    return F[None, :] / n + np.cross(om[None, :], r)


def knoten_aus_zellen(rho: np.ndarray) -> np.ndarray:
    """Knotenwerte (nx+1, ny+1, nz+1) als Mittel der bis zu acht angrenzenden Zellen (Rand: nur vorhandene)."""
    nx, ny, nz = rho.shape
    s = np.zeros((nx + 1, ny + 1, nz + 1))
    n = np.zeros_like(s)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                s[dx:dx + nx, dy:dy + ny, dz:dz + nz] += rho
                n[dx:dx + nx, dy:dy + ny, dz:dz + nz] += 1
    return s / np.maximum(n, 1)


class Erweiterung:
    """Werte außerhalb des Bauraums = Wert der nächsten Zelle im Bauraum (damit die Dichte am Teilrand nicht abfällt)."""

    def __init__(self, aktiv: np.ndarray) -> None:
        from scipy.ndimage import distance_transform_edt

        _, idx = distance_transform_edt(~aktiv, return_distances=True, return_indices=True)
        self.idx = tuple(idx)

    def __call__(self, rho: np.ndarray) -> np.ndarray:
        return rho[self.idx]


def iso_netz(rho_knoten: np.ndarray, schwelle: float, G: Any, max_dreiecke: int = 20_000
             ) -> tuple[np.ndarray, np.ndarray]:
    """Fläche ρ = Schwelle (Knotenfeld auf dem Gitter G) in Weltkoordinaten, ausgedünnt."""
    from kevcad_kernel.topologie import oberflaeche as ob

    f = np.pad(schwelle - rho_knoten, 1, constant_values=1.0)
    p, d = ob.marching_cubes(f, G.h, tuple(G.o - G.h))
    if len(d) == 0:
        return p, d
    p = G.zu_welt(p)
    if len(d) > max_dreiecke:
        p, d = ausduennen(p, d, max_dreiecke)
    return p, d


def ausduennen(p: np.ndarray, d: np.ndarray, ziel: int) -> tuple[np.ndarray, np.ndarray]:
    """Quadrik-Ausdünnung (fast-simplification) auf etwa ``ziel`` Dreiecke; das Ergebnis muss geschlossen und
    mannigfaltig bleiben (jede Kante genau zwei Dreiecke), sonst mit anderer Stärke noch einmal."""
    from kevcad_kernel.topologie import oberflaeche as ob

    if len(d) <= ziel:
        return p, d
    try:
        import fast_simplification as fs
    except Exception:  # noqa: BLE001 - ohne Ausdünnen geht es auch, nur größer
        return p, d
    bestes = None
    for agg in (7, 5, 4, 6, 3):
        try:
            p2, d2 = fs.simplify(p.astype(np.float32), d.astype(np.int32), target_reduction=1.0 - ziel / len(d),
                                 agg=agg)
        except Exception:  # noqa: BLE001
            continue
        d2 = np.asarray(d2, np.int64)
        if len(d2) == 0 or ob.offene_kanten(d2) != 0:
            continue
        if len(d2) <= 1.5 * ziel:
            return np.asarray(p2, float), d2
        if bestes is None or len(d2) < len(bestes[1]):
            bestes = (np.asarray(p2, float), d2)
    return bestes if bestes is not None else (p, d)


# -- Aufbau ---------------------------------------------------------------------------------------------------------


class Aufbau:
    """Gitter, Bauraum, Lager, Lasten und Schutzzonen eines Auftrags."""

    def __init__(self, A: dict[str, Any], einst: dict[str, Any]) -> None:
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape

        from kevcad_kernel.topologie import oberflaeche as ob
        from kevcad_kernel.topologie import raster

        t0 = time.perf_counter()
        self.A = A
        self.einst = einst
        self.hinweise: list[str] = list(A.get("hinweise") or [])
        shape = TopoDS_Shape()
        BRepTools.Read_s(shape, A["brep"], BRep_Builder())
        self.shape = shape
        groesse = float(np.max(np.asarray(A["bmax"]) - np.asarray(A["bmin"])))
        self.groesse = groesse
        self.Pw, self.Tw, self.Fw = raster.brep_netz(shape, ablenkung=max(0.01, min(0.05, groesse / 2000)))
        self.flaeche = ob.flaeche(self.Pw, self.Tw)
        self.volumen = float(A["volumen"])
        self.R = raster.druckrahmen(A.get("oben"))
        self.steg_mm = float(einst["steg"]) * LINIENBREITE
        ziel = VOXEL_FEIN if einst["fein"] else VOXEL
        if os.environ.get("KEVCAD_TOPOLOGIE_VOXEL"):  # Tests: kleineres Gitter
            ziel = int(os.environ["KEVCAD_TOPOLOGIE_VOXEL"])
        wand = 2.0 * self.volumen / max(self.flaeche, 1e-9)
        h = (self.volumen / ziel) ** (1 / 3)
        h_wand = wand / 2.5
        if h > h_wand:  # dünne Wände: feiner, aber höchstens dreimal so viele Voxel
            h = max(h_wand, (self.volumen / (3 * ziel)) ** (1 / 3))
            if h > h_wand * 1.01:
                self.hinweise.append(f"Dünne Wände ({wand:.1f} mm im Mittel): nur {wand / h:.1f} Voxel über die "
                                     "Wand; fein=True rechnet genauer")
        self.G = raster.gitter_fuer(self.Pw, self.R, self.volumen, 1, h_min=0.25, h_max=h)
        G = self.G
        xs, ys, zs = G.achsen_mitte()
        self.aktiv = raster.innen_gitter(G.zu_druck(self.Pw), self.Tw, xs, ys, zs)
        self.n = int(self.aktiv.sum())
        if self.n < 300:
            raise ValueError(f"Teil zu klein oder zu dünn für das Gitter ({self.n} Voxel bei h = {G.h:.2f} mm)")
        # Knoten: berührt, Rand
        nx, ny, nz = G.ne
        zahl = np.zeros(G.nn, dtype=np.int64)
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    zahl[dx:dx + nx, dy:dy + ny, dz:dz + nz] += self.aktiv
        self.knoten_aktiv = zahl > 0
        self.rand = (zahl > 0) & (zahl < 8)
        self.rand_idx = np.flatnonzero(self.rand.reshape(-1))
        self.Xr = G.knoten(self.rand_idx)
        _, tri_r = raster.naechstes_dreieck(self.Xr, self.Pw, self.Tw, 1.5 * G.h)
        self.flaeche_r = np.where(tri_r >= 0, self.Fw[np.maximum(tri_r, 0)], -1)
        self.nachbarn = {x: dict(nb) for x, nb in (A.get("nachbarn") or {}).items()}
        self._nahe: dict[str, np.ndarray] = {}
        self.akt_idx = np.flatnonzero(self.aktiv.reshape(-1))
        self.mitten = G.mitten(self.akt_idx)
        self.ms = {"gitter": round((time.perf_counter() - t0) * 1000, 1)}

    def innen_punkte(self, X: np.ndarray) -> np.ndarray:
        """Liegen die Punkte (Welt) im Teil? (Zelle des Gitters, die den Punkt enthält, gehört zum Bauraum)"""
        G = self.G
        ijk = np.floor((G.zu_druck(np.asarray(X, float)) - G.o[None, :]) / G.h).astype(np.int64)
        ok = np.all((ijk >= 0) & (ijk < np.asarray(G.ne)[None, :]), axis=1)
        out = np.zeros(len(ijk), dtype=bool)
        out[ok] = self.aktiv[ijk[ok, 0], ijk[ok, 1], ijk[ok, 2]]
        return out

    # Randknoten nahe an einem Nachbarn
    def nahe(self, x: str) -> np.ndarray:
        from kevcad_kernel.topologie import raster

        if x not in self._nahe:
            nb = self.nachbarn.get(x)
            if nb is None:
                self._nahe[x] = np.zeros(0, dtype=np.int64)
            else:
                with np.load(nb["datei"]) as z:
                    d, _ = raster.naechstes_dreieck(self.Xr, z["pos"], z["tri"], float(nb["tol"]) + 0.9 * self.G.h)
                self._nahe[x] = np.flatnonzero(np.isfinite(d))
        return self._nahe[x]

    def lager(self, faelle: list[dict[str, Any]]) -> np.ndarray:
        fest = np.zeros((3,) + self.G.nn, dtype=bool)
        sel = []
        for f in faelle:
            for x in f["lager"]:
                sel.append(self.nahe(x))
        idx = np.unique(np.concatenate(sel)) if sel else np.zeros(0, dtype=np.int64)
        if len(idx) == 0:
            raise ValueError("keine Lagerfläche auf dem Gitter gefunden (berühren sich Teil und Nachbar?)")
        ijk = np.unravel_index(self.rand_idx[idx], self.G.nn)
        for c in range(3):
            fest[(c,) + ijk] = True
        self.fest_knoten = self.rand_idx[idx]
        return fest

    def lastknoten(self, last: dict[str, Any]) -> tuple[np.ndarray, str]:
        """Randknoten einer Last (Indizes in ``rand_idx``) und wie sie gefunden wurden."""
        if last.get("kontakt_mit"):
            sel = self.nahe(last["kontakt_mit"])
            if len(sel):
                return sel, "kontakt"
        P = last.get("punkt")
        if P is None:
            return np.zeros(0, dtype=np.int64), "volumen"
        P = np.asarray(P, float)
        d = np.linalg.norm(self.Xr - P[None, :], axis=1)
        j0 = int(np.argmin(d))
        f0 = int(self.flaeche_r[j0])
        anteil, rmin, rmax = LAST_RADIUS
        r = min(max(anteil * self.groesse, rmin, 2 * self.G.h), rmax)
        for _ in range(4):
            sel = np.flatnonzero((d <= d[j0] + r) & ((self.flaeche_r == f0) if f0 >= 0 else True))
            if len(sel) >= 4:
                return sel, "flaeche"
            r *= 2
        sel = np.flatnonzero(d <= d[j0] + r)
        return sel, "umkreis"

    def lasten(self, fall: dict[str, Any], passiv_knoten: np.ndarray | None) -> tuple[np.ndarray, list[np.ndarray]]:
        F = np.zeros((3,) + self.G.nn)
        flaechen = []
        Fl = F.reshape(3, -1)
        for last in fall["lasten"]:
            kraft = np.asarray(last["kraft"], float)
            M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
            P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
            sel, wie = self.lastknoten(last)
            if len(sel):
                knoten = self.rand_idx[sel]
                X = self.Xr[sel]
            else:
                # ohne Punkt und Kontakt: auf die geschützten Zonen, sonst gleichmäßig auf alle Knoten des Teils
                knoten = passiv_knoten if passiv_knoten is not None and len(passiv_knoten) else \
                    np.flatnonzero(self.knoten_aktiv.reshape(-1))
                X = self.G.knoten(knoten)
                self.hinweise.append(f"Last ohne Angriffspunkt ({last.get('quelle') or 'Szenario'}): über "
                                     f"{'die Schutzzonen' if passiv_knoten is not None and len(passiv_knoten) else 'das Teil'}"
                                     " verteilt; für die Optimierung besser st.last(…, punkt=…) angeben")
                if P is None:
                    P = X.mean(axis=0)
            f = verteile(X, kraft, M, P)
            for c in range(3):
                np.add.at(Fl[c], knoten, f[:, c])
            flaechen.append(knoten)
        Fd = np.einsum("ij,j...->i...", self.R, F)  # Welt → Druck
        return Fd, flaechen

    def schutz(self, last_knoten: list[np.ndarray]) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Geschützte Elemente (ne) und eine Liste der Zonen für den Bericht."""
        from scipy.spatial import cKDTree

        from kevcad_kernel.druck.regeln import GEWINDEEINSAETZE
        from kevcad_kernel.statik.festkoerper import kontakt
        from kevcad_kernel.topologie import raster

        e = self.einst
        G = self.G
        h = G.h
        passiv = np.zeros(len(self.akt_idx), dtype=bool)
        zonen: list[dict[str, Any]] = []
        if e["bohrungen"] or e["einsaetze"]:
            for b in raster.bohrungen(self.shape, max_radius=max(30.0, 0.3 * self.groesse)):
                d = 2 * b.radius
                einsatz = None
                # Gewindeeinsätze sitzen in Sacklöchern: ein Ende der Bohrung liegt im Material
                enden = np.stack([b.punkt + b.achse * (b.t0 - 0.6), b.punkt + b.achse * (b.t1 + 0.6)])
                sack = bool(self.innen_punkte(enden).any())
                for groesse, m in (GEWINDEEINSAETZE["ruthex"].items() if sack else ()):
                    if abs(d - float(m["bohrung"])) <= 0.25 or abs(d - float(m["bohrung"]) - 0.2) <= 0.15:
                        einsatz = (groesse, float(m["wand_min"]))
                        break
                if einsatz and e["einsaetze"]:
                    w = max(self.steg_mm, 1.5 * einsatz[1])
                    art = f"Gewindeeinsatz {einsatz[0]}"
                elif e["bohrungen"]:
                    w = max(self.steg_mm, 0.6 * b.radius)
                    art = "Bohrung"
                else:
                    continue
                sel = b.abstand(self.mitten) <= w
                if sel.any():
                    passiv |= sel
                    zonen.append({"art": art, "d": round(d, 2), "ring_mm": round(w, 2), "tiefe": round(b.t1 - b.t0, 2),
                                  "elemente": int(sel.sum()), "punkt": [round(float(c), 2) for c in b.punkt],
                                  "achse": [round(float(c), 4) for c in b.achse]})
        ts = max(self.steg_mm, 1.5 * h)
        if e["kontakt"]:
            for i, kn in enumerate(last_knoten):
                if kn is None or len(kn) == 0:
                    continue
                d, _ = cKDTree(G.knoten(kn)).query(self.mitten, distance_upper_bound=ts)
                sel = np.isfinite(d)
                if sel.any():
                    passiv |= sel
                    zonen.append({"art": "Lastfläche", "haut_mm": round(ts, 2), "elemente": int(sel.sum())})
            for x in self.A.get("klemmen") or []:
                nb = self.nachbarn.get(x)
                if nb is None:
                    continue
                with np.load(nb["datei"]) as z:
                    dd, _ = raster.naechstes_dreieck(self.mitten, z["pos"], z["tri"], float(nb["tol"]) + ts)
                sel = np.isfinite(dd)
                if sel.any():
                    passiv |= sel
                    zonen.append({"art": f"Klemmfläche zu {x}", "haut_mm": round(ts, 2), "elemente": int(sel.sum())})
        if e["bett"]:  # geschlossene Bodenhaut in Stegdicke (mindestens eine Schicht des Gitters)
            k = np.unravel_index(self.akt_idx, G.ne)[2]
            dicke = max(self.steg_mm, h)
            sel = (k + 0.5) * h <= dicke
            passiv |= sel
            zonen.append({"art": "Bettfläche", "haut_mm": round(dicke, 2), "elemente": int(sel.sum())})
        for s in self.A.get("schutz") or []:
            sel = self._schutzform(s, ts)
            if sel is not None and sel.any():
                passiv |= sel
                zonen.append({"art": f"Schutz aus model.py ({s.get('art')})", "elemente": int(sel.sum())})
        out = np.zeros(G.ne, dtype=bool)
        out.reshape(-1)[self.akt_idx[passiv]] = True
        return out, zonen

    def _schutzform(self, s: dict[str, Any], ts: float) -> np.ndarray | None:
        from scipy.spatial import cKDTree

        from kevcad_kernel.topologie import raster

        art = s.get("art") or "form"
        if art == "quader":
            lo, hi = np.asarray(s["min"], float), np.asarray(s["max"], float)
            return np.all((self.mitten >= lo) & (self.mitten <= hi), axis=1)
        if art == "kugel":
            return np.linalg.norm(self.mitten - np.asarray(s["mitte"], float), axis=1) <= float(s["radius"])
        if art == "index":  # Fläche des Teils nach Nummer (wie im Viewer)
            tri = np.flatnonzero(self.Fw == int(s["index"]))
            if len(tri) == 0:
                self.hinweise.append(f"Schutzfläche #{s['index']} gibt es nicht")
                return None
            pts = self.Pw[self.Tw[tri]].mean(axis=1)
            d, _ = raster.naechstes_dreieck(self.mitten, self.Pw, self.Tw[tri], float(s.get("dicke") or ts))
            _ = cKDTree
            _ = pts
            return np.isfinite(d)
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.gp import gp_Trsf
        from OCP.TopLoc import TopLoc_Location
        from OCP.TopoDS import TopoDS_Shape

        form = TopoDS_Shape()
        BRepTools.Read_s(form, s["datei"], BRep_Builder())
        L = np.asarray(s.get("lage") or np.eye(4), float).reshape(4, 4)
        tr = gp_Trsf()
        tr.SetValues(*[float(L[i, j]) for i in range(3) for j in range(4)])
        form = form.Moved(TopLoc_Location(tr))
        P, T, _ = raster.brep_netz(form, ablenkung=0.05)
        if art == "flaeche":
            d, _ = raster.naechstes_dreieck(self.mitten, P, T, float(s.get("dicke") or ts))
            return np.isfinite(d)
        G = self.G
        xs, ys, zs = G.achsen_mitte()
        innen = raster.innen_gitter(G.zu_druck(P), T, xs, ys, zs)
        return innen.reshape(-1)[self.akt_idx]


# -- Druckkennzahlen --------------------------------------------------------------------------------------------------


def druck_kennzahlen(P: np.ndarray, T: np.ndarray, R: np.ndarray, material: str, dichte: float | None
                     ) -> dict[str, Any]:
    from kevcad_kernel.druck.empfehlung import empfehle
    from kevcad_kernel.druck.regeln import MATERIALIEN
    from kevcad_kernel.druck.schaetzung import schaetze
    from kevcad_kernel.druck.vorschau_geo import _form_geometrie

    mat = MATERIALIEN.get(material)
    ue = float(mat.ueberhang_max) if mat is not None else 45.0
    geo = _form_geometrie(np.asarray(P, float), np.asarray(T, np.int64), np.asarray(R, float), ue, 0.2)
    geo["volumen"] = abs(float(np.einsum("ij,ij->i", P[T[:, 0]], np.cross(P[T[:, 1]], P[T[:, 2]])).sum() / 6.0))
    e = empfehle(geo, material, "tragend")["einstellungen"]
    s = schaetze(geo, e, material, dichte=dichte)
    return {"filament_g": s["g"], "druckzeit_min": round(s["zeit_s"] / 60.0, 1),
            "ueberhang_mm2": geo.get("ueberhang_flaeche"), "einstellungen": e, "hoehe_mm": geo["groesse"][2]}


def decken_kippen(p: np.ndarray, d: np.ndarray, R: np.ndarray, z_bett: float, grad: float = 3.0
                  ) -> tuple[np.ndarray, np.ndarray, int]:
    """Waagrechte Unterseiten über dem Bett (Normale innerhalb 1,8° nach unten) in flache Pyramiden teilen: je Dreieck
    ein Punkt in der Mitte, um wenige Hundertstel Millimeter ins Material versetzt, so dass die drei neuen Dreiecke um
    ``grad`` geneigt sind. Die Form ändert sich kaum (Versatz ≈ 5 % des Inkreises), aber die Druckprüfung sieht steile
    Überhänge statt einzelner Decken: Decken prüft sie mit Punktklassifikation in OCCT, bei Tausenden Dreiecksflächen
    dauert das Minuten (gemessen 156 s für vier Decken), Überhänge rechnet sie am Netz in Millisekunden."""
    q = p @ R.T
    # Punkte knapp am Bett genau aufs Bett (das Ausdünnen verschiebt sie um Hundertstel; dann erkennt die
    # Druckprüfung die Auflage nicht mehr und hält die ganze Unterseite für eine schwebende Decke)
    nah = np.abs(q[:, 2] - z_bett) < 0.08
    q[nah, 2] = z_bett
    p = q @ R
    a, b, c = q[d[:, 0]], q[d[:, 1]], q[d[:, 2]]
    n = np.cross(b - a, c - a)
    A2 = np.linalg.norm(n, axis=1)
    nz = n[:, 2] / np.maximum(A2, 1e-12)
    zc = (a[:, 2] + b[:, 2] + c[:, 2]) / 3.0
    sel = np.flatnonzero((nz < -0.9995) & (zc > z_bett + 0.3) & (A2 > 1e-9))
    if len(sel) == 0:
        return p, d, 0
    t = d[sel]
    A, B, C = q[t[:, 0]], q[t[:, 1]], q[t[:, 2]]
    m = (A + B + C) / 3.0
    kanten = np.stack([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1), np.linalg.norm(A - C, axis=1)], 1)
    hoehe = (A2[sel] / 3.0)[:, None] / np.maximum(kanten, 1e-12)  # Abstand der Mitte zu jeder Kante (2·(A/3)/|e|)
    dz = hoehe.max(axis=1) * math.tan(math.radians(grad))
    m[:, 2] += dz  # nach oben = ins Material (die Fläche zeigt nach unten)
    neu = np.arange(len(p), len(p) + len(sel))
    p2 = np.concatenate([p, m @ R])
    rest = np.ones(len(d), dtype=bool)
    rest[sel] = False
    d2 = np.concatenate([d[rest], np.stack([t[:, 0], t[:, 1], neu], 1), np.stack([t[:, 1], t[:, 2], neu], 1),
                         np.stack([t[:, 2], t[:, 0], neu], 1)])
    return p2, d2, int(len(sel))


def steg_min(innen: np.ndarray, h: float) -> float | None:
    """Dünnster Steg: zweifacher Abstand zur Oberfläche auf dem Mittelgrat (lokale Maxima), 5-%-Quantil."""
    from scipy.ndimage import distance_transform_edt, maximum_filter

    if not innen.any():
        return None
    d = distance_transform_edt(innen) * h
    grat = innen & (d >= maximum_filter(d, size=3)) & (d > 0.5 * h)
    werte = 2.0 * d[grat]
    if len(werte) == 0:
        return None
    return round(float(np.percentile(werte, 5)), 2)


# -- Rechnung ---------------------------------------------------------------------------------------------------------


def rechne(A: dict[str, Any], ablage: Path) -> dict[str, Any]:
    from kevcad_kernel.statik.festkoerper import loeser
    from kevcad_kernel.statik.festkoerper import netz as fk_netz
    from kevcad_kernel.statik.festkoerper import werkstoff as wk
    from kevcad_kernel.topologie import nachrechnen as nr
    from kevcad_kernel.topologie import oberflaeche as ob
    from kevcad_kernel.topologie.ergebnis import schreibe_brep, solid_aus_netz
    from kevcad_kernel.topologie.mehrgitter import hex8_ke
    from kevcad_kernel.topologie.simp import Optimierer, Ueberhangfilter

    t_start = time.perf_counter()
    ms: dict[str, float] = {}
    einst = einstellungen(**(A.get("einstellungen") or {}))
    ordner = ablage / A["schluessel"]
    ordner.mkdir(parents=True, exist_ok=True)
    melde(0.01, "Gitter aufbauen", phase="vorbereiten")
    B = Aufbau(A, einst)
    G = B.G
    ms.update(B.ms)
    faelle = A["faelle"]
    fest = B.lager(faelle)
    # Lasten, dann Schutzzonen (Lastflächen geschützt), dann Lasten ohne Punkt auf die Schutzzonen
    F_list, last_knoten = [], []
    for f in faelle:
        Fd, kn = B.lasten(f, None)
        F_list.append(Fd)
        last_knoten += kn
    passiv, zonen = B.schutz(last_knoten)
    w = A["werkstoff"]
    druckteil = A.get("oben") is not None or w.get("q") is not None
    C = wk.steifigkeit(w["E"], w["nu"], w.get("E_z") if druckteil else None, np.array([0.0, 0.0, 1.0]))
    KE = hex8_ke(C)
    behalten = float(einst["behalten"])
    anteil_schutz = float(passiv.sum()) / max(B.n, 1)
    if anteil_schutz > 0.9 * behalten:
        neu = min(0.95, anteil_schutz + 0.1 * (1 - anteil_schutz))
        B.hinweise.append(f"Die Schutzzonen sind schon {anteil_schutz * 100:.0f} % des Teils; behalten auf "
                          f"{neu * 100:.0f} % angehoben")
        behalten = neu
    r_mm = max(1.5 * G.h, B.steg_mm)  # Dichtefilter: kleinste Stegbreite etwa der Radius
    gestuetzt = Ueberhangfilter.ausgangsueberhaenge(B.aktiv) if einst["ueberhang"] else None
    ms["aufbau"] = round((time.perf_counter() - t_start) * 1000, 1)
    melde(0.05, f"{B.n} Voxel, h = {G.h:.2f} mm, {len(zonen)} Schutzzonen", phase="vorbereiten",
          voxel=B.n, h_mm=round(G.h, 3))
    # Schutzzonen als Netz für den Viewer
    ext = Erweiterung(B.aktiv)
    schutz_p, schutz_d = iso_netz(knoten_aus_zellen(passiv.astype(float)), 0.5, G, 12_000)
    schutz_datei = _npz(ordner / "schutz.npz", punkte=schutz_p.astype(np.float32),
                        dreiecke=schutz_d.astype(np.uint32)) if len(schutz_d) else None
    melde(0.06, "Schutzzonen", phase="vorbereiten", schutz=schutz_datei)

    # Vorher: Festkörper am Ausgangsteil
    T = {"werkstoff": w, "druckteil": druckteil, "schicht": A.get("oben"), "masse_kg": A["masse_kg"],
         "volumen": A["volumen"], "bmin": A["bmin"], "bmax": A["bmax"],
         "ausrichtungen": {}}
    vorher: list[dict[str, Any]] = []
    lastflaechen_vorher: list[list[Any]] = []
    t1 = time.perf_counter()
    try:
        melde(0.07, "Ausgangsteil nachrechnen (FEM)", phase="vorher")
        n0 = fk_netz.vernetze(A["brep"])
        N0 = loeser.Netz(n0["p"], n0["t"], n0["rand"], n0["flaeche"])
        for i, f in enumerate(faelle):
            kurz, felder, fl = nr.rechne(N0, n0["h"], T, f, B.nachbarn)
            pfad = _npz(ordner / f"vorher_{i}.npz", **felder)
            vorher.append({**kurz, "feld": pfad, "szenario": f["szenario"], "ziel": f["ziel"]})
            lastflaechen_vorher.append(fl)
    except Exception as exc:  # noqa: BLE001 - ohne Vergleich geht es weiter
        B.hinweise.append(f"Ausgangsteil nicht nachgerechnet: {type(exc).__name__}: {exc}")
    ms["vorher"] = round((time.perf_counter() - t1) * 1000, 1)

    # SIMP
    t2 = time.perf_counter()
    opt = Optimierer(B.aktiv, passiv, KE, 1.0, G.h, fest, F_list, behalten, r_mm / G.h,
                     ueberhang=einst["ueberhang"], gestuetzt=gestuetzt)
    zust = {"bild": 0.0, "nr": 0}
    max_iter = int(einst["iterationen"])

    def bei_iteration(it: int, e: dict[str, Any]) -> None:
        jetzt = time.perf_counter()
        dichte = None
        if jetzt - zust["bild"] >= BILD_S or it < 2:
            zust["bild"] = jetzt
            rk = knoten_aus_zellen(ext(opt.xh))
            p, d = iso_netz(rk, 0.5, G)
            if len(d):
                zust["nr"] += 1
                dichte = _npz(ordner / f"dichte_{zust['nr'] % 3}.npz", punkte=p.astype(np.float32),
                              dreiecke=d.astype(np.uint32))
        c0 = opt.verlauf[0]["c"] if opt.verlauf else e["c"]
        melde(0.12 + 0.6 * (it + 1) / max_iter, f"Iteration {it + 1}: Nachgiebigkeit {e['c'] / c0 * 100:.0f} %, "
              f"Volumen {e['volumen'] * 100:.0f} %", phase="optimieren", iteration=it + 1, c=round(e["c"], 6),
              volumen=round(e["volumen"], 4), grau=round(e["grau"], 4), dichte=dichte)

    lauf = opt.lauf(max_iter=max_iter, min_iter=min(25, max_iter), melde=bei_iteration, zeit_s=ZEIT_S)
    ms["optimieren"] = round((time.perf_counter() - t2) * 1000, 1)
    ms["je_iteration"] = round(ms["optimieren"] / max(lauf["iterationen"], 1), 1)
    if lauf["grund"] == "zeit":
        B.hinweise.append(f"Zeitgrenze erreicht: nach {lauf['iterationen']} Iterationen beendet")

    # Oberfläche
    t3 = time.perf_counter()
    melde(0.75, "Oberfläche aus der Dichte", phase="oberflaeche")
    from scipy.ndimage import label, map_coordinates

    rho = np.where(B.aktiv, opt.xh, 0.0)
    lo_t, hi_t = 0.02, 0.98
    ziel_n = behalten * B.n
    for _ in range(40):
        t_mid = 0.5 * (lo_t + hi_t)
        if float((rho > t_mid).sum()) > ziel_n:
            lo_t = t_mid
        else:
            hi_t = t_mid
    schwelle = 0.5 * (lo_t + hi_t)
    # lose Inseln weg: nur, was mit einem Lager oder einer Last zusammenhängt
    fest_el = np.zeros(G.ne, dtype=bool)
    nx, ny, nz = G.ne
    knm = np.zeros(int(np.prod(G.nn)), dtype=bool)
    knm[B.fest_knoten] = True
    for kn in last_knoten:
        knm[kn] = True
    knm = knm.reshape(G.nn)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                fest_el |= knm[dx:dx + nx, dy:dy + ny, dz:dz + nz]
    lab, nlab = label(rho > schwelle, structure=np.ones((3, 3, 3)))
    behalte = np.unique(lab[fest_el & (lab > 0)])
    inseln = int(nlab - len(behalte))
    if inseln > 0:
        weg = (lab > 0) & ~np.isin(lab, behalte)
        rho = np.where(weg, 0.0, rho)
        B.hinweise.append(f"{inseln} lose {'Insel' if inseln == 1 else 'Inseln'} ohne Verbindung zu Lager oder Last "
                          "entfernt")
    # Feld auf dem halb so großen Gitter: max(Abstand zum Teil, Dichte)
    from kevcad_kernel.topologie import raster

    hc = 0.5 * G.h
    rand = 2
    nc = tuple(2 * n + 1 + 2 * rand for n in G.ne)
    oc = G.o - rand * hc
    xs = oc[0] + np.arange(nc[0]) * hc
    ys = oc[1] + np.arange(nc[1]) * hc
    zs = oc[2] + np.arange(nc[2]) * hc
    Pd = G.zu_druck(B.Pw)
    innen = raster.innen_gitter(Pd, B.Tw, xs, ys, zs)

    def punkte_c(idx: np.ndarray) -> np.ndarray:
        ijk = np.stack(np.unravel_index(idx, nc), axis=1)
        return G.zu_welt(oc[None, :] + ijk * hc)

    band = 2.5 * hc
    phi_teil = raster.abstand_band(innen, punkte_c, B.Pw, B.Tw, band)
    rk = knoten_aus_zellen(ext(rho))
    ii, jj, kk = np.meshgrid((np.arange(nc[0]) - rand) / 2.0, (np.arange(nc[1]) - rand) / 2.0,
                             (np.arange(nc[2]) - rand) / 2.0, indexing="ij")
    rho_c = map_coordinates(rk, [ii, jj, kk], order=1, mode="nearest")
    # Schwelle auf dem feinen Gitter neu, damit das Volumen des Körpers den Anteil trifft (die Interpolation glättet)
    im_teil = phi_teil < 0
    n_teil = float(im_teil.sum())
    lo_t, hi_t = 0.02, 0.98
    for _ in range(40):
        t_mid = 0.5 * (lo_t + hi_t)
        if float((im_teil & (rho_c > t_mid)).sum()) > behalten * n_teil:
            lo_t = t_mid
        else:
            hi_t = t_mid
    schwelle = 0.5 * (lo_t + hi_t)
    skala = 2.0 * r_mm
    phi_dichte = (schwelle - rho_c) * skala
    phi = np.maximum(phi_teil, phi_dichte)
    p, d = ob.marching_cubes(phi, hc, tuple(oc))
    if len(d) == 0:
        raise ValueError("Die Optimierung hat keinen Körper übrig gelassen")
    # nur die neuen Schnittflächen glätten, die Flächen des Teils bleiben
    u = (p - oc[None, :]) / hc
    a_t = map_coordinates(phi_teil, u.T, order=1, mode="nearest")
    a_d = map_coordinates(phi_dichte, u.T, order=1, mode="nearest")
    beweglich = a_d >= a_t - 1e-9
    p = ob.glaetten(p, d, beweglich, schritte=8)
    pw = G.zu_welt(p)
    roh = len(d)
    pw, d = ausduennen(pw, d, ZIEL_DREIECKE_FEIN if einst["fein"] else ZIEL_DREIECKE)
    pw, d, gekippt = decken_kippen(pw, d, G.R, float(G.o[2]))
    offen = ob.offene_kanten(d)
    if offen:
        B.hinweise.append(f"Oberfläche hat {offen} offene Kanten")
    vol = ob.volumen(pw, d)
    fl = ob.flaeche(pw, d)
    dicke = steg_min(phi < 0, hc)
    ms["oberflaeche"] = round((time.perf_counter() - t3) * 1000, 1)
    # Körper in Teilkoordinaten (wie die Form in model.py)
    t4 = time.perf_counter()
    L = np.asarray(A["lage"], float).reshape(4, 4)
    Li = np.linalg.inv(L)
    p_teil = pw @ Li[:3, :3].T + Li[:3, 3]
    solid = solid_aus_netz(p_teil, d)
    brep = ordner / "ergebnis.brep"
    schreibe_brep(solid, brep)
    netz_datei = _npz(ordner / "ergebnis.npz", punkte=pw.astype(np.float32), dreiecke=d.astype(np.uint32),
                      punkte_teil=p_teil.astype(np.float64))
    ms["koerper"] = round((time.perf_counter() - t4) * 1000, 1)
    melde(0.8, f"Körper: {len(d)} Dreiecke, {vol / 1000:.1f} cm³", phase="koerper", netz=netz_datei)

    # Nachher: Festkörper am Ergebnis
    t5 = time.perf_counter()
    nachher: list[dict[str, Any]] = []
    try:
        melde(0.82, "Ergebnis nachrechnen (FEM)", phase="nachher")
        h_fem = nr.netzgroesse(vol, fl, B.groesse)
        n1 = nr.vernetze_oberflaeche(pw, d, h_fem)
        N1 = loeser.Netz(n1["p"], n1["t"])
        T1 = {**T, "volumen": vol, "masse_kg": A["masse_kg"] * vol / max(A["volumen"], 1e-9)}
        for i, f in enumerate(faelle):
            kurz, felder, _ = nr.rechne(N1, h_fem, T1, f, B.nachbarn,
                                        lastflaechen_vorher[i] if i < len(lastflaechen_vorher) else None,
                                        direkt=True, zugabe=0.25)
            pfad = _npz(ordner / f"nachher_{i}.npz", **felder)
            nachher.append({**kurz, "feld": pfad, "szenario": f["szenario"], "ziel": f["ziel"]})
    except Exception as exc:  # noqa: BLE001
        B.hinweise.append(f"Ergebnis nicht nachgerechnet: {type(exc).__name__}: {exc}")
    ms["nachher"] = round((time.perf_counter() - t5) * 1000, 1)

    # Druck: Filament, Zeit, Überhänge vorher und nachher; Druckprüfung am Ergebnis
    t6 = time.perf_counter()
    melde(0.92, "Druckprüfung und Schätzung", phase="druck")
    material = A.get("material_id") or "petg"
    dichte = None
    if A.get("masse_kg") and A.get("volumen"):
        dichte = float(A["masse_kg"]) * 1e6 / float(A["volumen"])  # g/cm³
    druck_v, druck_n, pruef = {}, {}, None
    try:
        druck_v = druck_kennzahlen(B.Pw, B.Tw, B.R, material, dichte)
        druck_n = druck_kennzahlen(pw, d, B.R, material, dichte)
    except Exception as exc:  # noqa: BLE001
        B.hinweise.append(f"Druckschätzung fehlgeschlagen: {type(exc).__name__}: {exc}")
    try:
        if len(d) > 40_000:
            raise ValueError(f"Netz mit {len(d)} Dreiecken zu groß für die Druckprüfung")
        from build123d import Solid

        from kevcad_kernel.druck.pruefung import pruefe_druckteil

        welt = solid_aus_netz(pw, d)
        unten = tuple(float(c) for c in -B.R[2])
        erg = pruefe_druckteil(Solid(welt), material, ausrichtung=unten)
        pruef = {"zusammenfassung": erg["zusammenfassung"], "ok": erg["ok"],
                 "hinweise": [{k: h.get(k) for k in ("art", "schwere", "text")} for h in erg["hinweise"]][:12],
                 "kennzahlen": {k: erg["kennzahlen"].get(k) for k in ("stuetzflaeche_mm2", "hoehe_mm")}}
    except Exception as exc:  # noqa: BLE001
        B.hinweise.append(f"Druckprüfung am Ergebnis fehlgeschlagen: {type(exc).__name__}: {exc}")
    ms["druck"] = round((time.perf_counter() - t6) * 1000, 1)

    def kz(stufe: list[dict[str, Any]], volumen: float, druck: dict[str, Any], steg: float | None) -> dict[str, Any]:
        massg = volumen / 1000.0 * (dichte or 1.27)
        out = {"volumen_mm3": round(volumen, 1), "masse_g": round(massg, 1),
               "filament_g": druck.get("filament_g"), "druckzeit_min": druck.get("druckzeit_min"),
               "ueberhang_mm2": druck.get("ueberhang_mm2"), "steg_min_mm": steg}
        if stufe:
            s = min(stufe, key=lambda x: (x.get("sicherheit") or math.inf) / max(float(x.get("ziel") or 1), 1e-9))
            out.update(nr.kennzahlen(s, float(s.get("ziel") or 4.0)))
            out["szenario"] = s.get("szenario")
        return out

    kz_v = kz(vorher, float(A["volumen"]), druck_v, None)
    kz_n = kz(nachher, vol, druck_n, dicke)
    ersparnis = {"volumen_prozent": round(100 * (1 - vol / max(float(A["volumen"]), 1e-9)), 1)}
    for k in ("masse_g", "filament_g", "druckzeit_min"):
        if kz_v.get(k) and kz_n.get(k) is not None:
            ersparnis[k] = round(float(kz_v[k]) - float(kz_n[k]), 1)
    steg_mm = B.steg_mm
    if dicke is not None and dicke < steg_mm * 0.8:
        B.hinweise.append(f"Dünnster Steg {dicke:.1f} mm unter der Vorgabe {steg_mm:.1f} mm: steg erhöhen oder "
                          "fein=True")
    ms["gesamt"] = round((time.perf_counter() - t_start) * 1000, 1)
    return {
        "stand": "done", "version": VERSION, "teil": A["teil"], "schluessel": A["schluessel"],
        "lastfall": A["lastfall"], "szenarien": [f["szenario"] for f in faelle], "einstellungen": einst,
        "behalten_wirksam": round(behalten, 4),
        "gitter": {**G.kurz(), "voxel": B.n, "knoten": int(np.prod(G.nn)), "radius_mm": round(r_mm, 3),
                   "stufen": opt.mg.stufen, "schwelle": round(schwelle, 4)},
        "schutz": {"zonen": zonen, "anteil": round(anteil_schutz, 4), "netz": schutz_datei},
        "optimierung": {**lauf, "verlauf": [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in e.items()}
                                            for e in opt.verlauf],
                        "cg_gesamt": opt.mg.statistik["iterationen"]},
        "kennzahlen": {"vorher": kz_v, "nachher": kz_n, "ersparnis": ersparnis},
        "faelle": {"vorher": [{k: v for k, v in x.items()} for x in vorher],
                   "nachher": [{k: v for k, v in x.items()} for x in nachher]},
        "druckpruefung": pruef,
        "netz": {"dreiecke": int(len(d)), "dreiecke_roh": int(roh), "punkte": int(len(pw)), "offen": int(offen),
                 "flaeche_mm2": round(fl, 1), "decken_gekippt": gekippt},
        "dateien": {"brep": str(brep), "netz": netz_datei, "schutz": schutz_datei,
                    "vorher": [x.get("feld") for x in vorher], "nachher": [x.get("feld") for x in nachher]},
        "hinweise": B.hinweise, "grenzen": list(GRENZEN), "ms": ms,
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("Aufruf: python -m kevcad_kernel.topologie.prozess auftrag.json ergebnis.json", file=sys.stderr)
        return 2
    A = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    ablage = speicher()
    out: dict[str, Any]
    fertig = ablage / A["schluessel"] / "ergebnis.json"
    alt = None
    if fertig.exists() and not A.get("neu"):
        try:
            alt = json.loads(fertig.read_text(encoding="utf-8"))
            if alt.get("version") != VERSION or not Path(alt["dateien"]["brep"]).exists():
                alt = None
        except (OSError, ValueError, KeyError):
            alt = None
    if alt is not None:
        out = {**alt, "aus_speicher": True}
        melde(1.0, "aus dem Zwischenspeicher", phase="fertig")
    else:
        try:
            out = rechne(A, ablage)
            out["aus_speicher"] = False
            tmp = fertig.with_name("ergebnis.json.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, default=float), encoding="utf-8")
            os.replace(tmp, fertig)
        except Exception as exc:  # noqa: BLE001
            out = {"stand": "failed", "meldung": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc(limit=8), "teil": A.get("teil")}
        melde(1.0, "fertig", phase="fertig")
    tmp = argv[1] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, default=float)
    os.replace(tmp, argv[1])
    return 0


if __name__ == "__main__":
    _ = hashlib
    raise SystemExit(main())

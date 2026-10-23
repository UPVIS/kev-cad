"""S4-Prozess: ``python -m kevcad_kernel.statik.ccx.prozess <auftrag.json> <ergebnis.json>``.

Wie der FEM-Prozess der Stufe 3 (eigener Prozess, Fortschritt als JSON-Zeilen, Ergebnis als Datei,
Zwischenspeicher je Fall), nur rechnet CalculiX (eigenes Programm, GPL) statt scikit-fem:

1. Netz des Teils wie in S3 (Gmsh, Tetraeder, P2-Topologie aus scikit-fem: dieselben Knoten und Lasten), daraus C3D10.
2. Kontaktkörper (zugeschnittene Nachbarn) ebenso vernetzt: Stäbe, die Last einleiten, elastisch mit weichen
   Halte-Federn gegen Starrkörperbewegungen (sie tragen fast nichts; tragen sie doch, rutscht der Körper), starre
   Lager-Körper mit festen Knoten.
3. Lager: feste Verbindungen (Schraube, Kleben, Formschluss) und alles ohne Kontakt wie S3 fest eingespannt; Kontakt
   als Paar Fläche zu Fläche (Teil = Slave, Partner = Master), Strafverfahren, Coulomb-Reibung.
4. Lasten wie S3 (RBE3-Verteilung, konsistente Knotenkräfte); Lasten eines Stabs mit Kontakt an den Schnittflächen des
   Stabs (Kräfte beider Seiten aus dem Stabwerk), Klemmschrauben als Kräftepaar Kopf ↔ Einsatz im ersten Schritt.
5. Schritte: Vorspannung (Klemmung) → Last → Entlasten (bleibende Verformung, nur plastisch) und in einem zweiten
   Lauf die Laststeigerung bis zur Traglast (Grenzdehnung, Schichtfuge, Rutschen oder Kollaps; ccx wird beendet,
   sobald die Verschiebungen davonlaufen). Beulen als eigener linearer Lauf (*BUCKLE).
6. Auswertung: Sicherheit wie S3 aus den Spannungen unter Last (elastisch-plastisch, mit Kontakt), plastische
   Dehnung, bleibende Verformung, Kontaktdruck, Klaffen, Schlupf, Traglastfaktor, Beulfaktor; Feld für STATICS_FIELD
   mit Zusatzwerten (Kontaktdruck, plastische Dehnung, Klaffen, Schlupf).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.statik.ccx import VERSION, GRENZEN_S4
from kevcad_kernel.statik.ccx import frd as fr
from kevcad_kernel.statik.ccx import lauf
from kevcad_kernel.statik.ccx.deck import Deck, Koerper, Kontakt, Schritt
from kevcad_kernel.statik.festkoerper.prozess import _lastflaeche, _schreibe_npz, lies_fall, melde, speicher

try:  # Lagerarten und Flächenlasten der Simulation (Stufe 3, Simulation 2); ältere Stände kennen nur feste Lager
    from kevcad_kernel.statik.festkoerper.prozess import _flaechen_facetten, _gehalten, _lager_art
except ImportError:  # pragma: no cover
    _flaechen_facetten = None

    def _lager_art(nb: dict[str, Any]) -> str:
        return "fest"

    def _gehalten(nb: dict[str, Any]) -> list[list[float]]:
        return []

ZUSATZ = ("kontaktdruck", "plast_dehnung", "klaffen", "schlupf")
FEDER_ANTEIL = 1e-6  # Halte-Federn: Gesamtsteifigkeit mindestens Anteil · E · Größe des Körpers
FEDER_LAST = 0.02  # … und mindestens 2 % der Last je mm (bei 0,25 mm Weg tragen sie 0,5 % der Last)
ANFANG_KONTAKT = 0.002  # erstes Inkrement mit Kontakt: 0,2 % der Last (höchstens 0,1 mm Weg auf den Federn)
ANFANG_KLEMMUNG = 0.05  # nach einer Vorspannung (Klemmung) liegt der Körper an
RUTSCH_ANTEIL = 0.05  # tragen die Federn mehr als 5 % der Last, hält der Kontakt den Körper nicht
KONTAKT_FAKTOR = 2.0  # Druck-Strafsteifigkeit = Faktor · E (weicherer Werkstoff) je mm
HAFT_TEILER = 50.0  # Haftsteifigkeit = Druck-Strafsteifigkeit / Teiler
SUCH_MM = 0.3  # Kontaktzone: zugewandte Randflächen bis so weit vom Partner (dazu die Toleranz des Paars)
TRAG_MAX = 50.0
SCHLUPF_MM = 0.1  # ein frei gelagerter Körper, der sich so weit mehr bewegt als linear erwartet, rutscht
SPRUNG = ("rutschen",)  # Kriterien, die springen statt zu wachsen
TRAG_GENAU = 0.02  # Traglast: eine Klammer schmaler als 2 % des Faktors genügt
TRAG_LAEUFE = 3  # höchstens so viele Läufe der Laststeigerung (grob, dann in der Klammer fein)
TETRA_PLASTISCH = 0.95  # Abminderung der Traglast aus Fließen (C3D10 voll plastisch zu steif, PLAN-STATIK T42)


# ----------------------------------------------------------------------------------------------------------------------
# Kontaktzonen


def zugewandt(punkte: np.ndarray, normalen: np.ndarray, pos: np.ndarray, tri: np.ndarray, tol: float,
              cos_max: float = -0.5) -> np.ndarray:
    """Indizes der Randflächen (Mitte ``punkte``, äußere Normale ``normalen``), die höchstens ``tol`` vom Netz (pos,
    tri) entfernt sind und dem nächsten Dreieck zugewandt (Normalen gegeneinander, cos < ``cos_max``). Ohne die
    Richtungsprüfung kämen Stirn- und Innenflächen dazu (etwa die Innenwand eines Rohrs), die nie berühren, aber
    CalculiX mit Kontaktelementen bremsen."""
    from scipy.spatial import cKDTree

    from kevcad_kernel.statik.festkoerper.kontakt import STUECK, punkt_dreieck

    P = np.asarray(punkte, float)
    if len(P) == 0 or len(tri) == 0:
        return np.zeros(0, dtype=np.int64)
    Tr = np.asarray(pos, float)[np.asarray(tri, dtype=np.int64)]
    nt = np.cross(Tr[:, 1] - Tr[:, 0], Tr[:, 2] - Tr[:, 0])
    nt /= np.maximum(np.linalg.norm(nt, axis=1), 1e-300)[:, None]
    mitte = Tr.mean(axis=1)
    radius = np.max(np.linalg.norm(Tr - mitte[:, None, :], axis=2), axis=1) + tol
    listen = cKDTree(P).query_ball_point(mitte, radius)
    laengen = np.fromiter((len(x) for x in listen), dtype=np.int64, count=len(listen))
    if laengen.sum() == 0:
        return np.zeros(0, dtype=np.int64)
    ti = np.repeat(np.arange(len(Tr)), laengen)
    pi = np.fromiter((i for x in listen for i in x), dtype=np.int64, count=int(laengen.sum()))
    best = np.full(len(P), np.inf)
    best_t = np.full(len(P), -1, dtype=np.int64)
    for s0 in range(0, len(ti), STUECK):
        a, b = ti[s0:s0 + STUECK], pi[s0:s0 + STUECK]
        dd = punkt_dreieck(P[b], Tr[a, 0], Tr[a, 1], Tr[a, 2])
        o = np.lexsort((dd, b))  # je Punkt das nächste Dreieck zuerst
        b_o, a_o, d_o = b[o], a[o], dd[o]
        erst = np.ones(len(b_o), dtype=bool)
        erst[1:] = b_o[1:] != b_o[:-1]
        bb, aa, dmin = b_o[erst], a_o[erst], d_o[erst]
        besser = dmin < best[bb]
        best[bb[besser]] = dmin[besser]
        best_t[bb[besser]] = aa[besser]
    ok = np.isfinite(best) & (best <= tol)
    idx = np.where(ok)[0]
    cos = np.einsum("ij,ij->i", np.asarray(normalen, float)[idx], nt[best_t[idx]])
    return idx[cos < cos_max]


# ----------------------------------------------------------------------------------------------------------------------
# Netz → C3D10


class Teilnetz:
    """Netz eines Körpers (P2 aus S3) mit Kanten-Index und Umrechnung P2-Lastvektor → Knotenkräfte."""

    def __init__(self, N: Any, km: tuple[np.ndarray, np.ndarray] | None = None) -> None:
        self.N = N
        e = np.sort(N.mesh.edges, axis=0).astype(np.int64)
        self.ekey = e[0] * N.n + e[1]
        self.eord = np.argsort(self.ekey)
        mid = 0.5 * (N.p[N.mesh.edges[0]] + N.p[N.mesh.edges[1]])
        if km is not None and len(km[0]):  # Kantenmitten auf der Geometrie (Gmsh zweiter Ordnung)
            paare, pos = np.asarray(km[0], dtype=np.int64), np.asarray(km[1], float)
            k = self.kanten(paare[:, 0], paare[:, 1])
            ok = np.all(np.sort(N.mesh.edges[:, k].T, axis=1) == paare, axis=1)
            # nur kleine Verschiebungen übernehmen (Schutz gegen falsch zugeordnete Knoten)
            laenge = np.linalg.norm(N.p[paare[:, 0]] - N.p[paare[:, 1]], axis=1)
            ok &= np.linalg.norm(pos - mid[k], axis=1) < 0.25 * laenge
            mid[k[ok]] = pos[ok]
        self.knoten = np.vstack([N.p, mid])
        el = np.zeros((len(N.t), 10), dtype=np.int64)
        el[:, :4] = N.t
        el[:, 4:] = N.n + N.kante.T
        self.elemente = el

    def kanten(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        k = lo * self.N.n + hi
        return self.eord[np.searchsorted(self.ekey[self.eord], k)]

    def flaechenknoten(self, facetten: np.ndarray) -> np.ndarray:
        """Alle Knoten (Ecken und Kantenmitten) der Randdreiecke ``facetten``."""
        if len(facetten) == 0:
            return np.zeros(0, dtype=np.int64)
        f = self.N.rand[facetten]
        mitten = [self.kanten(f[:, i], f[:, j]) + self.N.n for i, j in ((0, 1), (1, 2), (0, 2))]
        return np.unique(np.concatenate([f.reshape(-1)] + mitten))

    def kraefte(self, f: np.ndarray) -> np.ndarray:
        """P2-Lastvektor (scikit-fem) → Knotenkräfte (n_knoten, 3)."""
        N = self.N
        F = np.zeros((len(self.knoten), 3))
        for c in range(3):
            F[:N.n, c] = f[N.basis.nodal_dofs[c]]
            F[N.n:, c] = f[N.basis.edge_dofs[c]]
        return F

    def oberflaeche(self, K: Koerper, facetten: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        el = self.N.mesh.f2t[0, self.N.rand_index[facetten]]
        return el, K.flaechen(el, self.N.rand[facetten])


def _netz_koerper(info: dict[str, Any], h_teil: float, ablage: Path) -> dict[str, Any]:
    """Kontaktkörper vernetzen (Zwischenspeicher je Körper und Netzgröße). Starre Körper gröber."""
    from kevcad_kernel.statik.festkoerper import netz

    starr = info["rolle"] == "lager"
    key = hashlib.sha1(json.dumps({"v": VERSION, "k": info["schluessel"], "box": info["box"], "starr": starr,
                                   "h": round(h_teil, 3), "verfeinern": info.get("verfeinern"),
                                   "h_mm": info.get("h_mm"), "km": True}, sort_keys=True).encode()).hexdigest()[:20]
    pfad = ablage / "netze" / f"k{key}.npz"
    if pfad.exists():
        try:
            with np.load(pfad) as z:
                return {k: z[k] for k in z.files} | {"h": float(z["h"])}
        except Exception:  # noqa: BLE001
            pass
    # elastische Körper so fein wie das Teil (Kontakt Fläche zu Fläche mag ähnliche Netze), starre gröber
    h = info.get("h_mm") or max(h_teil, 2.0) * (1.5 if starr else 1.0)
    n = netz.vernetze(info["brep"], h_vorgabe=h, verfeinern=info.get("verfeinern"), kantenmitten=True)
    _schreibe_npz(pfad, p=n["p"], t=n["t"], rand=n["rand"], flaeche=n["flaeche"], h=np.float64(n["h"]),
                  km_paare=n.get("km_paare", np.zeros((0, 2), np.int64)), km_pos=n.get("km_pos", np.zeros((0, 3))))
    return n


def _gleichungen(tn: "Teilnetz", d: Deck, fest_k: np.ndarray, gleit: list[tuple[np.ndarray, list[list[float]]]],
                 gelenk: list[np.ndarray]) -> list[list[tuple[int, int, float]]]:
    """Zwangsbedingungen des Teils (Körper 0) als lineare Gleichungen Σ c · u = 0 für CalculiX (*EQUATION): gleitende
    Lager je Knoten und gehaltener Richtung h (h · u = 0), gelenkige Lager als Zeilen der Stufe 3 (P2-Freiheitsgrade
    → Knoten). Der erste Term jeder Gleichung ist abhängig: je Gleichung ein anderer, nicht fester Freiheitsgrad."""
    N = tn.N
    fest = set(int(k) for k in fest_k)
    benutzt: set[tuple[int, int]] = set()
    out: list[list[tuple[int, int, float]]] = []
    for knoten, H in gleit:
        for k in knoten:
            k = int(k)
            if k in fest:
                continue
            for h in H:
                h = np.asarray(h, float)
                if float(np.linalg.norm(h)) < 1e-12:
                    continue
                order = [int(c) for c in np.argsort(-np.abs(h)) if abs(h[c]) > 1e-9 and (k, int(c)) not in benutzt]
                if not order:
                    continue
                dep = order[0]
                benutzt.add((k, dep))
                g = int(d.global_knoten(0, np.array([k]))[0])
                terme = [(g, dep + 1, float(h[dep]))] + [(g, c + 1, float(h[c])) for c in range(3)
                                                          if c != dep and abs(h[c]) > 1e-12]
                out.append(terme)
    if gelenk:
        ort = np.full(N.N, -1, dtype=np.int64)
        richtung = np.zeros(N.N, dtype=np.int64)
        for c in range(3):
            ort[N.basis.nodal_dofs[c]] = np.arange(N.n)
            richtung[N.basis.nodal_dofs[c]] = c
            ort[N.basis.edge_dofs[c]] = N.n + np.arange(N.basis.edge_dofs.shape[1])
            richtung[N.basis.edge_dofs[c]] = c
        for zeile in gelenk:
            z = np.asarray(zeile, float).reshape(-1)
            nz = np.flatnonzero(np.abs(z) > 1e-12 * max(float(np.abs(z).max()), 1e-300))
            if not len(nz):
                continue
            kand = [int(i) for i in nz[np.argsort(-np.abs(z[nz]))]
                    if int(ort[i]) not in fest and (int(ort[i]), int(richtung[i])) not in benutzt]
            if not kand:
                continue
            dep = kand[0]
            benutzt.add((int(ort[dep]), int(richtung[dep])))
            g = d.global_knoten(0, ort[nz])
            skala = 1.0 / float(np.abs(z[dep]))
            terme = [(int(d.global_knoten(0, np.array([ort[dep]]))[0]), int(richtung[dep]) + 1, float(z[dep] * skala))]
            terme += [(int(gi), int(richtung[i]) + 1, float(z[i] * skala)) for gi, i in zip(g, nz) if i != dep]
            out.append(terme)
    return out


def _netz_teil(T: dict[str, Any], fein: bool, ablage: Path) -> tuple[dict[str, Any], bool]:
    """Netz des Teils wie Stufe 3 (gleiche Größe und Ecken), dazu die Kantenmitten auf der Geometrie (eigener
    Zwischenspeicher, damit Stufe 3 ihr Netz behält)."""
    from kevcad_kernel.statik.festkoerper import netz

    schl = {"v": VERSION, "teil": T["schluessel_teil"], "fein": fein, "h": T.get("h_mm"), "km": True,
            "verfeinern": T.get("verfeinern"),
            "max": [netz.MAX_TET, netz.MAX_TET_FEIN, netz.WAND_ANTEIL, netz.KRUEMMUNG]}
    pfad = ablage / "netze" / f"s4{hashlib.sha1(json.dumps(schl, sort_keys=True).encode()).hexdigest()[:18]}.npz"
    if pfad.exists():
        try:
            with np.load(pfad) as z:
                return {k: z[k] for k in z.files} | {"h": float(z["h"])}, True
        except Exception:  # noqa: BLE001
            pass
    n = netz.vernetze(T["brep"], fein=fein, h_vorgabe=T.get("h_mm"), verfeinern=T.get("verfeinern"),
                      kantenmitten=True)
    _schreibe_npz(pfad, p=n["p"], t=n["t"], rand=n["rand"], flaeche=n["flaeche"], h=np.float64(n["h"]),
                  km_paare=n.get("km_paare", np.zeros((0, 2), np.int64)), km_pos=n.get("km_pos", np.zeros((0, 3))))
    return n, False


def _km(n: dict[str, Any]) -> tuple[np.ndarray, np.ndarray] | None:
    if n.get("km_paare") is None or not len(n["km_paare"]):
        return None
    return np.asarray(n["km_paare"]), np.asarray(n["km_pos"])


def _werkstoff_deck(w: dict[str, Any], fliess: dict[str, Any] | None, schicht: Any, druckteil: bool) -> dict[str, Any]:
    out = {"E": float(w["E"]), "nu": float(w["nu"])}
    if fliess:
        out["plastisch"] = fliess["kurve"]
    elif druckteil and w.get("E_z") and schicht is not None:
        out["E_z"] = float(w["E_z"])
        out["normale"] = list(schicht)
    return out


# ----------------------------------------------------------------------------------------------------------------------
# Auswertung


def _voigt(S: np.ndarray) -> np.ndarray:
    """ccx (SXX SYY SZZ SXY SYZ SZX) → Voigt wie S3 (xx, yy, zz, yz, xz, xy)."""
    return np.stack([S[:, 0], S[:, 1], S[:, 2], S[:, 4], S[:, 5], S[:, 3]], axis=1)


def _index(s: np.ndarray, T: dict[str, Any], f_mises: float) -> tuple[np.ndarray, np.ndarray]:
    """(Index, Kriterium 0 Mises / 1 Schicht / 2 quer unbekannt) je Knoten wie S3."""
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    w = T["werkstoff"]
    i_m, i_s = wk.index(s, f_mises, w.get("q"), T.get("schicht") if T["druckteil"] else None)
    if T["druckteil"] and i_s is None:
        if T.get("fliess"):  # Fließgrenze ist schon q · f
            return i_m, np.full(len(i_m), 2)
        return i_m / float(w.get("q") or 0.5), np.full(len(i_m), 2)
    if i_s is not None:
        return np.maximum(i_m, i_s), np.where(i_s > i_m, 1, 0)
    return i_m, np.zeros(len(i_m), dtype=np.int64)


def _flaeche_je_knoten(N: Any, sv: np.ndarray) -> np.ndarray:
    """Ein Drittel der angrenzenden Randdreiecke je Eckknoten (für Kraft und Fläche aus Knotenwerten)."""
    a = np.zeros(N.n)
    np.add.at(a, N.rand.reshape(-1), np.repeat(N.rand_flaeche_mm2 / 3.0, 3))
    return a


# ----------------------------------------------------------------------------------------------------------------------
# Ein Fall


class Fall:
    def __init__(self, T: dict[str, Any], f: dict[str, Any], opt: dict[str, Any], N: Any, n: dict[str, Any],
                 beruehrt: dict[str, np.ndarray], zone: dict[str, np.ndarray], koerper_netze: dict[str, Any]) -> None:
        self.T, self.f, self.opt, self.N, self.n = T, f, opt, N, n
        self.beruehrt, self.zone, self.kn = beruehrt, zone, koerper_netze
        self.hinweise: list[str] = list(f.get("hinweise") or [])
        self.groesse = float(np.max(np.asarray(T["bmax"]) - np.asarray(T["bmin"])))
        self.u_last: dict[str, float] = {}  # Verschiebung der frei gelagerten Körper bei λ = 1 (Lauf 1)

    # -- Aufbau ----------------------------------------------------------------------------------------------------

    def baue(self, art: str, stufen: list[tuple[float, float, float]] | None = None) -> dict[str, Any]:
        """Deck für ``art`` = "last" (Vorspannung, Last, Entlasten), "traglast" (Vorspannung, dann je Stufe
        (λ_von, λ_bis, größtes Inkrement als Anteil) eine Rampe der Last) oder "beulen" (linear, S3-Lager, *BUCKLE)."""
        T, f, opt, N = self.T, self.f, self.opt, self.N
        kontakt = opt["kontakt"] and art != "beulen"
        d = Deck()
        tn = Teilnetz(N, _km(self.n))
        K0 = Koerper(T["name"], tn.knoten, tn.elemente,
                     _werkstoff_deck(T["werkstoff"], T.get("fliess") if art != "beulen" else None, T.get("schicht"),
                                     T["druckteil"]))
        d.add(K0)
        netze = {0: tn}
        koerper_index: dict[str, int] = {}
        verb = T.get("verbindungen") or {}

        def ist_kontakt(x: str) -> bool:
            return kontakt and (verb.get(x) or {}).get("art") == "kontakt" and x in self.kn

        def koerper(x: str) -> int:
            if x in koerper_index:
                return koerper_index[x]
            info, nx, km = self.kn[x]
            tx = Teilnetz(nx, km)
            if info["rolle"] == "lager":
                w = {"E": float(T["werkstoff"]["E"]) * 100, "nu": 0.3}
            else:
                w = _werkstoff_deck(info["werkstoff"], info.get("fliess") if art != "beulen" else None, None, False)
            i = d.add(Koerper(x, tx.knoten, tx.elemente, w))
            netze[i] = tx
            koerper_index[x] = i
            return i

        fest_teil: list[np.ndarray] = []
        gleit: list[tuple[np.ndarray, list[list[float]]]] = []
        gelenk: list[np.ndarray] = []
        self.zwang_gehalten = False
        paare: list[tuple[str, int]] = []
        for x in f.get("lager") or []:
            if ist_kontakt(x) and self.kn[x][0]["rolle"] == "lager":
                i = koerper(x)
                d.fest.append(d.global_knoten(i, np.arange(len(netze[i].knoten))))
                paare.append((x, i))
            else:
                # Lagerarten der Simulation (ausdrücklich gesetzte Lager): fest, gleitend (gehaltene Richtungen je
                # Knoten), gelenkig (RBE3-artig: mittlere Verschiebung und Drehung um die gehaltenen Achsen null);
                # in CalculiX als *EQUATION, wie die Zwangsbedingungen der Stufe 3
                sel = self.beruehrt.get(x, np.zeros(0, dtype=np.int64))
                nb = T["nachbarn"].get(x, {})
                lart = _lager_art(nb)
                if lart == "gleitend" and len(sel):
                    gleit.append((tn.flaechenknoten(sel), _gehalten(nb)))
                elif lart == "gelenkig" and len(sel):
                    gelenk += N.gelenk_zeilen(sel, nb.get("drehachsen") or [])
                else:
                    fest_teil.append(tn.flaechenknoten(sel))
        fest_k = np.unique(np.concatenate(fest_teil)) if fest_teil else np.zeros(0, dtype=np.int64)
        if len(fest_k):
            d.fest.append(d.global_knoten(0, fest_k))
        if gleit or gelenk:
            d.gleichungen += _gleichungen(tn, d, fest_k, gleit, gelenk)
            if not len(fest_k):  # nur gleitende oder gelenkige Lager: gilt als gehalten (kein Halte-Federn-Fall)
                self.zwang_gehalten = True
        # Lasten (je Körper ein P2-Lastvektor, dann Knotenkräfte)
        lv = {0: np.zeros(N.N)}
        summe = np.zeros(3)
        lastflaechen = []
        V = float(N.vol.sum())
        lastkoerper: dict[int, float] = {}
        for last in f["lasten"]:
            F = np.asarray(last["kraft"], float)
            M = np.asarray(last["moment"], float) if last.get("moment") is not None else None
            P = np.asarray(last["punkt"], float) if last.get("punkt") is not None else None
            summe += F
            x = last.get("kontakt_mit")
            if x and ist_kontakt(x) and self.kn[x][0]["rolle"] == "last":
                i = koerper(x)
                if (x, i) not in paare:
                    paare.append((x, i))
                nx = netze[i].N
                lv.setdefault(i, np.zeros(nx.N))
                lastflaechen.append(self._schnitt_last(x, nx, lv[i], last, F, M, P))
                lastkoerper[i] = lastkoerper.get(i, 0.0) + float(np.linalg.norm(F))
                continue
            if last.get("flaeche_datei") and _flaechen_facetten is not None:  # Last auf der ganzen Fläche (Simulation)
                sel = _flaechen_facetten(N, last["flaeche_datei"])
                if len(sel) == 0:
                    sel = _lastflaeche(N, P, self.groesse, self.n["h"]) if P is not None else np.arange(len(N.rand))
                druck = (last.get("flaeche") or {}).get("druck")
                if druck:
                    lv[0] += N.last_druck(sel, float(druck))
                    F_ist = -float(druck) * (N.rand_normale[sel] * N.rand_flaeche_mm2[sel, None]).sum(axis=0)
                    summe += F_ist - F
                else:
                    lv[0] += N.last_flaeche(sel, F, None, None)
                lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
            elif x:
                sel = self.beruehrt.get(x, np.zeros(0, dtype=np.int64))
                if len(sel) == 0 and P is not None:
                    sel = _lastflaeche(N, P, self.groesse, self.n["h"])
                lv[0] += N.last_flaeche(sel, F, M, P)
                lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
            elif P is not None:
                sel = _lastflaeche(N, P, self.groesse, self.n["h"])
                lv[0] += N.last_flaeche(sel, F, M, P)
                lastflaechen.append(round(float(N.rand_flaeche_mm2[sel].sum()), 1))
            else:
                lv[0] += N.last_volumen(F / V)
                if M is not None and np.any(M):
                    lv[0] += N.last_flaeche(np.arange(len(N.rand)), np.zeros(3), M, None)
                lastflaechen.append(None)
        g = np.asarray(f.get("feld") or (0, 0, 0), float) * (T["masse_kg"] / max(T["volumen"], 1e-9))
        lv[0] += N.last_volumen(g)
        summe += g * V
        F_last = np.zeros((d.knotenzahl, 3))
        for i, v in lv.items():
            k = d.koerper[i]
            F_last[k.offset_k:k.offset_k + len(k.knoten)] += netze[i].kraefte(v)
        # Klemmschrauben: Kräftepaar Kopf ↔ Mutterseite auf dem Teil (Vorspannung)
        F_vor = np.zeros((d.knotenzahl, 3))
        klemm = []
        if kontakt:
            for kl in T.get("klemmungen") or []:
                r = self._klemmung(kl, N)
                if r is None:
                    self.hinweise.append(f"Klemmschraube {kl.get('schraube')}: Kopf- oder Mutterseite am Teil nicht "
                                         "gefunden, ohne Klemmkraft gerechnet")
                    continue
                F_vor[:len(tn.knoten)] += tn.kraefte(r.pop("_lv"))
                klemm.append(r)
        # Kontaktpaare
        E_teil = float(T["werkstoff"]["E"])
        for x, i in paare:
            info = self.kn[x][0]
            E_x = float(info["werkstoff"]["E"]) if info.get("werkstoff") else E_teil * 100
            K = KONTAKT_FAKTOR * min(E_teil, E_x)
            sl = self.zone.get(x, np.zeros(0, dtype=np.int64))
            if len(sl) == 0:
                self.hinweise.append(f"Kontakt mit {x}: keine Kontaktzone gefunden")
                continue
            nx = netze[i].N
            ms = zugewandt(nx.rand_mitte, nx.rand_normale, N.p, N.rand[sl], SUCH_MM + 1.0)
            if len(ms) == 0:
                self.hinweise.append(f"Kontakt mit {x}: keine zugewandten Flächen am Partner")
                continue
            mu = float((verb.get(x) or {}).get("reibwert") or 0.0)
            d.kontakte.append(Kontakt(f"C{len(d.kontakte)}", (0, *tn.oberflaeche(K0, sl)),
                                      (i, *netze[i].oberflaeche(d.koerper[i], ms)), mu, K, K / HAFT_TEILER,
                                      (verb.get(x) or {}).get("spiel")))
        # Halte-Federn für Körper ohne feste Knoten (Stäbe im Kontakt, das Teil ohne festes Lager)
        frei = [i for i in range(len(d.koerper)) if not any(
            np.isin(d.global_knoten(i, np.arange(len(netze[i].knoten))), fk).any() for fk in d.fest)
            and not (i == 0 and self.zwang_gehalten)]
        federn = {}
        for i in frei:
            k = d.koerper[i]
            gr = float(np.max(k.knoten.max(axis=0) - k.knoten.min(axis=0)))
            last_n = lastkoerper.get(i, float(np.linalg.norm(summe)))
            # so weich, dass sie fast nichts tragen, aber so steif, dass das erste Inkrement den Körper nicht aus der
            # Kontaktzone schiebt (bevor der Kontakt Steifigkeit hat): FEDER_LAST · Last je mm
            kges = max(FEDER_ANTEIL * float(k.werkstoff["E"]) * gr, FEDER_LAST * max(last_n, 1.0))
            kn = d.global_knoten(i, np.arange(len(k.knoten)))
            d.federn.append((kn, kges / len(kn)))
            federn[i] = {"k_ges": kges, "knoten": len(kn), "last_n": last_n}
        frei_last = any(i in lastkoerper for i in frei) or (0 in frei)  # ein frei gelagerter Körper bekommt Last
        # Ausgabe: Ecken des Teils und der freien Körper
        aus = [d.global_knoten(0, np.arange(N.n))]
        for i in frei:
            if i != 0:
                aus.append(d.global_knoten(i, np.arange(netze[i].N.n)))
        d.ausgabe_knoten = np.concatenate(aus)
        # Schritte
        if art == "beulen":
            d.schritte.append(Schritt("beulen", F_last, art="beulen", beulfaktoren=int(self.opt.get("beulmoden") or 4)))
        elif art == "last":
            if klemm:
                d.schritte.append(Schritt("vorspannung", F_vor, zeit=(ANFANG_KONTAKT if 0 in frei else 0.25, 1.0, 1e-7,
                                                                    0.5), frequenz=1000))
            # nach der Vorspannung liegt der geklemmte Körper schon an: zügiger anfangen
            anfang = (ANFANG_KLEMMUNG if klemm else ANFANG_KONTAKT) if frei_last else 0.25
            d.schritte.append(Schritt("last", F_vor + F_last, zeit=(anfang, 1.0, 1e-7, 0.5),
                                      frequenz=1000))
            if T.get("fliess"):
                d.schritte.append(Schritt("entlasten", F_vor, zeit=(0.5, 1.0, 1e-6, 1.0), frequenz=1000))
        else:
            if klemm:
                d.schritte.append(Schritt("vorspannung", F_vor, zeit=(ANFANG_KONTAKT if 0 in frei else 0.25, 1.0, 1e-7,
                                                                    0.5), frequenz=1000,
                                          ausgabe=("U",)))
            for j, (_, lb, dmax) in enumerate(stufen or [(0.0, 1.0, 0.04)]):
                anfang = min(0.01, dmax) if not (frei_last and j == 0) else min(dmax, ANFANG_KONTAKT / max(lb, 1.0))
                d.schritte.append(Schritt(f"traglast{j}", F_vor + lb * F_last, zeit=(anfang, 1.0, 1e-7, dmax),
                                          max_inkremente=600, ausgabe=("U", "S", "PEEQ")))
        self.d, self.netze, self.koerper_index = d, netze, koerper_index
        self.federn, self.klemm, self.fest_k = federn, klemm, fest_k
        self.summe, self.lastflaechen = summe, lastflaechen
        self.F_last = F_last
        return {"knoten": d.knotenzahl, "elemente": sum(len(k.elemente) for k in d.koerper),
                "kontakte": len(d.kontakte), "schritte": [s.name for s in d.schritte]}

    def _schnitt_last(self, x: str, nx: Any, lv: np.ndarray, last: dict[str, Any], F: np.ndarray,
                      M: np.ndarray | None, P: np.ndarray | None) -> float | None:
        """Last eines Stabs an seinen Schnittflächen (Rand des Zuschnitts): je Seite die Kraft dieser Seite aus dem
        Stabwerk, sonst die ganze Last verteilt auf alle Schnittflächen."""
        lo, hi = (np.asarray(v, float) for v in self.kn[x][0]["box"])
        c = nx.rand_mitte
        nrm = nx.rand_normale
        tol = 1e-3 * max(float(np.max(hi - lo)), 1.0)
        gruppen: dict[tuple[int, int], np.ndarray] = {}
        for ax in range(3):
            for s, wand in ((-1, lo[ax]), (1, hi[ax])):
                sel = np.where((np.abs(c[:, ax] - wand) < tol) & (nrm[:, ax] * s > 0.9))[0]
                if len(sel):
                    gruppen[(ax, s)] = sel
        if not gruppen:
            self.hinweise.append(f"{x}: keine Schnittfläche am Zuschnitt, Last auf die ganze Oberfläche")
            nx_sel = np.arange(len(nx.rand))
            lv += nx.last_flaeche(nx_sel, F, M, P)
            return round(float(nx.rand_flaeche_mm2.sum()), 1)
        seiten = last.get("seiten") or []
        flaeche = 0.0
        if seiten:
            for sd in seiten:
                r = np.asarray(sd["richtung"], float)
                best = max(gruppen, key=lambda k: float(np.dot(nrm[gruppen[k]].mean(axis=0), r)))
                if float(np.dot(nrm[gruppen[best]].mean(axis=0), r)) < 0.5:
                    self.hinweise.append(f"{x}: Seite in Richtung {np.round(r, 2).tolist()} ohne Schnittfläche "
                                         "(Stabende im Zuschnitt), Kraft dieser Seite auf die nächste Schnittfläche")
                sel = gruppen[best]
                Fs = np.asarray(sd["kraft"], float)
                Ms = np.asarray(sd["moment"], float)
                Ps = np.asarray(sd.get("punkt") or (P if P is not None else nx.rand_mitte[sel].mean(axis=0)), float)
                lv += nx.last_flaeche(sel, Fs, Ms, Ps)
                flaeche += float(nx.rand_flaeche_mm2[sel].sum())
            return round(flaeche, 1)
        sel = np.concatenate(list(gruppen.values()))
        lv += nx.last_flaeche(sel, F, M, P)
        return round(float(nx.rand_flaeche_mm2[sel].sum()), 1)

    def _klemmung(self, kl: dict[str, Any], N: Any) -> dict[str, Any] | None:
        from kevcad_kernel.statik.festkoerper import kontakt as kt

        def faces(namen: list[str], tol: float) -> np.ndarray:
            out = []
            for x in namen:
                nb = self.T["nachbarn"].get(x)
                if nb is None:
                    continue
                with np.load(nb["datei"]) as z:
                    dd = kt.abstand(N.rand_mitte, z["pos"], z["tri"], tol)
                out.append(np.where(np.isfinite(dd))[0])
            return np.unique(np.concatenate(out)) if out else np.zeros(0, dtype=np.int64)

        kopf, mutter = faces(kl["kopf"], 0.35), faces(kl["mutter"], 0.35)
        if len(kopf) == 0 and len(mutter) == 0:
            return None
        A = N.rand_flaeche_mm2

        def schwer(sel: np.ndarray, namen: list[str]) -> np.ndarray | None:
            if len(sel):
                return (A[sel, None] * N.rand_mitte[sel]).sum(axis=0) / A[sel].sum()
            pts = []
            for x in namen:  # Seite nicht am Teil (Mutter im starren Lager): Mitte ihres Netzes
                nb = self.T["nachbarn"].get(x)
                if nb is not None:
                    with np.load(nb["datei"]) as z:
                        pts.append(z["pos"])
            return np.concatenate(pts).mean(axis=0) if pts else None

        ck, cm = schwer(kopf, kl["kopf"]), schwer(mutter, kl["mutter"])
        if ck is None or cm is None:
            return None
        a = cm - ck
        if float(np.linalg.norm(a)) < 1e-6:
            return None
        a /= np.linalg.norm(a)
        if len(kopf):
            kopf_n = kopf[np.abs(N.rand_normale[kopf] @ a) > 0.7]
            if len(kopf_n):
                kopf = kopf_n
                ck = (A[kopf, None] * N.rand_mitte[kopf]).sum(axis=0) / A[kopf].sum()
                # Richtung senkrecht zur Auflage von Scheibe bzw. Kopf (in das Teil hinein); die Lage der Schwerpunkte
                # gibt nur das Vorzeichen (sonst kippt ein ungleich vernetzter Kopf die Kraft um einige Grad)
                nm = -(A[kopf, None] * N.rand_normale[kopf]).sum(axis=0)
                if float(np.linalg.norm(nm)) > 1e-9:
                    nm /= np.linalg.norm(nm)
                    a = nm if float(np.dot(nm, a)) > 0 else -nm
        Fk = float(kl["kraft"])
        lv = np.zeros(N.N)
        if len(kopf):
            lv += N.last_flaeche(kopf, Fk * a, None, ck)
        if len(mutter):
            lv += N.last_flaeche(mutter, -Fk * a, None, cm)
        return {"schraube": kl.get("schraube"), "kraft_n": Fk, "quelle": kl.get("quelle"),
                "achse": [round(float(c), 4) for c in a], "kopf": [round(float(c), 2) for c in ck],
                "mutter": [round(float(c), 2) for c in cm], "kopf_mm2": round(float(A[kopf].sum()), 1),
                "mutter_mm2": round(float(A[mutter].sum()), 1), "_lv": lv}

    # -- Rechnen -----------------------------------------------------------------------------------------------------

    def rechne(self, ordner: Path, name: str, fortschritt: Any, stopp: Any = None, timeout_s: float = 900.0
               ) -> dict[str, Any]:
        self.d.schreibe(str(ordner / f"{name}.inp"))
        return lauf.rechne(ordner, name, len(self.d.schritte), fortschritt=fortschritt, stopp=stopp,
                           timeout_s=timeout_s)


def _ende_je_schritt(inks: list[dict[str, Any]], schritte: int) -> list[dict[str, Any] | None]:
    """Letztes Inkrement jedes Schritts (Schritt k endet bei Gesamtzeit k)."""
    out: list[dict[str, Any] | None] = [None] * schritte
    for i in inks:
        k = int(math.ceil(i["zeit"] - 1e-6)) - 1
        if 0 <= k < schritte and abs(i["zeit"] - (k + 1)) < 1e-4:
            out[k] = i
    return out


def auswerten_last(fall: Fall, ordner: Path, name: str) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Ergebnis von Vorspannung, Last, Entlasten: Spannungen, plastische Dehnung, Kontakt, Federn, Feld."""
    T, f, N, d = fall.T, fall.f, fall.N, fall.d
    namen = [s.name for s in d.schritte]
    inks = fr.lies_frd(str(ordner / f"{name}.frd"), ("DISP", "STRESS", "PE", "CONTACT"))
    ende = _ende_je_schritt(inks, len(namen))
    i_last = namen.index("last")
    E = ende[i_last]
    if E is None:
        raise RuntimeError("CalculiX hat die Last nicht erreicht (keine Konvergenz)")
    nk = d.knotenzahl
    U = fr.feld(E, "DISP", nk, 3)
    S = fr.feld(E, "STRESS", nk, 6)
    PE = fr.feld(E, "PE", nk, 1)
    C = fr.feld(E, "CONTACT", nk, 6)
    w = T["werkstoff"]
    f_m = float((T.get("fliess") or {}).get("fy") or w["f"]) if T.get("fliess") else float(w["f"])
    if T.get("fliess") and T["druckteil"]:
        f_m = float(T["fliess"]["rm"]) if T.get("schicht") is not None else float(T["fliess"]["fy"])
    s = _voigt(S[:N.n])
    idx, krit = _index(s, T, f_m)
    from kevcad_kernel.statik.festkoerper import werkstoff as wk

    vm = wk.mises(s)
    frei = np.ones(N.n, dtype=bool)
    fest_ecken = fall.fest_k[fall.fest_k < N.n]
    frei[fest_ecken] = False
    if not frei.any():
        frei[:] = True
    kand = np.where(frei)[0]
    k = int(kand[np.argmax(idx[kand])])
    k_rand = int(np.argmax(idx))
    sicherheit = 1.0 / float(idx[k]) if idx[k] > 0 else math.inf
    u = U[:N.n]
    ub = np.linalg.norm(u, axis=1)
    pe = PE[:N.n, 0] if PE is not None else np.zeros(N.n)
    ziel = float(f["ziel"])
    info: dict[str, Any] = {
        "sicherheit_last": round(sicherheit, 3) if math.isfinite(sicherheit) else None,
        "spannung_max": round(float(vm[kand].max()), 3), "spannung_ort": round(float(vm[k]), 3),
        "kriterium": ("schicht" if krit[k] == 1 else ("quer_unbekannt" if krit[k] == 2 else "mises")),
        "ort": [round(float(c), 2) for c in N.p[k]],
        "sicherheit_lagerrand": round(1.0 / float(idx[k_rand]), 3) if idx[k_rand] > 0 else None,
        "ort_lagerrand": [round(float(c), 2) for c in N.p[k_rand]],
        "verformung_max_mm": round(float(ub.max()), 5),
        "verformung_ort": [round(float(c), 2) for c in N.p[int(np.argmax(ub))]],
        "festigkeit": f_m, "q": w.get("q"), "werkstoff": w.get("name"),
    }
    alt = {}
    if T["druckteil"]:
        for nm, nrm in (T.get("ausrichtungen") or {}).items():
            a_m, a_s = wk.index(s, f_m, w.get("q"), np.asarray(nrm))
            alt[nm] = round(1.0 / float(np.max(np.maximum(a_m, a_s)[kand])), 3)
    info["ausrichtungen"] = alt
    # Plastizität
    if T.get("fliess"):
        fl = T["fliess"]
        kp = int(np.argmax(pe))
        plast = {"modell": fl["modell"], "fliessgrenze": fl["fy"], "grenzdehnung": fl["grenzdehnung"],
                 "dehnung_max": round(float(pe.max()), 6), "ort": [round(float(c), 2) for c in N.p[kp]],
                 "fliesst": bool(pe.max() > 1e-6)}
        if "entlasten" in namen and ende[namen.index("entlasten")] is not None:
            Ue = fr.feld(ende[namen.index("entlasten")], "DISP", nk, 3)
            u0 = np.zeros((N.n, 3))
            if "vorspannung" in namen and ende[namen.index("vorspannung")] is not None:
                u0 = fr.feld(ende[namen.index("vorspannung")], "DISP", nk, 3)[:N.n]
            ue = np.linalg.norm(Ue[:N.n] - u0, axis=1)
            plast["bleibend_mm"] = round(float(ue.max()), 5)
            plast["bleibend_ort"] = [round(float(c), 2) for c in N.p[int(np.argmax(ue))]]
        info["plastisch"] = plast
    # Kontakt je Paar (Knotenwerte am Teil: Slave)
    zusatz = {z: np.zeros(N.n) for z in ZUSATZ}
    zusatz["plast_dehnung"] = pe.copy()
    if d.kontakte and C is not None:
        Cv = None
        if "vorspannung" in namen and ende[namen.index("vorspannung")] is not None:
            Cv = fr.feld(ende[namen.index("vorspannung")], "CONTACT", nk, 6)
        a_kn = _flaeche_je_knoten(N, np.arange(N.n))
        paare = []
        for x in sorted(fall.zone):
            if x not in fall.koerper_index:
                continue
            zone_kn = np.unique(N.rand[fall.zone[x]])
            p = C[zone_kn, 3]
            op = C[zone_kn, 0]
            sl = np.linalg.norm(C[zone_kn, 1:3], axis=1)
            tau = np.linalg.norm(C[zone_kn, 4:6], axis=1)
            if Cv is not None:
                sl = np.linalg.norm(C[zone_kn, 1:3] - Cv[zone_kn, 1:3], axis=1)
                zu_vor = Cv[zone_kn, 3] > 0
                klaff = np.where(zu_vor & (p <= 0), np.maximum(op, 0.0), 0.0)
            else:
                klaff = np.where(p <= 0, np.maximum(op, 0.0), 0.0)
            zusatz["kontaktdruck"][zone_kn] = np.maximum(p, 0.0)
            zusatz["klaffen"][zone_kn] = klaff
            zusatz["schlupf"][zone_kn] = sl
            A = a_kn[zone_kn]
            traegt = p > 1e-6
            v = (fall.T.get("verbindungen") or {}).get(x) or {}
            mu = float(v.get("reibwert") or 0.0)
            ausn = np.where(traegt, tau / np.maximum(mu * p, 1e-12), 0.0) if mu > 0 else np.zeros(len(p))
            paare.append({
                "mit": x, "rolle": fall.kn[x][0]["rolle"], "reibwert": mu, "reibwert_quelle": v.get("reibwert_quelle"),
                "quelle": v.get("quelle"), "druck_max": round(float(p.max(initial=0.0)), 3),
                "druck_ort": [round(float(c), 2) for c in N.p[zone_kn[int(np.argmax(p))]]] if len(p) else None,
                "kraft_n": round(float((np.maximum(p, 0) * A).sum()), 2),
                "flaeche_mm2": round(float(A.sum()), 1), "traegt_mm2": round(float(A[traegt].sum()), 1),
                "anteil_traegt": round(float(A[traegt].sum() / max(A.sum(), 1e-9)), 3),
                "klaffen_max_mm": round(float(klaff.max(initial=0.0)), 4),
                "schlupf_max_mm": round(float(sl.max(initial=0.0)), 4),
                "reibung_ausnutzung": round(float(ausn.max(initial=0.0)), 3),
                "gleitet_anteil": round(float(A[ausn > 0.98].sum() / max(A[traegt].sum(), 1e-9)), 3),
            })
        info["kontakt"] = {"paare": paare, "klemmungen": fall.klemm}
    # Federn: trägt ein freier Körper über die Federn statt über den Kontakt?
    rutsch = []
    for i, fd in fall.federn.items():
        k_ = d.koerper[i]
        nn = fall.netze[i].N.n
        ui = U[k_.offset_k:k_.offset_k + nn]
        kraft = float(np.linalg.norm(ui.mean(axis=0))) * fd["k_ges"]
        anteil = kraft / max(fd["last_n"], 1e-9)
        u0 = np.zeros(3)
        if "vorspannung" in namen and ende[namen.index("vorspannung")] is not None:
            u0 = fr.feld(ende[namen.index("vorspannung")], "DISP", nk, 3)[k_.offset_k:k_.offset_k + nn].mean(axis=0)
        fd["u_last"] = float(np.linalg.norm(ui.mean(axis=0) - u0))
        fall.u_last[k_.name] = fd["u_last"]
        rutsch.append({"koerper": k_.name, "federkraft_n": round(kraft, 3), "anteil": round(anteil, 4),
                       "verschiebung_mm": round(float(np.linalg.norm(ui.mean(axis=0))), 4),
                       "verschiebung_last_mm": round(fd["u_last"], 5)})
    info["federn"] = rutsch
    info["rutscht"] = any(r["anteil"] > RUTSCH_ANTEIL for r in rutsch)
    sv = np.unique(N.rand)
    remap = np.full(N.n, -1, dtype=np.int64)
    remap[sv] = np.arange(len(sv))
    felder = {"punkte": N.p[sv].astype(np.float32), "dreiecke": remap[N.rand].astype(np.uint32),
              "ausnutzung": (ziel * idx[sv]).astype(np.float32), "spannung": vm[sv].astype(np.float32),
              "verschiebung": u[sv].astype(np.float32)}
    for z_ in ZUSATZ:
        felder[z_] = zusatz[z_][sv].astype(np.float32)
    info["zusatz_max"] = {z_: round(float(zusatz[z_].max()), 6) for z_ in ZUSATZ}
    return info, felder


def auswerten_traglast(fall: Fall, ordner: Path, name: str, stufen: list[tuple[float, float, float]],
                       gestoppt: str | None) -> dict[str, Any]:
    """Laststeigerung: je Inkrement Lastfaktor, Verschiebung, plastische Dehnung, Index; erstes Kriterium zählt."""
    T, N, d = fall.T, fall.N, fall.d
    namen = [s.name for s in d.schritte]
    t0 = float(namen.index("traglast0"))
    lam_max = stufen[-1][1]

    def faktor(zeit: float) -> float:
        k = min(max(int(math.ceil(zeit - t0 - 1e-9)) - 1, 0), len(stufen) - 1)
        a, b, _ = stufen[k]
        return a + (b - a) * (zeit - t0 - k)

    alle = fr.lies_frd(str(ordner / f"{name}.frd"), ("DISP", "STRESS", "PE"))
    inks = [i for i in alle if i["zeit"] > t0 + 1e-9]
    u_vor: dict[int, np.ndarray] = {}
    vor = [i for i in alle if abs(i["zeit"] - t0) < 1e-4]
    if vor and t0 > 0:
        Uv = fr.feld(vor[-1], "DISP", d.knotenzahl, 3)
        if Uv is not None:
            for i in fall.federn:
                k_ = d.koerper[i]
                u_vor[i] = Uv[k_.offset_k:k_.offset_k + fall.netze[i].N.n].mean(axis=0)
    nk = d.knotenzahl
    w = T["werkstoff"]
    fl = T.get("fliess")
    f_m = float(w["f"])
    if fl:
        f_m = float(fl["rm"]) if (T["druckteil"] and T.get("schicht") is not None) else float(fl["fy"])
    frei = np.ones(N.n, dtype=bool)
    frei[fall.fest_k[fall.fest_k < N.n]] = False
    if not frei.any():
        frei[:] = True
    kurve = []
    kriterien: dict[str, float] = {}
    klammern: dict[str, tuple[float, float]] = {}
    vorher = None
    for ink in inks:
        lam = faktor(ink["zeit"])
        U = fr.feld(ink, "DISP", nk, 3)
        if U is None:
            continue
        S = fr.feld(ink, "STRESS", nk, 6)
        PE = fr.feld(ink, "PE", nk, 1)
        um = float(np.linalg.norm(U[:N.n], axis=1).max())
        pe = float(PE[:N.n, 0].max()) if PE is not None else 0.0
        werte = {"dehnung": pe / fl["grenzdehnung"] if fl else 0.0}
        if S is not None:
            idx, krit = _index(_voigt(S[:N.n]), T, f_m)
            if fl and not T["druckteil"]:
                werte["bruch"] = 0.0  # Metall: Fließen ist erlaubt, es zählt die Grenzdehnung
            elif fl and T["druckteil"]:
                ks = np.where(krit == 1, idx, 0.0)  # Schichtfuge bleibt spröde
                werte["schicht"] = float(ks[frei].max())
            else:
                werte["bruch"] = float(idx[frei].max())
        # Rutschen: ein frei gelagerter Körper (Stab im Kontakt, Teil ohne festes Lager) bewegt sich als Ganzes mehr
        # als SCHLUPF_MM und mehr als zehnmal so weit, wie es die Last bei λ = 1 linear erwarten ließe, oder seine
        # Halte-Federn tragen mehr als RUTSCH_ANTEIL der Last
        anteil = 0.0
        for i, fd in fall.federn.items():
            k_ = d.koerper[i]
            nn = fall.netze[i].N.n
            ui = U[k_.offset_k:k_.offset_k + nn].mean(axis=0) - u_vor.get(i, 0.0)
            last_n = fd["last_n"] * max(lam, 1e-9)
            anteil = max(anteil, float(np.linalg.norm(ui)) * fd["k_ges"] / max(last_n, 1e-9) / RUTSCH_ANTEIL)
            erwartet = max(SCHLUPF_MM, 10.0 * lam * float(fall.u_last.get(k_.name) or 0.0))
            anteil = max(anteil, float(np.linalg.norm(ui)) / erwartet)
        werte["rutschen"] = anteil
        kurve.append({"faktor": round(lam, 4), "verformung_max_mm": round(um, 5), "dehnung_max": round(pe, 6),
                      **{k_: round(v, 4) for k_, v in werte.items()}})
        for kr, v in werte.items():
            if kr not in kriterien and v >= 1.0:
                if vorher is None:
                    kriterien[kr] = lam
                    klammern[kr] = (0.0, lam)
                else:
                    lam0, v0 = vorher[0], vorher[1].get(kr, 0.0)
                    klammern[kr] = (lam0, lam)
                    if kr in SPRUNG:  # Sprung (Rutschen): Mitte der Klammer, die Werte dazwischen sind nicht linear
                        kriterien[kr] = 0.5 * (lam0 + lam)
                    else:
                        kriterien[kr] = lam0 + (lam - lam0) * (1.0 - v0) / max(v - v0, 1e-12)
        vorher = (lam, werte)
    letzt = kurve[-1]["faktor"] if kurve else 0.0
    if kriterien:
        kr, lam_t = min(kriterien.items(), key=lambda kv: kv[1])
        klammer = klammern[kr]
        art = {"dehnung": "Grenzdehnung", "schicht": "Schichtfuge", "bruch": "Festigkeit",
               "rutschen": "Rutschen"}[kr]
    elif gestoppt or (kurve and letzt < lam_max * 0.999):
        vor = kurve[-2]["faktor"] if len(kurve) >= 2 else 0.0
        kr, lam_t, art = "kollaps", letzt, "Kollaps (keine Gleichgewichtslage)"
        klammer = (letzt, letzt + max(letzt - vor, 0.02 * max(letzt, 1e-6)))
    else:
        kr, lam_t, art = "nicht_erreicht", lam_max, f"bis {lam_max:g} kein Versagen"
        klammer = (lam_max, lam_max)
    return {"faktor": round(float(lam_t), 4), "kriterium": kr, "text": art, "lastfaktor_max": lam_max,
            "erreicht": round(float(letzt), 4), "gestoppt": gestoppt, "kurve": kurve[-60:],
            "kriterien": {k_: round(v, 4) for k_, v in kriterien.items()},
            "klammer": [round(float(klammer[0]), 5), round(float(klammer[1]), 5)]}


# ----------------------------------------------------------------------------------------------------------------------
# Teil


def rechne_teil(T: dict[str, Any], opt: dict[str, Any], fein: bool, ablage: Path, von: float, bis: float
                ) -> list[dict[str, Any]]:
    t0 = time.perf_counter()
    kurz = T["name"].rsplit("/", 1)[-1]
    out: list[dict[str, Any]] = []
    offen = []
    for f in T["faelle"]:
        alt = lies_fall(ablage / "ccx" / f"{f['schluessel']}.npz")
        if alt is not None:
            out.append({**alt, "id": f["id"], "aus_speicher": True})
        else:
            offen.append(f)
    if not offen:
        melde(bis, f"{kurz}: aus dem Zwischenspeicher")
        return out
    from kevcad_kernel.statik.festkoerper import kontakt as kt
    from kevcad_kernel.statik.festkoerper import loeser

    def schritt(anteil: float, text: str) -> None:
        melde(von + (bis - von) * anteil, f"{kurz}: {text}")

    schritt(0.01, "vernetzen")
    n, netz_gemerkt = _netz_teil(T, fein, ablage)
    N = loeser.Netz(n["p"], n["t"], n["rand"], n["flaeche"])
    t_netz = (time.perf_counter() - t0) * 1000
    beruehrt: dict[str, np.ndarray] = {}
    zone: dict[str, np.ndarray] = {}
    for x, nb in T["nachbarn"].items():
        with np.load(nb["datei"]) as z:
            dd = kt.abstand(N.rand_mitte, z["pos"], z["tri"], max(float(nb["tol"]), SUCH_MM + float(nb["tol"])))
        beruehrt[x] = np.where(dd <= float(nb["tol"]))[0]
        if x in (T.get("koerper") or {}):
            with np.load(nb["datei"]) as z:
                zone[x] = zugewandt(N.rand_mitte, N.rand_normale, z["pos"], z["tri"], SUCH_MM + float(nb["tol"]))
    koerper_netze: dict[str, Any] = {}
    for x, info in (T.get("koerper") or {}).items():
        schritt(0.04, f"vernetzen: {x.rsplit('/', 1)[-1]}")
        try:
            nx = _netz_koerper(info, float(n["h"]), ablage)
            koerper_netze[x] = (info, loeser.Netz(nx["p"], nx["t"], nx["rand"], nx["flaeche"]), _km(nx))
        except Exception as exc:  # noqa: BLE001 - dann eben fest wie S3
            zone.pop(x, None)
            T.setdefault("_hinweise", []).append(f"{x}: Kontaktkörper nicht vernetzt ({exc}), fest gerechnet")
    for j, f in enumerate(offen):
        a0 = 0.08 + 0.9 * j / len(offen)
        a1 = 0.08 + 0.9 * (j + 1) / len(offen)
        t_f = time.perf_counter()
        fall = Fall(T, f, opt, N, n, beruehrt, zone, koerper_netze)
        fall.hinweise += T.get("_hinweise") or []
        arbeit = Path(tempfile.mkdtemp(prefix="kevcad-ccx-"))
        try:
            aufbau = fall.baue("last")
            ms: dict[str, float] = {"netz": round(t_netz, 1)}

            def fs(x: float, text: str, a=a0, b=a1) -> None:
                schritt(a + (b - a) * 0.45 * x, f"CalculiX {text}")

            r1 = fall.rechne(arbeit, "last", fs)
            ms["last"] = r1["ms"]
            if r1["fehler"] and not (arbeit / "last.frd").exists():
                raise RuntimeError("CalculiX: " + "; ".join(r1["fehler"][:3]))
            info, felder = auswerten_last(fall, arbeit, "last")
            ziel = float(f["ziel"])
            info["konvergenz"] = {"code": r1["code"], "inkremente": r1["inkremente"], "fehler": r1["fehler"][:3],
                                  "warnungen": r1["warnungen"][:5]}
            # Traglast: zweiter Lauf, Rampe bis lam_max; dann fein in der Klammer des maßgebenden Kriteriums
            if info.get("rutscht"):  # hält schon unter der Last nicht (die Halte-Federn tragen): keine Laststeigerung
                info["traglast"] = {"faktor": 0.0, "kriterium": "rutschen", "text": "rutscht schon unter der Last",
                                    "lastfaktor_max": 1.0, "erreicht": 1.0, "gestoppt": None, "kurve": [],
                                    "kriterien": {"rutschen": 0.0}}
            elif opt.get("traglast") and (T.get("fliess") or opt["kontakt"]):
                lam_el = info["sicherheit_last"] or 1.0
                if T.get("fliess") and info.get("plastisch", {}).get("fliesst"):
                    lam_el = 1.0
                lam_max = float(opt.get("lastfaktor_max") or min(TRAG_MAX, max(2.0, 3.0 * ziel, 3.0 * lam_el)))
                u_last = max(info["verformung_max_mm"], 1e-3)
                tr = None
                stufen = [(0.0, lam_max, 0.05)]
                for lauf_nr in range(TRAG_LAEUFE):
                    if lauf_nr:  # in der Klammer des vorigen Laufs fein: zügig bis an ihren Anfang, dann 16 Schritte
                        if tr is None or tr["kriterium"] == "nicht_erreicht":
                            break
                        lo, hi = tr["klammer"]
                        if hi <= lo or (hi - lo) <= TRAG_GENAU * max(hi, 1e-9):
                            break
                        stufen = ([(0.0, lo, 0.5)] if lo > 0 else []) + [(lo, hi * 1.001, 1.0 / 16)]
                    fall.baue("traglast", stufen)
                    grenze = max(0.02 * fall.groesse, 8.0 * u_last * stufen[-1][1])

                    def stopp(z: dict[str, Any], g=grenze) -> str | None:
                        if z.get("schritt") != len(fall.d.schritte):
                            return None
                        if z.get("disp_letzt", 0.0) > g:
                            return "Verschiebung läuft davon"
                        d_ = z.get("inc_disps") or []
                        if len(d_) >= 4 and d_[-1] > max(0.02, 30.0 * float(np.median(d_[:-1]))):
                            return "Verschiebung springt"
                        return None

                    def ft(x: float, text: str, a=a0, b=a1, nr=lauf_nr) -> None:
                        schritt(a + (b - a) * (0.45 + 0.18 * nr + 0.18 * x), f"Traglast {text}")

                    name_t = f"traglast{lauf_nr}"
                    r2 = fall.rechne(arbeit, name_t, ft, stopp=stopp)
                    ms[name_t] = r2["ms"]
                    if not (arbeit / f"{name_t}.frd").exists():
                        break
                    neu = auswerten_traglast(fall, arbeit, name_t, stufen, r2["gestoppt"])
                    neu["inkremente"] = r2["inkremente"]
                    neu["laeufe"] = lauf_nr + 1
                    if tr is not None and neu["kriterium"] == "nicht_erreicht":
                        break  # in der Klammer nicht erreicht: der vorige Lauf gilt
                    tr = neu
                if tr is not None:
                    if T.get("fliess") and tr["kriterium"] in ("dehnung", "kollaps"):
                        # Tetraeder zweiter Ordnung versteifen voll plastisch (am symmetrisch gelagerten Kragbalken
                        # +5,7 %, netzunabhängig): Traglast aus Fließen um diesen Anteil abgemindert (T42)
                        tr["faktor_roh"] = tr["faktor"]
                        tr["faktor"] = round(tr["faktor"] * TETRA_PLASTISCH, 4)
                    info["traglast"] = tr
            if opt.get("beulen"):
                fall.baue("beulen")
                r3 = fall.rechne(arbeit, "beulen", None)
                ms["beulen"] = r3["ms"]
                fk = [x for x in fr.beulfaktoren(str(arbeit / "beulen.dat"))] if (arbeit / "beulen.dat").exists() \
                    else []
                pos = [x for x in fk if x > 0]
                info["beulen"] = {"faktor": round(min(pos), 4) if pos else None, "faktoren": [round(x, 4) for x in fk],
                                  "fehler": r3["fehler"][:3]}
            # Sicherheit: Traglastfaktor, wenn gerechnet, sonst die Sicherheit unter Last
            tr = info.get("traglast")
            info["sicherheit"] = tr["faktor"] if tr and tr.get("faktor") else info["sicherheit_last"]
            if info.get("beulen", {}).get("faktor") and info["sicherheit"]:
                info["sicherheit"] = min(info["sicherheit"], info["beulen"]["faktor"])
            sf = info["sicherheit"]
            info["ziel"] = ziel
            info["ausnutzung"] = round(ziel / sf, 4) if sf else None
            info.update({
                "stand": "done", "verfahren": "ccx", "szenario": f["szenario"], "teil": T["name"],
                "schluessel": f["schluessel"], "lager": list(f.get("lager") or []),
                "lager_aus_last": f.get("lager_aus_last"), "lasten": f["lasten"], "s0": f.get("s0"),
                "hinweise": list(dict.fromkeys(fall.hinweise)), "kraft_n": [round(float(c), 3) for c in fall.summe],
                "lastflaechen_mm2": fall.lastflaechen,
                "netz": {"knoten": int(N.n), "tetraeder": int(len(N.t)), "freiheitsgrade": int(3 * aufbau["knoten"]),
                         "h_mm": round(float(n["h"]), 2), "fein": fein, "aus_speicher": netz_gemerkt,
                         "koerper": len(fall.d.koerper), "kontakte": aufbau["kontakte"],
                         "elemente": aufbau["elemente"]},
                "loeser": {"verfahren": "ccx", "inkremente": r1["inkremente"]},
                "optionen": {k_: opt.get(k_) for k_ in ("kontakt", "plastisch", "traglast", "beulen")},
                "ms": {**ms, "teil": round((time.perf_counter() - t_f) * 1000, 1)},
            })
            _schreibe_npz(ablage / "ccx" / f"{f['schluessel']}.npz",
                          info=np.frombuffer(json.dumps(info, ensure_ascii=False).encode("utf-8"), dtype=np.uint8),
                          **felder)
            out.append({**info, "id": f["id"], "aus_speicher": False, "_felder": felder})
        except Exception as exc:  # noqa: BLE001 - ein Fall darf die anderen nicht verhindern
            out.append({"id": f["id"], "stand": "failed", "szenario": f["szenario"], "teil": T["name"],
                        "meldung": f"CalculiX nicht gerechnet: {type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=8)})
        finally:
            if os.environ.get("KEVCAD_CCX_BEHALTEN"):
                melde(a1, f"{kurz}: Arbeitsordner {arbeit}")
            else:
                shutil.rmtree(arbeit, ignore_errors=True)
        schritt(a1, f"{j + 1} von {len(offen)} Lastfällen fertig")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("Aufruf: python -m kevcad_kernel.statik.ccx.prozess auftrag.json ergebnis.json", file=sys.stderr)
        return 2
    from kevcad_kernel.statik.ccx import installation

    t0 = time.perf_counter()
    auftrag = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    ablage = speicher()
    out: dict[str, Any] = {"stand": "done", "faelle": [], "pid": os.getpid(), "grenzen": list(GRENZEN_S4),
                           "verfahren": "ccx"}
    inst = installation.finde()
    teile = auftrag.get("teile") or []
    opt = auftrag.get("optionen") or {}
    if not inst["ok"]:
        for T in teile:
            for f in T["faelle"]:
                out["faelle"].append({"id": f["id"], "stand": "failed", "szenario": f["szenario"], "teil": T["name"],
                                      "meldung": inst["meldung"]})
    else:
        melde(0.0, f"{len(teile)} Teile, CalculiX")
        for i, T in enumerate(teile):
            von, bis = i / max(len(teile), 1), (i + 1) / max(len(teile), 1)
            try:
                for r in rechne_teil(T, opt, bool(auftrag.get("fein")), ablage, von, bis):
                    felder = r.pop("_felder", None)
                    if r.get("stand") == "done":
                        r["feld"] = str(ablage / "ccx" / f"{r['schluessel']}.npz")
                    del felder
                    out["faelle"].append(r)
            except Exception as exc:  # noqa: BLE001
                for f in T["faelle"]:
                    out["faelle"].append({"id": f["id"], "stand": "failed", "szenario": f["szenario"],
                                          "teil": T["name"], "meldung": f"nicht gerechnet: {type(exc).__name__}: "
                                                                        f"{exc}",
                                          "traceback": traceback.format_exc(limit=6)})
    out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    melde(1.0, "fertig")
    tmp = argv[1] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

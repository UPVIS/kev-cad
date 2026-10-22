"""Bild je Bauplanschritt: Kamera, Explosion entlang der Einführrichtung, Pfeile, Hervorhebung; Strichbild.

Die Parameter (``bild`` im Schritt, DOKUMENTE.md) entstehen bei jedem Lauf:

- **Explosion:** jede neue Einheit steht um ihren Einführweg zurückversetzt (``−richtung × weg``, 20 … 300 mm).
- **Kamera:** von den acht Isometrie-Richtungen die, aus der die neuen Teile (in Explosionslage) am wenigsten verdeckt
  sind und die Pfeile quer zum Blick liegen; bei gleicher Güte die des vorigen Schritts (ruhiger Ablauf). Rotation
  wie die App (blickt entlang lokal −Z, oben +Y), orthographisch.
- **Ausschnitt:** kleine neue Teile in einer großen Baugruppe: nur die Umgebung (Hüllquader der neuen Teile mit Rand).

Das Strichbild rechnet die Projektion von P6-Z (``zeichnung.projiziere``, auf dem Netz) und legt es in ein Feld 180 × 120 mm:
Linienarten ``sichtbar`` (montierte Teile), ``neu`` (neue Teile), ``duenn`` (Lichtkanten), ``pfeil`` (Einführpfeile).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.bauplan import raster as rs
from kevcad_kernel.bauplan.eingang import Eingang
from kevcad_kernel.pruefung.koerper import basis, richtung_schluessel

FELD = (180.0, 120.0)
RAND = 6.0  # mm im Feld
ISO = [np.array(v, dtype=float) / math.sqrt(3) for v in
       ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1), (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1))]
LINIEN_BAUPLAN = ("sichtbar", "neu", "duenn", "pfeil")
# Sichtbarkeit (Agrawala 2003, RECHERCHE-PHASE6 4.1): neue Teile, bisheriger Stand, Kamerawechsel
SICHT_NEU, SICHT_ALT, SICHT_WECHSEL = 0.50, 0.10, 0.35


def _r(v: Any, n: int = 3) -> Any:
    return [round(float(x), n) for x in v]


def quaternion(rechts: np.ndarray, oben: np.ndarray, hinten: np.ndarray) -> list[float]:
    """Quaternion (x, y, z, w) der Drehung mit den Spalten rechts, oben, hinten (= −Blick), wie CameraState."""
    m = np.stack([rechts, oben, hinten], axis=1)
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    return [round(float(c), 6) for c in (x, y, z, w)]


def blick_fuer(auge: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(Blickrichtung, rechts, oben) für eine Richtung zum Auge, oben ≈ +Z."""
    from kevcad_kernel.zeichnung.ansichten import aus_richtung

    b = aus_richtung(-auge, (0, 0, 1))
    return np.asarray(b.richtung), np.asarray(b.rechts), np.asarray(b.oben)


class Bilder:
    """Kamera und Explosion je Schritt; Raster je Teil und Richtung werden über die Schritte geteilt."""

    def __init__(self, ein: Eingang) -> None:
        self.ein = ein
        teile = ein.aufbau()
        if teile:
            lo = np.min([t.bmin for t in teile], axis=0)
            hi = np.max([t.bmax for t in teile], axis=0)
        else:
            lo, hi = np.zeros(3), np.ones(3)
        self.lo, self.hi = lo, hi
        self.groesse = float(np.linalg.norm(hi - lo)) or 1.0
        self.h = max(self.groesse / 180.0, 0.5)
        self._raster: dict[tuple, rs.Raster] = {}
        self._vorher: np.ndarray | None = None
        self.eigen: dict[str, list[float]] = {}

    def _r(self, name: str, auge: np.ndarray) -> rs.Raster:
        d = -auge
        key = (name, richtung_schluessel(d))
        r = self._raster.get(key)
        if r is None:
            k = self.ein.teile[name].koerper
            R = basis(d)
            r = rs.rastern(k.pos @ R.T, k.tri, self.h)
            self._raster[key] = r
        return r

    def explosion(self, schritt: dict[str, Any]) -> dict[str, list[float]]:
        """Versatz je neuem Teil: um den Einführweg zurück; Verbindungsmittel auf derselben Achse als Stapel mit
        wachsendem Abstand (Scheibe, dann Mutter weiter draußen; Agrawala 2003)."""
        out: dict[str, list[float]] = {}
        # Stapel: Teile, die nacheinander auf derselben Achse in dieselbe Richtung kommen (Scheibe und Mutter,
        # Stellring, Rolle, Stellring), stehen hintereinander statt übereinander: (Richtung, Achspunkt, Weg, Länge)
        stapel: list[list[Any]] = []
        for el in schritt.get("einbau") or []:
            if el.get("grundteil") or el.get("richtung") is None:
                continue
            r = np.asarray(el["richtung"], dtype=float)
            teile = [t for t in el.get("teile") or [] if t in self.ein.teile]
            if not teile:
                continue
            lo = np.min([self.ein.teile[t].bmin for t in teile], axis=0)
            hi = np.max([self.ein.teile[t].bmax for t in teile], axis=0)
            eigen = float(abs(np.dot(hi - lo, r)))
            L = float(np.clip(max(float(el.get("weg") or 0.0), 0.8 * eigen, 20.0), 20.0, 300.0))
            # Hüllrechteck quer zur Richtung: überdecken sich zwei Teile darin, stehen sie hintereinander
            from kevcad_kernel.pruefung.koerper import basis as _basis

            B = _basis(r)[:2]
            ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ B.T
            q_lo, q_hi = ecken.min(axis=0), ecken.max(axis=0)
            ist_vm = el.get("art") == "vm"
            for st in stapel:
                d, (s_lo, s_hi), L0, e0, vm0 = st
                if vm0 == ist_vm and float(np.dot(d, r)) > 0.99 and np.all(q_lo < s_hi - 0.5) \
                        and np.all(s_lo < q_hi - 0.5):
                    L = max(L, L0 + e0 + 8.0)
                    st[1] = (np.minimum(s_lo, q_lo), np.maximum(s_hi, q_hi))
                    st[2], st[3] = L, eigen
                    break
            else:
                stapel.append([r, (q_lo, q_hi), L, eigen, ist_vm])
            for t in teile:
                out[t] = _r(-r * L, 2)
        self.eigen = {t: list(v) for t, v in out.items()}  # eigener Weg je Teil (für die Pfeile)
        # Verbindungsmittel wandern mit ihrem Teil, wenn es im selben Schritt kommt (Mutter am abgerückten Halter)
        haupt = [el for el in schritt.get("einbau") or [] if el.get("art") != "vm" and not el.get("grundteil")
                 and el.get("richtung") is not None]
        for el in schritt.get("einbau") or []:
            if el.get("art") != "vm" or el.get("richtung") is None:
                continue
            for t in el.get("teile") or []:
                if t not in out:
                    continue
                nb = self.ein.nachbarn(t, kontakt=True)
                wirt = next((h for h in haupt if nb & set(h.get("teile") or [])), None)
                if wirt is None:
                    continue
                w0 = next((x for x in wirt.get("teile") or [] if x in out), None)
                if w0 is not None:
                    out[t] = _r(np.asarray(out[t]) + np.asarray(out[w0]), 2)
        return out

    @staticmethod
    def einheiten_im_schritt(schritt: dict[str, Any], teile_da: dict[str, Any]) -> dict[str, list[str]]:
        """Neue Einheiten eines Schritts: Hauptteil → Teile (Teil mit Einsätzen, Zukaufeinheit, Unterbaugruppe)."""
        out: dict[str, list[str]] = {}
        for el in schritt.get("einbau") or []:
            if el.get("grundteil") or el.get("richtung") is None:
                continue
            teile = [t for t in el.get("teile") or [] if t in teile_da]
            if teile:
                out[el.get("haupt") or teile[0]] = teile
        return out

    def parameter(self, schritt: dict[str, Any], vorher: list[str]) -> dict[str, Any]:
        """Kamera, Explosion, Pfeile, Hervorhebung und Ausschnitt eines Montageschritts."""
        neu = [t for t in schritt.get("neu") or [] if t in self.ein.teile]
        vorher = [t for t in vorher if t in self.ein.teile]
        expl = self.explosion(schritt)
        einheiten = self.einheiten_im_schritt(schritt, self.ein.teile)
        pfeile = []
        for el in schritt.get("einbau") or []:
            if el.get("grundteil") or el.get("richtung") is None:
                continue
            teile = [t for t in el.get("teile") or [] if t in self.ein.teile]
            if not teile:
                continue
            mitte = np.mean([self.ein.teile[t].zentrum for t in teile], axis=0)
            off = np.asarray(expl.get(teile[0], [0, 0, 0]), dtype=float)
            eigen = np.asarray(self.eigen.get(teile[0], off), dtype=float)
            pfeile.append({"teil": el.get("haupt") or teile[0], "richtung": _r(el["richtung"], 4),
                           "von": _r(mitte + off, 1), "nach": _r(mitte + off - eigen, 1)})
        # Ausschnitt
        punkte = []
        for t in neu:
            u = self.ein.teile[t]
            off = np.asarray(expl.get(t, [0, 0, 0]), dtype=float)
            punkte += [u.bmin, u.bmax, u.bmin + off, u.bmax + off]
        if not punkte:
            punkte = [self.lo, self.hi]
        lo, hi = np.min(punkte, axis=0), np.max(punkte, axis=0)
        neu_gr = float(np.linalg.norm(hi - lo))
        if neu_gr < 0.3 * self.groesse:
            rand = max(neu_gr, 0.15 * self.groesse)
            lo, hi = lo - rand, hi + rand
            kontext = [t for t in vorher if np.all(self.ein.teile[t].bmax >= lo) and np.all(self.ein.teile[t].bmin <= hi)]
        else:
            kontext = list(vorher)
            if vorher:
                lo = np.minimum(lo, np.min([self.ein.teile[t].bmin for t in vorher], axis=0))
                hi = np.maximum(hi, np.max([self.ein.teile[t].bmax for t in vorher], axis=0))
        # Kamera nach Agrawala 2003: neue Teile mindestens 50 % sichtbar, vom bisherigen Stand mindestens 10 %; die
        # Ansicht des vorigen Schritts bleibt, solange jedes neue Teil mindestens 35 % sichtbar ist
        von_unten = any(el.get("richtung") is not None and float(el["richtung"][2]) > 0.5
                        for el in schritt.get("einbau") or [])
        kandidaten = []
        for auge in ISO:
            if auge[2] < 0 and not von_unten:
                continue
            je_teil, alt_anteil = self._sicht(einheiten, kontext, expl, auge)
            werte = list(je_teil.values()) or [1.0]
            score = float(np.mean(werte))
            if pfeile:
                score += 0.4 * float(np.mean([math.sqrt(max(0.0, 1 - float(np.dot(auge, p["richtung"])) ** 2))
                                              for p in pfeile]))
            if auge[2] > 0:
                score += 0.05
            gut = min(werte) >= SICHT_NEU and (alt_anteil >= SICHT_ALT or not kontext)
            kandidaten.append((gut, score, auge, je_teil, alt_anteil))
        wahl = None
        if self._vorher is not None:
            for k in kandidaten:
                if float(np.dot(k[2], self._vorher)) > 0.99 and min(list(k[3].values()) or [1.0]) >= SICHT_WECHSEL:
                    wahl = k
                    break
        if wahl is None and kandidaten:
            wahl = max(kandidaten, key=lambda k: (k[0], k[1]))
        if wahl is None:
            wahl = (True, 0.0, ISO[0], {}, 1.0)
        _, _, auge, sicht, alt_anteil = wahl
        self._vorher = auge
        # bessere Ansicht je schlecht sichtbarem Teil (für den Befund „verdeckt“)
        vorschlag = {}
        for t, v in sicht.items():
            if v >= SICHT_NEU:
                continue
            best = max(kandidaten, key=lambda k: k[3].get(t, 0.0))
            if best[3].get(t, 0.0) > v + 0.1:
                vorschlag[t] = {"auge": _r(best[2], 4), "sichtbarkeit": round(best[3][t], 2)}
        d, rechts, oben = blick_fuer(auge)
        mitte = (lo + hi) / 2
        diag = float(np.linalg.norm(hi - lo)) or 100.0
        kamera = {"rotation": quaternion(rechts, oben, -d), "pivot": _r(mitte, 1), "distance": round(1.6 * diag, 1),
                  "ortho": True}
        return {"kamera": kamera, "ansicht": {"richtung": _r(d, 5), "oben": _r(oben, 5)}, "explosion": expl,
                "pfeile": pfeile, "hervorheben": neu, "kontext": kontext,
                "ausschnitt": {"min": _r(lo, 1), "max": _r(hi, 1)},
                "sichtbarkeit": {t: round(v, 2) for t, v in sicht.items()},
                "sichtbarkeit_bisher": round(alt_anteil, 2), "besser": vorschlag, "quelle": "auto"}

    def _sicht(self, einheiten: dict[str, list[str]], kontext: list[str], expl: dict[str, list[float]],
               auge: np.ndarray) -> tuple[dict[str, float], float]:
        """Sichtbarer Anteil je neuer Einheit (in Explosionslage, Bildpunkte vorn im Tiefenpuffer aller gezeigten
        Teile) und der Anteil des bisherigen Stands, der sichtbar bleibt."""
        if not einheiten:
            return {}, 1.0
        neu = [t for ts in einheiten.values() for t in ts]
        R = basis(-auge)
        raster: dict[str, rs.Raster] = {}
        for t in kontext:
            raster[t] = self._r(t, auge)
        for t in neu:
            r = self._r(t, auge)
            off = np.asarray(expl.get(t, [0, 0, 0]), dtype=float)
            if np.any(off):
                v = R @ off
                r = r.verschoben(v[0], v[1], v[2])
            raster[t] = r
        alle = rs.vereinige(list(raster.values()), self.h)
        out: dict[str, float] = {}
        for haupt, ts in einheiten.items():
            r = rs.vereinige([raster[t] for t in ts], self.h)
            if not len(r):
                out[haupt] = 0.0
                continue
            idx = alle.suche(r.keys)
            vorn = r.wmin <= alle.wmin[np.maximum(idx, 0)] + self.h
            out[haupt] = float(vorn.mean())
        if not kontext:
            return out, 1.0
        gesamt = vorn_alt = 0
        for t in kontext:
            r = raster[t]
            if not len(r):
                continue
            idx = alle.suche(r.keys)
            gesamt += len(r)
            vorn_alt += int((r.wmin <= alle.wmin[np.maximum(idx, 0)] + self.h).sum())
        return out, (vorn_alt / gesamt if gesamt else 1.0)


# ---------------------------------------------------------------------------------------------------------------------
# Strichbild


def _verschoben(shape: Any, off: list[float]) -> Any:
    from OCP.gp import gp_Trsf, gp_Vec
    from OCP.TopLoc import TopLoc_Location

    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*map(float, off)))
    return shape.Moved(TopLoc_Location(t))


def _clip(pl: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> list[np.ndarray]:
    """Polylinie auf ein Rechteck zuschneiden (Liang-Barsky je Segment, Züge bleiben zusammen)."""
    out: list[list[np.ndarray]] = []
    cur: list[np.ndarray] = []
    for a, b in zip(pl[:-1], pl[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t0, t1 = 0.0, 1.0
        ok = True
        for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
            if abs(p) < 1e-12:
                if q < 0:
                    ok = False
                    break
            else:
                t = q / p
                if p < 0:
                    t0 = max(t0, t)
                else:
                    t1 = min(t1, t)
        if not ok or t0 > t1:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
            continue
        pa = a + (b - a) * t0
        pb = a + (b - a) * t1
        if cur and np.linalg.norm(cur[-1] - pa) < 1e-9:
            cur.append(pb)
        else:
            if len(cur) >= 2:
                out.append(cur)
            cur = [pa, pb]
        if t1 < 1.0:
            out.append(cur)
            cur = []
    if len(cur) >= 2:
        out.append(cur)
    return [np.asarray(c, dtype=float) for c in out]


def _pfeil(a: np.ndarray, b: np.ndarray, kopf: float) -> list[np.ndarray]:
    v = b - a
    L = float(np.linalg.norm(v))
    if L < 1e-6:
        return []
    u = v / L
    n = np.array([-u[1], u[0]])
    k = min(kopf, 0.4 * L)
    spitze = [b - u * k + n * k * 0.45, b, b - u * k - n * k * 0.45]
    return [np.array([a, b]), np.array(spitze)]


def strichbild(ein: Eingang, schritt: dict[str, Any], schluessel: dict[str, str] | None = None,
               feld: tuple[float, float] = FELD) -> dict[str, Any]:
    """Strichbild eines Schritts in Blatt-mm (Feld 180 × 120): {"schritt", "rahmen", "massstab", "linien"}."""
    from kevcad_kernel.zeichnung import projiziere

    bild = schritt.get("bild") or {}
    expl = bild.get("explosion") or {}
    neu = [t for t in schritt.get("neu") or bild.get("hervorheben") or [] if t in ein.teile]
    kontext = [t for t in bild.get("kontext") or [] if t in ein.teile and t not in neu]
    formen: dict[str, Any] = {}
    keys: dict[str, str] = {}
    for t in kontext + neu:
        shape = ein.teile[t].koerper.shape
        off = expl.get(t)
        if off and any(abs(float(c)) > 1e-9 for c in off):
            shape = _verschoben(shape, off)
        formen[t] = shape
        k = (schluessel or {}).get(t) or ein.teile[t].kopf.get("_key") or ""
        keys[t] = f"{k}|{off}" if k else ""
    ansicht = bild.get("ansicht") or {"richtung": [-0.577, 0.577, -0.577], "oben": [0, 0, 1]}
    linien: dict[str, list[np.ndarray]] = {a: [] for a in LINIEN_BAUPLAN}
    if not formen:
        return {"schritt": schritt.get("id"), "rahmen": [0, 0, feld[0], feld[1]], "massstab": 1.0, "linien": linien}
    # auf dem Netz (Vorgabe von projiziere, HLRBRep_PolyAlgo): exakt kann schon bei wenigen Flächen Minuten dauern
    p = projiziere(formen, ansicht, verdeckt=False, mittel=False, je_teil=True,
                   schluessel={n: keys[n] for n in formen if keys.get(n)} or None)
    for name, d in p.teile.items():
        art = "neu" if name in neu else "sichtbar"
        linien[art] += list(d.get("sichtbar") or [])
        linien["duenn"] += list(d.get("duenn") or [])
    for pf in bild.get("pfeile") or []:  # nur für den Ausschnitt; gezeichnet wird nach dem Maßstab
        a2 = p.blick.projiziere(np.asarray(pf["von"], dtype=float))
        b2 = p.blick.projiziere(np.asarray(pf["nach"], dtype=float))
        linien["pfeil"].append(np.array([a2, b2]))
    alle = [pl for ls in linien.values() for pl in ls if len(pl)]
    if not alle:
        return {"schritt": schritt.get("id"), "rahmen": [0, 0, feld[0], feld[1]], "massstab": 1.0, "linien": linien}
    pts = np.concatenate(alle)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    w, h = max(float(hi[0] - lo[0]), 1e-6), max(float(hi[1] - lo[1]), 1e-6)
    s = min((feld[0] - 2 * RAND) / w, (feld[1] - 2 * RAND) / h)
    mitte = (lo + hi) / 2
    ziel = np.array([feld[0] / 2, feld[1] / 2])
    out: dict[str, list[np.ndarray]] = {}
    for art, ls in linien.items():
        if art == "pfeil":
            continue
        neu_ls = []
        for pl in ls:
            q = (np.asarray(pl, dtype=float) - mitte) * s + ziel
            neu_ls += _clip(q, 0.0, 0.0, feld[0], feld[1])
        out[art] = neu_ls
    # Pfeile mit Spitzen von 4 mm (nach dem Maßstab), enden kurz vor dem Ziel
    pf_ls = []
    for pf in bild.get("pfeile") or []:
        a2 = (p.blick.projiziere(np.asarray(pf["von"], dtype=float)) - mitte) * s + ziel
        b2 = (p.blick.projiziere(np.asarray(pf["nach"], dtype=float)) - mitte) * s + ziel
        b2 = a2 + (b2 - a2) * 0.85
        for pl in _pfeil(a2, b2, 4.0):
            pf_ls += _clip(pl, 0.0, 0.0, feld[0], feld[1])
    out["pfeil"] = pf_ls
    return {"schritt": schritt.get("id"), "rahmen": [0.0, 0.0, feld[0], feld[1]], "massstab": round(float(s), 6),
            "linien": out, "ms": round(p.ms, 1)}

"""Einpassen: Kameras, Gelenkwinkel, Brennweiten und Maße gemeinsam, Levenberg-Marquardt auf Kantenabständen.

Kosten je sichtbarem Modellkantenpunkt j eines Bildes:
    r_j = n_j . (u_j - q_j) - o_j         (Punkt-zu-Linie, Pixel der Stufe)
u_j ist der projizierte Punkt, n_j die Normale der projizierten Modellkante, q_j die nächste Bildkante im passenden
Kanal (Maskenrand für Umrisspunkte, sonst gleich gerichtete Canny-Kante), o_j der halbe Pixel Versatz am Maskenrand.
Robust mit Cauchy (Skala sigma), Punkte mit Abstand über `tor` zählen konstant. Die Zuordnung q_j wird bei jeder
Auswertung neu nachgeschlagen (ICP), die Sichtbarkeit und die Auswahl der Kantenpunkte nur alle `innen` Schritte
per GPU-Tiefenbild neu bestimmt.

Ableitungen analytisch: Projektion (OpenCV-Lochkamera), Lage linksseitig im Kamerasystem, Maße über die
Netzableitungen aus fotocad.cad_netz (das Netz ist linear in den Maßen), Gelenke über a x (X - p).

Unbekannte: [freie Maße | log f je Gerätegruppe | je Bild 3 Drehung + 3 Verschiebung + freie Gelenkwinkel].
Die Normalgleichungen sind klein (unter 300 Unbekannte), sie werden blockweise aufgebaut und direkt gelöst.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from .gl import fuer_netz
from .kamera import Kamera, exp_so3, projektion_ableitung

GRAD = math.pi / 180


@dataclass
class Ansicht:
    bild: object                      # bild.Bild
    netz: str                         # Schlüssel in netze
    kamera: Kamera
    winkel: np.ndarray | None = None  # Gelenkwinkel in Grad (Reihenfolge netz.gelenke)
    winkel_frei: tuple = ()           # Indizes der freien Gelenke
    f_gruppe: str | None = "gemeinsam"   # gleiche Gruppe = gleiche Brennweite; None = fest
    gewicht: float = 1.0


@dataclass
class Stufenplan:
    breite: int                       # Breite der Bildstufe in Pixeln
    sigma: float = 1.5                # Cauchy-Skala (Pixel der Stufe)
    tor: float = 12.0                 # größter Zuordnungsabstand (Pixel der Stufe)
    abstand: float = 3.0              # Abstand der Kantenpunkte (Pixel der Stufe)
    aussen: int = 4                   # Sichtbarkeitsdurchläufe
    innen: int = 3                    # LM-Schritte je Durchlauf
    hoechstens: int = 2500            # Kantenpunkte je Bild (nach der Sichtbarkeit)
    anteil_umriss: float = 0.6        # höchstens dieser Anteil innere Kanten wird verdrängt: Umriss zuerst


@dataclass
class Einstellungen:
    masken_gewicht: float = 1.0
    kanten_gewicht: float = 0.6
    umriss_auf_kanten: bool = True    # Umrisspunkte ohne Maske gegen Canny-Kanten
    korrelation: float = 2.0          # benachbarte Kantenpunkte sind abhängig: Gewicht / korrelation
    f_sigma_log: float | None = 0.15  # weiche Vorgabe für log f (None = frei)
    roll_sigma_grad: float | None = None
    lm_lambda: float = 1e-3
    tiefe_toleranz: float = 0.004     # relativ zur Tiefe
    gelenk_sigma_grad: float | None = None


@dataclass
class Zustand:
    theta: np.ndarray                 # alle Maße (absolut, Reihenfolge Ausgleich.namen)
    logf: dict                        # Gruppe -> log f
    kameras: list
    winkel: list

    def kopie(self):
        return Zustand(self.theta.copy(), dict(self.logf), [k.kopie() for k in self.kameras],
                       [None if w is None else np.array(w, float) for w in self.winkel])


class Ausgleich:
    def __init__(self, netze, ansichten, theta, frei, vorgaben=None, f_start=None, einstellungen=None,
                 protokoll=print, grenzen=None):
        """netze: {Name: ParamNetz}; theta: {Maß: Startwert} für alle Maße aller Netze; frei: einzupassende Maße;
        vorgaben: {Maß: (Mittel, Sigma)} weiche Vorgaben; f_start: {Gruppe: f in Pixeln} (sonst aus den Kameras)."""
        self.netze = netze
        self.ansichten = list(ansichten)
        self.e = einstellungen or Einstellungen()
        self.log = protokoll or (lambda *a, **k: None)
        namen = []
        for n in netze.values():
            for k in n.parameter:
                if k not in namen:
                    namen.append(k)
        for k, v in theta.items():
            if k not in namen and isinstance(v, (int, float)) and not isinstance(v, bool):
                namen.append(k)
        self.namen = namen
        self.frei = [k for k in frei if k in namen]
        self.vorgaben = dict(vorgaben or {})
        self.grenzen = dict(grenzen or {})          # harte Grenzen je Maß (unten, oben), z. B. Rand >= 5 mm
        self.f_gruppen = sorted({a.f_gruppe for a in self.ansichten if a.f_gruppe is not None})
        f0 = dict(f_start or {})
        for a in self.ansichten:
            if a.f_gruppe is not None and a.f_gruppe not in f0:
                f0[a.f_gruppe] = a.kamera.f
        self.f_vorgabe = {g: math.log(f0[g]) for g in self.f_gruppen}
        th = np.array([float(theta[k]) if k in theta else self._netz_wert(k) for k in namen])
        self.z = Zustand(th, dict(self.f_vorgabe), [a.kamera.kopie() for a in self.ansichten],
                         [None if a.winkel is None else np.array(a.winkel, float) for a in self.ansichten])
        for i, a in enumerate(self.ansichten):
            if a.f_gruppe is not None:
                self.z.kameras[i].f = math.exp(self.z.logf[a.f_gruppe])
        # Spalten: Maße, Brennweiten, je Bild Lage + Gelenke
        self.k = len(self.frei)
        self.nf = len(self.f_gruppen)
        self.spalte_f = {g: self.k + i for i, g in enumerate(self.f_gruppen)}
        self.spalte_bild = []
        c = self.k + self.nf
        for a in self.ansichten:
            self.spalte_bild.append(c)
            c += 6 + len(a.winkel_frei)
        self.n_unbekannt = c
        # Abbildung Netz-Parameter -> globale Spalte
        self.netz_spalten = {}
        for name, n in netze.items():
            idx_global = np.array([namen.index(k) for k in n.parameter], int)
            frei_spalte = np.array([self.frei.index(k) if k in self.frei else -1 for k in n.parameter], int)
            self.netz_spalten[name] = (idx_global, frei_spalte)
        self.zeichner = {name: fuer_netz(n) for name, n in netze.items()}
        self.proben = [None] * len(self.ansichten)
        self.zeiten = dict(sichtbarkeit=0.0, auswertung=0.0, loesen=0.0, bildstufen=0.0)
        self.verlauf = []

    def _netz_wert(self, k):
        for n in self.netze.values():
            if k in n.parameter:
                return n.theta0[n.parameter.index(k)]
        raise KeyError(k)

    def theta_dict(self, z=None):
        z = z or self.z
        return {k: float(v) for k, v in zip(self.namen, z.theta)}

    def _theta_netz(self, z, name):
        idx, _ = self.netz_spalten[name]
        return z.theta[idx]

    # ------------------------------------------------------------------ Sichtbarkeit
    def sichtbarkeit(self, plan, z=None, nur=None):
        z = z or self.z
        t0 = time.perf_counter()
        for i, a in enumerate(self.ansichten):
            if nur is not None and i not in nur:
                continue
            netz = self.netze[a.netz]
            st = a.bild.stufe(plan.breite)
            cam = z.kameras[i]
            th = self._theta_netz(z, a.netz)
            V = netz.ecken(th, z.winkel[i])
            zr = self.zeichner[a.netz]
            zr.setze(V)
            tiefe = zr.tiefe(cam, st.s, (st.breite, st.hoehe))
            P = netz.kanten_proben(V, cam, st.s, plan.abstand, 60 * plan.hoechstens)
            if P is None:
                self.proben[i] = None
                continue
            u, zz = P["u"], P["z"]
            ix = np.clip(u[:, 0].astype(int), 0, st.breite - 1)
            iy = np.clip(u[:, 1].astype(int), 0, st.hoehe - 1)
            # sichtbar, wenn in der 3x3-Nachbarschaft nichts deutlich davor liegt (Hintergrund = 0 zählt als fern)
            t_fern = np.where(tiefe > 0, tiefe, 1e9).astype(np.float32)
            import cv2
            t_max = cv2.dilate(t_fern, np.ones((3, 3), np.uint8))
            sicht = t_max[iy, ix] >= zz * (1 - self.e.tiefe_toleranz) - 1.0
            # Umriss nach außen: auf einer Seite der Kante ist im Modellbild nichts
            nrm = np.stack([-P["richtung"][:, 1], P["richtung"][:, 0]], 1)
            bedeckt = tiefe > 0
            def bei(off):
                q = u + off
                jx = np.clip(q[:, 0].astype(int), 0, st.breite - 1)
                jy = np.clip(q[:, 1].astype(int), 0, st.hoehe - 1)
                return bedeckt[jy, jx]
            plus, minus = bei(2.5 * nrm), bei(-2.5 * nrm)
            aussen = P["umriss"] & (plus != minus)
            vorzeichen = np.where(~plus, 1.0, -1.0)
            ok = sicht & ~st.ignoriert(u)
            keep = self._auswahl(np.flatnonzero(ok & aussen), np.flatnonzero(ok & ~aussen), plan)
            ids = np.unique(np.concatenate([P["a"][keep], P["b"][keep]]))
            ia = np.searchsorted(ids, P["a"][keep])
            ib = np.searchsorted(ids, P["b"][keep])
            sp = P["s"][keep].astype(np.float32)
            dX0 = ((1 - sp)[:, None, None] * netz.D[P["a"][keep]] + sp[:, None, None] * netz.D[P["b"][keep]])
            maske_da = st.kanaele[0] is not None
            typ = np.where(aussen[keep] & maske_da, 0, 1)
            if not self.e.umriss_auf_kanten:
                typ = np.where(aussen[keep] & ~maske_da, -1, typ)
            self.proben[i] = dict(ids=ids, ia=ia, ib=ib, s=sp, dX0=dX0, typ=typ, vz=vorzeichen[keep],
                                  gelenk=netz.punkt_gelenk[P["a"][keep]], stufe=st, n=len(keep))
        self.zeiten["sichtbarkeit"] += time.perf_counter() - t0

    @staticmethod
    def _auswahl(umriss, innen, plan):
        """Höchstens plan.hoechstens Punkte, Umrisspunkte zuerst (bis anteil_umriss), gleichmäßig ausgedünnt."""
        n = plan.hoechstens
        nu = min(len(umriss), max(int(n * plan.anteil_umriss), n - len(innen)))
        ni = min(len(innen), n - nu)
        def duenn(idx, k):
            if k >= len(idx):
                return idx
            return idx[np.linspace(0, len(idx) - 1, k).astype(int)]
        return np.sort(np.concatenate([duenn(umriss, nu), duenn(innen, ni)]))

    # ------------------------------------------------------------------ Auswertung
    def _ansicht(self, i, z, plan, jacobi):
        a = self.ansichten[i]
        P = self.proben[i]
        if P is None or P["n"] == 0:
            return None
        netz = self.netze[a.netz]
        st = P["stufe"]
        cam = z.kameras[i]
        th = self._theta_netz(z, a.netz)
        W = z.winkel[i]
        Vt = netz.ecken_teil(P["ids"], th, W)
        Va, Vb = Vt[P["ia"]], Vt[P["ib"]]
        sp = P["s"][:, None]
        X = (1 - sp) * Va + sp * Vb
        s = st.s
        Xk = X @ cam.R.T + cam.t
        z_ = np.maximum(Xk[:, 2], 1e-3)
        u = np.stack([cam.f * Xk[:, 0] / z_ + cam.cx, cam.f * Xk[:, 1] / z_ + cam.cy], 1) * s
        ua, _ = cam.projiziere(Va, s)
        ub, _ = cam.projiziere(Vb, s)
        d = ub - ua
        d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        n = np.stack([-d[:, 1], d[:, 0]], 1)
        typ = P["typ"]
        r = np.zeros(len(u))
        dist = np.full(len(u), 1e6)
        gew = np.zeros(len(u))
        m0 = typ == 0
        if m0.any():
            n[m0] *= P["vz"][m0, None]
            q, dd = st.kanaele[0].suche(u[m0])
            r[m0] = np.einsum("ij,ij->i", n[m0], u[m0] - q) - st.kantenversatz(q, n[m0])
            dist[m0] = dd
            gew[m0] = self.e.masken_gewicht
        m1 = typ == 1
        if m1.any() and st.kanten is not None:
            kan = st.kanal_fuer(n[m1])
            idx = np.flatnonzero(m1)
            for c in np.unique(kan):
                sel = idx[kan == c]
                q, dd = st.kanaele[c].suche(u[sel])
                r[sel] = np.einsum("ij,ij->i", n[sel], u[sel] - q)
                dist[sel] = dd
            gew[m1] = self.e.kanten_gewicht
        gew *= a.gewicht / self.e.korrelation
        innen = dist < plan.tor
        rt = r / plan.sigma
        rho = np.where(innen, 0.5 * np.log1p(rt * rt), 0.5 * math.log1p((plan.tor / plan.sigma) ** 2))
        kosten = float((gew * rho).sum())
        out = dict(kosten=kosten, r=r, innen=innen, gew=gew, n=len(r), u=u)
        if not jacobi:
            return out
        w_irls = gew * innen / (1 + rt * rt)
        # Ableitung des Skalarresiduums: a = n^T du/dXk (Stufe s)
        Jp, Jf = projektion_ableitung(Xk, cam.f)
        av = np.einsum("ni,nij->nj", n, Jp) * s                 # (n, 3)
        cols = []
        # Maße
        _, frei_spalte = self.netz_spalten[a.netz]
        dX = P["dX0"]
        g_pkt = P["gelenk"]
        if W is not None and len(netz.gelenke):
            dX = dX.astype(np.float64).copy()
            for g, gel in enumerate(netz.gelenke):
                m = g_pkt == g
                if m.any() and W[g]:
                    from .modell import drehung
                    Rg = drehung(gel.richtung, float(W[g]))
                    dX[m] = np.einsum("ij,njk->nik", Rg, dX[m])
                    for kname, dp in gel.punkt_ableitung.items():
                        if kname in netz.parameter:
                            j = netz.parameter.index(kname)
                            dX[m, :, j] += (np.eye(3) - Rg) @ np.asarray(dp, float)
        aw = av @ cam.R                                       # (n, 3): Ableitung nach Weltpunkt
        J_theta_netz = np.einsum("nj,njk->nk", aw, dX)          # (n, k_netz)
        spalten_idx, bloecke = [], []
        sel = frei_spalte >= 0
        if sel.any():
            spalten_idx.append(frei_spalte[sel])
            bloecke.append(J_theta_netz[:, sel])
        if a.f_gruppe is not None:
            spalten_idx.append(np.array([self.spalte_f[a.f_gruppe]]))
            bloecke.append((np.einsum("ni,ni->n", n, Jf) * s)[:, None])
        c0 = self.spalte_bild[i]
        J_rot = np.cross(Xk, av)                               # a^T (-[Xk]x)
        bl = [J_rot, av]
        if a.winkel_frei:
            for g in a.winkel_frei:
                gel = netz.gelenke[g]
                ax = np.asarray(gel.richtung, float)
                ax = ax / np.linalg.norm(ax)
                p = netz.gelenk_punkt(g, th)
                dW = np.where((g_pkt == g)[:, None], np.cross(ax, X - p), 0.0) * GRAD
                bl.append(np.einsum("nj,nj->n", aw, dW)[:, None])
        spalten_idx.append(np.arange(c0, c0 + 6 + len(a.winkel_frei)))
        bloecke.append(np.concatenate(bl, 1))
        J = np.concatenate(bloecke, 1) / plan.sigma
        out.update(J=J, spalten=np.concatenate(spalten_idx), w=w_irls, rt=rt)
        return out

    def _vorgaben(self, z, jacobi):
        """Weiche Vorgaben: Maße, Brennweiten, Rollwinkel, Gelenke. Liefert Kosten und (H, g)-Beiträge."""
        kosten = 0.0
        H = np.zeros((self.n_unbekannt, self.n_unbekannt)) if jacobi else None
        g = np.zeros(self.n_unbekannt) if jacobi else None
        for k, (mu, sig) in self.vorgaben.items():
            if k not in self.frei:
                continue
            j = self.frei.index(k)
            r = (z.theta[self.namen.index(k)] - mu) / sig
            kosten += 0.5 * r * r
            if jacobi:
                H[j, j] += 1 / sig ** 2
                g[j] += r / sig
        if self.e.f_sigma_log:
            for grp in self.f_gruppen:
                r = (z.logf[grp] - self.f_vorgabe[grp]) / self.e.f_sigma_log
                kosten += 0.5 * r * r
                if jacobi:
                    c = self.spalte_f[grp]
                    H[c, c] += 1 / self.e.f_sigma_log ** 2
                    g[c] += r / self.e.f_sigma_log
        if self.e.roll_sigma_grad:
            sig = math.sin(self.e.roll_sigma_grad * GRAD)
            for i, cam in enumerate(z.kameras):
                r = cam.R[0, 2] / sig
                kosten += 0.5 * r * r
                if jacobi:
                    # d R[0,2] / d dw = ([e_k]x R)[0, 2]
                    Jr = np.array([np.cross(e, cam.R[:, 2])[0] for e in np.eye(3)]) / sig
                    c = self.spalte_bild[i]
                    H[c:c + 3, c:c + 3] += np.outer(Jr, Jr)
                    g[c:c + 3] += Jr * r
        if self.e.gelenk_sigma_grad:
            sig = self.e.gelenk_sigma_grad
            for i, a in enumerate(self.ansichten):
                for jj, gi in enumerate(a.winkel_frei):
                    r = (z.winkel[i][gi] - a.winkel[gi]) / sig
                    kosten += 0.5 * r * r
                    if jacobi:
                        c = self.spalte_bild[i] + 6 + jj
                        H[c, c] += 1 / sig ** 2
                        g[c] += r / sig
        return kosten, H, g

    def kosten(self, z, plan):
        t0 = time.perf_counter()
        s = 0.0
        for i in range(len(self.ansichten)):
            o = self._ansicht(i, z, plan, False)
            if o is not None:
                s += o["kosten"]
        s += self._vorgaben(z, False)[0]
        self.zeiten["auswertung"] += time.perf_counter() - t0
        return s

    def normalgleichungen(self, z, plan):
        t0 = time.perf_counter()
        kosten, H, g = self._vorgaben(z, True)
        stat = []
        for i in range(len(self.ansichten)):
            o = self._ansicht(i, z, plan, True)
            if o is None:
                stat.append(None)
                continue
            kosten += o["kosten"]
            J, w, rt, c = o["J"], o["w"], o["rt"], o["spalten"]
            Jw = J * w[:, None]
            H[np.ix_(c, c)] += Jw.T @ J
            g[c] += Jw.T @ rt
            stat.append(o)
        self.zeiten["auswertung"] += time.perf_counter() - t0
        return kosten, H, g, stat

    def anwenden(self, z, dx):
        zn = z.kopie()
        for j, k in enumerate(self.frei):
            i = self.namen.index(k)
            zn.theta[i] += dx[j]
            if k in self.grenzen:
                lo, hi = self.grenzen[k]
                zn.theta[i] = min(max(zn.theta[i], lo), hi)
        for grp in self.f_gruppen:
            zn.logf[grp] += dx[self.spalte_f[grp]]
        for i, a in enumerate(self.ansichten):
            c = self.spalte_bild[i]
            cam = zn.kameras[i].schritt(dx[c:c + 3], dx[c + 3:c + 6])
            if a.f_gruppe is not None:
                cam.f = math.exp(zn.logf[a.f_gruppe])
            zn.kameras[i] = cam
            for jj, gi in enumerate(a.winkel_frei):
                zn.winkel[i][gi] += dx[c + 6 + jj]
        return zn

    # ------------------------------------------------------------------ Lösen
    def loese(self, plaene, nur_kameras=False, kameras_fest=False):
        """Stufen grob -> fein. nur_kameras: Maße fest; kameras_fest: Lagen und Brennweiten fest (nur Maße und
        Gelenke)."""
        lam = self.e.lm_lambda
        for plan in plaene:
            t0 = time.perf_counter()
            for b in {id(a.bild): a.bild for a in self.ansichten}.values():
                b.stufe(plan.breite)
            self.zeiten["bildstufen"] += time.perf_counter() - t0
            for durchlauf in range(plan.aussen):
                self.sichtbarkeit(plan)
                for _ in range(plan.innen):
                    kosten, H, g, _ = self.normalgleichungen(self.z, plan)
                    t1 = time.perf_counter()
                    gesperrt = np.zeros(self.n_unbekannt, bool)
                    if nur_kameras:
                        gesperrt[:self.k] = True
                    if kameras_fest:
                        gesperrt[self.k:self.k + self.nf] = True
                        for c in self.spalte_bild:
                            gesperrt[c:c + 6] = True
                    for i, a in enumerate(self.ansichten):
                        if self.proben[i] is None or self.proben[i]["n"] < 8:
                            gesperrt[self.spalte_bild[i]:self.spalte_bild[i] + 6 + len(a.winkel_frei)] = True
                    frei = ~gesperrt
                    Hf, gf = H[np.ix_(frei, frei)], g[frei]
                    diag = np.maximum(np.diag(Hf), 1e-9 * max(np.diag(Hf).max(), 1.0))
                    ok = False
                    for _versuch in range(6):
                        try:
                            dxf = -np.linalg.solve(Hf + lam * np.diag(diag), gf)
                        except np.linalg.LinAlgError:
                            lam *= 10
                            continue
                        dx = np.zeros(self.n_unbekannt)
                        dx[frei] = dxf
                        zn = self.anwenden(self.z, dx)
                        self.zeiten["loesen"] += time.perf_counter() - t1
                        kn = self.kosten(zn, plan)
                        t1 = time.perf_counter()
                        if kn < kosten:
                            self.z = zn
                            lam = max(lam / 3, 1e-7)
                            ok = True
                            break
                        lam *= 4
                    self.zeiten["loesen"] += time.perf_counter() - t1
                    self.verlauf.append(dict(breite=plan.breite, kosten=kosten, lam=lam, ok=ok))
                    if not ok:
                        break
        return self.z

    def loese_einzeln(self, plaene, f_frei=True, nur=None):
        """Nur Kameras (und Gelenke), jedes Bild mit eigenem LM-Schritt und eigener Dämpfung: bei festen Maßen sind
        die Bilder unabhängig, ein schlechtes Bild bremst die anderen nicht. Eine Brennweite wird mit eingepasst,
        wenn ihre Gruppe nur dieses eine Bild enthält (f_frei)."""
        nv = len(self.ansichten)
        nur = list(range(nv)) if nur is None else list(nur)
        gruppen_zahl = {}
        for a in self.ansichten:
            gruppen_zahl[a.f_gruppe] = gruppen_zahl.get(a.f_gruppe, 0) + 1
        lam = {i: self.e.lm_lambda for i in nur}
        for plan in plaene:
            t0 = time.perf_counter()
            for i in nur:
                self.ansichten[i].bild.stufe(plan.breite)
            self.zeiten["bildstufen"] += time.perf_counter() - t0
            for durchlauf in range(plan.aussen):
                self.sichtbarkeit(plan, nur=nur)
                aktiv = {i: self.proben[i] is not None and self.proben[i]["n"] >= 8 for i in nur}
                for _ in range(plan.innen):
                    for i in nur:
                        if not aktiv[i]:
                            continue
                        a = self.ansichten[i]
                        t1 = time.perf_counter()
                        kv, Hv, gv = self._vorgaben(self.z, True)
                        o = self._ansicht(i, self.z, plan, True)
                        self.zeiten["auswertung"] += time.perf_counter() - t1
                        if o is None:
                            aktiv[i] = False
                            continue
                        c0 = self.spalte_bild[i]
                        lokal = list(range(c0, c0 + 6 + len(a.winkel_frei)))
                        if f_frei and a.f_gruppe is not None and gruppen_zahl[a.f_gruppe] == 1:
                            lokal.append(self.spalte_f[a.f_gruppe])
                        sel = np.isin(o["spalten"], lokal)
                        cl = o["spalten"][sel]
                        J = o["J"][:, sel]
                        Jw = J * o["w"][:, None]
                        H = Jw.T @ J + Hv[np.ix_(cl, cl)]
                        g = Jw.T @ o["rt"] + gv[cl]
                        k_alt = o["kosten"] + kv
                        diag = np.maximum(np.diag(H), 1e-9 * max(np.diag(H).max(), 1.0))
                        ok = False
                        for _versuch in range(6):
                            try:
                                d = -np.linalg.solve(H + lam[i] * np.diag(diag), g)
                            except np.linalg.LinAlgError:
                                lam[i] *= 10
                                continue
                            dx = np.zeros(self.n_unbekannt)
                            dx[cl] = d
                            zn = self.anwenden(self.z, dx)
                            t1 = time.perf_counter()
                            on = self._ansicht(i, zn, plan, False)
                            k_neu = (on["kosten"] if on else 0.0) + self._vorgaben(zn, False)[0]
                            self.zeiten["auswertung"] += time.perf_counter() - t1
                            if k_neu < k_alt:
                                self.z = zn
                                lam[i] = max(lam[i] / 3, 1e-7)
                                ok = True
                                break
                            lam[i] *= 4
                        if not ok:
                            aktiv[i] = False
        return self.z

    def raster_gelenk(self, i, g, werte, plan):
        """Gelenk g in Ansicht i auf den besten der Werte setzen (mittlere robuste Kosten aller Kantenpunkte der
        Ansicht, Kamera fest). Für Gelenke mit vielen Nebenminima (Lenkrollen, Klappen)."""
        a = self.ansichten[i]
        st = a.bild.stufe(plan.breite)
        bestes = None
        for w in werte:
            z = self.z.kopie()
            z.winkel[i][g] = w
            self.sichtbarkeit(plan, z=z, nur=[i])
            o = self._ansicht(i, z, plan, False)
            if o is None:
                continue
            m = self.proben[i]["gelenk"] == g
            if m.sum() < 5:
                continue
            k = o["kosten"] / max(o["gew"].sum(), 1e-9)
            if bestes is None or k < bestes[0]:
                bestes = (k, w)
        if bestes is not None:
            self.z.winkel[i][g] = bestes[1]
        return bestes

    def iou(self, i, plan, z=None):
        """Überdeckung (IoU) von Modell und Bildmaske in Ansicht i (Stufe des Plans), ohne ignorierte Bereiche."""
        z = z or self.z
        a = self.ansichten[i]
        st = a.bild.stufe(plan.breite)
        if st.weich is None:
            return float("nan")
        netz = self.netze[a.netz]
        V = netz.ecken(self._theta_netz(z, a.netz), z.winkel[i])
        zr = self.zeichner[a.netz]
        zr.setze(V)
        m = zr.tiefe(z.kameras[i], st.s, (st.breite, st.hoehe)) > 0
        f = st.weich >= 0.5
        g = np.ones_like(f) if st.ignorieren is None else ~st.ignorieren
        return float((m & f & g).sum() / max(((m | f) & g).sum(), 1))

    # ------------------------------------------------------------------ Kennzahlen
    def bericht(self, plan):
        """Je Bild: Zahl der Punkte, Anteil zugeordnet, RMS (Pixel der Stufe) der zugeordneten Punkte."""
        self.sichtbarkeit(plan)
        out = []
        for i, a in enumerate(self.ansichten):
            o = self._ansicht(i, self.z, plan, False)
            if o is None:
                out.append(dict(name=a.bild.name, n=0))
                continue
            r, m = o["r"], o["innen"]
            out.append(dict(name=a.bild.name, n=int(o["n"]), zugeordnet=float(m.mean()),
                            rms=float(np.sqrt(np.mean(r[m] ** 2))) if m.any() else float("nan"),
                            median=float(np.median(np.abs(r[m]))) if m.any() else float("nan")))
        return out

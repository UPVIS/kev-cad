"""Unsicherheit: Kovarianz aus J^T W J, Sigma je Maß, und Empfehlungen, was die Unsicherheit am stärksten senkt.

- Kovarianz: Normalgleichungen am Ergebnis (robuste Gewichte, Vorgaben eingerechnet), Bildteil mit der geschätzten
  Streuung der zugeordneten Kantenpunkte skaliert. Die Gewichte enthalten schon den Korrelationsfaktor
  (benachbarte Kantenpunkte sind nicht unabhängig), sonst wären die Sigmas zu optimistisch.
- Nachmessen: Für jedes freie Maß die bedingte Kovarianz, wenn genau dieses Maß von Hand gemessen (fest) wäre.
  Empfohlen wird das Maß, das die Summe der Varianzen aller Maße am meisten senkt.
- Zusätzliche Aufnahme: virtuelle Kameras rundherum (gleicher Abstand und gleiche Brennweite wie die vorhandenen),
  je Richtung die Information der sichtbaren Kanten über die Maße, die eigene Lage herausgerechnet (Schur-Komplement).
  Empfohlen wird die Richtung mit der größten Senkung.
- Einrasten: ein Maß auf ein Raster oder eine Liste üblicher Werte setzen, wenn der Wert innerhalb einer Sigma liegt.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .kamera import Kamera, blick, projektion_ableitung


def kovarianz(A, plan):
    """Kovarianz aller freien Unbekannten am aktuellen Zustand; Rückgabe dict mit sigma je Maß (mm), Kovarianz der
    Maße, Streuung der Kantenpunkte (Pixel der Stufe) und Spaltenauswahl."""
    A.sichtbarkeit(plan)
    kosten, H, g, stat = A.normalgleichungen(A.z, plan)
    _, Hp, _ = A._vorgaben(A.z, True)
    reste, gew = [], []
    for o in stat:
        if o is None:
            continue
        m = o["innen"]
        reste.append(o["r"][m])
        gew.append(o["gew"][m])
    r = np.concatenate(reste) if reste else np.zeros(1)
    sigma_px = 1.4826 * float(np.median(np.abs(r))) if len(r) > 10 else plan.sigma
    skala = (sigma_px / plan.sigma) ** 2
    Himg = (H - Hp) / max(skala, 1e-6)
    Ht = Himg + Hp
    frei = np.diag(Ht) > 1e-12
    for i, a in enumerate(A.ansichten):
        if A.proben[i] is None or A.proben[i]["n"] < 8:
            frei[A.spalte_bild[i]:A.spalte_bild[i] + 6 + len(a.winkel_frei)] = False
    idx = np.flatnonzero(frei)
    C = np.full((A.n_unbekannt, A.n_unbekannt), np.nan)
    Hf = Ht[np.ix_(idx, idx)]
    Cf = np.linalg.pinv(Hf, rcond=1e-12)
    C[np.ix_(idx, idx)] = Cf
    k = A.k
    Cm = C[:k, :k]
    sig = {name: float(math.sqrt(max(Cm[j, j], 0.0))) if np.isfinite(Cm[j, j]) else float("inf")
           for j, name in enumerate(A.frei)}
    return dict(sigma=sig, kov_masse=Cm, kov=C, sigma_px=sigma_px, H_bild=Himg, H_vorgabe=Hp, frei=frei)


def nachmessen(kov, namen):
    """Je Maß: Summe der Varianzen aller Maße, wenn dieses Maß exakt bekannt wäre. Rückgabe sortiert, bestes zuerst:
    Liste (Maß, Varianz vorher, nachher, neue Sigmas)."""
    C = kov["kov_masse"]
    vorher = float(np.nansum(np.diag(C)))
    out = []
    for j, name in enumerate(namen):
        cjj = C[j, j]
        if not np.isfinite(cjj) or cjj <= 0:
            continue
        Cn = C - np.outer(C[:, j], C[j, :]) / cjj
        neu = {n: float(math.sqrt(max(Cn[i, i], 0.0))) for i, n in enumerate(namen)}
        out.append((name, vorher, float(np.nansum(np.diag(Cn))), neu))
    return sorted(out, key=lambda t: t[2])


def _info_virtuell(A, netz_name, kam, theta_netz, winkel, plan, sigma_px, frei_spalte):
    """Information über die freien Maße aus einer virtuellen Ansicht (Lage als Störgröße herausgerechnet)."""
    netz = A.netze[netz_name]
    V = netz.ecken(theta_netz, winkel)
    zr = A.zeichner[netz_name]
    zr.setze(V)
    s = plan.breite / kam.w
    br, ho = plan.breite, round(kam.h * s)
    tiefe = zr.tiefe(kam, s, (br, ho))
    P = netz.kanten_proben(V, kam, s, plan.abstand, 60 * plan.hoechstens)
    if P is None:
        return None
    u, z = P["u"], P["z"]
    ix = np.clip(u[:, 0].astype(int), 0, br - 1)
    iy = np.clip(u[:, 1].astype(int), 0, ho - 1)
    t_max = cv2.dilate(np.where(tiefe > 0, tiefe, 1e9).astype(np.float32), np.ones((3, 3), np.uint8))
    sicht = t_max[iy, ix] >= z * (1 - A.e.tiefe_toleranz) - 1.0
    nrm = np.stack([-P["richtung"][:, 1], P["richtung"][:, 0]], 1)
    bedeckt = tiefe > 0

    def bei(off):
        q = u + off
        return bedeckt[np.clip(q[:, 1].astype(int), 0, ho - 1), np.clip(q[:, 0].astype(int), 0, br - 1)]
    aussen = P["umriss"] & (bei(2.5 * nrm) != bei(-2.5 * nrm))
    keep = A._auswahl(np.flatnonzero(sicht & aussen), np.flatnonzero(sicht & ~aussen), plan)
    if len(keep) < 20:
        return None
    a_, b_, sp = P["a"][keep], P["b"][keep], P["s"][keep]
    X = (1 - sp[:, None]) * V[a_] + sp[:, None] * V[b_]
    dX = (1 - sp[:, None, None]) * netz.D[a_] + sp[:, None, None] * netz.D[b_]
    Xk = X @ kam.R.T + kam.t
    Jp, _ = projektion_ableitung(Xk, kam.f)
    n = nrm[keep]
    av = np.einsum("ni,nij->nj", n, Jp) * s
    aw = av @ kam.R
    Jt = np.einsum("nj,njk->nk", aw, dX)
    sel = frei_spalte >= 0
    Jm = np.zeros((len(keep), A.k))
    Jm[:, frei_spalte[sel]] = Jt[:, sel]
    Jl = np.concatenate([np.cross(Xk, av), av], 1)
    w = np.where(aussen[keep], A.e.masken_gewicht, A.e.kanten_gewicht) * 0.7 / A.e.korrelation / sigma_px ** 2
    Hmm = (Jm * w[:, None]).T @ Jm
    Hml = (Jm * w[:, None]).T @ Jl
    Hll = (Jl * w[:, None]).T @ Jl + 1e-9 * np.eye(6)
    return Hmm - Hml @ np.linalg.solve(Hll, Hml.T)


def aufnahme_empfehlen(A, kov, plan, richtungen=None, netz_name=None, winkel=None):
    """Bewertet virtuelle Zusatzaufnahmen. richtungen: Liste (Azimut, Höhe, Roll) in Grad; Abstand und Brennweite
    wie im Mittel der vorhandenen Kameras. Rückgabe sortiert (beste zuerst): (Richtung, Varianzsumme nachher)."""
    if richtungen is None:
        richtungen = [(az, el, 0.0) for el in (10, 35, 65) for az in range(0, 360, 30)]
    i0 = 0
    a0 = A.ansichten[i0]
    netz_name = netz_name or a0.netz
    netz = A.netze[netz_name]
    th = A._theta_netz(A.z, netz_name)
    winkel = A.z.winkel[i0] if winkel is None else winkel
    V = netz.ecken(th, winkel)
    mitte = (V.min(0) + V.max(0)) / 2
    abst = float(np.median([np.linalg.norm(k.zentrum - mitte) for k in A.z.kameras]))
    kam0 = A.z.kameras[i0]
    C = kov["kov_masse"]
    ok = np.isfinite(np.diag(C)) & (np.diag(C) > 0)
    Lam = np.zeros_like(C)
    Lam[np.ix_(ok, ok)] = np.linalg.pinv(C[np.ix_(ok, ok)])
    vorher = float(np.nansum(np.diag(C)))
    _, frei_spalte = A.netz_spalten[netz_name]
    out = []
    for az, el, roll in richtungen:
        R = blick(az, el, roll)
        Cz = mitte - abst * R[2]
        kam = Kamera(R=R, t=-R @ Cz, f=kam0.f, w=kam0.w, h=kam0.h)
        Hn = _info_virtuell(A, netz_name, kam, th, winkel, plan, kov["sigma_px"], frei_spalte)
        if Hn is None:
            continue
        Ln = Lam + Hn
        Cn = np.full_like(C, np.nan)
        Cn[np.ix_(ok, ok)] = np.linalg.pinv(Ln[np.ix_(ok, ok)])
        out.append(((az, el, roll), float(np.nansum(np.diag(Cn))), vorher,
                    {n: float(math.sqrt(max(Cn[j, j], 0))) for j, n in enumerate(A.frei) if ok[j]}))
    return sorted(out, key=lambda t: t[1])


def jackknife(A, plan, hoechstens=8, protokoll=None):
    """Streuung der Maße beim Weglassen je eines Bildes (Jackknife), warm gestartet am Ergebnis, nur die feinste
    Stufe. Erfasst, was die reine Statistik nicht sieht: Modellfehler und Eigenheiten einzelner Bilder.
    Rückgabe: {Maß: Sigma} oder None bei weniger als drei Bildern."""
    from .einpassen import Ansicht, Ausgleich
    n = len(A.ansichten)
    if n < 3:
        return None
    wahl = list(range(n)) if n <= hoechstens else list(np.linspace(0, n - 1, hoechstens).astype(int))
    theta0 = A.theta_dict()
    werte = []
    for i in wahl:
        ans = []
        for j, a in enumerate(A.ansichten):
            if j == i:
                continue
            ans.append(Ansicht(bild=a.bild, netz=a.netz, kamera=A.z.kameras[j].kopie(),
                               winkel=None if A.z.winkel[j] is None else A.z.winkel[j].copy(),
                               winkel_frei=a.winkel_frei, f_gruppe=a.f_gruppe))
        B = Ausgleich(A.netze, ans, theta0, frei=A.frei, vorgaben=A.vorgaben, einstellungen=A.e, protokoll=None,
                      grenzen=A.grenzen)
        B.z.logf.update({g: v for g, v in A.z.logf.items() if g in B.z.logf})
        for j, a in enumerate(B.ansichten):
            if a.f_gruppe:
                B.z.kameras[j].f = math.exp(B.z.logf[a.f_gruppe])
        B.loese([plan])
        werte.append([B.theta_dict()[k] for k in A.frei])
    W = np.array(werte)
    m = len(wahl)
    var = (n - 1) / n * ((W - W.mean(0)) ** 2).sum(0) * (n / m)
    return {k: float(math.sqrt(v)) for k, v in zip(A.frei, var)}


# Zuschläge, an der Küche gegen die fotocad-Referenz abgeglichen (BENCHMARK.md): die Abweichungen lagen beim
# 5- bis 18-Fachen der statistischen Sigma (Median) und beim 1,2- bis 2,7-Fachen der Jackknife-Sigma.
ZUSCHLAG_STAT = 8.0
ZUSCHLAG_JACK = 2.5


def sigma_gesamt(stat, jack=None):
    """Ehrliche Sigma je Maß: größer von ZUSCHLAG_JACK * Jackknife und ZUSCHLAG_STAT * statistischer Sigma."""
    return {k: max(ZUSCHLAG_STAT * stat[k], ZUSCHLAG_JACK * (jack or {}).get(k, 0.0)) for k in stat}


def einrasten(wert, sigma, raster=None, werte=None, faktor=1.0):
    """Nächster Rasterwert (z. B. 5 mm) oder Listenwert, wenn er innerhalb faktor * sigma liegt; sonst None."""
    kand = []
    if raster:
        kand.append(round(wert / raster) * raster)
    if werte:
        kand += list(werte)
    if not kand:
        return None
    best = min(kand, key=lambda v: abs(v - wert))
    return best if abs(best - wert) <= faktor * sigma else None

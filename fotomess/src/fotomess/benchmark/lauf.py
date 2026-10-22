"""Benchmark: Genauigkeit und Laufzeit gegen die Bildzahl, beide Prüfdatensätze, Vergleich mit fotocad.

    .venv/bin/python -m fotomess.benchmark.lauf kueche 1 2 3 5 10 22
    .venv/bin/python -m fotomess.benchmark.lauf fotocad 1 2 3 5
    .venv/bin/python -m fotomess.benchmark.lauf rollwagen 1 2 3 5 8 12
    .venv/bin/python -m fotomess.benchmark.lauf objectcapture 3 5 10
    .venv/bin/python -m fotomess.benchmark.lauf pruef 8
    .venv/bin/python -m fotomess.benchmark.lauf tabelle          # BENCHMARK.md aus den gespeicherten Ergebnissen
    .venv/bin/python -m fotomess.benchmark.lauf scarlett 1 2 3 5 8
    .venv/bin/python -m fotomess.benchmark.lauf scarlett_pruef_hoehe 8      # Breite frei, Höhe 47,5 fest
    .venv/bin/python -m fotomess.benchmark.lauf scarlett_pruef_tiefe 8      # Breite frei, Tiefe 117 fest
    .venv/bin/python -m fotomess.benchmark.lauf tabelle_scarlett

Ergebnisse je Lauf als JSON unter build/fotomess/benchmark/, Kontrollbilder unter build/fotomess/kontrolle/.
Laufzeiten ohne den einmaligen Modellaufbau (Netz mit Ableitungen, zwischengespeichert) und ohne das Laden der
Bilder; sie enthalten Grobsuche, Kandidaten, Kameras und Bündelausgleich.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parents[4]
AUSGABE = WURZEL / "build" / "fotomess"
ERG = AUSGABE / "benchmark"


def _speichere(name, d):
    ERG.mkdir(parents=True, exist_ok=True)
    (ERG / f"{name}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False, default=float))


def _lade(name):
    p = ERG / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ---------------------------------------------------------------------------------------------- Küche
def _kueche_einst():
    from ..einpassen import Einstellungen
    return Einstellungen(f_sigma_log=0.25, roll_sigma_grad=2.0)


def kueche_iou_eigen(N, theta, keys, kameras=None, winkel=None, nur_kameras=True):
    """Überdeckung des eigenen Modells (Maße theta) mit den Fotos keys; Kameras je Foto mit festen Maßen eingepasst
    (Start: gegebene oder Referenzkameras). Misst, wie gut die Maße die Fotos erklären, unabhängig von der
    Referenz."""
    from ..ablauf import standard_plaene
    from ..einpassen import Ansicht, Ausgleich
    from . import kueche as K
    P, kams, haube = K.referenz()
    E = K.eingaben(keys)
    ans = []
    for j, (e, k) in enumerate(zip(E, keys)):
        kam = kameras[j] if kameras else kams[k]
        w = winkel[j] if winkel else np.array([haube.get(k, 0.0)])
        ans.append(Ansicht(bild=e.bild, netz=e.netz, kamera=kam.kopie(), winkel=np.array(w, float), winkel_frei=e.winkel_frei,
                           f_gruppe=e.f_gruppe))
    A = Ausgleich(N, ans, dict(theta), frei=[], einstellungen=_kueche_einst(), f_start={k: a.kamera.f for k, a in zip(keys, ans)},
                  protokoll=None)
    pl = standard_plaene(E[0].bild.breite_arbeit)
    if nur_kameras:
        A.loese_einzeln(pl.buendel)
    return [A.iou(i, pl.buendel[-1]) for i in range(len(ans))]


def kueche(n, verfahren="fotomess"):
    from ..ablauf import kameras_finden, standard_plaene, vermessen
    from . import kueche as K
    keys = K.teilmenge(n)
    P, kams, haube = K.referenz()
    P0 = K.start_masse(P, K.ALLE)
    N = K.netze(P0, protokoll=None)
    E = K.eingaben(keys)
    frei = K.frei_fuer(keys)
    einst = _kueche_einst()
    vorg = {k: (P0[k], 60.0) for k in frei}
    if verfahren == "fotomess":
        erg = vermessen(N, E, {k: P0[k] for k in K.ALLE}, frei, vorgaben=vorg, einst=einst, protokoll=None)
        theta, kameras, winkel, zeiten = erg.theta, erg.kameras, erg.winkel, erg.zeiten
        namen = erg.namen
        from .. import unsicherheit as U
        t = time.perf_counter()
        kov = U.kovarianz(erg.ausgleich, erg.plaene.buendel[-1])
        jack = U.jackknife(erg.ausgleich, erg.plaene.buendel[-1])
        zeiten["unsicherheit"] = time.perf_counter() - t
        sigma = kov["sigma"]
        from ..kontrolle import kontrollbild
        for i, k in enumerate(namen[:3]):
            kontrollbild(erg.ausgleich, i, erg.plaene.buendel[-1], AUSGABE / "kontrolle" / f"kueche_{n}_{k}.jpg",
                         titel=f"Küche, {n} Foto(s): {k}")
    else:
        from . import fotocad_vergleich as FV
        from ..start import grobsuche
        t = time.perf_counter()
        starts = []
        for e in E:
            netz = N[e.netz]
            th = np.array([P0[k] for k in netz.parameter])
            g = grobsuche(netz, th, e.bild.maske, e.f, e.bild.breite, e.bild.hoehe, winkel=np.array(e.winkel),
                          hoehen=e.hoehen, beste=1)
            starts.append((e.bild, e.netz, g[0][1], np.array(e.winkel, float), bool(e.winkel_frei)))
        t_grob = time.perf_counter() - t
        r = FV.lauf(N, starts, {k: P0[k] for k in K.ALLE}, frei)
        theta, kameras, winkel = r["theta"], r["kameras"], r["winkel"]
        zeiten = dict(r["zeiten"], grobsuche=t_grob, gesamt=r["zeiten"]["gesamt"] + t_grob, auswertungen=r["auswertungen"])
        namen, sigma, jack = keys, {}, None
    idx = [keys.index(k) for k in namen]
    zeilen, fehler = K.bewerte(namen, theta, kameras, winkel, P, kams, haube, frei)
    iou_eigen = kueche_iou_eigen(N, theta, namen, kameras, winkel, nur_kameras=False)
    alle = list(K.ansichten())
    rest = [k for k in alle if k not in keys]
    iou_rest = kueche_iou_eigen(N, theta, rest) if rest else []
    iou_rest_ref = kueche_iou_eigen(N, P, rest) if rest else []
    iou_ref = K.iou_der_referenz(namen)
    d = dict(n=n, verfahren=verfahren, fotos=namen, frei=frei, zeiten=zeiten, kameras=zeilen,
             fehler_mm=fehler, start_fehler_mm={k: P0[k] - P[k] for k in frei},
             sigma_stat=sigma, sigma_jack=jack,
             iou_eigen=iou_eigen, iou_rest=iou_rest, iou_rest_referenzmasse=iou_rest_ref,
             iou_referenzkamera=[iou_ref[k] for k in namen],
             theta={k: theta[k] for k in frei})
    _speichere(f"kueche_{verfahren}_{n}", d)
    return d


# ---------------------------------------------------------------------------------------------- Rollwagen
def _rw_einst():
    from ..einpassen import Einstellungen
    return Einstellungen(f_sigma_log=0.15, roll_sigma_grad=15.0, kanten_gewicht=0.8)


RW_VORGABEN = {"rolle_h": (128, 30), "rahmen_h": (35, 15), "steg": (45, 20), "rand_h": (19, 8), "oeff_fase": (100, 30),
               "schraube_rand": (63, 15), "nachlauf": (26, 10), "rad_b": (32, 8), "eck_fase": (20, 10),
               "wagen_b": (410, 40), "rad_d": (100, 15)}


def rollwagen(n, zeiten_video=None, name=None, pruef=False, kontrolle=True):
    from .. import unsicherheit as U
    from ..ablauf import standard_plaene, vermessen
    from ..modelle import rollwagen as R
    from . import rollwagen as RW
    frei = RW.FREI + (RW.PRUEF_FREI if pruef else [])
    netz = RW.netz(frei=frei)
    t = time.perf_counter()
    B = RW.bilder(n, zeiten_video)
    t_bilder = time.perf_counter() - t
    f0, f35 = RW.f_vorgabe()
    E = RW.eingaben(B, f0)
    pl = standard_plaene(B[0].breite_arbeit, grob=270)
    vorg = {k: RW_VORGABEN[k] for k in frei}
    erg = vermessen({"rollwagen": netz}, E, dict(R.P), frei, vorgaben=vorg, einst=_rw_einst(), plaene=pl, kandidaten=4,
                    protokoll=None, grenzen=RW.GRENZEN)
    t = time.perf_counter()
    kov = U.kovarianz(erg.ausgleich, pl.buendel[-1])
    jack = U.jackknife(erg.ausgleich, pl.buendel[-1])
    nm = U.nachmessen(kov, erg.ausgleich.frei)
    richt = [(az, el, 0.0) for el in (10, 40, 70) for az in range(0, 360, 45)] + \
            [(az, -el, 180.0) for el in (20, 50) for az in range(0, 360, 45)]
    ae = U.aufnahme_empfehlen(erg.ausgleich, kov, pl.kameras[-1], richtungen=richt)
    t_unsicher = time.perf_counter() - t
    f = math.exp(list(erg.ausgleich.z.logf.values())[0])
    name = name or f"rollwagen_{'pruef_' if pruef else ''}{n}"
    if kontrolle:
        from ..kontrolle import kontrollbild
        for i, b in enumerate(erg.namen):
            kontrollbild(erg.ausgleich, i, pl.buendel[-1], AUSGABE / "kontrolle" / f"{name}_{b}.jpg",
                         titel=f"Rollwagen, {len(erg.namen)} Bild(er): {b}")
    d = dict(n=n, bilder=erg.namen, verworfen=erg.verworfen, iou_kameras=erg.iou_kameras, zeiten=erg.zeiten,
             t_bilder=t_bilder, t_unsicherheit=t_unsicher, f_px=f, f_vorgabe_px=f0, f35_meta=f35,
             theta={k: erg.theta[k] for k in frei}, sigma_stat=kov["sigma"], sigma_jack=jack, sigma_px=kov["sigma_px"],
             nachmessen=[(a, b, c) for a, b, c, _ in nm[:4]],
             aufnahme=[(list(a), b, c) for a, b, c, _ in ae[:4]],
             kameras=[k.als_dict() for k in erg.kameras], winkel=[list(map(float, w)) for w in erg.winkel],
             bericht=erg.ausgleich.bericht(pl.buendel[-1]))
    _speichere(name, d)
    return d


def objectcapture(n):
    """Kameras wie Apple Object Capture (anderer Agent, poses.json) als Vergleich: dieselben Videobilder, Lage nach
    Ähnlichkeitstransformation verglichen (Drehung aus den Blickrichtungen, Maßstab und Verschiebung aus den
    Kamerazentren)."""
    from ..kamera import log_so3
    pfad = Path.home() / "Library/Caches/de.upvis.kevcad.testdaten/rollwagen/poses.json"
    P = json.loads(pfad.read_text())
    cams = P["cameras"]
    # unter ihren Bildern dieselbe Auswahl wie sonst (Schärfe, Objekt ganz im Bild, über den Weg verteilt)
    from . import rollwagen as RW
    from .. import video
    k = RW.kennzahlen()
    tk = np.array([e["t"] for e in k])
    teil = []
    for c in cams:
        j = int(np.argmin(np.abs(tk - c["time_s"])))
        if abs(tk[j] - c["time_s"]) <= 0.1:
            teil.append(dict(k[j], t=round(c["time_s"], 3)))
    teil = sorted({e["t"]: e for e in teil}.values(), key=lambda e: e["t"])
    zeiten = [teil[i]["t"] for i in video.auswaehlen(teil, n)]
    d = rollwagen(n, zeiten_video=zeiten, name=f"objectcapture_{n}")
    d["objectcapture"] = oc_vergleich(d, cams)
    _speichere(f"objectcapture_{n}", d)
    return d


def oc_vergleich(d, cams):
    """Meine Kameras gegen die von Object Capture. Der Wagen ist um 180 Grad (Hochachse) symmetrisch; beide Lagen
    sind für das Messen gleichwertig, für den Vergleich wird je Bild die passende genommen."""
    from ..kamera import Kamera, log_so3
    S = np.diag([-1.0, -1.0, 1.0])
    mine, ihre = [], []
    for nm, kd in zip(d["bilder"], d["kameras"]):
        t = float(nm.rsplit("_", 1)[1])
        j = min(range(len(cams)), key=lambda i: abs(cams[i]["time_s"] - t))
        c = cams[j]["aligned"]["opencv"]
        mine.append(Kamera.aus_dict(kd))
        ihre.append((np.array(c["R"]), np.array(c["t"]), cams[j]["aligned"]["fx"] * 2160 / cams[j]["width"]))
    Q0 = ihre[0][0].T @ mine[0].R
    for i, k in enumerate(mine):
        Qa = ihre[i][0].T @ k.R
        Qb = ihre[i][0].T @ k.R @ S
        if np.linalg.norm(log_so3(Qb @ Q0.T)) < np.linalg.norm(log_so3(Qa @ Q0.T)):
            mine[i] = k.kopie(R=k.R @ S)              # gleiche Kamera, Objekt um 180 Grad gedreht
    # Q: mein Objektsystem -> ihr System; R_mein = R_ihr Q
    M = sum(Ro.T @ k.R for k, (Ro, to, fo) in zip(mine, ihre))
    U_, _, Vt = np.linalg.svd(M)
    Q = U_ @ np.diag([1, 1, np.linalg.det(U_ @ Vt)]) @ Vt
    Cm = np.array([Q @ k.zentrum for k in mine])
    Co = np.array([-Ro.T @ to for Ro, to, _ in ihre])
    if len(mine) >= 2:
        cm, co = Cm.mean(0), Co.mean(0)
        s = float(((Co - co) * (Cm - cm)).sum() / max(((Cm - cm) ** 2).sum(), 1e-9))
    else:
        cm, co, s = Cm.mean(0), Co.mean(0), 1.0
    rest = Co - (co + s * (Cm - cm))
    rot = [math.degrees(np.linalg.norm(log_so3(k.R @ Q.T @ Ro.T))) for k, (Ro, _, _) in zip(mine, ihre)]
    dist = [float(np.linalg.norm(c)) for c in Co]
    return dict(massstab=s, pos_rest_mm=[float(np.linalg.norm(r)) for r in rest], rot_grad=rot,
                abstand_mm=dist, f_ihre_px=[float(f) for _, _, f in ihre], f_meine_px=d["f_px"])


# ---------------------------------------------------------------------------------------------- Scarlett 2i2
def _sc_einst():
    from ..einpassen import Einstellungen
    return Einstellungen(f_sigma_log=0.15, roll_sigma_grad=15.0, kanten_gewicht=0.8)


# Prüfläufe: Breite frei, dafür ein anderes Maß fest (Name -> feste Werte). "hoehe": Herstellerhöhe 47,5 als
# Gehäusehöhe gelesen; "tiefe": Herstellertiefe 117 als Gehäusetiefe ohne Knöpfe gelesen (Gegenprobe zur Lesart
# „mit Knöpfen“).
SC_PRUEF = {"hoehe": {"hoehe": 47.5}, "tiefe": {"tiefe": 117.0}}


def scarlett(n, pruef=None, zeiten_video=None, name=None, kontrolle=True, jackknife=True):
    """Scarlett 2i2 aus n Videobildern. pruef: Schlüssel in SC_PRUEF (Breite frei, dieses Maß fest)."""
    from .. import unsicherheit as U
    from ..ablauf import standard_plaene, vermessen
    from ..modelle import scarlett as S
    from . import scarlett as SC
    fest = SC_PRUEF[pruef] if pruef else {}
    frei = [k for k in SC.FREI if k not in fest] + (["breite"] if pruef else [])
    netz = SC.netz(frei=SC.FREI + ["breite"])
    t = time.perf_counter()
    B = SC.bilder(n, zeiten_video)
    t_bilder = time.perf_counter() - t
    f0, f35 = SC.f_vorgabe()
    E = SC.eingaben(B, f0)
    pl = standard_plaene(B[0].breite_arbeit, grob=320)
    theta0 = dict(S.P, **fest)
    vorg = {k: SC.VORGABEN[k] for k in frei}
    erg = vermessen({"scarlett": netz}, E, theta0, frei, vorgaben=vorg, einst=_sc_einst(), plaene=pl, kandidaten=4,
                    protokoll=None, grenzen=SC.GRENZEN)
    t = time.perf_counter()
    kov = U.kovarianz(erg.ausgleich, pl.buendel[-1])
    jack = U.jackknife(erg.ausgleich, pl.buendel[-1]) if jackknife else None
    nm = U.nachmessen(kov, erg.ausgleich.frei)
    richt = [(az, el, 0.0) for el in (5, 30, 60, 85) for az in range(0, 360, 45)]
    ae = U.aufnahme_empfehlen(erg.ausgleich, kov, pl.kameras[-1], richtungen=richt)
    t_unsicher = time.perf_counter() - t
    f = math.exp(list(erg.ausgleich.z.logf.values())[0])
    name = name or f"scarlett_{'pruef_' + pruef + '_' if pruef else ''}{n}"
    bilder_pfade = []
    if kontrolle:
        from ..kontrolle import kontrollbild
        for i, b in enumerate(erg.namen):
            p = AUSGABE / "kontrolle" / f"{name}_{b}.jpg"
            kontrollbild(erg.ausgleich, i, pl.buendel[-1], p, titel=f"Scarlett, {len(erg.namen)} Bild(er): {b}")
            bilder_pfade.append(str(p))
    theta = {k: erg.theta[k] for k in SC.FREI + ["breite"]}
    d = dict(n=n, pruef=pruef, fest=fest, frei=frei, bilder=erg.namen, verworfen=erg.verworfen,
             iou_kameras=erg.iou_kameras, zeiten=erg.zeiten, t_bilder=t_bilder, t_unsicherheit=t_unsicher, f_px=f,
             f_vorgabe_px=f0, f35_meta=f35, theta=theta, gesamt=S.gesamt(theta), sigma_stat=kov["sigma"],
             sigma_jack=jack, sigma=U.sigma_gesamt(kov["sigma"], jack), sigma_px=kov["sigma_px"],
             nachmessen=[(a, b, c) for a, b, c, _ in nm[:4]], aufnahme=[(list(a), b, c) for a, b, c, _ in ae[:4]],
             kameras=[k.als_dict() for k in erg.kameras], kontrollbilder=bilder_pfade,
             bericht=erg.ausgleich.bericht(pl.buendel[-1]))
    _speichere(name, d)
    return d


def tabelle_scarlett():
    """Abschnitt für BENCHMARK.md aus den gespeicherten Läufen (fotomess und Object Capture)."""
    from . import scarlett as SC
    soll = SC.SOLL
    z = []

    def abw(ist, s):
        return f"{ist - s:+.1f} mm ({(ist - s) / s * 100:+.1f} %)"
    z.append("| Bilder (genutzt) | Laufzeit | f (px) | Gehäuse T × H | Gesamttiefe (mit Knöpfen) | kanten_r | knopf_h / gross_h | "
             "Tiefe 117 gegen Gesamttiefe | Höhe 47,5 gegen Gehäuse + Füße |")
    z.append("|---|---|---|---|---|---|---|---|---|")
    for n in (1, 2, 3, 5, 8):
        d = _lade(f"scarlett_{n}")
        if not d:
            continue
        th, sg, g = d["theta"], d["sigma"], d["gesamt"]
        z.append(f"| {n} ({len(d['bilder'])}) | {d['zeiten']['gesamt']:.1f} s | {d['f_px']:.0f} | "
                 f"{th['tiefe']:.1f} ± {sg['tiefe']:.1f} × {th['hoehe']:.1f} ± {sg['hoehe']:.1f} | {g['tiefe']:.1f} | "
                 f"{th['kanten_r']:.1f} ± {sg['kanten_r']:.1f} | {th['knopf_h']:.1f} ± {sg['knopf_h']:.1f} / "
                 f"{th['gross_h']:.1f} ± {sg['gross_h']:.1f} | {abw(g['tiefe'], soll['tiefe'])} | "
                 f"{abw(g['hoehe'], soll['hoehe'])} |")
    z.append("")
    for key in SC_PRUEF:
        for n in (5, 8):
            d = _lade(f"scarlett_pruef_{key}_{n}")
            if not d:
                continue
            th, sg = d["theta"], d["sigma"]
            fest = ", ".join(f"{k} = {v}" for k, v in d["fest"].items())
            z.append(f"- Prüflauf {n} Bilder ({len(d['bilder'])} genutzt), fest {fest}: Breite **{th['breite']:.1f} ± "
                     f"{sg['breite']:.1f} mm** (Soll 180, {abw(th['breite'], 180.0)}), Tiefe {th['tiefe']:.1f}, Höhe "
                     f"{th['hoehe']:.1f}, {d['zeiten']['gesamt']:.1f} s")
    z.append("")
    z.append("Object Capture (`kevcad-capture … --auflage --masz laenge=180`):\n")
    z.append("| Lauf | Bilder (ausgerichtet) | Object Capture | gesamt | Hülle L × B × H | obere Fläche | "
             "Deckelschicht L × B | B gegen 117 | H gegen 47,5 |")
    z.append("|---|---|---|---|---|---|---|---|---|")
    for lauf in ("scarlett_ganz", "scarlett_genau", "scarlett_umlauf", "scarlett_nah"):
        p = WURZEL / "build" / "capture" / lauf / "bericht.json"
        if not p.exists():
            continue
        b = json.loads(p.read_text())
        r = b["rekonstruktion"]
        h, g = b["huellmass_mm"], b["grundkoerper_mm"]
        tz = r["times"]
        gesamt = tz["reconstruction_s"] + tz.get("extraction_s", 0) + b["nachbearbeitung_s"]
        z.append(f"| {lauf} | {r['images']} ({r['posed']}) | {tz['reconstruction_s']:.0f} s | {gesamt:.0f} s | "
                 f"{h['laenge']:.1f} × {h['breite']:.1f} × {h['hoehe']:.1f} | {b.get('oberkante_mm') or float('nan'):.1f} | "
                 f"{g['laenge']:.1f} × {g['breite']:.1f} | {abw(h['breite'], 117.0)} | {abw(h['hoehe'], 47.5)} |")
    return "\n".join(z)


# ---------------------------------------------------------------------------------------------- Tabelle
def tabelle():
    zeilen = []
    zeilen.append("## Küche (Beelonia, Studiofotos auf Weiß)\n")
    zeilen.append("Start: alle 18 Maße um 3 bis 5 % verfälscht (mittlerer Fehler 25 mm), Kameras unbekannt. Referenz: "
                  "voller Bündelausgleich mit fotocad über alle 22 Fotos (selbst etwa ±1 cm unsicher, siehe README "
                  "der Küche).\n")
    zeilen.append("| Fotos | Verfahren | Laufzeit | Maße: mittl. Abweichung zur Referenz | Kameras: Drehung / Ort / f (Median) | "
                  "IoU eigenes Modell (eingepasste Fotos) | IoU übrige Fotos (eigene Maße / Referenzmaße) |")
    zeilen.append("|---|---|---|---|---|---|---|")
    for verf in ("fotomess", "fotocad"):
        for n in (1, 2, 3, 5, 10, 22):
            d = _lade(f"kueche_{verf}_{n}")
            if not d:
                continue
            fe = np.abs(list(d["fehler_mm"].values()))
            k = d["kameras"]
            rot = np.median([z["rot_grad"] for z in k])
            pos = np.median([z["pos_mm"] for z in k])
            fp = np.median([abs(z["f_prozent"]) for z in k])
            rest = (f"{np.mean(d['iou_rest']) * 100:.2f} / {np.mean(d['iou_rest_referenzmasse']) * 100:.2f} %"
                    if d["iou_rest"] else "–")
            zeilen.append(f"| {n} | {verf} | {d['zeiten']['gesamt']:.1f} s | {fe.mean():.1f} mm (max {fe.max():.0f}, "
                          f"{len(fe)} Maße) | {rot:.2f}° / {pos:.0f} mm / {fp:.1f} % | {np.mean(d['iou_eigen']) * 100:.2f} % | {rest} |")
    zeilen.append("")
    zeilen.append("")
    zeilen.append("Laufzeit fotomess je Schritt (s):\n")
    zeilen.append("| Fotos | Grobsuche | Kandidaten | Kameras | Bündel | gesamt | je Foto | Unsicherheit (mit Jackknife) |")
    zeilen.append("|---|---|---|---|---|---|---|---|")
    for n in (1, 2, 3, 5, 10, 22):
        d = _lade(f"kueche_fotomess_{n}")
        if d:
            z = d["zeiten"]
            zeilen.append(f"| {n} | {z['grobsuche']:.1f} | {z['kandidaten']:.1f} | {z['kameras']:.1f} | {z['buendel']:.1f} | "
                          f"{z['gesamt']:.1f} | {z['gesamt'] / n:.2f} | {z.get('unsicherheit', 0):.1f} |")
    from ..unsicherheit import sigma_gesamt
    zeilen.append("")
    zeilen.append("## Rollwagen (Video, echte Umgebung)\n")
    zeilen.append("Bekannt und fest: 610 × 410 mm, Räder Ø 100 mm. Sigma = größer von 2,5 × Jackknife und 8 × statistisch "
                  "(an der Küche abgeglichen). Brennweite gemeinsam für alle Bilder, Vorgabe aus den Metadaten 2796 px.\n")
    zeilen.append("| Bilder (genutzt) | Laufzeit | f (px) | rolle_h | rahmen_h | rand_h | rahmen_h + rand_h | steg | oeff_fase | "
                  "schraube_rand |")
    zeilen.append("|---|---|---|---|---|---|---|---|---|---|")
    for n in (1, 2, 3, 5, 8, 12, 20):
        d = _lade(f"rollwagen_{n}")
        if not d:
            continue
        sg = sigma_gesamt(d["sigma_stat"], d.get("sigma_jack"))

        def z(k):
            return f"{d['theta'][k]:.1f} ± {sg[k]:.1f}"
        summe = d["theta"]["rahmen_h"] + d["theta"]["rand_h"]
        zeilen.append(f"| {n} ({len(d['bilder'])}) | {d['zeiten']['gesamt']:.1f} s | {d['f_px']:.0f} | {z('rolle_h')} | "
                      f"{z('rahmen_h')} | {z('rand_h')} | {summe:.1f} | {z('steg')} | {z('oeff_fase')} | {z('schraube_rand')} |")
    p = _lade("rollwagen_pruef_8")
    if p:
        sg = sigma_gesamt(p["sigma_stat"], p.get("sigma_jack"))
        zeilen.append("")
        zeilen.append(f"Prüflauf (8 Bilder, nur 610 mm fest, Breite und Raddurchmesser mitgemessen): Breite "
                      f"{p['theta']['wagen_b']:.1f} ± {sg['wagen_b']:.1f} mm (Soll 410), Rad Ø {p['theta']['rad_d']:.1f} ± "
                      f"{sg['rad_d']:.1f} mm (Soll 100).")
    zeilen.append("")
    zeilen.append("Vergleich mit Apple Object Capture (gleiche Videobilder; Lage nach Ähnlichkeitstransformation):\n")
    zeilen.append("| Bilder | Laufzeit fotomess | f fotomess / Object Capture | Maßstab | Drehung (Median) | Ort (Median, Abstand 0,8 bis 1,2 m) |")
    zeilen.append("|---|---|---|---|---|---|")
    for n in (3, 5, 8, 10):
        d = _lade(f"objectcapture_{n}")
        if not d or "objectcapture" not in d:
            continue
        oc = d["objectcapture"]
        zeilen.append(f"| {len(d['bilder'])} | {d['zeiten']['gesamt']:.1f} s | {oc['f_meine_px']:.0f} / {np.mean(oc['f_ihre_px']):.0f} px | "
                      f"{oc['massstab']:.3f} | {np.median(oc['rot_grad']):.2f}° | {np.median(oc['pos_rest_mm']):.0f} mm |")
    return "\n".join(zeilen)


def main():
    teil = sys.argv[1]
    zahlen = [int(x) for x in sys.argv[2:]]
    for n in zahlen:
        from ..system import warte_auf_speicher
        warte_auf_speicher(25)
        t = time.perf_counter()
        if teil == "kueche":
            d = kueche(n, "fotomess")
        elif teil == "fotocad":
            d = kueche(n, "fotocad")
        elif teil == "rollwagen":
            d = rollwagen(n)
        elif teil == "pruef":
            d = rollwagen(n, pruef=True)
        elif teil == "objectcapture":
            d = objectcapture(n)
        elif teil == "scarlett":
            d = scarlett(n)
        elif teil.startswith("scarlett_pruef_"):
            d = scarlett(n, pruef=teil.removeprefix("scarlett_pruef_"))
        else:
            raise SystemExit(f"unbekannt: {teil}")
        print(f"{teil} {n}: fertig in {time.perf_counter() - t:.1f} s (Lauf {d['zeiten']['gesamt']:.1f} s)", flush=True)
    if teil == "tabelle":
        print(tabelle())
    if teil == "tabelle_scarlett":
        print(tabelle_scarlett())


if __name__ == "__main__":
    main()

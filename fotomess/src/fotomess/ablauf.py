"""Gesamtablauf: aus wenigen Bildern und einem parametrischen Netz die Kameras und Maße bestimmen.

1. Grobsuche je Bild (start.grobsuche, GPU-Atlas): einige verschiedene Startkameras.
2. Kandidaten: jede Startkamera mal jeden Startwinkel der freien Gelenke (z. B. Haube 45/70/95 Grad) als eigene
   Ansicht; alle zusammen kurz eingepasst (nur Kameras, jedes Bild für sich), je Bild gewinnt die beste Überdeckung.
3. Kameras je Bild verfeinern (Maße fest), dann der gemeinsame Ausgleich (Maße, Kameras, Brennweiten, Gelenke)
   grob -> fein.
4. Unsicherheit (unsicherheit.py) und Kontrollbilder.

Die Laufzeit wächst etwa linear mit der Bildzahl: alle Schritte außer dem Lösen der (kleinen) Normalgleichungen
arbeiten je Bild.
"""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field

import numpy as np

from .einpassen import Ansicht, Ausgleich, Einstellungen, Stufenplan
from .start import grobsuche


@dataclass
class Eingabe:
    bild: object
    netz: str
    f: float                                   # Vorgabe/Start der Brennweite (Originalpixel)
    f_gruppe: str | None = "gemeinsam"
    winkel: tuple | None = None                # Startwinkel der Gelenke (Grad)
    winkel_frei: tuple = ()
    winkel_starts: dict = field(default_factory=dict)   # Gelenk -> Liste von Startwinkeln für die Kandidaten
    hoehen: tuple | None = None                # Kamerahöhen (Grad) der Grobsuche
    rolls: tuple = (0.0,)
    azimute: tuple | None = None
    kamera: object = None                      # bekannte Startkamera (überspringt die Grobsuche)
    paare: tuple | None = None                 # (Höhe, Roll)-Paare der Grobsuche statt hoehen x rolls
    winkel_raster: dict = field(default_factory=dict)   # Gelenk -> Werte, nach der Kamerasuche einzeln abgetastet


@dataclass
class Plaene:
    kandidaten: list
    kameras: list
    buendel: list


def standard_plaene(breite, grob=370):
    """Stufen relativ zur Bildbreite der Arbeitskopie (z. B. 1476 bei Viertelgröße eines 24-MP-Fotos)."""
    b1, b2, b3 = grob, min(2 * grob, breite), breite
    return Plaene(
        kandidaten=[Stufenplan(b1, sigma=3.0, tor=25, abstand=2.0, aussen=2, innen=3, hoechstens=1200)],
        kameras=[Stufenplan(b1, sigma=3.0, tor=25, abstand=2.0, aussen=2, innen=4),
                 Stufenplan(b2, sigma=2.0, tor=12, abstand=2.5, aussen=3, innen=4)],
        buendel=[Stufenplan(b2, sigma=2.0, tor=12, abstand=2.5, aussen=3, innen=4),
                 Stufenplan(b3, sigma=1.5, tor=6, abstand=3.0, aussen=3, innen=4)])


def kameras_finden(netze, eingaben, theta, einst=None, plaene=None, kandidaten=2, protokoll=print):
    """Startkameras und Gelenkwinkel je Bild; Rückgabe: Liste von Ansicht und Zeiten."""
    t0 = time.perf_counter()
    zeiten = {}
    einst = einst or Einstellungen()
    kand_ans, herkunft = [], []
    for j, e in enumerate(eingaben):
        netz = netze[e.netz]
        th = np.array([theta[k] for k in netz.parameter])
        w0 = None if e.winkel is None else np.array(e.winkel, float)
        if e.kamera is not None:
            starts = [e.kamera]
        else:
            m = e.bild.maske
            erg = grobsuche(netz, th, m, e.f, e.bild.breite, e.bild.hoehe, winkel=w0, hoehen=e.hoehen,
                            rolls=e.rolls, azimute=e.azimute, beste=max(kandidaten, 2), paare=e.paare)
            starts = [k for _, k in erg[:kandidaten]]
        winkel_listen = []
        for g in range(0 if w0 is None else len(w0)):
            winkel_listen.append(e.winkel_starts.get(g, [w0[g]]))
        for kam in starts:
            for kombi in (itertools.product(*winkel_listen) if winkel_listen else [()]):
                w = None if w0 is None else np.array(kombi if kombi else w0, float)
                kand_ans.append(Ansicht(bild=e.bild, netz=e.netz, kamera=kam.kopie(), winkel=w,
                                        winkel_frei=e.winkel_frei, f_gruppe=f"kand{len(kand_ans)}" if e.f_gruppe else None))
                herkunft.append(j)
    zeiten["grobsuche"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    f_start = {a.f_gruppe: eingaben[h].f for a, h in zip(kand_ans, herkunft) if a.f_gruppe}
    A = Ausgleich(netze, kand_ans, theta, frei=[], einstellungen=einst, f_start=f_start, protokoll=None)
    plaene = plaene or standard_plaene(eingaben[0].bild.breite_arbeit)
    A.loese_einzeln(plaene.kandidaten)
    wahl = {}
    for i, h in enumerate(herkunft):
        q = A.iou(i, plaene.kandidaten[-1])
        if h not in wahl or q > wahl[h][0]:
            wahl[h] = (q, i)
    zeiten["kandidaten"] = time.perf_counter() - t1
    out = []
    for j, e in enumerate(eingaben):
        q, i = wahl[j]
        kam = A.z.kameras[i]
        out.append(Ansicht(bild=e.bild, netz=e.netz, kamera=kam, winkel=None if A.z.winkel[i] is None else A.z.winkel[i].copy(),
                           winkel_frei=e.winkel_frei, f_gruppe=e.f_gruppe))
        if protokoll:
            protokoll(f"  {e.bild.name}: Start-IoU {q:.3f} aus {sum(1 for h in herkunft if h == j)} Kandidaten")
    return out, zeiten


@dataclass
class Ergebnis:
    theta: dict
    kameras: list
    winkel: list
    ausgleich: Ausgleich
    zeiten: dict
    plaene: Plaene


def vermessen(netze, eingaben, theta_start, frei, vorgaben=None, einst=None, plaene=None, kandidaten=2,
              f_start=None, protokoll=print, verwerf_iou=0.8, grenzen=None):
    """Ganzer Ablauf. theta_start: alle Maße (dict), frei: einzupassende Maße, vorgaben: weiche Vorgaben."""
    t0 = time.perf_counter()
    einst = einst or Einstellungen()
    plaene = plaene or standard_plaene(eingaben[0].bild.breite_arbeit)
    ans, zeiten = kameras_finden(netze, eingaben, theta_start, einst, plaene, kandidaten, protokoll)
    t1 = time.perf_counter()
    f0 = dict(f_start or {})
    for e in eingaben:
        if e.f_gruppe and e.f_gruppe not in f0:
            f0[e.f_gruppe] = e.f
    A = Ausgleich(netze, ans, theta_start, frei=frei, vorgaben=vorgaben, einstellungen=einst, f_start=f0,
                  protokoll=None, grenzen=grenzen)
    # Brennweiten der Kandidatensuche übernehmen (Gruppen je Bild); gemeinsame Gruppe: Mittel der Logarithmen
    for grp in A.f_gruppen:
        werte = [math.log(a.kamera.f) for a in ans if a.f_gruppe == grp]
        A.z.logf[grp] = float(np.mean(werte))
    for i, a in enumerate(ans):
        if a.f_gruppe:
            A.z.kameras[i].f = math.exp(A.z.logf[a.f_gruppe])
    if any(e.winkel_raster for e in eingaben):
        A.loese_einzeln(plaene.kameras[:1])
        for i, e in enumerate(eingaben):
            for g, werte in e.winkel_raster.items():
                A.raster_gelenk(i, g, werte, plaene.kameras[-1])
    A.loese_einzeln(plaene.kameras)
    zeiten["kameras"] = time.perf_counter() - t1
    # Ausreißer-Bilder: Überdeckung deutlich unter den anderen (falsches Nebenminimum, Objekt angeschnitten);
    # nur verwerfen, wenn danach mindestens drei Bilder bleiben
    iou = np.array([A.iou(i, plaene.kameras[-1]) for i in range(len(ans))])
    verworfen = []
    if len(ans) >= 4 and np.isfinite(iou).all():
        grenze = min(verwerf_iou, float(np.median(iou)) - 0.08)
        behalten = [i for i in range(len(ans)) if iou[i] >= grenze]
        if 3 <= len(behalten) < len(ans):
            verworfen = [ans[i].bild.name for i in range(len(ans)) if i not in behalten]
            if protokoll:
                protokoll(f"  verworfen (IoU unter {grenze:.2f}): {verworfen}")
            neu = []
            for i in behalten:
                a = ans[i]
                neu.append(Ansicht(bild=a.bild, netz=a.netz, kamera=A.z.kameras[i].kopie(),
                                   winkel=None if A.z.winkel[i] is None else A.z.winkel[i].copy(),
                                   winkel_frei=a.winkel_frei, f_gruppe=a.f_gruppe))
            logf = dict(A.z.logf)
            A = Ausgleich(netze, neu, theta_start, frei=frei, vorgaben=vorgaben, einstellungen=einst, f_start=f0,
                          protokoll=None, grenzen=grenzen)
            A.z.logf.update({g: v for g, v in logf.items() if g in A.z.logf})
            iou = iou[behalten]
    t2 = time.perf_counter()
    if frei:
        A.loese(plaene.buendel)
    else:
        A.loese_einzeln(plaene.buendel)
    zeiten["buendel"] = time.perf_counter() - t2
    zeiten["gesamt"] = time.perf_counter() - t0
    zeiten.update({f"intern_{k}": v for k, v in A.zeiten.items()})
    erg = Ergebnis(theta=A.theta_dict(), kameras=A.z.kameras, winkel=A.z.winkel, ausgleich=A, zeiten=zeiten,
                   plaene=plaene)
    erg.verworfen = verworfen
    erg.iou_kameras = [float(x) for x in iou]
    erg.namen = [a.bild.name for a in A.ansichten]
    return erg

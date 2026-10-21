"""Prüfdatensatz Beelonia-Küche: 22 Studiofotos auf Weiß, Referenz aus dem vollen Bündelausgleich (fotocad).

Alles im Kundenordner wird nur gelesen (keine pyc-Dateien, keine Zwischenablagen dort). Referenz:
- Maße: kueche.P (nach dem Bündelausgleich übernommen),
- Kameras und Haubenwinkel: messung/netz_buendel.json,
- Fotozustand (Bauform, Haube offen/zu, Ofen, Besonderheiten): messung/mehrfach.py ANSICHTEN,
- nicht zu wertende Bildbereiche: Ausschlussquader (Deko, offene Türen) und lose Kabel, so wie sie die Referenz
  ausnimmt. Sie werden einmal mit der Referenzkamera ins Bild gezeichnet und gelten dann als Bildmarkierung (wie
  sie Kevin im Viewer malen würde), nicht als Vorwissen über die Kamera.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from ..bild import Bild
from ..kamera import Kamera
from ..modell import CACHE, Gelenk, baue_param_netz

KUECHE = Path.home() / "Code Experiments/Beelonia/cad/outdoor-kueche"
MESSUNG = KUECHE / "messung"
ABLAGE = CACHE / "kueche"
SKALA = 0.25                      # Arbeitskopie: Viertelgröße (wie die Bewertung der Referenz)

FORMEN = {"winkel": ("winkel", False), "winkel_ofen": ("winkel", True), "linie": ("linie", False)}
GEMEINSAM = ["h_fuss", "l_g", "d_g", "h_g"]
WINKEL = ["a", "l_r", "d_r", "ueb", "d_platte", "aufkantung", "theke_z"]
OFEN = ["ofen_b", "ofen_t", "ofen_h"]
LINIE = ["l2", "d2", "dw2", "ov2"]
PARAMETER = {"winkel": GEMEINSAM + WINKEL, "winkel_ofen": GEMEINSAM + WINKEL + OFEN, "linie": GEMEINSAM + LINIE + ["a", "theke_z"]}
ALLE = GEMEINSAM + WINKEL + OFEN + LINIE
LOSE = ("Motorkabel",)


def _importe():
    sys.dont_write_bytecode = True                 # nichts in den Kundenordner schreiben
    for p in (str(MESSUNG), str(KUECHE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import kueche  # noqa: F401
    import mehrfach as mf
    import netz_kameras as nk
    return mf, nk, kueche


def ansichten():
    mf, _, _ = _importe()
    return dict(mf.ANSICHTEN)


def bauform(key):
    form, haube, ofen, extra = ansichten()[key]
    return "linie" if form == "linie" else ("winkel_ofen" if ofen else "winkel")


def referenz():
    """Referenzmaße (kueche.P), Kameras und Haubenwinkel aus dem Bündelausgleich."""
    _, _, kueche = _importe()
    E = json.loads((MESSUNG / "netz_buendel.json").read_text())
    kams = {k: Kamera.aus_fotocad(c, k) for k, c in E["kameras"].items()}
    return dict(kueche.P), kams, {k: float(v) for k, v in E["haube"].items()}


def start_masse(P, frei, staerke=0.05):
    """Start für den Test: jedes freie Maß um +-staerke verfälscht (abwechselnd), sonst wie die Referenz."""
    q = dict(P)
    for i, k in enumerate(frei):
        q[k] = round(P[k] * (1 + staerke * (1 if i % 2 == 0 else -1) * (1.0 if i % 3 else 0.6)), 1)
    return q


def gelenk_haube(P):
    return Gelenk("Haube", ("grillhaube", "thermometer"), (0.0, P["scharnier_y"], P["scharnier_z"]), (1.0, 0.0, 0.0))


def netze(P_start, formen=None, prozesse=4, protokoll=print):
    """ParamNetz je Bauform, linearisiert an den Startmaßen (einmalig gebaut, dann aus dem Zwischenspeicher)."""
    _importe()
    from netz_bau import DATEI
    out = {}
    for b in formen or FORMEN:
        form, ofen = FORMEN[b]
        import time
        t = time.perf_counter()
        out[b] = baue_param_netz(DATEI, P_start, PARAMETER[b], {"form": form, "mit_ofen": ofen}, gelenke=[gelenk_haube(P_start)],
                                 auslassen=LOSE, prozesse=prozesse, datei_stand=(KUECHE / "kueche.py").stat().st_mtime)
        if protokoll:
            protokoll(f"Netz {b}: {len(out[b].V0)} Punkte, {len(out[b].tris)} Dreiecke, {len(out[b].kanten)} Kanten "
                      f"({out[b].kante_merkmal.sum()} Merkmalskanten), {time.perf_counter() - t:.1f} s")
    return out


def lade_bild(key):
    """Arbeitskopie (Viertelgröße), weiche Silhouette ohne loses Kabel, nicht zu wertende Bereiche."""
    mf, nk, _ = _importe()
    ABLAGE.mkdir(parents=True, exist_ok=True)
    ziel = ABLAGE / f"bild_{key}.npz"
    if ziel.exists():
        z = np.load(ziel)
        return Bild(z["farbe"], key, maske=z["maske"], ignorieren=z["ignorieren"], ursprung=(int(z["w"]), int(z["h"])))
    im = cv2.imread(str(KUECHE / "fotos" / f"FotoKaup{key}.jpg"))
    h, w = im.shape[:2]
    halb = cv2.resize(im, (round(w / 2), round(h / 2)), interpolation=cv2.INTER_AREA)
    bw, bh = round(w * SKALA), round(h * SKALA)
    farbe = cv2.resize(im, (bw, bh), interpolation=cv2.INTER_AREA)
    roh = halb.min(axis=2) < 245
    kabel = nk.kabelmaske(key, halb.shape[1], halb.shape[0])
    sil, unsicher = nk.ohne_kabel(roh, kabel)
    maske = cv2.resize(sil.astype(np.float32), (bw, bh), interpolation=cv2.INTER_AREA)
    ign = np.zeros((bh, bw), bool)
    if unsicher is not None:
        ign |= cv2.resize(unsicher.astype(np.uint8), (bw, bh), interpolation=cv2.INTER_AREA) > 0
    # Ausschlussquader mit Referenzkamera und Referenzmaßen der Altmessung (wie netz_kameras.py)
    J = nk.lade()
    cam = J["kameras"][key]
    aus = mf.zeichne(mf.ausschluss_koerper(J["masse"], key, "voll"), cam, SKALA, (bh, bw), weich=False) > 0
    ign |= cv2.dilate(aus.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    np.savez_compressed(ziel, farbe=farbe, maske=maske.astype(np.float16), ignorieren=ign, w=w, h=h)
    return Bild(farbe, key, maske=maske, ignorieren=ign, ursprung=(w, h))


def iou_referenz(key, kamera, haubenwinkel, zeichner_cache={}):
    """Überdeckung wie netz_kameras.binaer_iou (Viertelgröße, Schwelle 245, Löcher gefüllt, Ausschlüsse) am fertigen
    Referenz-GLB; misst die Kamera unabhängig von den eingepassten Maßen."""
    mf, nk, _ = _importe()
    b = nk.bauform(key)
    if b not in zeichner_cache:
        from fotocad.netz_gl import Zeichner
        zeichner_cache[b] = Zeichner(nk.lade_netz(b))
    J = nk.lade()
    return nk.binaer_iou(key, kamera.als_fotocad(), haubenwinkel, zeichner_cache[b], J["masse"])[0]


def f_vorgabe(w):
    """Ohne EXIF: Kleinbild 50 mm als Vorgabe (die Referenz streut 41 bis 70 mm)."""
    return 50.0 / 36.0 * w


# ---------------------------------------------------------------------------------------------- Lauf
TEILMENGEN = {
    1: ["0006"],
    2: ["0006", "0035"],
    3: ["0006", "0035", "0064"],
    5: ["0006", "0035", "0064", "0104a", "0020"],
    10: ["0006", "0035", "0064", "0104a", "0020", "0013", "0043", "0083", "0129", "0140"],
}


def teilmenge(n):
    return TEILMENGEN.get(n) or list(ansichten())


def frei_fuer(keys):
    """Freie Maße: alle Maße der Bauformen, die in den Fotos vorkommen."""
    out = []
    for k in keys:
        for p in PARAMETER[bauform(k)]:
            if p not in out:
                out.append(p)
    return out


def eingaben(keys):
    from ..ablauf import Eingabe
    A = ansichten()
    out = []
    for k in keys:
        b = lade_bild(k)
        offen = A[k][1] == "offen"
        out.append(Eingabe(bild=b, netz=bauform(k), f=f_vorgabe(b.breite), f_gruppe=k, winkel=(80.0 if offen else 0.0,),
                           winkel_frei=(0,) if offen else (), winkel_starts={0: [50.0, 75.0, 95.0]} if offen else {},
                           hoehen=tuple(np.arange(-10, 61, 10.0))))
    return out


def bewerte(keys, theta, kameras, winkel, P, kams_ref, haube_ref, frei, mit_iou=True):
    from ..kamera import winkel_zwischen
    zeilen = []
    for k, kam, w in zip(keys, kameras, winkel):
        ref = kams_ref[k]
        hw = float(w[0]) if w is not None else 0.0
        z = dict(foto=k, rot_grad=winkel_zwischen(kam.R, ref.R), pos_mm=float(np.linalg.norm(kam.zentrum - ref.zentrum)),
                 f_prozent=100 * (kam.f / ref.f - 1), haube=hw, haube_ref=haube_ref.get(k, 0.0))
        if mit_iou:
            z["iou"] = iou_referenz(k, kam, hw)
        zeilen.append(z)
    fehler = {p: float(theta[p] - P[p]) for p in frei}
    return zeilen, fehler


def iou_der_referenz(keys):
    _, kams, haube = referenz()
    return {k: iou_referenz(k, kams[k], haube.get(k, 0.0)) for k in keys}

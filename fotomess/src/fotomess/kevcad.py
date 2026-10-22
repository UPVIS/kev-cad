"""Einstieg für Kev CAD (Phase 4, MCP ``referenz_vermessen``): ein Auftrag des Kernels, eigener Prozess.

    .venv/bin/python -m fotomess.kevcad auftrag.json

Der Kernel baut das Netz vorher selbst (``kevcad_kernel.referenz.varianten``: model.py mit überschriebenen
``param``-Werten, Grundstand und je freiem Maß eine Variante, flächenweise). Hier entstehen daraus die Ableitungen
(wie ``fotocad.cad_netz.Jacobi``), dann Bilder und Masken in Arbeitsgröße, Einpassen, Unsicherheit und
Kontrollbilder. Auftrag:

```
{"varianten": ".../messung/varianten-<schlüssel>.pkl",
 "video": ".../IMG_5186.MOV" | "fotos": [...], "bilder": 8, "zeiten": null, "von": null, "bis": null,
 "ablage": ".../referenzen/<name>/messung", "arbeit": 1920,
 "maske": "vision+farbe" | "vision" | "weiss", "farbe_hsv": [[168, 4], 70, 25], "ausschluss_hsv": null,
 "gehaeuse": false, "umkreis": 0.12,
 "frei": [...], "vorgaben": {...}, "grenzen": {...}, "kb_brennweite": null, "kopfueber": false,
 "hoehen": [0, 80], "kanten_gewicht": 0.8, "jackknife": true}
```

Fortschritt als JSON-Zeilen auf stdout (``{"event": "progress", "phase", "fraction", "text"}``), am Ende
``{"event": "done", "ergebnis": "<ablage>/messung.json"}`` oder ``{"event": "error", "message"}``. Alles andere
(Ausgaben von OpenCV, Warten auf Speicher) geht auf stderr.

messung.json: Maße mit Sigma (Kombination aus Jackknife und Statistik, ``unsicherheit.sigma_gesamt``), je Bild Datei,
Maske, Kontrollbild und Kamera (``Kamera.als_dict``, Originalpixel), Empfehlungen (Nachmessen, Zusatzaufnahme),
Hüllmaße des eingepassten Modells (gesamt und je Teil, Gehäuse getrennt von der Hülle mit Anbauten), Zeiten.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_PROTO = None  # Dateideskriptor des echten stdout


def melde(event, **felder):
    zeile = json.dumps({"event": event, **felder}, ensure_ascii=False, default=float) + "\n"
    if _PROTO is None:
        sys.stdout.write(zeile)
        sys.stdout.flush()
    else:
        os.write(_PROTO, zeile.encode("utf-8"))


def fortschritt(phase, anteil, text):
    melde("progress", phase=phase, fraction=round(float(anteil), 3), text=text)


# ----------------------------------------------------------------------------------------------- Netz aus Varianten
# Ableitung je Fläche wie fotocad.cad_netz (Kevins Verfahren, Repo UPVIS/cad-aus-fotos); übernommen, damit das
# installierte Kev CAD nicht vom Arbeitsstand dieses Repos abhängt.

def _flaechen_zuordnen(f0, f1, toleranz):
    def merkmal(f):
        kreuz = np.cross(f[:, 1] - f[:, 0], f[:, 2] - f[:, 0])
        flaeche = np.linalg.norm(kreuz, axis=1)
        c = (f.mean(1) * flaeche[:, None]).sum(0) / max(flaeche.sum(), 1e-12)
        n = kreuz.sum(0)
        laenge = np.linalg.norm(n)
        n = n / laenge if laenge > 1e-3 * np.abs(f).max() else np.zeros(3)
        return c, n
    m0 = [merkmal(f) for f in f0]
    m1 = [merkmal(f) for f in f1]
    frei = set(range(len(f1)))
    out = [None] * len(f0)
    for gleich in (True, False):
        for i, f in enumerate(f0):
            if out[i] is not None:
                continue
            c, n = m0[i]
            beste, bd = None, toleranz
            for j in frei:
                if gleich and f1[j].shape != f.shape:
                    continue
                dist = np.linalg.norm(m1[j][0] - c) + 50 * (float(np.abs(n).sum() > 0) - float(n @ m1[j][1]))
                if dist < bd:
                    beste, bd = j, dist
            if beste is not None:
                frei.discard(beste)
                out[i] = beste
    return out


def _randpunkte(t):
    v = t.reshape(-1, 3)
    _, ids = np.unique(np.round(v, 4), axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    kanten = np.sort(np.concatenate([ids[:, [0, 1]], ids[:, [1, 2]], ids[:, [2, 0]]]), axis=1)
    k, n = np.unique(kanten, axis=0, return_counts=True)
    return np.isin(ids.ravel(), np.unique(k[n == 1]))


def _ableitung_flaeche(t0, t1, schritt, grenze, grenze_nachbar):
    from scipy.spatial import cKDTree
    v0 = t0.reshape(-1, 3)
    v1 = t1.reshape(-1, 3)
    if t1.shape == t0.shape:
        d = t1 - t0
        if np.abs(d).max() <= grenze:
            return d / schritt
        dist, idx = cKDTree(v1).query(v0)
        if dist.max() <= grenze_nachbar:
            return (v1[idx].reshape(t0.shape) - t0) / schritt
    r0, r1 = _randpunkte(t0), _randpunkte(t1)
    if r0.sum() < 3 or r1.sum() < 3:
        return None
    dist, idx = cKDTree(v1[r1]).query(v0[r0])
    treffer = dist <= grenze_nachbar
    if treffer.mean() < 0.6:
        return None
    quelle = v0[r0][treffer]
    d_quelle = v1[r1][idx[treffer]] - quelle
    k = min(4, len(quelle))
    dd, ii = cKDTree(quelle).query(v0, k=k)
    dd, ii = dd.reshape(len(v0), k), ii.reshape(len(v0), k)
    gew = 1.0 / np.maximum(dd, 1e-4) ** 2
    d = (gew[:, :, None] * d_quelle[ii]).sum(1) / gew.sum(1, keepdims=True)
    return d.reshape(t0.shape) / schritt


def ableitungen(basis, varianten, parameter, schritt):
    """{(Maß, Teil): d Dreiecke / d Maß} und die Liste starrer Flächen (Zerlegung geändert)."""
    ableitung, unstetig = {}, []
    for k, n in zip(parameter, varianten):
        for teil, f0 in basis.items():
            f1 = n.get(teil, [])
            f0n = [f for f in f0 if len(f)]
            f1n = [f for f in f1 if len(f)]
            zu = _flaechen_zuordnen(f0n, f1n, toleranz=1.5)
            teile, starr = [], 0
            for i, j in enumerate(zu):
                d = None if j is None else _ableitung_flaeche(f0n[i], f1n[j], schritt, 4 * schritt, 4 * schritt)
                if d is None:
                    starr += 1
                    d = np.zeros_like(f0n[i])
                teile.append(d)
            if starr:
                unstetig.append((k, teil, starr))
            d = np.concatenate(teile) if teile else np.zeros((0, 3, 3))
            if len(d) and np.abs(d).max() > 1e-6:
                ableitung[(k, teil)] = d.astype(np.float32)
    return ableitung, unstetig


def netz_aus_varianten(daten, cache_ordner=None):
    """ParamNetz aus dem Ergebnis von kevcad_kernel.referenz.varianten (zwischengespeichert je Inhalt)."""
    from scipy.spatial import cKDTree

    from .modell import ParamNetz
    basis = {n: [f for f in fl if len(f)] for n, fl in daten["basis"].items()}
    parameter = list(daten["parameter"])
    pfad = None
    if cache_ordner is not None:
        h = hashlib.sha1()
        for n in sorted(basis):
            h.update(n.encode())
            for f in basis[n]:
                h.update(np.ascontiguousarray(f, np.float32).tobytes())
        for v in daten["varianten"]:
            for n in sorted(v):
                for f in v[n]:
                    h.update(np.ascontiguousarray(f, np.float32).tobytes())
        h.update(repr((parameter, daten.get("schritt"), daten.get("farbflaechen") is not None)).encode())
        pfad = Path(cache_ordner) / f"netz-{h.hexdigest()[:16]}.pkl"
        if pfad.exists():
            try:
                return ParamNetz.lade(pfad), []
            except Exception:  # noqa: BLE001 - neu bauen
                pass
    ableitung, unstetig = ableitungen(basis, daten["varianten"], parameter, float(daten.get("schritt") or 0.5))
    netz = ParamNetz(basis, ableitung, parameter, daten["p"])
    netz.unstetig = unstetig
    ff = daten.get("farbflaechen")
    if ff:
        # Farbteile je Dreieck: über die Schwerpunkte der Ursprungsdreiecke (ParamNetz verschweißt und lässt
        # entartete Dreiecke weg)
        farb = np.zeros(len(netz.tris), bool)
        V = netz.V0
        mitte = V[netz.tris].mean(1)
        for ti, name in enumerate(netz.teile):
            sel = np.flatnonzero(netz.tri_teil == ti)
            fl = daten["basis"][name]
            flags = ff.get(name) or [False] * len(fl)
            schw, wert = [], []
            for fi, f in enumerate(fl):
                if len(f):
                    schw.append(f.mean(1))
                    wert.append(np.full(len(f), bool(flags[fi]) if fi < len(flags) else False))
            if not schw or not len(sel):
                continue
            baum = cKDTree(np.concatenate(schw))
            _, idx = baum.query(mitte[sel])
            farb[sel] = np.concatenate(wert)[idx]
        netz.farb_tris = farb
    if pfad is not None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        netz.speichere(pfad)
    return netz, unstetig


# ----------------------------------------------------------------------------------------------- Bilder und Masken

def _kennzahlen(video, farbe, ablage, von=None, bis=None):
    from . import video as V
    st = Path(video).stat()
    schl = hashlib.sha1(repr((str(video), st.st_size, int(st.st_mtime), farbe)).encode()).hexdigest()[:12]
    datei = Path(ablage) / f"kennzahlen-{schl}.json"
    if datei.exists():
        k = json.loads(datei.read_text())
    else:
        k = V.bewerten(video, 6.0, 640, farbbereich=tuple(farbe) if farbe else None)
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps(k))
    if von is not None or bis is not None:
        a, b = von if von is not None else -1e9, bis if bis is not None else 1e9
        k = [e for e in k if a <= e["t"] <= b]
    return k


def _holen(video, zeiten, ziel, breite):
    """Videobilder in Arbeitsgröße (lange Kante = breite) als JPEG; Name <video>_<t>.jpg."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    out = []
    for t in zeiten:
        datei = ziel / f"{Path(video).stem}_{t:07.3f}.jpg"
        if not datei.exists():
            skal = f"scale='if(gt(iw,ih),{breite},-2)':'if(gt(iw,ih),-2,{breite})'"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                            "-vf", skal, "-q:v", "2", str(datei)], check=True)
        out.append(datei)
    return out


def _foto_kopie(pfad, ziel, breite):
    """Foto in Arbeitsgröße als JPEG (HEIC über sips). Rückgabe: (Datei, Originalbreite, -höhe, f35 aus EXIF)."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    pfad = Path(pfad)
    quelle = pfad
    if pfad.suffix.lower() in (".heic", ".heif"):
        quelle = ziel / (pfad.stem + "_voll.jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", str(pfad), "--out", str(quelle)], check=True,
                       capture_output=True)
    f35 = None
    try:
        from PIL import Image
        with Image.open(quelle) as im:
            exif = im.getexif()
            f35 = exif.get_ifd(0x8769).get(0xA405) or None
    except Exception:  # noqa: BLE001
        f35 = None
    im = cv2.imread(str(quelle))
    if im is None:
        raise ValueError(f"Bild nicht lesbar: {pfad}")
    h, w = im.shape[:2]
    s = min(1.0, breite / max(w, h))
    klein = cv2.resize(im, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else im
    datei = ziel / (pfad.stem + ".jpg")
    cv2.imwrite(str(datei), klein, [cv2.IMWRITE_JPEG_QUALITY, 93])
    if quelle != pfad:
        quelle.unlink(missing_ok=True)
    return datei, w, h, (float(f35) if f35 else None)


def bilder(auftrag, ablage):
    """Bilder in Arbeitsgröße mit Masken (Masken werden in Arbeitsgröße gerechnet). Rückgabe: (Liste Bild, f in
    Originalpixeln, f35, Zeiten je Bild oder None)."""
    from . import masken
    from . import video as V
    from .bild import Bild
    from .kamera import brennweite_aus_35mm
    arbeit = int(auftrag.get("arbeit") or 1920)
    farbe = auftrag.get("farbe_hsv")
    art = auftrag.get("maske") or ("vision+farbe" if farbe else "vision")
    zeiten = None
    if auftrag.get("video"):
        video = auftrag["video"]
        info = V.info(video)
        w0, h0 = info["breite"], info["hoehe"]
        if auftrag.get("zeiten"):
            zeiten = [float(t) for t in auftrag["zeiten"]]
        else:
            fortschritt("bilder", 0.0, "Video bewerten (Schärfe, Kameraweg)")
            k = _kennzahlen(video, farbe, ablage, auftrag.get("von"), auftrag.get("bis"))
            if not k:
                raise ValueError("Im gewählten Abschnitt des Videos gibt es keine Bilder")
            wahl = V.auswaehlen(k, int(auftrag.get("bilder") or 8))
            zeiten = [k[i]["t"] for i in wahl]
        fortschritt("bilder", 0.3, f"{len(zeiten)} Bilder holen")
        dateien = _holen(video, zeiten, Path(ablage) / "bilder", arbeit)
        groessen = [(w0, h0)] * len(dateien)
        try:
            meta = masken.video_meta(video)
            f35 = float(meta.get("mdta/com.apple.quicktime.camera.focal_length.35mm_equivalent", 0)) or None
        except Exception:  # noqa: BLE001
            f35 = None
        beschnitt = 1.05
    else:
        dateien, groessen, f35s = [], [], []
        for p in auftrag.get("fotos") or []:
            d, w, h, f = _foto_kopie(p, Path(ablage) / "bilder", arbeit)
            dateien.append(d)
            groessen.append((w, h))
            f35s.append(f)
        if not dateien:
            raise ValueError("Keine Fotos angegeben")
        f35 = next((f for f in f35s if f), None)
        beschnitt = 1.0
    f35 = auftrag.get("kb_brennweite") or f35
    fortschritt("bilder", 0.45, "Masken rechnen")
    vis = masken.vision(dateien, Path(ablage) / "vision") if art.startswith("vision") else {}
    maskenordner = Path(ablage) / "masken"
    maskenordner.mkdir(parents=True, exist_ok=True)
    out = []
    for i, (d, (w0, h0)) in enumerate(zip(dateien, groessen)):
        im = cv2.imread(str(d))
        h, w = im.shape[:2]
        fm = None
        if art == "weiss":
            m = masken.weiss(im).astype(np.float32)
        else:
            if art == "vision+farbe" and farbe:
                fm = masken.farbe(im, tuple(farbe[0]), farbe[1], farbe[2])
            v = masken.instanz_waehlen(vis.get(str(d), []), fm)
            if v is None:
                v = fm.astype(np.float32) if fm is not None else np.zeros((h, w), np.float32)
            if fm is None:
                m = v.astype(np.float32)
            else:
                aus = auftrag.get("ausschluss_hsv")
                aus = (tuple(aus[0]), aus[1], aus[2]) if aus else None
                if auftrag.get("gehaeuse"):
                    opt = masken.gehaeuse_optionen(fm, w, ausschluss=aus,
                                                   umkreis_anteil=float(auftrag.get("umkreis") or 0.12))
                else:
                    opt = dict(ausschluss=aus)
                m = masken.kombiniert(im, v, fm, **opt)
        cv2.imwrite(str(maskenordner / (d.stem + ".png")), np.clip(m * 255, 0, 255).astype(np.uint8))
        b = Bild(im, d.stem, maske=m.astype(np.float32), ursprung=(w0, h0))
        if fm is not None:
            b.farbmaske = fm.astype(np.float32)
        b.datei = str(d)
        out.append(b)
        fortschritt("bilder", 0.45 + 0.55 * (i + 1) / len(dateien), f"Maske {i + 1} von {len(dateien)}")
    shutil.rmtree(Path(ablage) / "vision", ignore_errors=True)
    b0 = out[0]
    f = brennweite_aus_35mm(f35, b0.breite, b0.hoehe, beschnitt) if f35 else 50.0 / 36.0 * max(b0.breite, b0.hoehe)
    return out, f, f35, zeiten


# ----------------------------------------------------------------------------------------------- Ablauf

def _richtung_text(az, el):
    """Blickrichtung einer Zusatzaufnahme (fotomess.kamera.blick: Azimut 0 = von +X) in Worten, vorne = −Y."""
    seiten = {0: "von rechts (+X)", 45: "schräg von hinten rechts", 90: "von hinten (+Y)",
              135: "schräg von hinten links", 180: "von links (−X)", 225: "schräg von vorne links",
              270: "von vorne (−Y)", 315: "schräg von vorne rechts"}
    a = int(round((az % 360) / 45.0) * 45) % 360
    text = seiten.get(a, f"Azimut {az:.0f}°")
    if el <= 15:
        hoehe = "flach"
    elif el >= 70:
        hoehe = "steil von oben"
    else:
        hoehe = f"{el:.0f}° hoch"
    return f"{text}, {hoehe}"


def vermessen_kevcad(auftrag):
    from . import unsicherheit as U
    from .ablauf import Eingabe, standard_plaene, vermessen
    from .einpassen import Einstellungen
    from .kontrolle import kontrollbild
    import pickle

    t0 = time.perf_counter()
    ablage = Path(auftrag["ablage"])
    ablage.mkdir(parents=True, exist_ok=True)
    zeiten = {}
    fortschritt("modell", 0.0, "Messmodell vorbereiten")
    with open(auftrag["varianten"], "rb") as fh:
        daten = pickle.load(fh)
    netz, unstetig = netz_aus_varianten(daten, ablage / "cache")
    frei = [k for k in auftrag.get("frei") or daten["parameter"] if k in netz.parameter]
    zeiten["modell"] = time.perf_counter() - t0

    t = time.perf_counter()
    B, f0, f35, bildzeiten = bilder(auftrag, ablage)
    zeiten["bilder"] = time.perf_counter() - t
    video = bool(auftrag.get("video"))

    hoehen = auftrag.get("hoehen") or [0, 80]
    paare = [(float(e), 0.0) for e in range(int(hoehen[0]), int(hoehen[1]) + 1, 10)]
    if auftrag.get("kopfueber"):
        paare += [(-e, 180.0) for e in range(10, 81, 10)]
    zwillinge = tuple((np.array(q, float), np.array(c, float)) for q, c in daten.get("zwillinge") or [])
    # Startkameras (etwa aus Object Capture desselben Videos, ins Modellsystem gelegt): ohne Grobsuche und ohne
    # Zwillingslagen, die Lage steht damit fest
    from .kamera import Kamera
    def kamera_aus(k, b):
        """Kamera auf die Originalgröße des Bildes umgerechnet (Object Capture rechnet in seinen kleineren Bildern)."""
        sx, sy = b.breite / float(k["w"]), b.hoehe / float(k["h"])
        return Kamera(R=np.array(k["R"], float), t=np.array(k["t"], float), f=float(k["f"]) * sx, w=int(b.breite),
                      h=int(b.hoehe), cx=float(k["cx"]) * sx, cy=float(k["cy"]) * sy)
    start = dict(auftrag.get("startkameras") or {})
    nach_zeit = [(float(e["zeit"]), e["kamera"]) for e in auftrag.get("startkameras_zeit") or []]

    def eingabe(i, b):
        kam = kamera_aus(start[b.name], b) if b.name in start else None
        if kam is None and bildzeiten and nach_zeit:
            z, k = min(nach_zeit, key=lambda e: abs(e[0] - bildzeiten[i]))
            if abs(z - bildzeiten[i]) <= 0.4:
                kam = kamera_aus(k, b)
        return Eingabe(bild=b, netz="m", f=f0, f_gruppe="kamera" if video else "gemeinsam", paare=tuple(paare),
                       zwillinge=() if kam is not None else zwillinge, kamera=kam)
    E = [eingabe(i, b) for i, b in enumerate(B)]
    breite = B[0].breite_arbeit
    pl = standard_plaene(breite, grob=320 if breite >= 1280 else max(160, breite // 4))
    einst = Einstellungen(f_sigma_log=0.15 if f35 else 0.25, roll_sigma_grad=15.0 if video else 3.0,
                          kanten_gewicht=float(auftrag.get("kanten_gewicht") or 0.8))
    theta0 = dict(daten["p"])
    vorg = {k: tuple(v) for k, v in (auftrag.get("vorgaben") or {}).items() if k in frei}
    grenzen = {k: tuple(v) for k, v in (auftrag.get("grenzen") or {}).items() if k in frei}
    for k in frei:  # Vorgaben, wo keine angegeben sind: weich um den Startwert
        v = float(theta0[k])
        vorg.setdefault(k, (v, max(0.25 * abs(v), 5.0)))
        if v > 0:
            grenzen.setdefault(k, (max(0.05, 0.25 * v), 4.0 * v))
    fortschritt("einpassen", 0.0, f"Kameras und Maße einpassen ({len(B)} Bilder)")
    t = time.perf_counter()
    erg = vermessen({"m": netz}, E, theta0, frei, vorgaben=vorg, einst=einst, plaene=pl, kandidaten=4,
                    protokoll=None, grenzen=grenzen)
    zeiten["einpassen"] = time.perf_counter() - t
    fortschritt("unsicherheit", 0.0, "Unsicherheit und Empfehlungen")
    t = time.perf_counter()
    A = erg.ausgleich
    kov = U.kovarianz(A, pl.buendel[-1])
    jack = U.jackknife(A, pl.buendel[-1]) if auftrag.get("jackknife", True) else None
    nm = U.nachmessen(kov, A.frei)
    richt = [(az, el, 0.0) for el in (5, 30, 60, 85) for az in range(0, 360, 45)]
    try:
        ae = U.aufnahme_empfehlen(A, kov, pl.kameras[-1], richtungen=richt)
    except Exception:  # noqa: BLE001 - Empfehlung ist eine Zugabe
        ae = []
    sigma = U.sigma_gesamt(kov["sigma"], jack)
    zeiten["unsicherheit"] = time.perf_counter() - t

    fortschritt("kontrolle", 0.0, "Kontrollbilder")
    t = time.perf_counter()
    namen_zeit = {b.name: (bildzeiten[i] if bildzeiten else None) for i, b in enumerate(B)}
    datei_von = {b.name: b.datei for b in B}
    bericht = A.bericht(pl.buendel[-1])
    eintraege = []
    for i, name in enumerate(erg.namen):
        p = ablage / "kontrolle" / f"{name}.jpg"
        kontrollbild(A, i, pl.buendel[-1], p, titel=name)
        k = erg.kameras[i].als_dict()
        k["zentrum"] = [float(x) for x in k["zentrum"]]
        e = {"name": name, "zeit": namen_zeit.get(name), "datei": os.path.relpath(datei_von[name], ablage),
             "maske": f"masken/{name}.png", "kontrolle": f"kontrolle/{name}.jpg", "kamera": k,
             "iou": float(erg.iou_kameras[i]) if i < len(erg.iou_kameras) else None}
        if i < len(bericht) and isinstance(bericht[i], dict):
            e["zuordnung"] = {kk: float(vv) for kk, vv in bericht[i].items() if isinstance(vv, (int, float))}
        eintraege.append(e)
    for name in erg.verworfen:
        eintraege.append({"name": name, "zeit": namen_zeit.get(name),
                          "datei": os.path.relpath(datei_von[name], ablage), "maske": f"masken/{name}.png",
                          "verworfen": True})
    zeiten["kontrolle"] = time.perf_counter() - t

    theta = erg.theta
    th_netz = np.array([theta[k] for k in netz.parameter])
    V = netz.ecken(th_netz)

    def hull(P):
        lo, hi = P.min(0), P.max(0)
        return {"min": [round(float(x), 2) for x in lo], "max": [round(float(x), 2) for x in hi],
                "groesse": [round(float(x), 2) for x in hi - lo]}
    # eingepasstes Modell als Netz (für das Anlegen des Referenznetzes im Kernel)
    np.savez_compressed(ablage / "modell_eingepasst.npz", V=V.astype(np.float32), T=netz.tris.astype(np.int32))
    teile_huelle = {}
    for ti, name in enumerate(netz.teile):
        P = V[netz.punkt_teil == ti]
        if len(P):
            teile_huelle[name] = hull(P)
    var_vorher = nm[0][1] if nm else None
    out = {
        "format": "kevcad-fotomess/messung", "stand": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "frei": frei, "start": {k: float(daten["p"][k]) for k in frei},
        "fest": {k: float(v) for k, v in daten["p"].items() if k not in frei},
        "masse": {k: float(theta[k]) for k in frei}, "sigma": {k: float(sigma[k]) for k in frei},
        "sigma_statistisch": {k: float(kov["sigma"][k]) for k in frei},
        "sigma_jackknife": {k: float(v) for k, v in (jack or {}).items()} if jack else None,
        "brennweite_px": float(math.exp(list(A.z.logf.values())[0])), "brennweite_vorgabe_px": float(f0),
        "f35_meta": f35, "bildgroesse": [int(B[0].breite), int(B[0].hoehe)],
        "arbeit": [int(B[0].breite_arbeit), int(B[0].hoehe_arbeit)],
        "bilder": eintraege, "verworfen": list(erg.verworfen),
        "nachmessen": [{"mass": a, "varianz_vorher": float(b), "varianz_nachher": float(c),
                        "anteil": float(c / b) if b else None} for a, b, c, _ in nm[:3]],
        "aufnahme": [{"azimut": float(a[0]), "hoehe": float(a[1]), "varianz_nachher": float(b),
                      "anteil": float(b / var_vorher) if var_vorher else None,
                      "text": _richtung_text(a[0], a[1])} for a, b, _, _ in ae[:3]],
        "huelle": hull(V), "teile": teile_huelle,
        "unstetig": [list(u) for u in unstetig], "zeiten": {k: round(v, 2) for k, v in zeiten.items()},
        "zeiten_einpassen": {k: round(float(v), 2) for k, v in erg.zeiten.items() if not k.startswith("intern_")},
        "warnungen": list(daten.get("warnungen") or []),
        "quelle": {"video": auftrag.get("video"), "fotos": auftrag.get("fotos"), "von": auftrag.get("von"),
                   "bis": auftrag.get("bis")},
        "maske": {k: auftrag.get(k) for k in ("maske", "farbe_hsv", "ausschluss_hsv", "gehaeuse", "umkreis")},
        "startkameras": sum(1 for e in E if e.kamera is not None),
        "dauer_s": round(time.perf_counter() - t0, 1),
    }
    ziel = ablage / "messung.json"
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float))
    tmp.replace(ziel)
    return ziel


def main(argv=None):
    global _PROTO
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__)
        return 2
    _PROTO = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        auftrag = json.loads(Path(args[0]).read_text())
        ziel = vermessen_kevcad(auftrag)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        melde("error", message=f"{type(exc).__name__}: {exc}")
        return 1
    melde("done", ergebnis=str(ziel))
    return 0


if __name__ == "__main__":
    sys.exit(main())

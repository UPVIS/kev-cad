"""Kommandozeile: ein Vermessungsauftrag als JSON (so würde ihn das MCP-Werkzeug von Kev CAD übergeben).

    fotomess vermessen auftrag.json [ergebnis.json]

Auftrag (Beispiel):
{
  "bauer": "/pfad/modell.py:modell",          # Funktion p -> build123d.Compound mit benannten Teilen
  "gelenke": "/pfad/modell.py:gelenke",        # optional: Funktion p -> [fotomess.modell.Gelenk]
  "p": {"breite": 610, "hoehe": 128},          # Startwerte aller Maße
  "frei": ["hoehe"],                           # zu messende Maße (mindestens ein Maß bleibt fest: der Maßstab)
  "vorgaben": {"hoehe": [120, 20]},            # optional: weiche Vorgaben (Mittel, Sigma)
  "grenzen": {"rand": [8, 40]},                # optional: harte Grenzen (sichtbar vorhandene Teile nicht auf null)
  "video": "/pfad/video.mov", "bilder": 8,     # oder "fotos": ["/pfad/a.jpg", ...]
  "maske": "vision+farbe",                     # "weiss" (Studio), "vision", "vision+farbe"
  "farbe_hsv": [[95, 130], 70, 25],            # für vision+farbe; Rot über 0 hinweg: [[168, 4], 70, 25]
  "ausschluss_hsv": [[6, 24], 50, 45],         # optional: Farbe einer Unterlage, die Vision mitnimmt (Holzscheibe)
  "gehaeuse": true,                            # optional: Farbe fasst andersfarbige Blenden ein (konvexe Hülle innen)
  "farbteile": "/pfad/modell.py:farbteile",    # optional: ParamNetz -> bool je Dreieck (Teile in der Objektfarbe)
  "zwillinge": [[[[-1,0,0],[0,-1,0],[0,0,1]], [0,0,0]]],   # optional: (Q, c) fast gleich aussehende Lagen
  "kb_brennweite": 24,                         # optional, sonst aus den Metadaten oder 50 mm
  "kopfueber": true                            # Grobsuche auch von unten (Objekt liegt im Video auf dem Kopf)
}
Ergebnis: Maße mit Sigma, Kameras, Empfehlungen (Nachmessen, Zusatzaufnahme), Pfade der Kontrollbilder.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np


def _bilder(auftrag, ablage):
    from . import masken, video
    from .bild import Bild
    from .kamera import brennweite_aus_35mm
    if "video" in auftrag:
        k = video.bewerten(auftrag["video"], 6.0, 540,
                           farbbereich=tuple(auftrag["farbe_hsv"]) if auftrag.get("farbe_hsv") else None)
        wahl = video.auswaehlen(k, int(auftrag.get("bilder", 8)))
        dateien = video.holen(auftrag["video"], [k[i]["t"] for i in wahl], ablage / "bilder")
        try:
            meta = masken.video_meta(auftrag["video"])
            f35 = float(meta.get("mdta/com.apple.quicktime.camera.focal_length.35mm_equivalent", 0)) or None
        except Exception:
            f35 = None
    else:
        dateien = [Path(p) for p in auftrag["fotos"]]
        f35 = None
    f35 = auftrag.get("kb_brennweite") or f35
    art = auftrag.get("maske", "weiss")
    vis = masken.vision(dateien, ablage / "vision") if art.startswith("vision") else {}
    out = []
    for d in dateien:
        im = cv2.imread(str(d))
        h, w = im.shape[:2]
        if art == "weiss":
            m = masken.weiss(im).astype(np.float32)
        else:
            fm = masken.farbe(im, *auftrag["farbe_hsv"]) if art == "vision+farbe" else None
            v = masken.instanz_waehlen(vis.get(str(d), []), fm)
            if fm is None:
                m = v
            else:
                aus = auftrag.get("ausschluss_hsv")
                aus = (tuple(aus[0]), aus[1], aus[2]) if aus else None
                opt = masken.gehaeuse_optionen(fm, w, ausschluss=aus) if auftrag.get("gehaeuse") else \
                    dict(ausschluss=aus)
                m = masken.kombiniert(im, v, fm, **opt)
        breite = min(w, 1600)
        s = breite / w
        klein = cv2.resize(im, (breite, round(h * s)), interpolation=cv2.INTER_AREA)
        mk = cv2.resize(m.astype(np.float32), (breite, round(h * s)), interpolation=cv2.INTER_AREA)
        b = Bild(klein, d.stem, maske=mk, ursprung=(w, h))
        if art == "vision+farbe":
            b.farbmaske = cv2.resize(fm.astype(np.float32), (breite, round(h * s)), interpolation=cv2.INTER_AREA)
        out.append(b)
    f = brennweite_aus_35mm(f35, out[0].breite, out[0].hoehe, 1.05 if "video" in auftrag else 1.0) if f35 else \
        50.0 / 36.0 * max(out[0].breite, out[0].hoehe)
    return out, f, f35


def _funktion(angabe):
    """"datei.py:funktion" oder "paket.modul:funktion"."""
    import importlib
    ort, name = angabe.rsplit(":", 1)
    if ort.endswith(".py"):
        from fotocad.cad_netz import lade_bauer
        return lade_bauer(angabe)
    return getattr(importlib.import_module(ort), name)


def vermessen_auftrag(auftrag, ablage):
    from . import unsicherheit as U
    from .ablauf import Eingabe, standard_plaene, vermessen
    from .einpassen import Einstellungen
    from .kontrolle import kontrollbild
    from .modell import baue_param_netz
    ablage = Path(ablage)
    gelenke = _funktion(auftrag["gelenke"])(auftrag["p"]) if auftrag.get("gelenke") else []
    netz = baue_param_netz(auftrag["bauer"], auftrag["p"], auftrag["frei"], gelenke=gelenke)
    if auftrag.get("farbteile"):
        netz.farb_tris = np.asarray(_funktion(auftrag["farbteile"])(netz), bool)
    zwillinge = tuple((np.array(q, float), np.array(c, float)) for q, c in auftrag.get("zwillinge", []))
    bilder, f, f35 = _bilder(auftrag, ablage)
    paare = [(e, 0.0) for e in range(-10, 81, 10)]
    if auftrag.get("kopfueber"):
        paare += [(-e, 180.0) for e in range(10, 81, 10)]
    ng = len(gelenke)
    E = [Eingabe(bild=b, netz="m", f=f, f_gruppe="kamera" if "video" in auftrag else b.name,
                 winkel=tuple([0.0] * ng) if ng else None, winkel_frei=tuple(range(ng)), paare=tuple(paare),
                 winkel_raster={g: list(np.arange(0, 360, 30.0)) for g in range(ng)}, zwillinge=zwillinge)
         for b in bilder]
    pl = standard_plaene(bilder[0].breite_arbeit, grob=min(370, bilder[0].breite_arbeit // 4))
    vorg = {k: tuple(v) for k, v in auftrag.get("vorgaben", {}).items()}
    einst = Einstellungen(f_sigma_log=0.15 if f35 else 0.25, roll_sigma_grad=15.0 if "video" in auftrag else 3.0)
    grenzen = {k: tuple(v) for k, v in auftrag.get("grenzen", {}).items()}
    erg = vermessen({"m": netz}, E, dict(auftrag["p"]), auftrag["frei"], vorgaben=vorg, einst=einst, plaene=pl,
                    kandidaten=4, protokoll=None, grenzen=grenzen)
    kov = U.kovarianz(erg.ausgleich, pl.buendel[-1])
    jack = U.jackknife(erg.ausgleich, pl.buendel[-1])
    nm = U.nachmessen(kov, erg.ausgleich.frei)
    ae = U.aufnahme_empfehlen(erg.ausgleich, kov, pl.kameras[-1])
    bilder_pfade = []
    for i, name in enumerate(erg.namen):
        p = ablage / "kontrolle" / f"{name}.jpg"
        kontrollbild(erg.ausgleich, i, pl.buendel[-1], p, titel=name)
        bilder_pfade.append(str(p))
    sigma = U.sigma_gesamt(kov["sigma"], jack)
    return dict(masse={k: erg.theta[k] for k in auftrag["frei"]}, sigma=sigma, sigma_statistisch=kov["sigma"],
                sigma_jackknife=jack, brennweite_px=math.exp(list(erg.ausgleich.z.logf.values())[0]),
                kameras=[k.als_dict() for k in erg.kameras], bilder=erg.namen, verworfen=erg.verworfen,
                nachmessen=[dict(mass=a, varianz_vorher=b, varianz_nachher=c) for a, b, c, _ in nm[:3]],
                aufnahme=[dict(azimut=a[0], hoehe=a[1], varianz_nachher=b) for a, b, _, _ in ae[:3]],
                kontrollbilder=bilder_pfade, zeiten=erg.zeiten)


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "vermessen":
        print(__doc__)
        raise SystemExit(2)
    auftrag = json.loads(Path(sys.argv[2]).read_text())
    ablage = Path(auftrag.get("ablage", Path(sys.argv[2]).with_suffix("")))
    erg = vermessen_auftrag(auftrag, ablage)
    text = json.dumps(erg, indent=1, ensure_ascii=False, default=float)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(text)
    print(text)


if __name__ == "__main__":
    main()

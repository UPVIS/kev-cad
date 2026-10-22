"""Auswertung eines Scans (SCAN.md) zu Netz, Punktwolke, Kameras und Tiefenbildern für Kev CAD.

Ablauf (``auswerten``):

1. Einlesen (Ordner oder ZIP), Lagen von ARKit nach Kev CAD (z oben, mm) umrechnen.
2. Bilder wählen: alle Fotos, dazu Videobilder nach Abstand und Blickwinkel, Unschärfe aussortiert (``auswahl``).
3. Boden und Objekt: aus ``objekt.json`` oder geschätzt (stärkste waagrechte Ebene unter dem Fokuspunkt der Kameras,
   größte Gruppe von LiDAR-Punkten darüber).
4. Tiefe je Bild mit PromptDA (LiDAR als Prompt, Konfidenz 0 maskiert), ``--schnell`` mit dem kleinen Modell.
5. TSDF über die Box (Voxel aus der Boxgröße, etwa 2 mm), Netz mit marching cubes, größte Komponente.
6. Kev-CAD-System wie bei Object Capture: Boden z = 0, Mitte des Grundrisses x = y = 0, lange Seite = X.
7. Ausgabe: ``netz_mm.obj``/``.ply``, ``punkte_mm.ply``, ``poses.json`` (Form von kevcad-capture), ``kameras.json``
   (für fotomess), ``bilder/``, ``masken/`` (Silhouette des Netzes), ``tiefe/``, ``bericht.json``.

Fortschritt als JSON-Zeilen über ``melde`` (siehe cli.py).
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from kevscan import auswahl, format as fmt, geometrie as geo, netz as netzmod
from kevscan.tiefe import arbeitsgroesse, lidar_hochgerechnet
from kevscan.tsdf import TSDF, trunc_fuer, voxel_aus_box

BERICHT_FORMAT = "kevcad-scan/bericht"
ARBEIT = 1920  # lange Kante der Bilder für fotomess und die Fotoansicht
PHASEN = {"einlesen": (0.0, 0.03), "auswahl": (0.03, 0.05), "bilder": (0.08, 0.05), "tiefe": (0.13, 0.57),
          "tsdf": (0.70, 0.17), "netz": (0.87, 0.04), "masken": (0.91, 0.04), "bericht": (0.95, 0.05)}

Melde = Callable[[dict[str, Any]], None]


class Auswertung:
    def __init__(self, quelle: str | Path, aus: str | Path, *, schnell: bool = False, modell: str | None = None,
                 geraet: str | None = None, video_bilder: int | None = None, ohne_promptda: bool = False,
                 angleichen: bool = True, melde: Melde | None = None) -> None:
        self.quelle = Path(quelle).expanduser()
        self.aus = Path(aus).expanduser()
        self.schnell = schnell
        self.modell = modell or ("small" if schnell else "large")
        self.geraet = geraet
        self.video_bilder = video_bilder
        self.ohne_promptda = ohne_promptda
        self.angleichen = angleichen
        self._melde = melde or (lambda e: None)
        self.zeiten: dict[str, float] = {}
        self.warnungen: list[str] = []

    # ------------------------------------------------------------------------------------------------- Fortschritt
    def fortschritt(self, phase: str, anteil: float, text: str) -> None:
        start, breite = PHASEN.get(phase, (0.0, 0.0))
        self._melde({"event": "progress", "phase": phase, "fraction": round(float(anteil), 3),
                     "gesamt": round(start + breite * max(0.0, min(1.0, anteil)), 4), "text": text})

    # ------------------------------------------------------------------------------------------------- Ablauf
    def lauf(self) -> Path:
        t_start = time.perf_counter()
        self.aus.mkdir(parents=True, exist_ok=True)
        for d in ("bilder", "masken", "tiefe"):
            shutil.rmtree(self.aus / d, ignore_errors=True)
            (self.aus / d).mkdir()

        t = time.perf_counter()
        self.fortschritt("einlesen", 0.0, "Scan lesen")
        entpacken = self.aus / ".scan" if self.quelle.suffix.lower() == ".zip" else None
        ordner = fmt.oeffnen(self.quelle, entpacken)
        scan = fmt.lesen(ordner)
        self.warnungen += scan.warnungen
        alle = scan.fotos + scan.video
        R_alle, t_alle = [], []
        for a in alle:
            R, tt = geo.opencv_aus_arkit(a.R_wc, a.t_wc)
            R_alle.append(R)
            t_alle.append(tt)
        zentren = np.array([geo.zentrum(R, tt) for R, tt in zip(R_alle, t_alle)])
        richtungen = np.array([R[2] for R in R_alle])
        fokus = geo.fokuspunkt(zentren, richtungen)
        abstand = float(np.median(np.linalg.norm(zentren - fokus, axis=1)))
        self.zeiten["einlesen"] = time.perf_counter() - t

        # 2. Auswahl
        t = time.perf_counter()
        self.fortschritt("auswahl", 0.0, "Videobilder bewerten (Schärfe, Lage)")
        ist_foto = np.array([a.art == "foto" for a in alle])
        sch = np.zeros(len(alle))
        if scan.video_datei is not None:
            try:
                s = auswahl.video_schaerfe(scan.video_datei)
                nf = len(scan.fotos)
                m = min(len(s), len(scan.video))
                sch[nf:nf + m] = s[:m]
                if len(s) < len(scan.video):
                    self.warnungen.append(f"rgb.mp4 hat {len(s)} Bilder, odometry.csv {len(scan.video)} Zeilen")
                    for k in range(nf + m, len(alle)):
                        sch[k] = -1
            except RuntimeError as exc:
                self.warnungen.append(str(exc))
                sch[~ist_foto] = -1
        gueltig = np.array([auswahl.sichtbar(a.K, R, tt, a.w, a.h, fokus) and sch[i] >= 0
                            for i, (a, R, tt) in enumerate(zip(alle, R_alle, t_alle))])
        # Videobilder brauchen Tiefe; Fotos ohne Tiefe zählen für Kanten und Masken, nicht für die TSDF.
        # Fotos mit eingeschränktem Tracking (SCAN.md, fotos.json „tracking“) haben keine verlässliche Lage.
        gueltig &= np.array([a.art == "foto" or a.tiefe is not None for a in alle])
        for i, a in enumerate(alle):
            tr = str(a.extra.get("tracking") or "normal")
            if a.art == "foto" and tr != "normal":
                gueltig[i] = False
                self.warnungen.append(f"{a.name}: Tracking {tr}, Foto nicht genutzt")
        if self.video_bilder is not None:
            nvid = int(self.video_bilder)
        else:
            nvid = (12 if self.schnell else 40) if len(scan.fotos) else (24 if self.schnell else 60)
        wahl = auswahl.waehlen(zentren, richtungen, ist_foto, nvid, sch if scan.video_datei else None, abstand,
                               gueltig=gueltig)
        wahl = [i for i in wahl if gueltig[i]]
        if len(wahl) < 2:
            raise fmt.ScanFehler(f"Zu wenige brauchbare Bilder ({len(wahl)}): Objekt nicht im Bild oder Tiefe fehlt")
        self.zeiten["auswahl"] = time.perf_counter() - t

        # 3. Bilder in Arbeitsgröße
        t = time.perf_counter()
        self.fortschritt("bilder", 0.0, f"{len(wahl)} Bilder holen")
        bilder: list[dict[str, Any]] = []
        vid = [i for i in wahl if not ist_foto[i]]
        geholt = auswahl.video_bilder(scan.video_datei, [alle[i].index for i in vid], self.aus / "bilder",
                                      [alle[i].name for i in vid]) if vid else {}
        def hole(i: int) -> dict[str, Any] | None:
            a = alle[i]
            if a.art == "foto":
                im = cv2.imread(str(a.datei))
                if im is None:
                    self.warnungen.append(f"{a.datei.name} nicht lesbar")
                    return None
                datei = self.aus / "bilder" / f"{a.name}.jpg"
            else:
                datei = geholt.get(a.index)
                if datei is None:
                    self.warnungen.append(f"Videobild {a.index} nicht dekodiert")
                    return None
                im = cv2.imread(str(datei))
            h0, w0 = im.shape[:2]
            s = min(1.0, ARBEIT / max(w0, h0))
            K = a.K.copy()
            if (w0, h0) != (a.w, a.h):  # Kameramatrix gilt für a.w × a.h
                K[0] *= w0 / a.w
                K[1] *= h0 / a.h
            if s < 1.0:
                im = cv2.resize(im, (round(w0 * s), round(h0 * s)), interpolation=cv2.INTER_AREA)
                K[0] *= im.shape[1] / w0
                K[1] *= im.shape[0] / h0
            if a.art == "foto" or s < 1.0:
                cv2.imwrite(str(datei), im, [cv2.IMWRITE_JPEG_QUALITY, 93])
            # Tiefe eines Fotos aus dem letzten Videobild (SCAN.md, tiefe_quelle "videobild"): Lage leicht anders,
            # deshalb halbes Gewicht in TSDF und fotomess
            gewicht = 0.5 if a.extra.get("tiefe_quelle") == "videobild" else 1.0
            return {"name": a.name, "art": a.art, "index": a.index, "zeit": a.zeit, "datei": datei,
                    "w": im.shape[1], "h": im.shape[0], "K": K, "R": R_alle[i], "t": t_alle[i],
                    "lidar": a.tiefe, "konf": a.konfidenz, "gewicht": gewicht}

        from concurrent.futures import ThreadPoolExecutor  # JPEG lesen und verkleinern gibt die GIL frei

        with ThreadPoolExecutor(max_workers=4) as pool:
            for j, b in enumerate(pool.map(hole, wahl)):
                if b is not None:
                    bilder.append(b)
                self.fortschritt("bilder", (j + 1) / len(wahl), f"Bild {j + 1} von {len(wahl)}")
        self.zeiten["bilder"] = time.perf_counter() - t

        # 4. Boden und Objektbox (Kev-CAD-Welt vor dem Verschieben)
        boden_z, box_lo, box_hi, box_quelle = self._boden_und_box(scan, bilder, fokus, abstand)

        # 5. Tiefe je Bild
        t = time.perf_counter()
        schaetzer = None
        if not self.ohne_promptda:
            self.fortschritt("tiefe", 0.0, f"PromptDA {self.modell} laden")
            from kevscan.tiefe import Tiefenschaetzer

            schaetzer = Tiefenschaetzer(self.modell, self.geraet, angleichen=self.angleichen)
            self.zeiten["modell_laden"] = schaetzer.ladezeit_s
        je_bild: list[float] = []
        lidar_diff: list[float] = []
        faktoren: list[float] = []
        for j, b in enumerate(bilder):
            tb = time.perf_counter()
            lidar = fmt.lies_tiefe(b["lidar"])
            konf = fmt.lies_konfidenz(b["konf"], lidar.shape if lidar is not None else None)
            im = cv2.imread(str(b["datei"]))
            wt, ht = arbeitsgroesse(b["w"], b["h"])
            if lidar is None:
                b["tiefe"] = None
                continue
            if schaetzer is not None:
                tiefe, kg = schaetzer.schaetze(im, lidar, konf)
                faktoren.append(schaetzer.faktor)
            else:
                tiefe, kg = lidar_hochgerechnet(lidar, konf, wt, ht)
            sprung = tiefensprung(tiefe)
            tiefe = np.where(sprung, 0.0, tiefe).astype(np.float32)
            kg = (np.where(sprung, 0.0, kg) * b["gewicht"]).astype(np.float32)
            ht, wt = tiefe.shape
            Kt = b["K"].copy()
            Kt[0] *= wt / b["w"]
            Kt[1] *= ht / b["h"]
            b.update(tiefe=tiefe, tiefe_konf=kg, K_tiefe=Kt, farbe_tiefe=cv2.cvtColor(
                cv2.resize(im, (wt, ht), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
            cv2.imwrite(str(self.aus / "tiefe" / f"{b['name']}.png"), np.clip(np.rint(tiefe), 0, 65535).astype(np.uint16))
            cv2.imwrite(str(self.aus / "tiefe" / f"{b['name']}_konf.png"), np.clip(kg * 255, 0, 255).astype(np.uint8))
            lidar_diff += _lidar_abweichung(tiefe, lidar, konf)
            je_bild.append(time.perf_counter() - tb)
            self.fortschritt("tiefe", (j + 1) / len(bilder), f"Tiefe {j + 1} von {len(bilder)}"
                             + (f" (PromptDA {self.modell}, {schaetzer.geraet})" if schaetzer else " (nur LiDAR)"))
        geraet = schaetzer.geraet if schaetzer else None
        del schaetzer
        self.zeiten["tiefe"] = time.perf_counter() - t
        mit_tiefe = [b for b in bilder if b.get("tiefe") is not None]
        if len(mit_tiefe) < 2:
            raise fmt.ScanFehler("Zu wenige Bilder mit Tiefe")

        # 6. TSDF
        t = time.perf_counter()
        groesse = box_hi - box_lo
        voxel = voxel_aus_box(groesse, 2.0)
        lo = box_lo.copy()
        lo[2] = boden_z
        tsdf = TSDF(lo, box_hi, voxel, trunc_fuer(voxel, 2.0 if not self.ohne_promptda else 4.0))
        for j, b in enumerate(mit_tiefe):
            tsdf.integriere(b["tiefe"], b["K_tiefe"], b["R"], b["t"], konf=b["tiefe_konf"], farbe_rgb=b["farbe_tiefe"])
            self.fortschritt("tsdf", (j + 1) / len(mit_tiefe), f"Verschmelzen {j + 1} von {len(mit_tiefe)}")
        self.zeiten["tsdf"] = time.perf_counter() - t

        # 7. Netz
        t = time.perf_counter()
        self.fortschritt("netz", 0.0, "Netz erzeugen")
        roh = tsdf.netz()
        roh = _ohne_bodenreste(roh, boden_z, tsdf.voxel)
        n, info = netzmod.aufraeumen(roh)
        if not len(n["triangles"]):
            raise fmt.ScanFehler("Kein Netz entstanden (Objekt nicht gefunden oder Tiefe unbrauchbar)")
        g = netzmod.grundriss(n["positions"], boden_z + 0.15 * float(np.ptp(n["positions"][:, 2])))
        A = geo.rz(-math.radians(g["winkel_grad"]))
        bvec = -A @ np.array([g["mitte_x"], g["mitte_y"], boden_z])
        P = n["positions"] @ A.T + bvec
        T = n["triangles"]
        for b in bilder:
            b["R"], b["t"] = geo.bewegt(b["R"], b["t"], A, bvec)
        self.zeiten["netz"] = time.perf_counter() - t

        # 8. Masken, Punktwolke, Genauigkeit
        t = time.perf_counter()

        def maske(b: dict) -> None:
            m = netzmod.silhouette(P, T, b["K"], b["R"], b["t"], b["w"], b["h"])
            cv2.imwrite(str(self.aus / "masken" / f"{b['name']}.png"), np.clip(m * 255, 0, 255).astype(np.uint8))
            b["maske_anteil"] = float((m >= 0.5).mean())

        from concurrent.futures import ThreadPoolExecutor  # OpenCV gibt die GIL frei

        with ThreadPoolExecutor(max_workers=4) as pool:
            for j, _ in enumerate(pool.map(maske, bilder)):
                self.fortschritt("masken", (j + 1) / len(bilder), f"Maske {j + 1} von {len(bilder)}")
        self.zeiten["masken"] = time.perf_counter() - t

        t = time.perf_counter()
        self.fortschritt("bericht", 0.0, "Punktwolke und Genauigkeit")
        punkte, farben, abst = _punktwolke_und_abstand(mit_tiefe, P, T, box_lo, box_hi, A, bvec)
        normale = netzmod.normalen(P, T)
        kopf = (f"Kev Scan {scan.name}, mm, Z oben, Boden z = 0, Mitte x = y = 0, lange Seite = X\n"
                f"Quelle {scan.ordner}")
        netzmod.schreibe_obj(self.aus / "netz_mm.obj", P, T, kopf)
        netzmod.schreibe_ply(self.aus / "netz_mm.ply", P, T, farbe=n.get("colors"), normale=normale)
        if len(punkte):
            netzmod.schreibe_ply(self.aus / "punkte_mm.ply", punkte, farbe=farben)
        self._kameras_schreiben(bilder)
        sichtbar = _sichtbarkeit(P, bilder)
        lo_p, hi_p = np.percentile(P, 0.1, axis=0), np.percentile(P, 99.9, axis=0)
        zeiten = {k: round(v, 2) for k, v in self.zeiten.items()}
        zeiten["gesamt"] = round(time.perf_counter() - t_start, 2)
        if je_bild:
            zeiten["tiefe_je_bild"] = round(statistics.median(je_bild), 3)
            zeiten["tiefe_je_bild_mittel"] = round(statistics.fmean(je_bild), 3)
            zeiten["tiefe_erstes_bild"] = round(je_bild[0], 3)
        zeiten["tsdf_je_bild"] = round(self.zeiten["tsdf"] / max(1, len(mit_tiefe)), 3)
        bericht = {
            "format": BERICHT_FORMAT, "stand": time.strftime("%Y-%m-%dT%H:%M:%S"), "scan": scan.name,
            "quelle": str(scan.ordner), "meta": {k: scan.meta.get(k) for k in ("id", "geraet", "ios", "app", "erstellt",
                                                                         "hz", "dauer_s", "zeit_bezug", "videoformat")},
            "tiefe": {"verfahren": "lidar" if self.ohne_promptda else "promptda", "modell": None if self.ohne_promptda
                      else self.modell, "geraet": geraet, "an_lidar_angeglichen": bool(faktoren) and self.angleichen,
                      "massstab_an_lidar": {"median": round(float(np.median(faktoren)), 4),
                                            "min": round(min(faktoren), 4), "max": round(max(faktoren), 4)}
                      if faktoren else None},
            "bilder": {"fotos": sum(1 for b in bilder if b["art"] == "foto"),
                       "video": sum(1 for b in bilder if b["art"] == "video"), "gesamt": len(bilder),
                       "mit_tiefe": len(mit_tiefe), "videobilder_im_scan": len(scan.video),
                       "fotos_im_scan": len(scan.fotos)},
            "rekonstruktion": {"images": len(bilder), "posed": len(bilder)},
            "objekt": {"dreiecke": info.get("dreiecke"), "dreiecke_gesamt": info.get("dreiecke_gesamt"),
                       "komponenten": info.get("komponenten"), "box_quelle": box_quelle},
            "voxel_mm": round(tsdf.voxel, 3), "trunc_mm": round(tsdf.trunc, 2), "punkte": int(len(punkte)),
            "huellmass_mm": {"laenge": round(float(hi_p[0] - lo_p[0]), 1), "breite": round(float(hi_p[1] - lo_p[1]), 1),
                             "hoehe": round(float(hi_p[2]), 1)},
            "grundriss_mm": {"laenge": round(g["laenge"], 1), "breite": round(g["breite"], 1)},
            "oberkante_mm": round(float(hi_p[2]), 1),
            "genauigkeit": {**abst, "lidar_gegen_tiefe_mm": _quantile(lidar_diff)},
            "abdeckung": {**_abdeckung(bilder), **sichtbar},
            "boden": {"quelle": box_quelle, "hoehe_ar_m": round(float(boden_z) / 1000.0, 4),
                      "streuung_mm": round(getattr(self, "boden_streuung", 0.0), 2)},
            "box_mm": {"groesse": [round(float(x), 1) for x in (box_hi - box_lo)]},
            "transformation": {"beschreibung": "X_kevcad = A · (1000 · M · X_arkit) + b, M = [[1,0,0],[0,0,-1],[0,1,0]]",
                               "A": A.tolist(), "b": bvec.tolist(), "matrix": geo.matrix4(A @ geo.M_AR * 1000.0, bvec)},
            "zeiten": zeiten, "warnungen": self.warnungen,
            "dateien": {"netz": "netz_mm.obj", "netz_ply": "netz_mm.ply", "punkte": "punkte_mm.ply" if len(punkte)
                        else None, "posen": "poses.json", "kameras": "kameras.json"},
        }
        (self.aus / "bericht.json").write_text(json.dumps(bericht, indent=1, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(self.aus / ".scan", ignore_errors=True)
        self.fortschritt("bericht", 1.0, "fertig")
        return self.aus / "bericht.json"

    # ------------------------------------------------------------------------------------------------- Boden, Box
    def _boden_und_box(self, scan: fmt.Scan, bilder: list[dict], fokus: np.ndarray, abstand: float):
        """(boden_z, box_lo, box_hi, quelle) in der Kev-CAD-Welt vor dem Verschieben (mm)."""
        obj = scan.objekt or {}
        boden_z = None
        quelle = "geschaetzt"
        if isinstance(obj.get("boden"), dict) and obj["boden"].get("punkt") is not None:
            boden_z = float(geo.punkte_ar_zu_kev(np.asarray(obj["boden"]["punkt"], float)[None])[0, 2])
            quelle = "objekt.json"
        box = obj.get("box") if isinstance(obj.get("box"), dict) else None
        if box and box.get("mitte") is not None and box.get("groesse") is not None:
            m = geo.punkte_ar_zu_kev(np.asarray(box["mitte"], float)[None])[0]
            b, h, tt = (1000.0 * float(x) for x in box["groesse"])
            ecken = np.array([[sx * b / 2, sy * tt / 2, sz * h / 2] for sx in (-1, 1) for sy in (-1, 1)
                              for sz in (-1, 1)])
            ecken = ecken @ geo.rz(math.radians(float(box.get("drehung_y_grad") or 0.0))).T + m
            lo, hi = ecken.min(0), ecken.max(0)
            if boden_z is None:
                boden_z = float(lo[2])
            rand = 20.0
            return boden_z, lo - [rand, rand, 0], hi + [rand, rand, rand], "objekt.json"
        P = _lidar_punkte(bilder)
        if not len(P):
            raise fmt.ScanFehler("Keine LiDAR-Tiefe im Scan: Boden und Objekt lassen sich nicht finden")
        radius = max(150.0, 0.8 * abstand)
        nah = np.linalg.norm(P[:, :2] - fokus[:2], axis=1) < radius
        Q = P[nah] if nah.sum() > 200 else P
        if boden_z is None:
            unten = Q[Q[:, 2] < fokus[2]]
            unten = unten if len(unten) > 100 else Q
            z = unten[:, 2]
            bins = np.arange(z.min() - 4, z.max() + 8, 4.0)
            hist, kanten = np.histogram(z, bins=bins)
            k = int(np.argmax(hist))
            z0 = 0.5 * (kanten[k] + kanten[k + 1])
            boden_z = float(np.median(z[np.abs(z - z0) < 8.0]))
        # Schwelle über dem Boden aus der Streuung der Bodenpunkte (Rauschen und Lagefehler von ARKit), mindestens 8 mm
        zb = Q[np.abs(Q[:, 2] - boden_z) < 25.0, 2]
        streuung = 1.4826 * float(np.median(np.abs(zb - np.median(zb)))) if len(zb) > 50 else 0.0
        self.boden_streuung = streuung
        ueber = Q[(Q[:, 2] > boden_z + max(8.0, 4.0 * streuung))]
        if len(ueber) < 50:
            raise fmt.ScanFehler("Über dem Boden ist kein Objekt zu finden (zu flach oder nicht im Bild)")
        # Belegung im Grundriss (1 cm), Gruppe am Fokuspunkt
        zelle = 10.0
        ij = np.floor((ueber[:, :2] - fokus[:2]) / zelle).astype(int)
        r = int(math.ceil(radius / zelle)) + 1
        gitter = np.zeros((2 * r + 1, 2 * r + 1), np.uint8)
        ok = (np.abs(ij) <= r).all(1)
        np.add.at(gitter, (ij[ok, 0] + r, ij[ok, 1] + r), 1)
        belegt = (gitter >= 2).astype(np.uint8)
        belegt = cv2.morphologyEx(belegt, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n_lab, lab = cv2.connectedComponents(belegt, connectivity=8)
        if n_lab <= 1:
            raise fmt.ScanFehler("Kein Objekt über dem Boden gefunden")
        mitte = (r, r)
        if lab[mitte] > 0:
            wahl = lab[mitte]
        else:
            ys, xs = np.nonzero(lab)
            k = int(np.argmin((ys - r) ** 2 + (xs - r) ** 2))
            wahl = lab[ys[k], xs[k]]
        drin = ok.copy()
        drin[ok] = lab[ij[ok, 0] + r, ij[ok, 1] + r] == wahl
        O = ueber[drin]
        lo = np.percentile(O, 0.5, axis=0)
        hi = np.percentile(O, 99.5, axis=0)
        rand = 25.0
        lo = np.array([lo[0] - rand, lo[1] - rand, boden_z])
        hi = np.array([hi[0] + rand, hi[1] + rand, hi[2] + rand])
        return boden_z, lo, hi, quelle

    # ------------------------------------------------------------------------------------------------- Ausgabe
    def _kameras_schreiben(self, bilder: list[dict]) -> None:
        kameras, posen = [], []
        for b in bilder:
            R, t, K = b["R"], b["t"], b["K"]
            C = geo.zentrum(R, t)
            kam = {"R": R.tolist(), "t": t.tolist(), "f": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]),
                   "cy": float(K[1, 2]), "w": int(b["w"]), "h": int(b["h"])}
            rel = {"bild": f"bilder/{b['name']}.jpg", "maske": f"masken/{b['name']}.png"}
            if b.get("tiefe") is not None:
                rel.update(tiefe=f"tiefe/{b['name']}.png", konfidenz=f"tiefe/{b['name']}_konf.png",
                           tiefe_groesse=[int(b["tiefe"].shape[1]), int(b["tiefe"].shape[0])])
            kameras.append({"name": b["name"], "art": b["art"], "zeit": b["zeit"], "kamera": kam, **rel,
                            "maske_anteil": round(b.get("maske_anteil", 0.0), 4)})
            # Kamera -> Welt in der Form von RealityKit/ARKit (X rechts, Y oben, Blick -Z), wie kevcad-capture
            c2w = np.eye(4)
            c2w[:3, :3] = R.T @ geo.F_CAM
            c2w[:3, 3] = C
            hfov = math.degrees(2 * math.atan(b["w"] / (2 * K[0, 0])))
            posen.append({"image": f"{b['name']}.jpg", "path": str((self.aus / rel["bild"]).resolve()),
                          "width": int(b["w"]), "height": int(b["h"]),
                          "time_s": b["zeit"] if b["art"] == "video" else None,
                          "video_frame": b["index"] if b["art"] == "video" else None, "art": b["art"],
                          "aligned": {"opencv": {"R": R.tolist(), "t": t.tolist()}, "K": K.tolist(),
                                      "fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]),
                                      "cy": float(K[1, 2]), "hfov_deg": round(hfov, 3),
                                      "camera_to_world": c2w.tolist(), "position": C.tolist(),
                                      "view_dir": R[2].tolist(), "up": (-R[1]).tolist()},
                          **{k: v for k, v in rel.items() if k != "bild"}})
        (self.aus / "kameras.json").write_text(json.dumps(
            {"format": "kevscan/kameras", "netz": "netz_mm.obj", "punkte": "punkte_mm.ply", "bilder": kameras},
            indent=1, ensure_ascii=False), encoding="utf-8")
        (self.aus / "poses.json").write_text(json.dumps(
            {"format": "kevcad-capture/poses", "quelle": "kevscan", "system": "Kev CAD, mm, Z oben, Boden z = 0",
             "cameras": posen}, indent=1, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------------------------------------- Hilfen

def tiefensprung(tiefe: np.ndarray, fenster: int = 5, relativ: float = 0.03, absolut_mm: float = 2.0) -> np.ndarray:
    """Pixel an Tiefensprüngen (Spannweite im Fenster über 3 % der Tiefe plus 2 mm): dort mischt jede Schätzung
    Vorder- und Hintergrund (fliegende Punkte, „Krempe“ um Kanten). Sie zählen weder in der TSDF noch in fotomess."""
    k = np.ones((fenster, fenster), np.uint8)
    t = tiefe.astype(np.float32)
    leer = t <= 0
    hoch = cv2.dilate(np.where(leer, 0, t), k)
    tief = cv2.erode(np.where(leer, 1e9, t), k)
    spanne = hoch - np.minimum(tief, hoch)
    return (spanne > relativ * np.maximum(t, 1.0) + absolut_mm) | cv2.dilate(leer.astype(np.uint8), k).astype(bool)


def _lidar_punkte(bilder: list[dict], schritt: int = 2) -> np.ndarray:
    """LiDAR-Punkte mit hoher Konfidenz aus allen gewählten Bildern (Kev-CAD-Welt, mm)."""
    alle = []
    for b in bilder:
        d = fmt.lies_tiefe(b["lidar"])
        if d is None:
            continue
        c = fmt.lies_konfidenz(b["konf"], d.shape)
        h, w = d.shape
        K = b["K"].copy()
        K[0] *= w / b["w"]
        K[1] *= h / b["h"]
        v, u = np.mgrid[0:h:schritt, 0:w:schritt]
        z = d[v, u]
        ok = (z > 0) & (c[v, u] >= 2)
        u, v, z = u[ok] + 0.5, v[ok] + 0.5, z[ok]
        Xc = np.stack([(u - K[0, 2]) / K[0, 0] * z, (v - K[1, 2]) / K[1, 1] * z, z], 1)
        alle.append((Xc - b["t"]) @ b["R"])
    return np.concatenate(alle) if alle else np.zeros((0, 3))


def _ohne_bodenreste(netz: dict[str, np.ndarray], boden_z: float, voxel: float) -> dict[str, np.ndarray]:
    """Waagrechte, nach oben zeigende Dreiecke dicht über dem Boden weg (Boden, wenn er etwas zu tief geschätzt ist)."""
    P, T = netz["positions"], netz["triangles"]
    if not len(T):
        return netz
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    z = (a[:, 2] + b[:, 2] + c[:, 2]) / 3
    weg = (np.abs(n[:, 2]) > 0.7) & (z < boden_z + max(4.0 * voxel, 8.0))
    return {**netz, "triangles": T[~weg]}


def _lidar_abweichung(tiefe: np.ndarray, lidar: np.ndarray, konf: np.ndarray | None) -> list[float]:
    """|Tiefe − LiDAR| (mm) an LiDAR-Punkten hoher Konfidenz, je Bild höchstens 2000 Werte."""
    h, w = lidar.shape
    ht, wt = tiefe.shape
    v, u = np.nonzero((lidar > 0) & ((konf >= 2) if konf is not None else True))
    if not len(u):
        return []
    sel = np.linspace(0, len(u) - 1, min(2000, len(u))).astype(int)
    u, v = u[sel], v[sel]
    tu = np.clip(((u + 0.5) * wt / w).astype(int), 0, wt - 1)
    tv = np.clip(((v + 0.5) * ht / h).astype(int), 0, ht - 1)
    d = tiefe[tv, tu]
    ok = d > 0
    return np.abs(d[ok] - lidar[v[ok], u[ok]]).tolist()


def _quantile(werte: list[float] | np.ndarray) -> dict[str, float] | None:
    if werte is None or len(werte) == 0:
        return None
    w = np.asarray(werte, float)
    return {"median": round(float(np.median(w)), 2), "p90": round(float(np.percentile(w, 90)), 2),
            "mittel": round(float(w.mean()), 2), "n": int(len(w))}


def _punktwolke_und_abstand(bilder: list[dict], P: np.ndarray, T: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                            A: np.ndarray, bvec: np.ndarray, max_punkte: int = 400_000):
    """Punktwolke aus den Tiefenbildern (im Kev-CAD-System des Netzes) und Abstand der Tiefe zum Netz."""
    from scipy.spatial import cKDTree

    S, _ = netzmod.flaechenproben(P, T, 200_000)
    baum = cKDTree(S)
    punkte, farben, abst = [], [], []
    ecken = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ A.T + bvec
    unten, oben = ecken.min(0), ecken.max(0)
    for b in bilder:
        d, kg, K = b["tiefe"], b["tiefe_konf"], b["K_tiefe"]
        h, w = d.shape
        v, u = np.mgrid[0:h:2, 0:w:2]
        z = d[v, u]
        ok = (z > 0) & (kg[v, u] > 0.4)
        uu, vv, z = u[ok] + 0.5, v[ok] + 0.5, z[ok]
        Xc = np.stack([(uu - K[0, 2]) / K[0, 0] * z, (vv - K[1, 2]) / K[1, 1] * z, z], 1)
        X = (Xc - b["t"]) @ b["R"]  # b["R"], b["t"] sind schon im Kev-CAD-System des Netzes
        rgb = b["farbe_tiefe"][v[ok], u[ok]]
        drin = (X[:, 0] > unten[0]) & (X[:, 0] < oben[0]) & (X[:, 1] > unten[1]) & (X[:, 1] < oben[1]) & \
               (X[:, 2] > 1.0) & (X[:, 2] < oben[2])
        X, rgb = X[drin], rgb[drin]
        if not len(X):
            continue
        dist, _ = baum.query(X, distance_upper_bound=30.0)
        nah = np.isfinite(dist) & (dist < 15.0)
        abst.append(dist[nah & (X[:, 2] > 3.0)])
        punkte.append(X[nah])
        farben.append(rgb[nah])
    if not punkte:
        return np.zeros((0, 3)), np.zeros((0, 3), np.uint8), {"tiefe_gegen_netz_mm": None}
    X = np.concatenate(punkte)
    F = np.concatenate(farben)
    if len(X) > max_punkte:
        sel = np.random.default_rng(5).choice(len(X), max_punkte, replace=False)
        X, F = X[sel], F[sel]
    a = np.concatenate(abst) if abst else np.zeros(0)
    return X, F.astype(np.uint8), {"tiefe_gegen_netz_mm": _quantile(a),
                                   "beschreibung": "Abstand der Tiefenpunkte aller Bilder zum Netz (bis 15 mm)"}


def _sichtbarkeit(P: np.ndarray, bilder: list[dict]) -> dict[str, float]:
    """Anteil der Netzpunkte, die mindestens ein bzw. zwei Bilder mit passender Tiefe sehen."""
    zahl = np.zeros(len(P), np.int32)
    for b in bilder:
        if b.get("tiefe") is None:
            continue
        K, d = b["K_tiefe"], b["tiefe"]
        h, w = d.shape
        Xc = P @ b["R"].T + b["t"]
        z = Xc[:, 2]
        ok = z > 1
        u = np.full(len(P), -1.0)
        v = np.full(len(P), -1.0)
        u[ok] = K[0, 0] * Xc[ok, 0] / z[ok] + K[0, 2]
        v[ok] = K[1, 1] * Xc[ok, 1] / z[ok] + K[1, 2]
        ok &= (u >= 0) & (v >= 0) & (u < w) & (v < h)
        ui, vi = u[ok].astype(int), v[ok].astype(int)
        D = d[vi, ui]
        treffer = (D > 0) & (np.abs(D - z[ok]) < 10.0)
        zahl[np.flatnonzero(ok)[treffer]] += 1
    return {"gesehen_1": round(float((zahl >= 1).mean()), 4), "gesehen_2": round(float((zahl >= 2).mean()), 4)}


def _abdeckung(bilder: list[dict]) -> dict[str, Any]:
    """Rundumsicht: Anteil der 10°-Sektoren im Grundriss mit Kamera, Höhenwinkel von bis."""
    az, el = [], []
    for b in bilder:
        C = geo.zentrum(b["R"], b["t"])
        az.append(math.degrees(math.atan2(C[1], C[0])) % 360.0)
        el.append(math.degrees(math.atan2(C[2], max(math.hypot(C[0], C[1]), 1e-9))))
    sektoren = {int(a // 10) for a in az}
    return {"azimut_anteil": round(len(sektoren) / 36.0, 3),
            "hoehenwinkel_grad": [round(min(el), 1), round(max(el), 1)] if el else None}


def auswerten(quelle: str | Path, aus: str | Path, **kw: Any) -> Path:
    return Auswertung(quelle, aus, **kw).lauf()

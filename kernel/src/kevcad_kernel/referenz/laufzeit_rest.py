"""Referenzen in der Kernel-Laufzeit, Rest von Phase 4 (22.10.2026): Abweichung als Farbkarte, Maßstab nachträglich,
Scans in der App. ``ReferenzRestMixin`` ist Basis von ``ReferenzRuntimeMixin`` (laufzeit.py) und nutzt dessen
Ablage, Läufe und Nachrichten.

Abweichung (``abweichung.py``): Nach jedem Lauf, nach einem neuen Netz, einer neuen Lage oder einem neuen Maßstab
rechnet ein eigener Faden im Hintergrund je Referenz mit Netz die Abweichung auf dem Modell (je Teil) und auf dem
Referenznetz; Teile mit unverändertem Formschlüssel kommen aus dem Zwischenspeicher. Ergebnis: je Feld ein
``REF_DEVIATION`` (nur Felder, die die App noch nicht hat), danach ``REF_LIST`` mit der Kurzfassung ``abweichung``.
MCP ``referenz_abweichung`` wartet auf die Rechnung und gibt die Kennzahlen je Teil.

Maßstab (``massstab.py``): MCP ``referenz_massstab`` und App ``REF_SCALE`` (zwei Punkte am Netz oder ein benanntes
Maß, dazu das echte Maß in mm).

Scans: ``SCAN_LIST`` an die App (beim Verbinden, nach dem Empfang, nach jeder Übernahme), ``SCAN_IMPORT`` von der App
wie MCP ``scan_importieren``.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.referenz import ablage
from kevcad_kernel.referenz import abweichung as ab
from kevcad_kernel.referenz import massstab as ms
from kevcad_kernel.referenz.ablage import ReferenzFehler

APP_TYPEN_REST = ("REF_SCALE", "SCAN_IMPORT")
SCAN_PHASEN = {"einlesen": "Einlesen", "auswahl": "Bilder wählen", "bilder": "Bilder holen",
               "tiefe": "Tiefe (PromptDA)", "tsdf": "Verschmelzen (TSDF)", "netz": "Netz erzeugen",
               "masken": "Masken", "bericht": "Bericht", "gewichte": "Modell laden"}


class ReferenzRestMixin:
    def _ref_rest_init(self) -> None:
        self._ref_abw: dict[str, dict[str, Any]] = {}
        self._ref_abw_cache: dict[str, dict[str, Any]] = {}
        self._ref_abw_flaechen: dict[str, Any] = {}
        self._ref_abw_cond = threading.Condition()
        self._ref_abw_soll = 0
        self._ref_abw_ist = 0
        self._ref_abw_gesendet: set[str] = set()
        self._ref_abw_faden: threading.Thread | None = None
        self._ref_abw_zu = False
        self._ref_welt: dict[str, tuple[str, dict[str, np.ndarray]]] = {}

    # =================================================================================================================
    # Netz im System des Modells
    # =================================================================================================================

    def _ref_netz_welt(self, projekt: Path, n: str) -> tuple[str, dict[str, np.ndarray]] | None:
        """Referenznetz so, wie die App es zeigt (``lage`` angewandt), mit einem Schlüssel für seinen Stand."""
        from kevcad_kernel.referenz import netz

        obj = ablage.ordner(projekt, n) / ablage.CAPTURE / "netz_mm.obj"
        if not obj.is_file():
            return None
        meta = ablage.lese_meta(projekt, n) or {}
        lage = meta.get("lage")
        schl = f"{obj}:{obj.stat().st_mtime_ns}:{json.dumps(lage, sort_keys=True, default=str)}"
        alt = self._ref_welt.get(str(obj))
        if alt is not None and alt[0] == schl:
            return alt
        try:
            m = netz.lies_obj(obj)
        except (OSError, ValueError) as exc:
            self._log(f"[referenz] {obj}: {exc!r}")
            return None
        if lage:
            m = netz.bewege_netz(m, np.asarray(lage["A"], float), np.asarray(lage["b"], float))
        self._ref_welt[str(obj)] = (schl, m)
        return schl, m

    # =================================================================================================================
    # Abweichung: Rechnung im Hintergrund
    # =================================================================================================================

    def _ref_abw_planen(self) -> int:
        """Neue Rechnung anstoßen (gebündelt: läuft schon eine, folgt genau eine weitere). Rückgabe: Nummer, auf die
        ``_ref_abw_warten`` wartet."""
        with self._ref_abw_cond:
            if self._ref_abw_zu:
                return self._ref_abw_soll
            self._ref_abw_soll += 1
            soll = self._ref_abw_soll
            if self._ref_abw_faden is None or not self._ref_abw_faden.is_alive():
                self._ref_abw_faden = threading.Thread(target=self._ref_abw_schleife, name="kevcad-abweichung",
                                                       daemon=True)
                self._ref_abw_faden.start()
            self._ref_abw_cond.notify_all()
        return soll

    def _ref_abw_warten(self, soll: int, warten_s: float) -> bool:
        ende = time.monotonic() + max(0.0, warten_s)
        with self._ref_abw_cond:
            while self._ref_abw_ist < soll and not self._ref_abw_zu:
                rest = ende - time.monotonic()
                if rest <= 0:
                    return False
                self._ref_abw_cond.wait(min(rest, 1.0))
        return True

    def _ref_abw_schleife(self) -> None:
        while True:
            with self._ref_abw_cond:
                while self._ref_abw_ist >= self._ref_abw_soll and not self._ref_abw_zu:
                    self._ref_abw_cond.wait()
                if self._ref_abw_zu:
                    return
                ziel = self._ref_abw_soll
            try:
                self._ref_abw_alle()
            except Exception as exc:  # noqa: BLE001 - die Farbkarte darf nie die Laufzeit aufhalten
                import traceback

                self._log(f"[referenz] Abweichung: {exc!r}\n{traceback.format_exc()}")
            with self._ref_abw_cond:
                self._ref_abw_ist = max(self._ref_abw_ist, ziel)
                self._ref_abw_cond.notify_all()

    def _ref_abw_teile(self) -> list[dict[str, Any]]:
        """Teile des aktuellen Stands ohne Kulisse, mit Netz aus PART_UPSERT und Formschlüssel."""
        from kevcad_kernel.protocol import unpack_part

        out = []
        for rec in self.scene.records():
            if rec.header.get("kulisse") or not rec.counts.get("tri"):
                continue
            try:
                arr = unpack_part(rec.header, rec.payload)
            except ValueError:
                continue
            out.append({"name": rec.name, "positions": arr["positions"], "normals": arr["normals"],
                        "triangles": arr["triangles"], "key": f"{rec.key}:{json.dumps(rec.bbox, sort_keys=True)}"})
        return out

    def _ref_abw_alle(self) -> None:
        proj = self._project
        if proj is None:
            self._ref_abw = {}
            return
        namen = ablage.namen(proj.path)
        teile = self._ref_abw_teile()
        vorbereitet = [v for v in (ab.vorbereiten(t) for t in teile) if v is not None]
        schluessel_teile = {t["name"]: t["key"] for t in teile}
        _, kanten = ab.kantenlaenge([v["flaeche"] for v in vorbereitet])
        run = int(getattr(self, "_run_no", 0) or 0)
        neu: dict[str, dict[str, Any]] = {}
        benutzt: set[str] = set()
        flaechen: dict[str, Any] = {}
        for n in namen:
            welt = self._ref_netz_welt(proj.path, n)
            if welt is None:
                continue
            ref_schl, m = welt
            meta = ablage.lese_meta(proj.path, n) or {}
            einst = meta.get("abweichung") or {}
            t0 = time.perf_counter()
            if not vorbereitet:
                neu[n] = {"stand": "failed", "run": run, "meldung": "Kein Modell in der Szene (erst rechnen)",
                          "modell": {}, "referenz": None}
                continue
            V, T = m["positions"], m["triangles"]
            grenze = ab.grenze_aus(V, einst.get("grenze_mm"))
            rk = ab.schluessel(ref_schl, round(grenze, 3))
            flaeche = self._ref_abw_flaechen.get(rk) or flaechen.get(rk)
            felder_m: dict[str, dict[str, Any]] = {}
            gerechnet = 0
            for v, L in zip(vorbereitet, kanten):
                fk = ab.schluessel(rk, schluessel_teile[v["name"]], round(L, 4))
                f = self._ref_abw_cache.get(fk)
                if f is None:
                    if flaeche is None:
                        flaeche = ab.Flaeche(V, T)
                    f = {**ab.teil_feld(v, L, flaeche, grenze), "feld": fk}
                    gerechnet += 1
                felder_m[v["name"]] = f
                benutzt.add(fk)
            if flaeche is not None:
                flaechen[rk] = flaeche
            rfk = ab.schluessel(rk, sorted(schluessel_teile.items()), "referenz")
            fr = self._ref_abw_cache.get(rfk)
            if fr is None:
                fr = ab.auf_referenz(teile, V, T, grenze)
                fr = {**fr, "feld": rfk} if fr is not None else None
                gerechnet += 1
            if fr is not None:
                benutzt.add(rfk)
            skala_auto = ab.skala_auto(list(felder_m.values()) + ([fr] if fr else []))
            skala = float(einst.get("skala_mm") or 0) or skala_auto
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if gerechnet:
                self._log(f"[referenz] Abweichung {n}: {gerechnet} Feld(er) gerechnet in {ms:.0f} ms "
                          f"({len(T)} Dreiecke im Netz, {len(vorbereitet)} Teile)")
            else:  # alles aus dem Zwischenspeicher: die Dauer der letzten echten Rechnung bleibt stehen
                ms = (self._ref_abw.get(n) or {}).get("ms") or ms
            neu[n] = {"stand": "done", "run": run, "grenze_mm": round(grenze, 1), "skala_mm": skala,
                      "skala_auto": skala_auto, "skala_fest": bool(einst.get("skala_mm")),
                      "angelegt": bool(meta.get("lage")), "modell": felder_m, "referenz": fr,
                      "ms": ms, "meldung": None}
        # Zwischenspeicher: nur, was in dieser Runde gebraucht wurde
        alle = {f["feld"]: f for e in neu.values() for f in list(e.get("modell", {}).values()) +
                ([e["referenz"]] if e.get("referenz") else [])}
        self._ref_abw_cache = {k: alle[k] for k in benutzt if k in alle}
        self._ref_abw_flaechen = flaechen
        if self._project is None or self._project.path != proj.path:
            return
        self._ref_abw = neu
        self._ref_abw_senden()
        self._ref_liste_senden(sofort=True)

    def _ref_abw_felder(self, n: str) -> list[tuple[str, dict[str, Any]]]:
        e = self._ref_abw.get(n) or {}
        out = [("modell", f) for f in (e.get("modell") or {}).values()]
        if e.get("referenz"):
            out.append(("referenz", e["referenz"]))
        return out

    def _ref_abw_senden(self, conn: Any = None) -> None:
        from kevcad_kernel.protocol import pack_ref_abweichung

        if conn is not None:
            self._ref_abw_gesendet = set()
        send = conn.send if conn is not None else self._send_app
        for n, e in list(self._ref_abw.items()):
            for auf, f in self._ref_abw_felder(n):
                if f["feld"] in self._ref_abw_gesendet:
                    continue
                kopf, nutz = pack_ref_abweichung(referenz=n, run=int(e.get("run") or 0), auf=auf, teil=f.get("teil"),
                                                 feld=f["feld"], punkte=f["punkte"], dreiecke=f["dreiecke"],
                                                 werte=f["werte"], grenze_mm=e.get("grenze_mm"),
                                                 kennzahlen=f.get("kennzahlen"))
                kopf.pop("seq", None)
                if send(kopf, nutz) is not False:
                    self._ref_abw_gesendet.add(f["feld"])

    def _ref_abw_kurz(self, n: str) -> dict[str, Any] | None:
        """Kurzfassung für REF_LIST und MCP ``referenzen`` (ohne Felder)."""
        e = self._ref_abw.get(n)
        if not e:
            return None
        kurz = {k: e.get(k) for k in ("stand", "run", "grenze_mm", "skala_mm", "skala_auto", "skala_fest",
                                      "angelegt", "ms", "meldung")}
        kurz["teile"] = [{"teil": t, "feld": f["feld"], **f["kennzahlen"]} for t, f in (e.get("modell") or {}).items()]
        r = e.get("referenz")
        kurz["referenz"] = {"feld": r["feld"], **r["kennzahlen"]} if r else None
        return kurz

    def _referenz_nach_lauf(self, run: int) -> None:
        """Nach jedem Lauf: Abweichung neu, wenn eine Referenz ein Netz hat (Teile ohne Änderung aus dem Speicher)."""
        proj = self._project
        if proj is None:
            return
        if any((ablage.ordner(proj.path, n) / ablage.CAPTURE / "netz_mm.obj").is_file()
               for n in ablage.namen(proj.path)):
            self._ref_abw_planen()

    def _ref_rest_schliessen(self) -> None:
        with self._ref_abw_cond:
            self._ref_abw_zu = True
            self._ref_abw_cond.notify_all()

    # =================================================================================================================
    # KernelService
    # =================================================================================================================

    def referenz_abweichung(self, name: str | None = None, teile: list[str] | None = None,
                            grenze_mm: float | None = None, skala_mm: float | None = None, zeigen: bool = False,
                            auf: str = "modell", warten_s: float = 120.0) -> dict[str, Any]:
        """Abweichung Modell ↔ Referenznetz je Teil. {"ok", "referenz", "grenze_mm", "skala_mm", "teile": [{teil,
        mittel_mm, max_mm, p95_mm, versatz_mm, abgedeckt, ort_max}], "referenz_netz": {…}, "angelegt", "ms",
        "hinweise", "gezeigt"?}"""
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        if auf not in ("modell", "referenz"):
            return {"ok": False, "error": "auf: modell oder referenz"}
        try:
            n = ablage.finde(proj.path, name)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        if not (ablage.ordner(proj.path, n) / ablage.CAPTURE / "netz_mm.obj").is_file():
            return {"ok": False, "error": f"Die Referenz {n} hat kein Netz (Object Capture bzw. Scan fehlt); ohne Netz "
                                          "gibt es keine Abweichung. Fotos: Fotoansicht mit Differenz nutzen."}
        if grenze_mm is not None or skala_mm is not None:
            meta = ablage.lese_meta(proj.path, n) or {}
            einst = dict(meta.get("abweichung") or {})
            for k, v in (("grenze_mm", grenze_mm), ("skala_mm", skala_mm)):
                if v is not None:
                    if float(v) > 0:
                        einst[k] = float(v)
                    else:
                        einst.pop(k, None)  # 0 = wieder automatisch
            meta["abweichung"] = einst
            ablage.schreibe_meta(proj.path, n, meta)
        soll = self._ref_abw_planen()
        if not self._ref_abw_warten(soll, warten_s):
            return {"ok": False, "error": f"Die Abweichung ist nach {warten_s:.0f} s noch nicht fertig"}
        kurz = self._ref_abw_kurz(n)
        if not kurz:
            return {"ok": False, "error": f"Für {n} wurde keine Abweichung gerechnet"}
        if kurz.get("stand") != "done":
            return {"ok": False, "error": kurz.get("meldung") or "Abweichung nicht gerechnet"}
        liste = kurz["teile"]
        if teile:
            gesucht = [str(t) for t in teile]
            liste = [t for t in liste if any(t["teil"] == g or t["teil"].startswith(g.rstrip("/") + "/")
                                             for g in gesucht)]
            if not liste:
                return {"ok": False, "error": f"Keines der Teile {', '.join(gesucht)} ist im Modell"}
        hinweise = []
        if not kurz.get("angelegt"):
            hinweise.append("Das Netz ist nicht am Modell angelegt (System von Object Capture bzw. des Scans: Boden "
                            "z = 0, Mitte x = y = 0); die Abweichung enthält auch den Lagefehler. Erst "
                            "referenz_vermessen, dann liegt es am Modell.")
        wenig = [t["teil"] for t in liste if (t.get("abgedeckt") or 0) < 0.3]
        if wenig:
            hinweise.append(f"Kaum Referenz in der Nähe (unter 30 % abgedeckt): {', '.join(wenig[:6])}")
        out = {"ok": True, "referenz": n, "grenze_mm": kurz["grenze_mm"], "skala_mm": kurz["skala_mm"],
               "skala_fest": kurz["skala_fest"], "teile": liste, "referenz_netz": kurz["referenz"],
               "angelegt": kurz["angelegt"], "ms": kurz["ms"], "run": kurz["run"], "hinweise": hinweise}
        if zeigen:
            if self._link.connected:
                res = self.view_command("referenz_abweichung", {"name": n, "auf": auf, "an": True}, timeout_s=20)
                out["gezeigt"] = bool(res.get("ok"))
                if not res.get("ok"):
                    out["hinweise"].append(f"Anzeige in der App: {res.get('error') or res.get('message')}")
            else:
                out["gezeigt"] = False
        return out

    def referenz_massstab(self, name: str | None = None, mm: float = 0.0, punkte: list[list[float]] | None = None,
                          kante: str | None = None) -> dict[str, Any]:
        """Maßstab einer Referenz setzen: zwei Punkte am Netz (Welt, mm, wie im Viewer) oder ein benanntes Maß, dazu
        der echte Abstand ``mm``. {"ok", "referenz", "faktor", "faktor_gesamt", "ist_mm", "mm", "geaendert",
        "messung_skaliert", "punkte_am_netz", "text", "hinweise"}"""
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        try:
            n = ablage.finde(proj.path, name)
            return self._ref_massstab(proj, n, float(mm or 0), punkte, kante)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        except (OSError, ValueError, KeyError) as exc:
            return {"ok": False, "error": f"Maßstab nicht gesetzt: {type(exc).__name__}: {exc}"}

    def _ref_massstab(self, proj: Any, n: str, mm: float, punkte: Any, kante: str | None) -> dict[str, Any]:
        schluessel = (str(proj.path), n)
        with self._ref_lock:
            lauf = self._ref_laeufe.get(schluessel)
        if lauf is not None:
            raise ReferenzFehler(f"Für die Referenz {n} läuft gerade {lauf['art']}; danach den Maßstab setzen")
        meta = ablage.lese_meta(proj.path, n)
        if meta is None:
            raise ReferenzFehler(f"referenz.json von {n} ist nicht lesbar")
        if meta.get("art") == "scan":
            raise ReferenzFehler(f"{n} ist ein Scan vom iPhone: LiDAR und ARKit machen ihn metrisch, der Maßstab "
                                 "steht schon. Weicht ein Maß ab, lieber neu scannen oder referenz_vermessen mit "
                                 "bekannte_masse.")
        if (punkte is None) == (not kante):
            raise ReferenzFehler("Entweder punkte (zwei Punkte am Netz) oder kante (benanntes Maß) angeben")
        ordner = ablage.ordner(proj.path, n)
        messung = None
        ms_datei = ordner / ablage.MESSUNG / "messung.json"
        if ms_datei.is_file():
            try:
                messung = json.loads(ms_datei.read_text("utf-8"))
            except (OSError, ValueError):
                messung = None
        hinweise: list[str] = []
        am_netz = None
        if punkte is not None:
            pk = np.asarray(punkte, float).reshape(-1, 3) if len(punkte) else np.zeros((0, 3))
            if pk.shape != (2, 3):
                raise ReferenzFehler("punkte: genau zwei Punkte [x, y, z] in mm")
            welt = self._ref_netz_welt(proj.path, n)
            if welt is None:
                raise ReferenzFehler(f"Die Referenz {n} hat kein Netz: kante mit einem gemessenen Maß angeben")
            _, m = welt
            flaeche = ab.Flaeche(m["positions"], m["triangles"])
            d, Q, _ = flaeche.abfrage(pk)
            spann = float(np.linalg.norm(pk[1] - pk[0]))
            if float(d.max()) > max(3.0, 0.05 * spann):
                raise ReferenzFehler(f"Ein Punkt liegt {_de(float(d.max()), 1)} mm neben dem Netz: Punkte am Netz "
                                     "wählen")
            am_netz = [[round(float(x), 2) for x in q] for q in Q]
            ist = float(np.linalg.norm(Q[1] - Q[0]))
            art = "punkte"
            mit_messung = False
        else:
            ist, art = ms.kante_ist(meta, messung, str(kante))
            mit_messung = art == "messung"
        f = ms.faktor_pruefen(mm, ist)
        bekannt = ((meta.get("messung") or {}).get("bekannt") or {})
        if messung is not None and not mit_messung:
            hinweise.append("Die Vermessung bleibt: ihr Maßstab kommt aus den Maßen von model.py"
                            + (f" (bekannt: {', '.join(f'{k} = {v:g} mm' for k, v in bekannt.items())})"
                               if bekannt else "") + "; skaliert sind Netz und Kameras von Object Capture")
        erg = ms.ordner_skalieren(ordner, f, mit_messung=mit_messung)
        eintrag = {"mm": round(mm, 3), "ist_mm": round(ist, 3), "quelle": art if art != "huelle" else "kante",
                   "kante": kante, "punkte": am_netz, "stand": ablage.jetzt()}
        meta = ablage.lese_meta(proj.path, n) or meta
        meta = ms.meta_skalieren(meta, f, eintrag)
        if mit_messung:
            mm_meta = dict(meta.get("messung") or {})
            mm_meta["bekannt"] = {str(kante): round(mm, 3)}
            meta["messung"] = mm_meta
        if meta.get("art") == "video" and messung is not None and (ordner / ablage.CAPTURE / "poses.json").is_file():
            try:
                self._ref_lage_neu(proj.path, n, meta, json.loads(ms_datei.read_text("utf-8")))
            except (OSError, ValueError) as exc:
                self._log(f"[referenz] Lage nach dem Maßstab {n}: {exc!r}")
        ablage.schreibe_meta(proj.path, n, meta)
        self._ref_netz_cache.pop(str(ordner / ablage.CAPTURE / "netz_mm.obj"), None)
        self._ref_welt.pop(str(ordner / ablage.CAPTURE / "netz_mm.obj"), None)
        self._log(f"[referenz] Maßstab {n}: {ist:.2f} → {mm:.2f} mm (Faktor {f:.4f}), {', '.join(erg['geaendert'])}")
        if self._project is not None and self._project.path == proj.path:
            self._ref_liste_senden(sofort=True)
            self._ref_netz_senden(proj.path, n)
            self._ref_capture_fotos_senden(proj.path, n)
            self._ref_messung_senden(proj.path, n)
        self._ref_abw_planen()
        text = (f"Maßstab von {n}: {_de(ist, 1)} mm an der Referenz sind {_de(mm, 1)} mm, Faktor {_de(f, 4)}"
                + (f" (insgesamt {_de(meta['massstab']['faktor'], 4)})"
                   if abs(meta["massstab"]["faktor"] - f) > 1e-9 else "") + "; skaliert: " + ", ".join(erg["geaendert"]))
        return {"ok": True, "referenz": n, "faktor": round(f, 6), "faktor_gesamt": meta["massstab"]["faktor"],
                "ist_mm": round(ist, 2), "mm": round(mm, 2), "geaendert": erg["geaendert"],
                "messung_skaliert": erg["messung"], "punkte_am_netz": am_netz, "text": text, "hinweise": hinweise}

    # =================================================================================================================
    # Scans in der App
    # =================================================================================================================

    def _scan_liste_nachricht(self, neu: str | None = None) -> dict[str, Any] | None:
        if not hasattr(self, "scans"):
            return None
        res = self.scans()  # type: ignore[attr-defined]
        felder = ("id", "name", "empfangen", "erstellt", "geraet", "fotos", "videobilder", "objekt", "groesse_mb",
                  "vorschau", "zustand", "referenzen")
        return {"type": "SCAN_LIST", "ordner": res.get("ordner"), "neu": neu,
                "empfaenger": {k: (res.get("empfaenger") or {}).get(k) for k in ("laeuft", "port", "name", "dienst")},
                "scans": [{k: s.get(k) for k in felder} for s in (res.get("scans") or [])[:30]]}

    def _scan_liste_senden(self, conn: Any = None, neu: str | None = None) -> None:
        try:
            msg = self._scan_liste_nachricht(neu)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[scan] SCAN_LIST: {exc!r}")
            return
        if msg is not None:
            (conn.send if conn is not None else self._send_app)(msg)

    # =================================================================================================================
    # App → Kernel
    # =================================================================================================================

    def _ref_rest_app_anfrage(self, kind: str, header: dict[str, Any], ack: Any) -> bool:
        if kind == "REF_SCALE":
            res = self.referenz_massstab(header.get("referenz"), mm=float(header.get("mm") or 0),
                                         punkte=header.get("punkte"), kante=header.get("kante") or None)
            ack(bool(res.get("ok")), res.get("text") if res.get("ok") else str(res.get("error")))
            return True
        if kind == "SCAN_IMPORT":
            res = self.scan_importieren(header.get("scan") or None, name=header.get("name") or None,  # type: ignore
                                        schnell=bool(header.get("schnell")))
            ack(bool(res.get("ok")), (f"Scan wird als Referenz {res.get('name')} ausgewertet ("
                                      f"{'schnell' if header.get('schnell') else 'genau'})") if res.get("ok")
                else str(res.get("error")))
            self._scan_liste_senden()
            return True
        return False


def _de(x: float, nd: int) -> str:
    """Zahl mit Dezimalkomma für Texte an Kevin."""
    return f"{float(x):.{nd}f}".replace(".", ",")

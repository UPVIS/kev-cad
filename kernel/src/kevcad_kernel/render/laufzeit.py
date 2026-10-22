"""Renderings in der Kernel-Laufzeit (Phase 7, PLAN-PHASE7-RENDERINGS.md R2, R11): Aufträge „R-n“ für MCP ``render`` und
den Dialog „Rendern …“ der App (``RENDER_START``), schnell über die App (``RENDER_REQ``), Foto über Blender
(``RENDER_SCENE_REQ`` und render/blender.py), Stand an die App (``RENDER_STATUS``).

Mixin für ``KernelRuntime``; nutzt dort ``_project``, ``_link``, ``_request``, ``_send_app``, ``_pool``, ``scene``,
``catalog``, ``socket_path`` und aus ``CameraRuntime`` ``_camera_name``.
"""

from __future__ import annotations

import itertools
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.protocol import render_status
from kevcad_kernel.render import blender as bl
from kevcad_kernel.render import szenen as sz
from kevcad_kernel.render.materialien import part_pbr

ENDE = ("fertig", "fehler", "abgebrochen")
SPEICHER_MIN = 20  # % frei, darunter wartet ein Foto-Lauf (höchstens SPEICHER_WARTEN_S)
SPEICHER_WARTEN_S = 120.0
MAX_AUFTRAEGE = 40


class RenderRuntime:
    def _rs(self) -> dict[str, Any]:
        st = getattr(self, "_render_state", None)
        if st is None:
            st = {"lock": threading.RLock(), "auftraege": {}, "ids": itertools.count(1),
                  "blender": threading.Lock(), "cond": threading.Condition()}
            self._render_state = st  # type: ignore[attr-defined]
        return st

    # -- öffentlich (KernelService.render) -------------------------------------------------------------------------------

    def render(self, szene: str | None = "studio", ansicht: str | None = None, kamera: str | None = None,
               groesse: Any = None, qualitaet: str = "schnell", hintergrund: str | None = None,
               umgebung: str | None = None, ziel: str | None = None, warten_s: float | None = None,
               auftrag: str | None = None, abbrechen: bool = False, bild: bool = False, samples: int | None = None,
               von: str = "agent", vorschau: bool = False) -> dict[str, Any]:
        """Rendering anstoßen oder den Stand eines Auftrags abfragen (``auftrag``), auf Wunsch abbrechen."""
        if auftrag:
            return self._render_abfrage(str(auftrag), abbrechen=abbrechen, warten_s=warten_s or 0.0, bild=bild)
        job, err = self._render_vorbereiten(szene=szene, ansicht=ansicht, kamera=kamera, groesse=groesse,
                                            qualitaet=qualitaet, hintergrund=hintergrund, umgebung=umgebung,
                                            ziel=ziel, samples=samples, von=von, vorschau=vorschau)
        if err:
            return {"ok": False, "error": err}
        assert job is not None
        if job["qualitaet"] == "schnell":
            self._render_ausfuehren(job)
            return self._render_ergebnis(job, bild=bild)
        threading.Thread(target=self._render_ausfuehren, args=(job,), name=f"kevcad-render-{job['auftrag']}",
                         daemon=True).start()
        warte = 0.0 if warten_s is None else float(warten_s)
        if warte > 0:
            self._render_warten(job, warte)
        return self._render_ergebnis(job, bild=bild)

    # -- Ablauf ---------------------------------------------------------------------------------------------------------

    def _render_vorbereiten(self, *, szene: Any, ansicht: Any, kamera: Any, groesse: Any, qualitaet: Any,
                            hintergrund: Any, umgebung: Any, ziel: Any, samples: Any, von: str,
                            vorschau: bool) -> tuple[dict[str, Any] | None, str | None]:
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return None, "Kein Projekt offen. Erst project_open oder project_new aufrufen."
        if not self._link.connected:  # type: ignore[attr-defined]
            return None, "App nicht verbunden"
        if not self.scene.records():  # type: ignore[attr-defined]
            return None, "Keine Teile: erst run aufrufen"
        datenordner = Path(self.socket_path).expanduser().parent if getattr(self, "socket_path", None) else None
        try:
            s = sz.szene(szene, hintergrund=hintergrund, umgebung=umgebung, datenordner=datenordner)
            a = sz.ansicht(ansicht)
            q = sz.qualitaet(qualitaet)
            w, h = sz.groesse(groesse)
        except sz.RenderFehler as exc:
            return None, str(exc)
        if q == "foto" and bl.blender_pfad() is None:
            return None, ("Blender fehlt: für qualitaet=\"foto\" wird /Applications/Blender.app gebraucht "
                          "(oder KEVCAD_BLENDER). Ohne Blender geht qualitaet=\"schnell\".")
        kam = None
        if kamera:
            find = getattr(self, "_camera_name", None)
            kam = find(str(kamera)) if find is not None else None
            if kam is None:
                unknown = getattr(self, "_unknown_camera", None)
                res = unknown(str(kamera)) if unknown is not None else {"error": f"Kamera {kamera!r} gibt es nicht"}
                return None, str(res.get("error") or f"Kamera {kamera!r} gibt es nicht")
        pfad = sz.zielpfad(Path(proj.output_dir), proj.name, s, q, kamera=kam, ziel=ziel, vorschau=vorschau)
        st = self._rs()
        with st["lock"]:
            nr = next(st["ids"])
            job = {"auftrag": f"R-{nr}", "zustand": "wartet", "qualitaet": q, "szene": s, "ansicht": a, "kamera": kam,
                   "width": w, "height": h, "pfad": str(pfad), "von": von, "vorschau": bool(vorschau),
                   "fortschritt": 0.0, "text": "wartet", "fehler": None, "ms": None, "t0": time.monotonic(),
                   "samples": samples, "lauf": None, "abbruch": None, "kamera_json": None, "phasen": {},
                   "teile": 0, "dreiecke": None, "geraet": None, "fertig_um": None}
            st["auftraege"][job["auftrag"]] = job
            if len(st["auftraege"]) > MAX_AUFTRAEGE:
                for alt in [k for k, j in st["auftraege"].items() if j["zustand"] in ENDE][: len(st["auftraege"]) -
                                                                                              MAX_AUFTRAEGE]:
                    st["auftraege"].pop(alt, None)
        return job, None

    def _render_druck_oben(self) -> dict[str, list[float]]:
        """Aufbaurichtung je Druckteil (Welt, Ruhelage) aus der Druckprüfung des letzten Laufs: Schichtlinien liegen
        quer dazu, nicht quer zur Z-Achse des Modells (Druckvorschau und Druckprüfung nutzen dieselbe Ausrichtung)."""
        pruef = getattr(self, "_pruef", None)
        if pruef is None:
            return {}
        check, _ = pruef.letztes()
        teile = ((check or {}).get("druck") or {}).get("teile") or {}
        out = {}
        for name, t in teile.items():
            oben = ((t or {}).get("ausrichtung") or {}).get("oben_welt")
            if isinstance(oben, list) and len(oben) == 3:
                out[name] = [float(c) for c in oben]
        return out

    def _render_materialien(self) -> list[dict[str, Any]]:
        out = []
        oben = self._render_druck_oben()
        for rec in self.scene.records():  # type: ignore[attr-defined]
            mat = self.catalog.find_material(rec.material) if rec.material else None  # type: ignore[attr-defined]
            pbr = part_pbr(rec.header, mat)
            if pbr.get("oberflaeche") == "schichten" and rec.name in oben:
                pbr["druck_oben"] = oben[rec.name]  # Schichtlinien quer zur Druckrichtung (additiv)
            out.append({"name": rec.name, **pbr, "kulisse": bool(rec.header.get("kulisse"))})
        return out

    def _render_melden(self, job: dict[str, Any], zustand: str | None = None, *, fortschritt: float | None = None,
                       text: str | None = None) -> None:
        st = self._rs()
        with st["lock"]:
            if zustand:
                job["zustand"] = zustand
            if fortschritt is not None:
                job["fortschritt"] = fortschritt
            if text is not None:
                job["text"] = text
            if job["zustand"] in ENDE and job["ms"] is None:
                job["ms"] = int((time.monotonic() - job["t0"]) * 1000)
                job["fertig_um"] = time.time()
            head = render_status(job["auftrag"], job["zustand"], qualitaet=job["qualitaet"], szene=job["szene"]["name"],
                                 fortschritt=job["fortschritt"], text=job["text"],
                                 pfad=job["pfad"] if job["zustand"] == "fertig" else None, width=job["width"],
                                 height=job["height"], ms=job["ms"], von=job["von"], vorschau=job["vorschau"],
                                 fehler=job["fehler"])
        head.pop("seq", None)
        self._send_app(head)  # type: ignore[attr-defined]
        with st["cond"]:
            st["cond"].notify_all()

    def _render_fehler(self, job: dict[str, Any], text: str) -> None:
        job["fehler"] = text
        self._render_melden(job, "abgebrochen" if job.get("abbruch") else "fehler", text=text)

    def _render_ausfuehren(self, job: dict[str, Any]) -> None:
        try:
            Path(job["pfad"]).parent.mkdir(parents=True, exist_ok=True)
            if job["qualitaet"] == "schnell":
                self._render_schnell(job)
            else:
                self._render_foto(job)
        except Exception as exc:  # noqa: BLE001 - ein Auftrag darf die Laufzeit nicht stören
            self._render_fehler(job, f"{type(exc).__name__}: {exc}")

    def _render_schnell(self, job: dict[str, Any]) -> None:
        self._render_melden(job, "laeuft", fortschritt=0.1, text="RealityKit rendert")
        w, h = job["width"], job["height"]
        req = {"type": "RENDER_REQ", "auftrag": job["auftrag"], "szene": job["szene"], "ansicht": job["ansicht"],
               "kamera": job["kamera"], "width": w, "height": h, "teile": self._render_materialien(),
               "path": job["pfad"], "vorschau": job["vorschau"]}
        # großzügig: bei großen Modellen zeichnet die App nebenher den Viewport, das erste Bild übersetzt Shader
        reply, _, error = self._request(req, 60.0 + w * h / 1e6 * 10)  # type: ignore[attr-defined]
        if error:
            self._render_fehler(job, error)
            return
        if not reply.get("ok"):
            self._render_fehler(job, str(reply.get("message") or "App konnte nicht rendern"))
            return
        job["kamera_json"] = reply.get("kamera")
        job["phasen"] = reply.get("phasen") or {}
        job["app_ms"] = reply.get("ms")
        if reply.get("path"):
            job["pfad"] = str(reply["path"])
        job["teile"] = len(self.scene.records())  # type: ignore[attr-defined]
        self._render_melden(job, "fertig", fortschritt=1.0, text=f"fertig in {self._sek(reply.get('ms'))}")

    @staticmethod
    def _sek(ms: Any) -> str:
        try:
            return f"{float(ms) / 1000:.1f} s".replace(".", ",")
        except (TypeError, ValueError):
            return "?"

    def _render_foto(self, job: dict[str, Any]) -> None:
        st = self._rs()
        lock: threading.Lock = st["blender"]
        if not lock.acquire(blocking=False):
            self._render_melden(job, "wartet", text="wartet auf den laufenden Foto-Auftrag")
            while not lock.acquire(timeout=1.0):
                if job.get("abbruch"):
                    self._render_fehler(job, job["abbruch"])
                    return
        try:
            # Speicher: ein Cycles-Lauf belegt um 5 GB; bei knappem Speicher kurz warten
            frei = bl.freier_speicher_prozent()
            bis = time.monotonic() + SPEICHER_WARTEN_S
            while frei is not None and frei < SPEICHER_MIN and time.monotonic() < bis and not job.get("abbruch"):
                self._render_melden(job, "wartet", text=f"wartet auf Speicher ({frei} % frei)")
                time.sleep(5.0)
                frei = bl.freier_speicher_prozent()
            if job.get("abbruch"):
                self._render_fehler(job, job["abbruch"])
                return
            job["speicher_frei"] = frei
            self._render_melden(job, "laeuft", fortschritt=0.01, text="Szene aus der App holen")
            reply, _, error = self._request(  # type: ignore[attr-defined]
                {"type": "RENDER_SCENE_REQ", "auftrag": job["auftrag"], "ansicht": job["ansicht"],
                 "kamera": job["kamera"], "width": job["width"], "height": job["height"],
                 "kulisse": [r.name for r in self.scene.records() if r.header.get("kulisse")]}, 30.0)  # type: ignore[attr-defined]
            if error or not reply.get("ok"):
                self._render_fehler(job, error or str(reply.get("message") or "App lieferte keine Szene"))
                return
            job["kamera_json"] = reply.get("kamera")
            materialien = {m["name"]: m for m in self._render_materialien()}
            teile = []
            for t in reply.get("teile") or []:
                rec = self.scene.get(str(t.get("name")))  # type: ignore[attr-defined]
                if rec is None or not rec.payload:
                    continue
                if job["szene"].get("transparent") and (rec.header.get("kulisse") or rec.name.startswith("Kulisse/")):
                    continue  # freigestellt: nur das Produkt
                teile.append({"name": rec.name, "header": rec.header, "payload": rec.payload,
                              "matrix": t.get("matrix"), "pbr": materialien.get(rec.name) or part_pbr(rec.header, None)})
            if not teile:
                self._render_fehler(job, "Keine sichtbaren Teile in der App")
                return
            ordner = bl.arbeitsordner()
            try:
                t0 = time.monotonic()
                samples = bl.samples_fuer(job["width"], job["height"], job.get("samples"))
                szene_json, info = bl.szene_schreiben(
                    ordner, teile=teile, kamera=job["kamera_json"], szene=job["szene"], breite=job["width"],
                    hoehe=job["height"], samples=samples, ausgabe=Path(job["pfad"]))
                job["phasen"]["szene_ms"] = int((time.monotonic() - t0) * 1000)
                job["teile"] = info["teile"]
                job["dreiecke"] = info["dreiecke"]

                def fortschritt(anteil: float, text: str) -> None:
                    self._render_melden(job, "laeuft", fortschritt=anteil, text=text)

                lauf = bl.BlenderLauf(szene_json, zeitlimit=bl.zeitlimit_s(job["width"], job["height"], samples,
                                                                            info["dreiecke"]),
                                      fortschritt=fortschritt)
                job["lauf"] = lauf
                if job.get("abbruch"):
                    self._render_fehler(job, job["abbruch"])
                    return
                res = lauf.laufen()
                job["phasen"]["blender_ms"] = res.get("ms")
                job["geraet"] = res.get("geraet")
                job["samples"] = res.get("samples", samples)
                if res.get("ok") and Path(job["pfad"]).is_file():
                    self._render_melden(job, "fertig", fortschritt=1.0,
                                        text=f"fertig in {self._sek(res.get('ms'))} ({job['samples']} Proben)")
                else:
                    job["log"] = res.get("log")
                    self._render_fehler(job, str(res.get("fehler") or "Blender lieferte kein Bild"))
            finally:
                job["lauf"] = None
                bl.aufraeumen(ordner)
        finally:
            lock.release()

    # -- Abfrage, Warten, Abbrechen ----------------------------------------------------------------------------------

    def _render_warten(self, job: dict[str, Any], warten_s: float) -> None:
        st = self._rs()
        bis = time.monotonic() + warten_s
        with st["cond"]:
            while job["zustand"] not in ENDE and time.monotonic() < bis:
                st["cond"].wait(min(1.0, max(0.05, bis - time.monotonic())))

    def _render_abfrage(self, auftrag: str, *, abbrechen: bool, warten_s: float, bild: bool) -> dict[str, Any]:
        st = self._rs()
        with st["lock"]:
            job = st["auftraege"].get(auftrag)
            namen = list(st["auftraege"])
        if job is None:
            return {"ok": False, "error": f"Auftrag {auftrag!r} unbekannt"
                                          + (f" (bekannt: {', '.join(namen[-8:])})" if namen else "")}
        if abbrechen and job["zustand"] not in ENDE:
            self._render_abbrechen(job)
        if warten_s > 0:
            self._render_warten(job, warten_s)
        return self._render_ergebnis(job, bild=bild)

    def _render_abbrechen(self, job: dict[str, Any], grund: str = "abgebrochen") -> None:
        job["abbruch"] = grund
        lauf = job.get("lauf")
        if lauf is not None:
            lauf.abbrechen(grund)

    def _render_ergebnis(self, job: dict[str, Any], *, bild: bool = False) -> dict[str, Any]:
        st = self._rs()
        with st["lock"]:
            out = {k: v for k, v in job.items() if k not in ("lauf", "t0", "abbruch", "szene")}
            out["szene"] = job["szene"]["name"]
            out["szene_titel"] = job["szene"].get("titel")
            out["hintergrund"] = job["szene"].get("hintergrund")
            if job["zustand"] not in ENDE:
                out["laeuft_s"] = round(time.monotonic() - job["t0"], 1)
        out["ok"] = job["zustand"] not in ("fehler", "abgebrochen")
        if job["zustand"] in ("fehler", "abgebrochen"):
            out["error"] = job.get("fehler") or job["zustand"]
        if bild and job["zustand"] == "fertig":
            try:
                out["png"] = Path(job["pfad"]).read_bytes()
            except OSError:
                pass
        return out

    def render_auftraege(self) -> list[dict[str, Any]]:
        st = self._rs()
        with st["lock"]:
            jobs = list(st["auftraege"].values())
        return [self._render_ergebnis(j) for j in jobs]

    # -- Nachrichten der App --------------------------------------------------------------------------------------------

    def _render_app_message(self, kind: Any, header: dict[str, Any]) -> bool:
        if kind == "RENDER_START":
            self._pool.submit(self._render_start_von_app, header)  # type: ignore[attr-defined]
            return True
        if kind == "RENDER_CANCEL":
            st = self._rs()
            with st["lock"]:
                job = st["auftraege"].get(str(header.get("auftrag") or ""))
            if job is not None and job["zustand"] not in ENDE:
                self._render_abbrechen(job, "von Kevin abgebrochen")
            self._send_app({"type": "ACK", "reply_to": header.get("id"), "ok": job is not None,  # type: ignore[attr-defined]
                            "message": "" if job is not None else "Auftrag unbekannt"})
            return True
        return False

    def _render_start_von_app(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        groesse = None
        if header.get("breite") and header.get("hoehe"):
            groesse = [int(header["breite"]), int(header["hoehe"])]
        try:
            job, err = self._render_vorbereiten(
                szene=header.get("szene"), ansicht=header.get("ansicht"), kamera=header.get("kamera"),
                groesse=groesse, qualitaet=header.get("qualitaet"), hintergrund=header.get("hintergrund"),
                umgebung=header.get("umgebung"), ziel=header.get("ziel"), samples=header.get("samples"), von="app",
                vorschau=bool(header.get("vorschau")))
        except Exception as exc:  # noqa: BLE001
            job, err = None, f"{type(exc).__name__}: {exc}"
        if err or job is None:
            self._send_app({"type": "ACK", "reply_to": rid, "ok": False, "message": err})  # type: ignore[attr-defined]
            return
        self._send_app({"type": "ACK", "reply_to": rid, "ok": True, "message": job["auftrag"]})  # type: ignore[attr-defined]
        if job["qualitaet"] == "foto":  # dauert Minuten: eigener Faden statt eines der vier Plätze im Pool
            threading.Thread(target=self._render_ausfuehren, args=(job,), name=f"kevcad-render-{job['auftrag']}",
                             daemon=True).start()
        else:
            self._render_ausfuehren(job)

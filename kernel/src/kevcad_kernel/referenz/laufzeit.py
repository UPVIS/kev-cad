"""Referenzen in der Kernel-Laufzeit (Phase 4): MCP-Dienst und Nachrichten an die App.

``ReferenzRuntimeMixin`` gehört zu ``KernelRuntime`` (runtime.py). Es nutzt von dort ``_project``, ``_send_app``,
``_pool``, ``_log``, ``_catalog_dirs`` und ``_inventory_rule``.

- ``referenz_video``: kevcad-capture im Hintergrund (Object Capture), Fortschritt als REF_LIST, am Ende REF_UPSERT
  (Netz) und REF_PHOTOS (Satz ``capture``).
- ``referenz_fotos``: Fotos in Arbeitsgröße ins Projekt kopieren (``sips``), Kameras gibt es erst nach dem Vermessen.
- ``referenz_vermessen``: Varianten von model.py, dann fotomess; danach REF_PHOTOS (Satz ``messung``) und REF_RESULT.
  Liegt auch ein Netz aus demselben Video vor, legt der Kernel es an das Modell an (Lage aus Kamerapaaren).
- App: REF_ADD (Drag and Drop, Dialog), REF_MEASURE_REQ (Knopf „Vermessen“), REF_APPLY („Maße übernehmen“).
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.referenz import ablage, capture, netz, vermessen
from kevcad_kernel.referenz.ablage import ReferenzFehler

APP_TYPEN = ("REF_ADD", "REF_MEASURE_REQ", "REF_APPLY")
MELDE_ABSTAND_S = 0.4


class ReferenzRuntimeMixin:
    def _referenz_init(self) -> None:
        self._ref_lock = threading.RLock()
        self._ref_laeufe: dict[tuple[str, str], dict[str, Any]] = {}
        self._ref_fehler: dict[tuple[str, str], str] = {}
        self._ref_netz_cache: dict[str, tuple[Any, dict[str, Any], bytes]] = {}
        self._ref_zuletzt = 0.0

    # =================================================================================================================
    # KernelService
    # =================================================================================================================

    def referenzen(self, name: str | None = None, warten_s: float = 0.0) -> dict[str, Any]:
        """{"ok", "projekt", "referenzen": [Eintrag wie REF_LIST + "capture", "messung_ergebnis"?], "werkzeuge"}"""
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        if name:
            try:
                name = ablage.finde(proj.path, name)
            except ReferenzFehler as exc:
                return {"ok": False, "error": str(exc)}
            ende = time.monotonic() + max(0.0, float(warten_s or 0))
            while time.monotonic() < ende:
                with self._ref_lock:
                    lauf = self._ref_laeufe.get((str(proj.path), name))
                if lauf is None:
                    break
                lauf["fertig"].wait(min(1.0, max(0.05, ende - time.monotonic())))
        namen = [name] if name else ablage.namen(proj.path)
        liste = []
        for n in namen:
            e = self._ref_eintrag(proj.path, n)
            if e is None:
                continue
            meta = ablage.lese_meta(proj.path, n) or {}
            e = {**e, "ordner": str(ablage.ordner(proj.path, n))}
            ms = ablage.ordner(proj.path, n) / ablage.MESSUNG / "messung.json"
            if ms.is_file():
                try:
                    e["messung_ergebnis"] = vermessen.ergebnis_aus(
                        json.loads(ms.read_text("utf-8")), n, {"bekannt": (meta.get("messung") or {}).get("bekannt")
                                                                or {}}, ordner=ms.parent)
                except (OSError, ValueError, KeyError) as exc:
                    e["messung_fehler"] = str(exc)
            e["capture_einstellung"] = meta.get("capture")
            liste.append(e)
        return {"ok": True, "projekt": str(proj.path), "referenzen": liste,
                "werkzeuge": {"kevcad_capture": str(ablage.capture_programm() or "") or None,
                              "fotomess": str(ablage.fotomess_ordner() or "") or None,
                              "kevscan": _kevscan_ordner()}}

    def referenz_video(self, pfad: str, name: str | None = None, masz: dict[str, float] | None = None,
                       auflage: bool = False, von: float | None = None, bis: float | None = None,
                       einstellung: str = "schnell", warten_s: float = 0.0) -> dict[str, Any]:
        """Object Capture im Hintergrund starten. {"ok", "name", "ordner", "zustand", "befehl"} (mit ``warten_s`` bis
        dahin auch das Ergebnis)."""
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        video = Path(str(pfad or "")).expanduser()
        if not video.is_file():
            return {"ok": False, "error": f"Video {str(video)!r} gibt es nicht."}
        if not ablage.ist_video(video):
            return {"ok": False, "error": f"{video.name} ist kein Video (erlaubt: {', '.join(ablage.VIDEO_ENDUNGEN)})."}
        if einstellung not in capture.EINSTELLUNGEN:
            return {"ok": False, "error": f"einstellung {einstellung!r} unbekannt (schnell oder genau)"}
        try:
            ablage.lesbar(video)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        n = self._ref_name_fuer(proj.path, name or video.stem, video)
        schluessel = (str(proj.path), n)
        with self._ref_lock:
            laeuft = self._ref_laeufe.get(schluessel)
            if laeuft is not None:
                return {"ok": False, "error": f"Für die Referenz {n} läuft schon {laeuft['art']}; erst abwarten "
                                              "(referenzen(name, warten_s=…))."}
        ordner = ablage.ordner(proj.path, n)
        aus = ordner / ablage.CAPTURE
        try:
            cmd = capture.befehl(str(video), aus, einstellung=einstellung, masz=masz, auflage=auflage, von=von,
                                 bis=bis)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        meta = ablage.lese_meta(proj.path, n) or {"art": "video", "quelle": str(video), "erstellt": ablage.jetzt()}
        meta["capture"] = {"einstellung": einstellung, "masz": masz or {}, "auflage": bool(auflage), "von": von,
                           "bis": bis, "zustand": "rechnet", "gestartet": ablage.jetzt()}
        meta.pop("lage", None)
        ablage.schreibe_meta(proj.path, n, meta)
        shutil.rmtree(aus, ignore_errors=True)
        lauf = self._ref_lauf_beginnen(schluessel, "capture", "Object Capture startet")
        self._ref_netz_entfernen(n)

        def los() -> None:
            vermessen.warte_auf_speicher(lambda a, t: self._ref_fortschritt(schluessel, 0.0, t), 0.0)
            self._ref_fortschritt(schluessel, 0.0, "Bilder auswählen")
            erg: dict[str, Any] = {}
            for versuch in range(1, capture.VERSUCHE + 1):

                def melde(z: dict[str, Any]) -> None:
                    if "fertig" not in z:
                        self._ref_fortschritt(schluessel, float(z.get("fortschritt") or 0), z.get("text"))

                cl = capture.CaptureLauf(cmd, melde, log=self._log)
                lauf["capture"] = cl
                try:
                    cl.start()
                except OSError as exc:
                    erg = {"ok": False, "fehler": f"kevcad-capture startet nicht: {exc}"}
                    break
                cl.fertig.wait()
                erg = dict(cl.ergebnis, versuche=versuch)
                hinweis = capture.zweifel(erg.get("bericht"))
                if not erg.get("ok") or cl.abgebrochen or hinweis is None:
                    break
                # Object Capture ist nicht deterministisch (Scarlett, 22.10.2026: von vier gleichen Läufen zwei
                # brauchbar, einmal blieben 5 % der Dreiecke, einmal 31 von 60 Bildern und eine falsche Auflage)
                if versuch < capture.VERSUCHE:
                    self._log(f"[referenz] {n}: {hinweis}, rechnet noch einmal")
                    with self._ref_lock:
                        lauf["fortschritt"] = 0.0
                    self._ref_fortschritt(schluessel, 0.0, f"{hinweis}, rechnet noch einmal ({versuch + 1}. Versuch)")
                    shutil.rmtree(aus, ignore_errors=True)
                else:
                    erg.setdefault("warnungen", []).append(
                        f"{hinweis} (auch im {versuch}. Versuch): Netz prüfen; Video mit ruhigerem Hintergrund oder "
                        "--von/--bis versuchen")
            self._ref_capture_fertig(proj.path, n, erg)

        threading.Thread(target=los, name=f"kevcad-capture-{n}", daemon=True).start()
        out: dict[str, Any] = {"ok": True, "name": n, "ordner": str(ordner), "zustand": "rechnet",
                               "befehl": " ".join(cmd)}
        if warten_s and warten_s > 0:
            r = self.referenzen(n, warten_s=warten_s)
            if r.get("ok") and r.get("referenzen"):
                out["referenz"] = r["referenzen"][0]
                out["zustand"] = r["referenzen"][0]["zustand"]
        return out

    def referenz_fotos(self, pfade: list[str], name: str | None = None) -> dict[str, Any]:
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        dateien = [Path(str(p)).expanduser() for p in (pfade or [])]
        fehlt = [str(p) for p in dateien if not p.is_file()]
        if not dateien or fehlt:
            return {"ok": False, "error": "Fotos fehlen: " + (", ".join(fehlt) if fehlt else "keine angegeben")}
        keine = [p.name for p in dateien if not ablage.ist_foto(p)]
        if keine:
            return {"ok": False, "error": f"Keine Fotos: {', '.join(keine)}"}
        try:
            for p in dateien:
                ablage.lesbar(p)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        n = ablage.freier_name(proj.path, name or (dateien[0].parent.name if len(dateien) > 1 else dateien[0].stem))
        ziel = ablage.ordner(proj.path, n) / ablage.FOTOS
        ziel.mkdir(parents=True, exist_ok=True)
        kopiert = []
        for p in dateien:
            out = ziel / (p.stem + ".jpg")
            r = subprocess.run(["sips", "-Z", "1920", "-s", "format", "jpeg", str(p), "--out", str(out)],
                               capture_output=True, text=True)
            if r.returncode != 0 or not out.is_file():
                shutil.copy2(p, ziel / p.name)
                out = ziel / p.name
            kopiert.append(str(out))
        ablage.schreibe_meta(proj.path, n, {"art": "fotos", "quelle": [str(p) for p in dateien],
                                            "fotos": [Path(k).name for k in kopiert], "erstellt": ablage.jetzt()})
        self._ref_liste_senden(sofort=True)
        return {"ok": True, "name": n, "ordner": str(ablage.ordner(proj.path, n)), "fotos": kopiert,
                "hinweis": "Kameras und Maße gibt es nach referenz_vermessen."}

    def referenz_vermessen(self, quelle: str | None = None, freie_masse: list[str] | None = None,
                           bekannte_masse: dict[str, float] | None = None, bilder: int = 8,
                           vorgaben: dict[str, Any] | None = None, grenzen: dict[str, Any] | None = None,
                           maske: dict[str, Any] | None = None, von: float | None = None, bis: float | None = None,
                           kb_brennweite: float | None = None) -> dict[str, Any]:
        """Maße von model.py an der Referenz messen (synchron, etwa 1 bis 2 Minuten). {"ok", "referenz", "masse",
        "huelle", "grundkoerper", "empfehlungen", "bilder", "kontrollbilder", "dauer_s", …} wie REF_RESULT."""
        proj = self._project
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        try:
            n, meta = self._ref_quelle(proj.path, quelle)
        except ReferenzFehler as exc:
            return {"ok": False, "error": str(exc)}
        schluessel = (str(proj.path), n)
        with self._ref_lock:
            if any(k == schluessel and v["art"] == "messung" for k, v in self._ref_laeufe.items()):
                return {"ok": False, "error": f"Die Referenz {n} wird schon vermessen."}
        lauf = self._ref_lauf_beginnen(schluessel, "messung", "Messmodell bauen")
        try:
            return self._ref_vermessen(proj, n, meta, freie_masse, bekannte_masse, bilder, vorgaben, grenzen, maske,
                                       von, bis, kb_brennweite)
        except ReferenzFehler as exc:
            self._ref_fehler[schluessel] = str(exc)
            return {"ok": False, "referenz": n, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            import traceback

            self._log(traceback.format_exc())
            self._ref_fehler[schluessel] = f"{type(exc).__name__}: {exc}"
            return {"ok": False, "referenz": n, "error": f"Vermessen fehlgeschlagen: {type(exc).__name__}: {exc}"}
        finally:
            self._ref_lauf_beenden(schluessel, lauf)

    def referenz_fotoansicht(self, name: str | None = None, foto: int | str | None = None, satz: str | None = None,
                             modus: str | None = None, deckkraft: float | None = None, aus: bool = False,
                             bild: bool = False, breite: int = 1280) -> dict[str, Any]:
        """Fotoansicht in der App öffnen (VIEW_CMD referenz_foto) und auf Wunsch ihr Bild holen (SCREENSHOT_REQ mit
        source "referenz_foto"). {"ok", "message", "png"?, "width"?, "height"?, "ueberdeckung"?}"""
        if not self._link.connected:
            return {"ok": False, "error": "App nicht verbunden"}
        args: dict[str, Any] = {"aus": bool(aus)}
        if name:
            args["name"] = name
        if isinstance(foto, int) and not isinstance(foto, bool):
            args["index"] = max(0, int(foto) - 1)  # 1-basiert wie in der App
        elif foto:
            args["foto"] = str(foto)
        if satz:
            args["satz"] = satz
        if modus:
            args["modus"] = modus
        if deckkraft is not None:
            args["deckkraft"] = float(deckkraft)
        res = self.view_command("referenz_foto", args, timeout_s=60)
        if not res.get("ok"):
            return res
        out: dict[str, Any] = {"ok": True, "message": res.get("message")}
        if bild and not aus:
            reply, payload, error = self._request({"type": "SCREENSHOT_REQ", "width": int(breite), "height": 0,
                                                   "source": "referenz_foto", "view": None, "hide_overlays": True},
                                                  60)
            if error or not reply.get("ok", False):
                out["bild_fehler"] = error or reply.get("message")
            else:
                cam = reply.get("camera") or {}
                out.update(png=payload, width=reply.get("width"), height=reply.get("height"),
                           ueberdeckung=cam.get("ueberdeckung"), foto=cam.get("foto"))
        return out

    # =================================================================================================================
    # Vermessen
    # =================================================================================================================

    def _ref_vermessen(self, proj: Any, n: str, meta: dict[str, Any], frei, bekannt, bilder, vorgaben, grenzen, maske,
                       von, bis, kb_brennweite) -> dict[str, Any]:
        schluessel = (str(proj.path), n)
        ordner = ablage.ordner(proj.path, n)
        mess = ordner / ablage.MESSUNG
        mess.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()

        def melde(a: float, text: str) -> None:
            self._ref_fortschritt(schluessel, a, text)

        vermessen.warte_auf_speicher(melde, 0.0)
        melde(0.02, "Messmodell bauen (model.py mit den freien Maßen)")
        var = vermessen.varianten_bauen(modell=proj.model, frei=list(frei or []),
                                        bekannt={str(k): float(v) for k, v in (bekannte_masse_ok(bekannt)).items()},
                                        ausgabe=mess / "varianten.pkl", katalog=self._catalog_dirs(),
                                        inventar_regel=self._inventory_rule(reload=True))
        if not var.get("ok"):
            msg = str(var.get("error") or "Messmodell nicht gebaut")
            if var.get("line"):
                msg += f" (model.py Zeile {var['line']})"
            raise ReferenzFehler(msg)
        melde(0.12, f"Messmodell: {len(var.get('teile') or [])} Teile, {len(var.get('frei') or [])} freie Maße")
        if meta.get("art") == "scan":
            # Scan: bekannte Kameras (ARKit), Tiefe (PromptDA) und Masken aus der Auswertung (scan/vermessen.py)
            from kevcad_kernel.scan import vermessen as scan_vermessen

            q = scan_vermessen.quelle(ordner, max(1, min(int(bilder or 8), 24)))
        elif meta.get("art") == "video":
            q: dict[str, Any] = {"video": meta["quelle"]}
            if von is not None:
                q["von"] = float(von)
            if bis is not None:
                q["bis"] = float(bis)
        else:
            fotos = [str(ordner / ablage.FOTOS / f) for f in meta.get("fotos") or []]
            if not fotos:
                raise ReferenzFehler(f"Die Referenz {n} hat keine Fotos.")
            q = {"fotos": fotos}
        optionen = {"vorgaben": vorgaben, "grenzen": grenzen, "kb_brennweite": kb_brennweite}
        for k, v in (maske or {}).items():
            if k in vermessen.MASKEN_OPTIONEN:
                optionen[k] = v
        auftrag = vermessen.auftrag_fotomess(varianten=var, quelle=q, ablage_ordner=mess,
                                             bilder=max(1, min(int(bilder or 8), 24)), optionen=optionen)
        datei = vermessen.fotomess_lauf(auftrag, mess, melde)
        messung = json.loads(datei.read_text("utf-8"))
        # Liegt Object Capture zum selben Video vor, verfolgt es die Kamera über das ganze Video und kennt vorn und
        # hinten auch dort, wo sie gleich aussehen. Weicht ein Bild von fotomess um die Zwillingslage ab (Drehung um Z
        # gegen die übrigen Paare), rechnet fotomess noch einmal: dieselben Bilder, dessen eigene Kameras als Start,
        # die abweichenden in die Zwillingslage gedreht.
        zweiter = None
        posen = self._ref_capture_posen(proj.path, n) if meta.get("art") == "video" else []
        if posen:
            probe = dict(ablage.lese_meta(proj.path, n) or meta)
            self._ref_lage_neu(proj.path, n, probe, messung)
            lage = probe.get("lage")
            start = _zwillings_start(messung, lage, mess / "varianten.pkl") if lage and lage.get("ausreisser") \
                else None
            if start:
                zweiter = [a["zeit"] for a in lage["ausreisser"]]
                melde(0.55, f"{len(zweiter)} Bild(er) lagen gedreht: zweiter Durchgang in der richtigen Lage")
                auftrag2 = dict(auftrag, zeiten=[b["zeit"] for b in messung.get("bilder") or []
                                                 if b.get("zeit") is not None], startkameras=start)
                datei = vermessen.fotomess_lauf(auftrag2, mess, melde)
                messung = json.loads(datei.read_text("utf-8"))
        ergebnis = vermessen.ergebnis_aus(messung, n, var, ordner=mess)
        if zweiter:
            ergebnis["empfehlungen"].append({"art": "zweiter_durchgang", "text": (
                f"In {len(zweiter)} Bild(ern) ({', '.join(f'{z:.1f} s' for z in zweiter)}) lag das Modell zuerst "
                "gedreht (vorn und hinten vertauscht, erkannt an Object Capture); neu gerechnet in der richtigen "
                "Lage")})
        if messung.get("startkameras"):
            ergebnis["startkameras"] = messung["startkameras"]
        meta = ablage.lese_meta(proj.path, n) or meta
        meta["messung"] = {"stand": messung.get("stand"), "frei": var.get("frei"), "bekannt": var.get("bekannt"),
                           "bilder": ergebnis.get("bilder"), "dauer_s": round(time.perf_counter() - t0, 1),
                           "quelle": q}
        self._ref_lage_neu(proj.path, n, meta, messung)
        ungeprueft = (meta.get("lage") or {}).get("ohne_paar") or []
        if posen and ungeprueft:
            ergebnis["empfehlungen"].append({"art": "lage_ungeprueft", "text": (
                f"Lage in {len(ungeprueft)} Bild(ern) nicht gegen Object Capture prüfbar ("
                f"{', '.join(f'{z:.1f} s' for z in ungeprueft)}, dort fehlen dessen Kameras): Kontrollbild "
                "ansehen, ob vorn und hinten stimmen")})
        ablage.schreibe_meta(proj.path, n, meta)
        self._ref_fehler.pop(schluessel, None)
        if self._project is not None and self._project.path == proj.path:
            self._send_app({"type": "REF_PHOTOS", "referenz": n, "satz": "messung",
                            "fotos": vermessen.fotos_aus_messung(messung, mess)})
            self._send_app({"type": "REF_RESULT", **ergebnis})
            if meta.get("lage"):
                self._ref_netz_senden(proj.path, n)
                self._ref_capture_fotos_senden(proj.path, n)
        out = {"ok": True, **ergebnis, "teile_gemessen": var.get("teile"), "messmodell": var.get("messmodell"),
               "ordner": str(mess), "lage_netz": _lage_text(meta.get("lage")),
               "dauer_s": round(time.perf_counter() - t0, 1)}
        return out

    def _ref_quelle(self, projekt: Path, quelle: str | None) -> tuple[str, dict[str, Any]]:
        """Referenz zu ``quelle``: Name einer Referenz oder Pfad eines Videos (legt die Referenz ohne Netz an)."""
        if quelle and (Path(str(quelle)).expanduser().is_file() or "/" in str(quelle)):
            p = Path(str(quelle)).expanduser()
            if not p.is_file():
                raise ReferenzFehler(f"{str(p)!r} gibt es nicht.")
            if ablage.ist_video(p):
                ablage.lesbar(p)
                n = self._ref_name_fuer(projekt, p.stem, p)
                meta = ablage.lese_meta(projekt, n)
                if meta is None:
                    meta = {"art": "video", "quelle": str(p.resolve()), "erstellt": ablage.jetzt()}
                    ablage.schreibe_meta(projekt, n, meta)
                    self._ref_liste_senden(sofort=True)
                return n, meta
            raise ReferenzFehler("Fotos zuerst mit referenz_fotos ablegen, dann den Namen der Referenz angeben.")
        n = ablage.finde(projekt, quelle)
        meta = ablage.lese_meta(projekt, n)
        if meta is None:
            raise ReferenzFehler(f"referenz.json von {n} ist nicht lesbar.")
        if meta.get("art") == "video" and not Path(str(meta.get("quelle"))).is_file():
            raise ReferenzFehler(f"Das Video der Referenz {n} ist nicht erreichbar: {meta.get('quelle')}")
        if meta.get("art") == "video":
            ablage.lesbar(meta["quelle"])
        return n, meta

    def _ref_name_fuer(self, projekt: Path, wunsch: str, video: Path) -> str:
        """Bestehende Referenz desselben Videos wiederverwenden, sonst ein freier Name."""
        for n in ablage.namen(projekt):
            m = ablage.lese_meta(projekt, n) or {}
            if m.get("art") == "video" and str(m.get("quelle")) in (str(video), str(video.resolve())):
                return n
        return ablage.freier_name(projekt, wunsch)

    # =================================================================================================================
    # Capture
    # =================================================================================================================

    def _ref_capture_fertig(self, projekt: Path, n: str, erg: dict[str, Any]) -> None:
        schluessel = (str(projekt), n)
        meta = ablage.lese_meta(projekt, n) or {}
        cap = dict(meta.get("capture") or {})
        if erg.get("ok"):
            b = erg.get("bericht") or {}
            rek = b.get("rekonstruktion") or {}
            cap.update(zustand="fertig", dauer_s=erg.get("dauer_s"), fertig=ablage.jetzt(),
                       bilder=rek.get("images"), ausgerichtet=rek.get("posed"),
                       huelle=b.get("huellmass_mm"), grundkoerper=b.get("grundkoerper_mm"),
                       oberkante=b.get("oberkante_mm"), massstab_bekannt=b.get("massstab_bekannt"),
                       pruefmasse=b.get("pruefmasse"), warnungen=erg.get("warnungen") or [],
                       versuche=erg.get("versuche") or 1)
            self._ref_fehler.pop(schluessel, None)
        else:
            cap.update(zustand="fehler", fehler=erg.get("fehler"), dauer_s=erg.get("dauer_s"))
            self._ref_fehler[schluessel] = f"Object Capture: {erg.get('fehler')}"
            self._log(f"[referenz] kevcad-capture {n}: {erg.get('fehler')}\n{erg.get('stderr') or ''}")
        meta["capture"] = cap
        ms = ablage.ordner(projekt, n) / ablage.MESSUNG / "messung.json"
        if erg.get("ok") and ms.is_file():
            try:
                self._ref_lage_neu(projekt, n, meta, json.loads(ms.read_text("utf-8")))
            except (OSError, ValueError) as exc:
                self._log(f"[referenz] Lage {n}: {exc!r}")
        ablage.schreibe_meta(projekt, n, meta)
        with self._ref_lock:
            lauf = self._ref_laeufe.get(schluessel)
        if lauf is not None:
            self._ref_lauf_beenden(schluessel, lauf)
        if erg.get("ok") and self._project is not None and self._project.path == projekt:
            self._ref_netz_senden(projekt, n)
            self._ref_capture_fotos_senden(projekt, n)

    def _ref_capture_posen(self, projekt: Path, n: str) -> list[dict[str, Any]]:
        datei = ablage.ordner(projekt, n) / ablage.CAPTURE / "poses.json"
        if not datei.is_file() or not (datei.parent / "netz_mm.obj").is_file():
            return []
        try:
            return netz.lies_posen(datei)
        except (OSError, ValueError) as exc:
            self._log(f"[referenz] poses.json {n}: {exc!r}")
            return []

    def _ref_lage_neu(self, projekt: Path, n: str, meta: dict[str, Any], messung: dict[str, Any]) -> None:
        """Netz aus demselben Video an das Modell anlegen (netz.anlegen); ``meta["lage"]`` oder entfernt."""
        posen_datei = ablage.ordner(projekt, n) / ablage.CAPTURE / "poses.json"
        obj = ablage.ordner(projekt, n) / ablage.CAPTURE / "netz_mm.obj"
        meta.pop("lage", None)
        if meta.get("art") == "scan":
            # Scan: fotomess legt den Scan selbst an das Modell (messung["scan"]["lage"])
            from kevcad_kernel.scan.vermessen import lage_aus_messung

            lage = lage_aus_messung(messung) if obj.is_file() else None
            if lage is not None:
                meta["lage"] = lage
            return
        if meta.get("art") != "video" or not posen_datei.is_file() or not obj.is_file():
            return
        posen = netz.lies_posen(posen_datei)
        mk = [{"zeit": b.get("zeit"), "kamera": b["kamera"]} for b in messung.get("bilder") or []
              if b.get("kamera") and not b.get("verworfen")]
        try:
            n_obj = netz.lies_obj(obj)
        except (OSError, ValueError) as exc:
            self._log(f"[referenz] Netz {n}: {exc!r}")
            return
        lo, hi = n_obj["positions"].min(0), n_obj["positions"].max(0)
        lage = netz.anlegen(posen, mk, (lo + hi) / 2)
        if lage is None:
            return
        abstand = float(np.mean([np.linalg.norm(netz.zentrum(m["kamera"])) for m in mk])) if mk else 500.0
        if lage["rest_mm"] > 0.15 * abstand:
            meta["lage_verworfen"] = {k: v for k, v in lage.items() if k not in ("A", "b")}
            return
        meta.pop("lage_verworfen", None)
        # Feinanlegen an der Oberfläche des eingepassten Modells (fotomess schreibt es mit)
        modell = ablage.ordner(projekt, n) / ablage.MESSUNG / "modell_eingepasst.npz"
        if modell.is_file():
            try:
                with np.load(modell) as m:
                    fein = netz.feinanlegen(n_obj["positions"], m["V"], m["T"], lage["A"], lage["b"])
            except (OSError, ValueError, KeyError) as exc:
                self._log(f"[referenz] Feinanlegen {n}: {exc!r}")
                fein = None
            if fein is not None:
                A, b = fein["A"], fein["b"]
                M = np.eye(4)
                M[:3, :3] = A
                M[:3, 3] = b
                lage.update(A=A, b=b, matrix=[float(x) for x in M.T.reshape(-1)],
                            drehung_z=round(math.degrees(math.atan2(A[1, 0], A[0, 0])), 2),
                            verschiebung=[round(float(x), 2) for x in b],
                            fein={"rest_mm": fein["rest_mm"], "anteil": fein["anteil"]})
        meta["lage"] = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in lage.items()}

    # =================================================================================================================
    # Zustand der Läufe und Nachrichten
    # =================================================================================================================

    def _ref_lauf_beginnen(self, schluessel: tuple[str, str], art: str, text: str) -> dict[str, Any]:
        lauf = {"art": art, "fortschritt": 0.0, "text": text, "seit": time.monotonic(), "fertig": threading.Event()}
        with self._ref_lock:
            self._ref_laeufe[schluessel] = lauf
        self._ref_fehler.pop(schluessel, None)
        self._ref_liste_senden(sofort=True)
        return lauf

    def _ref_lauf_beenden(self, schluessel: tuple[str, str], lauf: dict[str, Any]) -> None:
        with self._ref_lock:
            if self._ref_laeufe.get(schluessel) is lauf:
                del self._ref_laeufe[schluessel]
        lauf["fertig"].set()
        self._ref_liste_senden(sofort=True)

    def _ref_fortschritt(self, schluessel: tuple[str, str], anteil: float, text: str | None) -> None:
        with self._ref_lock:
            lauf = self._ref_laeufe.get(schluessel)
            if lauf is None:
                return
            neu_text = text is not None and text != lauf.get("text")
            lauf["fortschritt"] = max(float(lauf.get("fortschritt") or 0), min(1.0, float(anteil)))
            if text:
                lauf["text"] = text
        self._ref_liste_senden(sofort=neu_text)

    def _ref_eintrag(self, projekt: Path, n: str) -> dict[str, Any] | None:
        meta = ablage.lese_meta(projekt, n)
        if meta is None:
            return None
        o = ablage.ordner(projekt, n)
        with self._ref_lock:
            lauf = self._ref_laeufe.get((str(projekt), n))
            lauf = dict(lauf) if lauf else None
        fehler = self._ref_fehler.get((str(projekt), n))
        netz_da = (o / ablage.CAPTURE / "netz_mm.obj").is_file()
        messung_da = (o / ablage.MESSUNG / "messung.json").is_file()
        cap = meta.get("capture") or {}
        if lauf:
            zustand = "rechnet"
        elif fehler or cap.get("zustand") == "fehler":
            zustand = "fehler"
        elif netz_da or messung_da:
            zustand = "fertig"
        else:
            zustand = "leer"
        quelle = meta.get("quelle")
        if isinstance(quelle, list):
            quelle = f"{len(quelle)} Foto" + ("" if len(quelle) == 1 else "s")
        mbilder = (meta.get("messung") or {}).get("bilder") or 0
        return {"name": n, "art": meta.get("art") or "video", "quelle": quelle, "zustand": zustand,
                "laeuft": lauf["art"] if lauf else None,
                "fortschritt": round(float(lauf["fortschritt"]), 3) if lauf else None,
                "text": lauf.get("text") if lauf else None,
                "meldung": fehler or (cap.get("fehler") if cap.get("zustand") == "fehler" else None),
                "netz": netz_da, "fotos": int(mbilder or len(meta.get("fotos") or [])), "messung": messung_da,
                "erstellt": meta.get("erstellt"),
                "capture": {k: cap.get(k) for k in ("einstellung", "zustand", "dauer_s", "bilder", "ausgerichtet",
                                                    "huelle", "grundkoerper", "oberkante", "masz", "auflage")}
                if cap else None,
                "lage": _lage_kurz(meta.get("lage"))}

    def _ref_liste(self) -> dict[str, Any]:
        proj = self._project
        eintraege = []
        if proj is not None:
            for n in ablage.namen(proj.path):
                e = self._ref_eintrag(proj.path, n)
                if e is not None:
                    eintraege.append(e)
        return {"type": "REF_LIST", "referenzen": vermessen.sauber(eintraege)}

    def _ref_liste_senden(self, sofort: bool = False) -> None:
        jetzt = time.monotonic()
        with self._ref_lock:
            if not sofort and jetzt - self._ref_zuletzt < MELDE_ABSTAND_S:
                return
            self._ref_zuletzt = jetzt
        try:
            self._send_app(self._ref_liste())
        except Exception as exc:  # noqa: BLE001
            self._log(f"[referenz] REF_LIST: {exc!r}")

    def _ref_netz_nachricht(self, projekt: Path, n: str) -> tuple[dict[str, Any], bytes] | None:
        obj = ablage.ordner(projekt, n) / ablage.CAPTURE / "netz_mm.obj"
        if not obj.is_file():
            return None
        meta = ablage.lese_meta(projekt, n) or {}
        lage = meta.get("lage")
        schl = f"{obj}:{obj.stat().st_mtime_ns}:{json.dumps(lage, sort_keys=True, default=str)}"
        cache = self._ref_netz_cache.get(str(obj))
        if cache is not None and cache[0] == schl:
            return cache[1], cache[2]
        try:
            m = netz.lies_obj(obj)
        except (OSError, ValueError) as exc:
            self._log(f"[referenz] {obj}: {exc!r}")
            return None
        if lage:
            m = netz.bewege_netz(m, np.asarray(lage["A"], float), np.asarray(lage["b"], float))
        from kevcad_kernel.protocol import pack_ref_netz

        kopf, nutz = pack_ref_netz(name=n, positions=m["positions"], normals=m["normals"], triangles=m["triangles"],
                                   lage=_lage_kurz(lage),
                                   quelle="kevscan" if meta.get("art") == "scan" else "object_capture")
        kopf.pop("seq", None)
        self._ref_netz_cache[str(obj)] = (schl, kopf, nutz)
        return kopf, nutz

    def _ref_netz_senden(self, projekt: Path, n: str, conn: Any = None) -> None:
        r = self._ref_netz_nachricht(projekt, n)
        if r is None:
            return
        (conn.send if conn is not None else self._send_app)(r[0], r[1])

    def _ref_netz_entfernen(self, n: str) -> None:
        self._send_app({"type": "REF_REMOVE", "name": n})

    def _ref_capture_fotos_senden(self, projekt: Path, n: str, conn: Any = None) -> None:
        posen_datei = ablage.ordner(projekt, n) / ablage.CAPTURE / "poses.json"
        if not posen_datei.is_file():
            return
        try:
            posen = netz.lies_posen(posen_datei)
        except (OSError, ValueError) as exc:
            self._log(f"[referenz] poses.json {n}: {exc!r}")
            return
        meta = ablage.lese_meta(projekt, n) or {}
        msg = {"type": "REF_PHOTOS", "referenz": n, "satz": "capture",
               "fotos": vermessen.fotos_aus_capture(posen, meta.get("lage"))}
        (conn.send if conn is not None else self._send_app)(vermessen.sauber(msg))

    def _ref_messung_senden(self, projekt: Path, n: str, conn: Any = None) -> None:
        mess = ablage.ordner(projekt, n) / ablage.MESSUNG
        datei = mess / "messung.json"
        if not datei.is_file():
            return
        try:
            messung = json.loads(datei.read_text("utf-8"))
        except (OSError, ValueError):
            return
        send = conn.send if conn is not None else self._send_app
        send(vermessen.sauber({"type": "REF_PHOTOS", "referenz": n, "satz": "messung",
                               "fotos": vermessen.fotos_aus_messung(messung, mess)}))
        bekannt = ((ablage.lese_meta(projekt, n) or {}).get("messung") or {}).get("bekannt") or {}
        send({"type": "REF_RESULT", **vermessen.ergebnis_aus(messung, n, {"bekannt": bekannt}, ordner=mess)})

    def _ref_alles(self, conn: Any = None) -> None:
        proj = self._project
        send = conn.send if conn is not None else self._send_app
        send(self._ref_liste())
        if proj is None:
            return
        for n in ablage.namen(proj.path):
            try:
                self._ref_netz_senden(proj.path, n, conn)
                self._ref_capture_fotos_senden(proj.path, n, conn)
                self._ref_messung_senden(proj.path, n, conn)
            except Exception as exc:  # noqa: BLE001 - eine kaputte Referenz darf die anderen nicht aufhalten
                self._log(f"[referenz] {n}: {exc!r}")

    # Haken der Laufzeit -----------------------------------------------------------------------------------------------

    def _referenz_on_connect(self, conn: Any) -> None:
        try:
            self._ref_alles(conn)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[referenz] beim Verbinden: {exc!r}")

    def _referenz_projekt(self, same: bool) -> None:
        if not same:
            self._pool.submit(self._ref_alles)

    def _referenz_schliessen(self) -> None:
        with self._ref_lock:
            laeufe = list(self._ref_laeufe.values())
        for lauf in laeufe:
            cl = lauf.get("capture")
            if cl is not None:
                cl.abbrechen()

    def _referenz_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in APP_TYPEN:
            return False
        threading.Thread(target=self._ref_app_anfrage, args=(kind, header), name=f"kevcad-{kind}",
                         daemon=True).start()
        return True

    def _ref_app_anfrage(self, kind: str, header: dict[str, Any]) -> None:
        rid = header.get("id")

        def ack(ok: bool, text: str) -> None:
            self._send_app({"type": "ACK", "reply_to": rid, "ok": ok, "message": text})

        try:
            if kind == "REF_ADD":
                pfade = [str(p) for p in header.get("pfade") or []]
                videos = [p for p in pfade if ablage.ist_video(p)]
                if videos:
                    res = self.referenz_video(videos[0], name=header.get("name") or None,
                                              masz=header.get("masz") or None, auflage=bool(header.get("auflage")),
                                              von=header.get("von"), bis=header.get("bis"),
                                              einstellung=header.get("einstellung") or "schnell")
                    ack(bool(res.get("ok")), f"Referenz {res.get('name')}: Object Capture läuft" if res.get("ok")
                        else str(res.get("error")))
                else:
                    res = self.referenz_fotos(pfade, name=header.get("name") or None)
                    ack(bool(res.get("ok")), f"Referenz {res.get('name')}: {len(res.get('fotos') or [])} Fotos "
                                             "abgelegt" if res.get("ok") else str(res.get("error")))
            elif kind == "REF_MEASURE_REQ":
                ack(True, "Vermessen läuft")
                res = self.referenz_vermessen(header.get("referenz"), freie_masse=header.get("frei") or None,
                                              bekannte_masse=header.get("bekannt") or None,
                                              bilder=int(header.get("bilder") or 8))
                if not res.get("ok"):
                    self._log(f"[referenz] Vermessen aus der App: {res.get('error')}")
                    self._ref_liste_senden(sofort=True)
            elif kind == "REF_APPLY":
                ack(*self._ref_uebernehmen(header.get("werte") or {}))
        except Exception as exc:  # noqa: BLE001
            ack(False, f"{type(exc).__name__}: {exc}")

    def _ref_uebernehmen(self, werte: dict[str, Any]) -> tuple[bool, str]:
        """Kevins Klick „Maße übernehmen“: Vorgabewerte der param()-Aufrufe in model.py ersetzen."""
        from kevcad_kernel.referenz.uebernehmen import UebernahmeFehler, uebernehmen

        proj = self._project
        if proj is None:
            return False, "Kein Projekt offen"
        try:
            werte = {str(k): float(v) for k, v in werte.items()}
            code = proj.model.read_text(encoding="utf-8")
            neu, aenderungen = uebernehmen(code, werte)
        except (UebernahmeFehler, SyntaxError, ValueError, OSError) as exc:
            return False, str(exc)
        res = self.model_write(neu)
        if not res.get("ok"):
            return False, str(res.get("error"))
        text = "; ".join(f"{a['name']} {a['vorher']} → {a['nachher']}" for a in aenderungen)
        self._log(f"[referenz] Maße übernommen: {text}")
        return True, f"In model.py übernommen: {text}"


def _zwillings_start(messung: dict[str, Any], lage: dict[str, Any], varianten_datei: Path
                     ) -> dict[str, dict[str, Any]] | None:
    """Startkameras für den zweiten Durchgang (fotomess ``startkameras``, je Bildname): die eingepassten Kameras des
    ersten, die Ausreißer in die Zwillingslage gedreht, die zu ihrer Abweichung passt (R' = R Q, t' = t + R (c − Q c),
    wie fotomess.ablauf.zwilling). None ohne Zwillinge im Messmodell."""
    import math
    import pickle

    try:
        with open(varianten_datei, "rb") as f:
            zwillinge = pickle.load(f).get("zwillinge") or []
    except (OSError, pickle.UnpicklingError, EOFError):
        return None
    if not zwillinge:
        return None
    abweichung = {round(float(a["zeit"]), 3): float(a["abweichung_grad"]) for a in lage.get("ausreisser") or []}
    def gier(Q: np.ndarray) -> float:
        return abs(math.degrees(math.atan2(Q[1, 0], Q[0, 0])))

    start = {}
    gedreht = 0
    for b in messung.get("bilder") or []:
        if b.get("verworfen") or not b.get("kamera"):
            continue
        k = {key: b["kamera"][key] for key in ("R", "t", "f", "cx", "cy", "w", "h")}
        z = b.get("zeit")
        if z is not None and round(float(z), 3) in abweichung:
            soll = abweichung[round(float(z), 3)]
            Q, c = min(((np.asarray(q, float), np.asarray(cc, float)) for q, cc in zwillinge),
                       key=lambda qc: abs(gier(qc[0]) - soll))
            if abs(gier(Q) - soll) < 45:  # nur echte Zwillingslagen, keine sonst verunglückten Bilder
                R, t = np.asarray(k["R"], float), np.asarray(k["t"], float)
                k["R"] = (R @ Q).tolist()
                k["t"] = (t + R @ (c - Q @ c)).tolist()
                gedreht += 1
        start[b["name"]] = k
    return start if gedreht else None


def _kevscan_ordner() -> str | None:
    from kevcad_kernel.scan.ablage import kevscan_ordner

    return str(kevscan_ordner() or "") or None


def bekannte_masse_ok(bekannt: Any) -> dict[str, float]:
    if not bekannt:
        return {}
    if not isinstance(bekannt, dict):
        raise ReferenzFehler("bekannte_masse als {\"name\": mm} angeben")
    out = {}
    for k, v in bekannt.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError) as exc:
            raise ReferenzFehler(f"bekanntes Maß {k}: Zahl in mm angeben") from exc
    return out


def _lage_kurz(lage: dict[str, Any] | None) -> dict[str, Any] | None:
    if not lage:
        return None
    return {k: lage.get(k) for k in ("drehung_z", "verschiebung", "massstab", "rest_mm", "paare", "fein")
            if k in lage}


def _lage_text(lage: dict[str, Any] | None) -> str | None:
    if not lage:
        return None
    v = lage.get("verschiebung") or [0, 0, 0]
    fein = lage.get("fein") or {}
    return (f"Netz an das Modell angelegt: {lage.get('drehung_z')}° um Z, verschoben um "
            f"({v[0]:.0f}; {v[1]:.0f}; {v[2]:.0f}) mm (Kameras {lage.get('rest_mm')} mm auseinander, "
            f"{lage.get('paare')} Paare" + (f"; an der Oberfläche nachgeführt, mittlerer Abstand {fein.get('rest_mm')} mm"
                                             if fein else "") + ")")

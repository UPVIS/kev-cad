"""Druckvorschau in der Kernel-Laufzeit (Mixin ``DruckvorschauRuntime`` für ``KernelRuntime``; DRUCKVORSCHAU.md).

Ablauf:

1. Nach jedem erfolgreichen Lauf kommt die Prüfung (``CHECK_DONE``) mit ``druck.vorschau`` (Geometrie je Druckteil aus
   dem Rechenprozess). Sobald auch der Lauf abgeschlossen ist (Reglerwerte bekannt), baut ein eigener Faden die
   Vorschau (``vorschau.baue``: Schätzung, schnelles Anordnen, Empfehlungen) und schickt ``PRINT_PREVIEW``.
2. Danach rechnet derselbe Faden mit Bambu Studio nach, wenn ``druck.slicer`` an ist und Bambu Studio da ist: je
   Gruppe ein Stück (Zwischenspeicher ``~/Library/Caches/de.upvis.kevcad/druck/<schlüssel>/``), dann je Material die
   genaue Anordnung (``--arrange``) und die Platten. Jedes Ergebnis ersetzt die Schätzung und schickt ein neues
   ``PRINT_PREVIEW``; der Abgleich (``abgleich.json``) wird nachgeführt. Ein neuer Lauf bricht ab.
3. Läufe mit Reglerwerten: nur Schätzung; Zwischenspeicher werden gelesen, aber nichts gespeichert, kein Slicer.

Anfragen der App: ``PRINT_PREVIEW_REQ``, ``PRINT_SETTINGS`` (``<projekt>/druck.json``), ``PRINT_EXPORT_REQ`` (3MF).
Erwartet von der Laufzeit: ``_project``, ``scene``, ``catalog``, ``_pruef``, ``_occ_lock``, ``_pool``,
``_send_app``, ``_log``, ``_reglerstand``.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from kevcad_kernel.druck import schaetzung as sz
from kevcad_kernel.druck import slicer as sl
from kevcad_kernel.druck import vorgaben as vg
from kevcad_kernel.druck import vorschau as vs
from kevcad_kernel.druck.vorschau_geo import teil_mit_form

ANFRAGEN = ("PRINT_PREVIEW_REQ", "PRINT_SETTINGS", "PRINT_EXPORT_REQ")
WARTEN_S = 60.0


class _Abbruch(Exception):
    pass


class DruckvorschauRuntime:
    # -----------------------------------------------------------------------------------------------------------------
    # Zustand

    def _druckvorschau_init(self) -> None:
        self._dv_lock = threading.RLock()
        self._dv_cond = threading.Condition(self._dv_lock)
        self._dv_laeufe: dict[int, dict[str, Any]] = {}      # run → Reglerwerte
        self._dv_checks: dict[int, dict[str, Any]] = {}      # run → CHECK-Kopf (wartet auf den Lauf)
        self._dv_eingang: dict[str, Any] | None = None        # letzter Eingang (run, druck, befunde, regler)
        self._dv_vorschau: dict[str, Any] | None = None
        self._dv_gruppen: list[vs.Gruppe] = []
        self._dv_platten: list[tuple[str, Any]] = []
        self._dv_stand = vs.SlicerStand()
        self._dv_auftrag: dict[str, Any] | None = None
        self._dv_abbruch = threading.Event()
        self._dv_gen = 0
        self._dv_ende = False
        self._dv_fertig = threading.Event()
        self._dv_faden = threading.Thread(target=self._dv_schleife, name="kevcad-druck", daemon=True)
        self._dv_faden.start()

    def _druckvorschau_schliessen(self) -> None:
        with self._dv_cond:
            self._dv_ende = True
            self._dv_abbruch.set()
            self._dv_cond.notify_all()

    def _druckvorschau_projekt(self, gleich: bool) -> None:
        """Projektwechsel: alles vergessen, laufenden Slicer abbrechen, leere Vorschau schicken."""
        if gleich:
            return
        with self._dv_cond:
            self._dv_gen += 1
            self._dv_abbruch.set()
            self._dv_auftrag = None
            self._dv_laeufe.clear()
            self._dv_checks.clear()
            self._dv_eingang = None
            self._dv_vorschau = None
            self._dv_gruppen = []
            self._dv_platten = []
            self._dv_stand = vs.SlicerStand()

    def _druckvorschau_on_connect(self, conn: Any) -> None:
        with self._dv_lock:
            v = self._dv_vorschau
        if v is not None:
            from kevcad_kernel.protocol import pack_print_preview

            conn.send(pack_print_preview(v))

    # -----------------------------------------------------------------------------------------------------------------
    # Auslöser

    def _druckvorschau_lauf(self, run: int, params: dict[str, Any] | None) -> None:
        """Nach RUN_END eines erfolgreichen Laufs (Reglerwerte dieses Laufs)."""
        with self._dv_cond:
            self._dv_laeufe[int(run)] = dict(params or {})
            for alt in sorted(self._dv_laeufe)[:-8]:
                self._dv_laeufe.pop(alt, None)
            check = self._dv_checks.pop(int(run), None)
        if check is not None:
            self._dv_eingang_setzen(check)

    def _druckvorschau_pruefung(self, check: dict[str, Any]) -> None:
        """CHECK_DONE (aus dem Lesefaden des Rechenprozesses): Vorschau bauen, sobald der Lauf abgeschlossen ist."""
        if check.get("state") != "done":
            return
        run = int(check.get("run") or 0)
        if run >= 1_000_000_000:  # Schattenlauf der Versionen (gehört nicht zur Szene)
            return
        with self._dv_cond:
            if run not in self._dv_laeufe:
                self._dv_checks[run] = check
                for alt in sorted(self._dv_checks)[:-4]:
                    self._dv_checks.pop(alt, None)
                return
        self._dv_eingang_setzen(check)

    def _dv_eingang_setzen(self, check: dict[str, Any]) -> None:
        run = int(check.get("run") or 0)
        with self._dv_cond:
            regler = bool(self._dv_laeufe.get(run))
            self._dv_eingang = {"run": run, "druck": check.get("druck") or {}, "befunde": check.get("befunde") or [],
                                "regler": regler}
            self._dv_gen += 1
            self._dv_abbruch.set()
            self._dv_auftrag = {"gen": self._dv_gen, "slicer": not regler, "art": "lauf"}
            self._dv_fertig.clear()
            self._dv_cond.notify_all()

    def _dv_neu_bauen(self, slicer: bool = True) -> None:
        """Gleicher Lauf, geänderte Vorgaben (PRINT_SETTINGS): neu bauen und für geänderte Gruppen slicen."""
        with self._dv_cond:
            if self._dv_eingang is None:
                return
            self._dv_gen += 1
            self._dv_abbruch.set()
            self._dv_auftrag = {"gen": self._dv_gen, "slicer": slicer and not self._dv_eingang.get("regler"),
                                "art": "einstellungen"}
            self._dv_fertig.clear()
            self._dv_cond.notify_all()

    # -----------------------------------------------------------------------------------------------------------------
    # Faden

    def _dv_schleife(self) -> None:
        while True:
            with self._dv_cond:
                while self._dv_auftrag is None and not self._dv_ende:
                    self._dv_cond.wait(0.5)
                if self._dv_ende:
                    return
                auftrag, self._dv_auftrag = self._dv_auftrag, None
                self._dv_abbruch = threading.Event()
                abbruch = self._dv_abbruch
                eingang = dict(self._dv_eingang or {})
            try:
                self._dv_bearbeiten(auftrag, eingang, abbruch)
            except (_Abbruch, sl.Abgebrochen):
                pass
            except Exception as exc:  # noqa: BLE001 - die Vorschau darf die Laufzeit nicht stören
                self._log(f"[druck] Vorschau fehlgeschlagen: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
                with self._dv_lock:
                    self._dv_stand.zustand = "fehler"
                    self._dv_stand.meldung = f"{type(exc).__name__}: {exc}"
                try:
                    self._dv_senden(eingang)
                except Exception:  # noqa: BLE001
                    pass
            finally:
                with self._dv_lock:
                    if self._dv_auftrag is None:
                        self._dv_fertig.set()

    def _dv_pruefe_abbruch(self, abbruch: threading.Event) -> None:
        if abbruch.is_set() or self._dv_ende:
            raise _Abbruch()

    def _dv_projekt_daten(self) -> tuple[dict[str, Any], dict[str, Any]]:
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {}, {"teile": {}}
        try:
            proj.reload_settings()
        except Exception:  # noqa: BLE001
            pass
        return dict(proj.settings or {}), vg.lies(proj.path)

    def _dv_material(self, mid: str) -> dict[str, Any] | None:
        try:
            return self.catalog.material(mid)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None

    def _dv_senden(self, eingang: dict[str, Any], reply_to: str | None = None) -> dict[str, Any]:
        """Vorschau aus dem Eingang und dem Slicer-Stand bauen, merken und an die App schicken."""
        from kevcad_kernel.protocol import pack_print_preview

        settings, vorgaben = self._dv_projekt_daten()
        druck = eingang.get("druck") or {}
        with self._dv_lock:
            stand = self._dv_stand
        if not druck.get("teile") or not any(not t.get("gedruckt") for t in (druck.get("teile") or {}).values()):
            alle_gedruckt = bool(druck.get("teile"))
            v = vs.leer(int(eingang.get("run") or 0), regler=bool(eingang.get("regler")),
                        **({"meldung": "Alle Druckteile sind schon gedruckt."} if alle_gedruckt else {}))
            if alle_gedruckt:
                v["gedruckt"] = vs.gedruckte_teile(druck)
            gr, platten = [], []
        else:
            v, gr, platten = vs.baue(int(eingang.get("run") or 0), druck, eingang.get("befunde") or [], vorgaben,
                                     settings, self._dv_material, stand, regler=bool(eingang.get("regler")))
            if vorgaben.get("fehler"):
                v["hinweise"].append({"schwere": "warnung", "art": "slicer", "text": str(vorgaben["fehler"])})
        with self._dv_lock:
            self._dv_vorschau = v
            self._dv_gruppen = gr
            self._dv_platten = platten
            self._dv_bau_nr = getattr(self, "_dv_bau_nr", 0) + 1
        self._send_app(pack_print_preview(v, reply_to=reply_to))  # type: ignore[attr-defined]
        # Bestand Stufe 2: was „Gebaut“ vom Filament abbucht, hängt an der Vorschau (BESTAND gebaut_filament)
        nachricht = getattr(self, "_bestand_vorschau_neu", None)
        if nachricht is not None and not v.get("regler"):
            nachricht()
        return v

    def _dv_bearbeiten(self, auftrag: dict[str, Any], eingang: dict[str, Any], abbruch: threading.Event) -> None:
        settings, _ = self._dv_projekt_daten()
        projekt = vs.projekt_einstellungen(settings)
        druck = eingang.get("druck") or {}
        regler = bool(eingang.get("regler"))
        # Zwischenspeicher lesen (auch bei Reglerwerten), dann die schnelle Vorschau
        with self._dv_lock:
            self._dv_stand = vs.SlicerStand(zustand="aus")
        if druck.get("teile"):
            gr, _ = vs.gruppen(druck, eingang.get("befunde") or [], self._dv_projekt_daten()[1], projekt)
            self._dv_cache_laden(gr)
        slicer_an = bool(projekt.get("slicer", True)) and auftrag.get("slicer") and not regler
        with self._dv_lock:
            st = self._dv_stand
            if not druck.get("teile"):
                st.zustand, st.meldung = "aus", "Keine Druckteile im Modell."
            elif regler:
                st.zustand = "aus"
            elif not projekt.get("slicer", True):
                st.zustand, st.meldung = "aus", "Slicer in kevcad.json abgeschaltet (\"druck\": {\"slicer\": false})."
            elif not sl.verfuegbar():
                st.zustand, st.meldung = "aus", "Bambu Studio nicht gefunden: nur Schätzung."
            else:
                st.zustand, st.meldung = "wartet", None
                st.version = sl.version()
        self._dv_senden(eingang)
        if not slicer_an or not druck.get("teile") or not sl.verfuegbar():
            return
        self._dv_slicen(eingang, abbruch)

    # -----------------------------------------------------------------------------------------------------------------
    # Zwischenspeicher

    @staticmethod
    def _dv_ergebnis_datei(schluessel: str) -> Path:
        return sl.cache_ordner() / schluessel / "ergebnis.json"

    def _dv_cache_laden(self, gr: list[vs.Gruppe]) -> None:
        stand = self._dv_stand
        for g in gr:
            p = self._dv_ergebnis_datei(g.schluessel)
            if g.schluessel not in stand.gruppen and p.is_file():
                try:
                    stand.gruppen[g.schluessel] = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        mats = sorted({g.material for g in gr})
        for m in mats:
            k = vs.anordnung_schluessel(m, gr)
            p = sl.cache_ordner() / "anordnung" / f"{k}.json"
            if p.is_file():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    stand.anordnung[k] = d
                    for pk, pv in (d.get("platten_ergebnis") or {}).items():
                        stand.platten[pk] = pv
                except (OSError, ValueError):
                    pass

    # -----------------------------------------------------------------------------------------------------------------
    # Slicer

    def _dv_stl(self, g: vs.Gruppe, druck: dict[str, Any], ordner: Path) -> Path:
        """STL der Gruppe in Druckausrichtung (erstes gezeigtes Teil), im Zwischenspeicher der Gruppe."""
        stl = ordner / f"{g.id}.stl"
        fest = ordner / "teil.stl"
        if fest.is_file():
            shutil.copyfile(fest, stl)
            return stl
        geo = teil_mit_form(druck.get("vorschau") or {}, g.teile[0])
        rec = self.scene.get(g.teile[0])  # type: ignore[attr-defined]
        if geo is None or rec is None:
            raise sl.SlicerFehler(f"{g.teile[0]}: Teil nicht in der Szene")
        with self._occ_lock:  # type: ignore[attr-defined]
            sl.stl_in_druckausrichtung(rec.shape, geo, fest)
        shutil.copyfile(fest, stl)
        return stl

    def _dv_slicen(self, eingang: dict[str, Any], abbruch: threading.Event) -> None:
        druck = eingang.get("druck") or {}
        with self._dv_lock:
            gr = list(self._dv_gruppen)
            stand = self._dv_stand
        offen = [g for g in gr if g.schluessel not in stand.gruppen and g.filament]  # auch „später“: Werte je Teil
        materialien = sorted({g.material for g in vs.auf_platten(gr) if g.filament})
        t0 = time.perf_counter()
        with self._dv_lock:
            stand.zustand = "rechnet"
            stand.gesamt = len(offen) + len(materialien)
            stand.fertig = 0
        abgleich_daten = sz.lies_abgleich()
        projekt = vs.projekt_einstellungen(self._dv_projekt_daten()[0])
        drucker, platte = str(projekt.get("drucker")), str(projekt.get("platte"))
        for g in offen:
            self._dv_pruefe_abbruch(abbruch)
            if not sl.platte_passt(str(g.filament), platte):  # Bambu Studio bräche ab (Hinweis steht in der Vorschau)
                with self._dv_lock:
                    stand.meldung = f"{g.filament} geht nicht auf der {platte}"
                    stand.fertig += 1
                continue
            ordner = sl.cache_ordner() / g.schluessel
            ordner.mkdir(parents=True, exist_ok=True)
            arbeit = sl.arbeitsordner("gruppe")
            try:
                stl = self._dv_stl(g, druck, ordner)
                e = {k: v for k, v in g.einstellungen.items() if k != "ausrichtung"}
                t1 = time.perf_counter()
                res = sl.slice_teil(stl, e, str(g.filament), arbeit, abbruch, drucker, platte)
                res["slicer_s"] = round(time.perf_counter() - t1, 2)
            except (sl.SlicerFehler, OSError) as exc:
                self._log(f"[druck] Slicer {g.name}: {exc}")
                with self._dv_lock:
                    stand.meldung = f"{g.name}: {exc}"
                    stand.fertig += 1
                continue
            finally:
                shutil.rmtree(arbeit, ignore_errors=True)
            # Abgleich: Schätzung (mit den Faktoren vor dem Abgleich) gegen Slicer
            info = self._dv_material(g.material) or {}
            dichte = float(info.get("dichte") or sz.FILAMENT.get(g.material, sz.FILAMENT["pla"]).dichte)
            fk = sz.faktoren(abgleich_daten, drucker, g.prozess, g.material)
            est = sz.schaetze(g.geo, g.einstellungen, g.material, fk, dichte)
            zeit_sl = max(1e-9, float(res["zeit_s"]) - float(res.get("start_s") or 0.0))
            res["abweichung"] = round(est["zeit_s"] / zeit_sl - 1, 3)
            res["abweichung_material"] = round(est["volumen_cm3"] / max(1e-9, float(res["volumen_cm3"])) - 1, 3)
            res["schaetzung"] = {"zeit_s": est["zeit_s"], "volumen_cm3": est["volumen_cm3"], "faktoren": fk}
            res["gruppe"] = g.name
            res["stand"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                neu = sz.abgleich_nachfuehren(drucker, g.prozess, g.material, est["roh"],
                                              {"zeit_s": zeit_sl, "volumen_cm3": res["volumen_cm3"]})
                res["abgleich"] = neu
                abgleich_daten = sz.lies_abgleich()
                self._dv_ergebnis_datei(g.schluessel).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                                 encoding="utf-8")
            except OSError as exc:
                self._log(f"[druck] Zwischenspeicher: {exc}")
            self._dv_pruefe_abbruch(abbruch)
            with self._dv_lock:
                stand.gruppen[g.schluessel] = res
                stand.fertig += 1
                stand.ms = (time.perf_counter() - t0) * 1000
            self._dv_senden(eingang)
        # genaue Anordnung und Platten je Material
        for mat in materialien:
            self._dv_pruefe_abbruch(abbruch)
            try:
                self._dv_platten_slicen(mat, gr, druck, abbruch, drucker, platte)
            except (sl.SlicerFehler, OSError) as exc:
                self._log(f"[druck] Anordnung {mat}: {exc}")
                with self._dv_lock:
                    stand.meldung = f"Anordnung {mat}: {exc}"
            with self._dv_lock:
                stand.fertig += 1
                stand.ms = (time.perf_counter() - t0) * 1000
            self._dv_senden(eingang)
        with self._dv_lock:
            stand.zustand = "fertig"
            stand.ms = (time.perf_counter() - t0) * 1000
            if stand.meldung is None:
                stand.meldung = None
        self._dv_senden(eingang)

    def _dv_platten_slicen(self, mat: str, gr: list[vs.Gruppe], druck: dict[str, Any], abbruch: threading.Event,
                           drucker: str, platte: str | None = None) -> None:
        gm = [g for g in vs.auf_platten(gr) if g.material == mat and g.filament]
        if not gm:
            return
        stand = self._dv_stand
        akey = vs.anordnung_schluessel(mat, gr)
        cache = sl.cache_ordner() / "anordnung"
        cache.mkdir(parents=True, exist_ok=True)
        arbeit = sl.arbeitsordner("platten")
        try:
            stls = {g.id: self._dv_stl(g, druck, sl.cache_ordner() / g.schluessel) for g in gm}
            lokal = {}
            for gid, p in stls.items():
                ziel = arbeit / f"{gid}.stl"
                shutil.copyfile(p, ziel)
                lokal[gid] = ziel
            if akey not in stand.anordnung:
                abstand = 6.0 + (10.0 if any(g.einstellungen.get("brim") for g in gm) else 0.0)
                platten = sl.anordnen([(lokal[g.id], g.anzahl) for g in gm], arbeit / "anordnen", abbruch,
                                      filament=str(gm[0].filament), drucker=drucker, abstand_mm=abstand,
                                      platte=platte)
                for p in platten:
                    for o in p["objekte"]:
                        o["gruppe"] = str(o.get("name") or "").split(".stl")[0]
                        o.pop("matrix", None)
                a = {"material": mat, "platten": platten, "stand": time.strftime("%Y-%m-%dT%H:%M:%S")}
                self._dv_pruefe_abbruch(abbruch)
                with self._dv_lock:
                    stand.anordnung[akey] = a
                (cache / f"{akey}.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
                self._dv_senden({**(self._dv_eingang or {})})
            # Platten genau slicen (feste Lagen aus der Anordnung, Einstellungen je Teil)
            with self._dv_lock:
                platten_jetzt = [p for m, p in self._dv_platten if m == mat]
            nach_id = {g.id: g for g in gr}
            ergebnis: dict[str, Any] = {}
            for p in platten_jetzt:
                pkey = vs.platten_schluessel(mat, p, nach_id)
                if pkey in stand.platten:
                    continue
                objekte = [sl.PlattenObjekt(stl=lokal[l_.stueck.gruppe], x=l_.x, y=l_.y, drehung=l_.drehung,
                                            einstellungen={k: v for k, v in nach_id[l_.stueck.gruppe].einstellungen
                                                           .items() if k != "ausrichtung"},
                                            name=l_.stueck.name) for l_ in p.lagen if l_.stueck.gruppe in lokal]
                if len(objekte) != len(p.lagen):
                    continue
                self._dv_pruefe_abbruch(abbruch)
                e0 = {k: v for k, v in nach_id[p.lagen[0].stueck.gruppe].einstellungen.items() if k != "ausrichtung"}
                res = sl.slice_platten([objekte], [str(gm[0].filament)], arbeit / f"p{len(ergebnis)}", e0, abbruch,
                                       drucker, platte)
                if res:
                    ergebnis[pkey] = res
                    with self._dv_lock:
                        stand.platten[pkey] = res
                    self._dv_senden({**(self._dv_eingang or {})})
            if ergebnis:
                p = cache / f"{akey}.json"
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    d.setdefault("platten_ergebnis", {}).update(ergebnis)
                    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except (OSError, ValueError):
                    pass
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    # -----------------------------------------------------------------------------------------------------------------
    # App

    def _druckvorschau_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in ANFRAGEN:
            return False
        self._pool.submit(self._dv_anfrage_sicher, header)  # type: ignore[attr-defined]
        return True

    def _dv_anfrage_sicher(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        try:
            kind = header.get("type")
            if kind == "PRINT_PREVIEW_REQ":
                from kevcad_kernel.protocol import pack_print_preview

                v = self._dv_aktuell(warten_s=10.0)
                self._send_app(pack_print_preview(v, reply_to=rid))  # type: ignore[attr-defined]
            elif kind == "PRINT_SETTINGS":
                von = str(header.get("von") or "kevin")
                res = self.druck_einstellen(header.get("teil") or header.get("gruppe") or "",
                                            header.get("einstellungen"), header.get("zweck"), von=von,
                                            zuruecksetzen=bool(header.get("zuruecksetzen")), warten=False)
                self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),  # type: ignore[attr-defined]
                                "message": res.get("meldung") or res.get("error") or ""})
            elif kind == "PRINT_EXPORT_REQ":
                from kevcad_kernel.protocol import print_export_res

                self._send_app({"type": "ACK", "reply_to": rid, "ok": True,  # type: ignore[attr-defined]
                                "message": "3MF wird geschrieben"})
                res = self.druck_export(header.get("ziel"), header.get("platten") or None,
                                        teile=header.get("teile") or None, ohne=header.get("ohne") or None)
                extra = {k: res[k] for k in ("hinweise", "ms", "geprueft", "pfade", "dateien", "weggelassen",
                                             "leere_platten") if k in res}
                self._send_app(print_export_res(str(rid), ok=bool(res.get("ok")), pfad=res.get("pfad"),  # type: ignore[attr-defined]
                                                platten=list(res.get("platten") or []), fehler=res.get("error"),
                                                **extra))
        except Exception as exc:  # noqa: BLE001
            self._send_app({"type": "ERROR", "reply_to": rid,  # type: ignore[attr-defined]
                            "message": f"{type(exc).__name__}: {exc}"})

    # -----------------------------------------------------------------------------------------------------------------
    # KernelService

    def _dv_aktuell(self, warten_s: float = WARTEN_S) -> dict[str, Any]:
        """Die Vorschau des letzten Laufs; wartet auf eine laufende Prüfung und den ersten Bau."""
        stand = self._pruef  # type: ignore[attr-defined]
        laeuft = stand.erwartet
        if laeuft is not None:
            stand.warte(laeuft, warten_s)
        frist = time.monotonic() + warten_s
        while time.monotonic() < frist:
            with self._dv_lock:
                v = self._dv_vorschau
                wartet = self._dv_auftrag is not None
                bekannt = self._dv_eingang is not None
                gebaut = v is not None and (self._dv_eingang is None or v.get("run") == self._dv_eingang.get("run"))
            if gebaut and not wartet:
                return v  # type: ignore[return-value]
            if not bekannt and laeuft is None:
                break
            time.sleep(0.02)
        with self._dv_lock:
            v = self._dv_vorschau
        return v if v is not None else vs.leer(0, "Noch kein Lauf mit Druckteilen.")

    def druckvorschau(self, detail: bool = False) -> dict[str, Any]:
        if self._project is None:  # type: ignore[attr-defined]
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        v = self._dv_aktuell()
        return {"ok": True, **(v if detail else vs.kurz(v))}

    def _dv_namen(self, teil: str) -> tuple[list[str], str | None]:
        """Teilnamen zu einem Teil, einer Gruppe (g3), einem Gruppennamen oder einem Baugruppen-Präfix."""
        with self._dv_lock:
            gr = list(self._dv_gruppen)
        teil = str(teil or "").strip()
        for g in gr:
            if teil in (g.id, g.name):
                return list(g.teile), g.name
        for g in gr:
            if teil in g.teile:
                return list(g.teile), g.name  # ein Teil steht für seine Gruppe (gleiche Teile gleich drucken)
        praefix = teil.rstrip("/") + "/"
        namen = [n for g in gr for n in g.teile if n.startswith(praefix)]
        return namen, None

    def druck_einstellen(self, teil: str, einstellungen: dict[str, Any] | None = None, zweck: str | None = None,
                         von: str = "agent", zuruecksetzen: bool = False, warten: bool = True) -> dict[str, Any]:
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        if einstellungen is None and zweck is None and not zuruecksetzen:
            return {"ok": False, "error": "Nichts zu ändern: einstellungen, zweck oder zuruecksetzen angeben."}
        self._dv_aktuell(warten_s=10.0 if warten else 0.5)
        namen, gruppe = self._dv_namen(teil)
        if not namen:
            with self._dv_lock:
                alle = [g.name for g in self._dv_gruppen]
            return {"ok": False, "error": f"Druckteil oder Gruppe {teil!r} nicht in der Druckvorschau"
                                          + (f" (Gruppen: {', '.join(alle[:12])})" if alle else "")}
        try:
            d = vg.setze(proj.path, namen, einstellungen=einstellungen, zweck=zweck, zuruecksetzen=zuruecksetzen,
                         von=von)
        except (vg.VorgabeFehler, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            return {"ok": False, "error": f"druck.json nicht schreibbar: {exc}"}
        teile = []
        if zuruecksetzen:
            teile.append("alle Vorgaben zurück")
        if zweck:
            teile.append(f"Zweck {zweck}")
        for k, v in vg.pruefe_einstellungen(einstellungen or {}).items():
            teile.append(f"{k} zurück" if v is None else vs.em._feld_text(k, v))
        meldung = f"{gruppe or teil}: " + ", ".join(teile) + f" (fest, druck.json, {len(namen)} Teil" + \
            ("e)" if len(namen) != 1 else ")")
        with self._dv_lock:
            vorher = getattr(self, "_dv_bau_nr", 0)
        self._dv_neu_bauen()
        out: dict[str, Any] = {"ok": True, "meldung": meldung, "teile": namen, "druck_json": str(vg.pfad(proj.path)),
                               "vorgaben": {n: d["teile"].get(n) for n in namen}}
        if warten:
            frist = time.monotonic() + 5.0
            while time.monotonic() < frist and getattr(self, "_dv_bau_nr", 0) <= vorher:
                time.sleep(0.02)
            with self._dv_lock:
                v = self._dv_vorschau
            if v is not None:
                out["gruppe"] = next((t for t in v.get("teile") or [] if set(namen) & set(t.get("teile") or [])), None)
        return out

    def druck_export(self, ziel: str | None = None, platten: list[int] | None = None, teile: list[str] | None = None,
                     ohne: list[str] | None = None) -> dict[str, Any]:
        """3MF der Platten (MCP ``druck_export``, ``PRINT_EXPORT_REQ``, Eingang von Phase 8): {"ok", "pfad",
        "platten", "fehler", "hinweise", "geprueft", "ms", "materialien"}; mit Bambu Studio ein Bambu-Projekt mit
        Drucker-, Prozess- und Filamentprofilen (``Metadata/project_settings.config``) und den Einstellungen je Teil
        (``Metadata/model_settings.config``), so dass ``BambuStudio --slice 0 <3mf>`` die Empfehlungen übernimmt.

        Auswahl (additiv, ``druck/auswahl.py``): ``teile`` nur diese Teile, ``ohne`` diese nicht (Teilname aus
        ``show()``, Baugruppe als Präfix, Gruppe „g3“ oder Gruppenname; ``ohne`` gewinnt). Die übrigen Teile bleiben an
        ihrer Stelle, leere Platten fallen weg. Dazu im Ergebnis "teile" (exportiert), "weggelassen" ([{"name",
        "grund": ohne | teile | spaeter, "platte", "anzahl"}], auch die Teile „später drucken“), "leere_platten" und je
        Datei "objekte" (Objektnamen im 3MF, wie Bambu Studio sie zeigt)."""
        res = self._druck_export(ziel, platten, teile, ohne)
        res.setdefault("fehler", None if res.get("ok") else res.get("error"))
        res.setdefault("pfad", None)
        return res

    def _druck_export(self, ziel: str | None = None, platten: list[int] | None = None,
                      teile: list[str] | None = None, ohne: list[str] | None = None) -> dict[str, Any]:
        from kevcad_kernel.druck import auswahl as au

        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen.", "platten": []}
        t0 = time.perf_counter()
        v = self._dv_aktuell()
        with self._dv_lock:
            gr = list(self._dv_gruppen)
            alle = list(self._dv_platten)
            eingang = dict(self._dv_eingang or {})
        if not alle:
            spaeter = [n for g in gr if g.spaeter for n in g.teile]
            if spaeter:
                return {"ok": False, "platten": [],
                        "error": "Alle Druckteile sind als später markiert (lager.druckteil(…, spaeter=True)): "
                                 + ", ".join(spaeter[:6]) + (" …" if len(spaeter) > 6 else "") + "."}
            return {"ok": False, "error": "Keine Druckteile im Modell.", "platten": []}
        nummern = [int(n) for n in (platten or [])] or list(range(1, len(alle) + 1))
        falsch = [n for n in nummern if not 1 <= n <= len(alle)]
        if falsch:
            return {"ok": False, "error": f"Platte {falsch[0]} gibt es nicht (1 bis {len(alle)})", "platten": []}
        try:
            ausw = au.waehle([(n, alle[n - 1][0], alle[n - 1][1]) for n in nummern], gr, teile, ohne,
                             gedruckt=[str(x.get("name")) for x in (v.get("gedruckt") or [])])
        except au.AuswahlFehler as exc:
            return {"ok": False, "error": str(exc), "platten": []}
        nicht = [nr for nr, _, p in ausw.platten if p.passt_nicht]
        if nicht:
            return {"ok": False, "error": f"Platte {nicht[0]}: Teil passt nicht in den Bauraum (Druckprüfung)",
                    "platten": []}
        pfad = Path(ziel).expanduser() if ziel else proj.output_dir / f"{proj.name}-druck.3mf"
        if pfad.suffix.lower() != ".3mf":
            pfad = pfad.with_suffix(".3mf")
        nach_id = {g.id: g for g in gr}
        druck = eingang.get("druck") or {}
        materialien = list(dict.fromkeys(m for _, m, _ in ausw.platten))
        arbeit = sl.arbeitsordner("export")
        hinweise: list[str] = []
        weg_text = au.weggelassen_text(ausw.weggelassen)
        if weg_text:
            hinweise.append(weg_text)
        hinweise += ausw.hinweise
        try:
            stls: dict[str, Path] = {}
            for _, _, p in ausw.platten:
                for l_ in p.lagen:
                    g = nach_id[l_.stueck.gruppe]
                    if g.id not in stls:
                        ordner = sl.cache_ordner() / g.schluessel
                        ordner.mkdir(parents=True, exist_ok=True)
                        stls[g.id] = self._dv_stl(g, druck, ordner)
                        ziel_stl = arbeit / f"{g.id}.stl"
                        shutil.copyfile(stls[g.id], ziel_stl)
                        stls[g.id] = ziel_stl
            dateien: list[dict[str, Any]] = []
            geprueft = sl.verfuegbar()
            projekt = vs.projekt_einstellungen(self._dv_projekt_daten()[0])  # kevcad.json jetzt (druck.platte)
            drucker = str(projekt.get("drucker") or vs.DRUCKER_ID)
            platte = str(projekt.get("platte") or sl.PLATTE_STANDARD)
            if projekt.get("platte_fehler"):
                hinweise.append(f"kevcad.json druck.platte: {projekt['platte_fehler']}; genommen: {platte}.")
            for mat in materialien:  # ein Bambu-Projekt je Material (ein Filament je Datei, P1P ohne AMS)
                sel = [(nr, p) for nr, m, p in ausw.platten if m == mat]
                nr_mat = [nr for nr, _ in sel]
                listen = [[sl.PlattenObjekt(stl=stls[l_.stueck.gruppe], x=l_.x, y=l_.y, drehung=l_.drehung,
                                            einstellungen={k: x for k, x in nach_id[l_.stueck.gruppe]
                                                           .einstellungen.items() if k != "ausrichtung"},
                                            name=l_.stueck.name) for l_ in p.lagen] for _, p in sel]
                pnamen = [f"Platte {nr}" for nr in nr_mat]  # Nummern wie in der Druckvorschau
                ziel_m = pfad if len(materialien) == 1 else pfad.with_name(f"{pfad.stem}-{mat}{pfad.suffix}")
                filament = next((g.filament for g in gr if g.material == mat and g.filament), None)
                gm = [g for g in vs.auf_platten(gr) if g.material == mat]
                if sl.verfuegbar() and filament:
                    e0 = {k: x for k, x in gm[0].einstellungen.items() if k != "ausrichtung"}
                    farbe = str((self._dv_material(mat) or {}).get("farbe") or "") or None
                    res = sl.export_3mf(listen, str(filament), ziel_m, arbeit / f"bambu-{mat}", e0, None, drucker,
                                        farbe, platte, platten_namen=pnamen)
                    hinweise.append(f"{mat.upper()}: in Bambu Studio geprüft, {len(nr_mat)} Platte"
                                    + ("n" if len(nr_mat) != 1 else "") + f", {res['objekte']} Teile, Profile "
                                    f"„{sl.MASCHINE}“, „{sl.prozess_name(float(e0.get('schicht_mm') or 0.2))}“, "
                                    f"„{filament}“, Platte „{platte}“ und Einstellungen je Teil.")
                    if res.get("benannt", 0) < len(res.get("namen") or []):
                        hinweise.append(f"{mat.upper()}: Objektnamen nur teilweise gesetzt ({res.get('benannt', 0)} "
                                        f"von {len(res.get('namen') or [])}); Bambu Studio zeigt sonst „assemble_…“.")
                    dateien.append({"pfad": str(ziel_m), "material": mat, "filament": filament, "platten": nr_mat,
                                    "objekte": list(res.get("namen") or [])})
                else:
                    # Ohne Bambu Studio: ein 3MF je Platte (Teile in ihrer Lage); Bambu Studio liest Platten nur aus
                    # eigenen Projekten, ein fremdes 3MF legt es ganz auf eine Platte
                    from kevcad_kernel.druck.dreimf import schreibe_3mf

                    geprueft = False
                    for nr, liste, pname in zip(nr_mat, listen, pnamen):
                        ziel_p = ziel_m if len(nr_mat) == 1 else \
                            ziel_m.with_name(f"{ziel_m.stem}-platte{nr}{ziel_m.suffix}")
                        r = schreibe_3mf(ziel_p, [liste], titel=f"Kev CAD · {proj.name} · Platte {nr}",
                                         platten_namen=[pname])
                        dateien.append({"pfad": str(ziel_p), "material": mat, "filament": filament, "platten": [nr],
                                        "objekte": list(r.get("namen") or [])})
                    hinweise.append(f"{mat.upper()}: ohne Bambu Studio geschrieben (je Platte eine Datei, Teile in "
                                    "ihrer Lage, ohne Profile); Drucker, Prozess und Filament beim Öffnen in Bambu "
                                    "Studio wählen.")
        except (sl.SlicerFehler, OSError) as exc:
            return {"ok": False, "error": f"3MF nicht geschrieben: {exc}", "platten": []}
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)
        if len({d["material"] for d in dateien}) > 1:
            hinweise.append(f"{len(materialien)} Materialien: je Material ein Bambu-Projekt (Spule zwischen den "
                            "Dateien wechseln).")
        return {"ok": True, "pfad": dateien[0]["pfad"], "pfade": [d["pfad"] for d in dateien], "dateien": dateien,
                "platten": [nr for nr, _, _ in ausw.platten], "hinweise": hinweise, "geprueft": geprueft,
                "ms": int(round((time.perf_counter() - t0) * 1000)), "materialien": materialien,
                "teile": ausw.teile, "weggelassen": ausw.weggelassen, "leere_platten": ausw.leere_platten}

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

from kevcad_kernel.druck import filamentwahl as fw
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

    def _dv_spulen(self) -> list[dict[str, Any]]:
        """Filamentspulen aus dem Bestand des Projekts (``bestand.json``, nur lesen) für die Wahl des Filamentprofils."""
        from kevcad_kernel.bestand.datei import pfade, spulen

        proj = self._project  # type: ignore[attr-defined]
        p, _ = pfade(proj.path if proj is not None else None)
        if p is None or not p.is_file():
            return []
        try:
            return spulen(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def _dv_zuletzt(self) -> dict[str, str]:
        """Zuletzt für dieses Projekt gewähltes Filament je Material (``druck.json`` → ``filament``)."""
        proj = self._project  # type: ignore[attr-defined]
        return vg.filament_zuletzt(proj.path) if proj is not None else {}

    def _dv_projekt(self) -> dict[str, Any]:
        """``kevcad.json`` → druck (jetzt) mit den Spulen des Bestands und dem zuletzt gewählten Filament."""
        return vs.projekt_einstellungen(self._dv_projekt_daten()[0], self._dv_spulen(), self._dv_zuletzt())

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
                                     settings, self._dv_material, stand, regler=bool(eingang.get("regler")),
                                     spulen=self._dv_spulen(), filament_zuletzt=self._dv_zuletzt())
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
        projekt = self._dv_projekt()
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
        projekt = self._dv_projekt()
        drucker, platte = str(projekt.get("drucker")), str(projekt.get("platte"))
        for g in offen:
            self._dv_pruefe_abbruch(abbruch)
            if not sl.platte_passt(g.filament_slicer, platte):  # Bambu Studio bräche ab (Hinweis steht in der Vorschau)
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
                res = sl.slice_teil(stl, e, g.filament_slicer, arbeit, abbruch, drucker, platte)
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
                                      filament=gm[0].filament_slicer, drucker=drucker, abstand_mm=abstand,
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
                res = sl.slice_platten([objekte], [gm[0].filament_slicer], arbeit / f"p{len(ergebnis)}", e0, abbruch,
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
                fil = header.get("filament")
                if isinstance(fil, str) and fil.strip().lower() == "vorschau":
                    fil = None  # nur intern (Phase 8); die App wählt das Filament ausdrücklich
                res = self.druck_export(header.get("ziel"), header.get("platten") or None,
                                        teile=header.get("teile") or None, ohne=header.get("ohne") or None,
                                        filament=fil or None)
                extra = {k: res[k] for k in ("hinweise", "ms", "geprueft", "pfade", "dateien", "weggelassen",
                                             "leere_platten", "filamente", "filament_frage", "vorschlaege",
                                             "druckfertig", "objekte_einstellungen")
                         if k in res}
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
                     ohne: list[str] | None = None, filament: Any = None) -> dict[str, Any]:
        """3MF der Platten (MCP ``druck_export``, ``PRINT_EXPORT_REQ``, Eingang von Phase 8): {"ok", "pfad",
        "platten", "fehler", "hinweise", "geprueft", "ms", "materialien"}; mit Bambu Studio ein Bambu-Projekt mit
        Drucker-, Prozess- und Filamentprofilen (``Metadata/project_settings.config``) und den Einstellungen je Teil
        (``Metadata/model_settings.config``), so dass ``BambuStudio --slice 0 <3mf>`` die Empfehlungen übernimmt.

        Auswahl (additiv, ``druck/auswahl.py``): ``teile`` nur diese Teile, ``ohne`` diese nicht (Teilname aus
        ``show()``, Baugruppe als Präfix, Gruppe „g3“ oder Gruppenname; ``ohne`` gewinnt). Die übrigen Teile bleiben an
        ihrer Stelle, leere Platten fallen weg. Dazu im Ergebnis "teile" (exportiert), "weggelassen" ([{"name",
        "grund": ohne | teile | spaeter, "platte", "anzahl"}], auch die Teile „später drucken“), "leere_platten" und je
        Datei "objekte" (Objektnamen im 3MF, wie Bambu Studio sie zeigt).

        Filament (Kevin, 22.10.2026, ``druck/filamente.py``): ``filament`` je Material ein Filament aus Kevins Liste
        (``{"petg": "polymaker-polylite-petg-gelb"}``, eine id oder eine Liste von ids). Fehlt es, wird nichts
        geschrieben: {"ok": false, "filament_frage": true, "vorschlaege": {material: {"zuletzt", "spulen",
        "liste"}}} mit der Anweisung, Kevin zu fragen. ``"vorschau"`` (nur intern, Phase 8: der Dialog „Drucken …“
        zeigt es Kevin) nimmt das Filament der Druckvorschau. Das Preset geht vollständig ins Bambu-Projekt; im
        Ergebnis "filamente" je Material und je Datei "filament_id", "filament_basis", "abweichungen", "temperaturen"."""
        res = self._druck_export(ziel, platten, teile, ohne, filament)
        res.setdefault("fehler", None if res.get("ok") else res.get("error"))
        res.setdefault("pfad", None)
        return res

    def _dv_filament_waehlen(self, filament: Any, materialien: list[str], gr: list[vs.Gruppe],
                             projekt: dict[str, Any]) -> tuple[dict[str, fw.FilamentWahl], dict[str, Any] | None]:
        """Filament je Material für den Export: (Wahl je Material, Fehler bzw. Rückfrage oder None)."""
        from kevcad_kernel.druck import filamente as fl

        drucker = str(projekt.get("drucker") or vs.DRUCKER_ID)
        platte = str(projekt.get("platte") or sl.PLATTE_STANDARD)
        out: dict[str, fw.FilamentWahl] = {}
        if isinstance(filament, str) and filament.strip().lower() == "vorschau":  # intern (Phase 8)
            for mat in materialien:
                g = next((x for x in vs.auf_platten(gr) if x.material == mat), None)
                w = dict(g.filament_wahl) if g is not None else {}
                out[mat] = fw.FilamentWahl(mat, w.get("profil") or (g.filament if g else None),
                                           str(w.get("quelle") or "system"), str(w.get("detail") or ""),
                                           filament=w.get("filament"), basis=w.get("basis"), preset=w.get("preset"),
                                           abweichungen=list(w.get("abweichungen") or []),
                                           temperaturen=w.get("temperaturen"))
            return out, None
        angaben: dict[str, str] = {}
        fehler: list[str] = []
        if isinstance(filament, dict):
            angaben = {str(k).lower(): str(v) for k, v in filament.items() if v}
        else:
            for e in [filament] if isinstance(filament, str) else list(filament or []):
                f = fl.finde(e)
                if f is None:
                    fehler.append(f"Filament {e!r} gibt es nicht in Kevins Liste (vorhanden: "
                                  + ", ".join(fl.vorschlaege_ids(str(e))) + "; neues mit filament_define)")
                else:
                    angaben[str(f.get("material") or "").lower()] = str(f.get("id"))
        fehlt = [m for m in materialien if m not in angaben]
        for mat in materialien:
            if mat not in angaben:
                continue
            f = fl.finde(angaben[mat])
            if f is None:
                fehler.append(f"Filament {angaben[mat]!r} gibt es nicht in Kevins Liste (vorhanden für {mat.upper()}: "
                              + (", ".join(fl.vorschlaege_ids(angaben[mat], mat)) or "keins") + "; neues mit "
                              "filament_define)")
                continue
            if str(f.get("material") or "").lower() != mat:
                fehler.append(f"Filament {f.get('id')!r} ist {str(f.get('material')).upper()}, die Platten brauchen "
                              f"{mat.upper()}")
                continue
            w = fw.wahl_fuer(f, "kevin", f"gewählt: {fl.anzeige(f)}", platte, drucker)
            if w.verworfen:
                fehler += w.verworfen
                continue
            out[mat] = w
        if fehler:
            return out, {"ok": False, "error": "; ".join(fehler), "platten": []}
        if fehlt:
            zuletzt = self._dv_zuletzt()
            spulen = self._dv_spulen()
            vorschlaege = {m: fw.vorschlaege(m, zuletzt.get(m), spulen) for m in fehlt}
            teile = []
            beispiel = []
            for m in fehlt:
                v_ = vorschlaege[m]
                z = f"zuletzt gewählt {v_['zuletzt']}" if v_["zuletzt"] else "noch keins gewählt"
                sp = ", ".join(f"{s_['kennung']} {s_.get('name') or ''} → {s_.get('filament') or '?'}"
                               for s_ in v_["spulen"]) or "keine"
                li = ", ".join(f"{x['id']} ({x['name']})" for x in v_["liste"]) or "keins (erst filament_define)"
                teile.append(f"{m.upper()}: {z}; Spulen im Bestand: {sp}; Filamente: {li}")
                bsp = v_["zuletzt"] or (v_["liste"][0]["id"] if v_["liste"] else "…")
                beispiel.append(f'"{m}": "{bsp}"')
            return out, {"ok": False, "filament_frage": True, "vorschlaege": vorschlaege, "platten": [],
                         "error": "Frag Kevin nach dem Filament, bevor du exportierst (es wurde nichts geschrieben). "
                                  "Nimm nie stillschweigend das zuletzt benutzte. Vorschläge: " + " | ".join(teile)
                                  + ". Dann druck_export(filament={" + ", ".join(beispiel) + "}) mit Kevins Antwort."}
        return out, None

    def _druck_export(self, ziel: str | None = None, platten: list[int] | None = None,
                      teile: list[str] | None = None, ohne: list[str] | None = None,
                      filament: Any = None) -> dict[str, Any]:
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
        projekt = self._dv_projekt()  # kevcad.json jetzt (druck.platte)
        wahl_je, frage = self._dv_filament_waehlen(filament, materialien, gr, projekt)
        if frage is not None:
            return frage
        arbeit = sl.arbeitsordner("export")
        hinweise: list[str] = []
        pruefungen: list[dict[str, Any]] = []
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
                gm = [g for g in vs.auf_platten(gr) if g.material == mat]
                wahl = wahl_je[mat]
                filament_n = wahl.profil
                herkunft = {"filament_id": wahl.filament, "filament_basis": wahl.basis,
                            "abweichungen": list(wahl.abweichungen), "filament_quelle": wahl.quelle,
                            "filament_detail": wahl.detail, "temperaturen": wahl.temperaturen}
                hinweise.append(self._dv_filament_text(mat, wahl))
                if sl.verfuegbar() and filament_n:
                    e0 = {k: x for k, x in gm[0].einstellungen.items() if k != "ausrichtung"}
                    farbe = str((self._dv_material(mat) or {}).get("farbe") or "") or None
                    res = sl.export_3mf(listen, wahl.slicer_filament, ziel_m, arbeit / f"bambu-{mat}", e0, None,
                                        drucker, farbe, platte, platten_namen=pnamen)
                    hinweise.append(f"{mat.upper()}: in Bambu Studio geprüft, {len(nr_mat)} Platte"
                                    + ("n" if len(nr_mat) != 1 else "") + f", {res['objekte']} Teile, Profile "
                                    f"„{sl.MASCHINE}“, „{sl.prozess_name(float(e0.get('schicht_mm') or 0.2))}“, "
                                    f"„{filament_n}“, Platte „{platte}“ und Einstellungen je Teil.")
                    # Paket B: vor der Ausgabe so slicen, wie Kevin es öffnet, und die Warnungen auswerten
                    pr_ = sl.pruefe_slicen(ziel_m, arbeit / f"pruef-{mat}")
                    pruefungen.append(pr_)
                    if pr_["fehler"]:
                        hinweise.append(f"{mat.upper()}: NICHT druckfertig, Bambu Studio slict das 3MF nicht: "
                                        f"{pr_['fehler']}")
                    elif pr_["warnungen"]:
                        hinweise.append(f"{mat.upper()}: NICHT druckfertig, Bambu Studio warnt: "
                                        + "; ".join(f"Platte {w['platte']}: {w['art']} ({w['text']})"
                                                    for w in pr_["warnungen"]))
                    else:
                        z_ = sum(p_["zeit_s"] for p_ in pr_["platten"])
                        g_ = sum(p_["g"] for p_ in pr_["platten"])
                        from kevcad_kernel.druck.vorschau_text import dauer_text

                        hinweise.append(f"{mat.upper()}: druckfertig, in Bambu Studio geslict ohne Warnungen "
                                        f"({dauer_text(z_)}, {g_:.0f} g).")
                    if res.get("benannt", 0) < len(res.get("namen") or []):
                        hinweise.append(f"{mat.upper()}: Objektnamen nur teilweise gesetzt ({res.get('benannt', 0)} "
                                        f"von {len(res.get('namen') or [])}); Bambu Studio zeigt sonst „assemble_…“.")
                    dateien.append({"pfad": str(ziel_m), "material": mat, "filament": filament_n, "platten": nr_mat,
                                    "objekte": list(res.get("namen") or []), **herkunft,
                                    "pruefung": {k: pr_[k] for k in ("ok", "warnungen", "platten", "fehler")}})
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
                        dateien.append({"pfad": str(ziel_p), "material": mat, "filament": filament_n,
                                        "platten": [nr], "objekte": list(r.get("namen") or []), **herkunft})
                    hinweise.append(f"{mat.upper()}: ohne Bambu Studio geschrieben (je Platte eine Datei, Teile in "
                                    "ihrer Lage, ohne Profile); Drucker, Prozess und Filament beim Öffnen in Bambu "
                                    f"Studio wählen" + (f": Preset „{filament_n}“." if filament_n else "."))
        except (sl.SlicerFehler, OSError) as exc:
            return {"ok": False, "error": f"3MF nicht geschrieben: {exc}", "platten": []}
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)
        neu = {m: w.filament for m, w in wahl_je.items() if w.filament and w.quelle == "kevin"}
        if neu:
            try:
                if vg.setze_filament(proj.path, neu):  # zuletzt gewählt: Annahme der Vorschau, Vorschlag beim Fragen
                    self._dv_neu_bauen()
            except OSError as exc:
                hinweise.append(f"druck.json nicht schreibbar (zuletzt gewähltes Filament): {exc}")
        if len({d["material"] for d in dateien}) > 1:
            hinweise.append(f"{len(materialien)} Materialien: je Material ein Bambu-Projekt (Spule zwischen den "
                            "Dateien wechseln).")
        return {"ok": True, "pfad": dateien[0]["pfad"], "pfade": [d["pfad"] for d in dateien], "dateien": dateien,
                "platten": [nr for nr, _, _ in ausw.platten], "hinweise": hinweise, "geprueft": geprueft,
                "ms": int(round((time.perf_counter() - t0) * 1000)), "materialien": materialien,
                "teile": ausw.teile, "weggelassen": ausw.weggelassen, "leere_platten": ausw.leere_platten,
                "filamente": {m: {"id": w.filament, "preset": w.profil, "basis": w.basis, "quelle": w.quelle,
                                  "detail": w.detail, "abweichungen": list(w.abweichungen),
                                  "temperaturen": w.temperaturen} for m, w in wahl_je.items()},
                # Paket B: druckfertig nur, wenn Bambu Studio jede Datei ohne Warnung geslict hat
                "druckfertig": bool(geprueft and pruefungen and all(p_["ok"] for p_ in pruefungen)),
                "objekte_einstellungen": self._dv_objekt_einstellungen(gr, ausw, wahl_je, platte)}

    @staticmethod
    def _dv_objekt_einstellungen(gr: list[vs.Gruppe], ausw: Any, wahl_je: dict[str, fw.FilamentWahl] | None = None,
                                 platte: str | None = None) -> list[dict[str, Any]]:
        """Je exportierter Gruppe die Einstellungen mit Begründung (Paket B, druckfertig je Objekt); Platte, Bett,
        Tempo und Kühlung kommen aus dem Preset des gewählten Filaments."""
        drin = {l_.stueck.gruppe for _, _, p in ausw.platten for l_ in p.lagen}
        out = []
        for g in gr:
            if g.id not in drin:
                continue
            b = dict(g.begruendung_je)
            w = (wahl_je or {}).get(g.material)
            if w is not None:
                t = w.temperaturen or {}
                b["platte"] = (f"{platte or sl.PLATTE_STANDARD}, Bett und Düse aus dem Preset „{w.profil}“"
                               + (f": {fw.temperaturen_text(t)}" if t else ""))
                lf = t.get("luefter") or [None, None]
                b["tempo"] = (f"Tempo und Kühlung aus dem Preset „{w.profil}“"
                              + (f" (Lüfter {lf[0]:g}–{lf[1]:g} %" if None not in lf else " (")
                              + (f", höchstens {t['max_volumen']:g} mm³/s)" if t.get("max_volumen") else ")")
                              + "; dessen Mindestschichtzeit bremst kleine Querschnitte selbst")
            out.append({"gruppe": g.id, "name": g.name, "teile": [n for n in g.teile if n in ausw.teile],
                        "einstellungen": {k: v for k, v in g.einstellungen.items()}, "fest": list(g.fest),
                        "begruendung_je": b})
        return out

    def _dv_material_druckbar(self, mid: str) -> bool:
        m = self._dv_material(mid)
        if m is None:
            try:
                m = self.catalog.find_material(mid, include_proposed=False)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                m = None
        return bool(m) and m.get("druckbar") is True and m.get("id") == mid

    def filament_liste(self, material: str | None = None) -> dict[str, Any]:
        """Kevins Filamente (``druck/filamente.py``) mit Preset, Basisprofil, Abweichungen und Temperaturen des
        aufgelösten Presets: {"ok", "pfad", "filamente", "zuletzt" (dieses Projekt), "spulen" (Bestand)}."""
        from kevcad_kernel.druck import filamente as fl

        try:
            liste = fl.liste(material)
            fl.lies()
        except fl.FilamentFehler as exc:
            return {"ok": False, "error": str(exc)}
        projekt = self._dv_projekt() if self._project is not None else {}  # type: ignore[attr-defined]
        platte = projekt.get("platte")
        out = []
        for f in liste:
            w = fw.wahl_fuer(f, "liste", fl.anzeige(f), platte)
            out.append({**f, "anzeige": fl.anzeige(f), "preset_name": fl.preset_name(f),
                        "abweichungen_text": fl.abweichungen_text(f), "temperaturen": w.temperaturen,
                        "probleme": list(w.verworfen)})
        spulen = [{"kennung": s.get("kennung"), "material": s.get("material"), "name": s.get("name"),
                   "gramm": s.get("gramm"), "filament": (fl.fuer_spule(s) or {}).get("id")}
                  for s in (self._dv_spulen() if self._project is not None else [])]  # type: ignore[attr-defined]
        return {"ok": True, "pfad": str(fl.pfad()), "filamente": out,
                "zuletzt": self._dv_zuletzt() if self._project is not None else {},  # type: ignore[attr-defined]
                "spulen": spulen}

    def filament_define(self, hersteller: str, produkt: str, material: str, farbe: str | None = None,
                        durchmesser_mm: float = 1.75, basis: str | None = None,
                        abweichungen: list[dict[str, Any]] | None = None, farbe_hex: str | None = None,
                        id: str | None = None, preset_name: str | None = None, quelle: str | None = None,  # noqa: A002
                        ersetzen: bool = False) -> dict[str, Any]:
        """Filament in Kevins Liste anlegen (ohne Katalog-Freigabe). ``basis`` ohne Angabe aus Hersteller und Produkt
        (Bambu-Studio-Profil für den P1P); ``abweichungen`` je {"schluessel", "wert", "quelle"}.
        {"ok", "filament", "neu", "hinweise"}"""
        from kevcad_kernel.druck import filamente as fl

        mat = str(material or "").strip().lower()
        hinweise: list[str] = []
        if not basis:
            basis = fw.basis_vorschlag(hersteller, produkt, mat)
            if basis:
                hinweise.append(f"Basisprofil aus Hersteller und Produkt: „{basis}“.")
            elif sl.system_ordner().is_dir():
                kand = [k[0] for k in fw._kandidaten(mat, vs.DRUCKER_ID)][:12]
                return {"ok": False, "error": "basis fehlt: kein Bambu-Studio-Profil passt zu "
                                              f"„{hersteller} {produkt}“; eins angeben (für den P1P 0.4: "
                                              + (", ".join(kand) or "keins") + ")"}
        eintrag = {"id": id, "hersteller": hersteller, "produkt": produkt, "material": mat, "farbe": farbe,
                   "farbe_hex": farbe_hex, "durchmesser_mm": durchmesser_mm,
                   "preset": {"basis": basis, "abweichungen": list(abweichungen or []),
                              **({"name": preset_name} if preset_name else {})},
                   **({"quelle": quelle} if quelle else {})}
        vorher = {f.get("id") for f in fl.liste()}
        try:
            f = fl.define(eintrag, ersetzen=ersetzen, material_ok=self._dv_material_druckbar)
        except fl.FilamentFehler as exc:
            return {"ok": False, "error": str(exc)}
        except OSError as exc:
            return {"ok": False, "error": f"{fl.pfad().name} nicht schreibbar: {exc}"}
        w = fw.wahl_fuer(f, "liste", fl.anzeige(f))
        self._dv_neu_bauen(slicer=False)
        return {"ok": True, "filament": {**f, "anzeige": fl.anzeige(f), "temperaturen": w.temperaturen},
                "neu": f.get("id") not in vorher, "hinweise": hinweise + list(w.verworfen), "pfad": str(fl.pfad())}

    @staticmethod
    def _dv_filament_text(mat: str, w: fw.FilamentWahl) -> str:
        """„PETG: Filament Polymaker PolyLite PETG gelb (1,75 mm), Preset „…“ (Basis „…“; keine Abweichungen);
        Düse 255 °C, Texturplatte 80 °C.“"""
        from kevcad_kernel.druck import filamente as fl

        f = fl.finde(w.filament) if w.filament else None
        t = fw.temperaturen_text(w.temperaturen)
        if f is None:
            return f"{mat.upper()}: Filamentprofil „{w.profil}“ ({w.detail})" + (f"; {t}." if t else ".")
        return (f"{mat.upper()}: Filament {fl.anzeige(f)}, Preset „{w.profil}“ (Basis „{w.basis}“; "
                f"{fl.abweichungen_text(f)})" + (f"; {t}." if t else "."))

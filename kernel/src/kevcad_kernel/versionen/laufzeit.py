"""Versionen in der Kernel-Laufzeit (PLAN-VERSIONEN.md): wird in ``KernelRuntime`` eingemischt.

Nutzt die Bausteine der Laufzeit (``_project``, ``scene``, ``_bom``, ``_pruef``, ``_send_app``, ``_request``,
``_enqueue``, ``_submit_run``, ``_worker``, ``_pool``, ``_link``). runtime.py ruft nur wenige Stellen auf:

- ``_versionen_init()`` im Konstruktor,
- ``_versionen_projekt(proj, same)`` beim Öffnen eines Projekts (legt das Repo an, übernimmt alte Stände),
- ``_versionen_nach_lauf(job, result)`` nach jedem erfolgreichen Lauf (statt ``save_version``), vor der
  Hintergrundrechnung der Dokumente,
- ``_versionen_dokumente_nach_lauf(job, hintergrund)`` mit den Futures der Hintergrundrechnung (Blätter, Bauplan),
- ``_versionen_pruefung(check)`` bei jedem fertigen CHECK,
- ``_versionen_app_message(kind, header)`` für die App-Nachrichten dieses Abschnitts,
- ``_versionen_on_connect(conn)`` beim Verbinden der App,
- ``_schatten_job(job)`` / ``_schatten_nachricht(...)`` für den Lauf ohne Live-Aufbau (Vergleich, Nachberechnung),
- ``_versionen_agent_titel(result, titel)`` in ``run(titel=…)``: Titel des Agenten an die Version des Laufs.

Titel (titel.py): Jede neue Version bekommt ihren automatischen Titel gleich nach dem Lauf; übernommene und ältere
Stände zieht ``_titel_nachziehen`` beim Öffnen und nach jeder Nachberechnung nach (nur Metadaten, nie Git).

Läufe, Wiederherstellen, Variantenwechsel und Meilensteine laufen über die Auftragsschlange der Laufzeit; so ändert
nichts die Dateien, während ein Lauf rechnet.

Dokumente (Phase 6, DOKUMENTE.md): Blätter und Bauplan liegen in ``dokumente/`` und gehören zu den Versionen. Nach
jedem Lauf rechnen sie im Hintergrund neu (Bezüge neu zuordnen, automatische Maße). Was dabei geschrieben wird, gehört
zu der Version, die der Lauf angelegt hat:

- Legt Lauf N eine Version an (oder das Wiederherstellen unmittelbar davor), darf sie die Ergebnisse der
  Hintergrundrechnung noch aufnehmen (``_ver_nachtrag``). Ist die Rechnung fertig, trägt ``dokumente_nachtragen`` die
  Änderungen in ``dokumente/`` in diese Version nach (neuer Commit, gleiche Nummer, Titel und Bild), wenn sie noch die
  Spitze ist, keinen Meilenstein trägt und kein anderer Zweig sie enthält.
- Beginnt vorher ein neuer Lauf, speichert die alte Rechnung nicht weiter (``_lauf_aktuell``); ein Lauf ohne Änderung
  und ohne überschriebene Parameter übernimmt dann das Nachtragen. Ändert sich bis dahin nur ``dokumente/``, legt ein
  Lauf keine eigene Version dafür an.
- Läufe mit überschriebenen Parametern (Regler, ``run(params=…)``) zeigen nicht den Stand der Dateien: ihre
  Hintergrundrechnung speichert nichts.
- Ändern Kevin oder der Agent ein Blatt oder den Bauplan selbst (``_versionen_dokumente_bearbeitet``), ist das eine
  eigene Änderung: Sie wird mit dem nächsten Lauf eine eigene Version.
- ``versionen_info(run)`` liefert dem Schriftfeld die Nummer der Version des Laufs (mit Variante und Meilenstein).
"""

from __future__ import annotations

import hashlib
import itertools
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.versionen.archiv import HAUPT, KevinsMeilenstein, Version, Versionsarchiv, VersionsFehler
from kevcad_kernel.versionen.git import GitFehler
from kevcad_kernel.versionen.schnappschuss import (
    Zwischenspeicher,
    daten_aus_teilen,
    kennzahlen,
    netz,
    pruef_daten,
    pruef_kurz,
)
from kevcad_kernel.versionen.vergleich import geister_auswahl, vergleiche, zusammenfassung

BILD_BREITE, BILD_HOEHE = 288, 180
BILD_ABSTAND_S = 180.0  # Vorschaubild für gewöhnliche Versionen höchstens alle drei Minuten
AGENT_AKTIV_S = 90.0  # Auto-Lauf so kurz nach einem Werkzeug des Agenten zählt als Agent
LISTE_LIMIT = 400
MAX_GEISTER_DREIECKE = 3_000_000
SCHATTEN_RUN_BASIS = 1_000_000_000
NACHRECHNEN_RUHE_S = 3.0  # so lange nach einem Lauf von Kevin oder dem Agenten keine Nachberechnung
AGENT_TITEL_ALTER_S = 15 * 60  # run(titel=…) ohne neue Version: Titel an die aktuelle, wenn sie so jung ist


class VersionenRuntimeMixin:
    """Versionen, Meilensteine, Wiederherstellen, Vergleich und Varianten (KernelService, App-Nachrichten)."""

    # =================================================================================================================
    # Zustand
    # =================================================================================================================

    def _versionen_init(self) -> None:
        self._archiv: Versionsarchiv | None = None
        self._ver_speicher: Zwischenspeicher | None = None
        self._ver_bereit = threading.Event()
        self._ver_lauf_nr: dict[int, int] = {}  # Lauf → Versionsnummer
        self._ver_pruef: dict[int, dict[str, Any]] = {}  # CHECK, der vor der Version ankam
        self._ver_aktuell: dict[str, Any] = {}  # Parameter und Stückliste des letzten erfolgreichen Laufs
        self._ver_letztes_bild = 0.0
        self._agent_seen = 0.0
        self._ver_aktiv = time.monotonic()  # letzter Lauf von Kevin oder dem Agenten
        self._ver_schatten = itertools.count(1)
        self._ver_nachrechnen: threading.Thread | None = None
        self._ver_generation = 0
        self._ver_rechner = None  # HintergrundRechner für die Nachberechnung (eigener Prozess, bei Bedarf)
        self._ver_letzte: tuple[int, dict[str, Any]] | None = None  # Daten der zuletzt gerechneten Version (Titel)
        # Version, die die Hintergrundrechnung ihres Laufs noch aufnimmt: {"nr", "commit", "lauf"} (Modulbeschreibung)
        self._ver_nachtrag: dict[str, Any] | None = None
        self._ver_nt_lock = threading.Lock()
        self._ver_dok_sperre = 0  # Hintergrundrechnungen bis zu diesem Lauf speichern nicht mehr (Dateien ersetzt)
        # Ungesicherte Änderungen in dokumente/: von Kev CAD selbst angelegt (erster Bauplan) bzw. von Kevin oder dem
        # Agenten bearbeitet; die nächste Version nur aus Dokumenten führt Kev CAD, solange niemand selbst etwas änderte
        self._ver_dok_auto = False
        self._ver_dok_eigen = False

    def _versionen_schliessen(self) -> None:
        """Beim Beenden der Laufzeit: Hintergrund-Rechenprozess beenden."""
        self._ver_generation += 1
        rechner, self._ver_rechner = self._ver_rechner, None
        if rechner is not None:
            rechner.stop()

    def _versionen_sitzung(self) -> str | None:
        """Claude-Sitzung für „Wer“: die des laufenden Werkzeugaufrufs (Kopf der Brücke, MIRROR.md „Sitzungen“),
        sonst die aktive Sitzung aus der Liste der verbundenen Agenten."""
        try:
            from kevcad_kernel.mcp_tools.tracking import claude_session

            sitzung = claude_session.get()
        except Exception:  # noqa: BLE001 - ohne MCP-Teil (Tests) keine Sitzung
            sitzung = None
        if sitzung:
            return str(sitzung)
        for s in self._agent.get("sessions") or []:
            if s.get("aktiv") and s.get("session_id"):
                return str(s["session_id"])
        return None

    # =================================================================================================================
    # Projekt
    # =================================================================================================================

    def _versionen_projekt(self, proj: Any, same: bool) -> None:
        if same and self._archiv is not None and self._archiv.projekt == proj.path:
            return
        self._ver_generation += 1
        self._dokumente_ersetzt()
        with self._ver_nt_lock:
            self._ver_dok_auto = self._ver_dok_eigen = False
        archiv = Versionsarchiv(proj.path, log=self._log)
        self._archiv = archiv
        self._ver_speicher = Zwischenspeicher(archiv.ordner)
        self._ver_lauf_nr.clear()
        self._ver_pruef.clear()
        self._ver_aktuell = {}
        self._ver_letzte = None
        self._ver_bereit.clear()
        t0 = time.perf_counter()
        try:
            res = archiv.oeffnen()
            if res.get("uebernommen"):
                self._log(f"[versionen] {res['uebernommen']} alte Stände übernommen in "
                          f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        except (GitFehler, OSError) as exc:
            archiv.verfuegbar = False
            archiv.meldung = f"Versionen nicht verfügbar: {exc}"
            self._log(f"[versionen] {archiv.meldung}")
        finally:
            self._ver_bereit.set()
        self._pool.submit(self._versionen_senden)
        if archiv.verfuegbar:
            self._pool.submit(self._versionen_hintergrund, archiv, self._ver_generation)

    def _versionen_hintergrund(self, archiv: Versionsarchiv, generation: int) -> None:
        """Nach dem Öffnen: einmal am Tag aufräumen, Titel nachziehen, dann fehlende Kennzahlen und Bilder
        nachrechnen."""
        try:
            if archiv.aufraeumen_faellig():
                res = archiv.aufraeumen()
                if res.get("entfernt") and self._ver_speicher is not None:
                    self._ver_speicher.entferne_verwaiste()
                    self._versionen_senden()
        except Exception as exc:  # noqa: BLE001 - Aufräumen darf nie stören
            self._log(f"[versionen] Aufräumen fehlgeschlagen: {exc!r}")
        self._titel_nachziehen(archiv, generation)
        self._nachrechnen_starten(generation)

    # =================================================================================================================
    # Nach dem Lauf, Prüfung, Wer
    # =================================================================================================================

    def _versionen_wer(self, job: Any) -> tuple[str, str | None]:
        src = getattr(job, "source", "")
        if src == "agent":
            return "agent", self._versionen_sitzung()
        if src == "app":
            return "kevin", None
        agent = bool(self._agent.get("connected")) and time.monotonic() - self._agent_seen < AGENT_AKTIV_S
        return ("agent", self._versionen_sitzung()) if agent else ("kevin", None)

    def _versionen_nach_lauf(self, job: Any, result: dict[str, Any]) -> None:
        """Im Auftragsfaden nach einem erfolgreichen Lauf: Version anlegen (bei Änderung) oder die aktuelle
        aktualisieren; Daten, Netze und Vorschaubild im Hintergrund."""
        proj = self._project
        archiv = self._archiv
        if proj is None or str(proj.model) != job.path:
            return
        self._ver_aktiv = time.monotonic()
        teile = [(r.name, r.key, r.header, r.payload) for r in self.scene.records() if not r.name.startswith("Skizze/")]
        with self._lock:
            bom = self._bom
        self._ver_aktuell = {"run": job.run, "params": dict(result.get("params") or {}), "bom": bom}
        if archiv is None or archiv.projekt != proj.path:
            return
        self._ver_bereit.wait(60)
        if not archiv.verfuegbar:
            try:
                proj.save_version(job.code)  # ohne Git wie bisher: model.py je Lauf
            except OSError as exc:
                result.setdefault("warnings", []).append(f"Version nicht gespeichert: {exc}")
            return
        try:
            jetzt = proj.model.read_text(encoding="utf-8")
        except OSError:
            jetzt = None
        if jetzt is not None and hashlib.sha1(jetzt.encode("utf-8")).hexdigest()[:12] != job.file_hash:
            return  # model.py ist schon weiter; der nächste Lauf legt die Version an
        wer, sitzung = self._versionen_wer(job)
        t0 = time.perf_counter()
        with self._ver_nt_lock:
            nt = self._ver_nachtrag
            nachtrag = (int(nt["nr"]), str(nt["commit"])) if nt else None
            # nur von Kev CAD angelegte Dokumente offen: die Version führt Kev CAD, nicht der Auslöser des Laufs
            auto = self._ver_dok_auto and not self._ver_dok_eigen
        try:
            v, neu = archiv.nach_lauf(wer=wer, sitzung=sitzung, lauf=job.run, nachtrag=nachtrag,
                                      wer_dokumente="kevcad" if auto else None)
        except (GitFehler, OSError) as exc:
            result.setdefault("warnings", []).append(f"Version nicht angelegt: {exc}")
            self._log(f"[versionen] Version nicht angelegt: {exc}")
            return
        if neu:
            with self._ver_nt_lock:
                self._ver_dok_auto = self._ver_dok_eigen = False
        self._nachtrag_merken(job, v, neu)
        if v is None:
            return
        ms = (time.perf_counter() - t0) * 1000
        if job.params:
            # Lauf mit überschriebenen Parametern (Agent, Regler der App): zeigt nicht den Stand der Dateien. Die
            # Version bekommt seine Daten nicht; fehlen ihr welche, rechnet die Nachberechnung sie aus den Dateien.
            self._ver_pruef.pop(job.run, None)
            if neu:
                self._versionen_titel(archiv, v, None)
                self._nachrechnen_anstossen()
            titel, _, _ = archiv.titel_von(v)
            result["version"] = {"nr": v.nr, "neu": neu, "ms": round(ms, 1), "titel": titel,
                                 "titel_auto": archiv.meta_von(v.nr).get("titel_auto")}
            self._pool.submit(self._versionen_senden)
            return
        self._ver_lauf_nr[job.run] = v.nr
        if len(self._ver_lauf_nr) > 500:
            for k in sorted(self._ver_lauf_nr)[:250]:
                self._ver_lauf_nr.pop(k, None)
        check = self._ver_pruef.pop(job.run, None)
        daten = daten_aus_teilen([(n, k, h) for n, k, h, _ in teile], bom=bom, params=result.get("params"),
                                 pruefung=check, schritte=result.get("steps"))
        werte: dict[str, Any] = {"kennzahlen": daten["kennzahlen"], "params": daten["params"], "lauf": job.run,
                                 "nachberechnung": None}
        if check is not None:
            werte["pruefung"] = pruef_kurz(check)
        archiv.aktualisiere(v.nr, **werte)
        t1 = time.perf_counter()
        vor = archiv.version_von_commit(v.eltern, v.zweig)
        if neu or archiv.titel_veraltet(v, vor, daten_da=vor is None or self._hat_titel_daten(vor.nr)):
            self._versionen_titel(archiv, v, daten, vor=vor)
        self._ver_letzte = (v.nr, daten)
        titel, _, _ = archiv.titel_von(v)
        result["version"] = {"nr": v.nr, "neu": neu, "ms": round(ms, 1), "titel": titel,
                             "titel_auto": archiv.meta_von(v.nr).get("titel_auto"),
                             "titel_ms": round((time.perf_counter() - t1) * 1000, 1)}
        if neu:
            self._log(f"[versionen] V{v.nr} angelegt ({titel}, {ms:.0f} ms)")
        meta = archiv.meta_von(v.nr)
        bild = neu and (time.time() - self._ver_letztes_bild >= BILD_ABSTAND_S or bool(meta.get("meilenstein")))
        bild = bild or not meta.get("bild")
        self._pool.submit(self._versionen_ablegen, archiv, v.nr, teile, daten, bild)

    def _versionen_ablegen(self, archiv: Versionsarchiv, nr: int, teile: list, daten: dict[str, Any],
                           bild: bool) -> None:
        speicher = self._ver_speicher
        try:
            if speicher is not None and archiv is self._archiv:
                speicher.speichere_daten(nr, daten)
                for name, key, header, payload in teile:
                    if key:
                        speicher.speichere_netz(key, header, payload)
                speicher.begrenze()
            if bild:
                self._versionen_bild(archiv, nr, [(h, p) for _, _, h, p in teile])
        except Exception as exc:  # noqa: BLE001
            self._log(f"[versionen] Zwischenspeicher V{nr}: {exc!r}")
        self._versionen_senden()

    def _versionen_pruefung(self, check: dict[str, Any]) -> None:
        """CHECK_DONE: Prüfstand an die Version des Laufs hängen (oder merken, bis sie da ist)."""
        if check.get("state") not in ("done", "failed"):
            return
        run = int(check.get("run") or 0)
        archiv = self._archiv
        nr = self._ver_lauf_nr.get(run)
        if nr is None:
            if run >= SCHATTEN_RUN_BASIS:
                return
            self._ver_pruef[run] = check
            if len(self._ver_pruef) > 20:
                for k in sorted(self._ver_pruef)[:10]:
                    self._ver_pruef.pop(k, None)
            return
        if archiv is None or not archiv.verfuegbar:
            return
        try:
            archiv.aktualisiere(nr, pruefung=pruef_kurz(check))
            m = archiv.meta_von(nr)
            if m.get("kennzahlen"):
                archiv.aktualisiere(nr, kennzahlen={**m["kennzahlen"], **pruef_kurz(check)})
            speicher = self._ver_speicher
            if speicher is not None:
                d = speicher.lade_daten(nr)
                if d is not None:
                    d["pruefung"] = pruef_daten(check)
                    speicher.speichere_daten(nr, d)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[versionen] Prüfstand V{nr}: {exc!r}")
        self._pool.submit(self._versionen_senden)

    # =================================================================================================================
    # Dokumente: Hintergrundrechnung in die Version des Laufs nachtragen (Modulbeschreibung)
    # =================================================================================================================

    def _nachtrag_merken(self, job: Any, v: Version | None, neu: bool) -> None:
        """Nach der Entscheidung über die Version: wer die Ergebnisse der Hintergrundrechnung aufnimmt."""
        with self._ver_nt_lock:
            nt = self._ver_nachtrag
            if v is None:
                self._ver_nachtrag = None
            elif neu:
                self._ver_nachtrag = None if job.params else {"nr": v.nr, "commit": v.commit, "lauf": job.run}
            elif nt is not None and nt.get("commit") == v.commit:
                if not job.params:  # gleicher Stand: die Rechnung dieses Laufs ersetzt die ältere
                    nt["lauf"] = job.run
            else:
                self._ver_nachtrag = None

    def _lauf_aktuell(self, run: int | None) -> bool:
        """Darf die Hintergrundrechnung von Lauf ``run`` (Blätter, Bauplan) noch speichern? Nur, solange kein neuerer
        Lauf begonnen hat und die Dateien seitdem nicht ersetzt wurden (Wiederherstellen, Variante, anderes Projekt);
        sonst gehörte ihr Ergebnis zu einem Stand, den es nicht mehr gibt. ``None``: immer (Aufrufe von Kevin und dem
        Agenten)."""
        if run is None:
            return True
        with self._lock:
            return self._run_no == run and run > self._ver_dok_sperre

    def _dokumente_ersetzt(self) -> None:
        """Die Projektdateien wurden ersetzt: laufende Hintergrundrechnungen speichern nicht mehr."""
        with self._lock:
            self._ver_dok_sperre = self._run_no
        with self._ver_nt_lock:
            self._ver_nachtrag = None

    def _versionen_dokumente_bearbeitet(self) -> None:
        """Kevin oder der Agent ändert ein Blatt oder den Bauplan selbst (zeichnung/laufzeit.py, bauplan/dienst.py):
        eine eigene Änderung, die mit dem nächsten Lauf eine eigene Version wird, nicht in die letzte wandert."""
        with self._ver_nt_lock:
            self._ver_nachtrag = None
            self._ver_dok_eigen = True

    def _versionen_dokumente_automatisch(self) -> None:
        """Kev CAD hat Dokumente von sich aus angelegt (der erste Bauplan, wenn die App oder der Agent ihn ansehen
        will): Das ist keine Änderung von Kevin. Sie gehört zur aktuellen Version, deren Stand sie beschreibt, und wird
        dort nachgetragen (wie die Hintergrundrechnung nach einem Lauf), wenn das erlaubt ist (Spitze, kein
        Meilenstein, keine eigene Bearbeitung offen). Sonst führt Kev CAD die nächste Version, die nur Dokumente
        ändert, statt Kevin."""
        archiv = self._archiv
        if archiv is None or not archiv.verfuegbar:
            return
        with self._ver_nt_lock:
            self._ver_dok_auto = True
            eigen = self._ver_dok_eigen

        def nachtragen() -> None:
            if eigen or archiv is not self._archiv or self._closed:
                return
            try:
                v = archiv.aktuelle()
                neu = archiv.dokumente_nachtragen(v.nr, v.commit) if v is not None else None
            except (GitFehler, OSError) as exc:
                self._log(f"[versionen] Bauplan nicht nachgetragen: {exc}")
                return
            if neu is None:
                return
            with self._ver_nt_lock:
                if not self._ver_dok_eigen:
                    self._ver_dok_auto = False
            self._log(f"[versionen] V{neu.nr}: von Kev CAD angelegte Dokumente nachgetragen")
            self._versionen_senden()

        try:
            self._pool.submit(nachtragen)
        except RuntimeError:  # Laufzeit wird beendet
            pass

    def _versionen_dokumente_nach_lauf(self, job: Any, hintergrund: list[Any]) -> None:
        """Im Auftragsfaden, gleich nach dem Start der Hintergrundrechnung von ``job`` (Futures von Blättern und
        Bauplan; ihr Ergebnis False heißt: nicht alles gespeichert, weil ein neuerer Lauf begann). Sind alle fertig und
        gehört ihr Ergebnis noch zur Version dieses Laufs, wird nachgetragen."""
        archiv = self._archiv
        with self._ver_nt_lock:
            nt = self._ver_nachtrag
            if job.params or nt is None or nt.get("lauf") != job.run or archiv is None:
                return
        offen = [f for f in hintergrund if f is not None]
        if not offen:
            self._nachtrag_starten(archiv, job.run, True)
            return
        zustand = {"rest": len(offen), "voll": True}
        sperre = threading.Lock()

        def fertig(f: Any) -> None:
            try:
                ok = f.cancelled() or f.result() is not False
            except Exception:  # noqa: BLE001 - eine gescheiterte Rechnung speichert nichts mehr
                ok = True
            with sperre:
                zustand["voll"] = bool(zustand["voll"] and ok)
                zustand["rest"] -= 1
                letzte = zustand["rest"] == 0
            if letzte:
                self._nachtrag_starten(archiv, job.run, bool(zustand["voll"]))

        for f in offen:
            f.add_done_callback(fertig)

    def _nachtrag_starten(self, archiv: Versionsarchiv, lauf: int, voll: bool) -> None:
        try:
            self._pool.submit(self._versionen_nachtragen, archiv, lauf, voll)
        except RuntimeError:  # Laufzeit wird beendet
            pass

    def _versionen_nachtragen(self, archiv: Versionsarchiv, lauf: int, voll: bool) -> None:
        with self._ver_nt_lock:
            nt = self._ver_nachtrag
            if nt is None or nt.get("lauf") != lauf or archiv is not self._archiv or self._closed:
                return
            if not voll:
                return  # ein neuerer Lauf begann während der Rechnung; ein Lauf gleichen Stands übernimmt
            self._ver_nachtrag = None
        t0 = time.perf_counter()
        try:
            v = archiv.dokumente_nachtragen(int(nt["nr"]), str(nt["commit"]))
        except (GitFehler, OSError) as exc:
            self._log(f"[versionen] Dokumente nicht nachgetragen: {exc}")
            return
        if v is not None:
            self._log(f"[versionen] V{v.nr}: Blätter und Bauplan aus Lauf {lauf} nachgetragen "
                      f"({(time.perf_counter() - t0) * 1000:.0f} ms)")
            self._versionen_senden()

    def versionen_info(self, run: int | None = None) -> dict[str, Any] | None:
        """Für das Schriftfeld der Blätter (zeichnung/laufzeit.py): die Version, zu der Lauf ``run`` gehört (sonst die
        aktuelle). {"version": "V12" bzw. "V12 (Flacher Rand)" in einer Variante, "nr", "variante",
        "meilenstein": Titel oder None}; None ohne Versionen."""
        archiv = self._archiv
        if archiv is None or not archiv.verfuegbar or not self._ver_bereit.is_set():
            return None
        try:
            liste = archiv.versionen()
            zweig = archiv.git.zweig() if liste else HAUPT
        except (GitFehler, OSError):
            return None
        if not liste:
            return None
        v = liste[0]
        nr = self._ver_lauf_nr.get(run) if run is not None else None
        if nr is not None and nr != v.nr:
            v = next((w for w in liste if w.nr == nr), v)
        variante = None
        if zweig != HAUPT:
            variante = str((archiv.meta.get("varianten", {}).get(zweig) or {}).get("name") or zweig)
        ms = (archiv.meta.get("versionen", {}).get(str(v.nr)) or {}).get("meilenstein") or {}
        return {"version": f"V{v.nr}" + (f" ({variante})" if variante else ""), "nr": v.nr, "variante": variante,
                "meilenstein": str(ms.get("titel") or "").strip() or None}

    # =================================================================================================================
    # Titel (titel.py, PLAN-VERSIONEN.md „Titel“)
    # =================================================================================================================

    def _titel_daten(self, nr: int | None) -> dict[str, Any] | None:
        if nr is None:
            return None
        letzte = self._ver_letzte
        if letzte is not None and letzte[0] == nr:
            return letzte[1]
        speicher = self._ver_speicher
        return speicher.lade_daten(nr) if speicher is not None else None

    def _hat_titel_daten(self, nr: int) -> bool:
        letzte = self._ver_letzte
        speicher = self._ver_speicher
        return (letzte is not None and letzte[0] == nr) or (speicher is not None and speicher.hat_daten(nr))

    def _versionen_titel(self, archiv: Versionsarchiv, v: Version, daten: dict[str, Any] | None, *,
                         vor: Version | None | bool = False) -> dict[str, Any] | None:
        """Automatischen Titel von ``v`` berechnen (``daten``: die eigenen, None = aus dem Zwischenspeicher)."""
        try:
            if vor is False:
                vor = archiv.version_von_commit(v.eltern, v.zweig)
            vorgaenger = vor if isinstance(vor, Version) else None
            alt = self._titel_daten(vorgaenger.nr) if vorgaenger else None
            neu = daten if daten is not None else self._titel_daten(v.nr)
            return archiv.titel_berechnen(v, vorgaenger, alt, neu)
        except Exception as exc:  # noqa: BLE001 - ein Titel darf nie einen Lauf stören
            self._log(f"[versionen] Titel V{v.nr}: {exc!r}")
            return None

    def _titel_nachziehen(self, archiv: Versionsarchiv | None, generation: int | None = None) -> int:
        """Automatische Titel aller Versionen nachziehen, wo sie fehlen oder veraltet sind: beim Öffnen (auch bei
        bestehenden Archiven mit „Übernommener Stand“), nach jeder Nachberechnung und nach Sicherungen. Schreibt nur
        die Metadaten; Kevins Meilensteine und Titel des Agenten bleiben unberührt."""
        if archiv is None or not archiv.verfuegbar:
            return 0
        try:
            alle = archiv.alle_versionen()
        except (GitFehler, OSError) as exc:
            self._log(f"[versionen] Titel nicht nachgezogen: {exc}")
            return 0
        nach_commit = {v.commit: v for v in alle.values()}
        geladen: dict[int, dict[str, Any] | None] = {}

        def daten(nr: int) -> dict[str, Any] | None:
            if nr not in geladen:
                if len(geladen) > 4:
                    geladen.clear()
                geladen[nr] = self._titel_daten(nr)
            return geladen[nr]

        hat = self._hat_titel_daten
        n = 0
        t0 = gesendet = time.monotonic()
        for v in sorted(alle.values(), key=lambda x: x.nr):
            if self._closed or archiv is not self._archiv or (generation is not None
                                                              and generation != self._ver_generation):
                break
            vor = nach_commit.get(v.eltern) if v.eltern else None
            if not archiv.titel_veraltet(v, vor, daten_da=hat(v.nr) and (vor is None or hat(vor.nr))):
                continue
            try:
                archiv.titel_berechnen(v, vor, daten(vor.nr) if vor else None, daten(v.nr))
                n += 1
            except Exception as exc:  # noqa: BLE001
                self._log(f"[versionen] Titel V{v.nr}: {exc!r}")
            if time.monotonic() - gesendet > 3.0:
                self._versionen_senden()
                gesendet = time.monotonic()
        if n:
            self._log(f"[versionen] {n} Titel nachgezogen in {(time.monotonic() - t0) * 1000:.0f} ms")
            self._versionen_senden()
        return n

    def _versionen_agent_titel(self, result: dict[str, Any], titel: str | None) -> dict[str, Any]:
        """``run(titel=…)``: Titel des Agenten an die Version dieses Laufs. Ohne neue Version (Dateien unverändert)
        an die aktuelle, wenn sie ein junger Lauf ohne eigenen Agententitel ist (der Auto-Lauf nach dem Speichern hat
        die Version schon angelegt); sonst bleibt alles, wie es ist, und ``hinweis`` sagt es."""
        titel = " ".join(str(titel or "").split())
        archiv = self._archiv
        if not titel or archiv is None or not archiv.verfuegbar or not result.get("ok"):
            return result
        info = dict(result.get("version") or {})
        if not info.get("nr"):
            info["hinweis"] = "Keine Version angelegt: Titel nicht vergeben."
            return {**result, "version": info}
        nr = int(info["nr"])
        passt = bool(info.get("neu"))
        if not passt:
            v = archiv.aktuelle()
            m = archiv.meta.get("versionen", {}).get(str(nr), {}) or {}
            passt = (v is not None and v.nr == nr and v.quelle == "lauf" and not m.get("titel_agent")
                     and time.time() - v.ts < AGENT_TITEL_ALTER_S)
        if passt:
            archiv.titel_agent(nr, titel)
            info["titel"] = archiv.meta_von(nr).get("titel_agent")
            info["titel_auto"] = archiv.meta_von(nr).get("titel_auto")
            info["titel_vergeben"] = True
            self._pool.submit(self._versionen_senden)
        else:
            info["hinweis"] = f"Dateien unverändert seit V{nr}: keine neue Version, Titel nicht vergeben."
        return {**result, "version": info}

    def _nachrechnen_anstossen(self) -> None:
        t = self._ver_nachrechnen
        if t is None or not t.is_alive():
            self._nachrechnen_starten(self._ver_generation)

    # =================================================================================================================
    # Nachrichten an die App
    # =================================================================================================================

    def _versionen_nachricht(self, reply_to: str | None = None) -> dict[str, Any] | None:
        proj, archiv = self._project, self._archiv
        if proj is None or archiv is None:
            return None
        try:
            data = archiv.liste(limit=LISTE_LIMIT)
            data["ungesichert"] = archiv.ungesichert()
        except (GitFehler, OSError) as exc:
            data = {"verfuegbar": False, "meldung": f"Versionen nicht lesbar: {exc}", "versionen": [], "gruppen": [],
                    "varianten": [], "variante": HAUPT, "ungesichert": False}
        msg = {"type": "VERSIONEN", "projekt": str(proj.path), **data}
        if reply_to:
            msg["reply_to"] = reply_to
        return msg

    def _versionen_senden(self, reply_to: str | None = None) -> None:
        if not self._link.connected and not reply_to:
            return
        try:
            msg = self._versionen_nachricht(reply_to)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[versionen] Liste nicht gebaut: {exc!r}")
            return
        if msg is not None:
            self._send_app(msg)

    def _versionen_on_connect(self, conn: Any) -> None:
        if self._archiv is None:
            return

        def senden() -> None:
            self._ver_bereit.wait(30)
            self._versionen_senden()

        self._pool.submit(senden)

    def _versionen_bild(self, archiv: Versionsarchiv, nr: int, teile: list[tuple[dict[str, Any], bytes]]) -> bool:
        """Vorschaubild über die App rendern (VERSION_BILD_REQ mit den Netzen) und ablegen."""
        if not self._link.connected or not teile:
            return False
        eintraege = []
        for header, payload in teile:
            try:
                eintraege.append(({"teil": header.get("name"), "farbe": header.get("color")}, netz(header, payload)))
            except Exception:  # noqa: BLE001 - fehlerhafte Geometrie auslassen
                continue
        return self._versionen_bild_netze(archiv, nr, eintraege)

    def _versionen_bild_netze(self, archiv: Versionsarchiv, nr: int, eintraege: list) -> bool:
        from kevcad_kernel.protocol import pack_netze

        if not self._link.connected or not eintraege:
            return False
        koepfe, nutzlast = pack_netze(eintraege)
        req = {"type": "VERSION_BILD_REQ", "nr": nr, "width": BILD_BREITE, "height": BILD_HOEHE, "view": "iso",
               "teile": koepfe}
        reply, png, error = self._request(req, 30.0, nutzlast)
        if error or not reply.get("ok") or not png:
            self._log(f"[versionen] Vorschaubild V{nr}: {error or reply.get('message') or 'kein Bild'}")
            return False
        ziel = archiv.ordner / "bilder" / f"{nr}.png"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(png)
        archiv.aktualisiere(nr, bild=f"bilder/{nr}.png")
        self._ver_letztes_bild = time.time()
        return True

    # =================================================================================================================
    # Lauf ohne Live-Aufbau (Schatten)
    # =================================================================================================================

    def _schatten_nachricht(self, job: Any, kind: str, header: dict[str, Any], payload: bytes) -> None:
        if kind == "PART" and header.get("run") == job.run:
            app_len = int(header.get("app_len", 0))
            app = dict(header.get("app") or {})
            job.teile.append((str(header.get("name")), str(header.get("key", "")), app, payload[:app_len]))

    def _schatten_job(self, job: Any) -> dict[str, Any]:
        err = self._ensure_worker()
        if err:
            return {"ok": False, "error": err}
        deviation, angular = self._precision()
        job.run = SCHATTEN_RUN_BASIS + next(self._ver_schatten)
        job.generation = self._worker.generation
        job.started = time.perf_counter()
        self._set_state("busy", job.params.get("_text") or "Version wird nachgerechnet")
        from kevcad_kernel.project import _read_settings

        settings, _ = _read_settings(Path(job.path).parent)
        regel = settings.get("inventar_regel", True) is not False
        sent = self._worker.send({"type": "RUN", "run": job.run, "path": job.path, "code": job.code, "params": {},
                                  "slow_ms": 0, "deviation": deviation, "angular": angular,
                                  "catalog": self._catalog_dirs(), "inventar_regel": regel, "pruefen": False,
                                  "schatten": True})
        finished = sent and job.finished.wait(job.timeout_s)
        final = job.final or {}
        ms = int((time.perf_counter() - job.started) * 1000)
        if not finished or final.get("type") in ("CRASH", "CLOSED"):
            if not finished:
                self._worker.kill()
            if final.get("type") != "CLOSED":
                self._restart_worker_async()
            self._set_state("ready", "bereit")
            return {"ok": False, "error": "Zeitlimit überschritten" if not finished else "Rechenprozess abgestürzt",
                    "ms": ms}
        self._set_state("ready", "bereit")
        if final.get("type") != "RUN_DONE":
            e = final.get("error") or {}
            return {"ok": False, "error": e.get("message") or "Lauf fehlgeschlagen", "line": e.get("line"), "ms": ms}
        shown = list(final.get("shown") or [])
        reihen = {name: i for i, name in enumerate(shown)}
        letzte: dict[str, tuple] = {}
        for t in job.teile:
            letzte[t[0]] = t  # gleicher Name mehrfach gezeigt: der letzte gilt
        teile = sorted((t for n, t in letzte.items() if n in reihen and not n.startswith("Skizze/")),
                       key=lambda t: reihen[t[0]])
        return {"ok": True, "teile": teile, "bom": final.get("bom"), "params": dict(final.get("params") or {}),
                "steps": list(final.get("steps") or []), "ms": ms}

    def _schatten_lauf(self, archiv: Versionsarchiv, v: Version, timeout_s: float = 300.0,
                       hintergrund: bool = False) -> dict[str, Any]:
        """Version ``v`` in einem eigenen Ordner rechnen, ohne die App oder die Szene zu berühren. ``hintergrund``:
        im eigenen, niedriger priorisierten Prozess (Nachberechnung), sonst im Rechenprozess der Laufzeit zwischen den
        Läufen (Vergleich: dessen Tessellierungsspeicher macht es schnell)."""
        from kevcad_kernel.runtime import Job

        ordner = archiv.ordner / "lauf" / f"{v.nr}-{next(self._ver_schatten)}"
        try:
            shutil.rmtree(ordner, ignore_errors=True)
            archiv.materialisiere(v, ordner)
            model = ordner / "model.py"
            code = model.read_text(encoding="utf-8")
        except (OSError, GitFehler) as exc:
            shutil.rmtree(ordner, ignore_errors=True)
            return {"ok": False, "error": f"Version V{v.nr} nicht auspackbar: {exc}"}
        if hintergrund:
            from kevcad_kernel.project import _read_settings
            from kevcad_kernel.versionen.hintergrund import HintergrundRechner

            if self._ver_rechner is None:
                self._ver_rechner = HintergrundRechner(log=self._log)
            settings, _ = _read_settings(ordner)
            deviation, angular = self._precision()
            try:
                return self._ver_rechner.rechne(
                    run=SCHATTEN_RUN_BASIS + next(self._ver_schatten), path=str(model), code=code,
                    inventar_regel=settings.get("inventar_regel", True) is not False, deviation=deviation,
                    angular=angular, catalog=self._catalog_dirs(), timeout_s=timeout_s)
            finally:
                shutil.rmtree(ordner, ignore_errors=True)
        job = Job(kind="schatten", code=code, source="versionen", timeout_s=timeout_s, path=str(model),
                  params={"_text": f"V{v.nr} wird nachgerechnet"})
        self._enqueue(job)
        job.done.wait()
        shutil.rmtree(ordner, ignore_errors=True)
        return job.result or {"ok": False, "error": "ohne Ergebnis"}

    def _versionen_daten(self, archiv: Versionsarchiv, v: Version, timeout_s: float = 300.0,
                         hintergrund: bool = False) -> tuple[dict[str, Any] | None, dict[str, dict], str | None]:
        """Daten einer Version für den Vergleich: aus dem Zwischenspeicher, sonst neu gerechnet. Rückgabe
        (daten, netze je Formschlüssel aus einem neuen Lauf, Fehlertext)."""
        speicher = self._ver_speicher
        d = speicher.lade_daten(v.nr) if speicher else None
        if d is not None and speicher is not None and speicher.hat_alle_netze(d):
            return d, {}, None
        res = self._schatten_lauf(archiv, v, timeout_s, hintergrund=hintergrund)
        if not res.get("ok"):
            msg = res.get("error") or "Lauf fehlgeschlagen"
            if res.get("line"):
                msg += f" (Zeile {res['line']})"
            return d, {}, f"V{v.nr} ließ sich nicht neu rechnen: {msg}"
        teile = res["teile"]
        alt_pruef = (d or {}).get("pruefung")
        daten = daten_aus_teilen([(n, k, h) for n, k, h, _ in teile], bom=res.get("bom"), params=res.get("params"),
                                 schritte=res.get("steps"))
        if alt_pruef:
            daten["pruefung"] = alt_pruef
        netze = {k: (h, p) for _, k, h, p in teile if k}
        if speicher is not None:
            try:
                speicher.speichere_daten(v.nr, daten)
                for k, (h, p) in netze.items():
                    speicher.speichere_netz(k, h, p)
                speicher.begrenze()
            except OSError as exc:
                self._log(f"[versionen] Zwischenspeicher V{v.nr}: {exc!r}")
        m = archiv.meta_von(v.nr)
        if not m.get("kennzahlen"):
            k = kennzahlen(daten["teile"], daten.get("stueckliste"))
            archiv.aktualisiere(v.nr, kennzahlen=k, params=daten["params"], nachberechnung=None)
        return daten, netze, None

    def _versionen_aktuell_daten(self) -> dict[str, Any]:
        teile = [(r.name, r.key, r.header) for r in self.scene.records() if not r.name.startswith("Skizze/")]
        akt = self._ver_aktuell
        with self._lock:
            bom = self._bom
        check, _ = self._pruef.letztes()
        return daten_aus_teilen(teile, bom=akt.get("bom", bom), params=akt.get("params") or {}, pruefung=check)

    # =================================================================================================================
    # Nachberechnung (alte Stände ohne Kennzahlen und Vorschaubild)
    # =================================================================================================================

    def _nachrechnen_starten(self, generation: int) -> None:
        # ein noch laufender Faden eines früheren Projekts endet von selbst (andere Generation)
        t = threading.Thread(target=self._nachrechnen, args=(generation,), name="kevcad-versionen-nach", daemon=True)
        self._ver_nachrechnen = t
        t.start()

    def _ruhig(self) -> bool:
        """Kein Lauf in der Schlange und der letzte ist ein paar Sekunden her (die Nachberechnung rechnet in einem
        eigenen Prozess, soll den Live-Aufbau aber nicht ausbremsen)."""
        with self._jobs_cond:
            leer = not self._jobs and self._current is None
        return leer and time.monotonic() - self._ver_aktiv > NACHRECHNEN_RUHE_S

    def _nachrechnen(self, generation: int) -> None:
        """Fehlende Kennzahlen und Vorschaubilder (übernommene Stände, Versionen aus der Zeit ohne App) nachrechnen,
        neueste zuerst, nur wenn der Kernel sonst nichts zu tun hat."""
        gesendet = time.monotonic()
        versucht: set[int] = set()  # je Öffnen des Projekts ein Versuch (der Katalog kann sich inzwischen ändern)
        while not self._closed and generation == self._ver_generation:
            archiv = self._archiv
            if archiv is None or not archiv.verfuegbar:
                return
            offen = None
            for v in archiv.versionen():
                if v.nr in versucht:
                    continue
                m = archiv.meta.get("versionen", {}).get(str(v.nr), {})
                if not m.get("kennzahlen") or (not m.get("bild") and self._link.connected):
                    offen = v
                    break
            if offen is None:
                self._versionen_senden()
                rechner, self._ver_rechner = self._ver_rechner, None
                if rechner is not None:
                    rechner.stop()  # Speicher freigeben, bis wieder etwas nachzurechnen ist
                return
            while not self._ruhig():
                if self._closed or generation != self._ver_generation:
                    return
                time.sleep(0.5)
            versucht.add(offen.nr)
            try:
                daten, netze, fehler = self._versionen_daten(archiv, offen, hintergrund=True)
                if generation != self._ver_generation:
                    return
                if fehler or daten is None:
                    archiv.aktualisiere(offen.nr, nachberechnung=fehler or "nicht nachrechenbar")
                    continue
                self._titel_nachziehen(archiv, generation)  # diese Version und ihre Nachfolger jetzt aus den Daten
                if not archiv.meta_von(offen.nr).get("bild") and self._link.connected:
                    eintraege = self._netze_fuer_bild(daten, netze)
                    if not self._versionen_bild_netze(archiv, offen.nr, eintraege) and self._link.connected:
                        archiv.aktualisiere(offen.nr, nachberechnung="Vorschaubild nicht erzeugt")
                    elif archiv.meta_von(offen.nr).get("nachberechnung"):
                        archiv.aktualisiere(offen.nr, nachberechnung=None)
            except Exception as exc:  # noqa: BLE001
                self._log(f"[versionen] Nachberechnung V{offen.nr}: {exc!r}")
                archiv.aktualisiere(offen.nr, nachberechnung=f"{type(exc).__name__}: {exc}")
            if time.monotonic() - gesendet > 3.0:
                self._versionen_senden()
                gesendet = time.monotonic()

    def _netze_fuer_bild(self, daten: dict[str, Any], netze: dict[str, tuple]) -> list:
        speicher = self._ver_speicher
        out = []
        for t in daten.get("teile") or []:
            key = t.get("key")
            n = None
            if key in netze:
                h, p = netze[key]
                try:
                    n = netz(h, p)
                except Exception:  # noqa: BLE001
                    n = None
            elif speicher is not None and key:
                n = speicher.lade_netz(key)
            if n is not None:
                out.append(({"teil": t["name"], "farbe": t.get("farbe")}, n))
        return out

    # =================================================================================================================
    # KernelService: Versionen
    # =================================================================================================================

    def _archiv_oder_fehler(self) -> Versionsarchiv | dict[str, Any]:
        if self._project is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        archiv = self._archiv
        if archiv is None:
            return {"ok": False, "error": "Versionen werden noch geladen."}
        self._ver_bereit.wait(60)
        if not archiv.verfuegbar:
            return {"ok": False, "error": archiv.meldung}
        return archiv

    def _aufgabe(self, fn, timeout_s: float = 120.0) -> Any:
        """``fn`` im Auftragsfaden ausführen (zwischen Läufen) und das Ergebnis liefern."""
        from kevcad_kernel.runtime import Job

        job = Job(kind="aufgabe", code="", source="versionen", timeout_s=timeout_s, fn=fn)
        self._enqueue(job)
        if not job.done.wait(timeout_s + 600):
            raise VersionsFehler("Zeitlimit beim Warten auf den Kernel")
        if isinstance(job.result, dict) and job.result.get("_ausnahme") is not None:
            raise job.result["_ausnahme"]
        if isinstance(job.result, dict) and job.result.get("ok") is False and job.result.get("error"):
            raise VersionsFehler(str(job.result["error"]))
        return job.result

    def versionen(self, limit: int | None = 50, variante: str | None = None) -> dict[str, Any]:
        archiv = self._archiv_oder_fehler()
        if isinstance(archiv, dict):
            return archiv
        try:
            zweig = archiv.zweig_von(variante) if variante else None
            data = archiv.liste(zweig, limit=limit)
            data["ungesichert"] = archiv.ungesichert()
        except (VersionsFehler, GitFehler) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **data}

    def _nach_aenderung_rechnen(self, source: str, warten: bool, timeout_s: float) -> dict[str, Any] | None:
        job = self._submit_run(None, 0, self.run_timeout_s, source=source)
        if isinstance(job, dict) or not warten:
            return job if isinstance(job, dict) else None
        job.done.wait(timeout_s)
        res = job.result or {}
        out = {"ok": bool(res.get("ok")), "run": res.get("run"), "teile": len(res.get("parts") or []),
               "duration_ms": res.get("duration_ms")}
        if res.get("error"):
            e = res["error"]
            out["error"] = e.get("message") if isinstance(e, dict) else str(e)
        if res.get("ok") and job.run:
            from kevcad_kernel.pruefung.anbindung import fuer_ergebnis

            check = fuer_ergebnis(self._pruef.warte(job.run, min(self.pruef_warten_s, timeout_s)))
            if check is not None:
                out["pruefung"] = {k: check.get(k) for k in ("state", "zusammenfassung", "zaehler")}
        return out

    def version_wiederherstellen(self, version: Any, *, wer: str = "agent", warten: bool = True,
                                 timeout_s: float = 300.0) -> dict[str, Any]:
        archiv = self._archiv_oder_fehler()
        if isinstance(archiv, dict):
            return archiv
        sitzung = self._versionen_sitzung() if wer == "agent" else None
        t0 = time.perf_counter()

        def aufgabe() -> dict[str, Any]:
            try:
                res = archiv.wiederherstellen(version, wer=wer, sitzung=sitzung)
            except (VersionsFehler, GitFehler) as exc:
                return {"_ausnahme": exc}
            neu = res.get("version")
            if not res.get("unveraendert") and neu is not None:
                # Blätter und Bauplan der alten Version neu zuordnen: das Ergebnis der Hintergrundrechnung des
                # folgenden Laufs gehört in die wiederhergestellte Version (keine zusätzliche Version dafür)
                self._dokumente_ersetzt()
                with self._ver_nt_lock:
                    self._ver_nachtrag = {"nr": neu.nr, "commit": neu.commit, "lauf": None}
            return res

        try:
            res = self._aufgabe(aufgabe)
        except (VersionsFehler, GitFehler) as exc:
            return {"ok": False, "error": str(exc)}
        ms_dateien = (time.perf_counter() - t0) * 1000
        self._pool.submit(self._titel_nachziehen, archiv, self._ver_generation)
        neu, aus, gesichert = res["version"], res["aus"], res["gesichert"]
        out: dict[str, Any] = {"ok": True, "version": neu.nr if neu else None, "aus": aus.nr,
                               "gesichert": gesichert.nr if gesichert else None, "unveraendert": res["unveraendert"],
                               "titel": archiv.version_dict(neu)["titel"] if neu else "", "ms_dateien": round(ms_dateien)}
        self._pool.submit(self._versionen_senden)
        lauf = self._nach_aenderung_rechnen("agent" if wer == "agent" else "app", warten, timeout_s)
        if lauf is not None:
            out["lauf"] = lauf
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        self._log(f"[versionen] wiederhergestellt aus V{aus.nr} → V{out['version']} in {out['ms']} ms")
        return out

    def meilenstein(self, titel: str, notiz: str = "", version: Any = None, *, wer: str = "agent",
                    entfernen: bool = False, ersetzen: bool = False) -> dict[str, Any]:
        """Meilenstein setzen. Kevins eigene Meilensteine bleiben (``geschuetzt``), außer mit ``ersetzen`` auf seinen
        ausdrücklichen Wunsch; der Titel des Agenten steht dann als Titel der Version unter Kevins Meilenstein."""
        archiv = self._archiv_oder_fehler()
        if isinstance(archiv, dict):
            return archiv
        sitzung = self._versionen_sitzung() if wer == "agent" else None

        def aufgabe() -> Any:
            try:
                if entfernen:
                    return archiv.meilenstein_entfernen(version)
                return archiv.meilenstein(version, titel, notiz, wer=wer, sitzung=sitzung, ersetzen=ersetzen)
            except KevinsMeilenstein as exc:
                return {"_geschuetzt": exc}
            except (VersionsFehler, GitFehler) as exc:
                return {"_ausnahme": exc}

        try:
            v = self._aufgabe(aufgabe)
        except (VersionsFehler, GitFehler) as exc:
            return {"ok": False, "error": str(exc)}
        self._pool.submit(self._titel_nachziehen, archiv, self._ver_generation)  # eine Sicherung braucht ihren Titel
        if isinstance(v, dict) and v.get("_geschuetzt") is not None:
            exc = v["_geschuetzt"]
            nr = exc.version.nr
            beschrieben = bool(titel.strip()) and not archiv.meta_von(nr).get("titel_agent")
            if beschrieben:
                archiv.titel_agent(nr, titel)
            self._pool.submit(self._versionen_senden)
            hinweis = f"V{nr} trägt Kevins Meilenstein „{exc.meilenstein.get('titel', '')}“; er bleibt unverändert."
            if beschrieben:
                hinweis += f" „{titel.strip()}“ steht als Titel der Version darunter."
            return {"ok": True, "version": nr, "titel": exc.meilenstein.get("titel", ""),
                    "notiz": exc.meilenstein.get("notiz", ""), "entfernt": False, "geschuetzt": True,
                    "hinweis": hinweis}
        out = {"ok": True, "version": v.nr, "titel": titel, "notiz": notiz, "entfernt": entfernen}
        if not entfernen:
            self._pool.submit(self._meilenstein_bild, archiv, v)
        else:
            self._pool.submit(self._versionen_senden)
        last = self._last_result or {}
        if not entfernen and last and not last.get("ok"):
            out["warnung"] = "Der letzte Lauf ist fehlgeschlagen: der Meilenstein zeigt einen Stand, der nicht rechnet."
        return out

    def _meilenstein_bild(self, archiv: Versionsarchiv, v: Version) -> None:
        """Meilensteine bekommen immer ein Vorschaubild: aktueller Stand aus der Szene, sonst aus dem Speicher."""
        try:
            if archiv.meta_von(v.nr).get("bild"):
                return
            aktuell = archiv.aktuelle()
            if aktuell is not None and aktuell.nr == v.nr and self.scene.records():
                self._versionen_bild(archiv, v.nr, [(r.header, r.payload) for r in self.scene.records()
                                                    if not r.name.startswith("Skizze/")])
            elif self._ver_speicher is not None:
                d = self._ver_speicher.lade_daten(v.nr)
                if d is not None:
                    self._versionen_bild_netze(archiv, v.nr, self._netze_fuer_bild(d, {}))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[versionen] Vorschaubild Meilenstein V{v.nr}: {exc!r}")
        finally:
            self._versionen_senden()

    def variante(self, aktion: str = "liste", name: str | None = None, von: Any = None, neuer_name: str | None = None,
                 *, wer: str = "agent", warten: bool = True, timeout_s: float = 300.0) -> dict[str, Any]:
        archiv = self._archiv_oder_fehler()
        if isinstance(archiv, dict):
            return archiv
        sitzung = self._versionen_sitzung() if wer == "agent" else None
        if aktion == "liste":
            return {"ok": True, "varianten": archiv.varianten()}
        if aktion not in ("anlegen", "wechseln", "umbenennen"):
            return {"ok": False, "error": f"aktion {aktion!r} unbekannt (liste, anlegen, wechseln, umbenennen)"}
        if not name:
            return {"ok": False, "error": "name fehlt"}
        t0 = time.perf_counter()

        def aufgabe() -> Any:
            try:
                if aktion == "anlegen":
                    res = archiv.variante_anlegen(name, von, wer=wer, sitzung=sitzung)
                elif aktion == "wechseln":
                    res = archiv.variante_wechseln(name, wer=wer, sitzung=sitzung)
                else:
                    return archiv.variante_umbenennen(name, neuer_name or "")
            except (VersionsFehler, GitFehler) as exc:
                return {"_ausnahme": exc}
            if not res.get("unveraendert"):
                self._dokumente_ersetzt()  # andere Dateien: laufende Hintergrundrechnungen speichern nicht mehr
            return res

        try:
            res = self._aufgabe(aufgabe)
        except (VersionsFehler, GitFehler) as exc:
            return {"ok": False, "error": str(exc)}
        if res.get("gesichert") is not None:
            self._pool.submit(self._titel_nachziehen, archiv, self._ver_generation)
        out: dict[str, Any] = {"ok": True, "aktion": aktion, "variante": res.get("zweig"), "name": res.get("name")}
        if res.get("gesichert") is not None:
            out["gesichert"] = res["gesichert"].nr
        if isinstance(res.get("von"), Version):
            out["von"] = res["von"].nr
        self._pool.submit(self._versionen_senden)
        if aktion in ("anlegen", "wechseln") and not res.get("unveraendert"):
            lauf = self._nach_aenderung_rechnen("agent" if wer == "agent" else "app", warten, timeout_s)
            if lauf is not None:
                out["lauf"] = lauf
        out["varianten"] = archiv.varianten()
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        return out

    def versionen_vergleichen(self, a: Any, b: Any = None, *, zeigen: bool = True, timeout_s: float = 300.0,
                              reply_to: str | None = None) -> dict[str, Any]:
        """Version ``a`` mit ``b`` vergleichen (``b`` None = aktueller Stand). Mit ``zeigen`` gehen Geisterkörper und
        Unterschiede als VERSION_VERGLEICH an die App (nur mit dem aktuellen Stand als ``b``)."""
        archiv = self._archiv_oder_fehler()
        if isinstance(archiv, dict):
            return archiv
        t0 = time.perf_counter()
        try:
            va = archiv.finde(a)
            aktuell = b is None or str(b).strip().lower() in ("", "aktuell", "jetzt", "head")
            vb = None if aktuell else archiv.finde(b)
        except (VersionsFehler, GitFehler) as exc:
            return {"ok": False, "error": str(exc)}
        hinweise = []
        daten_a, netze_a, fehler_a = self._versionen_daten(archiv, va, timeout_s)
        if aktuell:
            daten_b, netze_b, fehler_b = self._versionen_aktuell_daten(), {}, None
            if not daten_b["teile"]:
                hinweise.append("Aktueller Stand ohne Teile (noch kein erfolgreicher Lauf?)")
        else:
            daten_b, netze_b, fehler_b = self._versionen_daten(archiv, vb, timeout_s)
        for f in (fehler_a, fehler_b):
            if f:
                hinweise.append(f)
        leer = {"teile": [], "params": {}, "stueckliste": None, "pruefung": None, "kennzahlen": {}}
        v = vergleiche(daten_a or leer, daten_b or leer)
        try:
            code = archiv.code_diff(va, vb)
        except GitFehler as exc:
            code = {"dateien": [], "diff": "", "gekuerzt": False, "fehler": str(exc)}
        try:  # Blätter und Bauplan als eigene Gruppe (dokumente.py), nicht im Code
            v["dokumente"] = archiv.dokumente_vergleich(va, vb)
        except GitFehler as exc:
            v["dokumente"] = []
            hinweise.append(f"Dokumente nicht verglichen: {exc}")
        kopf_a = archiv.version_dict(va)
        kopf_b = archiv.version_dict(vb) if vb else {"nr": None, "titel": "Aktueller Stand", "zeit": None}
        out: dict[str, Any] = {
            "ok": True, "a": _kurz(kopf_a), "b": _kurz(kopf_b), "aktuell": aktuell,
            "zusammenfassung": zusammenfassung(v), **v, "code": code, "hinweise": hinweise,
        }
        geister: list = []
        if aktuell and daten_a:
            dreiecke = 0
            speicher = self._ver_speicher
            for name, key, art in geister_auswahl(v, daten_a):
                n = None
                if key in netze_a:
                    try:
                        n = netz(*netze_a[key])
                    except Exception:  # noqa: BLE001
                        n = None
                elif speicher is not None:
                    n = speicher.lade_netz(key)
                if n is None:
                    continue
                dreiecke += len(n["triangles"])
                if dreiecke > MAX_GEISTER_DREIECKE:
                    hinweise.append("Zu viele geänderte Teile: nicht alle als Geisterkörper gezeigt")
                    break
                geister.append(({"teil": name, "art": art}, n))
        out["geister"] = [{"teil": m["teil"], "art": m["art"]} for m, _ in geister]
        out["ms"] = round((time.perf_counter() - t0) * 1000)
        if zeigen or reply_to:
            self._vergleich_senden(out, geister, reply_to)
        return out

    def _vergleich_senden(self, out: dict[str, Any], geister: list, reply_to: str | None) -> None:
        from kevcad_kernel.protocol import pack_netze

        koepfe, nutzlast = pack_netze(geister)
        msg = {"type": "VERSION_VERGLEICH", **{k: v for k, v in out.items() if k not in ("ok", "geister")},
               "geometrie": koepfe}
        if reply_to:
            msg["reply_to"] = reply_to
        self._send_app(msg, nutzlast)

    # =================================================================================================================
    # App → Kernel
    # =================================================================================================================

    def _versionen_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in ("VERSIONEN_REQ", "VERSION_RESTORE", "VERSION_COMPARE", "VERSION_MILESTONE", "VARIANT"):
            return False
        self._pool.submit(self._versionen_app_anfrage, kind, header)
        return True

    def _versionen_app_anfrage(self, kind: str, header: dict[str, Any]) -> None:
        rid = header.get("id")

        def ack(res: dict[str, Any], text: str = "") -> None:
            self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),
                            "message": text if res.get("ok") else str(res.get("error") or "fehlgeschlagen")})

        try:
            if kind == "VERSIONEN_REQ":
                self._ver_bereit.wait(30)
                msg = self._versionen_nachricht(rid)
                if msg is None:
                    self._send_app({"type": "ERROR", "reply_to": rid, "message": "Kein Projekt offen"})
                else:
                    self._send_app(msg)
            elif kind == "VERSION_RESTORE":
                res = self.version_wiederherstellen(header.get("version"), wer="kevin", warten=False)
                ack(res, f"V{res.get('version')} aus V{res.get('aus')} wiederhergestellt" if res.get("ok") else "")
            elif kind == "VERSION_COMPARE":
                res = self.versionen_vergleichen(header.get("a"), header.get("b"), zeigen=False, reply_to=rid)
                if not res.get("ok"):
                    self._send_app({"type": "ERROR", "reply_to": rid, "message": res.get("error", "")})
            elif kind == "VERSION_MILESTONE":
                res = self.meilenstein(str(header.get("titel") or ""), str(header.get("notiz") or ""),
                                       header.get("version"), wer="kevin", entfernen=bool(header.get("entfernen")))
                ack(res, f"Meilenstein an V{res.get('version')}" if res.get("ok") else "")
            elif kind == "VARIANT":
                res = self.variante(str(header.get("aktion") or "liste"), header.get("name"), header.get("von"),
                                    header.get("neuer_name"), wer="kevin", warten=False)
                ack(res, f"Variante {res.get('name')}" if res.get("ok") else "")
        except Exception as exc:  # noqa: BLE001
            self._send_app({"type": "ERROR", "reply_to": rid, "message": f"{type(exc).__name__}: {exc}"})


def _kurz(v: dict[str, Any]) -> dict[str, Any]:
    return {k: v.get(k) for k in ("nr", "titel", "zeit", "wer_text", "meilenstein", "kennzahlen", "commit")}

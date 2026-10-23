"""Simulation in der Kernel-Laufzeit (Mixin für ``KernelRuntime``, PLAN-SIMULATION.md): Nachricht SIM an die App,
Anfragen SIM_REQ, SIM_EDIT, SIM_RUN, SIM_CANCEL und die MCP-Werkzeuge ``simulation_liste``, ``simulation_aendern``,
``simulation_rechnen``.

- **Ändern** (App und Agent gleich): Operationen auf ``simulation.json`` anwenden (``datei.anwenden``), schreiben, dann
  im Rechenprozess alles mit dem Modell des letzten Laufs neu rechnen (``statik.anbindung.neu_mit_simulation``, S0 und
  S1, Millisekunden bis eine Sekunde); fertige Abläufe und Festkörper eines unveränderten Szenarios bleiben, solange
  sich an den Lagern nichts geändert hat. Danach STATICS und SIM.
- **Rechnen** (Knöpfe im Bereich): ``rechnen`` (S0 und S1 sofort), ``festigkeit`` (FEM je Teil oder für alle mit Last,
  ``festigkeit``), ``ablauf`` (S2 für dynamische Lastfälle, wie nach einem Lauf im Hintergrund), ``grenze`` (wie viel
  Last, wie steil: ``simulation/grenze.py`` im Rechenprozess; wie schnell: der Ablauf mit Suche). Immer nur ein Auftrag
  zugleich; Stand als SIM_JOB (läuft mit Fortschritt, fertig, Fehler, abgebrochen).
"""

from __future__ import annotations

import ast
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.simulation import datei as dt

JOB_ARTEN = ("rechnen", "festigkeit", "ablauf", "grenze")
GRENZ_ARTEN = ("last", "neigung", "geschwindigkeit")
FORTSCHRITT_S = 0.4


def _lager_sig(sim: dict[str, Any] | None) -> tuple:
    s = sim or {}
    return (json.dumps(s.get("lager") or [], sort_keys=True),
            tuple(sorted(a.get("id") for a in s.get("abgeleitet") or [] if not a.get("aktiv", True))))


class SimulationRuntime:
    """Erwartet ``self._lock``, ``self._send_app``, ``self.execute``, ``self._pool``, ``self._project`` und die Statik
    der Laufzeit (``_statik_voll``, ``_statik_run``, ``_statik_senden``, ``_statik_warten``)."""

    @property
    def _sim(self) -> dict[str, Any]:
        z = self.__dict__.get("_sim_zustand")
        if z is None:
            z = self.__dict__.setdefault("_sim_zustand", {"sperre": threading.Lock(), "job": None, "auftrag": 0,
                                                          "abbruch": False, "schreiben": threading.Lock()})
        return z

    def _sim_projekt(self) -> Path | None:
        proj = getattr(self, "_project", None)
        return Path(proj.path) if proj is not None else None

    # -- Rechenprozess ------------------------------------------------------------------------------------------------

    def _sim_exec(self, auftrag: dict[str, Any], timeout_s: float = 120.0) -> dict[str, Any]:
        code = (f"__import__('kevcad_kernel.statik.dienst', fromlist=['auftrag']).auftrag("
                f"{json.dumps(auftrag, ensure_ascii=False)!r})")
        res = self.execute(code, timeout_s=timeout_s)  # type: ignore[attr-defined]
        if not res.get("ok"):
            raise RuntimeError(f"Rechenprozess: {res.get('error')}")
        pfad = Path(ast.literal_eval(str(res.get("result"))))
        try:
            erg = json.loads(pfad.read_text(encoding="utf-8"))
        finally:
            try:
                os.unlink(pfad)
            except OSError:
                pass
        if erg.get("stand") != "done":
            raise ValueError(erg.get("meldung") or "Statik nicht gerechnet")
        return erg

    def _sim_behalten(self, alt: dict[str, Any] | None, neu: dict[str, Any]) -> dict[str, Any]:
        """Neues Ergebnis nach einer Änderung: Szenarien des Agenten (``szenario_rechnen``) bleiben; fertige Abläufe und
        Festkörper eines unveränderten Szenarios bleiben, solange die Lager gleich sind."""
        if not alt:
            return neu
        gleich = _lager_sig(alt.get("simulation")) == _lager_sig(neu.get("simulation"))
        alte = {e.get("name"): e for e in alt.get("szenarien") or []}
        szen = []
        for e in neu.get("szenarien") or []:
            a = alte.get(e.get("name"))
            if gleich and a is not None and a.get("szenario") == e.get("szenario") and (
                    isinstance(a.get("ablauf"), dict) or isinstance(a.get("festkoerper"), dict)):
                szen.append(a)
            else:
                szen.append(e)
        namen = {e.get("name") for e in szen}
        szen += [e for e in alt.get("szenarien") or [] if (e.get("szenario") or {}).get("quelle") == "agent"
                 and e.get("name") not in namen]
        return {**neu, "szenarien": szen}

    def _sim_neu_rechnen(self) -> dict[str, Any]:
        """Alle Szenarien mit ``simulation.json`` neu (ohne model.py); STATICS und SIM an die App."""
        statik_warten = getattr(self, "_statik_warten", None)
        if statik_warten is not None:
            statik_warten()
        with self._lock:  # type: ignore[attr-defined]
            if self._statik_voll is None:  # type: ignore[attr-defined]
                return {"ok": True, "gerechnet": False,
                        "text": "Noch kein Lauf: die Lastfälle werden beim nächsten Lauf gerechnet"}
        erg = self._sim_exec({"simulation": True})
        erg.pop("dienst_ms", None)
        with self._lock:  # type: ignore[attr-defined]
            self._statik_voll = self._sim_behalten(self._statik_voll, erg)  # type: ignore[attr-defined]
            # Lastfälle der App gehören zum Lauf: ihre Befunde kommen in die Prüfung (T34)
            self._statik_lauf_namen = frozenset(  # type: ignore[attr-defined]
                str(e.get("name")) for e in erg.get("szenarien") or [])
        self._statik_senden()  # type: ignore[attr-defined]
        self._sim_signaturen_nachtragen(erg.get("simulation") or {})
        self._sim_senden()
        return {"ok": True, "gerechnet": True, "ms": erg.get("ms")}

    def _sim_signaturen_nachtragen(self, sim: dict[str, Any]) -> None:
        """Flächen ohne Signatur (vom Agenten nur mit Nummer gesetzt): Signatur der zugeordneten Fläche eintragen, damit
        die Zuordnung spätere Modelländerungen übersteht."""
        sig = sim.get("signaturen") or {}
        projekt = self._sim_projekt()
        if not sig or projekt is None:
            return
        with self._sim["schreiben"]:
            doc = dt.lies(projekt)
            geaendert = False
            for l in doc.get("lastfaelle") or []:
                for x in l.get("lasten") or []:
                    s = sig.get(str(x.get("id")))
                    if s and isinstance(x.get("ort"), dict) and not x["ort"].get("signatur"):
                        x["ort"]["signatur"] = dt.pruefe_ort({"signatur": s})["signatur"]
                        geaendert = True
            for x in doc.get("lager") or []:
                s = sig.get(str(x.get("id")))
                if s and isinstance(x.get("ort"), dict) and not x["ort"].get("signatur"):
                    x["ort"]["signatur"] = dt.pruefe_ort({"signatur": s})["signatur"]
                    geaendert = True
            if geaendert:
                try:
                    dt.schreibe(projekt, doc, von=str(doc.get("von") or "kevin"))
                except OSError:
                    pass

    # -- Nachricht SIM -------------------------------------------------------------------------------------------------

    def _sim_modell_kurz(self) -> dict[str, dict[str, Any]]:
        """Kurzfassungen der Szenarien des letzten Laufs (für „als Kopie bearbeiten“)."""
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        return {str(e.get("name")): dict(e.get("szenario") or {}) for e in (voll or {}).get("szenarien") or []
                if (e.get("szenario") or {})}

    def simulation_stand(self) -> dict[str, Any]:
        """Inhalt der Nachricht SIM (ohne Typ): Dokument der App mit Zustand je Last und Lager, Szenarien aus model.py,
        Lager aus model.py, abgeleitete Lager, Topologie-Einstellungen, Hinweise, laufender Auftrag."""
        projekt = self._sim_projekt()
        doc = dt.lies(projekt)
        with self._lock:  # type: ignore[attr-defined]
            voll, run = self._statik_voll, self._statik_run  # type: ignore[attr-defined]
        sim = dict((voll or {}).get("simulation") or {})
        zust = sim.get("zustand") or {}
        zl, za, zs = zust.get("lasten") or {}, zust.get("lager") or {}, zust.get("schutz") or {}
        app_namen = {l["name"] for l in doc["lastfaelle"]}
        ergebnis = {str(e.get("name")): e for e in (voll or {}).get("szenarien") or []}
        lastfaelle = []
        for l in doc["lastfaelle"]:
            e = ergebnis.get(l["name"]) or {}
            lasten = []
            for x in l.get("lasten") or []:
                z = zl.get(str(x.get("id"))) or {}
                lasten.append({**x, "zustand": z.get("zustand") or ("offen" if voll is None else "ok"),
                               "zustand_text": z.get("text") or "", "kraft_wirksam": z.get("kraft"),
                               "punkt_wirksam": z.get("punkt"), "normale_wirksam": z.get("normale"),
                               "flaeche_wirksam": z.get("flaeche"), "flaeche_mm2_wirksam": z.get("flaeche_mm2")})
            lastfaelle.append({**l, "lasten": lasten, "ampel": e.get("ampel"), "text": e.get("text"),
                               "gerechnet": bool(e)})
        modell = []
        for name, e in ergebnis.items():
            sz = e.get("szenario") or {}
            q = sz.get("quelle") or "modell"
            if q == "app":
                continue
            modell.append({"name": name, "quelle": q, "art": sz.get("art") or "statisch", "zeile": sz.get("zeile"),
                           "ampel": e.get("ampel"), "text": e.get("text"), "beschreibung": sz.get("beschreibung"),
                           "dynamisch": bool(sz.get("ablauf")), "ersetzt": False})
        for x in sim.get("ersetzt") or []:  # aus model.py, aber von der gleichnamigen Fassung der App ersetzt
            if x.get("name") in app_namen:
                modell.append({"name": x["name"], "quelle": "modell", "art": x.get("art") or "statisch",
                               "zeile": x.get("zeile"), "ampel": None, "text": "", "beschreibung": None,
                               "dynamisch": False, "ersetzt": True})
        lager = []
        for x in doc["lager"]:
            z = za.get(str(x.get("id"))) or {}
            lager.append({**x, "zustand": z.get("zustand") or ("offen" if voll is None else "ok"),
                          "zustand_text": z.get("text") or "", "punkt_wirksam": z.get("punkt"),
                          "normale_wirksam": z.get("normale"), "flaeche_wirksam": z.get("flaeche"),
                          "gehalten_wirksam": z.get("gehalten")})
        modell_lager = [{**L, "zustand": "ok", "zustand_text": ""} for L in sim.get("lager") or []
                        if L.get("quelle") == "modell"]
        for lid, z in za.items():
            if z.get("quelle") == "modell" and z.get("zustand") == "fehlt":
                modell_lager.append({"id": lid, "teil": z.get("teil"), "art": "fest", "quelle": "modell",
                                     "zustand": "fehlt", "zustand_text": z.get("text") or ""})
        topo = {}
        for teil, e in (doc.get("topologie") or {}).items():
            topo[teil] = {**e, "schutz": [{**s, **{k: v for k, v in (zs.get(f"{teil}#{s.get('index')}") or {}).items()
                                                   if k in ("zustand", "text")}}
                                          for s in e.get("schutz") or []]}
        job = self._sim.get("job")
        return {"run": int(run or 0), "stand": int(doc.get("stand") or 0), "datei": dt.DATEI,
                "vorhanden": bool(projekt is not None and dt.pfad(projekt).exists()), "lastfaelle": lastfaelle,
                "modell": modell, "lager": lager, "modell_lager": modell_lager,
                "abgeleitet": list(sim.get("abgeleitet") or []), "topologie": topo,
                "hinweise": list(sim.get("hinweise") or []), "fehler": doc.get("fehler"),
                "job": dict(job) if job else None}

    def _sim_senden(self, reply_to: str | None = None, conn: Any = None) -> bool:
        from kevcad_kernel.protocol import pack_sim

        if self._sim_projekt() is None:
            return False
        head = pack_sim(self.simulation_stand(), reply_to=reply_to)
        head.pop("seq", None)
        if conn is not None:
            conn.send(head)
            return True
        return bool(self._send_app(head))  # type: ignore[attr-defined]

    def _simulation_nach_lauf(self) -> None:
        """Nach CHECK_DONE (STATICS ist schon draußen): SIM mit dem Zustand des Laufs; Signaturen nachtragen."""
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        try:
            self._sim_signaturen_nachtragen((voll or {}).get("simulation") or {})
            self._sim_senden()
        except Exception as exc:  # noqa: BLE001 - die Simulation darf den Lauf nicht stören
            log = getattr(self, "_log", None)
            if log is not None:
                log(f"[simulation] SIM nicht gesendet: {type(exc).__name__}: {exc}")

    def _simulation_on_connect(self, conn: Any) -> None:
        try:
            self._sim_senden(conn=conn)
        except Exception:  # noqa: BLE001
            pass

    # -- App -----------------------------------------------------------------------------------------------------------

    def _simulation_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in ("SIM_REQ", "SIM_EDIT", "SIM_RUN", "SIM_CANCEL"):
            return False
        self._pool.submit(self._sim_anfrage_sicher, kind, header)  # type: ignore[attr-defined]
        return True

    def _sim_anfrage_sicher(self, kind: str, header: dict[str, Any]) -> None:
        rid = header.get("id")
        try:
            if kind == "SIM_REQ":
                self._sim_senden(reply_to=rid)
            elif kind == "SIM_EDIT":
                res = self.simulation_aendern(list(header.get("ops") or []), basis=header.get("basis"), von="kevin")
                self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),  # type: ignore[attr-defined]
                                "message": "; ".join(res.get("meldungen") or []) if res.get("ok")
                                else str(res.get("error") or "")})
                if not res.get("ok"):
                    self._sim_senden()
            elif kind == "SIM_RUN":
                res = self.simulation_rechnen(str(header.get("was") or ""), header.get("lastfall"),
                                              header.get("teil"), bool(header.get("fein")), header.get("grenze"),
                                              warten=False, von="app")
                self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),  # type: ignore[attr-defined]
                                "message": str(res.get("auftrag") if res.get("ok") else res.get("error") or "")})
            elif kind == "SIM_CANCEL":
                res = self.simulation_abbrechen()
                if rid:
                    self._send_app({"type": "ACK", "reply_to": rid, "ok": True,  # type: ignore[attr-defined]
                                    "message": "abgebrochen" if res.get("abgebrochen") else "nichts zu abbrechen"})
        except Exception as exc:  # noqa: BLE001
            self._send_app({"type": "ERROR", "reply_to": rid,  # type: ignore[attr-defined]
                            "message": f"Simulation: {type(exc).__name__}: {exc}"})

    # -- Aufträge (Knöpfe) ---------------------------------------------------------------------------------------------

    def _sim_job_senden(self) -> None:
        from kevcad_kernel.protocol import pack_sim_job

        job = self._sim.get("job")
        if job:
            head = pack_sim_job(job)
            head.pop("seq", None)
            self._send_app(head)  # type: ignore[attr-defined]

    def _sim_job_setzen(self, **kw: Any) -> None:
        z = self._sim
        if z.get("job") is None:
            return
        z["job"] = {**z["job"], **kw}
        self._sim_job_senden()

    def _sim_fortschritt(self, auftrag: int, lastfall: str | None, was: str) -> None:
        """Fortschritt eines FEM- oder Ablauf-Auftrags aus STATICS als SIM_JOB weiterreichen."""
        z = self._sim
        zuletzt = None
        while (z.get("job") or {}).get("auftrag") == auftrag and (z.get("job") or {}).get("stand") == "laeuft":
            with self._lock:  # type: ignore[attr-defined]
                voll = self._statik_voll  # type: ignore[attr-defined]
            f, text = None, None
            for e in (voll or {}).get("szenarien") or []:
                if lastfall is not None and e.get("name") != lastfall:
                    continue
                fk = e.get("festkoerper") if isinstance(e.get("festkoerper"), dict) else {}
                ab = e.get("ablauf") if isinstance(e.get("ablauf"), dict) else {}
                if was == "festigkeit" and fk.get("stand") == "laeuft":
                    f, text = float(fk.get("fortschritt") or 0.0), str(fk.get("text") or "")
                elif was in ("ablauf", "grenze") and ab.get("stand") == "laeuft":
                    f, text = None, "Ablauf wird simuliert"
            if (f, text) != zuletzt and text:
                zuletzt = (f, text)
                self._sim_job_setzen(fortschritt=f, text=text)
            time.sleep(FORTSCHRITT_S)

    def simulation_rechnen(self, was: str, lastfall: str | None = None, teil: str | None = None, fein: bool = False,
                           grenze: str | None = None, warten: bool = True, von: str = "agent",
                           timeout_s: float = 600.0) -> dict[str, Any]:
        """Knopf im Bereich Simulation: ``rechnen`` (S0/S1), ``festigkeit`` (FEM), ``ablauf`` (S2), ``grenze``
        (``last``, ``neigung``, ``geschwindigkeit``). Läuft im Hintergrund (Stand als SIM_JOB); mit ``warten`` bis zum
        Ergebnis."""
        if was not in JOB_ARTEN:
            return {"ok": False, "error": f"was {was!r} unbekannt ({', '.join(JOB_ARTEN)})"}
        if was == "grenze" and grenze not in GRENZ_ARTEN:
            return {"ok": False, "error": f"grenze {grenze!r} unbekannt ({', '.join(GRENZ_ARTEN)})"}
        if self._sim_projekt() is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        if was in ("ablauf", "grenze") and not lastfall:
            return {"ok": False, "error": "Lastfall angeben"}
        z = self._sim
        if not z["sperre"].acquire(blocking=False):
            laeuft = z.get("job") or {}
            return {"ok": False, "error": f"Es läuft schon ein Auftrag ({laeuft.get('was')} "
                                          f"„{laeuft.get('lastfall') or 'alle'}“)"}
        z["auftrag"] += 1
        nr = z["auftrag"]
        z["abbruch"] = False
        z["job"] = {"auftrag": nr, "was": was, "lastfall": lastfall, "teil": teil, "grenze": grenze, "von": von,
                    "stand": "laeuft", "fortschritt": None, "text": "startet", "ergebnis": None, "meldung": None,
                    "beginn": time.time()}
        self._sim_job_senden()
        fertig = threading.Event()
        ausgabe: dict[str, Any] = {}

        def arbeit() -> None:
            try:
                ausgabe.update(self._sim_auftrag(nr, was, lastfall, teil, fein, grenze, timeout_s))
            except Exception as exc:  # noqa: BLE001 - als Stand des Auftrags
                ausgabe.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                job = z.get("job") or {}
                if job.get("auftrag") == nr:
                    if z.get("abbruch"):
                        stand = "abgebrochen"
                    else:
                        stand = "done" if ausgabe.get("ok") else "failed"
                    self._sim_job_setzen(stand=stand, fortschritt=1.0 if stand == "done" else job.get("fortschritt"),
                                         text=str(ausgabe.get("text") or ("abgebrochen" if stand == "abgebrochen"
                                                                          else ausgabe.get("error") or "")),
                                         ergebnis=ausgabe.get("ergebnis"), meldung=ausgabe.get("error"),
                                         ms=round((time.time() - float(job.get("beginn") or time.time())) * 1000, 1))
                z["sperre"].release()
                fertig.set()

        if was in ("festigkeit", "ablauf") or (was == "grenze" and grenze == "geschwindigkeit"):
            self._pool.submit(self._sim_fortschritt, nr, lastfall, was)  # type: ignore[attr-defined]
        if warten:
            arbeit()
            return {"auftrag": nr, **ausgabe}
        threading.Thread(target=arbeit, name=f"simulation-{was}", daemon=True).start()
        return {"ok": True, "auftrag": nr, "text": f"{was} gestartet"}

    def _sim_auftrag(self, nr: int, was: str, lastfall: str | None, teil: str | None, fein: bool,
                     grenze: str | None, timeout_s: float) -> dict[str, Any]:
        if was == "rechnen":
            res = self._sim_neu_rechnen()
            return {**res, "text": "S0 und S1 gerechnet" if res.get("gerechnet") else res.get("text"),
                    "ergebnis": self._sim_lastfall_kurz(lastfall)}
        if was == "festigkeit":
            res = self.festigkeit(teil=teil or None, szenario=lastfall or None, fein=fein,  # type: ignore[attr-defined]
                                  zeigen=True, timeout_s=min(timeout_s, 600.0))
            if not res.get("ok"):
                return res
            teile = [{k: t.get(k) for k in ("teil", "ampel", "sicherheit", "ziel", "kriterium")}
                     for t in res.get("teile") or []]
            return {"ok": True, "text": f"Festkörper: {len(teile)} {'Teil' if len(teile) == 1 else 'Teile'} gerechnet",
                    "ergebnis": {"teile": teile, "szenarien": res.get("szenarien")}}
        if was == "ablauf" or (was == "grenze" and grenze == "geschwindigkeit"):
            return self._sim_ablauf(str(lastfall), grenze == "geschwindigkeit")
        # Grenze Last oder Neigung: Suche im Rechenprozess (S0 und S1)
        self._sim_job_setzen(text="sucht die Grenze (S0 und S1)")
        erg = self._sim_exec({"grenze": {"lastfall": lastfall, "art": grenze}}, timeout_s=min(timeout_s, 300.0))
        g = erg.get("grenze") or {}
        if self._sim.get("abbruch"):
            return {"ok": False, "error": "abgebrochen"}
        return {"ok": True, "text": g.get("text") or "Grenze gefunden", "ergebnis": g}

    def _sim_ablauf(self, lastfall: str, grenze: bool) -> dict[str, Any]:
        """Ablauf (S2) eines dynamischen Lastfalls wie nach einem Lauf, mit Suche der Grenzgeschwindigkeit."""
        with self._lock:  # type: ignore[attr-defined]
            voll, run = self._statik_voll, self._statik_run  # type: ignore[attr-defined]
        e = next((x for x in (voll or {}).get("szenarien") or [] if x.get("name") == lastfall), None)
        if e is None:
            return {"ok": False, "error": f"Lastfall {lastfall!r} ist noch nicht gerechnet (erst „Rechnen“)"}
        if not (e.get("szenario") or {}).get("ablauf"):
            return {"ok": False, "error": f"„{lastfall}“ hat keine Fahrt: Geschwindigkeit oder Animation eintragen"}
        with self._lock:  # type: ignore[attr-defined]
            szen = []
            for x in (self._statik_voll or {}).get("szenarien") or []:  # type: ignore[attr-defined]
                if x.get("name") == lastfall:
                    x = {**x, "ablauf": {"stand": "laeuft", "animation": f"Ablauf: {lastfall}"}}
                szen.append(x)
            self._statik_voll = {**(self._statik_voll or {}), "szenarien": szen}  # type: ignore[attr-defined]
        self._statik_senden()  # type: ignore[attr-defined]
        self._dynamik_hintergrund([lastfall], run)  # type: ignore[attr-defined]
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        e = next((x for x in (voll or {}).get("szenarien") or [] if x.get("name") == lastfall), {})
        ab = e.get("ablauf") if isinstance(e.get("ablauf"), dict) else {}
        if self._sim.get("abbruch"):
            return {"ok": False, "error": "abgebrochen"}
        if ab.get("stand") != "done":
            return {"ok": False, "error": ab.get("meldung") or "Ablauf nicht gerechnet"}
        nach = getattr(self, "_festkoerper_nach_szenario", None)
        if nach is not None and not grenze:
            nach(lastfall)
        kz = ab.get("kennzahlen") or {}
        out: dict[str, Any] = {"ok": True, "text": ab.get("text") or "Ablauf gerechnet",
                               "ergebnis": {"ampel": ab.get("ampel"), "animation": ab.get("animation"),
                                            "kennzahlen": {k: kz.get(k) for k in (
                                                "kippreserve", "a_abheben", "v_abheben", "abheben_max_mm",
                                                "rutschgrenze", "a_kipp_hand")}}}
        if grenze:
            werte = []
            if kz.get("v_abheben") is not None:
                werte.append({"kriterium": "Kippen (hebt ab)", "grenze": kz["v_abheben"], "einheit": "m/s",
                              "text": f"hebt ab ab {float(kz['v_abheben']):.2f} m/s".replace(".", ",")})
            for L in kz.get("ladung") or []:
                if L.get("v_grenze") is not None:
                    werte.append({"kriterium": f"{str(L.get('name')).rsplit('/', 1)[-1]} springt heraus",
                                  "grenze": L["v_grenze"], "einheit": "m/s",
                                  "text": f"{str(L.get('name')).rsplit('/', 1)[-1]} springt ab "
                                          f"{float(L['v_grenze']):.2f} m/s heraus".replace(".", ",")})
            werte.sort(key=lambda w: float(w["grenze"]))
            text = (f"„{lastfall}“: höchstens {float(werte[0]['grenze']):.2f} m/s ({werte[0]['kriterium']})"
                    .replace(".", ",")) if werte else f"„{lastfall}“: in der Suche nichts kritisch"
            out["text"] = text
            out["ergebnis"] = {"art": "geschwindigkeit", "lastfall": lastfall, "werte": werte, "text": text,
                               "hinweis": "Ablauf (S2) mit Rollouts, Bremsart des Lastfalls"}
        return out

    def _sim_lastfall_kurz(self, lastfall: str | None) -> dict[str, Any]:
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        return {"szenarien": [{"name": e.get("name"), "ampel": e.get("ampel"), "text": e.get("text")}
                              for e in (voll or {}).get("szenarien") or []
                              if lastfall is None or e.get("name") == lastfall]}

    def simulation_abbrechen(self) -> dict[str, Any]:
        z = self._sim
        job = z.get("job") or {}
        if job.get("stand") != "laeuft":
            return {"ok": True, "abgebrochen": False}
        z["abbruch"] = True
        if job.get("was") == "festigkeit":
            self.festigkeit_abbrechen()  # type: ignore[attr-defined]
        if job.get("was") in ("ablauf", "grenze"):
            dyn = getattr(self, "_dyn_abbrechen", None)
            if dyn is not None:
                dyn()
        self._sim_job_setzen(stand="abgebrochen", text="abgebrochen")
        return {"ok": True, "abgebrochen": True}

    # -- KernelService -------------------------------------------------------------------------------------------------

    def simulation_liste(self) -> dict[str, Any]:
        """Lastfälle, Lasten, Lager und Topologie-Einstellungen aus der App (simulation.json) mit Zustand, dazu die
        Szenarien und Lager aus model.py und die abgeleiteten Lager."""
        if self._sim_projekt() is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open aufrufen."}
        statik_warten = getattr(self, "_statik_warten", None)
        if statik_warten is not None:
            statik_warten()
        return {"ok": True, **self.simulation_stand()}

    def simulation_aendern(self, ops: list[dict[str, Any]], basis: int | None = None, von: str = "agent"
                           ) -> dict[str, Any]:
        """Operationen auf simulation.json (wie SIM_EDIT der App), dann alles mit dem letzten Modell neu rechnen."""
        projekt = self._sim_projekt()
        if projekt is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        with self._sim["schreiben"]:
            doc = dt.lies(projekt)
            if doc.get("fehler"):
                return {"ok": False, "error": doc["fehler"]}
            if basis is not None and int(basis) != int(doc.get("stand") or 0):
                return {"ok": False, "error": f"simulation.json wurde inzwischen geändert (Stand {doc.get('stand')} "
                                              f"statt {basis}); neu laden und noch einmal"}
            try:
                neu, meldungen = dt.anwenden(doc, ops, self._sim_modell_kurz())
            except dt.SimulationFehler as exc:
                return {"ok": False, "error": str(exc)}
            try:
                neu = dt.schreibe(projekt, neu, von=von)
            except OSError as exc:
                return {"ok": False, "error": f"simulation.json nicht schreibbar: {exc}"}
        try:
            res = self._sim_neu_rechnen()
        except (RuntimeError, ValueError) as exc:
            self._sim_senden()
            return {"ok": True, "stand": neu["stand"], "meldungen": meldungen, "gerechnet": False,
                    "warnung": f"gespeichert, aber nicht gerechnet: {exc}"}
        stand = self.simulation_stand()
        return {"ok": True, "stand": neu["stand"], "meldungen": meldungen, "gerechnet": bool(res.get("gerechnet")),
                "datei": str(dt.pfad(projekt)),
                "lastfaelle": [{"name": l["name"], "ampel": l.get("ampel"), "text": l.get("text"),
                                "lasten": [{"id": x.get("id"), "teil": x.get("teil"), "zustand": x.get("zustand"),
                                            "kraft": x.get("kraft_wirksam") or x.get("kraft")}
                                           for x in l.get("lasten") or []]} for l in stand["lastfaelle"]],
                "lager": [{"id": x.get("id"), "teil": x.get("teil"), "art": x.get("art"), "zustand": x.get("zustand")}
                          for x in stand["lager"]], "hinweise": stand["hinweise"]}

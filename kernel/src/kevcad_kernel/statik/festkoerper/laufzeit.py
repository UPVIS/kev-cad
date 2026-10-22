"""Festkörper (S3) in der Kernel-Laufzeit (Mixin für ``KernelRuntime``): MCP ``festigkeit``, Rechnung im Hintergrund
nach jedem Lauf (nur Teile mit Last), Fortschritt und Abbruch, Ergebnis in STATICS (Feld ``festkoerper`` je
Szenario, Urteile ``festkoerper``) und als STATICS_FIELD (Oberflächennetz mit Ausnutzung und Verschiebung).

Ablauf einer Rechnung:

1. Rechenprozess (EXEC auf ``statik.dienst.auftrag`` mit ``festkoerper``): Fälle aus dem Modell des letzten Laufs,
   Teile als BREP, Nachbarnetze (Millisekunden, ``festkoerper/auftrag.py``).
2. Eigener Prozess ``python -m kevcad_kernel.statik.festkoerper.prozess``: Gmsh, scikit-fem, pyamg; Fortschritt als
   Zeilen auf stdout, Ergebnis als Datei, Zwischenspeicher je Teilstand und Lastfall. Immer nur einer zugleich; ein
   neuer Lauf oder STATICS_CANCEL beendet ihn.
3. Laufzeit: Urteile in die Szenarien (``urteil.einbauen``) → STATICS, Felder → STATICS_FIELD.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

PROZESS_S = 300.0
SENDEN_S = 0.3
FAEDEN = 4
UEBERHOEHUNG_ANTEIL = 0.08  # größte Verschiebung erscheint als 8 % der Teilgröße


class Abgebrochen(RuntimeError):
    pass


def _hat_last(e: dict[str, Any]) -> bool:
    sz = e.get("szenario") or {}
    if sz.get("lasten") or sz.get("neigung") or sz.get("ablauf"):
        return True
    return any(abs(float(c)) > 1e-9 for c in sz.get("beschleunigung") or [])


def _kandidaten(voll: dict[str, Any] | None, nur: str | None = None) -> list[str]:
    """Szenarien mit Last, in denen ein Teil als Kragträger nachgewiesen ist (Bauteil oder Lager eines Stabs)."""
    out = []
    for e in (voll or {}).get("szenarien") or []:
        if nur is not None and e.get("name") != nur:
            continue
        if not _hat_last(e):
            continue
        if any(b.get("sicherheit") is not None for b in e.get("bauteile") or []) or any(
                float(np.linalg.norm(v.get("kraft") or (0, 0, 0))) >= 0.5 for v in e.get("verbinder") or []):
            out.append(e["name"])
    return out


class FestkoerperRuntime:
    """Erwartet ``self._lock``, ``self._send_app``, ``self.execute``, ``self._pool`` und die Statik der Laufzeit
    (``_statik_voll``, ``_statik_run``, ``_statik_aktiv``, ``_statik_senden``, ``_statik_warten``)."""

    @property
    def _fk(self) -> dict[str, Any]:
        z = self.__dict__.get("_fk_zustand")
        if z is None:
            z = self.__dict__.setdefault("_fk_zustand", {"proc": None, "token": 0, "sperre": threading.Lock(),
                                                          "felder": {}, "abbruch": False, "gesendet": 0.0,
                                                          "felder_run": None})
        return z

    # -- Bausteine -----------------------------------------------------------------------------------------------------

    def _fk_exec(self, wunsch: dict[str, Any], timeout_s: float = 120.0) -> dict[str, Any]:
        code = (f"__import__('kevcad_kernel.statik.dienst', fromlist=['auftrag']).auftrag("
                f"{json.dumps({'festkoerper': wunsch}, ensure_ascii=False)!r})")
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
            raise ValueError(erg.get("meldung") or "Festkörper nicht vorbereitet")
        return erg["festkoerper"]

    def _fk_prozess(self, job: dict[str, Any], fortschritt: Any, timeout_s: float = PROZESS_S) -> dict[str, Any]:
        """FEM-Prozess starten, Fortschritt weiterreichen, auf das Ergebnis warten. Abbruch: Prozess beenden."""
        ergebnis = Path(job["ordner"]) / "ergebnis.json"
        env = dict(os.environ, OMP_NUM_THREADS=str(FAEDEN), OPENBLAS_NUM_THREADS=str(FAEDEN),
                   VECLIB_MAXIMUM_THREADS=str(FAEDEN), PYTHONUNBUFFERED="1")
        z = self._fk
        t0 = time.perf_counter()
        proc = subprocess.Popen([sys.executable, "-m", "kevcad_kernel.statik.festkoerper.prozess", job["auftrag"],
                                 str(ergebnis)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        z["proc"] = proc
        fehler: list[str] = []

        def lies_fehler() -> None:
            assert proc.stderr is not None
            for zeile in proc.stderr:
                fehler.append(zeile)
                del fehler[:-40]

        threading.Thread(target=lies_fehler, daemon=True).start()
        uhr = threading.Timer(timeout_s, proc.kill)
        uhr.start()
        try:
            assert proc.stdout is not None
            for zeile in proc.stdout:
                try:
                    m = json.loads(zeile)
                except ValueError:
                    continue
                if isinstance(m, dict) and "fortschritt" in m:
                    fortschritt(float(m["fortschritt"]), str(m.get("text") or ""))
            proc.wait()
        finally:
            uhr.cancel()
            z["proc"] = None
        if z.get("abbruch"):
            raise Abgebrochen("abgebrochen")
        if not ergebnis.exists():
            if time.perf_counter() - t0 >= timeout_s - 0.5:
                raise RuntimeError(f"FEM-Prozess nach {timeout_s:g} s abgebrochen")
            raise RuntimeError(f"FEM-Prozess ohne Ergebnis beendet (Code {proc.returncode}): {''.join(fehler)[-800:]}")
        out = json.loads(ergebnis.read_text(encoding="utf-8"))
        out["prozess_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out

    def _fk_status(self, run: int | None, namen: list[str], fk: dict[str, Any], senden: bool = True,
                   erzwingen: bool = False, nur_laufende: bool = False) -> None:
        """Stand (läuft, Fortschritt, abgebrochen …) in die Szenarien ``namen`` schreiben, ohne fertige Teile zu
        verlieren; STATICS höchstens alle ``SENDEN_S``. ``nur_laufende``: nur Szenarien, deren Festkörper noch läuft
        (Abbruch und Fehler überschreiben kein fertiges Ergebnis)."""
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
            if voll is None or (run is not None and self._statik_run != run):  # type: ignore[attr-defined]
                return
            szen = []
            for e in voll.get("szenarien") or []:
                alt_fk = e.get("festkoerper") if isinstance(e.get("festkoerper"), dict) else {}
                if e.get("name") in namen and (not nur_laufende or alt_fk.get("stand") == "laeuft"):
                    e = dict(e)
                    alt = alt_fk
                    neu = {**alt, **{k: v for k, v in fk.items() if k != "teile"}}
                    if "teile" in fk:
                        neu["teile"] = fk["teile"]
                    neu.setdefault("teile", [])
                    neu.setdefault("stand", "laeuft")
                    e["festkoerper"] = neu
                szen.append(e)
            self._statik_voll = {**voll, "szenarien": szen}  # type: ignore[attr-defined]
        z = self._fk
        jetzt = time.perf_counter()
        if senden and (erzwingen or jetzt - z["gesendet"] >= SENDEN_S):
            z["gesendet"] = jetzt
            self._statik_senden()  # type: ignore[attr-defined]

    def _fk_feld_senden(self, kopf: dict[str, Any], pfad: str, run: int, conn: Any = None) -> bool:
        from kevcad_kernel.protocol import pack_statics_feld

        try:
            with np.load(pfad) as d:
                felder = {k: d[k] for k in ("punkte", "dreiecke", "ausnutzung", "spannung", "verschiebung")}
        except Exception:  # noqa: BLE001 - Zwischenspeicher gelöscht: dann eben ohne Feld
            return False
        p = felder["punkte"]
        groesse = float(np.max(p.max(axis=0) - p.min(axis=0))) if len(p) else 1.0
        vmax = float(np.max(np.linalg.norm(felder["verschiebung"], axis=1))) if len(p) else 0.0
        kopf = {**kopf, "ueberhoehung": round(max(1.0, min(1e4, UEBERHOEHUNG_ANTEIL * groesse / vmax)), 1)
                if vmax > 1e-9 else 1.0}
        header, payload = pack_statics_feld(kopf, felder, run=run)
        header.pop("seq", None)
        if conn is not None:
            conn.send(header, payload)
            return True
        return bool(self._send_app(header, payload))  # type: ignore[attr-defined]

    def _fk_einbauen(self, run: int | None, out: dict[str, Any], namen: list[str], zeigen: str | None = None
                     ) -> list[dict[str, Any]]:
        """Ergebnis des FEM-Prozesses in die Szenarien einbauen, STATICS und je Feld STATICS_FIELD senden."""
        from kevcad_kernel.statik.festkoerper import GRENZEN_S3
        from kevcad_kernel.statik.festkoerper.urteil import einbauen, teil_kurz

        je: dict[str, list[dict[str, Any]]] = {}
        felder: list[tuple[dict[str, Any], str]] = []
        for r in out.get("faelle") or []:
            t = teil_kurz(r)
            je.setdefault(r.get("szenario") or "", []).append(t)
            if r.get("stand") == "done" and r.get("feld"):
                felder.append(({"szenario": r["szenario"], "teil": r["teil"], "feld": r["schluessel"],
                                "ziel": t["ziel"], "sicherheit": t["sicherheit"], "ampel": t["ampel"],
                                "spannung_max": t["spannung_max"], "verformung_max_mm": t["verformung_max_mm"]},
                               r["feld"]))
        neu_alle: list[dict[str, Any]] = []
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
            if voll is None or (run is not None and self._statik_run != run):  # type: ignore[attr-defined]
                return []
            szen = []
            for e in voll.get("szenarien") or []:
                name = e.get("name")
                if name in namen or name in je:
                    alt = e.get("festkoerper") if isinstance(e.get("festkoerper"), dict) else {}
                    neu_teile = {t["teil"]: t for t in je.get(name, [])}
                    teile = [t for t in alt.get("teile") or [] if t.get("teil") not in neu_teile
                             and t.get("stand") in ("done", "failed")] + list(neu_teile.values())
                    gerechnet = [t for t in teile if t.get("stand") == "done"]
                    fk = {"stand": "done", "fortschritt": 1.0, "meldung": None,
                          "text": (f"{len(gerechnet)} {'Teil' if len(gerechnet) == 1 else 'Teile'} gerechnet"
                                   if gerechnet else "kein Teil gerechnet"), "teile": teile}
                    if not teile:
                        e = {k: v for k, v in e.items() if k != "festkoerper"}
                    else:
                        e = einbauen(e, fk)
                        neu_alle += [t for t in teile if t.get("teil") in neu_teile]
                szen.append(e)
            self._statik_voll = {**voll, "szenarien": szen,  # type: ignore[attr-defined]
                                 "grenzen": list(dict.fromkeys(list(voll.get("grenzen") or []) + list(GRENZEN_S3)))
                                 if neu_alle else voll.get("grenzen")}
            if zeigen:
                self._statik_aktiv = zeigen  # type: ignore[attr-defined]
            run_jetzt = self._statik_run  # type: ignore[attr-defined]
        z = self._fk
        for kopf, pfad in felder:
            z["felder"][(kopf["szenario"], kopf["teil"])] = (kopf, pfad)
            z["felder_run"] = run_jetzt
            self._fk_feld_senden(kopf, pfad, run_jetzt or 0)
        self._statik_senden(zeigen=bool(zeigen))  # type: ignore[attr-defined]
        return neu_alle

    def _fk_rechnen(self, wunsch: dict[str, Any], namen: list[str], run: int | None, token: int,
                    zeigen: str | None = None, timeout_s: float = PROZESS_S) -> dict[str, Any]:
        """Auftrag schreiben, FEM-Prozess rechnen lassen, einbauen. Liefert {"job", "out", "teile"}."""
        z = self._fk
        job = self._fk_exec(wunsch)
        try:
            if token != z["token"]:
                raise Abgebrochen("überholt")
            faelle = job.get("faelle") or []
            if not faelle:  # nichts zu rechnen: Markierung „läuft“ wieder weg
                self._fk_einbauen(run, {"faelle": []}, namen)
                return {"job": job, "out": {"faelle": []}, "teile": []}
            namen = sorted(set(namen) | {f["szenario"] for f in faelle})
            je: dict[str, list[dict[str, Any]]] = {}
            for f in faelle:
                je.setdefault(f["szenario"], []).append({"teil": f["teil"], "stand": "laeuft"})
            for n, teile in je.items():
                with self._lock:  # type: ignore[attr-defined]
                    e = next((x for x in (self._statik_voll or {}).get("szenarien") or []  # type: ignore[attr-defined]
                              if x.get("name") == n), {})
                fertig = [t for t in ((e.get("festkoerper") or {}).get("teile") or [])
                          if t.get("stand") == "done" and t["teil"] not in {x["teil"] for x in teile}]
                self._fk_status(run, [n], {"stand": "laeuft", "fortschritt": 0.0, "text": "startet",
                                           "teile": fertig + teile}, senden=False)
            self._fk_status(run, list(je), {}, erzwingen=True)

            def fortschritt(x: float, text: str) -> None:
                self._fk_status(run, list(je), {"stand": "laeuft", "fortschritt": x, "text": text})

            z["abbruch"] = False
            out = self._fk_prozess(job, fortschritt, timeout_s)
            if token != z["token"]:
                raise Abgebrochen("überholt")
            teile = self._fk_einbauen(run, out, namen, zeigen)
            return {"job": job, "out": out, "teile": teile}
        finally:
            shutil.rmtree(job.get("ordner") or "", ignore_errors=True)

    # -- Nach jedem Lauf -----------------------------------------------------------------------------------------------

    def _festkoerper_nach_lauf(self, voll: dict[str, Any] | None, nur: str | None = None) -> None:
        """Nach CHECK_DONE (bzw. nach ``szenario_rechnen`` für ``nur``): Szenarien mit Teilen unter Last als „läuft“
        markieren und im Hintergrund rechnen; eine laufende Rechnung eines älteren Laufs endet."""
        z = self._fk
        if not voll:  # zweites CHECK desselben Laufs oder keine Statik: nichts Neues, nichts abbrechen
            return
        if nur is None:
            self._fk_abbrechen_intern()
            z["felder"] = {}
        namen = _kandidaten(voll, nur)
        if not namen:
            return
        for e in (voll or {}).get("szenarien") or []:
            if e.get("name") in namen:
                e["festkoerper"] = {"stand": "laeuft", "fortschritt": 0.0, "text": "wartet", "meldung": None,
                                    "teile": []}
        with self._lock:  # type: ignore[attr-defined]
            run = self._statik_run  # type: ignore[attr-defined]
        z["token"] += 1
        self._pool.submit(self._festkoerper_hintergrund, namen, run, z["token"])  # type: ignore[attr-defined]

    def _festkoerper_nach_szenario(self, name: str) -> None:
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        if voll is not None and _kandidaten(voll, name):
            self._fk_status(None, [name], {"stand": "laeuft", "fortschritt": 0.0, "text": "wartet", "teile": []},
                            senden=False)
            with self._lock:  # type: ignore[attr-defined]
                run = self._statik_run  # type: ignore[attr-defined]
            self._pool.submit(self._festkoerper_hintergrund, [name], run, self._fk["token"])  # type: ignore[attr-defined]

    def _festkoerper_hintergrund(self, namen: list[str], run: int | None, token: int) -> None:
        z = self._fk
        with z["sperre"]:
            try:
                if token != z["token"]:
                    raise Abgebrochen("überholt")
                self._fk_rechnen({"auto": True, "szenarien": namen}, namen, run, token)
            except Abgebrochen:
                # nur, was noch „läuft“ (ein neuer Lauf hat eigene Szenarien, festigkeit() kann schon fertig sein)
                self._fk_status(run, namen, {"stand": "abgebrochen", "text": "abgebrochen"}, erzwingen=True,
                                nur_laufende=True)
            except Exception as exc:  # noqa: BLE001 - Hintergrund: als Meldung am Szenario
                self._fk_status(run, namen, {"stand": "failed", "meldung": f"Festkörper nicht gerechnet: "
                                                                         f"{type(exc).__name__}: {exc}"},
                                erzwingen=True, nur_laufende=True)

    def _fk_abbrechen_intern(self) -> bool:
        z = self._fk
        z["token"] += 1
        p = z.get("proc")
        if p is not None and p.poll() is None:
            z["abbruch"] = True
            try:
                p.kill()
            except OSError:
                pass
            return True
        return False

    # -- App ---------------------------------------------------------------------------------------------------------

    def _festkoerper_on_connect(self, conn: Any) -> None:
        z = self._fk
        with self._lock:  # type: ignore[attr-defined]
            run = self._statik_run  # type: ignore[attr-defined]
        if z.get("felder_run") != run:
            return
        for kopf, pfad in list(z["felder"].values()):
            self._fk_feld_senden(kopf, pfad, run or 0, conn=conn)

    def _festkoerper_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind != "STATICS_CANCEL":
            return False
        self._pool.submit(self.festigkeit_abbrechen)  # type: ignore[attr-defined]
        return True

    # -- KernelService -------------------------------------------------------------------------------------------------

    def festigkeit_abbrechen(self) -> dict[str, Any]:
        """Laufende Festkörper-Rechnung beenden (MCP und STATICS_CANCEL aus der App)."""
        lief = self._fk_abbrechen_intern()
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        namen = [e["name"] for e in (voll or {}).get("szenarien") or []
                 if (e.get("festkoerper") or {}).get("stand") == "laeuft"]
        if namen:
            self._fk_status(None, namen, {"stand": "abgebrochen", "text": "abgebrochen"}, erzwingen=True,
                            nur_laufende=True)
        return {"ok": True, "abgebrochen": lief or bool(namen), "szenarien": namen}

    def festigkeit(self, teil: str | None = None, szenario: str | None = None, fein: bool = False,
                   ablauf: bool = False, zeigen: bool = True, timeout_s: float = PROZESS_S) -> dict[str, Any]:
        """Festkörper-FEM (S3) für Teile mit Last: ``teil`` (Name oder Gruppe, sonst alle mit Last), ``szenario``
        (sonst alle mit Last), ``fein`` (feineres Netz), ``ablauf`` (größte Kontaktkraft aus dem Ablauf des Szenarios
        als Last). Wartet auf das Ergebnis und zeigt es in der App."""
        from kevcad_kernel.statik.rechnen import befunde

        t0 = time.perf_counter()
        self._statik_warten()  # type: ignore[attr-defined]
        with self._lock:  # type: ignore[attr-defined]
            voll, run = self._statik_voll, self._statik_run  # type: ignore[attr-defined]
        if voll is None:
            return {"ok": False, "error": "Noch keine Statik: erst run aufrufen."}
        szen = voll.get("szenarien") or []
        if szenario is not None and not any(e.get("name") == szenario for e in szen):
            import difflib

            tips = difflib.get_close_matches(szenario, [e.get("name") for e in szen], n=3, cutoff=0.3)
            return {"ok": False, "error": f"Szenario {szenario!r} gibt es nicht (vorhanden: "
                                          f"{', '.join(repr(e.get('name')) for e in szen)})"
                                          + (f"; meinten Sie {tips[0]!r}?" if tips else "")}
        wunsch: dict[str, Any] = {"fein": bool(fein)}
        if teil:
            wunsch["teile"] = [teil]
        if szenario:
            wunsch["szenarien"] = [szenario]
        hinweise: list[str] = []
        if ablauf:
            lasten, hin = self._fk_ablauf_lasten(voll, teil, szenario)
            hinweise += hin
            if not lasten:
                return {"ok": False, "error": "; ".join(hin) or "Keine Kontaktkraft aus einem Ablauf gefunden"}
            wunsch["lasten"] = lasten
        z = self._fk
        if not z["sperre"].acquire(timeout=timeout_s):
            return {"ok": False, "error": "Eine andere Festkörper-Rechnung läuft noch"}
        try:
            z["token"] += 1
            token = z["token"]
            namen = [szenario] if szenario else _kandidaten(voll)
            try:
                res = self._fk_rechnen(wunsch, namen, run, token, zeigen=szenario if zeigen else None,
                                       timeout_s=timeout_s)
            except Abgebrochen:
                return {"ok": False, "error": "Festkörper-Rechnung abgebrochen"}
            except (ValueError, RuntimeError) as exc:
                return {"ok": False, "error": str(exc)}
        finally:
            z["sperre"].release()
        teile = res["teile"]
        if not teile:
            nicht = res["job"].get("nicht") or []
            grund = "; ".join(f"{n['teil']}: {n['meldung']}" for n in nicht)
            return {"ok": False, "error": "Kein Teil mit Last zu rechnen" + (f" ({grund})" if grund else "")
                    + (f" für {teil!r}" if teil else "") + (f" in {szenario!r}" if szenario else "")
                    + ". Festkörper rechnet Teile, die im Szenario als Kragträger nachgewiesen werden (Last auf "
                      "einem Druckteil, einer Platte oder einem Verbinder, Lager eines Stabs)."}
        if zeigen and teile and not szenario:
            with self._lock:  # type: ignore[attr-defined]
                self._statik_aktiv = next((r["szenario"] for r in res["out"].get("faelle") or []  # type: ignore[attr-defined]
                                           if r.get("stand") == "done"), None)
            self._statik_senden(zeigen=True)  # type: ignore[attr-defined]
        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
        betroffen = [e for e in (voll or {}).get("szenarien") or []
                     if e.get("name") in {r.get("szenario") for r in res["out"].get("faelle") or []}]
        faelle = []
        for r in res["out"].get("faelle") or []:
            kurz = {k: v for k, v in r.items() if k not in ("feld", "traceback", "_felder")}
            faelle.append(kurz)
        return {"ok": True, "run": run, "faelle": faelle,
                "teile": teile, "befunde": befunde({"szenarien": betroffen}),
                "szenarien": [{"name": e["name"], "ampel": e.get("ampel"), "text": e.get("text")} for e in betroffen],
                "hinweise": hinweise, "grenzen": (voll or {}).get("grenzen"),
                "ms": {"gesamt": round((time.perf_counter() - t0) * 1000, 1), "vorbereiten": res["job"].get("ms"),
                       "prozess": res["out"].get("prozess_ms")}, "gezeigt": bool(zeigen)}

    def _fk_ablauf_lasten(self, voll: dict[str, Any], teil: str | None, szenario: str | None
                          ) -> tuple[list[dict[str, Any]], list[str]]:
        """Kontaktkräfte je Teil aus dem Ablauf (S2) eines Szenarios, im Bild mit der größten Summe: Kraft auf das Teil
        am Kontaktpunkt. Der Wagen ist in diesem Bild schon gefahren: Punkt und Kraft kommen über die Lage des Teils im
        Bild (Animation „Ablauf: …“) zurück in die Ruhelage, für die das Netz gilt."""
        lasten: list[dict[str, Any]] = []
        hinweise: list[str] = []
        hub = getattr(self, "anim_hub", None)
        for e in voll.get("szenarien") or []:
            if szenario is not None and e.get("name") != szenario:
                continue
            ab = e.get("ablauf")
            if not isinstance(ab, dict) or ab.get("stand") != "done":
                continue
            anim = hub.get(ab.get("animation")) if hub is not None and ab.get("animation") else None
            spalte = {n: i for i, n in enumerate(anim.teile)} if anim is not None else {}

            def in_ruhelage(name: str, k: int, punkt: Any, kraft: np.ndarray) -> tuple[list[float], list[float]]:
                i = spalte.get(name)
                if anim is None or i is None or k >= len(anim.matrices):
                    return [float(c) for c in punkt], kraft.tolist()
                M = np.asarray(anim.matrices[k, i], dtype=float)
                R, t = M[:3, :3], M[:3, 3]
                return (R.T @ (np.asarray(punkt, float) - t)).tolist(), (R.T @ kraft).tolist()
            # je Bild alle Kontakte auf das Teil (ein Körper aus einem Teil; Gelenke sind keine Kontakte, also alles
            # äußere Last); maßgebend ist das Bild mit der größten Summe der Beträge
            beste: dict[str, tuple[float, list[dict[str, Any]]]] = {}
            for k, bild in enumerate(ab.get("pfeile") or []):
                je: dict[str, list[dict[str, Any]]] = {}
                for p in bild:
                    paar = p.get("paar") or []
                    F = np.asarray(p.get("kraft") or (0, 0, 0), float)
                    for i, name in enumerate(paar):
                        if teil is not None and not (name == teil or name.startswith(teil.rstrip("/") + "/")):
                            continue
                        if name == "Boden" or "(" in name and "Teile)" in name:
                            continue
                        f = F if i == 1 else -F  # die Kraft wirkt auf den zweiten Körper des Paars
                        anderer = paar[1 - i] if len(paar) == 2 else None
                        punkt, kraft = in_ruhelage(name, k, p["punkt"], f)
                        je.setdefault(name, []).append(
                            {"szenario": e["name"], "teil": name, "kraft": kraft, "punkt": punkt, "bild": k,
                             "kontakt_mit": None if anderer == "Boden" else anderer,
                             "quelle": f"Kontaktkraft im Ablauf ({anderer})"})
                for name, ls in je.items():
                    s = sum(float(np.linalg.norm(x["kraft"])) for x in ls)
                    if s > beste.get(name, (0.0, []))[0]:
                        beste[name] = (s, ls)
            for name, (b, ls) in beste.items():
                if b >= 1.0:
                    lasten += [x for x in ls if float(np.linalg.norm(x["kraft"])) >= 0.5]
            if not beste:
                hinweise.append(f"Im Ablauf von {e['name']!r} trifft keine Kontaktkraft"
                                + (f" das Teil {teil!r}" if teil else " ein einzelnes Teil"))
        if not any(isinstance(e.get("ablauf"), dict) for e in voll.get("szenarien") or []):
            hinweise.append("Kein Ablauf gerechnet: erst dynamik(…) aufrufen")
        return lasten, hinweise

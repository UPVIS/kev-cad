"""Topologieoptimierung in der Kernel-Laufzeit (Mixin für ``KernelRuntime``): MCP ``topologie_optimieren``,
``topologie_ergebnis``, ``topologie_abbrechen``, ``topologie_uebernehmen``, Hintergrund für Aufrufe aus model.py,
Fortschritt und Abbruch, Nachrichten TOPO und TOPO_FIELD an die App, Anfragen TOPO_START, TOPO_CANCEL, TOPO_APPLY.

Ablauf eines Auftrags:

1. Rechenprozess (EXEC auf ``topologie.dienst.auftrag``): Lastfall wie beim Festkörper aus dem Modell des letzten
   Laufs, Teil als BREP, Nachbarnetze (Millisekunden).
2. Gibt es das Ergebnis schon im Projekt (gleicher Modellschlüssel, gleicher Lastfall), wird nur gezeigt.
3. Sonst eigener Prozess ``python -m kevcad_kernel.topologie.prozess``: Fortschritt als Zeilen (TOPO alle 0,3 s, die
   Dichte als TOPO_FIELD ``dichte``), Ergebnis als Datei. Immer nur einer zugleich; Abbruch beendet den Prozess.
4. Ergebnis ins Projekt (``topologie/<teil>-<schlüssel>.brep`` und ``.json``), TOPO mit Kennzahlen vorher und nachher,
   TOPO_FIELD ``schutz``, ``koerper``, ``vorher``, ``nachher``. Kam der Auftrag aus model.py, startet der Lauf neu.
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

PROZESS_S = 600.0
SENDEN_S = 0.3
FAEDEN = 4
UEBERHOEHUNG_ANTEIL = 0.08


class Abgebrochen(RuntimeError):
    pass


def _kurz_kz(kz: dict[str, Any] | None) -> dict[str, Any]:
    if not kz:
        return {}
    return {k: kz.get(k) for k in ("volumen_mm3", "masse_g", "filament_g", "druckzeit_min", "spannung_max",
                                   "sicherheit", "ziel", "ampel", "ausnutzung", "verformung_max_mm", "kriterium",
                                   "ueberhang_mm2", "steg_min_mm", "ort") if k in kz}


def ergebnis_text(st: dict[str, Any]) -> str:
    """Kurzer deutscher Text zum Stand (für MCP und die App)."""
    s = st.get("stand")
    teil = st.get("teil") or "Teil"
    if s == "laeuft":
        return f"{teil}: {st.get('text') or 'läuft'} ({round(100 * float(st.get('fortschritt') or 0))} %)"
    if s == "failed":
        return f"{teil}: Topologieoptimierung fehlgeschlagen: {st.get('meldung')}"
    if s == "abgebrochen":
        return f"{teil}: Topologieoptimierung abgebrochen"
    if s != "done":
        return f"{teil}: {st.get('text') or s or 'keine Optimierung'}"
    kz = st.get("kennzahlen") or {}
    v, n, e = kz.get("vorher") or {}, kz.get("nachher") or {}, kz.get("ersparnis") or {}

    def zahl(x: Any, nd: int = 1) -> str:
        if x is None:
            return "?"
        return f"{float(x):.{nd}f}".replace(".", ",")

    teile = [f"{teil}: Volumen −{zahl(e.get('volumen_prozent'), 0)} % ({zahl((v.get('volumen_mm3') or 0) / 1000)} → "
             f"{zahl((n.get('volumen_mm3') or 0) / 1000)} cm³)"]
    if n.get("filament_g") is not None:
        teile.append(f"Filament {zahl(v.get('filament_g'))} → {zahl(n.get('filament_g'))} g, Druckzeit "
                     f"{zahl(v.get('druckzeit_min'), 0)} → {zahl(n.get('druckzeit_min'), 0)} min")
    if n.get("sicherheit") is not None:
        teile.append(f"Sicherheit {zahl(v.get('sicherheit'), 2)} → {zahl(n.get('sicherheit'), 2)} (Ziel "
                     f"{zahl(n.get('ziel'), 0)}, {n.get('ampel')}), größte Spannung {zahl(v.get('spannung_max'))} → "
                     f"{zahl(n.get('spannung_max'))} N/mm², Verformung {zahl(v.get('verformung_max_mm'), 2)} → "
                     f"{zahl(n.get('verformung_max_mm'), 2)} mm")
    teile.append("Näherung, kein Festigkeitsnachweis")
    return "; ".join(teile) + "."


class TopologieRuntime:
    """Erwartet ``self._lock``, ``self._send_app``, ``self.execute``, ``self._pool``, ``self._project`` und
    ``self._submit_run`` der Laufzeit, dazu ``self.variante`` (Versionen)."""

    @property
    def _tp(self) -> dict[str, Any]:
        z = self.__dict__.get("_tp_zustand")
        if z is None:
            z = self.__dict__.setdefault("_tp_zustand", {
                "proc": None, "token": 0, "sperre": threading.Lock(), "stand": None, "felder": {}, "gesendet": 0.0,
                "abbruch": False, "auftrag": 0, "lauf_beginn": {}, "laeuft": None, "ergebnis": None,
                "warteschlange": []})
        return z

    # -- Bausteine -----------------------------------------------------------------------------------------------------

    def _tp_exec(self, wunsch: dict[str, Any], timeout_s: float = 120.0) -> dict[str, Any]:
        import tempfile

        fd, datei = tempfile.mkstemp(prefix="kevcad-topo-wunsch-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(wunsch, fh, ensure_ascii=False)
        code = (f"__import__('kevcad_kernel.topologie.dienst', fromlist=['auftrag_datei']).auftrag_datei("
                f"{datei!r})")
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
            raise ValueError(erg.get("meldung") or "Topologie nicht vorbereitet")
        return erg["topologie"]

    def _tp_status(self, **neu: Any) -> None:
        z = self._tp
        with self._lock:  # type: ignore[attr-defined]
            st = dict(z["stand"] or {})
            st.update(neu)
            st["text_lang"] = ergebnis_text(st)
            z["stand"] = st

    def _tp_senden(self, erzwingen: bool = False, conn: Any = None) -> None:
        from kevcad_kernel.protocol import pack_topo

        z = self._tp
        jetzt = time.perf_counter()
        if not erzwingen and conn is None and jetzt - z["gesendet"] < SENDEN_S:
            return
        with self._lock:  # type: ignore[attr-defined]
            st = dict(z["stand"] or {})
            run = getattr(self, "_run_no", 0)
        if not st:
            return
        z["gesendet"] = jetzt
        head = pack_topo(st, run=int(run or 0))
        head.pop("seq", None)
        if conn is not None:
            conn.send(head)
        else:
            self._send_app(head)  # type: ignore[attr-defined]

    def _tp_feld(self, art: str, pfad: str | None, kopf: dict[str, Any] | None = None, conn: Any = None,
                 merken: bool = True) -> bool:
        from kevcad_kernel.protocol import pack_topo_feld

        if not pfad:
            return False
        try:
            with np.load(pfad) as d:
                felder = {k: d[k] for k in d.files}
        except Exception:  # noqa: BLE001 - Datei weg: dann eben ohne Feld
            return False
        z = self._tp
        k = dict(kopf or {})
        k["art"] = art
        k.setdefault("auftrag", z["auftrag"])
        st = z["stand"] or {}
        k.setdefault("teil", st.get("teil"))
        if art in ("vorher", "nachher") and "verschiebung" in felder and len(felder["punkte"]):
            p = felder["punkte"]
            groesse = float(np.max(p.max(axis=0) - p.min(axis=0)))
            vmax = float(np.max(np.linalg.norm(felder["verschiebung"], axis=1)))
            k["ueberhoehung"] = round(max(1.0, min(1e4, UEBERHOEHUNG_ANTEIL * groesse / vmax)), 1) if vmax > 1e-9 \
                else 1.0
        try:
            header, payload = pack_topo_feld(k, felder)
        except Exception:  # noqa: BLE001
            return False
        header.pop("seq", None)
        if merken:
            z["felder"][art] = (k, pfad)
        if conn is not None:
            conn.send(header, payload)
            return True
        return bool(self._send_app(header, payload))  # type: ignore[attr-defined]

    def _tp_prozess(self, auftrag: str, ergebnis: Path, fortschritt: Any, timeout_s: float) -> dict[str, Any]:
        env = dict(os.environ, OMP_NUM_THREADS=str(FAEDEN), OPENBLAS_NUM_THREADS=str(FAEDEN),
                   VECLIB_MAXIMUM_THREADS=str(FAEDEN), PYTHONUNBUFFERED="1")
        z = self._tp
        t0 = time.perf_counter()
        proc = subprocess.Popen([sys.executable, "-m", "kevcad_kernel.topologie.prozess", auftrag, str(ergebnis)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
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
                    fortschritt(m)
            proc.wait()
        finally:
            uhr.cancel()
            z["proc"] = None
        if z.get("abbruch"):
            raise Abgebrochen("abgebrochen")
        if not ergebnis.exists():
            if time.perf_counter() - t0 >= timeout_s - 0.5:
                raise RuntimeError(f"Topo-Prozess nach {timeout_s:g} s abgebrochen")
            raise RuntimeError(f"Topo-Prozess ohne Ergebnis beendet (Code {proc.returncode}): {''.join(fehler)[-800:]}")
        out = json.loads(ergebnis.read_text(encoding="utf-8"))
        out["prozess_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out

    def _tp_projekt(self) -> Path | None:
        proj = getattr(self, "_project", None)
        return Path(proj.path) if proj is not None else None

    def _tp_aufruf_fuer(self, teil: str | None) -> dict[str, Any] | None:
        """Letzter Aufruf aus model.py für das Teil (mit der Form des Ausgangsteils)."""
        from kevcad_kernel.topologie.ergebnis import aufrufe

        projekt = self._tp_projekt()
        if projekt is None:
            return None
        alle = [a for a in aufrufe(projekt) if teil is None or a.get("teil") == teil]
        return max(alle, key=lambda a: float(a.get("zeit") or 0.0)) if alle else None

    # -- Auftrag -------------------------------------------------------------------------------------------------------

    def _tp_job(self, wunsch: dict[str, Any], quelle: str, token: int, timeout_s: float = PROZESS_S
                ) -> dict[str, Any]:
        """Ein Auftrag von Anfang bis Ende (im Hintergrund oder wartend). Rückgabe: Stand."""
        from kevcad_kernel.topologie import einstellungen, modell_schluessel
        from kevcad_kernel.topologie.ergebnis import lies_json, pfade, schreibe_json

        z = self._tp
        projekt = self._tp_projekt()
        if projekt is None:
            raise ValueError("Kein Projekt offen")
        z["auftrag"] += 1
        nr = z["auftrag"]
        einst = einstellungen(**(wunsch.get("einstellungen") or {}))
        z["felder"] = {}
        with self._lock:  # type: ignore[attr-defined]
            z["stand"] = {"stand": "laeuft", "auftrag": nr, "teil": wunsch.get("teil"), "szenario": wunsch.get("szenario"),
                          "einstellungen": einst, "fortschritt": 0.0, "phase": "vorbereiten", "text": "Auftrag",
                          "quelle": quelle, "iteration": 0, "max_iter": einst["iterationen"], "verlauf": []}
        self._tp_senden(erzwingen=True)
        job = self._tp_exec({**wunsch, "einstellungen": einst})
        try:
            if token != z["token"]:
                raise Abgebrochen("überholt")
            teil = job["teil"]
            # Ausgangsform: aus dem Aufruf in model.py, sonst die Form des gezeigten Teils
            with open(job["auftrag"], encoding="utf-8") as fh:
                A = json.load(fh)
            form = A.get("form")
            schutz_h = [s.get("hash") or s.get("schluessel") for s in wunsch.get("schutz") or []]
            mk = wunsch.get("modell_schluessel") or modell_schluessel(form, teil, wunsch.get("szenario"), einst,
                                                                     [h for h in schutz_h if h])
            pf = pfade(projekt, teil, mk)
            self._tp_status(teil=teil, szenario=job["szenarien"][0] if job.get("szenarien") else None,
                            modell_schluessel=mk, lastfall=job["lastfall"], hinweise=job.get("hinweise") or [])
            alt = lies_json(pf["json"]) if pf["json"].exists() and pf["brep"].exists() else None
            if alt and alt.get("lastfall") == job["lastfall"] and not wunsch.get("neu"):
                return self._tp_fertig(alt, pf, quelle, aus_projekt=True)
            if alt and alt.get("lastfall") != job["lastfall"] and not wunsch.get("neu") and quelle == "modell":
                self._tp_status(hinweise=(job.get("hinweise") or []) + [
                    "Der Lastfall hat sich seit dem gespeicherten Ergebnis geändert: neu optimiert"])
            ergebnis = Path(job["ordner"]) / "ergebnis.json"
            if wunsch.get("neu"):
                A["neu"] = True
                with open(job["auftrag"], "w", encoding="utf-8") as fh:
                    json.dump(A, fh, ensure_ascii=False)

            def fortschritt(m: dict[str, Any]) -> None:
                neu = {"fortschritt": float(m.get("fortschritt") or 0.0), "text": str(m.get("text") or ""),
                       "phase": m.get("phase")}
                if m.get("iteration"):
                    neu["iteration"] = int(m["iteration"])
                    st = z["stand"] or {}
                    v = list(st.get("verlauf") or [])
                    v.append({"i": int(m["iteration"]), "c": m.get("c"), "volumen": m.get("volumen"),
                              "grau": m.get("grau")})
                    neu["verlauf"] = v[-200:]
                if m.get("voxel"):
                    neu["voxel"] = m["voxel"]
                    neu["h_mm"] = m.get("h_mm")
                self._tp_status(**neu)
                if m.get("schutz"):
                    self._tp_feld("schutz", m["schutz"])
                if m.get("dichte"):
                    self._tp_feld("dichte", m["dichte"], {"iteration": m.get("iteration")}, merken=True)
                if m.get("netz"):
                    self._tp_feld("koerper", m["netz"])
                self._tp_senden(erzwingen=bool(m.get("dichte")))

            z["abbruch"] = False
            out = self._tp_prozess(job["auftrag"], ergebnis, fortschritt, timeout_s)
            if token != z["token"]:
                raise Abgebrochen("überholt")
            if out.get("stand") != "done":
                raise RuntimeError(out.get("meldung") or "Topologie fehlgeschlagen")
            # ins Projekt: Körper (Teilkoordinaten) und Kennzahlen
            pf["brep"].parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out["dateien"]["brep"], pf["brep"])
            meta = {**{k: out.get(k) for k in ("version", "teil", "lastfall", "szenarien", "einstellungen",
                                               "behalten_wirksam", "kennzahlen", "gitter", "schutz", "netz",
                                               "druckpruefung", "hinweise", "grenzen", "ms")},
                    "schluessel": mk, "berechnet": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "dateien": out.get("dateien"),
                    "optimierung": {k: v for k, v in (out.get("optimierung") or {}).items() if k != "verlauf"},
                    "verlauf": [{"i": i + 1, "c": e.get("c"), "volumen": e.get("volumen")}
                                for i, e in enumerate((out.get("optimierung") or {}).get("verlauf") or [])],
                    "faelle": {s: [{k: v for k, v in f.items() if k not in ("feld",)} for f in fl]
                               for s, fl in (out.get("faelle") or {}).items()}}
            schreibe_json(pf["json"], meta)
            return self._tp_fertig(meta, pf, quelle, aus_projekt=False)
        finally:
            shutil.rmtree(job.get("ordner") or "", ignore_errors=True)

    def _tp_fertig(self, meta: dict[str, Any], pf: dict[str, Path], quelle: str, aus_projekt: bool) -> dict[str, Any]:
        from kevcad_kernel.topologie import GRENZEN

        z = self._tp
        projekt = self._tp_projekt()
        datei = str(pf["brep"].relative_to(projekt)) if projekt is not None else str(pf["brep"])
        im_modell = self._tp_im_modell(meta.get("schluessel"))
        self._tp_status(stand="done", fortschritt=1.0, phase="fertig", text="fertig",
                        kennzahlen=meta.get("kennzahlen"), schutz={k: v for k, v in (meta.get("schutz") or {}).items()
                                                                   if k != "netz"},
                        netz=meta.get("netz"), gitter=meta.get("gitter"), druckpruefung=meta.get("druckpruefung"),
                        hinweise=meta.get("hinweise") or [], grenzen=meta.get("grenzen") or list(GRENZEN),
                        ergebnis={"datei": datei, "schluessel": meta.get("schluessel"), "im_modell": im_modell,
                                  "aus_projekt": aus_projekt},
                        verlauf=meta.get("verlauf") or (z["stand"] or {}).get("verlauf") or [],
                        optimierung=meta.get("optimierung"), ms=meta.get("ms"),
                        behalten_wirksam=meta.get("behalten_wirksam"), berechnet=meta.get("berechnet"))
        d = meta.get("dateien") or {}
        f = meta.get("faelle") or {}

        def feld_kopf(stufe: str) -> dict[str, Any]:
            x = (f.get(stufe) or [{}])[0] if f.get(stufe) else {}
            return {"sicherheit": x.get("sicherheit"), "ziel": x.get("ziel"),
                    "spannung_max": x.get("spannung_max"), "verformung_max_mm": x.get("verformung_max_mm")}
        self._tp_feld("schutz", d.get("schutz"))
        self._tp_feld("koerper", d.get("netz"))
        if d.get("vorher"):
            self._tp_feld("vorher", d["vorher"][0], feld_kopf("vorher"))
        if d.get("nachher"):
            self._tp_feld("nachher", d["nachher"][0], feld_kopf("nachher"))
        z["felder"].pop("dichte", None)
        self._tp_senden(erzwingen=True)
        z["ergebnis"] = meta
        return dict(z["stand"] or {})

    def _tp_im_modell(self, schluessel: str | None) -> bool:
        """Lädt model.py dieses Ergebnis (gleicher Modellschlüssel im letzten Aufruf)?"""
        projekt = self._tp_projekt()
        if projekt is None or not schluessel:
            return False
        from kevcad_kernel.topologie.ergebnis import aufrufe

        return any(a.get("schluessel") == schluessel for a in aufrufe(projekt))

    def _tp_hintergrund(self, wunsch: dict[str, Any], quelle: str, token: int) -> None:
        z = self._tp
        with z["sperre"]:
            try:
                if token != z["token"]:
                    raise Abgebrochen("überholt")
                st = self._tp_job(wunsch, quelle, token)
                if quelle == "modell" and st.get("stand") == "done" and not (st.get("ergebnis") or {}).get(
                        "aus_projekt"):
                    # model.py wartet auf dieses Ergebnis: Lauf neu, jetzt mit dem optimierten Körper
                    self._submit_run(None, 0, getattr(self, "run_timeout_s", 120.0), source="auto")  # type: ignore[attr-defined]
            except Abgebrochen:
                self._tp_status(stand="abgebrochen", text="abgebrochen")
                self._tp_sicher_senden()
            except Exception as exc:  # noqa: BLE001 - Hintergrund: als Meldung an die App
                import traceback

                log = getattr(self, "_log", None)
                if log is not None:
                    log(f"[topologie] fehlgeschlagen: {traceback.format_exc(limit=8)}")
                self._tp_status(stand="failed", meldung=f"{type(exc).__name__}: {exc}")
                self._tp_sicher_senden()
            finally:
                z["laeuft"] = None

    def _tp_sicher_senden(self) -> None:
        try:
            self._tp_senden(erzwingen=True)
        except Exception as exc:  # noqa: BLE001 - nie den Hintergrundfaden verlieren
            log = getattr(self, "_log", None)
            if log is not None:
                log(f"[topologie] TOPO nicht gesendet: {exc!r}")

    def _tp_starten(self, wunsch: dict[str, Any], quelle: str) -> dict[str, Any]:
        z = self._tp
        if z.get("laeuft") is not None:
            # ein neuer Wunsch ersetzt den laufenden (Kevin schiebt den Regler, startet neu)
            self._tp_abbrechen_intern()
        z["token"] += 1
        token = z["token"]
        z["laeuft"] = token
        self._pool.submit(self._tp_hintergrund, wunsch, quelle, token)  # type: ignore[attr-defined]
        return {"ok": True, "stand": "laeuft", "teil": wunsch.get("teil"), "szenario": wunsch.get("szenario")}

    def _tp_abbrechen_intern(self) -> bool:
        z = self._tp
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

    # -- nach dem Lauf: Aufrufe aus model.py ------------------------------------------------------------------------

    def _topologie_lauf_beginn(self, run: int) -> None:
        self._tp["lauf_beginn"][int(run)] = time.time()
        alt = [r for r in self._tp["lauf_beginn"] if r < int(run) - 20]
        for r in alt:
            self._tp["lauf_beginn"].pop(r, None)

    def _topologie_nach_lauf(self, check: dict[str, Any] | None, statik: dict[str, Any] | None) -> None:
        """Nach CHECK_DONE mit Statik: fehlende Ergebnisse der Aufrufe dieses Laufs im Hintergrund rechnen."""
        if not statik or not check:
            return
        projekt = self._tp_projekt()
        if projekt is None:
            return
        from kevcad_kernel.topologie.ergebnis import aufrufe, pfade

        run = int(check.get("run") or 0)
        beginn = self._tp["lauf_beginn"].get(run)
        if beginn is None:
            return
        offen = [a for a in aufrufe(projekt, seit=beginn - 1.0)
                 if a.get("automatisch", True) and not pfade(projekt, a["teil"], a["schluessel"])["brep"].exists()]
        z = self._tp
        if not offen or z.get("laeuft") is not None:
            return
        a = offen[0]
        wunsch = {"teil": a["teil"], "form": a.get("form"), "szenario": a.get("szenario"),
                  "einstellungen": a.get("einstellungen"), "schutz": a.get("schutz") or [],
                  "form_brep": a.get("form_brep"), "modell_schluessel": a["schluessel"]}
        self._tp_starten(wunsch, "modell")

    # -- App -----------------------------------------------------------------------------------------------------------

    def _topologie_on_connect(self, conn: Any) -> None:
        z = self._tp
        if not z.get("stand"):
            return
        self._tp_senden(conn=conn)
        for art, (kopf, pfad) in list(z["felder"].items()):
            self._tp_feld(art, pfad, kopf, conn=conn, merken=False)

    def _topologie_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind == "TOPO_START":
            wunsch = {k: header.get(k) for k in ("teil", "szenario") if header.get(k) is not None}
            wunsch["einstellungen"] = {k: header.get(k) for k in ("behalten", "ueberhang", "fein", "steg", "bett")
                                       if header.get(k) is not None}
            self._pool.submit(self._tp_app_start, wunsch)  # type: ignore[attr-defined]
            return True
        if kind == "TOPO_CANCEL":
            self._pool.submit(self.topologie_abbrechen)  # type: ignore[attr-defined]
            return True
        if kind == "TOPO_APPLY":
            self._pool.submit(self.topologie_uebernehmen)  # type: ignore[attr-defined]
            return True
        return False

    def _tp_app_start(self, wunsch: dict[str, Any]) -> None:
        a = self._tp_aufruf_fuer(wunsch.get("teil"))
        if a is not None:
            wunsch.setdefault("form_brep", a.get("form_brep"))
            wunsch.setdefault("form", a.get("form"))
        self._tp_starten(wunsch, "app")

    # -- KernelService -------------------------------------------------------------------------------------------------

    def topologie_optimieren(self, teil: str | None = None, szenario: str | None = None, behalten: float | None = None,
                             schutz: list[dict[str, Any]] | None = None, ueberhang: bool | None = None,
                             fein: bool | None = None, steg: float | None = None, bett: bool | None = None,
                             neu: bool = False, warten: bool = False, timeout_s: float = PROZESS_S) -> dict[str, Any]:
        """Topologieoptimierung eines Druckteils starten (im Hintergrund; ``warten`` = bis zum Ergebnis)."""
        if self._tp_projekt() is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open aufrufen."}
        statik_warten = getattr(self, "_statik_warten", None)
        if statik_warten is not None:
            statik_warten()
        wunsch: dict[str, Any] = {"teil": teil, "szenario": szenario, "neu": bool(neu),
                                  "einstellungen": {k: v for k, v in (("behalten", behalten), ("ueberhang", ueberhang),
                                                                      ("fein", fein), ("steg", steg), ("bett", bett))
                                                    if v is not None},
                                  "schutz": list(schutz or [])}
        a = self._tp_aufruf_fuer(teil)
        if a is not None and (teil is None or a.get("teil") == teil):
            wunsch["form_brep"] = a.get("form_brep")
            wunsch["form"] = a.get("form")
            wunsch["teil"] = wunsch["teil"] or a.get("teil")
        # Fehler (Teil, Szenario, keine Last) gleich melden statt im Hintergrund
        try:
            probe = self._tp_exec({**wunsch, "einstellungen": wunsch["einstellungen"]})
            shutil.rmtree(probe.get("ordner") or "", ignore_errors=True)
            wunsch["teil"] = probe["teil"]
            wunsch["szenario"] = wunsch["szenario"] or (probe.get("szenarien") or [None])[0]
        except (ValueError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        start = self._tp_starten(wunsch, "agent")
        if not warten:
            return {**start, "text": f"{wunsch['teil']}: Topologieoptimierung läuft im Hintergrund (Szenario "
                                     f"{wunsch['szenario']!r}); Ergebnis mit topologie_ergebnis(warten_s=…)"}
        return self.topologie_ergebnis(warten_s=timeout_s)

    def topologie_ergebnis(self, warten_s: float = 0.0) -> dict[str, Any]:
        """Stand der letzten Topologieoptimierung; ``warten_s``: so lange auf das Ende warten."""
        z = self._tp
        ende = time.time() + max(0.0, float(warten_s or 0.0))
        while z.get("laeuft") is not None and time.time() < ende:
            time.sleep(0.25)
        st = dict(z["stand"] or {})
        if not st:
            return {"ok": True, "stand": "keine", "text": "Noch keine Topologieoptimierung in dieser Sitzung"}
        out = {k: v for k, v in st.items() if k not in ("verlauf",)}
        if st.get("verlauf"):
            v = st["verlauf"]
            out["verlauf"] = {"iterationen": len(v), "nachgiebigkeit_relativ": [
                round(float(x["c"]) / float(v[0]["c"]), 4) for x in v if x.get("c") and v[0].get("c")][-10:]}
        out["kennzahlen"] = {s: _kurz_kz(k) if s != "ersparnis" else k
                             for s, k in (st.get("kennzahlen") or {}).items()}
        out["text"] = ergebnis_text(st)
        out["ok"] = st.get("stand") != "failed"
        if st.get("stand") == "failed":
            out["error"] = st.get("meldung")
        return out

    def topologie_abbrechen(self) -> dict[str, Any]:
        lief = self._tp_abbrechen_intern()
        z = self._tp
        if (z["stand"] or {}).get("stand") == "laeuft":
            self._tp_status(stand="abgebrochen", text="abgebrochen")
            self._tp_senden(erzwingen=True)
        return {"ok": True, "abgebrochen": lief}

    def topologie_uebernehmen(self, variante: str | None = None, warten: bool = False) -> dict[str, Any]:
        """Das letzte Ergebnis als Variante übernehmen: neue Variante anlegen, in model.py hinter dem Druckteil
        ``topologie.optimieren(…)`` mit denselben Einstellungen eintragen, Lauf. Kevin entscheidet, welche Variante
        bleibt."""
        z = self._tp
        st = dict(z["stand"] or {})
        if st.get("stand") != "done" or not st.get("ergebnis"):
            return {"ok": False, "error": "Kein fertiges Ergebnis zum Übernehmen"}
        projekt = self._tp_projekt()
        if projekt is None:
            return {"ok": False, "error": "Kein Projekt offen"}
        if (st.get("ergebnis") or {}).get("im_modell"):
            return {"ok": True, "unveraendert": True, "text": "model.py lädt dieses Ergebnis schon"}
        model = projekt / "model.py"
        try:
            code = model.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"model.py nicht lesbar: {exc}"}
        neu, info = einfuegen(code, st)
        if neu is None:
            return {"ok": False, "error": info, "zeile": aufruf_text("halter", st)}
        name = variante or f"Topologie {str(st.get('teil') or 'Teil').rsplit('/', 1)[-1]} " \
                           f"{round(100 * float((st.get('einstellungen') or {}).get('behalten') or 0.4))} %"
        var = getattr(self, "variante", None)
        res_var: dict[str, Any] = {}
        if var is not None:
            res_var = var("anlegen", name=name, warten=False)
            if not res_var.get("ok"):
                return {"ok": False, "error": f"Variante nicht angelegt: {res_var.get('error')}"}
        model.write_text(neu, encoding="utf-8")
        job = self._submit_run(None, 0, getattr(self, "run_timeout_s", 120.0), source="agent")  # type: ignore[attr-defined]
        lauf = None
        if warten and not isinstance(job, dict):
            job.done.wait(getattr(self, "run_timeout_s", 120.0))
            lauf = {"ok": bool((job.result or {}).get("ok")), "run": (job.result or {}).get("run")}
        self._tp_status(ergebnis={**(st.get("ergebnis") or {}), "im_modell": True, "variante": res_var.get("name")})
        self._tp_senden(erzwingen=True)
        return {"ok": True, "variante": res_var.get("name") or name, "zeile": info, "lauf": lauf,
                "text": f"Als Variante „{res_var.get('name') or name}“ übernommen; model.py: {info}"}


# -- model.py anpassen ------------------------------------------------------------------------------------------------


def aufruf_text(var: str, st: dict[str, Any]) -> str:
    from kevcad_kernel.topologie import STANDARD, einstellungen

    e = einstellungen(**(st.get("einstellungen") or {}))
    args = [var]
    if st.get("szenario"):
        args.append(f"szenario={st['szenario']!r}")
    for k in ("behalten", "ueberhang", "fein", "steg", "bett", "bohrungen", "einsaetze", "kontakt", "iterationen"):
        if e.get(k) != STANDARD.get(k) or k == "behalten":
            v = e[k]
            if isinstance(v, float) and v.is_integer() and k != "behalten":
                v = int(v)
            args.append(f"{k}={v!r}")
    return f"{var} = topologie.optimieren({', '.join(args)})"


def einfuegen(code: str, st: dict[str, Any]) -> tuple[str | None, str]:
    """model.py mit ``topologie.optimieren`` hinter der Zuweisung des Druckteils (``x = lager.druckteil(…, "Name",
    …)``) und dem Import. Rückgabe (neuer Code oder None, Beschreibung bzw. Fehler)."""
    teil = str(st.get("teil") or "")
    try:
        baum = ast.parse(code)
    except SyntaxError as exc:
        return None, f"model.py lässt sich nicht lesen: {exc}"
    kandidaten = []
    for node in ast.walk(baum):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        v = node.value
        if not isinstance(v, ast.Call):
            continue
        f = v.func
        fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
        if fname != "druckteil":
            continue
        name = None
        if len(v.args) >= 2 and isinstance(v.args[1], ast.Constant) and isinstance(v.args[1].value, str):
            name = v.args[1].value
        for kw in v.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                name = kw.value.value
        if name is not None and name.strip().strip("/") in (teil, teil.rsplit("/", 1)[-1]):
            kandidaten.append(node)
    if not kandidaten:
        return None, (f"In model.py keine Zuweisung „x = lager.druckteil(…, {teil!r}, …)“ gefunden: die Zeile bitte "
                      "selbst eintragen")
    node = kandidaten[0]
    var = node.targets[0].id  # type: ignore[union-attr]
    zeilen = code.splitlines(keepends=True)
    ende = int(getattr(node, "end_lineno", node.lineno))
    einzug = zeilen[node.lineno - 1][: len(zeilen[node.lineno - 1]) - len(zeilen[node.lineno - 1].lstrip())]
    neu_zeile = einzug + aufruf_text(var, st) + "  # Kev CAD: Topologie übernommen\n"
    if ende - 1 < len(zeilen) and not zeilen[ende - 1].endswith("\n"):
        zeilen[ende - 1] += "\n"
    zeilen.insert(ende, neu_zeile)
    text = "".join(zeilen)
    if "topologie" not in {a.asname or a.name for n in ast.walk(baum) if isinstance(n, ast.ImportFrom)
                           and n.module == "kevcad" for a in n.names}:
        # Import nach dem letzten „from kevcad import …“ bzw. „import kevcad…“, sonst ganz oben
        imp = [n for n in baum.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        zeilen = text.splitlines(keepends=True)
        pos = int(getattr(imp[-1], "end_lineno", imp[-1].lineno)) if imp else 0
        zeilen.insert(pos, "from kevcad import topologie\n")
        text = "".join(zeilen)
    return text, neu_zeile.strip()

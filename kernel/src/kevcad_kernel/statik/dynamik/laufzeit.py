"""Ablauf (S2) in der Kernel-Laufzeit (Mixin für ``KernelRuntime``): MCP ``dynamik`` und ``dynamik_grenze``, Rechnung
nach jedem Lauf für die Abläufe aus model.py, Ergebnis als STATICS (Szenario mit ``ablauf``) und als Animation
„Ablauf: <Name>“ (ANIM_DEF, die Zeitleiste spielt sie ab; kein neues Protokoll für das Abspielen).

Ablauf einer Anfrage:

1. Rechenprozess (EXEC auf ``statik.dienst.auftrag``): Szenario quasistatisch (S0/S1 mit der größten Verzögerung) und
   die Szene als Datei (Körper, Gelenke, Formen, Reibwerte; ``szene.py``).
2. Eigener Prozess ``python -m kevcad_kernel.statik.dynamik.prozess``: MuJoCo, CoACD, Ablauf, Suche nach den Grenzen
   (höchstens 4 Fäden). Immer nur ein Ablauf-Prozess zugleich.
3. Laufzeit: Lagen je Bild → ANIM_DEF an die App, Urteile in das Szenario (``urteil.einbauen``) → STATICS.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

WARTEN_S = 60.0
PROZESS_S = 240.0
FAEDEN = 4


def _antrieb_aus_animation(a: Any, antrieb: str | None) -> tuple[str | None, np.ndarray | None]:
    """(Teil, Verschiebung je Bild in mm) des geschobenen Teils einer Animation: das genannte Teil bzw. die größte
    Gruppe von Teilen, die sich nur verschieben (gleiche Bahn), z. B. der ganze Wagen."""
    teile = list(a.teile)
    if not teile:
        return None, None
    M = a.matrices
    if antrieb:
        for i, n in enumerate(teile):
            if n == antrieb or n.startswith(antrieb.rstrip("/") + "/"):
                return n, M[:, i, :3, 3]
        return None, None
    gruppen: dict[tuple, list[int]] = {}
    for i, n in enumerate(teile):
        R = M[:, i, :3, :3]
        if not np.allclose(R, np.eye(3)[None], atol=1e-6):
            continue
        key = tuple(np.round(M[-1, i, :3, 3], 1)) + tuple(np.round(M[len(M) // 2, i, :3, 3], 1))
        gruppen.setdefault(key, []).append(i)
    if not gruppen:
        return None, None
    beste = max(gruppen.values(), key=len)
    D = M[:, beste[0], :3, 3]
    if float(np.max(np.linalg.norm(D[:, :2], axis=1))) < 1.0:
        return None, None
    return teile[beste[0]], D


class DynamikRuntime:
    """Erwartet ``self._lock``, ``self._send_app``, ``self.execute``, ``self.anim_hub``, ``self._pool`` und die
    Statik der Laufzeit (``_statik_voll``, ``_statik_run``, ``_statik_aktiv``, ``_statik_senden``)."""

    # -- Bausteine -----------------------------------------------------------------------------------------------------

    @property
    def _dyn_sperre(self) -> threading.Lock:
        s = self.__dict__.get("_dyn_sperre_")
        if s is None:
            s = self.__dict__.setdefault("_dyn_sperre_", threading.Lock())
        return s

    def _dyn_spins(self, animation: str | None = None) -> dict[str, list[list[float]]]:
        """Drehachsen rollender Teile (Räder) aus den Animationen des letzten Laufs (Teil → [Punkt, Richtung])."""
        out: dict[str, list[list[float]]] = {}
        hub = getattr(self, "anim_hub", None)
        if hub is None:
            return out
        for a in hub.all():
            if a.header.get("ablauf"):
                continue
            if animation and a.name != animation:
                continue
            for n, (p, d) in a.spins.items():
                out.setdefault(n, [list(p), list(d)])
        return out

    def _dyn_bahn(self, animation: str, antrieb: str | None, v_wunsch: float | None) -> dict[str, Any]:
        """Sollbahn aus einer Animation: Weg längs der Fahrtrichtung (m) über der Zeit, auf ``v_wunsch`` skaliert."""
        a = self.anim_hub.get(animation)  # type: ignore[attr-defined]
        if a is None:
            raise ValueError(self.anim_hub.unknown(animation))  # type: ignore[attr-defined]
        teil, D = _antrieb_aus_animation(a, antrieb)
        if D is None:
            raise ValueError(f"In der Animation {animation!r} verschiebt sich kein Teil"
                             + (f" {antrieb!r}" if antrieb else "") + " (Sollbahn braucht eine Fahrt).")
        d = np.array([D[-1, 0], D[-1, 1], 0.0]) if np.linalg.norm(D[-1, :2]) > 1 else \
            np.array([*D[int(np.argmax(np.linalg.norm(D[:, :2], axis=1))), :2], 0.0])
        d /= np.linalg.norm(d)
        weg = (D @ d) / 1000.0
        t = np.asarray(a.times, float)
        v_max = float(np.max(np.abs(np.gradient(weg, t)))) if len(t) > 1 else 0.0
        if v_wunsch and v_max > 1e-6:
            t = t * (v_max / float(v_wunsch))
        return {"name": animation, "zeiten": t.tolist(), "weg_m": weg.tolist(), "richtung": d.tolist(),
                "teil": teil, "v_max": v_max}

    def _dyn_exec(self, auftrag: dict[str, Any], timeout_s: float = 120.0) -> dict[str, Any]:
        """EXEC im Rechenprozess (``statik.dienst.auftrag``), Ergebnis aus der Datei."""
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

    def _dyn_prozess(self, szene_datei: str, szenarien: list[dict[str, Any]], timeout_s: float = PROZESS_S
                     ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        """Ablauf-Prozess starten und auf das Ergebnis warten (immer nur einer zugleich)."""
        ordner = Path(tempfile.mkdtemp(prefix="kevcad-ablauf-"))
        auftrag = {"szene": szene_datei, "ausgabe": str(ordner / "ergebnis.json"), "lagen": str(ordner / "lagen.npz"),
                   "szenarien": szenarien, "fps": 50, "faeden": FAEDEN}
        (ordner / "auftrag.json").write_text(json.dumps(auftrag, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, OMP_NUM_THREADS=str(FAEDEN), PYTHONUNBUFFERED="1")
        t0 = time.perf_counter()
        try:
            with self._dyn_sperre:
                # eigener Prozess, abbrechbar (Simulation: „Abbrechen“ beendet ihn, ``_dyn_abbrechen``)
                proc = subprocess.Popen([sys.executable, "-m", "kevcad_kernel.statik.dynamik.prozess",
                                         str(ordner / "auftrag.json")], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, env=env)
                self.__dict__["_dyn_proc"] = proc
                try:
                    _, stderr = proc.communicate(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise
                finally:
                    self.__dict__["_dyn_proc"] = None
            if self.__dict__.pop("_dyn_abgebrochen", False):
                raise RuntimeError("Ablauf abgebrochen")
            if not (ordner / "ergebnis.json").exists():
                raise RuntimeError(f"Ablauf-Prozess ohne Ergebnis beendet (Code {proc.returncode}): "
                                   f"{(stderr or '')[-800:]}")
            out = json.loads((ordner / "ergebnis.json").read_text(encoding="utf-8"))
            felder: dict[str, np.ndarray] = {}
            if (ordner / "lagen.npz").exists():
                with np.load(ordner / "lagen.npz") as z:
                    felder = {k: z[k] for k in z.files}
            out["prozess_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return out, felder
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Ablauf-Prozess nach {timeout_s:g} s abgebrochen") from exc
        finally:
            for p in ordner.iterdir():
                try:
                    p.unlink()
                except OSError:
                    pass
            try:
                ordner.rmdir()
            except OSError:
                pass

    def _dyn_animation(self, ablauf: dict[str, Any], felder: dict[str, np.ndarray], i: int, run: int) -> str | None:
        """Lagen je Bild als Animation „Ablauf: <Name>“ ablegen und an die App schicken (ANIM_DEF)."""
        from kevcad_kernel.animation import pack_matrices
        from kevcad_kernel.anim_runtime import StoredAnimation

        if f"lagen_{i}" not in felder:
            return None
        teile = json.loads(bytes(felder[f"teile_{i}"]).decode("utf-8"))
        lagen = np.asarray(felder[f"lagen_{i}"], float)
        zeiten = np.asarray(felder[f"zeiten_{i}"], float)
        name = ablauf["animation"]
        fps = float(ablauf.get("fps") or 50.0)
        n = len(zeiten)
        dauer = round((n - 1) / fps, 6)
        header = {"run": run, "name": name, "dauer": dauer, "fps": fps, "bilder": n, "teile": teile, "kamera": False,
                  "sichtbar": [], "standard": False, "warnungen": [], "spuren": 0, "ablauf": True}
        payload = pack_matrices(lagen)
        a = StoredAnimation(name=name, run=run, header=header, payload=payload, matrices=lagen,
                            times=np.minimum(np.arange(n) / fps, dauer))
        hub = self.anim_hub  # type: ignore[attr-defined]
        with hub.lock:
            hub.anims[name] = a
        self._send_app({"type": "ANIM_DEF", **header}, payload)  # type: ignore[attr-defined]
        return name

    def _dyn_abbrechen(self) -> bool:
        """Laufenden Ablauf-Prozess beenden (Simulation: „Abbrechen“); True, wenn einer lief."""
        p = self.__dict__.get("_dyn_proc")
        if p is None or p.poll() is not None:
            return False
        self.__dict__["_dyn_abgebrochen"] = True
        try:
            p.kill()
        except OSError:
            pass
        return True

    def _dyn_einbauen(self, name: str, ablauf: dict[str, Any], run: int | None, zeigen: bool) -> dict[str, Any] | None:
        """Ablauf in das Szenario des Statik-Ergebnisses einbauen; STATICS an die App."""
        from kevcad_kernel.statik.dynamik.urteil import einbauen

        with self._lock:  # type: ignore[attr-defined]
            voll = self._statik_voll  # type: ignore[attr-defined]
            if voll is None or (run is not None and self._statik_run != run):  # type: ignore[attr-defined]
                return None
            szen = list(voll.get("szenarien") or [])
            for i, e in enumerate(szen):
                if e.get("name") == name:
                    szen[i] = einbauen(e, ablauf)
                    neu = szen[i]
                    break
            else:
                return None
            self._statik_voll = {**voll, "szenarien": szen,  # type: ignore[attr-defined]
                                 "grenzen": list(dict.fromkeys(list(voll.get("grenzen") or [])
                                                              + list(ablauf.get("grenzen") or []))),
                                 "vereinfachungen": list(dict.fromkeys(list(voll.get("vereinfachungen") or [])
                                                                      + list(ablauf.get("vereinfachungen") or [])))}
            if zeigen:
                self._statik_aktiv = name  # type: ignore[attr-defined]
        self._statik_senden(zeigen=zeigen)  # type: ignore[attr-defined]
        return neu

    @staticmethod
    def _dyn_behalten(alt: dict[str, Any] | None, neu: dict[str, Any], ausser: str | None = None) -> dict[str, Any]:
        """Neues Statik-Ergebnis aus dem Rechenprozess (Szenario auf Anfrage): Szenarien mit fertigem oder laufendem
        Ablauf übernimmt es aus dem bisherigen Ergebnis der Laufzeit (außer dem gerade gerechneten ``ausser``)."""
        if not alt:
            return neu
        mit = {e.get("name"): e for e in alt.get("szenarien") or []
               if isinstance(e.get("ablauf"), dict) or isinstance(e.get("festkoerper"), dict)}  # Stufe 3 auch
        if not mit:
            return neu
        szen = [mit.get(e.get("name"), e) if e.get("name") != ausser else e for e in neu.get("szenarien") or []]
        return {**neu, "szenarien": szen}

    # -- Nach jedem Lauf: Abläufe aus model.py im Hintergrund ----------------------------------------------------------

    def _dynamik_nach_lauf(self, voll: dict[str, Any] | None) -> None:
        """Nach CHECK_DONE: Szenarien mit Ablauf (st.szenario(…, geschwindigkeit=…)) als „läuft“ markieren und im
        Hintergrund rechnen."""
        if not voll:
            return
        offen = [e for e in voll.get("szenarien") or [] if (e.get("szenario") or {}).get("ablauf")]
        if not offen:
            return
        for e in offen:
            e["ablauf"] = {"stand": "laeuft", "animation": f"Ablauf: {e['name']}"}
        with self._lock:  # type: ignore[attr-defined]
            run = self._statik_run  # type: ignore[attr-defined]
        self._pool.submit(self._dynamik_hintergrund, [e["name"] for e in offen], run)  # type: ignore[attr-defined]

    def _dynamik_hintergrund(self, namen: list[str], run: int | None) -> None:
        try:
            with self._lock:  # type: ignore[attr-defined]
                voll = self._statik_voll  # type: ignore[attr-defined]
                if voll is None or self._statik_run != run:  # type: ignore[attr-defined]
                    return
                eintraege = {e["name"]: e for e in voll.get("szenarien") or [] if e.get("name") in namen}
            szenarien = [self._dyn_szenario(e["name"], (e.get("szenario") or {})) for e in eintraege.values()]
            antrieb = next((s.get("antrieb_teil") for s in szenarien if s.get("antrieb_teil")), None)
            erg = self._dyn_exec({"szene": {"spins": self._dyn_spins(), "antrieb": antrieb}})
            if run is not None and erg.get("szene_run") not in (None, run):
                return
            try:
                out, felder = self._dyn_prozess(erg["szene_datei"], szenarien)
            finally:
                try:
                    os.unlink(erg["szene_datei"])
                except OSError:
                    pass
            for i, s in enumerate(out.get("szenarien") or []):
                ablauf = s.get("ablauf") or {"stand": "failed", "meldung": out.get("meldung")}
                if ablauf.get("stand") == "done":
                    self._dyn_animation(ablauf, felder, i, run or 0)
                self._dyn_einbauen(s["name"], ablauf, run, zeigen=False)
            if out.get("stand") != "done":
                for n in namen:
                    self._dyn_einbauen(n, {"stand": "failed", "meldung": out.get("meldung")}, run, zeigen=False)
        except Exception as exc:  # noqa: BLE001 - Hintergrund: als Meldung am Szenario
            for n in namen:
                try:
                    self._dyn_einbauen(n, {"stand": "failed", "meldung": f"Ablauf nicht gerechnet: "
                                                                         f"{type(exc).__name__}: {exc}"}, run, False)
                except Exception:  # noqa: BLE001
                    pass

    def _dyn_szenario(self, name: str, sz: dict[str, Any], suche: bool = True) -> dict[str, Any]:
        """Auftrag für den Ablauf-Prozess aus der Kurzfassung eines Szenarios (``Szenario.kurz``)."""
        ab = dict(sz.get("ablauf") or {})
        out: dict[str, Any] = {"name": name, "geschwindigkeit": ab.get("geschwindigkeit"), "bremsen": ab.get("bremsen"),
                               "dauer": ab.get("dauer"), "stoss": ab.get("stoss"),
                               "fahrtrichtung": ab.get("fahrtrichtung") or [1.0, 0.0, 0.0],
                               "angriff": ab.get("angriff") or "boden", "suche": suche}
        ng = sz.get("neigung")
        if ng:
            out["neigung"] = ng.get("grad")
            out["neigung_richtung"] = ng.get("richtung")
        if ab.get("animation"):
            bahn = self._dyn_bahn(ab["animation"], ab.get("antrieb"), ab.get("geschwindigkeit"))
            out["bahn"] = bahn
            out["fahrtrichtung"] = bahn["richtung"]
            out["antrieb_teil"] = ab.get("antrieb") or bahn["teil"]
        elif ab.get("antrieb"):
            out["antrieb_teil"] = ab["antrieb"]
        return out

    # -- KernelService -------------------------------------------------------------------------------------------------

    def dynamik(self, name: str, geschwindigkeit: float | None = None, bremsen: Any = None, dauer: float | None = None,
                neigung: float | None = None, richtung: Any = None, stoss: float | None = None,
                animation: str | None = None, antrieb: str | None = None, angriff: Any = None,
                fahrtrichtung: Any = None, lasten: list[dict[str, Any]] | None = None, suche: bool = True,
                zeigen: bool = True, beschreibung: str | None = None, timeout_s: float = PROZESS_S
                ) -> dict[str, Any]:
        """Ablauf (S2) mit dem Modell des letzten Laufs: Szenario quasistatisch (S0/S1) plus Simulation in einem
        eigenen Prozess; Ergebnis im Statik-Abschnitt und als Animation „Ablauf: <Name>“."""
        from kevcad_kernel.statik.rechnen import befunde
        from kevcad_kernel.statik.szenario import szenario_aus

        t0 = time.perf_counter()
        self._statik_warten()  # type: ignore[attr-defined]
        sz: dict[str, Any] = {"name": name, "beschreibung": beschreibung,
                              "ablauf": {"geschwindigkeit": geschwindigkeit, "bremsen": bremsen, "dauer": dauer,
                                         "animation": animation, "antrieb": antrieb, "angriff": angriff,
                                         "fahrtrichtung": fahrtrichtung}, "lasten": list(lasten or [])}
        if neigung is not None:
            sz["neigung"] = {"grad": float(neigung), "richtung": richtung if richtung is not None else "+x"}
        if stoss is not None:
            sz["stoss"] = {"faktor": float(stoss)}
        try:
            kurz = szenario_aus(sz, "agent").kurz()
            if not kurz.get("ablauf"):
                raise ValueError("dynamik braucht geschwindigkeit=… (m/s) oder animation=\"Name\", dazu meist "
                                 "bremsen=\"abrupt\" oder eine Verzögerung in m/s²")
            auftrag = self._dyn_szenario(name, kurz, suche=suche)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            erg = self._dyn_exec({"szenario": sz, "szene": {"spins": self._dyn_spins(animation),
                                                            "antrieb": auftrag.get("antrieb_teil")}})
        except (ValueError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        t_szene = (time.perf_counter() - t0) * 1000
        with self._lock:  # type: ignore[attr-defined]
            run = self._statik_run  # type: ignore[attr-defined]
            neu = {k: v for k, v in erg.items() if not k.startswith("szene") and k not in ("antrieb", "dienst_ms")}
            self._statik_voll = self._dyn_behalten(self._statik_voll, neu, name)  # type: ignore[attr-defined]
        try:
            out, felder = self._dyn_prozess(erg["szene_datei"], [auftrag], timeout_s=timeout_s)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                os.unlink(erg["szene_datei"])
            except OSError:
                pass
        if out.get("stand") != "done" or not out.get("szenarien"):
            return {"ok": False, "error": out.get("meldung") or "Ablauf nicht gerechnet",
                    "traceback": out.get("traceback")}
        ablauf = out["szenarien"][0]["ablauf"]
        if ablauf.get("stand") != "done":
            return {"ok": False, "error": ablauf.get("meldung") or "Ablauf nicht gerechnet",
                    "traceback": ablauf.get("traceback")}
        anim = self._dyn_animation(ablauf, felder, 0, run or 0)
        e = self._dyn_einbauen(name, ablauf, None, zeigen=bool(zeigen)) or {}
        nach = getattr(self, "_festkoerper_nach_szenario", None)  # Stufe 3: Festkörper für Teile mit Last
        if nach is not None:
            nach(name)
        gezeigt = False
        if zeigen and anim and self._link.connected:  # type: ignore[attr-defined]
            # Zeitleiste auf den Ablauf stellen, ohne auf die Antwort der App zu warten
            self._pool.submit(self._dyn_zeigen, anim)  # type: ignore[attr-defined]
            gezeigt = True
        from kevcad_kernel.statik.laufzeit import _szenario_auszug

        auszug = _szenario_auszug(e, detail=True) if e else {}
        kurz_ablauf = {k: v for k, v in ablauf.items() if k not in ("verlauf", "pfeile", "koerper")}
        return {"ok": True, "run": run, "szenario": auszug, "ablauf": kurz_ablauf, "animation": anim,
                "gezeigt": gezeigt, "befunde": befunde({"szenarien": [e]}) if e else [],
                "grenzen": ablauf.get("grenzen"), "vereinfachungen": ablauf.get("vereinfachungen"),
                "ms": {**{f"ablauf_{k}" if k == "gesamt" else k: v for k, v in (ablauf.get("ms") or {}).items()},
                       "gesamt": round((time.perf_counter() - t0) * 1000, 1), "szene_und_statik": round(t_szene, 1),
                       "prozess": out.get("prozess_ms")},
                "szene": out.get("szene"), "coacd": out.get("coacd")}

    def _dyn_zeigen(self, anim: str) -> None:
        try:
            self.animation_seek(0.0, anim)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - App antwortet nicht: nur kein Sprung
            pass

    def dynamik_grenze(self, ohne: str = "beides", bremsen: Any = "abrupt", geschwindigkeit: float = 1.0,
                       name: str | None = None, **kw: Any) -> dict[str, Any]:
        """„Wie schnell darf ich schieben, ohne dass der Ball herausspringt bzw. das Rig kippt?“ – Suche über die
        Geschwindigkeit (Rollouts) bei der Bremsart ``bremsen``; dazu die Verzögerung, ab der es abhebt."""
        name = name or f"Grenze: bremsen {bremsen}"
        res = self.dynamik(name, geschwindigkeit=geschwindigkeit, bremsen=bremsen, suche=True, **kw)
        if not res.get("ok"):
            return res
        kz = (res.get("ablauf") or {}).get("kennzahlen") or {}
        grenzen: dict[str, Any] = {}
        if ohne in ("kippen", "beides"):
            grenzen["kippen"] = {"v_abheben": kz.get("v_abheben"), "a_abheben": kz.get("a_abheben"),
                                 "a_kipp_hand": kz.get("a_kipp_hand"),
                                 "a_abheben_ohne_ladung": kz.get("a_abheben_ohne_ladung")}
        if ohne in ("ball", "ladung", "beides"):
            grenzen["ladung"] = [{"name": L["name"], "v_grenze": L.get("v_grenze"), "nie_bis": L.get("v_grenze_bis")
                                  if L.get("v_grenze_nie") else None} for L in kz.get("ladung") or []]
        return {**res, "grenzen_suche": grenzen, "frage": ohne, "bremsen": bremsen}

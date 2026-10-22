"""Statik in der Kernel-Laufzeit (Mixin für ``KernelRuntime``): ``statik``, ``szenario_rechnen`` und die Nachricht
STATICS an die App.

Nach jedem Lauf rechnet der Prüfer „statik“ im Rechenprozess; das volle Ergebnis kommt im CHECK-Kopf (Feld ``statik``).
``_statik_check`` nimmt es dort heraus (im CHECK an die App und im Versionsarchiv bleibt die Kurzfassung), merkt es und
schickt es als STATICS. ``szenario_rechnen`` rechnet ein neues Szenario im Rechenprozess (EXEC auf
``statik.dienst.auftrag``, Ergebnis als Datei), ohne neuen Lauf, und zeigt es in der App.
"""

from __future__ import annotations

import ast
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

WARTEN_S = 60.0


def _szenario_auszug(e: dict[str, Any], detail: bool = True) -> dict[str, Any]:
    """Ein Szenario für den Agenten: Ampel, Kennzahlen, Urteile; mit ``detail`` Stäbe, Bauteile, Lager, S0."""
    out = {"name": e.get("name"), "ampel": e.get("ampel"), "text": e.get("text"), "ziel": e.get("ziel"),
           "szenario": e.get("szenario"), "kennzahlen": e.get("kennzahlen"),
           "urteile": [{k: v for k, v in u.items() if k != "alternative"} | (
               {"alternative": {k: u["alternative"].get(k) for k in ("name", "stock_id", "ersparnis_kg",
                                                                     "ersparnis_eur", "sicherheit")}}
               if isinstance(u.get("alternative"), dict) else {}) for u in e.get("urteile") or []]}
    if detail:
        out["staebe"] = [{k: s.get(k) for k in ("name", "sicherheit", "ampel", "radius")}
                         | {"ausnutzung_max": max(s.get("ausnutzung") or [0.0]),
                            "verschiebung_max_mm": max((sum(c * c for c in v) ** 0.5
                                                        for v in s.get("verschiebung") or []), default=0.0)}
                         for s in e.get("staebe") or []]
        out["stabwerte"] = e.get("stabwerte")
        out["teile"] = e.get("teile")
        out["auflager"] = e.get("auflager")
        s0 = e.get("s0") or {}
        out["kippen"] = s0.get("kippen")
        out["rutschen"] = s0.get("rutschen")
        out["lose"] = s0.get("lose")
        out["schrauben"] = s0.get("schrauben")
        out["s1"] = e.get("s1")
    return out


class StatikRuntime:
    """Erwartet ``self._pruef``, ``self._lock``, ``self._send_app``, ``self.execute`` der Laufzeit."""

    _statik_voll: dict[str, Any] | None = None
    _statik_run: int | None = None
    _statik_aktiv: str | None = None

    # -- Rechenprozess → Laufzeit → App --------------------------------------------------------------------------------

    def _statik_check(self, check: dict[str, Any]) -> dict[str, Any] | None:
        """CHECK_DONE: volles Statik-Ergebnis aus dem Kopf nehmen (dort bleibt die Kurzfassung) und merken."""
        from kevcad_kernel.protocol import statik_kurz

        voll = check.pop("statik", None)
        if not isinstance(voll, dict):
            return None
        check["statik"] = statik_kurz(voll)
        try:
            from kevcad_kernel.versionen.laufzeit import SCHATTEN_RUN_BASIS
        except Exception:  # noqa: BLE001
            SCHATTEN_RUN_BASIS = 1_000_000_000  # noqa: N806
        run = int(check.get("run") or 0)
        if run >= SCHATTEN_RUN_BASIS:
            return None
        with self._lock:  # type: ignore[attr-defined]
            if self._statik_run == run and self._statik_voll is not None:
                # zweites CHECK desselben Laufs (teilweise → done): gleiche Statik, Szenarien des Agenten behalten
                return None
            self._statik_voll, self._statik_run, self._statik_aktiv = voll, run, None
        return voll

    def _statik_senden(self, reply_to: str | None = None, zeigen: bool = False) -> bool:
        from kevcad_kernel.protocol import pack_statics

        with self._lock:  # type: ignore[attr-defined]
            voll, run, aktiv = self._statik_voll, self._statik_run, self._statik_aktiv
        if voll is None:
            return False
        head = pack_statics(voll, run=run or 0, aktiv=aktiv, reply_to=reply_to, zeigen=zeigen)
        head.pop("seq", None)
        return bool(self._send_app(head))  # type: ignore[attr-defined]

    def _statik_on_connect(self, conn: Any) -> None:
        from kevcad_kernel.protocol import pack_statics

        with self._lock:  # type: ignore[attr-defined]
            voll, run, aktiv = self._statik_voll, self._statik_run, self._statik_aktiv
        if voll is not None:
            head = pack_statics(voll, run=run or 0, aktiv=aktiv)
            head.pop("seq", None)
            conn.send(head)

    # -- KernelService -------------------------------------------------------------------------------------------------

    def _statik_warten(self) -> None:
        stand = self._pruef  # type: ignore[attr-defined]
        if stand.erwartet is not None:
            stand.warte(stand.erwartet, WARTEN_S)

    def statik(self, szenario: str | None = None) -> dict[str, Any]:
        """Ergebnis der Statik des letzten Laufs: alle Szenarien mit Ampel und Kennzahlen oder eines ausführlich."""
        self._statik_warten()
        with self._lock:  # type: ignore[attr-defined]
            voll, run = self._statik_voll, self._statik_run
        if voll is None:
            return {"ok": False, "error": "Noch keine Statik: erst run aufrufen (die Statik rechnet nach jedem Lauf "
                                          "mit, sobald die Prüfung fertig ist)."}
        szen = voll.get("szenarien") or []
        base = {"ok": True, "run": run, "aktiv": voll.get("aktiv"), "grenzen": voll.get("grenzen"),
                "vereinfachungen": voll.get("vereinfachungen"), "modell": voll.get("modell"), "ms": voll.get("ms"),
                "ueberdimensioniert": voll.get("ueberdimensioniert"), "auf_rollen": voll.get("auf_rollen"),
                "untergrund": voll.get("untergrund")}
        if szenario:
            e = next((x for x in szen if x.get("name") == szenario), None)
            if e is None:
                import difflib

                tips = difflib.get_close_matches(szenario, [x.get("name") for x in szen], n=3, cutoff=0.3)
                return {"ok": False, "error": f"Szenario {szenario!r} gibt es nicht (vorhanden: "
                                              f"{', '.join(repr(x.get('name')) for x in szen)})"
                                              + (f"; meinten Sie {tips[0]!r}?" if tips else "")}
            with self._lock:  # type: ignore[attr-defined]
                self._statik_aktiv = szenario
            self._statik_senden(zeigen=True)
            return {**base, "szenario": _szenario_auszug(e, detail=True)}
        return {**base, "szenarien": [_szenario_auszug(e, detail=False) for e in szen]}

    def szenario_rechnen(self, name: str, beschleunigung: Any = None, neigung: float | None = None,
                         richtung: Any = None, lasten: list[dict[str, Any]] | None = None, stoss: float | None = None,
                         ziel: float | None = None, beschreibung: str | None = None, zeigen: bool = True,
                         timeout_s: float = 60.0) -> dict[str, Any]:
        """Neues Szenario mit dem Modell des letzten Laufs rechnen (ohne neuen Lauf), in der App zeigen."""
        t0 = time.perf_counter()
        self._statik_warten()
        sz: dict[str, Any] = {"name": name, "beschreibung": beschreibung}
        if beschleunigung is not None:
            sz["beschleunigung"] = list(beschleunigung)
        if neigung is not None:
            sz["neigung"] = {"grad": float(neigung), "richtung": richtung if richtung is not None else "+x"}
        if stoss is not None:
            sz["stoss"] = {"faktor": float(stoss)}
        if ziel is not None:
            sz["ziel"] = float(ziel)
        sz["lasten"] = list(lasten or [])
        auftrag = json.dumps({"szenario": sz}, ensure_ascii=False)
        code = (f"__import__('kevcad_kernel.statik.dienst', fromlist=['auftrag']).auftrag({auftrag!r})")
        res = self.execute(code, timeout_s=timeout_s)  # type: ignore[attr-defined]
        if not res.get("ok"):
            return {"ok": False, "error": f"Statik im Rechenprozess fehlgeschlagen: {res.get('error')}"}
        pfad: Path | None = None
        try:
            pfad = Path(ast.literal_eval(str(res.get("result"))))
            erg = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Ergebnis der Statik nicht lesbar: {type(exc).__name__}: {exc}"}
        finally:
            if pfad is not None:
                try:
                    os.unlink(pfad)
                except OSError:
                    pass
        if erg.get("stand") != "done":
            return {"ok": False, "error": erg.get("meldung") or "Statik nicht gerechnet"}
        with self._lock:  # type: ignore[attr-defined]
            run = self._statik_run
            self._statik_voll = erg
            self._statik_aktiv = name if zeigen else None
        gezeigt = self._statik_senden(zeigen=bool(zeigen)) and bool(zeigen)
        e = next((x for x in erg.get("szenarien") or [] if x.get("name") == name), None)
        return {"ok": True, "run": run, "szenario": _szenario_auszug(e or {}, detail=True), "gezeigt": gezeigt,
                "grenzen": erg.get("grenzen"), "vereinfachungen": erg.get("vereinfachungen"),
                "ms": round((time.perf_counter() - t0) * 1000, 1), "rechnen_ms": erg.get("dienst_ms")}


def aufwaermen_im_hintergrund() -> None:
    """PyNite im Rechenprozess vorab laden (Faden, blockiert nichts)."""
    from kevcad_kernel.statik.dienst import aufwaermen

    threading.Thread(target=aufwaermen, name="statik-aufwaermen", daemon=True).start()

"""In der Kernel-Laufzeit: Stand der Prüfung je Lauf (für die App, das MCP-Werkzeug ``run``, ``status`` und die
Export-Sperre).

Ablauf: Nach ``RUN_END`` schickt die Laufzeit ``CHECK`` mit ``state: "running"`` und merkt sich den Lauf als offen
(``erwarte``). Kommt ``CHECK_DONE`` aus dem Rechenprozess, legt ``fertig`` das Ergebnis ab und weckt alle, die darauf
warten (``warte``). Befunde mit ``schwere: "fehler"`` sperren den Export, gleich aus welcher Prüfung sie stammen.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from kevcad_kernel.pruefung.befund import offen as offene_befunde

ENDZUSTAENDE = ("done", "failed", "cancelled")


class PruefStand:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.header: dict[str, Any] | None = None  # letztes fertiges CHECK (mit type)
        self.payload: bytes = b""
        self.erwartet: int | None = None  # Lauf, dessen Prüfung noch läuft
        self._zustand: dict[int, str] = {}  # Lauf → letzter Zustand

    # -- Laufzeit --------------------------------------------------------------------------------------------------

    def erwarte(self, run: int) -> bool:
        """Lauf ``run`` ist fertig, seine Prüfung läuft. False, wenn das Ergebnis schon da ist (der Rechenprozess
        prüft direkt nach RUN_DONE und kann schneller sein als die Laufzeit mit RUN_END)."""
        with self._cond:
            if self._zustand.get(run) in ENDZUSTAENDE:
                return False
            self.erwartet = run
            self._zustand[run] = "running"
            if len(self._zustand) > 200:
                for k in sorted(self._zustand)[:100]:
                    self._zustand.pop(k, None)
            return True

    def fuer_lauf(self, run: int) -> tuple[dict[str, Any] | None, bytes]:
        """Fertiges CHECK genau dieses Laufs (oder None)."""
        with self._cond:
            if self.header is not None and int(self.header.get("run") or 0) == run:
                return dict(self.header), self.payload
            return None, b""

    def fertig(self, header: dict[str, Any], payload: bytes) -> bool:
        """Ergebnis aus dem Rechenprozess. True, wenn es an die App gehen soll (nicht von einem überholten Lauf)."""
        run = int(header.get("run") or 0)
        state = str(header.get("state") or "done")
        with self._cond:
            self._zustand[run] = state
            if self.erwartet == run:
                self.erwartet = None
            neuer = self.header is None or run >= int(self.header.get("run") or 0)
            if state in ("done", "failed") and neuer:
                self.header = {**header, "type": "CHECK"}
                self.payload = payload if state == "done" else b""
            self._cond.notify_all()
            return neuer and state != "cancelled"

    def abbrechen(self, grund: str) -> None:
        """Rechenprozess beendet oder Projekt gewechselt: offene Prüfung gilt als abgebrochen."""
        with self._cond:
            if self.erwartet is not None:
                self._zustand[self.erwartet] = "cancelled"
                self.erwartet = None
            self._cond.notify_all()

    def reset(self) -> None:
        with self._cond:
            self.header, self.payload, self.erwartet = None, b"", None
            self._zustand.clear()
            self._cond.notify_all()

    # -- Abfragen --------------------------------------------------------------------------------------------------

    def warte(self, run: int, timeout: float) -> dict[str, Any] | None:
        """Wartet auf die Prüfung von Lauf ``run``. Ergebnis (CHECK-Kopf) oder ein Kopf mit ``state`` "cancelled" /
        "running" (Zeitlimit) bzw. None, wenn der Lauf gar nicht geprüft wird."""
        ende = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                z = self._zustand.get(run)
                if z is None:
                    return None
                if z in ("done", "failed") and self.header is not None and int(self.header.get("run") or 0) == run:
                    return dict(self.header)
                if z in ENDZUSTAENDE:
                    return {"type": "CHECK", "run": run, "state": z, "befunde": [],
                            "message": "Prüfung abgebrochen (neuerer Lauf)" if z == "cancelled" else None}
                rest = ende - time.monotonic()
                if rest <= 0:
                    return {"type": "CHECK", "run": run, "state": "running", "befunde": [],
                            "message": "Prüfung läuft noch"}
                self._cond.wait(min(rest, 0.5))

    def letztes(self) -> tuple[dict[str, Any] | None, bytes]:
        with self._cond:
            return (dict(self.header) if self.header else None), self.payload

    def offen(self, warten_s: float = 0.0) -> tuple[list[dict[str, Any]], bool]:
        """(Befunde mit schwere "fehler" der letzten fertigen Prüfung, ob noch eine Prüfung läuft). Läuft eine,
        wird bis zu ``warten_s`` auf sie gewartet."""
        with self._cond:
            run = self.erwartet
        if run is not None and warten_s > 0:
            self.warte(run, warten_s)
        with self._cond:
            befunde = list((self.header or {}).get("befunde") or [])
            return offene_befunde(befunde), self.erwartet is not None

    def kurz(self) -> dict[str, Any] | None:
        """Für ``status``: Lauf, Zustand, Zusammenfassung, Zähler."""
        with self._cond:
            h = self.header
            out = None
            if h is not None:
                out = {"run": h.get("run"), "state": h.get("state"), "zusammenfassung": h.get("zusammenfassung"),
                       "zaehler": h.get("zaehler"), "befunde": len(h.get("befunde") or [])}
            if self.erwartet is not None:
                out = {**(out or {}), "laeuft": self.erwartet}
            return out


def fuer_ergebnis(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """Teil des Laufergebnisses (MCP run): Zustand, Zusammenfassung, Zähler, Befunde, Statistik."""
    if check is None:
        return None
    out = {k: check.get(k) for k in ("state", "message", "zusammenfassung", "zaehler", "befunde", "duration_ms",
                                     "gewinde", "erlaubt", "statistik") if check.get(k) is not None}
    if check.get("druck"):  # Druckprüfung: Ausrichtung je Druckteil, ihre Hinweise nur über druckpruefung
        from kevcad_kernel.druck.bericht import druck_kurz, ohne_druckhinweise

        out["befunde"], n = ohne_druckhinweise(out.get("befunde") or [])
        out["druck"] = {**druck_kurz(check["druck"]), "hinweise_nur_in_druckpruefung": n}
    return out

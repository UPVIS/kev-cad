"""In der Kernel-Laufzeit: Stand der Prüfung je Lauf (für die App, das MCP-Werkzeug ``run``, ``status`` und die
Export-Sperre).

Ablauf: Nach ``RUN_END`` schickt die Laufzeit ``CHECK`` mit ``state: "running"`` und merkt sich den Lauf als offen
(``erwarte``). Kommt ``CHECK_DONE`` aus dem Rechenprozess, legt ``fertig`` das Ergebnis ab und weckt alle, die darauf
warten (``warte``). Befunde mit ``schwere: "fehler"`` sperren den Export, gleich aus welcher Prüfung sie stammen.

``state: "teilweise"`` (Prüftempo, 22.10.2026): Das Ergebnis steht, nur der Bewegungsraum hat das Zeitlimit des Laufs
erreicht und wird im Rechenprozess fertig gerechnet (``im_hintergrund``: die offenen Wege). Danach kommt für denselben
Lauf ein zweites ``CHECK_DONE`` mit ``state: "done"``. ``warte`` gibt das teilweise Ergebnis zurück (``run`` wartet
nicht auf den Hintergrund), ``warte(..., endstand=True)`` wartet auf den Endstand (``pruefen(warten=True)``).

Statik im Hintergrund (T34, ``statik/laufzeit.py``): Rechnen Ablauf (S2) oder Festkörper (S3) nach dem Lauf noch,
ist das CHECK ebenfalls ``teilweise``, mit ``statik_im_hintergrund`` (etwa ``Festkörper „Bremsen“``). Sind sie fertig,
trägt die Laufzeit ihre Befunde nach (``statik_dyn_*``, ``statik_festkoerper``) und meldet ``done``.
``statik_hintergrund`` ist der Lauf, für den das aussteht; ``warte(..., endstand=True)`` wartet auch darauf, die
Export-Sperre (``offen``) nicht: Statik-Befunde sind höchstens Warnungen (T10).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from kevcad_kernel.pruefung.befund import offen as offene_befunde

ENDZUSTAENDE = ("done", "failed", "cancelled")
ERGEBNIS = ("done", "failed", "teilweise")  # Zustände mit Ergebnis (teilweise: Bewegungsraum rechnet noch)


class PruefStand:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.header: dict[str, Any] | None = None  # letztes fertiges CHECK (mit type)
        self.payload: bytes = b""
        self.erwartet: int | None = None  # Lauf, dessen Prüfung noch läuft
        self.hintergrund: int | None = None  # Lauf, dessen Ergebnis teilweise ist (Bewegungsraum rechnet weiter)
        self.statik_hintergrund: int | None = None  # Lauf, dessen Ablauf bzw. Festkörper noch rechnet (T34)
        self._zustand: dict[int, str] = {}  # Lauf → letzter Zustand

    # -- Laufzeit --------------------------------------------------------------------------------------------------

    def erwarte(self, run: int) -> bool:
        """Lauf ``run`` ist fertig, seine Prüfung läuft. False, wenn das Ergebnis schon da ist (der Rechenprozess
        prüft direkt nach RUN_DONE und kann schneller sein als die Laufzeit mit RUN_END)."""
        with self._cond:
            if self._zustand.get(run) in ENDZUSTAENDE:
                return False
            if self.hintergrund is not None and self.hintergrund < run:
                # neuer Lauf: der Rechenprozess bricht das Fertigrechnen des alten ab, es bleibt teilweise
                self.hintergrund = None
                self._cond.notify_all()
            if self.statik_hintergrund is not None and self.statik_hintergrund < run:
                self.statik_hintergrund = None  # neuer Lauf: Ablauf und Festkörper des alten verfallen
                self._cond.notify_all()
            if self._zustand.get(run) == "teilweise":
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
            if state in ERGEBNIS and neuer:
                self.header = {**header, "type": "CHECK"}
                self.payload = payload if state != "failed" else b""
            if state == "teilweise" and neuer and header.get("im_hintergrund"):
                self.hintergrund = run  # leer: das Fertigrechnen ist gescheitert, es kommt nichts mehr
            elif self.hintergrund is not None and self.hintergrund <= run:
                self.hintergrund = None
            if state == "teilweise" and neuer and header.get("statik_im_hintergrund"):
                self.statik_hintergrund = run  # Ablauf oder Festkörper rechnen noch (T34)
            elif self.statik_hintergrund is not None and self.statik_hintergrund <= run:
                self.statik_hintergrund = None
            self._cond.notify_all()
            return neuer and state != "cancelled"

    def abbrechen(self, grund: str) -> None:
        """Rechenprozess beendet oder Projekt gewechselt: offene Prüfung gilt als abgebrochen."""
        with self._cond:
            if self.erwartet is not None:
                self._zustand[self.erwartet] = "cancelled"
                self.erwartet = None
            self.hintergrund = None  # das Fertigrechnen ist mit dem Rechenprozess weg; das Ergebnis bleibt teilweise
            # Ablauf und Festkörper laufen in eigenen Prozessen der Laufzeit weiter (statik_hintergrund bleibt)
            self._cond.notify_all()

    def reset(self) -> None:
        with self._cond:
            self.header, self.payload, self.erwartet, self.hintergrund = None, b"", None, None
            self.statik_hintergrund = None
            self._zustand.clear()
            self._cond.notify_all()

    # -- Abfragen --------------------------------------------------------------------------------------------------

    def warte(self, run: int, timeout: float, endstand: bool = False, statik: bool = True) -> dict[str, Any] | None:
        """Wartet auf die Prüfung von Lauf ``run``. Ergebnis (CHECK-Kopf) oder ein Kopf mit ``state`` "cancelled" /
        "running" (Zeitlimit) bzw. None, wenn der Lauf gar nicht geprüft wird. Ein teilweises Ergebnis (Bewegungsraum
        oder Statik rechnen im Hintergrund) kommt sofort zurück; mit ``endstand`` wird auf das fertige gewartet, solange
        daran gerechnet wird (sonst bleibt es teilweise, etwa nach einem neueren Lauf). ``statik=False``: nur auf den
        Bewegungsraum warten, nicht auf Ablauf und Festkörper (Export, Bedingungen)."""
        ende = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while True:
                z = self._zustand.get(run)
                if z is None:
                    return None
                eigenes = self.header is not None and int(self.header.get("run") or 0) == run
                if z in ("done", "failed") and eigenes:
                    return dict(self.header)  # type: ignore[arg-type]
                rechnet = self.hintergrund == run or (statik and self.statik_hintergrund == run)
                if z == "teilweise" and eigenes and (not endstand or not rechnet):
                    return dict(self.header)  # type: ignore[arg-type]
                if z in ENDZUSTAENDE or (z == "teilweise" and not eigenes):
                    return {"type": "CHECK", "run": run, "state": "cancelled", "befunde": [],
                            "message": "Prüfung abgebrochen (neuerer Lauf)"}
                rest = ende - time.monotonic()
                if rest <= 0:
                    if z == "teilweise":
                        return dict(self.header)  # type: ignore[arg-type]
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
            run = self.erwartet if self.erwartet is not None else self.hintergrund
        if run is not None and warten_s > 0:
            self.warte(run, warten_s, endstand=True, statik=False)  # Statik sperrt den Export nicht (T10)
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
            if self.hintergrund is not None:
                out = {**(out or {}), "hintergrund": self.hintergrund}
            if self.statik_hintergrund is not None:
                out = {**(out or {}), "statik_hintergrund": self.statik_hintergrund}
            return out


def fuer_ergebnis(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """Teil des Laufergebnisses (MCP run): Zustand, Zusammenfassung, Zähler, Befunde, Statistik."""
    if check is None:
        return None
    out = {k: check.get(k) for k in ("state", "message", "zusammenfassung", "zaehler", "befunde", "duration_ms",
                                     "gewinde", "erlaubt", "statistik", "im_hintergrund", "statik_im_hintergrund")
           if check.get(k) is not None}
    if check.get("druck"):  # Druckprüfung: Ausrichtung je Druckteil, ihre Hinweise nur über druckpruefung
        from kevcad_kernel.druck.bericht import druck_kurz, ohne_druckhinweise

        out["befunde"], n = ohne_druckhinweise(out.get("befunde") or [])
        out["druck"] = {**druck_kurz(check["druck"]), "hinweise_nur_in_druckpruefung": n}
    if check.get("statik"):  # Statik: Kurzfassung je Szenario (Ampel, Kennzahlen); ausführlich über MCP statik
        out["statik"] = check["statik"]
    return out

"""Druckprüfung in der Kernel-Laufzeit: ``KernelService.druckpruefung`` (Mixin für ``KernelRuntime``).

Rechnet nichts neu: Die Prüfung läuft nach jedem Lauf im Rechenprozess (Prüfer „druck“), das Ergebnis steht im letzten
CHECK (Feld ``druck`` und die Befunde mit ``wert.pruefung == "druck"``). Läuft gerade eine Prüfung, wartet das
Werkzeug auf sie.
"""

from __future__ import annotations

from typing import Any

WARTEN_S = 60.0


class DruckRuntime:
    """Erwartet ``self._pruef`` (``PruefStand``) und ``self.scene`` (``refs.Scene``) der Laufzeit."""

    def druckpruefung(self, teil: str | None = None) -> dict[str, Any]:
        from kevcad_kernel.druck.bericht import druck_auszug

        stand = self._pruef  # type: ignore[attr-defined]
        laeuft = stand.erwartet
        if laeuft is not None:
            stand.warte(laeuft, WARTEN_S)
        check, _ = stand.letztes()
        try:
            namen = list(self.scene.names())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            namen = []
        return druck_auszug(check, teil, namen)

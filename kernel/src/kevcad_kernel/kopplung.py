"""I-6 Live-Kopplung (PLAN-IPAD.md, Abschnitt 5; PROTOCOL.md, „I-6 Live-Kopplung“).

Jedes Gerät (Mac-App, iPad über die Mac-App) ist im Kernel eine App-Verbindung (app_link.py). Hier steht, was zwischen
den Geräten live geteilt wird:

- **Ansicht:** Ein Gerät in der Gemeinsamen Ansicht schickt bei jeder Änderung durch Kevin ``ANSICHT`` (Kamera, Sicht,
  Auswahl, Darstellung, Schnitt, Explosion; je Teil nur, was sich geändert hat). Der Kernel reicht sie an die anderen
  Geräte der Gemeinsamen Ansicht weiter, wenn das Gerät führt. Führung hat, wer zuletzt bedient: Ein neuer Griff
  (``griff``) übernimmt sofort, sonst erst nach ``FUEHRUNG_PAUSE_S`` Ruhe des führenden Geräts. Der Kernel merkt sich
  den Stand und gibt ihn einem Gerät, das in die Gemeinsame Ansicht wechselt.
- **Geräte:** ``GERAETE`` an jedes Gerät (mit ``ich``), sobald sich Verbindungen, Ansicht, Führung oder das aktive
  Gerät ändern.
- **Sprechen:** ``SPRECHEN_LIVE`` (Striche, Zeiger, Text) geht an alle anderen Geräte, auch in der Eigenen Ansicht.

Nur Verbindungen mit der Fähigkeit ``ansicht-1`` nehmen teil; ältere Apps bekommen nichts davon (Weiche in live.py).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kevcad_kernel.protocol import (
    ANSICHT_MODI, ANSICHT_TEILE, ANSICHT_TEILE_VOLL, FAEHIGKEIT_ANSICHT, FUEHRUNG_PAUSE_S, kanonisch,
)

if TYPE_CHECKING:
    from kevcad_kernel.app_link import AppConnection, AppLink


def nimmt_teil(conn: AppConnection) -> bool:
    """Kennt die App die Live-Kopplung (``ansicht-1`` in HELLO_APP)?"""
    f = conn.info.get("faehigkeiten")
    return isinstance(f, list) and FAEHIGKEIT_ANSICHT in f


class Kopplung:
    def __init__(self, link: AppLink, log: Callable[[str], None] | None = None) -> None:
        self._link = link
        self._log = log or (lambda zeile: None)
        self._lock = threading.Lock()
        self._fuehrt_t = 0.0  # monotone Zeit der letzten angenommenen ANSICHT des führenden Geräts
        self._stand: dict[str, Any] = {}  # letzte Teile der Gemeinsamen Ansicht
        self._gemeldet: dict[int, str] = {}  # zuletzt geschickte Geräteliste je Verbindung (kanonisch)
        self.zaehler = {"weiter": 0, "verworfen": 0, "fuehrung": 0, "live": 0}
        link.on_aktiv = self.geraete_melden

    # -- Nachrichten der Apps ------------------------------------------------------------------------------------------

    def hallo(self, conn: AppConnection) -> None:
        """Nach HELLO_APP: Eine App mit ``ansicht-1`` beginnt in der Gemeinsamen Ansicht, bis sie anderes meldet."""
        if nimmt_teil(conn):
            conn.info.setdefault("ansicht", "gemeinsam")
            self._stand_geben(conn)
        self.geraete_melden()

    def nachricht(self, conn: AppConnection, art: str, header: dict[str, Any]) -> None:
        if art == "ANSICHT_MODUS":
            self.modus(conn, header.get("modus"))
        elif art == "ANSICHT":
            self.ansicht(conn, header)
        elif art == "SPRECHEN_LIVE":
            self.sprechen(conn, header)

    def modus(self, conn: AppConnection, modus: Any) -> None:
        if modus not in ANSICHT_MODI:
            self._log(f"[kopplung] Unbekannte Ansicht {modus!r} von Nr. {conn.number}")
            return
        vorher = conn.info.get("ansicht")
        conn.info["ansicht"] = modus
        with self._lock:
            if modus == "eigen" and self._link.fuehrt is conn:
                self._link.fuehrt = None
        if modus == "gemeinsam" and vorher != "gemeinsam":
            self._stand_geben(conn)
        self.geraete_melden()

    def ansicht(self, conn: AppConnection, header: dict[str, Any]) -> None:
        """ANSICHT eines Geräts: annehmen, wenn es führt oder die Führung übernehmen darf, dann an die anderen Geräte der
        Gemeinsamen Ansicht."""
        if conn.info.get("ansicht") != "gemeinsam":
            return  # Eigene Ansicht: nichts teilen
        teile = {k: header[k] for k in ANSICHT_TEILE if k in header}
        if not teile:
            return
        jetzt = time.monotonic()
        with self._lock:
            f = self._link.fuehrt
            frei = f is None or f.closed or f.info.get("ansicht") != "gemeinsam"
            if not (frei or f is conn or header.get("griff") is True or jetzt - self._fuehrt_t >= FUEHRUNG_PAUSE_S):
                self.zaehler["verworfen"] += 1
                return
            wechsel = f is not conn
            self._link.fuehrt = conn
            self._fuehrt_t = jetzt
            # Auch ein voller Stand ergänzt nur: Apps vor dem 07.11.2026 kennen ``flaeche`` nicht, die zuletzt geteilte
            # Fläche bleibt dann stehen
            self._stand.update(teile)
            self.zaehler["weiter"] += 1
            if wechsel:
                self.zaehler["fuehrung"] += 1
        self._link.bedient(conn)  # Kevin arbeitet an diesem Gerät (meldet bei Wechsel die Geräte)
        weiter = {"type": "ANSICHT", "t": header.get("t"), "griff": bool(header.get("griff")),
                  "voll": bool(header.get("voll")), "von": conn.number, **teile}
        for c in self._link.verbindungen:
            if c is not conn and nimmt_teil(c) and c.info.get("ansicht") == "gemeinsam":
                c.send(weiter)
        if wechsel:
            self.geraete_melden()

    def sprechen(self, conn: AppConnection, header: dict[str, Any]) -> None:
        """Live-Striche, Zeiger und Text beim Sprechen: an alle anderen Geräte, auch in der Eigenen Ansicht."""
        weiter = {k: v for k, v in header.items() if k not in ("seq", "id")}
        weiter["von"] = conn.number
        self.zaehler["live"] += 1
        for c in self._link.verbindungen:
            if c is not conn and nimmt_teil(c):
                c.send(weiter)

    def getrennt(self, conn: AppConnection) -> None:
        with self._lock:
            if self._link.fuehrt is conn:
                self._link.fuehrt = None
            self._gemeldet.pop(conn.number, None)
        self.geraete_melden()

    # -- Stand und Geräte ----------------------------------------------------------------------------------------------

    def _stand_geben(self, conn: AppConnection) -> None:
        """Ein Gerät kommt in die Gemeinsame Ansicht: Es übernimmt den Stand des führenden Geräts (falls es einen gibt)."""
        with self._lock:
            f = self._link.fuehrt
            stand = dict(self._stand) if f is not None and f is not conn and not f.closed else {}
            von = f.number if f is not None else None
        if stand and all(k in stand for k in ANSICHT_TEILE_VOLL):  # flaeche fehlt bei Apps vor dem 07.11.2026
            conn.send({"type": "ANSICHT", "t": time.time(), "griff": False, "voll": True, "von": von, **stand})

    def stand(self) -> dict[str, Any]:
        """Für status: letzter Stand der Gemeinsamen Ansicht (Kamera usw.) und wer führt."""
        with self._lock:
            f = self._link.fuehrt
            return {"fuehrt": f.number if f is not None and not f.closed else None, "teile": sorted(self._stand),
                    "zaehler": dict(self.zaehler)}

    def geraete_melden(self) -> None:
        """GERAETE an jedes teilnehmende Gerät, wenn sich seine Sicht der Liste geändert hat."""
        liste = self._link.geraete()
        for c in self._link.verbindungen:
            if not nimmt_teil(c):
                continue
            eigene = [{**g, "ich": g["nr"] == c.number} for g in liste]
            text = kanonisch(eigene)
            with self._lock:
                if self._gemeldet.get(c.number) == text:
                    continue
                self._gemeldet[c.number] = text
            c.send({"type": "GERAETE", "geraete": eigene})


def geraete_text(geraete: list[dict[str, Any]]) -> str | None:
    """Zeile für status und das Lagebild zum Feedback: welche Geräte verbunden sind, welches aktiv ist und wie sie die
    Ansicht teilen. None bei nur einem Gerät ohne Kopplung (dann gibt es nichts zu sagen)."""
    if not geraete or (len(geraete) == 1 and geraete[0].get("art") != "ipad"):
        return None
    teile: list[str] = []
    for g in geraete:
        art = "iPad" if g.get("art") == "ipad" else "Mac"
        name = g.get("name") or art
        merkmale = [art] if name != art else []
        if g.get("aktiv"):
            merkmale.append("aktiv")
        if g.get("ansicht") == "gemeinsam":
            merkmale.append("führt die Gemeinsame Ansicht" if g.get("fuehrt") else "Gemeinsame Ansicht")
        elif g.get("ansicht") == "eigen":
            merkmale.append("Eigene Ansicht")
        teile.append(f"{name} ({', '.join(merkmale)})" if merkmale else name)
    return ("Geräte: " + " · ".join(teile) + ". Ansichtsbefehle gehen an die Gemeinsame Ansicht und das aktive Gerät; "
            "Lagebild und Bilder kommen vom aktiven Gerät.")

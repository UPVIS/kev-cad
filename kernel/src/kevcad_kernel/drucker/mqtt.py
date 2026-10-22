"""MQTT-Verbindung zum Drucker (paho-mqtt, EPL-2.0/EDL-1.0): TLS auf 8883, Benutzer ``bblp``, Zugangscode.

Eine Stelle für alles, was hinausgeht (``_senden``): Lesebefehle nur mit Abstand (``pushall`` höchstens alle 300 s),
Steuerbefehle nur, wenn ``sperre.pruefe_steuern`` für die aktuelle Lage nichts einzuwenden hat. Nach HMS
0500-0500-0001-0007 geht gar nichts mehr hinaus. Die Art eines Befehls bestimmt ``befehle.art`` aus seinem Inhalt.

Der Zugangscode liegt nur in diesem Objekt (und im paho-Client), solange die Verbindung besteht; ``stoppen`` verwirft
beide. Keine Meldung nennt Seriennummer oder Zugangscode.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from kevcad_kernel.drucker import befehle, sperre, tls
from kevcad_kernel.drucker.schluesselbund import Zugang
from kevcad_kernel.drucker.status import Bericht

PORT = 8883
BENUTZER = "bblp"


class MqttVerbindung:
    """Hält die Verbindung (paho ``loop_start`` mit eigenem Faden, Wiederverbinden mit Pause) und den ``Bericht``.

    ``lage``: liefert Weg und SSDP-Modus vom Dienst (für die Sperre). ``bei_aenderung``: ohne Argumente, nach jeder
    Änderung von Verbindung oder Bericht (aus dem paho-Faden; der Dienst drosselt).
    """

    def __init__(self, ip: str, zugang: Zugang, *, bei_aenderung: Callable[[], None],
                 lage: Callable[[], tuple[str, str | None]], port: int = PORT, ca_datei: str | None = None,
                 zeitlimit_s: float = 10.0, log: Callable[[str], None] | None = None) -> None:
        self.ip = ip
        self.port = int(port)
        self._zugang: Zugang | None = zugang
        self._bei_aenderung = bei_aenderung
        self._lage_fn = lage
        self._ca = ca_datei
        self.zeitlimit_s = zeitlimit_s
        self._log = log or (lambda _t: None)
        self._lock = threading.RLock()
        self.bericht = Bericht()
        self.verbindung = "aus"  # aus | verbindet | verbunden | getrennt | fehler
        self.meldung: str | None = None
        self._client = None
        self._seq = 0
        self._letztes_pushall: float | None = None
        self._gestartet = 0.0
        self._wachhund: threading.Timer | None = None
        self.gesendet: list[str] = []  # Namen der gesendeten Befehle (ohne Inhalt), für Status und Tests

    # ------------------------------------------------------------------------------------------------------------

    @property
    def thema_bericht(self) -> str:
        return f"device/{self._zugang.seriennummer}/report" if self._zugang else ""

    @property
    def thema_anfrage(self) -> str:
        return f"device/{self._zugang.seriennummer}/request" if self._zugang else ""

    def starten(self) -> None:
        import paho.mqtt.client as mqtt

        with self._lock:
            if self._client is not None or self._zugang is None:
                return
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"kevcad-{uuid.uuid4().hex[:10]}",
                            protocol=mqtt.MQTTv311, clean_session=True)
            c.username_pw_set(BENUTZER, self._zugang.zugangscode)
            c.tls_set_context(tls.kontext(self._ca))
            c.reconnect_delay_set(min_delay=2, max_delay=60)
            c.on_connect = self._on_connect
            c.on_disconnect = self._on_disconnect
            c.on_message = self._on_message
            c.on_connect_fail = self._on_connect_fail
            self._client = c
            self.verbindung = "verbindet"
            self.meldung = f"Verbinde mit {self.ip} …"
            self._gestartet = time.monotonic()
            try:
                c.connect_async(self.ip, self.port, keepalive=30)
                c.loop_start()
            except Exception as exc:  # noqa: BLE001
                self.verbindung = "fehler"
                self.meldung = f"Verbindung nicht möglich: {type(exc).__name__}"
            self._wachhund = threading.Timer(self.zeitlimit_s, self._zeitlimit)
            self._wachhund.daemon = True
            self._wachhund.start()
        self._bei_aenderung()

    def stoppen(self) -> None:
        with self._lock:
            c, self._client = self._client, None
            if self._wachhund is not None:
                self._wachhund.cancel()
                self._wachhund = None
            self._zugang = None  # Zugangscode nur so lange halten, wie die Verbindung besteht
            self.verbindung = "aus"
            self.meldung = None
        if c is not None:
            try:
                c.disconnect()
                c.loop_stop()
            except Exception:  # noqa: BLE001
                pass
            c.username_pw_set(BENUTZER, None)
        self.bericht.neue_verbindung()

    # ------------------------------------------------------------------------------------------------------------
    # Senden (einzige Stelle)

    def _lage(self) -> sperre.Lage:
        weg, ssdp = self._lage_fn()
        return sperre.lage_aus(weg, self.verbindung == "verbunden", self.bericht, ssdp)

    def _senden(self, befehl: dict[str, Any], *, start: bool = False, bestaetigt: bool = False) -> str | None:
        """None = gesendet; sonst der Grund, warum nicht."""
        with self._lock:
            c = self._client
            if c is None or self.verbindung != "verbunden":
                return "Keine Verbindung zum Drucker."
            if self.bericht.signatur_abgelehnt:
                return sperre.grund_weg_b(self._lage())
            art = befehle.art(befehl)
            jetzt = time.monotonic()
            if art == befehle.LESEN:
                if befehl.get("pushing") is not None:
                    if not sperre.pushall_frei(self._letztes_pushall, jetzt):
                        rest = befehle.PUSHALL_ABSTAND_S - (jetzt - (self._letztes_pushall or jetzt))
                        return f"Vollständiger Bericht erst wieder in {int(rest) + 1} s (P1P: höchstens alle 5 min)."
                    self._letztes_pushall = jetzt
            else:
                grund = sperre.pruefe_steuern(self._lage(), start=start, bestaetigt=bestaetigt)
                if grund:
                    return grund
            self._seq += 1
            inhalt = next(iter(befehl.values()))
            inhalt["sequence_id"] = str(self._seq)
            info = c.publish(self.thema_anfrage, json.dumps(befehl), qos=1)
            self.gesendet.append(befehle.name(befehl))
        try:
            info.wait_for_publish(timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
        if not info.is_published():
            return "Der Drucker hat den Befehl nicht bestätigt (Zeitüberschreitung)."
        return None

    def lesen_anfordern(self, *, pushall: bool = True) -> str | None:
        """``get_version`` und (mit Abstand) ``pushall``."""
        grund = self._senden(befehle.get_version())
        if pushall:
            grund = self._senden(befehle.pushall()) or grund
        return grund

    def steuern(self, befehl: dict[str, Any], *, start: bool = False, bestaetigt: bool = False) -> str | None:
        if befehle.art(befehl) != befehle.STEUERN:
            return "Kein Steuerbefehl."
        return self._senden(befehl, start=start, bestaetigt=bestaetigt)

    # ------------------------------------------------------------------------------------------------------------
    # paho-Rückrufe (eigener Faden)

    def _zeitlimit(self) -> None:
        with self._lock:
            if self._client is None or self.verbindung == "verbunden":
                return
            self.verbindung = "fehler"
            self.meldung = (f"Drucker unter {self.ip} antwortet nicht (Zeitüberschreitung nach {self.zeitlimit_s:g} s); "
                            "Kev CAD versucht es weiter.")
        self._bei_aenderung()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ARG002
        if getattr(reason_code, "is_failure", False):
            with self._lock:
                self.verbindung = "fehler"
                text = str(reason_code)
                if "authori" in text.lower() or "password" in text.lower():
                    self.meldung = "Der Drucker lehnt den Zugangscode ab (in den Drucker-Einstellungen prüfen)."
                else:
                    self.meldung = f"Der Drucker lehnt die Verbindung ab ({text})."
            client.disconnect()  # keine Wiederholung mit denselben Zugangsdaten
            self._bei_aenderung()
            return
        try:
            with self._lock:
                sn = self._zugang.seriennummer if self._zugang else ""
            tls.pruefe_cn(client.socket(), sn)
        except tls.ZertifikatFehler as exc:
            with self._lock:
                self.verbindung = "fehler"
                self.meldung = str(exc)
            client.disconnect()
            self._bei_aenderung()
            return
        with self._lock:
            self.bericht.neue_verbindung()  # Modus muss in jeder Verbindung neu kommen
            self.verbindung = "verbunden"
            self.meldung = None
            client.subscribe(self.thema_bericht, qos=0)
        self._log(f"[drucker] verbunden mit {self.ip}")
        self._bei_aenderung()
        threading.Thread(target=self.lesen_anfordern, name="kevcad-drucker-lesen", daemon=True).start()

    def _on_connect_fail(self, client, userdata) -> None:  # noqa: ARG002
        with self._lock:
            if self.verbindung != "fehler":
                self.verbindung = "verbindet"
                self.meldung = f"Drucker unter {self.ip} nicht erreichbar, neuer Versuch …"
        self._bei_aenderung()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ARG002
        with self._lock:
            if self._client is None:
                return
            if self.verbindung != "fehler":
                self.verbindung = "getrennt"
                self.meldung = "Verbindung zum Drucker getrennt, neuer Versuch …"
            self.bericht.neue_verbindung()
        self._bei_aenderung()

    def _on_message(self, client, userdata, msg) -> None:  # noqa: ARG002
        try:
            daten = json.loads(msg.payload.decode("utf-8", "replace"))
        except ValueError:
            return
        with self._lock:
            geaendert = self.bericht.aufnehmen(daten)
        if geaendert:
            self._bei_aenderung()

"""Unix-Socket zur App (PROTOCOL.md): der Kernel lauscht, die App verbindet sich.

- Mehrere App-Verbindungen zugleich (PLAN-IPAD.md, I-2): die Mac-App und jedes iPad, das die Mac-App durchreicht.
  Zustand geht an alle Verbindungen, Antworten nur an die fragende (die ``id`` einer Anfrage bekommt beim Lesen die
  Nummer der Verbindung vorangestellt, ``send`` nimmt sie beim Antworten wieder ab), gezielte Anfragen des Kernels an
  das aktive Gerät (zuletzt verbunden oder bedient). Meldet sich ein Gerät mit derselben Kennung neu, ersetzt die neue
  Verbindung die alte.
- Senden ist threadsicher und blockiert nie: Rahmen gehen in eine Warteschlange, ein eigener Faden schreibt. Hängt die
  App so lange, dass mehr als ``MAX_QUEUED_BYTES`` warten, wird die Verbindung getrennt.
- ``seq`` zählt je Verbindung ab 1 (Reihenfolge der Warteschlange = Reihenfolge auf dem Draht).
- Eine neue Verbindung wird erst nach ``activate()`` zur aktuellen; bis dahin schickt die Laufzeit über
  ``conn.send`` den Anfangsstand (HELLO, PROJECT, STATUS, Teile), damit nichts dazwischenrutscht.
- V2-5 (PROTOCOL.md, „V2-5 Live“): Jeder Rahmen geht vor dem Senden durch die Weiche der Verbindung
  (``live.LiveVerbindung``), unter derselben Sperre wie ``seq``: Sie entfernt neue Felder für ältere Apps und ersetzt
  für Apps mit ``delta-1`` Unverändertes durch kurze Nachrichten (oder lässt es weg).
"""

from __future__ import annotations

import contextlib
import os
import queue
import socket
import stat
import sys
import threading
from collections.abc import Callable
from typing import Any

from kevcad_kernel.live import LiveVerbindung
from kevcad_kernel.protocol import FrameReader, encode_frame

MAX_QUEUED_BYTES = 1 << 30
SOCKET_PATH_MAX = 103  # macOS: sun_path hat 104 Byte inklusive Nullbyte
MAX_VERBINDUNGEN = 8  # mehr Geräte sind nicht vorgesehen; darüber fliegt die älteste nicht aktive Verbindung
# Antworten, die zugleich Zustand sind: Die fragende Verbindung bekommt sie mit reply_to, alle anderen ohne
ZUSTAND_ANTWORTEN = frozenset({"PROJECT"})


class AppConnection:
    def __init__(self, sock: socket.socket, link: AppLink, number: int) -> None:
        self.sock = sock
        self.link = link
        self.number = number
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._lock = threading.Lock()
        self._seq = 0
        self._queued = 0
        self.closed = False
        self.info: dict[str, Any] = {}
        self.live = LiveVerbindung()  # V2-5: Fähigkeiten der App und was sie schon hat

    # -- V2-5: Fähigkeiten und Stand der Weiche (unter derselben Sperre wie das Senden) --------------------------------

    def set_faehigkeiten(self, faehigkeiten: list[str]) -> None:
        with self._lock:
            self.live.melden(faehigkeiten)

    def live_vergessen(self, namen: list[str]) -> None:
        with self._lock:
            self.live.vergessen(namen)

    def live_neueste(self, art: str) -> tuple[dict[str, Any], bytes] | None:
        with self._lock:
            return self.live.neueste(art)

    def start_writer(self) -> None:
        threading.Thread(target=self._write_loop, name=f"app-write-{self.number}", daemon=True).start()

    def start_reader(self) -> None:
        threading.Thread(target=self._read_loop, name=f"app-read-{self.number}", daemon=True).start()

    def send(self, header: dict[str, Any], payload: bytes = b"", *, vollstaendig: bool = False) -> bool:
        """Rahmen in die Warteschlange; True auch, wenn die Weiche ihn bewusst weglässt (die App hat ihn schon oder
        kann ihn nicht). ``vollstaendig``: nichts weglassen oder ersetzen (V2-5, Antwort auf NOCHMAL)."""
        with self._lock:
            if self.closed:
                return False
            seq = self._seq + 1
            try:
                gefiltert = self.live.filtern(header, payload, seq, vollstaendig=vollstaendig)
            except Exception as exc:  # noqa: BLE001 - die Weiche darf das Senden nie verhindern
                self.link._log(f"[app] V2-5-Weiche bei {header.get('type')}: {exc!r}")
                gefiltert = (header, payload)
            if gefiltert is None:
                return True
            header, payload = gefiltert
            self._seq = seq
            data = encode_frame({**header, "seq": seq}, payload)
            if self._queued + len(data) > MAX_QUEUED_BYTES:
                overflow = True
            else:
                overflow = False
                self._queued += len(data)
                self._queue.put(data)
        if overflow:
            self.link._log("[app] Verbindung getrennt: App liest nicht mehr (Warteschlange voll)")
            self.close()
            return False
        return True

    def _write_loop(self) -> None:
        while True:
            data = self._queue.get()
            if data is None:
                return
            try:
                self.sock.sendall(data)
            except OSError:
                self.close()
                return
            with self._lock:
                self._queued -= len(data)

    def _read_loop(self) -> None:
        reader = FrameReader()
        try:
            while True:
                try:
                    data = self.sock.recv(1 << 16)
                except OSError:
                    break
                if not data:
                    break
                try:
                    frames = reader.feed(data)
                except Exception as exc:  # noqa: BLE001 - kaputter Rahmen: Verbindung beenden
                    self.link._log(f"[app] Ungültiger Rahmen von der App: {exc!r}")
                    break
                for header, payload in frames:
                    rid = header.get("id")
                    if isinstance(rid, str):  # I-2: Antwort findet so zur fragenden Verbindung zurück
                        header["id"] = f"{self.number}:{rid}"
                    try:
                        self.link._on_message(self, header, payload)
                    except Exception as exc:  # noqa: BLE001
                        self.link._log(f"[app] Fehler bei {header.get('type')}: {exc!r}")
        finally:
            self.close()

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
        self._queue.put(None)
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self.sock.close()
        self.link._closed(self)


class AppLink:
    def __init__(
        self,
        socket_path: str,
        on_connect: Callable[[AppConnection], None],
        on_message: Callable[[AppConnection, dict[str, Any], bytes], None],
        on_disconnect: Callable[[AppConnection], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.socket_path = os.path.abspath(os.path.expanduser(socket_path))
        self._on_connect = on_connect
        self._on_message = on_message
        self._on_disconnect = on_disconnect or (lambda conn: None)
        self._log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self._server: socket.socket | None = None
        self._conns: list[AppConnection] = []  # aktivierte Verbindungen in der Reihenfolge des Verbindens
        self._aktiv: AppConnection | None = None  # zuletzt bedient: bekommt gezielte Anfragen (Bild, Lagebild)
        self._lock = threading.RLock()
        self._closing = False
        self._count = 0

    # -- Lebenszyklus --------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if len(self.socket_path.encode()) > SOCKET_PATH_MAX:
            raise ValueError(f"Socket-Pfad ist zu lang ({len(self.socket_path)} Zeichen, höchstens {SOCKET_PATH_MAX}): "
                             f"{self.socket_path}")
        os.makedirs(os.path.dirname(self.socket_path), exist_ok=True)
        try:
            st = os.lstat(self.socket_path)
            if stat.S_ISSOCK(st.st_mode) or stat.S_ISREG(st.st_mode):
                os.unlink(self.socket_path)  # alte Socket-Datei eines beendeten Kernels
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.socket_path)
        with contextlib.suppress(OSError):
            os.chmod(self.socket_path, 0o600)
        srv.listen(4)
        srv.settimeout(0.5)
        self._server = srv
        threading.Thread(target=self._accept_loop, name="app-accept", daemon=True).start()

    def close(self) -> None:
        with self._lock:
            self._closing = True
            conns, self._conns = list(self._conns), []
            self._aktiv = None
            srv, self._server = self._server, None
        for conn in conns:
            conn.close()
        if srv is not None:
            with contextlib.suppress(OSError):
                srv.close()
        with contextlib.suppress(OSError):
            os.unlink(self.socket_path)

    def _accept_loop(self) -> None:
        while True:
            srv = self._server
            if srv is None or self._closing:
                return
            try:
                sock, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._closing:
                    return
                continue
            sock.settimeout(None)
            with self._lock:
                self._count += 1
                conn = AppConnection(sock, self, self._count)
            conn.start_writer()
            try:
                self._on_connect(conn)  # schickt den Anfangsstand und ruft activate()
            except Exception as exc:  # noqa: BLE001
                self._log(f"[app] Fehler beim Verbinden: {exc!r}")
            if not conn.closed and conn not in self._conns:
                self.activate(conn)
            conn.start_reader()

    # -- Verbindung ----------------------------------------------------------------------------------------------------

    def activate(self, conn: AppConnection) -> None:
        """Verbindung nimmt ab jetzt am Zustand teil und wird das aktive Gerät: Wer eine App öffnet, arbeitet dort (wie
        vor I-2, als die neue Verbindung die alte ersetzte)."""
        ueberzaehlig: AppConnection | None = None
        with self._lock:
            if conn.closed or self._closing or conn in self._conns:
                return
            self._conns.append(conn)
            self._aktiv = conn
            if len(self._conns) > MAX_VERBINDUNGEN:
                ueberzaehlig = next((c for c in self._conns if c is not self._aktiv and c is not conn), None)
        if ueberzaehlig is not None:
            self._log(f"[app] Mehr als {MAX_VERBINDUNGEN} Verbindungen: Nr. {ueberzaehlig.number} getrennt")
            ueberzaehlig.close()

    def _closed(self, conn: AppConnection) -> None:
        with self._lock:
            if conn not in self._conns:
                return
            self._conns.remove(conn)
            if self._aktiv is conn:
                self._aktiv = self._conns[-1] if self._conns else None
        self._on_disconnect(conn)

    def bedient(self, conn: AppConnection) -> None:
        """Kevin hat an diesem Gerät etwas getan: Es wird das aktive Gerät."""
        with self._lock:
            if conn in self._conns and not conn.closed:
                self._aktiv = conn

    def gleiches_geraet_ersetzen(self, conn: AppConnection, schluessel: str) -> None:
        """Ein Gerät meldet sich neu (Neustart der App, neue Netzverbindung): ältere Verbindungen desselben Schlüssels
        (Gerätekennung, ohne sie die Bundle-ID) trennen, damit nichts doppelt ankommt."""
        with self._lock:
            conn.info["schluessel"] = schluessel
            alt = [c for c in self._conns if c is not conn and c.info.get("schluessel") == schluessel]
        for c in alt:
            self._log(f"[app] {schluessel} meldet sich neu: alte Verbindung Nr. {c.number} getrennt")
            c.close()

    @property
    def connected(self) -> bool:
        with self._lock:
            return any(not c.closed for c in self._conns)

    @property
    def connection(self) -> AppConnection | None:
        """Das aktive Gerät (zuletzt bedient); None ohne Verbindung."""
        with self._lock:
            conn = self._aktiv
        return conn if conn is not None and not conn.closed else None

    aktiv = connection

    @property
    def verbindungen(self) -> list[AppConnection]:
        with self._lock:
            return [c for c in self._conns if not c.closed]

    def geraete(self) -> list[dict[str, Any]]:
        """Verbundene Geräte für das Lagebild (Nummer, Art, Name, App, aktiv)."""
        with self._lock:
            conns = [c for c in self._conns if not c.closed]
            aktiv = self._aktiv
        aus: list[dict[str, Any]] = []
        for c in conns:
            g = c.info.get("geraet") if isinstance(c.info.get("geraet"), dict) else {}
            aus.append({"nr": c.number, "art": g.get("art") or "mac", "name": g.get("name"),
                        "app": c.info.get("bundle_id"), "aktiv": c is aktiv})
        return aus

    def send(self, header: dict[str, Any], payload: bytes = b"", *, an: AppConnection | None = None) -> bool:
        """Rahmen an die Apps. ``an``: nur diese Verbindung. Sonst: Antworten (``reply_to`` mit Verbindungsnummer) an die
        fragende Verbindung, alles andere an alle."""
        if an is not None:
            return an in self.verbindungen and an.send(header, payload)
        rt = header.get("reply_to")
        if isinstance(rt, str):
            nr, sep, original = rt.partition(":")
            if sep and nr.isdigit():
                conns = self.verbindungen
                ziel = next((c for c in conns if c.number == int(nr)), None)
                if ziel is None:
                    return False  # die fragende Verbindung ist weg: die Antwort gehört niemand anderem
                ok = ziel.send({**header, "reply_to": original}, payload)
                if header.get("type") in ZUSTAND_ANTWORTEN:
                    rest = {k: v for k, v in header.items() if k != "reply_to"}
                    for c in conns:
                        if c is not ziel:
                            c.send(rest, payload)
                return ok
        ok = False
        for conn in self.verbindungen:
            ok = conn.send(header, payload) or ok
        return ok

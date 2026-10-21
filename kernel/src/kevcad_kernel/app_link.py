"""Unix-Socket zur App (PROTOCOL.md): der Kernel lauscht, die App verbindet sich.

- Immer nur eine App-Verbindung; eine neue ersetzt die alte.
- Senden ist threadsicher und blockiert nie: Rahmen gehen in eine Warteschlange, ein eigener Faden schreibt. Hängt die
  App so lange, dass mehr als ``MAX_QUEUED_BYTES`` warten, wird die Verbindung getrennt.
- ``seq`` zählt je Verbindung ab 1 (Reihenfolge der Warteschlange = Reihenfolge auf dem Draht).
- Eine neue Verbindung wird erst nach ``activate()`` zur aktuellen; bis dahin schickt die Laufzeit über
  ``conn.send`` den Anfangsstand (HELLO, PROJECT, STATUS, Teile), damit nichts dazwischenrutscht.
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

from kevcad_kernel.protocol import FrameReader, encode_frame

MAX_QUEUED_BYTES = 1 << 30
SOCKET_PATH_MAX = 103  # macOS: sun_path hat 104 Byte inklusive Nullbyte


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

    def start_writer(self) -> None:
        threading.Thread(target=self._write_loop, name=f"app-write-{self.number}", daemon=True).start()

    def start_reader(self) -> None:
        threading.Thread(target=self._read_loop, name=f"app-read-{self.number}", daemon=True).start()

    def send(self, header: dict[str, Any], payload: bytes = b"") -> bool:
        with self._lock:
            if self.closed:
                return False
            self._seq += 1
            data = encode_frame({**header, "seq": self._seq}, payload)
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
        self._conn: AppConnection | None = None
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
            conn, self._conn = self._conn, None
            srv, self._server = self._server, None
        if conn is not None:
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
                old = self._conn
            if old is not None:
                old.close()
            conn.start_writer()
            try:
                self._on_connect(conn)  # schickt den Anfangsstand und ruft activate()
            except Exception as exc:  # noqa: BLE001
                self._log(f"[app] Fehler beim Verbinden: {exc!r}")
            if not conn.closed and self._conn is not conn:
                self.activate(conn)
            conn.start_reader()

    # -- Verbindung ----------------------------------------------------------------------------------------------------

    def activate(self, conn: AppConnection) -> None:
        with self._lock:
            if not conn.closed and not self._closing:
                self._conn = conn

    def _closed(self, conn: AppConnection) -> None:
        with self._lock:
            if self._conn is not conn:
                return
            self._conn = None
        self._on_disconnect(conn)

    @property
    def connected(self) -> bool:
        conn = self._conn
        return conn is not None and not conn.closed

    @property
    def connection(self) -> AppConnection | None:
        return self._conn

    def send(self, header: dict[str, Any], payload: bytes = b"") -> bool:
        conn = self._conn
        if conn is None:
            return False
        return conn.send(header, payload)

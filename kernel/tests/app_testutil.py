"""Hilfen für Tests der Laufzeit: eine minimale Test-App am Unix-Socket und eine Laufzeit mit Test-Katalog."""

from __future__ import annotations

import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from kevcad_kernel.protocol import FrameReader, encode_frame
from kevcad_kernel.runtime import KernelRuntime

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
TEST_CATALOG = Path(__file__).resolve().parent / "katalog_test"


class FakeApp:
    """Minimale App: verbindet sich, sammelt Rahmen mit Empfangszeit, beantwortet VIEW_CMD und SCREENSHOT_REQ.

    V2-5: ``faehigkeiten`` meldet die App in HELLO_APP (ohne: alles wie bisher); ``lage`` ist die Antwort auf
    LAGE_REQ (None: keine Antwort), ``lage_verzoegerung_s`` verzögert sie. I-2: ``geraet`` (Kennung, Art, Name) für
    Tests mit mehreren Geräten."""

    def __init__(self, path: str, answer: bool = True, faehigkeiten: list[str] | None = None,
                 lage: dict | None = None, lage_verzoegerung_s: float = 0.0, geraet: dict | None = None) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.frames: list[tuple[float, dict, bytes]] = []
        self.cond = threading.Condition()
        self.answer = answer
        self.lage = lage
        self.lage_verzoegerung_s = lage_verzoegerung_s
        self.seq = 0
        self.closed = False
        self._send_lock = threading.Lock()
        self._zu = False
        threading.Thread(target=self._read, daemon=True).start()
        hallo = {"type": "HELLO_APP", "app_version": "test", "bundle_id": "de.upvis.kevcad.pytest"}
        if faehigkeiten is not None:
            hallo["faehigkeiten"] = list(faehigkeiten)
        if geraet is not None:  # I-2: Kennung, Art und Name des Geräts (Mac, iPad)
            hallo["geraet"] = dict(geraet)
        self.send(hallo)

    def send(self, header: dict, payload: bytes = b"") -> None:
        with self._send_lock:
            self.seq += 1
            try:
                self.sock.sendall(encode_frame({**header, "seq": self.seq}, payload))
            except OSError:
                if not self._zu:  # nach close(): späte Antworten (etwa auf VERSION_BILD_REQ) still verwerfen
                    raise

    def _read(self) -> None:
        reader = FrameReader()
        while True:
            try:
                data = self.sock.recv(1 << 16)
            except OSError:
                break
            if not data:
                break
            for h, p in reader.feed(data):
                with self.cond:
                    self.frames.append((time.perf_counter(), h, p))
                    self.cond.notify_all()
                if self.answer and h["type"] == "VIEW_CMD":
                    self.send({"type": "ACK", "reply_to": h["id"], "ok": True, "message": f"{h['cmd']} ok"})
                elif self.answer and h["type"] == "SCREENSHOT_REQ":
                    self.send({"type": "SCREENSHOT_RES", "reply_to": h["id"], "ok": True, "width": h["width"],
                               "height": h["height"], "camera": {"projection": "perspective"}, "mm_per_px": None},
                              PNG)
                elif self.answer and h["type"] == "VERSION_BILD_REQ":  # Versionen: Vorschaubild
                    self.send({"type": "SCREENSHOT_RES", "reply_to": h["id"], "ok": True, "width": h["width"],
                               "height": h["height"], "camera": {}, "mm_per_px": None}, PNG)
                elif h["type"] == "LAGE_REQ" and self.lage is not None:  # V2-5: Lagebild
                    antwort = {"type": "LAGE", "reply_to": h["id"], **self.lage}
                    if self.lage_verzoegerung_s > 0:
                        threading.Timer(self.lage_verzoegerung_s, self.send, args=(antwort,)).start()
                    else:
                        self.send(antwort)
        self.closed = True

    def wait_for(self, pred, timeout: float = 30.0, start: int = 0):
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                for i, (t, h, p) in enumerate(self.frames[start:], start):
                    if pred(h):
                        return i, t, h, p
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"Rahmen nicht angekommen; bisher: {[h['type'] for _, h, _ in self.frames]}")
                self.cond.wait(left)

    def mark(self) -> int:
        with self.cond:
            return len(self.frames)

    def since(self, start: int) -> list[dict]:
        with self.cond:
            return [h for _, h, _ in self.frames[start:]]

    def close(self) -> None:
        self._zu = True
        self.sock.close()


@contextmanager
def catalog_env(own: Path | None = None):
    """Fester Test-Katalog statt der mitgelieferten Daten (und auf Wunsch ein eigener Katalogordner), solange die
    Laufzeit angelegt wird; die Laufzeit merkt sich die Ordner."""
    keys = {"KEVCAD_CATALOG_BUILTIN_DIR": str(TEST_CATALOG)}
    if own is not None:
        keys["KEVCAD_CATALOG_DIR"] = str(own)
    old = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def make_runtime(sock: str, own: Path | None = None, **kwargs) -> KernelRuntime:
    with catalog_env(own):
        rt = KernelRuntime(sock, 47999, **{"auto_run": False, "run_timeout_s": 60, **kwargs})
    # V2-1: die Version eines Laufs entsteht im Hintergrund; die Tests prüfen sie im Ergebnis von run, also wartet run
    # hier auf sie (Kevin und der Agent bekommen das Ergebnis ohne Warten, test_tempo.py prüft das)
    rt.versionen_warten_s = 60.0
    # V2-1b: run wartet in den Tests wie früher 3 s auf die Prüfung (test_tempo_pruefung.py prüft die Vorgabe)
    rt.run_warten_s = 3.0
    return rt

"""Kleiner Spiegel-Client für Tests und Messungen (Simulator und echte App): verbindet sich mit einem Spiegel-Socket,
schickt Rahmen mit `seq` und sammelt alle empfangenen Rahmen mit Empfangszeit."""

from __future__ import annotations

import ctypes
import hashlib
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kevcad_kernel.protocol import FrameReader, encode_frame  # noqa: E402

COMPRESSION_LZFSE = 0x801
_lib = ctypes.CDLL("/usr/lib/libcompression.dylib")
_lib.compression_decode_buffer.restype = ctypes.c_size_t
_lib.compression_decode_buffer.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t,
                                           ctypes.c_void_p, ctypes.c_int]


def lzfse_decode(packed: bytes, raw_size: int) -> bytes:
    dst = ctypes.create_string_buffer(raw_size + 1)
    n = _lib.compression_decode_buffer(dst, raw_size + 1, packed, len(packed), None, COMPRESSION_LZFSE)
    if n != raw_size:
        raise ValueError(f"LZFSE: {n} statt {raw_size} Byte")
    return dst.raw[:n]


class MirrorClient:
    def __init__(self, path: str, connect_timeout: float = 5.0) -> None:
        deadline = time.monotonic() + connect_timeout
        while True:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self.sock.connect(path)
                break
            except OSError:
                self.sock.close()
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self.t0 = time.perf_counter()
        self.frames: list[tuple[float, dict[str, Any], bytes]] = []
        self.closed = threading.Event()
        self._cond = threading.Condition()
        self._seq = 0
        self._paused = threading.Event()
        self._paused.set()
        self.meshes: dict[str, bytes] = {}
        self._blocks: dict[str, dict[int, bytes]] = {}
        self.mesh_errors: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()

    # Senden ----------------------------------------------------------------------------------------------------------

    def send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        self._seq += 1
        self.sock.sendall(encode_frame({**header, "seq": self._seq}, payload))

    def hello(self, client: str = "test") -> None:
        self.send({"type": "HELLO", "prio": "zustand", "protocol": "kevcad-mirror", "version": 1, "client": client,
                   "features": ["kcad-mesh-1"]})

    def watch(self, dauer_s: float = 300, geraet: str = "Test-iPhone") -> None:
        self.send({"type": "WATCH", "prio": "zustand", "dauer_s": dauer_s, "geraet": geraet})

    def cmd(self, cid: str, op: str, **args: Any) -> None:
        self.send({"type": "CMD", "prio": "kamera" if op == "kamera" else "zustand", "id": cid, "op": op,
                   "args": args})

    def request_missing(self) -> list[str]:
        """MESH_REQ für alle Teile der Szene, deren Netz noch fehlt."""
        hashes = sorted({p["hash"] for p in self.scene_parts() if p["hash"] not in self.meshes})
        if hashes:
            self.send({"type": "MESH_REQ", "prio": "zustand", "hashes": hashes})
        return hashes

    # Lesen -----------------------------------------------------------------------------------------------------------

    def pause_reading(self) -> None:
        self._paused.clear()

    def resume_reading(self) -> None:
        self._paused.set()

    def _read(self) -> None:
        reader = FrameReader()
        while True:
            self._paused.wait()
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            if not data:
                self.closed.set()
                with self._cond:
                    self._cond.notify_all()
                return
            now = time.perf_counter() - self.t0
            for h, p in reader.feed(data):
                if h.get("type") == "MESH":
                    self._mesh(h, p)
                with self._cond:
                    self.frames.append((now, h, p))
                    self._cond.notify_all()

    def _mesh(self, h: dict[str, Any], p: bytes) -> None:
        blocks = self._blocks.setdefault(h["hash"], {})
        blocks[h["block"]] = p
        if len(blocks) == h["blocks"]:
            packed = b"".join(blocks[i] for i in range(h["blocks"]))
            del self._blocks[h["hash"]]
            try:
                raw = lzfse_decode(packed, h["roh_bytes"])
                if hashlib.sha256(raw).hexdigest()[:16] != h["hash"]:
                    self.mesh_errors.append(f"{h['hash']}: Hash stimmt nicht")
                else:
                    self.meshes[h["hash"]] = raw
            except ValueError as exc:
                self.mesh_errors.append(f"{h['hash']}: {exc}")

    def headers(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self._cond:
            return [h for _, h, _ in self.frames if kind is None or h.get("type") == kind]

    def wait_for(self, pred: Callable[[dict[str, Any]], bool], timeout: float = 5.0, start: int = 0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for _, h, _ in self.frames[start:]:
                    if pred(h):
                        return h
                left = deadline - time.monotonic()
                if left <= 0 or self.closed.is_set():
                    types = [h.get("type") for _, h, _ in self.frames[-12:]]
                    raise TimeoutError(f"Rahmen nicht angekommen; zuletzt: {types}")
                self._cond.wait(left)

    def wait_until(self, cond: Callable[[], bool], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.01)
        return cond()

    def mark(self) -> int:
        with self._cond:
            return len(self.frames)

    def scene_parts(self) -> list[dict[str, Any]]:
        """Teileliste aus der letzten vollständigen SCENE, mit allen PART danach."""
        with self._cond:
            frames = [h for _, h, _ in self.frames]
        parts: dict[str, dict[str, Any]] = {}
        pages: dict[int, list[dict[str, Any]]] = {}
        for h in frames:
            if h["type"] == "SCENE":
                if h["seite"] == 0:
                    pages = {}
                pages[h["seite"]] = h["parts"]
                if len(pages) == h["seiten"]:
                    parts = {p["name"]: p for i in range(h["seiten"]) for p in pages[i]}
            elif h["type"] == "PART":
                if h["op"] == "upsert":
                    parts[h["name"]] = {k: h[k] for k in ("name", "hash", "color", "material", "bbox", "counts")}
                else:
                    parts.pop(h["name"], None)
        return list(parts.values())

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

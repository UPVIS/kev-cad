"""Spiegel-Simulator (MIRROR.md, Version 1.1): bietet einen Spiegel-Socket an wie die Kev-CAD-App, ohne App und Kernel.

Spielt eine Kernel-Aufzeichnung (`.kcadrec`, siehe samples/mirror-recordings/README.md) als Live-Aufbau mit
Zeitverhalten ab, beantwortet HELLO, WATCH, UNWATCH, MESH_REQ (auch wiederholt) und CMD (auch `einpassen`) wie die App (eigener Zustand, Wirkung als
STATE_DELTA bzw. CAMERA mit `quelle: "iphone"` an alle) und kann Kamerafahrten, Auswahlwechsel und einen Neustart mit
neuer Epoche auslösen. Je Verbindung eine Sendewarteschlange mit dem Vorrang aus MIRROR.md (zustand > kamera
latest-only ≤ 40/s > szene > netz, Netzblöcke einzeln nacheinander).

Aufruf (im Ordner kernel), Socket-Pfad kurz halten (macOS: höchstens 103 Byte):

    .venv/bin/python tools/mirror_sim.py --socket /tmp/kcsim.sock
    .venv/bin/python tools/mirror_sim.py --socket /tmp/kcsim.sock --auto
    .venv/bin/python tools/mirror_sim.py --socket /tmp/kcsim.sock --recording ../samples/mirror-recordings/kugelschieber.kcadrec

Ohne `--start fertig` beginnt die Szene leer; der Aufbau startet 1 s nach dem ersten WATCH (oder mit `aufbau`).
Befehle auf stdin, je eine Zeile:

    aufbau     Aufzeichnung als neuen Lauf abspielen (Teil für Teil wie am Mac)
    kamera     Kamerafahrt (Drehteller um Z, 3 s, 60 Stände je Sekunde, quelle mac)
    auswahl    Auswahl auf das nächste Teil (quelle mac)
    hervor     nächstes Teil orange hervorheben (quelle agent)
    leeren     Auswahl, Hervorhebung, Ausblenden und Isolieren zurücksetzen
    xray       Darstellung zwischen shaded_edges und xray wechseln
    agent      zweite Sitzung dazu (aktiv) bzw. wieder weg
    freigabe   Freigabe-Anfrage mit drei Vorschlägen (MIRROR.md 1.1), wie `freigabe_anfragen` eines Agenten
    freigabe-mac        ersten offenen Eintrag „am Mac“ freigeben (FREIGABE_ENDE mit id, grund mac)
    freigabe-zurueck    offene Anfragen zurückziehen (FREIGABE_ENDE, grund zurueckgezogen)
    neustart   Neustart mit neuer Epoche: Socket weg, Verbindungen zu, nach 1,5 s wieder da
    status     Verbindungen und Stand anzeigen
    ende       beenden

`--auto` spielt nach dem Aufbau alle 4 s eine dieser Aktionen der Reihe nach ab (mit `--neustart-alle N` jede N-te
Runde ein Neustart).

Freigabe (MIRROR.md, Version 1.1): FREIGABE geht ohne Miete an jede Verbindung nach dem HELLO (offene Anfragen gleich
mit), CMD `freigabe` wird mit Nonce, Ablauf und Anfrage geprüft und mit CMD_RES `status` beantwortet, danach
FREIGABE_ENDE. `--freigabe-ablauf S` verkürzt die 24 h zum Testen. Eine Prüfung der Gegenstelle (Signatur) gibt es im
Simulator nicht.

Gegenstelle spielen (`--client`): verbindet sich mit einem Spiegel-Socket, etwa dem der Testvariante im Testmodus
(`KEVCAD_FREIGABE_TESTMODUS=1`, nur Bundle-IDs mit `.test`), wartet auf FREIGABE und entscheidet jeden Eintrag:

    .venv/bin/python tools/mirror_sim.py --client "<Datenordner der Testvariante>/mirror.sock" --entscheidung frei
    … --client PFAD --pruefen   vorher falsche Nonce (ungueltig), hinterher Wiederholung (verbraucht)
"""

from __future__ import annotations

import argparse
import collections
import ctypes
import json
import math
import os
import secrets
import signal
import socket
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from kevcad_kernel.protocol import FrameReader, encode_frame  # noqa: E402
from mirror_demo import look_from, lzfse_encode, mesh_hash, mesh_raw, read_frames  # noqa: E402

VERSION = 1
BLOCK = 64 * 1024
HEADER_LIMIT = 16 * 1024
PAYLOAD_LIMIT = 64 * 1024
CAMERA_INTERVAL = 1 / 40
DEFAULT_RECORDING = ROOT.parent / "samples" / "mirror-recordings" / "gestell.kcadrec"
DEFAULT_SESSION = "00000000-0000-4000-8000-000000000001"
SECOND_SESSION = "00000000-0000-4000-8000-000000000002"
PRIOS = ("zustand", "kamera", "szene", "netz")
DISPLAYS = ("shaded_edges", "shaded", "wireframe", "xray")
FREIGABE_FEATURE = "freigabe-1"
FREIGABE_LAUFZEIT_S = 24 * 60 * 60
FREIGABE_STATUS = ("frei", "abgelehnt", "schon_frei", "fehlt", "ungueltig", "verbraucht", "abgelaufen", "beendet",
                   "nicht_erlaubt", "katalogfehler")
STANDARD_VIEWS = {
    "top": (0.0, 0.0, 1.0), "bottom": (0.0, 0.0, -1.0), "front": (0.0, -1.0, 0.0), "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0), "iso": (1.0, -1.0, 1.0), "iso_front_right": (1.0, -1.0, 1.0),
    "iso_front_left": (-1.0, -1.0, 1.0), "iso_back_right": (1.0, 1.0, 1.0), "iso_back_left": (-1.0, 1.0, 1.0),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def view_rotation(direction: tuple[float, float, float]) -> list[float]:
    """Quaternion Kamera → Welt für den Blick aus `direction`; von oben bzw. unten mit Welt-Y oben im Bild."""
    dx, dy, dz = direction
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        # Von oben: Kamera-Z = Welt-Z, Kamera-Y = Welt-Y (Identität); von unten: 180° um X
        return [0.0, 0.0, 0.0, 1.0] if dz > 0 else [1.0, 0.0, 0.0, 0.0]
    return look_from(direction)


def peer_uid(sock: socket.socket) -> int | None:
    """UID der Gegenstelle eines Unix-Sockets (getpeereid)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        uid = ctypes.c_uint32()
        gid = ctypes.c_uint32()
        if libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            return None
        return int(uid.value)
    except (OSError, AttributeError):
        return None


# ======================================================================================================================
# Freigabe vom iPhone (MIRROR.md, Version 1.1)
# ======================================================================================================================


def https_link(text: Any) -> str | None:
    """Nur https mit Rechnername gilt als Link (sonst weglassen)."""
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.strip()
    u = urlsplit(t)
    return t if u.scheme.lower() == "https" and u.hostname else None


def freigabe_eintrag(id: str, kind: str, name: str, art: str, kurz: str = "", link: str | None = None,
                     grund: str | None = None, projekt: str | None = None) -> dict[str, Any]:
    """Ein Eintrag in FREIGABE; `link` nur mit https, sonst fehlt das Feld."""
    e: dict[str, Any] = {"id": id, "kind": kind, "name": name, "art": art, "kurz": kurz}
    if https_link(link):
        e["link"] = https_link(link)
    e["grund"] = grund
    e["projekt"] = projekt
    return e


def freigabe_header(epoche: str, anfrage_id: str, nonce: str, ablauf: str,
                    eintraege: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FREIGABE", "epoche": epoche, "anfrage_id": anfrage_id, "nonce": nonce, "ablauf": ablauf,
            "eintraege": eintraege}


def freigabe_ende_header(epoche: str, anfrage_id: str, grund: str, id: str | None = None,
                         ergebnis: str | None = None) -> dict[str, Any]:
    h: dict[str, Any] = {"type": "FREIGABE_ENDE", "epoche": epoche, "anfrage_id": anfrage_id}
    if id is not None:
        h["id"] = id
    h["grund"] = grund
    if id is not None and ergebnis is not None:
        h["ergebnis"] = ergebnis
    return h


def freigabe_cmd(cid: str, anfrage_id: str, nonce: str, eintrag: str, entscheidung: str) -> dict[str, Any]:
    return {"type": "CMD", "id": cid, "op": "freigabe",
            "args": {"anfrage_id": anfrage_id, "nonce": nonce, "id": eintrag, "entscheidung": entscheidung}}


def iso_utc(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def demo_freigabe_eintraege(projekt: str | None, grund: str | None) -> list[dict[str, Any]]:
    """Drei Vorschläge wie aus stock_define, zukauf_anlegen und material_define (auch in den Testdateien)."""
    return [
        freigabe_eintrag("rohr-alfer-16x1", "teil", "ALFER-Rundrohr 16 × 1", "rohr", "d 16 · s 1 mm · 4,20 €/m · ALFER",
                         "https://www.alfer.com/", grund, projekt),
        freigabe_eintrag("alutec-05200", "teil", "ALUTEC Transportroller 05200", "zukaufteil",
                         "610 × 410 × 128 mm · 24,99 €/Stück · www.beispiel-shop.de",
                         "https://www.beispiel-shop.de/p/alutec-05200", grund, projekt),
        freigabe_eintrag("petg-cf", "material", "PETG-CF", "material", "1,3 g/cm³ · 29,00 €/kg", None, grund, projekt),
    ]


@dataclass
class SimFreigabe:
    """Eine offene Anfrage im Simulator."""
    anfrage_id: str
    nonce: str
    ablauf: float  # time.time()
    eintraege: list[dict[str, Any]]
    entschieden: dict[str, str] = field(default_factory=dict)  # id → frei | abgelehnt

    def offen(self) -> list[dict[str, Any]]:
        return [e for e in self.eintraege if e["id"] not in self.entschieden]


# ======================================================================================================================
# Netze
# ======================================================================================================================


@dataclass
class Mesh:
    hash: str
    packed: bytes
    raw_bytes: int

    @property
    def blocks(self) -> int:
        return max(1, (len(self.packed) + BLOCK - 1) // BLOCK)

    def block(self, i: int) -> tuple[dict[str, Any], bytes]:
        return ({"type": "MESH", "hash": self.hash, "format": "kcad-mesh-1", "block": i, "blocks": self.blocks,
                 "bytes": len(self.packed), "roh_bytes": self.raw_bytes}, self.packed[i * BLOCK:(i + 1) * BLOCK])


def part_entry(header: dict[str, Any], digest: str) -> dict[str, Any]:
    """Teil für SCENE und PART aus dem Kopf eines PART_UPSERT."""
    c = header["counts"]
    return {"name": header["name"], "hash": digest, "color": header.get("color") or [0.72, 0.75, 0.79, 1.0],
            "material": header.get("material"), "bbox": header.get("bbox"),
            "counts": {k: c.get(k, 0) for k in ("vert", "tri", "face", "edge", "epts")}}


def pack_mesh(header: dict[str, Any], payload: bytes) -> tuple[dict[str, Any], Mesh]:
    raw = mesh_raw(header, payload)
    digest = mesh_hash(raw)
    return part_entry(header, digest), Mesh(digest, lzfse_encode(raw), len(raw))


def scene_pages(epoche: str, project: dict[str, Any] | None, run: int, bbox: dict[str, Any] | None,
                parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SCENE in Seiten, jeder Kopf höchstens 16 KB (mit Reserve für die übrigen Felder)."""
    pages: list[list[dict[str, Any]]] = [[]]
    size = 0
    for entry in parts:
        n = len(json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode()) + 1
        if pages[-1] and size + n > HEADER_LIMIT - 1024:
            pages.append([])
            size = 0
        pages[-1].append(entry)
        size += n
    name = {"name": project["name"]} if project else None
    return [{"type": "SCENE", "epoche": epoche, "project": name, "run": run, "bbox": bbox, "seite": i,
             "seiten": len(pages), "parts": page} for i, page in enumerate(pages)]


def union_bbox(boxes: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return {"min": [min(b["min"][i] for b in boxes) for i in range(3)],
            "max": [max(b["max"][i] for b in boxes) for i in range(3)]}


# ======================================================================================================================
# Verbindung mit Sendewarteschlange nach Vorrang
# ======================================================================================================================


class Connection:
    """Eine Verbindung zum Spiegel-Socket: Lesefaden und Schreibfaden mit Vorrang."""

    def __init__(self, sim: MirrorSim, sock: socket.socket, number: int) -> None:
        self.sim = sim
        self.sock = sock
        self.number = number
        self.hello = False
        self.lease_until = 0.0
        self.geraet: str | None = None
        self.closed = False
        self._seq = 0
        self._cond = threading.Condition()
        self._queues: dict[str, collections.deque[tuple[dict[str, Any], bytes]]] = {
            "zustand": collections.deque(), "szene": collections.deque(), "netz": collections.deque()}
        self._camera: dict[str, Any] | None = None
        self._last_camera = 0.0
        self.sent: collections.Counter[str] = collections.Counter()
        self.bytes_sent = 0
        threading.Thread(target=self._read_loop, name=f"mirror-lesen-{number}", daemon=True).start()
        threading.Thread(target=self._write_loop, name=f"mirror-schreiben-{number}", daemon=True).start()

    @property
    def watching(self) -> bool:
        return not self.closed and time.monotonic() < self.lease_until

    def send(self, header: dict[str, Any], payload: bytes = b"", prio: str = "zustand") -> None:
        """Rahmen einreihen; `seq` und `prio` setzt der Schreibfaden in Leitungsreihenfolge."""
        if self.closed:
            return
        with self._cond:
            if prio == "kamera":
                self._camera = header  # nur der neueste zählt
            else:
                self._queues[prio].append(({**header, "prio": prio}, payload))
            self._cond.notify()

    def pending(self) -> int:
        with self._cond:
            return sum(len(q) for q in self._queues.values()) + (1 if self._camera else 0)

    def close(self, reason: str = "") -> None:
        with self._cond:
            if self.closed:
                return
            self.closed = True
            self._cond.notify_all()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.sim.connection_closed(self, reason)

    def _next(self) -> tuple[dict[str, Any], bytes] | None:
        """Nächster Rahmen nach Vorrang oder None (dann warten); setzt voraus, dass `_cond` gehalten wird."""
        while not self.closed:
            if self._queues["zustand"]:
                return self._queues["zustand"].popleft()
            wait: float | None = None
            if self._camera is not None:
                due = self._last_camera + CAMERA_INTERVAL - time.monotonic()
                if due <= 0:
                    header = self._camera
                    self._camera = None
                    self._last_camera = time.monotonic()
                    return {**header, "prio": "kamera"}, b""
                wait = due
            if self._queues["szene"]:
                return self._queues["szene"].popleft()
            if self._queues["netz"]:
                return self._queues["netz"].popleft()
            self._cond.wait(wait)
        return None

    def _write_loop(self) -> None:
        while True:
            with self._cond:
                item = self._next()
                if item is None:
                    return
                self._seq += 1
                header, payload = item
                header = {**header, "seq": self._seq}
            data = encode_frame(header, payload)
            try:
                self.sock.sendall(data)
            except OSError as exc:
                self.close(f"Schreibfehler: {exc}")
                return
            self.sent[header["type"]] += 1
            self.bytes_sent += len(data)

    def _read_loop(self) -> None:
        reader = FrameReader()
        while not self.closed:
            try:
                data = self.sock.recv(256 * 1024)
            except OSError as exc:
                self.close(f"Lesefehler: {exc}")
                return
            if not data:
                self.close("Gegenstelle hat getrennt")
                return
            try:
                frames = reader.feed(data)
            except (ValueError, UnicodeDecodeError) as exc:
                self.close(f"Datenstrom ungültig: {exc}")
                return
            for header, payload in frames:
                try:
                    self.sim.handle(self, header, payload)
                except Exception as exc:  # ein kaputter Rahmen soll den Simulator nicht beenden
                    self.sim.log(f"[{self.number}] Fehler bei {header.get('type')}: {type(exc).__name__}: {exc}")


# ======================================================================================================================
# Simulator
# ======================================================================================================================


@dataclass
class Session:
    session_id: str
    seit: str
    taetigkeit: str | None = None
    zuletzt: str | None = None
    last_mutation: float = field(default_factory=time.monotonic)


class MirrorSim:
    """Zustand und Verhalten der App auf dem Spiegel-Socket."""

    def __init__(self, socket_path: str, recording: Path = DEFAULT_RECORDING, *, speed: float = 1.0,
                 part_delay_ms: float = 0.0, bundle_id: str = "de.upvis.kevcad.sim", app_build: int = 0,
                 session_id: str = DEFAULT_SESSION, start_full: bool = False, build_on_watch: bool = True,
                 quiet: bool = False, aspect: float = 1.6,
                 freigabe_ablauf_s: float = FREIGABE_LAUFZEIT_S) -> None:
        self.socket_path = socket_path
        self.freigabe_ablauf_s = freigabe_ablauf_s
        self.freigaben: dict[str, SimFreigabe] = {}
        self.beendet: dict[str, str] = {}  # anfrage_id → Grund des Endes (für CMD_RES)
        self._freigabe_nr = 0
        self.speed = max(speed, 1e-3)
        self.part_delay_ms = part_delay_ms
        self.bundle_id = bundle_id
        self.app_build = app_build
        self.quiet = quiet
        self.build_on_watch = build_on_watch
        self.lock = threading.RLock()
        self.epoche = secrets.token_hex(8)
        self.rev = 0
        self.run = 0
        self.project: dict[str, Any] | None = None
        self.parts: dict[str, dict[str, Any]] = {}
        self.meshes: dict[str, Mesh] = {}
        self.connections: list[Connection] = []
        self._numbers = 0
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._building = threading.Lock()
        self._built_once = False
        self._cursor = 0
        self.closed = False
        self.events: list[str] = []
        self.sessions = [Session(session_id, now_iso(), "baut")]
        self.frames = read_frames(recording)
        self._packed: dict[str, tuple[dict[str, Any], Mesh]] = {}  # Name → Teil und Netz aus der Aufzeichnung
        for h, p in self.frames:
            if h["type"] == "PART_UPSERT":
                self._packed[h["name"]] = pack_mesh(h, p)
            elif h["type"] == "PROJECT":
                self.recorded_project = {"path": h.get("path"), "name": h.get("name")}
        if not hasattr(self, "recorded_project"):
            self.recorded_project = {"path": None, "name": recording.stem}
        self.sessions[0].taetigkeit = f"baut {self.recorded_project['name']}"
        self.view: dict[str, Any] = {
            "kamera": {"rotation": look_from((1.0, -1.2, 0.8)), "pivot": [0.0, 0.0, 0.0], "distance": 1000.0,
                       "fov": 45.0, "ortho": False, "ortho_scale": 800.0, "aspect": aspect},
            "auswahl": {"run": 0, "refs": []}, "verborgen": [], "isoliert": None, "hervorgehoben": [],
            "darstellung": "shaded_edges", "schnitt": None, "masse": [], "befunde": [],
            "lauf": {"run": 0, "laeuft": False, "schritt": None, "fehler": None},
        }
        if start_full:
            self._fill_from_recording()

    # ------------------------------------------------------------------------------------------------- Protokoll

    def log(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self.events.append(line)
        if not self.quiet:
            print(line, file=sys.stderr, flush=True)

    def _fill_from_recording(self) -> None:
        self.project = dict(self.recorded_project)
        self.run = max(self.run, 1)
        for name, (entry, mesh) in self._packed.items():
            self.parts[name] = entry
            self.meshes[mesh.hash] = mesh
        self._fit_camera()
        self.view["auswahl"] = {"run": self.run, "refs": []}
        self.view["lauf"] = {"run": self.run, "laeuft": False, "schritt": None, "fehler": None}
        self._built_once = True

    @property
    def bbox(self) -> dict[str, Any] | None:
        return union_bbox([p.get("bbox") for p in self.parts.values()])

    def _fit_camera(self, names: list[str] | None = None) -> dict[str, Any]:
        box = union_bbox([self.parts[n].get("bbox") for n in (names or list(self.parts)) if n in self.parts])
        if box:
            lo, hi = box["min"], box["max"]
            diag = max(math.dist(lo, hi), 10.0)
            self.view["kamera"] = {**self.view["kamera"], "pivot": [round((a + b) / 2, 3) for a, b in zip(lo, hi)],
                                   "distance": round(diag * 1.6, 1), "ortho_scale": round(diag * 1.2, 1)}
        return self.view["kamera"]

    def agents(self) -> list[dict[str, Any]]:
        """Sitzungen nach MIRROR.md: aktiv ist die mit dem letzten verändernden Aufruf der letzten 10 Minuten."""
        recent = [s for s in self.sessions if time.monotonic() - s.last_mutation < 600]
        active = max(recent, key=lambda s: s.last_mutation) if recent else None
        out = []
        for s in sorted(self.sessions, key=lambda s: (s is not active, s.seit)):
            d = {"session_id": s.session_id, "aktiv": s is active, "seit": s.seit, "taetigkeit": s.taetigkeit}
            if s.zuletzt:
                d["zuletzt"] = s.zuletzt
            out.append(d)
        return out

    # ------------------------------------------------------------------------------------------------- Socket

    def start(self) -> MirrorSim:
        path = self.socket_path
        if len(path.encode()) > 103:
            raise ValueError(f"Socket-Pfad zu lang ({len(path.encode())} Byte, höchstens 103): {path}")
        folder = Path(path).parent
        if not folder.exists():
            folder.mkdir(parents=True, mode=0o700)
            os.chmod(folder, 0o700)
        if os.path.exists(path):
            if not stat.S_ISSOCK(os.stat(path).st_mode):
                raise FileExistsError(f"{path} existiert und ist kein Socket")
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            srv.bind(path)
        finally:
            os.umask(old)
        os.chmod(path, 0o600)
        srv.listen(8)
        self._listener = srv
        self._accept_thread = threading.Thread(target=self._accept_loop, args=(srv,), name="mirror-accept",
                                               daemon=True)
        self._accept_thread.start()
        self.log(f"Spiegel-Simulator lauscht auf {path} (Epoche {self.epoche}, {len(self._packed)} Teile in der "
                 f"Aufzeichnung)")
        return self

    def _accept_loop(self, srv: socket.socket) -> None:
        while True:
            try:
                sock, _ = srv.accept()
            except OSError:
                return
            uid = peer_uid(sock)
            if uid is not None and uid != os.getuid():
                self.log(f"Verbindung von fremder UID {uid} abgewiesen")
                sock.close()
                continue
            with self.lock:
                self._numbers += 1
                conn = Connection(self, sock, self._numbers)
                self.connections.append(conn)
            self.log(f"[{conn.number}] verbunden")

    def connection_closed(self, conn: Connection, reason: str) -> None:
        with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)
        self.log(f"[{conn.number}] getrennt ({reason})")

    def stop(self) -> None:
        self.closed = True
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        for conn in list(self.connections):
            conn.close("Simulator beendet")
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def restart(self, pause_s: float = 1.5) -> None:
        """Wie ein Neustart der App: Socket weg, alle Verbindungen zu, neue Epoche, Socket wieder da."""
        self.log("Neustart: Socket weg")
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        for conn in list(self.connections):
            conn.close("Neustart")
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        time.sleep(pause_s)
        with self.lock:
            self.epoche = secrets.token_hex(8)
            self.rev = 0
        self.start()

    # ------------------------------------------------------------------------------------------------- Senden

    def _watchers(self) -> list[Connection]:
        return [c for c in self.connections if c.watching]

    def _broadcast(self, header: dict[str, Any], payload: bytes = b"", prio: str = "zustand") -> None:
        for c in self._watchers():
            c.send(header, payload, prio)

    def _delta(self, quelle: str, **fields: Any) -> None:
        with self.lock:
            self.view.update(fields)
            self.rev += 1
            self._broadcast({"type": "STATE_DELTA", "epoche": self.epoche, "rev": self.rev, "quelle": quelle,
                             **fields})

    def _camera(self, kamera: dict[str, Any], quelle: str) -> None:
        with self.lock:
            self.view["kamera"] = kamera
            self.rev += 1
            self._broadcast({"type": "CAMERA", "epoche": self.epoche, "rev": self.rev, "kamera": kamera,
                             "quelle": quelle}, prio="kamera")

    def _send_agents(self) -> None:
        with self.lock:
            msg = {"type": "AGENTS", "epoche": self.epoche, "agents": self.agents()}
            for c in self.connections:
                if c.hello:
                    c.send(msg)

    def _send_full(self, conn: Connection) -> None:
        with self.lock:
            for page in scene_pages(self.epoche, self.project, self.run, self.bbox, list(self.parts.values())):
                conn.send(page, prio="szene")
            conn.send({"type": "STATE", "epoche": self.epoche, "rev": self.rev, **self.view})

    def _send_scene_all(self) -> None:
        with self.lock:
            for c in self._watchers():
                self._send_full_scene_only(c)

    def _send_full_scene_only(self, conn: Connection) -> None:
        for page in scene_pages(self.epoche, self.project, self.run, self.bbox, list(self.parts.values())):
            conn.send(page, prio="szene")

    def hello_reply(self) -> dict[str, Any]:
        return {"type": "HELLO", "version": VERSION, "epoche": self.epoche, "app_build": self.app_build,
                "bundle_id": self.bundle_id, "features": ["kcad-mesh-1", FREIGABE_FEATURE], "project": self.project,
                "agents": self.agents()}

    # ------------------------------------------------------------------------------------------------- Empfangen

    def handle(self, conn: Connection, header: dict[str, Any], payload: bytes) -> None:
        kind = header.get("type")
        if kind == "HELLO":
            if header.get("protocol") not in (None, "kevcad-mirror") or header.get("version") != VERSION:
                self.log(f"[{conn.number}] HELLO mit protocol={header.get('protocol')!r} "
                         f"version={header.get('version')!r}; antworte mit Version {VERSION}")
            with self.lock:
                conn.hello = True
                conn.send(self.hello_reply())
                self._freigaben_an(conn)  # offene Anfragen gleich nach dem HELLO, ohne Miete
            self.log(f"[{conn.number}] HELLO von {header.get('client', '?')}")
        elif kind == "WATCH":
            dauer = float(header.get("dauer_s") or 300)
            conn.geraet = header.get("geraet")
            with self.lock:
                if not conn.hello:
                    conn.hello = True
                    conn.send(self.hello_reply())
                fresh = not conn.watching
                conn.lease_until = time.monotonic() + dauer
                if fresh:
                    self._send_full(conn)
            self.log(f"[{conn.number}] WATCH {dauer:g} s von {conn.geraet or '?'}"
                     + (" (voller Stand)" if fresh else " (verlängert)"))
            if fresh and self.build_on_watch and not self._built_once:
                self._built_once = True
                threading.Timer(1.0, self.build).start()
        elif kind == "UNWATCH":
            conn.lease_until = 0.0
            self.log(f"[{conn.number}] UNWATCH")
        elif kind == "MESH_REQ":
            hashes = [h for h in header.get("hashes") or [] if isinstance(h, str)]
            missing = []
            with self.lock:
                for h in hashes:
                    mesh = self.meshes.get(h)
                    if mesh is None:
                        missing.append(h)
                        continue
                    for i in range(mesh.blocks):
                        bh, bp = mesh.block(i)
                        conn.send(bh, bp, prio="netz")
            self.log(f"[{conn.number}] MESH_REQ {len(hashes)} Netze" + (f", unbekannt: {missing}" if missing else ""))
        elif kind == "CMD":
            self.command(conn, header)
        else:
            self.log(f"[{conn.number}] unbekannter Typ {kind!r} verworfen")

    # ------------------------------------------------------------------------------------------------- Befehle

    def _expand(self, refs: list[str]) -> tuple[list[str], list[str]]:
        """Referenzen auf Teilnamen; ein Name ohne eigenes Teil steht für alle Teile darunter („Rollwagen/…“)."""
        known: list[str] = []
        unknown: list[str] = []
        for r in refs:
            name = r.split("#", 1)[0]
            if name in self.parts:
                hits = [name]
            else:
                prefix = name.rstrip("/") + "/"
                hits = [n for n in self.parts if n.startswith(prefix)]
            if not hits:
                unknown.append(r)
            for h in hits:
                if h not in known:
                    known.append(h)
        return known, unknown

    def command(self, conn: Connection, header: dict[str, Any]) -> None:
        cid = str(header.get("id") or "")
        op = header.get("op")
        args = header.get("args") or {}
        ok, fehler = True, None
        if op == "freigabe":
            self._cmd_freigabe(conn, cid, args if isinstance(args, dict) else {})
            return
        with self.lock:
            if op == "kamera":
                kamera = args.get("kamera")
                if isinstance(kamera, dict) and len(kamera.get("rotation") or []) == 4:
                    # aspect beschreibt die Ansicht am Mac, nicht die des iPhones
                    self._camera({**kamera, "aspect": self.view["kamera"].get("aspect")}, "iphone")
                return  # latest-only, ohne Antwort
            if op == "auswahl":
                ok, fehler = self._cmd_auswahl(args)
            elif op == "sichtbarkeit":
                ok, fehler = self._cmd_sichtbarkeit(args)
            elif op == "fokus":
                known, unknown = self._expand([r for r in args.get("refs") or [] if isinstance(r, str)])
                if known:
                    self._camera(self._fit_camera(known), "iphone")
                ok = bool(known)
                fehler = f"Nicht gefunden: {', '.join(unknown)}" if unknown else None
            elif op == "ansicht":
                ok, fehler = self._cmd_ansicht(args)
            elif op == "einpassen":
                ok, fehler = self._cmd_einpassen(args)
            elif op == "darstellung":
                display = args.get("display")
                if display in DISPLAYS:
                    if display != self.view["darstellung"]:
                        self._delta("iphone", darstellung=display)
                else:
                    ok, fehler = False, f"Unbekannte Darstellung {display!r}"
            else:
                ok, fehler = False, f"Unbekannter Befehl {op!r}"
            conn.send({"type": "CMD_RES", "reply_to": cid, "ok": ok, "fehler": fehler})
        self.log(f"[{conn.number}] CMD {op} → {'ok' if ok else 'Fehler'}" + (f" ({fehler})" if fehler else ""))

    # ------------------------------------------------------------------------------------------------- Freigabe

    def _hello_conns(self) -> list[Connection]:
        return [c for c in self.connections if c.hello and not c.closed]

    def _freigabe_msg(self, f: SimFreigabe) -> dict[str, Any]:
        return freigabe_header(self.epoche, f.anfrage_id, f.nonce, iso_utc(f.ablauf), f.offen())

    def _freigaben_an(self, conn: Connection) -> None:
        self._abgelaufene_beenden()
        for f in self.freigaben.values():
            if f.offen():
                conn.send(self._freigabe_msg(f))

    def _ende(self, f: SimFreigabe, grund: str, id: str | None = None, ergebnis: str | None = None) -> None:
        msg = freigabe_ende_header(self.epoche, f.anfrage_id, grund, id, ergebnis)
        for c in self._hello_conns():
            c.send(msg)
        if id is None:
            self.freigaben.pop(f.anfrage_id, None)
            self.beendet[f.anfrage_id] = grund

    def _abgelaufene_beenden(self) -> None:
        now = time.time()
        for f in list(self.freigaben.values()):
            if now >= f.ablauf:
                self._ende(f, "abgelaufen")
                self.log(f"Freigabe {f.anfrage_id} abgelaufen")

    def freigabe_anfragen(self, eintraege: list[dict[str, Any]] | None = None, grund: str | None = None) -> str:
        """Wie `freigabe_anfragen` eines Agenten: neue Anfrage an alle (ersetzt eine offene)."""
        with self.lock:
            for alt in list(self.freigaben.values()):
                self._ende(alt, "zurueckgezogen")
            self._freigabe_nr += 1
            projekt = (self.project or self.recorded_project or {}).get("name")
            f = SimFreigabe(anfrage_id=f"F-{self._freigabe_nr:04d}-{secrets.token_hex(4)}",
                            nonce=secrets.token_hex(16), ablauf=time.time() + self.freigabe_ablauf_s,
                            eintraege=eintraege or demo_freigabe_eintraege(projekt, grund or "Für den Simulator"))
            self.freigaben[f.anfrage_id] = f
            msg = self._freigabe_msg(f)
            for c in self._hello_conns():
                c.send(msg)
            timer = threading.Timer(self.freigabe_ablauf_s + 0.05, self._ablauf_pruefen)
            timer.daemon = True
            timer.start()
        self.log(f"Freigabe {f.anfrage_id} angefragt: {', '.join(e['id'] for e in f.eintraege)}")  # Nonce nie ins Log
        return f.anfrage_id

    def _ablauf_pruefen(self) -> None:
        with self.lock:
            self._abgelaufene_beenden()

    def freigabe_mac(self) -> None:
        """Kevin gibt am Mac den ersten offenen Eintrag frei."""
        with self.lock:
            for f in self.freigaben.values():
                offen = f.offen()
                if not offen:
                    continue
                eid = offen[0]["id"]
                f.entschieden[eid] = "frei"
                self._ende(f, "mac", eid, "frei")
                if not f.offen():
                    self._ende(f, "mac")
                self.log(f"Freigabe {f.anfrage_id}: {eid} am Mac freigegeben")
                return
        self.log("Keine offene Freigabe")

    def freigabe_zurueckziehen(self) -> None:
        with self.lock:
            for f in list(self.freigaben.values()):
                self._ende(f, "zurueckgezogen")
                self.log(f"Freigabe {f.anfrage_id} zurückgezogen")

    def _cmd_freigabe(self, conn: Connection, cid: str, args: dict[str, Any]) -> None:
        anfrage_id = str(args.get("anfrage_id") or "")
        nonce = str(args.get("nonce") or "")
        eid = str(args.get("id") or "")
        entscheidung = args.get("entscheidung")
        status, fehler = "ungueltig", None
        with self.lock:
            self._abgelaufene_beenden()
            f = self.freigaben.get(anfrage_id)
            if entscheidung not in ("frei", "abgelehnt") or not eid:
                fehler = f"entscheidung {entscheidung!r} bzw. id fehlt (frei oder abgelehnt)"
            elif f is None:
                grund = self.beendet.get(anfrage_id)
                status = "abgelaufen" if grund == "abgelaufen" else ("beendet" if grund else "ungueltig")
                fehler = {"abgelaufen": "Die Anfrage ist abgelaufen.", "beendet": "Die Anfrage ist erledigt."}.get(
                    status, "Anfrage unbekannt")
            elif not secrets.compare_digest(nonce.encode(), f.nonce.encode()):
                fehler = "Die Nonce passt nicht zur Anfrage."
            elif eid not in {e["id"] for e in f.eintraege}:
                fehler = f"{eid} gehört nicht zur Anfrage."
            elif eid in f.entschieden:
                status, fehler = "verbraucht", f"{eid} ist schon entschieden."
            else:
                f.entschieden[eid] = entscheidung
                status = entscheidung
            conn.send({"type": "CMD_RES", "reply_to": cid, "ok": status in ("frei", "abgelehnt"), "fehler": fehler,
                       "status": status})
            if f is not None and status in ("frei", "abgelehnt"):
                self._ende(f, "iphone", eid, status)
                if not f.offen():
                    self._ende(f, "iphone")
        self.log(f"[{conn.number}] CMD freigabe {eid} → {status}" + (f" ({fehler})" if fehler else ""))

    def _cmd_auswahl(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        refs = [r for r in args.get("refs") or [] if isinstance(r, str)]
        modus = args.get("modus") or "setzen"
        if modus not in ("setzen", "dazu", "weg"):
            return False, f"Unbekannter Modus {modus!r}"
        run = args.get("run")
        valid, problems = [], []
        for r in refs:
            name = r.split("#", 1)[0]
            if name not in self.parts:
                problems.append(f"nicht gefunden: {r}")
            elif "#" in r and run is not None and run != self.run:
                problems.append(f"gilt nicht mehr (Lauf {run}, aktuell {self.run}): {r}")
            else:
                valid.append(r)
        current = list(self.view["auswahl"]["refs"])
        if modus == "setzen":
            new = valid
        elif modus == "dazu":
            new = current + [r for r in valid if r not in current]
        else:
            new = [r for r in current if r not in valid]
        if new != current or self.view["auswahl"]["run"] != self.run:
            self._delta("iphone", auswahl={"run": self.run, "refs": new})
        ok = bool(valid) or not refs
        return ok, "; ".join(problems) or None

    def _cmd_sichtbarkeit(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        mode = args.get("mode")
        known, unknown = self._expand([r for r in args.get("refs") or [] if isinstance(r, str)])
        hidden = list(self.view["verborgen"])
        if mode == "show_all":
            self._delta("iphone", verborgen=[], isoliert=None)
            return True, None
        if mode not in ("show", "hide", "isolate"):
            return False, f"Unbekannter Modus {mode!r}"
        if not known:
            return False, f"Unbekannte Teile: {', '.join(unknown) or '(keine)'}"
        if mode == "isolate":
            self._delta("iphone", verborgen=[n for n in self.parts if n not in known], isoliert=known)
        elif mode == "hide":
            self._delta("iphone", verborgen=[n for n in self.parts if n in hidden or n in known], isoliert=None)
        else:
            self._delta("iphone", verborgen=[n for n in hidden if n not in known], isoliert=None)
        return True, f"Nicht gefunden: {', '.join(unknown)}" if unknown else None

    def _cmd_einpassen(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        """Wie Pos1 (ohne refs: alles Sichtbare) bzw. „.“ (die genannten Teile); Kev CAD wählt Ränder und Projektion."""
        refs = args.get("refs")
        if refs is None or refs == []:
            visible = [n for n in self.parts if n not in self.view["verborgen"]]
            self._camera(self._fit_camera(visible or None), "iphone")
            return True, None
        known, unknown = self._expand([r for r in refs if isinstance(r, str)])
        if not known:
            return False, f"Unbekannte Referenz: {', '.join(unknown)}"
        self._camera(self._fit_camera(known), "iphone")
        return True, f"Nicht gefunden: {', '.join(unknown)}" if unknown else None

    def _cmd_ansicht(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        kamera = dict(self.view["kamera"])
        standard = args.get("standard")
        if standard is not None:
            if standard not in STANDARD_VIEWS:
                return False, f"Unbekannte Ansicht {standard!r}"
            kamera["rotation"] = view_rotation(STANDARD_VIEWS[standard])
        projection = args.get("projection")
        if projection is not None:
            if projection not in ("perspective", "orthographic"):
                return False, f"Unbekannte Projektion {projection!r}"
            kamera["ortho"] = projection == "orthographic"
        self.view["kamera"] = kamera
        visible = [n for n in self.parts if n not in self.view["verborgen"]]
        self._camera(self._fit_camera(visible or None), "iphone")
        return True, None

    # ------------------------------------------------------------------------------------------------- Abläufe

    def _sleep(self, ms: float) -> None:
        if ms > 0:
            time.sleep(ms / 1000 / self.speed)

    def build(self) -> None:
        """Aufzeichnung als neuen Lauf abspielen, mit den Abständen aus `rec_t_ms`."""
        if not self._building.acquire(blocking=False):
            self.log("Aufbau läuft schon")
            return
        try:
            self._built_once = True
            started = time.monotonic()
            last_t = None
            run = None
            for h, p in self.frames:
                t = float(h.get("rec_t_ms") or 0.0)
                if last_t is not None:
                    self._sleep(t - last_t)
                last_t = t
                kind = h["type"]
                if kind == "PROJECT":
                    with self.lock:
                        project = {"path": h.get("path"), "name": h.get("name")}
                        if self.project is None or self.project.get("name") != project["name"]:
                            self.project = project
                            self.parts = {}
                            self._send_scene_all()
                        self.project = project
                elif kind == "RUN_START":
                    with self.lock:
                        self.run += 1
                        run = self.run
                        self.sessions[0].last_mutation = time.monotonic()
                        self.sessions[0].zuletzt = now_iso()
                        self._delta("agent", lauf={"run": run, "laeuft": True, "schritt": None, "fehler": None},
                                    auswahl={"run": run, "refs": []})
                elif kind == "STEP":
                    with self.lock:
                        self._delta("agent", lauf={**self.view["lauf"], "schritt": h.get("text")})
                elif kind == "PART_UPSERT":
                    entry, mesh = self._packed.get(h["name"]) or pack_mesh(h, p)
                    with self.lock:
                        self.meshes[mesh.hash] = mesh
                        self.parts[entry["name"]] = entry
                        self._broadcast({"type": "PART", "epoche": self.epoche, "op": "upsert",
                                         "run": run or self.run, **entry}, prio="szene")
                    self._sleep(self.part_delay_ms * self.speed)
                elif kind == "PART_REMOVE":
                    with self.lock:
                        if self.parts.pop(h["name"], None) is not None:
                            self._broadcast({"type": "PART", "epoche": self.epoche, "op": "remove",
                                             "run": run or self.run, "name": h["name"]}, prio="szene")
                elif kind == "RUN_END":
                    self._delta("agent", lauf={"run": run or self.run, "laeuft": False, "schritt": None,
                                               "fehler": None})
                elif kind == "RUN_ERROR":
                    with self.lock:
                        self._delta("agent", lauf={"run": run or self.run, "laeuft": False, "schritt": None,
                                                   "fehler": h.get("message")})
                elif kind == "AGENT" and h.get("activity"):
                    self.sessions[0].taetigkeit = h["activity"]
                    self._send_agents()
            if not any(h["type"] == "RUN_END" for h, _ in self.frames):
                self._delta("agent", lauf={"run": run or self.run, "laeuft": False, "schritt": None, "fehler": None})
            with self.lock:
                if len(self.parts) and run == 1:
                    self._camera(self._fit_camera(), "mac")
            self.log(f"Aufbau fertig: Lauf {run}, {len(self.parts)} Teile in {time.monotonic() - started:.1f} s")
        finally:
            self._building.release()

    def orbit(self, seconds: float = 3.0, rate: float = 60.0) -> None:
        """Kamerafahrt: eine volle Umdrehung um Welt-Z (Drehteller), Stände mit `rate` je Sekunde."""
        steps = max(int(seconds * rate), 1)
        base = dict(self.view["kamera"])
        for k in range(1, steps + 1):
            a = math.radians(-50 + 360 * k / steps)
            self._camera({**base, "rotation": look_from((math.cos(a), math.sin(a), 0.65))}, "mac")
            time.sleep(1 / rate)
        self.log(f"Kamerafahrt fertig ({steps} Stände)")

    def next_selection(self) -> None:
        with self.lock:
            names = list(self.parts)
            if not names:
                return
            self._cursor = (self._cursor + 1) % len(names)
            self._delta("mac", auswahl={"run": self.run, "refs": [names[self._cursor]]})
        self.log(f"Auswahl: {names[self._cursor]}")

    def highlight_next(self) -> None:
        with self.lock:
            names = list(self.parts)
            if not names:
                return
            name = names[(self._cursor + 1) % len(names)]
            self._delta("agent", hervorgehoben=[{"refs": [name], "color": [1.0, 0.6, 0.0, 1.0], "label": "geändert"}])
        self.log(f"Hervorgehoben: {name}")

    def clear(self) -> None:
        self._delta("mac", auswahl={"run": self.run, "refs": []}, hervorgehoben=[], verborgen=[], isoliert=None)

    def toggle_xray(self) -> None:
        self._delta("mac", darstellung="shaded_edges" if self.view["darstellung"] == "xray" else "xray")

    def toggle_second_agent(self) -> None:
        with self.lock:
            second = [s for s in self.sessions if s.session_id == SECOND_SESSION]
            if second:
                self.sessions.remove(second[0])
            else:
                self.sessions.append(Session(SECOND_SESSION, now_iso(), "prüft Durchdringungen", now_iso()))
        self._send_agents()
        self.log("Zweite Sitzung " + ("weg" if second else "dazu (aktiv)"))

    def status(self) -> str:
        with self.lock:
            lines = [f"Epoche {self.epoche}, rev {self.rev}, Lauf {self.run}, {len(self.parts)} Teile, "
                     f"{len(self.meshes)} Netze"]
            for f in self.freigaben.values():
                lines.append(f"  Freigabe {f.anfrage_id}: offen {[e['id'] for e in f.offen()]}, "
                             f"entschieden {f.entschieden}")
            for c in self.connections:
                lease = max(0.0, c.lease_until - time.monotonic())
                lines.append(f"  [{c.number}] hello={c.hello} Miete {lease:.0f} s, wartend {c.pending()}, "
                             f"gesendet {dict(c.sent)}")
        return "\n".join(lines)

    def auto(self, interval: float = 4.0, restart_every: int = 0) -> None:
        """Demo-Schleife: nach dem ersten Aufbau der Reihe nach Aktionen abspielen."""
        while not self._built_once and not self.closed:
            time.sleep(0.2)
        while self._building.locked():
            time.sleep(0.2)
        actions = [self.orbit, self.next_selection, self.highlight_next, self.toggle_xray, self.toggle_xray,
                   self.clear, self.build]
        rounds = 0
        while not self.closed:
            for action in actions:
                time.sleep(interval)
                if self.closed:
                    return
                action()
            rounds += 1
            if restart_every and rounds % restart_every == 0:
                self.restart()


def command_loop(sim: MirrorSim) -> bool:
    """Befehle von stdin; True bei `ende`, False, wenn stdin zu ist."""
    actions = {
        "aufbau": sim.build, "lauf": sim.build, "kamera": sim.orbit, "auswahl": sim.next_selection,
        "hervor": sim.highlight_next, "leeren": sim.clear, "xray": sim.toggle_xray, "agent": sim.toggle_second_agent,
        "neustart": sim.restart, "freigabe": sim.freigabe_anfragen, "freigabe-mac": sim.freigabe_mac,
        "freigabe-zurueck": sim.freigabe_zurueckziehen,
    }
    for line in sys.stdin:
        cmd = line.strip().lower()
        if not cmd:
            continue
        if cmd in ("ende", "quit", "exit"):
            return True
        if cmd == "status":
            print(sim.status(), file=sys.stderr, flush=True)
        elif cmd in actions:
            threading.Thread(target=actions[cmd], daemon=True).start()
        else:
            print(f"Unbekannt: {cmd} (aufbau, kamera, auswahl, hervor, leeren, xray, agent, freigabe, freigabe-mac, "
                  "freigabe-zurueck, neustart, status, ende)", file=sys.stderr, flush=True)
    return False


# ======================================================================================================================
# Gegenstelle (--client): Freigabe vom „iPhone“ gegen die echte App im Testmodus
# ======================================================================================================================


class MirrorClient:
    """Kleiner Spiegel-Client: HELLO, Rahmen lesen, CMD schicken und auf CMD_RES warten."""

    def __init__(self, path: str, client: str = "mirror-sim") -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.reader = FrameReader()
        self.inbox: collections.deque[dict[str, Any]] = collections.deque()
        self.seq = 0
        self.send({"type": "HELLO", "protocol": "kevcad-mirror", "version": VERSION, "client": client,
                   "features": ["kcad-mesh-1", FREIGABE_FEATURE]})

    def send(self, header: dict[str, Any]) -> None:
        self.seq += 1
        self.sock.sendall(encode_frame({**header, "seq": self.seq, "prio": "zustand"}))

    def next(self, until: float, want: Any = None) -> dict[str, Any] | None:
        """Nächster Kopf (bis `until`, time.monotonic); mit `want` nur passende, andere bleiben im Eingang."""
        while True:
            for i, h in enumerate(self.inbox):
                if want is None or want(h):
                    del self.inbox[i]
                    return h
            rest = until - time.monotonic()
            if rest <= 0:
                return None
            self.sock.settimeout(rest)
            try:
                data = self.sock.recv(256 * 1024)
            except TimeoutError:
                return None
            except OSError:
                return None
            if not data:
                return None
            for h, _ in self.reader.feed(data):
                self.inbox.append(h)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def run_client(path: str, entscheidung: str = "frei", warten_s: float = 60.0, pruefen: bool = False,
               nur: list[str] | None = None) -> int:
    """Wartet auf FREIGABE und entscheidet jeden (oder nur die genannten) Einträge; Ausgang 0, wenn alles passt."""
    c = MirrorClient(path)
    ende = time.monotonic() + warten_s
    ok = True

    def out(text: str) -> None:
        print(text, flush=True)

    hello = c.next(ende, lambda h: h.get("type") == "HELLO")
    if hello is None:
        out("FEHLER kein HELLO")
        return 1
    out(f"HELLO: Epoche {hello.get('epoche')}, Merkmale {hello.get('features')}")
    f = c.next(ende, lambda h: h.get("type") == "FREIGABE")
    if f is None:
        out("FEHLER keine FREIGABE (Testmodus an? Bundle-ID mit .test und KEVCAD_FREIGABE_TESTMODUS=1)")
        return 1
    ids = [e["id"] for e in f.get("eintraege") or [] if not nur or e["id"] in nur]
    out(f"FREIGABE {f['anfrage_id']}: {', '.join(e['id'] + ' (' + e.get('kurz', '') + ')' for e in f['eintraege'])}, "
        f"Ablauf {f.get('ablauf')}")
    n = 0

    def cmd(eid: str, nonce: str, wofuer: str) -> dict[str, Any] | None:
        nonlocal n
        n += 1
        cid = f"sim-{n}"
        c.send(freigabe_cmd(cid, f["anfrage_id"], nonce, eid, wofuer))
        res = c.next(time.monotonic() + 45, lambda h: h.get("type") == "CMD_RES" and h.get("reply_to") == cid)
        out(f"CMD freigabe {eid} {wofuer} → " + (json.dumps(res, ensure_ascii=False) if res else "keine Antwort"))
        return res

    if pruefen and ids:
        res = cmd(ids[0], "0" * 32, entscheidung)
        good = bool(res) and res.get("ok") is False and res.get("status") == "ungueltig"
        ok &= good
        out(f"{'OK    ' if good else 'FEHLER'} falsche Nonce abgewiesen")
    for eid in ids:
        res = cmd(eid, f["nonce"], entscheidung)
        good = bool(res) and res.get("ok") is True and res.get("status") == entscheidung
        ok &= good
        out(f"{'OK    ' if good else 'FEHLER'} {eid} {entscheidung}")
        e = c.next(time.monotonic() + 5, lambda h: h.get("type") == "FREIGABE_ENDE" and h.get("id") == eid)
        good = bool(e) and e.get("grund") == "iphone" and e.get("ergebnis") == entscheidung
        ok &= good
        out(f"{'OK    ' if good else 'FEHLER'} FREIGABE_ENDE {json.dumps(e, ensure_ascii=False) if e else 'fehlt'}")
    if pruefen and ids:
        res = cmd(ids[0], f["nonce"], entscheidung)
        good = bool(res) and res.get("ok") is False and res.get("status") in ("verbraucht", "beendet")
        ok &= good
        out(f"{'OK    ' if good else 'FEHLER'} Wiederholung abgewiesen ({res.get('status') if res else '-'})")
    if not nur:
        e = c.next(time.monotonic() + 5, lambda h: h.get("type") == "FREIGABE_ENDE" and "id" not in h)
        good = bool(e) and e.get("grund") == "iphone"
        ok &= good
        out(f"{'OK    ' if good else 'FEHLER'} Anfrage erledigt: {json.dumps(e, ensure_ascii=False) if e else 'fehlt'}")
    c.close()
    out("ALLES OK" if ok else "FEHLER")
    return 0 if ok else 1


def _interrupt(*_: Any) -> None:
    raise KeyboardInterrupt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--socket", help="Socket-Pfad, kurz halten, z. B. /tmp/kcsim.sock")
    ap.add_argument("--client", metavar="PFAD", help="statt zu lauschen: als Gegenstelle mit PFAD verbinden und "
                    "Freigaben entscheiden (siehe Moduldoku)")
    ap.add_argument("--entscheidung", choices=("frei", "abgelehnt"), default="frei", help="bei --client")
    ap.add_argument("--nur", default="", help="bei --client: nur diese ids (Komma), sonst alle Einträge")
    ap.add_argument("--pruefen", action="store_true", help="bei --client: falsche Nonce und Wiederholung prüfen")
    ap.add_argument("--warten", type=float, default=60.0, help="bei --client: so lange auf FREIGABE warten (s)")
    ap.add_argument("--freigabe-ablauf", type=float, default=FREIGABE_LAUFZEIT_S,
                    help="Laufzeit einer Freigabe-Anfrage in s (Vorgabe 24 h)")
    ap.add_argument("--recording", type=Path, default=DEFAULT_RECORDING, help="Kernel-Aufzeichnung (.kcadrec)")
    ap.add_argument("--speed", type=float, default=1.0, help="Abspielgeschwindigkeit (1 = Echtzeit)")
    ap.add_argument("--part-delay-ms", type=float, default=0.0, help="zusätzliche Pause je Teil beim Aufbau")
    ap.add_argument("--start", choices=("leer", "fertig"), default="leer",
                    help="leer: Aufbau nach dem ersten WATCH; fertig: Szene von Anfang an vollständig")
    ap.add_argument("--bundle-id", default="de.upvis.kevcad.sim")
    ap.add_argument("--session-id", default=DEFAULT_SESSION, help="Sitzungskennung in agents")
    ap.add_argument("--auto", action="store_true", help="Aktionen der Reihe nach von selbst abspielen")
    ap.add_argument("--intervall", type=float, default=4.0, help="Abstand der Aktionen bei --auto in s")
    ap.add_argument("--neustart-alle", type=int, default=0, help="bei --auto jede N-te Runde ein Neustart")
    ap.add_argument("--aspect", type=float, default=1.6, help="Seitenverhältnis der Mac-Ansicht in kamera.aspect")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    if args.client:
        return run_client(args.client, args.entscheidung, args.warten, args.pruefen,
                          [i for i in args.nur.split(",") if i.strip()] or None)
    if not args.socket:
        ap.error("--socket oder --client angeben")
    sim = MirrorSim(args.socket, args.recording, speed=args.speed, part_delay_ms=args.part_delay_ms,
                    bundle_id=args.bundle_id, session_id=args.session_id, start_full=args.start == "fertig",
                    build_on_watch=args.start == "leer", quiet=args.quiet, aspect=args.aspect,
                    freigabe_ablauf_s=args.freigabe_ablauf)
    signal.signal(signal.SIGTERM, _interrupt)
    sim.start()
    if args.auto:
        threading.Thread(target=sim.auto, args=(args.intervall, args.neustart_alle), daemon=True).start()
    try:
        if not command_loop(sim):
            # stdin zu (z. B. im Hintergrund gestartet): weiterlaufen bis Strg-C bzw. SIGTERM
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

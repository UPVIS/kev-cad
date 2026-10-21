"""Spiegel-Rahmen (MIRROR.md, Version 1) aus einer Kernel-Aufzeichnung erzeugen: Referenz für Netzformat, Hash und
Blöcke und eine Folge typischer Zustandswechsel für die iPhone-Ansicht. Vorstufe von `mirror_sim.py` (M1).

Ausgabe: eine Datei mit Rahmen hintereinander wie auf dem Spiegel-Socket (u32 LE Kopf, JSON, u32 LE Nutzlast,
Nutzlast). Jeder Kopf trägt zusätzlich `rec_t_ms`, den Zeitpunkt in ms für ein Abspielen in Echtzeit.

Aufruf:  .venv/bin/python tools/mirror_demo.py <Aufzeichnung.kcadrec> <Ausgabe.kcadmirror>
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import secrets
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kevcad_kernel.protocol import FrameReader, encode_frame  # noqa: E402

BLOCK = 64 * 1024
HEADER_LIMIT = 16 * 1024
COMPRESSION_LZFSE = 0x801
_lib = ctypes.CDLL("/usr/lib/libcompression.dylib")
for _fn in (_lib.compression_encode_buffer, _lib.compression_decode_buffer):
    _fn.restype = ctypes.c_size_t
    _fn.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p,
                    ctypes.c_int]


def lzfse_encode(raw: bytes) -> bytes:
    cap = len(raw) + len(raw) // 8 + 4096
    dst = ctypes.create_string_buffer(cap)
    n = _lib.compression_encode_buffer(dst, cap, raw, len(raw), None, COMPRESSION_LZFSE)
    if n == 0:
        raise RuntimeError("LZFSE: Zielpuffer zu klein")
    return dst.raw[:n]


def lzfse_decode(packed: bytes, raw_size: int) -> bytes:
    dst = ctypes.create_string_buffer(raw_size)
    n = _lib.compression_decode_buffer(dst, raw_size, packed, len(packed), None, COMPRESSION_LZFSE)
    return dst.raw[:n]


def mesh_raw(header: dict, payload: bytes) -> bytes:
    """`kcad-mesh-1`: die Arrays aus PART_UPSERT ohne die B-Rep-Punkte am Ende."""
    return payload[:len(payload) - header["counts"]["vtx"] * 3 * 4]


def mesh_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def read_frames(path: Path) -> list[tuple[dict, bytes]]:
    reader = FrameReader()
    return list(reader.feed(path.read_bytes()))


def look_from(direction: tuple[float, float, float]) -> list[float]:
    """Quaternion (x, y, z, w) Kamera → Welt für eine Kamera, die aus `direction` (vom Drehpunkt zur Kamera) auf den
    Drehpunkt schaut, Welt-Z oben im Bild."""
    dx, dy, dz = direction
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    back = (dx / n, dy / n, dz / n)  # Kamera +Z zeigt von der Szene weg (Blick −Z)
    up_w = (0.0, 0.0, 1.0)
    rx = (up_w[1] * back[2] - up_w[2] * back[1], up_w[2] * back[0] - up_w[0] * back[2],
          up_w[0] * back[1] - up_w[1] * back[0])
    rn = math.sqrt(sum(c * c for c in rx)) or 1.0
    right = tuple(c / rn for c in rx)
    up = (back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2],
          back[0] * right[1] - back[1] * right[0])
    m = [[right[0], up[0], back[0]], [right[1], up[1], back[1]], [right[2], up[2], back[2]]]
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)
    return [round(c, 6) for c in q]


def build(recording: Path) -> list[tuple[dict, bytes]]:
    frames = read_frames(recording)
    parts: dict[str, tuple[dict, bytes]] = {}
    run = 0
    project = {"name": "Projekt"}
    for h, p in frames:
        if h["type"] == "PART_UPSERT":
            parts[h["name"]] = (h, p)
            run = h.get("run", run)
        elif h["type"] == "PART_REMOVE":
            parts.pop(h["name"], None)
        elif h["type"] == "PROJECT":
            project = {"name": h["name"]}

    epoche = secrets.token_hex(8)
    out: list[tuple[dict, bytes]] = []
    t = 0.0
    seq = 0

    def emit(header: dict, payload: bytes = b"", dt: float = 0.0) -> None:
        nonlocal t, seq
        t += dt
        seq += 1
        out.append(({**header, "seq": seq, "rec_t_ms": round(t, 1)}, payload))

    lo = [min(h["bbox"]["min"][i] for h, _ in parts.values()) for i in range(3)]
    hi = [max(h["bbox"]["max"][i] for h, _ in parts.values()) for i in range(3)]
    pivot = [round((a + b) / 2, 3) for a, b in zip(lo, hi)]
    diag = math.dist(lo, hi)
    agents = [{"session_id": "00000000-0000-4000-8000-000000000001", "aktiv": True,
               "seit": "2026-10-21T21:50:00Z", "taetigkeit": "baut " + project["name"]}]

    emit({"type": "HELLO", "prio": "zustand", "version": 1, "epoche": epoche, "app_build": 45,
          "bundle_id": "de.upvis.kevcad", "features": ["kcad-mesh-1"],
          "project": {"path": "/Users/kevin/Documents/Kev CAD/" + project["name"], "name": project["name"]},
          "agents": agents})
    emit({"type": "AGENTS", "prio": "zustand", "epoche": epoche, "agents": agents}, dt=5)

    meshes: dict[str, tuple[bytes, int]] = {}
    entries = []
    for name, (h, p) in parts.items():
        raw = mesh_raw(h, p)
        digest = mesh_hash(raw)
        packed = lzfse_encode(raw)
        assert lzfse_decode(packed, len(raw)) == raw
        meshes[digest] = (packed, len(raw))
        c = h["counts"]
        entries.append({"name": name, "hash": digest, "color": h["color"], "material": h.get("material"),
                        "bbox": h["bbox"], "counts": {k: c[k] for k in ("vert", "tri", "face", "edge", "epts")}})

    kamera = {"rotation": look_from((1.0, -1.2, 0.8)), "pivot": pivot, "distance": round(diag * 1.6, 1),
              "fov": 45.0, "ortho": False, "ortho_scale": round(diag * 1.2, 1)}
    rev = 1
    pages: list[list[dict]] = [[]]
    size = 0
    for entry in entries:  # Seiten so füllen, dass jeder Kopf unter 16 KB bleibt (mit Reserve für die übrigen Felder)
        n = len(json.dumps(entry, ensure_ascii=False).encode())
        if pages[-1] and size + n > HEADER_LIMIT - 1024:
            pages.append([])
            size = 0
        pages[-1].append(entry)
        size += n + 1
    for i, page in enumerate(pages):
        emit({"type": "SCENE", "prio": "szene", "epoche": epoche, "project": project, "run": run,
              "bbox": {"min": lo, "max": hi}, "seite": i, "seiten": len(pages), "parts": page}, dt=10 if i == 0 else 1)
    emit({"type": "STATE", "prio": "zustand", "epoche": epoche, "rev": rev, "kamera": kamera,
          "auswahl": {"run": run, "refs": []}, "verborgen": [], "isoliert": None, "hervorgehoben": [],
          "darstellung": "shaded_edges", "schnitt": None, "masse": [], "befunde": [],
          "lauf": {"run": run, "laeuft": False, "schritt": None, "fehler": None}}, dt=1)

    for digest, (packed, raw_size) in meshes.items():
        blocks = [packed[i:i + BLOCK] for i in range(0, len(packed), BLOCK)] or [b""]
        for i, block in enumerate(blocks):
            emit({"type": "MESH", "prio": "netz", "hash": digest, "format": "kcad-mesh-1", "block": i,
                  "blocks": len(blocks), "bytes": len(packed), "roh_bytes": raw_size}, block, dt=2)

    names = list(parts)
    first = names[0]
    # Drehteller: eine volle Umdrehung um Welt-Z in 3 s, 30 Stände je Sekunde
    for k in range(1, 91):
        a = math.radians(-50 + k * 4)
        rev += 1
        emit({"type": "CAMERA", "prio": "kamera", "epoche": epoche, "rev": rev, "quelle": "mac",
              "kamera": {**kamera, "rotation": look_from((math.cos(a), math.sin(a), 0.65))}}, dt=33.3)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "mac",
          "auswahl": {"run": run, "refs": [first]}}, dt=400)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "agent",
          "hervorgehoben": [{"refs": [first], "color": [1.0, 0.6, 0.0, 1.0], "label": "geändert"}]}, dt=600)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "iphone",
          "verborgen": names[1:3]}, dt=800)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "iphone",
          "isoliert": [first]}, dt=800)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "iphone",
          "isoliert": None, "verborgen": []}, dt=800)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "mac",
          "darstellung": "xray"}, dt=600)
    # Ein neuer Lauf: Teil kommt neu (gleiches Netz, gleicher Hash), Auswahl wird geleert
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "agent",
          "lauf": {"run": run + 1, "laeuft": True, "schritt": "Rahmen", "fehler": None}}, dt=800)
    emit({"type": "PART", "prio": "szene", "epoche": epoche, "op": "upsert", "run": run + 1, **entries[0]}, dt=300)
    rev += 1
    emit({"type": "STATE_DELTA", "prio": "zustand", "epoche": epoche, "rev": rev, "quelle": "agent",
          "lauf": {"run": run + 1, "laeuft": False, "schritt": None, "fehler": None},
          "auswahl": {"run": run + 1, "refs": []}, "darstellung": "shaded_edges"}, dt=500)
    # Befehle vom iPhone (Richtung VB → KC) und die Antwort, als Beispiel in derselben Datei
    emit({"type": "CMD", "prio": "kamera", "id": "i1", "op": "kamera", "args": {"kamera": kamera}}, dt=300)
    emit({"type": "CMD", "prio": "zustand", "id": "i2", "op": "auswahl",
          "args": {"refs": [first], "run": run + 1, "modus": "setzen"}}, dt=300)
    emit({"type": "CMD_RES", "prio": "zustand", "reply_to": "i2", "ok": True, "fehler": None}, dt=20)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    frames = build(args.recording)
    with open(args.out, "wb") as f:
        for h, p in frames:
            f.write(encode_frame(h, p))
    blocks = sum(1 for h, _ in frames if h["type"] == "MESH")
    print(f"{args.out.name}: {len(frames)} Rahmen, davon {blocks} Netzblöcke, {args.out.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

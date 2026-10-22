"""Erzeugt die Testdateien des Spiegels (MIRROR.md, Abschnitt „Testdateien“) aus echten Läufen.

Aufruf (im Ordner kernel):  .venv/bin/python tools/make_mirror_fixtures.py [Zielordner]
Ziel: mirror-fixtures/ im Wurzelordner des Repos. Quellen:

- samples/mirror-recordings/gestell.kcadrec (17 Teile): Szene, Zustand, Befehle
- samples/mirror-recordings/drehknopf.kcadrec (ein Teil, 6.680 Dreiecke): PART und das Netz über zwei Blöcke

Je Datei ein Rahmen (u32 LE Kopf, JSON, u32 LE Nutzlast, Nutzlast). Epoche, Zeiten und seq sind fest, damit die
Dateien bei jedem Lauf byte-gleich entstehen. `fixtures.json` hält die erwarteten Werte, die beide Seiten prüfen
(Kev CAD in KevCADWireTests und pytest, VoiceBridge in seinen eigenen Tests).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from kevcad_kernel.protocol import encode_frame  # noqa: E402
from mirror_demo import look_from, read_frames  # noqa: E402
from mirror_sim import (  # noqa: E402
    demo_freigabe_eintraege,
    freigabe_cmd,
    freigabe_ende_header,
    freigabe_header,
    pack_mesh,
    scene_pages,
    union_bbox,
)

RECORDINGS = ROOT.parent / "samples" / "mirror-recordings"
ZIEL = ROOT.parent / "mirror-fixtures"
EPOCHE = "0123456789abcdef"
SESSION_A = "6b1f2c3d-0000-4000-8000-00000000000a"
SESSION_B = "6b1f2c3d-0000-4000-8000-00000000000b"
# Freigabe (Version 1.1): feste Werte, damit die Dateien byte-gleich entstehen. Die Nonce ist ein Beispiel, keine echte.
ANFRAGE = "F-0001-5c1e9a27"
NONCE = "9f86d081884c7d659a2feaa0c55ad015"
ABLAUF = "2026-10-23T14:03:12Z"


def recorded_parts(name: str) -> list[tuple[dict[str, Any], Any]]:
    return [pack_mesh(h, p) for h, p in read_frames(RECORDINGS / name) if h["type"] == "PART_UPSERT"]


def build() -> tuple[dict[str, bytes], dict[str, Any]]:
    gestell = recorded_parts("gestell.kcadrec")
    knopf_entry, knopf_mesh = recorded_parts("drehknopf.kcadrec")[0]
    parts = [e for e, _ in gestell]
    names = [p["name"] for p in parts]
    bbox = union_bbox([p["bbox"] for p in parts])
    lo, hi = bbox["min"], bbox["max"]
    pivot = [round((a + b) / 2, 3) for a, b in zip(lo, hi)]
    kamera = {"rotation": look_from((1.0, -1.2, 0.8)), "pivot": pivot, "distance": 2152.6, "fov": 45.0,
              "ortho": False, "ortho_scale": 1614.4, "aspect": 1.6}
    agents = [
        {"session_id": SESSION_A, "aktiv": True, "seit": "2026-10-21T21:50:00Z", "taetigkeit": "führt model.py aus",
         "zuletzt": "2026-10-21T22:05:12Z"},
        {"session_id": SESSION_B, "aktiv": False, "seit": "2026-10-21T21:58:30Z", "taetigkeit": "schaut auf den Stand"},
    ]
    files: dict[str, bytes] = {}
    expect: dict[str, Any] = {"version": 1, "epoche": EPOCHE, "files": {}}

    def add(file: str, header: dict[str, Any], prio: str, seq: int, payload: bytes = b"", **values: Any) -> None:
        full = {**header, "seq": seq, "prio": prio}
        files[file] = encode_frame(full, payload)
        expect["files"][file] = {"type": header["type"], "prio": prio, "seq": seq, "payload_bytes": len(payload),
                                 **values}

    # Handschlag (seq je Absender: VB → KC und KC → VB zählen getrennt)
    add("hello_vb.bin", {"type": "HELLO", "protocol": "kevcad-mirror", "version": 1, "client": "voicebridge-mac",
                         "features": ["kcad-mesh-1"]}, "zustand", 1)
    add("hello_kc.bin", {"type": "HELLO", "version": 1, "epoche": EPOCHE, "app_build": 52,
                         "bundle_id": "de.upvis.kevcad", "features": ["kcad-mesh-1"],
                         "project": {"path": "/Users/kevin/Documents/Kev CAD/gestell", "name": "gestell"},
                         "agents": agents}, "zustand", 1, agents=2, aktiv=SESSION_A)
    add("agents.bin", {"type": "AGENTS", "epoche": EPOCHE, "agents": agents}, "zustand", 2, agents=2, aktiv=SESSION_A)
    add("watch.bin", {"type": "WATCH", "dauer_s": 300, "geraet": "iPhone von Kevin"}, "zustand", 2)
    add("unwatch.bin", {"type": "UNWATCH"}, "zustand", 9)

    # Szene: gestell in einer Seite, Lauf 3
    pages = scene_pages(EPOCHE, {"path": "/geheim", "name": "gestell"}, 3, bbox, parts)
    assert len(pages) == 1
    add("scene.bin", pages[0], "szene", 4, parts=len(parts), first=parts[0], names=names, bbox=bbox,
        triangles=sum(p["counts"]["tri"] for p in parts), hashes=len({p["hash"] for p in parts}))

    # Ein Teil dazu: der Drehknopf (Netz gepackt über zwei Blöcke)
    add("part_upsert.bin", {"type": "PART", "epoche": EPOCHE, "op": "upsert", "run": 4, **knopf_entry}, "szene", 5,
        part=knopf_entry)
    add("part_remove.bin", {"type": "PART", "epoche": EPOCHE, "op": "remove", "run": 4, "name": "Deckel"}, "szene", 6,
        name="Deckel")
    add("mesh_req.bin", {"type": "MESH_REQ", "hashes": [knopf_mesh.hash, parts[8]["hash"]]}, "zustand", 3,
        hashes=[knopf_mesh.hash, parts[8]["hash"]])
    assert knopf_mesh.blocks == 2, f"Drehknopf: {knopf_mesh.blocks} Blöcke statt 2"
    for i, file in ((0, "mesh_block_1.bin"), (1, "mesh_block_last.bin")):
        h, p = knopf_mesh.block(i)
        add(file, h, "netz", 7 + i, p, hash=knopf_mesh.hash, block=i, blocks=2, bytes=len(knopf_mesh.packed),
            roh_bytes=knopf_mesh.raw_bytes, counts=knopf_entry["counts"])

    # Zustand
    state = {
        "kamera": kamera,
        "auswahl": {"run": 3, "refs": [names[0], "Deckel#f3"]},
        "verborgen": [names[9]],
        "isoliert": None,
        "hervorgehoben": [{"refs": ["Deckel"], "color": [1.0, 0.6, 0.0, 1.0], "label": "geändert"}],
        "darstellung": "shaded_edges",
        "schnitt": {"axis": "z", "normal": [0.0, 0.0, 1.0], "offset": 450.0},
        "masse": [{"id": "m-1", "kind": "distance", "points": [[-400.0, -300.0, 0.0], [400.0, -300.0, 0.0]],
                   "text": "Abstand 800,000 mm (dx 800,000)"}],
        "befunde": [],
        "lauf": {"run": 3, "laeuft": False, "schritt": None, "fehler": None},
    }
    add("state.bin", {"type": "STATE", "epoche": EPOCHE, "rev": 17, **state}, "zustand", 10, state=state)
    add("state_delta_auswahl.bin", {"type": "STATE_DELTA", "epoche": EPOCHE, "rev": 18, "quelle": "mac",
                                    "auswahl": {"run": 3, "refs": [names[4]]}}, "zustand", 11,
        fields=["auswahl"], quelle="mac")
    iso = [n for n in names if n.startswith("Gestell/")]
    add("state_delta_sichtbarkeit.bin", {"type": "STATE_DELTA", "epoche": EPOCHE, "rev": 19, "quelle": "iphone",
                                         "verborgen": [n for n in names if n not in iso], "isoliert": iso},
        "zustand", 12, fields=["verborgen", "isoliert"], quelle="iphone", isoliert=iso)
    add("state_delta_alle_zeigen.bin", {"type": "STATE_DELTA", "epoche": EPOCHE, "rev": 20, "quelle": "iphone",
                                        "verborgen": [], "isoliert": None}, "zustand", 13,
        fields=["verborgen", "isoliert"], quelle="iphone", isoliert=None)
    kamera2 = {**kamera, "rotation": look_from((-1.0, -1.0, 0.6)), "distance": 1800.0}
    add("camera.bin", {"type": "CAMERA", "epoche": EPOCHE, "rev": 21, "kamera": kamera2, "quelle": "mac"}, "kamera", 14,
        kamera=kamera2)

    # Befehle vom iPhone (VB → KC) und die Antwort
    add("cmd_kamera.bin", {"type": "CMD", "id": "i-41", "op": "kamera", "args": {"kamera": kamera2}}, "kamera", 4,
        op="kamera", id="i-41")
    add("cmd_auswahl.bin", {"type": "CMD", "id": "i-42", "op": "auswahl",
                            "args": {"refs": [names[0]], "run": 3, "modus": "setzen"}}, "zustand", 5,
        op="auswahl", id="i-42", refs=[names[0]])
    add("cmd_sichtbarkeit.bin", {"type": "CMD", "id": "i-43", "op": "sichtbarkeit",
                                 "args": {"mode": "isolate", "refs": ["Gestell"]}}, "zustand", 6,
        op="sichtbarkeit", id="i-43")
    add("cmd_einpassen.bin", {"type": "CMD", "id": "i-45", "op": "einpassen", "args": {"refs": ["Deckel"]}},
        "zustand", 7, op="einpassen", id="i-45", refs=["Deckel"])
    add("cmd_res.bin", {"type": "CMD_RES", "reply_to": "i-42", "ok": True, "fehler": None}, "zustand", 15,
        reply_to="i-42", ok=True)
    add("cmd_res_fehler.bin", {"type": "CMD_RES", "reply_to": "i-44", "ok": False,
                               "fehler": "Unbekannte Darstellung 'glas'"}, "zustand", 16, reply_to="i-44", ok=False)

    # Freigabe vom iPhone (Version 1.1): Anfrage ohne Miete, Entscheidung je Eintrag, Ende je Eintrag und der Anfrage
    eintraege = demo_freigabe_eintraege("kugelschieber", "Für die Lenksperren am Kugelschieber")
    add("freigabe.bin", freigabe_header(EPOCHE, ANFRAGE, NONCE, ABLAUF, eintraege), "zustand", 17,
        anfrage_id=ANFRAGE, nonce=NONCE, ablauf=ABLAUF, ids=[e["id"] for e in eintraege],
        links=[e.get("link") for e in eintraege])
    add("cmd_freigabe.bin", freigabe_cmd("i-46", ANFRAGE, NONCE, "rohr-alfer-16x1", "frei"), "zustand", 8,
        op="freigabe", id="i-46", eintrag="rohr-alfer-16x1", entscheidung="frei")
    add("cmd_freigabe_ablehnen.bin", freigabe_cmd("i-47", ANFRAGE, NONCE, "alutec-05200", "abgelehnt"), "zustand", 10,
        op="freigabe", id="i-47", eintrag="alutec-05200", entscheidung="abgelehnt")
    add("cmd_res_freigabe.bin", {"type": "CMD_RES", "reply_to": "i-46", "ok": True, "fehler": None, "status": "frei"},
        "zustand", 18, reply_to="i-46", ok=True, status="frei")
    add("freigabe_ende_eintrag.bin", freigabe_ende_header(EPOCHE, ANFRAGE, "iphone", "rohr-alfer-16x1", "frei"),
        "zustand", 19, anfrage_id=ANFRAGE, id="rohr-alfer-16x1", grund="iphone", ergebnis="frei")
    add("cmd_res_freigabe_fehler.bin", {"type": "CMD_RES", "reply_to": "i-48", "ok": False,
                                        "fehler": "Die Nonce passt nicht zur Anfrage.", "status": "ungueltig"},
        "zustand", 20, reply_to="i-48", ok=False, status="ungueltig")
    add("freigabe_ende.bin", freigabe_ende_header(EPOCHE, ANFRAGE, "abgelaufen"), "zustand", 21, anfrage_id=ANFRAGE,
        id=None, grund="abgelaufen")
    return files, expect


def write(target: Path) -> dict[str, Any]:
    files, expect = build()
    target.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (target / name).write_bytes(data)
    (target / "fixtures.json").write_text(json.dumps(expect, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return expect


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ZIEL
    expect = write(target)
    print(f"{len(expect['files'])} Testdateien in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

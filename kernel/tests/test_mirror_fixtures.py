"""Testdateien des Spiegels (mirror-fixtures/): byte-gleich reproduzierbar, je ein Rahmen, Grenzen eingehalten, das
Netz des Drehknopfs über zwei Blöcke ergibt den Hash aus PART."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from mirror_testutil import lzfse_decode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import make_mirror_fixtures  # noqa: E402
from kevcad_kernel.protocol import FrameReader  # noqa: E402

FIXTURES = ROOT.parent / "mirror-fixtures"
REQUIRED = ["hello_kc.bin", "agents.bin", "scene.bin", "part_upsert.bin", "mesh_block_1.bin", "mesh_block_last.bin",
            "state.bin", "state_delta_auswahl.bin", "state_delta_sichtbarkeit.bin", "camera.bin", "cmd_kamera.bin",
            "cmd_auswahl.bin", "cmd_res.bin"]


def frame(name: str) -> tuple[dict, bytes]:
    frames = FrameReader().feed((FIXTURES / name).read_bytes())
    assert len(frames) == 1, name
    return frames[0]


def test_fixtures_are_reproducible(tmp_path):
    make_mirror_fixtures.write(tmp_path)
    committed = sorted(p.name for p in FIXTURES.iterdir())
    assert sorted(p.name for p in tmp_path.iterdir()) == committed
    for name in committed:
        assert (tmp_path / name).read_bytes() == (FIXTURES / name).read_bytes(), name


def test_every_file_is_one_frame_within_limits():
    expect = json.loads((FIXTURES / "fixtures.json").read_text(encoding="utf-8"))
    assert set(REQUIRED) <= set(expect["files"])
    for name, values in expect["files"].items():
        h, p = frame(name)
        raw_header = (FIXTURES / name).read_bytes()[4:4 + int.from_bytes((FIXTURES / name).read_bytes()[:4], "little")]
        assert len(raw_header) <= 16 * 1024 and len(p) <= 64 * 1024, name
        assert h["type"] == values["type"] and h["prio"] == values["prio"] and h["seq"] == values["seq"], name
        assert len(p) == values["payload_bytes"], name
        if "epoche" in h:
            assert h["epoche"] == expect["epoche"]


def test_mesh_over_two_blocks_matches_part_hash():
    part, _ = frame("part_upsert.bin")
    (h1, p1), (h2, p2) = frame("mesh_block_1.bin"), frame("mesh_block_last.bin")
    assert (h1["block"], h2["block"], h1["blocks"]) == (0, 1, 2)
    assert h1["hash"] == h2["hash"] == part["hash"]
    raw = lzfse_decode(p1 + p2, h1["roh_bytes"])
    assert hashlib.sha256(raw).hexdigest()[:16] == part["hash"]
    c = part["counts"]
    assert len(raw) == 4 * (c["vert"] * 6 + c["tri"] * 4 + c["epts"] * 3 + c["edge"] + 1)


def test_scene_has_no_path_and_all_parts():
    h, _ = frame("scene.bin")
    assert h["project"] == {"name": "gestell"}
    assert h["seiten"] == 1 and len(h["parts"]) == 17
    hello, _ = frame("hello_kc.bin")
    assert hello["project"]["path"].endswith("/gestell")
    assert [a["aktiv"] for a in hello["agents"]].count(True) == 1

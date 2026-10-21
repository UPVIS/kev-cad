import json
from pathlib import Path

import numpy as np

from kevcad_kernel.protocol import FrameReader, PartGeometry, encode_frame, pack_part, unpack_part

FIXTURES = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def test_frame_roundtrip_byte_by_byte():
    data = encode_frame({"type": "HELLO", "seq": 1}, b"") + encode_frame({"type": "X", "seq": 2}, b"\x01\x02\x03")
    reader = FrameReader()
    got = []
    for i in range(len(data)):
        got += reader.feed(data[i:i + 1])
    assert [h["type"] for h, _ in got] == ["HELLO", "X"]
    assert got[1][1] == b"\x01\x02\x03"


def test_pack_unpack_part():
    g = PartGeometry(
        positions=np.zeros((3, 3), np.float32), normals=np.zeros((3, 3), np.float32),
        triangles=np.array([[0, 1, 2]], np.uint32), tri_face=np.array([0], np.int32),
        edge_points=np.zeros((2, 3), np.float32), edge_offsets=np.array([0, 2], np.uint32),
        vertices=np.zeros((3, 3), np.float32), faces=[{"t": "plane", "a": 0.5}], edges=[{"t": "line", "l": 1.0}])
    header, payload = pack_part(run=1, name="T", geometry=g, color=(1, 1, 1, 1),
                                bbox={"min": [0, 0, 0], "max": [1, 1, 1]}, props={})
    arrays = unpack_part(header, payload)
    assert arrays["triangles"].tolist() == [[0, 1, 2]]
    assert arrays["edge_offsets"].tolist() == [0, 2]


def test_fixtures_decode():
    expected = json.loads((FIXTURES / "fixtures.json").read_text())
    frames = FrameReader().feed((FIXTURES / "stream.bin").read_bytes())
    assert [h["type"] for h, _ in frames] == [f["type"] for f in expected["frames"]]
    for (header, payload), info in zip(frames, expected["frames"]):
        assert len(payload) == info["payload_bytes"]
        if header["type"] == "PART_UPSERT":
            exp = expected["parts"][info["file"]]
            arrays = unpack_part(header, payload)
            assert header["counts"] == exp["counts"]
            assert np.allclose(arrays["positions"][0], exp["first_position"], atol=1e-3)
            assert arrays["tri_face"][-1] == exp["tri_face_last"]
            assert len(header["faces"]) == header["counts"]["face"]
            assert len(header["edges"]) == header["counts"]["edge"]

"""Scan mit dem iPhone (SCAN.md): Empfänger (HTTP, ZIP-Prüfung), Ablage, Auswahl für fotomess, MCP-Werkzeuge.

Eigene Ports (vom System vergeben, nie 47823/47824), kein Bonjour, Ablage im Temp-Ordner.
"""

from __future__ import annotations

import http.client
import io
import json
import urllib.parse
import zipfile
from pathlib import Path

import anyio
import pytest
from mcp_testutil import start_server, texts, with_client

from kevcad_kernel.scan import ablage
from kevcad_kernel.scan.empfang import Empfaenger
from kevcad_kernel.scan.vermessen import bilder_waehlen, lage_aus_messung


def _scan_zip(oben: str | None = "Würfel.kevscan", extra: dict[str, bytes] | None = None) -> bytes:
    puffer = io.BytesIO()
    vor = f"{oben}/" if oben else ""
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(vor + "meta.json", json.dumps({"format": "kevscan", "version": 1, "name": "Würfel",
                                                  "geraet": "iPhone16,2"}))
        z.writestr(vor + "odometry.csv", "timestamp, frame, x, y, z, qx, qy, qz, qw\n0.0, 0, 0, 0, 0, 0, 0, 0, 1\n")
        z.writestr(vor + "fotos.json", json.dumps({"fotos": [{"datei": "000.jpg"}]}))
        for name, daten in (extra or {}).items():
            z.writestr(name, daten)
    return puffer.getvalue()


def _post(port: int, body: bytes, name: str | None = "Würfel Test") -> tuple[int, dict]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    kopf = {"Content-Type": "application/zip"}
    if name is not None:
        kopf["X-KevScan-Name"] = urllib.parse.quote(name)
    c.request("POST", "/scan", body=body, headers=kopf)
    r = c.getresponse()
    return r.status, json.loads(r.read())


@pytest.fixture
def empf(tmp_path):
    gemeldet = []
    e = Empfaenger(tmp_path / "Scans", port=0, host="127.0.0.1", name="Testrechner", bonjour=False,
                   projekt=lambda: "Probe", bei_empfang=gemeldet.append)
    e.start()
    e.gemeldet = gemeldet
    yield e
    e.stop()


def test_empfaenger_nimmt_scan_an(empf):
    assert empf.port not in (47823, 47824)
    c = http.client.HTTPConnection("127.0.0.1", empf.port, timeout=10)
    c.request("GET", "/")
    info = json.loads(c.getresponse().read())
    assert info == {"dienst": "kevscan", "version": 1, "rechner": "Testrechner", "projekt": "Probe"}

    code, antwort = _post(empf.port, _scan_zip())
    assert code == 200 and antwort["ok"], antwort
    ordner = Path(antwort["ordner"])
    assert ordner.parent == empf.ordner and ordner.name.endswith("_Würfel Test")
    assert (ordner / "meta.json").is_file() and (ordner / ablage.STATUS).is_file()
    # ohne Ordner oben im ZIP geht es auch
    code, antwort2 = _post(empf.port, _scan_zip(oben=None), name=None)
    assert code == 200 and (Path(antwort2["ordner"]) / "meta.json").is_file()
    assert Path(antwort2["ordner"]).name.endswith("_Würfel")
    liste = ablage.liste(empf.ordner)
    assert {e["id"] for e in liste} == {ordner.name, Path(antwort2["ordner"]).name}
    assert liste[0]["fotos"] == 1 and liste[0]["videobilder"] == 1 and liste[0]["zustand"] == "neu"
    for _ in range(50):
        if len(empf.gemeldet) == 2:
            break
        anyio.run(anyio.sleep, 0.05)
    assert len(empf.gemeldet) == 2


def test_empfaenger_lehnt_ab(empf, tmp_path):
    # Pfad außerhalb des Ziels
    code, antwort = _post(empf.port, _scan_zip(extra={"../boese.txt": b"x"}))
    assert code == 400 and not antwort["ok"] and "Pfad" in antwort["fehler"]
    assert not (empf.ordner.parent / "boese.txt").exists()
    # kein Scan
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("irgendwas.txt", "x")
    code, antwort = _post(empf.port, puffer.getvalue())
    assert code == 400 and "meta.json" in antwort["fehler"]
    # kein ZIP
    code, antwort = _post(empf.port, b"kein zip")
    assert code == 400
    # zu groß
    empf.max_bytes = 10
    code, antwort = _post(empf.port, _scan_zip())
    assert code == 413
    assert not [p for p in empf.ordner.iterdir() if not p.name.startswith(".")]


def test_ablage_finden_und_variante(tmp_path):
    basis = tmp_path / "Scans"
    zipdatei = tmp_path / "Würfel.kevscan.zip"
    zipdatei.write_bytes(_scan_zip())
    ordner = ablage.finde(basis, str(zipdatei))  # Import aus Datei (AirDrop)
    assert ordner.parent == basis and ablage.lese_status(ordner)["quelle"] == "datei"
    assert ablage.finde(basis, None) == ordner
    assert ablage.finde(basis, "würfel") == ordner
    with pytest.raises(ablage.ScanFehler):
        ablage.finde(basis, "gibtsnicht")
    assert ablage.variante("/x/de.upvis.kevcad/kernel.sock") == "de.upvis.kevcad"
    assert ablage.variante("/tmp/abc/k.sock") is None
    assert ablage.anzeigename("de.upvis.kevcad.test.ui") == "Kev CAD Test ui"
    assert ablage.scans_ordner("/a/de.upvis.kevcad.test.ui/kernel.sock") == Path("/a/de.upvis.kevcad.test.ui/Scans")


def test_laufzeit_testvariante_startet_empfaenger(monkeypatch, tmp_path):
    """Kernel einer Testvariante: Empfänger läuft (ohne Bonjour), eigener Dienst, Ablage im Datenordner."""
    import shutil
    import tempfile

    from kevcad_kernel.runtime import KernelRuntime

    basis = Path(tempfile.mkdtemp(prefix="kcs", dir=tempfile.gettempdir()))
    var = basis / "de.upvis.kevcad.test.scan"
    var.mkdir()
    monkeypatch.setenv("KEVCAD_SCAN_BONJOUR", "0")
    monkeypatch.delenv("KEVCAD_SCAN_EMPFANG", raising=False)
    monkeypatch.delenv("KEVCAD_SCANS_DIR", raising=False)
    rt = KernelRuntime(str(var / "kernel.sock"), 0, auto_run=False, start_worker=False)
    try:
        s = rt.scans()
        e = s["empfaenger"]
        assert e["laeuft"] and e["dienst"] == "_kevscan-test._tcp" and e["name"].endswith("(Kev CAD Test scan)")
        assert s["ordner"] == str(var / "Scans") and s["scans"] == []
        code, antwort = _post(e["port"], _scan_zip())
        assert code == 200 and antwort["ok"]
        assert [x["name"] for x in rt.scans()["scans"]] == ["Würfel"]
        assert not rt.scan_importieren("letzter")["ok"]  # kein Projekt offen
    finally:
        rt.close()
        shutil.rmtree(basis, ignore_errors=True)
    assert rt._scan_empfaenger is None


def test_bilder_waehlen_und_lage():
    import numpy as np

    def eintrag(i, art, az):
        a = np.radians(az)
        C = np.array([600 * np.cos(a), 600 * np.sin(a), 300.0])
        return {"name": f"{art}_{i}", "art": art, "tiefe": "t.png",
                "kamera": {"R": np.eye(3).tolist(), "t": (-C).tolist()}}

    liste = [eintrag(i, "foto", 90 * i) for i in range(3)] + [eintrag(i, "video", 10 * i) for i in range(36)]
    wahl = bilder_waehlen(liste, 6)
    assert len(wahl) == 6 and sum(1 for e in wahl if e["art"] == "foto") == 3
    lage = lage_aus_messung({"scan": {"lage": {"A": np.eye(3).tolist(), "b": [1, 2, 3], "rest_mm": 0.3,
                                               "bilder": 8}}})
    assert lage["verschiebung"] == [1, 2, 3] and lage["drehung_z"] == 0 and len(lage["matrix"]) == 16


def test_mcp_scan_werkzeuge():
    server, fake = start_server()
    try:
        def call(name, args=None):
            return anyio.run(with_client, server.url, lambda c: c.call_tool(name, args or {}))

        res = call("scans")
        text = texts(res)[0]
        assert not res.is_error and text.startswith("1 Scan in /tmp/Scans") and "Port 50123" in text
        res = call("scan_importieren", {"scan": "letzter", "schnell": True})
        assert not res.is_error and "Auswertung läuft" in texts(res)[0]
        assert fake.calls_of("scan_importieren")[-1][0] == ("letzter", None, True, 0.0)
        res = call("scan_importieren", {"scan": "Quader", "warten_s": 600})
        text = texts(res)[0]
        assert "als Referenz Quader" in text and "Hülle 200,4 × 100,8 × 50,2 mm" in text
        assert call("scan_importieren", {"warten_s": 5000}).is_error  # Schema: höchstens 900 s
    finally:
        server.stop_thread()

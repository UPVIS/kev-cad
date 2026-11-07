"""I-8 Datei ans Gerät (PROTOCOL.md): Das iPad holt Dateien, die der Kernel am Mac geschrieben hat, stückweise zum Teilen.

Nur Dateien unter den Wurzeln des Kernels (offenes Projekt, Projektordner, Datenordner, Scans); Verknüpfungen nach
draußen und andere Orte enden mit ERROR. Die Antwort geht nur an die fragende Verbindung."""

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from app_testutil import FakeApp, make_runtime

from kevcad_kernel import datei_teilen
from kevcad_kernel.protocol import (
    DATEI_STUECK_MAX, KERNEL_FAEHIGKEITEN, FAEHIGKEIT_DATEI, check_datei_message, datei_beispiele,
)


def test_beispiele_sind_gueltig():
    for name, kopf, nutz, _ in datei_beispiele():
        assert check_datei_message(kopf, nutz) == [], name
    assert FAEHIGKEIT_DATEI in KERNEL_FAEHIGKEITEN


def test_pruefung_findet_fehler():
    assert check_datei_message({"type": "DATEI_REQ", "id": "a", "pfad": "relativ.txt"})
    assert check_datei_message({"type": "DATEI_REQ", "id": "a", "pfad": "/x", "ab": -1})
    kopf = {"type": "DATEI", "reply_to": "a", "pfad": "/x/y", "name": "y", "groesse": 4, "ab": 2, "laenge": 3,
            "geaendert": 1.0}
    assert any("Dateiende" in p for p in check_datei_message(kopf, b"abc"))
    assert any("Nutzlast" in p for p in check_datei_message({**kopf, "ab": 0}, b"ab"))


@pytest.fixture()
def ablage():
    tmp = Path(tempfile.mkdtemp(prefix="kcd", dir=tempfile.gettempdir())).resolve()
    (tmp / "Projekt" / "output").mkdir(parents=True)
    (tmp / "draussen").mkdir()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_stuecke_einer_datei(ablage):
    datei = ablage / "Projekt" / "output" / "Halter.stl"
    inhalt = bytes(range(256)) * 40  # 10 240 Byte
    datei.write_bytes(inhalt)
    erlaubt = [ablage / "Projekt"]
    gesammelt = b""
    ab = 0
    while True:
        antwort = datei_teilen.stueck({"id": "a", "pfad": str(datei), "ab": ab, "max": 4096}, erlaubt)
        assert not isinstance(antwort, str), antwort
        kopf, nutz = antwort
        assert check_datei_message({**kopf, "type": "DATEI"}, nutz) == []
        assert kopf["groesse"] == len(inhalt) and kopf["ab"] == ab and kopf["name"] == "Halter.stl"
        gesammelt += nutz
        ab += kopf["laenge"]
        if ab >= kopf["groesse"]:
            break
    assert gesammelt == inhalt


def test_max_ist_begrenzt(ablage):
    datei = ablage / "Projekt" / "gross.bin"
    with datei.open("wb") as f:
        f.truncate(DATEI_STUECK_MAX + 10)
    kopf, nutz = datei_teilen.stueck({"id": "a", "pfad": str(datei), "max": DATEI_STUECK_MAX * 4}, [ablage / "Projekt"])
    assert kopf["laenge"] == DATEI_STUECK_MAX == len(nutz)


def test_nur_unter_den_wurzeln(ablage):
    fremd = ablage / "draussen" / "geheim.txt"
    fremd.write_text("nein", encoding="utf-8")
    erlaubt = [ablage / "Projekt"]
    assert "nicht im Projekt" in datei_teilen.stueck({"id": "a", "pfad": str(fremd)}, erlaubt)
    # Verknüpfung im Projekt, die hinausführt
    (ablage / "Projekt" / "link.txt").symlink_to(fremd)
    assert "nicht im Projekt" in datei_teilen.stueck({"id": "a", "pfad": str(ablage / "Projekt" / "link.txt")},
                                                      erlaubt)
    # Umweg über .. im Pfad
    umweg = str(ablage / "Projekt" / ".." / "draussen" / "geheim.txt")
    assert "nicht im Projekt" in datei_teilen.stueck({"id": "a", "pfad": umweg}, erlaubt)
    assert "gibt es nicht" in datei_teilen.stueck({"id": "a", "pfad": str(ablage / "Projekt" / "fehlt.txt")}, erlaubt)
    assert "keine Datei" in datei_teilen.stueck({"id": "a", "pfad": str(ablage / "Projekt" / "output")}, erlaubt)
    assert "Dateiende" in datei_teilen.stueck({"id": "a", "pfad": str(fremd), "ab": 99}, [ablage])


def test_wurzeln_ohne_systemwurzel(ablage, monkeypatch):
    monkeypatch.setenv("KEVCAD_PROJECTS_DIR", str(ablage / "Projekte"))
    w = datei_teilen.wurzeln(ablage / "Projekt", str(ablage / "daten" / "k.sock"))
    assert (ablage / "Projekt") in w and (ablage / "daten") in w and (ablage / "Projekte") in w
    assert Path("/") not in w


def test_ueber_die_verbindung_nur_an_die_fragende_app():
    tmp = Path(tempfile.mkdtemp(prefix="kc", dir=tempfile.gettempdir()))
    sock = str(tmp / "k.sock")
    alt = os.environ.get("KEVCAD_PROJECTS_DIR")
    os.environ["KEVCAD_PROJECTS_DIR"] = str(tmp / "Projekte")
    rt = make_runtime(sock, start_worker=False)
    mac = FakeApp(sock, geraet={"id": "mac-d", "art": "mac", "name": "Mac"})
    pad = FakeApp(sock, geraet={"id": "pad-d", "art": "ipad", "name": "iPad"})
    try:
        mac.wait_for(lambda h: h["type"] == "HELLO")
        _, _, hallo, _ = pad.wait_for(lambda h: h["type"] == "HELLO")
        assert FAEHIGKEIT_DATEI in hallo.get("faehigkeiten", [])
        datei = tmp / "Projekte" / "Halter" / "output" / "Halter.csv"
        datei.parent.mkdir(parents=True)
        datei.write_text("Teil;Anzahl\nRohr;2\n", encoding="utf-8")
        a, b = mac.mark(), pad.mark()
        pad.send({"type": "DATEI_REQ", "id": "d-1", "pfad": str(datei)})
        _, _, kopf, nutz = pad.wait_for(lambda h: h.get("reply_to") == "d-1", start=b)
        assert kopf["type"] == "DATEI" and nutz == datei.read_bytes() and kopf["groesse"] == len(nutz)
        pad.send({"type": "DATEI_REQ", "id": "d-2", "pfad": "/etc/hosts"})
        _, _, fehler, _ = pad.wait_for(lambda h: h.get("reply_to") == "d-2", start=b)
        assert fehler["type"] == "ERROR" and "nicht im Projekt" in fehler["message"]
        time.sleep(0.2)
        assert not [h for h in mac.since(a) if h["type"] in ("DATEI", "ERROR")], "Antwort ging auch an den Mac"
    finally:
        mac.close()
        pad.close()
        rt.close()
        if alt is None:
            os.environ.pop("KEVCAD_PROJECTS_DIR", None)
        else:
            os.environ["KEVCAD_PROJECTS_DIR"] = alt
        shutil.rmtree(tmp, ignore_errors=True)

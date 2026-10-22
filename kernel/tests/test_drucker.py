"""Drucken (Phase 8): Bericht und Modus, Sperre, Befehle, SSDP, Schlüsselbund, Profile, Slicen (Attrappe und echt),
MQTT und FTPS gegen die Drucker-Attrappe, Dienst mit Weg A und B, Protokoll und Testdateien.

Nie gegen den echten Drucker: alles läuft gegen ``tools/drucker_attrappe.py`` auf 127.0.0.1 mit Testwerten."""

from __future__ import annotations

import json
import threading
import time
import zipfile
from pathlib import Path

import pytest
from drucker_testutil import (
    ECHTES_BAMBU,
    TEST_SERIENNUMMER,
    TEST_ZUGANGSCODE,
    Attrappe,
    bambu_attrappe,
    benutzer_profile,
    wuerfel_stl,
)

from kevcad_kernel.drucker import befehle, schluesselbund, sperre, ssdp
from kevcad_kernel.drucker.dienst import DruckerDienst, Quelle
from kevcad_kernel.drucker.mqtt import MqttVerbindung
from kevcad_kernel.drucker.profile import Profile
from kevcad_kernel.drucker.slicen import Abgebrochen, SlicenFehler, platten_lesen, slicen
from kevcad_kernel.drucker.status import Bericht, hms_code
from kevcad_kernel.protocol import FrameReader, check_drucker_message, drucker_status_beispiel, printer_status

FIX = Path(__file__).resolve().parents[2] / "app/KevCADCore/Tests/KevCADCoreTests/Fixtures"


def warte(bedingung, zeit: float = 10.0, schritt: float = 0.02):
    ende = time.monotonic() + zeit
    while time.monotonic() < ende:
        wert = bedingung()
        if wert:
            return wert
        time.sleep(schritt)
    raise AssertionError("Bedingung nicht erfüllt")


# =====================================================================================================================
# Bericht, Befehle, Sperre


def test_bericht_mischt_deltas_und_erkennt_modus():
    b = Bericht()
    assert b.entwicklermodus is None and b.druck_status() is None
    b.aufnehmen({"print": {"gcode_state": "RUNNING", "mc_percent": 42, "layer_num": 41, "total_layer_num": 98,
                           "mc_remaining_time": 62, "nozzle_temper": 219.46, "nozzle_target_temper": 220,
                           "bed_temper": 55, "bed_target_temper": 55, "stg_cur": 0, "spd_lvl": 2,
                           "subtask_name": "Halter"}})
    b.aufnehmen({"print": {"mc_percent": 43, "layer_num": 42}})  # Delta
    d = b.druck_status()
    assert d["zustand"] == "druckt" and d["fortschritt"] == pytest.approx(0.43) and d["schicht"] == 42
    assert d["schichten"] == 98 and d["restzeit_s"] == 62 * 60 and d["geschwindigkeit"] == "standard"
    assert b.temperaturen() == {"duese": 219.5, "duese_ziel": 220.0, "bett": 55.0, "bett_ziel": 55.0}
    assert b.entwicklermodus is None  # fun noch nicht gesehen
    b.aufnehmen({"print": {"fun": "3EC1AFFF9CFF"}})
    assert b.entwicklermodus is False
    b.aufnehmen({"print": {"fun": "3EC18FFF9CFF"}})
    assert b.entwicklermodus is True
    b.aufnehmen({"info": {"command": "get_version", "module": [{"name": "ota", "sw_ver": "01.10.00.00"}]}})
    assert b.firmware == "01.10.00.00"
    b.neue_verbindung()
    assert b.entwicklermodus is None and b.firmware is None  # Modus muss je Verbindung neu kommen


def test_hms_und_fehler():
    assert hms_code(0x05000500, 0x00010007) == "0500-0500-0001-0007"
    b = Bericht()
    b.aufnehmen({"print": {"hms": [{"attr": 0x05000500, "code": 0x00010007}, {"attr": 0x03000100,
                                                                                 "code": 0x00030007}],
                           "print_error": 0x0300400C}})
    f = b.fehler()
    assert [x["code"] for x in f] == ["0500-0500-0001-0007", "0300-0100-0003-0007", "0300-400C"]
    assert f[0]["schwere"] == "fehler" and "quittieren" in f[0]["text"]
    assert f[1]["schwere"] == "warnung" and f[2]["art"] == "print_error"
    assert b.signatur_abgelehnt


def test_befehle_art():
    assert befehle.art(befehle.pushall()) == befehle.LESEN
    assert befehle.art(befehle.get_version()) == befehle.LESEN
    for b in (befehle.pause(), befehle.fortsetzen(), befehle.abbrechen(),
              befehle.project_file("x.gcode.3mf", 1, "abc", "x"), {"system": {"command": "ledctrl"}},
              {"pushing": {"command": "start"}}, {"pushing": {"command": "pushall"}, "print": {}}, {}, "x"):
        assert befehle.art(b) == befehle.STEUERN, b
    p = befehle.project_file("kevcad-j-1.gcode.3mf", 2, "ABC", "Halter", zeitraffer=True)["print"]
    assert p["param"] == "Metadata/plate_2.gcode" and p["url"] == "file:///sdcard/cache/kevcad-j-1.gcode.3mf"
    assert p["use_ams"] is False and p["ams_mapping"] == [0] and p["bed_leveling"] is True and p["timelapse"] is True


def test_sperre_alle_bedingungen():
    gut = sperre.Lage(weg="b", verbunden=True, entwicklermodus=True, ssdp_verbindung="lan", signatur_abgelehnt=False)
    assert sperre.pruefe_steuern(gut) is None
    assert "Bestätigung" in sperre.pruefe_steuern(gut, start=True, bestaetigt=False)
    assert sperre.pruefe_steuern(gut, start=True, bestaetigt=True) is None
    from dataclasses import replace

    assert "Weg A" in sperre.pruefe_steuern(replace(gut, weg="a"))
    assert "Cloud" in sperre.pruefe_steuern(replace(gut, ssdp_verbindung="cloud"))
    assert "Verbindung" in sperre.pruefe_steuern(replace(gut, verbunden=False))
    assert "nicht nachgewiesen" in sperre.pruefe_steuern(replace(gut, entwicklermodus=None))
    assert "aus" in sperre.pruefe_steuern(replace(gut, entwicklermodus=False))
    assert "0500-0500-0001-0007" in sperre.pruefe_steuern(replace(gut, signatur_abgelehnt=True))
    assert sperre.pruefe_steuern(replace(gut, ssdp_verbindung=None)) is None  # SSDP nicht gehört: kein Hindernis
    assert sperre.pushall_frei(None, 0) and not sperre.pushall_frei(100.0, 399.0) and sperre.pushall_frei(100, 400)


# =====================================================================================================================
# SSDP und Schlüsselbund


NOTIFY = (b"NOTIFY * HTTP/1.1\r\nHost: 239.255.255.250:1990\r\nServer: UPnP/1.0\r\nLocation: 192.168.178.40\r\n"
          b"NT: urn:bambulab-com:device:3dprinter:1\r\nNTS: ssdp:alive\r\nUSN: " + TEST_SERIENNUMMER.encode() +
          b"\r\nCache-Control: max-age=1800\r\nDevModel.bambu.com: C11\r\nDevName.bambu.com: P1P Werkstatt\r\n"
          b"DevSignal.bambu.com: -52\r\nDevConnect.bambu.com: cloud\r\nDevBind.bambu.com: occupied\r\n\r\n")


def test_ssdp_lesen_ohne_seriennummer():
    f = ssdp.lies_notify(NOTIFY, "192.168.178.40")
    assert f is not None and f.modell == "P1P" and f.name == "P1P Werkstatt" and f.ip == "192.168.178.40"
    assert f.verbindung == "cloud" and f.kennung == ssdp.kennung(TEST_SERIENNUMMER) and len(f.kennung) == 12
    assert TEST_SERIENNUMMER not in json.dumps(f.als_dict())
    assert ssdp.lies_notify(b"M-SEARCH * HTTP/1.1\r\n\r\n") is None
    assert ssdp.lies_notify(b"NOTIFY * HTTP/1.1\r\nNT: upnp:rootdevice\r\nUSN: x\r\n\r\n") is None


def test_ssdp_lauscher_hoert_broadcast():
    import socket

    from mcp_testutil import free_port

    port = free_port()
    gemeldet = threading.Event()
    l = ssdp.Lauscher(gemeldet.set, port=port)
    l.starten()
    try:
        assert l.fehler is None
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(NOTIFY, ("127.0.0.1", port))
        assert gemeldet.wait(5)
        assert [f.modell for f in l.funde()] == ["P1P"]
        assert l.funde(jetzt=time.time() + ssdp.VERFALL_S + 1) == []
    finally:
        l.stoppen()


class _Lauf:
    def __init__(self, rc: int, out: str = "", err: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_schluesselbund_fester_dienst_und_keine_ausgabe():
    aufrufe = []

    def ausfuehren(cmd, **kw):
        aufrufe.append(cmd)
        return _Lauf(0, json.dumps({"seriennummer": "SN-TEST", "zugangscode": "CODE-TEST"}) + "\n")

    z = schluesselbund.lesen("p1p", ausfuehren=ausfuehren)
    assert z.seriennummer == "SN-TEST" and z.zugangscode == "CODE-TEST"
    assert aufrufe == [["/usr/bin/security", "find-generic-password", "-s", "de.upvis.kevcad.drucker", "-a", "p1p",
                        "-w"]]
    assert "SN-TEST" not in repr(z) and "CODE-TEST" not in str(z) and "CODE-TEST" not in f"{z!r}"
    with pytest.raises(schluesselbund.SchluesselbundFehler) as e:
        schluesselbund.lesen("p1p", ausfuehren=lambda cmd, **kw: _Lauf(44, "", "geheimer Fehlertext CODE-TEST"))
    assert "CODE-TEST" not in str(e.value) and "geheimer" not in str(e.value)
    with pytest.raises(schluesselbund.SchluesselbundFehler):
        schluesselbund.lesen("p1p", ausfuehren=lambda cmd, **kw: _Lauf(0, "kein json CODE-TEST"))
    for falsch in ("P1P", "p1p; rm", "-s", "a" * 33, ""):
        with pytest.raises(schluesselbund.SchluesselbundFehler):
            schluesselbund.lesen(falsch, ausfuehren=ausfuehren)
    assert len(aufrufe) == 1  # ungültige IDs erreichen security nie


# =====================================================================================================================
# Profile und Slicen


def test_profile_vererbung_und_auswahl(tmp_path):
    app = bambu_attrappe(tmp_path)
    p = Profile(app, benutzer_wurzel=benutzer_profile(tmp_path / "user"))
    m = p.laden("Bambu Lab P1P 0.4 nozzle")
    assert m["printable_height"] == "250" and "inherits" not in m
    f = p.laden("Kevins PLA")
    assert f["filament_density"] == ["1.24"] and f["nozzle_temperature"] == ["205"] and f["from"] == "User"
    assert p.prozess_fuer(0.2) == "0.20mm Standard @BBL P1P"
    assert p.prozess_fuer(0.15) == "0.16mm Optimal @BBL P1P"
    assert p.prozess_fuer(None) == "0.20mm Standard @BBL P1P"
    assert p.filament_fuer("pla", "Kevins PLA") == "Kevins PLA"
    assert p.filament_fuer("petg", "Gibt es nicht") == "Generic PETG @BBL P1P"
    assert p.filament_fuer("PETG-HF") == "Generic PETG @BBL P1P"
    einst, fil = p.schreiben(tmp_path / "flach", "0.20mm Standard @BBL P1P", ["Kevins PLA"])
    assert json.loads(fil[0].read_text())["filament_density"] == ["1.24"]
    assert json.loads(einst[1].read_text())["wall_loops"] == "2"


def test_slicen_attrappe_zwischenspeicher_und_modell_id(tmp_path, monkeypatch):
    app = bambu_attrappe(tmp_path)
    stl = wuerfel_stl(tmp_path / "w.stl")
    cache = tmp_path / "cache"
    p = Profile(app, benutzer_wurzel=None)
    einst, fil = p.schreiben(tmp_path / "prof", p.prozess_fuer(0.2), [p.filament_fuer("petg")])
    monkeypatch.setenv("FAKE_BAMBU_PLATTEN", "2")
    e = slicen([stl], "Test-platten", einstellungen=einst, filamente=fil, anordnen=True, ausrichten=True, app=app,
               cache=cache)
    assert not e.aus_zwischenspeicher and e.version == "02.07.01.62"
    assert [(x.nr, x.zeit_s, x.material) for x in e.platten] == [(1, 1049, "PETG"), (2, 2049, "PETG")]
    assert e.platten[1].g == pytest.approx(14.8) and e.platten[0].md5
    with zipfile.ZipFile(e.datei) as z:
        assert 'printer_model_id" value="C11"' in z.read("Metadata/slice_info.config").decode()
        assert not any(n.startswith("3D/Objects") for n in z.namelist())  # --min-save
    aufruf = json.loads(next(cache.rglob("aufruf.json")).read_text()) if list(cache.rglob("aufruf.json")) else None
    assert aufruf is None  # Arbeitsordner wird aufgeräumt
    e2 = slicen([stl], "Test-platten", einstellungen=einst, filamente=fil, anordnen=True, ausrichten=True, app=app,
                cache=cache)
    assert e2.aus_zwischenspeicher and e2.datei == e.datei
    assert platten_lesen(e2.datei)[0].zeit_s == 1049


def test_slicen_aufruf_und_home(tmp_path, monkeypatch):
    app = bambu_attrappe(tmp_path)
    stl = wuerfel_stl(tmp_path / "w.stl")
    # Aufruf mitschneiden: Attrappe schreibt aufruf.json in den Arbeitsordner, den slicen danach löscht → umleiten
    import kevcad_kernel.drucker.slicen as sl

    gesehen = {}
    echt = sl.subprocess.Popen

    def popen(cmd, **kw):
        gesehen["cmd"], gesehen["env"] = cmd, kw.get("env")
        return echt(cmd, **kw)

    monkeypatch.setattr(sl.subprocess, "Popen", popen)
    slicen([stl], "A", app=app, cache=tmp_path / "c")
    cmd = gesehen["cmd"]
    assert cmd[0].endswith("Contents/MacOS/BambuStudio") and "--min-save" in cmd and cmd[cmd.index("--slice") + 1] == "0"
    assert "--arrange" not in cmd and "--load-settings" not in cmd and cmd[-1] == str(stl)
    assert gesehen["env"]["HOME"] == str(tmp_path / "c" / "home")


def test_slicen_fehler_zeitlimit_abbruch(tmp_path, monkeypatch):
    app = bambu_attrappe(tmp_path)
    stl = wuerfel_stl(tmp_path / "w.stl")
    monkeypatch.setenv("FAKE_BAMBU_FEHLER", "Objekt ragt über die Platte")
    with pytest.raises(SlicenFehler, match="ragt über die Platte"):
        slicen([stl], "A", app=app, cache=tmp_path / "c1")
    monkeypatch.delenv("FAKE_BAMBU_FEHLER")
    monkeypatch.setenv("FAKE_BAMBU_SCHLAF", "5")
    t0 = time.monotonic()
    with pytest.raises(SlicenFehler, match="länger als"):
        slicen([stl], "A", app=app, cache=tmp_path / "c2", zeitlimit_s=0.6)
    abbruch = threading.Event()
    threading.Timer(0.4, abbruch.set).start()
    with pytest.raises(Abgebrochen):
        slicen([stl], "A", app=app, cache=tmp_path / "c3", abbruch=abbruch)
    assert time.monotonic() - t0 < 4.5
    with pytest.raises(SlicenFehler, match="Bambu Studio fehlt"):
        slicen([stl], "A", app=tmp_path / "Fehlt.app", cache=tmp_path / "c4")


@pytest.mark.skipif(not ECHTES_BAMBU.exists(), reason="Bambu Studio fehlt (Mac mini)")
def test_slicen_echt_mit_bambu_studio(tmp_path):
    """Echte CLI mit aufgelösten Systemprofilen; Kevins Benutzerordner wird nur gelesen."""
    p = Profile()
    stl = wuerfel_stl(tmp_path / "wuerfel.stl")
    einst, fil = p.schreiben(tmp_path / "prof", p.prozess_fuer(0.2), [p.filament_fuer("pla")])
    e = slicen([stl], "Wuerfel", einstellungen=einst, filamente=fil, anordnen=True, cache=tmp_path / "c")
    assert len(e.platten) == 1 and e.platten[0].zeit_s > 300 and 2 < e.platten[0].g < 8  # 20-mm-Würfel ≈ 3,7 g
    with zipfile.ZipFile(e.datei) as z:
        namen = z.namelist()
        assert "Metadata/plate_1.gcode" in namen and not any(n.startswith("3D/Objects") for n in namen)
        assert 'printer_model_id" value="C11"' in z.read("Metadata/slice_info.config").decode()
        assert "Bambu Lab P1P" in json.loads(z.read("Metadata/project_settings.config"))["printer_model"]


# =====================================================================================================================
# MQTT und FTPS gegen die Attrappe


class _Lage:
    def __init__(self, weg: str = "a", ssdp_modus: str | None = None) -> None:
        self.weg, self.ssdp = weg, ssdp_modus

    def __call__(self):
        return self.weg, self.ssdp


def _verbindung(a: Attrappe, lage: _Lage, code: str = TEST_ZUGANGSCODE, sn: str = TEST_SERIENNUMMER,
                zeitlimit: float = 10.0) -> MqttVerbindung:
    v = MqttVerbindung("127.0.0.1", schluesselbund.aus_werten(sn, code), bei_aenderung=lambda: None, lage=lage,
                       port=a.mqtt.port, ca_datei=a.ca, zeitlimit_s=zeitlimit)
    v.starten()
    return v


def test_mqtt_weg_a_liest_und_sendet_nie_steuerbefehle(tmp_path):
    with Attrappe(tmp_path / "a", modus="cloud") as a:
        v = _verbindung(a, _Lage("a", "cloud"))
        try:
            warte(lambda: v.verbindung == "verbunden")
            warte(lambda: v.bericht.firmware == "01.10.00.00" and v.bericht.fun_gesehen)
            assert v.bericht.entwicklermodus is False
            a.mqtt.druckt()
            warte(lambda: (v.bericht.druck_status() or {}).get("zustand") == "druckt")
            assert v.bericht.druck_status()["schicht"] == 41
            for b in (befehle.pause(), befehle.fortsetzen(), befehle.abbrechen(),
                      befehle.project_file("x.gcode.3mf", 1, "m", "x")):
                assert "Weg A" in v.steuern(b, start=True, bestaetigt=True)
            assert "5 min" in v.lesen_anfordern()  # pushall erst nach 5 min wieder
            time.sleep(0.3)
            namen = [next(iter(x.values()))["command"] for x in a.mqtt.empfangen]
            assert sorted(set(namen)) == ["get_version", "pushall"] and namen.count("pushall") == 1
            assert a.mqtt.hms == []  # kein abgelehnter Befehl
        finally:
            v.stoppen()
        assert v._zugang is None  # Zugangscode nach dem Trennen verworfen


def test_mqtt_weg_b_mit_entwicklermodus(tmp_path):
    with Attrappe(tmp_path / "a", modus="lan", entwickler=True) as a:
        v = _verbindung(a, _Lage("b", "lan"))
        try:
            warte(lambda: v.bericht.entwicklermodus is True)
            assert v.steuern(befehle.project_file("x.gcode.3mf", 1, "m", "x"), start=True, bestaetigt=False)
            assert v.steuern(befehle.project_file("x.gcode.3mf", 1, "m", "x"), start=True, bestaetigt=True) is None
            warte(lambda: (v.bericht.druck_status() or {}).get("zustand") == "druckt")
            assert v.steuern(befehle.pause()) is None
            warte(lambda: v.bericht.druck_status()["zustand"] == "pausiert")
            assert v.steuern(befehle.fortsetzen()) is None
            warte(lambda: v.bericht.druck_status()["zustand"] == "druckt")
            assert v.steuern(befehle.abbrechen()) is None
            warte(lambda: v.bericht.druck_status()["zustand"] == "fehlgeschlagen")
            assert v.steuern(befehle.pushall()) == "Kein Steuerbefehl."
        finally:
            v.stoppen()


def test_mqtt_cloud_trotz_weg_b_gesperrt_und_hms_sperrt_alles(tmp_path):
    with Attrappe(tmp_path / "a", modus="cloud") as a:
        v = _verbindung(a, _Lage("b", None))
        try:
            warte(lambda: v.bericht.entwicklermodus is False)
            assert "Developer Mode ist aus" in v.steuern(befehle.pause())
            assert all("print" not in x for x in a.mqtt.empfangen)
            # Falls doch ein abgelehnter Befehl gemeldet wird (z. B. aus Bambu Studio): danach geht nichts mehr hinaus
            a.mqtt.hms = [{"attr": 0x05000500, "code": 0x00010007}]
            a.mqtt.berichten({"hms": a.mqtt.hms})
            warte(lambda: v.bericht.signatur_abgelehnt)
            n = len(a.mqtt.empfangen)
            assert "0500-0500-0001-0007" in v.lesen_anfordern()
            time.sleep(0.2)
            assert len(a.mqtt.empfangen) == n
        finally:
            v.stoppen()


def test_mqtt_falscher_code_falsche_seriennummer_zeitlimit(tmp_path):
    with Attrappe(tmp_path / "a") as a:
        v = _verbindung(a, _Lage(), code="falsch")
        try:
            warte(lambda: v.verbindung == "fehler")
            assert "Zugangscode" in v.meldung and "falsch" not in v.meldung
            time.sleep(2.5)
            assert a.mqtt.anmeldungen == [False]  # kein erneuter Versuch mit denselben Daten
        finally:
            v.stoppen()
        v = _verbindung(a, _Lage(), sn="01P00AANDERS001")
        try:
            warte(lambda: v.verbindung == "fehler")
            assert "Seriennummer" in v.meldung and "01P00A" not in v.meldung
        finally:
            v.stoppen()
    with Attrappe(tmp_path / "b", antworten=False) as stumm:
        v = _verbindung(stumm, _Lage(), zeitlimit=0.8)
        try:
            warte(lambda: v.verbindung == "fehler", 5)
            assert "Zeitüberschreitung" in v.meldung
        finally:
            v.stoppen()


def test_mqtt_trennung_und_wiederverbinden(tmp_path):
    with Attrappe(tmp_path / "a", modus="lan", entwickler=True) as a:
        v = _verbindung(a, _Lage("b", "lan"))
        try:
            warte(lambda: v.bericht.entwicklermodus is True)
            a.mqtt.trennen()
            warte(lambda: v.verbindung in ("getrennt", "verbindet"), 5)
            assert v.bericht.entwicklermodus is None  # nach Trennung erst wieder nachweisen
            assert v.steuern(befehle.pause())  # gesperrt, solange nicht wieder verbunden
            warte(lambda: v.verbindung == "verbunden", 10)
        finally:
            v.stoppen()


def test_ftps_hochladen(tmp_path):
    from kevcad_kernel.drucker import ftps

    datei = tmp_path / "x.gcode.3mf"
    datei.write_bytes(b"PK" + bytes(range(256)) * 400)
    with Attrappe(tmp_path / "a") as a:
        stand = []
        pfad = ftps.hochladen("127.0.0.1", schluesselbund.aus_werten(TEST_SERIENNUMMER, TEST_ZUGANGSCODE), datei,
                              "kevcad-j-1.gcode.3mf", port=a.ftps.port, ca_datei=a.ca, fortschritt=stand.append)
        assert pfad == "cache/kevcad-j-1.gcode.3mf" and a.ftps.dateien[pfad] == datei.read_bytes()
        assert stand[-1] == 1.0
        with pytest.raises(ftps.UploadFehler, match="Zugangscode") as e:
            ftps.hochladen("127.0.0.1", schluesselbund.aus_werten(TEST_SERIENNUMMER, "falsch"), datei, "y",
                           port=a.ftps.port, ca_datei=a.ca)
        assert "falsch" not in str(e.value)
        with pytest.raises(ftps.UploadFehler, match="Seriennummer"):
            ftps.hochladen("127.0.0.1", schluesselbund.aus_werten("ANDERE", TEST_ZUGANGSCODE), datei, "y",
                           port=a.ftps.port, ca_datei=a.ca)


# =====================================================================================================================
# Dienst


class _App:
    def __init__(self) -> None:
        self.nachrichten: list[dict] = []
        self.lock = threading.Lock()

    def __call__(self, h: dict) -> bool:
        with self.lock:
            self.nachrichten.append(json.loads(json.dumps(h)))
        return True

    def von(self, typ: str) -> list[dict]:
        with self.lock:
            return [h for h in self.nachrichten if h["type"] == typ]


def _dienst(tmp_path, app_cb, *, attrappe: Attrappe | None = None, oeffnen=None, quelle=None):
    app = bambu_attrappe(tmp_path / "bambu")
    stl = wuerfel_stl(tmp_path / "w.stl")
    ausgabe = tmp_path / "Projekt" / "output"

    def q(platten, ordner):
        return Quelle(name="Projekt-platten", eingaben=[stl], ausgabe=ausgabe, anordnen=True, platten=platten,
                      filamente=["Generic PETG @BBL P1P"], prozess="0.20mm Standard @BBL P1P")

    def zugang(did):
        assert did == "p1p"
        return schluesselbund.aus_werten(attrappe.seriennummer if attrappe else TEST_SERIENNUMMER, TEST_ZUGANGSCODE)

    d = DruckerDienst(senden=app_cb, quelle=quelle or q, app=app, cache=tmp_path / "cache", zugang_lesen=zugang,
                      oeffnen=oeffnen or (lambda p: None), ssdp_an=False, ca_datei=attrappe.ca if attrappe else None,
                      profile=lambda: Profile(app, benutzer_wurzel=None))
    return d, ausgabe


def _eintrag(a: Attrappe | None, weg: str = "a", lesen: bool = True) -> dict:
    e = {"id": "p1p", "name": "P1P", "modell": "C11", "ip": "127.0.0.1", "weg": weg, "status_lesen": lesen}
    if a is not None:
        e.update(port_mqtt=a.mqtt.port, port_ftps=a.ftps.port)
    return e


def test_dienst_ohne_drucker_und_status_aus(tmp_path):
    app = _App()
    d, _ = _dienst(tmp_path, app)
    try:
        st = d.status()
        assert st["konfiguriert"] is False and st["verbindung"] == "aus" and st["drucker"] is None
        assert st["wege"]["a"]["moeglich"] is True and st["wege"]["b"]["moeglich"] is False
        assert st["kamera"] is False and st["steuern"] is False
        assert check_drucker_message(printer_status(st)) == []
        ok, _ = d.konfigurieren(_eintrag(None, lesen=False))
        assert ok
        st = warte(lambda: app.von("PRINTER_STATUS") and app.von("PRINTER_STATUS")[-1])
        assert st["verbindung"] == "aus" and "Status lesen" in st["meldung"] and st["drucker"]["modell"] == "P1P"
        assert not d.konfigurieren({"id": "Böse ID"})[0]
    finally:
        d.stoppen()


def test_dienst_weg_a_vorbereiten_bestaetigen_oeffnen(tmp_path):
    app = _App()
    geoeffnet = []
    d, ausgabe = _dienst(tmp_path, app, oeffnen=geoeffnet.append)
    try:
        antworten = []
        ok, text = d.auftrag_anfordern({"id": "a-1", "platten": [], "weg": "a", "bestaetigt": False},
                                       antworten.append)
        assert ok and "vorbereitet" in text.lower()
        warte(lambda: antworten)
        r = antworten[0]
        assert r["ok"] and r["schritt"] == "vorbereitet" and r["reply_to"] == "a-1" and not geoeffnet
        assert check_drucker_message(r) == []
        aid = r["auftrag"]
        assert d.auftrag().zustand == "bereit"
        ok, _ = d.auftrag_anfordern({"id": "a-2", "platten": [], "weg": "a", "bestaetigt": True, "auftrag": aid},
                                    antworten.append)
        warte(lambda: len(antworten) == 2)
        r = antworten[1]
        assert r["ok"] and r["schritt"] == "geoeffnet" and r["datei"] == str(ausgabe / "Projekt-platten.gcode.3mf")
        assert geoeffnet == [ausgabe / "Projekt-platten.gcode.3mf"] and geoeffnet[0].exists()
        assert r["ergebnis"]["platten"][0]["material"] == "PETG"
        assert d.auftrag().zustand == "geoeffnet" and "Senden" in d.auftrag().meldung
        st = d.status()
        assert st["auftrag"]["zustand"] == "geoeffnet" and check_drucker_message(printer_status(st)) == []
    finally:
        d.stoppen()


def test_dienst_agent_frage_und_verwerfen(tmp_path):
    app = _App()
    d, _ = _dienst(tmp_path, app)
    try:
        a = d.anfragen([1], "a", "Kevin will drucken")
        assert a.von == "agent" and a.zustand == "wartet"
        assert d.verwerfen(a.id)[0] and d.auftrag().zustand == "verworfen"
        ok, text = d.auftrag_anfordern({"id": "x", "platten": [1], "weg": "a", "bestaetigt": True,
                                        "auftrag": a.id}, lambda h: None)
        assert not ok and "verworfen" in text
        assert not d.auftrag_anfordern({"id": "x", "platten": [], "weg": "a", "bestaetigt": True, "auftrag": "j-99"},
                                       lambda h: None)[0]
    finally:
        d.stoppen()


def test_dienst_fehler_beim_slicen(tmp_path, monkeypatch):
    app = _App()
    d, _ = _dienst(tmp_path, app)
    monkeypatch.setenv("FAKE_BAMBU_FEHLER", "Kein Objekt auf der Platte")
    try:
        antworten = []
        d.auftrag_anfordern({"id": "a-1", "platten": [], "weg": "a", "bestaetigt": True}, antworten.append)
        warte(lambda: antworten)
        assert not antworten[0]["ok"] and "Kein Objekt" in antworten[0]["fehler"]
        assert d.auftrag().zustand == "fehler"
    finally:
        d.stoppen()


def test_dienst_weg_b_abgelehnt_ohne_einstellung_und_im_cloud_modus(tmp_path):
    app = _App()
    with Attrappe(tmp_path / "a", modus="cloud") as a:
        d, _ = _dienst(tmp_path, app, attrappe=a)
        try:
            d.konfigurieren(_eintrag(a, weg="a"))
            ok, text = d.auftrag_anfordern({"id": "1", "platten": [1], "weg": "b", "bestaetigt": True},
                                           lambda h: None)
            assert not ok and "Weg B ist nicht eingestellt" in text
            d.konfigurieren(_eintrag(a, weg="b"))
            warte(lambda: d.status()["verbindung"] == "verbunden")
            warte(lambda: d.status()["drucker"]["entwicklermodus"] is False)
            antworten = []
            ok, _ = d.auftrag_anfordern({"id": "2", "platten": [1], "weg": "b", "bestaetigt": True},
                                        antworten.append)
            assert ok
            warte(lambda: antworten)
            assert not antworten[0]["ok"] and "Developer Mode ist aus" in antworten[0]["fehler"]
            assert a.ftps.dateien == {} and a.ftps.anmeldungen == []  # nichts hochgeladen
            assert all("print" not in x for x in a.mqtt.empfangen)
            assert not d.steuern("pause")[0]
            st = d.status()
            assert st["steuern"] is False and st["wege"]["b"]["moeglich"] is False
            assert "Developer Mode" in st["wege"]["b"]["grund"] and len(st["wege"]["b"]["anleitung"]) >= 4
            assert TEST_SERIENNUMMER not in json.dumps(st) and TEST_ZUGANGSCODE not in json.dumps(st)
        finally:
            d.stoppen()


def test_dienst_weg_b_mit_entwicklermodus_gegen_attrappe(tmp_path):
    app = _App()
    with Attrappe(tmp_path / "a", modus="lan", entwickler=True) as a:
        d, _ = _dienst(tmp_path, app, attrappe=a)
        try:
            d.konfigurieren(_eintrag(a, weg="b"))
            warte(lambda: d.status()["steuern"] is True)
            antworten = []
            d.auftrag_anfordern({"id": "3", "platten": [1], "weg": "b", "bestaetigt": True,
                                 "optionen": {"bett_nivellieren": False, "flussrate": True, "zeitraffer": True}},
                                antworten.append)
            warte(lambda: antworten, 20)
            r = antworten[0]
            assert r["ok"] and r["schritt"] == "gestartet", r
            name = f"cache/kevcad-{r['auftrag']}.gcode.3mf"
            assert name in a.ftps.dateien
            start = [x["print"] for x in a.mqtt.empfangen if x.get("print", {}).get("command") == "project_file"][0]
            assert start["param"] == "Metadata/plate_1.gcode" and start["bed_leveling"] is False
            assert start["timelapse"] is True and start["url"] == f"file:///sdcard/{name}" and len(start["md5"]) == 32
            warte(lambda: (d.status()["druck"] or {}).get("zustand") == "druckt")
            assert d.steuern("pause") == (True, "Pause gesendet")
            warte(lambda: d.status()["druck"]["zustand"] == "pausiert")
            assert d.steuern("abbrechen")[0]
            assert d.steuern("aktualisieren")[0] is False  # pushall erst nach 5 min wieder
            assert not d.steuern("tanzen")[0]
        finally:
            d.stoppen()


def test_dienst_status_lesend_weg_a_gegen_attrappe(tmp_path):
    app = _App()
    with Attrappe(tmp_path / "a", modus="cloud") as a:
        d, _ = _dienst(tmp_path, app, attrappe=a)
        try:
            d.konfigurieren(_eintrag(a, weg="a"))
            warte(lambda: d.status()["verbindung"] == "verbunden")
            a.mqtt.druckt()
            st = warte(lambda: (lambda s: s if (s["druck"] or {}).get("zustand") == "druckt" else None)(d.status()))
            assert st["druck"]["fortschritt"] == pytest.approx(0.42) and st["temperaturen"]["duese_ziel"] == 220.0
            assert st["drucker"]["firmware"] == "01.10.00.00" and st["steuern"] is False
            assert check_drucker_message(printer_status(st)) == []
            letzte = warte(lambda: [h for h in app.von("PRINTER_STATUS") if (h["druck"] or {}).get("zustand")
                                    == "druckt"])
            assert letzte and TEST_ZUGANGSCODE not in json.dumps(app.nachrichten)
            assert TEST_SERIENNUMMER not in json.dumps(app.nachrichten)
            # gedrosselt: höchstens 2 Meldungen je Sekunde
            zeiten = len(app.von("PRINTER_STATUS"))
            for i in range(20):
                a.mqtt.berichten({"mc_percent": 43 + i})
            time.sleep(1.2)
            assert len(app.von("PRINTER_STATUS")) - zeiten <= 4
            assert app.von("PRINTER_STATUS")[-1]["druck"]["fortschritt"] == pytest.approx(0.62)
            # Einstellung aus → Verbindung weg, Code verworfen
            d.konfigurieren(_eintrag(a, weg="a", lesen=False))
            warte(lambda: d.status()["verbindung"] == "aus")
        finally:
            d.stoppen()


# =====================================================================================================================
# Protokoll und Testdateien


def test_protokoll_beispiel_und_geheimnisse():
    st = drucker_status_beispiel()
    assert check_drucker_message(printer_status(st)) == []
    schlecht = printer_status({**st, "drucker": {**st["drucker"], "seriennummer": "X"}})
    assert any("seriennummer" in f for f in check_drucker_message(schlecht))
    assert any("kamera" in f for f in check_drucker_message(printer_status({**st, "kamera": True})))
    assert check_drucker_message({"type": "PRINT_CONTROL", "id": "1", "aktion": "tanzen"}) == [
        "aktion 'tanzen' unbekannt"]
    assert check_drucker_message({"type": "PRINTER_CONFIG", "id": "1", "drucker": {"id": "p1p", "name": "x",
                                                                                     "modell": "C11", "ip": "",
                                                                                     "weg": "a", "status_lesen": True,
                                                                                     "zugangscode": "1"}})


@pytest.mark.skipif(not (FIX / "printer_status.frame").exists(), reason="Testdateien fehlen")
def test_testdateien_lesen_und_pruefen():
    data = json.loads((FIX / "fixtures.json").read_text())["drucker"]
    for f in data["frames"]:
        (header, payload), = FrameReader().feed((FIX / f["file"]).read_bytes())
        assert header["type"] == f["type"] and payload == b""
        if header["type"] != "ACK":
            assert check_drucker_message(header) == [], f["file"]
        roh = (FIX / f["file"]).read_bytes()
        assert TEST_ZUGANGSCODE.encode() not in roh
    (st, _), = FrameReader().feed((FIX / "printer_status.frame").read_bytes())
    assert st["druck"] == data["druck"] and st["drucker"] == data["drucker"]

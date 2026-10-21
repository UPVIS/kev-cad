"""CAD-Quellen der Zukaufteile ohne Netz: TraceParts-Client mit Attrappe (Ablauf, Fehler, Schlüssel nie im Text),
Deep-Links, Downloads-Ordner und ZIP (Temp-Ordner statt ~/Downloads)."""

import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from kevcad_kernel.zukauf import downloads as dl
from kevcad_kernel.zukauf import traceparts as tp

SCHLUESSEL = "geheim-1234567890"
STEP_KOPF = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


class Attrappe:
    """Nachgebaute TraceParts-API: zeichnet Aufrufe auf, antwortet wie in der Doku."""

    def __init__(self, *, gefunden=True, formate=None, warten=1, datei=b"PK\x03\x04zip"):
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.gefunden = gefunden
        self.formate = formate if formate is not None else [
            {"cadFormatId": 9, "cadFormatName": "IGES", "deliveryMethod": 1},
            {"cadFormatId": 22, "cadFormatName": "STEP AP214", "deliveryMethod": 1},
            {"cadFormatId": 23, "cadFormatName": "STEP AP242", "deliveryMethod": 2}]
        self.warten = warten
        self.datei = datei

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        if url.endswith("/v2/RequestToken"):
            data = json.loads(body)
            if data["apiKey"] != SCHLUESSEL:
                return 401, "Unauthorized", b"Unauthorized"
            return 200, {"token": "jwt-abc", "expiryDate": "2099-01-01T00:00:00Z"}, b""
        if headers.get("Authorization") not in (None, "Bearer jwt-abc") and "files.example" not in url:
            return 401, None, b""
        if "/v2/Search/PartNumber/Availability" in url:
            if not self.gefunden:
                return 404, None, b""
            return 200, {"partFamilyCode": "FAM-1", "classificationCode": "ALUTEC", "partNumber": "05200",
                         "selectionPath": "SP-1", "version": "3"}, b""
        if "/v3/Product/CadDataAvailability" in url:
            return 200, {"partNumberAvailability": {"partNumber": "05200", "availability": True},
                         "viewerAvailability": True, "cadFormatList": self.formate}, b""
        if url.endswith("/v3/Product/cadRequest"):
            return 200, 4711, b"4711"
        if "/v2/Product/cadFileUrl" in url:
            if self.warten > 0:
                self.warten -= 1
                return 204, None, b""
            return 200, "https://files.example/4711.zip", b'"https://files.example/4711.zip"'
        if url == "https://files.example/4711.zip":
            return 200, None, self.datei
        return 404, None, b""


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    path = tmp_path / "secrets.env"
    path.write_text(f"# Kevins Zugang\nTRACEPARTS_API_KEY={SCHLUESSEL}\nTRACEPARTS_TENANT_UID="
                    "11111111-2222-3333-4444-555555555555\nexport TRACEPARTS_USER_EMAIL=\"kevin@example.com\"\n",
                    encoding="utf-8")
    monkeypatch.setenv("KEVCAD_SECRETS_FILE", str(path))
    return path


def test_zugang_aus_secrets(secrets, tmp_path, monkeypatch):
    z, grund = tp.zugang()
    assert grund is None and z.user_email == "kevin@example.com" and SCHLUESSEL not in repr(z)
    monkeypatch.setenv("KEVCAD_SECRETS_FILE", str(tmp_path / "fehlt.env"))
    z, grund = tp.zugang()
    assert z is None and "TRACEPARTS_API_KEY" in grund and "Links" in grund


def test_traceparts_ablauf(secrets, tmp_path):
    fake = Attrappe(warten=2)
    z, _ = tp.zugang()
    client = tp.TraceParts(z, fake, sleep=lambda s: None)
    res = client.holen("05200", "ALUTEC", tmp_path / "tp", "alutec-05200")
    assert res["format"]["cadFormatName"] == "STEP AP214" and res["teil"]["partFamilyCode"] == "FAM-1"
    assert Path(res["datei"]).name == "alutec-05200.zip" and Path(res["datei"]).read_bytes().startswith(b"PK")
    urls = [c[1] for c in fake.calls]
    assert urls[0].endswith("/v2/RequestToken") and "partNumber=05200" in urls[1] and "catalog=ALUTEC" in urls[1]
    assert "removeChar=true" in urls[1] and "cultureInfo=de" in urls[2] and "partFamilyCode=FAM-1" in urls[2]
    body = json.loads(fake.calls[3][3])
    assert body == {"userEmail": "kevin@example.com", "cultureInfo": "de", "cadFormatId": 22,
                    "partFamilyCode": "FAM-1", "selectionPath": "SP-1"}
    assert sum("cadFileUrl" in u for u in urls) == 3  # zweimal 204, dann die URL
    assert all(c[2].get("Authorization") == "Bearer jwt-abc" for c in fake.calls[1:-1])
    assert "Authorization" not in fake.calls[-1][2]  # signierte Datei-URL ohne Token
    assert client.aufrufe == len(fake.calls)


def test_traceparts_nicht_gefunden_und_fehler(secrets, tmp_path):
    z, _ = tp.zugang()
    assert tp.TraceParts(z, Attrappe(gefunden=False)).holen("x", "Y", tmp_path, "x") == {"gefunden": False}
    res = tp.TraceParts(z, Attrappe(formate=[{"cadFormatId": 1, "cadFormatName": "IGES", "deliveryMethod": 1}])).holen(
        "05200", "ALUTEC", tmp_path, "x")
    assert res == {"gefunden": True, "teil": res["teil"], "format": None}
    falsch = tp.Zugang("falsch", "11111111-2222-3333-4444-555555555555", "k@example.com")
    with pytest.raises(tp.TracePartsFehler) as exc:
        tp.TraceParts(falsch, Attrappe()).holen("05200", "ALUTEC", tmp_path, "x")
    assert "Anmeldung fehlgeschlagen" in str(exc.value) and "falsch" not in str(exc.value)
    with pytest.raises(tp.TracePartsFehler, match="noch"):
        tp.TraceParts(z, Attrappe(warten=99), sleep=lambda s: None).holen("05200", "ALUTEC", tmp_path, "x")


def test_cad_links():
    links = tp.cad_links({"hersteller": "igus", "mpn": "GFM-1012-10", "url": "https://www.igus.example/p/gfm"})
    titles = [link["titel"] for link in links]
    assert titles[0] == "Produktseite (CAD-Download oft dort)" and titles[1].startswith("igus: CAD zu GFM-1012-10")
    assert any(t.startswith("TraceParts") for t in titles) and any(t.startswith("3Dfindit") for t in titles)
    assert links[-1]["url"].startswith("https://duckduckgo.com/?q=igus+GFM-1012-10+STEP")
    mc = tp.cad_links({"hersteller": "McMaster-Carr", "mpn": "91251A540"})
    assert mc[0]["url"] == "https://www.mcmaster.com/91251A540/"


# ------------------------------------------------------------------------------------------------------ Downloads


def _datei(path: Path, inhalt: bytes, alter_s: float = 0) -> Path:
    path.write_bytes(inhalt)
    t = time.time() - alter_s
    os.utime(path, (t, t))
    return path


def test_downloads_kandidaten_und_wahl(tmp_path, monkeypatch):
    d = tmp_path / "Downloads"
    d.mkdir()
    monkeypatch.setenv("KEVCAD_DOWNLOADS_DIR", str(d))
    _datei(d / "alt.step", STEP_KOPF, alter_s=3600)
    _datei(d / "05200_rollwagen.STEP", STEP_KOPF, alter_s=60)
    _datei(d / "anderes.stp", STEP_KOPF, alter_s=10)
    _datei(d / "halb.step.crdownload", STEP_KOPF)
    _datei(d / "bild.png", b"png")
    files = dl.kandidaten(dl.downloads_dir(), 30)
    assert [p.name for p in files] == ["anderes.stp", "05200_rollwagen.STEP"]
    assert dl.waehlen(files, {"id": "alutec-05200", "mpn": "05200"}).name == "05200_rollwagen.STEP"
    assert dl.waehlen(files, {"id": "x", "mpn": "999"}).name == "anderes.stp"  # sonst die neueste
    out, _ = dl.uebernehmen(files[1], tmp_path / "ziel", {"mpn": "05200"})
    assert out.name == "05200_rollwagen.step" and out.read_bytes() == STEP_KOPF
    with pytest.raises(dl.DownloadFehler, match="keine STEP-Datei"):
        dl.uebernehmen(_datei(d / "falsch.step", b"kein step"), tmp_path / "ziel", {})


def test_zip_sicher_entpacken(tmp_path):
    z = tmp_path / "cad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "x")
        zf.writestr("models/klein.step", STEP_KOPF)
        zf.writestr("models/ALUTEC_05200.stp", STEP_KOPF + b"x" * 10)
        zf.writestr("../../boese.step", STEP_KOPF + b"y" * 100)
        zf.writestr("__MACOSX/models/._ALUTEC_05200.stp", b"mac")
    out, hinweise = dl.uebernehmen(z, tmp_path / "ziel", {"mpn": "05200"})
    assert out == tmp_path / "ziel" / "ALUTEC_05200.stp" and out.is_file()
    assert hinweise == ["cad.zip enthält 2 STEP-Dateien; übernommen: ALUTEC_05200.stp"]
    assert not (tmp_path / "boese.step").exists() and not list(tmp_path.glob("**/boese.step"))
    nur_iges = tmp_path / "iges.zip"
    with zipfile.ZipFile(nur_iges, "w") as zf:
        zf.writestr("teil.igs", "x")
    with pytest.raises(dl.DownloadFehler, match=r"keine STEP-Datei \(nur \.igs\): im Portal das Format STEP"):
        dl.uebernehmen(nur_iges, tmp_path / "ziel", {})

"""Attrappe eines Bambu Lab P1P für Tests (Phase 8): MQTT-Broker über TLS und FTPS-Server mit implizitem TLS, beide
auf 127.0.0.1, mit eigener Test-CA und einem Zertifikat auf die Test-Seriennummer. Nie gegen den echten Drucker.

Verhalten wie ein P1P mit Firmware ab 01.08.02.00:
- ``modus="cloud"`` (bzw. Developer Mode aus): Lesebefehle (``pushall``, ``get_version``) werden beantwortet; jeder
  Steuerbefehl wird abgelehnt und erzeugt HMS 0500-0500-0001-0007 im nächsten Bericht (wie die echte Firmware).
- ``modus="lan"`` mit ``entwickler=True``: ``print.fun`` ohne Signatur-Bit; ``project_file``, ``pause``, ``resume``,
  ``stop`` ändern ``gcode_state`` und werden gemeldet.
- Der Bericht schickt nach ``pushall`` alles, sonst nur Deltas.

Für pytest: ``Attrappe(...)`` als Kontextmanager. Für den Selbsttest der App als Prozess::

    kernel/.venv/bin/python kernel/tools/drucker_attrappe.py --ordner /tmp/kc-attrappe [--modus cloud|lan]
        [--entwickler] [--druckt]

schreibt ``attrappe.json`` (Ports, CA-Datei, Test-Seriennummer und Test-Zugangscode – reine Testwerte) in den Ordner und
läuft, bis er beendet wird.
"""

from __future__ import annotations

import argparse
import datetime
import json
import socket
import ssl
import struct
import threading
import time
from pathlib import Path
from typing import Any

TEST_SERIENNUMMER = "01P00ATESTSN001"
TEST_ZUGANGSCODE = "12345678"
FUN_SIGNATUR = 0x20000000


def zertifikate(ordner: Path, cn: str) -> dict[str, Path]:
    """Test-CA und Server-Zertifikat (CN = Seriennummer) mit ``cryptography`` erzeugen."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    ordner.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Kev CAD Attrappe CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(jetzt - datetime.timedelta(days=1))
          .not_valid_after(jetzt + datetime.timedelta(days=60))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    import ipaddress

    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(days=1)).not_valid_after(jetzt + datetime.timedelta(days=60))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pfade = {"ca": ordner / "ca.pem", "cert": ordner / "server.pem", "key": ordner / "server.key"}
    pfade["ca"].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    pfade["cert"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pfade["key"].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
    return pfade


def _server_kontext(pfade: dict[str, Path]) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(pfade["cert"]), str(pfade["key"]))
    return ctx


def _lies_genau(s: socket.socket, n: int) -> bytes:
    daten = b""
    while len(daten) < n:
        teil = s.recv(n - len(daten))
        if not teil:
            raise ConnectionError("geschlossen")
        daten += teil
    return daten


def _laenge(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _str(daten: bytes, pos: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("!H", daten, pos)
    return daten[pos + 2:pos + 2 + n].decode("utf-8", "replace"), pos + 2 + n


class MqttAttrappe:
    def __init__(self, pfade: dict[str, Path], seriennummer: str, zugangscode: str, *, modus: str = "cloud",
                 entwickler: bool = False, firmware: str = "01.10.00.00", antworten: bool = True) -> None:
        self.seriennummer = seriennummer
        self.zugangscode = zugangscode
        self.modus = modus
        self.entwickler = entwickler and modus == "lan"
        self.firmware = firmware
        self.antworten = antworten  # False: TLS ja, aber nie CONNACK (Zeitüberschreitung)
        self.ctx = _server_kontext(pfade)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.lock = threading.Lock()
        self.clients: list[ssl.SSLSocket] = []
        self.empfangen: list[dict[str, Any]] = []  # alles, was an request ging
        self.anmeldungen: list[bool] = []
        self.hms: list[dict[str, int]] = []
        self.zustand: dict[str, Any] = {
            "gcode_state": "IDLE", "mc_percent": 0, "mc_remaining_time": 0, "layer_num": 0, "total_layer_num": 0,
            "nozzle_temper": 24.0, "nozzle_target_temper": 0.0, "bed_temper": 23.5, "bed_target_temper": 0.0,
            "print_error": 0, "subtask_name": "", "gcode_file": "", "stg_cur": -1, "spd_lvl": 2,
            "wifi_signal": "-48dBm", "mc_print_stage": "1",
        }
        self._halt = threading.Event()
        threading.Thread(target=self._annehmen, daemon=True).start()

    @property
    def fun(self) -> str:
        wert = 0x3EC18FFF9CFF if self.entwickler else 0x3EC1AFFF9CFF  # Beispielwerte aus ha-bambulab
        assert bool(wert & FUN_SIGNATUR) != self.entwickler
        return f"{wert:X}"

    def _annehmen(self) -> None:
        self.sock.settimeout(0.5)
        while not self._halt.is_set():
            try:
                roh, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._client, args=(roh,), daemon=True).start()

    def _client(self, roh: socket.socket) -> None:
        try:
            s = self.ctx.wrap_socket(roh, server_side=True)
        except (ssl.SSLError, OSError):
            roh.close()
            return
        try:
            while not self._halt.is_set():
                kopf = _lies_genau(s, 1)[0]
                n, mult = 0, 1
                while True:
                    b = _lies_genau(s, 1)[0]
                    n += (b & 0x7F) * mult
                    mult *= 128
                    if not b & 0x80:
                        break
                daten = _lies_genau(s, n) if n else b""
                art = kopf >> 4
                if art == 1:  # CONNECT
                    if not self.antworten:
                        continue
                    pos = 2 + struct.unpack_from("!H", daten, 0)[0]
                    flags = daten[pos + 1]
                    pos += 4
                    _cid, pos = _str(daten, pos)
                    if flags & 0x04:
                        _w, pos = _str(daten, pos)
                        _w, pos = _str(daten, pos)
                    benutzer = passwort = ""
                    if flags & 0x80:
                        benutzer, pos = _str(daten, pos)
                    if flags & 0x40:
                        passwort, pos = _str(daten, pos)
                    ok = benutzer == "bblp" and passwort == self.zugangscode
                    self.anmeldungen.append(ok)
                    s.sendall(bytes([0x20, 2, 0, 0 if ok else 5]))
                    if not ok:
                        break
                    with self.lock:
                        self.clients.append(s)
                elif art == 8:  # SUBSCRIBE
                    pid = daten[:2]
                    s.sendall(bytes([0x90, 3]) + pid + b"\x00")
                elif art == 3:  # PUBLISH
                    qos = (kopf >> 1) & 3
                    thema, pos = _str(daten, 0)
                    if qos:
                        pid = daten[pos:pos + 2]
                        pos += 2
                        s.sendall(bytes([0x40, 2]) + pid)
                    try:
                        inhalt = json.loads(daten[pos:].decode("utf-8"))
                    except ValueError:
                        inhalt = {}
                    if thema == f"device/{self.seriennummer}/request":
                        with self.lock:
                            self.empfangen.append(inhalt)
                        self._befehl(inhalt)
                elif art == 12:  # PINGREQ
                    s.sendall(bytes([0xD0, 0]))
                elif art == 14:  # DISCONNECT
                    break
        except (ConnectionError, OSError, ssl.SSLError, IndexError, struct.error):
            pass
        finally:
            with self.lock:
                if s in self.clients:
                    self.clients.remove(s)
            try:
                s.close()
            except OSError:
                pass

    def _befehl(self, inhalt: dict[str, Any]) -> None:
        if "pushing" in inhalt and inhalt["pushing"].get("command") == "pushall":
            self.berichten({**self.zustand, "fun": self.fun, "hms": list(self.hms)})
            return
        if "info" in inhalt and inhalt["info"].get("command") == "get_version":
            self.senden({"info": {"command": "get_version", "sequence_id": inhalt["info"].get("sequence_id"),
                                  "module": [{"name": "ota", "sw_ver": self.firmware},
                                             {"name": "rv1126", "sw_ver": "00.00.30.00"}]}})
            return
        p = inhalt.get("print") or {}
        befehl = p.get("command")
        if not self.entwickler:  # wie die Firmware ab 01.08.02.00: unsignierter Steuerbefehl → HMS
            self.hms = [{"attr": 0x05000500, "code": 0x00010007}]
            self.berichten({"hms": list(self.hms)})
            return
        if befehl == "project_file":
            self.zustand.update(gcode_state="RUNNING", subtask_name=p.get("subtask_name", ""),
                                gcode_file=p.get("url", ""), mc_percent=0, layer_num=0, total_layer_num=50,
                                mc_remaining_time=42, nozzle_target_temper=220.0, bed_target_temper=55.0, stg_cur=0)
        elif befehl == "pause":
            self.zustand.update(gcode_state="PAUSE", stg_cur=16)
        elif befehl == "resume":
            self.zustand.update(gcode_state="RUNNING", stg_cur=0)
        elif befehl == "stop":
            self.zustand.update(gcode_state="FAILED", stg_cur=-1)
        self.berichten({k: self.zustand[k] for k in ("gcode_state", "stg_cur", "subtask_name", "gcode_file",
                                                     "total_layer_num", "mc_remaining_time")})

    def senden(self, nachricht: dict[str, Any]) -> None:
        roh = json.dumps(nachricht).encode()
        thema = f"device/{self.seriennummer}/report".encode()
        rest = struct.pack("!H", len(thema)) + thema + roh
        paket = bytes([0x30]) + _laenge(len(rest)) + rest
        with self.lock:
            for c in list(self.clients):
                try:
                    c.sendall(paket)
                except OSError:
                    pass

    def berichten(self, delta: dict[str, Any]) -> None:
        self.zustand.update({k: v for k, v in delta.items() if k not in ("fun", "hms")})
        self.senden({"print": {**delta, "command": "push_status", "msg": 1}})

    def druckt(self, prozent: int = 42, schicht: int = 41, schichten: int = 98, rest_min: int = 62) -> None:
        self.berichten({"gcode_state": "RUNNING", "mc_percent": prozent, "layer_num": schicht,
                        "total_layer_num": schichten, "mc_remaining_time": rest_min, "nozzle_temper": 219.5,
                        "nozzle_target_temper": 220.0, "bed_temper": 55.0, "bed_target_temper": 55.0, "stg_cur": 0,
                        "subtask_name": "Kugelschieber-platten"})

    def trennen(self) -> None:
        with self.lock:
            for c in list(self.clients):
                try:
                    c.close()
                except OSError:
                    pass
            self.clients.clear()

    def schliessen(self) -> None:
        self._halt.set()
        self.trennen()
        try:
            self.sock.close()
        except OSError:
            pass


class FtpsAttrappe:
    """FTP mit implizitem TLS: USER/PASS/PBSZ/PROT/TYPE/PASV/CWD/MKD/STOR/QUIT. Dateien landen in ``dateien``."""

    def __init__(self, pfade: dict[str, Path], zugangscode: str) -> None:
        self.zugangscode = zugangscode
        self.ctx = _server_kontext(pfade)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.dateien: dict[str, bytes] = {}
        self.ordner = {"", "cache"}
        self.anmeldungen: list[bool] = []
        self._halt = threading.Event()
        threading.Thread(target=self._annehmen, daemon=True).start()

    def _annehmen(self) -> None:
        self.sock.settimeout(0.5)
        while not self._halt.is_set():
            try:
                roh, _ = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._sitzung, args=(roh,), daemon=True).start()

    def _sitzung(self, roh: socket.socket) -> None:
        try:
            s = self.ctx.wrap_socket(roh, server_side=True)
        except (ssl.SSLError, OSError):
            roh.close()
            return
        f = s.makefile("rb")

        def antwort(text: str) -> None:
            s.sendall((text + "\r\n").encode())

        cwd = ""
        daten_sock: socket.socket | None = None
        angemeldet = False
        try:
            antwort("220 Kev CAD Drucker-Attrappe")
            for zeile in f:
                befehl, _, arg = zeile.decode("utf-8", "replace").strip().partition(" ")
                befehl = befehl.upper()
                if befehl == "USER":
                    antwort("331 Passwort")
                elif befehl == "PASS":
                    angemeldet = arg == self.zugangscode
                    self.anmeldungen.append(angemeldet)
                    antwort("230 Angemeldet" if angemeldet else "530 Login incorrect")
                elif not angemeldet and befehl not in ("QUIT",):
                    antwort("530 Erst anmelden")
                elif befehl in ("PBSZ", "PROT", "TYPE"):
                    antwort("200 OK")
                elif befehl == "PASV":
                    daten_sock = socket.socket()
                    daten_sock.bind(("127.0.0.1", 0))
                    daten_sock.listen(1)
                    p = daten_sock.getsockname()[1]
                    antwort(f"227 Entering Passive Mode (127,0,0,1,{p >> 8},{p & 255})")
                elif befehl == "CWD":
                    ziel = arg.strip("/")
                    if ziel in self.ordner:
                        cwd = ziel
                        antwort("250 OK")
                    else:
                        antwort("550 Kein Ordner")
                elif befehl == "MKD":
                    self.ordner.add(arg.strip("/"))
                    antwort(f'257 "{arg}"')
                elif befehl == "STOR" and daten_sock is not None:
                    antwort("150 Bereit")
                    d, _ = daten_sock.accept()
                    daten_sock.close()
                    daten_sock = None
                    ds = self.ctx.wrap_socket(d, server_side=True)
                    inhalt = bytearray()
                    try:
                        while True:
                            teil = ds.recv(65536)
                            if not teil:
                                break
                            inhalt += teil
                    except (ssl.SSLEOFError, ssl.SSLZeroReturnError, ConnectionResetError):
                        pass
                    ds.close()
                    self.dateien[f"{cwd}/{arg}".lstrip("/")] = bytes(inhalt)
                    antwort("226 Fertig")
                elif befehl == "QUIT":
                    antwort("221 Tschüss")
                    break
                else:
                    antwort("502 Nicht unterstützt")
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                s.close()
            except OSError:
                pass

    def schliessen(self) -> None:
        self._halt.set()
        try:
            self.sock.close()
        except OSError:
            pass


class Attrappe:
    """MQTT- und FTPS-Attrappe mit gemeinsamer Test-CA."""

    def __init__(self, ordner: Path, *, modus: str = "cloud", entwickler: bool = False,
                 seriennummer: str = TEST_SERIENNUMMER, zugangscode: str = TEST_ZUGANGSCODE,
                 antworten: bool = True) -> None:
        self.pfade = zertifikate(Path(ordner), seriennummer)
        self.seriennummer = seriennummer
        self.zugangscode = zugangscode
        self.mqtt = MqttAttrappe(self.pfade, seriennummer, zugangscode, modus=modus, entwickler=entwickler,
                                 antworten=antworten)
        self.ftps = FtpsAttrappe(self.pfade, zugangscode)

    @property
    def ca(self) -> str:
        return str(self.pfade["ca"])

    def __enter__(self) -> "Attrappe":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.schliessen()

    def schliessen(self) -> None:
        self.mqtt.schliessen()
        self.ftps.schliessen()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ordner", required=True)
    ap.add_argument("--modus", choices=("cloud", "lan"), default="cloud")
    ap.add_argument("--entwickler", action="store_true")
    ap.add_argument("--druckt", action="store_true", help="nach der ersten Anmeldung einen laufenden Druck melden")
    args = ap.parse_args()
    ordner = Path(args.ordner)
    a = Attrappe(ordner, modus=args.modus, entwickler=args.entwickler)
    (ordner / "attrappe.json").write_text(json.dumps({
        "mqtt_port": a.mqtt.port, "ftps_port": a.ftps.port, "ca": a.ca, "seriennummer": a.seriennummer,
        "zugangscode": a.zugangscode, "modus": args.modus, "entwickler": args.entwickler}), encoding="utf-8")
    print(f"Attrappe läuft: MQTT {a.mqtt.port}, FTPS {a.ftps.port}, Ordner {ordner}", flush=True)
    gemeldet = False
    try:
        while True:
            time.sleep(1.0)
            if args.druckt and a.mqtt.clients and not gemeldet:
                time.sleep(1.0)
                a.mqtt.druckt()
                gemeldet = True
    except KeyboardInterrupt:
        pass
    finally:
        a.schliessen()


if __name__ == "__main__":
    main()

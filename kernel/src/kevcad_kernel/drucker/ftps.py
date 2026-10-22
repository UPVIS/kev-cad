"""Upload per FTPS (Weg B, gesperrt, nicht ausgebaut): implizites TLS auf Port 990, Benutzer ``bblp``, Zugangscode.

Nach bambulabs_api und ha-bambulab (beide MIT): Der Datenkanal nutzt die TLS-Sitzung des Steuerkanals
(``session=self.sock.session``), beim Hochladen kein ``unwrap()`` (sonst hängt der Server). Ablage ``cache/`` auf der
SD-Karte. Wird nur vom Dienst aufgerufen, nachdem die Sperre Weg B freigegeben hat.
"""

from __future__ import annotations

import ftplib
import ssl
from collections.abc import Callable
from pathlib import Path

from kevcad_kernel.drucker import tls
from kevcad_kernel.drucker.befehle import DRUCKER_ABLAGE
from kevcad_kernel.drucker.schluesselbund import Zugang

PORT = 990
BENUTZER = "bblp"


class _ImplizitFTPS(ftplib.FTP_TLS):
    """FTP_TLS mit implizitem TLS (Socket gleich beim Verbinden einpacken) und geteilter Sitzung im Datenkanal."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sock: ssl.SSLSocket | None = None

    @property
    def sock(self):  # type: ignore[override]
        return self._sock

    @sock.setter
    def sock(self, value) -> None:
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):  # noqa: ANN001
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size

    def storbinary(self, cmd, fp, blocksize=65536, callback=None, rest=None):  # noqa: ANN001
        self.voidcmd("TYPE I")
        conn = self.transfercmd(cmd, rest)
        try:
            while True:
                buf = fp.read(blocksize)
                if not buf:
                    break
                conn.sendall(buf)
                if callback:
                    callback(buf)
        finally:
            conn.close()  # ohne unwrap()
        return self.voidresp()


class UploadFehler(Exception):
    pass


def hochladen(ip: str, zugang: Zugang, datei: Path, ziel_name: str, *, port: int = PORT, ca_datei: str | None = None,
              zeitlimit_s: float = 30.0, fortschritt: Callable[[float], None] | None = None) -> str:
    """Lädt ``datei`` nach ``cache/<ziel_name>``; gibt den Pfad auf dem Drucker zurück. Fehler ohne Zugangsdaten."""
    groesse = max(1, datei.stat().st_size)
    gesendet = 0

    def weiter(buf: bytes) -> None:
        nonlocal gesendet
        gesendet += len(buf)
        if fortschritt:
            fortschritt(min(1.0, gesendet / groesse))

    ftp = _ImplizitFTPS(context=tls.kontext(ca_datei), timeout=zeitlimit_s)
    try:
        ftp.connect(ip, port, timeout=zeitlimit_s)
        tls.pruefe_cn(ftp.sock, zugang.seriennummer)
        ftp.login(BENUTZER, zugang.zugangscode)
        ftp.prot_p()
        ftp.set_pasv(True)
        try:
            ftp.cwd(DRUCKER_ABLAGE)
        except ftplib.error_perm:
            ftp.mkd(DRUCKER_ABLAGE)
            ftp.cwd(DRUCKER_ABLAGE)
        with datei.open("rb") as fh:
            ftp.storbinary(f"STOR {ziel_name}", fh, callback=weiter)
    except tls.ZertifikatFehler as exc:
        raise UploadFehler(str(exc)) from None
    except ftplib.error_perm as exc:
        text = str(exc)
        if text.startswith("530"):
            raise UploadFehler("Der Drucker lehnt die Anmeldung ab (Zugangscode prüfen).") from None
        raise UploadFehler(f"Upload abgelehnt ({text[:3]}).") from None
    except (OSError, EOFError, ftplib.Error) as exc:
        raise UploadFehler(f"Upload fehlgeschlagen: {type(exc).__name__}") from None
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            try:
                ftp.close()
            except Exception:  # noqa: BLE001
                pass
    return f"{DRUCKER_ABLAGE}/{ziel_name}"

"""TLS zum Drucker (MQTT 8883, FTPS 990): Zertifikatskette gegen die Bambu-CAs, Hostname-Prüfung aus (der Drucker hat
kein Zertifikat auf seine IP), stattdessen CN = Seriennummer prüfen (OpenBambuAPI ``tls.md``, ha-bambulab)."""

from __future__ import annotations

import ssl
from pathlib import Path

CA_DATEI = Path(__file__).with_name("bambu_ca.pem")


class ZertifikatFehler(Exception):
    pass


def kontext(ca_datei: str | Path | None = None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=str(ca_datei or CA_DATEI))
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    # Ab Python 3.13 ist VERIFY_X509_STRICT an; die Bambu-CAs erfüllen das nicht (ha-bambulab)
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2  # wie ha-bambulab (P2S-Firmware); für den P1P unschädlich
    return ctx


def common_name(cert: dict | None) -> str | None:
    for rdn in (cert or {}).get("subject", ()):
        for k, v in rdn:
            if k == "commonName":
                return str(v)
    return None


def pruefe_cn(sock: ssl.SSLSocket | None, seriennummer: str) -> None:
    """Wirft ``ZertifikatFehler``, wenn das Zertifikat nicht auf die Seriennummer ausgestellt ist (ohne beide Werte zu
    nennen: die Seriennummer bleibt aus Meldungen draußen)."""
    if sock is None:
        raise ZertifikatFehler("TLS-Verbindung ohne Zertifikat")
    cn = common_name(sock.getpeercert())
    if not cn or cn != seriennummer:
        raise ZertifikatFehler("Das Zertifikat des Druckers passt nicht zur eingetragenen Seriennummer")

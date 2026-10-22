"""Sperre vor jedem Steuerbefehl an den Drucker (DRUCKVORSCHAU.md, „Drucken (Phase 8)“, verbindlich).

Hintergrund: Seit Firmware 01.08.02.00 lehnt der P1P Steuerbefehle fremder Software ab, außer im LAN-only-Modus mit
Developer Mode. Ein abgelehnter Befehl erzeugt HMS 0500-0500-0001-0007 und blockiert weitere Drucke, bis Kevin ihn am
Drucker quittiert. Deshalb sendet der Kernel einen Steuerbefehl nur, wenn **alle** Bedingungen gelten; im Zweifel
nicht. Lesebefehle (``befehle.LESEN``) laufen nicht hierüber, nur ihr Abstand (``pushall_frei``).
"""

from __future__ import annotations

from dataclasses import dataclass

from kevcad_kernel.drucker.befehle import PUSHALL_ABSTAND_S
from kevcad_kernel.drucker.status import HMS_SIGNATUR_ABGELEHNT, Bericht

ANLEITUNG_WEG_B: list[str] = [
    "Firmware des P1P mindestens 01.08.02.00 (am Drucker: Einstellungen → Firmware).",
    "Am Drucker: Einstellungen → WLAN → „LAN Only Mode“ → Yes.",
    "Auf derselben Seite mit der Taste nach unten zu „Developer Mode“, den Hinweis lesen, ans Ende → Enable.",
    "Zugangscode und IP stehen auf derselben Seite; beides in Kev CAD unter Drucker-Einstellungen eintragen.",
    "Achtung: Bambu Handy, Fernzugriff und Cloud-Updates fallen damit weg. Zurück geht es auf demselben Weg.",
    "In Kev CAD Weg B wählen; Kev CAD prüft den Developer Mode bei jeder Verbindung selbst.",
]


@dataclass(frozen=True)
class Lage:
    """Was die Sperre über die Lage weiß (vom Dienst zusammengestellt)."""

    weg: str  # "a" | "b" aus den Einstellungen
    verbunden: bool  # MQTT-Verbindung in dieser Sitzung steht
    entwicklermodus: bool | None  # aus print.fun dieser Verbindung (None = nicht gesehen)
    ssdp_verbindung: str | None  # "lan" | "cloud" | None (nicht gehört)
    signatur_abgelehnt: bool  # HMS 0500-0500-0001-0007 offen


def lage_aus(weg: str, verbunden: bool, bericht: Bericht, ssdp_verbindung: str | None) -> Lage:
    return Lage(weg=weg, verbunden=verbunden, entwicklermodus=bericht.entwicklermodus if verbunden else None,
                ssdp_verbindung=ssdp_verbindung, signatur_abgelehnt=bericht.signatur_abgelehnt)


def grund_weg_b(lage: Lage) -> str | None:
    """None, wenn Weg B möglich ist; sonst der erste Grund dagegen (für Kevin lesbar)."""
    if lage.signatur_abgelehnt:
        return (f"Der Drucker meldet HMS {HMS_SIGNATUR_ABGELEHNT} (Befehl ohne Freigabe abgelehnt). Am Drucker "
                "quittieren; bis dahin sendet Kev CAD nichts.")
    if lage.ssdp_verbindung == "cloud":
        return "Der Drucker ist im Cloud-Modus (LAN Only Mode aus)."
    if not lage.verbunden:
        return "Keine Verbindung zum Drucker (IP, Seriennummer, Zugangscode und „Status lesen“ nötig)."
    if lage.entwicklermodus is None:
        return "Developer Mode ist nicht nachgewiesen (der Drucker hat noch keinen vollständigen Bericht geschickt)."
    if lage.entwicklermodus is False:
        return "Developer Mode ist aus (der Drucker verlangt signierte Befehle)."
    return None


def pruefe_steuern(lage: Lage, *, start: bool = False, bestaetigt: bool = False) -> str | None:
    """None = Steuerbefehl erlaubt; sonst Grund. ``start``: Druckstart, braucht zusätzlich Kevins Bestätigung."""
    if lage.weg != "b":
        return "Weg A ist eingestellt: Kev CAD steuert den Drucker nicht, das geht nur in Bambu Studio oder Bambu Handy."
    grund = grund_weg_b(lage)
    if grund:
        return grund
    if start and not bestaetigt:
        return "Der Druckstart braucht Kevins Bestätigung im Dialog „Drucken …“."
    return None


def pushall_frei(letzter: float | None, jetzt: float) -> bool:
    return letzter is None or jetzt - letzter >= PUSHALL_ABSTAND_S

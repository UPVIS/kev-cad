"""Zugangsdaten des Druckers aus dem macOS-Schlüsselbund lesen (DRUCKVORSCHAU.md, „Drucken (Phase 8)“, Einstellungen).

Die App legt je Drucker einen Eintrag an (generisches Passwort, Dienst ``DIENST``, Konto = Drucker-ID, Inhalt JSON
``{"seriennummer": …, "zugangscode": …}``) und erlaubt ``/usr/bin/security`` den Zugriff. Der Kernel liest ihn nur beim
Verbinden, mit festem Dienstnamen und geprüfter ID, und gibt weder Ausgabe noch Fehlertext von ``security`` weiter:
Fehler nennen nur, *dass* es nicht ging. ``Zugang`` verbirgt seine Werte in ``repr``/``str``, damit sie auch in einem
Traceback oder Protokoll nicht auftauchen.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

DIENST = "de.upvis.kevcad.drucker"
SECURITY = "/usr/bin/security"
ID_MUSTER = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")  # nie mit „-“ vorn (wäre für security eine Option)


class SchluesselbundFehler(Exception):
    """Ohne Inhalt aus dem Schlüsselbund; nur der Grund in Worten."""


@dataclass(frozen=True)
class Zugang:
    seriennummer: str = field(repr=False)
    zugangscode: str = field(repr=False)

    def __repr__(self) -> str:  # nie die Werte
        return "Zugang(…)"

    __str__ = __repr__


def pruefe_id(drucker_id: str) -> str:
    if not isinstance(drucker_id, str) or not ID_MUSTER.match(drucker_id):
        raise SchluesselbundFehler("Drucker-ID ungültig (erlaubt: a–z, 0–9, Bindestrich nicht vorn, höchstens 32 "
                                   "Zeichen)")
    return drucker_id


def _aus_text(text: str) -> Zugang:
    try:
        daten = json.loads(text)
    except ValueError:
        raise SchluesselbundFehler("Eintrag im Schlüsselbund hat ein unbekanntes Format") from None
    if not isinstance(daten, dict):
        raise SchluesselbundFehler("Eintrag im Schlüsselbund hat ein unbekanntes Format")
    sn = str(daten.get("seriennummer") or "").strip()
    code = str(daten.get("zugangscode") or "").strip()
    if not sn or not code:
        raise SchluesselbundFehler("Seriennummer oder Zugangscode fehlt im Schlüsselbund")
    return Zugang(seriennummer=sn, zugangscode=code)


def lesen(drucker_id: str, *, ausfuehren: Callable[..., subprocess.CompletedProcess] | None = None) -> Zugang:
    """Zugang des Druckers ``drucker_id`` lesen. ``ausfuehren`` nur für Tests (Ersatz für ``subprocess.run``)."""
    konto = pruefe_id(drucker_id)
    run = ausfuehren or subprocess.run
    try:
        res = run([SECURITY, "find-generic-password", "-s", DIENST, "-a", konto, "-w"], capture_output=True,
                  text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        raise SchluesselbundFehler("Schlüsselbund nicht lesbar (security lief nicht)") from None
    if res.returncode != 0:
        # Fehlertext von security bewusst nicht übernehmen
        raise SchluesselbundFehler("Keine Zugangsdaten im Schlüsselbund (in den Drucker-Einstellungen eintragen)")
    text = (res.stdout or "").strip()
    res = None  # noqa: F841 – Ausgabe nicht länger halten als nötig
    return _aus_text(text)


def aus_werten(seriennummer: str, zugangscode: str) -> Zugang:
    """Für Tests und die Attrappe."""
    return Zugang(seriennummer=seriennummer, zugangscode=zugangscode)

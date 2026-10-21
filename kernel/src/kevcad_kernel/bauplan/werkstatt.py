"""Werkstattwissen für den Bauplan: Werkzeug je Verbindungsmittel, Bohren, Sägen, Drucken.

Die Tabellen sind Normwerte (Schlüsselweiten ISO 4032/4017, Innensechskant ISO 4762/7380/10642/4026) bzw. die
Druckwerte aus skill/kev-cad/3d-druck.md (Bambu Lab P1P). Was nicht sicher ist, heißt Schätzung.
"""

from __future__ import annotations

import re
from typing import Any

from kevcad_kernel.bom import de_num

# Innensechskant (Schlüsselweite in mm) je Nenndurchmesser
INNEN_6KT = {
    "iso4762": {2: 1.5, 2.5: 2, 3: 2.5, 4: 3, 5: 4, 6: 5, 8: 6, 10: 8, 12: 10, 16: 14},  # Zylinderkopf
    "iso7380": {3: 2, 4: 2.5, 5: 3, 6: 4, 8: 5, 10: 6, 12: 8},  # Linsenkopf
    "iso10642": {3: 2, 4: 2.5, 5: 3, 6: 4, 8: 5, 10: 6, 12: 8},  # Senkkopf
    "iso4026": {3: 1.5, 4: 2, 5: 2.5, 6: 3, 8: 4, 10: 5, 12: 6},  # Gewindestift
}
# Schlüsselweite Sechskant (Mutter ISO 4032, Schraube ISO 4017/4014)
SW = {2: 4, 2.5: 5, 3: 5.5, 4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18, 16: 24, 20: 30}
# Kernloch (ISO 2306) und Durchgang mittel (ISO 273)
KERNLOCH = {3: 2.5, 4: 3.3, 5: 4.2, 6: 5.0, 8: 6.8, 10: 8.5, 12: 10.2, 16: 14.0}
DURCHGANG = {3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 16: 17.5}

# Druck (3d-druck.md, Abschnitt Materialien): Düse / Bett in °C, Lötkolben für Gewindeeinsätze
DRUCK = {
    "pla": {"duese": 205, "bett": 47, "einsatz": 225, "name": "PLA"},
    "petg": {"duese": 255, "bett": 80, "einsatz": 245, "name": "PETG", "hinweis": "Texturplatte (glatte PEI-Platte "
             "nur mit Trennmittel, PETG haftet sehr stark)"},
    "abs": {"duese": 270, "bett": 100, "einsatz": 265, "name": "ABS", "hinweis": "nur mit Einhausung (P1P offen)"},
    "asa": {"duese": 260, "bett": 100, "einsatz": 265, "name": "ASA", "hinweis": "nur mit Einhausung (P1P offen)"},
    "tpu-95a": {"duese": 230, "bett": 45, "einsatz": None, "name": "TPU 95A", "hinweis": "langsam drucken, ohne AMS"},
}
BAURAUM = (256.0, 256.0, 250.0)


def nenn(vm: dict[str, Any]) -> float | None:
    d = vm.get("d")
    return float(d) if d else None


def _norm_key(norm: Any) -> str:
    n = str(norm or "").lower().replace("_1", "").replace("-", "")
    return n


def werkzeug_vm(vm: dict[str, Any], name: str = "") -> list[str]:
    """Werkzeug für ein Verbindungsmittel (Typ, Norm, Nenndurchmesser)."""
    typ = str(vm.get("typ") or "")
    d = nenn(vm)
    norm = _norm_key(vm.get("norm"))
    low = name.lower()
    if typ == "WingNut" or "flügel" in low or "fluegel" in low or "rändel" in low:
        return ["von Hand"]
    if typ == "HeatSetNut" or "einsatz" in low:
        return []
    if typ == "PlainWasher" or "scheibe" in low:
        return []
    if typ in ("HexNut", "DomedCapNut") or ("mutter" in low and typ not in ("WingNut",)):
        sw = SW.get(d) if d else None
        return [f"Maulschlüssel SW {de_num(sw)}" if sw else "Maulschlüssel passend (Schätzung)"]
    if typ == "HexHeadScrew":
        sw = SW.get(d) if d else None
        return [f"Ring- oder Maulschlüssel SW {de_num(sw)}" if sw else "Schlüssel passend (Schätzung)"]
    for key in ("iso4762", "iso7380", "iso10642", "iso4026"):
        if norm.startswith(key):
            s = INNEN_6KT[key].get(d) if d else None
            if s:
                return [f"Innensechskant {de_num(s)} mm"]
    if typ == "SocketHeadCapScrew":
        s = INNEN_6KT["iso4762"].get(d) if d else None
        return [f"Innensechskant {de_num(s)} mm" if s else "Innensechskant passend (Schätzung)"]
    if typ == "ButtonHeadScrew":
        s = INNEN_6KT["iso7380"].get(d) if d else None
        return [f"Innensechskant {de_num(s)} mm" if s else "Innensechskant passend (Schätzung)"]
    if typ == "SetScrew":
        s = INNEN_6KT["iso4026"].get(d) if d else None
        return [f"Innensechskant {de_num(s)} mm" if s else "Innensechskant passend (Schätzung)"]
    if typ == "CounterSunkScrew":
        if "zoll" in low or "3⁄8" in low or "3/8" in low or "1/4" in low:
            return ["Schraubendreher oder Innensechskant passend zum Kopf (Schätzung)"]
        s = INNEN_6KT["iso10642"].get(d) if d else None
        return [f"Innensechskant {de_num(s)} mm" if s else "Innensechskant passend (Schätzung)"]
    return ["Werkzeug passend zum Kopf (Schätzung)"]


def zugang_mass(vm: dict[str, Any], name: str = "") -> tuple[float, float, str]:
    """(Radius, Länge, Art) des Raums, den das Werkzeug am Verbindungsmittel braucht (Schätzung): Innensechskant
    gerade über dem Kopf, Schlüssel rund um die Mutter, Finger rund um die Flügelmutter."""
    d = nenn(vm) or 6.0
    w = werkzeug_vm(vm, name)
    text = w[0] if w else ""
    if text == "von Hand":
        return d * 2.5 + 8.0, 12.0, "finger"
    if text.startswith("Maulschlüssel") or text.startswith("Ring"):
        sw = SW.get(d, 1.6 * d)
        return 1.25 * sw, max(4.0, 0.8 * d), "schluessel"
    if text.startswith("Innensechskant"):
        return max(1.0, 0.45 * d), 40.0, "stift"
    return max(1.0, 0.6 * d), 40.0, "stift"


def saege(material: str | None, art: str | None) -> list[str]:
    m = str(material or "").lower()
    if art == "holz" or "holz" in m or "birke" in m or "fichte" in m or "buche" in m:
        return ["Kappsäge oder Handsäge mit Gehrungslade"]
    if art == "platte":
        if "multiplex" in m or "holz" in m or "mdf" in m or "spanplatte" in m:
            return ["Tauch- oder Tischkreissäge mit Führungsschiene"]
        return ["Tafelschere, Stichsäge mit Metallblatt oder Plattensäge (Schätzung)"]
    if "alu" in m or "aw-" in m or "aluminium" in m:
        return ["Kappsäge mit Alu-Sägeblatt (Negativwinkel) oder Metallsäge", "Entgrater"]
    if "edelstahl" in m or "1.4" in m:
        return ["Metallkreissäge oder Bandsäge (Edelstahlblatt)", "Entgrater"]
    if "stahl" in m or "s235" in m:
        return ["Metallkreissäge, Bandsäge oder Winkelschleifer mit Trennscheibe", "Entgrater"]
    return ["Säge passend zum Material (Schätzung)", "Entgrater"]


def bohr_hinweis(material: str | None) -> str:
    m = str(material or "").lower()
    if "alu" in m or "aluminium" in m:
        return "Alu: HSS-Bohrer, etwas Spiritus oder Schneidöl, Späne oft entfernen"
    if "edelstahl" in m:
        return "Edelstahl: HSS-Co-Bohrer, langsam mit Druck und Schneidöl, nicht reiben lassen"
    if "stahl" in m:
        return "Stahl: ankörnen, vorbohren ab Ø 8, Schneidöl"
    if "polyprop" in m or "kunststoff" in m or m in ("pp", "pe", "pom"):
        return "Kunststoff: niedrige Drehzahl, scharfer Bohrer, Bohrung von beiden Seiten entgraten"
    if "holz" in m or "multiplex" in m or "birke" in m:
        return "Holz: Holzspiralbohrer mit Zentrierspitze, Unterlage gegen Ausreißen"
    return ""


def bohrer_text(d: float) -> str:
    return f"Bohrer Ø {de_num(d)}"


def druck_info(material: str | None) -> dict[str, Any]:
    m = str(material or "").lower()
    return DRUCK.get(m) or DRUCK.get(m.split("-")[0]) or {}


def stueck_name(name: str) -> str:
    """„Kugelschieber/Scheibe M4 vorn links“ → „Scheibe M4“ (für Sammeltexte)."""
    kurz = name.rsplit("/", 1)[-1]
    kurz = re.sub(r"\s*\((?:Druck|Rohr \d+)\)\s*", " ", kurz).strip()
    kurz = re.sub(r"\s+(\d+\s+)?(vorn|hinten|oben|unten|links|rechts|mitte|innen|außen|aussen)(\s+(links|rechts|"
                  r"vorn|hinten|oben|unten))*$", "", kurz, flags=re.IGNORECASE)
    kurz = re.sub(r"\s+(Schieber|Fänger|Träger)(\s+\d+)?$", "", kurz)
    kurz = re.sub(r"\s+\d+$", "", kurz)
    return kurz.strip() or name.rsplit("/", 1)[-1]

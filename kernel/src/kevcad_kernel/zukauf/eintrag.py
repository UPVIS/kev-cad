"""Zukaufteil-Einträge (KATALOG.md, Abschnitt „Zukaufteil (Phase 3)“): prüfen, aus Shop-Feldern zusammensetzen,
Maße und Preise aus Text lesen, Ersatzkörper aus den Maßen.

Leicht (kein build123d): läuft im Elternprozess beim Laden des Katalogs und in den MCP-Werkzeugen.
"""

from __future__ import annotations

import copy
import re
import time
import unicodedata
from typing import Any
from urllib.parse import urlparse

from kevcad_kernel.bezugspunkte import pruefen_punkt, pruefen_punkte
from kevcad_kernel.catalog import FREI, STATUS, VORGESCHLAGEN, ZUKAUF_ARTEN, fold, number

CAD_QUELLEN: tuple[str, ...] = ("traceparts", "hersteller", "download", "bd_warehouse", "skript", "keins")
CAD_MIT_DATEI = ("traceparts", "hersteller", "download")
ERSATZ_FORMEN: tuple[str, ...] = ("quader", "zylinder")
ACHSEN = ("x", "y", "z")
MASSE_KEYS = ("l", "b", "h", "d")
CAD_ENDUNGEN = ("step", "stp", "zip")
VEREINFACHT = " (vereinfacht)"

FELDER = (
    "id", "art", "name", "hersteller", "mpn", "gtin", "shop_nr", "shop", "url", "bild", "preis", "masse", "gewicht",
    "material", "cad", "ersatz", "einbaupunkt", "bezugspunkte", "status", "vorgeschlagen_am", "vorgeschlagen_von",
    "hinweis", "tags", "entfernt",
)

_ID_OK = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
_WAEHRUNG_RE = re.compile(r"^[A-Z]{3}$")


def heute() -> str:
    return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------------------------------------------------
# GTIN und ids


def gtin_digits(value: Any) -> str | None:
    """Ziffern einer EAN/GTIN (8 bis 14 Stellen, Leerzeichen und Bindestriche erlaubt), sonst None."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[\s-]", "", value)
    if not digits.isdigit() or not 8 <= len(digits) <= 14:
        return None
    return digits


def gtin_ok(value: Any) -> bool:
    """Prüfziffer nach GS1 (Modulo 10, Gewichte 3 und 1 von rechts)."""
    digits = gtin_digits(value)
    if digits is None:
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", fold(str(text)))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9.]+", "-", t).strip("-.")
    return re.sub(r"-{2,}", "-", t)


def make_id(hersteller: str | None = None, mpn: str | None = None, gtin: str | None = None,
            name: str | None = None, shop_nr: str | None = None) -> str:
    """id aus Hersteller und Nummer (``alutec-05200``), sonst aus GTIN oder Name."""
    if hersteller and mpn:
        base = f"{slug(hersteller)}-{slug(mpn)}"
    elif mpn:
        base = slug(mpn)
    elif hersteller and shop_nr:
        base = f"{slug(hersteller)}-{slug(shop_nr)}"
    elif gtin:
        base = f"gtin-{gtin_digits(gtin) or slug(gtin)}"
    elif name:
        base = slug(name)[:48]
    else:
        base = ""
    base = base.strip("-.")[:64]
    if base and not base[0].isalnum():
        base = base.lstrip("-.")
    return base or f"zukauf-{int(time.time())}"


# ---------------------------------------------------------------------------------------------------------------------
# Maße, Gewicht und Preise aus Text

_EINHEIT_MM = {"mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "zoll": 25.4, '"': 25.4,
               "″": 25.4, "”": 25.4, "mmt": 1.0, "cmt": 10.0, "mtr": 1000.0, "inh": 25.4, "ft": 304.8, "fot": 304.8}
_EINHEIT_G = {"g": 1.0, "gr": 1.0, "grm": 1.0, "kg": 1000.0, "kgm": 1000.0, "lb": 453.59237, "lbs": 453.59237,
              "lbr": 453.59237, "oz": 28.349523, "onz": 28.349523, "t": 1e6}
_NUM = r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)"
_UNIT = r"((?:mm|cm|dm|m|in|inch|zoll|\"|″|”)(?![a-zäöüß]))"


def _num(text: str, tausender: bool = False) -> float | None:
    """Zahl aus Text; ``tausender``: "1.600" ist 1600 (bei mm und g üblich), sonst 1,6."""
    t = text.strip().replace(" ", "")
    if "/" in t:  # Bruch wie 1/4
        a, _, b = t.partition("/")
        x, y = number(a), number(b)
        return x / y if x is not None and y else None
    if re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+,\d+", t) or (tausender and re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+", t)):
        t = t.replace(".", "")  # 1.234,5 bzw. 1.600 mm
    return number(t)


def laenge_mm(value: Any, einheit: str | None = None) -> float | None:
    """Länge in mm aus Zahl (mit Einheit) oder Text wie "12,8 cm", '1/4"', "610 mm"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = _EINHEIT_MM.get((einheit or "mm").strip().lower())
        return float(value) * f if f else None
    if not isinstance(value, str):
        return None
    m = re.fullmatch(rf"\s*{_NUM}\s*{_UNIT}?\.?\s*", value.strip().lower())
    if not m:
        return None
    unit = (m.group(2) or (einheit or "mm")).strip().lower()
    x = _num(m.group(1), tausender=unit in ("mm", "mmt"))
    f = _EINHEIT_MM.get(unit)
    return x * f if x is not None and f else None


def gewicht_g(value: Any, einheit: str | None = None) -> float | None:
    """Gewicht in g aus Zahl (mit Einheit) oder Text wie "1,8 kg", "640 g"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = _EINHEIT_G.get((einheit or "g").strip().lower())
        return float(value) * f if f else None
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|lbs?|oz|t)?\.?\s*", value.strip().lower())
    if not m:
        return None
    unit = (m.group(2) or (einheit or "g")).strip().lower()
    x = _num(m.group(1), tausender=unit in ("g", "gr", "grm"))
    f = _EINHEIT_G.get(unit)
    return x * f if x is not None and f else None


_TRIPLE = re.compile(rf"{_NUM}\s*{_UNIT}?\s*[x×*]\s*{_NUM}\s*{_UNIT}?\s*(?:[x×*]\s*{_NUM}\s*{_UNIT}?)?", re.I)
_LABELS = {
    "l": ("länge", "laenge", "length", "tiefe", "depth", "lang"),
    "b": ("breite", "width", "breit"),
    "h": ("höhe", "hoehe", "height", "hoch", "bauhöhe", "bauhoehe"),
    "d": ("durchmesser", "diameter", "ø", "⌀", "dm."),
}


def masse_aus_text(text: str) -> dict[str, float]:
    """Hüllmaße in mm aus Text: "61 x 41 x 12,8 cm" → l, b, h; "Länge: 610 mm"; "Ø 70 mm"; '1" lang'.

    Bei einer Kette "A x B x C" gilt die Reihenfolge l × b × h, die Einheit steht am Ende oder an jeder Zahl."""
    if not isinstance(text, str) or not text.strip():
        return {}
    low = text.lower().replace(" ", " ")
    out: dict[str, float] = {}
    for m in _TRIPLE.finditer(low):
        nums = [m.group(i) for i in (1, 3, 5)]
        units = [m.group(i) for i in (2, 4, 6)]
        last_unit = next((u for u in reversed(units) if u), None)
        if last_unit is None:
            continue  # ohne Einheit zu unsicher (Stückzahlen, Pakete)
        vals = [laenge_mm(n, u or last_unit) if n else None for n, u in zip(nums, units)]
        vals = [v for v in vals if v is not None]
        if len(vals) == 3:
            out.update(l=vals[0], b=vals[1], h=vals[2])
            break
        if len(vals) == 2 and re.search(r"(ø|⌀|durchmesser|diameter|d\s*=)", low[max(0, m.start() - 12):m.start()]):
            out.update(d=vals[0], l=vals[1])
            break
    for key, words in _LABELS.items():
        if key in out:
            continue
        found: list[float] = []
        for w in words:
            pat = rf"{re.escape(w)}\s*(?:\([^)]*\))?\s*[:=]?\s*(?:ca\.?\s*)?{_NUM}\s*{_UNIT}"
            for m in re.finditer(pat, low):
                vor = low[max(0, m.start() - 8):m.start()]
                if re.search(r"(innen|kern|loch|bohr|gewinde|inner|bore|hole)-?$", vor):
                    continue  # Innenmaße bestimmen die Hülle nicht
                v = laenge_mm(m.group(1), m.group(2))
                if v is not None:
                    found.append(v)
            if found and key != "d":
                break
        if key == "l" and not found:  # '1" Long', "160 cm lang"
            m = re.search(rf"{_NUM}\s*{_UNIT}\s*(?:long|lang)\b", low)
            if m:
                v = laenge_mm(m.group(1), m.group(2))
                if v is not None:
                    found.append(v)
        if found:
            out[key] = max(found) if key == "d" else found[0]
    return {k: round(v, 3) for k, v in out.items()}


_WAEHRUNGEN = {"€": "EUR", "eur": "EUR", "euro": "EUR", "$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP",
               "chf": "CHF", "fr.": "CHF"}


def preis_aus_text(value: Any) -> tuple[float | None, str | None]:
    """(Betrag, Währung) aus 24.99, "24,99 €", "EUR 1.299,00", "$12.50"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None
    if not isinstance(value, str):
        return None, None
    low = value.strip().lower().replace(" ", " ")
    waehrung = None
    for sym, code in _WAEHRUNGEN.items():
        if sym in low:
            waehrung = code
            break
    m = re.search(r"\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|\d+(?:[.,]\d{1,2})?", low)
    if not m:
        return None, waehrung
    t = m.group(0).replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t), waehrung
    except ValueError:
        return None, waehrung


# ---------------------------------------------------------------------------------------------------------------------
# Hüllmaße und Ersatzkörper


def masse_zahlen(masse: Any) -> dict[str, float]:
    return {k: v for k in MASSE_KEYS if isinstance(masse, dict) and (v := number(masse.get(k))) is not None}


def ersatz_aus_masse(masse: dict[str, Any]) -> dict[str, Any] | None:
    """Ersatzkörper aus den Hüllmaßen: Quader bei l, b, h; Zylinder bei d (stehend, Höhe l bzw. h)."""
    m = masse_zahlen(masse)
    if all(k in m for k in ("l", "b", "h")):
        return {"form": "quader", "masse": {"l": m["l"], "b": m["b"], "h": m["h"]}}
    if "d" in m:
        hoehe = m.get("l") or m.get("h") or m["d"]
        return {"form": "zylinder", "masse": {"d": m["d"], "l": hoehe}}
    return None


def ersatz_huelle(ersatz: dict[str, Any]) -> tuple[float, float, float] | None:
    """Hüllquader (x, y, z) des Ersatzkörpers im Quellsystem."""
    m = masse_zahlen((ersatz or {}).get("masse"))
    form = (ersatz or {}).get("form")
    if form == "quader" and all(k in m for k in ("l", "b", "h")):
        return (m["l"], m["b"], m["h"])
    if form == "zylinder" and "d" in m:
        hoehe = m.get("l") or m.get("h") or m["d"]
        achse = str((ersatz or {}).get("achse") or "z")
        return {"x": (hoehe, m["d"], m["d"]), "y": (m["d"], hoehe, m["d"])}.get(achse, (m["d"], m["d"], hoehe))
    return None


def huelle(entry: dict[str, Any]) -> tuple[float, float, float] | None:
    """Erwartete Hüllmaße (x, y, z) laut Katalog: Ersatzkörper, sonst die Maße (l × b × h, d × d × l, d × d × d)."""
    ers = entry.get("ersatz") if isinstance(entry.get("ersatz"), dict) else None
    if ers:
        h = ersatz_huelle(ers)
        if h:
            return h
    m = masse_zahlen(entry.get("masse"))
    if all(k in m for k in ("l", "b", "h")):
        return (m["l"], m["b"], m["h"])
    if "d" in m:
        hoehe = m.get("l") or m.get("h") or m["d"]
        return (m["d"], m["d"], hoehe)
    return None


def masse_text(masse: Any) -> str:
    from kevcad_kernel.bom import de_num

    m = masse_zahlen(masse)
    if all(k in m for k in ("l", "b", "h")):
        return f"{de_num(m['l'])} × {de_num(m['b'])} × {de_num(m['h'])} mm"
    if "d" in m:
        rest = m.get("l") or m.get("h")
        return f"Ø {de_num(m['d'])}" + (f" × {de_num(rest)}" if rest else "") + " mm"
    return ", ".join(f"{k} {de_num(v)}" for k, v in m.items()) + (" mm" if m else "")


# ---------------------------------------------------------------------------------------------------------------------
# Prüfen


def _http(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    p = urlparse(value.strip())
    return p.scheme in ("http", "https") and bool(p.netloc)


def validate_zukauf(entry: Any, material_ids: set[str] | None = None) -> list[str]:
    """Fehler eines Zukaufteils (leer = gültig). ``material_ids``: bekannte Materialien (None = nicht prüfen)."""
    if not isinstance(entry, dict):
        return ["Zukaufteil muss ein JSON-Objekt sein"]
    errors: list[str] = []
    eid = entry.get("id")
    who = f"Zukaufteil {eid!r}" if isinstance(eid, str) else "Zukaufteil"
    if not isinstance(eid, str) or not eid.strip():
        errors.append("Zukaufteil: Feld id fehlt (z. B. \"alutec-05200\": Hersteller und Nummer, klein, Bindestriche)")
    elif not _ID_OK.match(eid):
        errors.append(f"{who}: id nur aus Kleinbuchstaben, Ziffern, Bindestrichen und Punkten (Vorschlag: "
                      f"{slug(eid)!r})")
    if entry.get("art") not in ZUKAUF_ARTEN:
        errors.append(f"{who}: art muss \"zukaufteil\" sein")
    if not isinstance(entry.get("name"), str) or not entry["name"].strip():
        errors.append(f"{who}: Feld name fehlt (Anzeige, z. B. \"ALUTEC Transportroller 05200\")")
    has_mpn = isinstance(entry.get("mpn"), str) and entry["mpn"].strip()
    has_shop = isinstance(entry.get("shop_nr"), str) and entry["shop_nr"].strip()
    if not has_mpn and not has_shop:
        errors.append(f"{who}: mpn (Herstellernummer) fehlt; bei reinen Shop-Artikeln ohne Herstellernummer shop_nr "
                      "angeben")
    if has_mpn and not (isinstance(entry.get("hersteller"), str) and entry["hersteller"].strip()):
        errors.append(f"{who}: hersteller fehlt (zur Herstellernummer gehört der Hersteller)")
    for key in ("hersteller", "mpn", "shop_nr", "shop", "hinweis"):
        if entry.get(key) is not None and not isinstance(entry.get(key), str):
            errors.append(f"{who}: {key} muss Text sein")
    if entry.get("gtin") is not None:
        g = entry.get("gtin")
        if gtin_digits(g) is None:
            errors.append(f"{who}: gtin muss 8 bis 14 Ziffern haben (EAN/GTIN), nicht {g!r}")
        elif not gtin_ok(g):
            errors.append(f"{who}: gtin {g!r}: Prüfziffer stimmt nicht (Tippfehler?)")
    for key in ("url", "bild"):
        if entry.get(key) is not None and not _http(entry.get(key)):
            errors.append(f"{who}: {key} muss eine http(s)-Adresse sein")
    preis = entry.get("preis")
    if preis is not None:
        if not isinstance(preis, dict):
            errors.append(f"{who}: preis als Objekt {{\"je_stueck\": 24.99, \"waehrung\": \"EUR\", \"brutto\": true, "
                          "\"stand\": \"2026-10-21\", \"quelle\": \"https://…\"}")
        else:
            je = number(preis.get("je_stueck"))
            if je is None or je < 0:
                errors.append(f"{who}: preis.je_stueck muss eine Zahl ≥ 0 sein")
            if preis.get("waehrung") is not None and not _WAEHRUNG_RE.match(str(preis.get("waehrung"))):
                errors.append(f"{who}: preis.waehrung als ISO-Code wie \"EUR\"")
            if preis.get("brutto") is not None and not isinstance(preis.get("brutto"), bool):
                errors.append(f"{who}: preis.brutto muss true oder false sein (wie im Shop angegeben)")
            if preis.get("stand") is not None and not _DATE_RE.match(str(preis.get("stand"))):
                errors.append(f"{who}: preis.stand als Datum \"JJJJ-MM-TT\"")
            if preis.get("quelle") is not None and not isinstance(preis.get("quelle"), str):
                errors.append(f"{who}: preis.quelle muss Text sein (Link oder Händler)")
    masse = entry.get("masse")
    if not isinstance(masse, dict):
        errors.append(f"{who}: masse fehlt (Hüllmaße in mm: {{\"l\": 610, \"b\": 410, \"h\": 128}} oder "
                      "{\"d\": 70, \"l\": 1600})")
    else:
        unknown = [k for k in masse if k not in MASSE_KEYS]
        if unknown:
            errors.append(f"{who}: masse kennt nur l, b, h, d (nicht {', '.join(unknown)})")
        m = {}
        for k in MASSE_KEYS:
            if k in masse:
                v = number(masse.get(k))
                if v is None or v <= 0:
                    errors.append(f"{who}: masse.{k} muss eine Zahl > 0 sein (mm)")
                else:
                    m[k] = v
        if not unknown and not (all(k in m for k in ("l", "b", "h")) or "d" in m):
            errors.append(f"{who}: masse braucht l, b und h (Quader) oder d (rund, dazu l bzw. h)")
    if entry.get("gewicht") is not None:
        v = number(entry.get("gewicht"))
        if v is None or v <= 0:
            errors.append(f"{who}: gewicht in g als Zahl > 0")
    mat = entry.get("material")
    if mat is not None:
        if not isinstance(mat, str) or not mat.strip():
            errors.append(f"{who}: material muss die id eines Materials sein")
        elif material_ids is not None and mat not in material_ids:
            errors.append(f"{who}: Material {mat!r} gibt es im Katalog nicht (weglassen oder erst anlegen)")
    errors += _validate_cad(entry.get("cad"), who)
    ersatz = entry.get("ersatz")
    if ersatz is not None:
        if not isinstance(ersatz, dict):
            errors.append(f"{who}: ersatz als Objekt {{\"form\": \"quader\", \"masse\": {{...}}}}")
        else:
            if ersatz.get("form") not in ERSATZ_FORMEN:
                errors.append(f"{who}: ersatz.form muss quader oder zylinder sein")
            if ersatz.get("achse") is not None and ersatz.get("achse") not in ACHSEN:
                errors.append(f"{who}: ersatz.achse muss x, y oder z sein")
            if ersatz.get("form") in ERSATZ_FORMEN and ersatz_huelle(ersatz) is None:
                need = "l, b, h" if ersatz.get("form") == "quader" else "d und l"
                errors.append(f"{who}: ersatz.masse braucht {need} (mm)")
    if entry.get("einbaupunkt") is not None:
        errors += pruefen_punkt(entry.get("einbaupunkt"), f"{who}, einbaupunkt")
    if entry.get("bezugspunkte") is not None:
        errors += pruefen_punkte(entry.get("bezugspunkte"), who)
    if entry.get("tags") is not None and not (isinstance(entry["tags"], list)
                                               and all(isinstance(t, str) for t in entry["tags"])):
        errors.append(f"{who}: tags muss eine Liste von Texten sein")
    st = entry.get("status")
    if st is not None and st not in STATUS:
        errors.append(f"{who}: status {st!r} unbekannt (frei oder vorgeschlagen)")
    return errors


def _validate_cad(cad: Any, who: str) -> list[str]:
    if cad is None:
        return []
    if not isinstance(cad, dict):
        return [f"{who}: cad als Objekt {{\"quelle\": \"download\", \"datei\": \"zukauf/<id>/teil.step\"}}"]
    errors: list[str] = []
    quelle = cad.get("quelle")
    if quelle not in CAD_QUELLEN:
        errors.append(f"{who}: cad.quelle {quelle!r} unbekannt (erlaubt: {', '.join(CAD_QUELLEN)})")
    datei = cad.get("datei")
    if datei is not None:
        if not isinstance(datei, str) or not datei.strip():
            errors.append(f"{who}: cad.datei muss ein Pfad sein (relativ zum Ordner der Katalogdatei)")
        elif datei.startswith("/") or datei.startswith("~"):
            errors.append(f"{who}: cad.datei relativ zum Ordner der Katalogdatei angeben, nicht absolut")
        elif ".." in datei.replace("\\", "/").split("/"):
            errors.append(f"{who}: cad.datei darf den Ordner der Katalogdatei nicht verlassen (kein ..)")
    if quelle == "skript":
        if not isinstance(cad.get("funktion"), str) or not cad["funktion"].strip():
            errors.append(f"{who}: cad.funktion fehlt (Name der Funktion, die die Form liefert)")
        if not cad.get("modul") and not cad.get("datei"):
            errors.append(f"{who}: cad.modul (importierbarer Name) oder cad.datei (Python-Datei) fehlt")
    if quelle == "bd_warehouse" and not (isinstance(cad.get("klasse"), str) and cad["klasse"].strip()):
        errors.append(f"{who}: cad.klasse fehlt (bd_warehouse-Klasse, z. B. \"bearing.SingleRowDeepGrooveBallBearing\")")
    if cad.get("parameter") is not None and not isinstance(cad.get("parameter"), dict):
        errors.append(f"{who}: cad.parameter muss ein Objekt sein")
    if cad.get("stand") is not None and not _DATE_RE.match(str(cad.get("stand"))):
        errors.append(f"{who}: cad.stand als Datum \"JJJJ-MM-TT\"")
    return errors


# ---------------------------------------------------------------------------------------------------------------------
# Zusammensetzen


_SYNONYME = {
    "marke": "hersteller", "brand": "hersteller", "manufacturer": "hersteller", "herstellername": "hersteller",
    "artikelnummer": "mpn", "herstellernummer": "mpn", "art_nr": "mpn", "artnr": "mpn", "partnumber": "mpn",
    "part_number": "mpn", "ean": "gtin", "ean13": "gtin", "gtin13": "gtin", "sku": "shop_nr", "bestellnummer": "shop_nr",
    "link": "url", "image": "bild", "bild_url": "bild", "weight": "gewicht", "dimensions": "masse", "abmessungen": "masse",
    "titel": "name", "title": "name", "bezeichnung": "name",
}


def eingabe_art(eingabe: str | None) -> str | None:
    """"url", "gtin" oder "mpn" für eine Eingabe aus dem Dialog bzw. von Claude."""
    if not isinstance(eingabe, str) or not eingabe.strip():
        return None
    t = eingabe.strip()
    if _http(t):
        return "url"
    if gtin_digits(t) is not None and gtin_ok(t):
        return "gtin"
    return "mpn"


def entwurf(felder: dict[str, Any] | None = None, *, url: str | None = None, mpn: str | None = None,
            gtin: str | None = None, hersteller: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Katalogeintrag aus übergebenen Feldern (Claude, Dialog, Shop-Auswertung). Rückgabe (Eintrag, Hinweise).

    Ergänzt id, art, Ersatzkörper aus den Maßen, Preisstand (heute) und Preisquelle (Link); liest Zahlen aus Text."""
    raw = {(_SYNONYME.get(str(k).lower(), str(k).lower())): copy.deepcopy(v) for k, v in (felder or {}).items()
           if v is not None and v != ""}
    notes: list[str] = []
    e: dict[str, Any] = {k: v for k, v in raw.items() if k in FELDER}
    dropped = [k for k in raw if k not in FELDER and k not in ("preis_text", "waehrung", "brutto", "masse_text",
                                                                 "beschreibung", "quellen", "zu_pruefen")]
    if dropped:
        notes.append(f"Unbekannte Felder ignoriert: {', '.join(sorted(dropped))}")
    if url and not e.get("url"):
        e["url"] = url.strip()
    if mpn and not e.get("mpn"):
        e["mpn"] = str(mpn).strip()
    if gtin and not e.get("gtin"):
        e["gtin"] = str(gtin).strip()
    if hersteller and not e.get("hersteller"):
        e["hersteller"] = str(hersteller).strip()
    if isinstance(e.get("hersteller"), dict):  # schema.org Brand
        e["hersteller"] = e["hersteller"].get("name")
    for key in ("mpn", "shop_nr"):
        if isinstance(e.get(key), (int, float)) and not isinstance(e.get(key), bool):
            e[key] = str(e[key])
    if e.get("gtin") is not None:
        g = gtin_digits(e["gtin"])
        if g is not None:
            e["gtin"] = g
    # Maße
    masse = e.get("masse")
    if isinstance(masse, str):
        parsed = masse_aus_text(masse)
        if parsed:
            e["masse"] = parsed
        else:
            notes.append(f"Maße {masse!r} nicht lesbar: als {{\"l\", \"b\", \"h\"}} in mm angeben")
            e.pop("masse")
    elif isinstance(masse, dict):
        clean = {}
        for k, v in masse.items():
            key = {"laenge": "l", "länge": "l", "length": "l", "tiefe": "l", "depth": "l", "breite": "b",
                   "width": "b", "hoehe": "h", "höhe": "h", "height": "h", "durchmesser": "d", "diameter": "d"}.get(
                str(k).lower(), str(k).lower())
            val = laenge_mm(v) if isinstance(v, str) else number(v)
            clean[key] = round(val, 3) if val is not None else v
        e["masse"] = clean
    if raw.get("masse_text") and not e.get("masse"):
        parsed = masse_aus_text(str(raw["masse_text"]))
        if parsed:
            e["masse"] = parsed
    # Gewicht
    if isinstance(e.get("gewicht"), str):
        g = gewicht_g(e["gewicht"])
        if g is None:
            notes.append(f"Gewicht {e['gewicht']!r} nicht lesbar (in g angeben)")
            e.pop("gewicht")
        else:
            e["gewicht"] = round(g, 2)
    # Preis
    preis = e.get("preis")
    if preis is None and raw.get("preis_text"):
        preis = raw["preis_text"]
    if isinstance(preis, (int, float, str)) and not isinstance(preis, bool):
        betrag, waehrung = preis_aus_text(preis)
        preis = {"je_stueck": betrag} if betrag is not None else None
        if preis is not None and waehrung:
            preis["waehrung"] = waehrung
    if isinstance(preis, dict):
        preis = dict(preis)
        if isinstance(preis.get("je_stueck"), str):
            betrag, waehrung = preis_aus_text(preis["je_stueck"])
            preis["je_stueck"] = betrag
            if waehrung and not preis.get("waehrung"):
                preis["waehrung"] = waehrung
        if raw.get("waehrung") and not preis.get("waehrung"):
            preis["waehrung"] = str(raw["waehrung"]).upper()
        if isinstance(raw.get("brutto"), bool) and "brutto" not in preis:
            preis["brutto"] = raw["brutto"]
        preis.setdefault("waehrung", "EUR")
        preis.setdefault("stand", heute())
        if e.get("url"):
            preis.setdefault("quelle", e["url"])
        if "brutto" not in preis:
            notes.append("Preis: brutto oder netto ist nicht angegeben – im Shop nachsehen und preis.brutto setzen")
        e["preis"] = preis
    elif "preis" in e:
        e.pop("preis")
    # Name und id
    if not e.get("name"):
        bits = [e.get("hersteller"), e.get("mpn")]
        if any(bits):
            e["name"] = " ".join(str(b) for b in bits if b)
    if not e.get("id"):
        e["id"] = make_id(e.get("hersteller"), e.get("mpn"), e.get("gtin"), e.get("name"), e.get("shop_nr"))
    else:
        e["id"] = slug(str(e["id"]))
    e["art"] = "zukaufteil"
    if isinstance(e.get("masse"), dict) and not e.get("ersatz"):
        ers = ersatz_aus_masse(e["masse"])
        if ers:
            e["ersatz"] = ers
    if not e.get("cad"):
        e["cad"] = {"quelle": "keins"}
    return e, notes


def zu_pruefen(entry: dict[str, Any]) -> list[str]:
    """Was Kevin bestätigen sollte, bevor das Teil verbaut wird (fehlende oder unsichere Angaben)."""
    out = []
    if not entry.get("hersteller"):
        out.append("Hersteller")
    if not entry.get("mpn") and not entry.get("shop_nr"):
        out.append("Herstellernummer")
    if not isinstance(entry.get("masse"), dict) or not entry.get("masse"):
        out.append("Maße (Hüllmaß l × b × h in mm)")
    preis = entry.get("preis") if isinstance(entry.get("preis"), dict) else None
    if preis is None:
        out.append("Preis")
    elif "brutto" not in preis:
        out.append("Preis brutto oder netto")
    return out


def cad_art(entry: dict[str, Any]) -> str:
    """Wie das Teil im Modell erscheint: "hersteller" (Datei da), "skript", "vereinfacht" (Ersatzkörper)."""
    cad = entry.get("cad") if isinstance(entry.get("cad"), dict) else {}
    q = cad.get("quelle")
    if q in CAD_MIT_DATEI and cad.get("datei"):
        return "hersteller"
    if q == "skript":
        return "skript"
    if q == "bd_warehouse":
        return "hersteller"
    return "vereinfacht"


def kurz(entry: dict[str, Any]) -> str:
    """Eine Zeile: "ALUTEC Transportroller 05200 (ALUTEC 05200, 610 × 410 × 128 mm, 24,99 € brutto)"."""
    from kevcad_kernel.bom import eur

    bits = []
    if entry.get("hersteller") or entry.get("mpn"):
        bits.append(" ".join(str(x) for x in (entry.get("hersteller"), entry.get("mpn")) if x))
    if entry.get("masse"):
        bits.append(masse_text(entry.get("masse")))
    preis = entry.get("preis") if isinstance(entry.get("preis"), dict) else None
    if preis and number(preis.get("je_stueck")) is not None:
        art = {True: " brutto", False: " netto"}.get(preis.get("brutto"), "")
        bits.append(f"{eur(number(preis['je_stueck']))}{art}")
    return f"{entry.get('name') or entry.get('id')}" + (f" ({', '.join(bits)})" if bits else "")


def status_text(entry: dict[str, Any]) -> str:
    return "wartet auf Kevins Freigabe" if entry.get("status") == VORGESCHLAGEN else "frei"


__all__ = [
    "ZUKAUF_ARTEN", "CAD_QUELLEN", "ERSATZ_FORMEN", "CAD_ENDUNGEN", "VEREINFACHT", "FREI", "VORGESCHLAGEN",
    "gtin_ok", "gtin_digits", "make_id", "slug", "laenge_mm", "gewicht_g", "masse_aus_text", "preis_aus_text",
    "ersatz_aus_masse", "ersatz_huelle", "huelle", "masse_text", "validate_zukauf", "entwurf", "eingabe_art",
    "zu_pruefen", "cad_art", "kurz", "heute", "status_text",
]

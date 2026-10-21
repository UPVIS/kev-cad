"""Normteile erkennen („ISO 4762 M6×20“, „DIN 934 M8“, „Unterlegscheibe DIN 125 M10 A2“) und auf den Katalog bzw.
bd_warehouse umleiten, statt ein Zukaufteil anzulegen (PLAN-PHASE3-ZUKAUF.md, „Normteil? ja → bd_warehouse“).

Leicht: die Prüfung gegen bd_warehouse lädt build123d erst, wenn ein Normteil im Katalog fehlt.
"""

from __future__ import annotations

import re
from typing import Any

# Norm im Text → (Art, bd_warehouse-Klasse, Norm in bd_warehouse, Anzeige)
NORMEN: dict[str, tuple[str, str, str, str]] = {
    "iso4762": ("schraube", "SocketHeadCapScrew", "iso4762", "ISO 4762 (Zylinderschraube mit Innensechskant)"),
    "din912": ("schraube", "SocketHeadCapScrew", "iso4762", "DIN 912 = ISO 4762 (Zylinderschraube mit Innensechskant)"),
    "iso4017": ("schraube", "HexHeadScrew", "iso4017", "ISO 4017 (Sechskantschraube, Gewinde bis Kopf)"),
    "din933": ("schraube", "HexHeadScrew", "iso4017", "DIN 933 = ISO 4017 (Sechskantschraube)"),
    "iso4014": ("schraube", "HexHeadScrew", "iso4014", "ISO 4014 (Sechskantschraube mit Schaft)"),
    "din931": ("schraube", "HexHeadScrew", "iso4014", "DIN 931 = ISO 4014 (Sechskantschraube mit Schaft)"),
    "iso10642": ("schraube", "CounterSunkScrew", "iso10642", "ISO 10642 (Senkschraube mit Innensechskant)"),
    "din7991": ("schraube", "CounterSunkScrew", "iso10642", "DIN 7991 = ISO 10642 (Senkschraube)"),
    "iso7380": ("schraube", "ButtonHeadScrew", "iso7380_1", "ISO 7380 (Flachkopfschraube)"),
    "iso7045": ("schraube", "RaisedCheeseHeadScrew", "iso7045", "ISO 7045 (Linsenkopfschraube)"),
    "din7985": ("schraube", "RaisedCheeseHeadScrew", "iso7045", "DIN 7985 = ISO 7045 (Linsenkopfschraube)"),
    "iso1207": ("schraube", "CheeseHeadScrew", "iso1207", "ISO 1207 (Zylinderschraube mit Schlitz)"),
    "din84": ("schraube", "CheeseHeadScrew", "iso1207", "DIN 84 = ISO 1207 (Zylinderschraube mit Schlitz)"),
    "iso4026": ("schraube", "SetScrew", "iso4026", "ISO 4026 (Gewindestift)"),
    "din913": ("schraube", "SetScrew", "iso4026", "DIN 913 = ISO 4026 (Gewindestift)"),
    "iso4032": ("mutter", "HexNut", "iso4032", "ISO 4032 (Sechskantmutter)"),
    "din934": ("mutter", "HexNut", "iso4032", "DIN 934 = ISO 4032 (Sechskantmutter)"),
    "iso4035": ("mutter", "HexNut", "iso4035", "ISO 4035 (flache Sechskantmutter)"),
    "din439": ("mutter", "HexNut", "iso4035", "DIN 439 = ISO 4035 (flache Sechskantmutter)"),
    "din1587": ("mutter", "DomedCapNut", "din1587", "DIN 1587 (Hutmutter)"),
    "din557": ("mutter", "SquareNut", "din557", "DIN 557 (Vierkantmutter)"),
    "iso7089": ("scheibe", "PlainWasher", "iso7089", "ISO 7089 (Unterlegscheibe)"),
    "din125": ("scheibe", "PlainWasher", "iso7089", "DIN 125 = ISO 7089 (Unterlegscheibe)"),
    "iso7090": ("scheibe", "ChamferedWasher", "iso7090", "ISO 7090 (Unterlegscheibe mit Fase)"),
    "iso7093": ("scheibe", "PlainWasher", "iso7093", "ISO 7093 (große Unterlegscheibe)"),
    "din9021": ("scheibe", "PlainWasher", "iso7093", "DIN 9021 = ISO 7093 (große Unterlegscheibe)"),
    "din6797": ("scheibe", "InternalToothLockWasher", "din6797", "DIN 6797 (Zahnscheibe)"),
}

_NORM_RE = re.compile(r"\b(iso|din|en\s*iso)\s*[-:]?\s*(\d{2,5})(?:\s*[-_]\s*(\d))?\b", re.I)
_GROESSE_RE = re.compile(r"\bm\s*(\d+(?:[.,]\d+)?)(?:\s*([-x×*])\s*(\d+(?:[.,]\d+)?))?(?:\s*[x×*]\s*(\d+(?:[.,]\d+)?))?",
                         re.I)
_A2 = re.compile(r"\b(a2|a2-70|v2a|edelstahl|inox|stainless)\b", re.I)
_A4 = re.compile(r"\b(a4|a4-70|a4-80|v4a)\b", re.I)


def erkennen(text: str | None) -> dict[str, Any] | None:
    """Normteil im Text: {"art", "typ", "norm", "anzeige", "groesse" ("M6"), "laenge" (mm oder None),
    "steigung" (oder None), "werkstoff" ("a2" | "a4" | None)}; sonst None."""
    if not isinstance(text, str) or not text.strip():
        return None
    t = text.replace(" ", " ")
    m = _NORM_RE.search(t)
    if not m:
        return None
    prefix = "iso" if "iso" in m.group(1).lower() else "din"
    key = f"{prefix}{m.group(2)}"
    if key not in NORMEN:
        return None
    art, typ, norm, anzeige = NORMEN[key]
    rest = t[:m.start()] + " " + t[m.end():]
    g = _GROESSE_RE.search(rest)
    if not g:
        return {"art": art, "typ": typ, "norm": norm, "anzeige": anzeige, "groesse": None, "laenge": None,
                "steigung": None, "werkstoff": _werkstoff(t)}
    d = g.group(1).replace(",", ".").rstrip("0").rstrip(".") if "." in g.group(1) or "," in g.group(1) else g.group(1)
    sep, second, third = g.group(2), g.group(3), g.group(4)
    steigung, laenge = None, None
    if third is not None:  # M6x1x20
        steigung, laenge = float(second.replace(",", ".")), float(third.replace(",", "."))
    elif second is not None:
        val = float(second.replace(",", "."))
        if sep == "-" and val < 4:  # M8-1.25 ist eine Steigung, keine Länge
            steigung = val
        else:
            laenge = val
    return {"art": art, "typ": typ, "norm": norm, "anzeige": anzeige, "groesse": f"M{d}", "laenge": laenge,
            "steigung": steigung, "werkstoff": _werkstoff(t)}


def _werkstoff(text: str) -> str | None:
    if _A4.search(text):
        return "a4"
    if _A2.search(text):
        return "a2"
    return None


def umleiten(text: str | None, catalog: Any) -> dict[str, Any] | None:
    """Normteil → Lagerteil im Katalog (bevorzugt) oder Vorschlag für einen Katalogeintrag aus bd_warehouse.

    Rückgabe None (kein Normteil) oder {"normteil": {...erkennen...}, "stock_id": id | None, "treffer": [ids],
    "beispiel": Code für model.py | None, "vorschlag": Lagerteil-Eintrag für stock_define | None, "text": Meldung}."""
    info = erkennen(text)
    if info is None:
        return None
    out: dict[str, Any] = {"normteil": info, "stock_id": None, "treffer": [], "beispiel": None, "vorschlag": None}
    if info["groesse"] is None:
        out["text"] = (f"{info['anzeige']} ist ein Normteil, aber die Größe fehlt (z. B. M6). Normteile kommen aus dem "
                       "Lagerkatalog (stock_search), nicht als Zukaufteil.")
        return out
    rows = [r for r in catalog.items(info["art"]) if str((r.get("masse") or {}).get("norm", "")).lower() == info["norm"]
            and str((r.get("masse") or {}).get("groesse", "")).split("-")[0].upper() == info["groesse"].upper()]
    if info["werkstoff"]:
        want = {"a2": ("edelstahl-a2", "edelstahl"), "a4": ("edelstahl-a4", "v4a")}[info["werkstoff"]]
        pref = [r for r in rows if any(w in str(r.get("material", "")) for w in want)]
        rows = pref or rows
    else:
        pref = [r for r in rows if "a2" not in str(r.get("material", "")) and "a4" not in str(r.get("material", ""))]
        rows = pref or rows
    out["treffer"] = [r["id"] for r in rows]
    name = f"{info['groesse']}" + (f"x{info['laenge']:g}" if info["laenge"] else "")
    if rows:
        best = rows[0]
        out["stock_id"] = best["id"]
        if info["art"] == "schraube":
            laenge = f"{info['laenge']:g}" if info["laenge"] else "20"
            out["beispiel"] = (f"schraube = lager.teil({best['id']!r})\n"
                               f"s1 = schraube.verbauen(laenge={laenge}, name=\"Schrauben/{name} 1\")\n"
                               f"show(s1, \"Schrauben/{name} 1\")")
        else:
            gruppe = "Muttern" if info["art"] == "mutter" else "Scheiben"
            out["beispiel"] = (f"teil = lager.teil({best['id']!r})\nstueck = teil.verbauen(name=\"{gruppe}/{name} 1\")\n"
                               f"show(stueck, \"{gruppe}/{name} 1\")")
        out["text"] = (f"{info['anzeige']} {name} ist ein Normteil und liegt im Lagerkatalog als {best['id']} "
                       f"({best.get('name')}). Kein Zukaufteil und kein Download nötig: in model.py "
                       f"lager.teil({best['id']!r}) verbauen.")
        if info["art"] == "schraube" and not info["laenge"]:
            out["text"] += " Die Länge gibt verbauen(laenge=…) an."
        return out
    groesse = _bd_groesse(info)
    material = "edelstahl-a2" if info["werkstoff"] in ("a2", "a4") else "stahl-8.8-verzinkt"
    if groesse is None:
        out["text"] = (f"{info['anzeige']} {info['groesse']} gibt es weder im Lagerkatalog noch in bd_warehouse. "
                       "Kevin fragen; als Zukaufteil nur, wenn es wirklich kein Normteil ist.")
        return out
    art_wort = {"schraube": "Schraube", "mutter": "Mutter", "scheibe": "Scheibe"}[info["art"]]
    sid = f"{info['art']}-{info['norm'].replace('_', '-')}-{info['groesse'].lower()}" + (
        "-a2" if material == "edelstahl-a2" else "")
    out["vorschlag"] = {"id": sid, "art": info["art"], "name": f"{art_wort} {info['anzeige'].split(' (')[0]} "
                                                               f"{info['groesse']}",
                        "norm": info["anzeige"].split(" (")[0].split(" = ")[-1],
                        "masse": {"typ": info["typ"], "norm": info["norm"], "groesse": groesse},
                        "material": material}
    out["text"] = (f"{info['anzeige']} {name} ist ein Normteil (bd_warehouse {info['typ']} {groesse}), fehlt aber im "
                   f"Lagerkatalog. Auf Kevins Wunsch mit stock_define als Lagerteil vorschlagen (Eintrag in "
                   "\"vorschlag\"), nicht als Zukaufteil.")
    return out


def _bd_groesse(info: dict[str, Any]) -> str | None:
    """Größe in bd_warehouse-Schreibweise ("M6-1") oder None, wenn es sie nicht gibt."""
    try:
        from kevcad_kernel.profiles import fastener_class

        cls = fastener_class(info["art"], info["typ"])
        sizes = list(cls.sizes(info["norm"]))
    except Exception:  # noqa: BLE001 - ohne bd_warehouse keine Prüfung
        return None
    want = info["groesse"].upper()
    hits = [s for s in sizes if s.split("-")[0].upper() == want]
    if info.get("steigung") is not None:
        exact = [s for s in hits if s.split("-")[-1] in (f"{info['steigung']:g}",)]
        hits = exact or hits
    return hits[0] if hits else None

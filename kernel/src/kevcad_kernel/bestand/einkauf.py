"""Einkaufsliste wie im Bereich „Material“ der App (Strang „Material im Kernel angleichen“, 22.10.2026).

Eine Zusammenstellung für MCP ``einkaufsliste()``, den CSV-Export (EXPORT_REQ ``einkaufsliste_csv``), die Zeile in
``run`` und die Einkaufsliste in ``bom``. Vorbild und Vertrag ist ``MaterialDaten`` bzw. ``MaterialText`` in
``app/KevCADCore/Sources/KevCADCore/Material/MaterialDaten.swift``; Gruppen, Begriffe, Spalten, Rundung und Summe sind
dieselben, Text und CSV byteweise gleich dem, was die App teilt (Testdatei ``material`` in fixtures.json, geprüft von
``MaterialKernelGleichTests`` in Swift und ``test_material_einkauf.py`` hier).

Gruppen in fester Reihenfolge:

1. **Lagerware** – ``BOM.einkaufsliste``: Fehlmengen nach Abzug des Projektbestands in Kaufeinheiten (Stange, Platte,
   Stück, Sonderlänge, Zuschnitt), Normteile zum Kaufen eingeschlossen; dahinter (Strang „Bestand Stufe 2“) Filament-
   Spulen, wenn das Projekt Filament führt (``BOM.filament_bestand``): Bedarf aus der Druckvorschau desselben Laufs
   minus Bestand, auf ganze Spulen aufgerundet (``filament_kauf``, in der App ``FilamentBestand.kauf``);
2. **Zukaufteile** – je Stücklistenzeile eines Zukaufteils (auch Kamera, Objektiv, Kamerazubehör) mit Preis und Link
   aus dem Katalog; seit dem Strang „Feinschliff 2“ nach Abzug des Projektbestands (``BOM.zukauf_bestand``): ganz aus
   dem Bestand gedeckte Zeilen entfallen, teilweise gedeckte tragen nur die Fehlmenge (Hinweis „Bestand im Projekt: 1,
   gebraucht: 2“). Ohne ``zukauf_bestand`` (älterer Kernel) die ganze Anzahl;
3. **Normteile abzählen** – ``BOM.stueckgut``: gebraucht, aus Bestand, kaufen (Information zum Abzählen; was zu kaufen
   ist, steht schon unter Lagerware);
4. **Filament für Druckteile** – aus der Druckvorschau desselben Laufs (``summe.material``), sonst aus den Druckteilen
   der Stückliste (Volumen × Dichte).

Summe = Lagerware + Zukaufteile; Normteile zum Abzählen und Filament zählen nicht dazu (wie in der App).

Entscheidung (22.10.2026): Die App rendert Text und CSV weiter selbst, der Kernel rendert dieselben Bytes. Die App teilt
sofort und ohne Kernel (Teilen-Menü, Demo, älterer Kernel) und kennt Dinge, die der Kernel nicht kennt (abgehakte
Zeilen); eine gemeinsame Testdatei hält beide Seiten gleich.
"""

from __future__ import annotations

import math
import time
from typing import Any
from urllib.parse import urlsplit

from kevcad_kernel.appformat import anzahl, csv_feld, csv_zahl, euro, ganzzahl, kompakt, masse_g

LAGERWARE = "Lagerware"
ZUKAUFTEILE = "Zukaufteile"
NORMTEILE = "Normteile abzählen"
FILAMENT = "Filament für Druckteile"
CSV_KOPF = ["Gruppe", "Menge", "Einheit", "Benennung", "Lagerteil", "Preis je (EUR)", "Preis (EUR)", "Preisstand",
            "Bezugsquelle", "Link", "Hinweis"]
# Arten, die die App als Zukauf führt (MaterialGruppe.zukauf)
ZUKAUF_ARTEN = ("zukaufteil", "kamera", "objektiv", "kamerazubehoer")
DRUCKSTAND = {"schaetzung": "Schätzung", "slicer": "Bambu Studio", "gemischt": "Teils Bambu Studio"}


# ---------------------------------------------------------------------------------------------------------------------
# Lesen wie die Decoder der App (JSONValue: lenientString, doubleValue, intValue)


def _text(v: Any) -> str | None:
    """``lenientString``: Text (leer → None), ganze Zahl ohne Komma."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, str):
        return v or None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _int(v: Any) -> int | None:
    f = _num(v)
    return None if f is None else int(f)


def _url(text: Any, schemes: tuple[str, ...], host_noetig: bool) -> str | None:
    """Link wie ``EinkaufsPosition.url`` (http, https, mit Host) bzw. ``ZukaufLink.url`` (auch file)."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or any(c.isspace() for c in t):
        return None
    try:
        teile = urlsplit(t)
    except ValueError:
        return None
    if teile.scheme.lower() not in schemes:
        return None
    if host_noetig and not _host(t):
        return None
    return t


def _host(url: str) -> str | None:
    """Host wie ``URL.host`` (Groß- und Kleinschreibung bleiben)."""
    netloc = urlsplit(url).netloc.rpartition("@")[2]
    if netloc.startswith("["):
        return netloc[1:netloc.find("]")] or None
    return netloc.partition(":")[0] or None


# ---------------------------------------------------------------------------------------------------------------------
# Zusammenstellen


def _position(e: dict[str, Any], index: int) -> dict[str, Any]:
    """Zeile aus ``BOM.einkaufsliste`` wie ``EinkaufsPosition(json:)``."""
    pid = _text(e.get("id")) or f"position-{index + 1}"
    menge = _num(e.get("menge"))
    menge = 1.0 if menge is None else menge
    preis_je = _num(e.get("preis_je"))
    preis = _num(e.get("preis"))
    if preis is None and preis_je is not None:
        preis = preis_je * menge
    roh = e.get("link")
    bq = e.get("bezugsquelle") if isinstance(e.get("bezugsquelle"), dict) else {}
    url = roh if isinstance(roh, str) else (roh.get("url") if isinstance(roh, dict) else None)
    if not isinstance(url, str):
        url = bq.get("url")
    link_name = (_text(e.get("link_text")) or (_text(roh.get("name")) if isinstance(roh, dict) else None)
                 or _text(bq.get("name")))
    return {"gruppe": LAGERWARE, "id": pid, "benennung": _text(e.get("benennung")) or _text(e.get("name")) or pid,
            "menge": menge, "einheit": _text(e.get("einheit")) or "Stück", "preis_je": preis_je, "preis": preis,
            "link": _url(url, ("http", "https"), True), "link_text": link_name,
            "hinweis": _text(e.get("hinweis")), "preis_stand": _text(e.get("preis_stand")) or _text(e.get("stand")),
            "pos": None}


def _ist_zukauf(ln: dict[str, Any]) -> tuple[bool, bool]:
    """(Zukauf in der App, Zeile trägt Zukauf-Angaben wie ``ZukaufBOMInfo``)."""
    art = _text(ln.get("art"))
    stock = _text(ln.get("stock_id"))
    eigen = ln.get("eigenteil") if isinstance(ln.get("eigenteil"), bool) else (
        stock is None and art not in ("druckteil", "zukaufteil"))
    if eigen or art == "druckteil":
        return False, False
    info = art == "zukaufteil" or (art is None and (_text(ln.get("hersteller")) or _text(ln.get("mpn"))) is not None)
    return info or art in ZUKAUF_ARTEN, info


def _zukauf(ln: dict[str, Any], index: int, info: bool) -> dict[str, Any]:
    """Zukaufteil wie in ``MaterialDaten.init``: ganze Anzahl, Preis der Stückliste, Link und Nummern."""
    pos = _int(ln.get("pos"))
    pos = index + 1 if pos is None else pos
    teile = [t for t in ln.get("teile") or [] if isinstance(t, str)]
    stock = _text(ln.get("stock_id"))
    n = _int(ln.get("anzahl"))
    n = max(1, len(teile)) if n is None else n
    link = _url(ln.get("url"), ("http", "https", "file"), False) if info else None
    host = _host(link) if link else None
    titel = " · ".join(x for x in (_text(ln.get("hersteller")), _text(ln.get("mpn"))) if x) if info else ""
    gtin = _text(ln.get("gtin")) if info else None
    hinweis = " · ".join(x for x in (titel or None, f"EAN {gtin}" if gtin else None) if x)
    return {"gruppe": ZUKAUFTEILE, "id": stock or f"pos-{pos}",
            "benennung": _text(ln.get("benennung")) or _text(ln.get("name")) or stock or (teile[0] if teile else "Teil"),
            "menge": float(n), "einheit": "Stück", "preis_je": _num(ln.get("preis_je")), "preis": _num(ln.get("preis")),
            "link": link, "link_text": host.replace("www.", "") if host else None, "hinweis": hinweis or None,
            "preis_stand": _text(ln.get("preis_stand")) if info else None, "pos": pos}


def _zukauf_bestand(bom: dict[str, Any]) -> list[dict[str, Any]] | None:
    """``BOM.zukauf_bestand`` wie ``ZukaufBestand(json:)`` (None: der Kernel gleicht Zukaufteile nicht ab)."""
    roh = bom.get("zukauf_bestand")
    if not isinstance(roh, list):
        return None
    out = []
    for z in roh:
        if not isinstance(z, dict) or _text(z.get("stock_id")) is None:
            continue
        n = _int(z.get("anzahl")) or 0
        aus = _int(z.get("aus_bestand")) or 0
        kaufen = _int(z.get("kaufen"))
        out.append({"stock_id": _text(z.get("stock_id")), "pos": _int(z.get("pos")), "anzahl": n, "aus_bestand": aus,
                    "kaufen": max(0, n - aus) if kaufen is None else kaufen})
    return out


def _bestand_fuer(ln: dict[str, Any], liste: list[dict[str, Any]], benutzt: set[int]) -> dict[str, Any] | None:
    """Abgleich einer Zukauf-Zeile: gleiche ``stock_id`` und ``pos``, sonst der erste freie mit gleicher ``stock_id``."""
    stock = _text(ln.get("stock_id"))
    if stock is None:
        return None
    pos = _int(ln.get("pos"))
    kandidaten = [i for i, z in enumerate(liste) if z["stock_id"] == stock and i not in benutzt]
    for i in kandidaten:
        if pos is not None and liste[i]["pos"] == pos:
            benutzt.add(i)
            return liste[i]
    if kandidaten:
        benutzt.add(kandidaten[0])
        return liste[kandidaten[0]]
    return None


def _mit_bestand(z: dict[str, Any], zb: dict[str, Any] | None) -> dict[str, Any] | None:
    """Zukauf-Zeile nach Abzug des Projektbestands (wie ``MaterialDaten.zukaufMitBestand``): ganz gedeckt → None,
    teilweise → Fehlmenge, Preis anteilig, Hinweis „Bestand im Projekt: 1, gebraucht: 2“."""
    if zb is None or zb["aus_bestand"] <= 0:
        return z
    if zb["kaufen"] <= 0:
        return None
    n = zb["anzahl"]
    kaufen = zb["kaufen"]
    preis = None
    if z["preis_je"] is not None:
        preis = z["preis_je"] * kaufen
    elif z["preis"] is not None and n > 0:
        preis = z["preis"] * kaufen / n
    bestand = f"Bestand im Projekt: {zb['aus_bestand']}, gebraucht: {n}"
    hinweis = f"{z['hinweis']} · {bestand}" if z["hinweis"] else bestand
    return {**z, "menge": float(kaufen), "preis": preis, "hinweis": hinweis}


def _normteil(s: dict[str, Any]) -> dict[str, Any] | None:
    """``StueckgutBedarf(json:)``."""
    sid = _text(s.get("stock_id"))
    if sid is None:
        return None
    n = _int(s.get("anzahl")) or 0
    aus = _int(s.get("aus_bestand")) or 0
    kaufen = _int(s.get("kaufen"))
    return {"stock_id": sid, "benennung": _text(s.get("benennung")) or sid, "masse_text": _text(s.get("masse_text")) or "",
            "laenge": _num(s.get("laenge")), "anzahl": n, "aus_bestand": aus,
            "kaufen": max(0, n - aus) if kaufen is None else kaufen}


def _druckstand(v: Any) -> str:
    """``DruckStand(json:)``: bekannter Wert, sonst Schätzung."""
    s = v.lower() if isinstance(v, str) else ""
    return s if s in DRUCKSTAND else "schaetzung"


def _druckvorschau(dv: Any) -> dict[str, Any] | None:
    if not isinstance(dv, dict):
        return None
    return dv["druckvorschau"] if isinstance(dv.get("druckvorschau"), dict) else dv


def filament(bom: dict[str, Any], druckvorschau: dict[str, Any] | None = None,
             katalog: Any = None) -> list[dict[str, Any]]:
    """Filament je Werkstoff: aus der Druckvorschau desselben Laufs, sonst aus den Druckteilen der Stückliste."""
    dv = _druckvorschau(druckvorschau)
    run = _int(bom.get("run")) or 0
    if dv is not None:
        summe = dv.get("summe") if isinstance(dv.get("summe"), dict) else {}
        mats = [m for m in summe.get("material") or [] if isinstance(m, dict) and _text(m.get("material"))]
        if mats and (_int(dv.get("run")) or 0) == run:
            standard = _druckstand(dv.get("stand"))
            out = []
            for m in mats:
                mid = _text(m.get("material")) or ""
                farben = [f for f in m.get("farben") or [] if isinstance(f, dict)]
                if any(_text(f.get("farbe")) for f in farben):
                    # Strang „Rest Druck“: je Farbe der Platten eine Zeile („PETG gelb“), Teile = Stück auf den Platten
                    name = _text(m.get("name")) or mid.upper()
                    st = _druckstand(m.get("stand")) if "stand" in m else standard
                    for f in farben:
                        farbe = _text(f.get("farbe"))
                        nrs = {_int(x) for x in f.get("platten") or []}
                        teile = sum(len([t for t in p.get("teile") or [] if isinstance(t, dict)])
                                    for p in dv.get("platten") or [] if isinstance(p, dict) and _int(p.get("nr")) in nrs)
                        out.append({"werkstoff": f"{name} {farbe}" if farbe else name, "material": mid,
                                    "farbe": farbe, "teile": teile, "gramm": _num(f.get("g")) or 0.0,
                                    "preis": _num(f.get("kosten")), "preis_stand": _text(m.get("preis_stand")),
                                    "quelle": "druckvorschau", "stand": st})
                    continue
                teile = 0
                for g in dv.get("teile") or []:
                    if not isinstance(g, dict):
                        continue
                    namen = [t for t in g.get("teile") or [] if isinstance(t, str)]
                    if not (_text(g.get("gruppe")) or _text(g.get("name")) or namen):
                        continue  # DruckGruppe(json:) verwirft Gruppen ohne Kennung
                    if _text(g.get("material")) == mid:
                        n = _int(g.get("anzahl"))
                        teile += max(1, len(namen)) if n is None else n
                out.append({"werkstoff": _text(m.get("name")) or mid.upper(), "material": mid, "teile": teile,
                            "gramm": _num(m.get("g")) or 0.0, "preis": _num(m.get("kosten")),
                            "preis_stand": _text(m.get("preis_stand")), "quelle": "druckvorschau",
                            "stand": _druckstand(m.get("stand")) if "stand" in m else standard})
            return out
    out: list[dict[str, Any]] = []
    by: dict[str, dict[str, Any]] = {}
    for ln in bom.get("lines") or []:
        if not isinstance(ln, dict) or _text(ln.get("art")) != "druckteil" or ln.get("eigenteil") is True:
            continue
        if ln.get("gedruckt") is True:  # schon gedruckt (Strang „Feinschliff 2“): kein Filament mehr
            continue
        mat = _text(ln.get("material"))
        w = mat
        if mat is not None and katalog is not None:
            try:
                eintrag = katalog.material(mat)
            except Exception:  # noqa: BLE001 - nur der Anzeigename
                eintrag = None
            w = _text((eintrag or {}).get("name")) or mat
        w = w or "Filament"
        if w not in by:
            by[w] = {"werkstoff": w, "material": None, "teile": 0, "gramm": 0.0, "preis": None, "preis_stand": None,
                     "quelle": "stueckliste", "stand": None}
            out.append(by[w])
        f = by[w]
        teile = [t for t in ln.get("teile") or [] if isinstance(t, str)]
        n = _int(ln.get("anzahl"))
        f["teile"] += max(1, len(teile)) if n is None else n
        f["gramm"] += (_num(ln.get("kg")) or 0.0) * 1000
        if _num(ln.get("preis")) is not None:
            f["preis"] = (f["preis"] or 0.0) + _num(ln.get("preis"))
    return out


def filament_bestand(bom: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """``BOM.filament_bestand`` wie ``FilamentBestand(json:)`` je Material (None: das Projekt führt kein Filament)."""
    roh = bom.get("filament_bestand")
    if not isinstance(roh, list):
        return None
    out: dict[str, dict[str, Any]] = {}
    for f in roh:
        mid = _text(f.get("material")) if isinstance(f, dict) else None
        if mid is None or mid in out:
            continue
        g = _num(f.get("spule_g"))
        out[mid] = {"material": mid, "name": _text(f.get("name")) or mid.upper(), "gramm": _num(f.get("gramm")) or 0.0,
                    "spulen": max(0, _int(f.get("spulen")) or 0), "spule_g": g if g is not None and g > 0 else 1000.0,
                    "preis_je": _num(f.get("preis_je_spule")), "preis_stand": _text(f.get("preis_stand")),
                    # additiv (Strang „Rest Druck“): Spulen je Farbe (None = ohne Farbe)
                    **({"farben": [{"farbe": _text(x.get("farbe")), "gramm": _num(x.get("gramm")) or 0.0,
                                    "spulen": max(0, _int(x.get("spulen")) or 0)}
                                   for x in f.get("farben") or [] if isinstance(x, dict)]} if f.get("farben") else {})}
    return out


def _bestand_je_farbe(fil: list[dict[str, Any]], b: dict[str, Any], mid: str) -> dict[Any, dict[str, Any]]:
    """Bestand, der für jede Filamentzeile eines Materials gilt (Strang „Rest Druck“): eine Zeile mit Farbe nimmt nur
    Spulen dieser Farbe, eine ohne Farbe den ganzen übrigen Bestand des Materials; ohne Farben alles."""
    zeilen = [f for f in fil if f.get("quelle") == "druckvorschau" and f.get("material") == mid]
    if not any(f.get("farbe") for f in zeilen):
        return {f.get("farbe"): {"gramm": b["gramm"], "spulen": b["spulen"], "farbe": None} for f in zeilen}
    out: dict[Any, dict[str, Any]] = {}
    verbraucht_g = 0.0
    verbraucht_n = 0
    for f in zeilen:
        if not f.get("farbe"):
            continue
        x = next((x for x in b.get("farben") or [] if x["farbe"] == f["farbe"]), None)
        g, n = (x["gramm"], x["spulen"]) if x else (0.0, 0)
        out[f["farbe"]] = {"gramm": g, "spulen": n, "farbe": f["farbe"]}
        verbraucht_g += min(g, f["gramm"])
        verbraucht_n += n if g <= f["gramm"] + 1e-6 else 0
    for f in zeilen:
        if not f.get("farbe"):
            out[None] = {"gramm": max(0.0, b["gramm"] - verbraucht_g), "spulen": max(0, b["spulen"] - verbraucht_n),
                         "farbe": None}
    return out


def filament_kauf(fil: list[dict[str, Any]], fb: dict[str, dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Spulen zum Kaufen (Gruppe Lagerware) wie ``FilamentBestand.kauf``: je Werkstoff der Druckvorschau desselben Laufs
    Bedarf minus Bestand, auf ganze Spulen aufgerundet; nichts, wenn der Bestand reicht oder die Zahlen nur aus der
    Stückliste kommen."""
    out: list[dict[str, Any]] = []
    if fb is None:
        return out
    for f in fil:
        if f.get("quelle") != "druckvorschau" or not f.get("material"):
            continue
        b = fb.get(str(f["material"]))
        if b is None:
            continue
        hb = _bestand_je_farbe(fil, b, str(f["material"])).get(f.get("farbe")) or {"gramm": 0.0, "spulen": 0}
        fehl = f["gramm"] - hb["gramm"]
        if fehl <= 1e-6:
            continue
        n = math.ceil(fehl / b["spule_g"] - 1e-9)
        if n <= 0:
            continue
        farbe = f" {f['farbe']}" if f.get("farbe") else ""
        if hb["spulen"] > 0:
            hinweis = (f"Bedarf {masse_g(f['gramm'])}{farbe}, Bestand im Projekt: {masse_g(hb['gramm'])}{farbe} "
                       f"({anzahl(hb['spulen'], 'Spule', 'Spulen')})")
        elif f.get("farbe"):
            hinweis = f"Bedarf {masse_g(f['gramm'])}{farbe}, kein Filament in {f['farbe']} im Bestand des Projekts"
        else:
            hinweis = f"Bedarf {masse_g(f['gramm'])}, kein Filament im Bestand des Projekts"
        preis_je = b["preis_je"]
        out.append({"gruppe": LAGERWARE, "id": str(f["material"]), "benennung": f"Filament {f['werkstoff']}",
                    "menge": float(n), "einheit": f"Spule {kompakt(b['spule_g'], 1)} g", "preis_je": preis_je,
                    "preis": preis_je * n if preis_je is not None else None, "link": None, "link_text": None,
                    "hinweis": hinweis, "preis_stand": b["preis_stand"], "pos": None,
                    "bedarf_g": f["gramm"], "bestand_g": hb["gramm"], **({"farbe": f["farbe"]} if farbe else {})})
    return out


def _summe(werte: list[float | None]) -> float | None:
    w = [x for x in werte if x is not None]
    if not w:
        return None
    s = 0.0
    for x in w:
        s += x
    return s


def zusammenstellen(bom: dict[str, Any], druckvorschau: dict[str, Any] | None = None,
                    katalog: Any = None) -> dict[str, Any]:
    """Die ganze Einkaufsliste wie ``MaterialDaten``: Zeilen je Gruppe, Normteile, Filament und Summen."""
    lager_bom = [_position(e, i) for i, e in enumerate(bom.get("einkaufsliste") or []) if isinstance(e, dict)]
    fil = filament(bom, druckvorschau, katalog)
    fb = filament_bestand(bom)
    fkauf = filament_kauf(fil, fb)
    lager = lager_bom + fkauf
    zukauf = []
    zb_liste = _zukauf_bestand(bom)
    benutzt: set[int] = set()
    aus_bestand = []
    for i, ln in enumerate(bom.get("lines") or []):
        if isinstance(ln, dict):
            ist, info = _ist_zukauf(ln)
            if ist:
                zb = _bestand_fuer(ln, zb_liste, benutzt) if zb_liste is not None else None
                z = _mit_bestand(_zukauf(ln, i, info), zb)
                if zb is not None and zb["aus_bestand"] > 0:
                    aus_bestand.append({"stock_id": zb["stock_id"], "benennung": _zukauf(ln, i, info)["benennung"],
                                        "anzahl": zb["anzahl"], "aus_bestand": zb["aus_bestand"],
                                        "kaufen": zb["kaufen"]})
                if z is not None:
                    zukauf.append(z)
    normteile = [n for n in (_normteil(s) for s in bom.get("stueckgut") or [] if isinstance(s, dict)) if n]
    basis = _num(bom.get("einkauf_summe"))
    if basis is None:
        basis = _summe([z["preis"] for z in lager_bom])
    summe_lager = _summe([basis] + [z["preis"] for z in fkauf])  # wie einkaufLagerSumme der App
    summe_zukauf = _summe([z["preis"] for z in zukauf])
    zeilen = lager + zukauf
    # Filament, das der Bestand deckt (nur Information, wie zukauf_aus_bestand)
    fil_bestand = []
    for f in fil:
        b = (fb or {}).get(str(f.get("material"))) if f.get("quelle") == "druckvorschau" else None
        hb = _bestand_je_farbe(fil, b, str(f.get("material"))).get(f.get("farbe")) if b is not None else None
        if b is not None and hb is not None and hb["gramm"] > 0:
            fil_bestand.append({"material": b["material"], "werkstoff": f["werkstoff"], "bedarf_g": f["gramm"],
                                "bestand_g": hb["gramm"], "spulen": hb["spulen"],
                                "reicht": f["gramm"] - hb["gramm"] <= 1e-6,
                                **({"farbe": f["farbe"]} if f.get("farbe") else {})})
    return {"zeilen": zeilen, "lager": lager, "zukauf": zukauf, "zukauf_aus_bestand": aus_bestand,
            "normteile": normteile, "filament": fil, "filament_kauf": fkauf, "filament_bestand": fb,
            "filament_aus_bestand": fil_bestand,
            "positionen": len(zeilen), "summe_lager": summe_lager, "summe_zukauf": summe_zukauf,
            "summe": _summe([summe_lager, summe_zukauf]),
            "ohne_preis": sum(1 for z in zeilen if z["preis"] is None),
            "mit_bestand": any(k in bom for k in ("einkaufsliste", "bestand_stand", "fehlt", "stueckgut"))}


# ---------------------------------------------------------------------------------------------------------------------
# Texte (wie MaterialText.einkaufText und .einkaufCSV)


def _menge(z: dict[str, Any]) -> str:
    return kompakt(z["menge"], 2)


def normteil_name(s: dict[str, Any]) -> str:
    """Wie die Zeile in „Normteile · abzählen“: Benennung, bei Schrauben ohne Länge im Namen dazu das Maß."""
    if s.get("laenge") is not None and "Länge" not in s["benennung"]:
        return f"{s['benennung']} · {s['masse_text']}"
    return s["benennung"]


def normteil_mengen(s: dict[str, Any]) -> str:
    """„16 gebraucht, 12 aus Bestand, 4 kaufen“."""
    t = f"{ganzzahl(s['anzahl'])} gebraucht, {ganzzahl(s['aus_bestand'])} aus Bestand"
    return t + (f", {ganzzahl(s['kaufen'])} kaufen" if s["kaufen"] > 0 else "")


def filament_quelle(f: dict[str, Any]) -> str:
    """„Druckvorschau, Schätzung“ bzw. „Stückliste, Volumen × Dichte“."""
    if f.get("quelle") == "druckvorschau":
        return f"Druckvorschau, {DRUCKSTAND.get(str(f.get('stand')), 'Schätzung')}"
    return "Stückliste, Volumen × Dichte"


def heute_text() -> str:
    """Stand im Kopf wie die App beim Teilen („22.10.2026“)."""
    return time.strftime("%d.%m.%Y")


def text(e: dict[str, Any], projekt: str | None, stand: str | None = None) -> str:
    """``MaterialText.einkaufText`` ohne abgehakte Zeilen (alle „- [ ] “)."""
    out = ["Einkaufsliste" + (f" {projekt}" if projekt else "") + (f" (Stand {stand})" if stand else "")]
    zeilen = e["zeilen"]
    if not zeilen:
        out.append("Nichts zu kaufen, alles ist im Bestand.")
    for gruppe in (LAGERWARE, ZUKAUFTEILE):
        teil = [z for z in zeilen if z["gruppe"] == gruppe]
        if not teil:
            continue
        out.append("")
        out.append(gruppe)
        for z in teil:
            zeile = f"- [ ] {_menge(z)} × {z['einheit']}: {z['benennung']}"
            if z["preis"] is not None:
                zeile += f", {euro(z['preis'])}"
            if z["link"]:
                zeile += f" ({z['link']})"
            out.append(zeile)
            if z["hinweis"]:
                out.append(f"  {z['hinweis']}")
    summe = _summe([z["preis"] for z in zeilen])
    if summe is not None:
        out.append("")
        out.append(f"Summe: ≈ {euro(summe)}")
    if e["normteile"]:
        out.append("")
        out.append(NORMTEILE)
        for s in e["normteile"]:
            out.append(f"- {normteil_name(s)}: {normteil_mengen(s)}")
    if e["filament"]:
        out.append("")
        out.append(FILAMENT)
        for f in e["filament"]:
            zeile = f"- {f['werkstoff']}: {masse_g(f['gramm'])} für {anzahl(f['teile'], 'Teil', 'Teile')}"
            if f["preis"] is not None:
                zeile += f", {euro(f['preis'])}"
            out.append(zeile + f" ({filament_quelle(f)})")
    return "\n".join(out)


def csv(e: dict[str, Any]) -> str:
    """``MaterialText.einkaufCSV``: Semikolon, deutsche Zahlen, CRLF, mit BOM am Anfang (als UTF-8 schreiben, nicht
    ``utf-8-sig``). Spalte „Gruppe“ zuerst; Summe nach den Kaufzeilen, darunter Normteile und Filament ohne Preis."""
    zeilen = [";".join(CSV_KOPF)]
    for z in e["zeilen"]:
        zeilen.append(";".join(csv_feld(x) for x in [
            z["gruppe"], _menge(z).replace(".", ""), z["einheit"], z["benennung"], z["id"], csv_zahl(z["preis_je"]),
            csv_zahl(z["preis"]), z["preis_stand"] or "", z["link_text"] or "", z["link"] or "", z["hinweis"] or ""]))
    zeilen.append(";".join(["", "", "", "Summe", "", "", csv_zahl(_summe([z["preis"] for z in e["zeilen"]])), "", "",
                            "", ""]))
    for s in e["normteile"]:
        zeilen.append(";".join(csv_feld(x) for x in [
            NORMTEILE, ganzzahl(s["anzahl"]).replace(".", ""), "Stück", normteil_name(s), s["stock_id"], "", "", "", "",
            "", normteil_mengen(s)]))
    for f in e["filament"]:
        hinweis = anzahl(f["teile"], "Teil", "Teile") + (f", {euro(f['preis'])}" if f["preis"] is not None else "")
        zeilen.append(";".join(csv_feld(x) for x in [
            FILAMENT, kompakt(f["gramm"], 1).replace(".", ""), "g", f["werkstoff"], f["material"] or "", "", "",
            f["preis_stand"] or "", "", "", f"{hinweis} ({filament_quelle(f)})"]))
    return "﻿" + "\r\n".join(zeilen) + "\r\n"


def zeile_kurz(e: dict[str, Any]) -> str:
    """Eine Zeile für ``run``: wie die Kennzeile der App („3 Positionen · ≈ 29,37 €“)."""
    n = e["positionen"]
    if not n:
        return "Einkaufsliste: nichts zu kaufen, alles aus dem Bestand des Projekts"
    return (f"Einkaufsliste: {anzahl(n, 'Position', 'Positionen')}"
            + (f", ≈ {euro(e['summe'])}" if e["summe"] is not None else "") + " (Details mit einkaufsliste)")


def dateiname(projekt: str) -> str:
    """``EinkaufslisteFormat.dateiname``: Buchstaben, Ziffern, Leerzeichen, - und _ bleiben, alles andere wird -."""
    name = "".join(c if (c.isalnum() or c in " -_") else "-" for c in projekt).strip(" ")
    return (name or "projekt") + "-einkaufsliste.csv"

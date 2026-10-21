"""Produktdaten aus mitgeliefertem HTML einer Shop-Seite (extruct, BSD-3): JSON-LD, Microdata, RDFa, Open Graph.

Kev CAD lädt Shop-Seiten nie selbst (PLAN-PHASE3-ZUKAUF.md, Z1). Claude liest die Seite mit seinen eigenen Werkzeugen
und reicht das HTML an ``zukauf_html`` weiter; hier werden daraus die Felder eines Zukaufteils (KATALOG.md):

- JSON-LD/Microdata/RDFa ``Product`` (auch in ``@graph`` oder als ``ProductGroup``/``hasVariant``): ``name``,
  ``brand``/``manufacturer``, ``mpn``, ``gtin13``/``gtin``/…, ``sku``, ``image``, ``offers`` (Preis, Währung,
  ``valueAddedTaxIncluded``), ``width``/``height``/``depth``/``weight`` und ``additionalProperty``.
- Open Graph (``og:title``, ``og:image``, ``product:price:amount``, ``product:brand`` …) als Rückfall.
- Maße und Gewicht zusätzlich aus Beschreibung und Eigenschaften („Maße: 61 × 41 × 12,8 cm“).

Ergebnis ``{"felder": {...}, "quellen": [...], "zu_pruefen": [...], "hinweise": [...]}``; ``felder`` geht direkt in
``eintrag.entwurf``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from kevcad_kernel.zukauf.eintrag import gewicht_g, gtin_digits, gtin_ok, laenge_mm, masse_aus_text, preis_aus_text

MAX_HTML = 6_000_000  # Zeichen; größere Seiten werden gekürzt (Skripte am Ende sind selten Produktdaten)
_PRODUCT = ("product", "productgroup", "productmodel", "individualproduct", "somemodel")
_GTIN_KEYS = ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean", "isbn")
_UNIT_CODES = {"mmt": "mm", "cmt": "cm", "mtr": "m", "inh": "in", "dmt": "dm", "ft": "ft", "fot": "ft"}
_WEIGHT_CODES = {"kgm": "kg", "grm": "g", "lbr": "lb", "onz": "oz"}


def _types(item: dict[str, Any]) -> list[str]:
    t = item.get("@type") or item.get("type") or []
    if isinstance(t, str):
        t = [t]
    out = []
    for x in t:
        x = str(x).rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower()
        out.append(x)
    return out


def _first(value: Any) -> Any:
    if isinstance(value, list):
        for v in value:
            if v not in (None, "", [], {}):
                return v
        return None
    return value


def _text(value: Any) -> str | None:
    value = _first(value)
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or value.get("value") or value.get("url") or \
            value.get("contentUrl") or value.get("@id")
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _walk(node: Any):
    """Alle Objekte in JSON-LD (auch verschachtelt und in @graph)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _microdata_flat(item: dict[str, Any]) -> dict[str, Any]:
    """Microdata/RDFa von extruct ({"type", "properties"}) wie JSON-LD darstellen."""
    if "properties" in item and isinstance(item["properties"], dict):
        out = {"@type": item.get("type")}
        for k, v in item["properties"].items():
            out[k] = _microdata_flat(v) if isinstance(v, dict) else ([_microdata_flat(x) if isinstance(x, dict) else x
                                                                       for x in v] if isinstance(v, list) else v)
        return out
    return item


def _quantity(value: Any, *, weight: bool = False) -> float | None:
    """QuantitativeValue {value, unitCode|unitText} oder Text → mm bzw. g."""
    value = _first(value)
    if isinstance(value, dict):
        v = value.get("value") if "value" in value else value.get("@value")
        unit = str(value.get("unitCode") or value.get("unitText") or "").strip().lower()
        unit = (_WEIGHT_CODES if weight else _UNIT_CODES).get(unit, unit)
        if isinstance(v, str):
            v = v.replace(",", ".")
            try:
                v = float(v)
            except ValueError:
                return gewicht_g(str(value.get("value"))) if weight else laenge_mm(str(value.get("value")))
        if isinstance(v, (int, float)):
            return gewicht_g(float(v), unit or "g") if weight else laenge_mm(float(v), unit or "mm")
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        return gewicht_g(value) if weight else laenge_mm(value)
    return None


def _offer(product: dict[str, Any]) -> dict[str, Any]:
    offers = product.get("offers")
    offer = None
    for o in _walk(offers):
        if any(t in ("offer", "aggregateoffer") for t in _types(o)) or "price" in o or "lowPrice" in o:
            offer = o
            break
    if offer is None:
        return {}
    out: dict[str, Any] = {}
    price = offer.get("price", offer.get("lowPrice"))
    spec = None
    for s in _walk(offer.get("priceSpecification")):
        if "price" in s or "valueAddedTaxIncluded" in s:
            spec = s
            break
    if price is None and spec is not None:
        price = spec.get("price")
    betrag, waehrung = preis_aus_text(_first(price) if not isinstance(price, (int, float)) else price)
    if betrag is not None:
        out["je_stueck"] = betrag
    cur = offer.get("priceCurrency") or (spec or {}).get("priceCurrency")
    if cur:
        out["waehrung"] = str(_first(cur)).upper()
    elif waehrung:
        out["waehrung"] = waehrung
    vat = (spec or {}).get("valueAddedTaxIncluded", offer.get("valueAddedTaxIncluded"))
    if isinstance(vat, str):
        vat = {"true": True, "false": False}.get(vat.strip().lower())
    if isinstance(vat, bool):
        out["brutto"] = vat
    if offer.get("url"):
        out["angebot_url"] = _text(offer.get("url"))
    if offer.get("sku") and "sku" not in product:
        out["sku"] = _text(offer.get("sku"))
    return out


def _props(product: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for p in _walk(product.get("additionalProperty")):
        name, value = _text(p.get("name")), p.get("value")
        if name and value is not None:
            unit = p.get("unitText") or p.get("unitCode")
            text = f"{_text(value)} {_UNIT_CODES.get(str(unit).lower(), unit)}" if unit else _text(value)
            out.append((name, text or ""))
    return out


def _from_product(product: dict[str, Any]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    f["name"] = _text(product.get("name"))
    f["hersteller"] = _text(product.get("brand")) or _text(product.get("manufacturer"))
    f["mpn"] = _text(product.get("mpn"))
    for key in _GTIN_KEYS:
        g = _text(product.get(key))
        if g and gtin_digits(g):
            f["gtin"] = gtin_digits(g)
            break
    f["shop_nr"] = _text(product.get("sku")) or _text(product.get("productID"))
    img = _first(product.get("image"))
    f["bild"] = _text(img)
    f["url"] = _text(product.get("url"))
    f["beschreibung"] = _text(product.get("description"))
    offer = _offer(product)
    if offer.get("je_stueck") is not None:
        f["preis"] = {k: offer[k] for k in ("je_stueck", "waehrung", "brutto") if k in offer}
    if offer.get("sku") and not f.get("shop_nr"):
        f["shop_nr"] = offer["sku"]
    masse: dict[str, float] = {}
    for key, schema in (("l", "depth"), ("b", "width"), ("h", "height")):
        v = _quantity(product.get(schema))
        if v:
            masse[key] = round(v, 3)
    for key, schema in (("l", "length"), ("d", "diameter")):
        if key not in masse:
            v = _quantity(product.get(schema))
            if v:
                masse[key] = round(v, 3)
    w = _quantity(product.get("weight"), weight=True)
    if w:
        f["gewicht"] = round(w, 2)
    props = _props(product)
    prop_text = "; ".join(f"{n}: {v}" for n, v in props)
    if prop_text:
        found = masse_aus_text(prop_text)
        for k, v in found.items():
            masse.setdefault(k, v)
        if not f.get("gewicht"):
            m = re.search(r"gewicht[^:]*:\s*([\d.,]+\s*(?:kg|g))", prop_text, re.I)
            if m:
                g = gewicht_g(m.group(1))
                if g:
                    f["gewicht"] = round(g, 2)
        for n, v in props:
            low = n.lower()
            if not f.get("mpn") and any(w in low for w in ("herstellernummer", "artikelnummer des herstellers",
                                                            "hersteller-artikelnummer", "mpn")):
                f["mpn"] = v
            if not f.get("gtin") and any(w in low for w in ("ean", "gtin")) and gtin_digits(v):
                f["gtin"] = gtin_digits(v)
    if masse:
        f["masse"] = masse
    return {k: v for k, v in f.items() if v not in (None, "", {}, [])}


def _score(f: dict[str, Any]) -> int:
    return sum(1 for k in ("name", "hersteller", "mpn", "gtin", "preis", "masse", "bild") if f.get(k))


def auswerten(html: str, url: str | None = None) -> dict[str, Any]:
    """Felder eines Zukaufteils aus dem HTML einer Produktseite (siehe Moduldoku)."""
    import extruct

    hinweise: list[str] = []
    if not isinstance(html, str) or not html.strip():
        return {"felder": {}, "quellen": [], "zu_pruefen": [], "hinweise": ["Kein HTML übergeben"]}
    if len(html) > MAX_HTML:
        html = html[:MAX_HTML]
        hinweise.append(f"HTML auf {MAX_HTML} Zeichen gekürzt")
    try:
        data = extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata", "rdfa", "opengraph"],
                               uniform=False, errors="ignore")
    except Exception as exc:  # noqa: BLE001 - kaputtes HTML: mit dem auskommen, was geht
        data = {}
        hinweise.append(f"HTML nur teilweise lesbar ({type(exc).__name__})")
    data.setdefault("json-ld", [])
    data["json-ld"] += _jsonld_fallback(html, data["json-ld"])
    kandidaten: list[tuple[str, dict[str, Any]]] = []
    for syntax in ("json-ld", "microdata", "rdfa"):
        for top in data.get(syntax) or []:
            nodes = _walk(top) if syntax == "json-ld" else _walk(_microdata_flat(top) if isinstance(top, dict) else top)
            for node in nodes:
                if any(t in _PRODUCT for t in _types(node)):
                    kandidaten.append((syntax, node))
    felder: dict[str, Any] = {}
    quellen: list[str] = []
    best = None
    for syntax, node in kandidaten:
        f = _from_product(node)
        if best is None or _score(f) > _score(best[1]):
            best = (syntax, f)
    if best is not None:
        felder = dict(best[1])
        quellen.append(best[0])
        for syntax, node in kandidaten:  # Lücken aus weiteren Produktangaben füllen (z. B. Varianten)
            f = _from_product(node)
            added = [k for k in f if k not in felder]
            for k in added:
                felder[k] = f[k]
            if added and syntax not in quellen:
                quellen.append(syntax)
    og = _opengraph(data.get("opengraph") or [])
    if og:
        added = [k for k in og if k not in felder]
        for k in added:
            felder[k] = og[k]
        if added:
            quellen.append("opengraph")
    if not felder.get("masse"):
        text = " ".join(str(felder.get(k) or "") for k in ("name", "beschreibung"))
        found = masse_aus_text(text) or masse_aus_text(_sichtbarer_text(html))
        if found:
            felder["masse"] = found
            hinweise.append("Maße aus dem Seitentext gelesen: bitte prüfen")
    if not felder.get("name"):
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        title = re.split(r"\s+[|–-]\s+", title)[0].strip() if title else ""
        if title:
            felder["name"] = title
            hinweise.append("Name aus dem Seitentitel: bitte prüfen")
    if url and not felder.get("url"):
        felder["url"] = url
    if felder.get("gtin") and not gtin_ok(felder["gtin"]):
        hinweise.append(f"EAN {felder['gtin']} hat eine falsche Prüfziffer und wurde weggelassen")
        felder.pop("gtin")
    if isinstance(felder.get("beschreibung"), str) and len(felder["beschreibung"]) > 400:
        felder["beschreibung"] = felder["beschreibung"][:400] + " …"
    zu_pruefen = []
    if not felder.get("hersteller"):
        zu_pruefen.append("Hersteller")
    if not felder.get("mpn"):
        zu_pruefen.append("Herstellernummer (mpn)" + (" – Shop-Nummer gefunden" if felder.get("shop_nr") else ""))
    if not felder.get("masse"):
        zu_pruefen.append("Maße")
    if not felder.get("preis"):
        zu_pruefen.append("Preis")
    elif "brutto" not in felder["preis"]:
        zu_pruefen.append("Preis brutto oder netto")
    if not quellen:
        hinweise.append("Keine strukturierten Produktdaten gefunden (kein JSON-LD, Microdata oder Open Graph): Felder "
                        "selbst von der Seite ablesen und an zukauf_anlegen übergeben")
    return {"felder": felder, "quellen": quellen, "zu_pruefen": zu_pruefen, "hinweise": hinweise}


def _jsonld_fallback(html: str, have: list[Any]) -> list[Any]:
    """JSON-LD-Blöcke, die extruct wegen kleiner Fehler (Kommentare, Steuerzeichen) verwirft."""
    if have:
        return []
    out = []
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        raw = m.group(1).strip()
        raw = re.sub(r"^\s*<!--|-->\s*$", "", raw)
        raw = "".join(ch for ch in raw if ch >= " " or ch in "\n\t")
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _opengraph(items: list[Any]) -> dict[str, Any]:
    props: dict[str, str] = {}
    for item in items:
        for k, v in (item.get("properties") or []) if isinstance(item, dict) else []:
            props.setdefault(str(k).lower(), str(v))
    if not props:
        return {}
    f: dict[str, Any] = {}
    if props.get("og:title"):
        f["name"] = props["og:title"].strip()
    if props.get("og:image"):
        f["bild"] = props["og:image"].strip()
    if props.get("og:url"):
        f["url"] = props["og:url"].strip()
    if props.get("og:description"):
        f["beschreibung"] = props["og:description"].strip()
    brand = props.get("product:brand") or props.get("og:brand")
    if brand:
        f["hersteller"] = brand.strip()
    amount = props.get("product:price:amount") or props.get("og:price:amount")
    if amount:
        betrag, _ = preis_aus_text(amount)
        if betrag is not None:
            f["preis"] = {"je_stueck": betrag}
            cur = props.get("product:price:currency") or props.get("og:price:currency")
            if cur:
                f["preis"]["waehrung"] = cur.strip().upper()
    mpn = props.get("product:mfr_part_no") or props.get("product:retailer_part_no")
    if mpn:
        f["mpn" if "product:mfr_part_no" in props else "shop_nr"] = mpn.strip()
    ean = props.get("product:ean") or props.get("product:gtin") or props.get("product:upc")
    if ean and gtin_digits(ean):
        f["gtin"] = gtin_digits(ean)
    if f.get("beschreibung"):
        found = masse_aus_text(f["beschreibung"])
        if found:
            f["masse"] = found
    return f


def _sichtbarer_text(html: str) -> str:
    """Grober Seitentext ohne Skripte und Stile (für Maße im Fließtext)."""
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&times;", "×", t)
    return re.sub(r"\s+", " ", t)[:200_000]

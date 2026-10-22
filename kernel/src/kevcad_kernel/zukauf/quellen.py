"""CAD-Quellen der Zukaufteile: Deep-Links zu Herstellerportalen und freien Quellen (PLAN-PHASE3-ZUKAUF.md, Z2 und Z3).

Kevin lädt das CAD mit seinem Konto herunter, Kev CAD übernimmt es aus ``~/Downloads`` (``cad_uebernehmen``). Eine
automatische CAD-Quelle gibt es nicht: Die TraceParts-API ist seit dem 22.10.2026 stillgelegt (Kevins Entscheidung,
sie kostet Geld), ebenso ihr Schlüssel in ``secrets.env``. Kev CAD ruft keine Portale selbst ab, es baut nur die Links.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

# Suchadressen der Portale; die Muster sind beim ersten Einsatz im Browser zu prüfen (Portale ändern ihre Pfade)
PORTALE: dict[str, tuple[str, str]] = {
    "3dfindit": ("3Dfindit (CADENAS/PARTcommunity)", "https://www.3dfindit.com/de/?q={q}"),
    "misumi": ("MISUMI", "https://de.misumi-ec.com/vona2/result/?Keyword={q}"),
    "item": ("item", "https://www.item24.com/de-de/search/?q={q}"),
    "igus": ("igus", "https://www.igus.de/search?q={q}"),
    "mcmaster": ("McMaster-Carr", "https://www.mcmaster.com/{q}/"),
    "suche": ("Websuche", "https://duckduckgo.com/?q={q}"),
}
_HERSTELLER_PORTAL = {"misumi": "misumi", "item": "item", "igus": "igus", "mcmaster": "mcmaster",
                      "mcmaster-carr": "mcmaster", "mcmastercarr": "mcmaster"}


def _q(text: str) -> str:
    return urllib.parse.quote_plus(text.strip())


def cad_links(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Links zum Öffnen im Browser (``{titel, url}``): Produktseite, Herstellerportal, 3Dfindit, Websuche."""
    mpn = str(entry.get("mpn") or entry.get("shop_nr") or "").strip()
    hersteller = str(entry.get("hersteller") or "").strip()
    links: list[dict[str, str]] = []
    if entry.get("url"):
        links.append({"titel": "Produktseite (CAD-Download oft dort)", "url": str(entry["url"])})
    key = re.sub(r"[^a-z]", "", hersteller.lower())
    portal = next((p for h, p in _HERSTELLER_PORTAL.items() if key.startswith(h.replace("-", ""))), None)
    query = " ".join(x for x in (hersteller, mpn) if x) or str(entry.get("name") or "")
    if portal and mpn:
        titel, muster = PORTALE[portal]
        links.append({"titel": f"{titel}: CAD zu {mpn}", "url": muster.format(q=_q(mpn) if portal != "mcmaster"
                                                                             else urllib.parse.quote(mpn))})
    if query:
        titel, muster = PORTALE["3dfindit"]
        links.append({"titel": f"{titel}: {query}", "url": muster.format(q=_q(query))})
        titel, muster = PORTALE["suche"]
        links.append({"titel": f"{titel}: {query} STEP", "url": muster.format(q=_q(f"{query} STEP CAD download"))})
    seen: set[str] = set()
    out = []
    for link in links:
        if link["url"] not in seen:
            seen.add(link["url"])
            out.append(link)
    return out

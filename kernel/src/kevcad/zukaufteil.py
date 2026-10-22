"""Zukaufteile in model.py: ``lager.zukauf(...)`` (Vertrag in KATALOG.md, Abschnitt „Zukaufteil (Phase 3)“).

```python
wagen = lager.zukauf("alutec-05200")                  # nach id, sonst lager.zukauf(mpn="05200", hersteller="ALUTEC")
rw = wagen.verbauen("Rollwagen")                      # Part am Einbaupunkt: Hersteller-CAD, Skript oder Ersatzkörper
show(Pos(0, 0, 0) * rw, "Rollwagen")                  # gleicher Name wie in verbauen
oben = wagen.bezugspunkt("oben")                      # Location im System des verbauten Teils
show(Pos(0, 0, 0) * oben * ball, "Ball")
```

Geometrie je nach ``cad`` im Katalog:

- ``hersteller`` / ``download`` (ältere Einträge auch ``traceparts``) mit ``datei``: Hersteller-STEP (Namen, Farben, Baugruppe), Einheit und
  Achsen gegen ``masse`` geprüft und korrigiert, zwischengespeichert in ``<projekt>/zukauf/<id>/``.
- ``skript``: ``funktion`` aus ``modul`` bzw. ``datei`` (Python neben der Katalogdatei); ``verbauen(name, **kwargs)``
  reicht Schlüsselwörter an die Funktion weiter.
- ``bd_warehouse``: ``klasse`` mit ``parameter``.
- sonst: Ersatzkörper (Quader oder Zylinder aus ``ersatz`` bzw. ``masse``); im Teilebaum mit „(vereinfacht)“, in der
  App halbtransparent.

Der Einbaupunkt (Standard: Mitte der Unterseite, Z oben) wird zum Ursprung des verbauten Teils. Gebaut wird nur, was
freigegeben ist: Von Claude vorgeschlagene Zukaufteile warten auf Kevins Freigabe im Lagerkatalog.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from kevcad.lager import WARTET, LagerError, _register, _warn, katalog, released_material
from kevcad_kernel.catalog import ZUKAUF_ARTEN, Catalog, is_free, number
from kevcad_kernel.zukauf import eintrag as ze

__all__ = ["Zukaufteil", "finden"]


def _norm(text: Any) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


class Zukaufteil:
    """Ein Zukaufteil aus dem Katalog. ``verbauen(name)`` liefert die Form, ``bezugspunkt(name)`` eine Location."""

    def __init__(self, entry: dict[str, Any], cat: Catalog) -> None:
        self.eintrag = entry
        self.id: str = entry["id"]
        self.art: str = entry.get("art", "zukaufteil")
        self.name: str = entry.get("name") or entry["id"]
        self.hersteller: str | None = entry.get("hersteller")
        self.mpn: str | None = entry.get("mpn")
        self.gtin: str | None = entry.get("gtin")
        self.masse: dict[str, Any] = dict(entry.get("masse") or {})
        self.preis: dict[str, Any] = dict(entry.get("preis") or {})
        self.ebene: str = entry.get("ebene", "projekt")
        self._cat = cat

    def __repr__(self) -> str:
        wait = "" if is_free(self.eintrag) else ", vorgeschlagen"
        return f"<Zukaufteil {self.id!r}: {ze.kurz(self.eintrag)}, CAD {self.cad}, {self.ebene}{wait}>"

    @property
    def cad(self) -> str:
        """"hersteller", "skript" oder "vereinfacht" (laut Katalog; fehlt die Datei, wird es beim Verbauen
        vereinfacht)."""
        return ze.cad_art(self.eintrag)

    @property
    def bezugspunkte(self) -> list[str]:
        return sorted((self.eintrag.get("bezugspunkte") or {}).keys())

    # -- Pfade ---------------------------------------------------------------------------------------------------------

    def _base_dir(self) -> Path:
        src = self._cat.source("teil", self.id)
        if src is not None:
            return Path(src[1]).parent
        project = self._cat.dirs.get("project")
        return Path(project) if project else Path.cwd()

    def _cache_dir(self) -> Path:
        project = self._cat.dirs.get("project")
        return (Path(project) if project else self._base_dir()) / "zukauf" / self.id

    # -- Bezugspunkte --------------------------------------------------------------------------------------------------

    def bezugspunkt(self, name: str):
        """Location des benannten Bezugspunkts im System des verbauten Teils (wie ``verbauen`` es liefert)."""
        from kevcad_kernel.bezugspunkte import bezugspunkt

        try:
            return bezugspunkt(self.eintrag.get("bezugspunkte"), name, who=self.name)
        except ValueError as exc:
            raise LagerError(str(exc)) from exc

    # -- Verbauen ------------------------------------------------------------------------------------------------------

    def verbauen(self, name: str | None = None, **kwargs: Any):
        """build123d-Form mit label (= name), Farbe und Stücklistenzeile; Schlüsselwörter gehen bei ``cad.quelle``
        "skript" an die Funktion. Siehe Moduldoku."""
        from build123d import Color

        from kevcad_kernel.baum import markieren, transformieren
        from kevcad_kernel.bom import Piece
        from kevcad_kernel.zukauf import cad as zc

        label = str(name).strip().strip("/").replace("#", "-") if name is not None and str(name).strip() else self.name
        if not is_free(self.eintrag):
            raise LagerError(f"Zukaufteil {self.id!r} ist vorgeschlagen und {WARTET}.")
        mat = None
        if self.eintrag.get("material"):
            mat = released_material(self.eintrag["material"], cat=self._cat)
        cad = self.eintrag.get("cad") if isinstance(self.eintrag.get("cad"), dict) else {}
        quelle = cad.get("quelle") or "keins"
        art = "vereinfacht"
        hinweise: list[str] = []
        grob = False
        soll = ze.huelle(self.eintrag)
        if kwargs and quelle != "skript":
            raise LagerError(f"{self.name}: verbauen() nimmt nur bei Skript-Geometrie weitere Angaben "
                             f"({', '.join(kwargs)})")
        try:
            if quelle in ze.CAD_MIT_DATEI and cad.get("datei"):
                path = (self._base_dir() / str(cad["datei"])).resolve()
                if not path.is_file():
                    _warn(f"{self.name}: CAD-Datei {cad['datei']} fehlt – Ersatzkörper (vereinfacht); mit cad_suchen "
                          "und cad_uebernehmen neu holen")
                    shape = zc.ersatzkoerper(self.eintrag)
                else:
                    achsen = not isinstance(self.eintrag.get("einbaupunkt"), dict) or \
                        (self.eintrag["einbaupunkt"].get("richtung") in (None, [0, 0, 1]))
                    shape, info = zc.importieren(path, self._cache_dir(), soll, name=self.name, achsen_pruefen=achsen)
                    art, grob = "hersteller", bool(info.get("grob"))
                    hinweise += info.get("hinweise") or []
            elif quelle == "skript":
                shape, punkte = zc.skript_form(self.eintrag, self._base_dir(), kwargs)
                art = "skript"
                if punkte and not self.eintrag.get("bezugspunkte"):
                    hinweise.append("Bezugspunkte der Skript-Funktion stehen nicht im Katalog (bezugspunkte)")
            elif quelle == "bd_warehouse":
                shape, art = zc.bd_warehouse_form(self.eintrag), "hersteller"
            else:
                shape = zc.ersatzkoerper(self.eintrag)
        except zc.CadFehler as exc:
            raise LagerError(str(exc)) from exc
        if art in ("skript", "hersteller") and soll is not None and quelle not in ze.CAD_MIT_DATEI:
            p = zc.pruefen(zc.huellmass(shape), soll, achsen_pruefen=False)
            if p.abweichung > zc.TOL_OK:
                _warn(f"{self.name}: Hüllmaß {zc._dims(p.modell)} weicht bis {round(p.abweichung * 100):d} % von den "
                      f"Katalogmaßen {zc._dims(soll)} ab")
        for h in hinweise:
            _warn(f"{self.name}: {h}")
        shape = transformieren(shape, location=zc.einbau_lage(shape, self.eintrag))
        shape.label = label
        try:
            shape.material = None
        except Exception:  # noqa: BLE001
            pass
        if art == "vereinfacht" or (shape.color is None and not list(shape.children or ())):
            farbe = (mat or {}).get("farbe") or zc.ERSATZ_FARBE
            try:
                shape.color = Color(farbe)
            except Exception:  # noqa: BLE001
                pass
        if grob:
            markieren(shape, "kevcad_grob", True)
        try:
            shape.zukauf_id = self.id  # nur die id: Formen werden bei Pos(...) * form tief kopiert
            shape.lager_name = label
        except Exception:  # noqa: BLE001
            pass
        volume = float(shape.volume) if shape.solids() else 0.0
        gewicht = number(self.eintrag.get("gewicht"))
        dichte = number((mat or {}).get("dichte"))
        kg = gewicht / 1000.0 if gewicht is not None else (volume * dichte / 1e6 if dichte and volume else None)
        preis = self.preis
        info = {"id": self.id, "hersteller": self.hersteller, "mpn": self.mpn, "gtin": self.gtin,
                "url": self.eintrag.get("url"), "bild": self.eintrag.get("bild"), "cad": art,
                "cad_quelle": quelle if art != "vereinfacht" else ("keins" if quelle in ("keins", None) else quelle),
                "masse_text": ze.masse_text(self.masse) if self.masse else "",
                "preis_brutto": preis.get("brutto"), "waehrung": preis.get("waehrung")}
        piece = Piece(seq=0, name=label, stock_id=self.id, art="zukaufteil", benennung=self.name,
                      norm=None, material_id=(mat or {}).get("id"), material_name=(mat or {}).get("name"),
                      ebene=self.ebene, kg=kg, preis=number(preis.get("je_stueck")), preis_stand=preis.get("stand"),
                      preis_quelle=preis.get("quelle"), volume=volume, zukauf=info)
        _register(piece, shape)
        return shape


# ---------------------------------------------------------------------------------------------------------------------
# Finden


def finden(auswahl: str | None = None, /, *, mpn: str | None = None, hersteller: str | None = None,
           gtin: str | None = None) -> Zukaufteil:
    """Zukaufteil nach id, nach Herstellernummer (mit Hersteller) oder nach GTIN; sonst LagerError mit Vorschlägen."""
    cat = katalog()
    rows = [r for r in cat.items() if r.get("art") in ZUKAUF_ARTEN]
    if auswahl is not None:
        key = str(auswahl).strip()
        it = cat.item(key)
        if it is not None and it.get("art") in ZUKAUF_ARTEN:
            return _released(it, cat)
        if it is not None:
            raise LagerError(f"{key!r} ist ein Lagerteil ({it.get('name')}), kein Zukaufteil: lager.teil({key!r})")
        from kevcad_kernel.zukauf.normteile import umleiten

        red = umleiten(key, cat)
        if red is not None:
            raise LagerError(red["text"] + (f"\n{red['beispiel']}" if red.get("beispiel") else ""))
        if ze.gtin_digits(key) and gtin is None:
            gtin = key
        elif mpn is None:
            mpn = key
    hits = rows
    if gtin is not None:
        g = ze.gtin_digits(gtin) or str(gtin)
        hits = [r for r in rows if ze.gtin_digits(r.get("gtin")) == g]
    elif mpn is not None:
        hits = [r for r in rows if _norm(r.get("mpn")) == _norm(mpn) or _norm(r.get("shop_nr")) == _norm(mpn)]
        if hersteller is not None:
            hits = [r for r in hits if _norm(r.get("hersteller")) == _norm(hersteller)]
    elif hersteller is not None:
        hits = [r for r in rows if _norm(r.get("hersteller")) == _norm(hersteller)]
    else:
        raise LagerError("lager.zukauf braucht eine id, mpn= (mit hersteller=) oder gtin=, z. B. "
                         "lager.zukauf(\"alutec-05200\")")
    if len(hits) == 1:
        return _released(hits[0], cat)
    want = auswahl or mpn or gtin or hersteller
    if len(hits) > 1:
        listing = "; ".join(f"{h['id']} ({h.get('hersteller')} {h.get('mpn')})" for h in hits[:6])
        raise LagerError(f"{len(hits)} Zukaufteile passen zu {want!r}: {listing}. Mit id oder hersteller= eindeutig "
                         "machen.")
    ids = [r["id"] for r in rows]
    close = difflib.get_close_matches(str(want), ids, n=3, cutoff=0.5)
    raise LagerError(f"Zukaufteil {want!r} gibt es nicht im Katalog."
                     + (f" Meinten Sie: {', '.join(repr(c) for c in close)}?" if close else "")
                     + " Neue Zukaufteile legt zukauf_anlegen an (als Vorschlag für Kevin); zukauf_liste zeigt alle.")


def _released(entry: dict[str, Any], cat: Catalog) -> Zukaufteil:
    if not is_free(entry):
        raise LagerError(f"Zukaufteil {entry['id']!r} ist vorgeschlagen und {WARTET}.")
    return Zukaufteil(entry, cat)

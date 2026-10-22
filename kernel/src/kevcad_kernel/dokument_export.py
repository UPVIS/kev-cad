"""Dokumente exportieren (Phase 6, Strang P6-A2; DOKUMENTE.md, Anhang „Export“): Mischklasse für ``KernelRuntime``.

Das PDF baut die App (eine Zeichenfunktion für Bildschirm, PDF und Druck). Der Kernel prüft nur die Bausteine,
bestimmt den Zielpfad, schickt ``DOC_EXPORT_REQ`` und wartet auf ``DOC_EXPORT_RES``.

- MCP (KernelService, additiv): ``dokument_export(bausteine, ziel=None, drucken=False)``.
- ``drucken`` öffnet in der App den macOS-Druckdialog (je Blattformat ein Auftrag); nur auf Kevins ausdrücklichen
  Wunsch, so steht es in der Werkzeugbeschreibung.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from kevcad_kernel.protocol import DOC_EXPORT_BAUSTEINE, doc_export_req

# Reihenfolge = Standardreihenfolge im Export-Dialog der App
BAUSTEINE: tuple[str, ...] = DOC_EXPORT_BAUSTEINE
BAUSTEIN_TITEL: dict[str, str] = {"deckblatt": "Deckblatt", "stueckliste": "Stückliste", "teileliste": "Teileliste",
                                  "einkaufsliste": "Einkaufsliste", "zuschnitt": "Zuschnitt",
                                  "zeichnungen": "Zeichnungen", "bauplan": "Bauplan"}
# Andere Schreibweisen, die der Agent oder Kevin benutzen könnten
_ALIAS: dict[str, str] = {"titel": "deckblatt", "titelblatt": "deckblatt", "deckseite": "deckblatt",
                          "bom": "stueckliste", "stückliste": "stueckliste", "teile": "teileliste",
                          "einkauf": "einkaufsliste", "einkaufliste": "einkaufsliste", "kaufen": "einkaufsliste",
                          "schnitt": "zuschnitt", "zuschnittliste": "zuschnitt", "zeichnung": "zeichnungen",
                          "blaetter": "zeichnungen", "blätter": "zeichnungen", "anleitung": "bauplan",
                          "bauanleitung": "bauplan", "montage": "bauplan"}
FORMATE = ("A4", "A3")
AUSRICHTUNGEN = ("hoch", "quer")
APP_NOT_CONNECTED = "App nicht verbunden"


class BausteinFehler(ValueError):
    pass


def baustein_art(name: Any) -> str:
    s = str(name or "").strip().lower()
    s = _ALIAS.get(s, s)
    if s not in BAUSTEINE:
        raise BausteinFehler(f"Baustein {name!r} unbekannt (erlaubt: {', '.join(BAUSTEINE)}, oder 'alle')")
    return s


def normalisiere(bausteine: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bausteine wie im Export-Dialog: Liste aus Namen oder Objekten ``{art, spalten?, auswahl?}``. ``None``, leer oder
    ``"alle"``: alle in der Standardreihenfolge. ``"vorlage:<Name>"`` bzw. ``{"vorlage": Name}`` wählt eine
    gespeicherte Vorlage der App; ``{"format": "A3", "ausrichtung": "quer"}`` setzt das Format der Berichtsseiten.
    Liefert (Bausteine, Optionen)."""
    optionen: dict[str, Any] = {"format": None, "ausrichtung": None, "vorlage": None}
    if bausteine is None or bausteine == "" or bausteine == []:
        return [{"art": a} for a in BAUSTEINE], optionen
    if isinstance(bausteine, (str, dict)):
        bausteine = [bausteine]
    if not isinstance(bausteine, (list, tuple)):
        raise BausteinFehler("bausteine: Liste aus Namen oder Objekten {art, spalten, auswahl}")
    out: list[dict[str, Any]] = []
    for b in bausteine:
        if isinstance(b, str):
            s = b.strip()
            if s.lower() in ("alle", "all", "*"):
                out += [{"art": a} for a in BAUSTEINE if a not in {x["art"] for x in out}]
                continue
            if s.lower().startswith("vorlage:"):
                optionen["vorlage"] = s.split(":", 1)[1].strip() or None
                continue
            b = {"art": s}
        if not isinstance(b, dict):
            raise BausteinFehler(f"Baustein {b!r}: Name oder Objekt erwartet")
        b = dict(b)
        for key in ("format", "ausrichtung", "vorlage"):
            if key in b and "art" not in b:
                optionen[key] = b.pop(key)
        if not b:
            continue
        art = baustein_art(b.get("art"))
        eintrag: dict[str, Any] = {"art": art}
        if b.get("spalten") is not None:
            if not isinstance(b["spalten"], (list, tuple)) or not all(isinstance(x, str) for x in b["spalten"]):
                raise BausteinFehler(f"{art}: spalten als Liste von Namen")
            eintrag["spalten"] = list(b["spalten"])
        if b.get("auswahl") is not None:
            if art != "zeichnungen":
                raise BausteinFehler(f"auswahl gibt es nur für zeichnungen (Blatt-ids), nicht für {art}")
            eintrag["auswahl"] = [str(x) for x in b["auswahl"]]
        if any(x["art"] == art for x in out):
            raise BausteinFehler(f"Baustein {art} doppelt")
        out.append(eintrag)
    fmt = optionen.get("format")
    if fmt is not None:
        f = str(fmt).upper()
        if f not in FORMATE:
            raise BausteinFehler(f"format {fmt!r}: A4 oder A3")
        optionen["format"] = f
    aus = optionen.get("ausrichtung")
    if aus is not None:
        a = str(aus).lower()
        if a not in AUSRICHTUNGEN:
            raise BausteinFehler(f"ausrichtung {aus!r}: hoch oder quer")
        optionen["ausrichtung"] = a
    if not out and optionen.get("vorlage") is None:
        raise BausteinFehler("Keine Bausteine angegeben")
    return out, optionen


class DokumentExportDienst:
    """Mischklasse für KernelRuntime (nutzt ``_project``, ``_link``, ``_request``)."""

    def _export_ziel(self, ziel: str | None) -> Path:
        from kevcad_kernel.export import safe_name

        proj = self._project  # type: ignore[attr-defined]
        if ziel is None or not str(ziel).strip():
            return (proj.output_dir / f"{safe_name(proj.name)}-dokumente.pdf").resolve()
        p = Path(str(ziel)).expanduser()
        if not p.is_absolute():
            p = proj.output_dir / p
        if p.suffix.lower() != ".pdf":
            p = p.with_suffix(".pdf") if p.suffix == "" else p.with_name(p.name + ".pdf")
        return p.resolve()

    def dokument_export(self, bausteine: Any = None, ziel: str | None = None, drucken: bool = False,
                        timeout_s: float = 600.0) -> dict[str, Any]:
        """Lässt die App ein PDF aus den Bausteinen bauen (DOC_EXPORT_REQ → DOC_EXPORT_RES). ``drucken`` öffnet
        zusätzlich den Druckdialog. {"ok", "pfad", "seiten", "bausteine", "formate", "ms", "gedruckt", "hinweise"}"""
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        try:
            liste, optionen = normalisiere(bausteine)
        except BausteinFehler as exc:
            return {"ok": False, "error": str(exc)}
        link = getattr(self, "_link", None)
        if link is None or not link.connected:
            return {"ok": False, "error": APP_NOT_CONNECTED}
        pfad: Path | None = None
        if ziel is not None or not drucken:
            pfad = self._export_ziel(ziel)
            try:
                pfad.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return {"ok": False, "error": f"Ordner {pfad.parent} nicht anlegbar: {exc}"}
        req = doc_export_req(liste, ziel=str(pfad) if pfad else None, drucken=drucken, format=optionen.get("format"),
                             ausrichtung=optionen.get("ausrichtung"), vorlage=optionen.get("vorlage"))
        req.pop("seq", None)
        t0 = time.perf_counter()
        reply, _, error = self._request(req, timeout_s)  # type: ignore[attr-defined]
        if error:
            return {"ok": False, "error": error}
        if not reply.get("ok", False):
            return {"ok": False, "error": reply.get("fehler") or reply.get("message") or "PDF nicht erstellt",
                    "bausteine": reply.get("bausteine")}
        return {"ok": True, "pfad": reply.get("pfad") or (str(pfad) if pfad else None),
                "seiten": int(reply.get("seiten") or 0), "bausteine": reply.get("bausteine") or [],
                "formate": reply.get("formate") or {}, "gedruckt": reply.get("gedruckt"),
                "hinweise": list(reply.get("hinweise") or []),
                "ms": reply.get("ms") or int((time.perf_counter() - t0) * 1000), "phasen": reply.get("phasen") or {},
                "angefragt": [b["art"] for b in liste], "vorlage": optionen.get("vorlage")}

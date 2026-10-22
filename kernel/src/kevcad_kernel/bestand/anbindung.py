"""Bestand in der Kernel-Laufzeit: Mixin für ``KernelRuntime`` (runtime.py).

- Nach jedem Lauf erweitert ``_bestand_bom`` die Stückliste um Zuschnitt mit Bestand und Einkaufsliste; die Basis aus
  dem Rechenprozess bleibt gespeichert, damit Änderungen am Bestand ohne neuen Lauf neu geplant werden.
- ``BESTAND`` geht nach dem Verbinden, nach jedem Projektwechsel und nach jeder Änderung an die App (auch wenn
  bestand.json von außen geändert wurde, Prüfung im Beobachtungsfaden).
- Anfragen der App: ``BESTAND_REQ``, ``BESTAND_SAVE``, ``GEBAUT_REQ``, ``BUCHUNG_RUECKGAENGIG`` (ACK, danach BESTAND
  und BOM).
- MCP-Fassade (service.py): ``bestand_liste``, ``bestand_eintragen``, ``einkaufsliste``, ``gebaut_buchen``,
  ``buchung_rueckgaengig``; seit Strang „Bestand Stufe 2“ auch Filament (``bestand_eintragen`` mit ``material``,
  ``gramm``, ``spule`` …) und ``gedruckt_buchen`` (Filament der Druckvorschau abbuchen). „Gebaut“ bucht das Filament
  der noch nicht als gedruckt gebuchten Platten mit ab.

Erwartet von der Laufzeit: ``_lock``, ``_project``, ``_bom``, ``catalog``, ``_send_app``, ``_log``.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import threading
import time
from typing import Any

from kevcad_kernel.catalog import STANGENWARE, STUECKGUT, number

from .datei import (
    MELDUNG_BUCHUNGEN,
    BestandDatei,
    BestandError,
    aenderungen_text,
    fuehrt_filament,
    gramm_text,
    heute,
    pruefe_einstellungen,
    pruefe_posten,
    pruefe_spule,
    spulen,
    zahl,
)
from . import einkauf as ek
from . import filament as fl
from .planung import Verbrauch, gebaut_aenderungen, plane
from .text import bestand_text

FILAMENT_PARAMETER = ("material", "gramm", "gramm_voll", "spule", "farbe", "hersteller", "anzahl", "kennung",
                      "spulen_entfernen")

ANFRAGEN = ("BESTAND_REQ", "BESTAND_SAVE", "GEBAUT_REQ", "BUCHUNG_RUECKGAENGIG")
KEIN_PROJEKT = "Kein Projekt offen: Bestand gibt es je Projekt (bestand.json im Projektordner)."


class BestandAnbindung:
    """Bestand des offenen Projekts für die Laufzeit (siehe Moduldoku)."""

    def _bestand_init(self) -> None:
        self._bom_basis: dict[str, Any] | None = None  # Stückliste des Laufs ohne Bestand
        self._bestand_verbrauch: list[Verbrauch] = []
        self._bestand_statistik: list[dict[str, Any]] = []
        self._bestand_sig: tuple | None = None
        self._bestand_fil_gesendet: dict[str, Any] | None = None  # gebaut_filament der letzten BESTAND-Nachricht
        self._bestand_lock = threading.RLock()
        # Laufnummern beginnen nach jedem Kernelstart neu: die Sitzung gehört zur Sperre gegen doppeltes „Gebaut“
        self._bestand_sitzung = f"{time.strftime('%Y%m%d%H%M%S')}-{os.getpid()}"

    # -- Datei ---------------------------------------------------------------------------------------------------------

    def _bestand_datei(self) -> BestandDatei | None:
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return None
        return BestandDatei.fuer_projekt(proj.path, proj.name, katalog=self.catalog.item)  # type: ignore[attr-defined]

    def _bestand_lesen(self) -> tuple[BestandDatei | None, dict[str, Any] | None, str | None]:
        d = self._bestand_datei()
        if d is None:
            return None, None, None
        try:
            return d, d.lesen(), None
        except BestandError as exc:
            return d, None, str(exc)

    def _bestand_nachricht(self, reply_to: str | None = None) -> dict[str, Any]:
        """Nachricht BESTAND (BESTAND.md): Inhalt der Projektdatei, letzte Buchungen, Stand."""
        from kevcad_kernel.protocol import pack_bestand

        d, data, fehler = self._bestand_lesen()
        if d is not None:
            with self._bestand_lock:
                self._bestand_sig = d.signatur()
        fil = self._gebaut_filament(d, data)
        self._bestand_fil_gesendet = fil
        msg = pack_bestand(bestand=data, buchungen=d.buchungen(MELDUNG_BUCHUNGEN) if d is not None else [],
                           stand=d.stand() if d is not None else None, datei=str(d.pfad) if d is not None else None,
                           fehler=fehler, reply_to=reply_to, gebaut_filament=fil)
        msg.pop("seq", None)
        return msg

    def _gebaut_filament(self, d: BestandDatei | None, data: dict[str, Any] | None) -> dict[str, Any] | None:
        """BESTAND ``gebaut_filament`` (Strang „Bestand Stufe 2“): was „Gebaut“ jetzt vom Filament abbuchen würde;
        None, wenn das Projekt kein Filament führt."""
        if d is None or data is None or not fuehrt_filament(data):
            return None
        try:
            with self._lock:  # type: ignore[attr-defined]
                basis = self._bom_basis
            if basis is None:
                return fl.gebaut_vorschau(None, [], [], data, None, [], {}, None,
                                          "Noch keine Stückliste: erst rechnen", self._material_name)
            run = int(basis.get("run") or 0)
            plan = self._filament_plan(d, data, run, d.kennungen(data))
            schon, ganz = self._platten_gebucht(d, run)
            return fl.gebaut_vorschau(run, plan["ops"], plan["info"], data, self._einkauf_druckvorschau(),
                                      plan["platten"], schon, ganz, plan.get("hinweis"), self._material_name)
        except Exception as exc:  # noqa: BLE001 - BESTAND kommt auch ohne Vorschau des Filaments
            self._log(f"[kernel] Bestand: Filament-Vorschau fehlgeschlagen: {exc!r}")  # type: ignore[attr-defined]
            return None

    def _bestand_vorschau_neu(self) -> None:
        """Nach jeder neuen Druckvorschau (druck/vorschau_laufzeit.py): Führt das Projekt Filament und ändert sich, was
        „Gebaut“ abbuchen würde, geht BESTAND mit der neuen ``gebaut_filament`` an die App."""
        try:
            d, data, _ = self._bestand_lesen()
            fil = self._gebaut_filament(d, data)
            if fil is None or fil == getattr(self, "_bestand_fil_gesendet", None):
                return
            self._send_app(self._bestand_nachricht())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - die Druckvorschau darf daran nicht scheitern
            self._log(f"[kernel] Bestand nach Druckvorschau: {exc!r}")  # type: ignore[attr-defined]

    # -- Planung -------------------------------------------------------------------------------------------------------

    def _bestand_bom(self, basis: dict[str, Any]) -> dict[str, Any]:
        """Nach einem Lauf: Stückliste um Zuschnitt mit Bestand und Einkaufsliste erweitern."""
        with self._lock:  # type: ignore[attr-defined]
            self._bom_basis = basis
        return self._bestand_planen(basis)

    def _bestand_planen(self, basis: dict[str, Any]) -> dict[str, Any]:
        d, data, fehler = self._bestand_lesen()
        try:
            planung = plane(basis, data if d is not None and d.existiert else None, self.catalog,  # type: ignore
                            stand=d.stand() if d is not None else None, fehler=fehler)
        except Exception as exc:  # noqa: BLE001 - die Stückliste kommt auch ohne Bestand
            self._log(f"[kernel] Bestand: Planung fehlgeschlagen: {exc!r}")  # type: ignore[attr-defined]
            bom = copy.deepcopy(basis)
            bom["warnings"] = list(bom.get("warnings") or []) + [f"Bestand: Zuschnitt fehlgeschlagen ({exc})"]
            return bom
        with self._lock:  # type: ignore[attr-defined]
            self._bestand_verbrauch = planung.verbrauch
            self._bestand_statistik = planung.statistik
        return planung.bom

    def _bestand_neu_planen(self) -> None:
        with self._lock:  # type: ignore[attr-defined]
            basis = self._bom_basis
        if basis is None:
            return
        bom = self._bestand_planen(basis)
        with self._lock:  # type: ignore[attr-defined]
            if self._bom_basis is not basis:
                return  # inzwischen neuer Lauf
            self._bom = bom
        self._send_app({"type": "BOM", **bom})  # type: ignore[attr-defined]

    def _bestand_geaendert(self) -> None:
        """BESTAND und neue BOM an die App."""
        self._send_app(self._bestand_nachricht())  # type: ignore[attr-defined]
        self._bestand_neu_planen()

    def _bestand_projekt(self, same: bool) -> None:
        """Projektwechsel (aus ``_set_project``): Basis vergessen, BESTAND schicken."""
        if not same:
            with self._lock:  # type: ignore[attr-defined]
                self._bom_basis = None
                self._bestand_verbrauch = []
        self._send_app(self._bestand_nachricht())  # type: ignore[attr-defined]

    def _bestand_pruefen(self) -> None:
        """Beobachtungsfaden: bestand.json von außen geändert (Editor, Agent mit Dateiwerkzeugen)? Dann neu melden."""
        d = self._bestand_datei()
        if d is None:
            return
        if not self._bestand_lock.acquire(blocking=False):
            return
        try:
            sig = d.signatur()
            changed = self._bestand_sig is not None and sig != self._bestand_sig
            if self._bestand_sig is None:
                self._bestand_sig = sig
        finally:
            self._bestand_lock.release()
        if changed:
            self._log("[kernel] bestand.json geändert: neu planen")  # type: ignore[attr-defined]
            self._bestand_geaendert()

    # -- Anfragen der App ----------------------------------------------------------------------------------------------

    def _bestand_anfrage(self, header: dict[str, Any]) -> None:
        kind = header.get("type")
        rid = header.get("id")
        if kind == "BESTAND_REQ":
            self._send_app(self._bestand_nachricht(reply_to=rid))  # type: ignore[attr-defined]
            return
        with self._bestand_lock:
            if kind == "BESTAND_SAVE":
                res = self._bestand_speichern(header, von="kevin")
            elif kind == "GEBAUT_REQ":
                res = self._gebaut(run=header.get("run"), von="kevin", grund=str(header.get("grund") or ""))
            else:
                res = self._rueckgaengig(str(header.get("buchung") or ""), von="kevin")
            ack: dict[str, Any] = {"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),
                                   "message": res.get("message") if res.get("ok") else res.get("error", "")}
            if res.get("buchung"):
                ack["buchung"] = res["buchung"]["id"]
            self._send_app(ack)  # type: ignore[attr-defined]
            if res.get("ok") and res.get("buchung"):
                self._bestand_geaendert()

    def _bestand_speichern(self, header: dict[str, Any], von: str) -> dict[str, Any]:
        """BESTAND_SAVE: ganzer Posten (oder null zum Entfernen) bzw. Einstellungen."""
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft, erst reparieren: {fehler}"}
        grund = str(header.get("grund") or "")
        if any(k in header for k in ("spule", "spule_kennung", "filament_fuehren")):
            return self._spule_speichern(d, data, header, grund, von)
        if header.get("posten_id") is None and isinstance(header.get("einstellungen"), dict):
            neu = {k: v for k, v in header["einstellungen"].items() if v is not None}
            errors = pruefe_einstellungen(neu)
            if errors:
                return {"ok": False, "error": "; ".join(errors)}
            neu = {k: zahl(v) for k, v in neu.items()}
            vorher = data.get("einstellungen") or {}
            if neu == vorher:
                return {"ok": True, "message": "keine Änderung"}
            ops = [{"op": "einstellungen", "vorher": vorher, "nachher": neu}]
            art = "korrektur"
        else:
            pid = str(header.get("posten_id") or "").strip()
            if not pid:
                return {"ok": False, "error": "posten_id fehlt (Katalog-id des Lagerteils) oder einstellungen"}
            posten = header.get("posten")
            vorher = (data.get("posten") or {}).get(pid)
            if posten is None:
                if vorher is None:
                    return {"ok": False, "error": f"Posten {pid!r} ist nicht im Bestand"}
                ops = [{"op": "posten", "posten": pid, "vorher": vorher, "nachher": None}]
                art = "korrektur"
            else:
                res = self._posten_pruefen(d, data, pid, posten)
                if not res.get("ok"):
                    return res
                posten = res["posten"]
                if json.dumps(posten, sort_keys=True) == json.dumps(vorher, sort_keys=True):
                    return {"ok": True, "message": "keine Änderung"}
                ops = [{"op": "posten", "posten": pid, "vorher": vorher, "nachher": posten}]
                art = _art_fuer(vorher, posten)
        try:
            buchung = d.buchen(art, ops, von=von, grund=grund)
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"],
                "aenderungen_text": aenderungen_text(ops, self._benennung, self._material_name)}

    def _spule_speichern(self, d: BestandDatei, data: dict[str, Any], header: dict[str, Any], grund: str,
                         von: str) -> dict[str, Any]:
        """BESTAND_SAVE mit Filament (Strang „Bestand Stufe 2“, additiv): ``spule`` ohne ``spule_kennung`` legt
        ``anzahl`` (Standard 1) gleiche Spulen an, mit ``spule_kennung`` ändert es diese Spule, ``spule: null`` entfernt
        sie; ``filament_fuehren: true`` führt Filament ohne Spule. Dieselben Regeln wie MCP ``bestand_eintragen``."""
        if header.get("filament_fuehren") is True and "spule" not in header:
            if fuehrt_filament(data):
                return {"ok": True, "message": "keine Änderung"}
            ops = [{"op": "filament_fuehren", "vorher": False, "nachher": True}]
            try:
                buchung = d.buchen("eintrag", ops, von=von, grund=grund)
            except BestandError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"],
                    "aenderungen_text": aenderungen_text(ops, self._benennung, self._material_name)}
        kennung = str(header.get("spule_kennung") or "").strip() or None
        sp = header.get("spule")
        if kennung and sp is None:
            return self._filament_eintragen(grund=grund, material=None, gramm=None, gramm_voll=None, spule=None,
                                            farbe=None, hersteller=None, anzahl=None, kennung=None, ort=None,
                                            spulen_entfernen=[kennung], von=von)
        if not isinstance(sp, dict):
            return {"ok": False, "error": "spule fehlt: Objekt mit material, gramm, gramm_voll, name, hersteller, "
                                          "farbe, ort (oder null mit spule_kennung zum Entfernen)"}
        bad = [k for k in sp if k not in ("material", "gramm", "gramm_voll", "name", "hersteller", "farbe", "ort",
                                         "kennung", "seit")]
        if bad:
            return {"ok": False, "error": f"spule kennt {', '.join(map(str, bad))} nicht"}
        felder = {"material": sp.get("material"), "gramm": number(sp.get("gramm")),
                  "gramm_voll": number(sp.get("gramm_voll")), "spule": sp.get("name"), "farbe": sp.get("farbe"),
                  "hersteller": sp.get("hersteller"), "ort": sp.get("ort")}
        if kennung:
            res = self._filament_eintragen(grund=grund, kennung=kennung, anzahl=None, spulen_entfernen=None, von=von,
                                           **felder)
            if not res.get("ok") and str(res.get("error", "")).startswith("Keine Änderung"):
                return {"ok": True, "message": "keine Änderung"}
            return res
        anzahl = header.get("anzahl")
        return self._filament_eintragen(grund=grund, kennung=None, spulen_entfernen=None, von=von,
                                        anzahl=None if anzahl is None else int(number(anzahl) or 0), **felder)

    def _posten_pruefen(self, d: BestandDatei, data: dict[str, Any], pid: str, posten: Any) -> dict[str, Any]:
        """Posten gegen den Katalog prüfen; Reste ohne Kennung bekommen eine, ``seit`` ist sonst heute."""
        item = self.catalog.item(pid)  # type: ignore[attr-defined]
        if item is None:
            close = difflib.get_close_matches(pid, self.catalog.item_ids(), n=3, cutoff=0.6)  # type: ignore
            return {"ok": False, "error": f"Lagerteil {pid!r} gibt es im Katalog nicht"
                                          + (f"; meinten Sie {', '.join(repr(c) for c in close)}?" if close else "")}
        if not isinstance(posten, dict):
            return {"ok": False, "error": f"Posten {pid!r}: muss ein Objekt sein"}
        posten = copy.deepcopy(posten)
        kennungen = d.kennungen(data)
        for rest in posten.get("reste") or []:
            if isinstance(rest, dict):
                if not rest.get("kennung"):
                    rest["kennung"] = kennungen.neu("b" in rest or item.get("art") == "platte")
                rest.setdefault("ort", None)
                rest.setdefault("seit", heute())
                for k in ("laenge", "b", "h"):
                    if number(rest.get(k)) is not None:
                        rest[k] = zahl(number(rest[k]))
        errors = pruefe_posten(pid, posten, item.get("art"))
        if errors:
            return {"ok": False, "error": "\n".join(errors)}
        return {"ok": True, "posten": posten, "item": item}

    def _benennung(self, pid: str) -> str:
        item = self.catalog.item(pid)  # type: ignore[attr-defined]
        return f"{item.get('name')} ({pid})" if item else pid

    def _material_name(self, mid: str) -> str:
        try:
            m = self.catalog.material(mid) if mid else None  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - nur der Anzeigename
            m = None
        return str((m or {}).get("name") or mid)

    # -- Gebaut und Rückgängig -----------------------------------------------------------------------------------------

    # -- Filament abbuchen (Strang „Bestand Stufe 2“) -------------------------------------------------------------------

    def _platten_gebucht(self, d: BestandDatei, run: int) -> tuple[dict[int, str], str | None]:
        """Platten dieses Laufs (dieser Sitzung), deren Filament schon gebucht ist ({nr: buchung}), und die Buchung, die
        die ganze Druckvorschau gebucht hat (oder None)."""
        schon: dict[int, str] = {}
        ganz = None
        for b in d.buchungen():
            if (b.get("art") not in ("gedruckt", "gebaut") or b.get("rueckgaengig_durch") or b.get("run") != run
                    or b.get("sitzung") != self._bestand_sitzung or "filament" not in b):
                continue
            if b.get("filament_ganz"):
                ganz = str(b.get("id"))
            for p in b.get("platten") or []:
                schon.setdefault(int(p), str(b.get("id")))
        return schon, ganz

    def _filament_plan(self, d: BestandDatei, data: dict[str, Any], run: int, kennungen: Any,
                       platten: list[int] | None = None, vorzug: str | None = None,
                       warten_s: float = 0.0) -> dict[str, Any]:
        """Was „Gedruckt“ bzw. „Gebaut“ vom Filament abbucht: die Platten der Druckvorschau dieses Laufs, die noch nicht
        gebucht sind (oder die genannten). {"ops", "info", "platten", "ganz", "gramm", "hinweis", "error"}"""
        leer: dict[str, Any] = {"ops": [], "info": [], "platten": [], "ganz": False, "gramm": {}, "hinweis": None}
        if not fuehrt_filament(data):
            return leer
        v = fl._vorschau(self._einkauf_druckvorschau(warten_s))
        if v is None or int(number(v.get("run")) or 0) != int(run):
            return {**leer, "hinweis": f"Keine Druckvorschau zu Lauf {run}: Filament nicht abgebucht"}
        alle = [int(p["nr"]) for p in v.get("platten") or [] if isinstance(p, dict) and number(p.get("nr")) is not None]
        schon, ganz = self._platten_gebucht(d, run)
        if ganz is not None:
            if platten:
                return {**leer, "error": f"Das Filament von Lauf {run} ist schon ganz gebucht ({ganz})."}
            return {**leer, "hinweis": f"Filament schon gebucht ({ganz})"}
        if platten:
            unbekannt = [p for p in platten if p not in alle]
            if unbekannt:
                return {**leer, "error": f"Platte {', '.join(map(str, unbekannt))} gibt es in der Druckvorschau nicht "
                                         f"(Platten: {', '.join(map(str, alle)) or 'keine'})."}
            doppelt = sorted({p for p in platten if p in schon})
            if doppelt:
                return {**leer, "error": "Schon als gedruckt gebucht: " + ", ".join(
                    f"Platte {p} ({schon[p]})" for p in doppelt) + "."}
            wahl = sorted(set(int(p) for p in platten))
        else:
            wahl = [p for p in alle if p not in schon]
            if alle and not wahl:
                return {**leer, "hinweis": "Filament aller Platten schon gebucht"}
        ganz_jetzt = not schon and (not platten or sorted(alle) == wahl)
        bed = fl.bedarf(v, run, None if ganz_jetzt else wahl)
        ops, info = fl.verbrauch_aenderungen(bed, data, kennungen, heute(), self.catalog, vorzug)  # type: ignore
        return {"ops": ops, "info": info, "platten": wahl, "ganz": ganz_jetzt,
                "gramm": {m: zahl(g) for m, g in bed.items()}, "hinweis": None}

    @staticmethod
    def _filament_extra(plan: dict[str, Any]) -> dict[str, Any]:
        if not plan.get("ops"):
            return {}
        return {"platten": plan["platten"], "filament": plan["gramm"], "filament_ganz": plan["ganz"]}

    def _filament_info_text(self, info: list[dict[str, Any]]) -> list[str]:
        """„PETG: 188,8 g, davon 120 g aus S-0001, 68,8 g von einer gekauften Spule (Rest als S-0003)“."""
        out = []
        for i in info:
            t = f"{self._material_name(i['material'])}: {gramm_text(i['gramm'])}"
            teile = []
            if i.get("aus_bestand"):
                teile.append(f"{gramm_text(i['aus_bestand'])} aus {', '.join(i['spulen'])}")
            if i.get("gekauft"):
                teile.append(f"{gramm_text(i['gekauft'])} von gekauften Spulen"
                             + (f" (Rest als {i['neue_spule']})" if i.get("neue_spule") else ""))
            out.append(t + (", davon " + ", ".join(teile) if teile else ""))
        return out

    def _gedruckt(self, grund: str = "", platten: list[int] | None = None, spule: str | None = None,
                  run: Any = None, von: str = "agent", warten_s: float = 5.0) -> dict[str, Any]:
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft, erst reparieren: {fehler}"}
        if not fuehrt_filament(data):
            return {"ok": False, "error": "Das Projekt führt kein Filament: erst Spulen eintragen (bestand_eintragen mit "
                                          "material und gramm) oder mit anzahl=0 festhalten, dass keins da ist."}
        if spule and not any(s.get("kennung") == spule for s in spulen(data)):
            return {"ok": False, "error": f"Spule {spule} gibt es nicht (vorhanden: "
                                          f"{', '.join(str(s.get('kennung')) for s in spulen(data)) or 'keine'})."}
        v = fl._vorschau(self._einkauf_druckvorschau(warten_s))
        if v is None:
            return {"ok": False, "error": "Keine Druckvorschau: erst rechnen (run), dann „gedruckt“ buchen."}
        vrun = int(number(v.get("run")) or 0)
        with self._lock:  # type: ignore[attr-defined]
            basis = self._bom_basis
        if run is not None and int(run) != vrun:
            return {"ok": False, "error": f"Die Druckvorschau ist von Lauf {vrun}, nicht {run}."}
        if basis is not None and int(basis.get("run") or 0) != vrun:
            return {"ok": False, "error": f"Die Druckvorschau ist von Lauf {vrun}, die Stückliste von Lauf "
                                          f"{basis.get('run')}: kurz warten und erneut buchen."}
        plan = self._filament_plan(d, data, vrun, d.kennungen(data), platten or None, spule)
        if plan.get("error"):
            return {"ok": False, "error": plan["error"]}
        if not plan["ops"]:
            return {"ok": False, "error": "Nichts abzubuchen" + (f": {plan['hinweis']}." if plan.get("hinweis")
                                                                 else ": die Druckvorschau braucht kein Filament.")}
        try:
            buchung = d.buchen("gedruckt", plan["ops"], von=von, grund=grund,
                               extra={"run": vrun, "sitzung": self._bestand_sitzung, **self._filament_extra(plan)})
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"], "filament": plan["info"],
                "platten": plan["platten"], "filament_text": self._filament_info_text(plan["info"]),
                "aenderungen_text": aenderungen_text(plan["ops"], self._benennung, self._material_name)}

    def _gebaut(self, run: Any = None, von: str = "agent", grund: str = "", warten_s: float = 0.0) -> dict[str, Any]:
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft, erst reparieren: {fehler}"}
        with self._lock:  # type: ignore[attr-defined]
            basis = self._bom_basis
            verbrauch = list(self._bestand_verbrauch)
        if basis is None:
            return {"ok": False, "error": "Noch keine Stückliste: erst rechnen (run), dann „gebaut“ buchen."}
        current = int(basis.get("run") or 0)
        if run is not None and int(run) != current:
            return {"ok": False, "error": f"Die Stückliste ist von Lauf {current}, nicht {run}: bitte die aktuelle "
                                          "Stückliste ansehen und erneut buchen."}
        for b in d.buchungen():
            if (b.get("art") == "gebaut" and not b.get("rueckgaengig_durch") and b.get("run") == current
                    and b.get("sitzung") == self._bestand_sitzung):
                return {"ok": False, "error": f"Lauf {current} ist schon als gebaut gebucht ({b['id']}). Zum "
                                              "erneuten Buchen erst rückgängig machen oder neu rechnen."}
        kennungen = d.kennungen(data)
        try:
            ops = gebaut_aenderungen(verbrauch, data, kennungen, heute())
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        # Filament der Platten, die noch nicht als gedruckt gebucht sind (Strang „Bestand Stufe 2“)
        plan = self._filament_plan(d, data, current, kennungen, warten_s=warten_s)
        ops += plan["ops"]
        if not ops:
            return {"ok": False, "error": "Nichts zu buchen: der Zuschnitt nimmt nichts aus dem Bestand des Projekts "
                                          "und es entstehen keine Reste ab Mindestrest."
                                          + (f" ({plan['hinweis']})" if plan.get("hinweis") else "")}
        try:
            buchung = d.buchen("gebaut", ops, von=von, grund=grund,
                               extra={"run": current, "sitzung": self._bestand_sitzung, **self._filament_extra(plan)})
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        out = {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"],
               "aenderungen_text": aenderungen_text(ops, self._benennung, self._material_name)}
        if plan["info"] or plan.get("hinweis"):
            out["filament"] = plan["info"]
            out["filament_text"] = self._filament_info_text(plan["info"]) or [plan["hinweis"]]
        return out

    def _rueckgaengig(self, bid: str, von: str = "agent") -> dict[str, Any]:
        d = self._bestand_datei()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if not bid:
            return {"ok": False, "error": "buchung fehlt (id wie „B-0003“)"}
        try:
            buchung = d.rueckgaengig(bid, von=von)
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "message": f"{bid} rückgängig: {buchung['zusammenfassung']}",
                "aenderungen_text": aenderungen_text(buchung["aenderungen"], self._benennung, self._material_name)}

    # =================================================================================================================
    # KernelService: Bestand (MCP)
    # =================================================================================================================

    def bestand_liste(self, stock_id: str | None = None) -> dict[str, Any]:
        """Bestand und Reste des offenen Projekts: {"ok", "projekt", "datei", "stand", "bestand", "buchungen",
        "text"}."""
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft: {fehler}", "datei": str(d.pfad)}
        buchungen = d.buchungen(10)
        sid = (stock_id or "").strip() or None
        text = bestand_text(data, self.catalog, projekt=d.projekt, datei=d.pfad.name, stand=d.stand(),  # type: ignore
                            buchungen=buchungen, nur=sid)
        out: dict[str, Any] = {"ok": True, "projekt": d.projekt, "datei": str(d.pfad), "stand": d.stand(),
                               "bestand": data, "buchungen": buchungen, "text": text}
        if sid:
            out["posten"] = (data.get("posten") or {}).get(sid)
        return out

    def bestand_eintragen(self, stock_id: str | None = None, ganze: Any = None, reste: list[Any] | None = None,
                          reste_entfernen: list[str] | None = None, stueck: Any = None,
                          mindestrest_mm: float | None = None, reste_ersetzen: bool = False,
                          grund: str = "", *, material: str | None = None, gramm: float | None = None,
                          gramm_voll: float | None = None, spule: str | None = None, farbe: str | None = None,
                          hersteller: str | None = None, anzahl: int | None = None, kennung: str | None = None,
                          ort: str | None = None, spulen_entfernen: list[str] | None = None) -> dict[str, Any]:
        """Kevins Angabe zum Bestand eintragen (nur auf seine Angabe). ``ganze``: Anzahl (setzt) oder Objekt;
        ``reste``: dazu (Längen bzw. [b, h] oder Objekte mit ``ort``); ``reste_entfernen``: Kennungen; ``stueck``:
        Anzahl bzw. Liste {laenge, anzahl} (setzt je Länge). Filament (statt ``stock_id``): ``material`` mit ``gramm``
        (übrig), ``spule`` (Name), ``gramm_voll``, ``farbe``, ``hersteller``, ``ort``, ``anzahl`` (gleiche Spulen; 0:
        Filament führen ohne Spule) legt Spulen an; ``kennung`` ändert eine Spule; ``spulen_entfernen``.
        {"ok", "buchung", "aenderungen_text", "posten" bzw. "spulen"}"""
        filament = {"material": material, "gramm": gramm, "gramm_voll": gramm_voll, "spule": spule, "farbe": farbe,
                    "hersteller": hersteller, "anzahl": anzahl, "kennung": kennung, "ort": ort,
                    "spulen_entfernen": spulen_entfernen}
        ist_filament = any(filament[k] is not None for k in FILAMENT_PARAMETER) or (ort is not None and not stock_id)
        with self._bestand_lock:
            if ist_filament and (stock_id or "").strip():
                res = {"ok": False, "error": "Entweder ein Lagerteil (id) oder Filament (material, kennung, "
                                             "spulen_entfernen), nicht beides in einem Aufruf."}
            elif ist_filament:
                res = self._filament_eintragen(grund=grund, **filament)
            elif ort is not None:
                res = {"ok": False, "error": "ort gilt hier nur für Filamentspulen; Reste mit Ort als "
                                             "{\"laenge\": 430, \"ort\": \"Regal 2\"} unter reste angeben"}
            elif not (stock_id or "").strip():
                res = {"ok": False, "error": "id fehlt (Lagerteil aus dem Katalog) oder material (Filament)"}
            else:
                res = self._eintragen(str(stock_id), ganze, reste, reste_entfernen, stueck, mindestrest_mm,
                                      reste_ersetzen, grund)
            if res.get("ok") and res.get("buchung"):
                self._bestand_geaendert()
        return res

    def _filament_material(self, material: str) -> dict[str, Any] | None:
        try:
            return self.catalog.find_material(material, include_proposed=True)  # type: ignore[attr-defined]
        except AttributeError:
            return self.catalog.material(material)  # type: ignore[attr-defined]

    def _filament_eintragen(self, *, grund: str, material: str | None, gramm: float | None, gramm_voll: float | None,
                            spule: str | None, farbe: str | None, hersteller: str | None, anzahl: int | None,
                            kennung: str | None, ort: str | None, spulen_entfernen: list[str] | None,
                            von: str = "agent") -> dict[str, Any]:
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft, erst reparieren: {fehler}"}
        liste = spulen(data)
        by_k = {s.get("kennung"): s for s in liste}
        ops: list[dict[str, Any]] = []
        kennungen = d.kennungen(data)
        mat = None
        if material is not None:
            mat = self._filament_material(str(material))
            if mat is None:
                tips = []
                try:
                    tips = [m["id"] for m in self.catalog.printable_materials()]  # type: ignore[attr-defined]
                except AttributeError:
                    pass
                return {"ok": False, "error": f"Material {material!r} gibt es im Katalog nicht"
                                              + (f" (Druckmaterialien: {', '.join(tips)})" if tips else "")}
            if mat.get("druckbar") is not True:
                return {"ok": False, "error": f"{mat.get('name')} ist kein Druckmaterial (druckbar im Katalog); "
                                              "Filament gibt es nur für druckbare Materialien."}
        for k in spulen_entfernen or []:
            if k not in by_k:
                return {"ok": False, "error": f"Spule {k} gibt es nicht (vorhanden: "
                                              f"{', '.join(str(x) for x in by_k) or 'keine'})"}
            ops.append({"op": "spule", "kennung": k, "vorher": by_k[k], "nachher": None})
        if kennung:
            alt = by_k.get(kennung)
            if alt is None:
                return {"ok": False, "error": f"Spule {kennung} gibt es nicht (vorhanden: "
                                              f"{', '.join(str(x) for x in by_k) or 'keine'})"}
            if anzahl is not None:
                return {"ok": False, "error": "anzahl gilt nur für neue Spulen (ohne kennung)"}
            neu = dict(alt)
            if mat is not None:
                neu["material"] = mat["id"]
            for key, wert in (("gramm", gramm), ("gramm_voll", gramm_voll)):
                if wert is not None:
                    neu[key] = zahl(wert)
            for key, wert in (("name", spule), ("farbe", farbe), ("hersteller", hersteller), ("ort", ort)):
                if wert is not None:
                    neu[key] = str(wert).strip() or None
            if neu == alt:
                return {"ok": False, "error": f"Keine Änderung: Spule {kennung} hat diese Werte schon"}
            errors = pruefe_spule(f"Spule {kennung}", neu)
            if errors:
                return {"ok": False, "error": "\n".join(errors)}
            ops.append({"op": "spule", "kennung": kennung, "vorher": alt, "nachher": neu})
        elif mat is not None:
            n = 1 if anzahl is None else int(anzahl)
            if n < 0 or n > 50:
                return {"ok": False, "error": "anzahl zwischen 0 und 50 angeben (gleiche Spulen)"}
            if n == 0:
                if gramm:
                    return {"ok": False, "error": "anzahl=0 heißt „keine Spule da“; dann ohne gramm"}
                if not fuehrt_filament(data):
                    ops.append({"op": "filament_fuehren", "vorher": False, "nachher": True})
            voll = float(gramm_voll) if gramm_voll is not None else fl.spule_g(mat)
            g = float(gramm) if gramm is not None else voll
            if n and g <= 0:
                return {"ok": False, "error": "gramm muss größer als 0 sein; leere Spulen nicht eintragen "
                                              "(spulen_entfernen entfernt eine)"}
            for _ in range(n):
                neu = {"kennung": kennungen.spule(), "material": mat["id"], "gramm": zahl(g), "gramm_voll": zahl(voll),
                       "name": (spule or "").strip() or None, "hersteller": (hersteller or "").strip() or None,
                       "farbe": (farbe or "").strip() or None, "ort": (ort or "").strip() or None, "seit": heute()}
                errors = pruefe_spule(f"Spule {neu['kennung']}", neu)
                if errors:
                    return {"ok": False, "error": "\n".join(errors)}
                ops.append({"op": "spule", "kennung": neu["kennung"], "vorher": None, "nachher": neu})
        elif any(x is not None for x in (gramm, gramm_voll, spule, farbe, hersteller, anzahl, ort)):
            return {"ok": False, "error": "Für eine neue Spule material angeben (z. B. \"petg\"), zum Ändern kennung "
                                          "(z. B. \"S-0001\")"}
        if not ops:
            return {"ok": False, "error": "Keine Änderung: Filament wird schon geführt" if fuehrt_filament(data)
                    else "Nichts einzutragen: material und gramm (neue Spule), kennung (ändern) oder spulen_entfernen"}
        art = "eintrag" if all(op.get("vorher") in (None, False) for op in ops) else "korrektur"
        try:
            buchung = d.buchen(art, ops, von=von, grund=grund)
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"],
                "aenderungen_text": aenderungen_text(ops, self._benennung, self._material_name),
                "spulen": spulen(d.lesen())}

    def _eintragen(self, stock_id: str, ganze: Any, reste: list[Any] | None, reste_entfernen: list[str] | None,
                   stueck: Any, mindestrest_mm: float | None, reste_ersetzen: bool, grund: str) -> dict[str, Any]:
        d, data, fehler = self._bestand_lesen()
        if d is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        if data is None:
            return {"ok": False, "error": f"bestand.json ist fehlerhaft, erst reparieren: {fehler}"}
        pid = str(stock_id or "").strip()
        item = self.catalog.item(pid)  # type: ignore[attr-defined]
        if item is None:
            hits, _ = self.catalog.search(pid, limit=3)  # type: ignore[attr-defined]
            tip = ", ".join(h["id"] for h in hits)
            return {"ok": False, "error": f"Lagerteil {pid!r} gibt es im Katalog nicht"
                                          + (f"; Treffer: {tip}" if tip else " (stock_search benutzen)")}
        art = item.get("art")
        platte = art == "platte"
        vorher = (data.get("posten") or {}).get(pid)
        posten = copy.deepcopy(vorher) if vorher else {}
        if ganze is not None:
            if art not in STANGENWARE and not platte:
                return {"ok": False, "error": f"{item.get('name')} ist Stückgut: Menge mit stueck angeben"}
            g = dict(posten.get("ganze") or {})
            if isinstance(ganze, dict):
                g.update({k: v for k, v in ganze.items() if v is not None})
            else:
                n = number(ganze)
                if n is None:
                    return {"ok": False, "error": "ganze als Anzahl (z. B. 2) oder Objekt {anzahl, laenge} angeben"}
                g["anzahl"] = int(n)
            if platte and "b" not in g:
                fmt = item.get("platte")
                if not (isinstance(fmt, list) and len(fmt) == 2):
                    return {"ok": False, "error": f"{item.get('name')} hat kein Standardformat im Katalog: ganze als "
                                                  "{anzahl, b, h} angeben"}
                g["b"], g["h"] = zahl(fmt[0]), zahl(fmt[1])
            if not platte and "laenge" not in g:
                if not item.get("stangenlaenge"):
                    return {"ok": False, "error": f"{item.get('name')} hat keine Stangenlänge im Katalog: ganze als "
                                                  "{anzahl, laenge} angeben"}
                g["laenge"] = zahl(item["stangenlaenge"])
            posten["ganze"] = {k: (int(v) if k == "anzahl" else zahl(v)) for k, v in g.items()}
        if reste_ersetzen:
            posten["reste"] = []
        if reste_entfernen:
            have = {r.get("kennung") for r in posten.get("reste") or []}
            missing = [k for k in reste_entfernen if k not in have]
            if missing:
                return {"ok": False, "error": f"Rest {', '.join(missing)} gibt es bei {pid!r} nicht (vorhanden: "
                                              f"{', '.join(sorted(k for k in have if k)) or 'keine'})"}
            posten["reste"] = [r for r in posten.get("reste") or [] if r.get("kennung") not in reste_entfernen]
        if reste:
            if art not in STANGENWARE and not platte:
                return {"ok": False, "error": f"{item.get('name')} ist Stückgut: keine Reste"}
            neu = posten.setdefault("reste", [])
            for r in reste:
                if isinstance(r, dict):
                    row = {k: v for k, v in r.items() if k in ("laenge", "b", "h", "ort", "kennung", "seit")}
                elif isinstance(r, (list, tuple)) and len(r) == 2:
                    row = {"b": r[0], "h": r[1]}
                elif platte:
                    return {"ok": False, "error": "Plattenreste als [b, h] oder {b, h} angeben"}
                else:
                    row = {"laenge": r}
                neu.append(row)
        if stueck is not None:
            if art in STANGENWARE or platte:
                return {"ok": False, "error": f"{item.get('name')} wird in ganzen und Resten geführt, nicht als stueck"}
            if art not in STUECKGUT:
                return {"ok": False, "error": f"{item.get('name')} ({art}) führt der Bestand nicht"}
            rows = stueck if isinstance(stueck, list) else [{"anzahl": stueck}]
            cur = list(posten.get("stueck") or [])
            for row in rows:
                if not isinstance(row, dict):
                    row = {"anzahl": row}
                n = number(row.get("anzahl"))
                if n is None:
                    return {"ok": False, "error": "stueck: anzahl fehlt"}
                L = number(row.get("laenge"))
                cur = [r for r in cur if not (number(r.get("laenge")) == L)]
                cur.append({"laenge": zahl(L), "anzahl": int(n)} if L is not None else {"anzahl": int(n)})
            posten["stueck"] = sorted(cur, key=lambda r: (r.get("laenge") is None, r.get("laenge") or 0))
        if mindestrest_mm is not None:
            posten["mindestrest_mm"] = zahl(mindestrest_mm)
        res = self._posten_pruefen(d, data, pid, posten)
        if not res.get("ok"):
            return res
        posten = res["posten"]
        if json.dumps(posten, sort_keys=True) == json.dumps(vorher, sort_keys=True):
            return {"ok": False, "error": "Keine Änderung: der Bestand hat diese Werte schon"}
        ops = [{"op": "posten", "posten": pid, "vorher": vorher, "nachher": posten}]
        try:
            buchung = d.buchen(_art_fuer(vorher, posten), ops, von="agent", grund=grund)
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "aenderungen_text": aenderungen_text(ops, self._benennung, self._material_name),
                "posten": posten, "message": buchung["zusammenfassung"]}

    def _einkauf_druckvorschau(self, warten_s: float = 0.0) -> dict[str, Any] | None:
        """Druckvorschau für das Filament der Einkaufsliste: die zuletzt gebaute (wie sie die App zuletzt bekam); mit
        ``warten_s`` erst auf die Vorschau des laufenden Laufs warten (MCP direkt nach ``run``)."""
        if not hasattr(self, "_dv_lock"):
            return None
        try:
            if warten_s > 0:
                return self._dv_aktuell(warten_s)  # type: ignore[attr-defined]
            with self._dv_lock:  # type: ignore[attr-defined]
                return self._dv_vorschau  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - ohne Vorschau gilt das Filament der Stückliste
            return None

    def einkauf_zusammenstellen(self, bom: dict[str, Any] | None = None,
                                warten_s: float = 0.0) -> dict[str, Any] | None:
        """Einkaufsliste wie im Bereich „Material“ der App (``einkauf.zusammenstellen``) zur aktuellen Stückliste."""
        if bom is None:
            with self._lock:  # type: ignore[attr-defined]
                bom = self._bom  # type: ignore[attr-defined]
        if bom is None:
            return None
        return ek.zusammenstellen(bom, self._einkauf_druckvorschau(warten_s), self.catalog)  # type: ignore

    def einkaufsliste(self) -> dict[str, Any]:
        """Einkaufsliste wie in der App: Lagerware, Zukaufteile, Normteile zum Abzählen, Filament, Summe; Text und CSV
        (<projekt>/output/) byteweise wie „Teilen“ in der App."""
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        with self._lock:  # type: ignore[attr-defined]
            bom = self._bom  # type: ignore[attr-defined]
        if bom is None:
            return {"ok": False, "error": "Noch keine Stückliste: erst run aufrufen."}
        e = self.einkauf_zusammenstellen(bom, warten_s=5.0)
        assert e is not None
        out: dict[str, Any] = {"ok": True, "run": bom.get("run"),
                               **{k: bom.get(k) for k in ("einkaufsliste", "einkauf_summe", "einkauf_hinweis",
                                                          "bestand_stand", "fehlt", "stueckgut", "zukauf_bestand")},
                               "lagerware": e["lager"], "zukauf": e["zukauf"],
                               "zukauf_aus_bestand": e["zukauf_aus_bestand"], "normteile": e["normteile"],
                               "filament": e["filament"], "filament_kauf": e["filament_kauf"],
                               "filament_aus_bestand": e["filament_aus_bestand"],
                               "filament_bestand": bom.get("filament_bestand"),
                               "positionen": e["positionen"], "summe": e["summe"],
                               "summe_lager": e["summe_lager"], "summe_zukauf": e["summe_zukauf"],
                               "ohne_preis": e["ohne_preis"],
                               "text": ek.text(e, proj.name, ek.heute_text())}
        res = self._bestand_export_csv(proj, e)
        if res.get("ok"):
            out["csv"] = res["file"]
        else:
            out["warnings"] = [res["error"]]
        return out

    def _bestand_export_csv(self, proj: Any, e: dict[str, Any] | None = None) -> dict[str, Any]:
        """CSV der Einkaufsliste wie die App sie sichert und teilt (gleicher Name, gleiche Bytes)."""
        if e is None:
            e = self.einkauf_zusammenstellen(warten_s=5.0)
        if e is None:
            return {"ok": False, "error": "Einkaufsliste: noch kein erfolgreicher Lauf"}
        path = (proj.output_dir / ek.dateiname(proj.name)).resolve()
        try:
            proj.output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(ek.csv(e), encoding="utf-8", newline="")
        except OSError as exc:
            return {"ok": False, "error": f"Einkaufsliste nicht geschrieben: {exc}"}
        return {"ok": True, "file": str(path)}

    def gebaut_buchen(self, grund: str = "", run: int | None = None) -> dict[str, Any]:
        """Nur auf Kevins ausdrücklichen Wunsch: bucht ab, was der aktuelle Zuschnitt aus dem Projektbestand verplant,
        und legt die neuen Reste an. {"ok", "buchung", "aenderungen_text"}"""
        with self._bestand_lock:
            res = self._gebaut(run=run, von="agent", grund=grund, warten_s=5.0)
            if res.get("ok"):
                self._bestand_geaendert()
        return res

    def gedruckt_buchen(self, grund: str = "", platten: list[int] | None = None, spule: str | None = None,
                        run: int | None = None) -> dict[str, Any]:
        """Nur auf Kevins ausdrücklichen Wunsch (Strang „Bestand Stufe 2“): bucht das Filament der Druckvorschau ab
        (alle noch nicht gebuchten Platten oder die genannten), angebrochene Spulen zuerst bzw. ``spule`` zuerst.
        {"ok", "buchung", "aenderungen_text", "filament", "filament_text", "platten"}"""
        with self._bestand_lock:
            res = self._gedruckt(grund=grund, platten=platten, spule=spule, run=run, von="agent")
            if res.get("ok"):
                self._bestand_geaendert()
        return res

    def buchung_rueckgaengig(self, buchung: str) -> dict[str, Any]:
        """Bucht die Umkehrung einer Buchung. {"ok", "buchung", "aenderungen_text"}"""
        with self._bestand_lock:
            res = self._rueckgaengig(str(buchung or "").strip(), von="agent")
            if res.get("ok"):
                self._bestand_geaendert()
        return res


def _art_fuer(vorher: dict[str, Any] | None, nachher: dict[str, Any] | None) -> str:
    """„eintrag“, wenn nur etwas dazukommt; sonst „korrektur“."""
    if vorher is None:
        return "eintrag"
    if nachher is None:
        return "korrektur"
    gv = int(number((vorher.get("ganze") or {}).get("anzahl")) or 0)
    gn = int(number((nachher.get("ganze") or {}).get("anzahl")) or 0)
    rv = {r.get("kennung") for r in vorher.get("reste") or []}
    rn = {r.get("kennung") for r in nachher.get("reste") or []}
    alt = {r.get("laenge"): int(number(r.get("anzahl")) or 0) for r in vorher.get("stueck") or []}
    mehr = all(int(number(r.get("anzahl")) or 0) >= alt.get(r.get("laenge"), 0) for r in nachher.get("stueck") or [])
    weg = set(alt) - {r.get("laenge") for r in nachher.get("stueck") or []}
    if gn >= gv and rv <= rn and mehr and not weg and vorher.get("mindestrest_mm") == nachher.get("mindestrest_mm"):
        return "eintrag"
    return "korrektur"

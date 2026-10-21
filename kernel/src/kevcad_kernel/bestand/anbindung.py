"""Bestand in der Kernel-Laufzeit: Mixin für ``KernelRuntime`` (runtime.py).

- Nach jedem Lauf erweitert ``_bestand_bom`` die Stückliste um Zuschnitt mit Bestand und Einkaufsliste; die Basis aus
  dem Rechenprozess bleibt gespeichert, damit Änderungen am Bestand ohne neuen Lauf neu geplant werden.
- ``BESTAND`` geht nach dem Verbinden, nach jedem Projektwechsel und nach jeder Änderung an die App (auch wenn
  bestand.json von außen geändert wurde, Prüfung im Beobachtungsfaden).
- Anfragen der App: ``BESTAND_REQ``, ``BESTAND_SAVE``, ``GEBAUT_REQ``, ``BUCHUNG_RUECKGAENGIG`` (ACK, danach BESTAND
  und BOM).
- MCP-Fassade (service.py): ``bestand_liste``, ``bestand_eintragen``, ``einkaufsliste``, ``gebaut_buchen``,
  ``buchung_rueckgaengig``.

Erwartet von der Laufzeit: ``_lock``, ``_project``, ``_bom``, ``catalog``, ``_send_app``, ``_log``.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
import threading
import time
from typing import Any

from kevcad_kernel.catalog import KLEINTEILE, STANGENWARE, number

from .datei import (
    MELDUNG_BUCHUNGEN,
    BestandDatei,
    BestandError,
    aenderungen_text,
    heute,
    pruefe_einstellungen,
    pruefe_posten,
    zahl,
)
from .planung import Verbrauch, gebaut_aenderungen, plane
from .text import bestand_text, einkauf_csv, einkauf_text

ANFRAGEN = ("BESTAND_REQ", "BESTAND_SAVE", "GEBAUT_REQ", "BUCHUNG_RUECKGAENGIG")
KEIN_PROJEKT = "Kein Projekt offen: Bestand gibt es je Projekt (bestand.json im Projektordner)."


class BestandAnbindung:
    """Bestand des offenen Projekts für die Laufzeit (siehe Moduldoku)."""

    def _bestand_init(self) -> None:
        self._bom_basis: dict[str, Any] | None = None  # Stückliste des Laufs ohne Bestand
        self._bestand_verbrauch: list[Verbrauch] = []
        self._bestand_statistik: list[dict[str, Any]] = []
        self._bestand_sig: tuple | None = None
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
        msg = pack_bestand(bestand=data, buchungen=d.buchungen(MELDUNG_BUCHUNGEN) if d is not None else [],
                           stand=d.stand() if d is not None else None, datei=str(d.pfad) if d is not None else None,
                           fehler=fehler, reply_to=reply_to)
        msg.pop("seq", None)
        return msg

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
                "aenderungen_text": aenderungen_text(ops, self._benennung)}

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

    # -- Gebaut und Rückgängig -----------------------------------------------------------------------------------------

    def _gebaut(self, run: Any = None, von: str = "agent", grund: str = "") -> dict[str, Any]:
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
        try:
            ops = gebaut_aenderungen(verbrauch, data, d.kennungen(data), heute())
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        if not ops:
            return {"ok": False, "error": "Nichts zu buchen: der Zuschnitt nimmt nichts aus dem Bestand des Projekts "
                                          "und es entstehen keine Reste ab Mindestrest."}
        try:
            buchung = d.buchen("gebaut", ops, von=von, grund=grund,
                               extra={"run": current, "sitzung": self._bestand_sitzung})
        except BestandError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "buchung": buchung, "message": buchung["zusammenfassung"],
                "aenderungen_text": aenderungen_text(ops, self._benennung)}

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
                "aenderungen_text": aenderungen_text(buchung["aenderungen"], self._benennung)}

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

    def bestand_eintragen(self, stock_id: str, ganze: Any = None, reste: list[Any] | None = None,
                          reste_entfernen: list[str] | None = None, stueck: Any = None,
                          mindestrest_mm: float | None = None, reste_ersetzen: bool = False,
                          grund: str = "") -> dict[str, Any]:
        """Kevins Angabe zum Bestand eintragen (nur auf seine Angabe). ``ganze``: Anzahl (setzt) oder Objekt;
        ``reste``: dazu (Längen bzw. [b, h] oder Objekte mit ``ort``); ``reste_entfernen``: Kennungen; ``stueck``:
        Anzahl bzw. Liste {laenge, anzahl} (setzt je Länge). {"ok", "buchung", "aenderungen_text", "posten"}"""
        with self._bestand_lock:
            res = self._eintragen(stock_id, ganze, reste, reste_entfernen, stueck, mindestrest_mm, reste_ersetzen,
                                  grund)
            if res.get("ok") and res.get("buchung"):
                self._bestand_geaendert()
        return res

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
            if art not in KLEINTEILE:
                return {"ok": False, "error": f"{item.get('name')} wird in ganzen und Resten geführt, nicht als stueck"}
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
        return {"ok": True, "buchung": buchung, "aenderungen_text": aenderungen_text(ops, self._benennung),
                "posten": posten, "message": buchung["zusammenfassung"]}

    def einkaufsliste(self) -> dict[str, Any]:
        """Fehlmengen des aktuellen Projekts mit Preis und Summe, dazu die CSV-Datei in <projekt>/output/."""
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return {"ok": False, "error": KEIN_PROJEKT}
        with self._lock:  # type: ignore[attr-defined]
            bom = self._bom  # type: ignore[attr-defined]
        if bom is None:
            return {"ok": False, "error": "Noch keine Stückliste: erst run aufrufen."}
        out: dict[str, Any] = {"ok": True, "run": bom.get("run"),
                               **{k: bom.get(k) for k in ("einkaufsliste", "einkauf_summe", "einkauf_hinweis",
                                                          "bestand_stand", "fehlt", "stueckgut")},
                               "text": einkauf_text(bom, proj.name)}
        res = self._bestand_export_csv(proj)
        if res.get("ok"):
            out["csv"] = res["file"]
        else:
            out["warnings"] = [res["error"]]
        return out

    def _bestand_export_csv(self, proj: Any) -> dict[str, Any]:
        with self._lock:  # type: ignore[attr-defined]
            bom = self._bom  # type: ignore[attr-defined]
        if bom is None:
            return {"ok": False, "error": "Einkaufsliste: noch kein erfolgreicher Lauf"}
        path = (proj.output_dir / f"{_dateiname(proj.name)}-einkaufsliste.csv").resolve()
        try:
            proj.output_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(einkauf_csv(bom, proj.name), encoding="utf-8-sig", newline="")
        except OSError as exc:
            return {"ok": False, "error": f"Einkaufsliste nicht geschrieben: {exc}"}
        return {"ok": True, "file": str(path)}

    def gebaut_buchen(self, grund: str = "", run: int | None = None) -> dict[str, Any]:
        """Nur auf Kevins ausdrücklichen Wunsch: bucht ab, was der aktuelle Zuschnitt aus dem Projektbestand verplant,
        und legt die neuen Reste an. {"ok", "buchung", "aenderungen_text"}"""
        with self._bestand_lock:
            res = self._gebaut(run=run, von="agent", grund=grund)
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


def _dateiname(name: str) -> str:
    """Wie ``export.safe_name`` (ohne build123d zu laden)."""
    s = re.sub(r"[^\w\-. äöüÄÖÜß]+", "_", name, flags=re.UNICODE).strip(" ._")
    return s or "modell"


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

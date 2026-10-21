"""Zukaufteile in der Kernel-Laufzeit: MCP-Werkzeuge (über ``KernelService``) und App-Nachrichten.

- ``anlegen``: Felder (von Claude oder aus der Shop-Auswertung) → Katalogeintrag ``art: "zukaufteil"``. Über MCP immer
  ein Vorschlag (``status: "vorgeschlagen"``), aus der App (``ZUKAUF_NEU``) sofort ``frei``. Normteile werden auf den
  Lagerkatalog umgeleitet.
- ``html``: mitgeliefertes HTML auswerten (``shopdaten``), auf Wunsch gleich anlegen.
- ``suchen``: TraceParts (mit Kevins Schlüssel automatisch bis zum Import), sonst Links → ``wartet_auf_cad``.
- ``uebernehmen``: Datei (oder neueste passende aus ``~/Downloads``, auch ZIP) prüfen, in den Zukauf-Ordner legen,
  in den Katalog eintragen.
- ``liste``: alle Zukaufteile mit Freigabe und CAD-Stand.

Zustände je Projekt in ``<projekt>/.kevcad/zukauf-status.json``; nach dem Verbinden der App gehen alle, die noch
``wartet_auf_cad`` sind, als ``ZUKAUF_STATUS`` an die App (PROTOCOL.md, Festlegungen zu Phase 3).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.catalog import WRITABLE, ZUKAUF_ARTEN, CatalogError, is_free
from kevcad_kernel.protocol import zukauf_status
from kevcad_kernel.zukauf import downloads as dl
from kevcad_kernel.zukauf import eintrag as ze
from kevcad_kernel.zukauf import traceparts as tp

STATUS_DATEI = "zukauf-status.json"
MAX_SEEN = 30


class ZukaufDienst:
    """Gehört zu einer ``KernelRuntime`` (``rt``): nutzt deren Katalog, Projekt, App-Verbindung und OCCT-Sperre."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self._lock = threading.RLock()
        self._seen: list[dict[str, Any]] = []  # DOWNLOAD_SEEN der App, neueste zuletzt
        self.traceparts_transport = None  # für Tests: Attrappe statt echter Abrufe
        self.traceparts_sleep = time.sleep

    # =================================================================================================================
    # Hilfen

    @property
    def catalog(self):
        return self.rt.catalog

    def _project_path(self) -> Path | None:
        proj = getattr(self.rt, "_project", None)
        return Path(proj.path) if proj is not None else None

    def _entry(self, zid: str) -> tuple[dict[str, Any] | None, str | None]:
        zid = str(zid or "").strip()
        it = self.catalog.item(zid)
        if it is None:
            import difflib

            ids = [r["id"] for r in self.catalog.items() if r.get("art") in ZUKAUF_ARTEN]
            close = difflib.get_close_matches(zid, ids, n=3, cutoff=0.5)
            return None, (f"Zukaufteil {zid!r} gibt es nicht" + (f"; meinten Sie {', '.join(close)}?" if close else
                                                                  " (zukauf_liste zeigt alle)"))
        if it.get("art") not in ZUKAUF_ARTEN:
            return None, f"{zid!r} ist ein Lagerteil ({it.get('name')}), kein Zukaufteil"
        return it, None

    def _base_dir(self, entry: dict[str, Any]) -> Path:
        src = self.catalog.source("teil", entry["id"])
        if src is not None:
            return Path(src[1]).parent
        p = self._project_path()
        if p is None:
            raise CatalogError("Kein Projekt offen")
        return p

    def _cache_dir(self, entry: dict[str, Any]) -> Path:
        p = self._project_path()
        return (p if p is not None else self._base_dir(entry)) / "zukauf" / entry["id"]

    # -- Zustände ------------------------------------------------------------------------------------------------------

    def _status_path(self) -> Path | None:
        p = self._project_path()
        return p / ".kevcad" / STATUS_DATEI if p is not None else None

    def _status_load(self) -> dict[str, Any]:
        path = self._status_path()
        if path is None or not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _status(self, zid: str, zustand: str, text: str, *, cad_links: list[dict[str, str]] | None = None,
                name: str | None = None) -> dict[str, Any]:
        msg = zukauf_status(zid, zustand, text, cad_links=cad_links if zustand == "wartet_auf_cad" else None,
                            erwartet=list(ze.CAD_ENDUNGEN) if zustand == "wartet_auf_cad" else None, name=name)
        with self._lock:
            path = self._status_path()
            if path is not None:
                data = self._status_load()
                data[zid] = {k: v for k, v in msg.items() if k not in ("type", "id")} | {"seit": ze.heute()}
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(f".{path.name}.tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                    os.replace(tmp, path)
                except OSError:
                    pass
        self.rt._send_app(msg)
        return msg

    def _abgelehnt(self, entry: dict[str, Any], datei: Path, grund: str) -> None:
        """Datei passt nicht: ``fehler`` mit dem Grund. Wartete das Teil auf sein CAD (Rückfrage in der App), folgt
        wieder ``wartet_auf_cad`` mit den Links, damit die App den Download-Ordner weiter beobachtet und Kevin die
        richtige Datei holen kann (Zusammenführung Phase 3: die App hört bei ``fehler`` auf zu beobachten)."""
        zid = entry["id"]
        vorher = (self._status_load().get(zid) or {})
        self._status(zid, "fehler", grund, name=entry.get("name"))
        if vorher.get("zustand") == "wartet_auf_cad" and ze.cad_art(entry) == "vereinfacht":
            text = f"{datei.name} nicht übernommen: {grund}. Bitte die passende STEP-Datei herunterladen."
            self._status(zid, "wartet_auf_cad", text, cad_links=vorher.get("cad_links") or tp.cad_links(entry),
                         name=entry.get("name"))

    def offene_status(self) -> list[dict[str, Any]]:
        """ZUKAUF_STATUS für alle Zukaufteile des Projekts, die noch auf ihr CAD warten (nach dem Verbinden)."""
        out = []
        for zid, st in self._status_load().items():
            if st.get("zustand") != "wartet_auf_cad":
                continue
            entry = self.catalog.item(zid)
            if entry is None or entry.get("art") not in ZUKAUF_ARTEN or ze.cad_art(entry) != "vereinfacht":
                continue
            out.append(zukauf_status(zid, "wartet_auf_cad", str(st.get("text") or ""),
                                     cad_links=st.get("cad_links") or tp.cad_links(entry),
                                     erwartet=list(ze.CAD_ENDUNGEN), name=entry.get("name")))
        return out

    # =================================================================================================================
    # Anlegen

    def _duplikat(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        g = ze.gtin_digits(entry.get("gtin"))
        mpn = str(entry.get("mpn") or "").lower().replace(" ", "")
        hersteller = str(entry.get("hersteller") or "").lower().replace(" ", "")
        for r in self.catalog.items():
            if r.get("art") not in ZUKAUF_ARTEN or r["id"] == entry.get("id"):
                continue
            if g and ze.gtin_digits(r.get("gtin")) == g:
                return r
            if mpn and str(r.get("mpn") or "").lower().replace(" ", "") == mpn and \
                    str(r.get("hersteller") or "").lower().replace(" ", "") == hersteller:
                return r
        return None

    def anlegen(self, url: str | None = None, mpn: str | None = None, gtin: str | None = None,
                felder: dict[str, Any] | None = None, ebene: str = "projekt", *, hersteller: str | None = None,
                proposal: bool = True, status_senden: bool = True) -> dict[str, Any]:
        felder = dict(felder or {})
        if ebene not in WRITABLE:
            return {"ok": False, "error": f"Ebene {ebene!r} geht nicht (projekt oder eigen)"}
        from kevcad_kernel.zukauf.normteile import umleiten

        probe = " ".join(str(x) for x in (mpn, felder.get("mpn"), felder.get("name"), felder.get("titel")) if x)
        red = umleiten(probe, self.catalog) if probe else None
        if red is not None:
            return {"ok": True, "angelegt": False, "normteil": red["normteil"], "stock_id": red.get("stock_id"),
                    "treffer": red.get("treffer"), "beispiel": red.get("beispiel"), "vorschlag": red.get("vorschlag"),
                    "text": red["text"]}
        if not felder and (url or gtin) and not mpn:
            what = "dem Link" if url else "der EAN"
            return {"ok": False, "error": f"Mit {what} allein kennt Kev CAD das Teil nicht (es lädt keine Shop-Seiten). "
                                          "Die Seite selbst lesen und das HTML an zukauf_html geben oder die Felder "
                                          "(name, hersteller, mpn, masse, preis …) an zukauf_anlegen."}
        entry, notes = ze.entwurf(felder, url=url, mpn=mpn, gtin=gtin, hersteller=hersteller)
        if gtin and not ze.gtin_ok(gtin):
            notes.append(f"EAN {gtin!r} hat eine falsche Prüfziffer – bitte prüfen")
        dup = self._duplikat(entry)
        if dup is not None:
            return {"ok": True, "angelegt": False, "vorhanden": dup,
                    "text": f"Das Teil gibt es schon als {dup['id']} ({ze.kurz(dup)}, {ze.status_text(dup)}): "
                            f"lager.zukauf({dup['id']!r})"}
        existing = self.catalog.item(entry["id"])
        if existing is not None and existing.get("art") not in ZUKAUF_ARTEN:
            entry["id"] = f"{entry['id']}-zukauf"
        if not proposal:
            entry["status"] = "frei"
        try:
            saved, path, more = self.catalog.save("teil", entry, ebene, proposal=proposal)
        except CatalogError as exc:
            return {"ok": False, "error": str(exc), "entwurf": entry, "zu_pruefen": ze.zu_pruefen(entry)}
        notes += more
        text = (f"{ze.kurz(saved)} angelegt"
                + (" (Vorschlag, wartet auf Kevins Freigabe im Lagerkatalog)" if not is_free(saved) else ""))
        if status_senden:
            self._status(saved["id"], "angelegt", text, name=saved.get("name"))
        return {"ok": True, "angelegt": True, "item": saved, "datei": str(path), "hinweise": notes,
                "zu_pruefen": ze.zu_pruefen(saved), "cad": ze.cad_art(saved), "text": text}

    def html(self, url: str | None, html: str, *, anlegen: bool = False, ebene: str = "projekt",
             felder: dict[str, Any] | None = None) -> dict[str, Any]:
        from kevcad_kernel.zukauf.shopdaten import auswerten

        res = auswerten(html, url)
        werte = {k: v for k, v in res["felder"].items() if k != "beschreibung"}
        werte.update({k: v for k, v in (felder or {}).items() if v not in (None, "")})
        entry, notes = ze.entwurf(werte, url=url)
        out = {"ok": True, "felder": res["felder"], "entwurf": entry, "quellen": res["quellen"],
               "zu_pruefen": ze.zu_pruefen(entry), "hinweise": res["hinweise"] + notes}
        from kevcad_kernel.zukauf.normteile import umleiten

        red = umleiten(" ".join(str(x) for x in (entry.get("mpn"), entry.get("name")) if x), self.catalog)
        if red is not None:
            out["normteil"] = red["normteil"]
            out["stock_id"] = red.get("stock_id")
            out["text"] = red["text"]
            return out
        if anlegen:
            created = self.anlegen(url=url, felder=werte, ebene=ebene)
            out["angelegt"] = created
            if not created.get("ok"):
                out["ok"] = False
                out["error"] = created.get("error")
        return out

    # =================================================================================================================
    # CAD suchen und übernehmen

    def suchen(self, zid: str, *, automatisch: bool = True) -> dict[str, Any]:
        entry, err = self._entry(zid)
        if entry is None:
            return {"ok": False, "error": err}
        cad = entry.get("cad") if isinstance(entry.get("cad"), dict) else {}
        if ze.cad_art(entry) != "vereinfacht":
            datei = cad.get("datei")
            if not datei or (self._base_dir(entry) / datei).is_file():
                return {"ok": True, "zustand": "importiert", "cad": ze.cad_art(entry),
                        "text": f"{entry.get('name')} hat schon CAD ({cad.get('quelle')}"
                                + (f": {datei}" if datei else "") + ")"}
        hinweise: list[str] = []
        z, grund = tp.zugang()
        if z is not None and automatisch and entry.get("mpn") and entry.get("hersteller"):
            client = tp.TraceParts(z, self.traceparts_transport, sleep=self.traceparts_sleep)
            try:
                got = client.holen(str(entry["mpn"]), str(entry["hersteller"]), self._base_dir(entry) / "zukauf" /
                                   entry["id"] / "traceparts", entry["id"])
            except tp.TracePartsFehler as exc:
                got = None
                hinweise.append(str(exc))
            if got and got.get("datei"):
                res = self.uebernehmen(entry["id"], got["datei"], quelle="traceparts",
                                       lizenz=f"TraceParts-Nutzungsbedingungen ({tp.POWERED})",
                                       extra={"traceparts_id": (got.get("teil") or {}).get("partFamilyCode")})
                res["powered_by"] = tp.POWERED
                res["traceparts_aufrufe"] = client.aufrufe
                return res
            if got and got.get("gefunden") and not got.get("format"):
                hinweise.append("TraceParts kennt das Teil, bietet aber kein STEP mit direktem Download")
            elif got is not None and not got.get("gefunden"):
                hinweise.append(f"TraceParts kennt {entry['hersteller']} {entry['mpn']} nicht")
        elif grund:
            hinweise.append(grund)
        links = tp.cad_links(entry)
        text = (f"CAD für {entry.get('name')}: Kevin lädt die STEP-Datei herunter (Links), Kev CAD übernimmt sie aus "
                "dem Download-Ordner")
        self._status(entry["id"], "wartet_auf_cad", text, cad_links=links, name=entry.get("name"))
        return {"ok": True, "zustand": "wartet_auf_cad", "cad_links": links, "erwartet": list(ze.CAD_ENDUNGEN),
                "hinweise": hinweise, "text": text}

    def uebernehmen(self, zid: str, pfad: str | None = None, *, minuten: float = dl.STANDARD_MINUTEN,
                    erzwingen: bool = False, quelle: str = "download", lizenz: str | None = None,
                    extra: dict[str, Any] | None = None) -> dict[str, Any]:
        entry, err = self._entry(zid)
        if entry is None:
            return {"ok": False, "error": err}
        if entry.get("ebene") not in WRITABLE:
            return {"ok": False, "error": f"{zid} steht im mitgelieferten Katalog; Zukauf-CAD gehört in den Projekt- "
                                          "oder eigenen Katalog"}
        if pfad:
            datei = Path(pfad).expanduser()
        else:
            with self._lock:
                seen = [s["pfad"] for s in self._seen]
            files = dl.kandidaten(dl.downloads_dir(), minuten, extra=seen)
            datei = dl.waehlen(files, entry)
            if datei is None:
                return {"ok": False, "error": f"Keine neue STEP- oder ZIP-Datei der letzten {minuten:g} Minuten in "
                                              f"{dl.downloads_dir()}: Kevin bitten, das CAD herunterzuladen (Links aus "
                                              "cad_suchen), dann erneut cad_uebernehmen"}
        try:
            base = self._base_dir(entry)
        except CatalogError as exc:
            return {"ok": False, "error": str(exc)}
        ziel = base / "zukauf" / entry["id"]
        try:
            step, hinweise = dl.uebernehmen(datei, ziel, entry)
        except dl.DownloadFehler as exc:
            self._abgelehnt(entry, Path(datei), str(exc))
            return {"ok": False, "error": str(exc), "datei": str(datei)}
        from kevcad_kernel.zukauf import cad as zc

        try:
            with self.rt._occ_lock:
                shape, info = zc.importieren(step, self._cache_dir(entry), ze.huelle(entry), name=entry.get("name"),
                                             erzwingen=erzwingen)
                n_teile = len(shape.solids())
        except zc.CadFehler as exc:
            if step.parent == ziel and step.resolve() != Path(datei).resolve():
                try:
                    step.unlink()
                except OSError:
                    pass
            self._abgelehnt(entry, Path(datei), str(exc))
            return {"ok": False, "error": str(exc), "datei": str(datei)}
        rel = os.path.relpath(step, base)
        cad = {"quelle": quelle, "datei": rel, "lizenz": lizenz or "Herstellerbedingungen (nicht weitergeben)",
               "stand": ze.heute(), **{k: v for k, v in (extra or {}).items() if v}}
        updated = {k: v for k, v in entry.items() if k != "ebene"}
        updated["cad"] = cad
        try:  # Status bleibt, wie er ist: das CAD ändert nichts an der Freigabe
            saved, path, _ = self.catalog.save("teil", updated, entry["ebene"], proposal=False)
        except CatalogError as exc:
            return {"ok": False, "error": str(exc)}
        pr = info.get("pruefung") or {}
        text = (f"CAD für {entry.get('name')} übernommen: {Path(rel).name}, {n_teile} Körper"
                + (f", {'; '.join(info.get('hinweise'))}" if info.get("hinweise") else ""))
        self._status(entry["id"], "importiert", text, name=entry.get("name"))
        self.rt._rerun_after_catalog_change()
        return {"ok": True, "zustand": "importiert", "item": saved, "datei": str(step), "quelle_datei": str(datei),
                "pruefung": pr, "flaechen": info.get("flaechen"), "grob": info.get("grob"), "koerper": n_teile,
                "hinweise": hinweise + list(info.get("hinweise") or []), "text": text}

    # =================================================================================================================
    # Liste

    def liste(self, query: str = "") -> dict[str, Any]:
        rows, _ = self.catalog.search(query or "", limit=None)
        status = self._status_load()
        items = []
        for r in rows:
            if r.get("art") not in ZUKAUF_ARTEN:
                continue
            cad = r.get("cad") if isinstance(r.get("cad"), dict) else {}
            art = ze.cad_art(r)
            fehlt = False
            if art == "hersteller" and cad.get("datei"):
                try:
                    fehlt = not (self._base_dir(r) / cad["datei"]).is_file()
                except CatalogError:
                    fehlt = True
            items.append({**r, "cad_art": "vereinfacht" if fehlt else art, "cad_datei_fehlt": fehlt,
                          "zustand": (status.get(r["id"]) or {}).get("zustand"), "kurz": ze.kurz(r)})
        return {"ok": True, "items": items, "total": len(items)}

    # =================================================================================================================
    # App

    def app_neu(self, header: dict[str, Any], ack: Any = None) -> dict[str, Any]:
        """ZUKAUF_NEU: Kevins bestätigter Eintrag, sofort ``frei``. ``ack(ok, text)`` geht vor dem ZUKAUF_STATUS
        hinaus (PROTOCOL.md: ``ACK``, danach ``ZUKAUF_STATUS``); ohne CAD sucht der Kernel danach gleich (TraceParts
        bzw. Links → ``wartet_auf_cad``)."""
        felder = dict(header.get("felder") or {})
        eingabe = header.get("eingabe")
        kind = ze.eingabe_art(eingabe)
        res = self.anlegen(url=eingabe if kind == "url" and not felder.get("url") else None,
                           gtin=eingabe if kind == "gtin" and not felder.get("gtin") else None,
                           felder=felder, ebene=str(header.get("ebene") or "projekt"), proposal=False,
                           status_senden=False)
        if res.get("ok") and not res.get("angelegt"):
            res = {"ok": False, "error": res.get("text")}
        if ack is not None:
            ack(bool(res.get("ok")), res.get("text", "") if res.get("ok") else str(res.get("error", "")))
        if res.get("ok"):
            item = res["item"]
            self._status(item["id"], "angelegt", res["text"], name=item.get("name"))
            if ze.cad_art(item) == "vereinfacht":
                self.suchen(item["id"])
            self.rt._rerun_after_catalog_change()
        return res

    def app_download_seen(self, header: dict[str, Any]) -> None:
        pfad = header.get("pfad")
        if not isinstance(pfad, str) or not pfad:
            return
        with self._lock:
            self._seen = [s for s in self._seen if s["pfad"] != pfad][-(MAX_SEEN - 1):]
            self._seen.append({"pfad": pfad, "groesse": header.get("groesse"), "zeit": header.get("zeit")})

    def app_cad(self, header: dict[str, Any]) -> dict[str, Any]:
        return self.uebernehmen(str(header.get("teil") or ""), str(header.get("pfad") or "") or None)

    @property
    def gesehen(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._seen)

"""Anbindung der Zeichnungs-Engine an die Kernel-Laufzeit (Mixin für ``KernelRuntime``).

- Dateien: ``<projekt>/dokumente/zeichnungen/<id>.json`` lesen und schreiben (dokument.py).
- Nach jedem erfolgreichen Lauf (und beim Verbinden der App): alle Blätter neu rechnen (Projektionen und Merkmale
  liegen je Formstand im Zwischenspeicher, unveränderte Teile kosten fast nichts), Bezüge neu zuordnen, geänderte Blätter
  speichern, ``DOCS`` an die App.
- App: ``DRAWING_REQ`` → ``DRAWING``; ``DRAWING_EDIT`` → ``ACK``, danach ``DRAWING``.
- MCP (über ``KernelService``): ``drawings``, ``drawing_create``, ``drawing_edit``, ``drawing_image``.

OCCT-Arbeit läuft unter ``_occ_lock`` der Laufzeit (nacheinander mit Messen und Export), die Blätter unter einer
eigenen Sperre, damit ein Lauf und eine Bearbeitung nicht gleichzeitig dieselbe Datei schreiben.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.zeichnung import dokument as dok

STUECKLISTEN_ARTEN_NICHT = ("schraube", "mutter", "scheibe", "kamera", "objektiv", "kamerazubehoer")


class ZeichnungRuntimeMixin:
    """Erwartet von der Laufzeit: ``scene``, ``catalog``, ``_project``, ``_bom``, ``_run_no``, ``_lock``,
    ``_occ_lock``, ``_pool``, ``_send_app``, ``_log``."""

    # -- Zustand -------------------------------------------------------------------------------------------------------

    def _zeichnung_init(self) -> None:
        self._z_lock = threading.RLock()
        self._z_cache: dict[str, Any] = {}  # Blatt-id → Ergebnis (zeichner.Ergebnis) des letzten Rechnens
        self._z_docs: dict[str, Any] | None = None
        self._z_stand_run = 0
        self._z_cache_version: dict[str, str | None] = {}  # Blatt-id → Version im Schriftfeld des Ergebnisses
        self._z_cache_eingang: dict[str, Any] = {}  # Blatt-id → Datei, aus der das Ergebnis gerechnet wurde
        self._z_ausgelassen = 0  # Blätter, die eine überholte Hintergrundrechnung nicht gespeichert hat
        self._z_regler_lauf: int | None = None  # letzter Lauf mit überschriebenen Parametern (Szene ≠ Dateien)

    def _zeichnung_schliessen(self) -> None:
        from kevcad_kernel.zeichnung.projektion import EXAKT

        EXAKT.schliessen()

    def _zeichnung_projekt(self) -> None:
        with self._z_lock:
            self._z_cache.clear()
            self._z_cache_version.clear()
            self._z_cache_eingang.clear()
            self._z_docs = None

    def _z_szene_ist_dateistand(self) -> bool:
        """Zeigt die Szene den Stand der Dateien? Nicht nach einem Lauf mit überschriebenen Parametern (Regler,
        ``run(params=…)``): Blätter dazu werden gerechnet und gezeigt, aber nicht gespeichert (die Versionen erfassen
        ``dokumente/``, und die Bezüge sollen zum Stand von model.py passen)."""
        with self._lock:
            return self._z_regler_lauf is None or self._z_regler_lauf != self._run_no

    def _z_bearbeitet(self) -> None:
        """Kevin oder der Agent ändert Blätter: den Versionen melden (eigene Version beim nächsten Lauf)."""
        hook = getattr(self, "_versionen_dokumente_bearbeitet", None)
        if callable(hook):
            hook()

    def _z_ordner(self) -> Path | None:
        proj = getattr(self, "_project", None)
        return dok.ordner(proj.path) if proj is not None else None

    # -- Szene ---------------------------------------------------------------------------------------------------------

    def _z_szene(self) -> Any:
        from kevcad_kernel.zeichnung.szene import Szene, Teil

        teile = {}
        for rec in self.scene.records():
            if rec.name.startswith("Skizze/"):
                continue
            st = rec.header.get("stock") or {}
            kat = None
            if st.get("id"):
                try:
                    kat = self.catalog.item(str(st["id"]))
                except Exception:  # noqa: BLE001
                    kat = None
            teile[rec.name] = Teil(rec.name, rec.shape, rec.key, rec.header, kat)
        with self._lock:
            bom = self._bom
            run = self._run_no
        proj = self._project
        info = {"name": proj.name if proj else "", "pfad": str(proj.path) if proj else "",
                "version": self._z_version(run), "datum": _dt.date.today().isoformat()}
        return Szene(teile, bom, info, run)

    def _z_version(self, run: int) -> str | None:
        """Version für das Schriftfeld (nur zur Darstellung, nie gespeichert): die Version, zu der Lauf ``run`` gehört,
        vom Versions-Strang (``versionen_info``), mit Meilenstein „V12 „Prototyp““ und in einer Variante „V12 (Flacher
        Rand)“; ohne Versionen die Zahl der gespeicherten Stände des Projekts."""
        hook = getattr(self, "versionen_info", None)
        if callable(hook):
            try:
                info = hook(run) or {}
                text = info.get("version")
                if text:
                    ms = info.get("meilenstein")
                    return f"{text} „{ms}“" if ms else str(text)
            except Exception:  # noqa: BLE001
                pass
        proj = self._project
        if proj is None:
            return None
        try:
            n = len(list(proj.versions_dir.glob("*-model.py")))
        except OSError:
            n = 0
        return f"Stand {n}" if n else f"Lauf {run}"

    # -- Rechnen -------------------------------------------------------------------------------------------------------

    def _z_rechne(self, blatt: dict[str, Any], szene: Any, speichern: bool = True, lauf: int | None = None) -> Any:
        """Blatt rechnen und speichern. ``lauf``: Hintergrundrechnung dieses Laufs; sie speichert nur, solange er der
        neueste ist (``_lauf_aktuell`` der Versionen), sonst gehörte das Blatt zu einem überholten Stand (gezählt in
        ``_z_ausgelassen``)."""
        from kevcad_kernel.zeichnung.hausregeln import laden
        from kevcad_kernel.zeichnung.zeichner import rechne

        proj = self._project
        ordner = self._z_ordner()
        regeln, fehler = laden(proj.path if proj is not None else None)
        with self._occ_lock:
            erg = rechne(blatt, szene, regeln=regeln)
        if fehler:
            erg.hinweise.append(fehler)
        aktuell = getattr(self, "_lauf_aktuell", None)
        darf = not callable(aktuell) or lauf is None or aktuell(lauf)
        if speichern and ordner is not None and darf and ordner == self._z_ordner():
            try:
                dok.speichere(ordner / f"{erg.blatt['id']}.json", erg.blatt)
            except OSError as exc:
                self._log(f"[zeichnung] Blatt {erg.blatt['id']} nicht gespeichert: {exc}")
        elif speichern and not darf:
            self._z_ausgelassen += 1
        with self._z_lock:
            self._z_cache[erg.blatt["id"]] = erg
            self._z_cache_version[erg.blatt["id"]] = (szene.projekt or {}).get("version")
            self._z_cache_eingang[erg.blatt["id"]] = dok.zum_speichern(blatt)
        return erg

    def _z_alle_rechnen(self, speichern: bool = True, lauf: int | None = None) -> list[tuple[Path, Any, str | None]]:
        ordner = self._z_ordner()
        if ordner is None:
            return []
        out = []
        szene = None
        for pfad, blatt, fehler in dok.alle(ordner.parent.parent):
            if blatt is None:
                out.append((pfad, None, fehler))
                continue
            if szene is None:
                szene = self._z_szene()
            try:
                out.append((pfad, self._z_rechne(blatt, szene, speichern=speichern, lauf=lauf), None))
            except Exception as exc:  # noqa: BLE001 - ein kaputtes Blatt darf die anderen nicht aufhalten
                import traceback

                self._log(f"[zeichnung] {pfad.name}: {traceback.format_exc(limit=6)}")
                out.append((pfad, None, f"{type(exc).__name__}: {exc}"))
        return out

    def _z_docs_bauen(self, ergebnisse: list[tuple[Path, Any, str | None]], run: int) -> dict[str, Any]:
        blaetter = []
        for pfad, erg, fehler in ergebnisse:
            if erg is None:
                blaetter.append({"id": pfad.stem, "titel": pfad.stem, "inhalt": None, "format": None,
                                 "verwaiste_masse": 0, "fehler": fehler})
                continue
            b = erg.blatt
            blaetter.append({"id": b["id"], "titel": b["titel"], "inhalt": b["inhalt"], "format": b["format"],
                             "ausrichtung": b["ausrichtung"], "massstab": b["massstab"],
                             "verwaiste_masse": sum(1 for m in b["masse"] if m.get("verwaist")),
                             "masse": len(b["masse"]), "stand": erg.kopf.get("stand"),
                             "hinweise": list(erg.hinweise or []),
                             "pruefung": len(erg.kopf.get("pruefung") or [])})
        bauplan = None
        hook = getattr(self, "_bauplan_docs", None)  # Strang P6-B
        if callable(hook):
            try:
                bauplan = hook()
            except Exception:  # noqa: BLE001
                bauplan = None
        return {"type": "DOCS", "run": run, "blaetter": blaetter, "bauplan": bauplan}

    def _zeichnung_nach_lauf(self, run: int, speichern: bool = True) -> Any:
        """Nach RUN_END: im Hintergrund alle Blätter neu rechnen und DOCS schicken. ``speichern`` False (Lauf mit
        überschriebenen Parametern): nur rechnen und zeigen, die Dateien bleiben beim Stand von model.py. Rückgabe:
        Future (Ergebnis True, wenn alles gespeichert ist, was zu speichern war) oder None ohne Blätter."""
        with self._lock:
            self._z_regler_lauf = None if speichern else run
        ordner = self._z_ordner()
        if ordner is None or not ordner.is_dir() or not any(ordner.glob("*.json")):
            return None
        return self._pool.submit(self._z_nach_lauf_job, run, speichern)

    def _z_nach_lauf_job(self, run: int, speichern: bool = True) -> bool:
        try:
            t0 = time.perf_counter()
            with self._z_lock:
                self._z_ausgelassen = 0
                ergebnisse = self._z_alle_rechnen(speichern=speichern, lauf=run)
                vollstaendig = speichern and self._z_ausgelassen == 0
                docs = self._z_docs_bauen(ergebnisse, run)
                self._z_docs = docs
            self._send_app(docs)
            self._log(f"[zeichnung] {len(ergebnisse)} Blätter nach Lauf {run} in "
                      f"{(time.perf_counter() - t0) * 1000:.0f} ms" + ("" if speichern else " (nicht gespeichert)"))
            return vollstaendig
        except Exception as exc:  # noqa: BLE001
            self._log(f"[zeichnung] nach Lauf {run}: {exc!r}")
            return True

    def _zeichnung_on_connect(self, conn: Any) -> None:
        with self._z_lock:
            docs = self._z_docs
        if docs is not None:
            conn.send(docs)

    # -- App -----------------------------------------------------------------------------------------------------------

    def _zeichnung_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind == "DRAWING_REQ":
            self._pool.submit(self._z_app_req, header)
            return True
        if kind == "DRAWING_EDIT":
            self._pool.submit(self._z_app_edit, header)
            return True
        if kind == "DRAWING_CREATE":  # Vertrag 1.2
            self._pool.submit(self._z_app_create, header)
            return True
        if kind == "DOCS_REQ":
            self._pool.submit(self._z_app_docs, header)
            return True
        return False

    def _z_app_req(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        res = self.drawing(str(header.get("blatt") or ""))
        if not res.get("ok"):
            self._send_app({"type": "ERROR", "reply_to": rid, "message": res.get("error", "Blatt nicht gerechnet")})
            return
        self._send_app({"type": "DRAWING", "reply_to": rid, **res["kopf"]}, res["nutzlast"])

    def _z_app_edit(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        res = self.drawing_edit(str(header.get("blatt") or ""), list(header.get("ops") or []),
                                str(header.get("von") or "kevin"), melden=False)
        fehler = [e for e in res.get("ergebnisse") or [] if not e.get("ok")]
        ok = bool(res.get("ok")) and not fehler
        message = res.get("error") or "; ".join(f"{e['op']}: {e.get('fehler')}" for e in fehler)
        self._send_app({"type": "ACK", "reply_to": rid, "ok": ok, "message": message,
                        "ergebnisse": res.get("ergebnisse") or []})
        erg = self._z_cache.get(str(header.get("blatt") or ""))
        if erg is not None:
            self._send_app({"type": "DRAWING", **erg.kopf}, erg.nutzlast)
            self._send_app(self._z_docs_aktuell())  # Übersicht (Maße, verwaiste) passt zum bearbeiteten Blatt

    def _z_app_create(self, header: dict[str, Any]) -> None:
        """DRAWING_CREATE (Vertrag 1.2): ``drawing_create``, dann ACK und DOCS mit ``reply_to``."""
        rid = header.get("id")
        teile = header.get("teile")
        try:
            res = self.drawing_create(list(teile) if teile else None, str(header.get("art") or "teil"),
                                      header.get("format"), melden=False)
        except Exception as exc:  # noqa: BLE001 - z. B. unbekanntes Format
            res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        fehler = [b for b in res.get("blaetter") or [] if not b.get("ok")]
        message = res.get("error") or "; ".join(f"{b['id']}: {b.get('fehler')}" for b in fehler)
        self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")), "message": message,
                        "blaetter": [b.get("id") for b in res.get("blaetter") or [] if b.get("ok")]})
        if res.get("ok"):
            with self._z_lock:
                docs = self._z_docs
            self._send_app({**(docs or self._z_docs_aktuell()), "reply_to": rid})

    def _z_docs_aktuell(self) -> dict[str, Any]:
        """DOCS aus den zuletzt gerechneten Blättern (ungerechnete werden gerechnet), ohne alle neu zu rechnen."""
        ordner = self._z_ordner()
        ergebnisse: list[tuple[Path, Any, str | None]] = []
        with self._z_lock:
            for pfad, blatt, fehler in dok.alle(ordner.parent.parent) if ordner is not None else []:
                if blatt is None:
                    ergebnisse.append((pfad, None, fehler))
                    continue
                erg = self._z_cache.get(blatt["id"])
                if erg is None:
                    res = self.drawing(blatt["id"])
                    erg, fehler = res.get("ergebnis"), res.get("error")
                ergebnisse.append((pfad, erg, fehler))
            docs = self._z_docs_bauen(ergebnisse, self._run_no)
            self._z_docs = docs
        return docs

    def _z_melden(self, ergebnisse: list[Any]) -> None:
        """Änderungen über MCP (Vertrag 1.2) sofort an die App: DOCS und DRAWING je geändertem Blatt."""
        link = getattr(self, "_link", None)
        if link is not None and not link.connected:
            return
        self._send_app(self._z_docs_aktuell())
        for erg in ergebnisse:
            if erg is not None:
                self._send_app({"type": "DRAWING", **erg.kopf}, erg.nutzlast)

    def _z_app_docs(self, header: dict[str, Any]) -> None:
        with self._z_lock:
            ergebnisse = self._z_alle_rechnen(speichern=self._z_szene_ist_dateistand())
            docs = self._z_docs_bauen(ergebnisse, self._run_no)
            self._z_docs = docs
        self._send_app({**docs, "reply_to": header.get("id")})

    # -- KernelService: Zeichnungen ------------------------------------------------------------------------------------

    def drawings(self) -> dict[str, Any]:
        ordner = self._z_ordner()
        if ordner is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        out = []
        for pfad, blatt, fehler in dok.alle(ordner.parent.parent):
            if blatt is None:
                out.append({"id": pfad.stem, "fehler": fehler, "pfad": str(pfad)})
                continue
            erg = self._z_cache.get(blatt["id"])
            out.append({"id": blatt["id"], "titel": blatt["titel"], "inhalt": blatt["inhalt"],
                        "format": blatt["format"], "ausrichtung": blatt["ausrichtung"], "massstab": blatt["massstab"],
                        "ansichten": [a.get("art") for a in blatt["ansichten"]], "masse": len(blatt["masse"]),
                        "verwaiste_masse": [m["id"] for m in blatt["masse"] if m.get("verwaist")],
                        "eigene_masse": sum(1 for m in blatt["masse"] if m.get("quelle") in ("kevin", "agent")),
                        "pfad": str(pfad), "hinweise": list(erg.hinweise) if erg is not None else []})
        return {"ok": True, "blaetter": out, "ordner": str(ordner)}

    def drawing(self, blatt_id: str) -> dict[str, Any]:
        """Blatt rechnen (bzw. aus dem Zwischenspeicher, wenn der Stand passt): {"ok", "kopf", "nutzlast", "ergebnis"}"""
        ordner = self._z_ordner()
        if ordner is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        pfad = ordner / f"{blatt_id}.json"
        if not pfad.exists():
            vorhanden = ", ".join(p.stem for p in sorted(ordner.glob("*.json"))) if ordner.is_dir() else ""
            return {"ok": False, "error": f"Blatt {blatt_id!r} gibt es nicht" + (f" (vorhanden: {vorhanden})"
                                                                                 if vorhanden else
                                                                                 "; erst zeichnung_erstellen")}
        try:
            blatt = dok.lade(pfad)
        except dok.BlattFehler as exc:
            return {"ok": False, "error": str(exc)}
        with self._z_lock:
            erg = self._z_cache.get(blatt_id)
            datei = dok.zum_speichern(blatt)
            # neu rechnen, wenn ein neuer Lauf kam, die Datei nicht mehr dazu passt (weder Ergebnis noch Eingang des
            # Ergebnisses, z. B. von außen bearbeitet) oder sich die Version im Schriftfeld geändert hat (Meilenstein)
            if erg is None or erg.kopf.get("run") != self._run_no or datei not in (
                    dok.zum_speichern(erg.blatt), self._z_cache_eingang.get(blatt_id)) \
                    or self._z_cache_version.get(blatt_id) != self._z_version(self._run_no):
                try:
                    erg = self._z_rechne(blatt, self._z_szene(), speichern=self._z_szene_ist_dateistand())
                except Exception as exc:  # noqa: BLE001
                    import traceback

                    self._log(traceback.format_exc(limit=8))
                    return {"ok": False, "error": f"Blatt {blatt_id} nicht gerechnet: {type(exc).__name__}: {exc}"}
        return {"ok": True, "kopf": erg.kopf, "nutzlast": erg.nutzlast, "ergebnis": erg}

    def drawing_create(self, teile: list[str] | None = None, art: str = "teil", format: str | None = None,
                       *, melden: bool = True) -> dict[str, Any]:  # noqa: A002
        """Blätter anlegen (bestehende bleiben mit Kevins Änderungen erhalten und werden neu gerechnet). Ohne ``teile``:
        je Stücklistenposition eines gefertigten Teils ein Blatt und ein Blatt für den Zusammenbau. ``melden``
        (MCP, Vertrag 1.2): danach DOCS und DRAWING je neuem oder geändertem Blatt an die App; die App selbst
        (DRAWING_CREATE) bekommt ACK und DOCS mit ``reply_to``."""
        ordner = self._z_ordner()
        if ordner is None:
            return {"ok": False, "error": "Kein Projekt offen. Erst project_open oder project_new aufrufen."}
        if art not in ("teil", "baugruppe", "zusammenbau"):
            return {"ok": False, "error": f"art {art!r} unbekannt (teil, baugruppe, zusammenbau)"}
        fmt, ausr = _format(format)
        szene = self._z_szene()
        if not szene.teile:
            return {"ok": False, "error": "Keine Teile: erst run aufrufen."}
        self._z_bearbeitet()
        plaene: list[tuple[str, str, str, list[str]]] = []  # (id, titel, art, teile)
        if teile:
            unbekannt = [t for t in teile if not szene.auswahl([t])]
            if unbekannt:
                from kevcad_kernel.refs import unknown_part_message

                return {"ok": False, "error": unknown_part_message(unbekannt[0], szene.namen())}
            if art == "teil":
                for t in teile:
                    for teil in szene.auswahl([t]):
                        titel = _titel(teil.name)
                        plaene.append((dok.kennung(titel), titel, "teil", [teil.name]))
            else:
                titel = teile[0].rsplit("/", 1)[-1] if len(teile) == 1 else "Baugruppe"
                plaene.append((dok.kennung(titel), titel, art, list(teile)))
        elif art == "zusammenbau":
            plaene.append(("zusammenbau", "Zusammenbau", "zusammenbau", []))
        else:
            gesehen: set[str] = set()
            for name, t in szene.teile.items():
                if name in gesehen or not t.gefertigt:
                    continue
                gruppe = [n for n in szene.gleiche_teile(name) if n in szene.teile]
                gesehen.update(gruppe)
                titel = _titel(name)
                plaene.append((dok.kennung(titel), titel, "teil", [name]))
            plaene.append(("zusammenbau", "Zusammenbau", "zusammenbau", []))
        ergebnisse = []
        geaendert: list[Any] = []
        vorhanden = {p.stem for p in ordner.glob("*.json")} if ordner.is_dir() else set()
        nummer = len(vorhanden)
        kurz = "".join(w[0] for w in (szene.projekt.get("name") or "KC").replace("-", " ").split() if w)[:4].upper()
        with self._z_lock:
            stand_vorher = {k: e.kopf.get("stand") for k, e in self._z_cache.items()}
            for bid, titel, b_art, b_teile in plaene:
                pfad = ordner / f"{bid}.json"
                neu = not pfad.exists()
                try:
                    if neu:
                        nummer += 1
                        blatt = dok.neu(bid, titel, b_art, b_teile, fmt=fmt, ausrichtung=ausr)
                        blatt["schriftfeld"]["zeichnungsnummer"] = f"{kurz or 'KC'}-{nummer:03d}"
                    else:
                        blatt = dok.lade(pfad)
                    erg = self._z_rechne(blatt, szene)
                except Exception as exc:  # noqa: BLE001
                    import traceback

                    self._log(traceback.format_exc(limit=8))
                    ergebnisse.append({"id": bid, "ok": False, "fehler": f"{type(exc).__name__}: {exc}"})
                    continue
                ergebnisse.append(_zusammenfassung(erg, neu))
                if neu or erg.kopf.get("stand") != stand_vorher.get(bid):
                    geaendert.append(erg)
            alle = [(ordner / f"{e['id']}.json", self._z_cache.get(e["id"]), e.get("fehler")) for e in ergebnisse]
            self._z_docs = self._z_docs_bauen(alle if not vorhanden else self._z_alle_rechnen(), szene.run)
            docs = self._z_docs
        if melden:
            self._send_app(docs)
            for erg in geaendert:
                self._send_app({"type": "DRAWING", **erg.kopf}, erg.nutzlast)
        return {"ok": any(e.get("ok") for e in ergebnisse), "blaetter": ergebnisse, "ordner": str(ordner)}

    def drawing_edit(self, blatt_id: str, ops: list[dict[str, Any]], von: str = "agent", *,
                     melden: bool = True) -> dict[str, Any]:
        """Operationen auf ein Blatt (wie DRAWING_EDIT). ``melden`` (MCP, Vertrag 1.2): danach DOCS und DRAWING an
        die App; die App selbst (DRAWING_EDIT) bekommt ACK und danach DRAWING aus ``_z_app_edit``."""
        from kevcad_kernel.zeichnung.bearbeiten import anwenden

        res = self.drawing(blatt_id)
        if not res.get("ok"):
            return res
        erg = res["ergebnis"]
        self._z_bearbeitet()
        with self._z_lock:
            blatt, ergebnisse = anwenden(erg.blatt, ops, von, erg)
            try:
                neu = self._z_rechne(blatt, self._z_szene())
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"Blatt nach der Bearbeitung nicht gerechnet: {type(exc).__name__}: "
                                              f"{exc}", "ergebnisse": ergebnisse}
        if melden and any(e.get("ok") for e in ergebnisse):
            self._z_melden([neu])
        return {"ok": True, "ergebnisse": ergebnisse, "blatt": _zusammenfassung(neu, False)}

    def drawing_image(self, blatt_id: str, breite: int = 1800) -> dict[str, Any]:
        from kevcad_kernel.zeichnung.bild import png

        res = self.drawing(blatt_id)
        if not res.get("ok"):
            return res
        erg = res["ergebnis"]
        try:
            daten = png(erg.kopf, erg.nutzlast, int(breite))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Bild nicht erzeugt: {exc}"}
        W, H = erg.kopf.get("blattgroesse") or [297, 210]
        return {"ok": True, "png": daten, "breite": int(breite), "hoehe": int(round(int(breite) * H / W)),
                "blatt": _zusammenfassung(erg, False)}


def _format(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    t = str(text).strip().replace("_", " ").split()
    fmt = t[0].upper()
    if fmt not in dok.FORMATE:
        raise ValueError(f"Format {text!r} unbekannt (A4, A3 …, optional „quer“/„hoch“)")
    ausr = t[1].lower() if len(t) > 1 and t[1].lower() in ("quer", "hoch") else "quer"
    return fmt, ausr


def _titel(name: str) -> str:
    return name.rsplit("/", 1)[-1].strip()


def _zusammenfassung(erg: Any, neu: bool) -> dict[str, Any]:
    b = erg.blatt
    masse = []
    for m, k in zip(b["masse"], erg.kopf.get("masse") or []):
        masse.append({"id": m["id"], "art": m["art"], "ansicht": m.get("ansicht"), "text": k.get("text"),
                      "wert": k.get("wert"), "quelle": m.get("quelle"), "verwaist": bool(m.get("verwaist")),
                      "bezuege": [x.get("merkmal") or x.get("ref") for x in m.get("bezuege") or []]})
    return {"id": b["id"], "ok": True, "neu": neu, "titel": b["titel"], "inhalt": b["inhalt"],
            "format": f"{b['format']} {b['ausrichtung']}", "massstab": b["massstab"],
            "ansichten": [{"id": a["id"], "art": a["art"]} for a in b["ansichten"]],
            "masse": masse, "verwaist": [m["id"] for m in b["masse"] if m.get("verwaist")],
            "allgemein": list(b.get("allgemein") or []), "hinweise": list(erg.hinweise or []),
            "pruefung": list(erg.kopf.get("pruefung") or []), "ms": round(erg.ms, 1)}

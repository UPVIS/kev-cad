"""Bauplan als Teil der Kernel-Laufzeit (Mischklasse für ``KernelRuntime``).

- MCP (KernelService, additiv): ``bauplan(neu)``, ``bauplan_bearbeiten(ops, von)``, ``bauplan_pruefen(schritt)``.
- App: ``BAUPLAN_REQ`` → ``BAUPLAN``; ``BAUPLAN_EDIT`` und ``BAUPLAN_PRUEFEN`` → ``ACK``, danach ``BAUPLAN``.
- Nach jedem Lauf: gibt es ``dokumente/bauplan.json``, rechnet der Bauplan im Hintergrund neu (nach der Prüfung, weil
  er deren Gewindeeingriffe braucht), speichert und meldet ``DOCS``. Beim Verbinden geht das letzte ``DOCS`` mit.
- ``DOCS`` ist gemeinsam mit den Zeichnungen (P6-Z): die Blätter holt ``_docs_blaetter()``, wenn die Laufzeit sie
  anbietet (Strang P6-Z), sonst ist die Liste leer.

Gerechnet wird im Elternprozess auf eigenen Kopien der Formen (aus der BRep der Szene), nacheinander unter einer
eigenen Sperre; ein neuerer Lauf verwirft ein veraltetes Ergebnis.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from kevcad_kernel.bauplan import datei
from kevcad_kernel.bauplan.datei import BearbeitungsFehler


class BauplanDienst:
    """Mischklasse für KernelRuntime (nutzt ``_project``, ``scene``, ``_bom``, ``_constraints``, ``_pruef``,
    ``catalog``, ``_pool``, ``_send_app``, ``_log``)."""

    # -- Zustand (ohne __init__, damit die Laufzeit nichts aufrufen muss) -------------------------------------------

    def _bp(self) -> dict[str, Any]:
        st = getattr(self, "_bp_stand", None)
        if st is None:
            st = {"lock": threading.RLock(), "erg": None, "run": None, "pfad": None, "docs": None, "laeuft": None}
            self._bp_stand = st
        return st

    def _bp_run(self) -> int | None:
        bom = getattr(self, "_bom", None)
        return int(bom["run"]) if isinstance(bom, dict) and bom.get("run") else None

    # -- Erzeugen --------------------------------------------------------------------------------------------------

    def _bp_eingang(self, warten_s: float = 120.0):
        from kevcad_kernel.bauplan.eingang import sammle

        proj = self._project  # type: ignore[attr-defined]
        run = self._bp_run()
        if proj is None:
            raise RuntimeError("Kein Projekt offen. Erst project_open oder project_new aufrufen.")
        if run is None:
            raise RuntimeError("Noch kein erfolgreicher Lauf: erst run aufrufen.")
        check = self._pruef.warte(run, warten_s)  # type: ignore[attr-defined]
        if check is None or check.get("state") not in ("done", "failed"):
            check, _ = self._pruef.letztes()  # type: ignore[attr-defined]
        alt = datei.laden(proj.path)
        return sammle(self.scene.records(), bom=self._bom, bedingungen=self._constraints,  # type: ignore[attr-defined]
                      check=check, katalog=self.catalog, titel=proj.name, run=run,  # type: ignore[attr-defined]
                      projekt=proj.path, umfang=(alt or {}).get("umfang")), alt

    def _bp_erzeugen(self, erzwingen: bool = False):
        from kevcad_kernel.bauplan.plan import erzeuge

        st = self._bp()
        with st["lock"]:
            proj = self._project  # type: ignore[attr-defined]
            run = self._bp_run()
            erg = st["erg"]
            if (not erzwingen and erg is not None and st["run"] == run and proj is not None
                    and st["pfad"] == str(proj.path)):
                return erg
            ein, alt = self._bp_eingang()
            erg = erzeuge(ein, alt)
            if self._bp_run() != run:  # ein neuerer Lauf kam dazwischen: nicht speichern
                return erg
            datei.speichern(proj.path, erg.plan)
            st.update(erg=erg, run=run, pfad=str(proj.path), docs=datei.zusammenfassung(erg.plan))
            return erg

    def _bp_speichern(self, erg: Any) -> None:
        st = self._bp()
        proj = self._project  # type: ignore[attr-defined]
        if proj is not None:
            datei.speichern(proj.path, erg.plan)
        st["docs"] = datei.zusammenfassung(erg.plan)

    # -- MCP -------------------------------------------------------------------------------------------------------

    def bauplan(self, neu: bool = False) -> dict[str, Any]:
        """Bauplan des letzten Laufs (erzeugt ihn bei Bedarf, ``neu``: auf jeden Fall neu rechnen; Feste und Texte von
        Agent und Kevin bleiben). {"ok", "datei", "bauplan", "zusammenfassung", "zeiten"}"""
        try:
            erg = self._bp_erzeugen(erzwingen=neu)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            import traceback

            self._log(traceback.format_exc())  # type: ignore[attr-defined]
            return {"ok": False, "error": f"Bauplan nicht erzeugt: {type(exc).__name__}: {exc}"}
        self._bp_docs_senden()
        proj = self._project  # type: ignore[attr-defined]
        return {"ok": True, "datei": str(datei.pfad(proj.path)) if proj else None, "bauplan": erg.plan,
                "zusammenfassung": datei.zusammenfassung(erg.plan), "zeiten": erg.zeiten}

    def bauplan_bearbeiten(self, ops: list[dict[str, Any]], von: str = "agent") -> dict[str, Any]:
        """Operationen wie BAUPLAN_EDIT; danach Simulation neu. {"ok", "meldungen", "zusammenfassung", "befunde"}"""
        from kevcad_kernel.bauplan.plan import bilder_setzen, erzeuge, pruefe

        st = self._bp()
        with st["lock"]:
            try:
                erg = self._bp_erzeugen()
            except RuntimeError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                meldungen, neu = datei.bearbeiten(erg.plan, list(ops or []), von)
            except BearbeitungsFehler as exc:
                return {"ok": False, "error": f"Bauplan nicht geändert: {exc}"}
            if neu:  # Umfang oder Reihenfolge-Regel: Gerüst neu mit dem bearbeiteten Plan als Vorlage
                ein, _ = self._bp_eingang(1.0)
                erg = erzeuge(ein, erg.plan)
            else:
                bilder_setzen(erg.ein, erg.plan)
                pruefe(erg)
            st.update(erg=erg)
            self._bp_speichern(erg)
        self._bp_senden(None)
        befunde = [b for _, s in datei.alle_schritte(erg.plan) for b in s.get("pruefung") or []]
        return {"ok": True, "meldungen": meldungen, "zusammenfassung": datei.zusammenfassung(erg.plan),
                "befunde": befunde}

    def bauplan_pruefen(self, schritt: str | None = None) -> dict[str, Any]:
        """Simulation neu (alle Schritte oder einer). {"ok", "befunde", "zusammenfassung", "ms"}"""
        from kevcad_kernel.bauplan.plan import pruefe

        st = self._bp()
        with st["lock"]:
            try:
                erg = self._bp_erzeugen()
            except RuntimeError as exc:
                return {"ok": False, "error": str(exc)}
            if schritt is not None and datei.finde(erg.plan, schritt) is None:
                return {"ok": False, "error": f"Schritt {schritt!r} gibt es nicht"}
            t0 = time.perf_counter()
            befunde = pruefe(erg, schritt)
            self._bp_speichern(erg)
        self._bp_senden(None)
        return {"ok": True, "befunde": befunde, "zusammenfassung": datei.zusammenfassung(erg.plan),
                "ms": round((time.perf_counter() - t0) * 1000, 1), "schritt": schritt}

    def bauplan_bilder(self, schritte: list[str] | None = None) -> dict[str, Any]:
        """Strichbilder (Blatt-mm) für die Nachricht BAUPLAN und zur eigenen Prüfung."""
        from kevcad_kernel.bauplan.plan import strichbilder

        st = self._bp()
        with st["lock"]:
            try:
                erg = self._bp_erzeugen()
            except RuntimeError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "bilder": strichbilder(erg, schritte), "run": st["run"]}

    # -- App -------------------------------------------------------------------------------------------------------

    def _bp_senden(self, reply_to: str | None) -> None:
        """BAUPLAN mit Strichbildern an die App."""
        from kevcad_kernel.protocol import pack_bauplan

        link = getattr(self, "_link", None)
        if reply_to is None and (link is None or not link.connected):
            return  # ohne App keine Bilder rechnen
        res = self.bauplan_bilder()
        st = self._bp()
        erg = st["erg"]
        if not res.get("ok") or erg is None:
            if reply_to:
                self._send_app({"type": "ERROR", "reply_to": reply_to,  # type: ignore[attr-defined]
                                "message": res.get("error") or "Kein Bauplan"})
            return
        header, payload = pack_bauplan(erg.plan, res["bilder"], run=st["run"], reply_to=reply_to,
                                       stand=erg.plan.get("stand"))
        header.pop("seq", None)
        self._send_app(header, payload)  # type: ignore[attr-defined]

    def _bp_docs_senden(self) -> None:
        from kevcad_kernel.protocol import pack_docs

        st = self._bp()
        blaetter = []
        quelle = getattr(self, "_docs_blaetter", None)
        if callable(quelle):
            try:
                blaetter = list(quelle() or [])
            except Exception:  # noqa: BLE001
                blaetter = []
        msg = pack_docs(run=self._bp_run(), blaetter=blaetter, bauplan=st.get("docs"))
        msg.pop("seq", None)
        self._send_app(msg)  # type: ignore[attr-defined]

    def _bauplan_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in ("BAUPLAN_REQ", "BAUPLAN_EDIT", "BAUPLAN_PRUEFEN"):
            return False
        self._pool.submit(self._bp_app_anfrage, kind, header)  # type: ignore[attr-defined]
        return True

    def _bp_app_anfrage(self, kind: str, header: dict[str, Any]) -> None:
        rid = header.get("id")
        try:
            if kind == "BAUPLAN_REQ":
                res = self.bauplan()
                if not res.get("ok"):
                    self._send_app({"type": "ERROR", "reply_to": rid, "message": res["error"]})  # type: ignore
                    return
                self._bp_senden(rid)
            elif kind == "BAUPLAN_EDIT":
                res = self.bauplan_bearbeiten(list(header.get("ops") or []), str(header.get("von") or "kevin"))
                self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),  # type: ignore
                                "message": "; ".join(res.get("meldungen") or []) if res.get("ok") else res["error"]})
            elif kind == "BAUPLAN_PRUEFEN":
                res = self.bauplan_pruefen(header.get("schritt"))
                self._send_app({"type": "ACK", "reply_to": rid, "ok": bool(res.get("ok")),  # type: ignore
                                "message": "" if res.get("ok") else res["error"]})
        except Exception as exc:  # noqa: BLE001
            self._send_app({"type": "ERROR", "reply_to": rid, "message": f"{type(exc).__name__}: {exc}"})  # type: ignore

    def _bauplan_nach_lauf(self, run: int, result: dict[str, Any]) -> None:
        """Nach einem erfolgreichen Lauf: vorhandenen Bauplan im Hintergrund neu rechnen und DOCS melden."""
        proj = self._project  # type: ignore[attr-defined]
        if proj is None or not result.get("ok"):
            return
        if not datei.pfad(proj.path).exists():
            self._bp()["docs"] = None
            self._bp_docs_senden()
            return

        def arbeit() -> None:
            try:
                self._bp_erzeugen()
            except Exception as exc:  # noqa: BLE001 - im Hintergrund nur protokollieren
                self._log(f"[kernel] Bauplan nicht erneuert: {type(exc).__name__}: {exc}")  # type: ignore
                return
            if self._bp_run() == run:
                self._bp_docs_senden()

        self._pool.submit(arbeit)  # type: ignore[attr-defined]

    def _bauplan_on_connect(self, conn: Any) -> None:
        from kevcad_kernel.protocol import pack_docs

        st = self._bp()
        if st.get("docs") is None:
            proj = self._project  # type: ignore[attr-defined]
            if proj is not None:
                st["docs"] = datei.zusammenfassung(datei.laden(proj.path))
        msg = pack_docs(run=self._bp_run(), blaetter=[], bauplan=st.get("docs"))
        msg.pop("seq", None)
        conn.send(msg)

    def _bauplan_project_changed(self) -> None:
        st = self._bp()
        with st["lock"]:
            st.update(erg=None, run=None, pfad=None, docs=None)

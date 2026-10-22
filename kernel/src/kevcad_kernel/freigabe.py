"""Freigabe direkt im Projektfenster (Strang „Feinschliff 2“, PROTOCOL.md Abschnitt „Freigabe im Projektfenster“).

Vorschläge von Claude (``stock_define``, ``material_define``, Zukaufteile) gibt nur Kevin frei. Bisher ging das nur im
Lagerkatalog-Fenster; antwortete Kevin einem Agenten im Chat „freigegeben“, passierte nichts. Jetzt öffnet
``freigabe_anfragen(ids, grund)`` in der App den Dialog „Vorschläge freigeben“ im Projektfenster (Vorschau der Daten,
Link, „Freigeben“ je Eintrag und „Alle freigeben“). Der Kernel gibt selbst nichts frei: Er schickt
``FREIGABE_ANFRAGE`` und wartet, bis Kevin entschieden (alle Einträge frei oder abgelehnt) oder den Dialog geschlossen
hat (``FREIGABE_GESCHLOSSEN``), höchstens ``warten_s``. Was freigegeben ist, liest er aus dem Katalog: Die App gibt wie
im Lagerkatalog über ``CATALOG_SAVE`` mit ``status: "frei"`` frei, ablehnen ist ``CATALOG_DELETE``.

Mixin für ``KernelRuntime``; erwartet ``catalog``, ``_request``, ``_log``.
"""

from __future__ import annotations

import difflib
import itertools
import threading
import time
from typing import Any

from kevcad_kernel.catalog import VORGESCHLAGEN

WARTEN_STANDARD_S = 120.0
WARTEN_MAX_S = 900.0
ANFRAGE_TIMEOUT_S = 10.0


class FreigabeAnbindung:
    """Freigabe im Projektfenster (siehe Moduldoku)."""

    def _freigabe_init(self) -> None:
        self._freigabe_cond = threading.Condition()
        self._freigabe_geschlossen: dict[str, dict[str, Any]] = {}  # Anfrage → Meldung der App
        self._freigabe_nr = itertools.count(1)

    # -- Nachrichten der App -------------------------------------------------------------------------------------------

    def _freigabe_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        """``FREIGABE_GESCHLOSSEN``: Kevin hat den Dialog geschlossen (die Antwort auf die Anfrage steht fest)."""
        if kind != "FREIGABE_GESCHLOSSEN":
            return False
        anfrage = str(header.get("anfrage") or "")
        with self._freigabe_cond:
            self._freigabe_geschlossen[anfrage] = dict(header)
            self._freigabe_cond.notify_all()
        return True

    def _freigabe_katalog_geaendert(self) -> None:
        """Nach CATALOG_SAVE oder CATALOG_DELETE der App: wartende Anfragen prüfen neu."""
        with self._freigabe_cond:
            self._freigabe_cond.notify_all()

    # -- Katalog -------------------------------------------------------------------------------------------------------

    def _freigabe_eintrag(self, eid: str) -> tuple[str, dict[str, Any]] | None:
        """(kind, Eintrag) für eine id: zuerst Lagerteil, dann Material."""
        it = self.catalog.item(eid)  # type: ignore[attr-defined]
        if it is not None:
            return "teil", it
        mat = self.catalog.material(eid)  # type: ignore[attr-defined]
        if mat is not None:
            return "material", mat
        return None

    def _freigabe_stand(self, eintraege: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Je Eintrag: freigegeben (jetzt frei), abgelehnt (nicht mehr im Katalog) oder offen (weiter vorgeschlagen)."""
        out: dict[str, list[str]] = {"freigegeben": [], "abgelehnt": [], "offen": []}
        for e in eintraege:
            eid, kind = e["id"], e["kind"]
            now = self.catalog.item(eid) if kind == "teil" else self.catalog.material(eid)  # type: ignore[attr-defined]
            if now is None:
                out["abgelehnt"].append(eid)
            elif now.get("status") == VORGESCHLAGEN:
                out["offen"].append(eid)
            else:
                out["freigegeben"].append(eid)
        return out

    # -- MCP -----------------------------------------------------------------------------------------------------------

    def freigabe_anfragen(self, ids: list[str], grund: str = "", warten_s: float | None = None) -> dict[str, Any]:
        """Dialog „Vorschläge freigeben“ im Projektfenster öffnen und auf Kevins Entscheidung warten. Gibt nichts selbst
        frei. {"ok", "anfrage", "freigegeben", "abgelehnt", "offen", "schon_frei", "dialog": "entschieden" |
        "geschlossen" | "offen"}"""
        wanted = [str(i).strip() for i in (ids or []) if str(i).strip()]
        wanted = list(dict.fromkeys(wanted))
        if not wanted:
            return {"ok": False, "error": "ids fehlt: die ids der Vorschläge angeben (stock_define, material_define, "
                                          "zukauf_anlegen)"}
        eintraege: list[dict[str, Any]] = []
        schon_frei: list[str] = []
        fehler: list[str] = []
        for eid in wanted:
            found = self._freigabe_eintrag(eid)
            if found is None:
                ids_all = list(self.catalog.item_ids()) + list(self.catalog.material_ids())  # type: ignore[attr-defined]
                close = difflib.get_close_matches(eid, ids_all, n=3, cutoff=0.6)
                fehler.append(f"{eid!r} gibt es im Katalog nicht"
                              + (f" (meinten Sie {', '.join(repr(c) for c in close)}?)" if close else ""))
                continue
            kind, entry = found
            if entry.get("status") != VORGESCHLAGEN:
                schon_frei.append(eid)
                continue
            eintraege.append({"id": eid, "kind": kind, "name": entry.get("name") or eid,
                              "art": entry.get("art") if kind == "teil" else "material",
                              "ebene": entry.get("ebene")})
        if fehler:
            return {"ok": False, "error": "; ".join(fehler), "schon_frei": schon_frei}
        if not eintraege:
            return {"ok": True, "anfrage": None, "freigegeben": [], "abgelehnt": [], "offen": [],
                    "schon_frei": schon_frei, "dialog": "nicht_noetig"}
        anfrage = f"F-{next(self._freigabe_nr):04d}"
        header = {"type": "FREIGABE_ANFRAGE", "anfrage": anfrage, "eintraege": eintraege,
                  "grund": str(grund or "").strip() or None}
        _, _, err = self._request(header, ANFRAGE_TIMEOUT_S)  # type: ignore[attr-defined]
        if err:
            return {"ok": False, "error": f"Dialog nicht geöffnet: {err}", "schon_frei": schon_frei}
        self._log(f"[kernel] Freigabe {anfrage} angefragt: {', '.join(e['id'] for e in eintraege)}")  # type: ignore
        limit = WARTEN_STANDARD_S if warten_s is None else max(0.0, min(float(warten_s), WARTEN_MAX_S))
        ende = time.monotonic() + limit
        dialog = "offen"
        with self._freigabe_cond:
            while True:
                stand = self._freigabe_stand(eintraege)
                if not stand["offen"]:
                    dialog = "entschieden"
                    break
                if anfrage in self._freigabe_geschlossen:
                    dialog = "geschlossen"
                    break
                rest = ende - time.monotonic()
                if rest <= 0:
                    break
                self._freigabe_cond.wait(min(rest, 1.0))
            self._freigabe_geschlossen.pop(anfrage, None)
        return {"ok": True, "anfrage": anfrage, **stand, "schon_frei": schon_frei, "dialog": dialog,
                "gewartet_s": round(limit - max(0.0, ende - time.monotonic()), 1)}

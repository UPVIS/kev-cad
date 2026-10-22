"""Drucken (Phase 8) in der Kernel-Laufzeit: Mixin für ``KernelRuntime`` mit ``KernelService.drucker_status`` und
``KernelService.drucken`` sowie den App-Nachrichten ``PRINTER_CONFIG``, ``PRINTER_STATUS_REQ``, ``PRINT_JOB_REQ`` und
``PRINT_CONTROL`` (DRUCKVORSCHAU.md, „Drucken (Phase 8)“).

Quelle der Platten: die Druckvorschau (``druck_export`` von V-K, Laufzeitmethode wie das MCP-Werkzeug). Fehlt sie,
der Ersatzweg je Material aus den Druckteilen des letzten Laufs (STL, Bambu Studio richtet aus und ordnet an).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kevcad_kernel.drucker.dienst import DruckerDienst, Quelle, QuelleFehler
from kevcad_kernel.drucker.profile import PROZESS_STANDARD, Profile, material_schluessel
from kevcad_kernel.drucker.slicen import hat_projekt_einstellungen

ANFRAGEN = ("PRINTER_CONFIG", "PRINTER_STATUS_REQ", "PRINT_JOB_REQ", "PRINT_CONTROL")
ASK_WARTEN_S = 10.0


class DruckerRuntimeMixin:
    """Erwartet von der Laufzeit: ``_send_app``, ``_request``, ``_pool``, ``_log``, ``_project``, ``_lock``,
    ``_occ_lock``, ``scene``, ``_run_no``."""

    def _drucker_init(self) -> None:
        self._drucker = DruckerDienst(senden=self._send_app, quelle=self._drucker_quelle,  # type: ignore[attr-defined]
                                      log=self._log,  # type: ignore[attr-defined]
                                      ssdp_an=os.environ.get("KEVCAD_DRUCKER_SSDP", "1") != "0",
                                      # Selbsttest: CA der Attrappe (gilt nur für 127.0.0.1)
                                      ca_datei=os.environ.get("KEVCAD_DRUCKER_ATTRAPPE_CA") or None)

    def _drucker_on_connect(self, conn: Any) -> None:
        conn.send({"type": "PRINTER_STATUS", **self._drucker.status()})

    def _drucker_close(self) -> None:
        d = getattr(self, "_drucker", None)
        if d is not None:
            d.stoppen()

    # =================================================================================================================
    # KernelService

    def drucker_status(self) -> dict[str, Any]:
        st = self._drucker.status()
        return {"ok": True, **st}

    def drucken(self, platten: list[int] | None = None, weg: str = "a", grund: str | None = None) -> dict[str, Any]:
        from kevcad_kernel.runtime import NO_PROJECT

        if self._project is None:  # type: ignore[attr-defined]
            return {"ok": False, "error": NO_PROJECT}
        weg = (weg or "a").lower()
        if weg not in ("a", "b"):
            return {"ok": False, "error": f"weg {weg!r} unbekannt (a oder b)"}
        e = self._drucker.eintrag
        if weg == "b" and (e is None or e.weg != "b"):
            return {"ok": False, "error": "Weg B ist nicht eingestellt (Kevin hat Weg A gewählt). Für Weg B müsste "
                                          "Kevin LAN Only Mode und Developer Mode am Drucker einschalten und Weg B "
                                          "in den Drucker-Einstellungen wählen."}
        a = self._drucker.anfragen(platten, weg, grund)
        frage = {"type": "PRINT_JOB_ASK", "auftrag": a.id, "platten": list(a.platten), "weg": a.weg, "von": "agent",
                 "grund": grund}
        reply, _payload, err = self._request(frage, ASK_WARTEN_S)  # type: ignore[attr-defined]
        if err or reply.get("ok") is False:
            self._drucker.verwerfen(a.id)
            return {"ok": False, "error": f"Der Dialog „Drucken …“ ließ sich nicht öffnen: "
                                          f"{err or reply.get('message') or 'abgelehnt'}"}
        return {"ok": True, "auftrag": a.id, "zustand": "wartet", "weg": a.weg, "platten": list(a.platten),
                "meldung": "Der Dialog „Drucken …“ ist in Kev CAD offen. Es geschieht nichts, bis Kevin dort "
                           "bestätigt; den Stand zeigt drucker_status."}

    # =================================================================================================================
    # App

    def _drucker_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in ANFRAGEN:
            return False
        self._pool.submit(self._drucker_anfrage_sicher, header)  # type: ignore[attr-defined]
        return True

    def _drucker_anfrage_sicher(self, header: dict[str, Any]) -> None:
        rid = header.get("id")
        try:
            self._drucker_anfrage(header)
        except Exception as exc:  # noqa: BLE001
            self._send_app({"type": "ERROR", "reply_to": rid,  # type: ignore[attr-defined]
                            "message": f"{type(exc).__name__}: {exc}"})

    def _drucker_anfrage(self, header: dict[str, Any]) -> None:
        kind = header.get("type")
        rid = header.get("id")
        send = self._send_app  # type: ignore[attr-defined]
        if kind == "PRINTER_CONFIG":
            ok, text = self._drucker.konfigurieren(header.get("drucker"))
            send({"type": "ACK", "reply_to": rid, "ok": ok, "message": text})
        elif kind == "PRINTER_STATUS_REQ":
            send({"type": "PRINTER_STATUS", "reply_to": rid, **self._drucker.status()})
        elif kind == "PRINT_JOB_REQ":
            if self._project is None:  # type: ignore[attr-defined]
                send({"type": "ACK", "reply_to": rid, "ok": False, "message": "Kein Projekt offen"})
                return
            ok, text = self._drucker.auftrag_anfordern(header, send)
            send({"type": "ACK", "reply_to": rid, "ok": ok, "message": text})
        elif kind == "PRINT_CONTROL":
            aktion = str(header.get("aktion") or "")
            if aktion == "verwerfen":
                ok, text = self._drucker.verwerfen(header.get("auftrag"))
            else:
                ok, text = self._drucker.steuern(aktion)
            send({"type": "ACK", "reply_to": rid, "ok": ok, "message": text})

    # =================================================================================================================
    # Quelle der Platten

    def _drucker_quelle(self, platten: list[int], ordner: Path) -> Quelle:
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            from kevcad_kernel.runtime import NO_PROJECT

            raise QuelleFehler(NO_PROJECT)
        from kevcad_kernel.export import safe_name

        basis = safe_name(proj.name)
        name = f"{basis}-platten" if not platten else f"{basis}-platte-{'-'.join(str(p) for p in platten)}"
        export = getattr(self, "druck_export", None)
        if callable(export):
            res = export(ziel=str(ordner / f"{name}.3mf"), platten=list(platten))
            if not res.get("ok"):
                raise QuelleFehler(res.get("fehler") or res.get("error") or "Druckvorschau: Export fehlgeschlagen")
            pfad = Path(str(res.get("pfad")))
            mit = hat_projekt_einstellungen(pfad)
            q = Quelle(name=name, eingaben=[pfad], ausgabe=proj.output_dir, mit_einstellungen=mit,
                       platten=[int(p) for p in (res.get("platten") or platten)],
                       run=getattr(self, "_run_no", None))
            if not mit:
                q.prozess, q.filamente = self._drucker_profile_aus_vorschau(q.platten)
                q.hinweise.append("Das 3MF der Druckvorschau bringt keine Bambu-Einstellungen mit; Kev CAD nimmt die "
                                  "Systemprofile (P1P 0.4).")
            return q
        return self._drucker_ersatzquelle(platten, ordner, name)

    def _drucker_profile_aus_vorschau(self, platten: list[int]) -> tuple[str, list[str]]:
        vorschau_fn = getattr(self, "druckvorschau", None)
        prof = Profile()
        if not callable(vorschau_fn):
            return PROZESS_STANDARD, [self._drucker_filament(prof, "pla")]
        try:
            v = vorschau_fn()
        except Exception:  # noqa: BLE001
            return PROZESS_STANDARD, [self._drucker_filament(prof, "pla")]
        materialien: list[str] = []
        for p in v.get("platten") or []:
            if platten and p.get("nr") not in platten:
                continue
            for m in p.get("material") or []:
                if m.get("material") and m["material"] not in materialien:
                    materialien.append(m["material"])
        prozess, filamente = PROZESS_STANDARD, []
        for t in v.get("teile") or []:
            prof_t = t.get("profil") or {}
            if t.get("material") in materialien and prof_t.get("prozess"):
                prozess = prof_t["prozess"]
                break
        for mat in materialien or ["pla"]:
            wunsch = next(((t.get("profil") or {}).get("filament") for t in v.get("teile") or []
                           if t.get("material") == mat), None)
            filamente.append(prof.filament_fuer(mat, wunsch) if wunsch else self._drucker_filament(prof, mat))
        return prozess, filamente

    def _drucker_filament(self, prof: Profile, material: str) -> str:
        proj = self._project  # type: ignore[attr-defined]
        wunsch = None
        if proj is not None:
            fil = ((proj.settings.get("druck") or {}).get("filament") or {})
            wunsch = fil.get(material) or fil.get(material_schluessel(material))
        return prof.filament_fuer(material, wunsch)

    def _drucker_ersatzquelle(self, platten: list[int], ordner: Path, name: str) -> Quelle:
        """Ohne Druckvorschau: je Material eine „Platte“ aus den Druckteilen des letzten Laufs (STL je Teil)."""
        from build123d import export_stl

        proj = self._project  # type: ignore[attr-defined]
        gruppen: dict[str, list[Any]] = {}
        for rec in self.scene.records():  # type: ignore[attr-defined]
            info = rec.header.get("druckteil") or {}
            if info.get("verfahren", "3d-druck") != "3d-druck" or not rec.header.get("druckteil"):
                continue
            gruppen.setdefault(str(info.get("material") or "pla"), []).append(rec)
        if not gruppen:
            raise QuelleFehler("Keine Druckteile im letzten Lauf (lager.druckteil).")
        materialien = sorted(gruppen)
        if not platten:
            if len(materialien) > 1:
                raise QuelleFehler("Ohne Druckvorschau druckt Kev CAD je Material getrennt: bitte eine Platte wählen ("
                                   + ", ".join(f"{i} = {m.upper()}" for i, m in enumerate(materialien, 1)) + ").")
            platten = [1]
        if len(platten) != 1 or not 1 <= platten[0] <= len(materialien):
            raise QuelleFehler(f"Ohne Druckvorschau gibt es die Platten 1 bis {len(materialien)} (je Material eine).")
        material = materialien[platten[0] - 1]
        eingaben = []
        with self._occ_lock:  # type: ignore[attr-defined]
            for i, rec in enumerate(gruppen[material], start=1):
                p = ordner / f"teil_{i:03d}.stl"
                export_stl(rec.shape, str(p))
                eingaben.append(p)
        prof = Profile()
        return Quelle(name=name if len(materialien) == 1 else f"{name}-{material}", eingaben=eingaben,
                      ausgabe=proj.output_dir, anordnen=True, ausrichten=True, prozess=PROZESS_STANDARD,
                      filamente=[self._drucker_filament(prof, material)], platten=list(platten),
                      hinweise=["Ohne Druckvorschau: Bambu Studio richtet die Teile selbst aus und ordnet sie an "
                                f"({len(eingaben)} Teile, {material.upper()})."],
                      run=getattr(self, "_run_no", None))

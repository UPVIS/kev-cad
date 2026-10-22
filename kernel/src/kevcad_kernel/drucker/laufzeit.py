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
        # Tests: KEVCAD_BAMBU_STUDIO (Bambu-Studio-Attrappe), KEVCAD_DRUCKER_CACHE (eigener Zwischenspeicher)
        extra: dict[str, Any] = {}
        if os.environ.get("KEVCAD_BAMBU_STUDIO"):
            extra["app"] = Path(os.environ["KEVCAD_BAMBU_STUDIO"])
        if os.environ.get("KEVCAD_DRUCKER_CACHE"):
            extra["cache"] = Path(os.environ["KEVCAD_DRUCKER_CACHE"])
        if os.environ.get("KEVCAD_DRUCKER_NICHT_OEFFNEN") == "1":  # Selbsttest: Bambu Studio nicht wirklich öffnen
            extra["oeffnen"] = lambda p: self._log(f"[drucker] (Selbsttest) würde in Bambu Studio öffnen: {p.name}")  # type: ignore[attr-defined]
        self._drucker = DruckerDienst(senden=self._send_app, quelle=self._drucker_quelle,  # type: ignore[attr-defined]
                                      log=self._log, **extra,  # type: ignore[attr-defined]
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
            # Filament der Druckvorschau: der Dialog „Drucken …“ zeigt es Kevin vor dem Bestätigen
            res = export(ziel=str(ordner / f"{name}.3mf"), platten=list(platten), filament="vorschau")
            if not res.get("ok"):
                raise QuelleFehler(res.get("fehler") or res.get("error") or "Druckvorschau: Export fehlgeschlagen")
            # V-K: ein Bambu-Projekt je Material (Bambu Studio 2.07 slict mehrere Filamente per CLI nicht richtig;
            # der P1P ohne AMS druckt ohnehin ein Material je Platte)
            dateien = res.get("dateien") or [{"pfad": res.get("pfad"), "material": None,
                                              "platten": res.get("platten") or platten}]
            if len({str(d.get("material")) for d in dateien}) > 1:
                wahl = "; ".join(f"{str(d.get('material') or '?').upper()}: Platte "
                                 + ", ".join(str(n) for n in d.get("platten") or []) for d in dateien)
                raise QuelleFehler("Mehrere Materialien: Der P1P druckt ein Material je Platte. Bitte nur Platten "
                                   f"eines Materials wählen ({wahl}).")
            if len(dateien) > 1:  # V-K ohne Bambu Studio: je Platte eine Datei
                raise QuelleFehler("Die Druckvorschau hat je Platte eine eigene Datei geschrieben (ohne Bambu "
                                   "Studio). Bitte eine Platte wählen.")
            datei = dateien[0]
            pfad = Path(str(datei.get("pfad")))
            mit = hat_projekt_einstellungen(pfad)
            q = Quelle(name=name, eingaben=[pfad], ausgabe=proj.output_dir, mit_einstellungen=mit,
                       platten=[int(p) for p in (datei.get("platten") or res.get("platten") or platten)],
                       hinweise=[str(h) for h in res.get("hinweise") or []],
                       run=getattr(self, "_run_no", None))
            if not mit:
                q.prozess, q.filamente = self._drucker_profile_aus_vorschau(q.platten)
                q.platte = self._drucker_platte()
                q.hinweise.append("Das 3MF der Druckvorschau bringt keine Bambu-Einstellungen mit; Kev CAD nimmt die "
                                  "Systemprofile (P1P 0.4).")
            return q
        return self._drucker_ersatzquelle(platten, ordner, name)

    def _drucker_profile_aus_vorschau(self, platten: list[int]) -> tuple[str, list[str]]:
        vorschau_fn = getattr(self, "druckvorschau", None)
        prof = Profile(self._drucker.app)
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

    def _drucker_platte(self) -> str | None:
        """Druckplatte aus ``kevcad.json`` (``druck.platte``, Name wie in Bambu Studio), sonst None (Druckermodell)."""
        proj = self._project  # type: ignore[attr-defined]
        wert = ((proj.settings.get("druck") or {}).get("platte") if proj is not None else None)
        return str(wert) if wert else None

    def _drucker_filament(self, prof: Profile, material: str) -> str:
        proj = self._project  # type: ignore[attr-defined]
        wunsch = None
        if proj is not None:
            fil = ((proj.settings.get("druck") or {}).get("filament") or {})
            wunsch = fil.get(material) or fil.get(material_schluessel(material))
        if not wunsch:  # wie die Druckvorschau: zuletzt gewählt, Spule im Bestand, Liste (druck/filamentwahl.py)
            projekt_fn = getattr(self, "_dv_projekt", None)
            if callable(projekt_fn):
                try:
                    from kevcad_kernel.druck import filamentwahl as fw

                    wahl = fw.waehle(material, projekt_fn())
                    # Ersatzweg ohne Druckvorschau: das Basisprofil des angenommenen Filaments (Presets kennt nur
                    # der Weg über druck_export)
                    if wahl.basis and wahl.quelle != "system" and prof.kennt(wahl.basis):
                        wunsch = wahl.basis
                except Exception:  # noqa: BLE001 - dann wie bisher
                    pass
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
        prof = Profile(self._drucker.app)
        return Quelle(name=name if len(materialien) == 1 else f"{name}-{material}", eingaben=eingaben,
                      ausgabe=proj.output_dir, anordnen=True, ausrichten=True, prozess=PROZESS_STANDARD,
                      filamente=[self._drucker_filament(prof, material)], platte=self._drucker_platte(),
                      platten=list(platten),
                      hinweise=["Ohne Druckvorschau: Bambu Studio richtet die Teile selbst aus und ordnet sie an "
                                f"({len(eingaben)} Teile, {material.upper()})."],
                      run=getattr(self, "_run_no", None))

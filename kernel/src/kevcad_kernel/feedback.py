"""V2-6 Sprach-Feedback im Kernel (PROTOCOL.md, Abschnitt „V2-6 Sprach-Feedback“).

Die App schreibt das Paket selbst nach ``<projekt>/feedback/`` und meldet es mit ``FEEDBACK_PAKET``; der Kernel merkt
sich den Stand (``FEEDBACK_STAND``), weckt Wartende und führt in ``abgeholt.json``, was der Agent schon hat. Pakete, die
dort fehlen, sind offen: Sie überleben Neustarts und warten auf den nächsten Agenten, nichts wird gelöscht.

Während Kevin spricht, beginnt nichts Neues (``feedback_sperre``): Läufe, Ansichtsbefehle und Projektwechsel des Agenten
antworten sofort, ein Auto-Lauf wartet bis zum Ende des Stands. Laufendes läuft zu Ende.

Mixin für ``KernelRuntime``; erwartet ``_project``, ``_log`` und ``_auto_check``.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from kevcad_kernel.protocol import (
    FEEDBACK_ABGEHOLT, FEEDBACK_ABGEHOLT_FORMAT, FEEDBACK_NACHRICHTEN, FEEDBACK_ORDNER, FEEDBACK_STAENDE,
    check_feedback_message, check_feedback_paket, feedback_name_ok,
)

KEVIN_SPRICHT = ("Kevin spricht gerade, deshalb startet nichts Neues und die Ansicht bleibt bei ihm. "
                 "feedback() wartet, bis er fertig ist.")
SPERRE_ANSICHT = frozenset({"view", "focus", "visibility", "section", "explode"})
_TAKT_S = 0.5  # so oft sieht ein Wartender nach Abbruch und neuen Dateien; Pakete wecken ihn sofort


def _jetzt_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _schreiben(pfad: Path, daten: dict[str, Any]) -> None:
    """Atomar: temporäre Datei im selben Ordner, dann umbenennen."""
    tmp = pfad.with_name(f".{pfad.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, pfad)


class FeedbackRuntime:
    """Stand, Warten und Abholen (siehe Moduldoku)."""

    def _feedback_init(self) -> None:
        self._fb_cond = threading.Condition()
        self._fb_stand: dict[str, Any] = {"stand": "aus", "sitzung": None, "seit": None}
        self._fb_zuletzt: dict[str, str] = {}  # Projektpfad → zuletzt abgeholtes Paket

    # -- Nachrichten der App -------------------------------------------------------------------------------------------

    def _feedback_app_message(self, kind: str | None, header: dict[str, Any]) -> bool:
        if kind not in FEEDBACK_NACHRICHTEN:
            return False
        probleme = check_feedback_message(header)
        if probleme:
            self._log(f"[kernel] {kind} ungültig: {'; '.join(probleme)}")  # type: ignore[attr-defined]
            return True
        if kind == "FEEDBACK_STAND":
            self._feedback_stand_setzen(str(header["stand"]), str(header["sitzung"]), float(header["seit"]))
        else:
            self._log(f"[kernel] Feedback {header.get('name')}: {header.get('saetze')} Sätze, "  # type: ignore
                      f"{header.get('striche')} Striche")
            with self._fb_cond:
                self._fb_cond.notify_all()
        return True

    def _feedback_stand_setzen(self, stand: str, sitzung: str | None, seit: float | None) -> None:
        assert stand in FEEDBACK_STAENDE
        with self._fb_cond:
            vorher = self._fb_stand.get("stand")
            self._fb_stand = {"stand": stand, "sitzung": sitzung if stand != "aus" else None,
                              "seit": seit if stand != "aus" else None}
            self._fb_cond.notify_all()
        if vorher == "spricht" and stand != "spricht":
            self._feedback_auto_nachholen()

    def _feedback_verbindung_weg(self) -> None:
        """Ohne App spricht niemand mehr: Eine hängende Sperre hielte den Agenten sonst für immer auf."""
        if self._fb_stand.get("stand") != "aus":
            self._feedback_stand_setzen("aus", None, None)

    def _feedback_auto_nachholen(self) -> None:
        """Hat der Agent model.py geändert, während Kevin sprach, läuft der Auto-Lauf jetzt."""
        try:
            self._auto_check()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - ein Fehler hier darf die Nachricht der App nicht verlieren
            self._log(f"[kernel] Auto-Lauf nach dem Sprechen: {exc!r}")  # type: ignore[attr-defined]

    # -- Sperre --------------------------------------------------------------------------------------------------------

    @property
    def kevin_spricht(self) -> bool:
        return self._fb_stand.get("stand") == "spricht"

    def feedback_sperre(self) -> dict[str, Any] | None:
        """Antwort für alles, was warten muss, solange Kevin spricht; sonst None."""
        return {"ok": False, "error": KEVIN_SPRICHT, "kevin_spricht": True} if self.kevin_spricht else None

    # -- Pakete --------------------------------------------------------------------------------------------------------

    def _fb_ordner(self) -> Path | None:
        proj = self._project  # type: ignore[attr-defined]
        return None if proj is None else Path(proj.path) / FEEDBACK_ORDNER

    def _fb_abgeholt(self, ordner: Path) -> dict[str, str]:
        try:
            daten = json.loads((ordner / FEEDBACK_ABGEHOLT).read_text(encoding="utf-8"))
            pakete = daten.get("pakete")
            return dict(pakete) if isinstance(pakete, dict) else {}
        except (OSError, ValueError):
            return {}

    def _fb_offene(self, ordner: Path | None = None) -> list[str]:
        """Namen der offenen Pakete, das älteste zuerst. Der Name trägt die Zeit, nach ihm zu ordnen reicht."""
        ordner = ordner or self._fb_ordner()
        if ordner is None:
            return []
        try:
            namen = [p.stem for p in ordner.iterdir() if p.suffix == ".json" and feedback_name_ok(p.stem)]
        except OSError:
            return []
        fort = self._fb_abgeholt(ordner)
        return sorted((n for n in namen if n not in fort), key=_ordnung)

    def feedback_stand(self) -> dict[str, Any]:
        """{"stand": "spricht"|"pause"|"aus", "sitzung", "seit_s", "offen": Anzahl, "name": ältestes offenes Paket}"""
        with self._fb_cond:
            stand = dict(self._fb_stand)
        offene = self._fb_offene()
        seit = stand.pop("seit", None)
        return {**stand, "seit_s": None if seit is None else max(0.0, round(time.time() - seit, 1)),
                "offen": len(offene), "name": offene[0] if offene else None}

    def feedback_warten(self, warten_s: float, abbruch: threading.Event | None = None) -> dict[str, Any]:
        """Wartet auf ein offenes Paket, holt es aber nicht ab. {"da": bool, **feedback_stand()}"""
        ende = time.monotonic() + max(0.0, float(warten_s))
        with self._fb_cond:
            while True:
                if self._fb_offene():
                    break
                rest = ende - time.monotonic()
                if rest <= 0 or (abbruch is not None and abbruch.is_set()):
                    break
                self._fb_cond.wait(min(rest, _TAKT_S))
        stand = self.feedback_stand()
        return {"da": stand["offen"] > 0, **stand}

    def feedback_kurz(self, name: str) -> dict[str, Any]:
        """Sätze und Striche eines Pakets für die Meldung im Hintergrund, ohne es abzuholen."""
        ordner = self._fb_ordner()
        try:
            paket = json.loads((ordner / f"{name}.json").read_text(encoding="utf-8")) if ordner else {}
        except (OSError, ValueError):
            paket = {}
        return {"saetze": len(paket.get("saetze") or []), "striche": len(paket.get("striche") or [])}

    def feedback_holen(self, nochmal: bool = False) -> dict[str, Any]:
        """Ältestes offenes Paket, als abgeholt eingetragen; mit ``nochmal`` das zuletzt abgeholte.

        {"ok", "name", "paket", "bild": bytes | None, "bild_pfad", "json_pfad", "offen": weitere} oder {"ok": True,
        "leer": True}; bei einem Paket, das sich nicht lesen lässt, {"ok": False, "error"} (es gilt dann als abgeholt,
        damit es die folgenden nicht aufhält)."""
        ordner = self._fb_ordner()
        if ordner is None:
            return {"ok": False, "error": "Kein Projekt offen."}
        with self._fb_cond:
            if nochmal:
                name = self._fb_zuletzt.get(str(ordner)) or self._fb_letztes(ordner)
                if name is None:
                    return {"ok": True, "leer": True, "offen": len(self._fb_offene(ordner))}
            else:
                offene = self._fb_offene(ordner)
                if not offene:
                    return {"ok": True, "leer": True, "offen": 0}
                name = offene[0]
                self._fb_eintragen(ordner, name)
            self._fb_zuletzt[str(ordner)] = name
            offen = len(self._fb_offene(ordner))
        pfad = ordner / f"{name}.json"
        try:
            paket = json.loads(pfad.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"Feedback {name} nicht lesbar: {exc}", "offen": offen}
        # Kevins Worte gehen vor: Ein Paket mit Schönheitsfehlern kommt trotzdem an, der Fehler steht im Protokoll
        probleme = check_feedback_paket(paket)
        if probleme:
            self._log(f"[kernel] Feedback {name}: {'; '.join(probleme[:3])}")  # type: ignore[attr-defined]
        bild, bild_pfad = None, None
        eintrag = paket.get("bild")
        if isinstance(eintrag, dict) and isinstance(eintrag.get("datei"), str):
            ziel = ordner / Path(eintrag["datei"]).name
            try:
                bild, bild_pfad = ziel.read_bytes(), str(ziel)
            except OSError:
                pass
        return {"ok": True, "name": name, "paket": paket, "bild": bild, "bild_pfad": bild_pfad, "json_pfad": str(pfad),
                "offen": offen}

    def _fb_eintragen(self, ordner: Path, name: str) -> None:
        fort = self._fb_abgeholt(ordner)
        fort[name] = _jetzt_iso()
        _schreiben(ordner / FEEDBACK_ABGEHOLT, {"format": FEEDBACK_ABGEHOLT_FORMAT, "pakete": fort})

    def _fb_letztes(self, ordner: Path) -> str | None:
        """Zuletzt abgeholtes Paket nach einem Neustart: das jüngste in ``abgeholt.json``."""
        fort = self._fb_abgeholt(ordner)
        return max(fort, key=lambda n: (fort[n], _ordnung(n))) if fort else None


def _ordnung(name: str) -> tuple[str, int]:
    """``fb-…-2`` nach ``fb-…``, ``fb-…-10`` nach ``fb-…-9``."""
    m = re.fullmatch(r"(fb-\d{8}-\d{6})(?:-(\d+))?", name)
    return (m.group(1), int(m.group(2) or 1)) if m else (name, 0)

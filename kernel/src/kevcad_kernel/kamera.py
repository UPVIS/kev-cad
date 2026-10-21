"""Kameras im Kernel (Phase 5, Strang KAM): Anmeldung im Lauf, Auflösung am Laufende und der Kamerateil der Laufzeit.

Im Rechenprozess meldet ``lager.kamera(...)`` jede Kamera beim ``KameraRegister`` des Laufs an. Am Ende des Laufs löst
das Register Befestigungen an Teilen auf (``an(..., lokal=True)``), findet die gezeigten Teile des eigenen Objektivs
(``ausblenden``) und liefert die Köpfe für CAMERA_UPSERT (PROTOCOL.md, „Phase 5: Kameras“).

``CameraRuntime`` ist eine Ergänzung (Mixin) von ``KernelRuntime``: Kamerastand des letzten Laufs, Nachrichten an die
App (CAMERA_UPSERT, CAMERA_REMOVE), Vorschläge aus der App (CAMERA_SUGGEST) und die Service-Methoden für die
MCP-Werkzeuge (``cameras``, ``camera_info``, ``camera_view``, ``camera_image``, ``camera_catalog``,
``camera_suggestion``).
"""

from __future__ import annotations

import math
import re
import threading
import time
from pathlib import Path
from typing import Any

from kevcad_kernel.optik import blende_text, format_info, mm_text

PREFIX = "Kamera/"
MAX_BILD = 8192


# ---------------------------------------------------------------------------------------------------------------------
# Rechenprozess


class KameraRegister:
    """Kameras eines Laufs (Name → Kamera), in Reihenfolge der Anmeldung; gleicher Name ersetzt mit Warnung."""

    def __init__(self) -> None:
        self.kameras: dict[str, Any] = {}

    def register(self, cam: Any, warn=None) -> None:
        if cam.objekt_name in self.kameras and self.kameras[cam.objekt_name] is not cam and warn is not None:
            warn(f"Kamera {cam.name!r} gibt es schon in diesem Lauf: die neue ersetzt sie (name=… angeben)")
        self.kameras[cam.objekt_name] = cam

    def resolve(self, locations: dict[str, list[list[float]]], tokens: dict[str, str | None], shown: list[str],
                warn) -> list[dict[str, Any]]:
        """Köpfe für CAMERA_UPSERT (ohne type/run): lokale Befestigungen auflösen, eigenes Objektiv ausblenden,
        fehlende Lage und unbekannte Eltern-Teile melden."""
        out = []
        names = set(shown)
        for cam in self.kameras.values():
            msg = cam.aufloesen(locations)
            if msg:
                warn(msg)
            if not cam.gesetzt:
                warn(f"Kamera {cam.name}: keine Lage, steht im Ursprung mit Blick nach +X (.setzen(...) oder "
                     ".an(...) aufrufen)")
            if cam.teil and cam.teil not in names and not any(n.startswith(cam.teil + "/") for n in names):
                warn(f"Kamera {cam.name}: Teil {cam.teil!r} aus an() wurde nicht gezeigt")
            lens_token = cam._tokens.get("objektiv")
            if lens_token:
                for name in shown:
                    if tokens.get(name) == lens_token and name not in cam.ausblenden:
                        cam.ausblenden.append(name)
            out.append(cam.nachricht())
        return out


def location_of(shape: Any) -> list[list[float]] | None:
    """3 × 4-Matrix der Location einer gezeigten Form (für ``an(..., lokal=True)``), None ohne Location."""
    try:
        t = shape.location.wrapped.Transformation()
    except Exception:  # noqa: BLE001
        return None
    return [[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)]


# ---------------------------------------------------------------------------------------------------------------------
# Texte


def _deg(x: float | None) -> str:
    return "–" if x is None else f"{x:.1f}".replace(".", ",") + "°"


def camera_line(c: dict[str, Any]) -> str:
    """Eine Zeile je Kamera: „FX6 · Sony FX6 · Sigma 35 mm T1,5 · Vollformat UHD · 35 mm · T2,8 · …“."""
    obj = (c.get("objektiv") or {}).get("name") or "ohne Objektiv"
    nah, fern = c.get("schaerfe_nah"), c.get("schaerfe_fern")
    bits = [c.get("kurzname") or c.get("name"), (c.get("kamera") or {}).get("name") or "?", obj,
            (c.get("format") or {}).get("name") or "?", f"{_num(c.get('brennweite'))} mm",
            blende_text(float(c.get("blende") or 0), c.get("blendenart") or "f"),
            f"Fokus {mm_text(c.get('fokus') if c.get('fokus') is not None else math.inf)}",
            f"Bildwinkel {_deg(c.get('bildwinkel_h'))} × {_deg(c.get('bildwinkel_v'))}",
            f"Schärfe {mm_text(nah if nah is not None else math.inf)} bis "
            f"{mm_text(fern if fern is not None else math.inf)}"]
    if c.get("teil"):
        bits.append(f"an {c['teil']}")
    if c.get("vorschlag"):
        bits.append("Vorschlag aus der App wartet")
    return " · ".join(str(b) for b in bits)


def _num(x: Any) -> str:
    if not isinstance(x, (int, float)):
        return "–"
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _vec(v: Any) -> str:
    return "(" + "; ".join(_num(c) for c in (v or [])) + ")"


def safe_file(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._-]+", "-", text).strip("-") or "Kamera"


# ---------------------------------------------------------------------------------------------------------------------
# Laufzeit


class CameraRuntime:
    """Kamerateil der Laufzeit (Mixin für ``KernelRuntime``; nutzt dessen ``_send_app``, ``_request``, ``_link``,
    ``_project``, ``catalog`` und ``_lock``)."""

    def _cam_state(self) -> dict[str, Any]:
        st = self.__dict__.get("_kam")
        if st is None:
            st = {"cameras": {}, "suggestions": {}, "lock": threading.RLock()}
            self.__dict__["_kam"] = st
        return st

    # -- Laufzeit-Haken ------------------------------------------------------------------------------------------------

    def cameras_after_run(self, run: int, cameras: list[dict[str, Any]] | None) -> None:
        """Nach RUN_DONE: neue und geänderte Kameras an die App, weggefallene entfernen."""
        st = self._cam_state()
        new = {c["name"]: c for c in (cameras or []) if isinstance(c, dict) and c.get("name")}
        with st["lock"]:
            old = st["cameras"]
            st["cameras"] = new
            for name in [n for n in st["suggestions"] if n not in new]:
                st["suggestions"].pop(name, None)
        for name in old:
            if name not in new:
                self._send_app({"type": "CAMERA_REMOVE", "run": run, "name": name})
        for name, head in new.items():
            if old.get(name) != head:
                self._send_app({"type": "CAMERA_UPSERT", "run": run, **head})

    def cameras_clear(self, run: int) -> None:
        """Anderes Projekt: alle Kameras entfernen."""
        st = self._cam_state()
        with st["lock"]:
            old, st["cameras"], st["suggestions"] = st["cameras"], {}, {}
        for name in old:
            self._send_app({"type": "CAMERA_REMOVE", "run": run, "name": name})

    def cameras_on_connect(self, conn: Any, run: int) -> None:
        st = self._cam_state()
        with st["lock"]:
            heads = list(st["cameras"].values())
        for head in heads:
            conn.send({"type": "CAMERA_UPSERT", "run": run, **head})

    def camera_suggest_from_app(self, header: dict[str, Any]) -> None:
        """CAMERA_SUGGEST: Kevin hat Strg+Alt+0 gedrückt (aktive Kamera auf die Ansicht), als Vorschlag merken."""
        name = self._camera_name(str(header.get("name") or ""))
        if name is None:
            return
        keep = {k: header.get(k) for k in ("sensor_pos", "auge", "blick", "oben", "rechts", "roll")}
        keep["zeit"] = time.strftime("%H:%M:%S")
        with self._cam_state()["lock"]:
            self._cam_state()["suggestions"][name] = keep

    # -- Abfragen -------------------------------------------------------------------------------------------------------

    def _camera_name(self, name: str) -> str | None:
        st = self._cam_state()
        with st["lock"]:
            names = list(st["cameras"])
        key = name.strip()
        if not key:
            return names[0] if len(names) == 1 else None
        for cand in (key, PREFIX + key):
            if cand in names:
                return cand
        low = key.lower().removeprefix(PREFIX.lower())
        hits = [n for n in names if n.lower().removeprefix(PREFIX.lower()) == low]
        return hits[0] if len(hits) == 1 else None

    def _unknown_camera(self, name: str) -> dict[str, Any]:
        st = self._cam_state()
        with st["lock"]:
            names = [n.removeprefix(PREFIX) for n in st["cameras"]]
        if not names:
            return {"ok": False, "error": "Keine Kameras im Modell. In model.py mit lager.kamera(...).setzen(...) anlegen "
                                          "und run aufrufen."}
        if not name.strip():
            return {"ok": False, "error": f"Mehrere Kameras, bitte name angeben: {', '.join(names)}"}
        return {"ok": False, "error": f"Kamera {name!r} gibt es nicht. Vorhanden: {', '.join(names)}"}

    def cameras(self) -> dict[str, Any]:
        """{"ok", "cameras": [CAMERA_UPSERT-Kopf + "vorschlag"]}"""
        st = self._cam_state()
        with st["lock"]:
            cams = [dict(c, vorschlag=st["suggestions"].get(n)) for n, c in st["cameras"].items()]
        return {"ok": True, "cameras": cams}

    def camera_info(self, name: str) -> dict[str, Any]:
        full = self._camera_name(name)
        if full is None:
            return self._unknown_camera(name)
        st = self._cam_state()
        with st["lock"]:
            cam = dict(st["cameras"][full])
            sug = st["suggestions"].get(full)
        out = {"ok": True, "camera": cam, "vorschlag": sug}
        if sug:
            out["vorschlag_code"] = suggestion_code(cam, sug)
        return out

    def camera_view(self, name: str | None, timeout_s: float = 10) -> dict[str, Any]:
        """Durch die Kamera schauen (name) oder zurück zur freien Ansicht (None)."""
        full = None
        if name is not None:
            full = self._camera_name(name)
            if full is None:
                return self._unknown_camera(name)
        return self.view_command("camera_view", {"name": full}, timeout_s)

    def camera_suggestion(self, name: str = "", timeout_s: float = 10) -> dict[str, Any]:
        """Aktuelle Ansicht der App als neue Lage der Kamera vorschlagen (ohne model.py zu ändern)."""
        full = self._camera_name(name)
        if full is None:
            return self._unknown_camera(name)
        with self._cam_state()["lock"]:
            self._cam_state()["suggestions"].pop(full, None)  # nur einen frischen Vorschlag gelten lassen
        res = self.view_command("camera_suggest", {"name": full}, timeout_s)
        if not res.get("ok"):
            return res
        deadline = time.monotonic() + 3.0
        st = self._cam_state()
        while time.monotonic() < deadline:
            with st["lock"]:
                sug = st["suggestions"].get(full)
                cam = st["cameras"].get(full)
            if sug is not None and cam is not None:
                return {"ok": True, "name": full, "vorschlag": sug, "code": suggestion_code(cam, sug)}
            time.sleep(0.02)
        return {"ok": False, "error": "Die App hat keinen Vorschlag geschickt"}

    def camera_image(self, name: str, width: int = 1920, save: bool = True, return_png: bool = False,
                     overlays: bool = False, timeout_s: float = 60) -> dict[str, Any]:
        """Bild durch die Kamera (Lage, Bildwinkel und Seitenverhältnis des Formats) aus der App; gespeichert unter
        <projekt>/output/kameras/."""
        full = self._camera_name(name)
        if full is None:
            return self._unknown_camera(name)
        st = self._cam_state()
        with st["lock"]:
            cam = dict(st["cameras"][full])
        res = cam.get("aufloesung") or [16, 9]
        w = max(64, min(int(width or res[0]), MAX_BILD))
        h = max(16, min(int(round(w * res[1] / res[0])), MAX_BILD))
        if not self._link.connected:
            return {"ok": False, "error": "App nicht verbunden"}
        req = {"type": "SCREENSHOT_REQ", "width": w, "height": h, "source": "camera", "view": None,
               "hide_overlays": not overlays, "camera": full}
        reply, payload, error = self._request(req, timeout_s)
        if error:
            return {"ok": False, "error": error}
        if not reply.get("ok", False):
            return {"ok": False, "error": reply.get("message") or "App konnte kein Kamerabild erzeugen"}
        out: dict[str, Any] = {"ok": True, "name": full, "width": reply.get("width", w), "height": reply.get("height", h),
                               "camera": reply.get("camera") or {}, "kamera": cam, "bytes": len(payload)}
        if save:
            proj = self._project
            if proj is None:
                out["warnings"] = ["Kein Projekt offen: Bild nicht gespeichert"]
            else:
                folder = Path(proj.output_dir) / "kameras"
                stamp = time.strftime("%Y%m%d-%H%M%S")
                f_text = _num(cam.get("brennweite")).replace(",", ".")
                fname = f"{safe_file(full.removeprefix(PREFIX))}_{f_text}mm_{out['width']}x{out['height']}_{stamp}.png"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / fname
                    n = 2
                    while path.exists():
                        path = folder / fname.replace(".png", f"-{n}.png")
                        n += 1
                    path.write_bytes(payload)
                    out["file"] = str(path)
                except OSError as exc:
                    out["warnings"] = [f"Bild nicht gespeichert: {exc}"]
        if return_png or not save:
            out["png"] = payload
        return out

    def camera_catalog(self, query: str = "", art: str | None = None, limit: int = 40) -> dict[str, Any]:
        """Kameras, Objektive und Zubehör aus dem Katalog, mit berechneten Formatwerten."""
        arten = [art] if art else ["kamera", "objektiv", "kamerazubehoer"]
        items: list[dict[str, Any]] = []
        total = 0
        for a in arten:
            hits, n = self.catalog.search(query or "", art=a, limit=limit)
            total += n
            for it in hits:
                if a == "kamera":
                    it = dict(it, formate_berechnet=[format_info(f) for f in it.get("formate") or []])
                items.append(it)
        return {"ok": True, "items": items[:limit], "total": total}


def suggestion_code(cam: dict[str, Any], sug: dict[str, Any]) -> str:
    """model.py-Zeile für einen Vorschlag: Sensormitte und Blickrichtung (roll aus der Ansicht)."""
    var = re.sub(r"\W", "_", str(cam.get("kurzname") or "kamera").lower()) or "kamera"
    if var[0].isdigit():
        var = "k_" + var
    p = [round(float(v), 1) for v in sug.get("sensor_pos") or [0, 0, 0]]
    d = [round(float(v), 4) for v in sug.get("blick") or [1, 0, 0]]
    roll = round(float(sug.get("roll") or 0.0), 2)
    roll_text = f", roll={roll:g}" if abs(roll) > 0.01 else ""
    return (f"{var}.setzen(({p[0]:g}, {p[1]:g}, {p[2]:g}), richtung=({d[0]:g}, {d[1]:g}, {d[2]:g}){roll_text})"
            f"  # Vorschlag aus Kevins Ansicht")


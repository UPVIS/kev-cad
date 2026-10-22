"""Prüfung als Teil der Kernel-Laufzeit (KernelService): ``pruefen`` (letztes Ergebnis samt Montage und Stand,
auf Wunsch mit Nahansichten der Befunde) und ``ansichten`` (mehrere Offscreen-Bilder in einem Zug).

Mischklasse für ``KernelRuntime``; nutzt deren ``_pruef`` (PruefStand), ``_link`` und ``_request``.

Ansichten reisen als ``SCREENSHOT_REQ`` mit dem zusätzlichen Feld ``ansicht`` (PROTOCOL.md, Abschnitt „Prüfung“):
Blickrichtung (Standardansicht oder Vektor), Ziel (Teile oder Punkt mit Radius), Darstellung, Hervorhebung, Schnittkörper.
Ältere Apps ignorieren das Feld und liefern die Standardansicht; die App meldet in ``camera.ansicht``, dass sie es
umgesetzt hat. Kevins Kamera und Darstellung bleiben in jedem Fall unverändert.
"""

from __future__ import annotations

from typing import Any

STANDARD = ("top", "bottom", "front", "back", "left", "right", "iso", "iso_front_left", "iso_back_right",
            "iso_back_left")
DARSTELLUNGEN = ("shaded_edges", "shaded", "wireframe", "xray")


def ansicht_fuer_befund(b: dict[str, Any], groesse: float | None = None) -> list[dict[str, Any]]:
    """Zwei bis drei Nahansichten auf den Ort eines Befunds: iso, dazu zwei Richtungen quer zur Trennrichtung."""
    import numpy as np

    ort = b.get("ort")
    if ort is None:
        return []
    wert = b.get("wert") or {}
    tiefe = float(wert.get("tiefe") or 0.0)
    radius = max(25.0, 6.0 * tiefe, float(groesse or 0.0))
    # Röntgen nur, wo es einen Schnittkörper zu sehen gibt (Durchdringung); sonst normal schattiert mit Kanten
    darstellung = "xray" if b.get("geometrie") is not None else "shaded_edges"
    basis = {"punkt": [float(c) for c in ort], "radius": radius, "darstellung": darstellung, "schnittkoerper": True,
             "hervorheben": list(b.get("teile") or [])[:4]}
    ansichten = [{**basis, "name": f"{b.get('id')} iso", "standard": "iso"}]
    achse = wert.get("achse")
    if achse:  # quer zur Richtung, in die das Teil heraus müsste: dort sieht man die Überlappung als Streifen
        a = np.asarray(achse, dtype=float)
        a /= np.linalg.norm(a) or 1.0
        hilf = np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        q1 = np.cross(a, hilf)
        q1 /= np.linalg.norm(q1)
        q2 = np.cross(a, q1)
        for i, q in enumerate((q1, q2), 1):
            ansichten.append({**basis, "name": f"{b.get('id')} quer {i}", "richtung": [round(float(c), 4) for c in q]})
    else:
        ansichten += [{**basis, "name": f"{b.get('id')} vorn", "standard": "front"},
                      {**basis, "name": f"{b.get('id')} oben", "standard": "top"}]
    return ansichten


class PruefDienst:
    """Mischklasse für KernelRuntime."""

    def pruefen(self, warten_s: float = 120.0, endstand: bool = False) -> dict[str, Any]:
        """Letztes Prüfergebnis (wartet auf eine laufende Prüfung): CHECK-Kopf ohne type/seq. ``endstand``: auch
        auf das Fertigrechnen im Hintergrund warten (Zustand „teilweise“ → „done“), höchstens ``warten_s``."""
        stand = self._pruef  # type: ignore[attr-defined]
        hinten = stand.hintergrund if stand.hintergrund is not None else stand.statik_hintergrund  # auch Statik (T34)
        laufend = stand.erwartet if stand.erwartet is not None else (hinten if endstand else None)
        if laufend is not None:
            stand.warte(laufend, warten_s, endstand=endstand)
        check, _ = stand.letztes()
        if check is None:
            return {"ok": False, "error": "Noch keine Prüfung: erst run aufrufen (geprüft wird nach jedem Lauf)."}
        out = {"ok": True, **{k: v for k, v in check.items() if k not in ("type", "seq")}}
        if stand.erwartet is not None:
            out["laeuft"] = stand.erwartet
        if stand.hintergrund is not None:
            out["hintergrund"] = stand.hintergrund
        if stand.statik_hintergrund is not None:
            out["statik_hintergrund"] = stand.statik_hintergrund
        return out

    def ansichten(self, ansichten: list[dict[str, Any]], width: int = 640, height: int = 400,
                  timeout_s: float = 20) -> dict[str, Any]:
        """Mehrere Offscreen-Bilder aus der App, ohne Kevins Ansicht zu ändern: {"ok", "bilder": [{name, png, …}]}."""
        if not self._link.connected:  # type: ignore[attr-defined]
            from kevcad_kernel.runtime import APP_NOT_CONNECTED

            return {"ok": False, "error": APP_NOT_CONNECTED}
        bilder: list[dict[str, Any]] = []
        for a in ansichten:
            a = {k: v for k, v in a.items() if v is not None}
            standard = a.get("standard") if a.get("standard") in STANDARD else None
            req = {"type": "SCREENSHOT_REQ", "width": int(width), "height": int(height), "source": "offscreen",
                   "view": standard or "iso", "hide_overlays": True, "ansicht": a}
            reply, payload, error = self._request(req, timeout_s)  # type: ignore[attr-defined]
            if error:
                return {"ok": False, "error": error, "bilder": bilder}
            if not reply.get("ok", False) or not payload:
                return {"ok": False, "error": reply.get("message") or "App konnte kein Bild erzeugen", "bilder": bilder}
            camera = reply.get("camera") or {}
            bilder.append({"name": a.get("name") or standard or "Ansicht", "png": payload,
                           "width": reply.get("width", width), "height": reply.get("height", height),
                           "camera": camera, "ansicht_umgesetzt": bool(isinstance(camera, dict)
                                                                         and camera.get("ansicht"))})
        return {"ok": True, "bilder": bilder}

"""Im Rechenprozess: sammelt je gezeigtem Teil, was die Prüfung wissen muss (Material, nachgiebig, Lagerteil,
Achse und Kopfmaße von Schrauben und Muttern) und die Erklärungen aus model.py (``kevcad.pruefung``).

Das Ergebnis reist mit ``RUN_DONE`` als Feld ``pruefung`` an die Laufzeit: ``{"teile": {Name: Angaben},
"erklaerungen": {...}}``. Formen werden dabei in Namen übersetzt (gleiche Form ``IsPartner``, sonst ``label``).
"""

from __future__ import annotations

from typing import Any

import numpy as np

NACHGIEBIG_WORTE = ("schaum", "foam", "gummi", "rubber", "filz", "felt", "gurt", "tpu", "elastomer", "moosgummi")


def _matrix(loc: Any) -> np.ndarray:
    tr = loc.Transformation()
    m = np.eye(4)
    for r in range(3):
        for c in range(4):
            m[r, c] = tr.Value(r + 1, c + 1)
    return m


class Erfassung:
    def __init__(self) -> None:
        self.teile: dict[str, dict[str, Any]] = {}
        self.formen: dict[str, Any] = {}  # Name → gezeigte Form (für Formverweise in Erklärungen)
        self.eintraege: list[tuple[str, dict[str, Any]]] = []
        self.geometrie: dict[str, tuple] = {}  # Name → (Schlüssel, TopoDS, Punkte, Dreiecke, bbox, props, faces)

    # -- Erklärungen ---------------------------------------------------------------------------------------------

    def melde(self, art: str, daten: dict[str, Any]) -> None:
        self.eintraege.append((art, daten))

    # -- Teile ---------------------------------------------------------------------------------------------------

    def teil(self, name: str, shape: Any, mat: Any, pieces: list[Any], catalog: Any, tess: Any = None,
             props: dict[str, Any] | None = None) -> None:
        if tess is not None:  # Geometrie für die Prüfung im Rechenprozess (lauf.py)
            self.geometrie[name] = (tess.key, shape.wrapped, tess.geometry.positions, tess.geometry.triangles,
                                    tess.bbox, dict(props or tess.props), tess.geometry.faces)
        info: dict[str, Any] = {}
        entry = getattr(mat, "entry", None) if mat is not None else None
        if mat is not None:
            info["material"] = mat.display
        if entry:
            info["material_id"] = entry.get("id")
            if entry.get("nachgiebig"):
                info["nachgiebig"] = True
        if "nachgiebig" not in info and mat is not None and not entry:
            text = str(mat.display or "").lower()
            if any(w in text for w in NACHGIEBIG_WORTE):
                info["nachgiebig"] = True
        if pieces:
            p = pieces[0]
            info["lager"] = True
            info["art"] = p.art
            if p.stock_id:
                info["stock_id"] = p.stock_id
            if p.art == "druckteil":
                info["druckteil"] = True
            if p.art in ("schraube", "mutter", "scheibe"):
                try:
                    info.update(self._verbindung(shape, p, catalog))
                except Exception:  # noqa: BLE001 - ohne Achse keine Werkzeugprüfung, sonst kein Schaden
                    pass
        self.teile[name] = info
        self.formen[name] = shape

    @staticmethod
    def _verbindung(shape: Any, piece: Any, catalog: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        item = catalog.item(piece.stock_id) if catalog is not None and piece.stock_id else None
        masse = (item or {}).get("masse") or {}
        out["typ"] = masse.get("typ")
        out["norm"] = masse.get("norm")
        out["groesse"] = masse.get("groesse") or piece.groesse
        if piece.laenge:
            out["laenge"] = float(piece.laenge)
        import re

        m = re.match(r"[Mm](\d+(?:\.\d+)?)", str(out.get("groesse") or ""))
        if m:
            out["d"] = float(m.group(1))
        orig = piece.shape  # TopoDS_Shape, wie verbaut (Kopf auf z = 0, Achse +Z)
        # Lage: gleiche Form (IsPartner) → Verschiebung und Drehung gegenüber dem verbauten Teil. Kopfmaße rechnet die
        # Prüfung aus dem Netz entlang dieser Achse.
        if orig is None or not shape.wrapped.IsPartner(orig):
            return out
        rel = _matrix(shape.wrapped.Location()) @ np.linalg.inv(_matrix(orig.Location()))
        achse = rel[:3, :3] @ np.array([0.0, 0.0, 1.0])
        out["achse"] = [round(float(c), 6) for c in achse / np.linalg.norm(achse)]
        out["ursprung"] = [round(float(c), 4) for c in rel[:3, 3]]
        return out

    # -- Abschluss -----------------------------------------------------------------------------------------------

    def _namen(self, refs: list[Any], shown: list[str], warnungen: list[dict[str, Any]], wo: str,
               zeile: int | None) -> list[str]:
        out: list[str] = []
        for r in refs:
            if isinstance(r, str):
                t = r.strip().strip("/")
                if t in shown:
                    out.append(t)
                elif any(n.startswith(t + "/") for n in shown):
                    out.append(t + "/")
                else:
                    import difflib

                    tip = difflib.get_close_matches(t, shown, n=2, cutoff=0.6)
                    warnungen.append({"teil": t, "text": f"{wo}: kein gezeigtes Teil heißt {t!r}"
                                      + (f" (Zeile {zeile})" if zeile else "")
                                      + (f"; meinten Sie {', '.join(repr(x) for x in tip)}?" if tip else ""),
                                      "loesung": "Namen wie in show() verwenden (auch Gruppen wie \"Halter\")."})
                continue
            wrapped = getattr(r, "wrapped", None)
            treffer = []
            if wrapped is not None:
                for n, s in self.formen.items():
                    try:
                        if s.wrapped.IsPartner(wrapped):
                            treffer.append(n)
                    except Exception:  # noqa: BLE001
                        continue
            label = str(getattr(r, "label", "") or "")
            if not treffer and label in shown:
                treffer = [label]
            if not treffer:
                warnungen.append({"teil": label or type(r).__name__,
                                  "text": f"{wo}: Form {label or type(r).__name__} gehört zu keinem gezeigten Teil"
                                  + (f" (Zeile {zeile})" if zeile else ""),
                                  "loesung": "Den Namen aus show() angeben oder die gezeigte Form übergeben."})
            out += [n for n in treffer if n not in out]
        return out

    def ergebnis(self, shown: list[str]) -> dict[str, Any]:
        warnungen: list[dict[str, Any]] = []
        erkl: dict[str, Any] = {"montage": [], "erlaubt": [], "befestigt": [], "boden": None, "warnungen": warnungen}
        for art, d in self.eintraege:
            z = d.get("zeile")
            if art == "montage":
                teile = self._namen(d.get("teile") or [], shown, warnungen, "montage", z)
                if not teile:
                    continue
                erkl["montage"].append({
                    "teile": teile, "richtung": [list(r) for r in d.get("richtung") or []],
                    "nach": self._namen(d.get("nach") or [], shown, warnungen, "montage(nach=…)", z),
                    "werkzeug": d.get("werkzeug"), "baugruppe": bool(d.get("baugruppe")),
                    "schnappt": bool(d.get("schnappt")), "zeile": z})
            elif art == "erlaubt":
                a = self._namen(d.get("a") or [], shown, warnungen, "erlaubt_ueberlappung", z)
                b = self._namen(d.get("b") or [], shown, warnungen, "erlaubt_ueberlappung", z)
                if not d.get("grund"):
                    warnungen.append({"teil": (a or ["?"])[0],
                                      "text": "erlaubt_ueberlappung ohne Grund gilt nicht"
                                      + (f" (Zeile {z})" if z else ""),
                                      "loesung": "Grund angeben (z. B. grund=\"Gewinde im Kernloch\"), aber nur nach "
                                                 "Rückfrage bei Kevin; sonst die Durchdringung beheben."})
                    continue
                if a and b:
                    erkl["erlaubt"].append({"a": a, "b": b, "grund": d["grund"], "zeile": z})
            elif art == "befestigt":
                teile = self._namen(d.get("teile") or [], shown, warnungen, "befestigt", z)
                if not d.get("grund"):
                    warnungen.append({"teil": (teile or ["?"])[0],
                                      "text": "befestigt ohne Grund gilt nicht" + (f" (Zeile {z})" if z else ""),
                                      "loesung": "Grund angeben, z. B. grund=\"an der Wand verschraubt\"."})
                    continue
                if teile:
                    erkl["befestigt"].append({"teile": teile, "grund": d["grund"], "zeile": z})
            elif art == "boden":
                erkl["boden"] = {"z": float(d.get("z") or 0.0), "zeile": z}
        return {"teile": {n: self.teile.get(n, {}) for n in shown if n in self.teile}, "erklaerungen": erkl}

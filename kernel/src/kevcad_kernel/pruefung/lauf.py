"""Prüfung im Rechenprozess, direkt nach jedem Lauf.

Der Rechenprozess schickt erst ``RUN_DONE`` (die Laufzeit meldet ``RUN_END`` sofort an die App, der Live-Aufbau ist
fertig) und prüft danach mit den Formen, die er ohnehin im Speicher hat. Das Ergebnis geht als ``CHECK_DONE`` an die
Laufzeit, die es als ``CHECK`` an die App weiterreicht. Kommt währenddessen ein neuer Lauf, bricht die Prüfung ab
(``state: "cancelled"``); was bis dahin gerechnet ist, bleibt im Zwischenspeicher.

Zwischenspeicher über Läufe hinweg: Teilepaare nach Form und relativer Lage (``kollision.PaarCache``), Körper nach
Name und Formschlüssel (samt ihren Projektionen und Strahlschnitten).

Teilweise (Prüftempo, 22.10.2026): Legt eine Prüfung eine ``Fortsetzung`` ab (Bewegungsraum über dem Zeitlimit des
Laufs), geht das Ergebnis als ``state: "teilweise"`` mit ``im_hintergrund`` (offene Wege) hinaus. Der Rechenprozess
ruft danach ``fertig_rechnen`` auf, sobald nichts anderes ansteht: Es rechnet den Rest ohne Zeitlimit, ersetzt die
Befunde der betroffenen Arten und liefert dasselbe Ergebnis vollständig als ``done`` (gleicher Lauf).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kevcad_kernel.pruefung.koerper import Koerper, koerper_aus_topo
from kevcad_kernel.pruefung.kollision import PaarCache
from kevcad_kernel.pruefung.pruefer import Abgebrochen, Fortsetzung, abschliessen, pruefe

# Prüfungen, die nach jedem Lauf laufen (None = alle registrierten: erklaerungen, durchdringung, bedingungen aus
# bedingungen/anbindung.py, stand, montage)
AKTIV: tuple[str, ...] | None = None


class PruefLauf:
    def __init__(self) -> None:
        self.cache = PaarCache()
        self.koerper: dict[tuple[str, str], Koerper] = {}
        self.stand_cache: dict = {}
        # teilweises Ergebnis zum Fertigrechnen: (Lauf, Ergebnis, Schnittkörper, Fortsetzungen)
        self._offen: tuple[int, dict[str, Any], list, dict[str, Fortsetzung]] | None = None

    def koerper_fuer(self, erfassung: Any, shown: list[str], teile: dict[str, dict[str, Any]]) -> list[Koerper]:
        neu: dict[tuple[str, str], Koerper] = {}
        out: list[Koerper] = []
        for name in shown:
            g = erfassung.geometrie.get(name)
            if g is None:
                continue
            key, topo, pos, tri, bbox, props, faces = g
            k = self.koerper.get((name, key))
            if k is None:
                k = koerper_aus_topo(name, key, topo, pos, tri, bbox, props, faces, teile.get(name))
            else:
                k.info = dict(teile.get(name) or {})
            neu[(name, key)] = k
            out.append(k)
        self.koerper = neu
        if len(self.stand_cache) > 5000:
            self.stand_cache.clear()
        return out

    def pruefe(self, run: int, erfassung: Any, shown: list[str], abbrechen: Callable[[], None] | None = None,
               optionen: dict[str, Any] | None = None) -> tuple[dict[str, Any], bytes]:
        """Kopf und Nutzlast von CHECK (ohne seq)."""
        from kevcad_kernel.protocol import pack_check

        daten = erfassung.ergebnis(shown)
        opt = {"pruefungen": AKTIV, **(optionen or {})}
        self._offen = None
        try:
            ks = self.koerper_fuer(erfassung, shown, daten.get("teile") or {})
            erg, geo = pruefe(ks, daten.get("erklaerungen") or {}, opt, self.cache, abbrechen, self.stand_cache)
        except Abgebrochen as exc:
            header, payload = pack_check(run=run, state="cancelled", message=f"Prüfung abgebrochen: {exc}")
        except Exception as exc:  # noqa: BLE001 - die Prüfung darf den Rechenprozess nicht kippen
            import traceback

            header, payload = pack_check(run=run, state="failed",
                                         message=f"Prüfung fehlgeschlagen: {type(exc).__name__}: {exc}")
            header["traceback"] = traceback.format_exc(limit=8)
        else:
            hintergrund: dict[str, Fortsetzung] = erg.pop("_hintergrund", None) or {}
            offen = [n for f in hintergrund.values() for n in f.offen] if hintergrund else None
            header, payload = self._kopf(run, "teilweise" if hintergrund else "done", erg, geo, offen)
            if hintergrund:
                self._offen = (run, erg, geo, hintergrund)
        header.pop("seq", None)
        return header, payload

    def _kopf(self, run: int, state: str, erg: dict[str, Any], geo: list,
              im_hintergrund: list[str] | None = None) -> tuple[dict[str, Any], bytes]:
        from kevcad_kernel.protocol import pack_check

        header, payload = pack_check(run=run, state=state, ergebnis=erg, geometrie=geo, im_hintergrund=im_hintergrund)
        header["statistik"] = {"paare": erg.get("paare"), "zeiten_ms": erg.get("zeiten_ms"),
                               "zwischenspeicher": len(self.cache), "teile": erg.get("teile")}
        if erg.get("druck"):  # Druckprüfung: Ausrichtung und Kennzahlen je Druckteil (druck/anbindung.py)
            header["druck"] = erg["druck"]
        return header, payload

    @property
    def offen(self) -> int | None:
        """Lauf, dessen Ergebnis teilweise ist und noch fertig gerechnet wird (oder None)."""
        return self._offen[0] if self._offen is not None else None

    def fertig_rechnen(self, run: int, abbrechen: Callable[[], None] | None = None
                       ) -> tuple[dict[str, Any], bytes] | None:
        """Rest des teilweisen Ergebnisses von Lauf ``run`` rechnen: Kopf (ohne seq) und Nutzlast von CHECK mit
        ``state: "done"``, oder None, wenn für diesen Lauf nichts offen ist. ``abbrechen`` darf mit ``Abgebrochen``
        unterbrechen (ein Auftrag geht vor); das Teilergebnis bleibt dann offen, der nächste Aufruf setzt fort."""
        import copy
        import time

        if self._offen is None or self._offen[0] != run:
            return None
        _, erg, geo, hintergrund = self._offen
        t0 = time.perf_counter()
        arten = {a for f in hintergrund.values() for a in f.arten}
        befunde = [copy.deepcopy(b) for b in erg.get("befunde") or [] if b.get("art") not in arten]
        zusatz: dict[str, Any] = {}
        try:
            for f in hintergrund.values():
                neu, extra = f.rechne(abbrechen or (lambda: None))
                befunde += neu
                zusatz.update(extra)
        except Abgebrochen:
            raise  # ein Auftrag geht vor; der nächste Aufruf setzt fort
        except Exception as exc:  # noqa: BLE001 - das teilweise Ergebnis bleibt gültig, es kommt nur nichts mehr nach
            self._offen = None
            header, payload = self._kopf(run, "teilweise", erg, geo, [])
            header["message"] = (f"Bewegungsraum im Hintergrund fehlgeschlagen: {type(exc).__name__}: {exc}; "
                                 "erneut run aufrufen")
            header.pop("seq", None)
            return header, payload
        from kevcad_kernel.pruefung import befund as bf

        befunde, geometrie = abschliessen(befunde, geo)
        ms = (time.perf_counter() - t0) * 1000
        fertig = {**erg, **zusatz, "befunde": befunde, "zusammenfassung": bf.zusammenfassung(befunde),
                  "zaehler": bf.zaehler(befunde),
                  "zeiten_ms": {**(erg.get("zeiten_ms") or {}), "hintergrund": round(ms, 1)},
                  "dauer_ms": round(float(erg.get("dauer_ms") or 0.0) + ms, 1)}
        header, payload = self._kopf(run, "done", fertig, geometrie)
        header.pop("seq", None)
        self._offen = None
        return header, payload


# Druckprüfung (Prüfer „druck“, registriert sich beim Import) läuft ebenfalls nach jedem Lauf
from kevcad_kernel.druck import anbindung as _druck_anbindung  # noqa: E402,F401

if AKTIV is not None and "druck" not in AKTIV:
    AKTIV = (*AKTIV, "druck")

# Druckvorschau: Geometrie je Druckteil in Druckausrichtung, direkt nach der Druckprüfung (druck/vorschau_geo.py)
from kevcad_kernel.druck import vorschau_geo as _druck_vorschau_geo  # noqa: E402,F401

if AKTIV is not None and "druckvorschau" not in AKTIV:
    AKTIV = (*AKTIV, "druckvorschau")

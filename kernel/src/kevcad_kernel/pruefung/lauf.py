"""Prüfung im Rechenprozess, direkt nach jedem Lauf.

Der Rechenprozess schickt erst ``RUN_DONE`` (die Laufzeit meldet ``RUN_END`` sofort an die App, der Live-Aufbau ist
fertig) und prüft danach mit den Formen, die er ohnehin im Speicher hat. Das Ergebnis geht als ``CHECK_DONE`` an die
Laufzeit, die es als ``CHECK`` an die App weiterreicht. Kommt währenddessen ein neuer Lauf, bricht die Prüfung ab
(``state: "cancelled"``); was bis dahin gerechnet ist, bleibt im Zwischenspeicher.

Zwischenspeicher über Läufe hinweg: Teilepaare nach Form und relativer Lage (``kollision.PaarCache``), Körper nach
Name und Formschlüssel (samt ihren Projektionen und Strahlschnitten).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kevcad_kernel.pruefung.koerper import Koerper, koerper_aus_topo
from kevcad_kernel.pruefung.kollision import PaarCache
from kevcad_kernel.pruefung.pruefer import Abgebrochen, pruefe

# Prüfungen, die nach jedem Lauf laufen (None = alle registrierten)
AKTIV: tuple[str, ...] | None = None


class PruefLauf:
    def __init__(self) -> None:
        self.cache = PaarCache()
        self.koerper: dict[tuple[str, str], Koerper] = {}
        self.stand_cache: dict = {}

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
            header, payload = pack_check(run=run, state="done", ergebnis=erg, geometrie=geo)
            header["statistik"] = {"paare": erg.get("paare"), "zeiten_ms": erg.get("zeiten_ms"),
                                   "zwischenspeicher": len(self.cache), "teile": erg.get("teile")}
        header.pop("seq", None)
        return header, payload

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

Stufen (V2-1b): Hat sich ein Teil geändert und ist das Modell nicht klein, geht vor Druck, Montage, Statik und Bewegungsraum
ein Zwischenstand hinaus, ebenfalls ``teilweise``, mit ``im_hintergrund`` ["Druck", "Montage", "Statik", "Bewegungsraum"].
Agent und App sehen Durchdringungen, Bedingungen und Stand, während die Prüfung im selben Aufruf weiterrechnet; aus dem
Zwischenspeicher kommt sonst alles im ersten Anlauf, dann bleibt es bei einem ``CHECK``. Wer das Ergebnis einer späteren
Prüfung braucht, wartet mit ``PruefStand.abwarten``. Der Bewegungsraum bekommt in Stufen nur den Rest des Budgets ``VORNE_S``,
was er nicht schafft, rechnet ``fertig_rechnen``. Am Inhalt ändert das nichts: Gerechnet wird dasselbe, der Endstand ist
derselbe. Aus mit ``KEVCAD_PRUEF_STUFEN=0``.

FEM direkt nach der Statik (A1, PLAN-PRUEFUNG-INKREMENTELL.md): Die Statik läuft direkt nach dem Druck. Hat ein Szenario
Teile, die die Laufzeit danach mit der Festkörper-FEM rechnet (``statik/festkoerper/auftrag.kandidaten``), schreibt der
Rechenprozess den Auftrag gleich dort (``auftrag.nach_statik``) und schickt einen zweiten Zwischenstand (``teilweise``,
offen noch Montage und Bewegungsraum) mit Druck, Statik und dem Auftrag (``festkoerper_auftrag``, nur zwischen
Rechenprozess und Laufzeit). Die Laufzeit startet den FEM-Prozess damit sofort statt nach dem Ende der Prüfung über EXEC
(das nimmt der Rechenprozess nur zwischen zwei Aufträgen an). Nicht für Läufe der Versionen und nur mit Stufen.

Bewegungsraum von Beginn an (B2, B3): Gleich nach dem Aufbau der Körper gibt der Rechenprozess die Wege, die nicht im
Zwischenspeicher stehen, an eigene Geometrie-Prozesse (``bedingungen/helfer.py``); an der Stelle des Bewegungsraums holt er
ihre Ergebnisse ab, was noch fehlt, kommt wie bisher im Hintergrund. Ebenfalls nicht für Läufe der Versionen und nur mit
Stufen.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from kevcad_kernel.pruefung.koerper import Koerper, koerper_aus_topo
from kevcad_kernel.pruefung.kollision import PaarCache
from kevcad_kernel.pruefung.pruefer import Abgebrochen, Fortsetzung, abschliessen, pruefe

# Prüfungen, die nach jedem Lauf laufen (None = alle registrierten: erklaerungen, durchdringung, bedingungen aus
# bedingungen/anbindung.py, stand, montage)
AKTIV: tuple[str, ...] | None = None
VORNE_S = 0.7  # Stufen: so lange darf die Prüfung samt Bewegungsraum dauern, bevor der Rest in den Hintergrund geht
KLEIN_S = 0.2  # Stufen: darunter bleibt es bei einem CHECK (die erste Stufe und die letzte Prüfung waren so kurz) …
KLEIN_TEILE = 40  # … und das Modell hat weniger Teile
HINTEN_ZEITEN = ("druck", "druckvorschau", "montage", "statik", "bewegungsraum")
STAENDE_MERKEN = 8  # wie viele geprüfte Stände der Teile (wie die Statik, statik/merken.py)
SCHATTEN_RUN = 1_000_000_000  # Läufe der Versionen (versionen/laufzeit.py SCHATTEN_RUN_BASIS): keine FEM


def stufen_an() -> bool:
    return os.environ.get("KEVCAD_PRUEF_STUFEN", "1").strip().lower() not in ("0", "aus", "false", "nein", "no")


class PruefLauf:
    def __init__(self) -> None:
        self.cache = PaarCache()
        self.koerper: dict[tuple[str, str], Koerper] = {}
        self.stand_cache: dict = {}
        self._staende: list[frozenset[tuple[str, str]]] = []  # Teile der letzten Prüfungen, neueste zuletzt (Stufen)
        self._hinten_ms = 0.0  # längste Dauer von Montage, Statik und Bewegungsraum bisher (Stufen)
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

    def _zwischenstand_noetig(self, ks: list[Koerper], dauer_s: float) -> bool:
        """Lohnt ein Zwischenstand? Nur bei einem neuen Stand der Teile (ein schon geprüfter kommt aus dem Zwischenspeicher,
        auch der vor einer Maßänderung) und wenn das Modell nicht klein ist. Eine falsche Antwort kostet nichts am Ergebnis:
        ein CHECK mehr oder weniger."""
        if frozenset((k.name, k.key) for k in ks) in self._staende:
            return False
        return dauer_s >= KLEIN_S or self._hinten_ms >= KLEIN_S * 1000 or len(ks) >= KLEIN_TEILE

    def pruefe(self, run: int, erfassung: Any, shown: list[str], abbrechen: Callable[[], None] | None = None,
               optionen: dict[str, Any] | None = None,
               zwischenstand: Callable[[dict[str, Any], bytes], None] | None = None) -> tuple[dict[str, Any], bytes]:
        """Kopf und Nutzlast von CHECK (ohne seq). ``zwischenstand(kopf, nutzlast)``: Stufen, siehe Modulbeschreibung."""
        from kevcad_kernel.protocol import pack_check

        daten = erfassung.ergebnis(shown)
        opt = {"pruefungen": AKTIV, **(optionen or {})}
        self._offen = None
        ks: list[Koerper] = []

        def stufe(stand: Callable[[], tuple[dict[str, Any], list]], offen: list[str], dauer_s: float) -> None:
            if zwischenstand is None or not self._zwischenstand_noetig(ks, dauer_s):
                return
            if not _bedingungen.wege_da():
                offen = [o for o in offen if o != "Bewegungsraum"]
            kopf, nutz = self._kopf(run, "teilweise", *stand(), offen)
            kopf.pop("seq", None)
            zwischenstand(kopf, nutz)

        def fem_stufe(stand: Callable[[], tuple[dict[str, Any], list]], offen: list[str], dauer_s: float) -> None:
            """A1: direkt nach der Statik den Auftrag der Festkörper-FEM schreiben und mit diesem Stand schicken; die
            Laufzeit startet den FEM-Prozess damit sofort (über EXEC müsste sie bis zum Ende der Prüfung warten)."""
            if zwischenstand is None or run >= SCHATTEN_RUN:
                return
            from kevcad_kernel.statik.festkoerper.auftrag import nach_statik, verwerfen

            job = None
            try:
                erg, geo = stand()
                job = nach_statik(erg.get("statik"), run)
                if job is None:
                    return
                if not _bedingungen.wege_da():
                    offen = [o for o in offen if o != "Bewegungsraum"]
                kopf, nutz = self._kopf(run, "teilweise", erg, geo, offen)
            except Exception as exc:  # noqa: BLE001 - dann wie bisher: die Laufzeit schreibt den Auftrag nach dem Ende
                import sys

                print(f"Zwischenstand nach der Statik nicht geschickt: {type(exc).__name__}: {exc}", file=sys.stderr)
                verwerfen(job)
                return
            kopf["festkoerper_auftrag"] = job
            kopf.pop("seq", None)
            zwischenstand(kopf, nutz)

        stufen = zwischenstand is not None and stufen_an()
        if stufen:
            opt["vorne_s"] = VORNE_S
        try:
            ks = self.koerper_fuer(erfassung, shown, daten.get("teile") or {})
            vorlauf_ms = None
            if stufen and run < SCHATTEN_RUN:
                import time

                t_vor = time.perf_counter()
                _bedingungen.vorlauf_starten()  # B3: Bewegungsraum bei den Geometrie-Helfern, ab jetzt
                vorlauf_ms = (time.perf_counter() - t_vor) * 1000
            erg, geo = pruefe(ks, daten.get("erklaerungen") or {}, opt, self.cache, abbrechen, self.stand_cache,
                              stufe if stufen else None, nach_statik=fem_stufe if stufen else None)
            if vorlauf_ms is not None:
                erg.setdefault("zeiten_ms", {})["bewegungsraum_vorlauf"] = round(vorlauf_ms, 1)
            zeiten = erg.get("zeiten_ms") or {}
            self._hinten_ms = max(self._hinten_ms, sum(float(zeiten.get(k) or 0.0) for k in HINTEN_ZEITEN))
            stand = frozenset((k.name, k.key) for k in ks)
            self._staende = [s for s in self._staende if s != stand][-(STAENDE_MERKEN - 1):] + [stand]
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
        if erg.get("statik"):  # Statik: Szenarien mit Ampel, S0 und S1 (statik/anbindung.py); die Laufzeit macht STATICS
            header["statik"] = erg["statik"]
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

# Bereits gedruckte Teile: Form gegen gedruckt.json (Strang „Feinschliff 2“, druck/gedruckt.py). Fest nach der
# Druckvorschau einreihen (die Reihenfolge der Importe anderer Module darf das nicht verschieben)
from kevcad_kernel.druck import gedruckt as _druck_gedruckt  # noqa: E402
from kevcad_kernel.pruefung.pruefer import registriere as _registriere  # noqa: E402

_registriere("druckvorschau", _druck_vorschau_geo.pruefe, nach="druck")
_registriere("gedruckt", _druck_gedruckt.pruefe, nach="druckvorschau")

if AKTIV is not None and "gedruckt" not in AKTIV:
    AKTIV = (*AKTIV, "gedruckt")

# Statik Stufe 1 (PLAN-STATIK.md, statik/anbindung.py): ganz am Ende, sie braucht Kontakte, Stand und Druckausrichtung.
# Stand und Montage registrieren sich erst beim Laden der Erweiterungen; deshalb hier laden und danach anhängen
from kevcad_kernel.pruefung.pruefer import lade_erweiterungen as _lade_erweiterungen  # noqa: E402
from kevcad_kernel.statik import anbindung as _statik  # noqa: E402

_lade_erweiterungen()
_registriere("statik", _statik.pruefe)

if AKTIV is not None and "statik" not in AKTIV:
    AKTIV = (*AKTIV, "statik")

# Bewegungsraum zuletzt (V2-1b): Er dauert nach einer Änderung am längsten, und nichts hängt von ihm ab
from kevcad_kernel.bedingungen import anbindung as _bedingungen  # noqa: E402
from kevcad_kernel.pruefung.pruefer import ordnen as _ordnen  # noqa: E402

_registriere("bewegungsraum", _bedingungen.pruefe_bewegungsraum)
# Reihenfolge (Stufen): Stand liest nur Kontakte, Druck liest weder Stand noch Bedingungen; Montage braucht Stand, die Statik
# Stand, Druck (nur die Teile, nicht Vorschau und gedruckt) und die Paare, deshalb erst die Stufe bis zum Zwischenstand,
# dann der Rest. A1 (PLAN-PRUEFUNG-INKREMENTELL.md): die Statik direkt nach dem Druck, damit der Auftrag der
# Festkörper-FEM vor Druckvorschau, gedruckt und Montage hinausgeht (Druckvorschau, gedruckt und Montage lesen nichts aus
# der Statik, die Statik nichts aus ihnen)
REIHENFOLGE = ("erklaerungen", "durchdringung", "bedingungen", "stand", "druck", "statik", "druckvorschau", "gedruckt",
               "montage", "bewegungsraum")
_ordnen(REIHENFOLGE)

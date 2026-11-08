"""Geometrie-Helfer für den Bewegungsraum (B2 und B3, PLAN-PRUEFUNG-INKREMENTELL.md).

Der Bewegungsraum rechnet nach einer Änderung Sekunden lang exakte Schnittmengen (OCCT), und OCP gibt die GIL nicht frei:
Fäden im Rechenprozess bringen nichts. Deshalb rechnen bis zu drei eigene Prozesse („Helfer“) die Wege, gleich zu Beginn
der Prüfung (B3), während der Rechenprozess Durchdringung, Druck, Statik und Montage prüft. Der Bewegungsraum hängt nur am
Stand der Bedingungen und an den Formen, nicht an den anderen Prüfungen.

- Jeder Helfer hält die Formen, die er schon bekommen hat (BRep je Formschlüssel, einmal übertragen), und seine eigenen
  Zwischenspeicher je Teilepaar und Griffraum (``bewegungsraum._PAAR_CACHE``, ``_GRIFF_CACHE``) über Läufe hinweg. Ein Weg
  geht möglichst wieder an denselben Helfer, damit er dort seine Paare findet.
- Die Ergebnisse je Weg merkt der Rechenprozess wie seine eigenen (``bewegungsraum.merken``); die Schlüssel ändern sich
  nicht. Gerechnet wird mit derselben Funktion (``pruefe_bewegung``) an Kopien derselben Formen.
- Ein neuer Auftrag bricht den laufenden ab (das Gerechnete bleibt im Zwischenspeicher des Helfers). Stirbt ein Helfer
  oder scheitert ein Weg, rechnet der Rechenprozess den Weg selbst.
- Zahl nach Speicher (wie die FEM-Teilprozesse, A2): 3, bei Speicherdruck oder unter 25 % frei 2, kritisch oder unter
  12 % frei 1. ``KEVCAD_GEO_HELFER``: 0 schaltet ab, eine Zahl erzwingt sie (auch für kleine Modelle; Tests).
- Helfer rechnen mit nice 5: Statik und FEM liegen auf dem Weg zum Endstand, der Bewegungsraum erst nach der Montage.
- Gesendet wird aus einem eigenen Faden (ein Auftrag mit vielen Formen blockiert sonst den Rechenprozess, bis der
  Helfer liest), und Arbeit bekommen nur Helfer, die ihre Module schon geladen haben (rund 3 s nach dem Start).
- Helfer beenden sich, wenn der Rechenprozess nicht mehr lebt oder die Verbindung zu ihm abreißt.
- Nach 10 Minuten ohne Prüfung beendet der Rechenprozess die Helfer (Kevins MacBook hat 16 GB, drei Helfer belegen
  zusammen bis 1,2 GB) und startet sie zu Beginn des nächsten Laufs wieder (``aufwecken``), während model.py läuft.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from collections import OrderedDict
from typing import Any

HELFER_ENV = "KEVCAD_GEO_HELFER"
HELFER_MAX = 3
FREI_STUFEN = ((25.0, 3), (12.0, 2))  # freier Anteil in Prozent → höchstens so viele Helfer
DAUER_ANNAHME_MS = 500.0  # Weg ohne Erfahrung
KLEIN_TEILE = 40  # kleinere Modelle rechnen den Bewegungsraum selbst (wie die Stufen der Prüfung) …
KLEIN_MS = 300.0  # … außer der Bewegungsraum brauchte zuletzt mindestens so lange
NICE = 5  # Priorität der Helfer (Unix nice): Statik und FEM gehen vor
STATIK_ENV = "KEVCAD_STATIK_HELFER"  # "0": Statik-Schnitte nicht über die Helfer (Vergleiche)
LEERLAUF_ENV = "KEVCAD_GEO_HELFER_LEERLAUF_S"
LEERLAUF_S = 600.0  # ohne Prüfung so lange: Helfer beenden (Speicher), beim nächsten Lauf wieder starten


def erzwungen() -> int | None:
    """``KEVCAD_GEO_HELFER`` als Zahl (0 = aus) oder None (nach Speicher)."""
    w = (os.environ.get(HELFER_ENV) or "").strip()
    if not w:
        return None
    try:
        return max(0, min(int(w), 8))
    except ValueError:
        return None


def anzahl() -> int:
    """Wie viele Helfer jetzt rechnen dürfen."""
    n = erzwungen()
    if n is not None:
        return n
    from kevcad_kernel.statik.festkoerper.prozess import speicher_lage

    frei, druck = speicher_lage()
    n = HELFER_MAX
    if druck is not None and druck >= 4:
        n = 1
    elif druck is not None and druck >= 2:
        n = min(n, 2)
    if frei is not None:
        n = min(n, next((k for grenze, k in FREI_STUFEN if frei >= grenze), 1))
    return max(1, n)


# ---------------------------------------------------------------------------------------------------------------------
# Seite des Rechenprozesses


class _Helfer:
    def __init__(self, nr: int, eingang: queue.Queue) -> None:
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        self.nr = nr
        self.conn, kind = ctx.Pipe(duplex=True)
        self.proc = ctx.Process(target=_helfer_main, args=(kind, os.getpid()), daemon=True, name=f"kevcad-geo-{nr}")
        self.proc.start()
        kind.close()
        self.bekannt: set[str] = set()  # Formschlüssel, die der Helfer schon hat
        self.tot = False
        self.bereit = False  # hat seine Module geladen (meldet „bereit“)
        # Gesendet wird aus einem eigenen Faden: Ein Auftrag mit vielen Formen füllt den Puffer der Verbindung, und ein
        # frisch gestarteter Helfer liest erst nach dem Laden seiner Module (rund 3 s); so lange hielt das Senden die
        # Prüfung im Rechenprozess an
        self._ausgang: queue.Queue = queue.Queue()
        threading.Thread(target=self._lesen, args=(eingang,), name=f"geo-helfer-{nr}", daemon=True).start()
        threading.Thread(target=self._schreiben, name=f"geo-helfer-{nr}-senden", daemon=True).start()

    def _lesen(self, eingang: queue.Queue) -> None:
        while True:
            try:
                msg = self.conn.recv()
            except (EOFError, OSError):
                self.tot = True
                eingang.put((self.nr, ("tot",)))
                return
            except Exception as exc:  # noqa: BLE001 - kaputte Nachricht: Helfer gilt als tot
                self.tot = True
                eingang.put((self.nr, ("tot", repr(exc))))
                return
            if msg and msg[0] == "bereit":
                self.bereit = True
                continue
            eingang.put((self.nr, msg))

    def _schreiben(self) -> None:
        while True:
            msg = self._ausgang.get()
            try:
                self.conn.send(msg)
            except (OSError, ValueError, EOFError):
                self.tot = True
                return
            except Exception as exc:  # noqa: BLE001 - nicht übertragbar: Helfer gilt als tot, der Rechenprozess rechnet
                print(f"Geometrie-Helfer {self.nr}: Senden fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)
                self.tot = True
                return
            if msg and msg[0] == "ende":
                return

    def lebt(self) -> bool:
        return not self.tot and self.proc.is_alive()

    def senden(self, msg: tuple) -> bool:
        if self.tot:
            return False
        self._ausgang.put(msg)
        return True

    def beenden(self) -> None:
        self.senden(("ende",))
        try:
            self.proc.join(1.0)
        except Exception:  # noqa: BLE001
            pass
        if self.proc.is_alive():
            self.proc.terminate()


class Auftrag:
    """Wege eines Laufs bei den Helfern. ``ergebnis(i, warten_s, abbrechen)`` liefert das Ergebnis von Weg ``i``,
    ``FEHLT`` (Helfer tot oder Fehler: selbst rechnen) oder None (noch nicht da)."""

    FEHLT = object()

    def __init__(self, pool: Pool, jid: int, verteilung: dict[int, int]) -> None:
        self.pool = pool
        self.jid = jid
        self.verteilung = verteilung  # Weg → Helfer
        self.da: dict[int, Any] = {}
        self.dauer_ms: dict[int, float] = {}

    def _einsammeln(self, warten_s: float) -> None:
        ende = time.monotonic() + max(0.0, warten_s)
        while True:
            rest = ende - time.monotonic()
            try:
                nr, msg = self.pool.eingang.get(timeout=rest) if rest > 0 else self.pool.eingang.get_nowait()
            except queue.Empty:
                return
            self.pool.verarbeite(nr, msg)
            if msg and msg[0] in ("weg", "fehler") and msg[1] == self.jid:
                return  # etwas Neues für diesen Auftrag: der Aufrufer schaut nach
            if msg and msg[0] == "tot":
                return

    def ergebnis(self, i: int, warten_s: float | None, abbrechen: Any = None) -> Any:
        """``warten_s`` None: warten, bis es da ist (``abbrechen`` darf unterbrechen)."""
        ende = None if warten_s is None else time.monotonic() + warten_s
        while True:
            if i in self.da:
                return self.da[i]
            if self.pool.aktiv is not self:  # überholt (neuer Auftrag): nichts kommt mehr
                return Auftrag.FEHLT
            nr = self.verteilung.get(i)
            h = self.pool.helfer.get(nr) if nr is not None else None
            if h is None or not h.lebt():
                self._einsammeln(0.0)  # was noch unterwegs war
                return self.da.get(i, Auftrag.FEHLT)
            if abbrechen is not None:
                abbrechen()
            rest = 0.05 if ende is None else min(0.05, ende - time.monotonic())
            if rest <= 0:
                self._einsammeln(0.0)
                return self.da.get(i)
            self._einsammeln(rest)


class Pool:
    """Die Helfer des Rechenprozesses (einer je Rechenprozess, ``pool()``)."""

    def __init__(self) -> None:
        self.helfer: dict[int, _Helfer] = {}
        self.eingang: queue.Queue = queue.Queue()
        self._jid = 0
        self.aktiv: Auftrag | None = None
        self.zuordnung: dict[str, int] = {}  # Weg → Helfer beim letzten Mal (dort liegen seine Paare)
        self.dauer_ms: dict[str, float] = {}  # Weg → Rechenzeit beim letzten Mal
        self._breps: OrderedDict[str, bytes] = OrderedDict()
        # Leerlauf: nach LEERLAUF_S ohne Auftrag beenden (Speicher), beim nächsten Lauf wieder starten (``aufwecken``)
        self._lock = threading.RLock()
        self._rid = 0
        self._schnitt_da: dict[int, dict[int, Any]] = {}  # Statik-Schnitte (B2): Anfrage → Index → Ergebnis
        self.zuletzt = time.monotonic()
        self.schlafend = 0  # so viele Helfer liefen, bevor der Leerlauf sie beendet hat
        self._waechter: threading.Thread | None = None

    def _wache_starten(self) -> None:
        if self._waechter is not None and self._waechter.is_alive():
            return
        self._waechter = threading.Thread(target=self._wache, name="geo-helfer-leerlauf", daemon=True)
        self._waechter.start()

    def _wache(self) -> None:
        while True:
            time.sleep(max(0.2, min(30.0, leerlauf_s() / 4)))
            self.leerlauf_pruefen()

    def leerlauf_pruefen(self, jetzt: float | None = None) -> bool:
        """Helfer beenden, wenn seit ``leerlauf_s()`` kein Auftrag kam und keiner mehr rechnet. True, wenn beendet."""
        with self._lock:
            jetzt = time.monotonic() if jetzt is None else jetzt
            lebend = [h for h in self.helfer.values() if h.lebt()]
            if not lebend or jetzt - self.zuletzt < leerlauf_s():
                return False
            a = self.aktiv
            if a is not None and any(i not in a.da for i in a.verteilung):
                return False  # ein Auftrag rechnet noch (bei 10 min Leerlauf kaum denkbar)
            n = max(self.helfer) + 1 if self.helfer else 0
            self.beenden()
            self.schlafend = n
            print(f"Geometrie-Helfer: {len(lebend)} nach {leerlauf_s():.0f} s ohne Prüfung beendet", file=sys.stderr)
            return True

    def aufwecken(self) -> int:
        """Vom Leerlauf beendete Helfer wieder starten (beim nächsten Lauf, damit sie bis zur Prüfung geladen haben).
        Gibt die Zahl der gestarteten zurück."""
        with self._lock:
            n = self.schlafend
            if not n or self.helfer:
                return 0
            self.schlafend = 0
            self.zuletzt = time.monotonic()
            self._helfer_bereit(min(n, anzahl()))
            self._wache_starten()
            return len(self.helfer)

    def _helfer_bereit(self, n: int) -> list[_Helfer]:
        """Die ersten ``n`` Helfer, fehlende oder tote neu gestartet. Rechnen sollen nur die, die schon bereit sind
        (ein frischer Helfer lädt rund 3 s): Ist mindestens einer bereit, bekommen nur die bereiten Arbeit, die neuen
        erst beim nächsten Auftrag; sonst (der erste Auftrag) alle."""
        for nr in range(n):
            h = self.helfer.get(nr)
            if h is None or not h.lebt():
                if h is not None:
                    h.beenden()
                self.helfer[nr] = _Helfer(nr, self.eingang)
        alle = [self.helfer[nr] for nr in range(n)]
        return [h for h in alle if h.bereit] or alle

    def verarbeite(self, nr: int, msg: tuple) -> None:
        self.zuletzt = time.monotonic()
        a = self.aktiv
        if not msg:
            return
        if msg[0] == "weg" and a is not None and msg[1] == a.jid:
            _, _, i, erg, ms = msg
            a.da[i] = erg
            a.dauer_ms[i] = ms
        elif msg[0] == "fehler" and a is not None and msg[1] == a.jid:
            _, _, i, text = msg
            print(f"Geometrie-Helfer {nr}: Weg {i} fehlgeschlagen, rechne selbst: {text}", file=sys.stderr)
            a.da[i] = Auftrag.FEHLT
        elif msg[0] == "schnitt_erg":
            _, rid, i, erg = msg
            if rid in self._schnitt_da:
                self._schnitt_da[rid][i] = erg
        elif msg[0] == "tot":
            h = self.helfer.get(nr)
            if h is not None:
                h.tot = True

    def brep(self, fk: str, form: Any) -> bytes:
        hit = self._breps.get(fk)
        if hit is not None:
            self._breps.move_to_end(fk)
            return hit
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
        from OCP.TopLoc import TopLoc_Location

        from kevcad_kernel.tessellate import serialize_shape

        w = form.wrapped if hasattr(form, "wrapped") else form
        data = serialize_shape(BRepBuilderAPI_Copy(w.Located(TopLoc_Location()), True, False).Shape())
        self._breps[fk] = data
        while len(self._breps) > 400:
            self._breps.popitem(last=False)
        return data

    def verteilen(self, wege: list[tuple[int, str]], n: int, zuordnung: dict[str, int] | None = None
                  ) -> dict[int, int]:
        """Weg (Index, Name) → Helfer 0 … n−1: längste zuerst an den am wenigsten belasteten, aber an den vom letzten Mal
        (``zuordnung``, sonst ``self.zuordnung``), wenn der höchstens eine halbe Wegdauer mehr hat (dort liegen seine
        Paare)."""
        zuordnung = self.zuordnung if zuordnung is None else zuordnung
        last = [0.0] * n
        out: dict[int, int] = {}
        for i, name in sorted(wege, key=lambda w: -self.dauer_ms.get(w[1], DAUER_ANNAHME_MS)):
            d = self.dauer_ms.get(name, DAUER_ANNAHME_MS)
            k = min(range(n), key=lambda j: last[j])
            alt = zuordnung.get(name)
            if alt is not None and alt < n and last[alt] <= last[k] + 0.5 * d:
                k = alt
            out[i] = k
            last[k] += d
        return out

    def auftrag(self, wege: list[tuple[int, Any, list[str]]], formen: dict[str, Any], schluessel: dict[str, str],
                boxen: dict[str, tuple[Any, Any]], n: int) -> Auftrag | None:
        """Wege (Index, Bewegung, beteiligte Teile) an ``n`` Helfer. None, wenn keiner startet."""
        with self._lock:
            self.zuletzt = time.monotonic()
            self.schlafend = 0
            self._wache_starten()
            return self._auftrag(wege, formen, schluessel, boxen, n)

    def _auftrag(self, wege: list[tuple[int, Any, list[str]]], formen: dict[str, Any], schluessel: dict[str, str],
                 boxen: dict[str, tuple[Any, Any]], n: int) -> Auftrag | None:
        import numpy as np

        from kevcad_kernel.pruefung.koerper import _FORMEN, form_schluessel, lage_von

        self.abbrechen()
        try:
            helfer = self._helfer_bereit(n)
        except Exception as exc:  # noqa: BLE001 - dann rechnet der Rechenprozess wie bisher selbst
            print(f"Geometrie-Helfer starten fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)
            return None
        self._jid += 1
        jid = self._jid
        nummern = [h.nr for h in helfer]
        pos = self.verteilen([(i, bew.name) for i, bew, _ in wege], len(helfer),
                             {name: nummern.index(nr) for name, nr in self.zuordnung.items() if nr in nummern})
        verteilung = {i: nummern[k] for i, k in pos.items()}
        a = Auftrag(self, jid, verteilung)
        self.aktiv = a
        fks: dict[str, str] = {}
        for h in helfer:
            nr = h.nr
            meine = [(i, bew, namen) for i, bew, namen in wege if verteilung[i] == nr]
            if not meine:
                continue
            teile: dict[str, tuple] = {}
            neu: dict[str, bytes] = {}
            for _, _, namen in meine:
                for name in namen:
                    if name in teile:
                        continue
                    form = formen[name]
                    wk = schluessel.get(name) or ""
                    fk = fks.get(name)
                    if fk is None:
                        fk = (_FORMEN.get(wk) if wk else None) or form_schluessel(form.wrapped)
                        fks[name] = fk
                    lo, hi = boxen[name] if name in boxen else (None, None)
                    teile[name] = (wk, fk, lage_von(form.wrapped),
                                   None if lo is None else (np.asarray(lo, float), np.asarray(hi, float)))
                    if fk not in h.bekannt and fk not in neu:
                        neu[fk] = self.brep(fk, form)
            if h.senden(("auftrag", jid, neu, teile, [(i, bew) for i, bew, _ in meine])):
                h.bekannt.update(neu)
            for i, bew, _ in meine:
                self.zuordnung[bew.name] = nr
        return a

    def schnitte(self, form: str, welt: str, shape: Any, auftraege: list[tuple[Any, Any, float]],
                 selbst: Any) -> list[Any]:
        """Statik-Schnitte (B2, ``statik.bauteil.schnitte``): die Schnittebenen ``auftraege`` (Punkt, Richtung, Größe)
        reihum auf diesen Prozess (``selbst(i)`` rechnet hier) und die bereiten Helfer verteilen. Die Helfer ziehen sie
        zwischen zwei Schnittmengen des Bewegungsraums vor. Ist dieser Prozess mit seinen Ebenen fertig, rechnet er die
        noch nicht gelieferten selbst (nie langsamer als nacheinander); gerechnet wird überall mit derselben Funktion."""
        import numpy as np

        from kevcad_kernel.pruefung.koerper import lage_von

        with self._lock:
            helfer = [h for h in self.helfer.values() if h.bereit and h.lebt()]
            if not helfer or len(auftraege) < 2:
                return [selbst(i) for i in range(len(auftraege))]
            self._rid += 1
            rid = self._rid
            self._schnitt_da[rid] = {}
            L = lage_von(shape)
            wer: dict[int, Any] = {}
            plaetze = [None, *helfer]  # None: dieser Prozess
            je: dict[int, list[tuple[int, Any]]] = {}
            for i, a in enumerate(auftraege):
                h = plaetze[i % len(plaetze)]
                if h is not None:
                    je.setdefault(h.nr, []).append((i, a))
                    wer[i] = h
            for h in helfer:
                meine = je.get(h.nr)
                if not meine:
                    continue
                brep = None if form in h.bekannt else self.brep(form, _Koerperform(shape))
                if h.senden(("schnitte", rid, form, welt, L, brep,
                             [(i, np.asarray(S, float), np.asarray(e, float), float(g)) for i, (S, e, g) in meine])):
                    h.bekannt.add(form)
                else:
                    for i, _ in meine:
                        wer.pop(i, None)
        out: dict[int, Any] = {}
        da = self._schnitt_da[rid]

        def einsammeln() -> None:
            while True:
                try:
                    nr, msg = self.eingang.get_nowait()
                except queue.Empty:
                    return
                self.verarbeite(nr, msg)

        def nehmen(i: int) -> bool:
            erg = da.get(i)
            if isinstance(erg, dict) and "r" in erg:
                out[i] = erg["r"]
                return True
            return False

        for i in range(len(auftraege)):
            if i not in wer:
                out[i] = selbst(i)
        # Arbeit stehlen: Ebenen, die ein Helfer noch nicht geliefert hat (er rechnet vielleicht gerade eine Schnittmenge
        # des Bewegungsraums), rechnet dieser Prozess selbst; das Ergebnis ist dasselbe, das erste zählt
        offen = [i for i in wer]
        while offen:
            einsammeln()
            offen = [i for i in offen if not nehmen(i)]
            if offen:
                i = offen.pop()
                out[i] = selbst(i)
        self._schnitt_da.pop(rid, None)
        return [out[i] for i in range(len(auftraege))]

    def abbrechen(self) -> None:
        """Laufenden Auftrag abbrechen (neuer Lauf); die Helfer behalten, was sie schon gerechnet haben."""
        if self.aktiv is None:
            return
        for h in self.helfer.values():
            if h.lebt():
                h.senden(("abbruch", self.aktiv.jid))
        self.aktiv = None

    def dauer_merken(self, name: str, ms: float) -> None:
        self.dauer_ms[name] = float(ms)

    def beenden(self) -> None:
        with self._lock:
            for h in self.helfer.values():
                h.beenden()
            self.helfer.clear()
            self.aktiv = None


class _Koerperform:
    """TopoDS-Form mit ``wrapped`` (für ``Pool.brep``)."""

    def __init__(self, shape: Any) -> None:
        self.wrapped = shape


def schnitte_verteilen(k: Any, auftraege: list[tuple[Any, Any, float]], selbst: Any) -> list[Any] | None:
    """Statik-Schnitte eines Körpers der Prüfung über die Helfer (B2). None: keine bereiten Helfer (dann rechnet der
    Aufrufer wie bisher selbst)."""
    p = _POOL
    if p is None or erzwungen() == 0 or not getattr(k, "form", None) or not getattr(k, "key", None):
        return None
    if (os.environ.get(STATIK_ENV) or "1").strip().lower() in ("0", "aus", "false", "nein", "no"):
        return None
    if not any(h.bereit and h.lebt() for h in list(p.helfer.values())):
        return None
    return p.schnitte(k.form, k.key, k.shape, auftraege, selbst)


_POOL: Pool | None = None


def pool() -> Pool:
    global _POOL
    if _POOL is None:
        _POOL = Pool()
    return _POOL


def leerlauf_s() -> float:
    """Nach so vielen Sekunden ohne Prüfung beendet der Rechenprozess die Helfer (``KEVCAD_GEO_HELFER_LEERLAUF_S``,
    Vorgabe 600: Kevins MacBook hat 16 GB, drei Helfer belegen zusammen bis 1,2 GB)."""
    try:
        return max(0.1, float(os.environ.get(LEERLAUF_ENV) or LEERLAUF_S))
    except ValueError:
        return LEERLAUF_S


def aufwecken() -> None:
    """Zu Beginn eines echten Laufs (``worker.py``): vom Leerlauf beendete Helfer gleich wieder starten. Sie laden
    rund 3 s, der Lauf selbst dauert bei großen Modellen etwa so lange; so warten die Wege nicht auf den Start."""
    if _POOL is None:
        return
    try:
        _POOL.aufwecken()
    except Exception as exc:  # noqa: BLE001 - dann startet der nächste Auftrag sie
        print(f"Geometrie-Helfer aufwecken fehlgeschlagen: {type(exc).__name__}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------------
# Seite des Helfers


class _Neu(Exception):
    """Ein neuer Auftrag (oder Abbruch, Ende) ist da: den laufenden verlassen."""


def _helfer_main(conn: Any, eltern: int) -> None:  # pragma: no cover - läuft im eigenen Prozess (Tests über den Pool)
    import collections

    def wache() -> None:
        while True:
            time.sleep(1.0)
            if os.getppid() != eltern:
                os._exit(3)

    threading.Thread(target=wache, name="geo-wache", daemon=True).start()
    # Rechnen mit wenigen Fäden und niedrigerer Priorität: Die Helfer laufen neben Statik und FEM, die auf dem Weg zum
    # Endstand liegen; der Bewegungsraum wird erst nach der Montage gebraucht
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(v, "1")
    try:
        os.nice(NICE)
    except OSError:
        pass
    from kevcad_kernel.schnellstart import build123d_laden

    build123d_laden()
    from build123d import Shape
    from OCP.TopLoc import TopLoc_Location

    from kevcad_kernel.bedingungen import bewegungsraum as bw
    from kevcad_kernel.bedingungen.geometrie import matrix_trsf
    from kevcad_kernel.pruefung import koerper
    from kevcad_kernel.tessellate import deserialize_shape

    conn.send(("bereit",))
    roh: OrderedDict[str, Any] = OrderedDict()  # Formschlüssel → TopoDS ohne Lage
    welt: OrderedDict[str, Any] = OrderedDict()  # Weltschlüssel → Form in Weltlage
    vorrat: collections.deque = collections.deque()

    def naechste() -> tuple:
        return vorrat.popleft() if vorrat else conn.recv()

    def form_holen(wk: str, fk: str, L: Any) -> Any:
        f = welt.get(wk) if wk else None
        if f is None:
            f = Shape.cast(roh[fk].Located(TopLoc_Location(matrix_trsf(L))))
            if wk:
                welt[wk] = f
                koerper._FORMEN[wk] = fk
        return f

    def schnitte(msg: tuple) -> None:
        """Statik-Schnitte (B2): kurz, deshalb sofort, auch zwischen zwei Schnittmengen eines Wegs."""
        from kevcad_kernel.statik.bauteil import _schnitt

        _, rid, fk, wk, L, brep, items = msg
        try:
            if brep is not None:
                roh[fk] = deserialize_shape(brep).wrapped
            shape = form_holen(wk, fk, L).wrapped
        except Exception:  # noqa: BLE001 - der Rechenprozess rechnet selbst
            for i, *_ in items:
                conn.send(("schnitt_erg", rid, i, None))
            return
        for i, S, e, g in items:
            try:
                conn.send(("schnitt_erg", rid, i, {"r": _schnitt(shape, S, e, g)}))
            except Exception:  # noqa: BLE001
                conn.send(("schnitt_erg", rid, i, None))

    def abbrechen() -> None:
        while conn.poll():
            m = conn.recv()
            if m and m[0] == "schnitte":
                schnitte(m)
                continue
            vorrat.append(m)
        if vorrat:
            raise _Neu()

    while True:
        try:
            msg = naechste()
        except (EOFError, OSError):
            return
        if not msg or msg[0] == "ende":
            return
        if msg[0] == "schnitte":
            schnitte(msg)
            continue
        if msg[0] != "auftrag":
            continue
        _, jid, neue, teile, wege = msg
        for fk, data in neue.items():
            roh[fk] = deserialize_shape(data).wrapped
        while len(roh) > 3000:
            roh.popitem(last=False)
        formen: dict[str, Any] = {}
        schluessel: dict[str, str] = {}
        boxen: dict[str, Any] = {}
        try:
            for name, (wk, fk, L, box) in teile.items():
                f = form_holen(wk, fk, L)
                formen[name] = f
                if wk:
                    schluessel[name] = wk
                if box is not None:
                    boxen[name] = box
            while len(welt) > 3000:
                welt.popitem(last=False)
        except Exception as exc:  # noqa: BLE001 - Form fehlt (Helfer neu gestartet): alles selbst rechnen lassen
            for i, _ in wege:
                conn.send(("fehler", jid, i, f"Formen: {type(exc).__name__}: {exc}"))
            continue
        bw._BOXEN.clear()
        for name, f in formen.items():
            if name in boxen:
                bw._BOXEN[id(f)] = boxen[name]
        try:
            for i, bew in wege:
                t0 = time.perf_counter()
                try:
                    erg = bw.pruefe_bewegung(bew, formen, schluessel, None, abbrechen)
                except _Neu:
                    raise
                except Exception as exc:  # noqa: BLE001
                    import traceback

                    conn.send(("fehler", jid, i, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"))
                    continue
                conn.send(("weg", jid, i, erg, (time.perf_counter() - t0) * 1000))
            conn.send(("fertig", jid))
        except _Neu:
            pass
        finally:
            bw._BOXEN.clear()

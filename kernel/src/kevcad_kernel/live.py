"""V2-5 Live im Kernel (PROTOCOL.md, Abschnitt „V2-5 Live“; Format und Beispiele in protocol.py).

- ``LiveVerbindung``: die Weiche je App-Verbindung. ``AppConnection.send`` ruft ``filtern`` unter der Sperre der
  Verbindung, also genau in der Reihenfolge, in der die Rahmen auf den Draht gehen. Die Laufzeit erzeugt jede
  Nachricht mit den neuen Feldern (``PART_UPSERT.inhalt``, ``RUN_END.teile``, Netzköpfe mit ``inhalt``); die Weiche
  nimmt sie für Apps ohne ``delta-1`` heraus (sobald deren HELLO_APP da ist), lässt neue Nachrichtentypen nur zu Apps
  mit der passenden Fähigkeit und ersetzt für Apps mit ``delta-1``, was sie schon haben: ``PART_SAME`` statt
  ``PART_UPSERT`` (die App hält je Teil die letzten ``TEIL_INHALTE`` Inhalte), Statikfelder und Animationen gar
  nicht, große JSON-Nachrichten als ``WIE_ZUVOR``, Netze im Versionsbild durch Verweise. Sie merkt sich dafür, was die
  App von dieser Verbindung schon hat.
- ``Agentenspur``: die letzten 50 Schritte des Agenten (``AGENT_SCHRITT``, ``AGENT_SPUR``).
- ``aktueller_schritt``: Kontextvariable mit dem Schritt der laufenden MCP-Anfrage (gesetzt von der MCP-Hülle in
  ``mcp_tools/tracking.py``); die Tätigkeitsanzeige und ``run`` hängen darüber Text und Phasen an den Schritt.
- ``LiveRuntime``: Teil von ``KernelRuntime`` für HELLO_APP, PARTS_REQ, NOCHMAL, LAGE, IN_ARBEIT, die Agentenspur,
  das Lagebild und die Live-Maße.
"""

from __future__ import annotations

import collections
import contextvars
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from kevcad_kernel.protocol import (
    FAEHIGKEIT_DELTA, FAEHIGKEIT_IN_ARBEIT, FAEHIGKEIT_LAGE, FAEHIGKEIT_LIVE_MASSE, FAEHIGKEIT_SPUR, IN_ARBEIT_NACH_S,
    KERNEL_FAEHIGKEITEN, LAGE_WARTEN_S, LIVE_NACHRICHTEN, SPUR_FELDER, SPUR_LAENGE, SPUR_TEXT_MAX, TEIL_INHALTE,
    WIE_ZUVOR_ANTEIL, WIE_ZUVOR_ARTEN, WIE_ZUVOR_BASEN, inhalt_schluessel, kanonisch, netz_bytes, part_same,
    patch_anwenden, strukturpatch, wie_zuvor,
)

PARAM_ANZEIGE_S = 4.0  # so lange zeigt die App ein geändertes Maß am Teil
PARAM_TEILE_MAX = 24  # höchstens so viele Teile hervorheben
_ZAEHLER = ("PART_SAME", "PART_UPSERT", "WIE_ZUVOR", "voll", "STATICS_FIELD weg", "ANIM_DEF weg",
            "ANIM_COLLISIONS weg", "Netze aus der Szene", "ohne Fähigkeit weg")


# =====================================================================================================================
# Schritt der laufenden MCP-Anfrage
# =====================================================================================================================


@dataclass(frozen=True)
class SchrittBezug:
    """Schritt der Agentenspur, zu dem die laufende Anfrage gehört; ``melden`` nimmt Ereignisse (``agent_schritt``)."""

    id: str
    melden: Callable[[dict[str, Any]], None]

    def ereignis(self, **felder: Any) -> None:
        try:
            self.melden({"id": self.id, **felder})
        except Exception:  # noqa: BLE001 - die Spur darf nie ein Werkzeug scheitern lassen
            pass


aktueller_schritt: contextvars.ContextVar[SchrittBezug | None] = contextvars.ContextVar("kevcad_schritt",
                                                                                         default=None)


def _kuerzen(text: Any) -> str | None:
    if text is None:
        return None
    t = str(text).strip()
    if not t:
        return None
    t = t.splitlines()[0]
    return t if len(t) <= SPUR_TEXT_MAX else t[:SPUR_TEXT_MAX - 1] + "…"


# =====================================================================================================================
# Weiche je Verbindung
# =====================================================================================================================


@dataclass
class _Basis:
    """Ein Rahmen einer WIE_ZUVOR-Art, wie die App ihn hat (Kopf ohne seq als JSON-Wert und als Text)."""

    seq: int
    kopf: dict[str, Any]
    text: str
    nutzlast: bytes


class LiveVerbindung:
    """Was eine App-Verbindung kann und was sie schon hat. Nur unter der Sperre der Verbindung benutzen
    (``AppConnection``); ``faehigkeiten`` setzt ``AppConnection.set_faehigkeiten``."""

    def __init__(self) -> None:
        self.faehigkeiten: frozenset[str] = frozenset()
        self.gemeldet = False  # HELLO_APP da (Fähigkeiten bekannt)
        self.teile: dict[str, list[str]] = {}  # Name → Inhalte, die die App hält (der gezeigte zuletzt)
        self.delta_lauf: int | None = None  # Lauf, dessen RUN_START mit delta: true ging
        self.felder: dict[tuple[str, str], list[Any]] = {}  # (szenario, teil) → Schlüssel der Felder der App
        self.anim: dict[str, str] = {}  # Name → Prüfsumme des zuletzt geschickten ANIM_DEF
        self.kollisionen: dict[str, str] = {}  # Name → Prüfsumme des zuletzt geschickten ANIM_COLLISIONS
        self.basen: dict[str, collections.deque[_Basis]] = {}
        self.projekt: str | None = None
        self.zaehler: collections.Counter[str] = collections.Counter()

    # -- Fähigkeiten ---------------------------------------------------------------------------------------------------

    def hat(self, faehigkeit: str) -> bool:
        return faehigkeit in self.faehigkeiten

    def melden(self, faehigkeiten: Any) -> None:
        """HELLO_APP: Fähigkeiten der App übernehmen (unbekannte bleiben stehen, nutzt aber niemand)."""
        self.faehigkeiten = frozenset(str(f) for f in (faehigkeiten or []) if isinstance(f, str))
        self.gemeldet = True
        if not self.hat(FAEHIGKEIT_DELTA):
            self.basen.clear()  # ältere App: keine Basen für WIE_ZUVOR mehr nötig

    @property
    def delta(self) -> bool:
        return FAEHIGKEIT_DELTA in self.faehigkeiten

    @property
    def alt(self) -> bool:
        """Ältere App: HELLO_APP ohne delta-1 (vorher kennt der Kernel die App nicht und lässt die Felder drin)."""
        return self.gemeldet and not self.delta

    def hat_inhalt(self, name: Any, inhalt: Any) -> bool:
        return bool(inhalt) and inhalt in self.teile.get(name, ())

    def _zeige(self, name: str, inhalt: str) -> None:
        """Wie die App: ``inhalt`` wird der gezeigte Inhalt von ``name``, höchstens TEIL_INHALTE bleiben."""
        liste = self.teile.setdefault(name, [])
        if inhalt in liste:
            liste.remove(inhalt)
        liste.append(inhalt)
        del liste[:-TEIL_INHALTE]

    # -- Abfragen der Laufzeit -----------------------------------------------------------------------------------------

    def vergessen(self, namen: list[str]) -> None:
        """PARTS_REQ: diese Teile beim nächsten Senden vollständig schicken."""
        for n in namen:
            self.teile.pop(n, None)

    def neueste(self, art: str) -> tuple[dict[str, Any], bytes] | None:
        """NOCHMAL: die neueste Nachricht der Art, wie die App sie zuletzt bekam (Kopf ohne seq)."""
        basen = self.basen.get(art)
        if not basen:
            return None
        b = basen[-1]
        return json.loads(b.text), b.nutzlast

    # -- Weiche --------------------------------------------------------------------------------------------------------

    def filtern(self, header: dict[str, Any], payload: bytes, seq: int, *, vollstaendig: bool = False
                ) -> tuple[dict[str, Any], bytes] | None:
        """Was diese App statt ``header``/``payload`` bekommt (None: nichts). ``seq``: Nummer, die der Rahmen bekommt.
        ``vollstaendig``: nichts weglassen und nichts durch WIE_ZUVOR ersetzen (Antwort auf NOCHMAL)."""
        art = header.get("type")
        noetig = LIVE_NACHRICHTEN.get(art)
        if noetig is not None and noetig not in self.faehigkeiten:
            self.zaehler["ohne Fähigkeit weg"] += 1
            return None
        delta = self.delta
        darf = delta and not vollstaendig
        if art == "PART_UPSERT":
            name, inhalt = header.get("name"), header.get("inhalt")
            if darf and self.delta_lauf is not None and header.get("run") == self.delta_lauf \
                    and self.hat_inhalt(name, inhalt):
                self._zeige(name, inhalt)
                self.zaehler["PART_SAME"] += 1
                return part_same(header["run"], name, inhalt), b""
            if isinstance(name, str):
                if inhalt:
                    self._zeige(name, inhalt)
                else:
                    self.teile.pop(name, None)  # ohne Schlüssel: nichts, worauf PART_SAME sich beziehen könnte
            if delta:
                self.zaehler["PART_UPSERT"] += 1
            return (_ohne(header, "inhalt") if self.alt else header), payload
        if art == "PART_REMOVE":
            self.teile.pop(header.get("name"), None)
        elif art == "RUN_START":
            if delta:
                self.delta_lauf = header.get("run")
                return {**header, "delta": True}, payload
            self.delta_lauf = None
        elif art == "RUN_END":
            if self.alt:
                return _ohne(header, "teile"), payload
        elif art == "PROJECT":
            pfad = header.get("path")
            if pfad != self.projekt:
                if self.projekt is not None:
                    self.felder.clear()  # die App vergisst ihre Felder beim Projektwechsel ebenso
                self.projekt = pfad
        elif art == "STATICS_FIELD":
            paar = (str(header.get("szenario")), str(header.get("teil")))
            feld = header.get("feld")
            liste = self.felder.setdefault(paar, [])
            weg = darf and bool(feld) and feld in liste
            if feld in liste:
                liste.remove(feld)
            liste.append(feld)
            del liste[:-TEIL_INHALTE]  # wie die App: je Paar die letzten Felder
            if weg:
                self.zaehler["STATICS_FIELD weg"] += 1
                return None
        elif art == "ANIM_DEF":
            name = str(header.get("name"))
            pruef = _pruefsumme(header, payload, ohne=("seq", "run"))
            if darf and self.anim.get(name) == pruef:
                self.zaehler["ANIM_DEF weg"] += 1
                return None
            self.anim[name] = pruef
            self.kollisionen.pop(name, None)  # die App verwirft die Kollisionen eines neuen ANIM_DEF
        elif art == "ANIM_REMOVE":
            self.anim.pop(str(header.get("name")), None)
            self.kollisionen.pop(str(header.get("name")), None)
        elif art == "ANIM_COLLISIONS":
            name = str(header.get("name"))
            pruef = _pruefsumme(header, payload, ohne=("seq", "run", "reply_to"))
            if darf and not header.get("reply_to") and self.kollisionen.get(name) == pruef:
                self.zaehler["ANIM_COLLISIONS weg"] += 1
                return None
            self.kollisionen[name] = pruef
        elif art == "VERSION_BILD_REQ":
            return self._versionsbild(header, payload, darf)
        if art in WIE_ZUVOR_ARTEN and not header.get("reply_to"):
            return self._wie_zuvor(art, header, payload, seq, darf)
        return header, payload

    def _wie_zuvor(self, art: str, header: dict[str, Any], payload: bytes, seq: int, darf: bool
                   ) -> tuple[dict[str, Any], bytes]:
        if self.gemeldet and not self.delta:
            return header, payload  # ältere App: weder Basen noch Patches
        text = json.dumps({k: v for k, v in header.items() if k != "seq"}, ensure_ascii=False, separators=(",", ":"))
        neu = json.loads(text)
        basen = self.basen.setdefault(art, collections.deque(maxlen=WIE_ZUVOR_BASEN))
        out: tuple[dict[str, Any], bytes] = (header, payload)
        try:
            if darf and basen:
                out = self._patch(art, basen, neu, text, payload) or out
        finally:  # die Basis kommt immer dazu: die App legt jeden Rahmen dieser Art ebenso ab
            basen.append(_Basis(seq=seq, kopf=neu, text=text, nutzlast=payload))
        self.zaehler["WIE_ZUVOR" if out[0] is not header else "voll"] += 1
        return out

    def _patch(self, art: str, basen: collections.deque[_Basis], neu: dict[str, Any], text: str, payload: bytes
               ) -> tuple[dict[str, Any], bytes] | None:
        """Kleinster WIE_ZUVOR gegen eine der Basen, der die Probe besteht, sonst None."""
        grenze = len(text) * WIE_ZUVOR_ANTEIL
        bester = None
        for b in reversed(basen):  # die neueste zuerst
            if b.nutzlast != payload:
                continue
            patch = strukturpatch(b.kopf, neu, grenze)
            if patch is None:
                continue
            groesse = len(kanonisch(patch))
            if bester is None or groesse < bester[0]:
                bester = (groesse, b, patch)
                grenze = groesse
            if groesse < 256:
                break
        if bester is None:
            return None
        _, b, (setzen, weg) = bester
        # Probe: der Aufbau muss genau den neuen Kopf ergeben (auch 1 gegen 1.0 gegen true)
        if kanonisch(patch_anwenden(json.loads(b.text), setzen, weg, kopieren=False)) != kanonisch(neu):
            return None
        return wie_zuvor(art, b.seq, setzen, weg), b""

    def _versionsbild(self, header: dict[str, Any], payload: bytes, darf: bool) -> tuple[dict[str, Any], bytes]:
        koepfe = list(header.get("teile") or [])
        if not any("inhalt" in k for k in koepfe):
            return header, payload
        neue: list[dict[str, Any]] = []
        stuecke: list[bytes] = []
        offset = 0
        for k in koepfe:
            n = netz_bytes(k)
            stueck = payload[offset:offset + n]
            offset += n
            if darf and self.hat_inhalt(k.get("teil"), k.get("inhalt")):
                neue.append({**{kk: vv for kk, vv in k.items() if kk not in ("vert", "tri", "epts", "edge")},
                             "aus_szene": True})
                self.zaehler["Netze aus der Szene"] += 1
            else:
                neue.append(_ohne(k, "inhalt") if self.alt else k)
                stuecke.append(stueck)
        if offset != len(payload):  # passt nicht zusammen: so lassen, wie es ist (ohne die neuen Felder)
            return {**header, "teile": [_ohne(k, "inhalt") if self.alt else k for k in koepfe]}, payload
        return {**header, "teile": neue}, b"".join(stuecke)


def _ohne(header: dict[str, Any], feld: str) -> dict[str, Any]:
    if feld not in header:
        return header
    return {k: v for k, v in header.items() if k != feld}


def _pruefsumme(header: dict[str, Any], payload: bytes, ohne: tuple[str, ...]) -> str:
    h = hashlib.sha1(kanonisch({k: v for k, v in header.items() if k not in ohne}).encode("utf-8"))
    h.update(payload)
    return h.hexdigest()


# =====================================================================================================================
# Agentenspur
# =====================================================================================================================


class Agentenspur:
    """Die letzten ``SPUR_LAENGE`` Schritte des Agenten, threadsicher. Ein Schritt entsteht mit dem ersten Ereignis,
    das ``werkzeug`` nennt; spätere Ereignisse mit derselben ``id`` ergänzen ihn."""

    def __init__(self, laenge: int = SPUR_LAENGE) -> None:
        self.laenge = laenge
        self._lock = threading.Lock()
        self._schritte: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()

    def aktualisieren(self, ereignis: dict[str, Any]) -> dict[str, Any] | None:
        """Ereignis einarbeiten; zurück kommt der ganze neue Stand des Schritts (Kopie) oder None (verworfen)."""
        sid = ereignis.get("id")
        if not isinstance(sid, str) or not sid:
            return None
        with self._lock:
            s = self._schritte.get(sid)
            if s is None:
                if not ereignis.get("werkzeug"):
                    return None  # Ergänzung zu einem Schritt, den es nicht (mehr) gibt
                s = {"id": sid, "werkzeug": str(ereignis["werkzeug"]), "text": None, "absicht": None,
                     "sitzung": None, "beginn": time.time(), "ende": None, "dauer_ms": None, "stand": "laeuft",
                     "fehler": None}
                self._schritte[sid] = s
                while len(self._schritte) > self.laenge:
                    self._schritte.popitem(last=False)
            for k, v in ereignis.items():
                if k in ("id", "werkzeug"):
                    continue
                if k == "text":
                    if v and not s.get("text"):  # die erste Beschreibung bleibt
                        s["text"] = _kuerzen(v)
                elif k in ("absicht", "fehler"):
                    s[k] = _kuerzen(v)
                elif k == "sitzung":
                    s[k] = str(v)[:128] if v else None
                elif k == "phasen":
                    if isinstance(v, dict):
                        s["phasen"] = {**(s.get("phasen") or {}), **v}
                elif k == "stand":
                    if v in ("laeuft", "ok", "fehler"):
                        s["stand"] = v
                elif k in ("beginn", "ende", "dauer_ms"):
                    s[k] = round(float(v), 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
                elif k in SPUR_FELDER:
                    s[k] = v
            if s["stand"] == "fehler" and not s.get("fehler"):
                s["fehler"] = "Fehler ohne Meldung"
            if s["stand"] != "laeuft":
                if s.get("ende") is None:
                    s["ende"] = round(time.time(), 3)
                if s.get("dauer_ms") is None:
                    s["dauer_ms"] = round(max(0.0, (s["ende"] - s["beginn"]) * 1000), 1)
            return json.loads(json.dumps(s))

    def liste(self) -> list[dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(list(self._schritte.values())))


# =====================================================================================================================
# Laufzeit
# =====================================================================================================================


def _de_zahl(x: float) -> str:
    text = f"{float(x):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if text not in ("-0", "") else "0"


def _einheit(name: str) -> str:
    n = name.lower()
    if any(w in n for w in ("winkel", "grad", "deg", "neigung")):
        return "°"
    if any(w in n for w in ("anzahl", "zahl", "stueck", "stück")) or n.startswith("n_") or n.endswith("_n"):
        return ""
    return " mm"


class LiveRuntime:
    """V2-5 als Teil von ``KernelRuntime`` (siehe Moduldoku). Erwartet von der Laufzeit ``_link``, ``_lock``,
    ``_app_lock``, ``_send_app``, ``_request``, ``_send_view_nowait``, ``_annotations``, ``scene``, ``_selection``,
    ``_project``, ``_run_no``, ``_log``."""

    def _live_init(self) -> None:
        self._live_spur = Agentenspur()
        self._live_lage: dict[str, Any] | None = None  # letztes LAGE der App (auch verspätet)
        self._live_lage_t = 0.0
        self._live_params: dict[str, dict[str, Any]] = {}  # Projektpfad → param()-Werte des letzten guten Laufs

    # -- Verbindung ----------------------------------------------------------------------------------------------------

    def _live_conn(self) -> Any:
        return self._link.connection  # type: ignore[attr-defined]

    def _live_hat(self, faehigkeit: str) -> bool:
        conn = self._live_conn()
        live = getattr(conn, "live", None)
        return bool(conn is not None and not conn.closed and live is not None and live.hat(faehigkeit))

    def _live_hello_app(self, conn: Any, header: dict[str, Any]) -> None:
        """HELLO_APP: Fähigkeiten der App an die Verbindung; mit spur-1 die ganze Agentenspur."""
        faehig = header.get("faehigkeiten")
        conn.set_faehigkeiten(faehig if isinstance(faehig, list) else [])
        if faehig:
            gemeinsam = [f for f in KERNEL_FAEHIGKEITEN if f in faehig]
            self._log(f"[kernel] V2-5: App kann {', '.join(gemeinsam) or 'nichts davon'}")  # type: ignore[attr-defined]
        if conn.live.hat(FAEHIGKEIT_SPUR):
            with self._app_lock:  # type: ignore[attr-defined]
                conn.send({"type": "AGENT_SPUR", "schritte": self._live_spur.liste()})

    def _live_app_message(self, conn: Any, kind: str | None, header: dict[str, Any]) -> bool:
        """PARTS_REQ, NOCHMAL (App → Kernel); LAGE geht über die Antworten (``_request``). True = erledigt."""
        if kind == "PARTS_REQ":
            self._live_parts_req(conn, header.get("teile"))
            return True
        if kind == "NOCHMAL":
            with self._app_lock:  # type: ignore[attr-defined]
                letzte = conn.live_neueste(str(header.get("art")))
                if letzte is not None:
                    conn.send(letzte[0], letzte[1], vollstaendig=True)
            return True
        return False

    def _live_parts_req(self, conn: Any, namen: Any) -> None:
        with self._app_lock:  # type: ignore[attr-defined]
            recs = self.scene.records()  # type: ignore[attr-defined]
            if namen is None:
                wahl, fehlen = recs, []
            else:
                bekannt = {r.name: r for r in recs}
                namen = [str(n) for n in namen if isinstance(n, str)]
                wahl = [bekannt[n] for n in namen if n in bekannt]
                fehlen = [n for n in namen if n not in bekannt]
            conn.live_vergessen([r.name for r in wahl])
            for r in wahl:
                conn.send(r.header, r.payload)
            for n in fehlen:
                conn.send({"type": "PART_REMOVE", "run": self._run_no, "name": n})  # type: ignore[attr-defined]

    def _live_lage_merken(self, header: dict[str, Any]) -> None:
        lage = {k: v for k, v in header.items() if k not in ("type", "seq", "reply_to")}
        with self._lock:  # type: ignore[attr-defined]
            self._live_lage = lage
            self._live_lage_t = time.time()

    # -- Teile im Lauf ---------------------------------------------------------------------------------------------------

    def _live_inhalt(self, key: str, header: dict[str, Any], payload: bytes) -> str:
        return inhalt_schluessel(key, header, payload)

    def _live_lauf_beginn(self, job: Any) -> None:
        """Vor RUN_START: Reihenfolge des vorigen Laufs (für IN_ARBEIT) und Buchführung des neuen."""
        job.live = {"vorher": [r.name for r in self.scene.records()],  # type: ignore[attr-defined]
                    "gekommen": set(), "letzt": time.perf_counter(), "nach": None, "geaendert": [],
                    "in_arbeit": None, "in_arbeit_t": 0.0}

    def _live_teil(self, job: Any, name: str, alt: str | None, neu: str) -> None:
        """Ein Teil des Laufs ist da (vor dem Senden)."""
        st = getattr(job, "live", None)
        if not st:
            return
        st["gekommen"].add(name)
        st["letzt"] = time.perf_counter()
        st["nach"] = name
        if alt != neu and name not in st["geaendert"]:
            st["geaendert"].append(name)

    def _live_warten(self, job: Any) -> bool:
        """Wie ``job.finished.wait(job.timeout_s)``, dazwischen alle 0,1 s IN_ARBEIT prüfen."""
        ende = time.monotonic() + job.timeout_s
        while True:
            rest = ende - time.monotonic()
            if rest <= 0:
                return job.finished.is_set()
            if job.finished.wait(min(rest, 0.1)):
                return True
            try:
                self._live_in_arbeit(job)
            except Exception as exc:  # noqa: BLE001 - nur Anzeige
                self._log(f"[kernel] IN_ARBEIT: {exc!r}")  # type: ignore[attr-defined]

    def _live_in_arbeit(self, job: Any) -> None:
        st = getattr(job, "live", None)
        if not st or not self._live_hat(FAEHIGKEIT_IN_ARBEIT):
            return
        jetzt = time.perf_counter()
        if jetzt - st["letzt"] < IN_ARBEIT_NACH_S or jetzt - st["in_arbeit_t"] < IN_ARBEIT_NACH_S:
            return
        gekommen = st["gekommen"]
        teil = next((n for n in st["vorher"] if n not in gekommen), None)
        if teil is None or teil == st["in_arbeit"]:
            return
        st["in_arbeit"], st["in_arbeit_t"] = teil, jetzt
        self._send_app({"type": "IN_ARBEIT", "run": job.run, "teil": teil, "nach": st["nach"],  # type: ignore
                        "ms": round((jetzt - job.started) * 1000, 1)})

    def _live_lauf_ende(self, job: Any) -> None:
        """Nach RUN_END: was die Weiche der aktuellen App gespart hat, ins Protokoll (nur mit delta-1)."""
        conn = self._live_conn()
        live = getattr(conn, "live", None)
        if live is None or not live.delta:
            return
        z = live.zaehler
        teile = ", ".join(f"{k} {z[k]}" for k in _ZAEHLER if z.get(k))
        self._log(f"[kernel] V2-5 bis Lauf {job.run}: {teile or 'nichts ersetzt'}")  # type: ignore[attr-defined]

    # -- Live-Maße -------------------------------------------------------------------------------------------------------

    def _live_masse_nach_lauf(self, job: Any, params: dict[str, Any]) -> None:
        """Nach einem guten Lauf: geänderte param()-Werte kurz an den geänderten Teilen zeigen (live-masse-1)."""
        proj = self._project  # type: ignore[attr-defined]
        if proj is None:
            return
        schluessel = str(proj.path)
        with self._lock:  # type: ignore[attr-defined]
            vorher = self._live_params.get(schluessel)
            self._live_params[schluessel] = dict(params or {})
        if not vorher or not self._live_hat(FAEHIGKEIT_LIVE_MASSE):
            return
        geaendert = {k: (vorher[k], v) for k, v in (params or {}).items()
                     if k in vorher and _zahlwert(v) and _zahlwert(vorher[k]) and vorher[k] != v}
        if not geaendert:
            return
        st = getattr(job, "live", None) or {}
        recs = {r.name: r for r in self.scene.records()}  # type: ignore[attr-defined]
        teile = [n for n in st.get("geaendert") or [] if n in recs and not n.startswith("Skizze/")
                 and not recs[n].header.get("kulisse")]
        if not teile:
            return
        staemme = {t for k in geaendert for t in re.split(r"[_\W]+", k.lower()) if len(t) >= 4}
        passend = [n for n in teile if any(s in n.lower() for s in staemme)]
        ziel = (passend or teile)[:PARAM_TEILE_MAX]
        mins = [recs[n].bbox.get("min") for n in ziel]
        maxs = [recs[n].bbox.get("max") for n in ziel]
        if not all(mins) or not all(maxs):
            return
        lo = [min(m[i] for m in mins) for i in range(3)]
        hi = [max(m[i] for m in maxs) for i in range(3)]
        hoehe = max(hi[i] - lo[i] for i in range(3)) * 0.06
        punkt = [round((lo[0] + hi[0]) / 2, 3), round((lo[1] + hi[1]) / 2, 3), round(hi[2] + hoehe, 3)]
        text = " · ".join(f"{k} {_de_zahl(a)} → {_de_zahl(b)}{_einheit(k)}" for k, (a, b) in geaendert.items())
        aid = f"p-{next(self._annotations)}"  # type: ignore[attr-defined]
        self._send_view_nowait("annotate", {"kind": "label", "points": [punkt], "text": text,  # type: ignore
                                            "id": aid, "art": "param", "dauer_s": PARAM_ANZEIGE_S})
        self._send_view_nowait("highlight", {"refs": ziel, "color": None, "label": None, "clear": False,  # type: ignore
                                             "id": aid, "dauer_s": PARAM_ANZEIGE_S})

    def _live_view_vorher(self, cmd: str, args: dict[str, Any]) -> dict[str, Any]:
        """view_command: ``annotate`` mit ``dauer_s`` braucht eine id (zum Entfernen bei älteren Apps)."""
        if cmd == "annotate" and args.get("dauer_s") and not args.get("id"):
            args = {**args, "id": f"a-{next(self._annotations)}"}  # type: ignore[attr-defined]
        return args

    def _live_view_nachher(self, cmd: str, args: dict[str, Any], ok: bool) -> None:
        """Ältere Apps kennen ``dauer_s`` nicht: der Kernel entfernt das Maß selbst wieder."""
        dauer = args.get("dauer_s")
        if not ok or cmd != "annotate" or not isinstance(dauer, (int, float)) or dauer <= 0 \
                or self._live_hat(FAEHIGKEIT_LIVE_MASSE):
            return
        t = threading.Timer(float(dauer), self._send_view_nowait, args=("clear_annotations",  # type: ignore
                                                                        {"ids": [args.get("id")]}))
        t.daemon = True
        t.start()

    # -- Agentenspur (KernelService) --------------------------------------------------------------------------------------

    def agent_schritt(self, ereignis: dict[str, Any]) -> None:
        """Siehe KernelService.agent_schritt."""
        schritt = self._live_spur.aktualisieren(dict(ereignis or {}))
        if schritt is not None:
            self._send_app({"type": "AGENT_SCHRITT", "schritt": schritt})  # type: ignore[attr-defined]

    def agentenspur(self) -> list[dict[str, Any]]:
        """Siehe KernelService.agentenspur."""
        return self._live_spur.liste()

    def _live_phasen(self, result: dict[str, Any]) -> None:
        """run: Zeitpunkte des Laufs an den Schritt der laufenden MCP-Anfrage (falls es einen gibt)."""
        bezug = aktueller_schritt.get()
        if bezug is None or not result.get("run"):
            return
        z = result.get("zeiten_ms") or {}
        phasen: dict[str, Any] = {"run": result["run"]}
        for k in ("erstes_teil", "letztes_teil", "run_end", "pruefung", "zurueck"):
            if isinstance(z.get(k), (int, float)):
                phasen[k] = z[k]
        self.agent_schritt({"id": bezug.id, "phasen": phasen})

    # -- Lagebild (KernelService) ------------------------------------------------------------------------------------------

    def lagebild(self, warten_s: float = LAGE_WARTEN_S) -> dict[str, Any]:
        """Siehe KernelService.lagebild."""
        warten = min(max(0.0, float(warten_s)), 5.0)
        conn = self._live_conn()
        if conn is None or conn.closed:
            grund = "App nicht verbunden"
        elif not conn.live.hat(FAEHIGKEIT_LAGE):
            grund = "App liefert kein Lagebild (ältere Fassung ohne lage-1)"
        else:
            t0 = time.perf_counter()
            reply, _payload, fehler = self._request({"type": "LAGE_REQ"}, warten)  # type: ignore[attr-defined]
            if fehler is None and reply.get("type") == "LAGE":
                lage = {k: v for k, v in reply.items() if k not in ("type", "seq", "reply_to")}
                return {"ok": True, "quelle": "app", "antwort_ms": round((time.perf_counter() - t0) * 1000, 1),
                        **lage}
            grund = (f"keine Antwort der App in {warten * 1000:.0f} ms" if fehler and "Keine Antwort" in fehler
                     else (fehler or "unerwartete Antwort der App"))
        return self._live_lage_kernel(grund)

    def _live_lage_kernel(self, grund: str) -> dict[str, Any]:
        with self._lock:  # type: ignore[attr-defined]
            sel = dict(self._selection)  # type: ignore[attr-defined]
            letzte, t = self._live_lage, self._live_lage_t
        recs = self.scene.records()  # type: ignore[attr-defined]
        out: dict[str, Any] = {
            "ok": True, "quelle": "kernel", "grund": grund,
            "auswahl": {"run": sel.get("run"), "refs": list(sel.get("refs") or [])},
            "verborgen": [r.name for r in recs if not r.visible],
            "verborgen_quelle": "Befehle des Agenten",
            "teile": len(recs), "sichtbar": None, "maus": None, "kamera": None, "kamera_alter_s": None,
        }
        if letzte is not None and letzte.get("kamera"):
            out["kamera"] = letzte["kamera"]
            out["kamera_alter_s"] = round(time.time() - t, 1)
        return out


def _zahlwert(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

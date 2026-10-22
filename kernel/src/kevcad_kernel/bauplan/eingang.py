"""Eingangsdaten des Bauplans aus dem letzten Lauf: Teile mit ihrer Rolle, Verbindungen, Gewindepaare.

Quelle ist die Szene der Laufzeit (Kopf, Netz und BRep je Teil wie in PART_UPSERT), die Stückliste (BOM), der Bericht
der Bedingungen (CONSTRAINTS, ``verbinde`` und Gelenke) und das letzte Prüfergebnis (CHECK: Gewindeeingriffe,
erlaubte Überlappungen, Durchdringungen). Die Formen werden aus der BRep-Binärform neu gelesen (eigene Objekte, damit
der Bauplan im Hintergrund rechnen kann, ohne die Formen der Messungen zu teilen).

Rollen:

| Rolle | Bedeutung |
|---|---|
| ``stange`` | Lagerteil Stangenware (zuschneiden, bohren) |
| ``platte`` | Lagerteil Platte (zuschneiden, bohren) |
| ``druck`` | Druckteil (drucken, Einsätze einschmelzen) |
| ``vm`` | Verbindungsmittel: Schraube, Mutter, Scheibe, Gewindestift (aus dem Katalog oder am Namen erkannt) |
| ``einsatz`` | Gewindeeinsatz (wird beim Bearbeiten in sein Teil eingeschmolzen) |
| ``zukauf`` | Teil einer vorhandenen oder gekauften Einheit (Eigenteile einer Gruppe, die zusammenhängen; Kameras) |
| ``kauf`` | einzelnes vorhandenes oder gekauftes Teil ohne Lagerteil |
| ``ohne`` | gehört nicht zum Aufbau (Umgebung unter dem Boden, lose daneben, vom Agenten ausgenommen) |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kevcad_kernel.catalog import KLEINTEILE, STANGENWARE
from kevcad_kernel.optik import OPTIK_ARTEN
from kevcad_kernel.pruefung.koerper import Koerper

KONTAKT_TOL = 0.5  # mm: so nah gilt als Kontakt (Auflage, Spielpassung), wie die Prüfung
VM_WORTE = re.compile(r"(schraube|mutter|scheibe|gewindestift|stift|bolzen|niet|dübel|duebel|splint|"
                      r"sicherungsring|federring|gewindestange)", re.IGNORECASE)
EINSATZ_WORTE = re.compile(r"(gewindeeinsatz|einschmelz|heat.?set)", re.IGNORECASE)
LAGER_WORTE = re.compile(r"(kugellager|wälzlager|waelzlager|rillenkugel|nadellager|gleitlager|lagerbuchse|"
                         r"\blager\b)", re.IGNORECASE)
NENN = re.compile(r"[Mm](\d+(?:[.,]\d+)?)")


@dataclass
class BTeil:
    """Ein Teil, wie der Bauplan es sieht."""

    name: str
    rolle: str
    koerper: Koerper
    kopf: dict[str, Any]  # Kopf des PART_UPSERT (bbox, props, faces, stock, druckteil …)
    kanten: list[np.ndarray] = field(default_factory=list)  # Kantenzüge in Weltkoordinaten
    art: str | None = None  # Lagerteil-Art
    item: dict[str, Any] | None = None  # Katalogeintrag
    einheit: str | None = None  # Zukauf-Einheit (Name)
    wirt: str | None = None  # Einsatz oder eingeklebter Stift: Teil, in dem er sitzt
    geschaetzt: bool = False  # Rolle nur am Namen erkannt
    vm: dict[str, Any] = field(default_factory=dict)  # Verbindungsmittel: d, laenge, typ, norm, achse, kopf_richtung

    @property
    def stock(self) -> dict[str, Any] | None:
        return self.kopf.get("stock")

    @property
    def druck(self) -> dict[str, Any] | None:
        return self.kopf.get("druckteil")

    @property
    def masse_g(self) -> float:
        m = (self.kopf.get("props") or {}).get("mass")
        if m is not None:
            return float(m)
        return float((self.kopf.get("props") or {}).get("volume") or 0.0) * 1e-3  # 1 g/cm³ angenommen

    @property
    def masse_geschaetzt(self) -> bool:
        return (self.kopf.get("props") or {}).get("mass") is None

    @property
    def zentrum(self) -> np.ndarray:
        return np.asarray((self.kopf.get("props") or {}).get("center") or (self.bmin + self.bmax) / 2, dtype=float)

    @property
    def bmin(self) -> np.ndarray:
        return self.koerper.bmin

    @property
    def bmax(self) -> np.ndarray:
        return self.koerper.bmax

    @property
    def volumen(self) -> float:
        return float(self.koerper.volumen)

    @property
    def kurz(self) -> str:
        return self.name.rsplit("/", 1)[-1]

    @property
    def gruppe(self) -> str:
        return self.name.rsplit("/", 1)[0] if "/" in self.name else ""

    @property
    def material(self) -> str | None:
        if self.druck:
            return self.druck.get("material")
        if self.stock:
            return self.stock.get("material")
        return self.kopf.get("material")


@dataclass
class Verbindung:
    a: str
    b: str | None  # None: Boden
    art: str  # schraube, klemmung, steck, formschluss, kleben, aufliegen, drehgelenk, …, kontakt
    mit: list[str] = field(default_factory=list)
    quelle: str = "verbinde"  # verbinde | gelenk | bedingung | kontakt
    id: str | None = None
    text: str = ""

    @property
    def teile(self) -> list[str]:
        return [n for n in [self.a, self.b, *self.mit] if n]


@dataclass
class Eingang:
    titel: str
    run: int
    projekt: Path | None
    teile: dict[str, BTeil]
    bom: dict[str, Any]
    bedingungen: dict[str, Any] | None
    check: dict[str, Any] | None
    verbindungen: list[Verbindung]
    gewinde: list[tuple[str, str]]
    erlaubt: set[frozenset]
    durchdringend: set[frozenset]
    hat_verbinde: bool
    katalog: Any = None
    hinweise: list[str] = field(default_factory=list)
    ohne: dict[str, str] = field(default_factory=dict)  # Name → Grund
    _kontakte: dict[str, set[str]] = field(default_factory=dict)
    _kontakt_fertig: set[str] = field(default_factory=set)

    # -- Abfragen -------------------------------------------------------------------------------------------------

    def aufbau(self) -> list[BTeil]:
        """Teile des Aufbaus (ohne ``ohne``), in show()-Reihenfolge."""
        return [t for t in self.teile.values() if t.rolle != "ohne"]

    def boden_z(self) -> float:
        teile = self.aufbau()
        if not teile:
            return 0.0
        if any(abs(float(t.bmin[2])) <= KONTAKT_TOL for t in teile):
            return 0.0
        return float(min(t.bmin[2] for t in teile))

    def nachbarn(self, name: str, kontakt: bool | None = None) -> set[str]:
        """Teile, die mit ``name`` verbunden sind (verbinde, Gelenke, Bedingungen; Kontakt). ``kontakt`` None: geometrische
        Kontakte nur, wenn das Modell kein ``verbinde`` nutzt oder das Teil keine Angabe hat (geschätzt)."""
        out: set[str] = set()
        for v in self.verbindungen:
            t = v.teile
            if name in t:
                out.update(n for n in t if n != name)
        out.discard(name)
        if kontakt is None:
            kontakt = not self.hat_verbinde or not out
        if kontakt:
            out |= self.kontakte(name)
        out.discard(name)
        return out

    def kontakte(self, name: str) -> set[str]:
        """Geometrische Kontakte (Abstand bis 0,5 mm), bei Bedarf gerechnet und gemerkt."""
        if name not in self._kontakt_fertig:
            self._rechne_kontakte(name)
        return set(self._kontakte.get(name, set()))

    def _rechne_kontakte(self, name: str) -> None:
        t = self.teile.get(name)
        self._kontakt_fertig.add(name)
        if t is None:
            return
        lo, hi = t.bmin - KONTAKT_TOL, t.bmax + KONTAKT_TOL
        for n, u in self.teile.items():
            if n == name or u.rolle == "ohne":
                continue
            if np.any(u.bmin > hi) or np.any(u.bmax < lo):
                continue
            key = n
            if n in self._kontakt_fertig and name not in self._kontakte.get(n, set()):
                continue  # schon von der anderen Seite gerechnet: kein Kontakt
            if abstand(t.koerper.shape, u.koerper.shape, KONTAKT_TOL) <= KONTAKT_TOL:
                self._kontakte.setdefault(name, set()).add(key)
                self._kontakte.setdefault(key, set()).add(name)


def abstand(a: Any, b: Any, grenze: float) -> float:
    """Kleinster Abstand zweier Formen (OCCT); unendlich bei Fehler."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    try:
        ext = BRepExtrema_DistShapeShape(a, b)
        ext.SetDeflection(1e-3)
        ext.Perform()
        if ext.IsDone():
            return float(ext.Value())
    except Exception:  # noqa: BLE001
        pass
    return float("inf")


# ---------------------------------------------------------------------------------------------------------------------
# Aufbau


def _kanten(kopf: dict[str, Any], arrays: dict[str, np.ndarray]) -> list[np.ndarray]:
    pts = np.asarray(arrays.get("edge_points"), dtype=np.float64).reshape(-1, 3)
    offs = np.asarray(arrays.get("edge_offsets"), dtype=np.int64).reshape(-1)
    out = []
    for k in range(max(0, len(offs) - 1)):
        a, b = int(offs[k]), int(offs[k + 1])
        if b - a >= 2:
            out.append(pts[a:b])
    return out


def teil_aus_satz(name: str, kopf: dict[str, Any], payload: bytes, brep: bytes) -> tuple[Koerper, list[np.ndarray]]:
    """Körper (eigene Form aus der BRep-Binärform) und Kantenzüge aus einem Satz der Szene."""
    from kevcad_kernel.protocol import unpack_part
    from kevcad_kernel.tessellate import deserialize_shape

    arrays = unpack_part(kopf, payload)
    shape = deserialize_shape(brep).wrapped
    bbox = kopf.get("bbox") or {}
    props = kopf.get("props") or {}
    k = Koerper(name=name, key="", shape=shape,
                pos=np.asarray(arrays["positions"], dtype=np.float64).reshape(-1, 3),
                tri=np.asarray(arrays["triangles"], dtype=np.int64).reshape(-1, 3),
                bmin=np.asarray(bbox.get("min") or [0, 0, 0], dtype=np.float64),
                bmax=np.asarray(bbox.get("max") or [0, 0, 0], dtype=np.float64),
                volumen=float(props.get("volume") or 0.0),
                zentrum=np.asarray(props.get("center") or [0, 0, 0], dtype=np.float64),
                masse_g=props.get("mass"), info={}, flaechen=list(kopf.get("faces") or []))
    return k, _kanten(kopf, arrays)


def _rolle(name: str, kopf: dict[str, Any], katalog: Any,
           bom_art: str | None = None) -> tuple[str, str | None, dict | None, bool]:
    """(Rolle, Lagerteil-Art, Katalogeintrag, nur geschätzt). ``bom_art``: Art aus der Stücklistenzeile des Teils."""
    kurz = name.rsplit("/", 1)[-1]
    if kopf.get("druckteil"):
        return "druck", "druckteil", None, False
    zk = kopf.get("zukauf")
    if zk:  # Zukaufteil (Phase 3): gekauft und fertig; Normteile darunter (Flügelschraube DIN 316) sind Verbindungsmittel
        text = " ".join(str(zk.get(k) or "") for k in ("id", "mpn", "hersteller")) + " " + kurz
        if EINSATZ_WORTE.search(text):
            return "einsatz", "zukaufteil", None, False
        if VM_WORTE.search(kurz) or VM_WORTE.search(str(zk.get("mpn") or "")):
            return "vm", "zukaufteil", None, False
        return "kauf", "zukaufteil", None, False
    stock = kopf.get("stock")
    if stock:
        item = katalog.item(stock.get("id")) if katalog is not None and stock.get("id") else None
        art = (item or {}).get("art") or bom_art
        typ = str(((item or {}).get("masse") or {}).get("typ") or "")
        if art is None:  # Katalog fehlt: am Namen erkennen
            if EINSATZ_WORTE.search(kurz):
                return "einsatz", "mutter", item, True
            if VM_WORTE.search(kurz):
                return "vm", None, item, True
            return "stange", None, item, True
        if art in STANGENWARE:
            return "stange", art, item, False
        if art == "platte":
            return "platte", art, item, False
        if art in KLEINTEILE:
            if typ == "HeatSetNut" or EINSATZ_WORTE.search(kurz) or EINSATZ_WORTE.search(str(item.get("name"))):
                return "einsatz", art, item, False
            return "vm", art, item, False
        if art in OPTIK_ARTEN:
            return "kauf", art, item, False
        return "kauf", art, item, False
    if EINSATZ_WORTE.search(kurz):
        return "einsatz", None, None, True
    if VM_WORTE.search(kurz):
        return "vm", None, None, True
    return "eigen", None, None, False


def _vm_angaben(t: BTeil) -> dict[str, Any]:
    """Nenndurchmesser, Länge, Typ, Norm, Achse und Kopfseite eines Verbindungsmittels."""
    out: dict[str, Any] = {}
    masse = ((t.item or {}).get("masse") or {})
    out["typ"] = masse.get("typ")
    out["norm"] = masse.get("norm")
    groesse = str(masse.get("groesse") or "")
    m = NENN.search(groesse) or NENN.search(t.kurz)
    if m:
        out["d"] = float(m.group(1).replace(",", "."))
    if t.stock and t.stock.get("laenge"):
        out["laenge"] = float(t.stock["laenge"])
    else:
        ml = re.search(r"[Mm]\d+(?:[.,]\d+)?\s*[x×]\s*(\d+(?:[.,]\d+)?)", t.kurz)
        if ml:
            out["laenge"] = float(ml.group(1).replace(",", "."))
    if not out.get("typ"):
        k = t.kurz.lower()
        out["typ"] = ("WingScrew" if ("flügel" in k or "fluegel" in k) and "schraube" in k else
                      "WingNut" if "flügel" in k or "fluegel" in k else
                      "SetScrew" if "stift" in k or "gewindestange" in k else
                      "CounterSunkScrew" if "senk" in k else
                      "PlainWasher" if "scheibe" in k else
                      "HexNut" if "mutter" in k else "Screw")
    achse = vm_achse(t.koerper)
    if achse is not None:
        a, mitte, kopf = achse
        out["achse"] = [round(float(c), 6) for c in a]
        out["mitte"] = [round(float(c), 4) for c in mitte]
        if kopf is not None:
            out["kopf"] = [round(float(c), 6) for c in kopf]
    return out


def vm_achse(k: Koerper) -> tuple[np.ndarray, np.ndarray, np.ndarray | None] | None:
    """Achse (Einheitsvektor), Mitte und Kopfrichtung (vom Schaft zum Kopf) aus den Zylinderflächen und dem Netz."""
    achsen = k.zylinder_achsen(limit=1)
    if not achsen:
        ext = k.bmax - k.bmin
        i = int(np.argmax(ext)) if ext.max() > 1.5 * np.median(ext) else 2
        a = np.zeros(3)
        a[i] = 1.0
    else:
        a = achsen[0]
    pos = k.pos
    if not len(pos):
        return None
    mitte = (k.bmin + k.bmax) / 2
    # Mitte auf der Achse: Mittelpunkt der Zylinderfläche, sonst Hüllquadermitte
    zyl = [f for f in k.flaechen if f.get("t") == "cylinder" and f.get("ax") and f.get("c")]
    if zyl:
        zyl.sort(key=lambda f: -float(f.get("a") or 0.0))
        c = np.asarray(zyl[0]["c"], dtype=float)
        mitte = c + a * float(np.dot(mitte - c, a))
    t = (pos - mitte) @ a
    r = np.linalg.norm((pos - mitte) - np.outer(t, a), axis=1)
    lo, hi = float(t.min()), float(t.max())
    lang = hi - lo
    if lang < 1e-6:
        return a, mitte, None
    s = 0.15 * lang
    r_lo = float(r[t <= lo + s].max(initial=0.0))
    r_hi = float(r[t >= hi - s].max(initial=0.0))
    if abs(r_hi - r_lo) < 0.15 * max(r_hi, r_lo, 1e-6):
        return a, mitte, None
    return a, mitte, (a if r_hi > r_lo else -a)


def verbindungen_aus(bericht: dict[str, Any] | None) -> tuple[list[Verbindung], bool]:
    """Verbindungen aus dem Bericht der Bedingungen; zweiter Wert: das Modell nutzt ``verbinde``."""
    out: list[Verbindung] = []
    hat = False
    for it in (bericht or {}).get("items") or []:
        teile = list(it.get("teile") or [])
        if not teile:
            continue
        art = it.get("art")
        if art == "verbinde":
            hat = True
            if "gegen" in it or "mit" in it:  # additive Felder (befestigung.py)
                b = it.get("gegen")
                mit = list(it.get("mit") or [])
            else:
                text = str(it.get("text") or "")
                if len(teile) > 1 and f" an {teile[1]}" in text:
                    b, mit = teile[1], teile[2:]
                else:
                    b, mit = None, teile[1:]
            out.append(Verbindung(teile[0], b, str(it.get("verbindung") or "aufliegen"), mit, "verbinde",
                                  it.get("id"), str(it.get("text") or "")))
        elif it.get("gruppe") == "gelenk" and len(teile) >= 2:
            out.append(Verbindung(teile[0], teile[1], str(art), [], "gelenk", it.get("id"), str(it.get("text") or "")))
        elif it.get("gruppe") == "montage" and len(teile) >= 2:
            out.append(Verbindung(teile[0], teile[1], str(art), [], "bedingung", it.get("id"),
                                  str(it.get("text") or "")))
    return out, hat


FLUECHTIG = frozenset({"run", "seq", "since_run", "duration_ms", "ms", "aus_zwischenspeicher", "zwischenspeicher",
                       "neu_geprueft", "erzeugt"})


def stabil(o: Any) -> Any:
    """Für den Schlüssel der Eingaben: ohne Laufnummern, Zeiten (``…_ms``) und Angaben zum Zwischenspeicher, Zahlen
    gerundet (dieselben Eingaben ergeben in jedem Lauf denselben Schlüssel)."""
    if isinstance(o, dict):
        return {str(k): stabil(v) for k, v in o.items() if k not in FLUECHTIG and not str(k).endswith("_ms")}
    if isinstance(o, (list, tuple)):
        return [stabil(v) for v in o]
    if isinstance(o, np.ndarray):
        return stabil(o.tolist())
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (float, np.floating)):
        return round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def pruef_eingang(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """Was der Bauplan aus dem Prüfstand liest (``sammle``, ``geruest``): Gewindeeingriffe, erlaubte Überlappungen,
    Durchdringungen und Verformungen, Druckbefunde und die Druckprüfung je Teil. Andere Befunde (etwa der Bewegungsraum,
    der nur nach einer Änderung neu geprüft wird) bestimmen den Plan nicht. Wer im Bauplan weitere Teile des Prüfstands
    liest, nimmt sie hier auf."""
    if not check:
        return None
    befunde = [b for b in check.get("befunde") or [] if b.get("art") in ("durchdringung", "verformt")
               or str(b.get("art", "")).startswith("druck_")]
    druck = check.get("druck") or {}
    return {"state": check.get("state"), "gewinde": check.get("gewinde"), "erlaubt": check.get("erlaubt"),
            "befunde": befunde, "druck": {"teile": druck.get("teile"), "materialien": druck.get("materialien")}}


def schluessel(records: list[Any], *, bom: dict[str, Any] | None, bedingungen: dict[str, Any] | None,
               check: dict[str, Any] | None, katalog: Any, titel: str, projekt: Path | None) -> str:
    """Schlüssel über alles, was ``sammle`` liest und den Plan bestimmt: Formschlüssel (Form und Lage) und Kopf jedes
    Teils, Stückliste, Bedingungen, Prüfstand, die Katalogeinträge der Lagerteile, Titel und Projekt. Die Datei
    (gespeicherte Bearbeitungen, ``umfang``) prüft der Dienst getrennt. Kostet Millisekunden statt Sekunden."""
    import hashlib
    import json

    teile = []
    ids: set[str] = set()
    for rec in records:
        kopf = rec.header or {}
        teile.append([rec.name, getattr(rec, "key", ""), stabil(kopf)])
        st = kopf.get("stock") or {}
        if st.get("id"):
            ids.add(str(st["id"]))
    kat: dict[str, Any] = {}
    for i in sorted(ids):
        try:
            kat[i] = stabil(katalog.item(i)) if katalog is not None else None
        except Exception:  # noqa: BLE001 - unbekannter Eintrag: gilt als „fehlt“
            kat[i] = None
    daten = {"teile": teile, "bom": stabil(bom or {}), "bedingungen": stabil(bedingungen),
             "check": stabil(pruef_eingang(check)),
             "katalog": kat, "titel": titel, "projekt": str(projekt)}
    return hashlib.sha1(json.dumps(daten, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def sammle(records: list[Any], *, bom: dict[str, Any] | None, bedingungen: dict[str, Any] | None,
           check: dict[str, Any] | None, katalog: Any, titel: str, run: int, projekt: Path | None,
           umfang: dict[str, Any] | None = None) -> Eingang:
    """Eingang aus den Sätzen der Szene (``refs.PartRecord``) und den Berichten des Laufs."""
    teile: dict[str, BTeil] = {}
    bom_art = {t: str(line.get("art")) for line in (bom or {}).get("lines") or [] for t in line.get("teile") or []}
    for rec in records:
        kopf = dict(rec.header)
        kopf["_key"] = getattr(rec, "key", "")
        try:
            k, kanten = teil_aus_satz(rec.name, kopf, rec.payload, rec.brep)
        except Exception:  # noqa: BLE001 - ein kaputtes Teil darf den Bauplan nicht verhindern
            continue
        if k.volumen <= 1e-6 or not len(k.tri):
            continue  # Skizzen, Flächen, Kanten
        rolle, art, item, geschaetzt = _rolle(rec.name, kopf, katalog, bom_art.get(rec.name))
        teile[rec.name] = BTeil(rec.name, rolle, k, kopf, kanten, art, item, geschaetzt=geschaetzt)
    verbindungen, hat_verbinde = verbindungen_aus(bedingungen)
    gewinde = [(str(g["teile"][0]), str(g["teile"][1])) for g in (check or {}).get("gewinde") or []
               if len(g.get("teile") or []) >= 2]
    erlaubt = {frozenset(e["teile"][:2]) for e in (check or {}).get("erlaubt") or [] if len(e.get("teile") or []) >= 2}
    durch = {frozenset(b["teile"][:2]) for b in (check or {}).get("befunde") or []
             if b.get("art") in ("durchdringung", "verformt") and len(b.get("teile") or []) >= 2}
    ein = Eingang(titel=titel, run=run, projekt=projekt, teile=teile, bom=dict(bom or {}), bedingungen=bedingungen,
                  check=check, verbindungen=verbindungen, gewinde=gewinde, erlaubt=erlaubt, durchdringend=durch,
                  hat_verbinde=hat_verbinde, katalog=katalog)
    for t in teile.values():
        if t.rolle in ("vm", "einsatz"):
            t.vm = _vm_angaben(t)
    _umfang(ein, umfang or {})
    _einheiten(ein)
    _wirte(ein)
    return ein


def _passt(name: str, muster: list[str]) -> bool:
    return any(name == m.rstrip("/") or name.startswith(m.rstrip("/") + "/") for m in muster)


def _umfang(ein: Eingang, umfang: dict[str, Any]) -> None:
    """Was nicht zum Aufbau gehört: vom Agenten oder Kevin ausgenommen, Umgebung unter dem Boden, lose daneben."""
    ohne = list(umfang.get("ohne") or [])
    mit = list(umfang.get("mit") or [])
    for t in ein.teile.values():
        if _passt(t.name, ohne):
            t.rolle = "ohne"
            ein.ohne[t.name] = "im Bauplan ausgenommen"
        elif float(t.bmax[2]) <= 1e-3 and not _passt(t.name, mit):
            t.rolle = "ohne"
            ein.ohne[t.name] = "Umgebung (liegt unter dem Boden)"
    # Zusammenhang: Teile, die mit dem größten Teil des Aufbaus nicht verbunden sind, liegen lose daneben
    aufbau = [t.name for t in ein.aufbau()]
    if len(aufbau) < 2:
        return
    kanten: dict[str, set[str]] = {n: set() for n in aufbau}
    for v in ein.verbindungen:
        tt = [n for n in v.teile if n in kanten]
        for a in tt:
            kanten[a].update(b for b in tt if b != a)
    if not ein.hat_verbinde:  # ohne verbinde: Kontakte entscheiden (geschätzt)
        for n in aufbau:
            kanten[n] |= {m for m in ein.kontakte(n) if m in kanten}
    else:  # mit verbinde: Teile ohne jede Angabe über Kontakte anhängen (auch „auf boden“ ist eine Angabe)
        angegeben = {n for v in ein.verbindungen if v.quelle == "verbinde" for n in v.teile}
        for n in aufbau:
            if not kanten[n] and n not in angegeben:
                kanten[n] |= {m for m in ein.kontakte(n) if m in kanten}
                for m in kanten[n]:
                    kanten[m].add(n)
    gruppen: list[set[str]] = []
    gesehen: set[str] = set()
    for n in aufbau:
        if n in gesehen:
            continue
        g, stapel = set(), [n]
        while stapel:
            x = stapel.pop()
            if x in g:
                continue
            g.add(x)
            stapel.extend(kanten[x] - g)
        gesehen |= g
        gruppen.append(g)
    if len(gruppen) < 2:
        return
    gruppen.sort(key=lambda g: (-len(g), -sum(ein.teile[n].masse_g for n in g)))
    for g in gruppen[1:]:
        if any(_passt(n, mit) for n in g):
            continue
        for n in g:
            ein.teile[n].rolle = "ohne"
            ein.ohne[n] = "nicht mit dem Aufbau verbunden (liegt lose daneben)"


def _oberste(name: str) -> str:
    return name.split("/", 1)[0]


def _einheiten(ein: Eingang) -> None:
    """Vorhandene oder gekaufte Einheiten: zusammenhängende Eigenteile (und Kameras) derselben obersten Gruppe; am
    Namen erkannte Verbindungsmittel ohne Lagerteil, die nur Teile der Einheit berühren, gehören dazu."""
    kandidaten = [t for t in ein.teile.values() if t.rolle in ("eigen", "kauf") and not t.kopf.get("zukauf")]
    nach_id: dict[tuple, list[str]] = {}
    for t in ein.teile.values():
        if t.rolle == "kauf" and t.kopf.get("zukauf"):
            nach_id.setdefault((str(t.kopf["zukauf"].get("id")), _oberste(t.name)), []).append(t.name)
    for (_, _), namen_z in nach_id.items():  # mehrere Körper eines Zukaufteils, die zusammenhängen
        rest = set(namen_z)
        while rest:
            g, stapel = set(), [rest.pop()]
            while stapel:
                x = stapel.pop()
                g.add(x)
                for m in ein.kontakte(x) & rest:
                    rest.discard(m)
                    stapel.append(m)
            if len(g) > 1:
                name = _gemeinsam(sorted(g))
                for n in g:
                    ein.teile[n].rolle = "zukauf"
                    ein.teile[n].einheit = name
    namen = {t.name for t in kandidaten}
    kanten: dict[str, set[str]] = {n: set() for n in namen}
    for v in ein.verbindungen:
        tt = [n for n in v.teile if n in namen]
        for a in tt:
            kanten[a].update(b for b in tt if b != a and _oberste(b) == _oberste(a))
    for n in namen:
        if not ein.hat_verbinde or not kanten[n]:
            kanten[n] |= {m for m in ein.kontakte(n) if m in namen and _oberste(m) == _oberste(n)}
    gesehen: set[str] = set()
    for t in kandidaten:
        if t.name in gesehen:
            continue
        g, stapel = set(), [t.name]
        while stapel:
            x = stapel.pop()
            if x in g:
                continue
            g.add(x)
            stapel.extend(kanten[x] - g)
        gesehen |= g
        if len(g) < 2:
            ein.teile[t.name].rolle = "kauf"
            continue
        name = _gemeinsam(sorted(g))
        for n in g:
            ein.teile[n].rolle = "zukauf"
            ein.teile[n].einheit = name
    # Verbindungsmittel ohne Lagerteil, die nur eine Einheit berühren, gehören zu ihr (Achsschraube der Lenkrolle)
    for t in ein.teile.values():
        if t.rolle != "vm" or t.stock is not None:
            continue
        nb = {m for m in ein.nachbarn(t.name) if ein.teile.get(m) and ein.teile[m].rolle != "ohne"}
        einheiten = {ein.teile[m].einheit for m in nb if ein.teile[m].rolle == "zukauf"}
        fremd = [m for m in nb if ein.teile[m].rolle != "zukauf" and ein.teile[m].rolle != "vm"]
        if len(einheiten) == 1 and not fremd and nb and all(ein.teile[m].rolle in ("zukauf", "vm") and
                                                          (ein.teile[m].rolle == "zukauf" or ein.teile[m].stock is None)
                                                          for m in nb):
            t.rolle = "zukauf"
            t.einheit = next(iter(einheiten))


def _gemeinsam(namen: list[str]) -> str:
    """Gemeinsamer Namensanfang (ganze Abschnitte) oder der erste Name."""
    teile = [n.split("/") for n in namen]
    out = []
    for stuecke in zip(*teile):
        if len(set(stuecke)) == 1:
            out.append(stuecke[0])
        else:
            break
    return "/".join(out) if out else namen[0]


def _wirte(ein: Eingang) -> None:
    """Einsätze sitzen in ihrem Teil (eingeschmolzen); eingeklebte Gewindestifte in ihrem Einsatz bzw. Teil."""
    def wirt_fuer(name: str, arten: tuple[str, ...]) -> str | None:
        kand: list[str] = []
        for v in ein.verbindungen:
            if v.quelle != "verbinde" or name not in (v.a, v.b):
                continue
            ander = v.b if v.a == name else v.a
            if ander and ein.teile.get(ander) and ein.teile[ander].rolle in arten:
                kand.append(ander)
        if not kand:
            kand = [m for m in ein.kontakte(name) if ein.teile.get(m) and ein.teile[m].rolle in arten]
        if not kand:
            return None
        kand.sort(key=lambda m: (ein.teile[m].rolle != "druck", -ein.teile[m].volumen))
        return kand[0]

    for t in ein.teile.values():
        if t.rolle == "einsatz":
            t.wirt = wirt_fuer(t.name, ("druck", "stange", "platte", "kauf", "zukauf", "eigen"))
    # Wälzlager und Lagerbuchsen werden in ihr Teil eingepresst (Formschluss oder Kontakt, liegt in dessen Hülle)
    for t in ein.teile.values():
        if t.rolle != "kauf" or not LAGER_WORTE.search(t.kurz):
            continue
        w = wirt_fuer(t.name, ("druck", "stange", "platte", "eigen"))
        if w is None:
            continue
        u = ein.teile[w]
        if np.all(t.bmin >= u.bmin - 1.0) and np.all(t.bmax <= u.bmax + 1.0):
            t.rolle = "einsatz"
            t.wirt = w
            t.vm = {"typ": "Bearing"}
    # Gewindestift oder Schraube, mit „kleben“ an einen Einsatz (oder ein Teil) verbunden: eingeklebt
    for v in ein.verbindungen:
        if v.quelle != "verbinde" or v.art != "kleben" or v.b is None:
            continue
        a, b = ein.teile.get(v.a), ein.teile.get(v.b)
        if a is None or b is None:
            continue
        for stift, ziel in ((a, b), (b, a)):
            if stift.rolle == "vm" and str(stift.vm.get("typ")) in ("SetScrew", "Screw", "SocketHeadCapScrew") \
                    and ziel.rolle in ("einsatz", "druck", "stange", "platte"):
                stift.wirt = ziel.name
                break


def montage_wirt(ein: Eingang, name: str) -> str:
    """Teil, mit dem ``name`` in der Montage als Einheit wandert (Einsatz → Teil, Stift → Einsatz → Teil)."""
    seen = set()
    while True:
        t = ein.teile.get(name)
        if t is None or not t.wirt or name in seen:
            return name
        seen.add(name)
        name = t.wirt

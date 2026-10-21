"""Stückliste und Zuschnitt (PLAN-PHASE2 P5/P6, PROTOCOL.md Abschnitt „Phase 2“).

Ablauf im Rechenprozess:

1. Jedes ``lager.teil(...).verbauen(...)`` meldet ein ``Piece`` beim ``LagerRegister`` des Laufs an (mit Gewicht und
   Preis des Stücks und der Form für die Zuordnung).
2. Jedes ``show()`` fragt ``LagerRegister.link`` nach den Stücken, die zum gezeigten Teil gehören: zuerst über den
   Namen (gleich wie in ``verbauen``), dann über die Form (``IsPartner``: verschoben oder gedreht, auch als Kind eines
   Compound), zuletzt über das ``label`` (übersteht Bohren und Abziehen). Das Ergebnis landet als ``ShownPart``.
3. Am Ende des Laufs baut ``build_bom`` daraus Zeilen, Zuschnitt und Summen; die Nachricht ``BOM`` geht an die App.

Diese Datei importiert nichts Schweres (kein build123d); die Formen werden nur über ``.wrapped.IsPartner`` verglichen.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from typing import Any

from kevcad_kernel.catalog import ART_NAMEN, KLEINTEILE, STANGENWARE, number
from kevcad_kernel.optik import OPTIK_ARTEN

SAEGESCHNITT_MM = 3.0
DEFAULT_STANGENLAENGE_MM = 6000.0
ART_ORDER = {"stange": 0, "platte": 1, "klein": 2, "zukauf": 3, "druck": 4, "eigen": 5}


# ---------------------------------------------------------------------------------------------------------------------
# Zahlen


def de_num(value: float | None, digits: int = 1, group: bool = True) -> str:
    """Deutsche Zahl: Komma, Punkt als Tausendertrenner ab 1.000, Nullen am Ende gekürzt."""
    if value is None:
        return "–"
    x = float(value)
    text = f"{abs(x):.{digits}f}"
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    if group and len(whole) > 3:
        whole = f"{int(whole):,}".replace(",", ".")
    sign = "-" if x < 0 and (whole.strip("0.") or frac) else ""
    return sign + whole + ("," + frac if frac else "")


def de_fixed(value: float | None, digits: int = 2) -> str:
    """Deutsche Zahl mit fester Nachkommazahl (Preise): 7,06; 1.234,50."""
    if value is None:
        return "–"
    text = f"{abs(float(value)):.{digits}f}"
    whole, _, frac = text.partition(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return ("-" if value < 0 else "") + whole + ("," + frac if frac else "")


def eur(value: float | None) -> str:
    return "–" if value is None else f"{de_fixed(value, 2)} €"


def round_half(x: float) -> float:
    """Auf 0,5 mm runden (Schlüssel zum Zusammenfassen)."""
    return math.floor(x * 2 + 0.5) / 2


def _r(x: float | None, digits: int) -> float | None:
    return None if x is None else round(float(x), digits)


def _kg(x: float | None) -> float | None:
    """Gewicht runden: 3 Nachkommastellen, unter 1 kg 4 (Kleinteile, Druckteile)."""
    if x is None:
        return None
    return round(float(x), 3 if abs(x) >= 1 else 4)


def canonical_gehrung(g: tuple[float, float] | list[float]) -> tuple[float, float]:
    """Gleiche Zuschnitte, nur umgedreht: (0, 45) ≡ (45, 0) ≡ (0, -45). Ergebnis: |Ende| ≥ |Anfang|, Ende ≥ 0."""
    a, b = (round(float(g[0]), 1) + 0.0, round(float(g[1]), 1) + 0.0)
    for cand in ((a, b), (-a, -b), (b, a), (-b, -a)):
        if abs(cand[1]) >= abs(cand[0]) and cand[1] >= 0:
            return (cand[0] + 0.0, cand[1] + 0.0)
    return (a, b)


def size_label(groesse: str | None) -> str:
    """"M8-1.25" → "M8"."""
    return str(groesse or "").split("-")[0] or "?"


# ---------------------------------------------------------------------------------------------------------------------
# Stücke und gezeigte Teile


@dataclass
class Piece:
    """Eine ``verbauen``-Zeile oder ein Druckteil (``art`` "druckteil", ohne ``stock_id``)."""

    seq: int
    name: str
    stock_id: str | None
    art: str
    benennung: str
    norm: str | None = None
    material_id: str | None = None
    material_name: str | None = None
    ebene: str = "mitgeliefert"
    laenge: float | None = None  # Stangenware: Maß an der längsten Kante; Schrauben: Länge
    gehrung: tuple[float, float] = (0.0, 0.0)
    breite: float | None = None  # Platten
    tiefe: float | None = None
    flaeche_m2: float | None = None
    form: bool = False
    groesse: str | None = None  # Kleinteile
    stangenlaenge: float | None = None
    kg: float | None = None
    preis: float | None = None
    preis_stand: str | None = None
    preis_quelle: str | None = None
    kg_je_m: float | None = None
    preis_je_m: float | None = None
    verfahren: str | None = None  # Druckteile: "3d-druck" | "harzdruck"
    volume: float | None = None  # Druckteile: mm³
    size: list[float] | None = None  # Druckteile: Hüllmaß
    zukauf: dict[str, Any] | None = None  # Zukaufteile: Hersteller, Nummer, CAD-Art usw. (kevcad.zukaufteil)
    token: str | None = None  # Phase 5: Kennung der Form (Attribut lager_token, übersteht Kopien beim Verschieben)
    teile: list[str] = field(default_factory=list)
    shape: Any = field(default=None, repr=False, compare=False)
    solids: list[Any] = field(default_factory=list, repr=False, compare=False)
    ausrichtung: Any = field(default=None, repr=False, compare=False)  # Druckteile: Lage aufs Bett, None = automatisch

    @property
    def group(self) -> str:
        if self.art in STANGENWARE:
            return "stange"
        if self.art == "platte":
            return "platte"
        if self.art == "druckteil":
            return "druck"
        if self.art == "zukaufteil":
            return "zukauf"
        return "klein"

    @property
    def group_id(self) -> str:
        return self.stock_id or f"druck:{self.material_id}:{self.verfahren}"

    def masse_text(self) -> str:
        if self.art == "zukaufteil":
            return str((self.zukauf or {}).get("masse_text") or "")
        if self.art == "druckteil":
            return " × ".join(de_num(v) for v in (self.size or [0, 0, 0])) + " mm"
        if self.art in STANGENWARE:
            return f"{de_num(self.laenge or 0)} mm"
        if self.art == "platte":
            text = f"{de_num(self.breite or 0)} × {de_num(self.tiefe or 0)} mm"
            return f"Form {text}" if self.form else text
        if self.art == "schraube":
            return f"{size_label(self.groesse)} × {de_num(self.laenge or 0)}"
        if self.art in OPTIK_ARTEN:  # Kameras, Objektive, Zubehör: Text aus kevcad.kamera
            return self.groesse or ""
        return size_label(self.groesse)

    def key(self) -> tuple:
        if self.art == "druckteil":
            return ("druckteil", self.material_id, self.verfahren, _significant(self.volume or 0.0, 4),
                    tuple(sorted((round_half(v) for v in (self.size or [])), reverse=True)))
        if self.art in STANGENWARE:
            return (self.stock_id, round_half(self.laenge or 0.0), canonical_gehrung(self.gehrung))
        if self.art == "platte":
            if self.form:
                return (self.stock_id, "form", round(self.flaeche_m2 or 0.0, 5), round_half(self.breite or 0),
                        round_half(self.tiefe or 0))
            b, t = sorted((round_half(self.breite or 0), round_half(self.tiefe or 0)), reverse=True)
            return (self.stock_id, b, t)
        if self.art == "schraube":
            return (self.stock_id, round_half(self.laenge or 0.0))
        return (self.stock_id,)

    def druck_info(self) -> dict[str, Any]:
        """Feld ``druckteil`` an PART_UPSERT (zusätzlich zum Protokoll)."""
        return {"verfahren": self.verfahren, "material": self.material_id, "kg": _r(self.kg, 4),
                "preis": _r(self.preis, 2)}

    def zukauf_info(self) -> dict[str, Any]:
        """Feld ``zukauf`` an PART_UPSERT (PROTOCOL.md, Phase 3)."""
        z = self.zukauf or {}
        return {"id": self.stock_id, "hersteller": z.get("hersteller"), "mpn": z.get("mpn"), "cad": z.get("cad"),
                "preis": _r(self.preis, 2), "url": z.get("url")}

    def zukauf_line(self) -> dict[str, Any]:
        """Zusätzliche Felder der Stücklistenzeile bei Zukaufteilen (PROTOCOL.md, Phase 3)."""
        z = self.zukauf or {}
        return {"hersteller": z.get("hersteller"), "mpn": z.get("mpn"), "gtin": z.get("gtin"), "url": z.get("url"),
                "bild": z.get("bild"), "preis_stand": self.preis_stand, "preis_brutto": z.get("preis_brutto"),
                "cad_quelle": z.get("cad_quelle"), "vereinfacht": z.get("cad") == "vereinfacht"}

    def stock_info(self) -> dict[str, Any]:
        """Feld ``stock`` an PART_UPSERT."""
        return {"id": self.stock_id, "name": self.benennung, "laenge": _r(self.laenge, 3),
                "gehrung": [float(self.gehrung[0]), float(self.gehrung[1])], "material": self.material_id,
                "kg": _kg(self.kg), "preis": _r(self.preis, 2)}


@dataclass
class ShownPart:
    """Ein gezeigtes Teil des Laufs (letzter Stand je Name)."""

    name: str
    material: str | None = None  # Anzeige
    material_id: str | None = None  # Katalog-Material, falls bekannt
    material_name: str | None = None
    preis_je_kg: float | None = None
    preis_stand: str | None = None
    volume: float = 0.0  # mm³
    mass_g: float | None = None
    size: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    pieces: list[int] = field(default_factory=list)


def piece_values(item: dict[str, Any], material: dict[str, Any] | None, *, laenge: float | None = None,
                 flaeche_m2: float | None = None, volume_mm3: float | None = None) -> dict[str, Any]:
    """Gewicht und Preis eines Stücks: Stangenware kg_je_m × Länge und je_m × Länge, Platten Fläche × Dicke × Dichte
    und je_m2 × Fläche, Kleinteile Volumen × Dichte und je_stueck. Fehlt der Preis am Lagerteil, gilt preis_je_kg des
    Materials × Gewicht."""
    from kevcad_kernel.profiles import kg_je_m as calc_kg_je_m

    art = item.get("art")
    dichte = number((material or {}).get("dichte"))
    preis = item.get("preis") if isinstance(item.get("preis"), dict) else {}
    out: dict[str, Any] = {"kg": None, "preis": None, "kg_je_m": None, "preis_je_m": None,
                           "preis_stand": preis.get("stand"), "preis_quelle": preis.get("quelle")}
    if art in STANGENWARE:
        kgm = calc_kg_je_m(item, material)
        out["kg_je_m"] = kgm
        if kgm is not None and laenge is not None:
            out["kg"] = kgm * laenge / 1000.0
        je_m = number(preis.get("je_m"))
        out["preis_je_m"] = je_m
        if je_m is not None and laenge is not None:
            out["preis"] = je_m * laenge / 1000.0
    elif art == "platte":
        s = number((item.get("masse") or {}).get("s"))
        if flaeche_m2 is not None and s is not None and dichte is not None:
            out["kg"] = flaeche_m2 * s * dichte
        je_m2 = number(preis.get("je_m2"))
        if je_m2 is not None and flaeche_m2 is not None:
            out["preis"] = je_m2 * flaeche_m2
    else:
        if volume_mm3 is not None and dichte is not None:
            out["kg"] = volume_mm3 * dichte / 1e6
        je = number(preis.get("je_stueck"))
        if je is not None:
            out["preis"] = je
    if out["preis"] is None and out["kg"] is not None:
        pkg = number((material or {}).get("preis_je_kg"))
        if pkg is not None:
            out["preis"] = out["kg"] * pkg
            out["preis_stand"] = (material or {}).get("preis_stand")
            out["preis_quelle"] = (material or {}).get("preis_quelle") or "Materialpreis je kg"
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Anmeldung und Zuordnung im Lauf


def _solids(shape: Any) -> list[Any]:
    try:
        return [s.wrapped for s in shape.solids()]
    except Exception:  # noqa: BLE001
        return []


def _partner(a: Any, b: Any) -> bool:
    try:
        return bool(a.IsPartner(b))
    except Exception:  # noqa: BLE001
        return False


class LagerRegister:
    """Stücke eines Laufs und ihre Zuordnung zu gezeigten Teilen."""

    def __init__(self) -> None:
        self.pieces: list[Piece] = []
        self.links: dict[str, list[int]] = {}  # Teilname → seq der Stücke

    def register(self, piece: Piece, shape: Any = None) -> Piece:
        piece.seq = len(self.pieces) + 1
        if shape is not None:
            piece.shape = getattr(shape, "wrapped", None)
            piece.solids = _solids(shape)
        self.pieces.append(piece)
        return piece

    def link(self, name: str, shape: Any) -> list[Piece]:
        """Stücke zum gezeigten Teil ``name`` (siehe Moduldoku); merkt sich die Zuordnung (letztes show() gilt)."""
        found = [p for p in self.pieces if p.name == name]
        if len(found) > 1:
            partner = [p for p in found if self._is_partner(p, shape)]
            found = partner or found
        if not found:
            found = [p for p in self.pieces if self._is_partner(p, shape)]
            if len({p.seq for p in found}) > 1:
                # Gleiche OCCT-Form in mehreren Stücken (Zukauf-CAD aus dem Zwischenspeicher, Normteile als flache
                # Kopien): das Kind einer gezeigten Baugruppe gehört zum Stück, dessen Name davor steht
                # („Wagen B/Rolle_1“ → Stück „Wagen B“)
                prefixed = [p for p in found if p.name and name.startswith(p.name + "/")]
                if prefixed:
                    longest = max(len(p.name) for p in prefixed)
                    found = [p for p in prefixed if len(p.name) == longest]
        if not found:
            label = str(getattr(shape, "label", "") or "").strip()
            if label:
                found = [p for p in self.pieces if p.name == label]
        if not found:
            token = getattr(shape, "lager_token", None)
            if token:
                found = [p for p in self.pieces if p.token == token]
        self.links[name] = [p.seq for p in found]
        return found

    @staticmethod
    def _is_partner(piece: Piece, shape: Any) -> bool:
        wrapped = getattr(shape, "wrapped", None)
        if wrapped is None:
            return False
        if piece.shape is not None and _partner(wrapped, piece.shape):
            return True
        if not piece.solids:
            return False
        mine = _solids(shape)
        return any(_partner(s, ps) for s in mine for ps in piece.solids)

    def unlink(self, name: str) -> None:
        self.links.pop(name, None)


# ---------------------------------------------------------------------------------------------------------------------
# Stückliste


def _significant(x: float, digits: int) -> float:
    if not x:
        return 0.0
    return round(x, digits - 1 - int(math.floor(math.log10(abs(x)))))


def _strip_number(name: str) -> str:
    return re.sub(r"\s+\d+$", "", name).strip() or name


def first_fit_decreasing(lengths: list[float], stange: float, saege: float = SAEGESCHNITT_MM) -> tuple[list[list[float]], list[float]]:
    """Zuschnitt: (Stangen mit ihren Stücken, zu lange Stücke). Zwischen zwei Stücken geht ein Sägeschnitt verloren."""
    bars: list[list[float]] = []
    used: list[float] = []
    too_long: list[float] = []
    for length in sorted(lengths, reverse=True):
        if length > stange + 1e-9:
            too_long.append(length)
            continue
        for i, bar in enumerate(bars):
            if used[i] + saege + length <= stange + 1e-9:
                bar.append(length)
                used[i] += saege + length
                break
        else:
            bars.append([length])
            used.append(length)
    return bars, too_long


def build_bom(pieces: list[Piece], parts: list[ShownPart], *, inventar_regel: bool = False,
              saegeschnitt: float = SAEGESCHNITT_MM,
              default_stangenlaenge: float = DEFAULT_STANGENLAENGE_MM) -> dict[str, Any]:
    """Zeilen, Zuschnitt, Summen und Hinweise wie die Nachricht BOM (ohne ``type``/``run``).

    Mit ``inventar_regel`` gibt es keine Eigenteile: gezeigte Teile ohne Lagerteil oder Druckteil sind Verstöße und
    fehlen in der Liste (Hinweis). Ohne Regel werden sie mit Material als Eigenteil geführt."""
    warnings: list[str] = []
    by_seq = {p.seq: p for p in pieces}
    for p in pieces:
        p.teile = []
    linked: set[int] = set()
    for part in parts:
        for seq in part.pieces:
            piece = by_seq.get(seq)
            if piece is not None and part.name not in piece.teile:
                piece.teile.append(part.name)
                linked.add(seq)
    for p in pieces:
        if p.seq not in linked:
            what = (f"Druckteil „{p.name}“" if p.art == "druckteil" else
                    f"{'Zukaufteil' if p.art == 'zukaufteil' else 'Lagerteil'} „{p.name}“ ({p.benennung})")
            warnings.append(f"{what} ist keinem gezeigten Teil zugeordnet: in show() denselben Namen wie in "
                            f"{'druckteil' if p.art == 'druckteil' else 'verbauen'}() verwenden")

    # Lagerteile zusammenfassen
    groups: dict[tuple, list[Piece]] = {}
    first_seen: dict[str, int] = {}
    for p in pieces:
        groups.setdefault(p.key(), []).append(p)
        first_seen.setdefault(p.group_id, p.seq)
    order = sorted(groups.items(), key=lambda kv: (ART_ORDER[kv[1][0].group], first_seen[kv[1][0].group_id],
                                                   -(kv[1][0].laenge or 0.0) if kv[1][0].group != "platte"
                                                   else -((kv[1][0].flaeche_m2 or 0.0))))
    lines: list[dict[str, Any]] = []
    stands: set[str] = set()
    brutto: list[str] = []
    missing_price: list[str] = []
    for _key, grp in order:
        p = grp[0]
        n = len(grp)
        kg_je = p.kg
        preis_je = p.preis
        line: dict[str, Any] = {
            "pos": len(lines) + 1,
            "art": p.art,
            "stock_id": p.stock_id,
            "benennung": p.benennung if p.art != "druckteil" or n == 1 else _strip_number(p.benennung),
            "norm": p.norm,
            "material": p.material_name,
            "laenge": _r(round_half(p.laenge), 1) if p.laenge is not None and p.art in STANGENWARE
            else (_r(p.laenge, 1) if p.art == "schraube" else None),
            "gehrung": list(canonical_gehrung(p.gehrung)) if p.art in STANGENWARE else [0.0, 0.0],
            "masse_text": p.masse_text(),
            "anzahl": n,
            "kg_je": _kg(kg_je),
            "kg": _kg(sum(q.kg for q in grp if q.kg is not None)) if kg_je is not None else None,
            "preis_je": _r(preis_je, 2),
            "preis": _r(sum(q.preis for q in grp if q.preis is not None), 2) if preis_je is not None else None,
            "teile": [t for q in grp for t in q.teile],
            "eigenteil": False,
        }
        if p.art == "platte":
            line["flaeche_m2"] = _r(p.flaeche_m2, 4)
        if p.art == "druckteil":
            line["verfahren"] = p.verfahren
        if p.art == "zukaufteil":
            line.update(p.zukauf_line())
            if preis_je is not None and line.get("preis_brutto") is True:
                brutto.append(p.benennung)
        lines.append(line)
        if preis_je is None:
            missing_price.append(p.benennung)
        elif p.preis_stand:
            stands.add(str(p.preis_stand)[:7])

    # Eigenteile: gezeigt, mit Material, ohne Lagerteil
    without_material: list[str] = []
    own_groups: dict[tuple, list[ShownPart]] = {}
    outside: list[str] = []
    for part in parts:
        if part.pieces:
            continue
        if inventar_regel:
            outside.append(part.name)
            continue
        if not part.material:
            without_material.append(part.name)
            continue
        size = sorted((round_half(v) for v in part.size), reverse=True)
        key = (part.material_id or part.material, _significant(part.volume, 4), tuple(size))
        own_groups.setdefault(key, []).append(part)
    for grp in own_groups.values():
        p = grp[0]
        n = len(grp)
        kg_je = p.mass_g / 1000.0 if p.mass_g is not None else None
        preis_je = kg_je * p.preis_je_kg if kg_je is not None and p.preis_je_kg is not None else None
        lines.append({
            "pos": len(lines) + 1, "art": "eigenteil", "stock_id": None,
            "benennung": p.name if n == 1 else _strip_number(p.name), "norm": None,
            "material": p.material_name or p.material, "laenge": None, "gehrung": [0.0, 0.0],
            "masse_text": " × ".join(de_num(v) for v in p.size) + " mm", "anzahl": n,
            "kg_je": _kg(kg_je), "kg": _kg(kg_je * n) if kg_je is not None else None,
            "preis_je": _r(preis_je, 2), "preis": _r(preis_je * n, 2) if preis_je is not None else None,
            "teile": [q.name for q in grp], "eigenteil": True,
        })
        if preis_je is None:
            reason = (f"Material „{p.material}“ hat keinen preis_je_kg im Katalog" if p.material_id
                      else f"Material „{p.material}“ steht nicht im Katalog")
            warnings.append(f"{p.name}: Eigenteil ohne Preis ({reason})")
        elif p.preis_stand:
            stands.add(str(p.preis_stand))
    if outside:
        shown = ", ".join(outside[:5]) + (" …" if len(outside) > 5 else "")
        warnings.append(f"Inventar-Regel: {len(outside)} Teil(e) nicht aus dem Inventar, fehlen in der Stückliste: "
                        f"{shown}")
    if without_material:
        shown = ", ".join(without_material[:5]) + (" …" if len(without_material) > 5 else "")
        warnings.append(f"{len(without_material)} Teil(e) ohne Material und ohne Lagerteil fehlen in der Stückliste: "
                        f"{shown}")
    lagerteile_ohne_preis = [b for b in dict.fromkeys(missing_price)]
    if lagerteile_ohne_preis:
        warnings.append("Ohne Preis: " + ", ".join(lagerteile_ohne_preis))

    # Zuschnitt je Stangenware
    cuts: list[dict[str, Any]] = []
    bars_by_stock: dict[str, list[Piece]] = {}
    for p in pieces:
        if p.art in STANGENWARE and p.stock_id:
            bars_by_stock.setdefault(p.stock_id, []).append(p)
    for stock_id, plist in sorted(bars_by_stock.items(), key=lambda kv: first_seen[kv[0]]):
        p0 = plist[0]
        stange = p0.stangenlaenge
        if not stange:
            stange = default_stangenlaenge
            warnings.append(f"{p0.benennung}: stangenlaenge fehlt im Katalog, Zuschnitt mit {de_num(stange)} mm")
        lengths = [round_half(p.laenge or 0.0) for p in plist]
        bars, too_long = first_fit_decreasing(lengths, stange, saegeschnitt)
        for length in too_long:
            names = [p.name for p in plist if round_half(p.laenge or 0.0) == length]
            warnings.append(f"{p0.benennung}: Stück {de_num(length)} mm ({', '.join(names[:3])}) ist länger als die "
                            f"Stange ({de_num(stange)} mm) – Sonderlänge oder stoßen")
        total = len(bars) * stange
        waste = (total - sum(sum(b) for b in bars)) / total * 100.0 if total else 0.0
        cut: dict[str, Any] = {"stock_id": stock_id, "benennung": p0.benennung, "stangenlaenge": stange,
                               "saegeschnitt": saegeschnitt, "stangen": bars, "verschnitt_prozent": round(waste, 1)}
        if too_long:
            cut["zu_lang"] = too_long
        if p0.preis_je_m is not None:
            cut["preis_stangen"] = round(len(bars) * stange / 1000.0 * p0.preis_je_m, 2)
        cuts.append(cut)

    kg_total = sum(line["kg"] for line in lines if line["kg"] is not None)
    priced = [line["preis"] for line in lines if line["preis"] is not None]
    totals: dict[str, Any] = {
        "kg": round(kg_total, 3),
        "preis": round(sum(priced), 2) if priced else None,
        "positionen": len(lines),
        "teile": sum(line["anzahl"] for line in lines),
        "preis_hinweis": (_price_note(stands) + ("; Zukaufteile zum Shoppreis brutto" if brutto else "")) if priced
        else None,
    }
    return {"lines": lines, "cuts": cuts, "totals": totals, "warnings": warnings}


def _price_note(stands: set[str]) -> str:
    clean = sorted(s for s in stands if s)
    if not clean:
        return "Richtpreise"
    if len(clean) == 1:
        return f"Richtpreise, Stand {clean[0]}"
    return f"Richtpreise, Stand {clean[0]} bis {clean[-1]}"


def inventory_text(violations: list[str]) -> str:
    """Meldung für Verstöße gegen die Inventar-Regel (run, Export)."""
    n = len(violations)
    names = ", ".join(violations[:8]) + (" …" if n > 8 else "")
    teile = "1 Teil ist" if n == 1 else f"{n} Teile sind"
    return (f"Inventar-Regel: {teile} nicht aus dem Inventar: {names} – passendes Lagerteil mit stock_search suchen "
            "und verbauen, als Druckteil kennzeichnen (lager.druckteil) oder Kevin bitten, das Lagerteil anzulegen.")


def empty_bom() -> dict[str, Any]:
    return {"lines": [], "cuts": [], "totals": {"kg": 0.0, "preis": None, "positionen": 0, "teile": 0,
                                                "preis_hinweis": None}, "warnings": []}


# ---------------------------------------------------------------------------------------------------------------------
# Texte und CSV


def gehrung_text(g: list[float] | tuple[float, float] | None) -> str:
    if not g or not any(abs(float(v)) > 1e-9 for v in g):
        return ""
    return f"{de_num(g[0])}°/{de_num(g[1])}°"


def cut_lines(cut: dict[str, Any]) -> list[str]:
    """„Stange 1: 882 + 882 + … = 5.394 mm, Rest 606 mm“ je Stange."""
    out = []
    stange = float(cut.get("stangenlaenge") or 0)
    for i, bar in enumerate(cut.get("stangen") or [], 1):
        total = sum(bar)
        out.append(f"Stange {i}: {' + '.join(de_num(v) for v in bar)} = {de_num(total)} mm, "
                   f"Rest {de_num(stange - total)} mm")
    return out


def art_label(line: dict[str, Any]) -> str:
    if line.get("eigenteil"):
        return "Eigenteil"
    if line.get("art") == "druckteil":
        return "Druckteil" + (" (Harz)" if line.get("verfahren") == "harzdruck" else "")
    if line.get("art") == "zukaufteil":
        return "Zukaufteil" + (" (vereinfacht)" if line.get("vereinfacht") else "")
    return ART_NAMEN.get(str(line.get("art")), str(line.get("art")))


def to_csv(bom: dict[str, Any], title: str = "") -> str:
    """Stückliste, Zuschnitt, Summen als CSV (Semikolon, deutsche Zahlen). Als Datei mit ``utf-8-sig`` schreiben."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")

    def num(v: Any, digits: int = 3) -> str:
        return "" if v is None else de_num(v, digits, group=False)

    def money(v: Any) -> str:
        return "" if v is None else f"{float(v):.2f}".replace(".", ",")

    head = ["Stückliste"] + ([title] if title else []) + ([f"Lauf {bom['run']}"] if bom.get("run") else [])
    w.writerow(head)
    w.writerow(["Pos", "Art", "Benennung", "Norm", "Material", "Maße", "Länge (mm)", "Gehrung (°)", "Anzahl",
                "kg je Stück", "kg", "€ je Stück", "€", "Lagerteil", "Teile", "Hersteller", "Herstellernummer",
                "EAN", "Link", "Preisstand", "CAD"])
    for line in bom.get("lines") or []:
        g = line.get("gehrung") or [0, 0]
        w.writerow([line.get("pos"), art_label(line), line.get("benennung"), line.get("norm") or "",
                    line.get("material") or "", line.get("masse_text") or "", num(line.get("laenge"), 1),
                    f"{num(g[0], 1)} / {num(g[1], 1)}" if any(g) else "", line.get("anzahl"),
                    num(line.get("kg_je")), num(line.get("kg")), money(line.get("preis_je")), money(line.get("preis")),
                    line.get("stock_id") or "", ", ".join(line.get("teile") or [])]
                   + ([line.get("hersteller") or "", line.get("mpn") or "", line.get("gtin") or "",
                       line.get("url") or "", (line.get("preis_stand") or "") + (
                           " brutto" if line.get("preis_brutto") is True else (
                               " netto" if line.get("preis_brutto") is False else "")),
                       "vereinfacht" if line.get("vereinfacht") else (line.get("cad_quelle") or "")]
                      if line.get("art") == "zukaufteil" else []))
    w.writerow([])
    w.writerow(["Zuschnitt"])
    w.writerow(["Lagerteil", "Benennung", "Stange", "Stangenlänge (mm)", "Stücke (mm)", "Summe (mm)", "Rest (mm)",
                "Sägeschnitt (mm)", "Verschnitt (%)"])
    for cut in bom.get("cuts") or []:
        stange = float(cut.get("stangenlaenge") or 0)
        for i, bar in enumerate(cut.get("stangen") or [], 1):
            total = sum(bar)
            w.writerow([cut.get("stock_id"), cut.get("benennung"), i, num(stange, 1),
                        " + ".join(num(v, 1) for v in bar), num(total, 1), num(stange - total, 1),
                        num(cut.get("saegeschnitt"), 1), num(cut.get("verschnitt_prozent"), 1) if i == 1 else ""])
    w.writerow([])
    totals = bom.get("totals") or {}
    w.writerow(["Summen"])
    w.writerow(["Positionen", totals.get("positionen", 0)])
    w.writerow(["Teile", totals.get("teile", 0)])
    w.writerow(["Gewicht (kg)", num(totals.get("kg"))])
    w.writerow(["Materialkosten (€)", money(totals.get("preis"))])
    if totals.get("preis_hinweis"):
        w.writerow(["Hinweis", totals["preis_hinweis"]])
    for text in bom.get("warnings") or []:
        w.writerow(["Hinweis", text])
    return buf.getvalue()


def is_kleinteil(art: str) -> bool:
    return art in KLEINTEILE

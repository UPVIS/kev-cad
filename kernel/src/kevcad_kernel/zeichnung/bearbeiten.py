"""Bearbeitungs-Operationen eines Blatts (DOKUMENTE.md, ``DRAWING_EDIT.ops``), gemeinsam für App (``von: kevin``) und
MCP (``von: agent``).

| op | Felder | Wirkung |
|---|---|---|
| ``mass_verschieben`` | ``id``, ``versatz`` und/oder ``text_lage`` | Maß bleibt danach dort (``fest``) |
| ``mass_loeschen`` | ``id`` | automatische Maße kommen nicht wieder (``auto.unterdrueckt``) |
| ``mass_neu`` | ``art``, ``ansicht``, ``bezuege`` (Klick ``{ansicht, punkt}`` in Blatt-mm oder Bezug mit ``merkmal``), ``versatz``, ``text``, ``toleranz``, ``richtung`` | neues Maß mit ``quelle`` = von |
| ``ansicht_neu`` | ``art``, ``lage``, bei Schnitt ``schnitt``, bei Einzelheit ``einzelheit``, ``massstab`` | |
| ``ansicht_verschieben`` | ``id``, ``lage`` | Ansicht bleibt dort (``fest``) |
| ``ansicht_loeschen`` | ``id`` | Maße der Ansicht fallen mit weg |
| ``massstab`` | ``wert`` („1:2“) | schaltet die automatische Wahl ab |
| ``notiz`` | ``text``, ``lage``, ``zeiger`` | |
| ``notiz_loeschen`` | ``id`` | |
| ``schriftfeld`` | ``feld``, ``wert`` | Kevins Wert bleibt (Kev CAD überschreibt ihn nicht mehr) |
| ``auto`` | ``ansichten``, ``masse``, ``zuruecksetzen`` | automatische Ansichten bzw. Maße an oder aus; ``zuruecksetzen`` hebt alle Unterdrückungen auf und setzt automatische Maße neu |
| ``unterdrueckung_aufheben`` | ``index`` | Eintrag in ``unterdrueckt`` entfernen (das Maß kommt beim nächsten Rechnen wieder) |
| ``format`` (zusätzlich) | ``wert`` (A4 …), ``ausrichtung`` | schaltet die automatische Formatwahl ab |
| ``mass_aendern`` (zusätzlich) | ``id``, ``text``, ``toleranz``, ``fest`` | Text („<>“ = Messwert) oder Toleranz eines Maßes |
| ``schnitt_umkehren`` (1.3) | ``id`` | Blickrichtung eines Schnitts umkehren (die andere Hälfte bleibt stehen) |
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kevcad_kernel.zeichnung import bezuege as bz
from kevcad_kernel.zeichnung import dokument as dok
from kevcad_kernel.zeichnung.blatt import MASSSTAEBE, lage_umrechnen, massstab_faktor, massstab_text
from kevcad_kernel.zeichnung.merkmale import Merkmale

OPS = ("mass_verschieben", "mass_loeschen", "mass_neu", "ansicht_neu", "ansicht_verschieben", "ansicht_loeschen",
       "massstab", "notiz", "notiz_loeschen", "schriftfeld", "auto", "unterdrueckung_aufheben", "format", "mass_aendern",
       "schnitt_umkehren")


class OpFehler(ValueError):
    pass


def anwenden(blatt: dict[str, Any], ops: list[dict[str, Any]], von: str, erg: Any = None) -> tuple[dict[str, Any],
                                                                                                    list[dict[str, Any]]]:
    """Operationen nacheinander anwenden. ``erg``: letztes Rechenergebnis des Blatts (für Klicks in Ansichten).
    Liefert das geänderte Blatt und je Operation ``{"op", "ok", "id"?, "fehler"?}``. Fehlerhafte Operationen ändern
    nichts, die übrigen werden trotzdem ausgeführt."""
    von = von if von in ("kevin", "agent") else "kevin"
    b = dok.normalisiere(blatt)
    out = []
    for op in ops or []:
        name = str((op or {}).get("op") or "")
        try:
            if name not in OPS:
                raise OpFehler(f"Operation {name!r} unbekannt ({', '.join(OPS)})")
            res = globals()[f"_{name}"](b, op, von, erg) or {}
            out.append({"op": name, "ok": True, **res})
        except (OpFehler, dok.BlattFehler, KeyError, ValueError, TypeError) as exc:
            out.append({"op": name, "ok": False, "fehler": str(exc)})
    return dok.normalisiere(b), out


def _mass(b: dict[str, Any], mid: Any) -> dict[str, Any]:
    m = next((m for m in b["masse"] if m.get("id") == mid), None)
    if m is None:
        raise OpFehler(f"Maß {mid!r} gibt es nicht (vorhanden: {', '.join(str(x.get('id')) for x in b['masse'][:30])})")
    return m


def _ansicht(b: dict[str, Any], vid: Any) -> dict[str, Any]:
    a = next((a for a in b["ansichten"] if a.get("id") == vid), None)
    if a is None:
        raise OpFehler(f"Ansicht {vid!r} gibt es nicht (vorhanden: {', '.join(str(x.get('id')) for x in b['ansichten'])})")
    return a


def _punkt(v: Any, name: str) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(isinstance(x, (int, float)) for x in v):
        raise OpFehler(f"{name}: [x, y] in Blatt-mm angeben")
    return [float(v[0]), float(v[1])]


# ---------------------------------------------------------------------------------------------------------------------
# Maße
# ---------------------------------------------------------------------------------------------------------------------


def _mass_verschieben(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    m = _mass(b, op.get("id"))
    if op.get("versatz") is None and op.get("text_lage") is None:
        raise OpFehler("mass_verschieben braucht versatz oder text_lage")
    if op.get("versatz") is not None:
        m["versatz"] = float(op["versatz"])
    if op.get("text_lage") is not None:
        tl = _punkt(op["text_lage"], "text_lage")
        # gespeichert relativ: bei Hinweisen zum Ziel, bei linearen Maßen entlang der Maßlinie ab ihrer Mitte
        anker = m.get("anker") or []
        v = (erg.ansichten.get(str(m.get("ansicht"))) if erg is not None else None)
        mitte = np.asarray(v.mitte, dtype=float) if v is not None else np.zeros(2)
        if anker:
            a0 = np.asarray(anker[0], dtype=float) + mitte
            if len(anker) >= 2 and m.get("art") in ("linear", "durchmesser", "bezugskette"):
                a1 = np.asarray(anker[1], dtype=float) + mitte
                r = m.get("_richtung") or m.get("richtung") or ("x" if abs(a1[0] - a0[0]) >= abs(a1[1] - a0[1])
                                                                else "y")
                u = np.array([1.0, 0.0]) if r == "x" else np.array([0.0, 1.0]) if r == "y" else \
                    (a1 - a0) / (np.linalg.norm(a1 - a0) or 1.0)
                m["text_versatz"] = round(float((np.asarray(tl) - (a0 + a1) / 2) @ u), 3)
            else:
                m["text_versatz"] = [round(tl[0] - float(a0[0]), 3), round(tl[1] - float(a0[1]), 3)]
        else:
            m["text_versatz"] = None
    m["fest"] = True
    return {"id": m["id"]}


def _mass_loeschen(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    m = _mass(b, op.get("id"))
    b["masse"] = [x for x in b["masse"] if x is not m]
    if m.get("quelle") == "auto":
        unterdruecke(b, m)
    return {"id": m["id"]}


def unterdruecke(b: dict[str, Any], m: dict[str, Any]) -> None:
    """Automatisches Maß in ``unterdrueckt`` eintragen (Vertrag 1.1: Art, Ansicht, Bezüge; dazu der Schlüssel)."""
    eintrag = {"art": m.get("art"), "ansicht": m.get("ansicht"), "bezuege": list(m.get("bezuege") or []),
               "schluessel": m.get("schluessel")}
    if not any(passt_unterdrueckt(u, m) for u in b["unterdrueckt"]):
        b["unterdrueckt"].append(eintrag)


def _bezug_schluessel(x: dict[str, Any]) -> tuple[Any, ...]:
    return (x.get("teil") or "", x.get("merkmal") or x.get("ref") or "", x.get("element") or "")


def passt_unterdrueckt(u: dict[str, Any], m: dict[str, Any]) -> bool:
    """Gehört das Maß ``m`` zu einer Unterdrückung ``u``? Gleicher Schlüssel oder gleiche Art mit denselben Bezügen."""
    if u.get("schluessel") and m.get("schluessel"):
        return u["schluessel"] == m["schluessel"]
    if u.get("art") != m.get("art"):
        return False
    a = sorted(_bezug_schluessel(x) for x in u.get("bezuege") or [])
    b = sorted(_bezug_schluessel(x) for x in m.get("bezuege") or [])
    return a == b


def _mass_aendern(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    m = _mass(b, op.get("id"))
    for k in ("text", "toleranz"):
        if k in op:
            m[k] = op[k] if op[k] not in ("",) else None
    m["fest"] = bool(op.get("fest", True))
    return {"id": m["id"]}


def _mass_neu(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    art = op.get("art")
    roh = list(op.get("bezuege") or [])
    if not roh:
        raise OpFehler("mass_neu braucht bezuege: Klicks {ansicht, punkt} oder Bezüge {merkmal, teil}")
    vid = op.get("ansicht") or next((r.get("ansicht") for r in roh if isinstance(r, dict) and r.get("ansicht")), None)
    bezuege = []
    for r in roh:
        if not isinstance(r, dict):
            raise OpFehler("jeder Bezug ist ein Objekt")
        if r.get("punkt") is not None:
            if erg is None:
                raise OpFehler("Klick-Bezüge brauchen ein gerechnetes Blatt")
            vid_r = r.get("ansicht") or vid or _ansicht_unter(erg, _punkt(r["punkt"], "punkt"))
            if vid_r is None:
                raise OpFehler(f"Punkt {r['punkt']} liegt in keiner Ansicht")
            vid = vid or vid_r
            bezuege.append(klick(erg, vid_r, _punkt(r["punkt"], "punkt"), art, op.get("richtung")))
        else:
            bezuege.append(_bezug_aus_angabe(r, b, erg))
    if vid is None:
        vid = _ansicht_fuer(b, erg, bezuege)
    if vid is None or not any(a.get("id") == vid for a in b["ansichten"]):
        raise OpFehler(f"Ansicht {vid!r} gibt es nicht")
    if art is None:
        art = "linear" if len(bezuege) >= 2 else ("bohrung" if (bezuege[0].get("merkmal") or "").startswith(
            ("bohrung", "einsatztasche")) else "durchmesser" if bezuege[0].get("signatur", {}).get("typ") == "kreis"
            else "merkmal")
    if art not in dok.MASS_ARTEN:
        raise OpFehler(f"art {art!r} unbekannt ({', '.join(dok.MASS_ARTEN)})")
    if art in ("linear", "winkel") and len(bezuege) < 2:
        raise OpFehler(f"{art} braucht zwei Bezüge")
    mid = dok.naechste("m", {m.get("id") for m in b["masse"]})
    m = {"id": mid, "art": art, "ansicht": vid, "bezuege": bezuege, "richtung": op.get("richtung"),
         "versatz": float(op["versatz"]) if op.get("versatz") is not None else None, "text": op.get("text"),
         "toleranz": op.get("toleranz"), "quelle": von, "fest": op.get("versatz") is not None, "verwaist": False}
    b["masse"].append(m)
    return {"id": mid, "bezuege": [{"teil": x.get("teil"), "merkmal": x.get("merkmal"), "art": x.get("art"),
                                    "ref": x.get("ref")} for x in bezuege]}


def _bezug_aus_angabe(r: dict[str, Any], b: dict[str, Any], erg: Any) -> dict[str, Any]:
    """Bezug aus {"merkmal": "bohrung:2", "teil": …} (Agent) oder vollständigem Bezug."""
    if r.get("signatur"):
        return dict(r)
    mid = r.get("merkmal")
    if not mid:
        raise OpFehler("Bezug braucht punkt (Klick) oder merkmal (z. B. \"bohrung:2\", \"seite:x-\")")
    teil = r.get("teil")
    if teil is None:
        teil = b["inhalt"]["teile"][0] if b["inhalt"]["art"] == "teil" and b["inhalt"]["teile"] else ""
    mm: Merkmale | None = None
    if erg is not None:
        mm = erg.merkmale.get(teil) or (erg.merkmale.get("") if not teil else None)
    if mm is None:
        raise OpFehler(f"Merkmale von {teil or 'Zusammenbau'!r} nicht verfügbar (erst rechnen)")
    m = mm.get(str(mid))
    if m is None:
        ids = ", ".join(x.id for x in mm.liste[:40])
        raise OpFehler(f"Merkmal {mid!r} gibt es an {teil or 'der Baugruppe'!r} nicht (vorhanden: {ids})")
    out = bz.aus_merkmal(teil, m)
    if r.get("element"):
        out["element"] = r["element"]
    return out


def _ansicht_unter(erg: Any, p: list[float]) -> str | None:
    best = None
    for vid, v in erg.ansichten.items():
        r = v.rahmen.erweitert(4.0)
        if r.x0 <= p[0] <= r.x1 and r.y0 <= p[1] <= r.y1:
            d = math.hypot(p[0] - r.mitte[0], p[1] - r.mitte[1])
            if best is None or d < best[0]:
                best = (d, vid)
    return best[1] if best else None


def _ansicht_fuer(b: dict[str, Any], erg: Any, bezuege: list[dict[str, Any]]) -> str | None:
    """Erste Ansicht, in der alle Bezüge als Punkt oder Kante erscheinen (für Agent-Maße ohne Ansicht)."""
    for a in b["ansichten"]:
        if a.get("art") in ("iso", "iso_vorn_links", "iso_hinten_rechts", "iso_hinten_links"):
            continue
        return a.get("id")
    return None


def klick(erg: Any, vid: str, punkt: list[float], art: str | None = None, richtung: str | None = None) \
        -> dict[str, Any]:
    """Nächstes Element unter einem Klick (Blatt-mm) in der Ansicht ``vid``: Merkmale bevorzugt (Bohrung, Seite,
    Stirnseite, Fase, Radius), sonst Kante oder Punkt des Teils. Liefert einen Bezug."""
    v = erg.ansichten.get(vid)
    if v is None:
        raise OpFehler(f"Ansicht {vid!r} gibt es nicht")
    p = np.asarray(punkt, dtype=float)
    system = erg.system
    kandidaten: list[tuple[float, int, dict[str, Any]]] = []
    teile = [n for n in erg.merkmale if n]
    if len(teile) > 1 or not teile:
        # Zusammenbau: Teil mit der nächsten sichtbaren Linie
        best = None
        for name, d in (v.proj.teile or {}).items():
            for pl in d.get("sichtbar") or []:
                q = v.blatt(pl)
                dist = _abstand_polylinie(p, q)
                if best is None or dist < best[0]:
                    best = (dist, name)
        if best is None:
            raise OpFehler("kein Teil in der Nähe des Klicks")
        teile = [best[1]]
        if best[1] not in erg.merkmale:
            raise OpFehler(f"Teil {best[1]!r}: Merkmale nicht geladen")
    for name in teile:
        mm: Merkmale = erg.merkmale[name]
        for m in mm.liste:
            if m.art in ("huelle", "lochbild", "stange"):
                continue
            el = bz.element(m, mm, name)
            if el is None:
                continue
            d = _abstand_element(p, el, v, system)
            if d is not None:
                vorrang = 0 if m.art in ("bohrung", "einsatztasche", "radius", "fase", "muttertasche", "langloch") else 1
                if richtung in ("x", "y") and _parallel_zur_messrichtung(el, v, system, richtung):
                    vorrang = 3  # Kante liegt längs der Messrichtung: für dieses Maß kein sinnvoller Ansatz (Ecke)
                kandidaten.append((d, vorrang, bz.aus_merkmal(name, m)))
        for k in mm.kanten:
            q = v.blatt3(system.lokal(mm.system.welt(k.punkte)))
            d = _abstand_polylinie(p, q)
            vorrang = 2
            if richtung in ("x", "y") and len(q) >= 2:
                dq = q[-1] - q[0]
                if float(np.linalg.norm(dq)) > 1e-6 and abs(dq[1 if richtung == "x" else 0]) < 1e-6:
                    vorrang = 3
            kandidaten.append((d + 0.3, vorrang, bz.aus_kante(name, k)))
        for i, pt in enumerate(mm.punkte):
            q = v.blatt3(system.lokal(mm.system.welt(pt)))
            kandidaten.append((float(np.linalg.norm(q - p)) - 0.5, 1, bz.aus_punkt(name, pt, i)))
    if not kandidaten:
        raise OpFehler("nichts in der Nähe des Klicks gefunden")
    dmin = min(k[0] for k in kandidaten)
    nah = [k for k in kandidaten if k[0] <= dmin + 1.5]
    nah.sort(key=lambda k: (k[1], k[0]))
    if nah[0][0] > 8.0:
        raise OpFehler(f"kein Element näher als 8 mm am Klick (nächstes {nah[0][0]:.1f} mm)")
    return nah[0][2]


def _parallel_zur_messrichtung(el: bz.Element, v: Any, system: Any, richtung: str) -> bool:
    """Ebene, die als Kante längs der Messrichtung erscheint (die Deckfläche eines Rohrs für ein waagrechtes Maß)."""
    if el.typ != "ebene" or el.ecken is None:
        return False
    q = v.blatt3(system.lokal(np.asarray(el.ecken)))
    quer = 1 if richtung == "x" else 0
    return float(np.ptp(q[:, quer])) < 0.05 and float(np.ptp(q[:, 1 - quer])) > 0.05


def _abstand_polylinie(p: np.ndarray, q: np.ndarray) -> float:
    if len(q) == 1:
        return float(np.linalg.norm(q[0] - p))
    a, b = q[:-1], q[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12), 0, 1)
    c = a + ab * t[:, None]
    return float(np.min(np.linalg.norm(c - p, axis=1)))


def _abstand_element(p: np.ndarray, el: bz.Element, v: Any, system: Any) -> float | None:
    c = v.blatt3(system.lokal(el.p))
    if el.typ in ("kreis", "bogen") and el.r and el.d is not None and abs(
            float(np.dot(system.richtung_lokal(el.d), v.blick.d))) > 1 - 1e-6:
        return abs(float(np.linalg.norm(p - c)) - el.r * v.s) * 0.8
    if el.ecken is not None and len(el.ecken) >= 2:
        q = v.blatt3(system.lokal(np.asarray(el.ecken)))
        if np.ptp(q[:, 0]) < 0.05 or np.ptp(q[:, 1]) < 0.05:  # Ebene als Kante gesehen
            lo, hi = q.min(axis=0), q.max(axis=0)
            return _abstand_polylinie(p, np.array([lo, hi]))
        return None
    return float(np.linalg.norm(p - c))


# ---------------------------------------------------------------------------------------------------------------------
# Ansichten, Maßstab, Format
# ---------------------------------------------------------------------------------------------------------------------


def _ansicht_neu(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    art = op.get("art")
    if art not in dok.ANSICHT_ARTEN:
        raise OpFehler(f"art {art!r} unbekannt ({', '.join(dok.ANSICHT_ARTEN)})")
    vid = dok.naechste("v", {a.get("id") for a in b["ansichten"]})
    a: dict[str, Any] = {"id": vid, "art": art, "lage": None, "massstab": op.get("massstab"),
                         "verdeckt": art not in ("iso",), "mittellinien": True}
    if op.get("lage") is not None:
        a["lage"] = _punkt(op["lage"], "lage")
        a["fest"] = True
    if art == "schnitt":
        sp = dict(op.get("schnitt") or {})
        if not sp.get("ebene") and sp.get("linie") is not None:  # in der App gezogen: Linie in Blatt-mm
            linie = sp.pop("linie")
            sp.update(schnitt_aus_linie(erg, sp.get("von"), linie, bool(sp.pop("umkehren", False))))
        if not sp.get("ebene"):
            raise OpFehler("Schnitt braucht schnitt.ebene {punkt, normale} und schnitt.von")
        sp.setdefault("name", _naechster_buchstabe(b))
        a["schnitt"] = sp
    if art == "einzelheit":
        ez = dict(op.get("einzelheit") or {})
        if ez.get("mitte") is None and ez.get("kreis") is not None:  # in der App aufgezogen: Kreis in Blatt-mm
            kreis = ez.pop("kreis")
            ez.update(einzelheit_aus_kreis(erg, ez.get("von"), kreis, ez.get("faktor")))
        if ez.get("mitte") is None or not ez.get("von"):
            raise OpFehler("Einzelheit braucht einzelheit.von, mitte [x, y] (Modell-mm der Ansicht), radius, faktor")
        ez.setdefault("radius", 10.0)
        ez.setdefault("faktor", 4)
        ez.setdefault("name", _naechster_buchstabe(b))
        a["einzelheit"] = ez
    b["ansichten"].append(a)
    return {"id": vid}


def _quell_ansicht(erg: Any, von: Any, punkt: list[float]) -> tuple[str, Any]:
    """Ansicht, in der ein Schnitt oder eine Einzelheit angelegt wird: ``von`` oder die unter ``punkt`` (Blatt-mm)."""
    if erg is None:
        raise OpFehler("Das Blatt ist noch nicht gerechnet: erst DRAWING_REQ, dann Schnitt oder Einzelheit")
    vid = str(von) if von else _ansicht_unter(erg, punkt)
    v = erg.ansichten.get(vid) if vid else None
    if v is None:
        raise OpFehler("Schnitt und Einzelheit in einer Ansicht anlegen (Punkt liegt in keiner Ansicht)")
    if v.art in ("schnitt", "einzelheit") or not getattr(v.blick, "orthogonal", True):
        raise OpFehler(f"In der Ansicht {vid} ({v.art}) geht das nicht: eine Vorder-, Seiten- oder Draufsicht wählen")
    return vid, v


def blatt_zu_modell(v: Any, p: Any) -> np.ndarray:
    """Blatt-mm → Modell-mm der Ansicht (2D vor dem Maßstab), Umkehrung von ``_Ansicht.blatt`` samt Unterbrechungen
    langer Rohre."""
    p = np.asarray(p, dtype=float)
    x0, y0, x1, y1 = v.rahmen_m
    cx = (float(v.gx(x0)) + float(v.gx(x1))) / 2
    cy = (y0 + y1) / 2
    g = cx + (p[0] - v.mitte[0]) / v.s
    if v.brueche:
        w = max(x1 - x0, 1.0)
        xs = np.linspace(x0 - 2 * w, x1 + 2 * w, 8001)
        x = float(np.interp(g, v.gx(xs), xs))
    else:
        x = float(g)
    return np.array([x, cy + (p[1] - v.mitte[1]) / v.s])


def schnitt_aus_linie(erg: Any, von: Any, linie: Any, umkehren: bool = False) -> dict[str, Any]:
    """Schnittebene aus einer in der App gezogenen Linie (zwei Punkte in Blatt-mm): Die Ebene enthält die Linie und die
    Blickrichtung der Ansicht. Blickrichtung des Schnitts zur größeren Hälfte der Ansicht (der kleinere Teil vor der
    Ebene fällt weg); geht die Linie durch die Mitte, nach links der Zeichenrichtung. ``umkehren``: die andere Seite
    (in der App ⌥ beim Ziehen)."""
    if not isinstance(linie, (list, tuple)) or len(linie) != 2:
        raise OpFehler("schnitt.linie: zwei Punkte [[x, y], [x, y]] in Blatt-mm")
    a, b = _punkt(linie[0], "schnitt.linie"), _punkt(linie[1], "schnitt.linie")
    # die Linie beginnt und endet meist außerhalb des Teils: maßgeblich ist die Ansicht unter ihrer Mitte
    vid, v = _quell_ansicht(erg, von, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
    a2, b2 = blatt_zu_modell(v, a), blatt_zu_modell(v, b)
    d2 = b2 - a2
    if float(np.linalg.norm(d2)) < 1e-6:
        raise OpFehler("Schnittlinie zu kurz: zwei verschiedene Punkte ziehen")
    d2 = d2 / np.linalg.norm(d2)
    n2 = np.array([-d2[1], d2[0]])  # links der Zeichenrichtung
    x0, y0, x1, y1 = v.rahmen_m
    zur_mitte = np.array([(x0 + x1) / 2, (y0 + y1) / 2]) - a2
    seite = float(np.dot(zur_mitte, n2))
    if abs(seite) > 0.02 * max(x1 - x0, y1 - y0, 1.0) and seite < 0:
        n2 = -n2
    if umkehren:
        n2 = -n2
    rechts, oben = np.asarray(v.blick.rechts, dtype=float), np.asarray(v.blick.oben, dtype=float)
    punkt = a2[0] * rechts + a2[1] * oben
    normale = n2[0] * rechts + n2[1] * oben
    return {"von": vid, "ebene": {"punkt": [round(float(c), 4) for c in punkt],
                                  "normale": [round(float(c), 6) for c in normale]}}


EINZELHEIT_FAKTOREN = (2, 4, 5, 10)


def einzelheit_aus_kreis(erg: Any, von: Any, kreis: Any, faktor: Any = None) -> dict[str, Any]:
    """Einzelheit aus einem in der App aufgezogenen Kreis (``{"mitte": [x, y], "radius": r}`` in Blatt-mm): Mitte und
    Radius in Modell-mm der Ansicht; ohne ``faktor`` so, dass die Einzelheit etwa 60 mm groß wird (2, 4, 5 oder 10)."""
    if not isinstance(kreis, dict):
        raise OpFehler("einzelheit.kreis: {mitte: [x, y], radius} in Blatt-mm")
    m = _punkt(kreis.get("mitte"), "einzelheit.kreis.mitte")
    r = float(kreis.get("radius") or 0)
    if r < 1.0:
        raise OpFehler("Einzelheit: Kreis mit mindestens 1 mm Radius aufziehen")
    vid, v = _quell_ansicht(erg, von, m)
    if faktor is None:
        ziel = 60.0 / (2 * r)
        faktor = max([f for f in EINZELHEIT_FAKTOREN if f <= ziel] or [EINZELHEIT_FAKTOREN[0]])
    return {"von": vid, "mitte": [round(float(c), 4) for c in blatt_zu_modell(v, m)],
            "radius": round(r / v.s, 4), "faktor": faktor}


def _naechster_buchstabe(b: dict[str, Any]) -> str:
    benutzt = {str((a.get("schnitt") or a.get("einzelheit") or {}).get("name")) for a in b["ansichten"]}
    for ch in "ABCDEFGHJKLMNPRSTUVWXYZ":
        if ch not in benutzt:
            return ch
    return "Z"


def _ansicht_verschieben(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    a = _ansicht(b, op.get("id"))
    a["lage"] = _punkt(op.get("lage"), "lage")
    a["fest"] = True
    return {"id": a["id"]}


def _schnitt_umkehren(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    """Blickrichtung eines Schnitts umkehren: Normale der Ebene umdrehen (Pfeile am Schnittverlauf zeigen dann zur
    anderen Seite, die Schnittansicht zeigt die andere Hälfte)."""
    a = _ansicht(b, op.get("id"))
    ebene = ((a.get("schnitt") or {}).get("ebene") or {}) if a.get("art") == "schnitt" else {}
    n = ebene.get("normale")
    if not isinstance(n, (list, tuple)) or len(n) != 3:
        raise OpFehler(f"Ansicht {a.get('id')!r} ist kein Schnitt (nur Schnitte haben eine Blickrichtung)")
    ebene["normale"] = [(-float(c)) + 0.0 for c in n]
    a["schnitt"].pop("blick", None)  # eine feste Blickrichtung gehörte zur alten Seite
    return {"id": a["id"]}


def _ansicht_loeschen(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    a = _ansicht(b, op.get("id"))
    b["ansichten"] = [x for x in b["ansichten"] if x is not a]
    weg = [m for m in b["masse"] if m.get("ansicht") == a["id"]]
    b["masse"] = [m for m in b["masse"] if m.get("ansicht") != a["id"]]
    if b["auto"].get("ansichten") and not b["ansichten"]:
        b["auto"]["ansichten"] = False  # sonst plant Kev CAD die gelöschten Ansichten neu
    return {"id": a["id"], "masse_entfernt": len(weg)}


def _massstab(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    wert = op.get("wert")
    try:
        f = massstab_faktor(wert)
    except (ValueError, ZeroDivisionError) as exc:
        raise OpFehler(f"Maßstab {wert!r} nicht lesbar (z. B. \"1:2\", ISO 5455: {', '.join(MASSSTAEBE)})") from exc
    if f <= 0:
        raise OpFehler("Maßstab muss positiv sein")
    b["massstab"] = massstab_text(f)
    b["auto"]["massstab"] = False
    for a in b["ansichten"]:
        if not a.get("fest"):
            a["lage"] = None
    return {"wert": b["massstab"]}


def _format(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    fmt = str(op.get("wert") or "").upper()
    if fmt not in dok.FORMATE:
        raise OpFehler(f"Format {fmt!r} unbekannt ({', '.join(dok.FORMATE)})")
    vorher = (str(b.get("format") or fmt), str(b.get("ausrichtung") or "quer"))
    b["format"] = fmt
    if op.get("ausrichtung") in ("quer", "hoch"):
        b["ausrichtung"] = op["ausrichtung"]
    b["auto"]["format"] = False
    for a in b["ansichten"]:  # feste Lagen gelten im bisherigen Format: anteilig mitnehmen (der Zeichner klemmt sie)
        if a.get("fest") and a.get("lage"):
            a["lage"] = lage_umrechnen(a["lage"], vorher, (b["format"], b["ausrichtung"]))
    return {"wert": fmt, "ausrichtung": b["ausrichtung"]}


# ---------------------------------------------------------------------------------------------------------------------
# Notizen, Schriftfeld, Automatik
# ---------------------------------------------------------------------------------------------------------------------


def _notiz(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    text = str(op.get("text") or "").strip()
    if not text:
        raise OpFehler("notiz braucht text")
    lage = _punkt(op.get("lage") or [30.0, 30.0], "lage")
    zeiger = op.get("zeiger")
    if isinstance(zeiger, dict) and zeiger.get("punkt") is not None and erg is not None:
        vid = zeiger.get("ansicht") or _ansicht_unter(erg, _punkt(zeiger["punkt"], "zeiger.punkt"))
        if vid is not None:
            try:
                zeiger = {**klick(erg, vid, _punkt(zeiger["punkt"], "zeiger.punkt")), "ansicht": vid,
                          "punkt": zeiger["punkt"]}
            except OpFehler:
                zeiger = {"punkt": zeiger["punkt"]}
    nid = dok.naechste("n", {n.get("id") for n in b["notizen"]})
    b["notizen"].append({"id": nid, "text": text, "lage": lage, "zeiger": zeiger, "quelle": von})
    return {"id": nid}


def _notiz_loeschen(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    nid = op.get("id")
    if not any(n.get("id") == nid for n in b["notizen"]):
        raise OpFehler(f"Notiz {nid!r} gibt es nicht")
    b["notizen"] = [n for n in b["notizen"] if n.get("id") != nid]
    return {"id": nid}


def _schriftfeld(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    feld = str(op.get("feld") or "")
    if feld not in dok.SCHRIFTFELD:
        raise OpFehler(f"Feld {feld!r} unbekannt ({', '.join(dok.SCHRIFTFELD)})")
    b["schriftfeld"][feld] = op.get("wert")
    fest = b.setdefault("schriftfeld_fest", [])
    if feld not in fest:
        fest.append(feld)
    if feld == "benennung" and op.get("wert"):
        b["titel"] = str(op["wert"])
    return {"feld": feld}


def _auto(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    for k in ("ansichten", "masse"):
        if k in op and op[k] is not None:
            b["auto"][k] = bool(op[k])
            if k == "masse" and not op[k]:
                b["masse"] = [m for m in b["masse"] if m.get("quelle") != "auto" or m.get("fest")]
    if op.get("zuruecksetzen"):
        # alle Unterdrückungen aufheben und die automatischen Maße neu setzen lassen (Kevins und Agent-Maße bleiben)
        n = len(b["unterdrueckt"])
        b["unterdrueckt"] = []
        b["masse"] = [m for m in b["masse"] if m.get("quelle") != "auto"]
        if op.get("ansichten") is not False and b["auto"].get("ansichten"):
            b["ansichten"] = [a for a in b["ansichten"] if a.get("fest")]
        return {"auto": {k: b["auto"][k] for k in ("ansichten", "masse")}, "aufgehoben": n}
    return {"auto": {k: b["auto"][k] for k in ("ansichten", "masse")}}


def _unterdrueckung_aufheben(b: dict[str, Any], op: dict[str, Any], von: str, erg: Any) -> dict[str, Any]:
    i = op.get("index")
    if not isinstance(i, int) or not 0 <= i < len(b["unterdrueckt"]):
        raise OpFehler(f"index {i!r} ungültig (0 bis {len(b['unterdrueckt']) - 1})" if b["unterdrueckt"]
                       else "es gibt keine Unterdrückung")
    eintrag = b["unterdrueckt"].pop(i)
    return {"index": i, "art": eintrag.get("art")}

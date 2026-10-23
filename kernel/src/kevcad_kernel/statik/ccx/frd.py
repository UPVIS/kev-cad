"""Ergebnisse von CalculiX lesen: ``.frd`` (ASCII, Knotenwerte je Inkrement) und ``.dat`` (Beulfaktoren, Summen).

``.frd``: je Inkrement ein Kopf ``100CL`` mit der Schrittzeit, dann Blöcke (``DISP``, ``STRESS``, ``PE``,
``CONTACT``, ``CSTR`` …) mit Zeilen `` -1`` + Knotennummer (I10) + Werte (E12.5, ohne Trennzeichen). ``lies_frd``
liefert je Inkrement {"schritt", "zeit", "bloecke": {Name: (Knotennummern, Werte (n, k))}}.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _werte(zeile: str, start: int, breite: int = 12) -> list[float]:
    out = []
    i = start
    rest = zeile.rstrip("\n")
    while i + breite <= len(rest) + 0:
        s = rest[i:i + breite]
        if not s.strip():
            break
        out.append(float(s))
        i += breite
    if i < len(rest) and rest[i:].strip():
        out.append(float(rest[i:]))
    return out


def lies_frd(pfad: str, bloecke: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Alle Inkremente mit ihren Knotenblöcken (nur ``bloecke``, sonst alle): {"nr", "zeit" (Gesamtzeit; jeder
    Schritt dauert 1, Schritt k also bis k), "bloecke": {Name: (Knotennummern, Werte (n, k))}}."""
    inkremente: list[dict[str, Any]] = []
    aktuell: dict[str, Any] | None = None
    name: str | None = None
    knoten: list[int] = []
    werte: list[list[float]] = []
    lang = True
    with open(pfad, encoding="latin-1") as fh:
        for zeile in fh:
            kopf = zeile[:6]
            if kopf.strip().startswith("2C"):
                lang = zeile.rstrip().endswith("1") or len(zeile.rstrip()) > 40
                continue
            if zeile.startswith("  100C"):
                # "  100CL  107 1.100000000        4453                     0    7           1": Name (100 + Nr.),
                # Gesamtzeit, Knotenzahl, …, laufende Nummer des Inkrements; je Block eines Inkrements ein Kopf
                nr = int(zeile[7:12])
                if aktuell is None or aktuell["nr"] != nr:
                    aktuell = {"nr": nr, "zeit": float(zeile[12:24]), "bloecke": {}}
                    inkremente.append(aktuell)
                name = None
                continue
            if zeile.startswith(" -4"):
                name = zeile[3:13].strip()
                knoten, werte = [], []
                continue
            if zeile.startswith(" -5"):
                continue
            if zeile.startswith(" -1") and name is not None:
                if bloecke is None or name in bloecke:
                    b = 13 if lang else 8
                    knoten.append(int(zeile[3:b]))
                    werte.append(_werte(zeile, b))
                continue
            if zeile.startswith(" -2") and name is not None:  # Fortsetzung (mehr als 6 Werte)
                if bloecke is None or name in bloecke:
                    b = 13 if lang else 8
                    werte[-1].extend(_werte(zeile, b))
                continue
            if zeile.startswith(" -3") and name is not None:
                if aktuell is not None and (bloecke is None or name in bloecke) and knoten:
                    breite = max(len(w) for w in werte)
                    W = np.zeros((len(werte), breite))
                    for i, w in enumerate(werte):
                        W[i, :len(w)] = w
                    aktuell["bloecke"][name] = (np.asarray(knoten, dtype=np.int64), W)
                name = None
                continue
    return inkremente


def feld(ink: dict[str, Any], name: str, n: int, spalten: int | None = None) -> np.ndarray | None:
    """Block als dichtes Feld (n Knoten, Index = Knotennummer − 1); fehlende Knoten 0."""
    b = ink["bloecke"].get(name)
    if b is None:
        return None
    kn, W = b
    k = W.shape[1] if spalten is None else spalten
    out = np.zeros((n, k))
    ok = (kn >= 1) & (kn <= n)
    out[kn[ok] - 1, :min(k, W.shape[1])] = W[ok, :k]
    return out


def beulfaktoren(dat: str) -> list[float]:
    """Beulfaktoren aus der ``.dat`` (Abschnitt „B U C K L I N G   F A C T O R   O U T P U T“)."""
    out: list[float] = []
    an = False
    with open(dat, encoding="latin-1") as fh:
        for zeile in fh:
            if "B U C K L I N G" in zeile:
                an = True
                continue
            if an:
                t = zeile.split()
                if len(t) == 2:
                    try:
                        out.append(float(t[1]))
                        continue
                    except ValueError:
                        pass
                if out and not t:
                    break
    return out


def summen(dat: str, wort: str = "forces") -> list[np.ndarray]:
    """Summen (``TOTALS=ONLY``) aus der ``.dat`` je Ausgabe, etwa die Lagerkraft aller festen Knoten."""
    out: list[np.ndarray] = []
    an = False
    with open(dat, encoding="latin-1") as fh:
        for zeile in fh:
            if "total" in zeile and wort in zeile:
                an = True
                continue
            if an:
                t = zeile.split()
                if len(t) >= 3:
                    try:
                        out.append(np.array([float(x) for x in t[:3]]))
                    except ValueError:
                        pass
                    an = False
    return out

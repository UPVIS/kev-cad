"""Hausregeln (DOKUMENTE.md 1.1): Werte, für die die Normen keine Zahl vorgeben. Standard hier, Abweichungen je Projekt
in ``<projekt>/dokumente/hausregeln.json``. Sie werden nie als „ISO“ ausgewiesen.

```json
{"masslinienabstand": {"erste": 10.0, "weitere": 7.0}, "schraffurabstand": 2.5, "pfeil": {"winkel": 15, "laenge_faktor": 10},
 "schrift": {"familie": "osifont", "hoehe": 3.5}}
```

- Maßlinienabstand 10 mm zur Körperkante, 7 mm untereinander (DIN 406, Wikibooks; RECHERCHE-PHASE6.md 1.4).
- Pfeil gefüllt, Öffnungswinkel 15°, Länge 10 × d mit d = 0,25 mm (schmale Linie der Liniengruppe 0,5).
- Schrift osifont (ISO 3098 Typ B), Versalhöhe 3,5 mm.
"""

from __future__ import annotations

import contextvars
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHMAL = 0.25  # d der schmalen Linie (Liniengruppe 0,5)


@dataclass(frozen=True)
class Hausregeln:
    erste: float = 10.0
    weitere: float = 7.0
    schraffurabstand: float = 2.5
    pfeil_winkel: float = 15.0
    pfeil_faktor: float = 10.0
    schrift: str = "osifont"
    schrifthoehe: float = 3.5

    @property
    def pfeil_laenge(self) -> float:
        return self.pfeil_faktor * SCHMAL

    @property
    def pfeil_halbbreite(self) -> float:
        return self.pfeil_laenge * math.tan(math.radians(self.pfeil_winkel / 2))

    def als_dict(self) -> dict[str, Any]:
        return {"masslinienabstand": {"erste": self.erste, "weitere": self.weitere},
                "schraffurabstand": self.schraffurabstand,
                "pfeil": {"winkel": self.pfeil_winkel, "laenge_faktor": self.pfeil_faktor},
                "schrift": {"familie": self.schrift, "hoehe": self.schrifthoehe}}


STANDARD = Hausregeln()
_AKTIV: contextvars.ContextVar[Hausregeln] = contextvars.ContextVar("kevcad_hausregeln", default=STANDARD)


def aktiv() -> Hausregeln:
    return _AKTIV.get()


def setze(regeln: Hausregeln) -> contextvars.Token:
    return _AKTIV.set(regeln)


def zuruecksetzen(token: contextvars.Token) -> None:
    _AKTIV.reset(token)


def _zahl(v: Any, vorgabe: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return vorgabe
    return min(max(x, lo), hi)


def aus_dict(d: dict[str, Any] | None) -> Hausregeln:
    d = d or {}
    ml = d.get("masslinienabstand") or {}
    pf = d.get("pfeil") or {}
    sc = d.get("schrift") or {}
    return Hausregeln(
        erste=_zahl(ml.get("erste"), STANDARD.erste, 4, 30),
        weitere=_zahl(ml.get("weitere"), STANDARD.weitere, 4, 20),
        schraffurabstand=_zahl(d.get("schraffurabstand"), STANDARD.schraffurabstand, 0.7, 10),
        pfeil_winkel=_zahl(pf.get("winkel"), STANDARD.pfeil_winkel, 10, 90),
        pfeil_faktor=_zahl(pf.get("laenge_faktor"), STANDARD.pfeil_faktor, 5, 20),
        schrift=str(sc.get("familie") or STANDARD.schrift),
        schrifthoehe=_zahl(sc.get("hoehe"), STANDARD.schrifthoehe, 1.8, 7),
    )


def laden(projekt: str | Path | None) -> tuple[Hausregeln, str | None]:
    """Hausregeln des Projekts (Datei fehlt: Standard). Liefert (Regeln, Fehlermeldung oder None)."""
    if not projekt:
        return STANDARD, None
    p = Path(projekt) / "dokumente" / "hausregeln.json"
    if not p.exists():
        return STANDARD, None
    try:
        return aus_dict(json.loads(p.read_text(encoding="utf-8"))), None
    except (OSError, ValueError) as exc:
        return STANDARD, f"hausregeln.json nicht lesbar ({exc}); Standard gilt"

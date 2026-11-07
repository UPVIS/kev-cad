#!/usr/bin/env python3
"""Parität zwischen Kev CAD für Mac und für iPad prüfen (PLAN-IPAD.md, I3 und I-9).

Kev CAD hat eine gemeinsame Oberfläche (app/Sources/KevCAD) und einen gemeinsamen Kern (app/KevCADCore). Eigen je Gerät
ist nur die Hülle: app/Sources/KevCAD/Mac/ und app/Sources/KevCADPad/. Diese Prüfung meldet, wo die beiden Geräte
auseinanderlaufen können:

1. Hüllen-Dateien: Jede Datei in Mac/ hat ein Gegenstück in KevCADPad/ oder eine Ausnahme mit Grund in paritaet.json
   (`nur_mac`), umgekehrt ebenso (`nur_ipad`). Nach jedem Abgleich hält paritaet.lock.json die Prüfsummen fest. Ändert
   sich danach nur eine Seite eines Paars (oder eine Ausnahme-Datei), meldet die Prüfung das.
2. Mac-Stellen: Blöcke `#if os(macOS)` ohne `#else` im gemeinsamen Code, die nicht nur Importe enthalten und keinen
   Kommentar mit Grund tragen („nur am Mac“, „iPad: …“, Muster in paritaet.json), sind Stellen, an denen das iPad nichts
   bekommt. Der Bestand ist im Abgleich festgehalten; gemeldet werden neue und geänderte.
3. Marken „iPad: folgt in I-x“: offene Stellen nach Plan, je Paket gezählt. Eine Marke zu einem Paket, das in
   PLAN-IPAD.md als fertig gilt, ist veraltet und wird gemeldet.
4. Befehle ohne iPad-Auslöser: Sobald der Befehlskatalog (Tastenbelegung.swift) Auslöser je Gerät trägt, meldet die
   Prüfung jeden Befehl ohne Auslöser am iPad (bis dahin vorbereitet, siehe `befehlskatalog` in paritaet.json).

    python3 tools/paritaet.py                     Bericht (Ausgang 1, wenn etwas offen ist)
    python3 tools/paritaet.py --kurz              eine Zeile (für Bauskripte; Ausgang wie oben)
    python3 tools/paritaet.py --alle              Bericht mit dem ganzen Bestand an Mac-Stellen und allen Marken
    python3 tools/paritaet.py abgleichen PFAD …   nach dem Nachziehen bzw. Prüfen: Paare, Ausnahmen und Mac-Stellen
                                                  dieser Dateien als abgeglichen eintragen
    python3 tools/paritaet.py abgleichen --alle   alles eintragen (nur nach vollständiger Prüfung)
    python3 tools/paritaet.py liste               Hüllen-Dateien mit Gegenstück bzw. Grund

Regel dazu: CLAUDE.md „Mac und iPad (Parität)“; Vorbild ~/.claude/rules/app-paritaet-ios-android.md (Rotation).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

WURZEL = Path(os.environ.get("KEVCAD_PARITAET_WURZEL") or Path(__file__).resolve().parent.parent)
KARTE = WURZEL / "paritaet.json"
SPERRE = WURZEL / "paritaet.lock.json"

MARKE = re.compile(r"iPad:[^\n]*?folgt\s+in\s+(I-\d+[a-z]?)")
IF_MAC = re.compile(r"^\s*#if\s+os\(macOS\)\s*(//.*)?$")
IF_JEDES = re.compile(r"^\s*#if\b")
ELSE = re.compile(r"^\s*#(else|elseif)\b")
ENDIF = re.compile(r"^\s*#endif\b")
NUR_IMPORT = re.compile(r"^\s*(@preconcurrency\s+|@_exported\s+|@testable\s+)?import\s+\w+|^\s*$|^\s*//")


def lade_json(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}


def rel(p: Path) -> str:
    return p.relative_to(WURZEL).as_posix()


def dateien(muster: list[str], ohne: list[str] | None = None) -> list[str]:
    out: set[str] = set()
    for m in muster:
        for p in WURZEL.glob(m):
            if p.is_file() and "/.build/" not in str(p) and "/build/" not in rel(p):
                out.add(rel(p))
    for m in ohne or []:
        out -= {r for r in out if Path(r).match(m) or r.startswith(m.rstrip("*"))}
    return sorted(out)


def pruefsumme(pfad: str) -> str | None:
    p = WURZEL / pfad
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# MARK: Hüllen

def huellen(karte: dict) -> tuple[list[str], list[str]]:
    return dateien(karte["mac_huelle"]), dateien(karte["ipad_huelle"])


def gegenstueck(pfad: str, karte: dict) -> str | None:
    paare = karte.get("paare", {})
    if pfad in paare:
        return paare[pfad]
    for mac, ipad in paare.items():
        if ipad == pfad:
            return mac
    return None


# MARK: Mac-Stellen

@dataclass
class Stelle:
    datei: str
    zeile: int
    kennung: str  # Prüfsumme aus Datei und Inhalt des Blocks
    vorschau: str
    marke: str | None = None  # Paket aus „iPad: folgt in I-x“, wenn der Grund eine Marke ist


def mac_stellen(text: str, datei: str, begruendung: re.Pattern) -> tuple[list[Stelle], int]:
    """Blöcke `#if os(macOS)` ohne `#else`, nicht nur Importe, ohne Grund. Zweiter Wert: begründete Blöcke."""
    zeilen = text.splitlines()
    stapel: list[list] = []  # [start, ist_mac, hat_else]
    offen: list[Stelle] = []
    begruendet = 0
    for i, z in enumerate(zeilen):
        if IF_JEDES.match(z):
            stapel.append([i, bool(IF_MAC.match(z)), False])
        elif ELSE.match(z):
            if stapel:
                stapel[-1][2] = True
        elif ENDIF.match(z):
            if not stapel:
                continue
            start, ist_mac, hat_else = stapel.pop()
            if not ist_mac or hat_else:
                continue
            inhalt = zeilen[start + 1:i]
            if all(NUR_IMPORT.match(x) for x in inhalt):
                continue
            # Grund: Kommentar am #if, bis zu vier Kommentarzeilen darüber, die ersten zwei Zeilen im Block
            umfeld = [zeilen[start]] + inhalt[:2]
            j = start - 1
            while j >= 0 and start - j <= 4 and zeilen[j].strip().startswith("//"):
                umfeld.append(zeilen[j])
                j -= 1
            umfeld_text = " ".join(umfeld)
            m = MARKE.search(umfeld_text)
            if begruendung.search(umfeld_text) or m:
                begruendet += 1
                continue
            norm = "\n".join(x.strip() for x in inhalt if x.strip())
            kennung = hashlib.sha256(f"{datei}\n{norm}".encode()).hexdigest()[:16]
            vorschau = next((x.strip() for x in inhalt if x.strip() and not x.strip().startswith("//")), "")[:90]
            offen.append(Stelle(datei, start + 1, kennung, vorschau))
    return offen, begruendet


def alle_mac_stellen(karte: dict) -> tuple[dict[str, list[Stelle]], int]:
    muster = re.compile(karte["begruendung_muster"], re.IGNORECASE)
    out: dict[str, list[Stelle]] = {}
    begruendet = 0
    for d in dateien(karte["gemeinsam"], karte.get("gemeinsam_ohne")):
        offen, b = mac_stellen((WURZEL / d).read_text(encoding="utf-8", errors="replace"), d, muster)
        begruendet += b
        if offen:
            out[d] = offen
    return out, begruendet


# MARK: Marken

def fertige_pakete() -> set[str]:
    """Pakete, deren Stand in PLAN-IPAD.md mit „fertig“ beginnt."""
    plan = WURZEL / "PLAN-IPAD.md"
    if not plan.exists():
        return set()
    fertig = set()
    for z in plan.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(I-\d+[a-z]?)\b[^|]*\|.*\|\s*([^|]*)\|\s*$", z)
        if m and m.group(2).strip().lower().startswith("fertig"):
            fertig.add(m.group(1))
    return fertig


def marken(karte: dict) -> list[tuple[str, int, str]]:
    out = []
    for d in dateien(karte["marken_quellen"]):
        for n, z in enumerate((WURZEL / d).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in MARKE.finditer(z):
                out.append((d, n, m.group(1)))
    return out


# MARK: Befehlskatalog

def befehle_ohne_ipad(karte: dict) -> tuple[bool, list[str]]:
    """(aktiv, Befehle ohne iPad-Auslöser). Aktiv erst, wenn der Katalog ein Feld für den iPad-Auslöser kennt."""
    kat = karte.get("befehlskatalog") or {}
    p = WURZEL / kat.get("datei", "")
    if not kat or not p.is_file():
        return False, []
    text = p.read_text(encoding="utf-8")
    felder = kat.get("ipad_felder", [])
    eintrag = re.compile(kat["eintrag"])
    treffer = list(eintrag.finditer(text))
    stuecke = []
    for k, t in enumerate(treffer):
        ende = treffer[k + 1].start() if k + 1 < len(treffer) else len(text)
        stueck = text[t.start():ende]
        schluss = re.search(r"\n\s*\]", stueck)  # Ende der Liste: nichts dahinter zählt zum Eintrag
        stuecke.append((t.group(1), stueck[:schluss.start()] if schluss else stueck))
    if not any(f in s for _, s in stuecke for f in felder):
        return False, []
    # I-4: Auslöser außerhalb der Einträge, etwa die Felder des Werkzeugkranzes (`.befehl(.vorne, …)`): Muster mit dem
    # Befehl als erster Gruppe, gesucht in der ganzen Datei
    weitere = {m.group(1) for muster in kat.get("weitere", []) for m in re.finditer(muster, text)}
    fehlt = [b for b, s in stuecke
             if not any(f in s for f in felder) and b not in weitere and b not in kat.get("nur_mac", {})]
    return True, fehlt


# MARK: Bericht

@dataclass
class Befund:
    ohne_zuordnung: list[str] = field(default_factory=list)
    fehlt: list[tuple[str, str]] = field(default_factory=list)
    nur_eine_seite: list[tuple[str, str, str]] = field(default_factory=list)  # (geändert, Gegenstück, Seite)
    beide: list[tuple[str, str]] = field(default_factory=list)
    ausnahme_geaendert: list[tuple[str, str]] = field(default_factory=list)
    nie: list[str] = field(default_factory=list)
    neue_stellen: list[Stelle] = field(default_factory=list)
    bestand: int = 0
    begruendet: int = 0
    marken: list[tuple[str, int, str]] = field(default_factory=list)
    veraltet: list[tuple[str, int, str]] = field(default_factory=list)
    katalog_aktiv: bool = False
    befehle: list[str] = field(default_factory=list)

    @property
    def offen(self) -> int:
        return (len(self.ohne_zuordnung) + len(self.fehlt) + len(self.nur_eine_seite) + len(self.beide)
                + len(self.ausnahme_geaendert) + len(self.neue_stellen) + len(self.veraltet) + len(self.befehle))


def pruefen() -> Befund:
    karte = lade_json(KARTE)
    sperre = lade_json(SPERRE)
    huellen_sperre = sperre.get("huellen", {})
    b = Befund()
    mac, ipad = huellen(karte)
    nur_mac, nur_ipad = karte.get("nur_mac", {}), karte.get("nur_ipad", {})
    paare = karte.get("paare", {})
    for d in mac + ipad:
        seite = "mac" if d in mac else "ipad"
        if d in nur_mac or d in nur_ipad:
            alt = huellen_sperre.get(d)
            if alt is None:
                b.nie.append(d)
            elif alt.get("summe") != pruefsumme(d):
                b.ausnahme_geaendert.append((d, (nur_mac | nur_ipad)[d]))
            continue
        gs = gegenstueck(d, karte)
        if gs is None:
            b.ohne_zuordnung.append(d)
            continue
        if seite == "ipad":
            continue  # Paare zählen einmal, von der Mac-Seite aus
        if not (WURZEL / gs).exists():
            b.fehlt.append((d, gs))
            continue
        alt = huellen_sperre.get(d)
        if alt is None or alt.get("gegenstueck") != gs:
            b.nie.append(d)
            continue
        m_neu, i_neu = alt.get("summe") != pruefsumme(d), alt.get("gegenstueck_summe") != pruefsumme(gs)
        if m_neu and i_neu:
            b.beide.append((d, gs))
        elif m_neu:
            b.nur_eine_seite.append((d, gs, "Mac"))
        elif i_neu:
            b.nur_eine_seite.append((gs, d, "iPad"))
    for d, gs in paare.items():
        if d not in mac and (WURZEL / gs).exists():
            b.fehlt.append((gs, d))

    stellen, b.begruendet = alle_mac_stellen(karte)
    bekannt = sperre.get("mac_stellen", {})
    for d, liste in stellen.items():
        alte = set(bekannt.get(d, []))
        for s in liste:
            if s.kennung in alte:
                b.bestand += 1
            else:
                b.neue_stellen.append(s)

    fertig = fertige_pakete()
    b.marken = marken(karte)
    b.veraltet = [m for m in b.marken if m[2] in fertig]
    b.katalog_aktiv, b.befehle = befehle_ohne_ipad(karte)
    return b


def marken_je_paket(liste: list[tuple[str, int, str]]) -> str:
    zaehler: dict[str, int] = {}
    for _, _, p in liste:
        zaehler[p] = zaehler.get(p, 0) + 1
    return ", ".join(f"{p}: {n}" for p, n in sorted(zaehler.items(), key=lambda x: (len(x[0]), x[0])))


def bericht(kurz: bool = False, alle: bool = False) -> int:
    b = pruefen()
    if kurz:
        teile = []
        if b.ohne_zuordnung:
            teile.append(f"{len(b.ohne_zuordnung)} Hüllen-Dateien ohne Zuordnung")
        if b.fehlt:
            teile.append(f"{len(b.fehlt)} Gegenstücke fehlen")
        if b.nur_eine_seite or b.beide:
            teile.append(f"{len(b.nur_eine_seite) + len(b.beide)} Hüllen nur einseitig bzw. beidseitig geändert")
        if b.ausnahme_geaendert:
            teile.append(f"{len(b.ausnahme_geaendert)} Ausnahmen geändert")
        if b.neue_stellen:
            teile.append(f"{len(b.neue_stellen)} neue Mac-Stellen ohne Grund")
        if b.veraltet:
            teile.append(f"{len(b.veraltet)} veraltete Marken")
        if b.befehle:
            teile.append(f"{len(b.befehle)} Befehle ohne iPad-Auslöser")
        if b.nie:
            teile.append(f"{len(b.nie)} nie abgeglichen")
        marken_text = f"; Marken „iPad: folgt“ {len(b.marken)} ({marken_je_paket(b.marken)})" if b.marken else ""
        if teile:
            print(f"[Parität] offen: {', '.join(teile)}{marken_text}. Bericht: python3 tools/paritaet.py")
        else:
            print(f"[Parität] Mac und iPad abgeglichen{marken_text}.")
        return 1 if b.offen else 0

    def liste(titel: str, eintraege, fmt):
        if eintraege:
            print(f"\n## {titel} ({len(eintraege)})")
            for e in eintraege:
                print("  " + fmt(e))

    print(f"Parität Mac/iPad in {WURZEL}")
    liste("Hüllen-Datei ohne Zuordnung (Gegenstück anlegen oder in paritaet.json eintragen)", b.ohne_zuordnung,
          lambda e: e)
    liste("Gegenstück fehlt", b.fehlt, lambda e: f"{e[0]}  ->  {e[1]}")
    liste("Nur eine Seite geändert, Gegenstück nachziehen", b.nur_eine_seite,
          lambda e: f"{e[2]}: {e[0]}  ->  {e[1]}")
    liste("Beide Seiten geändert, gegeneinander prüfen", b.beide, lambda e: f"{e[0]}  <->  {e[1]}")
    liste("Ausnahme geändert (gilt der Grund noch? braucht das andere Gerät einen Weg?)", b.ausnahme_geaendert,
          lambda e: f"{e[0]}  ({e[1]})")
    liste("Neue Mac-Stelle ohne iPad-Zweig und ohne Grund (#else ergänzen oder Grund als Kommentar)", b.neue_stellen,
          lambda s: f"{s.datei}:{s.zeile}  {s.vorschau}")
    liste("Marke zu einem fertigen Paket (veraltet: umsetzen oder Paket in der Marke korrigieren)", b.veraltet,
          lambda e: f"{e[0]}:{e[1]}  ({e[2]})")
    if b.katalog_aktiv:
        liste("Befehle ohne Auslöser am iPad", b.befehle, lambda e: e)
    liste("Noch nie abgeglichen", b.nie, lambda e: e)
    print(f"\nMac-Stellen: {b.begruendet} begründet, {b.bestand} im abgeglichenen Bestand"
          + ("" if alle else " (Liste: --alle)"))
    if alle:
        bekannt = lade_json(SPERRE).get("mac_stellen", {})
        stellen, _ = alle_mac_stellen(lade_json(KARTE))
        for d, l in stellen.items():
            for s in l:
                if s.kennung in set(bekannt.get(d, [])):
                    print(f"  {s.datei}:{s.zeile}  {s.vorschau}")
    if b.marken:
        print(f"Marken „iPad: folgt in I-x“: {len(b.marken)} ({marken_je_paket(b.marken)})"
              + ("" if alle else " (Liste: --alle)"))
        if alle:
            for d, n, p in b.marken:
                print(f"  {p}  {d}:{n}")
    if not b.katalog_aktiv:
        print("Befehlskatalog: noch ohne Auslöser je Gerät (I-4), Prüfung vorbereitet.")
    if b.offen or b.nie:
        print("\nNach dem Nachziehen bzw. Prüfen: python3 tools/paritaet.py abgleichen <Pfad> …")
    else:
        print("\nAlles abgeglichen.")
    return 1 if b.offen else 0


def abgleichen(pfade: list[str], alle: bool) -> int:
    karte = lade_json(KARTE)
    sperre = lade_json(SPERRE)
    huellen_sperre = sperre.setdefault("huellen", {})
    stellen_sperre = sperre.setdefault("mac_stellen", {})
    mac, ipad = huellen(karte)
    ausnahmen = set(karte.get("nur_mac", {})) | set(karte.get("nur_ipad", {}))
    stellen, _ = alle_mac_stellen(karte)
    gemeinsam = set(dateien(karte["gemeinsam"], karte.get("gemeinsam_ohne")))

    gewaehlt: set[str] = set()
    if alle:
        gewaehlt = set(mac) | set(ipad) | gemeinsam
    for p in pfade:
        pp = Path(p)
        r = pp.resolve().relative_to(WURZEL.resolve()).as_posix() if pp.is_absolute() else pp.as_posix()
        if not (WURZEL / r).exists():
            print(f"Gibt es nicht: {p}")
            continue
        gewaehlt.add(r)
        gs = gegenstueck(r, karte)
        if gs:
            gewaehlt.add(gs)
    for d in sorted(gewaehlt):
        if d in ausnahmen:
            huellen_sperre[d] = {"summe": pruefsumme(d)}
            print(f"abgeglichen (Ausnahme): {d}")
        elif d in mac:
            gs = gegenstueck(d, karte)
            if gs and (WURZEL / gs).exists():
                huellen_sperre[d] = {"summe": pruefsumme(d), "gegenstueck": gs, "gegenstueck_summe": pruefsumme(gs)}
                print(f"abgeglichen: {d}  <->  {gs}")
        if d in gemeinsam:
            neu = sorted(s.kennung for s in stellen.get(d, []))
            if neu:
                if set(neu) != set(stellen_sperre.get(d, [])):
                    print(f"Mac-Stellen eingetragen: {d} ({len(neu)})")
                stellen_sperre[d] = neu
            else:
                stellen_sperre.pop(d, None)
    # Einträge zu verschwundenen Dateien entfernen
    for tabelle in (huellen_sperre, stellen_sperre):
        for d in [d for d in tabelle if not (WURZEL / d).exists()]:
            del tabelle[d]
    SPERRE.write_text(json.dumps(sperre, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def zeige_liste() -> int:
    karte = lade_json(KARTE)
    mac, ipad = huellen(karte)
    for d in mac + ipad:
        grund = karte.get("nur_mac", {}).get(d) or karte.get("nur_ipad", {}).get(d)
        if grund:
            print(f"nur {'Mac ' if d in mac else 'iPad'}  {d}  ({grund})")
        else:
            gs = gegenstueck(d, karte)
            print(f"Paar      {d}  <->  {gs or '–'}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["abgleichen"]:
        sys.exit(abgleichen([a for a in args[1:] if a != "--alle"], "--alle" in args))
    if args[:1] == ["liste"]:
        sys.exit(zeige_liste())
    sys.exit(bericht(kurz="--kurz" in args, alle="--alle" in args))

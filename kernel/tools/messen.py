"""Misst Läufe eines Kev-CAD-Projekts, wie Kevin sie erlebt: Laufzeit mit Rechenprozess und einer App-Attrappe am
Socket, Zeitstempel je Rahmen. Arbeitet immer auf einer Kopie (Projekt und eigener Katalog in einem Temp-Ordner unter
/tmp); Kevins Projekt, Katalog, Druck-Zwischenspeicher und Filamentliste werden nicht angefasst.

Aufruf (aus dem Repo, mit der Umgebung des Kernels):

    kernel/.venv/bin/python -u kernel/tools/messen.py "$HOME/Documents/Kev CAD/Kugelschieber Variante B"
    ... --laeufe kalt,gleich,kommentar,param:breite=140,ersetze:120=125   (Vorgabe: kalt,gleich,kommentar)
    ... --ohne-gedaechtnis      Rechengedächtnis aus (KEVCAD_GEDAECHTNIS=0), zum Vergleich
    ... --warten-s 3            an run weitergeben (wie lange run höchstens auf die Prüfung wartet)
    ... --profil                statt der Laufzeit: Runner.run im Prozess, kalt, warm, warm mit Abtastung
    ... --json datei.json       alle Ergebnisse (Zeiten, zeiten_ms, Rahmen) als JSON

Läufe: ``kalt`` (erster Lauf nach dem Start), ``gleich`` (ohne Änderung), ``kommentar`` (Kommentar am Ende von
model.py), ``param:NAME=WERT`` (run mit params), ``ersetze:ALT=NEU`` (erste Fundstelle in model.py ersetzen).

Nach jedem Lauf wartet das Werkzeug auf das Prüfergebnis und bis die Laufzeit nichts mehr zu tun hat, damit sich die
Läufe nicht überlagern. Spalten: Teile im Viewer (erstes bis letztes PART_UPSERT), RUN_END, Rückkehr von ``run``,
Prüfung fertig (CHECK mit Ergebnis), alles in Sekunden ab dem Aufruf von ``run``.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

KATALOG = Path.home() / "Library/Application Support/de.upvis.kevcad/katalog"
MCP_PORT = 47996  # nur die Zahl in HELLO; nie 47823/47824 (Kevins App)
IGNORIEREN = shutil.ignore_patterns(".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp",
                                    "*.stl", "__pycache__", ".DS_Store")


def kopieren(projekt: Path, katalog: Path | None) -> tuple[Path, Path]:
    """Projekt und Katalog in einen neuen Temp-Ordner kopieren; Umgebung so setzen, dass nichts von Kevin geschrieben
    wird (wie tests/conftest.py)."""
    arbeit = Path(tempfile.mkdtemp(prefix="kcmessen-", dir="/tmp"))
    eigen = arbeit / "katalog"
    if katalog is not None and katalog.is_dir():
        shutil.copytree(katalog, eigen)
    else:
        eigen.mkdir()
    kopie = arbeit / projekt.name
    shutil.copytree(projekt, kopie, ignore=IGNORIEREN)
    os.environ["KEVCAD_CATALOG_DIR"] = str(eigen)
    druck = arbeit / "druck"
    os.environ.setdefault("KEVCAD_DRUCK_CACHE", str(druck / "cache"))
    os.environ.setdefault("KEVCAD_DRUCK_ABGLEICH", str(druck / "abgleich.json"))
    os.environ.setdefault("KEVCAD_BAMBU_APP", str(druck / "kein-bambu-studio.app"))  # kein Slicen nebenbei
    os.environ.setdefault("KEVCAD_FESTKOERPER_CACHE", str(druck / "festkoerper"))
    os.environ.setdefault("KEVCAD_FILAMENTE", str(druck / "filamente.json"))
    return arbeit, kopie


class AppAttrappe:
    """Minimale App am Socket: sammelt Rahmen mit Empfangszeit und beantwortet Anfragen, auf die die Laufzeit wartet
    (Ansicht, Bild, Vorschaubild der Versionen)."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    def __init__(self, pfad: str) -> None:
        from kevcad_kernel.protocol import encode_frame

        self._encode = encode_frame
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(pfad)
        self.frames: list[tuple[float, dict, int]] = []  # (Zeit, Kopf, Größe der Nutzlast)
        self.cond = threading.Condition()
        self.seq = 0
        self._send_lock = threading.Lock()
        threading.Thread(target=self._lesen, daemon=True).start()
        self.senden({"type": "HELLO_APP", "app_version": "messen", "bundle_id": "de.upvis.kevcad.messen"})

    def senden(self, kopf: dict, nutz: bytes = b"") -> None:
        with self._send_lock:
            self.seq += 1
            self.sock.sendall(self._encode({**kopf, "seq": self.seq}, nutz))

    def _lesen(self) -> None:
        from kevcad_kernel.protocol import FrameReader

        leser = FrameReader()
        while True:
            try:
                data = self.sock.recv(1 << 20)
            except OSError:
                break
            if not data:
                break
            for h, p in leser.feed(data):
                with self.cond:
                    self.frames.append((time.perf_counter(), h, len(p)))
                    self.cond.notify_all()
                art = h.get("type")
                if art == "VIEW_CMD":
                    self.senden({"type": "ACK", "reply_to": h["id"], "ok": True})
                elif art in ("SCREENSHOT_REQ", "VERSION_BILD_REQ"):
                    self.senden({"type": "SCREENSHOT_RES", "reply_to": h["id"], "ok": True,
                                 "width": h.get("width", 1), "height": h.get("height", 1), "camera": {},
                                 "mm_per_px": None}, self.PNG)

    def marke(self) -> int:
        with self.cond:
            return len(self.frames)

    def warte(self, pred, timeout: float, start: int = 0) -> tuple[float, dict] | None:
        ende = time.monotonic() + timeout
        with self.cond:
            while True:
                for t, h, _ in self.frames[start:]:
                    if pred(h):
                        return t, h
                rest = ende - time.monotonic()
                if rest <= 0:
                    return None
                self.cond.wait(min(rest, 0.5))

    def seit(self, start: int) -> list[tuple[float, dict, int]]:
        with self.cond:
            return list(self.frames[start:])

    def schliessen(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _s(x: float | None) -> str:
    return "–" if x is None else f"{x:.2f}"


def lauf_messen(rt, app: AppAttrappe, kopie: Path, art: str, args) -> dict:
    """Einen Lauf auslösen und auswerten."""
    params = None
    if art.startswith("param:"):
        name, _, wert = art[len("param:"):].partition("=")
        params = {name: float(wert)}
    elif art.startswith("ersetze:"):
        alt, _, neu = art[len("ersetze:"):].partition("=")
        m = kopie / "model.py"
        text = m.read_text(encoding="utf-8")
        if alt not in text:
            raise SystemExit(f"ersetze: {alt!r} kommt in model.py nicht vor")
        m.write_text(text.replace(alt, neu, 1), encoding="utf-8")
    elif art == "kommentar":
        m = kopie / "model.py"
        m.write_text(m.read_text(encoding="utf-8") + f"\n# Messung: kleine Änderung {time.time():.0f}\n",
                     encoding="utf-8")
    elif art not in ("kalt", "gleich"):
        raise SystemExit(f"Lauf {art!r} unbekannt")
    extra = {}
    if args.warten_s is not None:
        extra["warten_s"] = args.warten_s
    start = app.marke()
    t0 = time.perf_counter()
    res = rt.run(params=params, timeout_s=args.timeout_s, **extra)
    t_zurueck = time.perf_counter() - t0
    run = res.get("run")
    # Prüfergebnis dieses Laufs abwarten (es darf nach der Rückkehr von run kommen)
    ergebnis = app.warte(lambda h: h.get("type") == "CHECK" and h.get("run") == run
                         and h.get("state") in ("done", "failed", "teilweise"), args.pruef_max_s, start)
    endstand = None
    if ergebnis is not None and ergebnis[1].get("state") == "teilweise":
        endstand = app.warte(lambda h: h.get("type") == "CHECK" and h.get("run") == run
                             and h.get("state") in ("done", "failed"), args.pruef_max_s, start)
    rt.wait_idle(120)
    time.sleep(args.pause_s)
    frames = app.seit(start)
    arten: dict[str, list] = {}
    for t, h, n in frames:
        e = arten.setdefault(h.get("type"), [0, 0, None, None])
        e[0] += 1
        e[1] += n
        e[2] = t - t0 if e[2] is None else e[2]
        e[3] = t - t0
    teile = arten.get("PART_UPSERT")
    run_end = arten.get("RUN_END")
    out = {
        "lauf": art, "run": run, "ok": res.get("ok"),
        "teile": len(res.get("parts") or []),
        "teile_erst_s": teile[2] if teile else None, "teile_letzt_s": teile[3] if teile else None,
        "run_end_s": run_end[2] if run_end else None,
        "zurueck_s": t_zurueck,
        "pruefung_s": (ergebnis[0] - t0) if ergebnis else None,
        "pruefung_state": ergebnis[1].get("state") if ergebnis else None,
        "pruefung_endstand_s": (endstand[0] - t0) if endstand else None,
        "pruefung_im_ergebnis": (res.get("pruefung") or {}).get("state"),
        "zeiten_ms": res.get("zeiten_ms"),
        "rahmen": {k: {"anzahl": v[0], "mb": round(v[1] / 1e6, 3), "erster_s": round(v[2], 3),
                       "letzter_s": round(v[3], 3)} for k, v in arten.items()},
        "fehler": (res.get("error") or {}).get("message") if not res.get("ok") else None,
    }
    return out


def tabelle(ergebnisse: list[dict]) -> str:
    zeilen = ["| Lauf | Teile im Viewer | RUN_END | `run()` kehrt zurück | Prüfung fertig |",
              "|---|---|---|---|---|"]
    for e in ergebnisse:
        teile = f"{_s(e['teile_erst_s'])} bis {_s(e['teile_letzt_s'])} s" if e["teile_erst_s"] is not None else "–"
        pr = f"{_s(e['pruefung_s'])} s ({e['pruefung_state']})" if e["pruefung_s"] is not None else "–"
        if e.get("pruefung_endstand_s") is not None:
            pr += f", Endstand {_s(e['pruefung_endstand_s'])} s"
        zeilen.append(f"| {e['lauf']} | {teile} | {_s(e['run_end_s'])} s | {_s(e['zurueck_s'])} s | {pr} |")
    return "\n".join(zeilen)


PHASEN = ("skript", "katalog", "module", "modell", "tessellierung", "serialisierung", "senden", "animation", "bom",
          "kameras", "bedingungen", "erstes_teil", "letztes_teil", "run_end", "kern", "nachlauf", "zurueck",
          "pruefung")


def phasen(ergebnisse: list[dict]) -> str:
    zeilen = []
    for e in ergebnisse:
        z = e.get("zeiten_ms") or {}
        if not z:
            continue
        teile = [f"{k} {z[k]:.0f}" for k in PHASEN if isinstance(z.get(k), (int, float))]
        gd = z.get("gedaechtnis")
        if isinstance(gd, dict):
            teile.append("Gedächtnis " + ", ".join(f"{k} {v}" for k, v in gd.items()))
        zeilen.append(f"  {e['lauf']}: " + ", ".join(teile))
    return "zeiten_ms (Dauer bzw. Zeitpunkt ab Start des Laufs):\n" + "\n".join(zeilen) if zeilen else ""


def messen(args) -> int:
    projekt = Path(args.projekt).expanduser().resolve()
    if not (projekt / "model.py").is_file():
        raise SystemExit(f"{projekt}: kein Kev-CAD-Projekt (model.py fehlt)")
    if args.ohne_gedaechtnis:
        os.environ["KEVCAD_GEDAECHTNIS"] = "0"
    arbeit, kopie = kopieren(projekt, Path(args.katalog).expanduser() if args.katalog else KATALOG)
    if args.profil:
        try:
            return profil(kopie, arbeit / "katalog", args)
        finally:
            if not args.behalten:
                shutil.rmtree(arbeit, ignore_errors=True)
    from kevcad_kernel.runtime import KernelRuntime

    log = (lambda line: None) if not args.log else None
    t0 = time.perf_counter()
    rt = KernelRuntime(str(arbeit / "k.sock"), MCP_PORT, auto_run=False, run_timeout_s=900, log=log)
    ergebnisse: list[dict] = []
    app = None
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        print(f"Rechenprozess bereit nach {time.perf_counter() - t0:.1f} s", flush=True)
        app = AppAttrappe(str(arbeit / "k.sock"))
        app.warte(lambda h: h.get("type") == "HELLO", 10)
        res = rt.project_open(str(kopie))
        if not res.get("ok"):
            raise SystemExit(f"Projekt nicht geöffnet: {res}")
        rt.wait_idle(60)
        time.sleep(1.0)
        for art in [a.strip() for a in args.laeufe.split(",") if a.strip()]:
            e = lauf_messen(rt, app, kopie, art, args)
            ergebnisse.append(e)
            rahmen = ", ".join(f"{k} {v['anzahl']}× {v['mb']:.2f} MB" for k, v in e["rahmen"].items()
                               if v["mb"] >= 0.05)
            print(f"{art}: Lauf {e['run']} ok={e['ok']} {e['teile']} Teile, zurück nach {e['zurueck_s']:.2f} s, "
                  f"Prüfung {e['pruefung_state']} nach {_s(e['pruefung_s'])} s; Rahmen: {rahmen}"
                  + (f"; Fehler: {e['fehler']}" if e["fehler"] else ""), flush=True)
    finally:
        if app is not None:
            app.schliessen()
        rt.close()
        if not args.behalten:
            shutil.rmtree(arbeit, ignore_errors=True)
        else:
            print(f"Arbeitsordner: {arbeit}")
    print()
    print(tabelle(ergebnisse))
    text = phasen(ergebnisse)
    if text:
        print()
        print(text)
    if args.json:
        Path(args.json).write_text(json.dumps({"projekt": str(projekt), "laeufe": ergebnisse,
                                               "gedaechtnis": not args.ohne_gedaechtnis}, ensure_ascii=False,
                                              indent=1), encoding="utf-8")
    return 0


def profil(kopie: Path, katalog: Path, args) -> int:
    """Runner.run im Prozess ohne Laufzeit und App: kalt, warm und warm mit Abtastung des Hauptfadens (alle 1 ms der
    ganze Stapel; inklusive Zeit je Funktion, dazu die oberste Python-Funktion)."""
    import build123d  # noqa: F401 - Import nicht mitmessen

    from kevcad_kernel.runner import Runner

    try:  # wie im Rechenprozess (worker.py); aus mit --ohne-gedaechtnis
        from kevcad_kernel import gedaechtnis

        print(f"Rechengedächtnis: {'an' if gedaechtnis.installieren() else 'aus'}")
    except ImportError:  # ältere Kernel-Fassung
        pass
    r = Runner(lambda h, p=b"": None)
    msg = {"run": 1, "path": str(kopie / "model.py"), "catalog": {"own": str(katalog)}, "inventar_regel": True}
    t = time.perf_counter()
    res = r.run(msg)
    print(f"kalt: {time.perf_counter() - t:.2f} s ({res['type']}, {len(res['shown'])} Teile)")
    if res["type"] != "RUN_DONE":
        print((res.get("error") or {}).get("message"))
    for _ in range(max(0, args.warm - 1)):
        msg["run"] += 1
        t = time.perf_counter()
        r.run(msg)
        print(f"warm: {time.perf_counter() - t:.2f} s")
    haupt = threading.main_thread().ident
    inklusive: collections.Counter = collections.Counter()
    exklusiv: collections.Counter = collections.Counter()
    stopp = threading.Event()
    n = [0]

    def name(f) -> str:
        fn = f.f_code.co_filename
        kurz = (fn.split("site-packages/")[-1] if "site-packages/" in fn else fn.split("/src/")[-1] if "/src/" in fn
                else Path(fn).name)
        return f"{kurz}:{f.f_code.co_name}"

    def abtasten() -> None:
        while not stopp.is_set():
            f = sys._current_frames().get(haupt)
            if f is not None:
                n[0] += 1
                exklusiv[name(f)] += 1
                gesehen = set()
                while f is not None:
                    k = name(f)
                    if k not in gesehen:
                        gesehen.add(k)
                        inklusive[k] += 1
                    f = f.f_back
            time.sleep(0.001)

    th = threading.Thread(target=abtasten, daemon=True)
    msg["run"] += 1
    th.start()
    t = time.perf_counter()
    res = r.run(msg)
    dt = time.perf_counter() - t
    stopp.set()
    th.join()
    gesamt = max(1, n[0])
    print(f"warm mit Abtastung: {dt:.2f} s, {gesamt} Proben; zeiten_ms {json.dumps(res.get('zeiten_ms'))}")
    print("inklusive (Anteil der Proben, in denen die Funktion auf dem Stapel lag):")
    for k, c in inklusive.most_common(args.top):
        print(f"  {100 * c / gesamt:5.1f} %  {k}")
    print("exklusiv (oberste Python-Funktion; OCP-Aufrufe zählen zur aufrufenden Funktion):")
    for k, c in exklusiv.most_common(25):
        print(f"  {100 * c / gesamt:5.1f} %  {k}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("projekt", help="Projektordner (wird kopiert, nie verändert)")
    ap.add_argument("--laeufe", default="kalt,gleich,kommentar", help="Läufe, durch Komma getrennt")
    ap.add_argument("--katalog", default=None, help=f"eigener Katalog (Vorgabe: {KATALOG}, wird kopiert)")
    ap.add_argument("--ohne-gedaechtnis", action="store_true", help="Rechengedächtnis aus (KEVCAD_GEDAECHTNIS=0)")
    ap.add_argument("--warten-s", type=float, default=None, help="an run weitergeben (Prüfung höchstens so lange)")
    ap.add_argument("--timeout-s", type=float, default=900.0, help="Zeitlimit je Lauf")
    ap.add_argument("--pruef-max-s", type=float, default=600.0, help="so lange höchstens auf die Prüfung warten")
    ap.add_argument("--pause-s", type=float, default=1.0, help="Pause nach jedem Lauf")
    ap.add_argument("--profil", action="store_true", help="Runner.run im Prozess mit Abtastung statt der Laufzeit")
    ap.add_argument("--warm", type=int, default=2, help="--profil: so viele Läufe vor dem abgetasteten")
    ap.add_argument("--top", type=int, default=60, help="--profil: so viele Zeilen inklusive")
    ap.add_argument("--json", default=None, help="Ergebnisse zusätzlich als JSON-Datei")
    ap.add_argument("--log", action="store_true", help="Meldungen der Laufzeit auf stderr")
    ap.add_argument("--behalten", action="store_true", help="Arbeitsordner nicht löschen")
    return messen(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

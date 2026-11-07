"""Prüfzeit nach einer Änderung und Gleichheitsprobe (PLAN-PRUEFUNG-INKREMENTELL.md, Schritt A0).

Anlass: Beim Kugelschieber (t7) wartete der Agent 30 bis 48 s auf ``pruefen()``, der Lauf selbst brauchte 5 bis 7 s.
Ohne Sprachmodell und ohne App, an einer Kopie von Kevins Projekt:

    kernel/.venv/bin/python -u benchmark/pruefzeit.py [--kernel-src …] [--schritte "kalt;laufrolle_l=90;…"]
        [--probe] [--ablage <ordner>] [--netze-von <ablage>] [--vergleich <pruefzeit.json>]

Je Schritt: Lauf (``run(params=…)``) und Prüfung bis zum Endstand (``pruefen(endstand=True)``), Systemlast und freier
Speicher, dazu die **Zeitleiste** ab Beginn des Laufs: Ankunft jedes CHECK aus dem Rechenprozess (Zustand, offene
Prüfungen, ob Statik oder FEM-Auftrag dabei ist), FEM-Auftrag (EXEC), FEM-Prozess und je Teil Beginn und Ende, Endstand.

**Gleichheitsprobe** (``--probe``): Nach jedem Schritt rechnet ein frischer Kernel in einem eigenen Prozess (leere
Speicher) denselben Stand (Kopie des Projekts vor dem Schritt) mit denselben Parametern bis zum Endstand. Er teilt nur
die FEM-Netze (Gmsh vernetzt nicht reproduzierbar, Plan Abschnitt 4.1); „gleich wie volle Neuberechnung“ heißt für die
FEM: gleich bei denselben Netzen. Verglichen wird mit ``pruefzeit_analyse/gleichheit.py``: Befunde, Schnittkörper,
Montage, Stand, Druck, Bedingungen, Statik je Szenario samt Festkörper je Teil, Felder der FEM. Ungleich: Ausgang 1.

Vergleich zweier Stände des Kernels: ``--netze-von <ablage>`` übernimmt die FEM-Netze eines früheren Aufrufs (dann
rechnen beide mit denselben Netzen), ``--vergleich <pruefzeit.json>`` vergleicht die Endstände Schritt für Schritt mit
ihm. ``--kernel-src @<ref>:kernel/src`` misst einen festen Stand des Repos (``lauf.stand_pfad``).

Ablage (Vorgabe ``/Volumes/UPVIS ULTRA/_cache/kevcad-pruefzeit/<Zeit>-<name>``, ohne die Platte
``~/Library/Caches/de.upvis.kevcad-bench/``): Arbeitsordner, Katalogkopie, Zwischenspeicher von Druck und FEM, TMPDIR,
Endstände je Schritt und das Ergebnis ``pruefzeit.json``; nichts auf Kevins Projekt, nichts auf der Systemplatte außer
den Sockets.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
sys.path.insert(0, str(HIER / "pruefzeit_analyse"))

import lauf  # noqa: E402

KUGEL = Path.home() / "Documents" / "Kev CAD" / "Kugelschieber Variante B"
KATALOG = Path.home() / "Library/Application Support/de.upvis.kevcad/katalog"
ULTRA = Path("/Volumes/UPVIS ULTRA/_cache/kevcad-pruefzeit")
MCP_HELLO_PORT = 47995  # nur die Zahl in HELLO; nie 47823/47824 (Kevins App)
IGNORIEREN = shutil.ignore_patterns(".kevcad", "versionen", "output", "export*", "*.3mf", "*.step", "*.stp", "*.stl",
                                    "__pycache__", ".DS_Store", "dokumente")
STANDARD_SCHRITTE = "kalt;laufrolle_l=90;laufrolle_l=90;-"


# ---------------------------------------------------------------------------------------------------------------------
# Umgebung


def umgebung(arbeit: Path, katalog: Path) -> dict[str, Path]:
    """Ablagen eines Kernels unter ``arbeit`` (der Katalog wird geteilt, er wird nur gelesen)."""
    pfade = {"projekte": arbeit / "projekte", "druck": arbeit / "druck", "fem": arbeit / "fem", "tmp": arbeit / "tmp"}
    for p in pfade.values():
        p.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "KEVCAD_CATALOG_DIR": str(katalog), "KEVCAD_PROJECTS_DIR": str(pfade["projekte"]),
        "KEVCAD_DRUCK_CACHE": str(pfade["druck"] / "cache"),
        "KEVCAD_DRUCK_ABGLEICH": str(pfade["druck"] / "abgleich.json"),
        "KEVCAD_BAMBU_APP": str(pfade["druck"] / "kein-bambu-studio.app"),
        "KEVCAD_FESTKOERPER_CACHE": str(pfade["fem"]), "KEVCAD_FILAMENTE": str(pfade["druck"] / "filamente.json"),
        "KEVCAD_DRUCKER_SSDP": "0", "TMPDIR": str(pfade["tmp"]),
    })
    tempfile.tempdir = str(pfade["tmp"])
    return pfade


def netze_uebernehmen(von: Path, nach: Path) -> int:
    """FEM-Netze (``netze/*.npz``) als harte Links (sonst Kopien) in einen anderen Zwischenspeicher."""
    ziel = nach / "netze"
    ziel.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in sorted((von / "netze").glob("*.npz")) if (von / "netze").is_dir() else []:
        q = ziel / p.name
        if q.exists():
            continue
        try:
            os.link(p, q)
        except OSError:
            shutil.copy2(p, q)
        n += 1
    return n


def systemstand() -> dict[str, Any]:
    """Last (1 min) und freier Speicher (kern.memorystatus_level, Prozent)."""
    frei = None
    try:
        frei = int(subprocess.run(["sysctl", "-n", "kern.memorystatus_level"], capture_output=True, text=True,
                                  timeout=5).stdout.strip())
    except Exception:  # noqa: BLE001
        pass
    return {"last": round(os.getloadavg()[0], 1), "speicher_frei_prozent": frei}


def runtime(sock: str, log: Any = None) -> Any:
    from kevcad_kernel.runtime import KernelRuntime  # noqa: PLC0415

    return KernelRuntime(sock, MCP_HELLO_PORT, auto_run=False, run_timeout_s=900, log=log or (lambda line: None))


def schliessen(rt: Any) -> None:
    rt.close()
    pool = getattr(rt, "_pool", None)
    if pool is not None:
        pool.shutdown(wait=True)


def schritte_lesen(text: str) -> list[tuple[str, dict[str, float] | None]]:
    out = []
    for s in text.split(";"):
        s = s.strip()
        if s in ("kalt", "-", "", "datei"):
            out.append(("kalt" if s == "kalt" else "zurück auf die Datei", None))
            continue
        params = {}
        for teil in s.split(","):
            name, _, wert = teil.partition("=")
            params[name.strip()] = float(wert)
        out.append((s, params))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Zeitleiste


class Zeitleiste:
    """Ereignisse eines Schritts mit Zeit ab Beginn des Laufs (s). Die Laufzeit läuft in diesem Prozess: ihre Methoden
    werden umhüllt, der FEM-Prozess meldet Beginn und Ende je Teil im Ergebnis (``zeiten_teile``)."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.ereignisse: list[dict[str, Any]] = []
        self.fem: list[dict[str, Any]] = []

    def neu(self) -> None:
        self.t0 = time.time()
        self.ereignisse = []
        self.fem = []

    def e(self, name: str, t: float | None = None, **kw: Any) -> None:
        self.ereignisse.append({"t": round((time.time() if t is None else t) - self.t0, 3), "e": name, **kw})

    def anschliessen(self) -> None:
        from kevcad_kernel.runtime import KernelRuntime  # noqa: PLC0415

        zl = self
        o_msg = KernelRuntime._on_worker_message

        def on_msg(self: Any, gen: int, header: dict[str, Any], payload: bytes) -> Any:
            kind = header.get("type")
            if kind == "CHECK_DONE":
                app = header.get("app") or {}
                zl.e("check", state=app.get("state"), offen=app.get("im_hintergrund"),
                     statik=isinstance(app.get("statik"), dict),
                     fem_auftrag=any(k.startswith("festkoerper_auftrag") for k in app))
            elif kind in ("RUN_DONE", "RUN_FAILED"):
                zl.e(kind.lower(), dauer_ms=header.get("duration_ms"))
            return o_msg(self, gen, header, payload)

        KernelRuntime._on_worker_message = on_msg

        def huelle(name: str, nachher: Any = None) -> None:
            o = getattr(KernelRuntime, name)

            def f(self: Any, *a: Any, **kw: Any) -> Any:
                zl.e(f"{name}_start")
                try:
                    out = o(self, *a, **kw)
                except BaseException as exc:
                    zl.e(f"{name}_fehler", fehler=repr(exc)[:200])
                    raise
                zl.e(f"{name}_ende", **(nachher(out) if nachher is not None else {}))
                return out

            setattr(KernelRuntime, name, f)

        def fem_aus(out: dict[str, Any]) -> dict[str, Any]:
            zl.fem.append(out)
            return {"teile": len(out.get("zeiten_teile") or []), "speicher_mb": out.get("speicher_mb"),
                    "faelle": len(out.get("faelle") or [])}

        huelle("_fk_exec", lambda job: {"faelle": len(job.get("faelle") or []), "ms": job.get("ms")})
        huelle("_fk_prozess", fem_aus)
        huelle("_festkoerper_hintergrund")

    def ergebnis(self) -> dict[str, Any]:
        """Ereignisse, dazu je FEM-Prozess die Teile (Beginn, Ende ab Laufbeginn, Prozess)."""
        teile = []
        speicher = []
        for out in self.fem:
            beginn = out.get("beginn")
            for z in out.get("zeiten_teile") or []:
                if beginn is None:
                    continue
                teile.append({"teil": z["teil"].rsplit("/", 1)[-1], "pid": z.get("pid"),
                              "von": round(beginn + z["start"] - self.t0, 2), "bis": round(beginn + z["ende"] - self.t0, 2)})
            for p in out.get("prozesse") or [{"pid": out.get("pid"), "speicher_mb": out.get("speicher_mb")}]:
                speicher.append(p)
        faelle = [{"teil": str(r.get("teil") or "").rsplit("/", 1)[-1], "szenario": r.get("szenario"),
                   "stand": r.get("stand"), "aus_speicher": r.get("aus_speicher"),
                   "verfahren": (r.get("loeser") or {}).get("verfahren"),
                   "freiheitsgrade": (r.get("netz") or {}).get("freiheitsgrade"), "ms": r.get("ms")}
                  for out in self.fem for r in out.get("faelle") or []]
        return {"ereignisse": self.ereignisse, "fem_teile": sorted(teile, key=lambda x: x["von"]),
                "fem_prozesse": speicher, "fem_faelle": faelle}


def zeitleiste_text(zl: dict[str, Any]) -> list[str]:
    zeilen = []
    for e in zl["ereignisse"]:
        extra = {k: v for k, v in e.items() if k not in ("t", "e") and v not in (None, False, [], {})}
        zeilen.append(f"    {e['t']:7.2f} s  {e['e']}" + (f"  {extra}" if extra else ""))
    for t in zl["fem_teile"]:
        zeilen.append(f"    {t['von']:7.2f} → {t['bis']:6.2f} s  FEM {t['teil']} (pid {t['pid']})")
    return zeilen


# ---------------------------------------------------------------------------------------------------------------------
# Referenz: frischer Kernel im eigenen Prozess


def referenz_starten(auftrag: dict[str, Any], pfad: Path) -> subprocess.Popen:
    pfad.write_text(json.dumps(auftrag, ensure_ascii=False), encoding="utf-8")
    return subprocess.Popen([sys.executable, "-u", str(Path(__file__).resolve()), "--referenz", str(pfad)],
                            stdout=open(pfad.with_suffix(".log"), "w", encoding="utf-8"), stderr=subprocess.STDOUT)


def referenz(pfad: Path) -> int:
    """Im eigenen Prozess: frischer Kernel, Kopie des Projekts, ein Lauf mit den Parametern, Endstand als JSON."""
    import gleichheit  # noqa: PLC0415

    a = json.loads(pfad.read_text(encoding="utf-8"))
    arbeit = Path(a["arbeit"])
    pfade = umgebung(arbeit, Path(a["katalog"]))
    n = netze_uebernehmen(Path(a["netze"]), pfade["fem"])
    projekt = pfade["projekte"] / "kugelschieber"
    shutil.copytree(a["projekt"], projekt, ignore=IGNORIEREN)
    sock = f"/tmp/kcpz-ref-{os.getpid()}.sock"
    rt = runtime(sock)
    t0 = time.monotonic()
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        rt.project_open(str(projekt))
        res = rt.run(params=a.get("params"), timeout_s=900)
        endstand = gleichheit.erfassen(rt)
    finally:
        schliessen(rt)
    Path(a["ausgabe"]).write_text(json.dumps({"endstand": endstand, "lauf_ok": bool(res.get("ok", True)),
                                              "netze_uebernommen": n,
                                              "fem": str(pfade["fem"] / "faelle"),
                                              "s": round(time.monotonic() - t0, 1)}, ensure_ascii=False, default=str),
                                  encoding="utf-8")
    return 0


def nachvergleich(ablage: Path) -> int:
    """Gleichheitsprobe einer früheren Ablage aus ihren Dateien neu werten (Endstände und FEM-Zwischenspeicher)."""
    import gleichheit  # noqa: PLC0415

    ungleich = 0
    for i, s in enumerate(json.loads((ablage / "pruefzeit.json").read_text(encoding="utf-8"))["schritte"]):
        ref = ablage / f"referenz-{i}" / "endstand.json"
        if not ref.exists():
            continue
        a = json.loads(Path(s["endstand"]).read_text(encoding="utf-8"))
        r = json.loads(ref.read_text(encoding="utf-8"))
        v = gleichheit.vergleichen(a, r["endstand"], ablage / "haupt" / "fem" / "faelle", Path(r["fem"]))
        print(f"[{i}] {s['schritt']}: {gleichheit.kurz(v)}")
        for u in v["unterschiede"][:12]:
            print(f"      {u['pfad']}: {str(u['a'])[:120]} | {str(u['b'])[:120]}")
        for grund in sorted({u["grund"] for u in v["bekannt"]}):
            print(f"      bekannt ({sum(1 for u in v['bekannt'] if u['grund'] == grund)}): {grund}")
        ungleich += 0 if v["gleich"] else 1
    return 1 if ungleich else 0


# ---------------------------------------------------------------------------------------------------------------------
# Ablauf


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel-src", default=None, help="Kernel-Stand (Ordner oder @<git-ref>:kernel/src)")
    ap.add_argument("--projekt", default=str(KUGEL))
    ap.add_argument("--schritte", default=STANDARD_SCHRITTE,
                    help='";"-getrennt: "kalt", "-" (Datei), "name=wert[,name=wert]"')
    ap.add_argument("--param", default=None, help="alte Form: nur diese Änderung (kalt; Änderung; noch einmal; Datei)")
    ap.add_argument("--probe", action="store_true", help="Gleichheitsprobe nach jedem Schritt")
    ap.add_argument("--probe-schritte", default=None, help="nur diese Schritte prüfen (Nummern ab 0, Komma)")
    ap.add_argument("--ablage", default=None)
    ap.add_argument("--name", default="pruefzeit")
    ap.add_argument("--netze-von", default=None, help="FEM-Netze aus der Ablage eines früheren Aufrufs übernehmen")
    ap.add_argument("--vergleich", default=None, help="Endstände mit diesem pruefzeit.json vergleichen")
    ap.add_argument("--nachlauf-s", type=float, default=2.0, help="nach dem Endstand so lange warten")
    ap.add_argument("--referenz", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--nachvergleich", default=None, help="Probe einer früheren Ablage aus ihren Dateien neu werten")
    args = ap.parse_args()
    if args.kernel_src:
        lauf._kernel_src_einsetzen(lauf.stand_pfad(args.kernel_src))
    if args.referenz:
        return referenz(Path(args.referenz))
    if args.nachvergleich:
        return nachvergleich(Path(args.nachvergleich))
    import gleichheit  # noqa: PLC0415

    import kevcad_kernel  # noqa: PLC0415

    stempel = time.strftime("%Y%m%d-%H%M%S")
    if args.ablage:
        ablage = Path(args.ablage)
    elif ULTRA.parent.is_dir():
        ablage = ULTRA / f"{stempel}-{args.name}"
    else:
        ablage = Path.home() / "Library/Caches/de.upvis.kevcad-bench" / f"{stempel}-{args.name}"
    ablage.mkdir(parents=True, exist_ok=True)
    katalog = ablage / "katalog"
    if not katalog.exists():
        if KATALOG.is_dir():
            shutil.copytree(KATALOG, katalog)
        else:
            katalog.mkdir()
    pfade = umgebung(ablage / "haupt", katalog)
    if args.netze_von:
        n = netze_uebernehmen(Path(args.netze_von) / "haupt" / "fem", pfade["fem"])
        print(f"{n} FEM-Netze aus {args.netze_von} übernommen", flush=True)
    projekt = pfade["projekte"] / "kugelschieber"
    shutil.copytree(args.projekt, projekt, ignore=IGNORIEREN)
    schritte = schritte_lesen(args.schritte)
    if args.param:
        name, _, wert = args.param.partition("=")
        p = {name: float(wert)}
        schritte = [("kalt", None), ("Änderung", p), ("dieselbe Änderung noch einmal", p),
                    ("zurück auf die Datei", None)]
    probe_nur = {int(x) for x in args.probe_schritte.split(",")} if args.probe_schritte else None
    vergleich = json.loads(Path(args.vergleich).read_text(encoding="utf-8")) if args.vergleich else None
    zl = Zeitleiste()
    zl.anschliessen()
    print(f"Kernel: {kevcad_kernel.__file__}\nAblage: {ablage}", flush=True)
    rt = runtime(f"/tmp/kcpz-{os.getpid()}.sock")
    out: dict[str, Any] = {"kernel": kevcad_kernel.__file__, "kernel_src": args.kernel_src, "ablage": str(ablage),
                           "beginn": stempel, "schritte": []}
    ungleich = 0
    try:
        if not rt.wait_worker_ready(300):
            raise SystemExit("Rechenprozess startet nicht")
        rt.project_open(str(projekt))
        for i, (titel, params) in enumerate(schritte):
            stand_vorher = None
            mit_probe = args.probe and (probe_nur is None or i in probe_nur)
            if mit_probe:
                stand_vorher = ablage / f"stand-{i}"
                shutil.copytree(projekt, stand_vorher, ignore=IGNORIEREN)
            sys_vorher = systemstand()
            zl.neu()
            res = rt.run(params=params, timeout_s=900)
            zl.e("run_zurueck", ok=res.get("ok", True))
            t_run = time.time() - zl.t0
            endstand = gleichheit.erfassen(rt)
            t_end = time.time() - zl.t0
            zl.e("endstand", state=endstand["check"].get("state"))
            sys_nachher = systemstand()
            time.sleep(args.nachlauf_s)
            check = endstand["check"]
            stat = check.get("statistik") or {}
            eintrag: dict[str, Any] = {
                "schritt": f"{i}:{titel}", "params": params, "ok": res.get("ok", True), "run_s": round(t_run, 2),
                "bis_endstand_s": round(t_end, 2), "state": check.get("state"), "system_vorher": sys_vorher,
                "system_nachher": sys_nachher, "zeiten_ms": stat.get("zeiten_ms"), "paare": stat.get("paare"),
                "zusammenfassung": check.get("zusammenfassung"), "lauf_zeiten": res.get("zeiten_ms"),
                "zeitleiste": zl.ergebnis()}
            pfad_endstand = ablage / f"endstand-{i}.json"
            pfad_endstand.write_text(json.dumps(endstand, ensure_ascii=False, default=str), encoding="utf-8")
            eintrag["endstand"] = str(pfad_endstand)
            fem_speicher = max((p.get("speicher_mb") or 0.0 for p in eintrag["zeitleiste"]["fem_prozesse"]),
                               default=None)
            print(f"[{i}] {titel}: Lauf {t_run:.2f} s, Endstand {t_end:.2f} s ab Laufbeginn ({check.get('state')}), "
                  f"Last {sys_vorher['last']}→{sys_nachher['last']}, Speicher frei {sys_vorher['speicher_frei_prozent']} %"
                  + (f", FEM-Spitze {fem_speicher:.0f} MB" if fem_speicher else ""), flush=True)
            for z in zeitleiste_text(eintrag["zeitleiste"]):
                print(z, flush=True)
            if mit_probe:
                ref_ordner = ablage / f"referenz-{i}"
                auftrag = {"projekt": str(stand_vorher), "params": params, "arbeit": str(ref_ordner),
                           "katalog": str(katalog), "netze": str(pfade["fem"]),
                           "ausgabe": str(ref_ordner / "endstand.json")}
                ref_ordner.mkdir(parents=True, exist_ok=True)
                t_ref = time.monotonic()
                p = referenz_starten(auftrag, ref_ordner / "auftrag.json")
                code = p.wait()
                if code != 0 or not (ref_ordner / "endstand.json").exists():
                    eintrag["probe"] = {"gleich": False, "fehler": f"Referenz endete mit {code}",
                                        "log": str(ref_ordner / "auftrag.log")}
                else:
                    ref = json.loads((ref_ordner / "endstand.json").read_text(encoding="utf-8"))
                    v = gleichheit.vergleichen(copy.deepcopy(endstand), ref["endstand"], pfade["fem"] / "faelle",
                                               Path(ref["fem"]))
                    v["referenz_s"] = round(time.monotonic() - t_ref, 1)
                    eintrag["probe"] = v
                    print(f"    Probe: {gleichheit.kurz(v)} (Referenz {v['referenz_s']} s)", flush=True)
                    for u in v["unterschiede"][:8]:
                        print(f"      {u['pfad']}: {str(u['a'])[:120]} | {str(u['b'])[:120]}", flush=True)
                if not eintrag["probe"].get("gleich"):
                    ungleich += 1
            if vergleich is not None and i < len(vergleich.get("schritte") or []):
                anderer = vergleich["schritte"][i]
                a2 = json.loads(Path(anderer["endstand"]).read_text(encoding="utf-8"))
                fem_anderer = Path(vergleich["ablage"]) / "haupt" / "fem" / "faelle"
                v = gleichheit.vergleichen(copy.deepcopy(endstand), a2, pfade["fem"] / "faelle", fem_anderer)
                eintrag["vergleich"] = v
                print(f"    Vergleich mit {vergleich['ablage']}: {gleichheit.kurz(v)}", flush=True)
                for u in v["unterschiede"][:8]:
                    print(f"      {u['pfad']}: {str(u['a'])[:120]} | {str(u['b'])[:120]}", flush=True)
            out["schritte"].append(eintrag)
            (ablage / "pruefzeit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
    finally:
        schliessen(rt)
        (ablage / "pruefzeit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
        print(f"Ergebnis: {ablage / 'pruefzeit.json'}", flush=True)
    return 1 if ungleich else 0


if __name__ == "__main__":
    sys.exit(main())

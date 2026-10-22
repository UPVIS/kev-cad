"""Git als unsichtbarer Speicher der Versionen (PLAN-VERSIONEN.md, V1).

Eigenes Repo in ``<projekt>/.kevcad/git`` (eigenes ``GIT_DIR``), Arbeitskopie ist der Projektordner. Git läuft über
die Kommandozeile mit einer eigenen, abgeschlossenen Umgebung: keine globale oder System-Konfiguration, keine Hooks,
keine Signatur, Autor „Kev CAD“. Am globalen Git von Kevin ändert sich nichts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path

AUTOR = "Kev CAD"
AUTOR_MAIL = "kevcad@localhost"
HAUPT = "haupt"  # Zweig des Hauptstands

# Nicht erfasst (Kevin, 21.10.2026): Ausgaben, interne Daten von Kev CAD, Bestand (gehört nicht zu den Versionen),
# dazu Systemmüll und Zwischendateien.
AUSSCHLUSS = """\
# Kev CAD: nicht in den Versionen (von Kev CAD verwaltet)
/output/
/.kevcad/
/bestand.json
__pycache__/
*.pyc
.DS_Store
.*.tmp
*.tmp
*.swp
*~
.ipynb_checkpoints/
.vscode/
.idea/
"""
GROSS_MARKE = "# Zu groß für die Versionen (automatisch):"
MAX_DATEI_BYTES = 200 * 1024 * 1024

_git_ok: bool | None = None
_git_meldung = ""
_git_exe = "git"
_git_lock = threading.Lock()

GIT_FEHLT = ("Git fehlt auf diesem Mac: Versionen sind aus. Abhilfe: im Terminal `xcode-select --install` ausführen "
             "(installiert die Befehlszeilenwerkzeuge mit Git) und Kev CAD neu starten.")


class GitFehler(RuntimeError):
    """Git-Aufruf gescheitert (Meldung enthält Befehl und stderr)."""


def git_verfuegbar() -> tuple[bool, str]:
    """Ob ein brauchbares git da ist; zweiter Wert ist die Meldung für Kevin, wenn nicht. Unter macOS ist
    /usr/bin/git ohne Befehlszeilenwerkzeuge nur ein Platzhalter, der mit einem Fehler endet."""
    global _git_ok, _git_meldung, _git_exe
    with _git_lock:
        if _git_ok is None:
            exe = shutil.which("git")
            if exe is None:
                _git_ok, _git_meldung = False, GIT_FEHLT
            else:
                try:
                    r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20,
                                       env=_basis_env())
                    _git_ok = r.returncode == 0 and r.stdout.startswith("git version")
                    _git_meldung = "" if _git_ok else GIT_FEHLT
                except (OSError, subprocess.SubprocessError):
                    _git_ok, _git_meldung = False, GIT_FEHLT
                if _git_ok:
                    _git_exe = _echtes_git(exe)
        return bool(_git_ok), _git_meldung


def _echtes_git(exe: str) -> str:
    """/usr/bin/git ist unter macOS ein Umweg über xcrun (je Aufruf gut 10 ms); das eigentliche Programm direkt
    benutzen, wenn es sich finden lässt."""
    if exe != "/usr/bin/git" or not shutil.which("xcrun"):
        return exe
    try:
        r = subprocess.run(["xcrun", "--find", "git"], capture_output=True, text=True, timeout=10, env=_basis_env())
        echt = r.stdout.strip()
        if r.returncode == 0 and echt and os.access(echt, os.X_OK):
            return echt
    except (OSError, subprocess.SubprocessError):
        pass
    return exe


def _basis_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": AUTOR,
        "GIT_AUTHOR_EMAIL": AUTOR_MAIL,
        "GIT_COMMITTER_NAME": AUTOR,
        "GIT_COMMITTER_EMAIL": AUTOR_MAIL,
        "LC_ALL": "C",
        "LANG": "C",
    })
    return env


# feste Einstellungen je Aufruf (statt einer Konfigurationsdatei, die jemand ändern könnte)
_OPTIONEN = ("-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
             "-c", "core.autocrlf=false", "-c", "core.quotepath=false", "-c", "gc.auto=0",
             "-c", "core.fsmonitor=false", "-c", "advice.detachedHead=false", "-c", "init.defaultBranch=" + HAUPT,
             "-c", "core.precomposeunicode=true", "-c", "user.useConfigOnly=false")


class GitRepo:
    """Ein Projekt-Repo. Alle Aufrufe sind synchron; Aufrufer serialisieren selbst (Versionsarchiv)."""

    def __init__(self, projekt: Path) -> None:
        self.projekt = Path(projekt)
        self.git_dir = self.projekt / ".kevcad" / "git"

    # -- Grundlagen ----------------------------------------------------------------------------------------------------

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = _basis_env()
        env["GIT_DIR"] = str(self.git_dir)
        env["GIT_WORK_TREE"] = str(self.projekt)
        if extra:
            env.update(extra)
        return env

    def run(self, *args: str, input: bytes | str | None = None, env: dict[str, str] | None = None,  # noqa: A002
            check: bool = True, timeout: float = 120.0) -> subprocess.CompletedProcess:
        data = input.encode("utf-8") if isinstance(input, str) else input
        try:
            r = subprocess.run([_git_exe, *_OPTIONEN, *args], input=data, capture_output=True, cwd=str(self.projekt),
                               env=self.env(env), timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitFehler(f"git {args[0] if args else ''}: {exc}") from exc
        if check and r.returncode != 0:
            err = r.stderr.decode("utf-8", "replace").strip() or r.stdout.decode("utf-8", "replace").strip()
            raise GitFehler(f"git {' '.join(args[:3])} (Exitcode {r.returncode}): {err[:600]}")
        return r

    def text(self, *args: str, **kw) -> str:
        return self.run(*args, **kw).stdout.decode("utf-8", "replace")

    @property
    def vorhanden(self) -> bool:
        return (self.git_dir / "HEAD").is_file()

    def init(self) -> None:
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        self.run("init", "-q", "--initial-branch=" + HAUPT)
        self.schreibe_ausschluss()

    def schreibe_ausschluss(self, gross: Iterable[str] = ()) -> None:
        """``info/exclude`` neu schreiben; ``gross`` sind zu große Dateien (relativ), die dauerhaft draußen bleiben."""
        datei = self.git_dir / "info" / "exclude"
        datei.parent.mkdir(parents=True, exist_ok=True)
        alt = self.grosse_dateien()
        alle = sorted(set(alt) | {g.strip("/") for g in gross})
        text = AUSSCHLUSS
        if alle:
            text += GROSS_MARKE + "\n" + "".join("/" + g + "\n" for g in alle)
        datei.write_text(text, encoding="utf-8")

    def grosse_dateien(self) -> list[str]:
        datei = self.git_dir / "info" / "exclude"
        try:
            zeilen = datei.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        if GROSS_MARKE not in zeilen:
            return []
        return [z.strip().lstrip("/") for z in zeilen[zeilen.index(GROSS_MARKE) + 1:] if z.strip()]

    # -- Abfragen ------------------------------------------------------------------------------------------------------

    def head(self) -> str | None:
        r = self.run("rev-parse", "-q", "--verify", "HEAD^{commit}", check=False)
        return r.stdout.decode().strip() or None if r.returncode == 0 else None

    def zweig(self) -> str:
        r = self.run("symbolic-ref", "-q", "--short", "HEAD", check=False)
        return r.stdout.decode().strip() or HAUPT

    def zweige(self) -> dict[str, str]:
        """Zweigname → Commit der Spitze."""
        out = {}
        for zeile in self.text("for-each-ref", "--format=%(refname:short)%00%(objectname)", "refs/heads").splitlines():
            if "\0" in zeile:
                name, sha = zeile.split("\0", 1)
                out[name] = sha
        return out

    def rev(self, ref: str) -> str | None:
        r = self.run("rev-parse", "-q", "--verify", ref + "^{commit}", check=False)
        return r.stdout.decode().strip() or None if r.returncode == 0 else None

    def baum(self, ref: str) -> str:
        return self.text("rev-parse", ref + "^{tree}").strip()

    def unversionierte(self) -> list[str]:
        """Neue, nicht ausgeschlossene Dateien (relativ zum Projekt)."""
        out = self.run("ls-files", "--others", "--exclude-standard", "-z").stdout.decode("utf-8", "replace")
        return [p for p in out.split("\0") if p]

    def status(self) -> list[tuple[str, str]]:
        """(Kürzel, Pfad) je geänderter, neuer oder gelöschter Datei (``status --porcelain``), ohne Ausgeschlossene."""
        out = self.run("status", "--porcelain=v1", "-z", "-uall", "--no-renames").stdout.decode("utf-8", "replace")
        return [(e[:2], e[3:]) for e in out.split("\0") if len(e) > 3]

    def bereite_vor(self) -> tuple[list[str], bool]:
        """Alle Änderungen vormerken (``add -A``). Zu große neue Dateien kommen vorher dauerhaft in den Ausschluss.
        Rückgabe: (deren Namen für eine Warnung, ob es überhaupt Änderungen gab). Ohne Änderung bleibt es bei einem
        einzigen Git-Aufruf."""
        st = self.status()
        if not st:
            return [], False
        gross = []
        for code, rel in st:
            if code == "??":
                try:
                    if (self.projekt / rel).stat().st_size > MAX_DATEI_BYTES:
                        gross.append(rel)
                except OSError:
                    pass
        if gross:
            self.schreibe_ausschluss(gross)
        self.run("add", "-A")
        return gross, True

    def geaendert(self) -> bool:
        """Vorgemerkter Stand weicht von HEAD ab (oder es gibt noch keinen Commit)."""
        if self.head() is None:
            return bool(self.text("ls-files", "-z").strip("\0"))
        return self.run("diff", "--cached", "--quiet", "HEAD", check=False).returncode != 0

    def commit(self, nachricht: str, datum: int | None = None) -> str:
        env = None
        if datum is not None:
            env = {"GIT_AUTHOR_DATE": f"@{int(datum)} +0000", "GIT_COMMITTER_DATE": f"@{int(datum)} +0000"}
        self.run("commit", "-q", "--no-verify", "--allow-empty-message", "-F", "-", input=nachricht, env=env)
        return self.head() or ""

    def log(self, ref: str, *, alle: bool = False) -> list[dict]:
        """Commits (neueste zuerst) mit Eltern, Zeit, Nachricht und geänderten Dateien."""
        args = ["log", "--format=%x1e%H%x00%P%x00%at%x00%B%x00", "--name-only", "--no-renames"]
        args += ["--all"] if alle else ["--first-parent", ref]
        r = self.run(*args, check=False)
        if r.returncode != 0:
            return []
        out = []
        for block in r.stdout.decode("utf-8", "replace").split("\x1e"):
            if not block.strip():
                continue
            teile = block.split("\0")
            if len(teile) < 5:
                continue
            sha, eltern, zeit, nachricht, rest = teile[0], teile[1], teile[2], teile[3], "\0".join(teile[4:])
            out.append({"commit": sha.strip(), "eltern": eltern.split(), "ts": int(zeit or 0),
                        "nachricht": nachricht, "dateien": [z for z in rest.splitlines() if z.strip()]})
        return out

    def enthaltende_zweige(self, sha: str) -> list[str]:
        return [z.strip() for z in self.text("branch", "--format=%(refname:short)", "--contains", sha).splitlines()
                if z.strip()]

    def datei(self, ref: str, pfad: str) -> bytes | None:
        r = self.run("show", f"{ref}:{pfad}", check=False)
        return r.stdout if r.returncode == 0 else None

    def dateien(self, ref: str) -> list[str]:
        out = self.run("ls-tree", "-r", "-z", "--name-only", ref).stdout.decode("utf-8", "replace")
        return [p for p in out.split("\0") if p]

    def archiv(self, ref: str) -> bytes:
        return self.run("archive", "--format=tar", ref, timeout=300).stdout

    # -- Arbeitskopie --------------------------------------------------------------------------------------------------

    def stelle_her(self, ref: str) -> None:
        """Index und Arbeitskopie auf den Baum von ``ref`` setzen (HEAD bleibt). Dateien, die versioniert sind, aber in
        ``ref`` fehlen, verschwinden; ausgeschlossene Dateien bleiben unberührt."""
        self.run("read-tree", "-u", "--reset", ref)

    def wechsle(self, zweig: str) -> None:
        self.run("checkout", "-f", "-q", zweig)

    def neuer_zweig(self, zweig: str, ref: str) -> None:
        self.run("branch", zweig, ref)

    def setze_zweig(self, zweig: str, sha: str) -> None:
        self.run("update-ref", f"refs/heads/{zweig}", sha)

    def commit_baum(self, baum: str, eltern: str | None, nachricht: str, autor_ts: int, commit_ts: int) -> str:
        args = ["commit-tree", baum]
        if eltern:
            args += ["-p", eltern]
        env = {"GIT_AUTHOR_DATE": f"@{autor_ts} +0000", "GIT_COMMITTER_DATE": f"@{commit_ts} +0000"}
        return self.text(*args, input=nachricht, env=env).strip()

    def nachricht(self, ref: str) -> str:
        """Commit-Nachricht unverändert (für ``commit_baum``; ``%B`` hängte eine Leerzeile an)."""
        roh = self.text("cat-file", "commit", ref)
        return roh.split("\n\n", 1)[1] if "\n\n" in roh else ""

    def zeiten(self, ref: str) -> tuple[int, int]:
        """(Autorzeit, Commitzeit) in Sekunden."""
        teile = self.text("show", "-s", "--format=%at %ct", ref).split()
        return int(teile[0]), int(teile[1])

    def baum_mit(self, ref: str, pfad: str) -> str:
        """Baum von ``ref``, in dem der Ordner ``pfad`` dem Stand der Arbeitskopie entspricht; alles andere bleibt wie
        in ``ref``. Läuft über einen eigenen Index, der echte Index bleibt unberührt."""
        vorhanden = (self.projekt / pfad).exists() or bool(self.text("ls-tree", "--name-only", ref, pfad).strip())
        if not vorhanden:
            return self.baum(ref)
        index = self.git_dir / f"index-nachtrag-{os.getpid()}-{threading.get_ident()}"
        env = {"GIT_INDEX_FILE": str(index)}
        try:
            self.run("read-tree", ref, env=env)
            self.run("add", "-A", "--", pfad, env=env)
            return self.text("write-tree", env=env).strip()
        finally:
            try:
                index.unlink()
            except OSError:
                pass

    def vormerken(self, pfad: str) -> None:
        """Nur ``pfad`` im echten Index auf den Stand der Arbeitskopie bringen."""
        if (self.projekt / pfad).exists() or self.text("ls-files", "--", pfad).strip():
            self.run("add", "-A", "--", pfad)

    def fast_import(self, strom: bytes) -> None:
        self.run("fast-import", "--quiet", "--done", input=strom, timeout=600)

    def hash_objekte(self, pfade: list[Path]) -> list[str]:
        if not pfade:
            return []
        liste = "\n".join(str(p) for p in pfade) + "\n"
        return self.text("hash-object", "-w", "--no-filters", "--stdin-paths", input=liste).split()

    def diff_text(self, a: str, b: str | None, *, kontext: int = 3, pfade: Iterable[str] = ()) -> str:
        """Unterschied von ``a`` zu ``b`` (None = vorgemerkter Stand der Arbeitskopie); ``pfade``: Pfadangaben
        (auch ``:(exclude)…``)."""
        args = ["diff", "--no-color", "--no-ext-diff", f"-U{kontext}", "--no-renames"]
        args += [a, b] if b else ["--cached", a]
        pfade = list(pfade)
        return self.text(*args, *(["--", *pfade] if pfade else []))

    def diff_zahlen(self, a: str, b: str | None, *, pfade: Iterable[str] = ()) -> list[dict]:
        pfade = list(pfade)
        nach = ["--", *pfade] if pfade else []
        args = ["diff", "--numstat", "--no-renames", "-z"]
        args += [a, b] if b else ["--cached", a]
        out = self.run(*args, *nach).stdout.decode("utf-8", "replace")
        status_args = ["diff", "--name-status", "--no-renames", "-z"] + ([a, b] if b else ["--cached", a]) + nach
        st = self.run(*status_args).stdout.decode("utf-8", "replace").split("\0")
        status = {st[i + 1]: st[i] for i in range(0, len(st) - 1, 2) if st[i]}
        res = []
        for eintrag in out.split("\0"):
            if not eintrag.strip():
                continue
            felder = eintrag.split("\t", 2)
            if len(felder) < 3:
                continue
            plus, minus, pfad = felder
            res.append({"pfad": pfad, "status": status.get(pfad, "M"),
                        "plus": int(plus) if plus.isdigit() else None,
                        "minus": int(minus) if minus.isdigit() else None,
                        "binaer": not plus.isdigit()})
        return res

    def aufraeumen_speicher(self) -> None:
        self.run("reflog", "expire", "--expire=now", "--all", check=False)
        self.run("gc", "--prune=now", "--quiet", check=False, timeout=600)

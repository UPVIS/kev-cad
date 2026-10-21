"""Versionen, Meilensteine, Wiederherstellen, Vergleich und Varianten (PLAN-VERSIONEN.md).

- ``git``: Git als unsichtbarer Speicher (eigenes Repo in ``<projekt>/.kevcad/git``).
- ``archiv``: Versionen eines Projekts (anlegen, Meilensteine, Wiederherstellen, Varianten, Aufräumen, Übernahme).
- ``schnappschuss``: Daten und Netze je Version (Vergleich, Vorschaubild).
- ``vergleich``: zwei Stände vergleichen.
- ``laufzeit``: Einbindung in die Kernel-Laufzeit (KernelService, App-Nachrichten).
"""

from kevcad_kernel.versionen.archiv import HAUPT, HAUPT_NAME, Version, Versionsarchiv, VersionsFehler
from kevcad_kernel.versionen.git import GitFehler, git_verfuegbar

__all__ = ["HAUPT", "HAUPT_NAME", "GitFehler", "Version", "Versionsarchiv", "VersionsFehler", "git_verfuegbar"]

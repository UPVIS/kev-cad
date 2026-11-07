# Messwerkzeug „Prüfung inkrementell“ (Analyse 06.11.2026)

Grundlage von PLAN-PRUEFUNG-INKREMENTELL.md. Ändert keinen Repo-Code: Die Messhülle `instrument/sitecustomize.py` wird
über PYTHONPATH in Laufzeit, Rechenprozess und FEM-Prozess geladen und ist nur mit `KCZ_PROTOKOLL` aktiv.

```bash
PY="/Users/kevinschwed/Code Experiments/Kev CAD/kernel/.venv/bin/python"   # Umgebung des Kernels
AB="/Volumes/UPVIS ULTRA/_cache/kevcad-pruefzeit/$(date +%Y%m%d-%H%M%S)"    # Ablage nicht auf der Systemplatte
mkdir -p "$AB"
PYTHONPATH="benchmark/pruefzeit_analyse/instrument:kernel/src" KCZ_PROTOKOLL="$AB/protokoll.jsonl" \
  KCZ_UHR=1 KCZ_KOERPER=1 "$PY" -u benchmark/pruefzeit_analyse/pruefzeit_detail.py --ablage "$AB" \
  --schritte "kalt;laufrolle_l=90;laufrolle_l=95"
```

Schalter: `KCZ_UHR` (Wanduhr je Funktion), `KCZ_KOERPER` (Form- und Lageschlüssel je Teil), `KCZ_SCHATTEN`
(Schattenzähler: Treffer mit Schlüssel aus Form und relativer Lage, Grund jedes neuen Statik-Schnitts), `KCZ_FEM_KOPIE`
(FEM-Aufträge sichern), `KCZ_PROFIL` (cProfile; unter Python 3.12 im Rechenprozess unvollständig).

`fem_versuch.py <auftrag> <arbeitsordner mit netze/> seq|lu|par4`: Löserversuche an einem gesicherten FEM-Auftrag.

Seit A0 (07.11.2026) im Repo-Werkzeug: `gleichheit.py` ist die Gleichheitsprobe von `benchmark/pruefzeit.py` (Endstand
inkrementell gegen frischen Kernel mit denselben FEM-Netzen).

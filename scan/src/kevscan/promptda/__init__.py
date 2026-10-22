"""Prompt Depth Anything (PromptDA), für Kev Scan übernommen und für Apple Silicon (MPS) angepasst.

Herkunft:

- PromptDA, https://github.com/DepthAnything/PromptDA (Haotong Lin u. a., CVPR 2025), Apache-2.0
  (``LICENSE`` in diesem Ordner): ``promptda/promptda.py``, ``promptda/model/dpt.py``, ``promptda/model/blocks.py``,
  ``promptda/model/config.py``.
- DINOv2, https://github.com/facebookresearch/dinov2 (Meta), Apache-2.0: Vision Transformer (``dinov2/models/
  vision_transformer.py``, ``dinov2/layers``), in der Fassung, die PromptDA unter ``torchhub/`` mitbringt.
- Gewichte: Hugging Face ``depth-anything/prompt-depth-anything-vitl`` und ``-vits`` (Apache-2.0), beim ersten
  Gebrauch geladen (``kevscan.tiefe``), nicht im Paket.

Änderungen gegenüber dem Original (Apache-2.0, Abschnitt 4b):

- Nur der Teil für die Vorhersage, in drei Dateien zusammengefasst (``vit.py``, ``dpt.py``, ``modell.py``); kein
  ``torch.hub``, kein xFormers, keine Trainings- und Hilfsskripte.
- Aufmerksamkeit über ``torch.nn.functional.scaled_dot_product_attention`` (läuft auf MPS und CPU, spart Speicher).
- Lageeinbettung je Bildgröße einmal auf der CPU interpoliert (bikubisch) und zwischengespeichert.
- Normierung der Tiefe mit ``amin``/``amax`` statt ``quantile`` (gleiches Ergebnis für 0 und 1, läuft auf MPS).
- Keine Abhängigkeit von CUDA; Gerät wählt ``kevscan.tiefe`` (MPS, sonst CPU).

Die Schichtnamen sind unverändert, damit die Originalgewichte ohne Umbenennen passen.
"""

from kevscan.promptda.modell import MODELLE, PromptDA

__all__ = ["MODELLE", "PromptDA"]

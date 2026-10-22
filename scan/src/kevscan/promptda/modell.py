# Copyright (c) PromptDA (Haotong Lin u. a.). Licensed under the Apache License, Version 2.0.
# Aus PromptDA (https://github.com/DepthAnything/PromptDA): promptda/promptda.py und promptda/model/config.py, für Kev
# Scan ohne torch.hub und CUDA (siehe __init__.py).
"""PromptDA: metrische Tiefe in Bildauflösung aus einem Farbbild und einer groben LiDAR-Tiefe als Prompt."""

from __future__ import annotations

from pathlib import Path

import torch
from torch import nn

from kevscan.promptda.dpt import DPTHead
from kevscan.promptda.vit import vit

KONFIG = {
    "vits": {"features": 64, "out_channels": [48, 96, 192, 384], "layer_idxs": [2, 5, 8, 11]},
    "vitb": {"features": 128, "out_channels": [96, 192, 384, 768], "layer_idxs": [2, 5, 8, 11]},
    "vitl": {"features": 256, "out_channels": [256, 512, 1024, 1024], "layer_idxs": [4, 11, 17, 23]},
}
# Kurzname -> (Encoder, Hugging-Face-Repo der Gewichte)
MODELLE = {
    "large": ("vitl", "depth-anything/prompt-depth-anything-vitl"),
    "small": ("vits", "depth-anything/prompt-depth-anything-vits"),
}


class PromptDA(nn.Module):
    patch_size = 14

    def __init__(self, encoder: str = "vitl") -> None:
        super().__init__()
        cfg = KONFIG[encoder]
        self.encoder = encoder
        self.layer_idxs = list(cfg["layer_idxs"])
        self.pretrained = vit(encoder)
        dim = self.pretrained.blocks[0].attn.qkv.in_features
        self.depth_head = DPTHead(in_channels=dim, features=cfg["features"], out_channels=cfg["out_channels"])
        self.register_buffer("_mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("_std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

    @classmethod
    def aus_datei(cls, ckpt: str | Path, encoder: str) -> "PromptDA":
        """Gewichte aus model.ckpt (Lightning-Prüfpunkt; Schlüssel mit Vorsatz wie im Original abgeschnitten)."""
        modell = cls(encoder)
        daten = torch.load(str(ckpt), map_location="cpu", weights_only=False)
        sd = daten.get("state_dict", daten)
        eigen = modell.state_dict()
        neu = {}
        for k, v in sd.items():
            kurz = k[9:] if k[9:] in eigen else (k.split(".", 1)[1] if "." in k and k.split(".", 1)[1] in eigen else k)
            neu[kurz] = v
        fehlt, zuviel = modell.load_state_dict(neu, strict=False)
        fehlt = [k for k in fehlt if k not in ("_mean", "_std")]
        if fehlt or zuviel:
            raise RuntimeError(f"Gewichte passen nicht zum Modell {encoder}: fehlt {fehlt[:5]}, zu viel {zuviel[:5]}")
        return modell.eval()

    def forward(self, x: torch.Tensor, prompt_depth: torch.Tensor) -> torch.Tensor:
        b = prompt_depth.shape[0]
        flach = prompt_depth.reshape(b, -1)
        lo = flach.amin(dim=1, keepdim=True)[:, :, None, None]
        hi = flach.amax(dim=1, keepdim=True)[:, :, None, None]
        pd = (prompt_depth - lo) / torch.clamp(hi - lo, min=1e-6)
        h, w = x.shape[-2:]
        features = self.pretrained.get_intermediate_layers((x - self._mean) / self._std, self.layer_idxs,
                                                           return_class_token=True)
        depth = self.depth_head(features, h // self.patch_size, w // self.patch_size, pd)
        return depth * (hi - lo) + lo

    @torch.no_grad()
    def predict(self, image: torch.Tensor, prompt_depth: torch.Tensor) -> torch.Tensor:
        """image 1 × 3 × H × W in [0, 1] (H, W Vielfache von 14), prompt_depth 1 × 1 × h × w in Metern ->
        Tiefe 1 × 1 × H × W in Metern."""
        return self.forward(image, prompt_depth)

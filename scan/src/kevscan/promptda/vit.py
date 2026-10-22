# Copyright (c) Meta Platforms, Inc. and affiliates. Licensed under the Apache License, Version 2.0.
# Vision Transformer aus DINOv2 (https://github.com/facebookresearch/dinov2, dinov2/models/vision_transformer.py und
# dinov2/layers), in der Fassung aus PromptDA/torchhub. Für Kev Scan gekürzt auf die Vorhersage; Aufmerksamkeit über
# scaled_dot_product_attention, Lageeinbettung je Bildgröße zwischengespeichert (siehe __init__.py).
"""DINOv2-ViT als Rückgrat von PromptDA (nur Vorhersage, Schichtnamen wie im Original)."""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import nn


class PatchEmbed(nn.Module):
    def __init__(self, img_size: int, patch_size: int, in_chans: int, embed_dim: int) -> None:
        super().__init__()
        self.patch_size = patch_size
        self.num_patches = (img_size // patch_size) ** 2
        self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=patch_size, stride=patch_size)
        self.norm = nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.proj(x)
        return x.flatten(2).transpose(1, 2)


class Attention(nn.Module):
    def __init__(self, dim: int, num_heads: int) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, n, c = x.shape
        qkv = self.qkv(x).reshape(b, n, 3, self.num_heads, c // self.num_heads).permute(2, 0, 3, 1, 4)
        x = F.scaled_dot_product_attention(qkv[0], qkv[1], qkv[2])
        return self.proj(x.transpose(1, 2).reshape(b, n, c))


class LayerScale(nn.Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * self.gamma


class Mlp(nn.Module):
    def __init__(self, dim: int, hidden: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.act(self.fc1(x)))


class Block(nn.Module):
    def __init__(self, dim: int, num_heads: int, mlp_ratio: float = 4.0) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-6)
        self.attn = Attention(dim, num_heads)
        self.ls1 = LayerScale(dim)
        self.norm2 = nn.LayerNorm(dim, eps=1e-6)
        self.mlp = Mlp(dim, int(dim * mlp_ratio))
        self.ls2 = LayerScale(dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.ls1(self.attn(self.norm1(x)))
        return x + self.ls2(self.mlp(self.norm2(x)))


class DinoVisionTransformer(nn.Module):
    def __init__(self, embed_dim: int, depth: int, num_heads: int, patch_size: int = 14, img_size: int = 518) -> None:
        super().__init__()
        self.patch_size = patch_size
        self.embed_dim = embed_dim
        self.patch_embed = PatchEmbed(img_size, patch_size, 3, embed_dim)
        n = self.patch_embed.num_patches
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, n + 1, embed_dim))
        self.blocks = nn.ModuleList([Block(embed_dim, num_heads) for _ in range(depth)])
        self.norm = nn.LayerNorm(embed_dim, eps=1e-6)
        self.head = nn.Identity()
        self.mask_token = nn.Parameter(torch.zeros(1, embed_dim))
        self._lage_cache: dict[tuple[int, int, str, torch.dtype], torch.Tensor] = {}

    def interpolate_pos_encoding(self, x: torch.Tensor, w: int, h: int) -> torch.Tensor:
        """Lageeinbettung für ein Bild mit w × h Pixeln (w = Höhe, h = Breite wie im Original), wie DINOv2 in der
        PromptDA-Fassung: bikubisch mit dem Versatz 0,1; je Größe einmal auf der CPU gerechnet."""
        npatch = x.shape[1] - 1
        n = self.pos_embed.shape[1] - 1
        if npatch == n and w == h:
            return self.pos_embed
        schl = (w, h, str(x.device), x.dtype)
        if schl in self._lage_cache:
            return self._lage_cache[schl]
        pe = self.pos_embed.detach().float().cpu()
        cls_pe, patch_pe = pe[:, 0], pe[:, 1:]
        dim = x.shape[-1]
        w0, h0 = w // self.patch_size + 0.1, h // self.patch_size + 0.1
        s = int(math.sqrt(n))
        patch_pe = F.interpolate(patch_pe.reshape(1, s, s, dim).permute(0, 3, 1, 2),
                                 scale_factor=(w0 / math.sqrt(n), h0 / math.sqrt(n)), mode="bicubic")
        assert int(w0) == patch_pe.shape[-2] and int(h0) == patch_pe.shape[-1]
        patch_pe = patch_pe.permute(0, 2, 3, 1).reshape(1, -1, dim)
        out = torch.cat((cls_pe.unsqueeze(0), patch_pe), dim=1).to(device=x.device, dtype=x.dtype)
        self._lage_cache[schl] = out
        return out

    def prepare_tokens(self, x: torch.Tensor) -> torch.Tensor:
        _, _, w, h = x.shape
        x = self.patch_embed(x)
        x = torch.cat((self.cls_token.expand(x.shape[0], -1, -1).to(x.dtype), x), dim=1)
        return x + self.interpolate_pos_encoding(x, w, h)

    def get_intermediate_layers(self, x: torch.Tensor, n: list[int], return_class_token: bool = True,
                                norm: bool = True):
        x = self.prepare_tokens(x)
        out = []
        for i, blk in enumerate(self.blocks):
            x = blk(x)
            if i in n:
                out.append(x)
        if norm:
            out = [self.norm(o) for o in out]
        cls = [o[:, 0] for o in out]
        out = [o[:, 1:] for o in out]
        if return_class_token:
            return tuple(zip(out, cls))
        return tuple(out)


def vit(encoder: str) -> DinoVisionTransformer:
    """ViT-S/14 oder ViT-L/14 (img_size 518 wie hubconf von DINOv2)."""
    if encoder == "vits":
        return DinoVisionTransformer(embed_dim=384, depth=12, num_heads=6)
    if encoder == "vitb":
        return DinoVisionTransformer(embed_dim=768, depth=12, num_heads=12)
    if encoder == "vitl":
        return DinoVisionTransformer(embed_dim=1024, depth=24, num_heads=16)
    raise ValueError(f"Encoder {encoder!r} unbekannt (vits, vitb, vitl)")

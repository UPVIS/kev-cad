# Copyright (c) 2024, Depth Anything V2 / PromptDA (Haotong Lin u. a.). Licensed under the Apache License, Version 2.0.
# Aus PromptDA (https://github.com/DepthAnything/PromptDA): promptda/model/dpt.py und promptda/model/blocks.py,
# für Kev Scan gekürzt auf die Vorhersage (ohne quantisierte Addition, ohne ungenutzte Blöcke, siehe __init__.py).
"""DPT-Kopf von PromptDA mit Tiefen-Prompt in jeder Fusionsstufe (Schichtnamen wie im Original)."""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


class ResidualConvUnit(nn.Module):
    def __init__(self, features: int, activation: nn.Module) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(features, features, kernel_size=3, stride=1, padding=1, bias=True)
        self.conv2 = nn.Conv2d(features, features, kernel_size=3, stride=1, padding=1, bias=True)
        self.activation = activation

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.conv1(self.activation(x))
        out = self.conv2(self.activation(out))
        return out + x


class FeatureFusionDepthBlock(nn.Module):
    """Fusion zweier Stufen, dazu die Prompt-Tiefe (auf die Stufengröße gebracht) als Restglied."""

    def __init__(self, features: int) -> None:
        super().__init__()
        act = nn.ReLU(False)
        self.out_conv = nn.Conv2d(features, features, kernel_size=1, stride=1, padding=0, bias=True)
        self.resConfUnit1 = ResidualConvUnit(features, act)
        self.resConfUnit2 = ResidualConvUnit(features, act)
        self.resConfUnit_depth = nn.Sequential(
            nn.Conv2d(1, features, kernel_size=3, stride=1, padding=1, bias=True), act,
            nn.Conv2d(features, features, kernel_size=3, stride=1, padding=1, bias=True), act,
            nn.Conv2d(features, features, kernel_size=3, stride=1, padding=1, bias=True))

    def forward(self, *xs: torch.Tensor, prompt_depth: torch.Tensor | None = None, size=None) -> torch.Tensor:
        output = xs[0]
        if len(xs) == 2:
            output = output + self.resConfUnit1(xs[1])
        output = self.resConfUnit2(output)
        if prompt_depth is not None:
            pd = F.interpolate(prompt_depth, output.shape[2:], mode="bilinear", align_corners=False)
            output = output + self.resConfUnit_depth(pd)
        modifier = {"scale_factor": 2} if size is None else {"size": size}
        output = F.interpolate(output, **modifier, mode="bilinear", align_corners=True)
        return self.out_conv(output)


class DPTHead(nn.Module):
    def __init__(self, in_channels: int, features: int, out_channels: list[int]) -> None:
        super().__init__()
        self.projects = nn.ModuleList([nn.Conv2d(in_channels, oc, kernel_size=1, stride=1, padding=0)
                                       for oc in out_channels])
        self.resize_layers = nn.ModuleList([
            nn.ConvTranspose2d(out_channels[0], out_channels[0], kernel_size=4, stride=4, padding=0),
            nn.ConvTranspose2d(out_channels[1], out_channels[1], kernel_size=2, stride=2, padding=0),
            nn.Identity(),
            nn.Conv2d(out_channels[3], out_channels[3], kernel_size=3, stride=2, padding=1)])
        s = nn.Module()
        s.layer1_rn = nn.Conv2d(out_channels[0], features, kernel_size=3, stride=1, padding=1, bias=False)
        s.layer2_rn = nn.Conv2d(out_channels[1], features, kernel_size=3, stride=1, padding=1, bias=False)
        s.layer3_rn = nn.Conv2d(out_channels[2], features, kernel_size=3, stride=1, padding=1, bias=False)
        s.layer4_rn = nn.Conv2d(out_channels[3], features, kernel_size=3, stride=1, padding=1, bias=False)
        s.refinenet1 = FeatureFusionDepthBlock(features)
        s.refinenet2 = FeatureFusionDepthBlock(features)
        s.refinenet3 = FeatureFusionDepthBlock(features)
        s.refinenet4 = FeatureFusionDepthBlock(features)
        head_features_1, head_features_2 = features, 32
        s.output_conv1 = nn.Conv2d(head_features_1, head_features_1 // 2, kernel_size=3, stride=1, padding=1)
        s.output_conv2 = nn.Sequential(
            nn.Conv2d(head_features_1 // 2, head_features_2, kernel_size=3, stride=1, padding=1), nn.ReLU(True),
            nn.Conv2d(head_features_2, 1, kernel_size=1, stride=1, padding=0), nn.Sigmoid())
        self.scratch = s

    def forward(self, out_features, patch_h: int, patch_w: int, prompt_depth: torch.Tensor) -> torch.Tensor:
        out = []
        for i, x in enumerate(out_features):
            x = x[0]
            x = x.permute(0, 2, 1).reshape((x.shape[0], x.shape[-1], patch_h, patch_w))
            x = self.resize_layers[i](self.projects[i](x))
            out.append(x)
        l1, l2, l3, l4 = out
        s = self.scratch
        l1, l2, l3, l4 = s.layer1_rn(l1), s.layer2_rn(l2), s.layer3_rn(l3), s.layer4_rn(l4)
        p4 = s.refinenet4(l4, size=l3.shape[2:], prompt_depth=prompt_depth)
        p3 = s.refinenet3(p4, l3, size=l2.shape[2:], prompt_depth=prompt_depth)
        p2 = s.refinenet2(p3, l2, size=l1.shape[2:], prompt_depth=prompt_depth)
        p1 = s.refinenet1(p2, l1, prompt_depth=prompt_depth)
        x = s.output_conv1(p1)
        x = F.interpolate(x, (int(patch_h * 14), int(patch_w * 14)), mode="bilinear", align_corners=True)
        return s.output_conv2(x)

"""Small deterministic multiscale occurrence residual model for A5B."""

from __future__ import annotations

import torch
from torch import Tensor, nn


class ShellMeanGraphSAGE(nn.Module):
    """One shell-specific mean-aggregation operator with explicit self information."""

    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(2 * input_dim, output_dim)
        self.activation = nn.ReLU()

    def forward(self, x: Tensor, source: Tensor, target: Tensor, degree: Tensor) -> Tensor:
        neighbor_sum = torch.zeros_like(x)
        neighbor_sum.index_add_(0, target, x[source])
        neighbor_mean = neighbor_sum / degree.clamp_min(1.0).unsqueeze(1)
        return self.activation(self.linear(torch.cat([x, neighbor_mean], dim=1)))


class MultiscaleOccurrenceResidualModel(nn.Module):
    """Four independent shell operators followed by a shallow residual head."""

    def __init__(self, input_dim: int, shell_count: int = 4, shell_hidden_dim: int = 8, post_hidden_dim: int = 8, dropout: float = 0.1) -> None:
        super().__init__()
        if shell_count != 4:
            raise ValueError("A5B requires exactly four graph-distance shells")
        self.shell_layers = nn.ModuleList([ShellMeanGraphSAGE(input_dim, shell_hidden_dim) for _ in range(shell_count)])
        self.post = nn.Sequential(
            nn.Linear(shell_count * shell_hidden_dim, post_hidden_dim),
            nn.ReLU(),
            nn.Dropout(float(dropout)),
            nn.Linear(post_hidden_dim, 1),
        )

    def forward(self, x: Tensor, shell_sources: list[Tensor], shell_targets: list[Tensor], shell_degrees: list[Tensor]) -> Tensor:
        if not (len(shell_sources) == len(shell_targets) == len(shell_degrees) == len(self.shell_layers) == 4):
            raise ValueError("A5B shell tensors must contain exactly four relations")
        representations = [
            layer(x, source, target, degree)
            for layer, source, target, degree in zip(self.shell_layers, shell_sources, shell_targets, shell_degrees)
        ]
        return self.post(torch.cat(representations, dim=1)).squeeze(-1)


def parameter_count(model: nn.Module) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))

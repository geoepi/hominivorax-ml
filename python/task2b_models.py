"""Task-2B recurrent hurdle models."""

from __future__ import annotations

import torch
from torch import Tensor, nn

from hurdle_zt_nb import positive_parameter


class HurdleHeads(nn.Module):
    def __init__(self, hidden: int, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.occurrence = nn.Linear(hidden, 1)
        self.count_mean = nn.Linear(hidden, 1)
        self.raw_theta = nn.Parameter(torch.tensor(1.0))

    def project(self, hidden: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        hidden = self.dropout(torch.tanh(hidden))
        logits = self.occurrence(hidden).squeeze(-1)
        mu = positive_parameter(self.count_mean(hidden).squeeze(-1))
        theta = positive_parameter(self.raw_theta)
        return logits, mu, theta


class GRUHurdleNB(nn.Module):
    model_name = "GRU-Hurdle-NB"

    def __init__(self, input_size: int, hidden_size: int, dropout: float = 0.1) -> None:
        super().__init__()
        self.recurrent = nn.GRU(input_size, hidden_size, num_layers=1)
        self.heads = HurdleHeads(hidden_size, dropout)

    def step(self, x: Tensor, hidden: Tensor | None = None) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        output, hidden = self.recurrent(x.unsqueeze(0), hidden)
        logits, mu, theta = self.heads.project(output.squeeze(0))
        return logits, mu, theta, hidden


class GConvGRUHurdleNB(nn.Module):
    model_name = "GConvGRU-Hurdle-NB"

    def __init__(self, input_size: int, hidden_size: int, k: int, dropout: float = 0.1, normalization: str = "sym") -> None:
        super().__init__()
        from torch_geometric_temporal.nn.recurrent import GConvGRU

        self.k = int(k)
        self.normalization = normalization
        self.recurrent = GConvGRU(
            in_channels=input_size,
            out_channels=hidden_size,
            K=self.k,
            normalization=normalization,
        )
        self.heads = HurdleHeads(hidden_size, dropout)

    def step(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_weight: Tensor | None = None,
        hidden: Tensor | None = None,
    ) -> tuple[Tensor, Tensor, Tensor, Tensor]:
        hidden = self.recurrent(x, edge_index, edge_weight=edge_weight, H=hidden)
        logits, mu, theta = self.heads.project(hidden)
        return logits, mu, theta, hidden


def model_metadata(model: nn.Module) -> dict[str, object]:
    return {
        "model_type": getattr(model, "model_name", model.__class__.__name__),
        "parameter_count": int(sum(p.numel() for p in model.parameters())),
    }

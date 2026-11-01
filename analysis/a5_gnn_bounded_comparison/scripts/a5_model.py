"""Small deterministic model and diagnostic primitives for the A5 experiment."""

from __future__ import annotations

import math
import random
from typing import Iterable

import numpy as np
import torch
from scipy.sparse import csr_matrix, eye, identity
from scipy.sparse.linalg import eigsh
from torch import Tensor, nn
from torch.nn import functional as F


THETA = 0.7018903965556372
EPS = 1e-8


def set_seed(seed: int) -> dict[str, object]:
    """Set all available RNGs and deterministic-operation flags."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    return {
        "seed": int(seed),
        "torch_deterministic_algorithms": True,
        "torch_deterministic_warn_only": True,
        "cudnn_deterministic": bool(getattr(torch.backends.cudnn, "deterministic", False)),
        "cudnn_benchmark": bool(getattr(torch.backends.cudnn, "benchmark", False)),
    }


def _log1mexp_torch(log_x: Tensor) -> Tensor:
    """Stable log(1-exp(x)) for x <= 0."""
    threshold = -math.log(2.0)
    safe = torch.minimum(log_x, torch.full_like(log_x, -EPS))
    return torch.where(
        safe < threshold,
        torch.log1p(-torch.exp(safe)),
        torch.log(torch.clamp(-torch.expm1(safe), min=EPS)),
    )


def _zt_nb_log_prob_torch(count: Tensor, log_mu: Tensor, theta: float) -> Tensor:
    theta_t = torch.as_tensor(float(theta), dtype=log_mu.dtype, device=log_mu.device)
    log_theta = torch.log(theta_t)
    log_mu = torch.clamp(log_mu, -20.0, 20.0)
    log_denom = torch.logaddexp(log_theta, log_mu)
    log_p0 = theta_t * (log_theta - log_denom)
    log_positive = _log1mexp_torch(log_p0)
    y = count.to(log_mu.dtype)
    log_pmf = (
        torch.lgamma(y + theta_t)
        - torch.lgamma(theta_t)
        - torch.lgamma(y + 1.0)
        + theta_t * (log_theta - log_denom)
        + y * (log_mu - log_denom)
    )
    return log_pmf - log_positive


def exact_joint_hurdle_nll(
    count: Tensor,
    occurrence_logit: Tensor,
    count_log_mean: Tensor,
    theta: float = THETA,
    mask: Tensor | None = None,
) -> Tensor:
    """Exact observation-level hurdle NLL used by A3 and A5."""
    if count.shape != occurrence_logit.shape or count.shape != count_log_mean.shape:
        raise ValueError("count and both predictor tensors must have identical shapes")
    positive = count > 0
    occurrence_nll = torch.where(
        positive,
        F.softplus(-occurrence_logit),
        F.softplus(occurrence_logit),
    )
    count_nll = -_zt_nb_log_prob_torch(count, count_log_mean, theta)
    loss = occurrence_nll + torch.where(positive, count_nll, torch.zeros_like(count_nll))
    if mask is not None:
        selected = mask.to(dtype=torch.bool)
        if selected.shape != loss.shape:
            raise ValueError("hurdle loss mask has the wrong shape")
        loss = loss[selected]
    if loss.numel() == 0:
        raise ValueError("exact hurdle loss received an empty mask")
    return loss.mean()


def exact_joint_hurdle_nll_numpy(
    count: np.ndarray,
    occurrence_logit: np.ndarray,
    count_log_mean: np.ndarray,
    theta: float = THETA,
    mask: np.ndarray | None = None,
) -> float:
    """Independent NumPy reference implementation for contract tests."""
    from scipy.special import gammaln

    y = np.asarray(count, dtype=np.float64)
    occ = np.asarray(occurrence_logit, dtype=np.float64)
    log_mu = np.clip(np.asarray(count_log_mean, dtype=np.float64), -20.0, 20.0)
    if y.shape != occ.shape or y.shape != log_mu.shape:
        raise ValueError("count and both predictor arrays must have identical shapes")
    positive = y > 0
    occurrence_nll = np.where(positive, np.logaddexp(0.0, -occ), np.logaddexp(0.0, occ))
    log_theta = math.log(float(theta))
    log_denom = np.logaddexp(log_theta, log_mu)
    log_p0 = float(theta) * (log_theta - log_denom)
    log_positive = np.where(
        log_p0 < -math.log(2.0),
        np.log1p(-np.exp(log_p0)),
        np.log(np.maximum(-np.expm1(log_p0), EPS)),
    )
    log_pmf = (
        gammaln(y + float(theta))
        - gammaln(float(theta))
        - gammaln(y + 1.0)
        + float(theta) * (log_theta - log_denom)
        + y * (log_mu - log_denom)
    )
    loss = occurrence_nll + np.where(positive, -(log_pmf - log_positive), 0.0)
    if mask is not None:
        selected = np.asarray(mask, dtype=bool)
        loss = loss[selected]
    if loss.size == 0:
        raise ValueError("exact hurdle loss received an empty mask")
    return float(np.mean(loss))


def hurdle_predictions(occurrence_logit: Tensor, count_log_mean: Tensor, theta: float = THETA) -> tuple[Tensor, Tensor, Tensor]:
    """Return occurrence probability, conditional positive mean, and mean."""
    probability = torch.sigmoid(occurrence_logit)
    log_mu = torch.clamp(count_log_mean, -20.0, 20.0)
    theta_t = torch.as_tensor(float(theta), dtype=log_mu.dtype, device=log_mu.device)
    log_p0 = theta_t * (torch.log(theta_t) - torch.logaddexp(torch.log(theta_t), log_mu))
    positive_probability = torch.clamp(-torch.expm1(log_p0), min=EPS)
    conditional = torch.exp(log_mu) / positive_probability
    return probability, conditional, probability * conditional


def center_residual(residual: Tensor) -> Tensor:
    """Center a [node] residual deterministically across all nodes."""
    if residual.ndim != 1:
        raise ValueError("residual must be a one-dimensional node vector")
    return residual - residual.mean()


class MeanGraphSAGELayer(nn.Module):
    """GraphSAGE mean aggregation with explicit self-information."""

    def __init__(self, input_dim: int, output_dim: int, activation: str = "relu") -> None:
        super().__init__()
        self.linear = nn.Linear(2 * input_dim, output_dim)
        if activation == "relu":
            self.activation = nn.ReLU()
        elif activation == "gelu":
            self.activation = nn.GELU()
        else:
            raise ValueError(f"unsupported activation: {activation}")

    def forward(self, x: Tensor, source: Tensor, target: Tensor, degree: Tensor) -> Tensor:
        neighbor_sum = torch.zeros_like(x)
        neighbor_sum.index_add_(0, target, x[source])
        neighbor_mean = neighbor_sum / degree.clamp_min(1.0).unsqueeze(1)
        return self.activation(self.linear(torch.cat([x, neighbor_mean], dim=1)))


class GraphSAGEResidualModel(nn.Module):
    """Two independent shallow GraphSAGE residual branches."""

    def __init__(self, input_dim: int, hidden_dim: int = 16, dropout: float = 0.1, activation: str = "relu") -> None:
        super().__init__()
        self.occurrence_layer1 = MeanGraphSAGELayer(input_dim, hidden_dim, activation)
        self.occurrence_layer2 = MeanGraphSAGELayer(hidden_dim, hidden_dim, activation)
        self.occurrence_head = nn.Linear(hidden_dim, 1)
        self.count_layer1 = MeanGraphSAGELayer(input_dim, hidden_dim, activation)
        self.count_layer2 = MeanGraphSAGELayer(hidden_dim, hidden_dim, activation)
        self.count_head = nn.Linear(hidden_dim, 1)
        self.dropout = nn.Dropout(float(dropout))

    def _branch(self, x: Tensor, source: Tensor, target: Tensor, degree: Tensor, prefix: str) -> Tensor:
        layer1 = getattr(self, f"{prefix}_layer1")(x, source, target, degree)
        layer1 = self.dropout(layer1)
        layer2 = getattr(self, f"{prefix}_layer2")(layer1, source, target, degree)
        layer2 = self.dropout(layer2)
        return getattr(self, f"{prefix}_head")(layer2).squeeze(-1)

    def forward(self, x: Tensor, source: Tensor, target: Tensor, degree: Tensor) -> tuple[Tensor, Tensor]:
        return (
            self._branch(x, source, target, degree, "occurrence"),
            self._branch(x, source, target, degree, "count"),
        )


class NodewiseMLPResidualModel(nn.Module):
    """Node-wise PE ablation with two independent residual branches."""

    def __init__(self, input_dim: int, hidden_dim: int = 16, dropout: float = 0.1, activation: str = "relu") -> None:
        super().__init__()
        act = nn.ReLU if activation == "relu" else nn.GELU
        self.occurrence = nn.Sequential(nn.Linear(input_dim, hidden_dim), act(), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim), act(), nn.Dropout(dropout), nn.Linear(hidden_dim, 1))
        self.count = nn.Sequential(nn.Linear(input_dim, hidden_dim), act(), nn.Dropout(dropout), nn.Linear(hidden_dim, hidden_dim), act(), nn.Dropout(dropout), nn.Linear(hidden_dim, 1))

    def forward(self, x: Tensor, source: Tensor | None = None, target: Tensor | None = None, degree: Tensor | None = None) -> tuple[Tensor, Tensor]:
        del source, target, degree
        return self.occurrence(x).squeeze(-1), self.count(x).squeeze(-1)


def parameter_count(model: nn.Module) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))


def make_model(candidate: str, input_dim: int, hidden_dim: int = 16, dropout: float = 0.1, activation: str = "relu") -> nn.Module:
    if candidate == "A5-PE":
        return NodewiseMLPResidualModel(input_dim, hidden_dim, dropout, activation)
    if candidate in {"A5-GNN", "A5-GNN-NOPE"}:
        return GraphSAGEResidualModel(input_dim, hidden_dim, dropout, activation)
    raise ValueError(f"unknown neural candidate: {candidate}")


def canonical_directed_edges(source: Iterable[int], target: Iterable[int], node_count: int) -> tuple[np.ndarray, np.ndarray]:
    """Return sorted unique bidirectional, non-self edges."""
    source_arr = np.asarray(list(source), dtype=np.int64)
    target_arr = np.asarray(list(target), dtype=np.int64)
    if source_arr.shape != target_arr.shape:
        raise ValueError("source and target edge vectors have different lengths")
    if ((source_arr < 0) | (source_arr >= node_count) | (target_arr < 0) | (target_arr >= node_count)).any():
        raise ValueError("graph edge is outside the node domain")
    pairs = np.concatenate([
        np.column_stack([source_arr, target_arr]),
        np.column_stack([target_arr, source_arr]),
    ])
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]
    pairs = np.unique(pairs, axis=0)
    order = np.lexsort((pairs[:, 1], pairs[:, 0]))
    pairs = pairs[order]
    return pairs[:, 0], pairs[:, 1]


def normalized_laplacian(adjacency: csr_matrix) -> csr_matrix:
    degree = np.asarray(adjacency.sum(axis=1)).ravel().astype(np.float64)
    inv_sqrt = np.zeros_like(degree)
    nonzero = degree > 0
    inv_sqrt[nonzero] = 1.0 / np.sqrt(degree[nonzero])
    diagonal = csr_matrix((inv_sqrt, (np.arange(len(degree)), np.arange(len(degree)))), shape=adjacency.shape)
    result = identity(adjacency.shape[0], format="csr", dtype=np.float64) - diagonal @ adjacency @ diagonal
    isolated = np.flatnonzero(~nonzero)
    if len(isolated):
        result[isolated, isolated] = 0.0
    return result.tocsr()


def laplacian_positional_encoding(adjacency: csr_matrix, coordinates: np.ndarray, n_components: int = 8) -> tuple[np.ndarray, dict[str, object]]:
    """Create response-independent standardized coordinates and signed eigenvectors."""
    coordinates = np.asarray(coordinates, dtype=np.float64)
    if coordinates.ndim != 2 or coordinates.shape[1] != 2 or not np.isfinite(coordinates).all():
        raise ValueError("coordinates must be a finite [node, 2] array")
    coord_mean = coordinates.mean(axis=0)
    coord_sd = coordinates.std(axis=0)
    coord_sd = np.where(coord_sd > 0, coord_sd, 1.0)
    standardized = (coordinates - coord_mean) / coord_sd
    laplacian = normalized_laplacian(adjacency)
    k = min(adjacency.shape[0] - 2, max(24, n_components + 12))
    v0 = np.arange(1, adjacency.shape[0] + 1, dtype=np.float64)
    v0 /= np.linalg.norm(v0)
    eigenvalues, eigenvectors = eigsh(laplacian, k=k, which="SM", v0=v0, tol=1e-8, maxiter=200000)
    order = np.argsort(eigenvalues, kind="stable")
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    selected: list[np.ndarray] = []
    selected_values: list[float] = []
    for value, vector in zip(eigenvalues, eigenvectors.T):
        if value <= 1e-7:
            continue
        signed = np.asarray(vector, dtype=np.float64).copy()
        pivot = int(np.argmax(np.abs(signed)))
        if signed[pivot] < 0:
            signed *= -1.0
        selected.append(signed)
        selected_values.append(float(value))
        if len(selected) == n_components:
            break
    if len(selected) != n_components:
        raise RuntimeError(f"only {len(selected)} nontrivial Laplacian eigenvectors were available")
    eigen = np.column_stack(selected)
    encoding = np.concatenate([standardized, eigen], axis=1)
    metadata = {
        "coordinate_mean": coord_mean.tolist(),
        "coordinate_sd": coord_sd.tolist(),
        "eigenvalues": selected_values,
        "eigenvector_count": int(n_components),
        "orientation": "entry with maximum absolute value is positive",
    }
    return encoding, metadata


def deterministic_spatial_shells(adjacency: csr_matrix, max_shell: int = 4) -> dict[int, csr_matrix]:
    """Build exact shortest-path shells without materializing dense distances."""
    adjacency = adjacency.tocsr(copy=True)
    adjacency.data[:] = 1.0
    adjacency.eliminate_zeros()
    reachable = identity(adjacency.shape[0], format="csr", dtype=np.float64)
    frontier = adjacency.copy()
    shells: dict[int, csr_matrix] = {}
    for shell_id in range(1, max_shell + 1):
        shell = frontier - frontier.multiply(reachable)
        shell.eliminate_zeros()
        shell.data[:] = 1.0
        shells[shell_id] = shell.tocsr()
        reachable = reachable + shell
        reachable.data[:] = 1.0
        reachable.eliminate_zeros()
        frontier = shell @ adjacency
        frontier.eliminate_zeros()
        frontier.data[:] = 1.0
    return shells

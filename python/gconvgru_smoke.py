#!/usr/bin/env python3
"""Tiny GPU-only GConvGRU forward/backward smoke test."""

from __future__ import annotations

import json
import platform


def main() -> int:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available; run this smoke test on an allocated GPU node")

    from torch_geometric_temporal.nn.recurrent import GConvGRU

    device = torch.device("cuda")
    x = torch.tensor(
        [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.25]],
        dtype=torch.float32,
        device=device,
    )
    edge_index = torch.tensor(
        [[0, 1, 1, 2, 2, 3, 3, 0], [1, 0, 2, 1, 3, 2, 0, 3]],
        dtype=torch.long,
        device=device,
    )

    model = GConvGRU(in_channels=2, out_channels=4, K=2).to(device)
    hidden = model(x, edge_index)
    if tuple(hidden.shape) != (4, 4):
        raise AssertionError(f"unexpected hidden-state shape: {tuple(hidden.shape)}")

    loss = hidden.square().mean()
    loss.backward()
    gradients = [
        parameter.grad
        for parameter in model.parameters()
        if parameter.requires_grad
    ]
    if not gradients or not all(
        gradient is not None and torch.isfinite(gradient).all().item()
        for gradient in gradients
    ):
        raise AssertionError("one or more trainable parameters lacks finite gradients")

    result = {
        "python": platform.python_version(),
        "pytorch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "device": torch.cuda.get_device_name(device),
        "input_shape": list(x.shape),
        "edge_index_shape": list(edge_index.shape),
        "hidden_shape": list(hidden.shape),
        "loss": float(loss.detach().cpu()),
        "finite_gradients": True,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

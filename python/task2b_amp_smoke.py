"""Validate mixed-precision forward/backward on an allocated CUDA device."""

from __future__ import annotations

import json
import torch

from hurdle_zt_nb import hurdle_losses
from task2b_models import GConvGRUHurdleNB


def main() -> None:
    if not torch.cuda.is_available(): raise RuntimeError("CUDA unavailable")
    device = torch.device("cuda")
    torch.manual_seed(20261002)
    model = GConvGRUHurdleNB(24, 8, 2, 0.1).to(device)
    x = torch.randn(3, 4, 24, device=device)
    counts = torch.tensor([[0., 1., 0., 2.], [1., 0., 0., 3.], [0., 0., 1., 0.]], device=device)
    edge = torch.tensor([[0, 1, 1, 2, 2, 3, 3, 0], [1, 0, 2, 1, 3, 2, 0, 3]], device=device)
    weight = torch.ones(edge.shape[1], device=device)
    hidden = None; losses = []
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        for t in range(3):
            logits, mu, theta, hidden = model.step(x[t], edge, weight, hidden)
            # Keep likelihood arithmetic in float32.
            losses.append(hurdle_losses(logits.float(), mu.float(), model.heads.raw_theta.float(), counts[t])["optimization_loss"])
    loss = torch.stack(losses).mean()
    loss.backward()
    finite = bool(torch.isfinite(loss).item()) and all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in model.parameters() if p.requires_grad)
    if not finite: raise RuntimeError("mixed-precision loss or gradients are non-finite")
    print(json.dumps({"cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(device), "loss": float(loss.detach().cpu()), "finite_gradients": finite, "dtype": "float16 autocast with float32 likelihood"}, indent=2))


if __name__ == "__main__":
    main()

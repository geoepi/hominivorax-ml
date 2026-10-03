from __future__ import annotations

import torch

from task2b_models import GConvGRUHurdleNB, GRUHurdleNB
from hurdle_zt_nb import hurdle_losses


def one(model, graph: bool) -> None:
    x = torch.randn(3, 4, 24)
    count = torch.tensor([[0., 1., 0., 2.], [1., 0., 0., 3.], [0., 0., 1., 0.]])
    hidden = None
    edge = torch.tensor([[0, 1, 1, 2, 2, 3, 3, 0], [1, 0, 2, 1, 3, 2, 0, 3]], dtype=torch.long)
    weight = torch.ones(edge.shape[1])
    losses = []
    for t in range(3):
        if graph:
            logits, mu, theta, hidden = model.step(x[t], edge, weight, hidden)
        else:
            logits, mu, theta, hidden = model.step(x[t], hidden)
        losses.append(hurdle_losses(logits, mu, model.heads.raw_theta, count[t])["optimization_loss"])
    loss = torch.stack(losses).mean()
    loss.backward()
    if not torch.isfinite(loss): raise AssertionError("non-finite model loss")
    if not all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters() if p.requires_grad): raise AssertionError("non-finite model gradient")


if __name__ == "__main__":
    one(GRUHurdleNB(24, 8, 0.1), False)
    one(GConvGRUHurdleNB(24, 8, 2, 0.1), True)
    print("Task-2B model smoke: PASS")

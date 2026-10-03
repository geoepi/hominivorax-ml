#!/usr/bin/env python3
"""Recompute stored development metrics from checkpoints, including weekly summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import numpy as np
import torch

from task2b_models import GConvGRUHurdleNB, GRUHurdleNB
from task2b_pipeline import (N_CONTEXT, assert_dataset, assert_development_only,
                             build_features, exact_metrics, load_data, make_masks,
                             step_model)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pattern", default="*_temporal_all_*.json")
    args = parser.parse_args()
    if not torch.cuda.is_available(): raise RuntimeError("postprocessing requires CUDA")
    data = load_data(args.output_root); assert_dataset(data)
    device = torch.device("cuda")
    cache = {}
    for path in sorted((args.output_root / "runs/task2b").glob(args.pattern)):
        record = json.loads(path.read_text())
        if record.get("final_test_predictive_metrics_calculated") is not False: continue
        key = (int(record["fold"]), record.get("feature_variant", "all"))
        if key not in cache:
            features, _ = build_features(data, key[0])
            if key[1] == "without_livestock": features = np.concatenate([features[:, :, :12], features[:, :, 22:]], axis=2)
            elif key[1] == "without_calendar": features = features[:, :, :22]
            cache[key] = torch.as_tensor(features, dtype=torch.float32, device=device)
        x = cache[key]
        train_mask, eval_mask = make_masks(data, int(record["fold"]), record["regime"], record.get("spatial_fold"))
        assert_development_only(eval_mask, data, "development")
        model = (GConvGRUHurdleNB(x.shape[2], int(record["hidden_size"]), int(record["K"]), float(record["dropout"])).to(device)
                 if record["model"] == "gconvgru" else GRUHurdleNB(x.shape[2], int(record["hidden_size"]), float(record["dropout"])).to(device))
        checkpoint = torch.load(args.output_root / "models/task2b" / f"{record['run_id']}.pt", map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["state_dict"]); model.eval()
        edge = torch.as_tensor(data["edges"][["source_node", "target_node"]].to_numpy(np.int64).T.copy(), dtype=torch.long, device=device)
        weight = torch.ones(edge.shape[1], device=device) if record["model"] == "gconvgru" else None
        eval_indices = np.where(eval_mask.any(axis=1))[0]
        last = N_CONTEXT + int(eval_indices[-1]) + 1
        hidden = None; logits = []; mu_rows = []; theta = None
        with torch.no_grad():
            for t in range(N_CONTEXT):
                _, _, _, hidden = step_model(model, record["model"], x[t], edge, weight, hidden)
            for t in range(N_CONTEXT, last):
                out_logits, out_mu, out_theta, hidden = step_model(model, record["model"], x[t], edge, weight, hidden)
                logits.append(out_logits.cpu().numpy()); mu_rows.append(out_mu.cpu().numpy()); theta = float(out_theta.cpu())
        logits = np.asarray(logits)[eval_indices[0]:eval_indices[-1] + 1]
        mu = np.asarray(mu_rows)[eval_indices[0]:eval_indices[-1] + 1]
        selected = eval_mask[eval_indices[0]:eval_indices[-1] + 1]
        counts = np.asarray(data["counts"])[eval_indices[0]:eval_indices[-1] + 1]
        record["metrics"] = exact_metrics(counts[selected], logits[selected], mu[selected], theta)
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        p0 = theta * (np.log(theta) - np.log(theta + np.maximum(mu, 1e-8)))
        conditional = np.maximum(mu, 1e-8) / np.maximum(-np.expm1(p0), 1e-8)
        expected = p * conditional
        record["metrics"].update({
            "weekly_observed_total": counts[selected].reshape(len(eval_indices), -1).sum(axis=1).tolist() if selected.all() else [float(counts[t][selected[t]].sum()) for t in range(len(selected))],
            "weekly_predicted_total": expected.reshape(len(eval_indices), -1).sum(axis=1).tolist(),
            "weekly_observed_positive_nodes": [int((counts[t][selected[t]] > 0).sum()) for t in range(len(selected))],
            "weekly_predicted_positive_nodes": p.reshape(len(eval_indices), -1).sum(axis=1).tolist(),
        })
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render the bounded P5A figure set from compact metric outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def save(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()


def render(root: Path) -> None:
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    metrics = pd.read_csv(root / "metrics" / "occurrence_count_metrics.csv")
    paired = pd.read_csv(root / "metrics" / "paired_proxy_minus_realized.csv")
    frontier = pd.read_csv(root / "metrics" / "frontier_metrics.csv")
    env = pd.read_csv(root / "metrics" / "environmental_proxy_error_by_family.csv")
    support = pd.read_csv(root / "metrics" / "support_metrics.csv")

    # P5A-1: issue-time proxy design schematic.
    fig, ax = plt.subplots(figsize=(11, 2.7))
    ax.axis("off")
    ax.text(0.02, 0.58, "Issue origin T", ha="left", va="center", fontsize=12, weight="bold")
    ax.text(0.20, 0.58, "T-3   T-2   T-1", ha="center", va="center", fontsize=11)
    ax.text(0.47, 0.58, "L(T)=T-1\nlatest safely prior state", ha="center", va="center", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#e8f1fb", edgecolor="#4472c4"))
    ax.text(0.74, 0.58, "E0: persist L(T)\nE1: mean T-1:T-3\nE2: same-week history\n(2 cycles required)", ha="center", va="center", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#f3f3f3", edgecolor="#666666"))
    ax.text(0.98, 0.58, "h=1   h=2   h=3\nexact frozen 34-column schema", ha="right", va="center", fontsize=10,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="#eaf4ea", edgecolor="#4b8b4b"))
    for x1, x2 in [(0.11, 0.18), (0.32, 0.40), (0.56, 0.67), (0.83, 0.94)]:
        ax.annotate("", xy=(x2, 0.58), xytext=(x1, 0.58), arrowprops=dict(arrowstyle="->", lw=1.5, color="#555555"))
    save(figures / "P5A-1_proxy_design.png")

    # P5A-2: occurrence performance by proxy and horizon.
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True)
    plot = metrics.loc[metrics["proxy_id"].isin(["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"])]
    for axis, metric, ylabel in [(axes[0], "brier", "Brier score (lower is better)"), (axes[1], "auprc", "AUPRC (higher is better)")]:
        for proxy_id, group in plot.groupby("proxy_id", sort=False):
            group = group.sort_values("horizon")
            axis.plot(group["horizon"], group[metric], marker="o", label=proxy_id)
        axis.set_xlabel("Horizon")
        axis.set_ylabel(ylabel)
        axis.set_xticks([1, 2, 3])
        axis.grid(alpha=0.25)
    axes[1].legend(fontsize=8)
    save(figures / "P5A-2_occurrence_performance.png")

    # P5A-3: paired degradation.
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharex=True)
    for axis, metric, ylabel in [(axes[0], "brier", "Proxy − realized Brier"), (axes[1], "auprc", "Proxy − realized AUPRC")]:
        work = paired.loc[(paired["metric"] == metric) & paired["proxy_id"].isin(["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"])]
        for proxy_id, group in work.groupby("proxy_id", sort=False):
            axis.plot(group["horizon"], group["difference_proxy_minus_realized"], marker="o", label=proxy_id)
        axis.axhline(0, color="#555555", lw=0.8)
        axis.set_xlabel("Horizon")
        axis.set_ylabel(ylabel)
        axis.set_xticks([1, 2, 3])
        axis.grid(alpha=0.25)
    axes[1].legend(fontsize=8)
    save(figures / "P5A-3_proxy_degradation.png")

    # P5A-4: frontier effect.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        p = frontier.loc[(frontier["proxy_id"] == proxy_id) & frontier["frontier_class"].eq("previously_unoccupied")].set_index("horizon")["brier"]
        r = frontier.loc[(frontier["proxy_id"] == "REALIZED_ENV") & frontier["frontier_class"].eq("previously_unoccupied")].set_index("horizon")["brier"]
        ax.plot([1, 2, 3], [(p.loc[h] - r.loc[h]) for h in [1, 2, 3]], marker="o", label=proxy_id)
    ax.axhline(0, color="#555555", lw=0.8)
    ax.set_xlabel("Horizon")
    ax.set_ylabel("Previously-unoccupied Brier difference")
    ax.set_xticks([1, 2, 3])
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    save(figures / "P5A-4_frontier_effect.png")

    # P5A-5: environmental error by family.
    fig, ax = plt.subplots(figsize=(10, 4.5))
    work = env.loc[env["proxy_id"].isin(["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"])]
    pivot = work.groupby(["proxy_id", "family"], as_index=False)["mae"].mean()
    pivot["label"] = pivot["proxy_id"].str.replace("_", " ") + " / " + pivot["family"]
    ax.bar(pivot["label"], pivot["mae"], color=["#4472c4" if value.startswith("E0") else "#70ad47" for value in pivot["proxy_id"]])
    ax.set_ylabel("Mean environmental MAE")
    ax.set_xlabel("Proxy / predictor family")
    ax.tick_params(axis="x", rotation=55, labelsize=8)
    ax.grid(axis="y", alpha=0.25)
    save(figures / "P5A-5_environmental_proxy_error.png")

    # P5A-6: support-class proportions.
    fig, ax = plt.subplots(figsize=(9, 4.5))
    order = ["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]
    classes = ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]
    wide = support.groupby(["proxy_id", "support_class"], as_index=False)["n"].sum().pivot(index="proxy_id", columns="support_class", values="n").fillna(0).reindex(order)
    wide = wide.div(wide.sum(axis=1), axis=0).reindex(columns=classes)
    bottom = np.zeros(len(wide))
    colors = {"SUPPORTED": "#70ad47", "CAUTION": "#ffc000", "EXTRAPOLATIVE": "#c00000"}
    for cls in classes:
        ax.bar(wide.index, wide[cls], bottom=bottom, label=cls, color=colors[cls])
        bottom += wide[cls].to_numpy()
    ax.set_ylim(0, 1)
    ax.set_ylabel("Proportion of evaluated rows")
    ax.set_xlabel("Environmental contract")
    ax.tick_params(axis="x", rotation=25)
    ax.legend(fontsize=8)
    save(figures / "P5A-6_support_class_impact.png")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    render(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

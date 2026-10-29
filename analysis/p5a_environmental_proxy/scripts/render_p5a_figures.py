#!/usr/bin/env python3
"""Render the bounded P5A figure set from compact metric outputs."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - exercised on the validated Atlas image
    plt = None


def save(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()


def svg_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def write_svg(path: Path, title: str, body: str, width: int = 1000, height: int = 500) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/>
<text x="40" y="34" font-family="Arial, sans-serif" font-size="20" font-weight="bold">{svg_escape(title)}</text>
{body}
</svg>
'''
    path.write_text(document, encoding="utf-8")


def svg_line_chart(path: Path, title: str, ylabel: str, series: list[tuple[str, list[float], str]],
                   y_min: float | None = None, y_max: float | None = None) -> None:
    width, height = 1000, 500
    left, right, top, bottom = 95, 40, 65, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, points, _ in series for value in points if np.isfinite(value)]
    if not values:
        values = [0.0, 1.0]
    lo = min(values) if y_min is None else y_min
    hi = max(values) if y_max is None else y_max
    if np.isclose(lo, hi):
        lo, hi = lo - 1.0, hi + 1.0
    pad = 0.06 * (hi - lo)
    lo -= pad
    hi += pad
    sx = lambda x: left + (x - 1) / 2 * plot_w
    sy = lambda y: top + (hi - y) / (hi - lo) * plot_h
    parts = [f'<text x="18" y="{top + plot_h / 2}" transform="rotate(-90 18 {top + plot_h / 2})" font-family="Arial" font-size="14">{svg_escape(ylabel)}</text>']
    for tick in np.linspace(lo, hi, 5):
        y = sy(float(tick))
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#dddddd"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial" font-size="12">{tick:.3g}</text>')
    for x in (1, 2, 3):
        parts.append(f'<line x1="{sx(x):.1f}" y1="{top}" x2="{sx(x):.1f}" y2="{top + plot_h}" stroke="#eeeeee"/>')
        parts.append(f'<text x="{sx(x):.1f}" y="{height - 35}" text-anchor="middle" font-family="Arial" font-size="13">h={x}</text>')
    colors = {"REALIZED_ENV": "#555555", "E0_LAST_AVAILABLE": "#4472c4", "E1_TRAILING3_MEAN": "#70ad47", "E2_SEASONAL_EXPECTATION": "#c00000"}
    for label, points, color in series:
        coords = [(sx(index + 1), sy(float(value))) for index, value in enumerate(points) if np.isfinite(value)]
        if not coords:
            continue
        points_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        line_color = colors.get(label, color)
        parts.append(f'<polyline points="{points_text}" fill="none" stroke="{line_color}" stroke-width="2.5"/>')
        for x, y in coords:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{line_color}"/>')
    legend_x = left + 15
    for index, (label, _, color) in enumerate(series):
        line_color = colors.get(label, color)
        x = legend_x + index * 210
        parts.append(f'<line x1="{x}" y1="{top - 22}" x2="{x + 22}" y2="{top - 22}" stroke="{line_color}" stroke-width="3"/>')
        parts.append(f'<text x="{x + 28}" y="{top - 17}" font-family="Arial" font-size="12">{svg_escape(label)}</text>')
    write_svg(path, title, "\n".join(parts), width, height)


def render_svg_fallback(root: Path) -> None:
    """Render a bounded, dependency-free SVG figure set on Atlas images without matplotlib."""
    figures = root / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    metrics = pd.read_csv(root / "metrics" / "occurrence_count_metrics.csv")
    paired = pd.read_csv(root / "metrics" / "paired_proxy_minus_realized.csv")
    frontier = pd.read_csv(root / "metrics" / "frontier_metrics.csv")
    env = pd.read_csv(root / "metrics" / "environmental_proxy_error_by_family.csv")
    support = pd.read_csv(root / "metrics" / "support_metrics.csv")
    contracts = ["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]
    colors = ["#555555", "#4472c4", "#70ad47"]

    design = '''<line x1="110" y1="235" x2="890" y2="235" stroke="#555" stroke-width="2" marker-end="url(#arrow)"/>
<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#555"/></marker></defs>
<g font-family="Arial" font-size="16" text-anchor="middle"><text x="110" y="190">issue T</text><text x="245" y="190">T-3 · T-2 · T-1</text><text x="430" y="190">L(T)=T-1</text><text x="650" y="190">E0: persist · E1: trailing 3 · E2: seasonal</text><text x="880" y="190">h=1,2,3</text></g>
<g font-family="Arial" font-size="13" text-anchor="middle"><rect x="55" y="260" width="115" height="45" fill="#e8f1fb" stroke="#4472c4"/><text x="112" y="287">availability cutoff</text><rect x="370" y="260" width="120" height="45" fill="#f3f3f3" stroke="#666"/><text x="430" y="287">proxy state</text><rect x="820" y="260" width="120" height="45" fill="#eaf4ea" stroke="#4b8b4b"/><text x="880" y="287">34 columns</text></g>'''
    write_svg(figures / "P5A-1_proxy_design.svg", "P5A-1 Issue-time proxy design", design, 1000, 360)

    def line_values(frame: pd.DataFrame, metric: str, proxy_id: str) -> list[float]:
        subset = frame.loc[frame["proxy_id"].eq(proxy_id)].sort_values("horizon")
        return [float(subset.loc[subset["horizon"].eq(h), metric].iloc[0]) if (subset["horizon"].eq(h)).any() else np.nan for h in (1, 2, 3)]

    for name, metric, ylabel in [("P5A-2_occurrence_performance.svg", "brier", "Brier score (lower is better)"), ("P5A-2_occurrence_auprc.svg", "auprc", "AUPRC (higher is better)")]:
        series = [(proxy, line_values(metrics, metric, proxy), color) for proxy, color in zip(contracts, colors)]
        svg_line_chart(figures / name, "P5A-2 Occurrence performance by contract", ylabel, series)
    for name, metric, ylabel in [("P5A-3_proxy_brier_degradation.svg", "brier", "Proxy − realized Brier"), ("P5A-3_proxy_auprc_degradation.svg", "auprc", "Proxy − realized AUPRC")]:
        series = [(proxy, line_values(paired.loc[paired["metric"].eq(metric)], "difference_proxy_minus_realized", proxy), color) for proxy, color in zip(contracts[1:], colors[1:])]
        svg_line_chart(figures / name, "P5A-3 Paired proxy degradation", ylabel, series, y_min=0.0 if metric == "brier" else None)

    frontier_series = []
    for proxy, color in zip(contracts[1:], colors[1:]):
        vals = []
        for horizon in (1, 2, 3):
            proxy_row = frontier.loc[(frontier["proxy_id"].eq(proxy)) & frontier["frontier_class"].eq("previously_unoccupied") & frontier["horizon"].eq(horizon), "brier"]
            real_row = frontier.loc[(frontier["proxy_id"].eq("REALIZED_ENV")) & frontier["frontier_class"].eq("previously_unoccupied") & frontier["horizon"].eq(horizon), "brier"]
            vals.append(float(proxy_row.iloc[0] - real_row.iloc[0]) if len(proxy_row) and len(real_row) else np.nan)
        frontier_series.append((proxy, vals, color))
    svg_line_chart(figures / "P5A-4_frontier_effect.svg", "P5A-4 Frontier effect", "Previously-unoccupied Brier difference", frontier_series)

    family = env.loc[env["proxy_id"].isin(contracts[1:])].groupby(["proxy_id", "family"], as_index=False)["mae"].mean()
    labels = [f"{row.proxy_id.replace('_', ' ')} / {row.family}" for row in family.itertuples()]
    values = [float(value) for value in family["mae"]]
    max_value = max(values) if values else 1.0
    bars = [f'<text x="70" y="{75 + i * 28}" font-family="Arial" font-size="12">{svg_escape(label)}</text><rect x="300" y="{61 + i * 28}" width="{620 * value / max_value:.1f}" height="17" fill="{colors[1] if "E0" in label else colors[2]}"/><text x="930" y="{75 + i * 28}" font-family="Arial" font-size="12">{value:.3g}</text>' for i, (label, value) in enumerate(zip(labels, values))]
    write_svg(figures / "P5A-5_environmental_proxy_error.svg", "P5A-5 Environmental proxy error by family", "\n".join(bars), 1000, max(180, 100 + 30 * len(bars)))

    wide = support.groupby(["proxy_id", "support_class"], as_index=False)["n"].sum().pivot(index="proxy_id", columns="support_class", values="n").fillna(0).reindex(contracts).fillna(0)
    wide = wide.div(wide.sum(axis=1), axis=0).fillna(0)
    classes = ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]
    class_colors = {"SUPPORTED": "#70ad47", "CAUTION": "#ffc000", "EXTRAPOLATIVE": "#c00000"}
    parts = []
    for i, proxy in enumerate(contracts):
        x = 150 + i * 250
        bottom = 0.0
        parts.append(f'<text x="{x + 55}" y="455" text-anchor="middle" font-family="Arial" font-size="12">{proxy}</text>')
        for cls in classes:
            value = float(wide.loc[proxy, cls]) if cls in wide.columns else 0.0
            y = 400 - (bottom + value) * 300
            parts.append(f'<rect x="{x}" y="{y:.1f}" width="110" height="{value * 300:.1f}" fill="{class_colors[cls]}"/>')
            bottom += value
    for i, cls in enumerate(classes):
        parts.append(f'<rect x="760" y="{100 + i * 25}" width="16" height="16" fill="{class_colors[cls]}"/><text x="782" y="{113 + i * 25}" font-family="Arial" font-size="12">{cls}</text>')
    parts.append('<line x1="100" y1="400" x2="900" y2="400" stroke="#555"/>')
    write_svg(figures / "P5A-6_support_class_impact.svg", "P5A-6 Support-class impact", "\n".join(parts), 1000, 500)


def render(root: Path) -> None:
    if plt is None:
        render_svg_fallback(root)
        return
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

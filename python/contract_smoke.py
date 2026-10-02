#!/usr/bin/env python3
"""Validate the R-to-Python Parquet boundary without touching source data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        import pandas as pd
        import torch
        from torch_geometric.utils import is_undirected
    except ImportError as error:
        raise SystemExit(f"required contract-smoke dependency is unavailable: {error}")

    nodes = pd.read_parquet(args.nodes)
    edges = pd.read_parquet(args.edges)
    required_nodes = {"node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat"}
    required_edges = {"source_node", "target_node"}
    if not required_nodes.issubset(nodes.columns):
        raise AssertionError(f"node schema missing: {sorted(required_nodes - set(nodes.columns))}")
    if not required_edges.issubset(edges.columns):
        raise AssertionError(f"edge schema missing: {sorted(required_edges - set(edges.columns))}")

    node_ids = nodes["node_id"].astype("int64").to_numpy()
    expected_ids = list(range(len(nodes)))
    if sorted(node_ids.tolist()) != expected_ids:
        raise AssertionError("node_id must be a contiguous zero-based deterministic index")
    if nodes["node_id"].duplicated().any():
        raise AssertionError("node_id is not unique")

    edge_values = edges[["source_node", "target_node"]].astype("int64").to_numpy()
    if len(edge_values):
        if edge_values.min() < 0 or edge_values.max() >= len(nodes):
            raise AssertionError("edge index outside node range")
        edge_index = torch.as_tensor(edge_values.T, dtype=torch.long)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)

    result = {
        "node_count": int(len(nodes)),
        "edge_count": int(len(edges)),
        "node_sha256": sha256_file(args.nodes),
        "edge_sha256": sha256_file(args.edges),
        "edge_index_shape": list(edge_index.shape),
        "edge_index_dtype": str(edge_index.dtype),
        "undirected": bool(is_undirected(edge_index, num_nodes=len(nodes))),
    }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared helpers for the Structured A3 production entrypoints.

The entrypoints in this directory are orchestration adapters. Scientific
feature construction, fitting, prediction, and product rendering remain in
the validated implementations under ``analysis/structured_a3_fullfit``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import a3_pipeline as pipeline  # noqa: E402


@dataclass(frozen=True)
class A3Context:
    config: dict[str, Any]
    config_path: Path
    repo_root: Path
    scientific_path: Path
    scientific: dict[str, Any]
    mode: str
    run_id: str

    @property
    def inputs(self) -> dict[str, Any]:
        value = self.config.get("inputs", {})
        if not isinstance(value, dict):
            raise pipeline.PipelineError("inputs must be a mapping")
        return value

    @property
    def output_root(self) -> Path:
        # Every production invocation is isolated by run_id. This prevents a
        # retry or prospective run from overwriting a prior artifact tree.
        return Path(pipeline.output_root(self.config, self.mode)).expanduser() / self.run_id

    @property
    def log_root(self) -> Path:
        return Path(str(self.config["logs_root"])).expanduser() / self.run_id

    @property
    def chime_execution_id(self) -> str | None:
        return pipeline.current_chime_execution_id()

    def input_path(self, key: str, *, required: bool = True) -> Path | None:
        value = self.inputs.get(key)
        if value in (None, ""):
            if required:
                raise pipeline.PipelineError(f"missing inputs.{key}")
            return None
        return pipeline.resolve_path(value, base=self.config_path.parent, repo_root=self.repo_root)

    def model_output_root(self) -> Path:
        value = self.inputs.get("model_output_root", self.inputs.get("static_predictor_root"))
        path = pipeline.resolve_path(value, base=self.config_path.parent, repo_root=self.repo_root)
        return path.parent if path.name == "raw" else path

    def canonical_args(self, output_root: Path | None = None) -> argparse.Namespace:
        return argparse.Namespace(
            model_output=self.model_output_root(),
            front_features=self.input_path("history_feature_path"),
            anthropogenic_features=self.input_path("anthropogenic_feature_path"),
            soil_features=self.input_path("soil_feature_path"),
            output_root=output_root or self.output_root,
            permutation_replicates=10,
            correlation_sample=100_000,
            seed=20261006,
        )


def load_context(config_path: Path, mode: str, run_id: str) -> A3Context:
    config, repo_root, scientific_path = pipeline.load_config(config_path)
    scientific = pipeline.validate_frozen_manifest(scientific_path)
    return A3Context(config, config_path.resolve(), repo_root, scientific_path, scientific, mode, run_id)


def load_fullfit_module(repo_root: Path):
    path = repo_root / "analysis" / "structured_a3_fullfit" / "scripts" / "run_fullfit_products.py"
    if not path.exists():
        raise pipeline.PipelineError(f"validated full-fit implementation is missing: {path}")
    spec = importlib.util.spec_from_file_location("structured_a3_fullfit_products", path)
    if spec is None or spec.loader is None:
        raise pipeline.PipelineError(f"could not load validated full-fit implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict[str, Any]) -> None:
    pipeline.atomic_write_json(path, payload)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{__import__('os').getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_stage_json(ctx: A3Context, name: str, payload: dict[str, Any], *, output_copy: bool = True) -> None:
    payload = dict(payload)
    payload["chime_execution_id"] = ctx.chime_execution_id
    write_json(ctx.log_root / name, payload)
    if output_copy:
        write_json(ctx.output_root / "manifests" / name, payload)


def run_checked(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True)
    if completed.returncode != 0:
        raise pipeline.PipelineError(f"command exited with status {completed.returncode}: {' '.join(command)}")


def read_json_or_yaml(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        value = pipeline.load_yaml(path)
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise pipeline.PipelineError(f"manifest must be a mapping: {path}")
    return value


def deployed_model_path(ctx: A3Context, deployment: dict[str, Any]) -> Path:
    explicit = pipeline.lookup(deployment, ("model_artifact", "model_file", "deployed_model_path"))
    if explicit:
        path = Path(str(explicit))
        if not path.is_absolute():
            path = (ctx.config_path.parent / path).resolve()
        return path
    configured = ctx.inputs.get("deployed_model_output_root")
    if configured:
        root = pipeline.resolve_path(configured, base=ctx.config_path.parent, repo_root=ctx.repo_root)
    else:
        root = Path(str(ctx.config.get("production_model_output_root", ctx.config.get("output_root", ""))))
    return root / "model" / "fullfit_a3_model.json"


def week_tuple(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def ensure_input_paths(ctx: A3Context) -> dict[str, str]:
    keys = (
        "observation_path",
        "environmental_root",
        "static_predictor_root",
        "history_feature_path",
        "anthropogenic_feature_path",
        "soil_feature_path",
    )
    paths: dict[str, str] = {}
    for key in keys:
        path = ctx.input_path(key)
        assert path is not None
        if not path.exists():
            raise pipeline.PipelineError(f"configured input does not exist: inputs.{key}={path}")
        paths[key] = str(path)
    model_root = ctx.model_output_root()
    if not (model_root / "raw").exists():
        raise pipeline.PipelineError(f"production model raw bundle is missing: {model_root / 'raw'}")
    paths["model_output_root"] = str(model_root)
    return paths


def leakage_payload(support) -> dict[str, Any]:
    same = int(support["same_week_or_future_history_uses"].sum())
    missing = int(support["missing_history_cutoff_rows"].sum())
    return {
        "status": "PASS" if same == 0 and missing == 0 else "FAIL",
        "same_week_or_future_uses": same,
        "missing_history_cutoff_rows": missing,
        "weeks_checked": int(len(support)),
    }


def common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=pipeline.MODES, required=True)
    return parser

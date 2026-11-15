"""Run the bounded, two-stage A6-VIF GPBoost challenger."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import inspect
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
import warnings
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

try:
    import resource
except ImportError:  # pragma: no cover - Windows-only import guard for local contract checks
    resource = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
A6_DIR = REPOSITORY_ROOT / "analysis/a6_gpboost_correlated_spatial_ml/scripts"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A6 = load_module(A6_DIR / "run_a6.py", "a6_vif_original_helpers")
A5 = A6.A5
PARAMETER_NAMES = ["GP_var", "GP_range_time", "GP_range_space"]
PARENT_A6_SHA = "e734427b29111917261861a67aafa2379a5bfc07"
VIF_CANDIDATE = "A6-VIF"

_PROGRESS_ROOT: Path | None = None
_EXECUTION_STARTED = 0.0
_EXECUTION_CPU_STARTED = 0.0
_EXECUTION_DEADLINE: float | None = None
_CURRENT_STAGE = "NOT_STARTED"
_STOP_REQUESTED = False
_STOP_SIGNAL: int | None = None
_WARNING_MESSAGES: list[str] = []


class A6VIFBlocked(RuntimeError):
    """Raised when the requested two-stage GPBoost contract cannot be honored."""


class A6VIFDeadlineExceeded(A6VIFBlocked):
    """Raised at a safe Python callback boundary when the internal budget expires."""


def scheduler_signal_handler(signum: int, _frame: Any) -> None:
    global _STOP_REQUESTED, _STOP_SIGNAL
    _STOP_REQUESTED = True
    _STOP_SIGNAL = int(signum)


def initialize_progress(root: Path, deadline_seconds: float) -> None:
    global _PROGRESS_ROOT, _EXECUTION_STARTED, _EXECUTION_CPU_STARTED, _EXECUTION_DEADLINE
    _PROGRESS_ROOT = root
    _EXECUTION_STARTED = time.perf_counter()
    _EXECUTION_CPU_STARTED = runtime_snapshot()["cpu_seconds"]
    _EXECUTION_DEADLINE = _EXECUTION_STARTED + float(deadline_seconds)
    emit_progress("EXECUTION", "STARTED", deadline_seconds=float(deadline_seconds), utc=utc_now())


def install_durable_warning_logger() -> None:
    prior_showwarning = warnings.showwarning

    def showwarning(message, category, filename, lineno, file=None, line=None):
        formatted = warnings.formatwarning(message, category, filename, lineno, line)
        _WARNING_MESSAGES.append(formatted.rstrip())
        if _PROGRESS_ROOT is not None:
            path = _PROGRESS_ROOT / "logs/warnings.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"utc": utc_now(), "category": category.__name__, "message": str(message), "filename": filename, "lineno": int(lineno)}) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        prior_showwarning(message, category, filename, lineno, file=file, line=line)

    warnings.showwarning = showwarning
    warnings.simplefilter("always")


def emit_progress(stage: str, event: str, *, update_status: bool = True, **details: Any) -> None:
    global _CURRENT_STAGE
    _CURRENT_STAGE = stage
    now = time.perf_counter()
    snapshot = runtime_snapshot()
    payload = {
        "utc": utc_now(),
        "stage": stage,
        "event": event,
        "elapsed_wall_seconds": float(now - _EXECUTION_STARTED) if _EXECUTION_STARTED else None,
        "process_cpu_seconds": float(snapshot["cpu_seconds"]),
        "peak_rss_bytes": float(snapshot["peak_rss_bytes"]),
        **details,
    }
    if _PROGRESS_ROOT is not None:
        path = _PROGRESS_ROOT / "logs/progress.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if update_status:
            write_json_atomic(_PROGRESS_ROOT / "results/run_status.json", {
                "status": "RUNNING",
                "current_stage": stage,
                "last_event": event,
                "last_event_utc": payload["utc"],
                "elapsed_wall_seconds": payload["elapsed_wall_seconds"],
                "process_cpu_seconds": payload["process_cpu_seconds"],
                "peak_rss_bytes": payload["peak_rss_bytes"],
            })
    print(json.dumps(payload, sort_keys=True, default=str), flush=True)


def enforce_internal_deadline(stage: str) -> None:
    if _STOP_REQUESTED:
        emit_progress(stage, "STOP_REQUESTED_BY_SCHEDULER", signal=_STOP_SIGNAL)
        raise A6VIFDeadlineExceeded(f"scheduler pre-timeout signal {_STOP_SIGNAL} received during {stage}")
    if _EXECUTION_DEADLINE is not None and time.perf_counter() >= _EXECUTION_DEADLINE:
        emit_progress(stage, "INTERNAL_DEADLINE_EXCEEDED")
        raise A6VIFDeadlineExceeded(f"internal execution deadline exceeded during {stage}")


def gpboost_progress_callback(gp: Any, stage: str):
    last_callback = [time.perf_counter()]

    def callback(environment: Any) -> None:
        now = time.perf_counter()
        model = getattr(environment, "model", None)
        numerical: dict[str, Any] = {}
        for source_name, source in (("booster", model), ("gp_model", gp)):
            if source is None:
                continue
            for label, method_name in (
                ("mode_finding_steps", "_get_num_mode_finding_steps"),
                ("cg_steps", "_get_num_cg_steps"),
                ("cg_tridiag_steps", "_get_num_cg_steps_tridiag"),
            ):
                method = getattr(source, method_name, None)
                if callable(method):
                    try:
                        numerical[f"{source_name}_{label}"] = int(method())
                    except Exception as exc:
                        numerical[f"{source_name}_{label}_diagnostic_error"] = str(exc)
        evaluations = getattr(environment, "evaluation_result_list", None)
        if evaluations is not None:
            numerical["evaluation"] = evaluations
        try:
            covariances, _ = covariance_table(gp)
            numerical["covariance_parameters"] = covariances
        except Exception as exc:
            numerical["covariance_diagnostic_error"] = str(exc)
        iteration = int(getattr(environment, "iteration", -1)) + 1
        emit_progress(
            stage,
            "ITERATION",
            update_status=False,
            iteration=iteration,
            iteration_wall_seconds=float(now - last_callback[0]),
            **numerical,
        )
        last_callback[0] = now
        enforce_internal_deadline(stage)

    callback.order = 50
    callback.before_iteration = False
    return callback


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False)
    with temporary.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_npz_atomic(path: Path, arrays: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    with np.load(temporary, allow_pickle=False) as check:
        if set(check.files) != set(arrays):
            raise RuntimeError(f"prediction archive validation failed for {path}")
    with temporary.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_model_atomic(model: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{os.getpid()}.tmp{path.suffix}")
    model.save_model(str(temporary))
    if not temporary.exists() or temporary.stat().st_size <= 0:
        raise A6VIFBlocked(f"model serialization produced an empty temporary artifact: {temporary}")
    with temporary.open("rb+") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_config(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    opt = json.loads(path.read_text(encoding="utf-8"))
    if opt.get("analysis") != "a6_vif_bounded_gate" or opt.get("parent_a6_commit") != PARENT_A6_SHA:
        raise RuntimeError("A6-VIF parent or analysis identifier changed")
    base_path = (path.parent / opt["base_config"]).resolve()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("analysis") != "a6_gpboost_correlated_spatial_ml":
        raise RuntimeError("the original A6 configuration is not the declared base")
    if base["gpboost"]["num_neighbors"] != 20 or base["gpboost"]["num_neighbors_pred"] != 40:
        raise RuntimeError("the frozen original A6 Vecchia specification changed")
    config = copy.deepcopy(base)
    config["analysis"] = "a6_vif_bounded_gate"
    config["gpboost"].update(opt["gpboost_overrides"])
    required_gp = {
        "gp_approx": "full_scale_vecchia",
        "num_ind_points": 200,
        "ind_points_selection": "kmeans++",
        "num_neighbors": 8,
        "num_neighbors_pred": 40,
        "matrix_inversion_method": "iterative",
        "vecchia_ordering_spatiotemporal": "time",
    }
    actual_gp = {name: config["gpboost"].get(name) for name in required_gp}
    if actual_gp != required_gp:
        raise RuntimeError(f"A6-VIF GPBoost configuration contract failed: expected={required_gp}, actual={actual_gp}")
    if config["gpboost"]["cov_fct_shape"] != 1.5 or config["gpboost"]["likelihood"] != "bernoulli_logit":
        raise RuntimeError("A6-VIF Matérn or likelihood contract changed")
    if config["predictors"]["count"] != 34 or config["predictors"]["coordinates_are_tree_features"]:
        raise RuntimeError("A6-VIF predictor contract changed")
    if config["development_period"]["folds"] != base["development_period"]["folds"] or config["seeds"] != [1729, 31415, 271828]:
        raise RuntimeError("A6-VIF temporal folds or seeds changed")
    if opt["covariance_estimation"]["parameter_names"] != PARAMETER_NAMES:
        raise RuntimeError("A6-VIF named covariance parameter order changed")
    if int(opt["covariance_estimation"].get("gp_seed", -1)) != 31415:
        raise RuntimeError("A6-VIF Stage A GP seed must match the authorized gate seed 31415")
    config["a6_vif"] = opt
    config["a6_vif_provenance"] = {
        "opt_config_path": str(path.resolve()),
        "opt_config_sha256": sha256_file(path),
        "base_config_path": str(base_path),
        "base_config_sha256": sha256_file(base_path),
    }
    return config, opt


def resolve_output_root(explicit: Path | None) -> Path:
    value = explicit or (Path(os.environ["A6_VIF_OUTPUT_ROOT"]) if os.environ.get("A6_VIF_OUTPUT_ROOT") else None)
    if value is None:
        raise RuntimeError("A6_VIF_OUTPUT_ROOT or --output-root is required")
    root = value.expanduser().resolve()
    if "/90daydata/" not in str(root).replace("\\", "/"):
        raise RuntimeError(f"A6-VIF large outputs must be under /90daydata/disease_ecology: {root}")
    return root


def runtime_snapshot() -> dict[str, float]:
    if resource is None:
        return {"cpu_seconds": 0.0, "peak_rss_bytes": 0.0}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "cpu_seconds": float(usage.ru_utime + usage.ru_stime),
        "peak_rss_bytes": float(usage.ru_maxrss * 1024),
    }


@contextmanager
def fold_lock(path: Path):
    """Use an OS lock, released automatically if a Slurm process is interrupted."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"identical fold task already holds {path}") from exc
        yield


def load_data(args: argparse.Namespace) -> Any:
    data_args = argparse.Namespace(
        config=args.config,
        model_output=args.model_output,
        front_features=args.front_features,
        anthropogenic_features=args.anthropogenic_features,
        soil_features=args.soil_features,
        edges=args.edges,
        a3_reference=args.a3_reference,
        a3_frozen_output=args.a3_frozen_output,
        spatial_assignments=None,
    )
    return A6.load_data(data_args)


def source_checksums(config_path: Path) -> dict[str, str]:
    paths = {
        "a6_vif_runner": Path(__file__).resolve(),
        "original_a6_runner": Path(A6.__file__).resolve(),
        "a5_runner": Path(A5.__file__).resolve(),
        "a5b_runner": Path(A6.A5B.__file__).resolve(),
        "a5_augmentation": Path(A5.AUG.__file__).resolve(),
        "a4_reference_helpers": Path(A5.A4.__file__).resolve(),
        "a5_model": (REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison/scripts/a5_model.py").resolve(),
        "task2c_metrics": (REPOSITORY_ROOT / "python/task2c_metrics.py").resolve(),
        "a6_vif_config": config_path.resolve(),
        "gpboost_vif_api_preflight": (REPOSITORY_ROOT / "analysis/a6_vif_bounded_gate/API_PREFLIGHT.md").resolve(),
        "a6_base_config": (config_path.parent / json.loads(config_path.read_text(encoding="utf-8"))["base_config"]).resolve(),
        "a6_vif_slurm_script": (REPOSITORY_ROOT / "hpc/run_a6_vif.sbatch").resolve(),
        "a6_vif_submitter": (REPOSITORY_ROOT / "hpc/submit_a6_vif_gate.sh").resolve(),
        "a6_vif_timeout_finalizer": (REPOSITORY_ROOT / "analysis/a6_vif_bounded_gate/scripts/finalize_a6_vif_budget.py").resolve(),
    }
    result = {}
    for name, path in paths.items():
        if not path.exists():
            raise RuntimeError(f"required implementation provenance source is missing: {path}")
        result[name] = sha256_file(path)
    return result


def time_limit_seconds(value: str) -> int:
    parts = [int(part) for part in value.split(":")]
    if len(parts) != 3:
        raise ValueError(f"expected HH:MM:SS walltime, got {value}")
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def load_gpboost():
    try:
        import gpboost as gpb
    except Exception as exc:  # environment-dependent
        raise A6VIFBlocked(f"A6_VIF_SOFTWARE_BLOCKED: GPBoost import failed: {exc}") from exc
    if getattr(gpb, "__version__", None) != "1.8.0":
        raise A6VIFBlocked(f"A6_VIF_SOFTWARE_BLOCKED: expected GPBoost 1.8.0, got {getattr(gpb, '__version__', None)}")
    return gpb


def audit_gpboost_api(gpb: Any, output: Path) -> dict[str, Any]:
    fit_sig = inspect.signature(gpb.GPModel.fit)
    optim_sig = inspect.signature(gpb.GPModel.set_optim_params)
    train_sig = inspect.signature(gpb.train)
    pred_sig = inspect.signature(gpb.GPModel.set_prediction_data)
    gp_sig = inspect.signature(gpb.GPModel)
    gp_doc = inspect.getdoc(gpb.GPModel.__init__) or ""
    required = {
        "constructor_gp_approx": "gp_approx" in gp_sig.parameters,
        "constructor_num_ind_points": "num_ind_points" in gp_sig.parameters,
        "constructor_ind_points_selection": "ind_points_selection" in gp_sig.parameters,
        "constructor_matrix_inversion_method": "matrix_inversion_method" in gp_sig.parameters,
        "constructor_vecchia_ordering": "vecchia_ordering" in gp_sig.parameters,
        "constructor_num_neighbors": "num_neighbors" in gp_sig.parameters,
        "vif_approximation_documented": "full_scale_vecchia" in gp_doc,
        "non_gaussian_vif_documented": "non-Gaussian likelihoods with a VIF approximation" in gp_doc,
        "matern_space_time_documented": "matern_space_time" in gp_doc,
        "inducing_point_selection_documented": "ind_points_selection" in gp_doc and "kmeans++" in gp_doc,
        "GPModel.fit_offset": "offset" in fit_sig.parameters,
        "GPModel.set_optim_params": "params" in optim_sig.parameters,
        "train_fixed_covariance": "train_gp_model_cov_pars" in train_sig.parameters,
        "train_progress_callbacks": "callbacks" in train_sig.parameters,
        "prediction_type_setting": "vecchia_pred_type" in pred_sig.parameters,
        "prediction_neighbor_setting": "num_neighbors_pred" in pred_sig.parameters,
        "GPModel_fit_init_cov_pars_documented": "init_cov_pars" in (inspect.getdoc(gpb.GPModel.set_optim_params) or ""),
        "train_fixed_covariance_documented": "provide values via the 'init_cov_pars'" in (inspect.getdoc(gpb.train) or ""),
        "GPModel_fit_forwards_offset": "offset_c" in inspect.getsource(gpb.GPModel.fit) and "GPB_OptimCovPar" in inspect.getsource(gpb.GPModel.fit),
    }
    if not all(required.values()):
        raise A6VIFBlocked(f"installed GPBoost 1.8.0 does not satisfy the A6-VIF API contract: {required}")
    payload = {
        "status": "PASSED",
        "gpboost_version": gpb.__version__,
        "gpboost_path": str(Path(gpb.__file__).resolve()),
        "api_signatures": {
            "GPModel": str(gp_sig),
            "GPModel.fit": str(fit_sig),
            "GPModel.set_optim_params": str(optim_sig),
            "GPModel.set_prediction_data": str(pred_sig),
            "gpb.train": str(train_sig),
        },
        "api_contract": required,
        "verified_model_contract": {
            "bernoulli_logit": True,
            "matern_space_time": True,
            "gp_approx": "full_scale_vecchia",
            "inducing_points": 200,
            "inducing_point_selection": "kmeans++",
            "local_vecchia_neighbors": 8,
            "matrix_inversion_method": "iterative",
            "vecchia_ordering": "time",
            "fit_offset_on_linear_predictor": True,
            "fixed_covariance_train_flag": True,
            "init_cov_pars_via_set_optim_params": True,
            "explicit_prediction_neighbors": 40,
            "api_signature_verified": True,
            "non_gaussian_vif_documented": True,
        },
        "installed_gpboost_doc_excerpts": [
            line.strip() for line in gp_doc.splitlines()
            if any(term in line for term in ("full_scale_vecchia", "non-Gaussian likelihoods with a VIF", "matern_space_time", "ind_points_selection", "num_ind_points"))
        ],
    }
    path = output / "provenance/gpboost_api_audit.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old != payload:
            raise RuntimeError(f"refusing to overwrite changed GPBoost API audit: {path}")
    else:
        write_json_atomic(path, payload)
    return payload


def select_spatial_sites(coords_xy: np.ndarray, eligible_nodes: np.ndarray, sample_size: int, bins_per_axis: int, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Choose outcome-blind sites round-robin over fixed spatial tiles."""
    eligible = np.asarray(eligible_nodes, dtype=np.int64)
    coords = np.asarray(coords_xy, dtype=np.float64)
    if len(eligible) == 0 or len(np.unique(eligible)) != len(eligible):
        raise RuntimeError("covariance subset requires unique eligible spatial nodes")
    sample_size = min(int(sample_size), len(eligible))
    values = coords[eligible]
    x_edges = np.linspace(float(values[:, 0].min()), float(values[:, 0].max()) + 1e-12, bins_per_axis + 1)
    y_edges = np.linspace(float(values[:, 1].min()), float(values[:, 1].max()) + 1e-12, bins_per_axis + 1)
    bx = np.clip(np.searchsorted(x_edges, values[:, 0], side="right") - 1, 0, bins_per_axis - 1)
    by = np.clip(np.searchsorted(y_edges, values[:, 1], side="right") - 1, 0, bins_per_axis - 1)
    tile = bx * bins_per_axis + by
    rng = np.random.default_rng(seed)
    priority = rng.random(len(eligible))
    grouped: list[np.ndarray] = []
    for tile_id in range(bins_per_axis * bins_per_axis):
        local = np.flatnonzero(tile == tile_id)
        if len(local):
            grouped.append(eligible[local[np.argsort(priority[local], kind="stable")]])
    edge_nodes = {
        int(eligible[int(np.argmin(values[:, 0]))]),
        int(eligible[int(np.argmax(values[:, 0]))]),
        int(eligible[int(np.argmin(values[:, 1]))]),
        int(eligible[int(np.argmax(values[:, 1]))]),
    }
    chosen = list(sorted(edge_nodes))
    chosen_set = set(chosen)
    for depth in range(max((len(group) for group in grouped), default=0)):
        for group in grouped:
            if depth >= len(group):
                continue
            node = int(group[depth])
            if node not in chosen_set:
                chosen.append(node)
                chosen_set.add(node)
                if len(chosen) == sample_size:
                    break
        if len(chosen) == sample_size:
            break
    if len(chosen) != sample_size:
        raise RuntimeError(f"deterministic spatial subset selected {len(chosen)} sites, expected {sample_size}")
    sample = np.asarray(chosen, dtype=np.int64)
    full_nn = cKDTree(values).query(values, k=2)[0][:, 1]
    sample_nn = cKDTree(coords[sample]).query(coords[sample], k=2)[0][:, 1]

    def quantiles(arr: np.ndarray) -> dict[str, float]:
        return {f"p{q}": float(np.quantile(arr, q / 100)) for q in (10, 50, 90)}

    summary = {
        "method": "deterministic_spatial_stratification_all_training_weeks",
        "uses_outcomes_for_site_selection": False,
        "seed": int(seed),
        "grid_bins_per_axis": int(bins_per_axis),
        "full_eligible_sites": int(len(eligible)),
        "sampled_sites": int(len(sample)),
        "sampling_fraction": float(len(sample) / len(eligible)),
        "occupied_spatial_tiles": int(len(grouped)),
        "full_domain_extent_xy": {"min": values.min(axis=0).tolist(), "max": values.max(axis=0).tolist()},
        "sample_extent_xy": {"min": coords[sample].min(axis=0).tolist(), "max": coords[sample].max(axis=0).tolist()},
        "nearest_neighbor_distance_km": {"full_domain": quantiles(full_nn), "sample": quantiles(sample_nn)},
        "sample_node_ids": sample.tolist(),
    }
    return sample, summary


def flatten_training(fold: Any, times: np.ndarray, node_ids: np.ndarray, coords_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray(times, dtype=np.int64)
    node_ids = np.asarray(node_ids, dtype=np.int64)
    x = fold.x[times[:, None], node_ids, :].reshape(-1, 34).astype(np.float64)
    y_count = fold.counts[times[:, None], node_ids].reshape(-1).astype(np.int64)
    y = (y_count > 0).astype(np.int64)
    offset = fold.eta[times[:, None], node_ids].reshape(-1).astype(np.float64)
    coords = A6.build_coords(coords_xy, times, node_ids, space_time=True)
    if x.shape[1] != 34 or coords.shape != (len(y), 3) or len(offset) != len(y):
        raise RuntimeError("training feature, offset, and space-time coordinate rows are not aligned")
    if not np.array_equal(coords[:, 0].astype(np.int64), np.repeat(times, len(node_ids))):
        raise RuntimeError("space-time coordinate first column is not the weekly index")
    return x, y, y_count, offset, coords


def make_gp_model(gpb: Any, coords: np.ndarray, seed: int, config: dict[str, Any], threads: int) -> Any:
    gp = config["gpboost"]
    init_started = time.perf_counter()
    warning_start = len(_WARNING_MESSAGES)
    model = gpb.GPModel(
            likelihood=gp["likelihood"],
            gp_coords=coords,
            cov_function=gp["spatiotemporal_cov_function"],
            cov_fct_shape=gp["cov_fct_shape"],
            gp_approx=gp["gp_approx"],
            num_ind_points=int(gp["num_ind_points"]),
            ind_points_selection=gp["ind_points_selection"],
            num_neighbors=int(gp["num_neighbors"]),
            vecchia_ordering=gp["vecchia_ordering_spatiotemporal"],
            matrix_inversion_method=gp["matrix_inversion_method"],
            num_parallel_threads=int(threads),
            seed=int(seed),
    )
    init_warnings = _WARNING_MESSAGES[warning_start:]
    emit_progress(
        "GP_INITIALIZATION",
        "COMPLETED",
        update_status=False,
        rows=int(len(coords)),
        elapsed_seconds=float(time.perf_counter() - init_started),
        inducing_points_requested=int(gp["num_ind_points"]),
        inducing_point_selection=gp["ind_points_selection"],
        vecchia_neighbors=int(gp["num_neighbors"]),
        matrix_inversion_method=gp["matrix_inversion_method"],
        initialization_warnings=init_warnings,
    )
    model._a6_vif_initialization_warnings = init_warnings
    return model


def covariance_table(gp: Any) -> tuple[dict[str, float], list[dict[str, Any]]]:
    table = gp.get_cov_pars(format_pandas=True)
    if not isinstance(table, pd.DataFrame) or len(table) != 1:
        raise A6VIFBlocked("GPBoost did not return one named space-time covariance parameter row")
    missing = set(PARAMETER_NAMES) - set(table.columns)
    if missing:
        raise A6VIFBlocked(f"GPBoost covariance table is missing named parameters: {sorted(missing)}")
    values = {name: float(table.iloc[0][name]) for name in PARAMETER_NAMES}
    rows = table.to_dict(orient="records")
    return values, rows


def validate_covariance(values: dict[str, float], maxit: int | None = None, iterations: int | None = None) -> dict[str, Any]:
    positive = all(math.isfinite(values[name]) and values[name] > 0 for name in PARAMETER_NAMES)
    screen_limits = {"lower": 1e-8, "upper": 1e8}
    within_broad_screen = bool(positive and all(screen_limits["lower"] < values[name] < screen_limits["upper"] for name in PARAMETER_NAMES))
    near_screen_boundary = [
        name for name in PARAMETER_NAMES
        if math.isfinite(values[name]) and (
            values[name] <= screen_limits["lower"] * 1.01
            or values[name] >= screen_limits["upper"] * 0.99
        )
    ]
    nondegenerate = bool(within_broad_screen)
    convergence = bool(iterations is not None and iterations > 0 and (maxit is None or iterations < maxit))
    return {
        "finite_positive": bool(positive),
        "non_degenerate": bool(nondegenerate),
        "boundary_screen_passed": bool(within_broad_screen),
        "boundary_screen_limits": screen_limits,
        "near_boundary_parameters": near_screen_boundary,
        "boundary_screen_source": "broad analysis screen; GPBoost Python API does not expose optimizer bound-hit status",
        "optimizer_iterations": int(iterations) if iterations is not None else None,
        "optimizer_maxit": int(maxit) if maxit is not None else None,
        "convergence_diagnostic": "optimizer_returned_before_maxit_proxy" if convergence else "maxit_reached_or_optimizer_iterations_unavailable",
        "explicit_optimizer_convergence_status_available": False,
        "convergence_is_iteration_limit_proxy": True,
        "converged": convergence,
    }


def covariance_fingerprint(
    stage: str,
    fold_id: int,
    train_times: np.ndarray,
    eligible_nodes: np.ndarray,
    sample_nodes: np.ndarray,
    data: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": stage,
        "fold": int(fold_id),
        "training_week_indices": np.asarray(train_times, dtype=np.int64).tolist(),
        "training_node_ids_sha256": sha256_json(np.asarray(eligible_nodes, dtype=np.int64).tolist()),
        "sample_node_ids_sha256": sha256_json(np.asarray(sample_nodes, dtype=np.int64).tolist()),
        "input_sha256": dict(data.hashes),
        "config_sha256": sha256_json(config["a6_vif_provenance"]),
        "source_sha256": config["a6_vif_provenance"]["source_sha256"],
        "gpboost_version": "1.8.0",
    }


def load_completed_covariance(stage_dir: Path, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
    if not stage_dir.exists():
        return None
    for attempt_dir in sorted(stage_dir.glob("attempt_*")):
        marker = attempt_dir / "completion.json"
        estimate = attempt_dir / "stage_a_estimate.json"
        if not marker.exists():
            continue
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if payload.get("status") != "COMPLETED":
            continue
        if not estimate.exists() or sha256_file(estimate) != payload.get("estimate_sha256"):
            raise RuntimeError(f"completed Stage A covariance artifact checksum failed: {estimate}")
        if payload.get("fingerprint") == fingerprint:
            result = json.loads(estimate.read_text(encoding="utf-8"))
            result["attempt_directory"] = str(attempt_dir)
            result["estimate_sha256"] = payload["estimate_sha256"]
            result["reused"] = True
            return result
    return None


def next_attempt_dir(stage_dir: Path) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    numbers = [int(path.name.split("_")[-1]) for path in stage_dir.glob("attempt_*") if path.name.split("_")[-1].isdigit()]
    attempt = max(numbers, default=0) + 1
    path = stage_dir / f"attempt_{attempt:03d}"
    path.mkdir(exist_ok=False)
    return path


def estimate_covariance(
    gpb: Any,
    fold: Any,
    train_times: np.ndarray,
    eligible_nodes: np.ndarray,
    coords_xy: np.ndarray,
    fold_root: Path,
    data: Any,
    config: dict[str, Any],
    fold_id: int,
    stage_name: str,
    threads: int,
) -> dict[str, Any]:
    stage_started = time.perf_counter()
    stage_cpu_before = runtime_snapshot()["cpu_seconds"]
    emit_progress(f"STAGE_A_{stage_name}", "STARTED", training_week_indices=np.asarray(train_times, dtype=np.int64).tolist())
    opt = config["a6_vif"]["covariance_estimation"]
    sample_nodes, sample_summary = select_spatial_sites(
        coords_xy,
        eligible_nodes,
        opt["sample_nodes"],
        opt["spatial_grid_bins_per_axis"],
        int(opt["sampling_seed"]),
    )
    fingerprint = covariance_fingerprint(stage_name, fold_id, train_times, eligible_nodes, sample_nodes, data, config)
    stage_dir = fold_root / "covariance" / stage_name
    reused = load_completed_covariance(stage_dir, fingerprint)
    if reused is not None:
        reused["reused"] = True
        emit_progress(f"STAGE_A_{stage_name}", "REUSED_COMPLETED_ESTIMATE", estimate_sha256=reused.get("estimate_sha256"))
        return reused

    x, y, _, offset, coords = flatten_training(fold, train_times, sample_nodes, coords_xy)
    emit_progress(
        f"STAGE_A_{stage_name}",
        "DATA_PREPARED",
        update_status=False,
        sample_nodes=int(len(sample_nodes)),
        observations=int(len(y)),
        training_weeks=int(len(train_times)),
        feature_count=int(x.shape[1]),
        coordinate_order=["time_week_offset", "x_km", "y_km"],
        spatial_sampling=sample_summary,
    )
    week_class_counts = []
    n_sites = len(sample_nodes)
    for index, week in enumerate(np.asarray(train_times, dtype=np.int64)):
        start = index * n_sites
        stop = start + n_sites
        week_class_counts.append({"week_index": int(week), "positive": int(y[start:stop].sum()), "negative": int(len(y[start:stop]) - y[start:stop].sum())})
    if np.unique(y).size < 2:
        raise A6VIFBlocked(f"Stage A {stage_name} subset lacks occurrence-class variation")
    if any(row["positive"] + row["negative"] != n_sites for row in week_class_counts):
        raise RuntimeError("Stage A per-week subset row accounting failed")
    initial = opt["initial_covariance_parameters"]
    if list(initial) != PARAMETER_NAMES:
        initial = {name: float(initial[name]) for name in PARAMETER_NAMES}
    init_vector = np.asarray([float(initial[name]) for name in PARAMETER_NAMES], dtype=np.float64)
    seed = int(opt["gp_seed"])
    emit_progress(f"STAGE_A_{stage_name}", "GP_INITIALIZATION_STARTED", update_status=False, observation_count=int(len(y)), threads=int(threads), gp_seed=seed)
    gp = make_gp_model(gpb, coords, seed, config, threads)
    params = {
        "init_cov_pars": init_vector,
        "optimizer_cov": opt["optimizer_cov"],
        "maxit": int(opt["maxit"]),
        "delta_rel_conv": float(opt["delta_rel_conv"]),
        "trace": bool(opt["trace"]),
    }
    attempt_dir = next_attempt_dir(stage_dir)
    write_json_atomic(attempt_dir / "status.json", {"status": "RUNNING", "stage": stage_name, "started_utc": utc_now(), "fingerprint": fingerprint, "approximation": "full_scale_vecchia", "inducing_points": int(config["gpboost"]["num_ind_points"]), "vecchia_neighbors": int(config["gpboost"]["num_neighbors"])})
    before = runtime_snapshot()
    started = time.perf_counter()
    caught: list[str] = []
    try:
        enforce_internal_deadline(f"STAGE_A_{stage_name}")
        emit_progress(f"STAGE_A_{stage_name}", "COVARIANCE_OPTIMIZATION_STARTED", update_status=False, optimizer_cov=params["optimizer_cov"], maxit=params["maxit"], initial_covariance_parameters=init_vector.tolist())
        warning_start = len(_WARNING_MESSAGES)
        gp.fit(y=y.astype(np.float64), offset=offset.astype(np.float64), params=params)
        caught = _WARNING_MESSAGES[warning_start:]
        enforce_internal_deadline(f"STAGE_A_{stage_name}")
        elapsed = time.perf_counter() - started
        after = runtime_snapshot()
        covariance, table = covariance_table(gp)
        iterations = int(gp._get_num_optim_iter())
        diagnostics = validate_covariance(covariance, int(opt["maxit"]), iterations)
        xy_extent = np.ptp(coords[:, 1:3], axis=0)
        spatial_diameter = float(np.linalg.norm(xy_extent))
        temporal_span = int(np.ptp(np.asarray(train_times, dtype=np.int64)))
        diagnostics["range_identifiability_screen"] = {
            "training_temporal_span_weeks": temporal_span,
            "sampled_spatial_domain_diagonal_km": spatial_diameter,
            "temporal_range_to_training_span_ratio": float(covariance["GP_range_time"] / max(temporal_span, 1)),
            "spatial_range_to_domain_diagonal_ratio": float(covariance["GP_range_space"] / max(spatial_diameter, 1e-12)),
            "temporal_range_exceeds_training_span": bool(covariance["GP_range_time"] > max(temporal_span, 1)),
            "spatial_range_exceeds_domain_diagonal": bool(covariance["GP_range_space"] > max(spatial_diameter, 1e-12)),
            "interpretation": "diagnostic only; no new model-selection threshold was introduced",
        }
        if not diagnostics["finite_positive"] or not diagnostics["non_degenerate"] or not diagnostics["converged"]:
            raise A6VIFBlocked(f"Stage A covariance validation failed: {diagnostics}; parameters={covariance}")
        estimate = {
            "status": "COMPLETED",
            "stage": stage_name,
            "fold": int(fold_id),
            "gp_seed": int(seed),
            "covariance_parameters": covariance,
            "covariance_parameter_table": table,
            "covariance_diagnostics": diagnostics,
            "observations_used": int(len(y)),
            "full_partition_observations": int(len(train_times) * len(eligible_nodes)),
            "training_weeks": np.asarray(train_times, dtype=np.int64).tolist(),
            "training_week_extent": [int(np.min(train_times)), int(np.max(train_times))],
            "temporal_separation_coverage_weeks": {
                "adjacent_week_gap_min": int(np.diff(np.asarray(train_times, dtype=np.int64)).min()) if len(train_times) > 1 else None,
                "adjacent_week_gap_median": float(np.median(np.diff(np.asarray(train_times, dtype=np.int64)))) if len(train_times) > 1 else None,
                "adjacent_week_gap_max": int(np.diff(np.asarray(train_times, dtype=np.int64)).max()) if len(train_times) > 1 else None,
                "available_pairwise_lag_weeks": sorted(set(int(abs(left - right)) for index, left in enumerate(np.asarray(train_times, dtype=np.int64)) for right in np.asarray(train_times, dtype=np.int64)[index + 1:])),
            },
            "sampled_occurrence_counts": {"positive": int(y.sum()), "negative": int(len(y) - y.sum())},
            "sampled_week_class_counts": week_class_counts,
            "spatial_sampling": sample_summary,
            "optimizer": {key: value for key, value in params.items() if key != "init_cov_pars"} | {
                "init_cov_pars_parameter_order": PARAMETER_NAMES,
                "init_cov_pars_values": init_vector.tolist(),
            },
            "runtime": {
                "optimizer_wall_seconds": float(elapsed),
                "wall_seconds": float(time.perf_counter() - stage_started),
                "cpu_seconds": max(0.0, after["cpu_seconds"] - before["cpu_seconds"]),
                "stage_cpu_seconds": max(0.0, after["cpu_seconds"] - stage_cpu_before),
                "peak_rss_bytes_process": after["peak_rss_bytes"],
                "allocated_cpus": int(threads),
            },
            "warnings": caught + list(getattr(gp, "_a6_vif_initialization_warnings", [])),
            "input_sha256": dict(data.hashes),
            "config_sha256": sha256_json(config["a6_vif_provenance"]),
            "source_sha256": config["a6_vif_provenance"]["source_sha256"],
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "gpboost_version": gpb.__version__,
            "created_utc": utc_now(),
        }
        estimate_path = attempt_dir / "stage_a_estimate.json"
        emit_progress(f"STAGE_A_{stage_name}", "COVARIANCE_OPTIMIZATION_COMPLETED", update_status=False, covariance_parameters=covariance, covariance_diagnostics=diagnostics, optimizer_iterations=iterations, optimizer_wall_seconds=float(elapsed), warnings=estimate["warnings"])
        estimate["runtime"]["pre_serialization_wall_seconds"] = float(time.perf_counter() - stage_started)
        write_json_atomic(estimate_path, estimate)
        marker = {
            "status": "COMPLETED",
            "stage": stage_name,
            "fingerprint": fingerprint,
            "estimate_path": str(estimate_path),
            "estimate_sha256": sha256_file(estimate_path),
            "completed_utc": utc_now(),
        }
        write_json_atomic(attempt_dir / "completion.json", marker)
        write_json_atomic(attempt_dir / "status.json", marker)
        estimate["attempt_directory"] = str(attempt_dir)
        estimate["estimate_sha256"] = marker["estimate_sha256"]
        estimate["reused"] = False
        emit_progress(f"STAGE_A_{stage_name}", "COMPLETED", covariance_parameters=covariance, covariance_diagnostics=diagnostics, observations=int(len(y)), wall_seconds=estimate["runtime"]["wall_seconds"], cpu_seconds=estimate["runtime"]["stage_cpu_seconds"], estimate_sha256=marker["estimate_sha256"])
        return estimate
    except Exception as exc:
        state = "INCOMPLETE_BUDGET_EXCEEDED" if isinstance(exc, A6VIFDeadlineExceeded) else "FAILED"
        write_json_atomic(attempt_dir / "failure.json", {"status": state, "stage": stage_name, "error": str(exc), "traceback": traceback.format_exc(), "failed_utc": utc_now(), "fingerprint": fingerprint})
        write_json_atomic(attempt_dir / "status.json", {"status": state, "stage": stage_name, "error": str(exc), "failed_utc": utc_now(), "fingerprint": fingerprint})
        raise


def thread_count() -> int:
    requested = int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1))
    if requested != 16:
        raise A6VIFBlocked(f"A6-VIF requires exactly 16 allocated CPU threads, found {requested}")
    return requested


def covariance_vector(values: dict[str, float]) -> np.ndarray:
    return np.asarray([float(values[name]) for name in PARAMETER_NAMES], dtype=np.float64)


def fixed_covariance_train(
    gpb: Any,
    config: dict[str, Any],
    seed: int,
    x_train: np.ndarray,
    y_train: np.ndarray,
    offset_train: np.ndarray,
    coords_train: np.ndarray,
    rounds: int,
    covariance: dict[str, float],
    valid: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    early_stopping: bool = False,
) -> tuple[Any, Any, dict[str, Any]]:
    fit_started = time.perf_counter()
    stage = "STAGE_B_INNER_BOOSTING" if early_stopping else "STAGE_B_FINAL_BOOSTING"
    emit_progress(stage, "GP_INITIALIZATION_STARTED", training_rows=int(len(y_train)), feature_count=int(x_train.shape[1]), inducing_points=int(config["gpboost"]["num_ind_points"]), vecchia_neighbors=int(config["gpboost"]["num_neighbors"]))
    gp_init_started = time.perf_counter()
    gp = make_gp_model(gpb, coords_train, seed, config, thread_count())
    gp.set_optim_params({"init_cov_pars": covariance_vector(covariance)})
    gp_init_seconds = time.perf_counter() - gp_init_started
    emit_progress(stage, "COVARIANCE_INITIALIZED_FIXED", update_status=False, covariance_parameters={name: float(covariance[name]) for name in PARAMETER_NAMES}, parameter_order=PARAMETER_NAMES, train_gp_model_cov_pars=False)
    data_started = time.perf_counter()
    train_set = A6.make_dataset(gpb, x_train, y_train, offset_train)
    valid_set = None
    if valid is not None:
        x_valid, y_valid, offset_valid, coords_valid = valid
        valid_set = A6.make_dataset(gpb, x_valid, y_valid, offset_valid)
        gp.set_prediction_data(
            vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
            num_neighbors_pred=int(config["gpboost"]["num_neighbors_pred"]),
            gp_coords_pred=coords_valid,
        )
    dataset_setup_seconds = time.perf_counter() - data_started
    emit_progress(stage, "DATASETS_AND_PREDICTION_NEIGHBORS_READY", update_status=False, train_rows=int(len(y_train)), validation_rows=int(len(valid[1])) if valid is not None else 0, prediction_neighbors=int(config["gpboost"]["num_neighbors_pred"]) if valid is not None else None)
    params = A6.model_params(config, seed)
    params["num_threads"] = thread_count()
    started = time.perf_counter()
    caught: list[str] = []
    emit_progress(stage, "BOOSTING_STARTED", update_status=False, maximum_rounds=int(rounds), early_stopping=bool(early_stopping), patience=int(config["boosting"]["early_stopping_rounds"]) if early_stopping else None)
    warning_start = len(_WARNING_MESSAGES)
    booster = gpb.train(
            params=params,
            train_set=train_set,
            num_boost_round=int(rounds),
            gp_model=gp,
            use_gp_model_for_validation=True,
            train_gp_model_cov_pars=False,
            valid_sets=[valid_set] if valid_set is not None else None,
            valid_names=["inner"] if valid_set is not None else None,
            early_stopping_rounds=int(config["boosting"]["early_stopping_rounds"]) if early_stopping else None,
            callbacks=[gpboost_progress_callback(gp, "STAGE_B_INNER_BOOSTING" if early_stopping else "STAGE_B_FINAL_BOOSTING")],
            verbose_eval=False,
            keep_training_booster=True,
    )
    caught = _WARNING_MESSAGES[warning_start:]
    enforce_internal_deadline("STAGE_B_INNER_BOOSTING" if early_stopping else "STAGE_B_FINAL_BOOSTING")
    elapsed = time.perf_counter() - started
    before_covariance = {name: float(covariance[name]) for name in PARAMETER_NAMES}
    after_covariance, after_table = covariance_table(gp)
    differences = {name: float(after_covariance[name] - before_covariance[name]) for name in PARAMETER_NAMES}
    fixed_ok = bool(all(abs(value) <= 1e-10 for value in differences.values()))
    if not fixed_ok:
        raise A6VIFBlocked(f"GPBoost changed covariance parameters with train_gp_model_cov_pars=False: {differences}")
    current_iteration = int(booster.current_iteration())
    best_iteration = int(getattr(booster, "best_iteration", 0) or 0)
    info = {
        "seed": int(seed),
        "requested_rounds": int(rounds),
        "best_iteration": best_iteration,
        "current_iteration": current_iteration,
        "selected_rounds": best_iteration if early_stopping and best_iteration > 0 else current_iteration,
        "runtime_seconds": float(elapsed),
        "gp_initialization_seconds": float(gp_init_seconds),
        "dataset_setup_seconds": float(dataset_setup_seconds),
        "fit_total_seconds": float(time.perf_counter() - fit_started),
        "train_gp_model_cov_pars": False,
        "use_gp_model_for_validation": True,
        "covariance_parameters_before": before_covariance,
        "covariance_parameters_after": after_covariance,
        "covariance_parameter_table_after": after_table,
        "covariance_parameter_differences": differences,
        "covariance_fixed_verified": fixed_ok,
        "prediction_neighbors_explicit": int(config["gpboost"]["num_neighbors_pred"]),
        "warnings": caught,
        "num_mode_finding_steps": int(gp._get_num_mode_finding_steps()) if callable(getattr(gp, "_get_num_mode_finding_steps", None)) else None,
        "num_optimizer_iterations": int(gp._get_num_optim_iter()) if callable(getattr(gp, "_get_num_optim_iter", None)) else None,
        "converged": bool(current_iteration > 0 and fixed_ok),
    }
    if info["selected_rounds"] <= 0:
        info["selected_rounds"] = int(rounds)
    emit_progress(stage, "BOOSTING_COMPLETED", update_status=False, current_iteration=current_iteration, best_iteration=best_iteration, selected_rounds=int(info["selected_rounds"]), fit_wall_seconds=float(info["fit_total_seconds"]), boosting_wall_seconds=float(elapsed), covariance_parameters=after_covariance, covariance_parameter_changes=differences, covariance_fixed_verified=fixed_ok, mode_finding_steps=info["num_mode_finding_steps"], optimizer_iterations=info["num_optimizer_iterations"], warnings=caught)
    return booster, gp, info


def get_original_a6_row(original_root: Path, candidate: str, fold: int, seed: int, data: Any) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    metric_path = original_root / "results/fold_seed_metrics.csv"
    prediction_path = original_root / "predictions" / f"{candidate}_fold{fold}_seed{seed}.npz"
    manifest_path = original_root / "manifests" / f"{candidate}_fold{fold}_seed{seed}.json"
    if not metric_path.exists() or not prediction_path.exists() or not manifest_path.exists():
        raise RuntimeError(f"original A6 comparison artifacts are incomplete for {candidate}, fold {fold}, seed {seed}")
    metrics = pd.read_csv(metric_path)
    candidate_rows = metrics.loc[metrics["candidate"].astype(str).eq(candidate)]
    selected = candidate_rows.loc[
        candidate_rows["fold"].astype(int).eq(int(fold))
        & candidate_rows["seed"].astype(int).eq(int(seed))
    ]
    with np.load(prediction_path, allow_pickle=False) as archive:
        arrays = {key: np.asarray(archive[key]) for key in archive.files}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("candidate") != candidate or int(manifest.get("seed", -1)) != int(seed):
        raise RuntimeError(f"original A6 manifest identity mismatch for {candidate}, fold {fold}, seed {seed}")
    if len(selected) == 0:
        raise RuntimeError(f"original A6 metrics row is missing for {candidate}, fold {fold}, seed {seed}")
    fold_record = next((item for item in A6.FOLDS if int(item["fold"]) == int(fold)), None)
    if fold_record is None:
        raise RuntimeError(f"unknown original A6 fold {fold}")
    train_times = np.asarray(fold_record["train_indices"], dtype=np.int64)
    train_prevalence = float(np.mean(data.counts[train_times] > 0))
    computed_metrics = A5.metric_frame(
        arrays["y"], arrays["p"], arrays["conditional"], arrays["mu"], train_prevalence,
    )
    matched_rows = []
    for _, row in selected.iterrows():
        if all(
            name in row and pd.notna(row[name]) and math.isclose(float(row[name]), float(computed_metrics[name]), rel_tol=0.0, abs_tol=1e-12)
            for name in A6.REQUIRED_METRICS
        ):
            matched_rows.append(row)
    if not matched_rows:
        raise RuntimeError(f"no original A6 metrics row matches its prediction artifact for {candidate}, fold {fold}, seed {seed}")
    canonical_metrics = matched_rows[0].to_dict()
    canonical_metrics.update({name: float(computed_metrics[name]) for name in A6.REQUIRED_METRICS})
    return canonical_metrics, arrays, {
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "prediction_path": str(prediction_path),
        "prediction_sha256": sha256_file(prediction_path),
        "metrics_row_count": int(len(selected)),
        "metrics_rows_matching_prediction": int(len(matched_rows)),
        "metrics_recomputed_from_prediction": True,
        "original_runtime_seconds_total": float(manifest.get("runtime_seconds_total", math.nan)),
        "original_manifest": manifest,
    }


def prediction_metrics_from_record(record: dict[str, Any]) -> dict[str, float]:
    return {name: float(record[name]) for name in A6.REQUIRED_METRICS if name in record and pd.notna(record[name])}


def native_gpboost_warning_lines(output_root: Path) -> list[str]:
    warnings_found: list[str] = []
    for path in (output_root / "logs/runner.stdout.log", output_root / "logs/runner.stderr.log"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "[Warning]" in line or "[ERROR]" in line or "[Fatal]" in line:
                warnings_found.append(line.strip())
    return list(dict.fromkeys(warnings_found))


def save_a3_baseline(fold: Any, data: Any, fold_root: Path, frozen_output: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    fold_root.mkdir(parents=True, exist_ok=True)
    metric_path = fold_root / "a3_metrics.json"
    prediction_path = fold_root / "a3_predictions.npz"
    if metric_path.exists() and prediction_path.exists():
        record = json.loads(metric_path.read_text(encoding="utf-8"))
        if sha256_file(prediction_path) != record.get("prediction_sha256"):
            raise RuntimeError("existing A3 baseline prediction checksum failed; refusing to overwrite")
        with np.load(prediction_path, allow_pickle=False) as archive:
            arrays = {key: np.asarray(archive[key]) for key in archive.files}
        if record.get("input_sha256") == data.hashes:
            return record["record"], arrays
        raise RuntimeError("existing A3 fold baseline has incompatible inputs; refusing to overwrite")
    frozen = A5.load_frozen_a3_predictions(frozen_output, fold.fold, data.counts, fold.validation_times)
    raw_validation = data.a3[np.asarray(fold.validation_times, dtype=np.int64)].reshape(-1, 34)
    precise_x = A5.apply_frozen_scaling(
        raw_validation,
        fold.scaling,
        A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES,
    )
    precise_predictions = A5.AUG.predict(fold.a3_state, precise_x)
    reproduced = (
        fold.counts[np.asarray(fold.validation_times, dtype=np.int64)].reshape(-1).astype(np.int64),
        *precise_predictions,
    )
    for name, expected, observed in zip(("y", "p", "conditional", "mu"), (frozen[k] for k in ("y", "p", "conditional", "mu")), reproduced):
        if name == "y":
            if not np.array_equal(expected, observed):
                raise RuntimeError("frozen A3 validation labels do not align with A6-VIF fold rows")
        elif not np.allclose(expected, observed, rtol=0, atol=1e-9):
            raise RuntimeError(f"frozen A3 {name} reproduction failed for fold {fold.fold}")
    y, p, conditional, mu = (np.asarray(frozen[key]) for key in ("y", "p", "conditional", "mu"))
    train_prev = float(np.mean(fold.counts[fold.train_times] > 0))
    record, arrays = A5.fold_prediction_record(
        "A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu, train_prev,
        {"converged": True, "a3_fit": "frozen_A3", "reproduced_max_abs": {"p": float(np.max(np.abs(p - reproduced[1]))), "conditional": float(np.max(np.abs(conditional - reproduced[2]))), "mu": float(np.max(np.abs(mu - reproduced[3])))}}
    )
    write_npz_atomic(prediction_path, arrays)
    write_json_atomic(metric_path, {"record": record, "input_sha256": dict(data.hashes), "prediction_sha256": sha256_file(prediction_path)})
    return record, arrays


def validate_outer_fold(fold: Any) -> None:
    train = np.asarray(fold.train_times, dtype=np.int64)
    validation = np.asarray(fold.validation_times, dtype=np.int64)
    if len(train) == 0 or len(validation) == 0 or not set(train).isdisjoint(set(validation)):
        raise RuntimeError("outer training and validation weeks overlap or are empty")
    if int(train.max()) >= int(validation.min()):
        raise RuntimeError("outer validation includes a week at or before the training cutoff")


def find_completed_seed(
    seed_root: Path,
    seed: int,
    config: dict[str, Any],
    data: Any,
    training_node_ids: np.ndarray | None = None,
    prediction_node_ids: np.ndarray | None = None,
) -> dict[str, Any] | None:
    if not seed_root.exists():
        return None
    for attempt_dir in sorted(seed_root.glob("attempt_*")):
        manifest_path = attempt_dir / "completion.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "COMPLETED":
            continue
        if manifest.get("seed") != int(seed):
            continue
        if manifest.get("input_sha256") != data.hashes or manifest.get("config_sha256") != config["a6_vif_provenance"]["opt_config_sha256"] or manifest.get("source_sha256") != config["a6_vif_provenance"]["source_sha256"]:
            continue
        if training_node_ids is not None and manifest.get("training_node_ids_sha256") != sha256_json(np.asarray(training_node_ids, dtype=np.int64).tolist()):
            continue
        if prediction_node_ids is not None and manifest.get("prediction_node_ids_sha256") != sha256_json(np.asarray(prediction_node_ids, dtype=np.int64).tolist()):
            continue
        for rel, digest in manifest["checksums"].items():
            path = attempt_dir / rel
            if not path.exists() or sha256_file(path) != digest:
                raise RuntimeError(f"completed seed artifact checksum failed: {path}")
        return manifest
    return None


def next_seed_attempt(seed_root: Path) -> Path:
    seed_root.mkdir(parents=True, exist_ok=True)
    return next_attempt_dir(seed_root)


def fit_seed(
    gpb: Any,
    data: Any,
    fold: Any,
    fold_root: Path,
    fold_id: int,
    seed: int,
    coords_xy: np.ndarray,
    config: dict[str, Any],
    data_hashes: dict[str, str],
    inner_cov: dict[str, Any],
    outer_cov: dict[str, Any],
    seed_count: int,
    train_nodes: np.ndarray | None = None,
    prediction_nodes: np.ndarray | None = None,
    unit_scope: str = "primary_temporal_oof",
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    seed_root = fold_root / "seeds" / f"seed_{seed}"
    train_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64) if train_nodes is None else np.asarray(train_nodes, dtype=np.int64)
    prediction_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64) if prediction_nodes is None else np.asarray(prediction_nodes, dtype=np.int64)
    existing = find_completed_seed(seed_root, seed, config, data, train_nodes, prediction_nodes)
    if existing is not None:
        prediction_path = Path(existing["artifact_paths"]["prediction"])
        with np.load(prediction_path, allow_pickle=False) as archive:
            arrays = {key: np.asarray(archive[key]) for key in archive.files}
        return existing["record"], arrays, existing

    attempt_dir = next_seed_attempt(seed_root)
    write_json_atomic(attempt_dir / "status.json", {"status": "RUNNING", "seed": int(seed), "fold": int(fold_id), "started_utc": utc_now()})
    started_total = time.perf_counter()
    before_total = runtime_snapshot()
    try:
        emit_progress("STAGE_B", "STARTED", fold=int(fold_id), seed=int(seed), full_training_nodes=int(len(train_nodes)), prediction_nodes=int(len(prediction_nodes)))
        evaluation_mask = np.zeros(A6.NODE_COUNT, dtype=bool)
        evaluation_mask[prediction_nodes] = True
        emit_progress("STAGE_B_INNER_DATA", "PREPARATION_STARTED", update_status=False)
        inner_train, inner_monitor = A5.inner_split(
            fold.train_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or not set(inner_train).issubset(set(fold.train_times)) or not set(inner_monitor).issubset(set(fold.train_times)):
            raise RuntimeError("inner early-stopping split is not contained in the outer training partition")
        if fold_id == 3 and (not np.array_equal(inner_train, np.arange(41)) or not np.array_equal(inner_monitor, np.arange(41, 52))):
            raise A6VIFBlocked(f"fold-3 inner partition differs from the authorized 0-40/41-51 contract: train={inner_train.tolist()}, monitor={inner_monitor.tolist()}")
        x_inner, y_inner, _, offset_inner, coords_inner = flatten_training(fold, inner_train, train_nodes, coords_xy)
        x_monitor, y_monitor, _, offset_monitor, coords_monitor = flatten_training(fold, inner_monitor, train_nodes, coords_xy)
        emit_progress("STAGE_B_INNER_DATA", "PREPARATION_COMPLETED", update_status=False, training_weeks=np.asarray(inner_train, dtype=np.int64).tolist(), monitoring_weeks=np.asarray(inner_monitor, dtype=np.int64).tolist(), training_rows=int(len(y_inner)), monitoring_rows=int(len(y_monitor)))
        inner_booster, inner_gp, inner_info = fixed_covariance_train(
            gpb, config, seed, x_inner, y_inner, offset_inner, coords_inner,
            config["boosting"]["maximum_boosting_rounds"], inner_cov["covariance_parameters"],
            (x_monitor, y_monitor, offset_monitor, coords_monitor), True,
        )
        selected_rounds = int(inner_info["selected_rounds"])
        if selected_rounds < 1 or selected_rounds > int(config["boosting"]["maximum_boosting_rounds"]):
            raise A6VIFBlocked(f"invalid inner-selected boosting rounds: {selected_rounds}")
        inner_info["inner_train_week_indices"] = np.asarray(inner_train, dtype=np.int64).tolist()
        inner_info["inner_monitor_week_indices"] = np.asarray(inner_monitor, dtype=np.int64).tolist()
        inner_info["outer_validation_used"] = False
        emit_progress("STAGE_B", "SELECTED_BOOSTING_ROUNDS", update_status=False, selected_rounds=selected_rounds, inner_train_weeks=np.asarray(inner_train, dtype=np.int64).tolist(), inner_monitor_weeks=np.asarray(inner_monitor, dtype=np.int64).tolist())
        del inner_booster, inner_gp

        emit_progress("STAGE_B_FINAL_DATA", "PREPARATION_STARTED", update_status=False)
        x_train, y_train, _, offset_train, coords_train = flatten_training(fold, fold.train_times, train_nodes, coords_xy)
        if len(y_train) != len(fold.train_times) * len(train_nodes):
            raise RuntimeError("Stage B did not receive the complete outer training dataset")
        if set(np.unique(coords_train[:, 0].astype(np.int64))) - set(np.asarray(fold.train_times, dtype=np.int64)):
            raise RuntimeError("outer validation or future weeks entered Stage B coordinates")
        emit_progress("STAGE_B_FINAL_DATA", "PREPARATION_COMPLETED", update_status=False, training_weeks=np.asarray(fold.train_times, dtype=np.int64).tolist(), training_rows=int(len(y_train)), feature_count=int(x_train.shape[1]), offset_range=[float(offset_train.min()), float(offset_train.max())])
        final_booster, final_gp, final_info = fixed_covariance_train(
            gpb, config, seed, x_train, y_train, offset_train, coords_train,
            selected_rounds, outer_cov["covariance_parameters"],
        )
        train_prevalence = float(np.mean(y_train))

        predict_started = time.perf_counter()
        emit_progress("PREDICTION", "STARTED", fold=int(fold_id), seed=int(seed), prediction_weeks=np.asarray(fold.validation_times, dtype=np.int64).tolist(), prediction_neighbors=int(config["gpboost"]["num_neighbors_pred"]))
        x_eval, y_eval, _, offset_eval, coords_eval = flatten_training(fold, fold.validation_times, prediction_nodes, coords_xy)
        prediction_setup_started = time.perf_counter()
        final_gp.set_prediction_data(
            vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
            num_neighbors_pred=int(config["gpboost"]["num_neighbors_pred"]),
            gp_coords_pred=coords_eval,
        )
        prediction_setup_seconds = time.perf_counter() - prediction_setup_started
        emit_progress("PREDICTION", "PREDICTION_NEIGHBORS_READY", update_status=False, rows=int(len(y_eval)), prediction_setup_seconds=float(prediction_setup_seconds), vecchia_pred_type=config["gpboost"]["vecchia_pred_type"], num_neighbors_pred=int(config["gpboost"]["num_neighbors_pred"]))
        prediction_first_started = time.perf_counter()
        first = final_booster.predict(
            x_eval,
            gp_coords_pred=coords_eval,
            offset_pred=offset_eval,
            num_iteration=selected_rounds,
        )
        first_prediction_seconds = time.perf_counter() - prediction_first_started
        emit_progress("PREDICTION", "PRIMARY_PREDICTION_COMPLETED", update_status=False, elapsed_seconds=float(first_prediction_seconds))
        repeat_started = time.perf_counter()
        second = final_booster.predict(
            x_eval,
            gp_coords_pred=coords_eval,
            offset_pred=offset_eval,
            num_iteration=selected_rounds,
        )
        repeatability_seconds = time.perf_counter() - repeat_started
        predict_seconds = time.perf_counter() - predict_started
        if not isinstance(first, dict) or "response_mean" not in first or not isinstance(second, dict) or "response_mean" not in second:
            raise A6VIFBlocked("GPBoost prediction did not return response_mean with the A3 offset")
        probability = np.asarray(first["response_mean"], dtype=np.float64)
        repeat_probability = np.asarray(second["response_mean"], dtype=np.float64)
        repeat_difference = float(np.max(np.abs(probability - repeat_probability))) if len(probability) else 0.0
        tolerance = float(config["prediction_repeatability"]["absolute_tolerance"])
        repeatability = bool(np.allclose(probability, repeat_probability, rtol=0, atol=tolerance))
        emit_progress("PREDICTION_REPEATABILITY", "COMPLETED" if repeatability else "FAILED", update_status=False, max_abs_difference=repeat_difference, absolute_tolerance=tolerance, repeat_prediction_seconds=float(repeatability_seconds))
        if not repeatability:
            raise A6VIFBlocked(f"label-free prediction repeatability failed: max_abs_difference={repeat_difference}, tolerance={tolerance}")
        if probability.shape != y_eval.shape or not np.isfinite(probability).all() or np.any(probability < -1e-12) or np.any(probability > 1 + 1e-12):
            raise A6VIFBlocked("A6-VIF returned invalid validation probabilities")
        probability = np.clip(probability, 0.0, 1.0)

        y_a3, p_a3, conditional_a3, mu_a3 = A5.numpy_a3_predictions(fold, fold.validation_times, evaluation_mask)
        if not np.array_equal(y_a3, y_eval):
            raise RuntimeError("prediction node mask and validation labels are not aligned")
        train_prevalence = float(np.mean(fold.counts[np.asarray(fold.train_times)[:, None], train_nodes] > 0))
        record, arrays = A5.fold_prediction_record(
            VIF_CANDIDATE,
            fold_id,
            seed,
            fold.validation_times,
            evaluation_mask,
            y_eval,
            probability,
            conditional_a3,
            mu_a3,
            train_prevalence,
            {
                "converged": bool(inner_info["covariance_fixed_verified"] and final_info["covariance_fixed_verified"]),
                "selected_rounds": selected_rounds,
                "gpboost_version": gpb.__version__,
                "num_neighbors": 8,
                "num_neighbors_pred": 40,
                "covariance_parameters": outer_cov["covariance_parameters"],
                "covariance_fixed_verified": bool(final_info["covariance_fixed_verified"]),
            },
        )
        record.update({
            "stage_a_inner_runtime_seconds": float(inner_cov["runtime"]["wall_seconds"]),
            "stage_a_outer_runtime_seconds": float(outer_cov["runtime"]["wall_seconds"]),
            "stage_b_inner_round_selection_seconds": float(inner_info["runtime_seconds"]),
            "stage_b_inner_fit_total_seconds": float(inner_info["fit_total_seconds"]),
            "stage_b_inner_gp_initialization_seconds": float(inner_info["gp_initialization_seconds"]),
            "stage_b_inner_dataset_setup_seconds": float(inner_info["dataset_setup_seconds"]),
            "stage_b_full_training_seconds": float(final_info["runtime_seconds"]),
            "stage_b_final_fit_total_seconds": float(final_info["fit_total_seconds"]),
            "stage_b_final_gp_initialization_seconds": float(final_info["gp_initialization_seconds"]),
            "stage_b_final_dataset_setup_seconds": float(final_info["dataset_setup_seconds"]),
            "prediction_runtime_seconds": float(predict_seconds),
            "prediction_setup_seconds": float(prediction_setup_seconds),
            "prediction_primary_seconds": float(first_prediction_seconds),
            "prediction_repeatability_seconds": float(repeatability_seconds),
            "inner_covariance_diagnostics": inner_cov["covariance_diagnostics"],
            "outer_covariance_diagnostics": outer_cov["covariance_diagnostics"],
            "inner_covariance_fixed_verified": bool(inner_info["covariance_fixed_verified"]),
            "latent_mode_solver_status": "completed_without_exception; GPBoost Python API exposes iteration counts but no convergence boolean",
            "latent_mode_convergence_boolean_available": False,
            "latent_mode_finding_steps_inner": inner_info.get("num_mode_finding_steps"),
            "latent_mode_finding_steps_final": final_info.get("num_mode_finding_steps"),
            "numerical_warnings_inner": inner_info.get("warnings", []),
            "numerical_warnings_final": final_info.get("warnings", []),
            "observations_covariance_inner": int(inner_cov["observations_used"]),
            "observations_covariance_outer": int(outer_cov["observations_used"]),
            "observations_boosting": int(len(y_train)),
            "prediction_repeatability_max_abs_difference": repeat_difference,
            "outer_validation_labels_supplied_to_prediction": False,
            "outer_validation_used_for_round_selection": False,
            "training_offset": "frozen_A3_logit_offset_init_score",
            "prediction_offset": "frozen_A3_logit_offset_pred",
            "coordinate_order": ["time_week_offset", "x_km", "y_km"],
            "spatial_support_audit": support_audit(data, fold, coords_xy, coords_eval, train_nodes),
            "unit_scope": unit_scope,
            "training_node_count": int(len(train_nodes)),
            "evaluation_node_count": int(len(prediction_nodes)),
        })

        booster_path = attempt_dir / "a6_vif.booster.txt"
        gp_path = attempt_dir / "a6_vif.gpmodel.json"
        prediction_path = attempt_dir / "predictions.npz"
        emit_progress("SERIALIZATION", "STARTED", update_status=False, output_directory=str(attempt_dir))
        serialization_started = time.perf_counter()
        save_model_atomic(final_booster, booster_path)
        save_model_atomic(final_gp, gp_path)
        write_npz_atomic(prediction_path, arrays)
        for artifact in (booster_path, gp_path, prediction_path):
            if not artifact.exists() or artifact.stat().st_size <= 0:
                raise A6VIFBlocked(f"completed model/prediction artifact is empty: {artifact}")
        serialization_seconds = time.perf_counter() - serialization_started
        emit_progress("SERIALIZATION", "COMPLETED", update_status=False, elapsed_seconds=float(serialization_seconds), files=[{"path": str(path), "size_bytes": int(path.stat().st_size)} for path in (booster_path, gp_path, prediction_path)])
        elapsed_total = time.perf_counter() - started_total
        after_total = runtime_snapshot()
        stage_b_cpu_seconds = max(0.0, after_total["cpu_seconds"] - before_total["cpu_seconds"])
        stage_a_shared_runtime = float(inner_cov["runtime"]["wall_seconds"] + outer_cov["runtime"]["wall_seconds"])
        stage_a_shared_cpu = float(inner_cov["runtime"]["cpu_seconds"] + outer_cov["runtime"]["cpu_seconds"])
        seed_count = max(1, int(seed_count))
        record["stage_b_runtime_seconds_total"] = float(elapsed_total)
        record["stage_a_shared_runtime_seconds_total"] = stage_a_shared_runtime
        record["stage_a_allocated_runtime_seconds"] = stage_a_shared_runtime / seed_count
        record["runtime_seconds_total"] = float(elapsed_total + stage_a_shared_runtime / seed_count)
        record["comparable_model_unit_runtime_seconds"] = float(record["runtime_seconds_total"])
        record["total_execution_runtime_seconds_through_serialization"] = float(time.perf_counter() - _EXECUTION_STARTED) if _EXECUTION_STARTED else None
        record["serialization_seconds"] = float(serialization_seconds)
        record["stage_b_cpu_seconds"] = stage_b_cpu_seconds
        record["stage_a_allocated_cpu_seconds"] = stage_a_shared_cpu / seed_count
        record["cpu_seconds_total"] = stage_b_cpu_seconds + stage_a_shared_cpu / seed_count
        record["peak_rss_bytes_process"] = after_total["peak_rss_bytes"]
        record["allocated_cpus"] = thread_count()
        record["cpu_utilization_fraction"] = float(record["cpu_seconds_total"] / max(record["runtime_seconds_total"] * thread_count(), 1e-9))
        record["stage_b_covariance_parameter_changes"] = final_info["covariance_parameter_differences"]
        record["stage_b_covariance_train_flag"] = False
        write_json_atomic(attempt_dir / "metrics.json", record)
        checksums = {
            "a6_vif.booster.txt": sha256_file(booster_path),
            "a6_vif.gpmodel.json": sha256_file(gp_path),
            "predictions.npz": sha256_file(prediction_path),
            "metrics.json": sha256_file(attempt_dir / "metrics.json"),
        }
        completion = {
            "status": "COMPLETED",
            "candidate": VIF_CANDIDATE,
            "fold": int(fold_id),
            "seed": int(seed),
            "attempt": attempt_dir.name,
            "record": record,
            "artifact_paths": {"booster": str(booster_path), "gp_model": str(gp_path), "prediction": str(prediction_path)},
            "checksums": checksums,
            "input_sha256": data_hashes,
            "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_vif_provenance"]["source_sha256"],
            "inner_covariance_sha256": inner_cov["estimate_sha256"],
            "outer_covariance_sha256": outer_cov["estimate_sha256"],
            "training_node_ids_sha256": sha256_json(train_nodes.tolist()),
            "prediction_node_ids_sha256": sha256_json(prediction_nodes.tolist()),
            "completed_utc": utc_now(),
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "execution_branch": os.environ.get("STGNN_GIT_BRANCH", "unknown"),
        }
        write_json_atomic(attempt_dir / "completion.json", completion)
        write_json_atomic(attempt_dir / "status.json", {"status": "COMPLETED", "completion_path": str(attempt_dir / "completion.json"), "completed_utc": utc_now()})
        emit_progress("STAGE_B", "COMPLETED", fold=int(fold_id), seed=int(seed), selected_rounds=selected_rounds, model_unit_wall_seconds=float(record["runtime_seconds_total"]), process_cpu_hours=float(record["cpu_seconds_total"] / 3600.0), peak_rss_bytes=float(record["peak_rss_bytes_process"]))
        del final_booster, final_gp
        return record, arrays, completion
    except Exception as exc:
        state = "INCOMPLETE_BUDGET_EXCEEDED" if isinstance(exc, A6VIFDeadlineExceeded) else "FAILED"
        write_json_atomic(attempt_dir / "failure.json", {"status": state, "fold": int(fold_id), "seed": int(seed), "error": str(exc), "traceback": traceback.format_exc(), "failed_utc": utc_now()})
        write_json_atomic(attempt_dir / "status.json", {"status": state, "fold": int(fold_id), "seed": int(seed), "error": str(exc), "failed_utc": utc_now()})
        raise


def prepare_fold(args: argparse.Namespace, data: Any, fold_id: int, frozen_output: Path) -> tuple[Any, dict[str, Any], dict[str, np.ndarray]]:
    emit_progress("FOLD_AND_OFFSET_VERIFICATION", "STARTED", fold=int(fold_id))
    fold_record = next((item for item in A6.FOLDS if int(item["fold"]) == int(fold_id)), None)
    if fold_record is None:
        raise ValueError(f"unknown A6 temporal fold {fold_id}")
    fold = A5.prepare_temporal_fold(data, fold_record, frozen_output)
    validate_outer_fold(fold)
    if fold_id == 3 and (not np.array_equal(fold.train_times, np.arange(52)) or not np.array_equal(fold.validation_times, np.arange(52, 60))):
        raise A6VIFBlocked(f"canonical fold 3 differs from authorized weeks 0-51/52-59: train={fold.train_times.tolist()}, validation={fold.validation_times.tolist()}")
    fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
    a3_record, a3_arrays = save_a3_baseline(fold, data, fold_root, frozen_output)
    emit_progress("FOLD_AND_OFFSET_VERIFICATION", "COMPLETED", fold=int(fold_id), outer_training_weeks=np.asarray(fold.train_times, dtype=np.int64).tolist(), outer_validation_weeks=np.asarray(fold.validation_times, dtype=np.int64).tolist(), frozen_a3_offset_reproduced=True, predictor_count=int(fold.x.shape[2]))
    return fold, a3_record, a3_arrays


def run_fold(args: argparse.Namespace, config: dict[str, Any], opt: dict[str, Any], data: Any, gpb: Any, fold_id: int, seeds: list[int], mode: str) -> dict[str, Any]:
    if any(seed not in config["seeds"] for seed in seeds):
        raise ValueError(f"A6-VIF seed not in original A6 seed set: {seeds}")
    fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
    with fold_lock(fold_root / ".fold.lock"):
        fold, a3_record, a3_arrays = prepare_fold(args, data, fold_id, args.a3_frozen_output)
        coords_xy = A6.node_coordinates(data)
        train_times = np.asarray(fold.train_times, dtype=np.int64)
        inner_train, inner_monitor = A5.inner_split(
            train_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or not set(inner_train).issubset(set(train_times)) or not set(inner_monitor).issubset(set(train_times)):
            raise RuntimeError("inner early-stopping split violates outer training boundaries")
        all_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64)
        inner_cov = estimate_covariance(gpb, fold, inner_train, all_nodes, coords_xy, fold_root, data, config, fold_id, "inner_round_selection", thread_count())
        outer_cov = estimate_covariance(gpb, fold, train_times, all_nodes, coords_xy, fold_root, data, config, fold_id, "outer_final_fit", thread_count())
        results: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for seed in seeds:
            record, arrays, completion = fit_seed(gpb, data, fold, fold_root, fold_id, int(seed), coords_xy, config, data.hashes, inner_cov, outer_cov, len(seeds))
            results.append(record)
            statuses.append({"seed": int(seed), "status": completion["status"], "attempt": completion.get("attempt")})
        metrics_path = fold_root / "fold_seed_metrics.csv"
        requested_frame = pd.DataFrame(results)
        if metrics_path.exists():
            old = pd.read_csv(metrics_path)
            old_keys = set(zip(old["fold"].astype(int), old["seed"].astype(int)))
            new_keys = set(zip(requested_frame["fold"].astype(int), requested_frame["seed"].astype(int)))
            if old_keys != new_keys:
                raise RuntimeError(f"existing completed fold metrics differ in seed coverage: {metrics_path}")
            old_metrics = old.sort_values(["fold", "seed"]).reset_index(drop=True)
            new_metrics = requested_frame.sort_values(["fold", "seed"]).reset_index(drop=True)
            for metric in A6.REQUIRED_METRICS:
                if metric in old_metrics and not np.allclose(old_metrics[metric], new_metrics[metric], rtol=0, atol=1e-12, equal_nan=True):
                    raise RuntimeError(f"existing completed fold metrics changed for {metric}: {metrics_path}")
        else:
            write_csv_atomic(metrics_path, requested_frame)
        status = {
            "status": "COMPLETED",
            "mode": mode,
            "fold": int(fold_id),
            "seed_status": statuses,
            "inner_covariance_attempt": inner_cov["attempt_directory"],
            "outer_covariance_attempt": outer_cov["attempt_directory"],
            "covariance_reused": {"inner": bool(inner_cov.get("reused")), "outer": bool(outer_cov.get("reused"))},
            "input_sha256": dict(data.hashes),
            "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_vif_provenance"]["source_sha256"],
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "completed_utc": utc_now(),
        }
        fold_status_path = fold_root / "fold_status.json"
        if fold_status_path.exists():
            old_status = json.loads(fold_status_path.read_text(encoding="utf-8"))
            if old_status.get("status") != "COMPLETED" or old_status.get("input_sha256") != status["input_sha256"] or old_status.get("config_sha256") != status["config_sha256"] or old_status.get("source_sha256") != status["source_sha256"]:
                raise RuntimeError(f"existing completed fold status conflicts with this run: {fold_status_path}")
        else:
            write_json_atomic(fold_status_path, status)
        return {"status": "COMPLETED", "fold": fold_id, "metrics": results, "a3_record": a3_record, "a3_arrays": a3_arrays, "inner_covariance": inner_cov, "outer_covariance": outer_cov}


def require_primary_spatial_authorization(output_root: Path) -> dict[str, Any]:
    decision_path = output_root / "results/a6_vif_decision.json"
    status_path = output_root / "results/aggregate_status.json"
    if not decision_path.exists() or not status_path.exists():
        raise RuntimeError("spatial-stress execution requires completed primary temporal aggregation")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    aggregate_status = json.loads(status_path.read_text(encoding="utf-8"))
    if aggregate_status.get("status") != "COMPLETED" or not decision.get("primary_guardrails_passed", False):
        raise RuntimeError("spatial-stress execution is not authorized because primary temporal guardrails did not pass")
    return decision


def prepare_spatial_stress_fold(data: Any, spatial_fold: int) -> tuple[Any, np.ndarray, np.ndarray, dict[str, Any], dict[str, np.ndarray]]:
    if data.spatial_assignment is None:
        raise RuntimeError("spatial-stress assignment file was not loaded")
    assignment_frame = data.spatial_assignment
    if "model_node_id" not in assignment_frame or "spatial_fold" not in assignment_frame:
        raise RuntimeError("spatial-stress assignment lacks model_node_id/spatial_fold")
    if not np.array_equal(assignment_frame["model_node_id"].to_numpy(np.int64), np.arange(A6.NODE_COUNT)):
        raise RuntimeError("spatial-stress node assignments are not in canonical node order")
    assignment = assignment_frame["spatial_fold"].to_numpy(np.int64)
    spatial_values = np.unique(assignment)
    if len(spatial_values) < 2 or spatial_fold not in set(spatial_values.tolist()):
        raise RuntimeError(f"unknown spatial-stress fold {spatial_fold}; configured folds are {spatial_values.tolist()}")
    train_nodes = np.flatnonzero(assignment != int(spatial_fold)).astype(np.int64)
    eval_nodes = np.flatnonzero(assignment == int(spatial_fold)).astype(np.int64)
    if len(train_nodes) == 0 or len(eval_nodes) == 0 or np.intersect1d(train_nodes, eval_nodes).size:
        raise RuntimeError("spatial-stress training and evaluation nodes are empty or overlap")
    all_times = np.arange(A6.DEVELOPMENT_WEEKS, dtype=np.int64)
    raw_train = data.a3[:, train_nodes].reshape(-1, 34)
    raw_all = data.a3.reshape(-1, 34)
    y_train_count = data.counts[:, train_nodes].reshape(-1)
    state, (_, x_all_flat), _, scaling = A5.fit_a3_for_rows(
        raw_train, y_train_count, raw_all, A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES,
    )
    x_all = x_all_flat.reshape(A6.DEVELOPMENT_WEEKS, A6.NODE_COUNT, 34).astype(np.float32)
    design_all = np.concatenate([np.ones((A6.DEVELOPMENT_WEEKS, A6.NODE_COUNT, 1)), x_all.astype(np.float64)], axis=2)
    eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
    xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
    fold_id = 100 + int(spatial_fold)
    fold = A5.FoldPrepared(fold_id, all_times, all_times, x_all, data.counts, eta, xi, {**state, "scaling": scaling}, scaling)
    mask = np.zeros(A6.NODE_COUNT, dtype=bool)
    mask[eval_nodes] = True
    train_prevalence = float(np.mean(y_train_count > 0))
    y_eval, p_eval, conditional_eval, mu_eval = A5.numpy_a3_predictions(fold, all_times, mask)
    a3_record, a3_arrays = A5.fold_prediction_record(
        "A3", fold_id, None, all_times, mask, y_eval, p_eval, conditional_eval, mu_eval, train_prevalence,
        {"converged": True, "a3_fit": "refit_on_spatial_training_nodes", "selection_used": False},
    )
    a3_record.update({"spatial_fold": int(spatial_fold), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)), "unit_scope": "secondary_spatial_stress"})
    return fold, train_nodes, eval_nodes, a3_record, a3_arrays


def run_spatial_fold(args: argparse.Namespace, config: dict[str, Any], data: Any, gpb: Any, spatial_fold: int) -> dict[str, Any]:
    decision = require_primary_spatial_authorization(args.output_root)
    fold_root = args.output_root / "spatial_stress/folds" / f"spatial_fold_{int(spatial_fold):02d}"
    with fold_lock(fold_root / ".fold.lock"):
        fold, train_nodes, eval_nodes, a3_record, a3_arrays = prepare_spatial_stress_fold(data, spatial_fold)
        a3_path = fold_root / "a3_predictions.npz"
        a3_metrics_path = fold_root / "a3_metrics.json"
        if a3_path.exists() or a3_metrics_path.exists():
            if not a3_path.exists() or not a3_metrics_path.exists():
                raise RuntimeError(f"incomplete spatial-stress A3 baseline exists under {fold_root}")
            existing_a3 = json.loads(a3_metrics_path.read_text(encoding="utf-8"))
            if existing_a3.get("prediction_sha256") != sha256_file(a3_path) or existing_a3.get("input_sha256") != data.hashes or existing_a3.get("training_node_ids_sha256") != sha256_json(train_nodes.tolist()):
                raise RuntimeError(f"spatial-stress A3 baseline provenance/checksum conflict under {fold_root}")
            with np.load(a3_path, allow_pickle=False) as archive:
                a3_arrays = {key: np.asarray(archive[key]) for key in archive.files}
            a3_record = existing_a3["record"]
        else:
            write_npz_atomic(a3_path, a3_arrays)
            write_json_atomic(a3_metrics_path, {
                "record": a3_record,
                "input_sha256": dict(data.hashes),
                "training_node_ids_sha256": sha256_json(train_nodes.tolist()),
                "prediction_node_ids_sha256": sha256_json(eval_nodes.tolist()),
                "prediction_sha256": sha256_file(a3_path),
            })

        coords_xy = A6.node_coordinates(data)
        all_times = np.arange(A6.DEVELOPMENT_WEEKS, dtype=np.int64)
        inner_train, inner_monitor = A5.inner_split(
            all_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or set(inner_train) | set(inner_monitor) != set(all_times):
            raise RuntimeError("spatial-stress round-selection split is invalid")
        inner_cov = estimate_covariance(gpb, fold, inner_train, train_nodes, coords_xy, fold_root, data, config, 100 + spatial_fold, "inner_round_selection", thread_count())
        outer_cov = estimate_covariance(gpb, fold, all_times, train_nodes, coords_xy, fold_root, data, config, 100 + spatial_fold, "outer_final_fit", thread_count())
        results: list[dict[str, Any]] = []
        for seed in config["seeds"]:
            record, _, _ = fit_seed(
                gpb, data, fold, fold_root, 100 + int(spatial_fold), int(seed), coords_xy,
                config, data.hashes, inner_cov, outer_cov, len(config["seeds"]),
                train_nodes=train_nodes, prediction_nodes=eval_nodes,
                unit_scope="secondary_spatial_stress",
            )
            record.update({"spatial_fold": int(spatial_fold), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes))})
            results.append(record)
        metrics_path = fold_root / "spatial_fold_metrics.csv"
        requested = pd.DataFrame([a3_record, *results])
        if metrics_path.exists():
            existing = pd.read_csv(metrics_path)
            old_keys = set(zip(existing["candidate"].astype(str), existing["seed"].fillna(-1).astype(int)))
            new_keys = set(zip(requested["candidate"].astype(str), requested["seed"].fillna(-1).astype(int)))
            if old_keys != new_keys:
                raise RuntimeError(f"existing spatial-stress metrics have conflicting seed coverage: {metrics_path}")
        else:
            write_csv_atomic(metrics_path, requested)
        status = {
            "status": "COMPLETED", "spatial_fold": int(spatial_fold), "fold_id": int(100 + spatial_fold),
            "seed_ids": [int(seed) for seed in config["seeds"]], "selection_used": False, "a4s_refit": False,
            "primary_decision": decision["status"], "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)),
            "training_node_ids_sha256": sha256_json(train_nodes.tolist()), "prediction_node_ids_sha256": sha256_json(eval_nodes.tolist()),
            "input_sha256": dict(data.hashes), "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_vif_provenance"]["source_sha256"], "completed_utc": utc_now(),
        }
        status_path = fold_root / "fold_status.json"
        if status_path.exists():
            prior = json.loads(status_path.read_text(encoding="utf-8"))
            if prior.get("status") != "COMPLETED" or prior.get("input_sha256") != status["input_sha256"] or prior.get("training_node_ids_sha256") != status["training_node_ids_sha256"]:
                raise RuntimeError(f"existing spatial-stress fold status conflicts: {status_path}")
        else:
            write_json_atomic(status_path, status)
        return status


def support_audit(data: Any, fold: Any, coords_xy: np.ndarray, coords_pred: np.ndarray, training_node_ids: np.ndarray | None = None) -> dict[str, Any]:
    train_nodes = np.arange(len(coords_xy), dtype=np.int64) if training_node_ids is None else np.asarray(training_node_ids, dtype=np.int64)
    train_xy = coords_xy[train_nodes]
    eval_xy = coords_pred[:, 1:]
    xmin, ymin = train_xy.min(axis=0)
    xmax, ymax = train_xy.max(axis=0)
    inside = (eval_xy[:, 0] >= xmin) & (eval_xy[:, 0] <= xmax) & (eval_xy[:, 1] >= ymin) & (eval_xy[:, 1] <= ymax)
    times = coords_pred[:, 0].astype(np.int64)
    return {
        "training_node_count": int(len(train_xy)),
        "prediction_row_count": int(len(coords_pred)),
        "prediction_spatial_fraction_within_training_extent": float(np.mean(inside)),
        "training_xy_min": [float(xmin), float(ymin)],
        "training_xy_max": [float(xmax), float(ymax)],
        "prediction_week_min": int(times.min()),
        "prediction_week_max": int(times.max()),
        "last_training_week": int(np.max(fold.train_times)),
        "temporal_extrapolation_weeks": [int(times.min() - np.max(fold.train_times)), int(times.max() - np.max(fold.train_times))],
        "queen_adjacency_used_for_gp": False,
        "gp_coordinates_from_canonical_projected_node_xy": True,
        "future_or_same_week_outcomes_used_as_predictors": False,
    }


def compare_gate(
    args: argparse.Namespace,
    config: dict[str, Any],
    data: Any,
    fold_id: int,
    seed: int,
    fit_record: dict[str, Any],
    opt_arrays: dict[str, np.ndarray],
    a3_record: dict[str, Any],
    a3_arrays: dict[str, np.ndarray],
    covariance: dict[str, Any],
    fit_completion: dict[str, Any],
    comparison_source_sha256: dict[str, str],
) -> dict[str, Any]:
    emit_progress("FINAL_QUALIFICATION", "STARTED", fold=int(fold_id), seed=int(seed))
    original_root = args.original_a6_run_root
    original_metrics, original_arrays, original_provenance = get_original_a6_row(original_root, "A6-GPB-ST", fold_id, seed, data)
    for key in ("y", "week_index", "node_id"):
        if key not in original_arrays or key not in opt_arrays or not np.array_equal(original_arrays[key], opt_arrays[key]):
            raise RuntimeError(f"original A6 and A6-VIF fold rows do not align for {key}")
    spatial = A5.spatial_diagnostics(
        {"A3": a3_arrays, "A6-GPB-ST": original_arrays, VIF_CANDIDATE: opt_arrays},
        data, config, args.output_root,
    )
    temporal = A5.temporal_diagnostics({"A3": a3_arrays, "A6-GPB-ST": original_arrays, VIF_CANDIDATE: opt_arrays}, args.output_root)
    frontier = A5.frontier_diagnostics({"A3": a3_arrays, "A6-GPB-ST": original_arrays, VIF_CANDIDATE: opt_arrays}, data, args.output_root)
    leakage = A6.run_leakage_tests(config, data, args.output_root)
    native_warnings = native_gpboost_warning_lines(args.output_root)
    inducing_removals = [int(match.group(1)) for line in native_warnings if (match := re.search(r"(\d+) inducing points are removed", line))]
    inducing_points_effective_after_reported_removals = [
        max(0, int(config["gpboost"]["num_ind_points"]) - removed)
        for removed in inducing_removals
    ]
    shell_one = spatial.loc[spatial["residual"].eq("occurrence") & spatial["shell"].eq(1)].set_index("candidate")["moran_i"].to_dict()
    guard = config["guardrails"]
    gate = config["a6_vif"]["gate"]
    pr_a3_diff = float(fit_record["pr_auc"] - a3_record["pr_auc"])
    brier_a3_diff = float(fit_record["brier_skill"] - a3_record["brier_skill"])
    nll_a3_diff = float(fit_record["joint_hurdle_nll"] - a3_record["joint_hurdle_nll"])
    intercept_a3_worsening = abs(abs(float(fit_record["calibration_intercept"])) - abs(float(a3_record["calibration_intercept"])))
    slope_a3_worsening = abs(abs(float(fit_record["calibration_slope"])) - abs(float(a3_record["calibration_slope"])))
    pr_original_diff = float(fit_record["pr_auc"] - original_metrics["pr_auc"])
    brier_original_diff = float(fit_record["brier_skill"] - original_metrics["brier_skill"])
    nll_original_diff = float(fit_record["joint_hurdle_nll"] - original_metrics["joint_hurdle_nll"])
    original_runtime = float(original_provenance["original_runtime_seconds_total"])
    opt_runtime = float(fit_record["runtime_seconds_total"])
    speedup = original_runtime / opt_runtime if math.isfinite(original_runtime) and opt_runtime > 0 else float("nan")
    moran_reduction = float(shell_one["A3"] - shell_one[VIF_CANDIDATE])
    moran_worsening_vs_original = float(shell_one[VIF_CANDIDATE] - shell_one["A6-GPB-ST"])
    temporal_rows = temporal.loc[(temporal["candidate"].astype(str) == VIF_CANDIDATE) & (temporal["residual"].astype(str) == "occurrence")]
    temporal_correlations = temporal.loc[temporal["residual"].astype(str).eq("occurrence")].to_dict(orient="records")
    frontier_rows = frontier.loc[frontier["candidate"].astype(str).isin(["A3", "A6-GPB-ST", VIF_CANDIDATE])].to_dict(orient="records")
    stage_a_valid = bool(
        fit_record["inner_covariance_diagnostics"]["converged"]
        and fit_record["outer_covariance_diagnostics"]["converged"]
        and fit_record["inner_covariance_diagnostics"]["non_degenerate"]
        and fit_record["outer_covariance_diagnostics"]["non_degenerate"]
    )
    stage_b_covariance_fixed = bool(
        fit_record["covariance_fixed_verified"]
        and fit_record["inner_covariance_fixed_verified"]
        and all(abs(value) <= 1e-10 for value in fit_record["stage_b_covariance_parameter_changes"].values())
    )
    scientific_checks = {
        "stage_a_covariance_converged_and_valid": stage_a_valid,
        "stage_b_covariance_fixed": stage_b_covariance_fixed,
        "prediction_repeatability": bool(fit_record["prediction_repeatability_max_abs_difference"] <= config["prediction_repeatability"]["absolute_tolerance"]),
        "finite_bounded_predictions": bool(np.isfinite(opt_arrays["p"]).all() and np.all((opt_arrays["p"] >= 0) & (opt_arrays["p"] <= 1))),
        "occurrence_temporal_residual_diagnostics_available": bool(len(temporal_rows) == 3 and temporal_rows["correlation"].notna().all() and (temporal_rows["valid_same_cell_pairs"] > 0).all()),
        "frontier_region_metrics_available": bool(any(row.get("candidate") == VIF_CANDIDATE for row in frontier_rows)),
        "a3_offset_and_34_predictor_contract": bool(fit_record["training_offset"] == "frozen_A3_logit_offset_init_score" and fit_record["prediction_offset"] == "frozen_A3_logit_offset_pred" and fit_record["observations_boosting"] > 0),
        "outer_validation_not_used_for_fit_or_round_selection": bool(not fit_record["outer_validation_labels_supplied_to_prediction"] and not fit_record["outer_validation_used_for_round_selection"]),
        "outer_fold_leakage_contract": bool(leakage.get("status") == "PASSED"),
        "spatial_temporal_prediction_support": bool(fit_record["spatial_support_audit"]["prediction_spatial_fraction_within_training_extent"] == 1.0 and min(fit_record["spatial_support_audit"]["temporal_extrapolation_weeks"]) >= 1),
        "canonical_coordinate_order": bool(fit_record["coordinate_order"] == ["time_week_offset", "x_km", "y_km"] and not fit_record["spatial_support_audit"]["queen_adjacency_used_for_gp"]),
        "inducing_points_retained_at_200": bool(not inducing_removals),
        "pr_auc_guardrail_vs_a3": bool(pr_a3_diff >= -float(gate["maximum_pr_auc_degradation_vs_a3"]))
        and bool(pr_original_diff >= -float(gate["maximum_pr_auc_degradation_vs_a3"])),
        "brier_skill_guardrail": bool(brier_a3_diff >= -float(gate["maximum_brier_skill_degradation_vs_a3"]))
        and bool(brier_original_diff >= -float(gate["maximum_brier_skill_degradation_vs_a3"])),
        "joint_hurdle_nll_guardrail": bool(nll_a3_diff <= float(gate["maximum_joint_hurdle_nll_worsening_vs_a3"]))
        and bool(nll_original_diff <= float(gate["maximum_joint_hurdle_nll_worsening_vs_a3"])),
        "calibration_guardrails_vs_a3": bool(intercept_a3_worsening <= float(gate["maximum_calibration_intercept_worsening_vs_a3"]) and slope_a3_worsening <= float(gate["maximum_calibration_slope_worsening_vs_a3"])),
        "shell1_occurrence_moran_reduction_vs_a3": bool(moran_reduction >= float(gate["minimum_shell1_occurrence_moran_reduction_vs_a3"])),
        "shell1_occurrence_moran_not_degraded_vs_original_a6": bool(moran_worsening_vs_original <= float(gate["maximum_shell1_occurrence_moran_worsening_vs_original_a6"])),
    }
    checks = {
        **scientific_checks,
        "minimum_twofold_runtime_reduction": bool(math.isfinite(speedup) and speedup >= float(gate["minimum_speedup_vs_original_a6"])),
    }
    limitation_checks = {
        name: passed for name, passed in checks.items()
        if name not in {"minimum_twofold_runtime_reduction", "inducing_points_retained_at_200"}
    }
    scientifically_acceptable = all(limitation_checks.values())
    if all(checks.values()):
        decision = "A6_VIF_GATE_SUPPORTED"
    elif scientifically_acceptable and math.isfinite(speedup):
        decision = "A6_VIF_GATE_SUPPORTED_WITH_LIMITATIONS"
    else:
        decision = "A6_VIF_GATE_NOT_SUPPORTED"
    payload = {
        "status": decision,
        "fold": int(fold_id),
        "seed": int(seed),
        "created_utc": utc_now(),
        "checks": checks,
        "comparison": {
            "predictive_metrics_a3": prediction_metrics_from_record(a3_record),
            "predictive_metrics_original_a6": prediction_metrics_from_record(original_metrics),
            "predictive_metrics_a6_vif": prediction_metrics_from_record(fit_record),
            "differences_vs_a3": {"pr_auc": pr_a3_diff, "brier_skill": brier_a3_diff, "joint_hurdle_nll": nll_a3_diff, "calibration_intercept_worsening": intercept_a3_worsening, "calibration_slope_worsening": slope_a3_worsening},
            "differences_vs_original_a6": {"pr_auc": pr_original_diff, "brier_skill": brier_original_diff, "joint_hurdle_nll": nll_original_diff},
            "spatial_shell1_occurrence_moran": {name: float(shell_one[name]) for name in ("A3", "A6-GPB-ST", VIF_CANDIDATE)},
            "shell1_moran_reduction_vs_a3": moran_reduction,
            "shell1_moran_worsening_vs_original_a6": moran_worsening_vs_original,
            "covariance_parameters": covariance["covariance_parameters"],
            "original_a6_runtime_seconds": original_runtime,
            "a6_vif_gate_runtime_seconds": opt_runtime,
            "speedup": speedup,
            "runtime_components_seconds": {
                "stage_a_inner_covariance_total": float(fit_record["stage_a_inner_runtime_seconds"]),
                "stage_a_outer_covariance_total": float(fit_record["stage_a_outer_runtime_seconds"]),
                "stage_b_inner_gp_initialization": float(fit_record["stage_b_inner_gp_initialization_seconds"]),
                "stage_b_inner_dataset_setup": float(fit_record["stage_b_inner_dataset_setup_seconds"]),
                "stage_b_inner_boosting": float(fit_record["stage_b_inner_round_selection_seconds"]),
                "stage_b_final_gp_initialization": float(fit_record["stage_b_final_gp_initialization_seconds"]),
                "stage_b_final_dataset_setup": float(fit_record["stage_b_final_dataset_setup_seconds"]),
                "stage_b_final_boosting": float(fit_record["stage_b_full_training_seconds"]),
                "prediction_setup": float(fit_record["prediction_setup_seconds"]),
                "prediction_primary": float(fit_record["prediction_primary_seconds"]),
                "prediction_repeatability": float(fit_record["prediction_repeatability_seconds"]),
                "serialization": float(fit_record["serialization_seconds"]),
            },
            "temporal_occurrence_residual_correlations": temporal_correlations,
            "frontier_metrics": frontier_rows,
            "covariance_diagnostics_inner": fit_record["inner_covariance_diagnostics"],
            "covariance_diagnostics_outer": fit_record["outer_covariance_diagnostics"],
            "latent_mode_diagnostics": {
                "inner_mode_finding_steps": fit_record.get("latent_mode_finding_steps_inner"),
                "final_mode_finding_steps": fit_record.get("latent_mode_finding_steps_final"),
                "convergence_boolean_available": fit_record.get("latent_mode_convergence_boolean_available"),
                "solver_status": fit_record.get("latent_mode_solver_status"),
            },
            "gpboost_native_warnings": native_warnings,
            "requested_inducing_points": int(config["gpboost"]["num_ind_points"]),
            "reported_inducing_point_removals": inducing_removals,
            "implied_inducing_points_after_each_reported_removal": inducing_points_effective_after_reported_removals,
            "process_cpu_hours": float(fit_record["cpu_seconds_total"] / 3600.0),
            "process_average_cpu_utilization": float(fit_record["cpu_utilization_fraction"]),
            "peak_rss_bytes": float(fit_record["peak_rss_bytes_process"]),
            "original_a6_artifacts": original_provenance,
            "frontier_rows": int(len(frontier)),
            "temporal_residual_rows": int(len(temporal)),
        },
        "limitations": [
            "The qualification uses one outer fold and one seed.",
            "Stage A covariance estimates use a deterministic 2,048-site spatially stratified sample spanning only training weeks.",
            "GPBoost exposes latent-mode iteration counts but no Python-level convergence boolean; optimizer convergence is reported as an iteration-limit proxy.",
            "A supported gate does not automatically launch any larger evaluation.",
        ],
        "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
        "comparison_execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
        "model_execution_sha": fit_completion.get("execution_sha", "unknown"),
        "model_execution_branch": fit_completion.get("execution_branch", "unknown"),
        "model_source_sha256": fit_completion.get("source_sha256", {}),
        "comparison_source_sha256": comparison_source_sha256,
        "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"],
    }
    if inducing_removals:
        payload["limitations"].append(
            f"GPBoost reported removal of inducing points during initialization: counts={inducing_removals}; implied remaining counts={inducing_points_effective_after_reported_removals}. No alternative inducing-point method was substituted."
        )
    if not checks["minimum_twofold_runtime_reduction"]:
        payload["limitations"].append("The completed model unit did not achieve the mandatory twofold speedup; no larger run is authorized.")
    write_csv_atomic(args.output_root / "results/a6_vif_gate_metrics.csv", pd.DataFrame([
        {"candidate": "A3", "fold": fold_id, "seed": seed, **prediction_metrics_from_record(a3_record)},
        {"candidate": "A6-GPB-ST", "fold": fold_id, "seed": seed, **prediction_metrics_from_record(original_metrics)},
        {"candidate": VIF_CANDIDATE, "fold": fold_id, "seed": seed, **prediction_metrics_from_record(fit_record)},
    ]))
    report_path = args.durable_summary_root / f"a6_vif_gate_report_{args.output_root.name}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = [
        "# A6-VIF bounded qualification gate", "",
        f"**Gate decision:** `{decision}`", "",
        f"Fold {fold_id}, seed {seed}; original A6 comparator: fold {fold_id}, seed {seed}.",
        f"Measured speedup: **{speedup:.2f}×** ({original_runtime / 3600:.2f} original hours / {opt_runtime / 3600:.2f} A6-VIF hours).",
        f"Training data: {fit_record['observations_boosting']:,} full Stage B rows; covariance subsets {covariance['observations_used']:,} outer and {fit_record['observations_covariance_inner']:,} inner rows.",
        "", "## Gate checks", "", "| Check | Result |", "|---|---:|",
    ]
    report.extend(f"| {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |" for name, passed in checks.items())
    report.extend([
        "", "## Predictive and spatial comparison", "",
        "| Metric | Frozen A3 | Original A6 | A6-VIF |", "|---|---:|---:|---:|",
    ])
    for metric in ("pr_auc", "brier_skill", "calibration_intercept", "calibration_slope", "joint_hurdle_nll"):
        report.append(f"| {metric} | {float(a3_record[metric]):.6g} | {float(original_metrics[metric]):.6g} | {float(fit_record[metric]):.6g} |")
    report.extend([
        "", f"Shell 1 occurrence Moran's I: A3 {shell_one['A3']:.6g}; original A6 {shell_one['A6-GPB-ST']:.6g}; A6-VIF {shell_one[VIF_CANDIDATE]:.6g}.",
        "", "## Runtime components", "", "| Component | Seconds |", "|---|---:|",
    ])
    report.extend(f"| {name.replace('_', ' ')} | {seconds:.2f} |" for name, seconds in payload["comparison"]["runtime_components_seconds"].items())
    report.extend(["", "## Temporal occurrence residual correlation", "", "| Candidate | Lag weeks | Correlation | Same-cell pairs |", "|---|---:|---:|---:|"])
    report.extend(f"| {row['candidate']} | {row['lag_weeks']} | {row['correlation']} | {row['valid_same_cell_pairs']} |" for row in temporal_correlations)
    report.extend(["", "## Frontier-region performance", "", "| Candidate | Definition | Region | Node-weeks | PR AUC | Brier skill | Log loss |", "|---|---|---|---:|---:|---:|---:|"])
    for row in frontier_rows:
        report.append(f"| {row.get('candidate')} | {row.get('definition')} | {row.get('frontier_class')} | {row.get('n_node_weeks')} | {row.get('pr_auc', math.nan)} | {row.get('brier_skill', math.nan)} | {row.get('joint_hurdle_nll', math.nan)} |")
    report.extend(["", "## Numerical diagnostics", "", f"Stage A inner covariance: `{fit_record['inner_covariance_diagnostics']}`", f"Stage A outer covariance: `{fit_record['outer_covariance_diagnostics']}`", f"Latent-mode finding steps: inner `{fit_record.get('latent_mode_finding_steps_inner')}`, final `{fit_record.get('latent_mode_finding_steps_final')}`. The installed Python API does not expose a latent-mode convergence boolean.", ""])
    report.extend(["", "## GPBoost native warnings", ""])
    if native_warnings:
        report.extend(f"- `{line}`" for line in native_warnings)
    else:
        report.append("No GPBoost native warning/error lines were captured in the runner logs.")
    if inducing_removals:
        report.append(f"Requested inducing points: {config['gpboost']['num_ind_points']}; GPBoost reported removals {inducing_removals}, implying counts {inducing_points_effective_after_reported_removals} for the corresponding initializations. This is recorded as a limitation; no alternate selection method was substituted.")
    report.extend([
        "", "## Interpretation", "",
        "This gate uses the single authorized temporal fold and seed. It used the frozen A3 occurrence offset, the unchanged 34 predictors, joint Matérn space-time covariance with `full_scale_vecchia`, 200 requested kmeans++ inducing points, eight training neighbors, time ordering, iterative matrix inversion, and the explicit 40-neighbor prediction setting. This report does not authorize any additional run.",
        "",
    ])
    report_text = "\n".join(report)
    write_text_atomic(report_path, report_text)
    output_report = args.output_root / "results/a6_vif_gate_report.md"
    write_text_atomic(output_report, report_text)
    write_json_atomic(args.output_root / "results/a6_vif_gate_decision.json", payload)
    emit_progress("FINAL_QUALIFICATION", "COMPLETED", gate_status=decision, speedup=float(speedup), checks=checks)
    return payload


def run_gate(args: argparse.Namespace, config: dict[str, Any], opt: dict[str, Any], data: Any, gpb: Any, fold_id: int, seed: int) -> dict[str, Any]:
    existing_decision_path = args.output_root / "results/a6_vif_gate_decision.json"
    if existing_decision_path.exists():
        raise A6VIFBlocked("this A6-VIF qualification is one-shot; an existing decision blocks retries")
    existing_covariance = args.output_root / "folds" / f"fold_{fold_id:02d}" / "covariance"
    existing_stage_b = args.output_root / "folds" / f"fold_{fold_id:02d}" / "seeds"
    if (existing_covariance.exists() and any(existing_covariance.rglob("attempt_*"))) or (existing_stage_b.exists() and any(existing_stage_b.rglob("attempt_*"))):
        raise A6VIFBlocked("existing covariance or Stage B attempts block rerunning this one-shot gate")
    emit_progress("FOLD_AND_OFFSET_VERIFICATION", "GATE_ENTRY", fold=int(fold_id), seed=int(seed))
    try:
        result = run_fold(args, config, opt, data, gpb, fold_id, [seed], "gate")
        fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
        seed_complete = find_completed_seed(fold_root / "seeds" / f"seed_{seed}", seed, config, data)
        if seed_complete is None:
            raise RuntimeError("gate fit completion marker is missing")
        opt_arrays = result["a3_arrays"]
        with np.load(seed_complete["artifact_paths"]["prediction"], allow_pickle=False) as archive:
            opt_arrays = {key: np.asarray(archive[key]) for key in archive.files}
        a3_record = result["a3_record"]
        a3_arrays = result["a3_arrays"]
        outer_cov = result["outer_covariance"]
        gate = compare_gate(args, config, data, fold_id, seed, seed_complete["record"], opt_arrays, a3_record, a3_arrays, outer_cov, seed_complete, source_checksums(args.config))
        write_json_atomic(args.output_root / "results/run_status.json", {"status": gate["status"], "completed_utc": utc_now(), "fold": fold_id, "seed": seed})
        return gate
    except Exception as exc:
        if existing_decision_path.exists():
            existing = json.loads(existing_decision_path.read_text(encoding="utf-8"))
            if existing.get("status") in {"A6_VIF_GATE_SUPPORTED", "A6_VIF_GATE_SUPPORTED_WITH_LIMITATIONS"}:
                return existing
        decision = {
            "status": "A6_VIF_GATE_NOT_SUPPORTED",
            "fold": int(fold_id),
            "seed": int(seed),
            "reason": str(exc),
            "traceback": traceback.format_exc(),
            "created_utc": utc_now(),
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"],
        }
        write_json_atomic(args.output_root / "results/a6_vif_gate_decision.json", decision)
        report_path = args.durable_summary_root / f"a6_vif_gate_report_{args.output_root.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(report_path,
            "# A6-VIF bounded qualification gate\n\n"
            "**Gate decision:** `A6_VIF_GATE_NOT_SUPPORTED`\n\n"
            f"Fold {fold_id}, seed {seed}.\n\n"
            f"Observed blocker: {exc}\n\n"
            "The gate stopped at this failure. No additional optimization experiment or full temporal evaluation was launched.\n"
        )
        write_json_atomic(args.output_root / "results/run_status.json", {"status": decision["status"], "reason": str(exc), "completed_utc": utc_now()})
        return decision


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gate"], required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--a3-reference", type=Path, required=True)
    parser.add_argument("--a3-frozen-output", type=Path, required=True)
    parser.add_argument("--original-a6-run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--durable-summary-root", type=Path, default=REPOSITORY_ROOT / "analysis/a6_vif_bounded_gate/results")
    parser.add_argument("--fold", type=int)
    parser.add_argument("--seeds", type=int, nargs="+")
    return parser


def main() -> int:
    args = create_parser().parse_args()
    if args.fold != 3 or args.seeds != [31415]:
        raise A6VIFBlocked("this one-shot qualification runner is restricted to temporal fold 3 / seed 31415")
    config, opt = read_config(args.config)
    args.output_root = resolve_output_root(args.output_root)
    args.original_a6_run_root = args.original_a6_run_root.expanduser().resolve()
    args.durable_summary_root = args.durable_summary_root.expanduser().resolve() / args.output_root.name
    resources = opt["execution"]["gate_resources"]
    if resources != {"automatic_retries": 0, "internal_deadline": "05:20:00", "walltime": "06:00:00", "cpu_hours": 96, "hard_stop": "05:35:00", "cpus": 16, "memory": "64G"}:
        raise A6VIFBlocked(f"bounded compute-budget configuration changed: {resources}")
    if int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 16:
        raise A6VIFBlocked(f"Slurm allocation must be exactly 16 CPUs, got {os.environ.get('SLURM_CPUS_PER_TASK')}")
    comparison_source_sha256 = source_checksums(args.config)
    source_sha256 = comparison_source_sha256
    config["a6_vif_provenance"]["source_sha256"] = source_sha256
    for name in ("results", "provenance", "folds", "logs"):
        (args.output_root / name).mkdir(parents=True, exist_ok=True)
    one_shot_marker = args.output_root / "provenance/one_shot_execution_started.json"
    if one_shot_marker.exists():
        raise A6VIFBlocked(f"automatic retries and reruns are disabled; execution marker already exists: {one_shot_marker}")
    write_json_atomic(one_shot_marker, {"status": "STARTED", "fold": 3, "seed": 31415, "started_utc": utc_now(), "slurm_job_id": os.environ.get("SLURM_JOB_ID")})
    initialize_progress(args.output_root, time_limit_seconds(resources["internal_deadline"]))
    install_durable_warning_logger()
    signal.signal(signal.SIGUSR1, scheduler_signal_handler)
    signal.signal(signal.SIGTERM, scheduler_signal_handler)
    if thread_count() != 16:
        raise A6VIFBlocked("effective GPBoost thread count does not match the 16-CPU Slurm allocation")
    emit_progress("API_AUDIT", "STARTED")
    gpb = load_gpboost()
    api = audit_gpboost_api(gpb, args.output_root)
    emit_progress("API_AUDIT", "COMPLETED", gpboost_version=gpb.__version__, requested_configuration={key: config["gpboost"][key] for key in ("likelihood", "gp_approx", "num_ind_points", "ind_points_selection", "num_neighbors", "num_neighbors_pred", "vecchia_ordering_spatiotemporal", "matrix_inversion_method", "cov_fct_shape")})
    emit_progress("DATA_PREPARATION", "STARTED")
    data_started = time.perf_counter()
    data = load_data(args)
    emit_progress("DATA_PREPARATION", "COMPLETED", elapsed_seconds=float(time.perf_counter() - data_started), input_sha256=dict(data.hashes), node_count=int(A6.NODE_COUNT), development_week_count=int(A6.DEVELOPMENT_WEEKS), predictor_count=34)
    environment = {
        "status": "PASSED",
        "gpboost_version": gpb.__version__,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "slurm_cpus_per_task": int(os.environ.get("SLURM_CPUS_PER_TASK", thread_count())),
        "input_sha256": dict(data.hashes),
        "config_provenance": config["a6_vif_provenance"],
        "source_sha256": source_sha256,
        "api_audit": api,
        "effective_gpboost_settings": {
            "likelihood": config["gpboost"]["likelihood"],
            "cov_function": config["gpboost"]["spatiotemporal_cov_function"],
            "cov_fct_shape": config["gpboost"]["cov_fct_shape"],
            "gp_approx": config["gpboost"]["gp_approx"],
            "num_ind_points": config["gpboost"]["num_ind_points"],
            "ind_points_selection": config["gpboost"]["ind_points_selection"],
            "num_neighbors": config["gpboost"]["num_neighbors"],
            "num_neighbors_pred": config["gpboost"]["num_neighbors_pred"],
            "vecchia_ordering": config["gpboost"]["vecchia_ordering_spatiotemporal"],
            "matrix_inversion_method": config["gpboost"]["matrix_inversion_method"],
            "num_parallel_threads": 16,
            "seed": 31415,
            "coordinate_order": ["time_week_offset", "x_km", "y_km"],
        },
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "created_utc": utc_now(),
    }
    environment_path = args.output_root / "provenance/environment_manifest.json"
    if not environment_path.exists():
        write_json_atomic(environment_path, environment)
    else:
        prior_environment = json.loads(environment_path.read_text(encoding="utf-8"))
        for key in ("gpboost_version", "input_sha256", "config_provenance", "api_audit"):
            if prior_environment.get(key) != environment.get(key):
                raise RuntimeError(f"existing environment provenance changed in {key}: {environment_path}")
        if prior_environment.get("status") != "PASSED":
            raise RuntimeError(f"existing environment provenance is not PASSED: {environment_path}")
    if args.mode == "gate":
        if args.fold is None or args.seeds is None or len(args.seeds) != 1:
            raise ValueError("gate mode requires --fold and exactly one --seeds value")
        result = run_gate(args, config, opt, data, gpb, args.fold, args.seeds[0])
        snapshot = runtime_snapshot()
        wall = float(time.perf_counter() - _EXECUTION_STARTED)
        result["total_execution_runtime_seconds"] = wall
        result["process_cpu_seconds_total"] = max(0.0, snapshot["cpu_seconds"] - _EXECUTION_CPU_STARTED)
        result["process_cpu_hours_total"] = result["process_cpu_seconds_total"] / 3600.0
        result["process_average_cpu_utilization"] = result["process_cpu_seconds_total"] / max(wall * 16, 1e-9)
        result["peak_rss_bytes_process"] = snapshot["peak_rss_bytes"]
        result["slurm_job_id"] = os.environ.get("SLURM_JOB_ID")
        result["allocation"] = {"cpus": 16, "memory": "64G", "walltime_seconds": 21600, "cpu_hour_budget": 96}
        result["execution_budget_status"] = "WITHIN_BUDGET" if wall <= 21600 and result["process_cpu_seconds_total"] <= 96 * 3600 else "BUDGET_EXCEEDED"
        if result["execution_budget_status"] != "WITHIN_BUDGET":
            result["status"] = "A6_VIF_GATE_NOT_SUPPORTED"
            result.setdefault("limitations", []).append("The completed process exceeded the six-hour walltime or 96 CPU-hour budget; the bounded qualification is not supported.")
            result.setdefault("checks", {})["execution_budget_within_limits"] = False
        else:
            result.setdefault("checks", {})["execution_budget_within_limits"] = True
        write_json_atomic(args.output_root / "results/a6_vif_gate_decision.json", result)
        write_json_atomic(args.output_root / "results/run_status.json", {"status": result["status"], "completed_utc": utc_now(), "fold": args.fold, "seed": args.seeds[0], "total_execution_runtime_seconds": wall})
        write_json_atomic(one_shot_marker, {"status": "COMPLETED", "fold": 3, "seed": 31415, "completed_utc": utc_now(), "gate_status": result["status"], "slurm_job_id": os.environ.get("SLURM_JOB_ID")})
        output_report = args.output_root / "results/a6_vif_gate_report.md"
        durable_report = args.durable_summary_root / f"a6_vif_gate_report_{args.output_root.name}.md"
        if durable_report.exists():
            report_text = durable_report.read_text(encoding="utf-8")
        elif output_report.exists():
            report_text = output_report.read_text(encoding="utf-8")
        else:
            report_text = "# A6-VIF bounded qualification gate\n\nNo complete comparison report was produced.\n"
        decision_line = f"**Gate decision:** `{result['status']}`"
        if re.search(r"(?m)^\*\*Gate decision:\*\* `[^`]+`$", report_text):
            report_text = re.sub(r"(?m)^\*\*Gate decision:\*\* `[^`]+`$", decision_line, report_text, count=1)
        else:
            report_text = f"{decision_line}\n\n{report_text}"
        report_text += (
            "\n## Complete execution accounting\n\n"
            f"- Total execution wall time: {wall:.2f} s ({wall / 3600:.3f} h).\n"
            f"- Python-process CPU time: {result['process_cpu_seconds_total']:.2f} s ({result['process_cpu_hours_total']:.3f} CPU-h).\n"
            f"- Process average CPU utilization over 16 allocated CPUs: {result['process_average_cpu_utilization']:.4f}.\n"
            f"- Process peak RSS: {result['peak_rss_bytes_process']:.0f} bytes.\n"
            f"- Slurm job ID: {result['slurm_job_id']}.\n"
            f"- Budget status: `{result['execution_budget_status']}`.\n"
        )
        write_text_atomic(output_report, report_text)
        durable_report.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(durable_report, report_text)
        emit_progress("FINAL_QUALIFICATION", "COMPLETED", gate_status=result["status"], total_execution_runtime_seconds=wall, process_cpu_hours=result["process_cpu_hours_total"])
        write_json_atomic(args.output_root / "provenance/checksum_manifest.json", {
            "status": "COMPLETED", "config_sha256": config["a6_vif_provenance"]["opt_config_sha256"], "source_sha256": source_sha256,
            "input_sha256": dict(data.hashes), "files": [
                {"path": str(path.relative_to(args.output_root)), "size_bytes": int(path.stat().st_size), "sha256": sha256_file(path)}
                for path in sorted(args.output_root.rglob("*")) if path.is_file() and path.name != "checksum_manifest.json"
            ], "created_utc": utc_now(),
        })
        print(json.dumps({"status": result["status"], "fold": args.fold, "seed": args.seeds[0], "total_execution_runtime_seconds": wall}, indent=2), flush=True)
        return 0
    raise AssertionError(f"unsupported mode {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())

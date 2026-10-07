#!/usr/bin/env python3
"""Fail-safe Structured A3 production submission and stage runner.

The submission path only coordinates validated Atlas-side commands. It does
not contain a second model implementation. Scientific values are read from
the immutable frozen A3 manifest and checked before any stage is submitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGES = ("P0", "P1", "P2", "P3", "P4", "P5")
MODES = ("production_fullfit", "prospective_evaluation")
MODEL_NAME = "STRUCTURED_A3"
PREDICTOR_COUNT = 34
THETA = 0.7018903965556372
PENALTY = 0.01
OBJECTIVE = "exact_joint_hurdle_nll"
NODE_COUNT = 10037
HISTORY_FEATURES = (
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
)


class PipelineError(RuntimeError):
    """A fail-safe validation or execution error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _strip_comment(line: str) -> str:
    quoted = False
    quote = ""
    for i, char in enumerate(line):
        if char in "'\"":
            if not quoted:
                quoted, quote = True, char
            elif quote == char:
                quoted = False
        elif char == "#" and not quoted and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if (value.startswith("\"") and value.endswith("\"")) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1].replace("\\\"", "\"")
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
    try:
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", value):
            return float(value)
    except ValueError:
        pass
    return value


def _simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small mapping-oriented YAML subset used by deployment files.

    PyYAML is preferred on Atlas. This fallback keeps the launcher usable in a
    minimal environment and intentionally rejects complex YAML constructs.
    """
    rows = []
    for raw in text.splitlines():
        cleaned = _strip_comment(raw)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        rows.append((indent, cleaned.strip()))

    def parse(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(rows) or rows[index][0] < indent:
            return {}, index
        is_list = rows[index][1].startswith("- ")
        result: Any = [] if is_list else {}
        while index < len(rows) and rows[index][0] == indent:
            _, item = rows[index]
            if is_list:
                if not item.startswith("- "):
                    raise PipelineError("unsupported YAML list structure")
                result.append(_scalar(item[2:]))
                index += 1
                continue
            if ":" not in item:
                raise PipelineError(f"invalid YAML mapping line: {item}")
            key, value = item.split(":", 1)
            key = key.strip().strip("\"'")
            value = value.strip()
            index += 1
            if value:
                result[key] = _scalar(value)
            elif index < len(rows) and rows[index][0] > indent:
                result[key], index = parse(index, rows[index][0])
            else:
                result[key] = None
        return result, index

    parsed, position = parse(0, rows[0][0] if rows else 0)
    if position != len(rows) or not isinstance(parsed, dict):
        raise PipelineError("unsupported YAML structure")
    return parsed


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text)
    except ImportError:
        parsed = _simple_yaml(text)
    if not isinstance(parsed, dict):
        raise PipelineError(f"configuration must be a mapping: {path}")
    return parsed


def resolve_path(value: str | Path, *, base: Path, repo_root: Path | None = None) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    if repo_root is not None and (repo_root / path).exists():
        return (repo_root / path).resolve()
    return (base / path).resolve()


def load_config(path: Path) -> tuple[dict[str, Any], Path, Path]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise PipelineError(f"configuration does not exist: {path}")
    config = load_yaml(path)
    configured_root = config.get("repository_root", str(REPO_ROOT))
    repo_root = resolve_path(configured_root, base=path.parent)
    scientific_value = config.get("scientific_config", str(REPO_ROOT / "config" / "structured_a3.yaml"))
    scientific_path = resolve_path(scientific_value, base=path.parent, repo_root=repo_root)
    if not scientific_path.exists():
        raise PipelineError(f"scientific configuration does not exist: {scientific_path}")
    return config, repo_root, scientific_path


def validate_frozen_manifest(scientific_path: Path) -> dict[str, Any]:
    scientific = load_yaml(scientific_path)
    section = scientific.get("scientific_specification")
    if not isinstance(section, dict):
        raise PipelineError("STOP: scientific_specification mapping is missing")
    manifest_value = section.get("manifest")
    if not manifest_value:
        raise PipelineError("STOP: frozen manifest path is missing")
    manifest_path = resolve_path(manifest_value, base=scientific_path.parent, repo_root=REPO_ROOT)
    if not manifest_path.exists():
        raise PipelineError(f"STOP: frozen manifest is unavailable: {manifest_path}")
    actual_sha = sha256_file(manifest_path)
    expected_sha = str(section.get("manifest_sha256", ""))
    if expected_sha and actual_sha != expected_sha:
        raise PipelineError(f"STOP: frozen manifest checksum mismatch: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = manifest.get("model", {})
    domain = manifest.get("domain", {})
    preprocessing = manifest.get("preprocessing", {})
    history = manifest.get("history_features", {})
    if manifest.get("manifest_status") != "FROZEN_BEFORE_EVALUATION_OUTCOMES":
        raise PipelineError("STOP: manifest is not frozen before evaluation outcomes")
    if model.get("id") != MODEL_NAME:
        raise PipelineError(f"STOP: model name mismatch: {model.get('id')}")
    if int(model.get("predictor_count", -1)) != PREDICTOR_COUNT:
        raise PipelineError("STOP: Structured A3 predictor count is not 34")
    if len(model.get("predictor_order", [])) != PREDICTOR_COUNT:
        raise PipelineError("STOP: Structured A3 predictor order is incomplete")
    if float(model.get("theta", float("nan"))) != THETA or not model.get("theta_fixed", False):
        raise PipelineError("STOP: Structured A3 theta is not the frozen exact value")
    if float(model.get("penalty", float("nan"))) != PENALTY:
        raise PipelineError("STOP: Structured A3 penalty differs from the frozen value")
    if model.get("objective") != OBJECTIVE:
        raise PipelineError("STOP: Structured A3 objective differs from the frozen value")
    if int(domain.get("node_count", -1)) != NODE_COUNT:
        raise PipelineError("STOP: canonical domain node count is not 10,037")
    if model.get("model_changes_after_freeze_allowed") is not False:
        raise PipelineError("STOP: model changes after freeze are not disabled")
    if preprocessing.get("evaluation_fit_forbidden") is not True:
        raise PipelineError("STOP: evaluation-period preprocessing is not forbidden")
    if history.get("future_or_same_week_observations_forbidden") is not True:
        raise PipelineError("STOP: same-week/future history leakage is not forbidden")
    if len(history.get("features", [])) != len(HISTORY_FEATURES) or set(history.get("features", [])) != set(HISTORY_FEATURES):
        raise PipelineError("STOP: causal history feature contract differs")
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": actual_sha,
        "predictor_manifest_sha256": sha256_file(REPO_ROOT / "docs" / "current" / "predictors.csv"),
        "model_name": model["id"],
        "predictor_count": model["predictor_count"],
        "theta": model["theta"],
        "penalty": model["penalty"],
        "objective": model["objective"],
        "node_count": domain["node_count"],
    }


def _nested(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def validate_config(config: dict[str, Any], mode: str, *, dry_run: bool, scientific: dict[str, Any]) -> list[str]:
    if mode not in MODES:
        raise PipelineError(f"unsupported mode: {mode}")
    errors: list[str] = []
    for key in ("repository_root", "scientific_config", "output_root", "logs_root", "scratch_root"):
        if not config.get(key):
            errors.append(f"missing configuration field: {key}")
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append("inputs must be a mapping")
    for key in ("observation_path", "environmental_root", "static_predictor_root", "history_feature_path"):
        if not inputs.get(key):
            errors.append(f"missing configuration field: inputs.{key}")
    if mode == "prospective_evaluation" and not inputs.get("deployed_model_manifest"):
        errors.append("prospective_evaluation requires inputs.deployed_model_manifest")
    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        errors.append("commands must be a mapping")
        commands = {}
    for stage in ("P0", "P1", "P2", "P4", "P5"):
        if not isinstance(commands.get(stage), str) or not commands.get(stage).strip():
            errors.append(f"missing commands.{stage}")
    mode_commands = commands.get(mode, {})
    p3 = mode_commands.get("P3") if isinstance(mode_commands, dict) else None
    if not isinstance(p3, str) or not p3.strip():
        errors.append(f"missing commands.{mode}.P3")
    if mode == "prospective_evaluation" and isinstance(p3, str):
        if "--no-refit" not in p3 and "no_refit" not in p3:
            errors.append("prospective P3 command must declare --no-refit")
        refit_scan = p3.replace("--no-refit", "").replace("no_refit", "")
        if re.search(r"\b(?:refit|retrain|train_model|fit_model)\b", refit_scan, flags=re.IGNORECASE):
            errors.append("prospective P3 command appears to refit or retrain")
    slurm = config.get("slurm", {})
    if not isinstance(slurm, dict):
        errors.append("slurm must be a mapping")
    elif not dry_run:
        for key in ("account", "partition"):
            if slurm.get(key) in (None, "", "CHANGE_ME"):
                errors.append(f"Atlas SLURM field is unresolved: slurm.{key}")
    if mode == "prospective_evaluation" and not dry_run:
        deployed = Path(str(inputs.get("deployed_model_manifest")))
        if not deployed.exists():
            errors.append(f"deployed model manifest does not exist: {deployed}")
    if errors:
        raise PipelineError("configuration validation failed:\n- " + "\n- ".join(errors))
    return []


def command_for(config: dict[str, Any], mode: str, stage: str) -> str:
    commands = config.get("commands", {})
    if stage == "P3":
        return str(commands[mode][stage])
    return str(commands[stage])


def render_command(command: str, context: dict[str, Any]) -> str:
    try:
        return command.format(**context)
    except KeyError as exc:
        raise PipelineError(f"command contains unknown context field: {exc.args[0]}") from exc


def output_root(config: dict[str, Any], mode: str) -> str:
    if mode == "prospective_evaluation":
        prospective = config.get("prospective_output_root")
        if not prospective:
            raise PipelineError("prospective_output_root is required for prospective evaluation")
        if prospective == config.get("output_root"):
            raise PipelineError("prospective evaluation output must be distinct from production output")
        return str(prospective)
    return str(config["output_root"])


def stage_context(config: dict[str, Any], config_path: Path, repo_root: Path, mode: str, run_id: str) -> dict[str, Any]:
    return {
        "config": str(config_path),
        "repository_root": str(repo_root),
        "repo_root": str(repo_root),
        "project_root": str(repo_root.parent),
        "output_root": output_root(config, mode),
        "production_output_root": str(config.get("output_root", "")),
        "prospective_output_root": str(config.get("prospective_output_root", "")),
        "scratch_root": str(config.get("scratch_root", "")),
        "logs_root": str(config.get("logs_root", "")),
        "python_executable": str(config.get("python_executable", sys.executable)),
        "run_id": run_id,
        "mode": mode,
    }


def new_run_id(mode: str, sha: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"a3-{mode}-{stamp}-{sha[:8]}"


def run_manifest_path(config: dict[str, Any], run_id: str) -> Path:
    return Path(str(config["logs_root"])).expanduser() / run_id / "submission_manifest.json"


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def base_manifest(run_id: str, mode: str, scientific: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "mode": mode,
        "repository_sha": git_sha(repo_root),
        "scientific_specification_sha256": scientific["manifest_sha256"],
        "predictor_manifest_sha256": scientific["predictor_manifest_sha256"],
        "model_name": scientific["model_name"],
        "theta": scientific["theta"],
        "penalty": scientific["penalty"],
        "domain_node_count": scientific["node_count"],
        "created_utc": utc_now(),
        "stages": {},
    }


def print_plan(config: dict[str, Any], config_path: Path, repo_root: Path, mode: str, run_id: str, scientific: dict[str, Any]) -> None:
    context = stage_context(config, config_path, repo_root, mode, run_id)
    print("A3 PIPELINE DRY RUN")
    print(f"run_id: {run_id}")
    print(f"mode: {mode}")
    print(f"repository_sha: {git_sha(repo_root)}")
    print(f"scientific_manifest_sha256: {scientific['manifest_sha256']}")
    previous = None
    for stage in STAGES:
        dependency = f"afterok:{previous}" if previous else "none"
        command = render_command(command_for(config, mode, stage), context)
        log = Path(str(config["logs_root"])) / run_id / "stages" / f"{stage}.out"
        print(f"stage={stage} job_id=NOT_SUBMITTED dependency={dependency} log={log}")
        print(f"  command={command}")
        previous = f"<job:{stage}>"
    if mode == "prospective_evaluation":
        print("prospective policy: frozen model scoring only; refit not permitted")
    print("submissions: 0")


def submit_pipeline(config: dict[str, Any], config_path: Path, repo_root: Path, mode: str, run_id: str, scientific: dict[str, Any], restart_from: str | None) -> int:
    manifest_path = run_manifest_path(config, run_id)
    if restart_from:
        if restart_from not in STAGES:
            raise PipelineError(f"invalid --restart-from stage: {restart_from}")
        if not manifest_path.exists():
            raise PipelineError(f"restart manifest does not exist: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("mode") != mode or manifest.get("scientific_specification_sha256") != scientific["manifest_sha256"]:
            raise PipelineError("STOP: restart manifest does not match mode or frozen scientific manifest")
        start = STAGES.index(restart_from)
        for stage in STAGES[:start]:
            if manifest.get("stages", {}).get(stage, {}).get("status") != "COMPLETED":
                raise PipelineError(f"STOP: cannot restart at {restart_from}; upstream {stage} is not completed")
    else:
        if manifest_path.exists():
            raise PipelineError(f"run manifest already exists; choose another --run-id or use --restart-from: {manifest_path}")
        manifest = base_manifest(run_id, mode, scientific, repo_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    context = stage_context(config, config_path, repo_root, mode, run_id)
    start = STAGES.index(restart_from) if restart_from else 0
    previous_job: str | None = None
    if start > 0:
        previous = manifest["stages"][STAGES[start - 1]].get("job_id")
        previous_job = previous if previous not in (None, "", "LOCAL") else None
    atomic_write_json(manifest_path, manifest)
    for index in range(start, len(STAGES)):
        stage = STAGES[index]
        dependency = f"afterok:{previous_job}" if previous_job else None
        stage_log_dir = manifest_path.parent / "stages"
        stage_log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = stage_log_dir / f"{stage}.out"
        stderr_path = stage_log_dir / f"{stage}.err"
        stage_runner = repo_root / "scripts" / "a3_pipeline.py"
        command = [
            sys.executable,
            str(stage_runner),
            "--stage",
            stage,
            "--mode",
            mode,
            "--config",
            str(config_path),
            "--run-id",
            run_id,
        ]
        slurm = config.get("slurm", {})
        sbatch = ["sbatch", "--parsable", f"--job-name=a3-{mode[:12]}-{stage}", f"--output={stdout_path}", f"--error={stderr_path}"]
        if slurm.get("account") not in (None, "", "CHANGE_ME"):
            sbatch.append(f"--account={slurm['account']}")
        if slurm.get("partition") not in (None, "", "CHANGE_ME"):
            sbatch.append(f"--partition={slurm['partition']}")
        if slurm.get("qos"):
            sbatch.append(f"--qos={slurm['qos']}")
        for key, flag in (("nodes", "--nodes"), ("ntasks", "--ntasks"), ("cpus_per_task", "--cpus-per-task"), ("mem", "--mem"), ("time", "--time")):
            if slurm.get(key) not in (None, ""):
                sbatch.append(f"{flag}={slurm[key]}")
        if dependency:
            sbatch.append(f"--dependency={dependency}")
        sbatch.extend(["--wrap", " ".join(shlex.quote(part) for part in command)])
        try:
            result = subprocess.run(sbatch, cwd=repo_root, text=True, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            manifest.setdefault("stages", {})[stage] = {"stage": stage, "status": "SUBMISSION_FAILED", "dependency": dependency, "log": str(stdout_path), "error": detail.strip(), "start_time": utc_now()}
            atomic_write_json(manifest_path, manifest)
            raise PipelineError(f"SLURM submission failed for {stage}: {detail.strip()}") from exc
        job_id = result.stdout.strip().splitlines()[-1].split(";")[0]
        manifest.setdefault("stages", {})[stage] = {
            "stage": stage,
            "job_id": job_id,
            "dependency": dependency,
            "status": "SUBMITTED",
            "start_time": utc_now(),
            "log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "input_manifest_sha": scientific["manifest_sha256"],
            "output_manifest_sha": None,
        }
        atomic_write_json(manifest_path, manifest)
        print(f"stage={stage} job_id={job_id} dependency={dependency or 'none'} log={stdout_path}")
        previous_job = job_id
    print(f"submission_manifest={manifest_path}")
    return 0


def lookup(payload: Any, names: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                return payload[name]
        for value in payload.values():
            found = lookup(value, names)
            if found is not None:
                return found
    return None


def validate_deployed_manifest(config: dict[str, Any], scientific: dict[str, Any]) -> None:
    path = Path(str(config.get("inputs", {}).get("deployed_model_manifest", "")))
    if not path.exists():
        raise PipelineError(f"STOP: deployed frozen-model manifest is missing: {path}")
    payload = load_yaml(path) if path.suffix.lower() in {".yaml", ".yml"} else json.loads(path.read_text(encoding="utf-8"))
    required = {
        "model_sha": ("model_sha", "model_sha256", "release_sha", "release_commit"),
        "fit_end_week": ("fit_end_week", "fit_horizon", "current_fit_horizon"),
        "evaluation_end_week": ("evaluation_end_week", "evaluation_horizon", "evaluation_end"),
        "predictor_specification": ("predictor_specification", "predictor_manifest_sha256", "predictor_manifest_hash"),
        "theta": ("theta",),
        "penalty": ("penalty",),
    }
    missing = [label for label, names in required.items() if lookup(payload, names) is None]
    if missing:
        raise PipelineError("STOP: deployed manifest is missing required fields: " + ", ".join(missing))
    theta = float(lookup(payload, required["theta"]))
    penalty = float(lookup(payload, required["penalty"]))
    if theta != scientific["theta"] or penalty != scientific["penalty"]:
        raise PipelineError("STOP: deployed model theta or penalty differs from frozen Structured A3")
    predictor_value = str(lookup(payload, required["predictor_specification"]))
    if scientific["predictor_manifest_sha256"] not in predictor_value and predictor_value != scientific["manifest_sha256"]:
        raise PipelineError("STOP: deployed predictor specification does not match the frozen manifest")


def update_stage_manifest(path: Path, stage: str, update: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        raise PipelineError(f"run manifest does not exist: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("stages", {}).setdefault(stage, {}).update(update)
    atomic_write_json(path, manifest)
    return manifest


def run_stage(config: dict[str, Any], config_path: Path, repo_root: Path, mode: str, run_id: str, stage: str, scientific: dict[str, Any]) -> int:
    if stage not in STAGES:
        raise PipelineError(f"invalid stage: {stage}")
    manifest_path = run_manifest_path(config, run_id)
    # P0 retains the frozen-model guard here, then invokes the repository
    # preflight adapter so horizon and leakage evidence are persisted.
    if mode == "prospective_evaluation" and stage == "P3":
        validate_deployed_manifest(config, scientific)
        command = command_for(config, mode, stage)
        if "--no-refit" not in command and "no_refit" not in command:
            raise PipelineError("STOP: prospective stage command does not declare no-refit")
    context = stage_context(config, config_path, repo_root, mode, run_id)
    start = utc_now()
    update_stage_manifest(manifest_path, stage, {"status": "RUNNING", "start_time": start, "job_id": os.environ.get("SLURM_JOB_ID", "LOCAL")})
    try:
        command = render_command(command_for(config, mode, stage), context)
        completed = subprocess.run(command, cwd=repo_root, shell=True, text=True)
        if completed.returncode != 0:
            raise PipelineError(f"configured command exited with status {completed.returncode}")
        if stage in {"P1", "P2", "P3"}:
            leakage = Path(str(config["logs_root"])) / run_id / "leakage_audit.json"
            if leakage.exists():
                audit = json.loads(leakage.read_text(encoding="utf-8"))
                bad = audit.get("same_week_or_future_uses", audit.get("same_week_or_future_rows", 0))
                if int(bad or 0) != 0:
                    raise PipelineError("STOP: history-feature leakage audit found same-week or future uses")
        output_manifest = Path(str(config["logs_root"])) / run_id / "output_manifest.json"
        output_sha = sha256_file(output_manifest) if output_manifest.exists() else None
        update_stage_manifest(manifest_path, stage, {"status": "COMPLETED", "end_time": utc_now(), "output_manifest_sha": output_sha})
        if mode == "prospective_evaluation" and stage == "P5":
            print("PROSPECTIVE EVALUATION COMPLETE — REFIT NOT PERFORMED")
        return 0
    except Exception as exc:
        update_stage_manifest(manifest_path, stage, {"status": "FAILED", "end_time": utc_now(), "error": str(exc)})
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--restart-from", choices=STAGES)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--internal-preflight", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.mode:
        raise PipelineError("--mode is required")
    config, repo_root, scientific_path = load_config(args.config)
    scientific = validate_frozen_manifest(scientific_path)
    validate_config(config, args.mode, dry_run=args.dry_run, scientific=scientific)
    current_sha = git_sha(repo_root)
    run_id = args.run_id or new_run_id(args.mode, current_sha if current_sha != "unknown" else scientific["manifest_sha256"])
    if args.stage:
        return run_stage(config, args.config.resolve(), repo_root, args.mode, run_id, args.stage, scientific)
    if args.internal_preflight:
        print(json.dumps({"status": "P0_PASS", "model": MODEL_NAME, "predictors": PREDICTOR_COUNT, "theta": THETA, "penalty": PENALTY, "objective": OBJECTIVE, "node_count": NODE_COUNT}, indent=2))
        return 0
    if args.dry_run:
        print_plan(config, args.config.resolve(), repo_root, args.mode, run_id, scientific)
        return 0
    return submit_pipeline(config, args.config.resolve(), repo_root, args.mode, run_id, scientific, args.restart_from)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PipelineError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

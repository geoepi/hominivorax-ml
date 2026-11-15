import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "analysis/a6_vif_bounded_gate/config/a6_vif_config.json"
RUNNER_PATH = ROOT / "analysis/a6_vif_bounded_gate/scripts/run_a6_vif.py"
SBATCH_PATH = ROOT / "hpc/run_a6_vif.sbatch"


def load_finalizer():
    path = ROOT / "analysis/a6_vif_bounded_gate/scripts/finalize_a6_vif_budget.py"
    spec = importlib.util.spec_from_file_location("a6_vif_budget_finalizer_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def function_node(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


class A6VIFGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.source = RUNNER_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_fixed_vif_configuration_and_fold_scope(self):
        gp = self.config["gpboost_overrides"]
        self.assertEqual(gp["likelihood"], "bernoulli_logit")
        self.assertEqual(gp["gp_approx"], "full_scale_vecchia")
        self.assertEqual(gp["num_ind_points"], 200)
        self.assertEqual(gp["ind_points_selection"], "kmeans++")
        self.assertEqual(gp["num_neighbors"], 8)
        self.assertEqual(gp["num_neighbors_pred"], 40)
        self.assertEqual(gp["matrix_inversion_method"], "iterative")
        self.assertEqual(gp["vecchia_ordering_spatiotemporal"], "time")
        self.assertEqual(self.config["covariance_estimation"]["gp_seed"], 31415)
        self.assertEqual(self.config["execution"]["gate_resources"], {
            "automatic_retries": 0,
            "internal_deadline": "05:20:00",
            "walltime": "06:00:00",
            "cpu_hours": 96,
            "hard_stop": "05:35:00",
            "cpus": 16,
            "memory": "64G",
        })
        self.assertIn("args.fold != 3 or args.seeds != [31415]", self.source)
        self.assertIn("np.arange(41)", self.source)
        self.assertIn("np.arange(41, 52)", self.source)
        self.assertIn("np.arange(52, 60)", self.source)

    def test_gpboost_constructor_and_fixed_covariance_contract(self):
        make_gp = function_node(self.tree, "make_gp_model")
        constructor = next(
            node for node in ast.walk(make_gp)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "GPModel"
        )
        names = {keyword.arg for keyword in constructor.keywords}
        self.assertTrue({
            "likelihood", "gp_coords", "cov_function", "cov_fct_shape", "gp_approx",
            "num_ind_points", "ind_points_selection", "num_neighbors",
            "vecchia_ordering", "matrix_inversion_method", "num_parallel_threads", "seed",
        }.issubset(names))

        fit = function_node(self.tree, "fixed_covariance_train")
        train_call = next(
            node for node in ast.walk(fit)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "train"
        )
        kwargs = {keyword.arg: keyword.value for keyword in train_call.keywords}
        self.assertIsInstance(kwargs["train_gp_model_cov_pars"], ast.Constant)
        self.assertIs(kwargs["train_gp_model_cov_pars"].value, False)
        self.assertIn("covariance_parameter_differences", ast.unparse(fit))
        self.assertIn("gp.set_optim_params", ast.unparse(fit))

    def test_one_shot_slurm_budget_and_thread_contract(self):
        parser = function_node(self.tree, "create_parser")
        self.assertIn("choices=['gate']", ast.unparse(parser))
        sbatch = SBATCH_PATH.read_text(encoding="utf-8")
        for directive in (
            "#SBATCH --cpus-per-task=16",
            "#SBATCH --mem=64G",
            "#SBATCH --time=06:00:00",
            "#SBATCH --signal=B:USR1@1800",
            "#SBATCH --no-requeue",
        ):
            self.assertIn(directive, sbatch)
        self.assertIn("HARD_DEADLINE=$((JOB_SCRIPT_STARTED + 20100))", sbatch)
        self.assertIn("kill -KILL", sbatch)
        self.assertIn("num_parallel_threads=int(threads)", self.source)

    def test_budget_finalizer_preserves_stage_a_and_marks_running_stage_b(self):
        finalizer = load_finalizer()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage_a = root / "folds/fold_03/covariance/outer/attempt_001"
            stage_b = root / "folds/fold_03/seeds/seed_31415/attempt_001"
            stage_a.mkdir(parents=True)
            stage_b.mkdir(parents=True)
            (stage_a / "stage_a_estimate.json").write_text("{}", encoding="utf-8")
            (stage_a / "completion.json").write_text(json.dumps({"status": "COMPLETED"}), encoding="utf-8")
            (stage_a / "status.json").write_text(json.dumps({"status": "COMPLETED"}), encoding="utf-8")
            (stage_b / "status.json").write_text(json.dumps({"status": "RUNNING", "stage": "STAGE_B"}), encoding="utf-8")
            logs = root / "logs"
            logs.mkdir()
            (logs / "progress.jsonl").write_text(json.dumps({"stage": "STAGE_B", "event": "ITERATION", "iteration": 8}) + "\n", encoding="utf-8")

            result = finalizer.finalize(root, 124, True, "hard timeout")

            decision = json.loads((root / "results/a6_vif_gate_decision.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "A6_VIF_GATE_NOT_SUPPORTED")
            self.assertEqual(decision["failure_classification"], "INCOMPLETE_BUDGET_EXCEEDED")
            self.assertEqual(len(decision["completed_stage_a_estimates"]), 1)
            self.assertFalse(decision["stage_b_completed"])
            self.assertEqual(json.loads((stage_a / "status.json").read_text(encoding="utf-8"))["status"], "COMPLETED")
            self.assertEqual(json.loads((stage_b / "status.json").read_text(encoding="utf-8"))["status"], "INCOMPLETE_BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()

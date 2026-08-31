from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from runtime_assurance.cli import main
from runtime_assurance.config import write_json
from runtime_assurance.pipeline import run_benchmark
from runtime_assurance.provenance import verify_manifest


ROOT = Path(__file__).resolve().parents[1]


def copy_benchmark_sources(root: Path) -> None:
    for relative in [
        Path("config/assurance_policy.json"),
        Path("assurance_case/uav_runtime_case.json"),
        Path("hazards/stpa_model.json"),
    ]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    shutil.copytree(
        ROOT / "runtime_assurance",
        root / "runtime_assurance",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


class PipelineAndCliTests(unittest.TestCase):
    def test_validate_cli_accepts_committed_models(self) -> None:
        self.assertEqual(main(["validate", "--root", str(ROOT)]), 0)

    def test_small_benchmark_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_benchmark_sources(root)
            write_json(
                root / "experiments" / "benchmark_config.json",
                {
                    "schema_version": "1.0",
                    "duration_s": 30.0,
                    "sample_period_s": 0.1,
                    "scenario_oracle": {
                        "comm_age_ms_min": 1200.0,
                        "cross_modal_consistency_max": 0.35,
                        "lidar_age_ms_min": 500.0,
                        "localization_confidence_max": 0.45,
                        "stopping_margin_m_max": 0.0,
                    },
                    "representative_seed": 1,
                    "seeds": [1, 2],
                    "scenarios": [
                        {
                            "id": "baseline",
                            "fault": "none",
                            "onset_s": None,
                            "expected_monitor_ids": [],
                            "action_trigger_monitor_id": None,
                            "expected_action": "CONTINUE",
                        },
                        {
                            "id": "communication_loss",
                            "fault": "communication_loss",
                            "onset_s": 2.0,
                            "expected_monitor_ids": ["M-COMM-FRESH"],
                            "action_trigger_monitor_id": "M-COMM-FRESH",
                            "expected_action": "RETURN_HOME",
                        },
                    ],
                },
            )
            first = run_benchmark(root)
            self.assertEqual(first["run_count"], 4)
            self.assertTrue(first["all_benchmark_checks_passed"])
            verified = verify_manifest(root)
            self.assertEqual(verified["traces_verified"], 4)
            self.assertGreater(verified["results_verified"], 0)
            first_bytes = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            second = run_benchmark(root)
            self.assertEqual(first, second)
            second_bytes = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_bytes, second_bytes)

    def test_manifest_verifier_detects_modified_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_benchmark_sources(root)
            write_json(
                root / "experiments" / "benchmark_config.json",
                {
                    "schema_version": "1.0",
                    "duration_s": 2.0,
                    "sample_period_s": 0.1,
                    "scenario_oracle": {
                        "comm_age_ms_min": 1200.0,
                        "cross_modal_consistency_max": 0.35,
                        "lidar_age_ms_min": 500.0,
                        "localization_confidence_max": 0.45,
                        "stopping_margin_m_max": 0.0,
                    },
                    "representative_seed": 1,
                    "seeds": [1],
                    "scenarios": [
                        {
                            "id": "baseline",
                            "fault": "none",
                            "onset_s": None,
                            "expected_monitor_ids": [],
                            "action_trigger_monitor_id": None,
                            "expected_action": "CONTINUE",
                        }
                    ],
                },
            )
            run_benchmark(root)
            trace = root / "data" / "generated" / "traces" / "baseline" / "seed-1.csv"
            trace.write_bytes(trace.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verify_manifest(root)

    def test_manifest_verifier_detects_modified_result_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copy_benchmark_sources(root)
            (root / "experiments").mkdir(parents=True, exist_ok=True)
            shutil.copy2(
                ROOT / "experiments" / "benchmark_config.json",
                root / "experiments" / "benchmark_config.json",
            )
            run_benchmark(root)

            report = root / "results" / "benchmark_report.md"
            original_report = report.read_bytes()
            report.write_bytes(original_report + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verify_manifest(root)
            report.write_bytes(original_report)
            self.assertTrue(verify_manifest(root)["valid"])

            nested_source = root / "runtime_assurance" / "subpkg" / "helper.py"
            nested_source.parent.mkdir(parents=True, exist_ok=True)
            nested_source.write_text("VALUE = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source manifest coverage mismatch"):
                verify_manifest(root)
            nested_source.unlink()

            source = root / "runtime_assurance" / "evaluation.py"
            source.write_bytes(source.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verify_manifest(root)


if __name__ == "__main__":
    unittest.main()

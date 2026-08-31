from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime_assurance.config import load_policy, read_json
from runtime_assurance.evaluation import replay_trace
from runtime_assurance.simulation import generate_trace, load_benchmark, read_trace, write_trace


ROOT = Path(__file__).resolve().parents[1]


class SimulationAndEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(ROOT / "config" / "assurance_policy.json")
        self.case = read_json(ROOT / "assurance_case" / "uav_runtime_case.json")
        self.stpa = read_json(ROOT / "hazards" / "stpa_model.json")
        self.benchmark = load_benchmark(
            ROOT / "experiments" / "benchmark_config.json", self.policy
        )

    def test_generation_is_byte_deterministic(self) -> None:
        scenario = self.benchmark.scenarios[1]
        first = generate_trace(scenario, 101, self.benchmark, self.policy)
        second = generate_trace(scenario, 101, self.benchmark, self.policy)
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.csv"
            second_path = Path(directory) / "second.csv"
            write_trace(first_path, first)
            write_trace(second_path, second)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())

    def test_baseline_selects_only_continue(self) -> None:
        scenario = self.benchmark.scenarios[0]
        rows = generate_trace(scenario, 101, self.benchmark, self.policy)
        replay = replay_trace(
            rows,
            self.policy,
            self.case,
            self.stpa,
            scenario.expected_monitor_ids,
            scenario.action_trigger_monitor_id,
            scenario.expected_action,
        )
        self.assertEqual(replay.metrics.maximum_action, "CONTINUE")
        self.assertEqual(replay.metrics.pre_injection_intervention_rate, 0.0)
        self.assertIsNone(replay.metrics.scenario_oracle_positive_coverage)

    def test_every_fault_activates_target_monitor_and_action(self) -> None:
        for scenario in self.benchmark.scenarios[1:]:
            with self.subTest(scenario=scenario.id):
                rows = generate_trace(scenario, 101, self.benchmark, self.policy)
                replay = replay_trace(
                    rows,
                    self.policy,
                    self.case,
                    self.stpa,
                    scenario.expected_monitor_ids,
                    scenario.action_trigger_monitor_id,
                    scenario.expected_action,
                )
                self.assertTrue(replay.metrics.expected_monitors_activated)
                self.assertIsNotNone(replay.metrics.assurance_response_time_s)
                self.assertLessEqual(float(replay.metrics.assurance_response_time_s), 0.3)
                self.assertIsNotNone(replay.metrics.policy_response_time_s)
                self.assertLessEqual(float(replay.metrics.policy_response_time_s), 0.3)
                self.assertTrue(replay.metrics.exact_expected_action_selected)
                self.assertEqual(replay.metrics.maximum_action, scenario.expected_action)
                self.assertFalse(replay.metrics.unexpected_monitor_activation)
                self.assertFalse(replay.metrics.overreaction_observed)
                self.assertIsNotNone(replay.metrics.pre_oracle_intervention_rate)

    def test_reader_rejects_non_monotonic_timestamps(self) -> None:
        scenario = self.benchmark.scenarios[0]
        rows = generate_trace(scenario, 101, self.benchmark, self.policy)[:3]
        rows[2]["timestamp_s"] = rows[1]["timestamp_s"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.csv"
            write_trace(path, rows)
            with self.assertRaisesRegex(ValueError, "strictly increasing"):
                read_trace(path)

    def test_benchmark_rejects_overflowed_integer_seed(self) -> None:
        text = (ROOT / "experiments" / "benchmark_config.json").read_text(encoding="utf-8")
        text = text.replace('"seeds": [101,', '"seeds": [1e309,', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.json"
            path.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                load_benchmark(path, self.policy)

    def test_action_cannot_be_counted_once_then_drop_during_positive_oracle(self) -> None:
        scenario = self.benchmark.scenarios[1]
        rows = generate_trace(scenario, 101, self.benchmark, self.policy)
        for row in rows:
            if float(row["timestamp_s"]) >= 23.0:
                row["localization_confidence"] = 0.95
                row["scenario_oracle_positive"] = True
        replay = replay_trace(
            rows,
            self.policy,
            self.case,
            self.stpa,
            scenario.expected_monitor_ids,
            scenario.action_trigger_monitor_id,
            scenario.expected_action,
        )
        self.assertTrue(replay.metrics.exact_expected_action_selected)
        self.assertTrue(replay.metrics.post_selection_underreaction_observed)
        self.assertGreater(replay.metrics.post_selection_underreaction_frames, 0)


if __name__ == "__main__":
    unittest.main()

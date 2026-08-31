from __future__ import annotations

import unittest
import copy
import tempfile
from pathlib import Path

from runtime_assurance.config import load_policy, read_json, write_json
from runtime_assurance.monitors import derive_metric
from runtime_assurance.supervisor import RuntimeAssuranceSupervisor


ROOT = Path(__file__).resolve().parents[1]


def safe_frame(timestamp_s: float) -> dict[str, object]:
    return {
        "timestamp_s": timestamp_s,
        "localization_confidence": 0.95,
        "lidar_age_ms": 50.0,
        "cross_modal_consistency": 0.92,
        "obstacle_distance_m": 12.0,
        "speed_mps": 2.0,
        "comm_age_ms": 80.0,
        "fallback_available": True,
    }


class MonitorAndSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(ROOT / "config" / "assurance_policy.json")
        self.case = read_json(ROOT / "assurance_case" / "uav_runtime_case.json")
        self.stpa = read_json(ROOT / "hazards" / "stpa_model.json")

    def supervisor(self) -> RuntimeAssuranceSupervisor:
        return RuntimeAssuranceSupervisor(self.policy, self.case, self.stpa)

    def test_stopping_margin_uses_declared_flight_envelope(self) -> None:
        monitor = self.policy.monitors_by_id["M-OBS-MARGIN"]
        margin = derive_metric(safe_frame(0.0), monitor, self.policy)
        self.assertAlmostEqual(float(margin), 8.7, places=6)

    def test_failure_requires_three_samples_and_recovery_requires_five(self) -> None:
        supervisor = self.supervisor()
        self.assertEqual(
            supervisor.step(safe_frame(0.0)).argument_support_state.value, "SUPPORTED"
        )
        for index in range(1, 3):
            frame = safe_frame(index * 0.1)
            frame["localization_confidence"] = 0.2
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.argument_support_state.value, "DEGRADED")
        frame = safe_frame(0.3)
        frame["localization_confidence"] = 0.2
        failed = supervisor.step(frame)
        self.assertEqual(failed.argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(failed.action, "HOVER")

        for index in range(4, 8):
            self.assertEqual(
                supervisor.step(safe_frame(index * 0.1)).argument_support_state.value,
                "UNSUPPORTED",
            )
        recovered = supervisor.step(safe_frame(0.8))
        self.assertEqual(recovered.argument_support_state.value, "SUPPORTED")
        self.assertEqual(recovered.action, "CONTINUE")

    def test_missing_metric_fails_closed_to_abort(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame.pop("comm_age_ms")
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(snapshot.action, "ABORT")
        self.assertEqual(snapshot.observations["M-COMM-FRESH"].reason, "missing or non-finite input")

    def test_string_false_is_not_coerced_to_true(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame["fallback_available"] = "false"
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(snapshot.action, "ABORT")

    def test_latched_failure_escalates_when_evidence_becomes_missing(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame["localization_confidence"] = 0.2
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.action, "HOVER")

        for index in range(3, 5):
            frame = safe_frame(index * 0.1)
            frame.pop("localization_confidence")
            snapshot = supervisor.step(frame)
            self.assertEqual(snapshot.action, "HOVER")
        frame = safe_frame(0.5)
        frame.pop("localization_confidence")
        snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(snapshot.action, "ABORT")

    def test_alternating_numeric_and_missing_failures_cannot_remain_supported(self) -> None:
        supervisor = self.supervisor()
        snapshots = []
        for index in range(10):
            frame = safe_frame(index * 0.1)
            if index % 2:
                frame.pop("localization_confidence")
            else:
                frame["localization_confidence"] = 0.2
            snapshots.append(supervisor.step(frame))
        self.assertEqual(snapshots[2].argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(snapshots[2].action, "HOVER")
        self.assertTrue(
            all(
                snapshot.argument_support_state.value != "SUPPORTED"
                for snapshot in snapshots[2:]
            )
        )

    def test_alternating_warning_and_failure_latches_degraded_support(self) -> None:
        supervisor = self.supervisor()
        snapshots = []
        for index in range(10):
            frame = safe_frame(index * 0.1)
            frame["localization_confidence"] = 0.7 if index % 2 == 0 else 0.2
            snapshots.append(supervisor.step(frame))
        self.assertEqual(snapshots[1].argument_support_state.value, "DEGRADED")
        self.assertTrue(
            all(
                snapshot.argument_support_state.value != "SUPPORTED"
                for snapshot in snapshots[1:]
            )
        )

    def test_abort_action_requires_recovery_window_before_downgrade(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame.pop("localization_confidence")
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.action, "ABORT")

        for index in range(3, 7):
            frame = safe_frame(index * 0.1)
            frame["localization_confidence"] = 0.2
            snapshot = supervisor.step(frame)
            self.assertEqual(snapshot.action, "ABORT")
        frame = safe_frame(0.7)
        frame["localization_confidence"] = 0.2
        snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.action, "HOVER")

    def test_mixed_pass_and_warning_recovery_reaches_degraded(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame["localization_confidence"] = 0.2
            snapshot = supervisor.step(frame)
        self.assertEqual(snapshot.argument_support_state.value, "UNSUPPORTED")

        for offset in range(5):
            frame = safe_frame((offset + 3) * 0.1)
            frame["localization_confidence"] = 0.95 if offset % 2 == 0 else 0.7
            snapshot = supervisor.step(frame)
            if offset < 4:
                self.assertEqual(snapshot.argument_support_state.value, "UNSUPPORTED")
        self.assertEqual(snapshot.argument_support_state.value, "DEGRADED")
        self.assertEqual(snapshot.action, "SLOW")

    def test_overflowing_derived_margin_fails_closed(self) -> None:
        supervisor = self.supervisor()
        for index in range(3):
            frame = safe_frame(index * 0.1)
            frame["speed_mps"] = 1e308
            snapshot = supervisor.step(frame)
        self.assertIsNone(snapshot.observations["M-OBS-MARGIN"].value)
        self.assertEqual(snapshot.action, "ABORT")

    def test_non_finite_policy_values_are_rejected(self) -> None:
        raw = read_json(ROOT / "config" / "assurance_policy.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for value in ["NaN", "Infinity", "-Infinity"]:
                invalid = copy.deepcopy(raw)
                invalid["flight_envelope"][
                    "guaranteed_deceleration_lower_bound_mps2"
                ] = value
                write_json(path, invalid)
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, "finite"):
                        load_policy(path)
            path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Non-finite JSON number"):
                read_json(path)
            with self.assertRaises(ValueError):
                write_json(path, {"value": float("nan")})

            text = (ROOT / "config" / "assurance_policy.json").read_text(
                encoding="utf-8"
            )
            path.write_text(text.replace('"ABORT": 5', '"ABORT": 1e309'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finite"):
                load_policy(path)

    def test_invalid_action_priority_is_rejected_during_load(self) -> None:
        raw = read_json(ROOT / "config" / "assurance_policy.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            invalid = copy.deepcopy(raw)
            invalid["action_priority"].pop("CONTINUE")
            write_json(path, invalid)
            with self.assertRaisesRegex(ValueError, "define CONTINUE"):
                load_policy(path)

            invalid = copy.deepcopy(raw)
            invalid["monitors"][0]["missing_action"] = "SLOW"
            write_json(path, invalid)
            with self.assertRaisesRegex(ValueError, "warning <= failure <= missing"):
                load_policy(path)

            for value in [True, 5.5]:
                invalid = copy.deepcopy(raw)
                invalid["action_priority"]["ABORT"] = value
                write_json(path, invalid)
                with self.subTest(priority=value):
                    with self.assertRaisesRegex(ValueError, "positive integer|must be an integer"):
                        load_policy(path)


if __name__ == "__main__":
    unittest.main()

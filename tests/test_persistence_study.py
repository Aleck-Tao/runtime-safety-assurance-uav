from dataclasses import replace
from pathlib import Path
import unittest

from runtime_assurance.config import load_policy, read_json
from runtime_assurance.persistence_study import event_metrics, intervals, load_settings, make_trace
from runtime_assurance.supervisor import RuntimeAssuranceSupervisor


ROOT = Path(__file__).resolve().parents[1]


class PersistenceStudyTests(unittest.TestCase):
    def setUp(self):
        self.base = load_policy(ROOT / "config/assurance_policy.json")
        self.settings = load_settings(ROOT)
        self.case = read_json(ROOT / "assurance_case/uav_runtime_case.json")
        self.stpa = read_json(ROOT / "hazards/stpa_model.json")

    def replay(self, family, pattern, persistence, threshold):
        rows = make_trace(family, pattern, 101, self.base, self.settings)
        monitor_id = self.settings["families"][family]["monitor_id"]
        policy = replace(self.base, failure_samples=persistence,
            monitors=tuple(replace(m, fail_threshold=threshold) if m.id == monitor_id else m
                           for m in self.base.monitors))
        supervisor = RuntimeAssuranceSupervisor(policy, self.case, self.stpa)
        selected = [policy.action_priority[supervisor.step(row).action] >= policy.action_priority["HOVER"]
                    for row in rows]
        return event_metrics([row["oracle_positive"] for row in rows], selected, .1, 150)

    def test_short_events_expose_persistence_misses_for_both_families(self):
        for family, threshold in (("localization", .55), ("obstacle", 0.)):
            for persistence, detected in ((1, 4), (3, 2), (5, 1)):
                with self.subTest(family=family, persistence=persistence):
                    metrics, events = self.replay(family, "short_pulses", persistence, threshold)
                    self.assertEqual(metrics["event_count"], 4)
                    self.assertEqual(metrics["detected_events"], detected)
                    for event in events:
                        if event["detected"]:
                            self.assertAlmostEqual(event["detection_delay_s"], (persistence - 1) * .1)
                        else:
                            self.assertIsNone(event["detection_delay_s"])

    def test_each_repeated_event_requires_new_detection_and_recovery(self):
        metrics, events = self.replay("localization", "repeated_recovery", 5, .55)
        self.assertEqual(metrics["detected_events"], 3)
        self.assertEqual(metrics["unmatched_action_episodes"], 0)
        for event in events:
            self.assertEqual(event["detection_delay_s"], .4)
            self.assertEqual(event["recovery_delay_s"], .4)
            self.assertFalse(event["recovery_censored"])

    def test_boundary_noise_separates_oracle_from_monitor_threshold(self):
        aggressive, events = self.replay("localization", "boundary_noise", 1, .60)
        conservative, _ = self.replay("localization", "boundary_noise", 5, .50)
        self.assertEqual(events, [])
        self.assertIsNone(aggressive["event_recall"])
        self.assertGreater(aggressive["unmatched_action_episodes"], 0)
        self.assertEqual(conservative["unmatched_action_episodes"], 0)

    def test_appending_quiet_samples_cannot_dilute_event_metrics(self):
        oracle = [False] * 10 + [True] * 10 + [False] * 10
        action = [False] * 12 + [True] * 12 + [False] * 6
        expected = event_metrics(oracle, action, .1, 30)
        self.assertEqual(expected, event_metrics(oracle + [False] * 1000, action + [False] * 1000, .1, 30))

    def test_extending_positive_tail_does_not_improve_detection_delay_or_recall(self):
        short, _ = event_metrics([False] * 10 + [True] * 10 + [False] * 10,
                                 [False] * 12 + [True] * 10 + [False] * 8, .1, 30)
        long, _ = event_metrics([False] * 10 + [True] * 100 + [False] * 10,
                                [False] * 12 + [True] * 100 + [False] * 8, .1, 120)
        for field in ("event_recall", "detected_events", "max_detected_delay_s", "unmatched_action_episodes"):
            self.assertEqual(short[field], long[field])

    def test_missed_event_is_not_a_zero_latency_success(self):
        metrics, events = event_metrics([False, True, True, False], [False] * 4, .1, 4)
        self.assertEqual(metrics["missed_events"], 1)
        self.assertIsNone(metrics["max_detected_delay_s"])
        self.assertIsNone(events[0]["detection_delay_s"])

    def test_early_episode_is_matched_and_has_signed_lead(self):
        metrics, events = event_metrics([False, False, True, True, False],
                                       [False, True, True, True, False], .1, 5)
        self.assertEqual(metrics["unmatched_action_episodes"], 0)
        self.assertEqual(events[0]["detection_delay_s"], 0.)
        self.assertEqual(events[0]["signed_action_onset_offset_s"], -.1)

    def test_right_censoring_and_missing_recovery_are_explicit(self):
        metrics, events = event_metrics([False, True, True], [False, True, True], .1, 3)
        self.assertTrue(events[0]["event_right_censored"])
        self.assertTrue(events[0]["recovery_censored"])
        self.assertEqual(metrics["recovery_censored_events"], 1)

    def test_intervals_keep_single_sample_and_terminal_event(self):
        self.assertEqual(intervals([True, False, True, True]), [(0, 1), (2, 4)])

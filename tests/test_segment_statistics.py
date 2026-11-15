"""Check clustered ratio variance and shared-user covariance against known values."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from segment_statistics import cluster_rate, cluster_difference


class SegmentStatisticsTests(unittest.TestCase):
    def test_rate_uses_episode_ratio_and_cluster_correction(self):
        result = cluster_rate([1, 0, 1, 0], [1, 1, 1, 1])
        self.assertEqual(result["estimate"], 0.5)
        self.assertAlmostEqual(result["standard_error"] ** 2, 1 / 12)
        weighted = cluster_rate([8, 0], [10, 1])
        self.assertAlmostEqual(weighted["estimate"], 8 / 11)

    def test_paired_users_are_not_treated_as_independent_groups(self):
        result = cluster_difference([1, 0, 1, 0], [1, 1, 1, 1], [2, 0, 2, 0], [2, 2, 2, 2])
        self.assertEqual(result["estimate"], 0)
        self.assertEqual(result["standard_error"], 0)
        self.assertIsNone(result["p_value"])

    def test_difference_matches_hand_computed_joint_influence(self):
        result = cluster_difference([0, 0, 1, 0], [1, 2, 2, 1], [1, 1, 1, 0], [2, 1, 2, 1])
        self.assertAlmostEqual(result["estimate"], 1 / 3)
        self.assertAlmostEqual(result["standard_error"] ** 2, 23 / 486)
        self.assertEqual(result["confidence_level"], 0.975)
        self.assertAlmostEqual(result["adjusted_p_value"], min(1, 2 * result["p_value"]))

    def test_row_order_does_not_change_inference(self):
        y, n = np.array([0, 1, 3]), np.array([1, 2, 4])
        original = cluster_rate(y, n)
        shuffled = cluster_rate(y[::-1], n[::-1])
        self.assertAlmostEqual(original["standard_error"], shuffled["standard_error"])

    def test_empty_degenerate_and_invalid_counts_are_explicit(self):
        self.assertEqual(cluster_rate([], [])["inference_status"], "no_observations")
        self.assertEqual(cluster_rate([0, 0], [1, 2])["inference_status"], "degenerate_variance")
        self.assertEqual(cluster_rate([1], [2])["inference_status"], "insufficient_clusters")
        for y, n in [([2], [1]), ([0.5], [1]), ([float('nan')], [1]), ([1, 0], [1])]:
            with self.assertRaises(ValueError):
                cluster_rate(y, n)


if __name__ == "__main__":
    unittest.main()

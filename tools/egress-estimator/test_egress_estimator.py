import unittest
from unittest.mock import patch, mock_open
import sys
import os

# Ensure tools/egress-estimator is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egress_estimator as ee


class TestEgressEstimator(unittest.TestCase):
    def test_workload_calculation_and_bounds(self):
        w = ee.Workload("test-api", 100.0, 30, 2.0)
        # 100 * 30 + 2 * 1024 = 3000 + 2048 = 5048.0
        self.assertEqual(w.total_gb, 5048.0)

        with self.assertRaises(ValueError):
            ee.Workload("bad-api", -10.0, 30, 0.0)
        with self.assertRaises(ValueError):
            ee.Workload("bad-window", 100.0, 0, 0.0)
        with self.assertRaises(ValueError):
            ee.Workload("bad-seed", 100.0, 30, -1.0)

    def test_estimate_normal_and_zero_rate(self):
        workloads = [ee.Workload("api", 100.0, 30, 0.0)]  # 3000 GB over 30 days (1 mo)
        
        # Normal rate ($0.10/GB, $9000/mo CCI) -> internet total = $300, break_even = 90,000 GB
        res = ee.estimate(workloads, 0.10, 9000.0, 0.0)
        self.assertEqual(res["summary"]["internet_total_usd"], 300.0)
        self.assertEqual(res["summary"]["cci_total_usd"], 9000.0)
        self.assertEqual(res["summary"]["break_even_gb"], 90000.0)
        self.assertEqual(res["summary"]["recommendation"], "Internet egress")

        # Zero internet rate -> break_even should be inf without ZeroDivisionError
        res_zero = ee.estimate(workloads, 0.0, 9000.0, 0.0)
        self.assertEqual(res_zero["summary"]["break_even_gb"], float("inf"))
        self.assertEqual(res_zero["summary"]["recommendation"], "Internet egress")

    def test_load_workloads_csv(self):
        csv_data = "workload,gb_per_day,window_days,seed_tib\nsvc-a,50,21,1\n"
        with patch("builtins.open", mock_open(read_data=csv_data)):
            wls = ee.load_workloads("dummy.csv", 30)
            self.assertEqual(len(wls), 1)
            self.assertEqual(wls[0].name, "svc-a")
            self.assertEqual(wls[0].gb_per_day, 50.0)
            self.assertEqual(wls[0].window_days, 21)
            self.assertEqual(wls[0].seed_tib, 1.0)


if __name__ == "__main__":
    unittest.main()

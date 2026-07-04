"""端到端单测：自博弈产 trace → analysis.parser 产有效 Report；SimValidator 0 误差。"""

import json
import os
import shutil
import tempfile
import unittest

import _pathsetup  # noqa: F401
from analysis.parser import parse_log
import sim_server


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.out_dir = tempfile.mkdtemp(prefix="sim_e2e_")

    def tearDown(self):
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_self_play_produces_valid_report(self):
        summary = sim_server.play_one_game(seed=7, variant="baseline", out_dir=self.out_dir,
                                           verbose=False)
        self.assertTrue(summary["recon_ok"], summary.get("recon_msg", ""))
        # 两个 trace 文件
        logs = sorted(f for f in os.listdir(self.out_dir) if f.endswith(".log"))
        self.assertEqual(len(logs), 2)
        for fn in logs:
            report = parse_log(os.path.join(self.out_dir, fn), source="sim", variant="baseline")
            self.assertIsNotNone(report, "parser returned None for %s" % fn)
            self.assertIn(report.get("outcome"), ("WIN", "LOSS", "TIE", "UNDELIVERED"))
            me = report.get("finalScore", {}).get("me", {})
            self.assertIsNotNone(me.get("total"))
            # baseline 应稳定交付（双方都交付）
            self.assertTrue(report.get("delivery", {}).get("me", {}).get("frame", 0) > 0)


if __name__ == "__main__":
    unittest.main()

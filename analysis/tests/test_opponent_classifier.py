"""`analysis.opponent_classifier` + aggregator 对手类分桶单测（Iter 32）。

三类阈值（物理含义，不扫参数）：guard-type（oppGuards 非空）/ quality-route
（freshnessEnd≥85 且 goodFruitEnd≥95 或 iceUsed）/ speed-route（其余）。旧 trace 无
对手鲜度且无设卡 → unknown。优先级 guard > quality > speed。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "client"))

from analysis import aggregator as A  # noqa: E402
from analysis.opponent_classifier import (  # noqa: E402
    CLASS_GUARD, CLASS_QUALITY, CLASS_SPEED, CLASS_UNKNOWN,
    annotate_opp_class, classify_opponent,
)


def _report(match_id="m1", outcome="WIN", me_total=755,
            opp_fresh_end=None, opp_good_end=None, opp_ice=None,
            opp_guards=None, opp_deliver=None, opp_task=60, opp_total=760):
    """构造一份含对手字段的 Report（控制分类器输入）。"""
    opp_guards = opp_guards or []
    return {
        "schemaVersion": 2, "matchId": match_id, "playerId": 1001, "teamId": "RED",
        "source": "platform", "variant": "baseline", "durationRound": 600,
        "outcome": outcome,
        "finalScore": {"me": {"total": me_total}, "opp": {"total": opp_total}},
        "delivery": {"me": {"frame": 444, "freshness": 79.9, "goodFruit": 97},
                     "opp": {"frame": opp_deliver}},
        "tasks": {"me": {"base": 150}, "opp": {"base": opp_task, "claimed": []}},
        "trajectory": {"opponent": {"freshnessEnd": opp_fresh_end,
                                    "goodFruitEnd": opp_good_end,
                                    "iceUsed": opp_ice or [], "nodeEnd": "S15"}},
        "opponentInteraction": {"oppGuards": opp_guards, "windows": [],
                                "bounties": [], "myGuards": []},
        "classification": {"luckClass": "expected_loss", "segments": ["delivered"]},
    }


class TestClassify(unittest.TestCase):
    def test_guard_type_when_opp_guards_nonempty(self):
        r = _report(opp_fresh_end=90.0, opp_good_end=99,
                    opp_guards=[{"node": "S10", "frame": 200, "defense": 3}])
        self.assertEqual(classify_opponent(r)["class"], CLASS_GUARD)

    def test_quality_route_high_freshness_with_ice(self):
        r = _report(opp_fresh_end=88.0, opp_good_end=90, opp_ice=[340])
        # freshnessEnd≥85 且 iceUsed 非空 → quality（goodFruit<95 但有冰）
        self.assertEqual(classify_opponent(r)["class"], CLASS_QUALITY)

    def test_quality_route_high_freshness_high_good(self):
        r = _report(opp_fresh_end=92.0, opp_good_end=99)
        self.assertEqual(classify_opponent(r)["class"], CLASS_QUALITY)

    def test_speed_route_low_freshness(self):
        r = _report(opp_fresh_end=70.0, opp_good_end=80)
        self.assertEqual(classify_opponent(r)["class"], CLASS_SPEED)

    def test_speed_route_freshness_below_threshold(self):
        # freshnessEnd=84 < 85 → speed
        r = _report(opp_fresh_end=84.0, opp_good_end=99)
        self.assertEqual(classify_opponent(r)["class"], CLASS_SPEED)

    def test_guard_overrides_quality(self):
        # 即使满足 quality 条件，有设卡 → guard-type
        r = _report(opp_fresh_end=92.0, opp_good_end=99,
                    opp_guards=[{"node": "S10", "frame": 200, "defense": 3}])
        self.assertEqual(classify_opponent(r)["class"], CLASS_GUARD)

    def test_unknown_when_no_opp_fields(self):
        r = _report(opp_fresh_end=None, opp_good_end=None, opp_guards=[])
        self.assertEqual(classify_opponent(r)["class"], CLASS_UNKNOWN)

    def test_signals_populated(self):
        r = _report(opp_fresh_end=88.0, opp_good_end=99, opp_ice=[340],
                    opp_guards=[{"node": "S10"}], opp_deliver=557, opp_task=165)
        sig = classify_opponent(r)["signals"]
        self.assertEqual(sig["freshnessEnd"], 88.0)
        self.assertEqual(sig["goodFruitEnd"], 99)
        self.assertEqual(sig["iceUsedCount"], 1)
        self.assertEqual(sig["oppGuardCount"], 1)
        self.assertEqual(sig["oppDeliverFrame"], 557)
        self.assertEqual(sig["oppTaskBase"], 165)


class TestAnnotate(unittest.TestCase):
    def test_annotate_injects_into_classification(self):
        r = _report(opp_fresh_end=92.0, opp_good_end=99)
        annotate_opp_class(r)
        self.assertEqual(r["classification"]["opponentClass"], CLASS_QUALITY)
        self.assertIn("oppClassSignals", r["classification"])

    def test_annotate_idempotent(self):
        r = _report(opp_fresh_end=92.0, opp_good_end=99)
        annotate_opp_class(r)
        annotate_opp_class(r)
        self.assertEqual(r["classification"]["opponentClass"], CLASS_QUALITY)

    def test_index_entry_carries_opponent_class(self):
        r = _report(opp_fresh_end=70.0, opp_good_end=80)
        idx = A.build_index([r])
        self.assertEqual(idx[0]["opponentClass"], CLASS_SPEED)


class TestBucketSection(unittest.TestCase):
    def test_section_lists_each_class_with_winrate(self):
        reports = [
            _report("g1", outcome="WIN", opp_fresh_end=92, opp_good_end=99),   # quality, WIN
            _report("g2", outcome="LOSS", opp_fresh_end=92, opp_good_end=99),  # quality, LOSS
            _report("g3", outcome="WIN", opp_fresh_end=70, opp_good_end=80),   # speed, WIN
            _report("g4", outcome="LOSS", opp_fresh_end=70, opp_good_end=80,
                    opp_guards=[{"node": "S10"}]),                              # guard, LOSS
        ]
        for r in reports:
            annotate_opp_class(r)
        section = A._opp_class_section(reports)
        # 三类各出现一次，含 N 与胜率
        self.assertIn("guard-type", section)
        self.assertIn("quality-route", section)
        self.assertIn("speed-route", section)
        # quality N=2 W=0.5
        self.assertIn("quality-route (N=2): W 0.50", section)
        # 跨类归因一句话
        self.assertIn("归因", section)

    def test_section_handles_unknown_only(self):
        r = _report(opp_fresh_end=None, opp_good_end=None, opp_guards=[])
        annotate_opp_class(r)
        section = A._opp_class_section([r])
        self.assertIn(CLASS_UNKNOWN, section)

    def test_analysis_report_contains_bucket_header(self):
        r = _report(opp_fresh_end=92, opp_good_end=99)
        annotate_opp_class(r)
        md = A.build_analysis_report([r])
        self.assertIn("## 对手类分桶", md)
        self.assertIn("quality-route", md)


if __name__ == "__main__":
    unittest.main()

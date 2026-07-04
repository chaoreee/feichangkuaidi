"""`analysis.aggregator` 单测——跨局统计 / 场景分段 / 运气分类 / 异常局标记 /
seed 配对 A/B + CI + 分段回归 + `rules.py` 对账自检。
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)  # 让 analysis 包可导入；aggregator 自行把 client 加入 path
sys.path.insert(0, os.path.join(_ROOT, "client"))

from analysis import aggregator as A  # noqa: E402
from core import rules  # noqa: E402


def _report(match_id="m1", outcome="WIN", variant="baseline", seed=None, source="sim",
            me_total=685, me_task=90, me_good=92, me_fresh=78.0, deliver_frame=470,
            opp_total=0, opp_delivered=False, me_delivered=True,
            segments=("delivered", "task90_reached"), luck="expected_win",
            proj_error=None, waiting_stuck=(), rejected=(),
            me_bounty=0, me_penalty=0):
    """构造一份合法 Report（schemaVersion=1）。me_total 默认对账自洽。"""
    return {
        "schemaVersion": 1,
        "matchId": match_id, "playerId": 1001, "teamId": "RED",
        "seed": seed, "source": source, "variant": variant, "durationRound": 600,
        "outcome": outcome,
        "finalScore": {"me": {"total": me_total, "delivery": None, "task": None,
                              "time": None, "goodFruit": None, "freshness": None,
                              "bounty": me_bounty, "penalty": me_penalty},
                       "opp": {"total": opp_total, "delivery": None, "task": None,
                               "time": None, "goodFruit": None, "freshness": None,
                               "bounty": 0, "penalty": 0}},
        "delivery": {"me": {"frame": deliver_frame, "verifyFrame": 463,
                            "goodFruit": me_good, "freshness": me_fresh},
                     "opp": {"frame": 488 if opp_delivered else None},
                     "rushTriggerFrame": 450},
        "tasks": {"me": {"base": me_task,
                         "milestones": [60, 90] if me_task >= 90 else ([60] if me_task >= 60 else []),
                         "claimed": []},
                  "opp": {"base": 60, "milestones": [60], "claimed": []},
                  "missedReachable90": None},
        "resources": {"iceUsed": [], "horseUsed": None, "rushTactic": None},
        "trajectory": {"freshness": {"start": 100.0, "end": me_fresh, "min": me_fresh},
                       "goodFruit": {"start": 100, "end": me_good, "badCrossings": []}},
        "opponentInteraction": {"windows": [], "oppGuards": [], "bounties": [], "myGuards": []},
        "failures": {"rejected": list(rejected), "waitingStuck": list(waiting_stuck),
                     "invalidActions": 0, "decisionTimeouts": 0, "canAffordBlocked": []},
        "projection": {"modeSwitches": [],
                       "confidence": {"min": 0.3, "median": 0.6, "max": 0.8},
                       "projectedMyScore": 700.0, "actualMyScore": me_total,
                       "error": proj_error, "oppEtaPredictedDeliver": 485,
                       "oppActualDeliver": 488 if opp_delivered else None},
        "classification": {"scoreMargin": me_total - opp_total,
                           "luckClass": luck, "segments": list(segments)},
        "decisionTimeline": [],
    }


class TestReconcile(unittest.TestCase):
    def _expected_total(self, task=90, good=92, fresh=78.0, frame=470, bounty=0, penalty=0):
        comps = [rules.delivery_base_score(task), rules.good_fruit_score(good),
                 rules.freshness_score(fresh), rules.time_score(frame, task),
                 rules.task_score(task, delivered=True), bounty]
        return max(0, sum(comps) - penalty)

    def test_matching_report_passes(self):
        total = self._expected_total()
        r = _report(me_total=total)
        ok, err, note = A.reconcile(r)
        self.assertTrue(ok)
        self.assertIsNone(note)
        self.assertAlmostEqual(err, 0, delta=1.5)

    def test_mismatch_flagged(self):
        total = self._expected_total()
        r = _report(me_total=total + 50)
        ok, err, note = A.reconcile(r)
        self.assertFalse(ok)
        self.assertAlmostEqual(err, -50, delta=1.5)

    def test_stub_total_skipped(self):
        r = _report(me_total=0)
        ok, err, note = A.reconcile(r)
        self.assertEqual(note, "no_real_score")


class TestSegments(unittest.TestCase):
    def test_segment_block_reports_each_segment(self):
        reports = [
            _report(match_id="w1", segments=["delivered", "task90_reached", "mid_lead", "opp_delivered"]),
            _report(match_id="w2", outcome="UNDELIVERED", me_total=0,
                    segments=["undelivered", "task90_missed", "mid_trail", "opp_delivered"]),
        ]
        block = A.segment_block(reports)
        self.assertIn("delivered", block)
        self.assertIn("undelivered", block)
        self.assertIn("task90_reached", block)
        self.assertIn("mid_trail", block)


class TestAnomalyFlagging(unittest.TestCase):
    def test_undelivered_flagged(self):
        reports = [_report(match_id="u", outcome="UNDELIVERED", me_total=0, segments=["undelivered"])]
        flagged = A.flag_anomalies(reports)
        self.assertEqual(len(flagged), 1)
        self.assertIn("UNDELIVERED", flagged[0][1])

    def test_waiting_stuck_flagged(self):
        reports = [_report(match_id="s", waiting_stuck=[{"fromFrame": 140, "toFrame": 160, "node": "S14"}])]
        self.assertEqual(len(A.flag_anomalies(reports)), 1)

    def test_proj_error_flagged(self):
        reports = [_report(match_id="p", proj_error=58.0)]
        self.assertEqual(len(A.flag_anomalies(reports)), 1)

    def test_loss_task_below_90_flagged(self):
        reports = [_report(match_id="l", outcome="LOSS", me_total=645, me_task=60,
                           opp_total=700, opp_delivered=True,
                           segments=["delivered", "task90_missed", "opp_delivered"])]
        flagged = A.flag_anomalies(reports)
        self.assertEqual(len(flagged), 1)
        self.assertTrue(any("task<90" in r for r in flagged[0][1]))

    def test_clean_win_not_flagged(self):
        reports = [_report(match_id="ok", proj_error=5.0)]
        self.assertEqual(len(A.flag_anomalies(reports)), 0)


class TestLuckTally(unittest.TestCase):
    def test_tally(self):
        reports = [_report(match_id="1", luck="expected_win"),
                   _report(match_id="2", luck="expected_win"),
                   _report(match_id="3", luck="unlucky_loss"),
                   _report(match_id="4", luck="lucky_win")]
        self.assertEqual(A.luck_tally(reports),
                         {"expected_win": 2, "unlucky_loss": 1, "lucky_win": 1})


class TestABPairing(unittest.TestCase):
    def _pair_set(self, n, baseline_score=700, variant_score=720):
        reps = []
        for s in range(n):
            reps.append(_report(match_id="b%d" % s, variant="baseline", seed=s, me_total=baseline_score))
            reps.append(_report(match_id="v%d" % s, variant="tuned", seed=s, me_total=variant_score))
        return reps

    def test_pairs_by_seed(self):
        reps = self._pair_set(5)
        result = A.ab_pair(reps)
        self.assertIsNotNone(result)
        _b, _v, pairs = result
        self.assertEqual(len(pairs), 5)

    def test_ab_report_low_sample_note(self):
        text = A.ab_report(self._pair_set(5))
        self.assertIsNotNone(text)
        self.assertIn("假设级", text)
        self.assertIn("tuned", text)

    def test_ab_report_sufficient_sample(self):
        self.assertIn("达 A/B 门槛", A.ab_report(self._pair_set(35)))

    def test_ab_report_mean_diff_and_ci(self):
        text = A.ab_report(self._pair_set(35, baseline_score=700, variant_score=730))
        self.assertIn("diff +30.0", text)
        self.assertIn("95% CI", text)

    def test_segment_regression_flagged(self):
        reps = []
        for s in range(35):
            reps.append(_report(match_id="b%d" % s, variant="baseline", seed=s, me_total=790,
                                segments=["delivered", "task90_reached"]))
            reps.append(_report(match_id="v%d" % s, variant="tuned", seed=s, me_total=760,
                                segments=["delivered", "task90_reached"]))
        text = A.ab_report(reps)
        self.assertIn("SEGMENT REGRESSION", text)
        self.assertIn("task90_reached", text)

    def test_no_variants_returns_none(self):
        self.assertIsNone(A.ab_report([_report(match_id="x", variant="baseline", seed=1)]))


class TestBuildAnalysisReport(unittest.TestCase):
    def test_main_report_sections(self):
        reports = [
            _report(match_id="w1", me_total=685, opp_total=600, opp_delivered=True),
            _report(match_id="w2", outcome="UNDELIVERED", me_total=0,
                    segments=["undelivered", "task90_missed"]),
        ]
        md = A.build_analysis_report(reports)
        for section in ("WIN_RATE", "DELIVERY_RATE", "MEAN_SCORE", "DELIVERY_FRAME",
                        "TASK_90_REACH", "PROJ_ERROR", "运气分类", "场景分段",
                        "对账自检", "异常局标记"):
            self.assertIn(section, md)

    def test_main_report_includes_recon_summary(self):
        total = (rules.delivery_base_score(90) + rules.good_fruit_score(92)
                 + rules.freshness_score(78.0) + rules.time_score(470, 90)
                 + rules.task_score(90, delivered=True))
        md = A.build_analysis_report([_report(match_id="ok", me_total=total, me_task=90)])
        self.assertIn("ok=1", md)


class TestIndexAndTimelines(unittest.TestCase):
    def test_build_index_fields_and_reportpath(self):
        rs = [_report(match_id="m1", outcome="WIN", luck="expected_win", seed=11,
                      segments=("delivered", "task90_reached")),
              _report(match_id="m2", outcome="LOSS", luck="unlucky_loss", seed=12,
                      me_total=400, me_task=70,
                      segments=("delivered", "task90_missed"))]
        idx = A.build_index(rs, report_relpath=lambda mid: "reports/%s.report.json" % mid)
        self.assertEqual(len(idx), 2)
        e = next(x for x in idx if x["matchId"] == "m1")
        self.assertEqual(e["outcome"], "WIN")
        self.assertEqual(e["luckClass"], "expected_win")
        self.assertEqual(e["seed"], 11)
        self.assertEqual(e["reportPath"], "reports/m1.report.json")
        self.assertIn("task90_reached", e["segments"])

    def test_build_timelines_for_anomaly_only(self):
        # WIN expected_win 非异常 → 不入 timelines；unlucky_loss 入。
        normal = _report(match_id="ok", outcome="WIN", luck="expected_win")
        anomaly = _report(match_id="bad", outcome="LOSS", luck="unlucky_loss",
                          me_total=400, me_task=70,
                          segments=("delivered", "task90_missed"),
                          proj_error=-80)
        anomaly["decisionTimeline"] = [
            {"frame": 120, "event": "TASK_CLAIM", "detail": "TK2"},
            {"frame": 290, "event": "BREAKTHROUGH", "detail": "CLEAR S14 cost 1"},
            {"frame": 450, "event": "RUSH_TACTIC", "detail": "RUSH_SPEED"},
        ]
        md = A.build_timelines([normal, anomaly])
        self.assertIsNotNone(md)
        self.assertIn("matchId=bad", md)
        self.assertNotIn("matchId=ok", md)
        self.assertIn("r120 TASK", md)
        self.assertIn("r290 BREAK", md)
        self.assertIn("r450 RUSH", md)

    def test_build_timelines_none_when_no_anomaly(self):
        rs = [_report(match_id="ok", outcome="WIN", luck="expected_win")]
        self.assertIsNone(A.build_timelines(rs))


if __name__ == "__main__":
    unittest.main()

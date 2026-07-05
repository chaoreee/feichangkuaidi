"""`analysis.aggregator` 单测——跨局统计 / 场景分段 / 运气分类 / 异常局标记 /
seed 配对 A/B + CI + 分段回归 + `rules.py` 对账自检。
"""

import math
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
            me_bounty=0, me_penalty=0, client_version="iter36"):
    """构造一份合法 Report（schemaVersion=1）。me_total 默认对账自洽。"""
    return {
        "schemaVersion": 1,
        "matchId": match_id, "playerId": 1001, "teamId": "RED",
        "seed": seed, "source": source, "variant": variant, "durationRound": 600,
        "clientVersion": client_version,
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


def _opp_report(match_id="m1", opp_components=None, opp_guards=None,
                blocked_me_frames=0, opp_ice=0, opp_fresh_min=None, opp_fresh_end=None):
    """构造带 P1-A 对手分项/设卡/资源的 Report。"""
    r = _report(match_id=match_id, me_total=755, opp_total=760, opp_delivered=True,
                me_task=90, me_good=97, me_fresh=79.0, deliver_frame=452)
    if opp_components:
        r["finalScore"]["opp"].update(opp_components)
    if opp_guards is not None:
        r["opponentInteraction"]["oppGuards"] = opp_guards
    if blocked_me_frames:
        r["failures"]["rejected"] = [
            {"frame": 300 + i, "action": "MOVE", "code": "MOVE_BLOCKED_BY_GUARD",
             "target": "S10"} for i in range(blocked_me_frames)]
    r["trajectory"]["opponent"] = {
        "freshnessEnd": opp_fresh_end, "freshnessMin": opp_fresh_min,
        "goodFruitEnd": 98, "badFruitEnd": 0, "nodeEnd": "S15",
        "verifyFrame": None,
        "iceUsed": [{"frame": 200, "from": 2, "to": 1} for _ in range(opp_ice)],
        "frames": []}
    return r


class TestOppStatsP1A(unittest.TestCase):
    def test_opp_score_components(self):
        reps = [
            _opp_report(match_id="a", opp_components={"delivery": 240, "task": 60,
                      "time": 20, "goodFruit": 98, "freshness": 88.0, "bounty": 0}),
            _opp_report(match_id="b", opp_components={"delivery": 240, "task": 90,
                      "time": 16, "goodFruit": 99, "freshness": 92.0, "bounty": 0}),
        ]
        comps, n = A.opp_score_components(reps)
        self.assertEqual(n, 2)
        self.assertAlmostEqual(comps["freshness"], 90.0, delta=0.1)
        self.assertAlmostEqual(comps["task"], 75.0, delta=0.1)
        self.assertEqual(comps["delivery"], 240.0)

    def test_opp_score_components_legacy_skipped(self):
        # 旧 trace 无分项 → n=0
        reps = [_report(match_id="legacy")]
        comps, n = A.opp_score_components(reps)
        self.assertEqual(n, 0)
        self.assertEqual(comps["delivery"], 0.0)

    def test_opp_guard_stats(self):
        reps = [
            _opp_report(match_id="g1", opp_guards=[{"node": "S10", "frame": 100}],
                        blocked_me_frames=5),
            _opp_report(match_id="g2", opp_guards=[], blocked_me_frames=0),
            _opp_report(match_id="g3",
                        opp_guards=[{"node": "S07", "frame": 200},
                                    {"node": "S10", "frame": 300}],
                        blocked_me_frames=3),
        ]
        ep, games, blocked = A.opp_guard_stats(reps)
        self.assertEqual(ep, 3)  # 1 + 0 + 2
        self.assertEqual(games, 2)  # g1, g3
        self.assertEqual(blocked, 8)  # 5 + 0 + 3

    def test_opp_section_in_analysis_report(self):
        reps = [_opp_report(match_id="x",
                            opp_components={"delivery": 240, "task": 60, "time": 20,
                                            "goodFruit": 98, "freshness": 88.0, "bounty": 0},
                            opp_guards=[{"node": "S10", "frame": 100}],
                            blocked_me_frames=4, opp_ice=2,
                            opp_fresh_min=85.0, opp_fresh_end=88.0)]
        md = A.build_analysis_report(reps)
        self.assertIn("对手分项与设卡（P1-A）", md)
        self.assertIn("OPP_SCORE_COMP", md)
        self.assertIn("OPP_GUARD: episodes=1", md)
        self.assertIn("blocked_me_frames=4", md)
        self.assertIn("OPP_ICE_USED: 2 total", md)
        self.assertIn("OPP_FRESHNESS", md)


class TestVersionAB(unittest.TestCase):
    """§3 真实对战版本 A/B（非配对两样本）。

    真实 trace seed=null 无法配对；老/新 client 各对随机对手池打→两独立样本。
    """

    def test_single_version_returns_none(self):
        reps = [_report(match_id="a", client_version="iter36", source="platform"),
                _report(match_id="b", client_version="iter36+abc", source="platform")]
        self.assertIsNone(A.version_ab_report(reps))  # 同 iter 归一化为一版

    def test_sim_filtered_out(self):
        # sim 源不入真实 A/B（走 ab_report seed 配对）
        reps = ([_report(match_id="o%d" % i, client_version="iter31", source="sim")
                 for i in range(35)] +
                [_report(match_id="n%d" % i, client_version="iter36", source="sim")
                 for i in range(35)])
        self.assertIsNone(A.version_ab_report(reps))

    def test_two_versions_emits_delta_and_ci(self):
        old = [_report(match_id="o%d" % i, client_version="iter31", source="platform",
                       me_total=755, me_fresh=80.0, me_good=97)
               for i in range(35)]
        new = [_report(match_id="n%d" % i, client_version="iter36+def", source="platform",
                       me_total=775, me_fresh=87.0, me_good=100)
               for i in range(35)]
        text = A.version_ab_report(old + new)
        self.assertIsNotNone(text)
        self.assertIn("iter31", text)
        self.assertIn("iter36", text)  # +def 已归一化
        self.assertIn("MEAN_SCORE", text)
        self.assertIn("WIN_RATE", text)
        self.assertIn("95% CI", text)
        self.assertIn("CONFOUND", text)

    def test_version_key_normalizes_git_hash(self):
        self.assertEqual(A._version_key({"clientVersion": "iter36+abc1234"}), "iter36")
        self.assertEqual(A._version_key({"clientVersion": "iter36-abc"}), "iter36")
        self.assertEqual(A._version_key({"clientVersion": "iter36"}), "iter36")
        self.assertEqual(A._version_key({}), "unknown")

    def test_low_sample_flag(self):
        old = [_report(match_id="o%d" % i, client_version="iter31", source="platform") for i in range(5)]
        new = [_report(match_id="n%d" % i, client_version="iter36", source="platform") for i in range(5)]
        text = A.version_ab_report(old + new)
        self.assertIn("假设级", text)

    def test_segment_regression_flagged(self):
        old = [_report(match_id="o%d" % i, client_version="iter31", source="platform", me_total=790,
                       segments=["delivered", "task90_reached"]) for i in range(35)]
        new = [_report(match_id="n%d" % i, client_version="iter36", source="platform", me_total=760,
                       segments=["delivered", "task90_reached"]) for i in range(35)]
        text = A.version_ab_report(old + new)
        self.assertIn("SEGMENT REGRESSION", text)
        self.assertIn("task90_reached", text)

    def test_welch_diff_ci(self):
        a = [700.0] * 20 + [760.0] * 20  # mean 730
        b = [750.0] * 40                  # mean 750
        diff, hw = A._welch_diff_ci(a, b)
        self.assertAlmostEqual(diff, -20.0, delta=0.01)
        self.assertGreater(hw, 0)
        self.assertFalse(math.isinf(hw))

    def test_rate_diff_ci(self):
        rs_a = [{"outcome": "WIN"}] * 14 + [{"outcome": "LOSS"}] * 6   # 0.7
        rs_b = [{"outcome": "WIN"}] * 6 + [{"outcome": "LOSS"}] * 14   # 0.3
        diff, hw = A._rate_diff_ci(rs_a, rs_b, lambda r: r.get("outcome") == "WIN")
        self.assertAlmostEqual(diff, 0.4, delta=0.01)
        self.assertFalse(math.isinf(hw))


if __name__ == "__main__":
    unittest.main()

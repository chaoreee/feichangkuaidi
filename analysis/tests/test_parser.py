"""`analysis.parser` 单测——把 client trace 日志解析为结构化 Report（schemaVersion=1）。

构造合成 trace 文本（与 `client/logger/match_logger.py` 输出格式一致），逐字段断言解析结果。
"""

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # analysis 包可导入

from analysis.parser import parse_log, SCHEMA_VERSION  # noqa: E402


def _fmt(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        s = "%.2f" % v
        return s.rstrip("0").rstrip(".") or "0"
    if isinstance(v, (list, tuple)):
        return "[%s]" % "|".join(str(x) for x in v)
    return str(v)


def _emit(event, round=None, **fields):
    parts = ["matchId=m"]
    if round is not None:
        parts.append("round=%s" % round)
    for k, v in fields.items():
        if v is None:
            continue
        parts.append("%s=%s" % (k, _fmt(v)))
    return "00:00:00.000 %s %s" % (event, ", ".join(parts))


def _write_log(lines):
    fh = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
    fh.write("\n".join(lines) + "\n")
    fh.close()
    return fh.name


class TestParseIdentityAndSchema(unittest.TestCase):
    def test_identity_and_seed(self):
        path = _write_log([
            _emit("Startup", playerId=1001, host="h", port=8081, version="1.0"),
            _emit("Start", teamId="RED", camp=0, durationRound=600, nodes=15, edges=21, seed=42),
            _emit("Over", resultType="NORMAL", overRound=48, winner=1001, iWon=True),
            _emit("Score", player=1001, me=True, total=672, delivered=True, deliverRound=48,
                  fresh=97.6, goodFruit=100, taskScore=60, bountyScore=0),
            _emit("Score", player=2002, me=False, total=0, delivered=False, deliverRound=0),
        ])
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(r["matchId"], "m")
        self.assertEqual(r["playerId"], 1001)
        self.assertEqual(r["teamId"], "RED")
        self.assertEqual(r["seed"], 42)
        self.assertEqual(r["durationRound"], 600)


class TestOutcome(unittest.TestCase):
    def _over_log(self, me_delivered=True, me_retired=False, winner=1001, iWon=True):
        return [
            _emit("Startup", playerId=1001),
            _emit("Over", resultType="NORMAL", overRound=48, winner=winner, iWon=iWon),
            _emit("Score", player=1001, me=True, total=672, delivered=me_delivered,
                  retired=me_retired, deliverRound=48 if me_delivered else 0,
                  fresh=97, goodFruit=100, taskScore=60, bountyScore=0),
            _emit("Score", player=2002, me=False, total=0, delivered=False),
        ]

    def test_win(self):
        path = _write_log(self._over_log())
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["outcome"], "WIN")

    def test_loss(self):
        path = _write_log(self._over_log(winner=2002, iWon=False))
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["outcome"], "LOSS")

    def test_tie(self):
        path = _write_log(self._over_log(winner=None, iWon=False))
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["outcome"], "TIE")

    def test_undelivered(self):
        path = _write_log(self._over_log(me_delivered=False, winner=2002, iWon=False))
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["outcome"], "UNDELIVERED")

    def test_retired(self):
        path = _write_log(self._over_log(me_delivered=False, me_retired=True, winner=2002, iWon=False))
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["outcome"], "RETIRED")


class TestTrajectoryAndDelivery(unittest.TestCase):
    def test_freshness_and_bad_crossings(self):
        lines = [_emit("Startup", playerId=1001)]
        seq = [(100, 100), (80, 100), (75, 100), (70, 100)]  # fresh 跨 90、80
        for i, (f, g) in enumerate(seq):
            lines.append(_emit("Frame", round=10 + i, phase="NORMAL", node="S02",
                               state="IDLE", fresh=f, goodFruit=g, taskScore=0,
                               verified=False, delivered=False))
        lines += [_emit("Over", winner=1001, iWon=True, overRound=20),
                  _emit("Score", me=True, total=1, delivered=True, deliverRound=20,
                        fresh=70, goodFruit=100, taskScore=0, bountyScore=0),
                  _emit("Score", me=False, total=0, delivered=False)]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        tr = r["trajectory"]["freshness"]
        self.assertEqual(tr["start"], 100)
        self.assertEqual(tr["end"], 70)
        self.assertEqual(tr["min"], 70)
        self.assertEqual(r["trajectory"]["goodFruit"]["badCrossings"], [90, 80])

    def test_verify_and_rush_trigger_frame(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Frame", round=40, phase="NORMAL", node="S14", state="IDLE",
                  fresh=98, goodFruit=100, taskScore=60, verified=False, delivered=False),
            _emit("Frame", round=42, phase="RUSH", node="S14", state="IDLE",
                  fresh=97, goodFruit=100, taskScore=60, verified=False, delivered=False),
            _emit("Frame", round=46, phase="RUSH", node="S14", state="IDLE",
                  fresh=96, goodFruit=100, taskScore=60, verified=True, delivered=False),
            _emit("Over", winner=1001, iWon=True, overRound=48),
            _emit("Score", me=True, total=672, delivered=True, deliverRound=48,
                  fresh=96, goodFruit=100, taskScore=60, bountyScore=0),
            _emit("Score", me=False, total=0, delivered=False),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["delivery"]["me"]["verifyFrame"], 46)
        self.assertEqual(r["delivery"]["me"]["frame"], 48)
        self.assertEqual(r["delivery"]["rushTriggerFrame"], 42)


class TestProjectionAndModeSwitch(unittest.TestCase):
    def test_mode_switch_and_confidence(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Frame", round=1, phase="NORMAL", node="S01", state="IDLE",
                  fresh=100, goodFruit=100, taskScore=0, verified=False, delivered=False),
            _emit("Projection", round=1, myScore=700, oppScore=655, gap=45, mode="EVEN",
                  myDeliver=470, oppDeliver=480, confidence=0.3),
            _emit("Projection", round=300, myScore=750, oppScore=700, gap=50, mode="EVEN",
                  myDeliver=470, oppDeliver=480, confidence=0.6),
            _emit("ModeChange", round=301, **{"from": "EVEN", "to": "CONSERVATIVE",
                                              "reason": "gap_above_threshold"}),
            _emit("Projection", round=301, myScore=760, oppScore=700, gap=60, mode="CONSERVATIVE",
                  myDeliver=470, oppDeliver=480, confidence=0.8),
            _emit("Over", winner=1001, iWon=True, overRound=470),
            _emit("Score", me=True, total=755, delivered=True, deliverRound=470,
                  fresh=78, goodFruit=92, taskScore=90, bountyScore=0),
            _emit("Score", me=False, total=740, delivered=True, deliverRound=480),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(r["projection"]["modeSwitches"]), 1)
        ms = r["projection"]["modeSwitches"][0]
        self.assertEqual(ms["from"], "EVEN")
        self.assertEqual(ms["to"], "CONSERVATIVE")
        self.assertEqual(r["projection"]["confidence"]["min"], 0.3)
        self.assertEqual(r["projection"]["confidence"]["max"], 0.8)
        self.assertEqual(r["projection"]["projectedMyScore"], 760.0)
        self.assertEqual(r["projection"]["oppEtaPredictedDeliver"], 480)
        self.assertEqual(r["projection"]["actualMyScore"], 755)
        self.assertAlmostEqual(r["projection"]["error"], 5.0, delta=0.1)
        self.assertEqual(r["classification"]["scoreMargin"], 15)


class TestActions(unittest.TestCase):
    def test_resource_rush_task_breakthrough_guard_window(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Frame", round=200, phase="NORMAL", node="S06", state="IDLE",
                  fresh=79, goodFruit=100, taskScore=0, verified=False, delivered=False),
            _emit("Action", round=200, action="USE_RESOURCE", resource="ICE_BOX"),
            _emit("Frame", round=150, phase="NORMAL", node="S05", state="IDLE",
                  fresh=80, goodFruit=100, taskScore=0, verified=False, delivered=False),
            _emit("Action", round=150, action="USE_RESOURCE", resource="FAST_HORSE"),
            _emit("Frame", round=455, phase="RUSH", node="S14", state="IDLE",
                  fresh=70, goodFruit=100, taskScore=60, verified=False, delivered=False),
            _emit("Action", round=455, action="RUSH_PROTECT"),
            _emit("Frame", round=21, phase="NORMAL", node="S09", state="IDLE",
                  fresh=99, goodFruit=100, taskScore=0, verified=False, delivered=False),
            _emit("Action", round=21, action="CLAIM_TASK", task="TK1"),
            _emit("Frame", round=300, phase="NORMAL", node="S10", state="IDLE",
                  fresh=95, goodFruit=100, taskScore=30, verified=False, delivered=False),
            _emit("Action", round=300, action="BREAK_GUARD", target="S10", good=1),
            _emit("Frame", round=310, phase="NORMAL", node="S07", state="IDLE",
                  fresh=94, goodFruit=99, taskScore=30, verified=False, delivered=False),
            _emit("Action", round=310, action="SET_GUARD", target="S07", extra=2),
            _emit("GuardDecision", round=310, target="S07", defense=4, gap=60, denial=6),
            _emit("Frame", round=125, phase="NORMAL", node="S03", state="IDLE",
                  fresh=98, goodFruit=100, taskScore=0, verified=False, delivered=False),
            _emit("Action", round=125, action="WINDOW_CARD", contest="C1",
                  contestType="TASK", card="BING_ZHENG"),
            _emit("Over", winner=1001, iWon=True, overRound=470),
            _emit("Score", me=True, total=700, delivered=True, deliverRound=470,
                  fresh=78, goodFruit=92, taskScore=90, bountyScore=0),
            _emit("Score", me=False, total=0, delivered=False),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        # 资源 / 急策
        self.assertEqual(len(r["resources"]["iceUsed"]), 1)
        self.assertEqual(r["resources"]["iceUsed"][0]["freshnessBefore"], 79.0)
        self.assertEqual(r["resources"]["horseUsed"], "FAST_HORSE@150")
        self.assertEqual(r["resources"]["rushTactic"], {"type": "RUSH_PROTECT", "frame": 455})
        # 任务领取（template 未知→None；node 取该帧 Frame 节点）
        self.assertEqual(r["tasks"]["me"]["claimed"][0]["node"], "S09")
        self.assertEqual(r["tasks"]["me"]["claimed"][0]["frame"], 21)
        # 突破（opp guard）
        self.assertEqual(r["opponentInteraction"]["oppGuards"][0]["node"], "S10")
        # 设卡 + GuardDecision 补 defense
        self.assertEqual(r["opponentInteraction"]["myGuards"][0]["defense"], 4)
        self.assertEqual(r["opponentInteraction"]["myGuards"][0]["denial"], 6)
        # 窗口
        self.assertEqual(r["opponentInteraction"]["windows"][0]["type"], "TASK")
        self.assertEqual(r["opponentInteraction"]["windows"][0]["myCard"], "BING_ZHENG")
        self.assertIn("contested", r["classification"]["segments"])
        # timeline 含关键事件
        events = [t["event"] for t in r["decisionTimeline"]]
        self.assertIn("TASK_CLAIM", events)
        self.assertIn("BREAKTHROUGH", events)


class TestRejectionAndCanAfford(unittest.TestCase):
    def test_rejected_and_can_afford_parsed(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Rejected", round=200, action="MOVE", code="MOVE_BLOCKED_BY_GUARD", target="S10"),
            _emit("CanAffordBlock", round=300, action="DETOUR_TASK", reason="time", target="S07"),
            _emit("Over", winner=1001, iWon=True, overRound=470),
            _emit("Score", me=True, total=700, delivered=True, deliverRound=470,
                  fresh=78, goodFruit=92, taskScore=90, bountyScore=0),
            _emit("Score", me=False, total=0, delivered=False),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(r["failures"]["rejected"]), 1)
        self.assertEqual(r["failures"]["rejected"][0]["code"], "MOVE_BLOCKED_BY_GUARD")
        self.assertEqual(len(r["failures"]["canAffordBlocked"]), 1)
        self.assertEqual(r["failures"]["canAffordBlocked"][0]["reason"], "time")


class TestWaitingStall(unittest.TestCase):
    def test_consecutive_waiting_recorded(self):
        lines = [_emit("Startup", playerId=1001)]
        for i in range(4):
            lines.append(_emit("Frame", round=140 + i, phase="NORMAL", node="S14",
                               state="WAITING", fresh=90, goodFruit=100, taskScore=60,
                               verified=False, delivered=False))
        lines.append(_emit("Frame", round=144, phase="NORMAL", node="S14", state="IDLE",
                           fresh=90, goodFruit=100, taskScore=60, verified=False, delivered=False))
        lines += [_emit("Over", winner=1001, iWon=True, overRound=470),
                  _emit("Score", me=True, total=700, delivered=True, deliverRound=470,
                        fresh=78, goodFruit=92, taskScore=60, bountyScore=0),
                  _emit("Score", me=False, total=0, delivered=False)]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        stuck = r["failures"]["waitingStuck"]
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0]["fromFrame"], 140)
        self.assertEqual(stuck[0]["node"], "S14")


class TestEdgeCases(unittest.TestCase):
    def test_empty_log_returns_none(self):
        path = _write_log([_emit("Startup", playerId=1001)])
        try:
            self.assertIsNone(parse_log(path))
        finally:
            os.unlink(path)

    def test_decision_timeout_counted_from_ms(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Action", round=5, action="MOVE", target="S02", ms=450.0),
            _emit("Over", winner=1001, iWon=True, overRound=470),
            _emit("Score", me=True, total=700, delivered=True, deliverRound=470,
                  fresh=78, goodFruit=92, taskScore=90, bountyScore=0),
            _emit("Score", me=False, total=0, delivered=False),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["failures"]["decisionTimeouts"], 1)


if __name__ == "__main__":
    unittest.main()

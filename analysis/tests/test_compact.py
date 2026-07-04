"""`analysis.compact` 单测——精简 trace 派生与还原（P1-B）。

构造合成完整 trace（与 `client/logger/match_logger.py` 输出格式一致），验证：
1. `compact_trace` → `parse_compact` 与 `parse_log` 关键字段 0 误差（roundtrip）。
2. 精简纯文本 < 10KB/局（回归保护，防膨胀）。
3. 连续相同拒绝合并为 1 行 `REJ x<n>`，`parse_compact` 还原计数。
4. 旧 trace（无 P1-A 富化字段）→ 精简格式优雅降级。
"""

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # analysis 包可导入

from analysis.compact import compact_trace, parse_compact, to_b64, from_b64  # noqa: E402
from analysis.parser import parse_log  # noqa: E402


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


def _full_trace():
    """构造一局含鲜活度跨越/任务/冰鉴/拒绝/等待/结算的完整 trace。"""
    lines = [
        _emit("Startup", playerId=1001, host="h", port=8081, version="iter30+abc1234"),
        _emit("Start", teamId="RED", camp=0, durationRound=600, nodes=15, edges=21, seed=42),
        _emit("Map", nodes=["S01:START", "S02:CHECKPOINT", "S10:KEY_PASS", "S14:GATE", "S15:FINISH"],
              edges=["S01-S02:30:ROAD", "S02-S10:40:ROAD", "S10-S14:36:ROAD", "S14-S15:10:ROAD"],
              tasks=["S02:t1:20"]),
        _emit("Ready", round=1),
        # r1 初始
        _emit("Frame", round=1, phase="NORMAL", node="S01", state="IDLE", fresh=100,
              goodFruit=100, taskScore=0, verified=False, delivered=False,
              oppNode="S01", oppState="IDLE", oppFresh=100, oppGood=100, oppTask=0),
        _emit("Projection", round=1, myScore=428, oppScore=428, gap=0, mode="EVEN",
              myDeliver=416, oppDeliver=416, confidence=0.3),
        _emit("Eta", round=1, oppFrom="S02", toGate=396, toFinish=416, verified=False, conf=0.3),
        _emit("Action", round=1, action="MOVE", target="S02", fresh=100, goodFruit=100, gap=0),
        # r2 移动中
        _emit("Frame", round=2, phase="NORMAL", node="S01", state="MOVING", fresh=99.9,
              goodFruit=100, taskScore=0, verified=False, delivered=False,
              oppNode="S01", oppState="MOVING", oppFresh=99.9, oppGood=100, oppTask=0),
        _emit("Projection", round=2, myScore=428, oppScore=428, gap=0, mode="EVEN",
              myDeliver=417, oppDeliver=417, confidence=0.31),
        _emit("Eta", round=2, oppFrom="S02", toGate=395, toFinish=415, verified=False, conf=0.31),
        _emit("Action", round=2, action="MOVE", target="S02", fresh=99.9, goodFruit=100, gap=0),
    ]
    # r3..r30 移动（鲜度从 99.9 线性下降，跨 90 在 r~110；这里快进到关键帧）
    for r in range(3, 31):
        fresh = round(100 - 0.1 * (r - 1), 2)
        lines.append(_emit("Frame", round=r, phase="NORMAL", node="S01", state="MOVING",
                           fresh=fresh, goodFruit=100, taskScore=0, verified=False, delivered=False,
                           oppNode="S01", oppState="MOVING", oppFresh=fresh, oppGood=100, oppTask=0))
        lines.append(_emit("Projection", round=r, myScore=428, oppScore=428, gap=0, mode="EVEN",
                           myDeliver=417 + r - 1, oppDeliver=417 + r - 1, confidence=0.31))
        lines.append(_emit("Eta", round=r, oppFrom="S02", toGate=395 - (r - 2),
                           toFinish=415 - (r - 2), verified=False, conf=0.31))
        lines.append(_emit("Action", round=r, action="MOVE", target="S02", fresh=fresh,
                           goodFruit=100, gap=0))
    # r31 到站 S02，领任务
    lines += [
        _emit("Frame", round=31, phase="NORMAL", node="S02", state="IDLE", fresh=97.0,
              goodFruit=100, taskScore=0, verified=False, delivered=False,
              oppNode="S02", oppState="IDLE", oppFresh=97.0, oppGood=100, oppTask=0),
        _emit("Projection", round=31, myScore=428, oppScore=428, gap=0, mode="EVEN",
              myDeliver=446, oppDeliver=446, confidence=0.32),
        _emit("Action", round=31, action="CLAIM_TASK", task="TK1", fresh=97.0, goodFruit=100, gap=0),
        # r32 处理中
        _emit("Frame", round=32, phase="NORMAL", node="S02", state="PROCESSING", fresh=96.9,
              goodFruit=100, taskScore=0, verified=False, delivered=False,
              oppNode="S02", oppState="PROCESSING", oppFresh=96.9, oppGood=100, oppTask=0),
        _emit("Action", round=32, action="MOVE", target="S02", fresh=96.9, goodFruit=100, gap=0),
        # r35 处理完，task 分到 20，天气命中
        _emit("Frame", round=35, phase="NORMAL", node="S02", state="IDLE", fresh=96.6,
              goodFruit=100, taskScore=20, verified=False, delivered=False,
              oppNode="S02", oppState="IDLE", oppFresh=96.6, oppGood=100, oppTask=20, weather="HOT"),
        _emit("Action", round=35, action="MOVE", target="S10", fresh=96.6, goodFruit=100, gap=0),
        # r200 鲜度跨 90 → 89.5
        _emit("Frame", round=200, phase="NORMAL", node="S02", state="MOVING", fresh=89.5,
              goodFruit=99, taskScore=20, verified=False, delivered=False,
              oppNode="S02", oppState="MOVING", oppFresh=89.5, oppGood=99, oppTask=20),
        _emit("Projection", round=200, myScore=470, oppScore=470, gap=0, mode="EVEN",
              myDeliver=446, oppDeliver=446, confidence=0.5),
        _emit("Action", round=200, action="MOVE", target="S10", fresh=89.5, goodFruit=99, gap=0),
        # r250 用冰鉴
        _emit("Frame", round=250, phase="NORMAL", node="S02", state="MOVING", fresh=85.0,
              goodFruit=99, taskScore=20, verified=False, delivered=False,
              oppNode="S02", oppState="MOVING", oppFresh=85.0, oppGood=99, oppTask=20),
        _emit("Action", round=250, action="USE_RESOURCE", resource="ICE_BOX", fresh=85.0,
              goodFruit=99, gap=0),
        # r300 中局 gap=-25（落后）
        _emit("Frame", round=300, phase="NORMAL", node="S10", state="MOVING", fresh=82.0,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=88.0, oppGood=99, oppTask=40),
        _emit("Projection", round=300, myScore=700, oppScore=725, gap=-25, mode="CONSERVATIVE",
              myDeliver=460, oppDeliver=440, confidence=0.6),
        _emit("Eta", round=300, oppFrom="S10", toGate=120, toFinish=140, verified=False, conf=0.6),
        _emit("ModeChange", round=300, reason="gap_collapse", **{"from": "EVEN", "to": "CONSERVATIVE"}),
        _emit("Action", round=300, action="MOVE", target="S14", fresh=82.0, goodFruit=98, gap=-25),
        # r310-313 等待停滞 4 帧（>=3 触发 waitingStuck）
        _emit("Frame", round=310, phase="NORMAL", node="S10", state="WAITING", fresh=81.5,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=87.5, oppGood=99, oppTask=40),
        _emit("Action", round=310, action="MOVE", target="S14", fresh=81.5, goodFruit=98, gap=-25),
        _emit("Frame", round=311, phase="NORMAL", node="S10", state="WAITING", fresh=81.4,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=87.4, oppGood=99, oppTask=40),
        _emit("Action", round=311, action="MOVE", target="S14", fresh=81.4, goodFruit=98, gap=-25),
        _emit("Frame", round=312, phase="NORMAL", node="S10", state="WAITING", fresh=81.3,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=87.3, oppGood=99, oppTask=40),
        _emit("Action", round=312, action="MOVE", target="S14", fresh=81.3, goodFruit=98, gap=-25),
        _emit("Frame", round=313, phase="NORMAL", node="S10", state="WAITING", fresh=81.2,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=87.2, oppGood=99, oppTask=40),
        _emit("Action", round=313, action="MOVE", target="S14", fresh=81.2, goodFruit=98, gap=-25),
        # r314 恢复移动
        _emit("Frame", round=314, phase="NORMAL", node="S10", state="MOVING", fresh=81.1,
              goodFruit=98, taskScore=20, verified=False, delivered=False,
              oppNode="S10", oppState="MOVING", oppFresh=87.1, oppGood=99, oppTask=40),
        _emit("Action", round=314, action="MOVE", target="S14", fresh=81.1, goodFruit=98, gap=-25),
        # r400 鲜度跨 80
        _emit("Frame", round=400, phase="NORMAL", node="S14", state="MOVING", fresh=79.5,
              goodFruit=97, taskScore=20, verified=False, delivered=False,
              oppNode="S14", oppState="MOVING", oppFresh=82.0, oppGood=98, oppTask=60),
        _emit("Projection", round=400, myScore=740, oppScore=745, gap=-5, mode="EVEN",
              myDeliver=450, oppDeliver=445, confidence=0.7),
        _emit("Action", round=400, action="MOVE", target="S15", fresh=79.5, goodFruit=97, gap=-5),
        # r440 验核
        _emit("Frame", round=440, phase="NORMAL", node="S14", state="IDLE", fresh=78.0,
              goodFruit=97, taskScore=20, verified=True, delivered=False,
              oppNode="S14", oppState="IDLE", oppFresh=80.0, oppGood=98, oppTask=60),
        _emit("Action", round=440, action="MOVE", target="S15", fresh=78.0, goodFruit=97, gap=-5),
        # r452 交付 + RUSH
        _emit("Frame", round=452, phase="RUSH", node="S15", state="IDLE", fresh=77.5,
              goodFruit=97, taskScore=20, verified=True, delivered=True,
              oppNode="S15", oppState="IDLE", oppFresh=79.0, oppGood=98, oppTask=60),
        _emit("Projection", round=452, myScore=758, oppScore=752, gap=6, mode="CONSERVATIVE",
              myDeliver=452, oppDeliver=455, confidence=0.9),
        _emit("Action", round=452, action="MOVE", target="S15", fresh=77.5, goodFruit=97, gap=6),
        # 结算
        _emit("Over", resultType="NORMAL", reason="ALL_DELIVERED", overRound=452, winner=1001, iWon=True),
        _emit("Score", player=1001, me=True, total=758, delivered=True, deliverRound=452,
              fresh=77.5, goodFruit=97, taskScore=20, bountyScore=0,
              scoreDetail=["delivery=240", "tasks=20", "time=30", "goodFruit=97",
                           "freshness=77.5", "bounty=0", "penalty=0", "total=758"]),
        _emit("Score", player=2002, me=False, total=752, delivered=True, deliverRound=455,
              fresh=79.0, goodFruit=98, taskScore=60, bountyScore=0,
              scoreDetail=["delivery=240", "tasks=60", "time=20", "goodFruit=98",
                           "freshness=79", "bounty=0", "penalty=0", "total=752"]),
    ]
    return lines


def _write_log(lines):
    fh = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False, encoding="utf-8")
    fh.write("\n".join(lines) + "\n")
    fh.close()
    return fh.name


class TestRoundtrip(unittest.TestCase):
    def test_roundtrip(self):
        lines = _full_trace()
        path = _write_log(lines)
        try:
            r_log = parse_log(path)
            ctext = compact_trace(lines)  # 直接传文本（list of lines）
            r_cp = parse_compact(ctext)
        finally:
            os.unlink(path)
        self.assertIsNotNone(r_log)
        self.assertIsNotNone(r_cp)
        # 关键字段 0 误差
        self.assertEqual(r_cp["matchId"], r_log["matchId"])
        self.assertEqual(r_cp["outcome"], r_log["outcome"])
        self.assertEqual(r_cp["finalScore"]["me"]["total"], r_log["finalScore"]["me"]["total"])
        self.assertEqual(r_cp["finalScore"]["opp"]["total"], r_log["finalScore"]["opp"]["total"])
        self.assertEqual(r_cp["finalScore"]["me"]["bounty"], r_log["finalScore"]["me"]["bounty"])
        self.assertEqual(r_cp["finalScore"]["opp"]["bounty"], r_log["finalScore"]["opp"]["bounty"])
        # P1-A scoreDetail 透传：分项分 round-trip 0 误差（compact 经 det= 还原）
        for who in ("me", "opp"):
            for k in ("delivery", "task", "time", "goodFruit", "freshness"):
                self.assertEqual(r_cp["finalScore"][who][k], r_log["finalScore"][who][k],
                                 "scoreDetail %s.%s mismatch" % (who, k))
        self.assertEqual(r_cp["delivery"]["me"]["frame"], r_log["delivery"]["me"]["frame"])
        self.assertEqual(r_cp["delivery"]["me"]["verifyFrame"], r_log["delivery"]["me"]["verifyFrame"])
        self.assertEqual(r_cp["delivery"]["me"]["freshness"], r_log["delivery"]["me"]["freshness"])
        self.assertEqual(r_cp["delivery"]["me"]["goodFruit"], r_log["delivery"]["me"]["goodFruit"])
        self.assertEqual(r_cp["delivery"]["opp"]["frame"], r_log["delivery"]["opp"]["frame"])
        self.assertEqual(r_cp["delivery"]["rushTriggerFrame"], r_log["delivery"]["rushTriggerFrame"])
        # 对手交互
        self.assertEqual(r_cp["opponentInteraction"]["oppGuards"], r_log["opponentInteraction"]["oppGuards"])
        self.assertEqual(r_cp["opponentInteraction"]["myGuards"], r_log["opponentInteraction"]["myGuards"])
        self.assertEqual(r_cp["opponentInteraction"]["windows"], r_log["opponentInteraction"]["windows"])
        self.assertEqual(r_cp["opponentInteraction"]["bounties"], r_log["opponentInteraction"]["bounties"])
        # 失败模式计数
        self.assertEqual(len(r_cp["failures"]["rejected"]), len(r_log["failures"]["rejected"]))
        self.assertEqual(len(r_cp["failures"]["waitingStuck"]), len(r_log["failures"]["waitingStuck"]))
        self.assertEqual(r_cp["failures"]["decisionTimeouts"], r_log["failures"]["decisionTimeouts"])
        self.assertEqual(len(r_cp["failures"]["canAffordBlocked"]),
                         len(r_log["failures"]["canAffordBlocked"]))
        # 轨迹
        self.assertEqual(r_cp["trajectory"]["freshness"], r_log["trajectory"]["freshness"])
        self.assertEqual(r_cp["trajectory"]["goodFruit"]["badCrossings"],
                         r_log["trajectory"]["goodFruit"]["badCrossings"])
        # 对手轨迹：compact 为有损视图，只对比 compact 能还原的标量字段
        # （frames/iceUsed/badFruitEnd/verifyFrame/freshnessMin 是 P1-A parser 侧富化，compact 不携带）
        for k in ("freshnessEnd", "goodFruitEnd", "nodeEnd"):
            self.assertEqual(r_cp["trajectory"]["opponent"][k],
                             r_log["trajectory"]["opponent"][k],
                             "trajectory.opponent.%s mismatch" % k)
        # 投影
        self.assertEqual(r_cp["projection"]["projectedMyScore"], r_log["projection"]["projectedMyScore"])
        self.assertEqual(r_cp["projection"]["oppEtaPredictedDeliver"],
                         r_log["projection"]["oppEtaPredictedDeliver"])
        self.assertEqual(r_cp["projection"]["modeSwitches"], r_log["projection"]["modeSwitches"])
        # 分类
        self.assertEqual(r_cp["classification"]["scoreMargin"],
                         r_log["classification"]["scoreMargin"])
        self.assertEqual(r_cp["classification"]["luckClass"], r_log["classification"]["luckClass"])
        self.assertEqual(r_cp["classification"]["segments"], r_log["classification"]["segments"])
        # 资源
        self.assertEqual(r_cp["resources"]["iceUsed"], r_log["resources"]["iceUsed"])
        self.assertEqual(r_cp["resources"]["horseUsed"], r_log["resources"]["horseUsed"])
        # 任务
        self.assertEqual(r_cp["tasks"]["me"]["base"], r_log["tasks"]["me"]["base"])
        self.assertEqual(r_cp["tasks"]["me"]["milestones"], r_log["tasks"]["me"]["milestones"])
        self.assertEqual(r_cp["tasks"]["me"]["claimed"], r_log["tasks"]["me"]["claimed"])


class TestSizeBudget(unittest.TestCase):
    def test_size_budget(self):
        ctext = compact_trace(_full_trace())
        self.assertLess(len(ctext), 10000, "compact trace must be < 10KB/match (got %d)" % len(ctext))
        # b64 更小
        self.assertLess(len(to_b64(ctext)), 4000)

    def test_b64_roundtrip(self):
        ctext = compact_trace(_full_trace())
        self.assertEqual(from_b64(to_b64(ctext)), ctext)


class TestRejectionCollapse(unittest.TestCase):
    def test_rejection_collapse(self):
        # 构造 224 次连续相同拒绝
        lines = [
            _emit("Startup", playerId=1001, version="iter30+x"),
            _emit("Start", teamId="RED", durationRound=600, nodes=5, edges=4, seed=1),
            _emit("Frame", round=1, phase="NORMAL", node="S10", state="IDLE", fresh=80,
                  goodFruit=97, taskScore=20, verified=True, delivered=False,
                  oppNode="S14", oppState="MOVING", oppFresh=88, oppGood=99, oppTask=40),
        ]
        for r in range(2, 226):
            lines.append(_emit("Rejected", round=r, action="MOVE", code="MOVE_BLOCKED_BY_GUARD",
                               target="S11"))
        lines += [
            _emit("Over", resultType="TIMEOUT", reason="FRAME_LIMIT", overRound=600, winner=2002, iWon=False),
            _emit("Score", player=1001, me=True, total=60, delivered=False, deliverRound=0,
                  fresh=50, goodFruit=90, taskScore=20, bountyScore=0),
            _emit("Score", player=2002, me=False, total=755, delivered=True, deliverRound=450,
                  fresh=88, goodFruit=99, taskScore=60, bountyScore=0),
        ]
        ctext = compact_trace(lines)
        # 224 次连续拒绝 → 1 行 REJ x224
        rej_lines = [ln for ln in ctext.splitlines() if ln.startswith("REJ ")]
        self.assertEqual(len(rej_lines), 1)
        self.assertIn("x224", rej_lines[0])
        # parse_compact 还原计数
        r_cp = parse_compact(ctext)
        self.assertEqual(len(r_cp["failures"]["rejected"]), 224)
        # 与 parse_log 计数一致
        path = _write_log(lines)
        try:
            r_log = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(len(r_cp["failures"]["rejected"]), len(r_log["failures"]["rejected"]))
        self.assertEqual(r_cp["outcome"], "UNDELIVERED")
        self.assertEqual(r_cp["finalScore"]["me"]["total"], 60)


class TestLegacyTrace(unittest.TestCase):
    def test_legacy_trace(self):
        """旧 trace：Frame 行缺 oppState/oppTask/weather 等字段，无 P1-A 富化。"""
        lines = [
            _emit("Startup", playerId=1001, version="1.0"),
            _emit("Start", teamId="RED", durationRound=600, nodes=3, edges=2, seed=7),
            # 旧 Frame：只有 node/state/fresh/goodFruit（无 opp*/weather）
            _emit("Frame", round=1, node="S01", state="IDLE", fresh=100, goodFruit=100,
                  verified=False, delivered=False),
            _emit("Action", round=1, action="MOVE", target="S02"),
            _emit("Frame", round=2, node="S01", state="MOVING", fresh=99.5, goodFruit=100,
                  verified=False, delivered=False),
            _emit("Over", resultType="NORMAL", overRound=2, winner=1001, iWon=True),
            _emit("Score", player=1001, me=True, total=500, delivered=True, deliverRound=2,
                  fresh=99.5, goodFruit=100, taskScore=0, bountyScore=0),
            _emit("Score", player=2002, me=False, total=480, delivered=True, deliverRound=2),
        ]
        ctext = compact_trace(lines)
        # 缺字段优雅降级：不抛异常，仍产出精简文本与 Report
        self.assertIn("# ", ctext)
        r_cp = parse_compact(ctext)
        self.assertIsNotNone(r_cp)
        self.assertEqual(r_cp["matchId"], "m")
        self.assertEqual(r_cp["outcome"], "WIN")
        self.assertEqual(r_cp["finalScore"]["me"]["total"], 500)
        # 缺 opp 字段 → trajectory.opponent 相应 None
        self.assertIsNone(r_cp["trajectory"]["opponent"]["freshnessEnd"])
        # finalScore 分项（P1-A 未落地）保持 None，与 parser stub 一致
        self.assertIsNone(r_cp["finalScore"]["me"]["freshness"])
        # 与 parse_log 一致
        path = _write_log(lines)
        try:
            r_log = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r_cp["finalScore"], r_log["finalScore"])
        self.assertEqual(r_cp["outcome"], r_log["outcome"])


if __name__ == "__main__":
    unittest.main()

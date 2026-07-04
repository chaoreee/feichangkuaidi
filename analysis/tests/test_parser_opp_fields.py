"""`analysis.parser` P1-A 富化字段单测——对手分项分 / 设卡区间 / 对手稀疏轨迹 / 任务跳变。

构造含 P1-A 字段（scoreDetail / Guards / oppResources / oppNext 等）的合成 trace，
断言 parser 正确抽取；并验证旧 trace（无新字段）优雅降级。
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


def _score(me=True, total=758, sd=None, **kw):
    fields = {"player": 1001 if me else 2002, "me": me, "total": total,
              "delivered": kw.get("delivered", True), "deliverRound": kw.get("deliverRound", 452),
              "fresh": kw.get("fresh", 77.5 if me else 79.0),
              "goodFruit": kw.get("goodFruit", 97 if me else 98),
              "taskScore": kw.get("taskScore", 20 if me else 60),
              "bountyScore": kw.get("bountyScore", 0)}
    if sd is not None:
        fields["scoreDetail"] = sd
    return _emit("Score", **fields)


class TestScoreDetail(unittest.TestCase):
    def test_score_detail_fills_components(self):
        sd = ["delivery=240", "tasks=20", "time=30", "goodFruit=97",
              "freshness=77.5", "bounty=0", "penalty=0", "total=758"]
        path = _write_log([
            _emit("Startup", playerId=1001, version="iter31+abc"),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True, sd=sd),
            _score(me=False, total=752, sd=["delivery=240", "tasks=60", "time=20",
                                            "goodFruit=98", "freshness=79", "bounty=0",
                                            "penalty=0", "total=752"]),
        ])
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["schemaVersion"], 2)
        me = r["finalScore"]["me"]
        self.assertEqual(me["delivery"], 240)
        self.assertEqual(me["task"], 20)
        self.assertEqual(me["time"], 30)
        self.assertEqual(me["goodFruit"], 97)
        self.assertEqual(me["freshness"], 77.5)
        self.assertEqual(me["penalty"], 0)
        opp = r["finalScore"]["opp"]
        self.assertEqual(opp["freshness"], 79)
        self.assertEqual(opp["task"], 60)
        self.assertEqual(opp["delivery"], 240)

    def test_score_detail_task_singular_key_compat(self):
        # sim 用 task（单数），parser 须兼容
        path = _write_log([
            _emit("Startup", playerId=1001),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True, sd=["delivery=240", "task=90", "total=758"]),
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ])
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertEqual(r["finalScore"]["me"]["task"], 90)

    def test_legacy_trace_components_null(self):
        # 旧 trace 无 scoreDetail → 分项全 None（向后兼容）
        path = _write_log([
            _emit("Startup", playerId=1001),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True),  # 无 sd
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ])
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        self.assertIsNone(r["finalScore"]["me"]["delivery"])
        self.assertIsNone(r["finalScore"]["me"]["freshness"])
        self.assertIsNone(r["finalScore"]["opp"]["delivery"])


class TestOppGuards(unittest.TestCase):
    def test_guards_line_tracks_opp_episode(self):
        # r100 对手在 S10 设卡（owner=BLUE，me=RED），r150 撤卡
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Frame", round=50, fresh=100, oppNode="S05"),
            _emit("Guards", round=100, guards=["S10:BLUE:4"]),
            _emit("Frame", round=120, fresh=95, oppNode="S05"),
            _emit("Guards", round=120, guards=["S10:BLUE:4"]),
            _emit("Guards", round=150, guards=[]),  # 撤卡
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True),
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        gs = r["opponentInteraction"]["oppGuards"]
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0]["node"], "S10")
        self.assertEqual(gs[0]["frame"], 100)
        self.assertEqual(gs[0]["lastFrame"], 120)
        self.assertEqual(gs[0]["defense"], 4)
        self.assertEqual(gs[0]["durationFrames"], 21)  # 100..120

    def test_own_guard_not_in_opp_guards(self):
        # 己方设卡（owner=RED）不计入 oppGuards
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Guards", round=100, guards=["S07:RED:2", "S10:BLUE:3"]),
            _emit("Guards", round=200, guards=[]),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True),
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        gs = r["opponentInteraction"]["oppGuards"]
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0]["node"], "S10")

    def test_break_guard_response_attached_to_episode(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Frame", round=100, fresh=90, node="S09"),
            _emit("Guards", round=100, guards=["S10:BLUE:4"]),
            _emit("Action", round=110, action="BREAK_GUARD", target="S10", good=1),
            _emit("Guards", round=120, guards=[]),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True),
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        gs = r["opponentInteraction"]["oppGuards"]
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0]["myResponse"], "BREAK_GUARD")
        self.assertEqual(gs[0]["cost"]["good"], 1)

    def test_legacy_trace_falls_back_to_break_guard(self):
        # 旧 trace 无 Guards 行：BREAK_GUARD 派生记录（保旧测试不回归）
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Frame", round=100, fresh=90, node="S09"),
            _emit("Action", round=110, action="BREAK_GUARD", target="S10", good=1),
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True),
            _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        gs = r["opponentInteraction"]["oppGuards"]
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0]["node"], "S10")
        self.assertEqual(gs[0]["myResponse"], "BREAK_GUARD")


class TestOppTrajectory(unittest.TestCase):
    def test_opp_frames_sparse_and_capped(self):
        # 构造 50 帧对手 node 每帧变化 → frames 应被截到 24（首12+末12）
        lines = [_emit("Startup", playerId=1001), _emit("Start", teamId="RED", seed=7)]
        for i in range(50):
            lines.append(_emit("Frame", round=i + 1, fresh=90,
                               oppNode="S%02d" % (i + 1), oppState="MOVING",
                               oppResources=["ICE_BOX=2"]))
        lines += [_emit("Over", winner=1001, iWon=True, overRound=60),
                  _score(me=True), _score(me=False, total=0, delivered=False, deliverRound=0)]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        frames = r["trajectory"]["opponent"]["frames"]
        self.assertLessEqual(len(frames), 24)
        self.assertEqual(frames[0]["n"], "S01")
        self.assertEqual(frames[-1]["n"], "S50")

    def test_opp_resources_and_task_jumps(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Frame", round=1, fresh=100, oppNode="S05", oppTask=0,
                  oppFresh=100, oppResources=["ICE_BOX=2"]),
            _emit("Frame", round=50, fresh=95, oppNode="S05", oppTask=20, oppFresh=95,
                  oppResources=["ICE_BOX=1"]),  # 任务跳变 + 冰鉴递减 + 鲜度降
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True), _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        opp = r["trajectory"]["opponent"]
        self.assertEqual(opp["iceUsed"], [{"frame": 50, "from": 2, "to": 1}])
        self.assertEqual(r["tasks"]["opp"]["claimed"], [{"frame": 50, "taskScore": 20}])
        self.assertEqual(opp["freshnessMin"], 95)

    def test_opp_fields_in_frames(self):
        lines = [
            _emit("Startup", playerId=1001),
            _emit("Start", teamId="RED", seed=7),
            _emit("Frame", round=1, fresh=100, oppNode="S05", oppState="IDLE",
                  oppBad=0, oppVerified=False, oppMoveProg=0.0, oppNext="S06",
                  oppGuardAP=3, oppResources=["ICE_BOX=2"]),
            _emit("Frame", round=2, fresh=99, oppNode="S05", oppState="IDLE",
                  oppBad=0, oppVerified=False, oppMoveProg=0.0, oppNext="S06",
                  oppGuardAP=3, oppResources=["ICE_BOX=2"]),  # 无变化→不新增 frame
            _emit("Over", winner=1001, iWon=True, overRound=452),
            _score(me=True), _score(me=False, total=0, delivered=False, deliverRound=0),
        ]
        path = _write_log(lines)
        try:
            r = parse_log(path)
        finally:
            os.unlink(path)
        frames = r["trajectory"]["opponent"]["frames"]
        self.assertEqual(len(frames), 1)  # 仅变化帧
        self.assertEqual(frames[0]["nx"], "S06")
        self.assertEqual(frames[0]["ga"], 3)
        self.assertEqual(frames[0]["rs"], ["ICE_BOX=2"])


if __name__ == "__main__":
    unittest.main()

"""analysis 管线单测：用合成 JSONL 验证 parser/evaluator/optimizer。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from analysis.evaluator import evaluate  # noqa: E402
from analysis.optimizer import suggest  # noqa: E402
from analysis.parser import parse_log  # noqa: E402
from analysis.report import analyze  # noqa: E402


def _write_log(records):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _delivered_session():
    return [
        {"ts": 1, "round": None, "kind": "state", "matchId": None, "payload": {"note": "startup", "playerId": 1001}},
        {"ts": 2, "round": None, "kind": "send", "matchId": None, "payload": {"msg": "registration", "playerId": 1001}},
        {"ts": 3, "round": None, "kind": "recv", "matchId": "M1",
         "payload": {"msg": "start", "matchId": "M1", "teamId": "RED", "durationRound": 600}},
        {"ts": 4, "round": 1, "kind": "frame", "matchId": "M1",
         "payload": {"phase": "NORMAL", "node": "S01", "state": "IDLE", "freshness": 100.0,
                     "goodFruit": 100, "taskScore": 0, "verified": False, "delivered": False, "events": []}},
        {"ts": 5, "round": 1, "kind": "decide", "matchId": "M1",
         "payload": {"actions": [{"action": "MOVE", "targetNodeId": "S02"}], "ms": 1.2}},
        {"ts": 6, "round": 2, "kind": "frame", "matchId": "M1",
         "payload": {"phase": "NORMAL", "node": "S11", "state": "IDLE", "freshness": 96.0,
                     "goodFruit": 99, "taskScore": 90, "verified": False, "delivered": False,
                     "events": ["TASK_COMPLETE"]}},
        {"ts": 7, "round": 2, "kind": "decide", "matchId": "M1", "payload": {"actions": [], "ms": 0.5}},
        {"ts": 8, "round": None, "kind": "recv", "matchId": "M1",
         "payload": {"msg": "over", "payload": {"resultType": "NORMAL", "overRound": 55, "winnerPlayerId": 1001,
                     "players": [{"playerId": 1001, "delivered": True, "deliverRound": 55, "totalScore": 700,
                                  "freshness": 96.0, "goodFruit": 99, "taskScore": 90}]}}},
    ]


class TestAnalysis(unittest.TestCase):
    def test_parse_basic(self):
        path = _write_log(_delivered_session())
        try:
            p = parse_log(path)
            self.assertEqual(p["match_id"], "M1")
            self.assertEqual(p["player_id"], 1001)
            self.assertEqual(p["team_id"], "RED")
            self.assertEqual(len(p["frames"]), 2)
            self.assertEqual(len(p["decisions"]), 2)
            self.assertIsNotNone(p["over"])
        finally:
            os.remove(path)

    def test_parse_last_session_only(self):
        # 两个会话追加：应只解析最后一个
        recs = _delivered_session() + [
            {"ts": 9, "round": None, "kind": "state", "matchId": None, "payload": {"note": "startup", "playerId": 2002}},
            {"ts": 10, "round": 1, "kind": "frame", "matchId": "M2", "payload": {"node": "S01"}},
        ]
        path = _write_log(recs)
        try:
            p = parse_log(path)
            self.assertEqual(p["player_id"], 2002)
            self.assertEqual(len(p["frames"]), 1)
        finally:
            os.remove(path)

    def test_evaluate_delivered(self):
        p = parse_log(_write_log(_delivered_session()))
        ev = evaluate(p)
        self.assertTrue(ev["delivered"])
        self.assertTrue(ev["won"])
        self.assertEqual(ev["final_score"], 700)
        self.assertEqual(ev["task_score"], 90)
        self.assertEqual(ev["action_histogram"].get("MOVE"), 1)
        self.assertEqual(ev["heartbeat_frames"], 1)
        self.assertEqual(ev["event_histogram"].get("TASK_COMPLETE"), 1)
        self.assertEqual(ev["exception_count"], 0)
        self.assertTrue(any("交付" in s for s in ev["strengths"]))

    def test_evaluate_not_delivered_flags_problem(self):
        recs = [
            {"kind": "state", "payload": {"note": "startup", "playerId": 1001}},
            {"kind": "recv", "payload": {"msg": "start", "matchId": "M1", "durationRound": 600}, "matchId": "M1"},
            {"round": 5, "kind": "frame", "payload": {"node": "S07", "state": "IDLE", "freshness": 40.0,
                                                      "goodFruit": 100, "taskScore": 0, "delivered": False}},
            {"round": 5, "kind": "decide", "payload": {"actions": [], "ms": 0.3}},
            {"round": 6, "kind": "error", "payload": {"error": "decide_exception", "detail": "KeyError('x')"}},
        ]
        p = parse_log(_write_log(recs))
        ev = evaluate(p)
        self.assertFalse(ev["delivered"])
        self.assertEqual(ev["exception_count"], 1)
        self.assertTrue(any("未完成交付" in s for s in ev["problems"]))
        sug = suggest(p, ev)
        areas = [a for a, _, _ in sug]
        self.assertIn("交付", areas)
        self.assertIn("Bug", areas)

    def test_report_writes_file(self):
        p = _write_log(_delivered_session())
        try:
            out = analyze(p)
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("对局分析报告", text)
            self.assertIn("改进建议", text)
            os.remove(out)
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main()

"""parser 单测：用真实 mock 日志夹具验证解析与降级兼容。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from analysis.parser import parse_text, parse_file  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures_match_mock.log")

SAMPLE_FRAME = ("11:26:29.712 Frame matchId=mock_match_001, round=5, phase=NORMAL, "
                "node=S07, state=IDLE, fresh=92.5, goodFruit=78, taskScore=30, "
                "verified=False, delivered=False, weather=HOT, "
                "opp=S09|MOVING|88|80|60|F|F, events=[NODE_ENTER|PROCESS_COMPLETE]")


class TestParserPrimitives(unittest.TestCase):
    def test_split_fields_plain(self):
        from analysis.parser import _split_fields
        f = dict(_split_fields("matchId=x, round=3, action=MOVE, target=S05"))
        self.assertEqual(f["matchId"], "x")
        self.assertEqual(f["round"], "3")
        self.assertEqual(f["target"], "S05")

    def test_split_fields_value_with_comma(self):
        # detail 含 ", " 但其后非 key=，不应误切
        from analysis.parser import _split_fields
        f = dict(_split_fields("round=4, detail=Error(111, 'refused'), code=X"))
        self.assertEqual(f["round"], "4")
        self.assertEqual(f["code"], "X")
        self.assertIn("111", f["detail"])

    def test_parse_list(self):
        from analysis.parser import _parse_list
        self.assertEqual(_parse_list("[a|b|c]"), ["a", "b", "c"])
        self.assertEqual(_parse_list("[]"), [])
        self.assertIsNone(_parse_list("plain"))

    def test_opp_mirror_full(self):
        from analysis.parser import OppMirror
        o = OppMirror.parse("S09|MOVING|88|80|60|F|F")
        self.assertEqual(o.node, "S09")
        self.assertEqual(o.fresh, 88.0)
        self.assertEqual(o.good_fruit, 80)
        self.assertFalse(o.verified)
        self.assertFalse(o.delivered)

    def test_opp_mirror_dash(self):
        from analysis.parser import OppMirror
        o = OppMirror.parse("-")
        self.assertIsNone(o.node)
        self.assertIsNone(o.fresh)


class TestParseFrameLine(unittest.TestCase):
    def test_frame_with_opp_weather(self):
        traces = parse_text(SAMPLE_FRAME)
        self.assertEqual(len(traces), 1)
        fr = traces[0].frames[0]
        self.assertEqual(fr.round, 5)
        self.assertEqual(fr.node, "S07")
        self.assertEqual(fr.fresh, 92.5)
        self.assertEqual(fr.weather, "HOT")
        self.assertEqual(fr.opp.node, "S09")
        self.assertEqual(fr.opp.fresh, 88.0)
        self.assertEqual(fr.events, ["NODE_ENTER", "PROCESS_COMPLETE"])

    def test_frame_legacy_no_opp(self):
        # 旧格式 Frame（无 opp/weather）应降级解析
        line = ("10:00:00.000 Frame matchId=m, round=1, phase=NORMAL, "
                "node=S01, state=IDLE, fresh=100, goodFruit=100, taskScore=0, "
                "verified=False, delivered=False")
        fr = parse_text(line)[0].frames[0]
        self.assertEqual(fr.round, 1)
        self.assertIsNone(fr.weather)
        self.assertIsNone(fr.opp.node)
        self.assertEqual(fr.events, [])


class TestParseFixture(unittest.TestCase):
    def setUp(self):
        self.traces = parse_file(FIXTURE)

    def test_multiple_sessions(self):
        # 夹具文件以追加模式累积多场，至少 1 场
        self.assertGreaterEqual(len(self.traces), 1)

    def test_last_session_complete(self):
        t = self.traces[-1]
        self.assertEqual(t.meta.match_id, "mock_match_001")
        self.assertEqual(t.meta.gate, "S14")
        self.assertEqual(t.meta.terminals, ["S15"])
        self.assertGreater(len(t.frames), 50)
        self.assertGreater(len(t.actions), 50)
        self.assertEqual(len(t.budgets), len(t.frames))  # 每帧一条 Budget
        self.assertIsNotNone(t.over)
        self.assertTrue(t.over.i_won)
        # 本方交付
        me = next(s for s in t.scores if s.me)
        self.assertTrue(me.delivered)
        self.assertEqual(me.deliver_round, 81)
        self.assertAlmostEqual(me.fresh, 95.95, places=2)

    def test_blocks_parsed(self):
        t = self.traces[-1]
        nodes = {b.node for b in t.blocks}
        self.assertIn("S13", nodes)   # 障碍
        self.assertIn("S10", nodes)   # 己方设卡
        cleared = [b for b in t.blocks if b.cleared]
        self.assertTrue(any(b.node == "S13" for b in cleared))


if __name__ == "__main__":
    unittest.main()

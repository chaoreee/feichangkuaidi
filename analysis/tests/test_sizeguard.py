"""`analysis.sizeguard` 单测：确保 reports/ 产物文件 <100KB。

覆盖：小报告原样返回不拷贝；大报告超预算时合并/封顶达标；count 保信息；
输入不被 mutate；JSON list / text 守卫；目录自检。
"""

import copy
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from analysis.sizeguard import (  # noqa: E402
    MAX_FILE_BYTES, _serialize, assert_dir_under_limit,
    fit_json_list, fit_report, fit_text,
)


def _small_report():
    return {
        "schemaVersion": 2, "matchId": "m1", "outcome": "WIN",
        "finalScore": {"me": {"total": 755}, "opp": {"total": 740}},
        "decisionTimeline": [{"frame": 100, "event": "TASK_CLAIM", "detail": "T1"}],
        "failures": {"rejected": [], "canAffordBlocked": []},
    }


def _huge_report(n_rejects=600, n_timeline=2000):
    """构造一份超 100KB 的报告：n_rejects 条连续相同拒绝 + n_timeline 条不同 timeline。"""
    rejected = [{"frame": 200 + i, "action": "MOVE",
                 "code": "MOVE_BLOCKED_BY_GUARD", "target": "S10"}
                for i in range(n_rejects)]
    timeline = ([{"frame": 200 + i, "event": "REJECTED",
                  "detail": "MOVE code=MOVE_BLOCKED_BY_GUARD"} for i in range(n_rejects)]
                + [{"frame": 1 + i, "event": "FRAME_TICK", "detail": "node=S%s" % i}
                   for i in range(n_timeline)])
    r = _small_report()
    r["failures"]["rejected"] = rejected
    r["decisionTimeline"] = timeline
    return r


class FitReportTests(unittest.TestCase):

    def test_small_report_unchanged_same_object(self):
        r = _small_report()
        self.assertIs(fit_report(r), r)  # 不拷贝、原样返回

    def test_does_not_mutate_input(self):
        r = _huge_report()
        before = copy.deepcopy(r)
        fitted = fit_report(r)
        self.assertEqual(r, before)  # 输入未被修改
        self.assertIsNot(fitted, r)
        self.assertGreater(len(_serialize(r)), MAX_FILE_BYTES)

    def test_fits_under_limit(self):
        fitted = fit_report(_huge_report())
        self.assertLessEqual(len(_serialize(fitted)), MAX_FILE_BYTES)

    def test_coalescing_preserves_count(self):
        # 600 条连续相同拒绝 → 合并为 1 条 count=600（信息不丢）
        fitted = fit_report(_huge_report(n_rejects=600, n_timeline=0))
        rejected = fitted["failures"]["rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["count"], 600)
        self.assertEqual(rejected[0]["firstFrame"], 200)
        self.assertEqual(rejected[0]["lastFrame"], 799)
        self.assertEqual(rejected[0]["code"], "MOVE_BLOCKED_BY_GUARD")

    def test_timeline_coalesced_when_identical(self):
        fitted = fit_report(_huge_report(n_rejects=600, n_timeline=0))
        # 600 条相同 REJECTED timeline → 合并为 1 条
        tl = fitted["decisionTimeline"]
        rej_entries = [t for t in tl if t.get("event") == "REJECTED"]
        self.assertEqual(len(rej_entries), 1)
        self.assertEqual(rej_entries[0]["count"], 600)

    def test_capping_inserts_elision_marker(self):
        # 大量不同 timeline 事件 → 封顶保头尾，含 _ELIDED 标记
        fitted = fit_report(_huge_report(n_rejects=0, n_timeline=5000))
        self.assertLessEqual(len(_serialize(fitted)), MAX_FILE_BYTES)
        tl = fitted["decisionTimeline"]
        markers = [t for t in tl if t.get("event") == "_ELIDED"]
        self.assertTrue(markers, "expected at least one elision marker")
        self.assertGreater(markers[0]["count"], 0)
        # 头尾都被保留（首条是 FRAME_TICK r1，末条是 FRAME_TICK r5000）
        # 合并后 frame→firstFrame/lastFrame，故取 firstFrame
        self.assertEqual(tl[0]["firstFrame"], 1)
        self.assertEqual(tl[-1]["firstFrame"], 5000)

    def test_fitted_report_is_valid_json(self):
        fitted = fit_report(_huge_report())
        # 落盘后能被 json 重新解析
        parsed = json.loads(_serialize(fitted).decode("utf-8"))
        self.assertEqual(parsed["matchId"], "m1")

    def test_stage4_fallback_drops_timeline(self):
        # 病态：标量字段本身接近上限 + 巨大 timeline，最终兜底也须达标
        r = _small_report()
        r["big"] = "x" * (MAX_FILE_BYTES - 5000)  # 接近上限的标量字段
        r["decisionTimeline"] = [{"frame": i, "event": "X", "detail": "y" * 200}
                                 for i in range(2000)]
        fitted = fit_report(r)
        self.assertLessEqual(len(_serialize(fitted)), MAX_FILE_BYTES)


class FitJsonListTests(unittest.TestCase):

    def test_under_limit_unchanged(self):
        lst = [{"matchId": "m%s" % i} for i in range(10)]
        self.assertIs(fit_json_list(lst), lst)

    def test_over_limit_capped_with_marker(self):
        lst = [{"matchId": "m%s" % i, "payload": "x" * 500} for i in range(2000)]
        self.assertGreater(len(_serialize(lst)), MAX_FILE_BYTES)
        fitted = fit_json_list(lst)
        self.assertLessEqual(len(_serialize(fitted)), MAX_FILE_BYTES)
        self.assertTrue(any(e.get("_truncated") for e in fitted))
        # 前部条目保留
        self.assertEqual(fitted[0]["matchId"], "m0")

    def test_capped_list_is_valid_json(self):
        lst = [{"matchId": "m%s" % i, "payload": "x" * 500} for i in range(2000)]
        fitted = fit_json_list(lst)
        json.loads(_serialize(fitted).decode("utf-8"))  # 不抛


class FitTextTests(unittest.TestCase):

    def test_under_limit_unchanged(self):
        s = "short text"
        self.assertEqual(fit_text(s), s)

    def test_over_limit_truncated_with_marker(self):
        s = "x" * (MAX_FILE_BYTES + 5000)
        out = fit_text(s)
        self.assertLessEqual(len(out.encode("utf-8")), MAX_FILE_BYTES)
        self.assertIn("truncated", out)

    def test_multibyte_not_split(self):
        # 中文字符占 3 字节，截断点不能落在字符中间
        s = "中" * (MAX_FILE_BYTES // 3 + 1000)
        out = fit_text(s)
        out.encode("utf-8")  # 不抛 UnicodeError（说明未切断多字节）


class AssertDirTests(unittest.TestCase):

    def test_finds_oversized_and_clean(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "small.json"), "w") as fh:
                fh.write("{}")
            with open(os.path.join(d, "big.json"), "w") as fh:
                fh.write("x" * (MAX_FILE_BYTES + 100))
            oversized = assert_dir_under_limit(d)
            self.assertEqual(len(oversized), 1)
            self.assertIn("big.json", oversized[0][0])
            # 干净目录
            with tempfile.TemporaryDirectory() as d2:
                with open(os.path.join(d2, "ok.json"), "w") as fh:
                    fh.write("{}")
                self.assertEqual(assert_dir_under_limit(d2), [])


if __name__ == "__main__":
    unittest.main()

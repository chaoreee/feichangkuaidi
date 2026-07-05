"""分析 CLI：python -m analysis <log...> [--corpus] [--out DIR]

单场：解析 → 指标 → 诊断 → Markdown 报告，写 reports/<日期>_<matchId>.md。
多场 + --corpus：各单报告 + 跨场聚合报告。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.parser import parse_file  # noqa: E402
from analysis.metrics import compute  # noqa: E402
from analysis.diagnose import diagnose  # noqa: E402
from analysis.report import render  # noqa: E402
from analysis import corpus  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m analysis",
                                 description="分析荔枝争运战 trace 日志")
    ap.add_argument("logs", nargs="+", help="trace .log 文件路径（可多个）")
    ap.add_argument("--corpus", action="store_true", help="多场时额外生成跨场聚合报告")
    ap.add_argument("--out", default="reports", help="报告输出目录（默认 reports/）")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")

    items = []  # (match_id, metrics, findings)
    reports_written = []

    for log_path in args.logs:
        if not os.path.isfile(log_path):
            print("warn: 不存在，跳过：%s" % log_path, file=sys.stderr)
            continue
        traces = parse_file(log_path)
        for i, trace in enumerate(traces):
            m = compute(trace)
            fs = diagnose(m)
            mid = m.match_id or ("session_%d" % i)
            md = render(trace, m, fs)
            out_name = "%s_%s.md" % (today, _safe(mid))
            out_path = os.path.join(args.out, out_name)
            # 同名追加重命名
            out_path = _unique(out_path)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
            reports_written.append(out_path)
            items.append((mid, m, fs))
            print("analyzed: %s → %s (frames=%d, findings=%d)" % (
                mid, out_path, len(trace.frames), len(fs)))

    if args.corpus and len(items) > 1:
        agg = corpus.aggregate(items)
        out_path = os.path.join(args.out, "%s_corpus.md" % today)
        out_path = _unique(out_path)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(agg)
        reports_written.append(out_path)
        print("corpus: %d matches → %s" % (len(items), out_path))

    print("\n已生成 %d 份报告：" % len(reports_written))
    for p in reports_written:
        print("  " + p)
    return 0


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(name))


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists("%s_%d%s" % (base, i, ext)):
        i += 1
    return "%s_%d%s" % (base, i, ext)


if __name__ == "__main__":
    sys.exit(main())

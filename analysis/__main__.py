"""CLI：扫描目录下的 `match_*.log` → 解析为单局 Report → 聚合 → 写出报告。

用法：
    python3 -m analysis [--out-dir docs] [--source NAME] [--variant NAME] <dir> [<dir> ...]

每个 dir 递归搜集 `*.log`（client 写出的 trace）。累积语料：每次读取全部日志重新解析聚合。

source/variant 推断（可被 --source/--variant 覆盖）：
- source：路径含 `real` → platform；含 `sim` → sim；否则 platform。
- variant：父目录名是 `baseline`/`tuned`/`v_*` 时取之；否则 baseline。
  （仿真 A/B 把日志分放 logs/sim/baseline/ 与 logs/sim/tuned/ 即可自动配对。）
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = os.path.join(_ROOT, "client")
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from analysis import aggregator  # noqa: E402
from analysis.compact import compact_trace, to_b64  # noqa: E402
from analysis.opponent_classifier import annotate_opp_class  # noqa: E402
from analysis.parser import parse_log  # noqa: E402


def _infer_source(path, override):
    if override:
        return override
    lower = path.replace(os.sep, "/").lower()
    if "/sim/" in lower or lower.endswith("/sim") or "/sim\\" in lower:
        return "sim"
    if "/real/" in lower:
        return "platform"
    return "platform"


def _infer_variant(path, override):
    if override:
        return override
    parent = os.path.basename(os.path.dirname(path))
    if parent in ("baseline", "tuned") or parent.startswith("variant_"):
        return parent
    return "baseline"


def collect_reports(dirs, source_override, variant_override):
    reports, paths, skipped = [], [], []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.endswith(".log") or not fn.startswith("match_"):
                    continue
                path = os.path.join(root, fn)
                source = _infer_source(path, source_override)
                variant = _infer_variant(path, variant_override)
                report = parse_log(path, source=source, variant=variant)
                if report is None:
                    skipped.append((path, "parse_failed_or_empty"))
                    continue
                reports.append(report)
                paths.append(path)
    return reports, paths, skipped


def main(argv):
    ap = argparse.ArgumentParser(description="Parse match trace logs and aggregate analysis reports.")
    ap.add_argument("dirs", nargs="+", help="directories to scan for match_*.log")
    ap.add_argument("--out-dir", default=os.path.join(_ROOT, "reports"),
                    help="output directory for all analysis artifacts (default: repo-root reports/)")
    ap.add_argument("--source", default=None, help="override source tag for all logs")
    ap.add_argument("--variant", default=None, help="override variant tag for all logs")
    ap.add_argument("--b64", action="store_true",
                    help="also print each match's compact trace as gzip+base64 (for chat paste)")
    args = ap.parse_args(argv)

    reports, log_paths, skipped = collect_reports(args.dirs, args.source, args.variant)
    if not reports:
        print("no valid match logs found in %s" % " ".join(args.dirs), file=sys.stderr)
        return 1

    # Iter 32：注入对手类标签（guard/quality/speed/unknown）到每局 classification，
    # 使单局 report.json / index / 聚合报告共享同一标签。纯观测，不改决策。
    for r in reports:
        annotate_opp_class(r)

    # 所有分析产物（聚合 md + 单局 report.json + index + timelines）统一落 --out-dir
    # （默认仓库根 reports/，与规格文档 docs/ 解耦——docs 只放规格，reports 放派生分析结果）。
    os.makedirs(args.out_dir, exist_ok=True)

    # 1) 单局 Report JSON（含 decisionTimeline）—— AI 下钻单局的入口
    def _safe_name(mid):
        return str(mid).replace(os.sep, "_").replace("/", "_")

    def _report_relpath(mid):
        return "%s.report.json" % _safe_name(mid)

    for r in reports:
        mid = r.get("matchId") or "unknown"
        rpath = os.path.join(args.out_dir, "%s.report.json" % _safe_name(mid))
        with open(rpath, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print("wrote %d report.json to %s" % (len(reports), args.out_dir))

    # 1b) 精简 trace（P1-B）：由完整 trace 派生，落 reports/<matchId>.compact.log（入库，我 pull 可直读）。
    #     真实平台 trace 无法上传，精简格式 ~6–9KB/局使我绕开瓶颈；parse_compact 可还原 Report。
    b64_lines = []
    for r, lpath in zip(reports, log_paths):
        mid = r.get("matchId") or "unknown"
        try:
            ctext = compact_trace(lpath)
        except Exception:
            continue
        cpath = os.path.join(args.out_dir, "%s.compact.log" % _safe_name(mid))
        with open(cpath, "w", encoding="utf-8") as fh:
            fh.write(ctext + "\n")
        if args.b64:
            b64_lines.append("%s\t%s" % (mid, to_b64(ctext)))
    print("wrote %d compact.log to %s" % (len(reports), args.out_dir))
    if b64_lines:
        sys.stdout.write("\n".join(b64_lines) + "\n")

    # 2) 索引 index.json —— 按 outcome/luckClass/segments 快速定位单局
    index = aggregator.build_index(reports, report_relpath=_report_relpath)
    index_path = os.path.join(args.out_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2, sort_keys=True)
    print("wrote %s" % index_path)

    # 3) 跨局聚合报告 analysis_report.md
    main_md = aggregator.build_analysis_report(reports)
    main_path = os.path.join(args.out_dir, "analysis_report.md")
    with open(main_path, "w", encoding="utf-8") as fh:
        fh.write(main_md)
    print("wrote %s (N=%d)" % (main_path, len(reports)))

    # 4) A/B 配对报告 ab_report.md（有配对才生成）
    ab = aggregator.ab_report(reports)
    if ab:
        ab_path = os.path.join(args.out_dir, "ab_report.md")
        with open(ab_path, "w", encoding="utf-8") as fh:
            fh.write(ab + "\n")
        print("wrote %s" % ab_path)

    # 5) 异常局时序摘要 timelines.md（有异常局才生成）
    tl_md = aggregator.build_timelines(reports)
    if tl_md:
        tl_path = os.path.join(args.out_dir, "timelines.md")
        with open(tl_path, "w", encoding="utf-8") as fh:
            fh.write(tl_md + "\n")
        print("wrote %s" % tl_path)

    if skipped:
        print("skipped %d log(s)" % len(skipped), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

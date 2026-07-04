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
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = os.path.join(_ROOT, "client")
if _CLIENT not in sys.path:
    sys.path.insert(0, _CLIENT)

from analysis import aggregator  # noqa: E402
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
    reports, skipped = [], []
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
    return reports, skipped


def main(argv):
    ap = argparse.ArgumentParser(description="Parse match trace logs and aggregate analysis reports.")
    ap.add_argument("dirs", nargs="+", help="directories to scan for match_*.log")
    ap.add_argument("--out-dir", default=os.path.join(_ROOT, "docs"),
                    help="output directory for analysis_report.md / ab_report.md")
    ap.add_argument("--source", default=None, help="override source tag for all logs")
    ap.add_argument("--variant", default=None, help="override variant tag for all logs")
    args = ap.parse_args(argv)

    reports, skipped = collect_reports(args.dirs, args.source, args.variant)
    if not reports:
        print("no valid match logs found in %s" % " ".join(args.dirs), file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    main_md = aggregator.build_analysis_report(reports)
    main_path = os.path.join(args.out_dir, "analysis_report.md")
    with open(main_path, "w", encoding="utf-8") as fh:
        fh.write(main_md)
    print("wrote %s (N=%d)" % (main_path, len(reports)))

    ab = aggregator.ab_report(reports)
    if ab:
        ab_path = os.path.join(args.out_dir, "ab_report.md")
        with open(ab_path, "w", encoding="utf-8") as fh:
            fh.write(ab + "\n")
        print("wrote %s" % ab_path)
    if skipped:
        print("skipped %d log(s)" % len(skipped), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

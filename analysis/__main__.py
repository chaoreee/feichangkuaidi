"""CLI 入口：python -m analysis <logfile|dir>  → 生成 analysis.md。"""

import sys

from analysis.report import analyze


def main(argv):
    if len(argv) < 1:
        print("usage: python -m analysis <logfile-or-dir>")
        return 2
    out = analyze(argv[0])
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

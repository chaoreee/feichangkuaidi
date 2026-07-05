"""支持 `python -m analysis` 入口。"""

import sys

from analysis.cli import main

if __name__ == "__main__":
    sys.exit(main())

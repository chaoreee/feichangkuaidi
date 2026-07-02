#!/bin/bash
# 打包提交 ZIP 并自检（任务书 §10）。实际逻辑在 build_zip.py（纯标准库）。
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/build_zip.py" "$@"

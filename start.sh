#!/bin/bash
# 平台启动脚本（任务书 §10.2）：./start.sh <playerId> <host> <port>
# 将平台传入的 3 个参数透传给客户端；纯标准库运行，无现场安装、不联网。
set -e

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>" >&2
  exit 1
fi

PLAYER_ID="$1"
HOST="$2"
PORT="$3"

# 脚本所在目录（ZIP 根 / 仓库根），据此定位 client/main.py。
DIR="$(cd "$(dirname "$0")" && pwd)"

exec python3 "$DIR/client/main.py" "$PLAYER_ID" "$HOST" "$PORT"

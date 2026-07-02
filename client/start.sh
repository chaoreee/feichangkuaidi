#!/bin/bash
# Launch script (task book section 10.2): ./start.sh <playerId> <host> <port>
# The platform passes the three arguments through to the client.
# Pure standard library, no on-site install, no network fetch.
set -e

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <playerId> <host> <port>" >&2
  exit 1
fi

PLAYER_ID="$1"
HOST="$2"
PORT="$3"

# Directory of this script (the ZIP root); main.py sits next to it.
DIR="$(cd "$(dirname "$0")" && pwd)"

exec python3 "$DIR/main.py" "$PLAYER_ID" "$HOST" "$PORT"

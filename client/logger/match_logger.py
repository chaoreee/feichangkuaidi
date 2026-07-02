"""结构化 JSONL 运行日志（delivery_spec §4）。

每行一条 JSON 记录：{ts, round, kind, payload}。
kind ∈ recv / send / decide / state / error。
matchId 在收到 start 前未知：先在内存缓冲，bind_match() 后落到
`logs/match_{matchId}_{playerId}.jsonl` 并 flush 缓冲。线程安全（接收线程也会写 error）。
"""

import json
import os
import threading
import time


class MatchLogger:
    def __init__(self, log_dir, player_id):
        self.log_dir = log_dir
        self.player_id = player_id
        self.match_id = None
        self.path = None
        self._fh = None
        self._buffer = []
        self._lock = threading.Lock()
        os.makedirs(log_dir, exist_ok=True)

    def bind_match(self, match_id):
        """收到 start 后绑定 matchId：打开日志文件并 flush 之前的缓冲记录。"""
        with self._lock:
            self.match_id = match_id
            safe = str(match_id).replace(os.sep, "_").replace("/", "_")
            self.path = os.path.join(self.log_dir, "match_%s_%s.jsonl" % (safe, self.player_id))
            self._fh = open(self.path, "a", encoding="utf-8")
            for line in self._buffer:
                self._fh.write(line + "\n")
            self._buffer.clear()
            self._fh.flush()

    def log(self, kind, round=None, **payload):
        record = {
            "ts": round_ts(),
            "round": round,
            "kind": kind,
            "matchId": self.match_id,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            if self._fh is not None:
                self._fh.write(line + "\n")
                self._fh.flush()
            else:
                self._buffer.append(line)

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None


def round_ts():
    """当前 Unix 时间戳（毫秒精度浮点，保留 3 位）。"""
    return round(time.time(), 3)

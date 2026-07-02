"""日志解析：把 JSONL 运行日志重建为结构化对局数据。

支持传入 .jsonl 文件或目录（目录取最近修改的 .jsonl）。日志为追加写，可能包含多次会话；
只解析最后一次会话（从最后一个 startup 标记到结尾），对应最近一次运行。
"""

import json
import os

_FRAME_KEYS = ("phase", "node", "state", "freshness", "goodFruit", "taskScore",
               "verified", "delivered", "events")


def _read_records(fp):
    records = []
    with open(fp, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _resolve_file(path):
    if os.path.isdir(path):
        jsonls = [os.path.join(path, f) for f in os.listdir(path) if f.endswith(".jsonl")]
        if not jsonls:
            raise FileNotFoundError("no .jsonl log in %s" % path)
        return max(jsonls, key=os.path.getmtime)
    return path


def _last_session(records):
    starts = [i for i, r in enumerate(records)
              if r.get("kind") == "state" and (r.get("payload") or {}).get("note") == "startup"]
    return records[starts[-1]:] if starts else records


def parse_log(path):
    fp = _resolve_file(path)
    records = _last_session(_read_records(fp))
    parsed = {
        "log_file": fp, "match_id": None, "player_id": None, "team_id": None,
        "duration_round": None, "startup": {}, "frames": [], "decisions": [],
        "errors": [], "over": None,
    }
    for r in records:
        kind = r.get("kind")
        p = r.get("payload") or {}
        rnd = r.get("round")
        if parsed["match_id"] is None and r.get("matchId"):
            parsed["match_id"] = r.get("matchId")
        if kind == "state" and p.get("note") == "startup":
            parsed["startup"] = p
            parsed["player_id"] = p.get("playerId")
        elif kind == "recv" and p.get("msg") == "start":
            parsed["team_id"] = p.get("teamId")
            parsed["duration_round"] = p.get("durationRound")
            if p.get("matchId"):
                parsed["match_id"] = p.get("matchId")
        elif kind == "frame":
            frame = {"round": rnd}
            frame.update({k: p.get(k) for k in _FRAME_KEYS})
            parsed["frames"].append(frame)
        elif kind == "decide":
            parsed["decisions"].append({"round": rnd, "actions": p.get("actions") or [], "ms": p.get("ms")})
        elif kind == "error":
            entry = {"round": rnd}
            entry.update(p)
            parsed["errors"].append(entry)
        elif kind == "recv" and p.get("msg") == "over":
            parsed["over"] = p.get("payload")
    return parsed

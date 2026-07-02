"""效果评估：从解析数据计算表现指标与定性优点/问题/风险。"""

import statistics

DECISION_BUDGET_MS = 400.0  # 与 client/config.DECISION_BUDGET 对齐（秒×1000）


def _me_over(over, pid):
    if not over:
        return None
    for pl in over.get("players") or []:
        if pl.get("playerId") == pid:
            return pl
    return None


def evaluate(parsed):
    frames = parsed["frames"]
    decisions = parsed["decisions"]
    over = parsed["over"]
    pid = parsed["player_id"]
    last = frames[-1] if frames else {}
    me_over = _me_over(over, pid)

    ev = {}
    ev["result_type"] = over.get("resultType") if over else None
    ev["over_round"] = over.get("overRound") if over else None
    ev["winner_player_id"] = over.get("winnerPlayerId") if over else None
    ev["won"] = (over.get("winnerPlayerId") == pid) if over else None

    def pick(key, frame_key):
        """优先取 over 里本方字段，缺失则回退到末帧。"""
        if me_over is not None and me_over.get(key) is not None:
            return me_over.get(key)
        return last.get(frame_key)

    ev["delivered"] = bool(pick("delivered", "delivered") or False)
    ev["deliver_round"] = me_over.get("deliverRound") if me_over else None
    ev["final_score"] = me_over.get("totalScore") if me_over else None
    ev["final_freshness"] = pick("freshness", "freshness")
    ev["final_good"] = pick("goodFruit", "goodFruit")
    ev["task_score"] = pick("taskScore", "taskScore") or 0
    ev["last_node"] = last.get("node")
    ev["last_state"] = last.get("state")

    ms = [d["ms"] for d in decisions if isinstance(d.get("ms"), (int, float))]
    ev["decision"] = {
        "count": len(decisions),
        "avg_ms": round(statistics.mean(ms), 3) if ms else 0,
        "max_ms": max(ms) if ms else 0,
        "over_budget": sum(1 for m in ms if m > DECISION_BUDGET_MS),
    }

    hist = {}
    heartbeat = 0
    for d in decisions:
        if not d["actions"]:
            heartbeat += 1
        for a in d["actions"]:
            act = a.get("action")
            hist[act] = hist.get(act, 0) + 1
    ev["action_histogram"] = hist
    ev["heartbeat_frames"] = heartbeat

    eh = {}
    for f in frames:
        for t in (f.get("events") or []):
            eh[t] = eh.get(t, 0) + 1
    ev["event_histogram"] = eh

    ev["error_count"] = len(parsed["errors"])
    ev["exception_count"] = sum(1 for e in parsed["errors"] if str(e.get("error", "")).endswith("exception"))
    ev["frames_total"] = len(frames)

    ev["strengths"], ev["problems"], ev["risks"] = _qualitative(ev)
    return ev


def _qualitative(ev):
    strengths, problems, risks = [], [], []
    if ev["delivered"]:
        strengths.append("完成终点交付（送达/好果/鲜度/用时分可结算）")
        if ev["deliver_round"]:
            strengths.append("交付回合 %s" % ev["deliver_round"])
        if ev["final_good"] is not None:
            strengths.append("交付好果 %s、鲜度 %s" % (ev["final_good"], ev["final_freshness"]))
    else:
        problems.append("未完成交付：送达/好果/鲜度/用时分归零（末位置=%s，状态=%s）"
                        % (ev["last_node"], ev["last_state"]))

    ts = ev["task_score"] or 0
    if ts >= 90:
        strengths.append("皇榜任务基础分累计 %s ≥90（送达/用时满额并触发里程碑）" % ts)
    elif ts > 0:
        risks.append("皇榜任务基础分累计 %s <90，送达基础分与用时分被折减" % ts)
    else:
        problems.append("未完成任何皇榜任务（任务分为 0）")

    if ev["final_freshness"] is not None and ev["final_freshness"] < 50:
        risks.append("交付/末帧鲜度偏低 %s（鲜度品质分低）" % ev["final_freshness"])

    if ev["decision"]["over_budget"] > 0:
        problems.append("决策超时 %d 帧（>%.0fms）" % (ev["decision"]["over_budget"], DECISION_BUDGET_MS))
    if ev["exception_count"] > 0:
        problems.append("决策/解析异常 %d 次" % ev["exception_count"])
    other = ev["error_count"] - ev["exception_count"]
    if other > 0:
        risks.append("其他错误/拒绝记录 %d 次（查错误码）" % other)
    return strengths, problems, risks

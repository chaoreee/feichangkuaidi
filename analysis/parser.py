"""单局 trace 日志解析器：`match_*.log` → 结构化 `Report`（schemaVersion=1）。

输入是 `client/logger/match_logger.py` 写出的人类可读 trace（每行 `<时钟> <Event> matchId=..., round=..., k=v`）。
解析为 `docs/iteration_plan_v2.md` §3.4 定义的单局报告 schema。**纯确定性、可单测**——
事实 100% 从日志文本抽取，AI 据此做解释。

client 已在 trace 中记录了赛后分析所需的绝大部分事实（Frame/Action/Projection/ModeChange/
Over/Score）。少量 decision 内部信号（被拒动作、canAfford 拦截）由 client 额外写成
`Rejected`/`CanAffordBlock` trace 行（仅日志，非分析），本解析器据此还原。
"""

import os
import re
import statistics

SCHEMA_VERSION = 1

_GOOD_TO_BAD = (90, 80, 70, 60, 50, 40, 30, 20, 10)
_MILESTONES = (60, 90, 110)
_WAITING_STALL_THRESHOLD = 3
_LINE_RE = re.compile(r"^(\d\d:\d\d:\d\d\.\d\d\d) (\w+) (.*)$")


def _parse_fields(rest):
    """`matchId=x, round=3, k=v` → {matchId: x, round: 3, k: v}。值做类型推断。"""
    out = {}
    for part in rest.split(", "):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k] = _coerce(v.strip())
    return out


def _coerce(v):
    if v == "None":
        return None
    if v == "True":
        return True
    if v == "False":
        return False
    # list: [a|b|c]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        if not inner:
            return []
        return [_coerce(x) for x in inner.split("|")]
    # int
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _num(v, default=None):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return v
    try:
        return int(v)
    except (ValueError, TypeError):
        pass
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


class _Acc:
    """单局累计器：边解析 trace 边累计事实。"""

    def __init__(self):
        self.match_id = None
        self.player_id = None
        self.team_id = None
        self.seed = None
        self.duration_round = 600
        # 终局
        self.over = None
        self.score_me = None
        self.score_opp = None
        # 轨迹 / 帧状态
        self.fresh_start = None
        self.fresh_min = None
        self.fresh_end = None
        self.good_start = None
        self.good_end = None
        self._prev_fresh = None
        self.bad_crossings = []
        self.verify_frame = None
        self.rush_trigger_frame = None
        self._prev_verified = False
        self._prev_phase_rush = False
        self.last_frame = None
        # waiting 停滞
        self._wait_node = None
        self._wait_from = None
        self._wait_len = 0
        self.waiting_stuck = []
        # 投影
        self.mode_switches = []
        self.conf_samples = []
        self.last_my_score = None
        self.last_opp_deliver_proj = None
        # 资源 / 急策 / 动作
        self.ice_used = []
        self.horse_used = None
        self.rush_tactic = None
        self.task_claims = []
        self.windows = []
        self.my_guards = []
        self.opp_guards = []
        self.bounty_attempts = []
        self.timeline = []
        # 对手逐帧（Frame 行携带 oppNode/oppFresh/oppGood）
        self.opp_fresh_end = None
        self.opp_good_end = None
        self.opp_node = None
        # 失败
        self.rejected = []
        self.can_afford_blocked = []
        self.decision_timeouts = 0
        # 中局 / 天气 / 争抢
        self.mid_gap = None
        self._mid_done = False
        self.weather_hit = False
        self.contested = False

    def feed(self, event, f):
        getattr(self, "_on_" + event, self._noop)(f)

    def _noop(self, f):
        pass

    # ---- 事件 ----
    def _on_Startup(self, f):
        self.player_id = f.get("playerId", self.player_id)

    def _on_Start(self, f):
        self.team_id = f.get("teamId")
        self.duration_round = f.get("durationRound") or 600
        self.seed = f.get("seed")

    def _on_Frame(self, f):
        rnd = f.get("round")
        fresh = _num(f.get("fresh"))
        good = _num(f.get("goodFruit"))
        if fresh is not None:
            if self.fresh_start is None:
                self.fresh_start = fresh
                self._prev_fresh = fresh
            else:
                if self._prev_fresh is not None and fresh < self._prev_fresh:
                    for t in _GOOD_TO_BAD:
                        if self._prev_fresh >= t > fresh and t not in self.bad_crossings:
                            self.bad_crossings.append(t)
                self._prev_fresh = fresh
            self.fresh_end = fresh
            if self.fresh_min is None or fresh < self.fresh_min:
                self.fresh_min = fresh
        if good is not None:
            if self.good_start is None:
                self.good_start = good
            self.good_end = good
        # 对手逐帧状态（Frame 行 opp* 字段）
        opp_fresh = _num(f.get("oppFresh"))
        opp_good = _num(f.get("oppGood"))
        if opp_fresh is not None:
            self.opp_fresh_end = opp_fresh
        if opp_good is not None:
            self.opp_good_end = opp_good
        opp_node = f.get("oppNode")
        if opp_node is not None:
            self.opp_node = opp_node
        # 天气命中（Frame 行 weather 字段；非空即本帧有生效天气）
        if f.get("weather"):
            self.weather_hit = True
        verified = bool(f.get("verified"))
        if verified and not self._prev_verified:
            self.verify_frame = rnd
        self._prev_verified = verified
        phase = f.get("phase")
        is_rush = phase == "RUSH"
        if is_rush and not self._prev_phase_rush and self.rush_trigger_frame is None:
            self.rush_trigger_frame = rnd
        self._prev_phase_rush = is_rush
        # waiting 停滞
        state = f.get("state")
        if state == "WAITING":
            node = f.get("node")
            if node == self._wait_node:
                self._wait_len += 1
            else:
                self._close_wait(rnd)
                self._wait_node = node
                self._wait_from = rnd
                self._wait_len = 1
        else:
            self._close_wait(rnd)
        # 中局 gap 快照
        if not self._mid_done and (rnd or 0) >= 300:
            self._mid_done = True
        self.last_frame = f

    def _close_wait(self, rnd):
        if self._wait_len >= _WAITING_STALL_THRESHOLD:
            self.waiting_stuck.append({
                "fromFrame": self._wait_from,
                "toFrame": (self._wait_from or rnd) + self._wait_len - 1,
                "node": self._wait_node})
        self._wait_node = None
        self._wait_from = None
        self._wait_len = 0

    def _on_Projection(self, f):
        my = _num(f.get("myScore"))
        if my is not None:
            self.last_my_score = round(my, 1)
        opp_d = _num(f.get("oppDeliver"))
        if opp_d is not None:
            self.last_opp_deliver_proj = opp_d
        conf = _num(f.get("confidence"))
        if conf is not None:
            self.conf_samples.append(conf)
        gap = _num(f.get("gap"))
        # 中局快照：r300 前持续更新，取最后一帧 gap 作为中局分差（_mid_done 在 _on_Frame r300 时置位）
        if not self._mid_done and gap is not None:
            self.mid_gap = round(gap, 1)

    def _on_ModeChange(self, f):
        self.mode_switches.append({
            "frame": f.get("round"), "from": f.get("from"), "to": f.get("to"),
            "gap": _num(f.get("gap")), "reason": f.get("reason")})
        self._timeline_push(f.get("round"), "MODE_CHANGE",
                            "%s->%s" % (f.get("from"), f.get("to")))

    def _on_Action(self, f):
        act = f.get("action")
        rnd = f.get("round")
        if f.get("ms") is not None:
            self.decision_timeouts += 1
        if act == "USE_RESOURCE":
            res = f.get("resource")
            fresh_before = _num((self.last_frame or {}).get("fresh"))
            if res == "ICE_BOX":
                self.ice_used.append({"frame": rnd,
                                      "freshnessBefore": round(fresh_before, 2)
                                      if fresh_before is not None else None})
                self._timeline_push(rnd, "USE_ICE",
                                    "fresh=%s" % (round(fresh_before, 1)
                                                  if fresh_before is not None else "?"))
            elif res in ("FAST_HORSE", "SHORT_HORSE"):
                self.horse_used = "%s@%s" % (res, rnd)
                self._timeline_push(rnd, "USE_HORSE", res)
        elif act == "RUSH_PROTECT":
            self.rush_tactic = {"type": "RUSH_PROTECT", "frame": rnd}
            self._timeline_push(rnd, "RUSH_TACTIC", "RUSH_PROTECT")
        elif act == "RUSH_SPEED":
            self.rush_tactic = {"type": "RUSH_SPEED", "frame": rnd}
            self._timeline_push(rnd, "RUSH_TACTIC", "RUSH_SPEED")
        elif act == "CLAIM_TASK":
            node = (self.last_frame or {}).get("node")
            self.task_claims.append({"template": None, "node": node,
                                     "frame": rnd, "detourExtra": None})
            self._timeline_push(rnd, "TASK_CLAIM", "%s" % f.get("task"))
        elif act in ("CLEAR", "BREAK_GUARD", "FORCED_PASS"):
            method = act
            node = f.get("target")
            cost_good = (_num(f.get("good")) or 0) if act == "BREAK_GUARD" else (
                1 if act == "CLEAR" else 0)
            if act == "BREAK_GUARD":
                self.opp_guards.append({"node": node, "frame": rnd,
                                        "myResponse": "BREAK_GUARD",
                                        "cost": {"good": cost_good, "frames": 0}})
            self._timeline_push(rnd, "BREAKTHROUGH", "%s %s cost %d" % (method, node, cost_good))
        elif act == "SET_GUARD":
            self.my_guards.append({"node": f.get("target"), "frame": rnd,
                                   "defense": None, "extraGood": f.get("extra") or 0})
            self._timeline_push(rnd, "SET_GUARD", "%s" % f.get("target"))
        elif act == "WINDOW_CARD":
            self.windows.append({"frame": rnd, "type": f.get("contestType"),
                                 "contestId": f.get("contest"),
                                 "myCard": f.get("card"), "oppCard": None, "result": None})
            self.contested = True
            self._timeline_push(rnd, "WINDOW_CARD", "card=%s" % f.get("card"))

    def _on_GuardDecision(self, f):
        # 补充同帧 SET_GUARD 的 defense/denial/gap（GuardDecision 在 Action 之后同帧出现）
        if self.my_guards:
            g = self.my_guards[-1]
            g["defense"] = f.get("defense")
            g["gap"] = _num(f.get("gap"))
            g["denial"] = _num(f.get("denial"))

    def _on_Bounty(self, f):
        # decision._maybe_bounty 触发时记一行 Bounty trace：target/reward/delta/extra/动作/烧好果
        rec = {"frame": f.get("round"), "target": f.get("target"),
               "reward": _num(f.get("reward")), "delta": _num(f.get("delta")),
               "extraFrames": _num(f.get("extra")), "action": f.get("action"),
               "goodBurned": _num(f.get("goodBurn")) or 0}
        self.bounty_attempts.append(rec)
        self._timeline_push(f.get("round"), "BOUNTY",
                            "%s reward=%s delta=%s %s"
                            % (f.get("target"), f.get("reward"),
                               f.get("delta"), f.get("action")))

    def _on_Over(self, f):
        self.over = f

    def _on_Score(self, f):
        if f.get("me"):
            self.score_me = f
        else:
            self.score_opp = f

    def _on_Rejected(self, f):
        self.rejected.append({"frame": f.get("round"), "action": f.get("action"),
                              "code": f.get("code"), "target": f.get("target")})
        self._timeline_push(f.get("round"), "REJECTED",
                            "%s code=%s" % (f.get("action"), f.get("code")))

    def _on_CanAffordBlock(self, f):
        if len(self.can_afford_blocked) < 40:
            self.can_afford_blocked.append({"frame": f.get("round"), "action": f.get("action"),
                                            "reason": f.get("reason"), "target": f.get("target")})

    def _on_Error(self, f):
        # 错误事件：恶劣天气不在 Error；天气命中由 Frame.events 体现。此处不处理。
        pass

    def _timeline_push(self, frame, event, detail):
        # 保留全量时序（去截断）：单局关键事件量级在百级，可全量承载；
        # 截断会丢前半局根因（task 冲 90、中局切档等），违背时序还原初衷。
        self.timeline.append({"frame": frame, "event": event, "detail": detail})


def _med(samples):
    if not samples:
        return None
    return round(statistics.median(samples), 3)


def _outcome(acc):
    me = acc.score_me or {}
    over = acc.over or {}
    if me.get("retired"):
        return "RETIRED"
    if not me.get("delivered"):
        return "UNDELIVERED"
    winner = over.get("winner")
    if winner is None:
        return "TIE"
    pid = acc.player_id
    if str(winner) == str(pid) or over.get("iWon") is True:
        return "WIN"
    return "LOSS"


def _final_score(score):
    if not score:
        return {"total": 0, "delivery": None, "task": None, "time": None,
                "goodFruit": None, "freshness": None, "bounty": 0, "penalty": 0}
    return {
        "total": _num(score.get("total")) or 0,
        "delivery": None, "task": None, "time": None,
        "goodFruit": None, "freshness": None,
        "bounty": _num(score.get("bountyScore")) or 0,
        "penalty": 0,
    }


def _task_block(score):
    base = _num((score or {}).get("taskScore")) or 0
    reached = [m for m in _MILESTONES if base >= m]
    return {"base": base, "milestones": reached}


def _segments(acc, me_task_base):
    segs = []
    delivered = bool((acc.score_me or {}).get("delivered"))
    segs.append("delivered" if delivered else "undelivered")
    segs.append("task90_reached" if me_task_base >= 90 else "task90_missed")
    if acc.mid_gap is not None:
        if acc.mid_gap > 20:
            segs.append("mid_lead")
        elif acc.mid_gap < -20:
            segs.append("mid_trail")
        else:
            segs.append("mid_even")
    if acc.weather_hit:
        segs.append("weather_hit")
    if acc.contested:
        segs.append("contested")
    opp_del = bool((acc.score_opp or {}).get("delivered"))
    segs.append("opp_delivered" if opp_del else "opp_undelivered")
    return segs


def _luck_class(outcome, proj_error):
    if outcome == "TIE":
        return "expected_tie"
    surprising = proj_error is not None and abs(proj_error) > 50
    if outcome == "WIN":
        return "lucky_win" if surprising else "expected_win"
    if outcome == "LOSS":
        return "unlucky_loss" if surprising else "expected_loss"
    return "expected_loss"  # UNDELIVERED / RETIRED：自身 bug，修真 bug


def build_report(acc, source="platform", variant="baseline"):
    me = acc.score_me or {}
    opp = acc.score_opp or {}
    me_task_base = _num(me.get("taskScore")) or 0
    actual_me = _num(me.get("total")) or 0
    proj_error = (round(acc.last_my_score - actual_me, 1)
                  if acc.last_my_score is not None and actual_me else None)
    score_margin = None
    if acc.score_me is not None and acc.score_opp is not None:
        score_margin = (_num(me.get("total")) or 0) - (_num(opp.get("total")) or 0)
    outcome = _outcome(acc)
    opp_deliver = _num(opp.get("deliverRound"))

    return {
        "schemaVersion": SCHEMA_VERSION,
        "matchId": acc.match_id,
        "playerId": acc.player_id,
        "teamId": acc.team_id,
        "seed": acc.seed,
        "source": source,
        "variant": variant,
        "durationRound": acc.duration_round,
        "outcome": outcome,
        "finalScore": {"me": _final_score(acc.score_me), "opp": _final_score(acc.score_opp)},
        "delivery": {
            "me": {"frame": _num(me.get("deliverRound")),
                   "verifyFrame": acc.verify_frame,
                   "goodFruit": acc.good_end,
                   "freshness": (round(acc.fresh_end, 2) if acc.fresh_end is not None else None)},
            "opp": {"frame": opp_deliver},
            "rushTriggerFrame": acc.rush_trigger_frame,
        },
        "tasks": {
            "me": {**_task_block(acc.score_me), "claimed": acc.task_claims},
            "opp": {**_task_block(acc.score_opp), "claimed": []},
            "missedReachable90": None,  # 待 Phase B 静态规划器计算
        },
        "resources": {"iceUsed": acc.ice_used, "horseUsed": acc.horse_used,
                      "rushTactic": acc.rush_tactic},
        "trajectory": {
            "freshness": {"start": acc.fresh_start, "end": acc.fresh_end, "min": acc.fresh_min},
            "goodFruit": {"start": acc.good_start, "end": acc.good_end,
                          "badCrossings": list(acc.bad_crossings)},
            "opponent": {"freshnessEnd": acc.opp_fresh_end, "goodFruitEnd": acc.opp_good_end,
                         "nodeEnd": acc.opp_node},
        },
        "opponentInteraction": {"windows": acc.windows, "oppGuards": acc.opp_guards,
                                "bounties": acc.bounty_attempts, "myGuards": acc.my_guards},
        "failures": {"rejected": acc.rejected, "waitingStuck": acc.waiting_stuck,
                     "invalidActions": 0, "decisionTimeouts": acc.decision_timeouts,
                     "canAffordBlocked": acc.can_afford_blocked},
        "projection": {
            "modeSwitches": acc.mode_switches,
            "confidence": {"min": (round(min(acc.conf_samples), 3) if acc.conf_samples else None),
                           "median": _med(acc.conf_samples),
                           "max": (round(max(acc.conf_samples), 3) if acc.conf_samples else None)},
            "projectedMyScore": acc.last_my_score,
            "actualMyScore": actual_me or None,
            "error": proj_error,
            "oppEtaPredictedDeliver": acc.last_opp_deliver_proj,
            "oppActualDeliver": opp_deliver,
        },
        "classification": {
            "scoreMargin": score_margin,
            "luckClass": _luck_class(outcome, proj_error),
            "segments": _segments(acc, me_task_base),
        },
        "decisionTimeline": list(acc.timeline),
    }


def parse_log(path, source="platform", variant="baseline"):
    """解析单局 trace 日志为 Report dict。无法解析的行静默跳过；永不抛出。"""
    acc = _Acc()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                m = _LINE_RE.match(line)
                if not m:
                    continue
                _clock, event, rest = m.groups()
                f = _parse_fields(rest)
                if not acc.match_id or acc.match_id == "-":
                    mid = f.get("matchId")
                    if mid and mid != "-":
                        acc.match_id = mid
                acc.feed(event, f)
    except Exception:
        return None
    if acc.over is None and acc.score_me is None:
        return None  # 未结束/空日志
    return build_report(acc, source=source, variant=variant)

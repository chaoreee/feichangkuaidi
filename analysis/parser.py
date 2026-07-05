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

SCHEMA_VERSION = 2

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
        self.client_version = None
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
        self.runtime_opp_class = None  # Iter 37 §1 运行期对手类（末帧 Projection.oppClass）
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
        self.opp_fresh_min = None
        self.opp_good_end = None
        self.opp_bad_end = None
        self.opp_node = None
        self.opp_verified_frame = None
        self._prev_opp_verified = False
        # P1-A：对手稀疏轨迹（仅变化帧，≤40 条）+ 任务分跳变 + 冰鉴使用推断
        self.opp_frames = []
        self._prev_opp = None
        self.opp_task_jumps = []
        self._prev_opp_task = None
        self.opp_ice_used = []
        self._prev_opp_ice = None
        # P1-A：对手设卡区间（从 Guards 行追踪）
        self._opp_guard_active = {}  # node -> {firstFrame, lastFrame, defense}
        self.opp_guard_episodes = []
        self._break_guard_responses = []  # {node, frame, costGood}（_on_Action BREAK_GUARD）
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
        v = f.get("version")
        if v is not None and v != "":
            self.client_version = str(v)  # 版本恒为字符串（trace 值推断可能把 "1.0" 转 float）

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
            if self.opp_fresh_min is None or opp_fresh < self.opp_fresh_min:
                self.opp_fresh_min = opp_fresh
        if opp_good is not None:
            self.opp_good_end = opp_good
        opp_node = f.get("oppNode")
        if opp_node is not None:
            self.opp_node = opp_node
        # P1-A：对手资源/鲜度/任务轨迹富化
        opp_bad = _num(f.get("oppBad"))
        if opp_bad is not None:
            self.opp_bad_end = opp_bad
        opp_verified = bool(f.get("oppVerified"))
        if opp_verified and not self._prev_opp_verified:
            self.opp_verified_frame = rnd
        self._prev_opp_verified = opp_verified
        opp_task = _num(f.get("oppTask"))
        if opp_task is not None:
            if self._prev_opp_task is not None and opp_task > self._prev_opp_task:
                self.opp_task_jumps.append({"frame": rnd, "taskScore": opp_task})
            self._prev_opp_task = opp_task
        # 对手冰鉴使用推断：ICE_BOX 库存递减即用了一次
        opp_res = f.get("oppResources")
        opp_ice = None
        if isinstance(opp_res, list):
            for item in opp_res:
                if isinstance(item, str) and item.startswith("ICE_BOX="):
                    opp_ice = _num(item.split("=", 1)[1])
                    break
        if opp_ice is not None:
            if self._prev_opp_ice is not None and opp_ice < self._prev_opp_ice:
                self.opp_ice_used.append({"frame": rnd, "from": self._prev_opp_ice, "to": opp_ice})
            self._prev_opp_ice = opp_ice
        # 对手稀疏轨迹快照（仅任一字段变化时记一条，≤40 条保 report.json 体积）
        opp_snap = {
            "r": rnd, "n": opp_node, "s": f.get("oppState"), "ts": opp_task,
            "b": opp_bad, "vf": (opp_verified or None), "mp": _num(f.get("oppMoveProg")),
            "nx": f.get("oppNext"), "ga": _num(f.get("oppGuardAP")), "rs": opp_res,
        }
        opp_snap = {k: v for k, v in opp_snap.items() if v is not None}
        if opp_snap:
            # 比较键排除 r（round 每帧变，不应触发记录），仅状态变化才记
            snap_cmp = tuple(sorted((k, v) for k, v in opp_snap.items() if k != "r"))
            if snap_cmp != self._prev_opp:
                self._push_opp_frame(opp_snap)
                self._prev_opp = snap_cmp
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

    def _push_opp_frame(self, snap):
        """对手稀疏轨迹：append 一条；超 24 条时保留首 12 + 末 12（截中段）控 report.json 体积。"""
        self.opp_frames.append(snap)
        if len(self.opp_frames) > 24:
            self.opp_frames = self.opp_frames[:12] + self.opp_frames[-12:]

    # ---- 对手设卡区间（P1-A，从 Guards 行追踪）----
    def _on_Guards(self, f):
        rnd = f.get("round")
        raw = f.get("guards")
        if raw is None:
            return
        seen = set()
        for item in raw:
            if not isinstance(item, str) or item.count(":") < 2:
                continue
            node, owner, defense = item.split(":", 2)
            seen.add(node)
            if owner == self.team_id:
                continue  # 己方设卡不记入 oppGuards
            defense_n = _num(defense) or 0
            ep = self._opp_guard_active.get(node)
            if ep is None:
                self._opp_guard_active[node] = {"firstFrame": rnd, "lastFrame": rnd,
                                                "defense": defense_n}
            else:
                ep["lastFrame"] = rnd
                ep["defense"] = defense_n
        # 消失的节点 finalize
        for node in list(self._opp_guard_active.keys()):
            if node not in seen:
                self._finalize_guard_episode(node)

    def _finalize_guard_episode(self, node):
        ep = self._opp_guard_active.pop(node, None)
        if ep is None:
            return
        self.opp_guard_episodes.append({
            "node": node, "frame": ep["firstFrame"], "lastFrame": ep["lastFrame"],
            "durationFrames": (ep["lastFrame"] - ep["firstFrame"] + 1)
                              if ep["lastFrame"] is not None and ep["firstFrame"] is not None
                              else None,
            "defense": ep["defense"], "myResponse": None, "cost": None,
        })

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
        # Iter 37 §1 运行期对手类（每帧覆盖，末帧即终局估计）
        oc = f.get("oppClass")
        if oc:
            self.runtime_opp_class = oc

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
                self._break_guard_responses.append({"node": node, "frame": rnd,
                                                    "costGood": cost_good})
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


def _parse_score_detail(sd):
    """Score 行的 scoreDetail → dict。

    接受三种形态（parser `_coerce` 还原为 list / compact `_coerce` 留作 `[k=v|...]` 原始串 / 单条 `k=v`）：
    - list `[k=v, ...]`（parser 路径，`_coerce` 已拆 `[a|b]`）
    - 字符串 `[k=v|k=v|...]`（compact 路径，`_coerce` 未拆 list）
    - 字符串 `k=v`（单条）
    协议 scoreDetail 键：delivery/goodFruit/freshness/time/tasks/bounty/penalty/total。
    兼容 sim 的 `task`（单数）键。旧 trace 无 scoreDetail → {}（分项全 None，向后兼容）。
    """
    out = {}
    if not sd:
        return out
    if isinstance(sd, str):
        s = sd.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        sd = [p for p in s.split("|") if p]
    for item in sd:
        if not isinstance(item, str) or "=" not in item:
            continue
        k, v = item.split("=", 1)
        out[k.strip()] = _coerce(v.strip())
    return out


def _final_score(score):
    if not score:
        return {"total": 0, "delivery": None, "task": None, "time": None,
                "goodFruit": None, "freshness": None, "bounty": 0, "penalty": 0}
    sd = _parse_score_detail(score.get("scoreDetail"))
    # task：协议用 tasks（复数），sim 用 task（单数），两者兼容
    task = sd.get("tasks", sd.get("task"))
    return {
        "total": _num(score.get("total")) or 0,
        "delivery": _num(sd.get("delivery")),
        "task": _num(task),
        "time": _num(sd.get("time")),
        "goodFruit": _num(sd.get("goodFruit")),
        "freshness": _num(sd.get("freshness")),
        "bounty": (_num(score.get("bountyScore")) if score.get("bountyScore") is not None
                   else _num(sd.get("bounty"))) or 0,
        "penalty": _num(sd.get("penalty")) or 0,
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
    opp_guards = _build_opp_guards(acc)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "matchId": acc.match_id,
        "playerId": acc.player_id,
        "teamId": acc.team_id,
        "seed": acc.seed,
        "clientVersion": acc.client_version,
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
            "opp": {"frame": opp_deliver, "verifyFrame": acc.opp_verified_frame},
            "rushTriggerFrame": acc.rush_trigger_frame,
        },
        "tasks": {
            "me": {**_task_block(acc.score_me), "claimed": acc.task_claims},
            "opp": {**_task_block(acc.score_opp), "claimed": acc.opp_task_jumps},
            "missedReachable90": None,  # 待 Phase B 静态规划器计算
        },
        "resources": {"iceUsed": acc.ice_used, "horseUsed": acc.horse_used,
                      "rushTactic": acc.rush_tactic},
        "trajectory": {
            "freshness": {"start": acc.fresh_start, "end": acc.fresh_end, "min": acc.fresh_min},
            "goodFruit": {"start": acc.good_start, "end": acc.good_end,
                          "badCrossings": list(acc.bad_crossings)},
            "opponent": {"freshnessEnd": acc.opp_fresh_end,
                         "freshnessMin": acc.opp_fresh_min,
                         "goodFruitEnd": acc.opp_good_end, "badFruitEnd": acc.opp_bad_end,
                         "nodeEnd": acc.opp_node, "verifyFrame": acc.opp_verified_frame,
                         "iceUsed": acc.opp_ice_used, "frames": acc.opp_frames},
        },
        "opponentInteraction": {"windows": acc.windows, "oppGuards": opp_guards,
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
            "runtimeOpponentClass": acc.runtime_opp_class,
        },
        "classification": {
            "scoreMargin": score_margin,
            "luckClass": _luck_class(outcome, proj_error),
            "segments": _segments(acc, me_task_base),
        },
        "decisionTimeline": list(acc.timeline),
    }


def _build_opp_guards(acc):
    """oppGuards：优先用 Guards 行追踪的设卡区间（附 BREAK_GUARD 响应）；
    无 Guards 行（旧 trace）回落 _on_Action BREAK_GUARD 派生记录，保旧测试不回归。"""
    # finalize 仍未关闭的区间（对局结束时仍在的设卡）
    for node in list(acc._opp_guard_active.keys()):
        acc._finalize_guard_episode(node)
    if acc.opp_guard_episodes:
        eps = [dict(ep) for ep in acc.opp_guard_episodes]
        # 把 BREAK_GUARD 响应挂到匹配区间（同 node、帧落在区间内）
        for resp in acc._break_guard_responses:
            for ep in eps:
                f0, f1 = ep["frame"], ep["lastFrame"]
                if ep["node"] == resp["node"] and f0 is not None and (
                        f1 is None or f0 <= resp["frame"] <= (f1 + 30)):
                    ep["myResponse"] = "BREAK_GUARD"
                    ep["cost"] = {"good": resp["costGood"], "frames": 0}
                    break
        return eps
    # 旧 trace 无 Guards 行：保持既有 BREAK_GUARD 派生行为
    return acc.opp_guards


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

"""精简 trace 派生器（P1-B，数据回流通道）。

完整 trace ~880KB–1.16MB/局、`.gitignore` 不入库 → 我只能读 `reports/`。本模块把完整
trace **派生**为事件驱动紧凑格式（~6–9KB/局纯文本 / ~1.4KB gzip+base64），落 `reports/`
入库，使我 pull 后能直读、彻底绕开"原始 trace 无法上传"瓶颈。

架构对齐（CLAUDE.md 既有原则：client trace = 传输格式单文件 / repo 产物 = 分析格式多文件
可重生成）：精简 trace 是可从完整 trace 重生成的派生产物，属 repo 产物，不进 client。

两个方向：
- `compact_trace(source)`：完整 trace（路径或文本）→ 精简文本。多局文件按局分块（`---` 分隔）。
- `parse_compact(text)`：精简文本（首块）→ 结构化 `Report` dict（schema 与 `parser.build_report`
  一致，复用 `parser` 的 `_final_score`/`_task_block`/`_segments`/`_luck_class` 防漂移）。
  当完整 trace 丢失、仅剩精简时仍可重建 report.json。

格式 spec 见 `docs/compact_trace_format.md`。P1-A（Iter 31）补记的 oppResources/Guards/
scoreDetail 一旦进入完整 trace，本模块自动透传（精简从完整派生），无需改 compact。
"""

import base64
import gzip
import os

from analysis.parser import (
    SCHEMA_VERSION,
    _LINE_RE,
    _GOOD_TO_BAD,
    _MILESTONES,
    _parse_fields,
    _final_score,
    _task_block,
    _segments,
    _luck_class,
    _num,
)

_THRESH = _GOOD_TO_BAD  # (90,80,70,60,50,40,30,20,10)
_WAITING_STALL = 3
_CAB_CAP = 40  # 对齐 parser._on_CanAffordBlock 的 40 条上限


# --------------------------------------------------------------------------- #
# 值格式化（与 client/logger/match_logger._fmt 一致：float 去尾零）            #
# --------------------------------------------------------------------------- #
def _fmt_num(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        s = "%.2f" % v
        return s.rstrip("0").rstrip(".") or "0"
    return str(v)


def _kv(prefix, **fields):
    parts = []
    for k, v in fields.items():
        if v is None:
            continue
        parts.append("%s=%s" % (k, _fmt_num(v)))
    return " ".join(parts) and ("%s %s" % (prefix, " ".join(parts))) or prefix


# --------------------------------------------------------------------------- #
# 单局紧凑化                                                                   #
# --------------------------------------------------------------------------- #
class _Match:
    """单局累计器：边遍历完整 trace 行边产出精简行。"""

    def __init__(self):
        self.out = []
        # 头部
        self.pid = None
        self.version = None
        self.header_emitted = False
        # 帧状态 / 轨迹
        self.first_frame = True
        self.prev = {}  # node/state/phase/goodFruit/taskScore/oppNode/oppTask/delivered/verified/weather
        self.prev_fresh = None
        self.prev_ofresh = None
        self.fstart = self.fmin = self.fend = None
        self.gstart = self.gend = None
        self.onode = None
        self.ofend = self.ogend = None
        self.bad_crossings = []
        self.obad_crossings = []
        self.verify_frame = None
        self.rush_trigger = None
        self._prev_verified = False
        self._prev_phase = None
        self.weather_hit = False
        # 动作合并
        self.prev_action_key = None
        # 拒绝 / canAfford 合并
        self.rej = None  # (action, code, target, first_round, count)
        self.cab = None  # (action, reason, target, first_round, count)
        # 投影
        self.last_my = None
        self.last_opp_deliver = None
        self.last_gap = None
        self.last_mode = None
        self.conf_samples = []
        self.mid_gap = None
        self._mid_done = False
        # 结算
        self.over = None
        self.score_me = None
        self.score_opp = None
        # waiting 停滞推算
        self.cur_node = None
        self.cur_state = None
        self.wait_start = None
        self.wait_node = None
        self.last_round = None

    # ---- 入口 ----
    def feed(self, event, f):
        getattr(self, "_on_" + event, self._noop)(f)

    def _noop(self, f):
        pass

    # ---- 头部 / 拓扑 ----
    def _on_Startup(self, f):
        self.pid = f.get("playerId", self.pid)
        v = f.get("version")
        if v not in (None, ""):
            self.version = str(v)

    def _on_Start(self, f):
        if not self.header_emitted:
            mid = f.get("matchId")
            self.out.append("# %s v=%s pid=%s team=%s seed=%s dur=%s" % (
                mid, self.version or "-", self.pid or "-",
                f.get("teamId"), f.get("seed"), f.get("durationRound") or 600))
            self.header_emitted = True

    def _on_Map(self, f):
        nodes = f.get("nodes") or []
        edges = f.get("edges") or []
        tasks = f.get("tasks") or []
        self.out.append("Map N=%d E=%d" % (len(nodes), len(edges)))
        if nodes:
            self.out.append("N " + " ".join(_compact_node(t) for t in nodes))
        if edges:
            self.out.append("E " + " ".join(_compact_edge(t) for t in edges))
        if tasks:
            self.out.append("T " + " ".join(str(t) for t in tasks))

    def _on_Ready(self, f):
        pass  # 冗余

    # ---- 帧变化 ----
    def _on_Frame(self, f):
        rnd = f.get("round")
        self.last_round = rnd
        node = f.get("node")
        state = f.get("state")
        phase = f.get("phase")
        good = _num(f.get("goodFruit"))
        ts = _num(f.get("taskScore"))
        onode = f.get("oppNode")
        ots = _num(f.get("oppTask"))
        fresh = _num(f.get("fresh"))
        ofresh = _num(f.get("oppFresh"))
        delivered = bool(f.get("delivered"))
        verified = bool(f.get("verified"))
        weather = f.get("weather")

        # 轨迹统计
        if fresh is not None:
            if self.fstart is None:
                self.fstart = fresh
            self.fend = fresh
            self.fmin = fresh if self.fmin is None else min(self.fmin, fresh)
        if good is not None:
            if self.gstart is None:
                self.gstart = good
            self.gend = good
        if onode is not None:
            self.onode = onode
        if ofresh is not None:
            self.ofend = ofresh
        if _num(f.get("oppGood")) is not None:
            self.ogend = _num(f.get("oppGood"))
        if weather:
            self.weather_hit = True

        # 鲜度阈值跨越
        if self.prev_fresh is not None and fresh is not None:
            for t in _THRESH:
                if self.prev_fresh >= t > fresh and t not in self.bad_crossings:
                    self.bad_crossings.append(t)
        if self.prev_ofresh is not None and ofresh is not None:
            for t in _THRESH:
                if self.prev_ofresh >= t > ofresh and t not in self.obad_crossings:
                    self.obad_crossings.append(t)
        if fresh is not None:
            self.prev_fresh = fresh
        if ofresh is not None:
            self.prev_ofresh = ofresh

        # verify / rush 触发
        if verified and not self._prev_verified:
            self.verify_frame = rnd
        self._prev_verified = verified
        if phase == "RUSH" and self._prev_phase != "RUSH" and self.rush_trigger is None:
            self.rush_trigger = rnd
        self._prev_phase = phase

        # waiting 停滞推算（基于状态/节点变化）
        self._update_waiting(rnd, state, node)

        # 输出 F 行
        if self.first_frame:
            self.first_frame = False
            self.out.append("F r%s n=%s st=%s ph=%s gf=%s ts=%s on=%s ots=%s" % (
                rnd, node, state, phase,
                _fmt_num(good), _fmt_num(ts), onode, _fmt_num(ots)))
        else:
            changes = []
            if node != self.prev.get("node"):
                changes.append("n=%s" % node)
            if state != self.prev.get("state"):
                changes.append("st=%s" % state)
            if phase != self.prev.get("phase"):
                changes.append("ph=%s" % phase)
            if good != self.prev.get("goodFruit"):
                changes.append("gf=%s" % _fmt_num(good))
            if ts != self.prev.get("taskScore"):
                changes.append("ts=%s" % _fmt_num(ts))
            if onode != self.prev.get("oppNode"):
                changes.append("on=%s" % onode)
            if ots != self.prev.get("oppTask"):
                changes.append("ots=%s" % _fmt_num(ots))
            if delivered and not self.prev.get("delivered"):
                changes.append("del=1")
            if verified and not self.prev.get("verified"):
                changes.append("vfy=1")
            if weather and weather != self.prev.get("weather"):
                changes.append("w=%s" % weather)
            # 鲜度阈值跨越标记（本帧新增的下行跨越，去重）
            for t in self._new_crossings(self.prev.get("_pf"), fresh):
                changes.append("fr%d" % t)
            for t in self._new_crossings(self.prev.get("_pof"), ofresh):
                changes.append("ofr%d" % t)
            if changes:
                self.out.append("F r%s %s" % (rnd, " ".join(changes)))

        self.prev = dict(self.prev)
        self.prev.update({"node": node, "state": state, "phase": phase,
                          "goodFruit": good, "taskScore": ts, "oppNode": onode,
                          "oppTask": ots, "delivered": delivered, "verified": verified,
                          "weather": weather, "_pf": self.prev_fresh, "_pof": self.prev_ofresh})

    def _new_crossings(self, prev, cur):
        if prev is None or cur is None:
            return []
        out = []
        for t in _THRESH:
            if prev >= t > cur:
                out.append(t)
        return out

    def _update_waiting(self, rnd, state, node):
        # 关闭：当前在 WAITING 且本帧状态转出或节点变化
        if self.cur_state == "WAITING" and self.wait_start is not None:
            closed = False
            if state is not None and state != "WAITING":
                self._close_wait(rnd)
                closed = True
            elif node is not None and self.wait_node is not None and node != self.wait_node:
                self._close_wait(rnd)
                closed = True
            if closed:
                pass
        if state == "WAITING":
            if self.wait_start is None or self.wait_node != node:
                if self.wait_start is not None:
                    self._close_wait(rnd)  # 节点变了重启
                self.wait_start = rnd
                self.wait_node = node
        self.cur_state = state
        if node is not None:
            self.cur_node = node

    def _close_wait(self, rnd):
        # 由调用方在状态/节点变化时触发；waitingStuck 在 parse 侧统一还原，
        # 此处仅保留起止供 parse_compact 用 F 行推算（不在精简格式里直接落 waiting 行）。
        self.wait_start = None
        self.wait_node = None

    # ---- 投影 / ETA ----
    def _on_Projection(self, f):
        my = _num(f.get("myScore"))
        if my is not None:
            self.last_my = round(my, 1)
        opp_d = _num(f.get("oppDeliver"))
        if opp_d is not None:
            self.last_opp_deliver = opp_d
        gap = _num(f.get("gap"))
        if gap is not None:
            self.last_gap = round(gap, 1)
        mode = f.get("mode")
        if mode is not None:
            self.last_mode = mode
        conf = _num(f.get("confidence"))
        if conf is not None:
            self.conf_samples.append(conf)
        rnd = f.get("round")
        if not self._mid_done and (rnd or 0) >= 300:
            self._mid_done = True
        if not self._mid_done and gap is not None:
            self.mid_gap = round(gap, 1)

    def _on_Eta(self, f):
        pass  # 冗余于 Projection oppDeliver；逐帧体积大，丢弃

    # ---- 动作 ----
    def _on_Action(self, f):
        act = f.get("action")
        rnd = f.get("round")
        ms = f.get("ms")
        if act in (None, "NONE"):
            if ms is not None:
                # 超预算的心跳仍计入 decisionTimeouts
                self.out.append("A r%s NONE ms=%s" % (rnd, _fmt_num(ms)))
            return
        target = f.get("target")
        resource = f.get("resource")
        task = f.get("task")
        contest = f.get("contest")
        ctype = f.get("contestType")
        card = f.get("card")
        good = f.get("good")
        extra = f.get("extraGood")
        key = (act, target, resource, task, contest, ctype, card, good, extra)
        if key != self.prev_action_key:
            parts = ["A r%s %s" % (rnd, act)]
            if target is not None:
                parts.append("target=%s" % target)
            if resource is not None:
                parts.append("res=%s" % resource)
            if task is not None:
                parts.append("task=%s" % task)
            if contest is not None:
                parts.append("contest=%s" % contest)
            if ctype is not None:
                parts.append("type=%s" % ctype)
            if card is not None:
                parts.append("card=%s" % card)
            if good is not None:
                parts.append("good=%s" % good)
            if extra is not None:
                parts.append("extra=%s" % extra)
            fresh = f.get("fresh")
            if fresh is not None:
                parts.append("fresh=%s" % _fmt_num(fresh))
            if ms is not None:
                parts.append("ms=%s" % _fmt_num(ms))
            self.out.append(" ".join(parts))
            self.prev_action_key = key

    # ---- 信号行（原样紧凑保留） ----
    def _on_ModeChange(self, f):
        self.out.append("ModeChange r%s %s->%s reason=%s gap=%s" % (
            f.get("round"), f.get("from"), f.get("to"),
            f.get("reason"), _fmt_num(_num(f.get("gap")))))

    def _on_GuardDecision(self, f):
        self.out.append(_kv("GuardDecision", **{
            "r": f.get("round"), "target": f.get("target"), "reason": f.get("reason"),
            "gap": _num(f.get("gap")), "defense": f.get("defense"),
            "denial": _num(f.get("denial")), "extraGood": f.get("extraGood")}))

    def _on_Bounty(self, f):
        self.out.append(_kv("Bounty", **{
            "r": f.get("round"), "target": f.get("target"), "reward": _num(f.get("reward")),
            "delta": _num(f.get("delta")), "extra": _num(f.get("extra")),
            "action": f.get("action"), "goodBurn": _num(f.get("goodBurn"))}))

    def _on_Rejected(self, f):
        key = (f.get("action"), f.get("code"), f.get("target"))
        rnd = f.get("round")
        if self.rej is not None and self.rej[0] == key:
            self.rej = (key, self.rej[1], self.rej[2] + 1)
        else:
            self._flush_rej()
            self.rej = (key, rnd, 1)

    def _flush_rej(self):
        if self.rej is None:
            return
        (act, code, target), first, count = self.rej
        self.out.append("REJ r%s x%d %s %s %s" % (
            first, count, code, act, target))
        self.rej = None

    def _on_CanAffordBlock(self, f):
        key = (f.get("action"), f.get("reason"), f.get("target"))
        rnd = f.get("round")
        if self.cab is not None and self.cab[0] == key:
            self.cab = (key, self.cab[1], self.cab[2] + 1)
        else:
            self._flush_cab()
            self.cab = (key, rnd, 1)

    def _flush_cab(self):
        if self.cab is None:
            return
        (act, reason, target), first, count = self.cab
        self.out.append("CAB r%s x%d %s %s %s" % (
            first, count, act, reason, target))
        self.cab = None

    # ---- 结算 ----
    def _on_Over(self, f):
        self._flush_rej()
        self._flush_cab()
        self.over = f

    def _on_Score(self, f):
        if f.get("me"):
            self.score_me = f
        else:
            self.score_opp = f

    def _on_Error(self, f):
        pass

    # ---- 收尾 ----
    def finish(self):
        self._flush_rej()
        self._flush_cab()
        # 轨迹摘要
        self.out.append(_kv("Traj", **{
            "fstart": self.fstart, "fmin": self.fmin, "fend": self.fend,
            "gstart": self.gstart, "gend": self.gend, "onode": self.onode,
            "ofend": self.ofend, "ogend": self.ogend}))
        # 投影摘要
        self.out.append(_kv("Proj", **{
            "my": self.last_my, "oppDel": self.last_opp_deliver,
            "gap": self.last_gap, "mode": self.last_mode}))
        if self.conf_samples:
            self.out.append("Conf min=%.3f med=%.3f max=%.3f" % (
                min(self.conf_samples),
                _med(self.conf_samples), max(self.conf_samples)))
        if self.mid_gap is not None:
            self.out.append("MidGap=%s" % _fmt_num(self.mid_gap))
        # 结算
        if self.over is not None:
            o = self.over
            self.out.append("Over result=%s reason=%s round=%s winner=%s iWon=%s" % (
                o.get("resultType"), o.get("reason"), o.get("overRound"),
                o.get("winner"), o.get("iWon")))
        if self.score_me is not None:
            self.out.append("Score me " + _score_fields(self.score_me))
        if self.score_opp is not None:
            self.out.append("Score opp " + _score_fields(self.score_opp))
        return self.out


def _med(samples):
    import statistics
    return statistics.median(samples)


def _score_fields(s):
    parts = ["total=%s" % _fmt_num(_num(s.get("total")) or 0),
             "del=%s" % s.get("delivered"),
             "dframe=%s" % _fmt_num(_num(s.get("deliverRound")) or 0),
             "fresh=%s" % _fmt_num(_num(s.get("fresh"))),
             "good=%s" % _fmt_num(_num(s.get("goodFruit"))),
             "task=%s" % _fmt_num(_num(s.get("taskScore")) or 0),
             "bounty=%s" % _fmt_num(_num(s.get("bountyScore")) or 0)]
    # P1-A 透传：scoreDetail（Iter 31 落地后出现）
    det = s.get("scoreDetail")
    if det:
        parts.append("det=%s" % det)
    return " ".join(parts)


def _compact_node(tok):
    # "S01:START" -> "S01:S"
    if ":" in tok:
        nid, ntype = tok.split(":", 1)
        return "%s:%s" % (nid, (ntype or "")[:1])
    return tok


def _compact_edge(tok):
    # "S01-S02:30:ROAD" -> "S01-S02:30:R" ; "S01>S02:30:ROAD" 定向保留 >
    if ":" in tok:
        head, dist, rtype = tok.split(":", 2)
        return "%s:%s:%s" % (head, dist, (rtype or "")[:1])
    return tok


# --------------------------------------------------------------------------- #
# 多局切分                                                                     #
# --------------------------------------------------------------------------- #
def _split_matches(lines):
    """完整 trace 行 → 每局的 (event, fields) 列表列表。

    边界：Over 之后的下一个 Startup 开新局。单局文件 → 单元素列表。
    """
    matches = []
    cur = []
    over_seen = False
    for line in lines:
        m = _LINE_RE.match(line)
        if not m:
            continue
        _clock, event, rest = m.groups()
        f = _parse_fields(rest)
        if event == "Startup" and over_seen and cur:
            matches.append(cur)
            cur = []
            over_seen = False
        cur.append((event, f))
        if event == "Over":
            over_seen = True
    if cur:
        matches.append(cur)
    return matches


def compact_trace(source):
    """完整 trace（路径或文本）→ 精简文本。

    多局文件按局分块、`---` 分隔。每局 ~6–9KB。
    """
    text = _read_source(source)
    matches = _split_matches(text.splitlines())
    blocks = []
    for evs in matches:
        mt = _Match()
        for event, f in evs:
            mt.feed(event, f)
        blocks.append("\n".join(mt.finish()))
    return "\n---\n".join(blocks)


def _read_source(source):
    if isinstance(source, (list, tuple)):
        return "\n".join(source)
    if isinstance(source, str) and ("\n" in source or not os.path.isfile(source)):
        return source
    with open(source, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# 精简 → Report                                                                #
# --------------------------------------------------------------------------- #
class _PState:
    """parse_compact 累计器。"""

    def __init__(self):
        self.match_id = None
        self.pid = None
        self.team_id = None
        self.seed = None
        self.version = None
        self.dur = 600
        # 轨迹
        self.fstart = self.fmin = self.fend = None
        self.gstart = self.gend = None
        self.onode = None
        self.ofend = self.ogend = None
        self.bad_crossings = []
        self.verify_frame = None
        self.rush_trigger = None
        self.weather_hit = False
        # 帧游标（waiting 推算 + claim 节点）
        self.cur_node = None
        self.cur_state = None
        self.wait_start = None
        self.wait_node = None
        self.waiting_stuck = []
        # 动作 / 资源
        self.ice_used = []
        self.horse_used = None
        self.rush_tactic = None
        self.task_claims = []
        self.windows = []
        self.my_guards = []
        self.opp_guards = []
        self.bounties = []
        self.decision_timeouts = 0
        # 信号
        self.mode_switches = []
        self.timeline = []
        # 拒绝 / canAfford
        self.rejected = []
        self.can_afford = []
        # 投影
        self.last_my = None
        self.last_opp_deliver = None
        self.last_gap = None
        self.last_mode = None
        self.conf_min = self.conf_med = self.conf_max = None
        self.mid_gap = None
        # 结算
        self.over = None
        self.score_me = None
        self.score_opp = None


def _parse_kv(tokens):
    d = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            d[k] = _coerce(v)
    return d


def _coerce(v):
    if v == "None":
        return None
    if v == "True":
        return True
    if v == "False":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_compact(text):
    """精简文本（首块）→ Report dict；空/无结算返回 None。"""
    if text is None:
        return None
    blocks = text.split("\n---\n")
    if not blocks:
        return None
    return _parse_block(blocks[0].splitlines())


def _parse_block(lines):
    st = _PState()
    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        head = line.split(" ", 1)[0]
        rest = line[len(head):].strip()
        if head == "#":
            _parse_header(st, rest)
        elif head == "F":
            _parse_f(st, rest)
        elif head == "A":
            _parse_a(st, rest)
        elif head == "ModeChange":
            _parse_modechange(st, rest)
        elif head == "GuardDecision":
            _parse_guarddecision(st, rest)
        elif head == "Bounty":
            _parse_bounty(st, rest)
        elif head == "REJ":
            _parse_rej(st, rest)
        elif head == "CAB":
            _parse_cab(st, rest)
        elif head == "Traj":
            _parse_traj(st, rest)
        elif head == "Proj":
            _parse_proj(st, rest)
        elif head == "Conf":
            _parse_conf(st, rest)
        elif head == "MidGap=":
            st.mid_gap = _num(rest)
        elif head.startswith("MidGap="):
            st.mid_gap = _num(line.split("=", 1)[1])
        elif head == "Over":
            _parse_over(st, rest)
        elif head == "Score":
            _parse_score(st, rest)
        # Map/N/E/T 头部拓扑：归因参考用，report 不依赖，跳过

    if st.over is None and st.score_me is None:
        return None
    return _build_compact_report(st)


def _parse_header(st, rest):
    # <matchId> v=<ver> pid=<pid> team=<team> seed=<seed> dur=<dur>
    parts = rest.split()
    if parts:
        st.match_id = parts[0]
    kv = _parse_kv(parts[1:])
    st.version = kv.get("v") if kv.get("v") not in (None, "-") else None
    st.pid = kv.get("pid") if kv.get("pid") not in (None, "-") else None
    st.team_id = kv.get("team")
    st.seed = kv.get("seed")
    st.dur = kv.get("dur") or 600


def _parse_f(st, rest):
    # r<round> <changes>
    parts = rest.split()
    if not parts:
        return
    rnd = _num(parts[0][1:]) if parts[0].startswith("r") else None
    new_state = st.cur_state
    new_node = st.cur_node
    for tok in parts[1:]:
        if tok.startswith("fr") and tok[2:].isdigit():
            t = int(tok[2:])
            if t not in st.bad_crossings:
                st.bad_crossings.append(t)
        elif tok.startswith("ofr") and tok[3:].isdigit():
            pass  # 对手跨越不入 me 的 badCrossings（parser 亦只记 me）
        elif tok.startswith("vfy=1"):
            if st.verify_frame is None:
                st.verify_frame = rnd
        elif tok.startswith("del=1"):
            pass
        elif tok.startswith("w="):
            st.weather_hit = True
        elif tok.startswith("ph="):
            ph = tok[3:]
            if ph == "RUSH" and st.rush_trigger is None:
                st.rush_trigger = rnd
            new_state = new_state  # phase 不影响 waiting
        elif tok.startswith("st="):
            new_state = tok[3:]
        elif tok.startswith("n="):
            new_node = tok[2:]
    # waiting 停滞推算
    _update_waiting(st, rnd, new_state, new_node)
    st.cur_state = new_state
    if new_node is not None:
        st.cur_node = new_node


def _update_waiting(st, rnd, new_state, new_node):
    if st.cur_state == "WAITING" and st.wait_start is not None:
        if new_state is not None and new_state != "WAITING":
            _close_wait(st, rnd)
        elif new_node is not None and st.wait_node is not None and new_node != st.wait_node:
            _close_wait(st, rnd)
    if new_state == "WAITING":
        if st.wait_start is None or st.wait_node != new_node:
            if st.wait_start is not None:
                _close_wait(st, rnd)
            st.wait_start = rnd
            st.wait_node = new_node


def _close_wait(st, rnd):
    if st.wait_start is None or rnd is None:
        st.wait_start = None
        st.wait_node = None
        return
    duration = rnd - st.wait_start
    if duration >= _WAITING_STALL:
        st.waiting_stuck.append({
            "fromFrame": st.wait_start,
            "toFrame": rnd - 1,
            "node": st.wait_node})
    st.wait_start = None
    st.wait_node = None


def _parse_a(st, rest):
    # r<round> <action> [k=v ...]
    parts = rest.split()
    if not parts:
        return
    rnd = _num(parts[0][1:]) if parts[0].startswith("r") else None
    act = parts[1] if len(parts) > 1 else None
    kv = _parse_kv(parts[2:])
    if act == "NONE":
        if "ms" in kv:
            st.decision_timeouts += 1
        return
    if "ms" in kv:
        st.decision_timeouts += 1
    if act == "USE_RESOURCE":
        res = kv.get("res")
        fresh = _num(kv.get("fresh"))
        if res == "ICE_BOX":
            st.ice_used.append({"frame": rnd,
                                "freshnessBefore": round(fresh, 2) if fresh is not None else None})
            st.timeline.append({"frame": rnd, "event": "USE_ICE",
                                "detail": "fresh=%s" % (round(fresh, 1) if fresh is not None else "?")})
        elif res in ("FAST_HORSE", "SHORT_HORSE"):
            st.horse_used = "%s@%s" % (res, rnd)
            st.timeline.append({"frame": rnd, "event": "USE_HORSE", "detail": res})
    elif act in ("RUSH_PROTECT", "RUSH_SPEED"):
        st.rush_tactic = {"type": act, "frame": rnd}
        st.timeline.append({"frame": rnd, "event": "RUSH_TACTIC", "detail": act})
    elif act == "CLAIM_TASK":
        st.task_claims.append({"template": None, "node": st.cur_node,
                               "frame": rnd, "detourExtra": None})
        st.timeline.append({"frame": rnd, "event": "TASK_CLAIM", "detail": "%s" % kv.get("task")})
    elif act == "BREAK_GUARD":
        node = kv.get("target")
        cost_good = _num(kv.get("good")) or 0
        st.opp_guards.append({"node": node, "frame": rnd,
                              "myResponse": "BREAK_GUARD",
                              "cost": {"good": cost_good, "frames": 0}})
        st.timeline.append({"frame": rnd, "event": "BREAKTHROUGH",
                            "detail": "BREAK_GUARD %s cost %d" % (node, cost_good)})
    elif act in ("CLEAR", "FORCED_PASS"):
        st.timeline.append({"frame": rnd, "event": "BREAKTHROUGH",
                            "detail": "%s %s" % (act, kv.get("target"))})
    elif act == "SET_GUARD":
        st.my_guards.append({"node": kv.get("target"), "frame": rnd,
                             "defense": None, "extraGood": kv.get("extra") or 0})
        st.timeline.append({"frame": rnd, "event": "SET_GUARD", "detail": "%s" % kv.get("target")})
    elif act == "WINDOW_CARD":
        st.windows.append({"frame": rnd, "type": kv.get("type"),
                           "contestId": kv.get("contest"),
                           "myCard": kv.get("card"), "oppCard": None, "result": None})
        st.timeline.append({"frame": rnd, "event": "WINDOW_CARD", "detail": "card=%s" % kv.get("card")})
    else:
        st.timeline.append({"frame": rnd, "event": "ACTION", "detail": "%s %s" % (act, kv.get("target"))})


def _parse_modechange(st, rest):
    # r<round> <from>-><to> reason=<r> gap=<g>
    parts = rest.split()
    if not parts:
        return
    rnd = _num(parts[0][1:]) if parts[0].startswith("r") else None
    trans = parts[1] if len(parts) > 1 else None
    frm = to = None
    if trans and "->" in trans:
        frm, to = trans.split("->", 1)
    kv = _parse_kv(parts[2:])
    st.mode_switches.append({"frame": rnd, "from": frm, "to": to,
                             "gap": _num(kv.get("gap")), "reason": kv.get("reason")})
    st.timeline.append({"frame": rnd, "event": "MODE_CHANGE", "detail": "%s->%s" % (frm, to)})


def _parse_guarddecision(st, rest):
    kv = _parse_kv(rest.split())
    if st.my_guards:
        g = st.my_guards[-1]
        g["defense"] = kv.get("defense")
        g["gap"] = _num(kv.get("gap"))
        g["denial"] = _num(kv.get("denial"))


def _parse_bounty(st, rest):
    kv = _parse_kv(rest.split())
    rec = {"frame": kv.get("r"), "target": kv.get("target"),
           "reward": _num(kv.get("reward")), "delta": _num(kv.get("delta")),
           "extraFrames": _num(kv.get("extra")), "action": kv.get("action"),
           "goodBurned": _num(kv.get("goodBurn")) or 0}
    st.bounties.append(rec)
    st.timeline.append({"frame": kv.get("r"), "event": "BOUNTY",
                        "detail": "%s reward=%s delta=%s %s" % (
                            kv.get("target"), kv.get("reward"), kv.get("delta"), kv.get("action"))})


def _parse_rej(st, rest):
    # r<first> x<count> <code> <action> <target>
    parts = rest.split()
    if len(parts) < 2:
        return
    first = _num(parts[0][1:]) if parts[0].startswith("r") else None
    count = 1
    idx = 1
    if parts[idx].startswith("x"):
        count = int(parts[idx][1:])
        idx += 1
    code = parts[idx] if idx < len(parts) else None
    idx += 1
    act = parts[idx] if idx < len(parts) else None
    idx += 1
    target = parts[idx] if idx < len(parts) else None
    for _ in range(count):
        st.rejected.append({"frame": first, "action": act, "code": code, "target": target})
    st.timeline.append({"frame": first, "event": "REJECTED",
                        "detail": "%s code=%s x%d" % (act, code, count)})


def _parse_cab(st, rest):
    parts = rest.split()
    if len(parts) < 2:
        return
    first = _num(parts[0][1:]) if parts[0].startswith("r") else None
    count = 1
    idx = 1
    if parts[idx].startswith("x"):
        count = int(parts[idx][1:])
        idx += 1
    act = parts[idx] if idx < len(parts) else None
    idx += 1
    reason = parts[idx] if idx < len(parts) else None
    idx += 1
    target = parts[idx] if idx < len(parts) else None
    for _ in range(count):
        if len(st.can_afford) < _CAB_CAP:
            st.can_afford.append({"frame": first, "action": act, "reason": reason, "target": target})


def _parse_traj(st, rest):
    kv = _parse_kv(rest.split())
    st.fstart = _num(kv.get("fstart"))
    st.fmin = _num(kv.get("fmin"))
    st.fend = _num(kv.get("fend"))
    st.gstart = _num(kv.get("gstart"))
    st.gend = _num(kv.get("gend"))
    st.onode = kv.get("onode")
    st.ofend = _num(kv.get("ofend"))
    st.ogend = _num(kv.get("ogend"))


def _parse_proj(st, rest):
    kv = _parse_kv(rest.split())
    st.last_my = _num(kv.get("my"))
    st.last_opp_deliver = _num(kv.get("oppDel"))
    st.last_gap = _num(kv.get("gap"))
    st.last_mode = kv.get("mode")


def _parse_conf(st, rest):
    kv = _parse_kv(rest.split())
    st.conf_min = _num(kv.get("min"))
    st.conf_med = _num(kv.get("med"))
    st.conf_max = _num(kv.get("max"))


def _parse_over(st, rest):
    kv = _parse_kv(rest.split())
    st.over = kv


def _parse_score(st, rest):
    # me|opp total=.. del=.. ...
    parts = rest.split()
    if not parts:
        return
    who = parts[0]
    kv = _parse_kv(parts[1:])
    score = {
        "total": _num(kv.get("total")) or 0,
        "delivered": kv.get("del"),
        "deliverRound": _num(kv.get("dframe")),
        "fresh": _num(kv.get("fresh")),
        "goodFruit": _num(kv.get("good")),
        "taskScore": _num(kv.get("task")) or 0,
        "bountyScore": _num(kv.get("bounty")) or 0,
        "scoreDetail": kv.get("det"),  # P1-A 透传
    }
    if who == "me":
        st.score_me = score
    else:
        st.score_opp = score


# --------------------------------------------------------------------------- #
# 组装 Report（与 parser.build_report 同 schema，复用其 helper 防漂移）        #
# --------------------------------------------------------------------------- #
class _AccShim:
    """给 parser._segments/_outcome 用的属性垫片。"""

    pass


def _build_compact_report(st):
    me = st.score_me or {}
    opp = st.score_opp or {}
    me_task_base = _num(me.get("taskScore")) or 0
    actual_me = _num(me.get("total")) or 0
    proj_error = (round(st.last_my - actual_me, 1)
                  if st.last_my is not None and actual_me else None)
    score_margin = None
    if st.score_me is not None and st.score_opp is not None:
        score_margin = (_num(me.get("total")) or 0) - (_num(opp.get("total")) or 0)

    # outcome（与 parser._outcome 同逻辑）
    outcome = _compute_outcome(st, me)

    # _segments 需要一个带 score_me/score_opp/mid_gap/weather_hit/contested 的 acc
    acc = _AccShim()
    acc.score_me = me
    acc.score_opp = opp
    acc.mid_gap = st.mid_gap
    acc.weather_hit = st.weather_hit
    acc.contested = bool(st.windows)

    opp_deliver = _num(opp.get("deliverRound"))
    fresh_end = st.fend if st.fend is not None else _num(me.get("fresh"))
    good_end = st.gend if st.gend is not None else _num(me.get("goodFruit"))

    return {
        "schemaVersion": SCHEMA_VERSION,
        "matchId": st.match_id,
        "playerId": st.pid,
        "teamId": st.team_id,
        "seed": st.seed,
        "clientVersion": st.version,
        "source": "platform",
        "variant": "baseline",
        "durationRound": st.dur,
        "outcome": outcome,
        "finalScore": {"me": _final_score(me), "opp": _final_score(opp)},
        "delivery": {
            "me": {"frame": _num(me.get("deliverRound")),
                   "verifyFrame": st.verify_frame,
                   "goodFruit": good_end,
                   "freshness": (round(fresh_end, 2) if fresh_end is not None else None)},
            "opp": {"frame": opp_deliver},
            "rushTriggerFrame": st.rush_trigger,
        },
        "tasks": {
            "me": {**_task_block(me), "claimed": st.task_claims},
            "opp": {**_task_block(opp), "claimed": []},
            "missedReachable90": None,
        },
        "resources": {"iceUsed": st.ice_used, "horseUsed": st.horse_used,
                      "rushTactic": st.rush_tactic},
        "trajectory": {
            "freshness": {"start": st.fstart, "end": fresh_end, "min": st.fmin},
            "goodFruit": {"start": st.gstart, "end": good_end,
                          "badCrossings": list(st.bad_crossings)},
            "opponent": {"freshnessEnd": (st.ofend if st.ofend is not None else _num(opp.get("fresh"))),
                         "goodFruitEnd": (st.ogend if st.ogend is not None else _num(opp.get("goodFruit"))),
                         "nodeEnd": st.onode},
        },
        "opponentInteraction": {"windows": st.windows, "oppGuards": st.opp_guards,
                                "bounties": st.bounties, "myGuards": st.my_guards},
        "failures": {"rejected": st.rejected, "waitingStuck": st.waiting_stuck,
                     "invalidActions": 0, "decisionTimeouts": st.decision_timeouts,
                     "canAffordBlocked": st.can_afford},
        "projection": {
            "modeSwitches": st.mode_switches,
            "confidence": {"min": st.conf_min, "median": st.conf_med, "max": st.conf_max},
            "projectedMyScore": st.last_my,
            "actualMyScore": actual_me or None,
            "error": proj_error,
            "oppEtaPredictedDeliver": st.last_opp_deliver,
            "oppActualDeliver": opp_deliver,
        },
        "classification": {
            "scoreMargin": score_margin,
            "luckClass": _luck_class(outcome, proj_error),
            "segments": _segments(acc, me_task_base),
        },
        "decisionTimeline": st.timeline,
    }


def _compute_outcome(st, me):
    over = st.over or {}
    if me.get("retired"):
        return "RETIRED"
    if not me.get("delivered"):
        return "UNDELIVERED"
    winner = over.get("winner")
    if winner is None:
        return "TIE"
    pid = st.pid
    if str(winner) == str(pid) or over.get("iWon") is True:
        return "WIN"
    return "LOSS"


# --------------------------------------------------------------------------- #
# b64（gzip+base64，聊天粘贴用）                                               #
# --------------------------------------------------------------------------- #
def to_b64(compact_text):
    """精简文本 → gzip+base64 字符串（~1.4KB/局，供聊天粘贴）。"""
    raw = compact_text.encode("utf-8")
    return base64.b64encode(gzip.compress(raw)).decode("ascii")


def from_b64(b64_text):
    return gzip.decompress(base64.b64decode(b64_text)).decode("utf-8")


# --------------------------------------------------------------------------- #
# 独立 CLI：python3 -m analysis.compact <logfile> [--b64]                      #
# --------------------------------------------------------------------------- #
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Derive a compact trace from a full match log.")
    ap.add_argument("logfile", help="path to match_*.log")
    ap.add_argument("--b64", action="store_true", help="emit gzip+base64 (for chat paste)")
    args = ap.parse_args(argv)
    text = compact_trace(args.logfile)
    if args.b64:
        print(to_b64(text))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

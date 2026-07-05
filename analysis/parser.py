"""trace 文本日志 → 结构化 MatchTrace。

行格式：``<HH:MM:SS.mmm> <Event> matchId=..., round=N, k=v, k=v``（match_logger.py）。
本解析器对缺失字段降级兼容：旧日志（无 opp/Block/Contest/Reject/Budget）也能解析。

一个 .log 文件可能含多次对局（本地 mock 以追加模式累积；真实平台下载为单场），
按 Startup 行切分会话，每会话产出一个 MatchTrace。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# 行首：时钟 + 事件名 + 剩余字段串
_LINE_RE = re.compile(r"^(\d\d:\d\d:\d\d\.\d+)\s+(\S+)\s+(.*)$")
# 字段切分：仅在 ", key=" 处切（值里含逗号也不误切）
_FIELD_SPLIT_RE = re.compile(r", (?=[A-Za-z_]\w*=)")


def _split_fields(s):
    """把 'matchId=x, round=3, k=v' 切成 [(key, value)]。"""
    out = []
    for piece in _FIELD_SPLIT_RE.split(s):
        if "=" not in piece:
            continue
        k, v = piece.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_bool(v):
    if v == "True":
        return True
    if v == "False":
        return False
    return None


def _parse_list(v):
    """[a|b|c] → [a, b, c]；非列表返回 None。"""
    if not v or not v.startswith("[") or not v.endswith("]"):
        return None
    inner = v[1:-1]
    if not inner:
        return []
    return inner.split("|")


@dataclass
class OppMirror:
    """Frame 行 opp= 字段解析：node|state|fresh|goodFruit|taskScore|verified|delivered。"""
    node: Optional[str] = None
    state: Optional[str] = None
    fresh: Optional[float] = None
    good_fruit: Optional[int] = None
    task_score: Optional[int] = None
    verified: Optional[bool] = None
    delivered: Optional[bool] = None

    @classmethod
    def parse(cls, raw):
        if raw is None or raw == "-":
            return cls()
        parts = raw.split("|")
        # 补齐到 7 段
        while len(parts) < 7:
            parts.append("-")

        def b(p):
            if p == "T":
                return True
            if p == "F":
                return False
            return None

        return cls(
            node=None if parts[0] == "-" else parts[0],
            state=None if parts[1] == "-" else parts[1],
            fresh=None if parts[2] == "-" else _to_float(parts[2]),
            good_fruit=None if parts[3] == "-" else _to_int(parts[3]),
            task_score=None if parts[4] == "-" else _to_int(parts[4]),
            verified=b(parts[5]),
            delivered=b(parts[6]),
        )


@dataclass
class Frame:
    round: Optional[int] = None
    phase: Optional[str] = None
    node: Optional[str] = None
    state: Optional[str] = None
    fresh: Optional[float] = None
    good_fruit: Optional[int] = None
    task_score: Optional[int] = None
    verified: Optional[bool] = None
    delivered: Optional[bool] = None
    weather: Optional[str] = None
    opp: Optional[OppMirror] = None
    events: list = field(default_factory=list)


@dataclass
class Action:
    round: Optional[int] = None
    action: Optional[str] = None
    target: Optional[str] = None
    task: Optional[str] = None
    resource: Optional[str] = None
    contest: Optional[str] = None
    card: Optional[str] = None
    rush: Optional[str] = None
    good: Optional[int] = None
    bad: Optional[int] = None
    extra_good: Optional[int] = None
    ms: Optional[float] = None


@dataclass
class Block:
    round: Optional[int] = None
    node: Optional[str] = None
    obstacle: Optional[str] = None
    guard_owner: Optional[str] = None
    guard_def: Optional[int] = None
    cleared: bool = False


@dataclass
class Contest:
    round: Optional[int] = None
    contest_id: Optional[str] = None
    type: Optional[str] = None
    ri: Optional[int] = None
    my_pt: Optional[int] = None
    opp_pt: Optional[int] = None
    my_card: Optional[str] = None
    opp_card: Optional[str] = None


@dataclass
class Reject:
    round: Optional[int] = None
    action: Optional[str] = None
    target: Optional[str] = None
    code: Optional[str] = None


@dataclass
class Budget:
    round: Optional[int] = None
    est: Optional[int] = None
    left: Optional[int] = None


@dataclass
class ScoreLine:
    player: Optional[int] = None
    me: bool = False
    total: Optional[int] = None
    delivered: bool = False
    deliver_round: Optional[int] = None
    retired: bool = False
    fresh: Optional[float] = None
    good_fruit: Optional[int] = None
    task_score: Optional[int] = None
    bounty_score: Optional[int] = None


@dataclass
class OverLine:
    result_type: Optional[str] = None
    reason: Optional[str] = None
    over_round: Optional[int] = None
    winner: Optional[int] = None
    i_won: Optional[bool] = None


@dataclass
class MatchMeta:
    match_id: Optional[str] = None
    player_id: Optional[int] = None
    duration_round: int = 600
    team_id: Optional[str] = None
    camp: Optional[str] = None
    gate: Optional[str] = None
    terminals: list = field(default_factory=list)
    process_nodes: list = field(default_factory=list)


@dataclass
class MatchTrace:
    meta: MatchMeta = field(default_factory=MatchMeta)
    frames: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    contests: list = field(default_factory=list)
    rejects: list = field(default_factory=list)
    budgets: list = field(default_factory=list)
    over: Optional[OverLine] = None
    scores: list = field(default_factory=list)
    raw_lines: int = 0


def parse_file(path):
    """解析 .log 文件，返回 MatchTrace 列表（按 Startup 切分；无 Startup 则整文件一场）。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return parse_text(text)


def parse_text(text):
    """解析多行文本，返回 MatchTrace 列表。"""
    sessions = []
    cur = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        _, event, _ = m.groups()
        if event == "Startup":
            if cur:
                sessions.append(cur)
            cur = [line]
        else:
            if not cur:
                cur = [line]  # 无 Startup 开头的孤儿行归为一场
            else:
                cur.append(line)
    if cur:
        sessions.append(cur)
    return [_parse_session(lines) for lines in sessions]


def _parse_session(lines):
    trace = MatchTrace()
    trace.raw_lines = len(lines)
    for line in lines:
        m = _LINE_RE.match(line)
        if not m:
            continue
        _, event, rest = m.groups()
        fields = dict(_split_fields(rest))
        _dispatch(trace, event, fields)
    return trace


def _dispatch(trace, event, f):
    if event == "Startup":
        trace.meta.player_id = _to_int(f.get("playerId"))
    elif event == "Start":
        trace.meta.team_id = f.get("teamId")
        trace.meta.camp = f.get("camp")
        trace.meta.duration_round = _to_int(f.get("durationRound")) or 600
        trace.meta.gate = f.get("gate")
        terms = _parse_list(f.get("terminals"))
        if terms is not None:
            trace.meta.terminals = terms
        pnodes = _parse_list(f.get("processNodes"))
        if pnodes is not None:
            trace.meta.process_nodes = pnodes
    elif event == "Frame":
        trace.frames.append(Frame(
            round=_to_int(f.get("round")),
            phase=f.get("phase"),
            node=f.get("node"),
            state=f.get("state"),
            fresh=_to_float(f.get("fresh")),
            good_fruit=_to_int(f.get("goodFruit")),
            task_score=_to_int(f.get("taskScore")),
            verified=_to_bool(f.get("verified")),
            delivered=_to_bool(f.get("delivered")),
            weather=f.get("weather"),
            opp=OppMirror.parse(f.get("opp")),
            events=_parse_list(f.get("events")) or [],
        ))
    elif event == "Action":
        trace.actions.append(Action(
            round=_to_int(f.get("round")),
            action=f.get("action"),
            target=f.get("target"),
            task=f.get("task"),
            resource=f.get("resource"),
            contest=f.get("contest"),
            card=f.get("card"),
            rush=f.get("rush"),
            good=_to_int(f.get("good")),
            bad=_to_int(f.get("bad")),
            extra_good=_to_int(f.get("extraGood")),
            ms=_to_float(f.get("ms")),
        ))
    elif event == "Block":
        trace.blocks.append(Block(
            round=_to_int(f.get("round")),
            node=f.get("node"),
            obstacle=f.get("obstacle"),
            guard_owner=f.get("guardOwner"),
            guard_def=_to_int(f.get("guardDef")),
            cleared=_to_bool(f.get("cleared")) is True,
        ))
    elif event == "Contest":
        trace.contests.append(Contest(
            round=_to_int(f.get("round")),
            contest_id=f.get("contestId"),
            type=f.get("type"),
            ri=_to_int(f.get("ri")),
            my_pt=_to_int(f.get("myPt")),
            opp_pt=_to_int(f.get("oppPt")),
            my_card=f.get("myCard"),
            opp_card=f.get("oppCard"),
        ))
    elif event == "Reject":
        trace.rejects.append(Reject(
            round=_to_int(f.get("round")),
            action=f.get("action"),
            target=f.get("target"),
            code=f.get("code"),
        ))
    elif event == "Budget":
        trace.budgets.append(Budget(
            round=_to_int(f.get("round")),
            est=_to_int(f.get("est")),
            left=_to_int(f.get("left")),
        ))
    elif event == "Over":
        winner = _to_int(f.get("winner"))
        trace.over = OverLine(
            result_type=f.get("resultType"),
            reason=f.get("reason"),
            over_round=_to_int(f.get("overRound")),
            winner=winner,
            i_won=_to_bool(f.get("iWon")),
        )
        trace.meta.match_id = trace.meta.match_id or f.get("matchId")
    elif event == "Score":
        trace.scores.append(ScoreLine(
            player=_to_int(f.get("player")),
            me=_to_bool(f.get("me")) is True,
            total=_to_int(f.get("total")),
            delivered=_to_bool(f.get("delivered")) is True,
            deliver_round=_to_int(f.get("deliverRound")),
            retired=_to_bool(f.get("retired")) is True,
            fresh=_to_float(f.get("fresh")),
            good_fruit=_to_int(f.get("goodFruit")),
            task_score=_to_int(f.get("taskScore")),
            bounty_score=_to_int(f.get("bountyScore")),
        ))
    # 从任意行补 matchId
    if trace.meta.match_id in (None, "-") and f.get("matchId") not in (None, "-"):
        trace.meta.match_id = f.get("matchId")

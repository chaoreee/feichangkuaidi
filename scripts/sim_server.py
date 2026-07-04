"""高保真自博弈仿真器编排 + 批量 CLI（Phase A，进程内）。

驱动两个真实 DecisionEngine（同进程）对 SimEngine 物理（core/rules.py）下棋，每帧为双方
构造 inquire → WorldState → engine.decide，回收动作喂 SimEngine.step。trace 复用
client/main.py 的 _log_* 辅助函数写出 → 与真实客户端同格式，analysis/parser.py 可读。

用法（单局）：
    python3 -m scripts.sim_server --seed 1 --variant baseline
用法（批量）：
    python3 -m scripts.sim_server --games 50 --seeds 1..50 --variant baseline [--out logs/sim/baseline]

输出：logs/sim/<variant>/match_<matchId>_<playerId>.log（每局两份，RED+BLUE）。
matchId = sim_<variant>_s<seed>，供聚合器按 seed 配对 A/B。

Phase A 范围（标"待完善/待真实 trace 验证"）：悬赏/窗口争夺留空；资源不动态刷新；
任务池 seed 合成；天气区域按路线类型近似。所有 sim 结论须标"待真实 trace 验证"。
"""

import argparse
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT = os.path.join(_ROOT, "client")
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
for _p in (_CLIENT, _ROOT, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
from core.game_map import GameMap  # noqa: E402
from core.world_state import WorldState  # noqa: E402
from logger.match_logger import MatchLogger  # noqa: E402
from strategy.decision import DecisionEngine, GameContext  # noqa: E402
from protocol.enums import Team, Phase  # noqa: E402
import main as client_main  # noqa: E402  -- 复用 _log_* trace 辅助

from sim_engine import SimEngine  # noqa: E402
from sim_validator import validate, SimReconcileError  # noqa: E402

_MAP = os.path.join(_ROOT, "samples", "map_config.json")
RED_ID = 1001
BLUE_ID = 2001


def load_map_config():
    with open(_MAP, encoding="utf-8") as fh:
        return json.load(fh)


def build_start_data(mc, match_id, seed):
    """合成 start 消息载荷（gameplay.roles + nodes/edges/processNodes/resources/taskTemplates）。"""
    return {
        "matchId": match_id, "rulesVersion": "sim", "round": 1, "tick": 0,
        "durationRound": 600, "seed": seed,
        "map": {"maxX": mc["map"]["maxX"], "maxY": mc["map"]["maxY"],
                "gameplay": {"roles": {"startNodeId": "S01", "gateNodeId": "S14",
                                       "terminalNodeIds": ["S15"], "safeZoneNodeIds": ["S15"]}}},
        "players": [{"playerId": RED_ID, "camp": 0, "teamId": Team.RED, "name": "sim-red"},
                    {"playerId": BLUE_ID, "camp": 1, "teamId": Team.BLUE, "name": "sim-blue"}],
        "nodes": mc["nodes"], "edges": mc["edges"], "processNodes": mc["processNodes"],
        "resources": [{"nodeId": r["nodeId"], "resourceType": r["resourceType"], "count": 1}
                      for r in mc.get("visibleResources", [])],
        "taskTemplates": [{"taskTemplateId": "T01", "score": 30},
                          {"taskTemplateId": "T02", "score": 30}],
    }


class _Side:
    """单侧编排状态：上下文 + 引擎 + 日志器。"""

    def __init__(self, player_id, team_id, camp, start_data, log_dir):
        self.player_id = player_id
        self.team_id = team_id
        self.logger = MatchLogger(log_dir, player_id)
        self.logger.trace("Startup", playerId=player_id, host="sim", port=0,
                          version=config.CLIENT_VERSION)
        self.logger.trace("Register", playerId=player_id, name=config.DEFAULT_PLAYER_NAME)
        self.logger.bind_match(start_data["matchId"])
        self.ctx = GameContext(player_id, team_id, camp, start_data)
        self.engine = DecisionEngine(self.ctx)


def play_one_game(seed, variant, out_dir, mc=None, max_rounds=600, verbose=False):
    """跑一局自博弈，写双方 trace，返回结果摘要 dict。"""
    if mc is None:
        mc = load_map_config()
    match_id = "sim_%s_s%d" % (variant, seed)
    start_data = build_start_data(mc, match_id, seed)
    game_map = GameMap(start_data)
    engine = SimEngine(start_data, game_map, seed=seed)

    os.makedirs(out_dir, exist_ok=True)
    red = _Side(RED_ID, Team.RED, 0, start_data, out_dir)
    blue = _Side(BLUE_ID, Team.BLUE, 1, start_data, out_dir)
    sides = {Team.RED: red, Team.BLUE: blue}

    # 开局 trace：Start / Map / Ready（双方各写一份）
    for s in sides.values():
        s.logger.trace("Start", teamId=s.team_id, camp=s.ctx.camp,
                       durationRound=start_data.get("durationRound"),
                       nodes=len(start_data.get("nodes", []) or []),
                       edges=len(start_data.get("edges", []) or []),
                       seed=start_data.get("seed"))
        client_main._log_map(s.logger, start_data)
        s.logger.trace("Ready", round=start_data.get("round") or 1)

    stuck = {Team.RED: False, Team.BLUE: False}
    last_pos = {Team.RED: red.engine and "S01", Team.BLUE: "S01"}
    stuck_since = {Team.RED: 0, Team.BLUE: 0}

    for rnd in range(1, max_rounds + 1):
        actions_by_team = {}
        for team, s in sides.items():
            inquire = engine.build_inquire(team)
            world = None
            try:
                world = WorldState(inquire, s.player_id, s.ctx.game_map)
            except Exception as exc:
                s.logger.trace("Error", round=rnd, error="parse_exception", detail=repr(exc))
            client_main._log_frame(s.logger, rnd, inquire, world)

            t0 = time.perf_counter()
            acts = []
            if world is not None:
                try:
                    acts = s.engine.decide(world)
                except Exception as exc:
                    s.logger.trace("Error", round=rnd, error="decide_exception", detail=repr(exc))
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

            if world is not None:
                client_main._log_projection(s.logger, rnd, s.engine)
            client_main._log_actions(s.logger, rnd, acts, elapsed_ms, world, s.engine)
            client_main._log_engine_events(s.logger, rnd, s.engine)
            actions_by_team[team] = acts

        engine.step(actions_by_team)

        # 卡死检测：位置长时间不变且未交付/未退赛
        for team in (Team.RED, Team.BLUE):
            p = engine.players[team]
            if p.delivered or p.retired:
                continue
            if p.pos == last_pos[team] and p.state in ("WAITING", "IDLE", "PROCESSING", "VERIFYING"):
                if stuck_since[team] == 0:
                    stuck_since[team] = rnd
                elif rnd - stuck_since[team] >= 120:
                    stuck[team] = True
            else:
                stuck_since[team] = 0
            last_pos[team] = p.pos

        if engine.is_ended():
            break

    # 结算 trace：Over + Score（双方各写一份，含对手分）
    over_data = engine.build_over_data()
    for team, s in sides.items():
        client_main._log_over(s.logger, s.player_id, over_data)
        s.logger.trace("Shutdown")
        s.logger.close()

    # 对账自检（over_data 报告分 vs rules 重算）
    recon_ok = True
    recon_msg = ""
    try:
        validate(engine, over_data)
    except SimReconcileError as exc:
        recon_ok = False
        recon_msg = str(exc)

    summary = _summary(engine, match_id, seed, variant, stuck, recon_ok, recon_msg)
    if verbose:
        print("[%s] %s" % (match_id, _fmt_summary(summary)))
    return summary


def _summary(engine, match_id, seed, variant, stuck, recon_ok, recon_msg):
    rs = engine.final_score(Team.RED)
    bs = engine.final_score(Team.BLUE)
    return {
        "matchId": match_id, "seed": seed, "variant": variant,
        "round": engine.round, "phase": engine.phase,
        "RED": {"delivered": engine.players[Team.RED].delivered,
                "deliverRound": engine.players[Team.RED].deliver_round,
                "score": rs["total"], "task": engine.players[Team.RED].task_score,
                "fresh": round(engine.players[Team.RED].freshness, 2),
                "good": engine.players[Team.RED].good_fruit, "stuck": stuck[Team.RED]},
        "BLUE": {"delivered": engine.players[Team.BLUE].delivered,
                 "deliverRound": engine.players[Team.BLUE].deliver_round,
                 "score": bs["total"], "task": engine.players[Team.BLUE].task_score,
                 "fresh": round(engine.players[Team.BLUE].freshness, 2),
                 "good": engine.players[Team.BLUE].good_fruit, "stuck": stuck[Team.BLUE]},
        "recon_ok": recon_ok, "recon_msg": recon_msg,
    }


def _fmt_summary(s):
    return ("RED del=%s r=%s score=%d task=%d | BLUE del=%s r=%s score=%d task=%d | "
            "round=%d recon=%s stuck=%s/%s" % (
                s["RED"]["delivered"], s["RED"]["deliverRound"], s["RED"]["score"], s["RED"]["task"],
                s["BLUE"]["delivered"], s["BLUE"]["deliverRound"], s["BLUE"]["score"], s["BLUE"]["task"],
                s["round"], s["recon_ok"], s["RED"]["stuck"], s["BLUE"]["stuck"]))


def run_batch(games, seed_start, variant, out_dir, verbose=False):
    mc = load_map_config()
    summaries = []
    t0 = time.time()
    for i in range(games):
        seed = seed_start + i
        s = play_one_game(seed, variant, out_dir, mc, verbose=verbose)
        summaries.append(s)
    _print_batch_report(summaries, time.time() - t0)
    # 退出码：对账失败或卡死回归 → 非 0
    bad = [s for s in summaries if not s["recon_ok"]]
    stucked = [s for s in summaries if s["RED"]["stuck"] or s["BLUE"]["stuck"]]
    return 0 if not bad and not stucked else 1


def _print_batch_report(summaries, elapsed):
    n = len(summaries)
    both = []
    for s in summaries:
        both.append(("RED", s["RED"], s))
        both.append(("BLUE", s["BLUE"], s))
    delivered = sum(1 for _, p, _ in both if p["delivered"])
    deliver_frames = [p["deliverRound"] for _, p, _ in both if p["delivered"]]
    scores = [p["score"] for _, p, _ in both]
    recon_fail = sum(1 for s in summaries if not s["recon_ok"])
    stucked = sum(1 for s in summaries if s["RED"]["stuck"] or s["BLUE"]["stuck"])

    def _stats(vals):
        if not vals:
            return "n=0"
        vals = sorted(vals)
        import statistics
        return "n=%d min=%d median=%.0f mean=%.1f max=%d" % (
            len(vals), vals[0], statistics.median(vals), statistics.mean(vals), vals[-1])

    print("=" * 60)
    print("Sim batch: N=%d matches (%d player-games)  variant=%s  %.1fs" % (
        n, len(both), summaries[0]["variant"] if summaries else "?", elapsed))
    print("DELIVERY_RATE: %.3f (%d/%d)" % (delivered / len(both), delivered, len(both)))
    print("DELIVERY_FRAME: %s" % _stats(deliver_frames))
    print("SCORE: %s" % _stats(scores))
    print("RECON_FAIL: %d   STUCK: %d" % (recon_fail, stucked))
    if recon_fail:
        for s in summaries:
            if not s["recon_ok"]:
                print("  recon-fail %s: %s" % (s["matchId"], s["recon_msg"][:120]))
    if stucked:
        for s in summaries:
            if s["RED"]["stuck"] or s["BLUE"]["stuck"]:
                print("  stuck %s: RED=%s BLUE=%s round=%d" % (
                    s["matchId"], s["RED"]["stuck"], s["BLUE"]["stuck"], s["round"]))
    print("=" * 60)


def main(argv):
    ap = argparse.ArgumentParser(description="High-fidelity in-process self-play simulator (Phase A).")
    ap.add_argument("--games", type=int, default=1, help="number of matches to play")
    ap.add_argument("--seed", type=int, default=None, help="single seed (overrides --seeds)")
    ap.add_argument("--seeds", type=str, default="1..50", help="seed range 'start..end' (inclusive)")
    ap.add_argument("--variant", type=str, default="baseline", help="variant tag (baseline/tuned/...)")
    ap.add_argument("--out", type=str, default=None, help="output dir (default logs/sim/<variant>)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.seed is not None:
        seed_start = args.seed
        games = 1
    else:
        lo, hi = args.seeds.split("..")
        seed_start = int(lo)
        games = args.games if args.games else (int(hi) - int(lo) + 1)

    out_dir = args.out or os.path.join(_ROOT, "logs", "sim", args.variant)
    return run_batch(games, seed_start, args.variant, out_dir, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""SimValidator —— 赛后对账自检：用 core/rules.py 从引擎终态原始字段独立重算终局分，
与 sim 报告的 over_data 逐项对账，断言 0 误差。

sim 的 final_score 与 over_data totalScore 是两条独立代码路径（_score_detail vs
_player_over 写入），对账确保二者一致——catch 报告分与规则镜像分脱钩的 bug。不匹配
抛 SimReconcileError 并打印差异。与 analysis 聚合器的 rules.py 对账形成双保险。
"""

from core import rules
from protocol.enums import Team


class SimReconcileError(AssertionError):
    pass


def _recompute(p):
    """从玩家原始字段独立重算终局分项。"""
    if p.delivered:
        detail = {
            "delivery": rules.delivery_base_score(p.task_score),
            "task": rules.task_score(p.task_score, delivered=True),
            "time": rules.time_score(p.deliver_round, p.task_score),
            "goodFruit": rules.good_fruit_score(p.good_fruit),
            "freshness": rules.freshness_score(p.freshness),
            "bounty": rules.bounty_score(p.bounty_score, delivered=True),
            "penalty": p.penalty_score,
        }
    else:
        detail = {
            "delivery": 0, "time": 0, "goodFruit": 0, "freshness": 0,
            "task": rules.task_score(p.task_score, delivered=False),
            "bounty": rules.bounty_score(p.bounty_score, delivered=False),
            "penalty": p.penalty_score,
        }
    detail["total"] = rules.total_score(
        [detail["delivery"], detail["task"], detail["time"],
         detail["goodFruit"], detail["freshness"], detail["bounty"]],
        detail["penalty"])
    return detail


def validate(engine, over_data=None):
    """对账：over_data 中每个玩家的 totalScore 必须与 rules 独立重算一致。

    over_data 为 None 时仅做内部自洽检查（final_score vs recompute，必通过）。
    """
    issues = []
    # 内部自洽：final_score 与 _recompute 必一致（两条公式路径）
    for team in (Team.RED, Team.BLUE):
        p = engine.players[team]
        recomputed = _recompute(p)
        sim_detail = engine.final_score(team)
        for k in ("delivery", "task", "time", "goodFruit", "freshness", "bounty", "total"):
            if recomputed.get(k) != sim_detail.get(k):
                issues.append("internal team=%s field=%s recompute=%s final_score=%s"
                              % (team, k, recomputed.get(k), sim_detail.get(k)))
    # over_data 对账：报告分 vs rules 重算
    if over_data is not None:
        for op in over_data.get("players", []):
            pid = op.get("playerId")
            team = next((t for t, p in engine.players.items() if p.player_id == pid), None)
            if team is None:
                issues.append("over_data playerId=%s not in engine" % pid)
                continue
            recomputed = _recompute(engine.players[team])
            if op.get("totalScore") != recomputed["total"]:
                issues.append("over_data team=%s reported totalScore=%s but rules recompute=%s"
                              % (team, op.get("totalScore"), recomputed["total"]))
    if issues:
        raise SimReconcileError("score reconciliation failed:\n  " + "\n  ".join(issues))
    return {
        Team.RED: engine.final_score(Team.RED)["total"],
        Team.BLUE: engine.final_score(Team.BLUE)["total"],
    }

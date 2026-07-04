"""对手策略分类器（analysis 侧，纯观测，假设级）。

用 P1-A 已抽到的对手逐帧轨迹 / 用冰 / 设卡，把每局对手打一个类标签，供 aggregator
按对手类分桶做群体归因（`docs/iteration_loop_design.md` §0.5）。**只抽取事实、不做优化、
不出建议**。阈值取物理含义（鲜度 85 = 一次好果跨越线、好果 95 = 实质量满），**不扫参数**；
N<30 标「假设级」，Iter 33+ 真实数据回流后再校准。

三类（design §0.5，互斥全覆盖，优先级 guard > quality > speed）：
- **guard-type**：对手至少设卡一次（`oppGuards` 非空）。二值、物理清晰——进攻性设卡是对手
  主动选择的强信号，覆盖一切路线型归类。
- **quality-route**：鲜度积累型 —— `freshnessEnd ≥ 85` 且（`goodFruitEnd ≥ 95` 或 `iceUsed` 非空）。
  对手把 spare-time 投入保鲜/好果积累而非抢交付。
- **speed-route**：其余 —— 快交付 / 低鲜度 / 低任务型。

旧 trace 无对手字段（freshnessEnd 与 oppGuards 均 None/空）→ `unknown`，不崩。
"""

# 物理含义阈值（不扫参数；N<30 标假设级，待 Iter 33+ 真实数据校准）
QUALITY_FRESH = 85.0   # 一次好果→坏果跨越线（90/80/70…）之上，保鲜有效
QUALITY_GOOD = 95      # 实质量满附近

CLASS_GUARD = "guard-type"
CLASS_QUALITY = "quality-route"
CLASS_SPEED = "speed-route"
CLASS_UNKNOWN = "unknown"


def _opp_trajectory(report):
    return (report.get("trajectory") or {}).get("opponent") or {}


def _opp_guards(report):
    return (report.get("opponentInteraction") or {}).get("oppGuards") or []


def classify_opponent(report):
    """对单局对手打类标签。

    返回 ``{"class": str, "signals": dict}``。``signals`` 记录判定依据（freshnessEnd /
    goodFruitEnd / iceUsedCount / oppGuardCount / oppDeliverFrame / oppTaskBase），供归因下钻。
    """
    traj = _opp_trajectory(report)
    guards = _opp_guards(report)
    fresh_end = traj.get("freshnessEnd")
    good_end = traj.get("goodFruitEnd")
    ice_used = traj.get("iceUsed") or []
    opp_deliver = ((report.get("delivery") or {}).get("opp") or {}).get("frame")
    opp_task = ((report.get("tasks") or {}).get("opp") or {}).get("base")

    signals = {
        "freshnessEnd": fresh_end,
        "goodFruitEnd": good_end,
        "iceUsedCount": len(ice_used),
        "oppGuardCount": len(guards),
        "oppDeliverFrame": opp_deliver,
        "oppTaskBase": opp_task,
    }

    # 旧 trace 无对手鲜度且无设卡 → 无法判
    if fresh_end is None and not guards:
        return {"class": CLASS_UNKNOWN, "signals": signals}

    # 优先级 1：设卡型（进攻性设卡是主动强信号，覆盖路线型归类）
    if guards:
        return {"class": CLASS_GUARD, "signals": signals}

    # 优先级 2：鲜度积累型
    if fresh_end is not None and fresh_end >= QUALITY_FRESH:
        if (good_end is not None and good_end >= QUALITY_GOOD) or ice_used:
            return {"class": CLASS_QUALITY, "signals": signals}

    # 优先级 3：速度型（其余）
    return {"class": CLASS_SPEED, "signals": signals}


def annotate_opp_class(report):
    """把对手类标签注入 report 的 classification（就地修改并返回 report）。

    幂等：已存在 ``opponentClass`` 则不重算（除非 force）。供 ``__main__`` 在写 report.json
    前统一调用，使单局 report / index / 聚合报告共享同一标签。
    """
    cls = classify_opponent(report)
    report.setdefault("classification", {})["opponentClass"] = cls["class"]
    report.setdefault("classification", {}).setdefault("oppClassSignals", cls["signals"])
    return report

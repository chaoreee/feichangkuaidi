"""Layer 2 档位参数映射（docs/game_theory_projection_strategy.md §5.1）。

把写死的策略常量按风险档位 `RiskMode` 映射为一组可调参数 `StrategyTuning`。
EVEN 档**严格复用** config 既有默认值，保证在信息不足/均衡时行为与现状完全一致。

铁律（§5.1）：三档只调"意愿/上限"，**不改变**"必过 `_can_afford`（时间地板）
且必过 ΔEV 地板（分数地板）"这条与门——AGGRESSIVE 也不例外，
`action_min_net_score` 三档均不得为负。

本模块是只读配置工厂；是否消费它、以及消费的时机由决策层按落地阶段决定
（P1 纯观测阶段不消费，保证端到端不变）。
"""

from dataclasses import dataclass

import config
from strategy.projection import RiskMode


@dataclass(frozen=True)
class StrategyTuning:
    mode: RiskMode
    task_seek_target: int              # §5.1 行1：为任务绕路的上限（任务分达此值即不再绕路）
    task_detour_max_extra_frames: int  # §5.1 行2：绕路做任务允许的最大额外帧
    action_min_net_score: float        # §3.3：增量动作的最低净收益门槛 ΔEV（分数质量地板）
    rush_protect_freshness_below: float  # §5.1 行4：护果令触发的鲜度阈值（低于即用）
    protect_good_fruit_on_breakthrough: bool  # §5.1 行3：突破时优先不烧好果（FORCED_PASS）


def tuning_for_mode(mode):
    """按档位返回一组策略参数。未知档位回落 EVEN。"""
    if mode == RiskMode.CONSERVATIVE:
        return StrategyTuning(
            mode=RiskMode.CONSERVATIVE,
            task_seek_target=config.CONSERVATIVE_TASK_SEEK_TARGET,
            task_detour_max_extra_frames=config.CONSERVATIVE_TASK_DETOUR_MAX_EXTRA_FRAMES,
            action_min_net_score=config.ACTION_MIN_NET_SCORE_CONSERVATIVE,
            rush_protect_freshness_below=config.RUSH_PROTECT_FRESHNESS_BELOW,
            protect_good_fruit_on_breakthrough=True,   # 领先锁好果：能负担时间税则优先 FORCED_PASS
        )
    if mode == RiskMode.AGGRESSIVE:
        return StrategyTuning(
            mode=RiskMode.AGGRESSIVE,
            task_seek_target=config.AGGRESSIVE_TASK_SEEK_TARGET,
            task_detour_max_extra_frames=config.AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES,
            action_min_net_score=config.ACTION_MIN_NET_SCORE_AGGRESSIVE,
            rush_protect_freshness_below=config.AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW,
            protect_good_fruit_on_breakthrough=False,  # 落后争速：允许烧好果攻坚更快通过
        )
    # EVEN：复用既有默认，等价于现状（ΔEV 地板除外——地板是 P2 起对所有档位的新增守卫）。
    return StrategyTuning(
        mode=RiskMode.EVEN,
        task_seek_target=config.TASK_SEEK_TARGET,
        task_detour_max_extra_frames=config.TASK_DETOUR_MAX_EXTRA_FRAMES,
        action_min_net_score=config.ACTION_MIN_NET_SCORE,
        rush_protect_freshness_below=config.RUSH_PROTECT_FRESHNESS_BELOW,
        protect_good_fruit_on_breakthrough=False,      # 保持现状（烧好果攻坚）
    )

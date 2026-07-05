"""运行期对手类追踪器（Iter 37 §1，纯观测）。

每帧从 ``world`` 累积对手可观测信号（设卡次数 / 用冰次数 / 鲜度 min&last / 好果 last /
任务 last / 交付帧），给出运行期对手类估计。判定阈值与 ``analysis/opponent_classifier.py``
一致——**SSOT 在 analysis 侧**，此处为 client 自包含镜像（client 不可 import analysis，
纯 stdlib 提交件）。两类判定必一致，赛后可对账验证。

目的（§1）：①验证运行期分类与赛后离线分类一致 ②定位分类稳定点（为 §2 对手类驱动策略
切换的门控做准备）。**纯观测、不改任何动作**；每帧 class 经 ``main._log_projection`` 写入
``Projection`` trace 行的 ``oppClass`` 字段，parser 取末帧作 ``runtimeOpponentClass``。

三类（互斥全覆盖，优先级 guard > quality > speed，与 analysis 侧相同）：
- guard-type：对手至少设卡一次；
- quality-route：latest 鲜度 ≥ 85 且（好果 ≥ 95 或用过冰鉴）；
- speed-route：其余。

运行期与赛后差异：鲜度/好果用 latest（终局前仍在变化），故 class 在中段可能翻转、终局
稳定——这正是 §1 要观测的稳定点。冰鉴用「库存单调递减」推断使用次数（设卡同法：新出现的
对手设卡节点计数）。
"""

# 阈值镜像（SSOT: analysis/opponent_classifier.py，改其一须同步）
QUALITY_FRESH = 85.0
QUALITY_GOOD = 95
CLASS_GUARD = "guard-type"
CLASS_QUALITY = "quality-route"
CLASS_SPEED = "speed-route"
CLASS_UNKNOWN = "unknown"


class OpponentTracker:
    """每帧 ``update(world)`` 累积信号；``classify()`` 返回 ``(class, signals)``。

    无 world.opponent 时（如 1v1 之外或解析异常）安全跳过，class 保持 unknown。
    """

    def __init__(self):
        self.opp_guard_placements = 0      # 对手新设卡次数（节点新出现对手 active guard）
        self._prev_opp_guard_nodes = None  # 上一帧对手设卡节点集；None=首帧不计数
        self.opp_ice_uses = 0              # 对手 ICE_BOX 库存递减总量
        self._prev_opp_ice = None          # 上一帧对手 ICE_BOX 库存
        self.opp_fresh_min = None
        self.opp_fresh_last = None
        self.opp_good_last = None
        self.opp_task_last = None
        self.opp_deliver_frame = None
        self.frames_observed = 0

    def update(self, world):
        opp = getattr(world, "opponent", None)
        if opp is None:
            return
        self.frames_observed += 1
        me_team = getattr(getattr(world, "me", None), "team_id", None)

        # 设卡：扫描节点 active guard owner != 我方 → 对手设卡节点集；新增计数
        cur_guard_nodes = set()
        for nid, ns in (getattr(world, "node_states", None) or {}).items():
            owner = ns.active_guard_owner() if hasattr(ns, "active_guard_owner") else None
            if owner is not None and owner != me_team:
                cur_guard_nodes.add(nid)
        if self._prev_opp_guard_nodes is not None:
            self.opp_guard_placements += len(cur_guard_nodes - self._prev_opp_guard_nodes)
        self._prev_opp_guard_nodes = cur_guard_nodes

        # 用冰：ICE_BOX 库存递减量累计（领冰会先增，仅递减段计为使用）
        ice = (opp.resources or {}).get("ICE_BOX")
        if ice is None:
            ice = 0
        if self._prev_opp_ice is not None and ice < self._prev_opp_ice:
            self.opp_ice_uses += (self._prev_opp_ice - ice)
        self._prev_opp_ice = ice

        # 鲜度 / 好果 / 任务：取 latest，鲜度另记 min
        if opp.freshness is not None:
            self.opp_fresh_last = opp.freshness
            if self.opp_fresh_min is None or opp.freshness < self.opp_fresh_min:
                self.opp_fresh_min = opp.freshness
        if opp.good_fruit is not None:
            self.opp_good_last = opp.good_fruit
        if opp.task_score is not None:
            self.opp_task_last = opp.task_score

        # 交付帧：对手 delivered 首次为 True 的回合
        if self.opp_deliver_frame is None and getattr(opp, "delivered", False):
            self.opp_deliver_frame = getattr(world, "round", None)

    def classify(self):
        """返回 ``(class, signals_dict)``。latest 鲜度作 end 代理（终局前仍变）。"""
        fresh = self.opp_fresh_last
        good = self.opp_good_last
        guards = self.opp_guard_placements
        ice = self.opp_ice_uses

        if fresh is None and guards == 0:
            cls = CLASS_UNKNOWN
        elif guards > 0:
            cls = CLASS_GUARD
        elif fresh is not None and fresh >= QUALITY_FRESH:
            if (good is not None and good >= QUALITY_GOOD) or ice > 0:
                cls = CLASS_QUALITY
            else:
                cls = CLASS_SPEED
        else:
            cls = CLASS_SPEED

        signals = {
            "freshnessEnd": fresh,
            "goodFruitEnd": good,
            "iceUsedCount": ice,
            "oppGuardCount": guards,
            "oppDeliverFrame": self.opp_deliver_frame,
            "oppTaskBase": self.opp_task_last,
            "framesObserved": self.frames_observed,
            "freshnessMin": self.opp_fresh_min,
        }
        return cls, signals

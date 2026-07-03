# 博弈投影驱动策略设计与实现说明

> 主题：静态最优解 + 对手投影调节层。
> 目标：在不削弱现有 delivery-first 安全基线的前提下，把 `world.opponent` 纳入每帧决策，用投影分差驱动风险档位切换，逐步提升胜率与最高分上限。
> 状态：设计文档，后续实现需按阶段进入 `client/`，并在每次能力变化后同步更新 `AGENTS.md` 能力矩阵与迭代日志。

---

## 1. 背景与问题

当前策略已经具备稳定交付、时间感知路由、任务/资源收益、遇阻突破、防卡死续行等能力。它的核心优势是稳：所有动作围绕“确保交付”展开，且通过 `_keep_moving`、`_can_afford`、`time_optimal_path` 避免卡死和超时。

但现状仍偏“单机最优 + 反应式避让”：对手主要被视为动态环境的一部分，例如对方设卡后再绕行或突破，而不是一个会影响我方最优选择的博弈对象。`WorldState.opponent` 中的对手位置、任务分、鲜度、好果、是否验核、移动进度等信息尚未形成决策总线。

本方案的核心改造不是推翻 delivery-first，而是在其上增加一层“对手投影驱动的风险档位切换”：

- 对手慢、我方领先时，自动更保守，锁定已形成的优势。
- 对手快、我方落后时，自动更进取，争取任务分、悬赏、终局抢交付等增量。
- 对手不可预测或信息不足时，回到现有基线，不让上层博弈动作破坏交付下限。

### 1.1 时序前提（关键）

**真实平台交付帧基本在 450 之后**（mock 仿真里 ~r48–r55 就交付是简化模型的产物，不代表实战，禁止据此判断）。这意味着：

- 存在约 450 帧的漫长争夺中局——对手的位置、任务分、鲜度不是背景噪声，而是长期影响我方最优选择的博弈对象。因此本方案的 Layer 1（投影总线）与 Layer 3（任务/鲜度/资源 race）有**真实价值**，不是投机。
- 交付在 450+ 意味着到 600 帧只剩约 150 帧余量，**时间轴本就很紧**。任何"更进取"的绕路/攻坚都同时压迫时间红线，AGGRESSIVE 档必须比直觉更克制（见 §5.1、§9）。

### 1.2 信息可见性前提

本游戏为**全信息对抗**：协议 §7 的 `inquire.players[]` 对**双方**下发 `freshness / goodFruit / taskScore / verified / moveProgress / currentNodeId` 等全字段（`core/world_state.py` 的 `PlayerView` 已全解析），无战争迷雾。所以"投影对手终局分"在数据上可行。**唯一不可观测的是对手的意图/路线选择**——这决定了对手投影的 `confidence`：位置可见，去向靠推断（见 §4.4）。

### 1.3 现有安全地板只守时间、不守分数质量（本方案要补的最大缺口）

现有 `_can_afford` 只判断"做完额外动作后是否仍能在 600 帧内交付"，它是**时间预算守卫，不是分数守卫**。它无法阻止一个"时间够、但净分为负"的动作——例如为一点任务分绕远路烧掉好果与鲜度。历史上 commit 839cfc9 / Iteration 8 的真实败局正源于"过度贪任务/烧好果"这一失败模式。

因此本方案在时间地板之外**新增一道分数质量地板**：任何上层增量动作在执行前，必须用 `core/rules.py` 估算其对**投影终局分的净影响 ΔEV**，只有 `ΔEV ≥ 0`（或超过设定阈值）才执行。这是让 AGGRESSIVE 档不重蹈覆辙的核心约束（见 §3.3、§5、§9）。

## 2. 总体范式

策略分为 5 层。上层只调节风险偏好和机会选择，不允许绕过底层安全约束。

```text
Layer 0  安全地板
  _keep_moving / _can_afford / time_optimal_path
  所有上层动作必须通过这些约束。

Layer 1  投影总线
  my_proj / opp_proj -> gap -> mode
  mode in {CONSERVATIVE, EVEN, AGGRESSIVE}

Layer 2  低风险增量
  档位参数调节 / 悬赏机会主义 / 终局交付 race / 窗口 EV

Layer 3  中风险博弈
  对手轨迹 ETA / 任务分 race / 鲜度与好果 race

Layer 4  高风险主动进攻
  条件化 SET_GUARD，仅在锁胜场景启用
```

设计铁律：

- 任何新增动作仍必须经过 `_can_afford` 时间预算守卫（守时间下限）。
- 任何新增增量动作还必须经过**分数质量地板 `ΔEV ≥ 0`**（守分数下限）——只靠时间守卫不足以防”时间够但净分为负”的动作（见 §3.3）。
- 任何移动相关逻辑不得削弱 `_keep_moving` 的主动续行能力。
- 对手逻辑只决定”是否更保守或更进取”，不决定”是否放弃交付”。
- 无法可靠估计时，默认 `EVEN`，保持当前策略行为。

## 3. Layer 0：安全地板

Layer 0 保持现状，不作为本方案首轮改造目标。

### 3.1 核心约束

| 约束 | 职责 | 不变量 |
|---|---|---|
| `_keep_moving` | `MOVING/WAITING` 每帧主动续行或重规划 | 交付前不得因空动作卡死 |
| `_can_afford` | 判断额外动作后是否仍能在 600 帧内交付 | 上层收益动作不得压垮交付 |
| `time_optimal_path` | 以帧数为权重选择时间最优路线 | 上层只改变候选目标或 blocked 集合 |

### 3.2 实现要求

- 不新增绕开 `_can_afford` 的动作出口。
- 不让 `mode=AGGRESSIVE` 直接覆盖终点交付优先级。
- 不让 `mode=CONSERVATIVE` 禁用必要突破，若不突破会无法交付，则仍按现有保底逻辑执行。

### 3.3 分数质量地板（新增安全约束）

`_can_afford` 只回答"时间够不够"，不回答"这个动作是否让我方最终得分更高"。本方案要求所有 Layer 2-4 的**增量**动作（绕路任务、悬赏破卡、抢/deny 资源、主动设卡等；不含保交付的必要动作）在执行前额外通过一道分数质量守卫。

```text
ΔEV = proj_score(采取该动作) - proj_score(不采取该动作)
     其中两侧投影分均用 core/rules.py 纯函数计算，
     计入该动作带来的：任务分/悬赏分增量、
     以及其代价——额外耗时导致的用时分下降、
     烧好果导致的好果数量分下降、
     额外鲜度损耗（含跨阈值转坏）导致的鲜度分下降。

执行条件： ΔEV >= ACTION_MIN_NET_SCORE  （默认 0，可按档位/动作类型抬高）
```

要点：

- 建议实现为 `client/strategy/` 下一个纯函数 `net_score_delta(world, action_plan)`，只读投影总线与 `core/rules.py`，无副作用，便于单测。
- 这是"必须同时通过时间地板与分数地板"的与门：`_can_afford(...) and net_score_delta(...) >= threshold`。
- 保交付的必要动作（推进、验核、防卡死续行、避免无法交付的必要突破）**不受**此地板约束——地板只管"可选增量"，不管"交付下限"。
- CONSERVATIVE 档可把 `ACTION_MIN_NET_SCORE` 抬高（要求更高确定收益才动），AGGRESSIVE 档可略降但**不得为负**——即"更进取"只放宽下限，绝不允许做净负分动作。

## 4. Layer 1：投影总线

Layer 1 是本方案最高价值的基础设施。它每帧基于当前世界状态投影双方终局分与预计交付帧，再计算分差和风险档位。后续 Layer 2-4 都只读取它，不重复实现各自的对手判断。

### 4.1 数据结构建议

建议在 `client/strategy/` 下新增独立模块，例如 `projection.py`，避免把 `decision.py` 继续膨胀。

```python
@dataclass(frozen=True)
class Projection:
    player_id: str
    deliver_frame: int | None
    projected_score: float
    projected_good_fruit: int
    projected_freshness: float
    projected_task_score: int
    projected_bounty_score: int
    route: tuple[str, ...]
    confidence: float

class RiskMode(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    EVEN = "EVEN"
    AGGRESSIVE = "AGGRESSIVE"

@dataclass(frozen=True)
class ProjectionBus:
    my_projection: Projection
    opponent_projection: Projection | None
    gap: float
    mode: RiskMode
    reason: str
```

### 4.2 投影分计算

投影终局分应复用 `core/rules.py` 的纯函数，避免复制公式。

```text
proj_score =
  delivery_base_score(task_base)
  + good_fruit_score(proj_good_fruit)
  + freshness_score(proj_freshness)
  + time_score(proj_deliver_frame, task_base)
  + task_score(task_base, delivered=True)
  + bounty_score(proj_raw_bounty)
  - penalty
```

投影字段说明：

- `proj_deliver_frame`：当前 `round` + 从当前位置到交付的预计耗时。
- `proj_good_fruit`：当前好果数减去预计跨越鲜度阈值触发的转坏数量。
- `proj_freshness`：当前鲜度减去沿途按路线类型累计的鲜度损耗。
- `task_base`：当前任务分，可叠加确定性很高的顺路任务分。
- `proj_raw_bounty`：已确定或高度确定能顺路获取的悬赏原始分。
- `penalty`：已知惩罚或 actionResults 中可归因的惩罚。

### 4.3 交付帧估算

我方估算可调用现有内部能力：

- 当前位置为节点：从 `current_node_id` 调用 `time_optimal_path` 到终点。
- 当前位置在边上：保守处理为“到 `next_node_id` 的剩余帧 + 从 `next_node_id` 到终点”。
- 若未完成宫门验核：额外加 `VERIFY_GATE` 耗时；若小分队探路已生效，使用减免后的耗时。
- 若下一跳存在已知障碍或敌卡：按现有 blocked/突破逻辑估算，不做乐观假设。

对手估算使用 `world.opponent`：

- `opponent.current_node_id`
- `opponent.next_node_id`
- `opponent.move_progress`
- `opponent.verified`
- `opponent.task_score`
- `opponent.good_fruit`
- `opponent.freshness`

当对手字段不足时，降低 `confidence`，并倾向 `EVEN`。

### 4.4 风险档位状态机

基础规则：

```text
gap = my_projection.projected_score - opponent_projection.projected_score

gap > +LEAD_SAFE   -> CONSERVATIVE
abs(gap) <= LEAD_SAFE -> EVEN
gap < -LEAD_SAFE   -> AGGRESSIVE
```

建议加入滞后，避免 mode 在临界点抖动：

- `LEAD_SAFE` 初始可设为 30-50 分，必须由真实 trace 校准。
- 连续 `MODE_HYSTERESIS_FRAMES` 帧满足同向条件才切档。
- 若 `opponent_projection.confidence` 低于阈值，保持上一档或回落 `EVEN`。

置信度随时间演化（重要）：

- 对手终局分投影依赖预测其路线/交付帧，而我方只能观测对手**当前位置**、无法观测其**意图**。因此比赛前中段 `gap` 噪声大，`confidence` 通常偏低，mode 大概率长期停在 `EVEN`——这是设计预期，不是缺陷。
- 越临近终局（对手路线收敛、可选项减少），投影越可信、`gap` 越有决策意义。**mode 切换的主要战场在中后段**。
- 推论：不要指望前段就靠 gap 做激进决策；前段以现有基线稳交付为主，把博弈动作的收益兑现留给投影可信的中后段。

### 4.5 接入位置

建议在 `DecisionEngine.decide(world)` 的早期构建投影总线：

```text
decide(world)
  -> projection_bus = projector.build(world, game_map, memory)
  -> memory.update_mode(projection_bus)
  -> 按现有优先级决策
     但任务、资源、窗口、突破、终局急策等读取 projection_bus.mode
```

投影总线应是只读输入，不应直接产生动作。动作仍由现有策略函数输出，保持职责边界清晰。

## 5. Layer 2：低风险增量

Layer 2 只依赖 Layer 1，目标是在较低风险下提升收益。它不新增复杂预测，只把现有策略常量和机会动作变成“按 mode 调节”。

### 5.1 档位参数调节

将当前写死常量映射为 `mode` 的函数。

| 参数 | CONSERVATIVE | EVEN | AGGRESSIVE |
|---|---|---|---|
| `TASK_SEEK_TARGET` | 0，不为任务绕路 | 90，保持现状 | 110，冲 50 分里程碑 |
| `TASK_DETOUR_MAX_EXTRA_FRAMES` | 0 | 70，保持现状 | 先试 90（不是 120），且必过 `_can_afford` + ΔEV 地板 |
| 突破烧好果意愿 | 优先绕行或 `FORCED_PASS` | 保持现状 | 允许更积极攻坚，但每次攻坚过 ΔEV 地板 |
| `RUSH_PROTECT` 时机 | 鲜度低于 90 即用 | 保持现状 | 仅鲜度危急才用，保留急策 |
| 窗口出牌 | 只出无代价牌或弃权 | 保持现状 | 积极争夺正 EV 窗口 |

> AGGRESSIVE 的绕路上限**刻意从直觉的 120 收敛到 90**：真实交付在 450+、到 600 只剩约 150 帧余量（§1.1），过宽的绕路会同时顶时间红线和侵蚀分数。放宽只是"允许在 ΔEV 为正时多走"，不是"鼓励走满"。必须先用真实 trace 证明不掉交付质量，再逐步上调。

实现建议：

- 新增 `StrategyTuning` dataclass。
- 新增 `tuning_for_mode(mode)` 函数。
- 原 `config.py` 常量作为 `EVEN` 默认值，不直接删除。
- 三档参数只调"意愿/上限"，**不改变**"必过 `_can_afford` 且必过 ΔEV 地板"这条与门（§3.3）——AGGRESSIVE 也不例外。

### 5.2 悬赏机会主义

当前 `world.bounties` 已解析，但策略尚未充分使用。悬赏适合做“顺路低代价收益”。

触发条件：

- 我方当前投影路径附近存在对手设卡，且该设卡已产生或即将产生破关悬赏。
- `_plan_attack` 可计算出低成本破卡方案。
- 好果仍满足交付安全线。
- 额外耗时通过 `_can_afford`。
- 不为悬赏大幅改道，只做顺路或近路动作。

输出动作：

- 可破卡：`BREAK_GUARD(targetNodeId, goodFruit/badFruit, rushTactic?)`
- 不可低成本破卡：保持现有绕行或强制通行逻辑。

### 5.3 终局交付 Race

现有急策主要看我方状态。新增对手投影条件：

- 对手预计 `N` 帧内可交付。
- 我方也接近交付，且使用 `RUSH_SPEED` 或 `RUSH_PROTECT` 后可提前或提高交付质量。
- 使用急策不破坏已验证的交付条件。

行为：

- 落后或接近时：优先用 `RUSH_SPEED` 抢交付帧。
- 领先且鲜度临界时：优先用 `RUSH_PROTECT` 锁好果与鲜度。

### 5.4 窗口 EV

当前 `_window_card` 倾向出第一张可出的牌。建议改为期望收益选择。

计算输入：

- 本方可用牌、好果、坏果、行动点。
- 对手资源、好果、坏果、历史窗口出牌倾向。
- contest 类型、目标节点价值、胜负后的时间/好果影响。

规则：

- `CONSERVATIVE`：只出无代价牌，否则 `ABSTAIN`。
- `EVEN`：只出明显正收益牌。
- `AGGRESSIVE`：允许更积极投入行动点或果品，但仍不得影响交付底线。

## 6. Layer 3：中风险博弈

Layer 3 依赖 Layer 1 的投影总线与更细的对手轨迹预测。它会主动争夺任务和资源，因此必须逐个开关、逐个验证。

价值评估：因真实对局有约 450 帧的争夺中局（§1.1），任务分 race / 鲜度 race / 资源 deny **有真实收益空间**，值得实现——但每个子能力都必须同时过 `_can_afford` 与 ΔEV 地板（§3.3），且默认关闭、拿到真实 trace 证明为正后逐项打开。

### 6.1 对手轨迹 ETA

目标：估算对手到宫门、任务点、资源点、终点的时间。

输入：

- `opponent.current_node_id`
- `opponent.next_node_id`
- `opponent.move_progress`
- `opponent.verified`
- 地图边权、天气、节点处理耗时、宫门验核耗时

输出：

```python
@dataclass(frozen=True)
class OpponentEta:
    to_gate: int | None
    to_finish: int | None
    to_nodes: dict[str, int]
    confidence: float
```

使用原则：

- ETA 只作为 tie-breaker 或争夺判断输入。
- 不把对手假定为完全理性；若轨迹频繁变化，降低 confidence。

### 6.2 任务分 Race

任务分不仅影响任务项本身，也影响用时分：

```text
time_score = raw_time_score * min(task_score, 90) / 90
```

因此任务分未到 90 时，边际价值可能高于表面任务分。

#### 追平逻辑

若：

- 对手任务分已达到或即将达到 90；
- 我方任务分未达到 90；
- 我方有可承受绕路任务；

则：

- 将 mode 倾向 `AGGRESSIVE`；
- 放宽 `TASK_SEEK_TARGET` 和 `TASK_DETOUR_MAX_EXTRA_FRAMES`；
- 仍必须通过 `_can_afford`。

#### Deny 逻辑

若：

- 对手正在奔向某个关键任务点；
- 我方 ETA 更早或接近；
- 抢占任务点可阻止对手达到 90 或关键里程碑；
- 我方仍能安全交付；

则可主动绕向该任务点。

守卫：

- 不为 deny 跑空趟。
- 任务点被对手保护、不可领取、已被领取时立即放弃。
- 真实日志未验证前默认关闭或仅在 `AGGRESSIVE` 下开启。

### 6.3 鲜度与好果 Race

鲜度阈值会触发好果转坏，因此双方接近阈值时，路线选择和冰鉴使用时机有博弈价值。

策略方向：

- 对手鲜度逼近 90/80/70 等阈值，我方鲜度安全：我方可以走更稳路线，不必硬拼时间，让对手自然承担阈值损失。
- 我方鲜度更危险：提前使用冰鉴，或争夺路线上的冰鉴资源。
- 资源节点库存有限且双方 ETA 接近时，才考虑“抢资源”或“deny 资源”。

守卫：

- 不为抢冰鉴显著偏离交付路线。
- 冰鉴使用仍以保阈值为核心，不能为了“省资源”导致好果转坏。

## 7. Layer 4：条件化主动进攻

Layer 4 属于高风险能力，必须在 Layer 1 和 Layer 3 稳定后启用。重点是把 `ENABLE_OFFENSIVE` 从二元开关升级为条件开关。

价值评估与前提：胜负比的是双方绝对总分，`SET_GUARD` 本身不给我方加分，只在"denied 掉的对手边际收益足以使其反超/被我方反超"的临界局才改变胜负；且设卡要在**我方交付前**花我方的帧和好果。因真实中局够长（§1.1），这类临界局确实存在，故 Layer 4 值得保留为**可选项**；但其 ROI 明显低于 Layer 1-3，应最后实现、默认关闭，且设卡计划同样要过 ΔEV 地板（把"denial 对胜负的期望价值"计入，而非只看时间）。

### 7.1 SET_GUARD 启用条件

当且仅当以下条件全部满足时考虑主动设卡：

1. `mode == CONSERVATIVE`，且投影领先足够大，目标是锁胜而非搏命。
2. 目标节点是对手投影路线上的关键单点，例如 `KEY_PASS` 或不可绕行瓶颈。
3. 设卡存活窗口覆盖对手预计通过时刻，例如 30/60 帧窗口能对齐。
4. 投入好果后仍满足交付最低安全线。
5. 设卡动作耗时通过 `_can_afford`。
6. 对手路线预测 confidence 足够高。

### 7.2 风险与回滚

主动设卡的主要风险：

- 误判对手路线，浪费好果与行动帧。
- 过度投入导致我方交付质量下降。
- 触发对手悬赏收益。

因此实现必须带开关：

- `ENABLE_OFFENSIVE=false` 仍作为默认值。
- 新增 `ENABLE_CONDITIONAL_GUARD=false`，真实日志验证后再打开。
- trace 中必须记录设卡原因、投影分差、目标节点、预计对手通过帧、投入好果。

## 8. 日志与可观测性

该方案依赖投影校准，因此 trace 必须能解释每次 mode 切换和关键偏离。

建议新增 trace 事件：

```text
Projection matchId=..., round=..., myScore=..., oppScore=..., gap=..., mode=..., myDeliver=..., oppDeliver=..., confidence=...
ModeChange matchId=..., round=..., from=EVEN, to=AGGRESSIVE, reason=gap_below_threshold, frames=...
Tuning matchId=..., round=..., mode=..., taskTarget=..., detourMax=...
RaceDecision matchId=..., round=..., kind=TASK_DENY, target=S09, myEta=..., oppEta=..., accepted=true
BountyDecision matchId=..., round=..., target=S12, bounty=..., attackCost=..., accepted=true
GuardDecision matchId=..., round=..., target=S10, oppEta=..., defense=..., accepted=false, reason=low_confidence
```

记录原则：

- 每帧最多一行 `Projection`，避免日志爆炸。
- 只有发生档位变化、关键争夺、悬赏、主动设卡时记录细节。
- 所有 rejected decision 只记录高价值候选，避免无效噪声。

## 9. 配置项建议

建议新增或集中以下配置：

```python
LEAD_SAFE = 40
MODE_HYSTERESIS_FRAMES = 5
PROJECTION_MIN_CONFIDENCE = 0.55

# 分数质量地板（§3.3）：增量动作的最低净收益门槛
ACTION_MIN_NET_SCORE = 0            # EVEN 默认：净分为负不做
ACTION_MIN_NET_SCORE_CONSERVATIVE = 8   # 领先时要求更高确定收益才动
ACTION_MIN_NET_SCORE_AGGRESSIVE = 0     # 落后时放宽下限，但不得为负

AGGRESSIVE_TASK_SEEK_TARGET = 110
AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES = 90   # 从直觉的 120 收敛（§5.1）；真实 trace 验证后再上调
CONSERVATIVE_TASK_SEEK_TARGET = 0
CONSERVATIVE_TASK_DETOUR_MAX_EXTRA_FRAMES = 0

ENDGAME_RACE_WINDOW = 20
BOUNTY_MAX_EXTRA_FRAMES = 25
BOUNTY_MIN_NET_SCORE = 15

ENABLE_TASK_DENY = False
ENABLE_RESOURCE_DENY = False
ENABLE_CONDITIONAL_GUARD = False
```

初始值只作为起点，必须用真实 `logs/` trace 校准。注意 `AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES` 与 `ACTION_MIN_NET_SCORE_AGGRESSIVE` 是防止重蹈 839cfc9"过度贪任务/烧好果"覆辙的两道闸，调参时不可为了追分把二者同时放松。

## 10. 实现落地计划

| 阶段 | 内容 | 前置 | 风险 | 验收 |
|---|---|---|---|---|
| P0 | 真实 trace 败局归因，量化领先被翻、落后未搏、悬赏未捡、被设卡未破 | 真实 `logs/` | 无 | 形成参数建议：`LEAD_SAFE`、关键设卡点、任务争夺点 |
| P1 | Layer 1 投影总线 + mode 状态机，**纯观测**：只算投影、只写 trace、**不改任何动作** | P0（观测层本身零风险，可先做） | 零 | trace 每帧输出双方投影分/交付帧/gap/mode/confidence；端到端结果与现状逐帧一致；可对比"投影 vs 真实终局分"误差 |
| P1.5 | 分数质量地板 `net_score_delta`（§3.3）：纯函数 + 单测，先落地再供 P2+ 调用 | P1 | 低 | 单测覆盖正/负 ΔEV；对已知场景估分与 `core/rules.py` 一致 |
| P2 | Layer 2：档位参数、悬赏、终局 race、窗口 EV（每个增量动作过 `_can_afford` + ΔEV 地板） | P1.5 | 低 | mock 与单测覆盖三档行为；真实日志未出现交付率或交付质量下降 |
| P3 | Layer 3：轨迹 ETA、任务 race、鲜度/资源 race | P1.5 | 中 | 每个子能力独立开关；逐项用真实 trace 验证 ΔEV 为正 |
| P4 | Layer 4：条件化 SET_GUARD（ROI 最低，最后做） | P1.5 + P3 稳定 | 中高 | 只在锁胜场景触发；trace 可解释每次设卡的胜负期望收益 |

> 落地顺序要点：**P1 先行且零风险**——纯观测投影不改动作，能立即验证投影精度、为一切参数校准提供依据，独立价值即成立。**P1.5 的分数质量地板必须早于任何改动作的层**，否则 AGGRESSIVE 档会重演 839cfc9 的过度贪任务/烧好果。

每阶段流程：

1. 先用 trace 验证假设。
2. 实现最小闭环。
3. 补单测与 mock 回归。
4. 用真实对局日志复核收益与风险。
5. 更新 `AGENTS.md` 能力矩阵、迭代日志与 `CHANGELOG.md`。

## 11. 测试策略

### 11.1 单元测试

建议新增测试文件：

- `client/tests/test_projection.py`
- `client/tests/test_risk_mode.py`
- `client/tests/test_game_theory_tuning.py`
- `client/tests/test_net_score_delta.py`（分数质量地板，§3.3）

覆盖点：

- 投影分公式调用正确。
- 对手信息缺失时 confidence 降低，并回落 `EVEN`。
- `gap` 跨阈值且满足滞后后才切档。
- 三档参数映射正确。
- 任务 deny、悬赏、设卡在 `_can_afford=false` 时不会输出动作。
- **ΔEV 地板：净分为负的增量动作被拒绝**；同一动作在 AGGRESSIVE 档放宽阈值后仍不允许净负分通过；保交付的必要动作不受地板约束。

### 11.2 Mock 场景

建议扩展 `scripts/mock_server.py` 或构造策略级 fixture：

- 我方大幅领先：应进入 `CONSERVATIVE`，减少绕路任务与消耗。
- 我方小幅领先/接近：保持 `EVEN`。
- 我方落后：进入 `AGGRESSIVE`，允许更高任务目标。
- 对手即将交付：触发终局 race。
- 顺路悬赏：低成本破卡拿悬赏。
- 对手奔向关键任务：在开关打开时触发 deny。

### 11.3 回归指标

任何阶段上线前必须满足：

- 不降低稳定交付率。
- 不引入交付前 WAITING/MOVING 卡死。
- 单帧决策仍在预算内。
- 无非法动作惩罚明显增加。
- 对真实 trace 的解释能力增强：能说清楚当时为何保守、为何进取。

## 12. 成功标准

短期成功：

- 每帧可得到双方投影分、预计交付帧和 mode。
- mode 切换可在 trace 中解释。
- 不改变策略动作时，端到端表现与现状一致。

中期成功：

- 领先局更少因过度贪任务或烧好果被翻。
- 落后局更愿意追任务分、抢终局交付或捡悬赏。
- 任务分未达 90 的局面能被系统性识别。

长期成功：

- `world.opponent` 成为策略总线的一等输入。
- 主动进攻从“默认关闭”升级为“仅在锁胜且收益可解释时启用”。
- 每轮真实对局都能按“trace -> 归因 -> 参数校准 -> 实现 -> 回归 -> 更新基线”闭环推进。

# 真实日志驱动综合迭代优化——Client 策略优化方案

> 基于 2026-07-04 拉取的首批 10 局对战平台前十名真实报告（`reports/`，N=10 假设级）。
> 我方 playerId=2696，clientVersion=iter25，variant=baseline。
> **〔Iter 32 起泛化〕** 原名"打败前十名"。前十名为首批高价值样本，**非范围限定**；后续目标泛化为对平台真实对手群体（任意对手，不限于前十名）的综合迭代优化。下方诊断基于首批样本，结论作为历史证据保留。
> 结论先行：**唯一高置信、低风险、可立即落地的杠杆是修复"被对手设卡卡死"的未交付 bug**；
> 其余杠杆（抬分数地板 / denial）均被分析器数据缺口阻断，需先补日志与分析器。

---

## 1. 诊断：我方是固定点，胜负 100% 由对手质量决定

### 1.1 战绩与分数
- 4 胜 / 5 负 / 1 未交付 = 实际 4W/6L（40%）。其中 1 场是 60 分的灾难性未交付。
- **我方分数近乎常量**：9 场交付局 score=754–758，deliverFrame 几乎恒为 444，freshness≈79.9，goodFruit=97，task_base=150，用 1 冰鉴 @~327，RUSH_PROTECT @~426，CLEAR S06 @1。
- 与 CLAUDE.md Phase 0（30 局）结论完全一致：我方 play 是固定点。

### 1.2 负局完全由对手鲜度/好果质量决定（分隔近乎完美）
| 局 | 我分 | 对手分 | 差距 | 对手鲜度 | 对手好果 | 对手交付帧 |
|---|---|---|---|---|---|---|
| L1 vs2986 | 755 | 761 | **−6** | 88.3 | 99 | 557 |
| L3 vs2814 | 755 | 776 | −21 | 92.2 | 99 | 481 |
| L6 vs2738 | 757 | 779 | −22 | 93.2 | 99 | 472 |
| L9 vs2614 | 755 | 771 | −16 | 90.7 | 97 | 478 |
| L10 vs2613 | 758 | 760 | **−2** | 82.2 | 99 | 475 |
| **未交付** vs2735 | 60 | 500 | −440 | 76.3 | 93 | 427 |
| W2 vs2809 | 755 | 692 | +63 | 70.3 | 95 | 465 |
| W5 vs2839 | 755 | 544 | +211 | 74.7 | 98 | 434 |
| W7 vs2931 | 754 | 739 | +15 | 73.5 | 95 | 458 |
| W8 vs2619 | 755 | 737 | +18 | 71.0 | 98 | 476 |

- **胜负分隔线 = 对手终局鲜度 ~82**（与 Phase 0 一致）：oppFr<80 → 我 4/4 全胜；oppFr≥82 → 我 0/5 全负。
- **关键：8/9 场交付局我方比对手交付更早（444 vs 427–557）却仍输** —— 证伪"早交付"单独获胜，输在鲜度/好果质量。
- 负局差距小：L1=−6、L10=−2，仅需 +5~10 分即可翻盘；L3/L6 需 +20+ 分。
- 我方 freshness 79.9 vs 负局对手 82–93：**鲜度差 +8~13 是核心负杠杆**，对齐 Phase 0 的 +24 上界（鲜度 +19 / 好果 +3）。

### 1.3 灾难性未交付（match vs2735）——真实卡死 bug
- 224 次 `MOVE_BLOCKED_BY_GUARD` 拒绝，帧 262–485，**全部 target=S10**。
- 我方全程未发一次 `BREAK_GUARD` / `FORCED_PASS`，最终 60 分未交付。
- 对手用进攻性设卡（offensive SET_GUARD）封我路线 S10，我方既未绕行也未突破。

---

## 2. 根因定位：`_keep_moving` 无视被设卡的在途目标

`client/strategy/decision.py` 决策入口 `decide()`（line 102–104）：

```python
if me.state in (PlayerState.MOVING, PlayerState.WAITING):
    result = self._keep_moving(...)
    return result          # ← 直接返回，永不进入 _plan/_advance/_breakthrough
```

`_keep_moving`（line 148–149）：

```python
if me.next_node_id:
    return [actions.move(me.next_node_id)]   # ← 无 blocked / cooldown 检查
```

而 `_apply_rejection_feedback`（line 394–397）确实把被拒目标写入 `self._cooldown`，但 `_keep_moving` 根本不读 `_cooldown` / `_blocked_nodes`。

**死锁链**：
1. 我方在途目标 `next_node_id=S10`（移动中被对手设卡）。
2. 每帧 `_keep_moving` 重发 `MOVE(S10)` 续行。
3. 服务端因 S10 被对手设卡回 `MOVE_BLOCKED_BY_GUARD`。
4. 反馈把 S10 加入 `_cooldown`，但 `_keep_moving` 忽略，仍重发 `MOVE(S10)`。
5. 因 `me.state` 仍为 MOVING/WAITING，永不进入 `_plan` → 永不 `_advance`/`_breakthrough`。
6. 卡 224 帧至终局，60 分未交付。

这与 Iter 8（卡 S14/WAITING 至 600 帧）同源：**MOVING/WAITING 续行路径缺乏"在途目标已失效"的再规划**。Iter 8 修了"无在途目标"分支，未修"在途目标被设卡"分支。

---

## 3. 优化方案（按置信度 / ROI 排序）

### P0｜修复设卡卡死（高置信、低风险、立即落地）—— 预期 +1 胜

**改动点**：`_keep_moving` 在重发 `MOVE(next_node_id)` 前，检查该节点是否已被对手设卡或在冷却期；若是，丢弃在途目标，回落到 `_plan` 全量重规划（`_advance` 会绕行，无法绕行则 `_breakthrough` 发 `FORCED_PASS`/`BREAK_GUARD`）。

```python
def _keep_moving(self, world, me, gm, node, terminal, gate):
    horse = self._maybe_horse(me, gm, terminal)
    if horse:
        return [horse]
    nxt = me.next_node_id
    if nxt:
        # 在途目标被对手设卡 / 在冷却期 → 不再续行，回落全量重规划（绕行或突破）
        ns = world.node(nxt)
        owner = ns.active_guard_owner() if ns else None
        if (owner and owner != me.team_id) or self._is_cooldown(world, nxt):
            return self._plan(world, me, gm, node, terminal, gate)
        return [actions.move(nxt)]
    return self._plan(world, me, gm, node, terminal, gate)
```

**为什么低风险**：
- 仅在"在途目标已失效"时改道，正常续行（目标可达）行为不变 —— 不影响其余 9 局的 444 帧交付。
- 落回的 `_plan` → `_advance` 已有完整的"绕行 vs 突破"权衡与 `_can_afford`/ΔEV 地板保护。
- 与 Iter 8 同一设计哲学（防卡死续行），补全其盲区。
- 修后该局 60 → ~755，即便对手仍赢，也至少不再白送一局；若对手因此被拖慢（我方突破后仍交付），可能直接翻盘。

**验收**：268 单测全过 + 新增 2 项（在途目标被设卡→重规划绕行 / 在途目标在冷却→重规划）；sim A/B 50 种子 0 回归（baseline 路线无设卡场景，行为不变）； CLIENT_VERSION bump。

### P1｜分析器数据补全（解锁鲜度/denial 杠杆的前提）—— 当前 reports 不足以设计

当前 `report.json` schema 的关键缺口（10 局全部如此），使我无法回答"对手凭什么鲜度 88–93"：

| 缺口 | 现状 | 阻断的决策 |
|---|---|---|
| **分项分全 null** | `finalScore.{me,opp}.{delivery,task,time,goodFruit,freshness}` 均为 null（仅 total/bounty/penalty） | 无法定位对手赢在哪个分项（鲜度？好果？任务？）。聚合 `analysis_report.md` 有分项均值，是 aggregator 用 rules.py 重算的，但单局 report 未落盘、对手分项未拆。 |
| **对手设卡不可见** | `opponentInteraction.oppGuards` 恒为 []（即便 224 次被卡） | 无法量化对手进攻性设卡频率/位置/时机，无法设计对称 denial |
| **对手资源用量不可见** | 无对手 ice/horse 使用记录 | **核心缺口**：无法回答"对手鲜度 88–93 是靠多冰鉴、早冰鉴、还是更短路线"——鲜度策略全凭猜测 |
| **对手任务领取不可见** | `tasks.opp.claimed` 恒为 [] | 无法判断对手任务分 135–180 的构成 |
| **对手轨迹仅终态** | `trajectory.opponent` 仅 freshnessEnd/goodFruitEnd/nodeEnd | 无法逐帧重建对手路线、计算 ETA 精度、定位 denial 目标节点 |
| **天气无明细** | 仅 weather_hit 段标签 | 无法判断对手是否更会躲天气 |

**分析器迭代方案**（`analysis/parser.py` + client trace 事实补充）：

1. **分项分落盘**：parser 解析 over 消息时用 `core/rules.py` 重算双方 `delivery/task/time/goodFruit/freshness` 分项，写入 `finalScore.{me,opp}`（单局 + 对手均补全）。aggregator 已有逻辑，下沉到单局 report。
2. **对手设卡捕获**：client trace 已记录对手事件（`Frame` 行的 `opp*`）——确认 over/inquire 消息是否含对手 SET_GUARD；若含，parser 提取入 `oppGuards[]`（frame/node/defense）。若协议不广播对手设卡，则从"我方 MOVE_BLOCKED_BY_GUARD + 我方节点状态 active_guard_owner"反推（match 4 已能反推 S10 被设卡）。
3. **对手资源/任务捕获**：协议 `inquire` 是否暴露对手库存/已领任务？核对 `docs/protocol.md`；可暴露的字段全部入 trace + parser。这是判断鲜度来源的关键。
4. **对手逐帧轨迹**：parser 把 client trace 的对手逐帧 `opp*`（位置/鲜度/好果）落成 `trajectory.opponent.frames[]`，供 ETA 校准与 denial 目标选取。
5. **天气明细**：parser 提取每段天气的起止帧/强度/区域，落 `weather[]`。

**验收**：用现有 10 局 trace 回灌，验证 6 项字段非空、对账自检 0 误差；再跑一轮真实对战取 reports。

### P2｜抬分数地板：鲜度/好果质量积累（依赖 P1 数据 + 决赛新图）

- Phase B 联合静态规划器（Iter 26–28）已建好，samples 图中性故 flag 关。
- **真实杠杆确认**：负局对手鲜度 88–93 vs 我方 79.9，+8~13。若 +15 鲜度，可翻 L1(−6)/L10(−2)/L9(−16)；+20 可翻 L3(−21)/L6(−22)。
- **但手段未知**：多冰鉴？早冰鉴？更短路线？躲天气？—— 必须等 P1 补全对手资源/轨迹数据后才能定方向，否则重演 Iter 26–28"投影乐观、samples 无廉价鲜度"的盲调。
- **决策**：P1 数据回流后，若发现对手用 ≥2 冰鉴或更短鲜度路线，针对性开 `ENABLE_FRESHNESS_RACE` / 调冰鉴使用阈值 / 在决赛图上重测 `ENABLE_STATIC_PLANNER`。

### P3｜denial：设卡/争抢压低对手分（依赖 P1 对手轨迹 + 高风险）

- 对手已对我用进攻性设卡（match 4）。对称地，我方可在对手必经关隘设卡拖慢其鲜度。
- 但 `SET_GUARD` 当前冻结（P4，ROI 最低、占用己方交付时间），且会烧好果。
- **决策**：仅当 P1 显示对手路线高度可预测（单一关隘必经）且我方锁胜时，才条件化开 `ENABLE_CONDITIONAL_GUARD`（已有实现）。优先级最低。

---

## 4. 落地顺序与可达性（基于首批 10 局样本；泛化后作历史参考）

| 步骤 | 动作 | 预期胜率提升 | 依赖 |
|---|---|---|---|
| 1 | **P0 修设卡卡死** | 4/10 → ≥5/10（白送的未交付局拿回） | 无，立即 |
| 2 | **P1 分析器补全** + 取新一轮 reports | 解锁 P2/P3 | client trace + parser 改造 |
| 3 | P2 鲜度质量积累（数据驱动定方向） | +1~3 局（翻 L1/L10/L9） | P1 数据 |
| 4 | P3 denial（可选） | +0~1 局 | P1 对手轨迹 |

**诚实评估**：仅 P0 可立即拿到 +1 胜。要"打过前十名的每个队伍"，还需 P1→P2 把分数地板从 755 抬到 ~770（覆盖 L1/L10/L9 的 −6/−2/−16 差距）。L3/L6 的 −21/−22 差距需鲜度 +20+ 或 denial，难度更高、风险更大。**当前 reports 不足以设计 P2/P3，必须先做 P1**。

## 5. 演进路线（Iter 32 起框架升级）

> P0/P1-A/P1-B 已完成。下方"建议立即执行"原为手动取 reports 节奏，**已被 codeagent 自动对战闭环取代**（详见 `docs/iteration_loop_design.md` §0.5）。

**两阶段目标**："静态最优解的基础上追求博弈最优解"。

1. **Iter 32（零策略风险）**：用 codeagent 跑首轮真实对战 A/B 建立基线（codeagent 自动收集 `logs/match_*.log` 调 `analysis` 生成 reports，无需 repo 侧契约）；analysis 加**对手类分桶群体归因段**（用 P1-A 已抽轨迹/用冰/设卡聚类 speed/quality/guard-type）。
2. **静态最优（Iter 33+，先）**：抬地板 755→770，纯路线/冰鉴/鲜度积累、不读对手。开 `ENABLE_STATIC_PLANNER` 或调冰阈值，codeagent 真实 A/B 验证。证据最硬（鲜度 +19 唯一正杠杆）。
3. **博弈最优（Iter 34+，后）**：对手感知策略切换。新增对手策略分类器；决策侧用对手类替代抽象 mode——现有 CONSERVATIVE/EVEN/AGGRESSIVE 拨动的是已封顶 task 绕路（无效杠杆），须把鲜度/冰/路线绑入档位。
4. **P3 denial（Iter 35+）**：按归因选分支，codeagent A/B + N≥30。

**验证门重定义**：sim A/B 降为回归 + 不变量门（镜像自博弈无法验证博弈层）；真实对战 A/B 升为合入门。**降噪**：A/B 未过则删/回退，不再"保留作 variant 平台"。

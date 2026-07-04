# 打败前十名 — P0–P3 详细设计与实现

> 本文件是接下来数轮迭代的**执行蓝图**。每轮按一个 Pn 推进：先实现、再单测、再 sim A/B、最后（需阈值合入者）等真实 trace N≥30。
> 配套总览：`docs/beat_top10_plan.md`。证据来源：`reports/`（10 局对前十名，clientVersion=iter25）。
> 所有 file:line 基于 2026-07-04 仓库状态。

---

## 0. 跨轮铁律（每轮必须遵守）

1. **证据型闭环**：假设 → 实现 → 单测 → sim A/B 50 种子 → 仅当正向且分段不回归才固化。任何阈值合入须真实 trace N≥30。
2. **flag 纪律**：新增能力一律加 `ENABLE_*` flag **默认关**；A/B 过门槛才开。运行期行为变化的轮次 `CLIENT_VERSION` bump（`config.code_version()`）。
3. **策略通用**：一切节点/路线/资源/任务候选点从 `start`/`inquire` 动态读取，禁止硬编码（决赛换新图）。
4. **不扫阈值逼正向**：扫参数 = 过拟合初赛图，禁止。阈值须有物理/数据依据。
5. **保交付第一**：任何增量动作须同时过 `_can_afford`（时间）与 `ΔEV≥0`（分数）两道地板。未交付 = 0 分。
6. **同步更新**：每轮落地后更新 `CLAUDE.md`（能力矩阵 + §7 迭代日志）与 `CHANGELOG.md`。

### sim A/B 门槛（§1.2 "done" 标准）
- 50 种子，flag-on vs baseline。
- mean 分数差 CI 95% 须下界 > 0（**正向**，非"中性跨 0"）。
- 分段不回归：交付率、task-90 达成、mid_lead/trail/even、weather_hit、contested 各段胜率不劣化。
- 0 STUCK（waitingStuck=0）、对账 0 误差。
- 注：当前 sim 是**镜像自博弈**（gap 恒 0、mode 恒 EVEN），无法验证博弈层（P3）—— P3 须等真实 trace。

---

## P0 — 修复"被对手设卡卡死"的未交付 bug

**优先级**：最高（高置信、低风险、无依赖、立即落地）。
**预期收益**：vs2735 那局 60 → ~755，4/10 → ≥5/10。即便不翻盘也消除白送的未交付。
**证据**：`reports/...2735...report.json`——224 次 `MOVE_BLOCKED_BY_GUARD` 全打 S10（帧 262–485），全程未发 `BREAK_GUARD`/`FORCED_PASS`。

### P0.1 根因
`decision.py:102-104` MOVING/WAITING 态直接 `_keep_moving` 返回，永不进 `_plan`/`_advance`/`_breakthrough`：
```python
if me.state in (PlayerState.MOVING, PlayerState.WAITING):
    result = self._keep_moving(...)
    return result
```
`_keep_moving`（`decision.py:138-150`）重发 `MOVE(me.next_node_id)` **不检查该节点是否被对手设卡 / 在冷却期**：
```python
if me.next_node_id:
    return [actions.move(me.next_node_id)]
```
`_apply_rejection_feedback`（`decision.py:394-397`）把被拒目标写入 `self._cooldown`（`REJECT_BLOCK_ROUNDS=4`），但 `_keep_moving` 不读它。死锁：在途目标被设卡 → 每帧重发 MOVE → 被拒 → cooldown 被忽略 → 卡至终局。与 Iter 8（卡 S14）同源，Iter 8 只修了"无在途目标"分支。

### P0.2 实现
**唯一改动点**：`client/strategy/decision.py` `_keep_moving`，重发前校验在途目标是否失效。

```python
def _keep_moving(self, world, me, gm, node, terminal, gate):
    """处于移动中/主动等待中时保证持续前进，绝不空等卡死。

    - 值得加速且无移动增益 → 用一次马（不影响本帧继续前进）。
    - 有在途目标且目标仍可达（未被对手设卡 / 不在冷却期）→ 重发 MOVE 续行。
    - 在途目标已失效（被对手设卡 / 在冷却期）→ 丢弃在途目标，回落 _plan 全量重规划
      （_advance 会绕行，无法绕行则 _breakthrough 发 FORCED_PASS / BREAK_GUARD）。
      修复真实败局：对手在途设卡导致 MOVE_BLOCKED_BY_GUARD 连拒百帧、未交付。
    - 无在途目标（已在节点却被报为等待）→ 按节点空闲重新规划。
    """
    horse = self._maybe_horse(me, gm, terminal)
    if horse:
        return [horse]
    nxt = me.next_node_id
    if nxt:
        if self._in_transit_target_blocked(world, me, nxt):
            return self._plan(world, me, gm, node, terminal, gate)
        return [actions.move(nxt)]
    return self._plan(world, me, gm, node, terminal, gate)

def _in_transit_target_blocked(self, world, me, nxt):
    """在途目标是否已失效：被对手设卡（active guard owner != 我方）或在节点冷却期。"""
    if self._is_cooldown(world, nxt):
        return True
    ns = world.node(nxt)
    owner = ns.active_guard_owner() if ns else None
    return bool(owner and owner != me.team_id)
```

**为什么低风险**：仅在"在途目标已失效"时改道；正常续行（目标可达）行为完全不变 → 不影响其余 9 局的 444 帧交付。落回的 `_plan`→`_advance` 已有完整"绕行 vs 突破"权衡（`_select_path` blocked 感知 + `_breakthrough` FORCED_PASS/BREAK_GUARD + `_can_afford`/ΔEV 地板）。与 Iter 8 同一防卡死哲学，补其盲区。

### P0.3 单测（`client/tests/test_keep_moving_guard.py`，新建）
仿 `test_breakthrough_fruit.py` 的 `_node/_edge/_world/_break` 模式。构造 `me.state=MOVING`、`me.next_node_id=SG`，`decide()` 返回 action：
1. `test_transit_target_guarded_replans`：SG 被对手设卡（`guard={active,defense>0,ownerTeamId=opp}`）→ 返回非 MOVE(SG)（应为绕行 MOVE 或 FORCED_PASS/BREAK_GUARD），证明回落 `_plan`。
2. `test_transit_target_cooldown_replans`：SG 在 `self._cooldown`（exp>round）→ 同上回落 `_plan`。
3. `test_transit_target_clear_continues`：SG 无设卡不在冷却 → 返回 `MOVE(SG)`（续行行为不变，防回归）。
4. `test_transit_target_own_guard_continues`：SG 被己方设卡（owner==me.team_id）→ 仍 `MOVE(SG)`（己方卡不挡己方）。
5. `test_no_in_transit_target_replans`：`me.next_node_id=None` + WAITING → 调 `_plan`（既有行为，防回归）。

### P0.4 验收
- 268 client 单测全过 + 新增 5 项全过。
- sim A/B 50 种子（baseline 路线无设卡场景，flag 不涉及）**0 回归**：mean / 交付率 / task-90 / 分段全一致、0 STUCK、对账 0 误差。
- `CLIENT_VERSION` bump（运行期行为变化：被设卡时改道）。
- 更新 `CLAUDE.md` §4.3「移动/等待中主动续行」行 + §7 Iter 29。

### P0.5 风险与回退
- 风险：回落 `_plan` 每帧重算有性能成本。`_plan` 轻量（Dijkstra + 机会式），单帧 <500ms 预算内。若实测超时，加"失效目标一次性入冷却后直接 `_plan`"已天然限频（冷却 4 帧内同一目标不会再被选）。
- 回退：单 `git revert`，无 flag 依赖（P0 是 bug 修复，无条件合入）。

---

## P1 — 分析器数据补全 + 精简 trace 回流（解锁 P2/P3 的前提）

**优先级**：次高。**当前 reports 不足以设计 P2/P3**——核心未知"对手凭什么鲜度 88–93"无法回答；且原始 trace ~880KB/局无法上传，我只能读 `reports/`。
**关键发现（研究确认）**：协议层对手信息**几乎全可见**（`inquire.players[]` + `over.players[].scoreDetail` 暴露鲜度/好果/库存/设卡/任务分/分项分），缺口在 **client 不记 + parser 不抽**，非协议不可见。
**目标**：① 让单局 `report.json` 携带双方分项分、对手逐帧轨迹、对手设卡、对手资源/任务（**P1-A**）；② 由完整 trace 派生**精简 trace** 落 `reports/`，使我 pull 后能直读、彻底绕开"原始 trace 无法上传"瓶颈（**P1-B**）。

### P1.1 数据缺口三分类（研究结论）

| 数据 | 协议可见 | client trace | parser 抽取 |
|---|---|---|---|
| 对手鲜度/好果/位置/状态/任务分 | ✅ inquire | ✅ Frame opp* | 部分（鲜度/好果/位置抽，state/task 未抽） |
| 对手 badFruit/库存(ice/horse/intel)/verified/moveProgress/nextNodeId/guardActionPoint/buffs | ✅ inquire | ❌ | ❌ |
| 对手设卡（nodes[].guard 全局可见） | ✅ inquire | ❌ | ❌（oppGuards 恒 []） |
| over 双方分项分（delivery/task/time/goodFruit/freshness） | ✅ scoreDetail | ❌（只记 total/taskScore/bountyScore） | ❌（`_final_score` stub 全 None） |
| 对手任务领取明细 | ✅ inquire | ❌ | ❌（tasks.opp.claimed 恒 []） |

### P1.2 P1-A 实现：富化完整 trace + parser 抽取 + aggregator 落盘

#### A. client 记更多事实（`client/main.py`）
1. **`_log_frame`（main.py:291-311）补对手字段**：`oppBad`、`oppVerified`、`oppMoveProg`、`oppNext`、`oppGuardAP`、`oppResources`（库存 dict 序列化，如 `ice=2,horse=1`）。均为 inquire 已有、零推断。
2. **`_log_frame` 补全节点设卡快照**：每帧（或设卡变化时）记 `Guards` 行——所有 `active_guard_owner() is not None` 的节点 `{node,owner,defense}`。这是对手进攻性设卡的**唯一可观测来源**（match 4 的 S10 设卡将首次被记录）。
3. **`_log_over`（main.py:90-104）补 scoreDetail**：Score 行加 `scoreDetail` 字段（delivery/task/time/goodFruit/freshness/penalty），双方都记。协议 over 已提供。

#### B. parser 抽取（`analysis/parser.py`）
1. **`_final_score`（parser.py:369-379）去 stub**：从 Score 行的 `scoreDetail` 填双方 `delivery/task/time/goodFruit/freshness/penalty`（不再全 None）。
2. **Frame 行扩抽取**：`oppState`、`oppTask`、`oppBad`、`oppVerified`、`oppMoveProg`、`oppNext`、`oppGuardAP`、`oppResources` 入 `trajectory.opponent.frames[]`（逐帧）。
3. **`oppGuards`（parser.py:282）实装**：从 `Guards` 行解析每帧设卡快照，聚合为 `oppGuards[]`（owner!=me 的设卡：frame首次出现/node/defense/持续帧数）。
4. **`tasks.opp.claimed`**：从对手 `oppTask` 跳变 + over `taskScore` 反推对手任务分进程（无明细则记 taskScore 轨迹）。
5. **schemaVersion → 2**：新增字段标注，向后兼容（parser 按 schemaVersion 分支）。

#### C. aggregator 落盘 + 对手分项（`analysis/aggregator.py`）
1. **单局 report 落双方分项分**：`recompute_total`（aggregator.py:78-111）当前只算 me 且只存聚合均值。改为：单局 report.json 的 `finalScore.me/opp` 直接填 scoreDetail（来自 trace，无需重算）；aggregator 额外保留 rules.py 重算作对账。
2. **`opp_score_components`**：新增对手分项均值（delivery/task/time/goodFruit/freshness/bounty），与 `me_score_components` 对称——**首次能量化"对手赢在哪个分项"**。
3. **对手设卡统计段**：`opp_guard_count`（对手进攻性设卡次数）、`opp_guard_blocked_me_frames`（我被卡帧数）入聚合报告 + 新段 `opp_offensive_guard`。
4. **对手资源/鲜度轨迹统计**：`opp_ice_used`（从 oppResources 库存减少推断）、`opp_freshness_trajectory`（min/end）。

### P1-A.3 单测
- parser：新增 `test_parser_opp_fields.py`——构造含新字段的 trace 文本，断言 `finalScore.opp.freshness` 非 null、`oppGuards` 含 S10、`trajectory.opponent.frames` 含 oppNext/oppResources。
- aggregator：扩 `test_aggregator.py`——断言 `opp_score_components` 6 项非空、`opp_guard_count` 正确。
- **回灌验证**：用现有 10 局 trace 回灌（若 client 未重跑，old trace 缺新字段 → parser 须优雅降级，旧字段仍抽、新字段标 null，schemaVersion=1 兼容）。

### P1-A.4 验收
- 现有 42 analysis 单测全过 + 新增 parser/aggregator 单测全过。
- **新一轮真实 reports 回流后**（用户取）：10+ 局 report.json 的 `finalScore.opp.{delivery,task,time,goodFruit,freshness}` 全非 null、`oppGuards` 在设卡局非空、`trajectory.opponent.frames` 非空。
- `analysis_report.md` 出现 `opp_score_components` 与 `opp_guard_count` 段。
- 对账自检 0 误差（rules.py 重算 vs total）。

### P1.5 P1-A 交付件影响
- client trace 多记字段 → 字节量略增（可接受，trace 仅内网分析用、不上传平台）。
- `CLIENT_VERSION` bump（trace 格式变化）。
- **不改任何运行期决策**——P1-A 纯观测/分析，零策略风险。

---

### P1-B 精简 trace（数据回流通道）

**问题**：原始完整 trace ~880KB–1.16MB/局（7352 行），`.gitignore` 中 `logs/**/*.log` 不入库不上传 → 我只能读 `reports/`。raw gzip+base64 仍 116KB，超可粘贴上限；纯 gzip 87KB。**完整 trace 无法到达我**。
**实测结论**（已验证）：靠 gzip 单独不够（raw gzip 87KB）；必须**先转事件驱动紧凑格式再压缩**。膨胀源不是行前缀（去掉只省 24%），而是每帧记 Frame/Projection/Eta/Action 四行 + freshness 每帧都变使 delta 失效。

| 方案 | 体积 | 保真度 |
|---|---|---|
| raw gzip+base64 | 116KB | 完整 ❌ 超 5KB |
| 紧凑纯文本 | ~6–9KB/局 | 高（含轨迹） |
| 紧凑 gzip+base64 | ~1.4KB/局 | 高 ✅ |

**方案**：精简 trace 由分析管线**从完整 trace 派生**（非 client 双写），随 `python3 -m analysis` 一起产出，落 `reports/match_<id>.compact.log`（入库，我可 pull 直读）。

**架构对齐**（CLAUDE.md 既有原则：client trace = 传输格式单文件 / repo 产物 = 分析格式多文件可重生成）：
```
平台运行：client/logs/match_*.log          ← 完整 trace（client 唯一写的，不变）
    ↓ 随交付件下载
本地 logs/match_*.log                       ← gitignored，parser 输入
    ↓ python3 -m analysis
reports/match_*.report.json                 ← 入库（现有）
reports/match_*.compact.log   ← 【P1-B 新增】精简 trace，入库，我 pull 可直读
```

**为什么不在 client 双写**：精简 trace 是可从完整 trace 重生成的派生产物，按架构原则属 repo 产物，不该进 client（client 保持纯 stdlib 单文件传输）；派生逻辑放 `analysis/` 一处，演进只改一个地方，避免双份格式耦合维护。

**目录澄清**：`logs/**/*.log` 是 gitignored，放 logs/ 我看不到。要"辅助 reports 做参考"且能到达我，精简 trace 必须落 `reports/`（入库）。

#### P1-B.1 精简格式（事件驱动，纯文本）
每局 ~150–330 行 / ~6–9KB。行类型：
- `Startup` / `Start` / `Ready` / `Over` / `Score`：头部尾部（Score 含 scoreDetail 双方）。
- `Map N=... E=...`：拓扑快照（节点 id+类型首字母、边 `a-b:dist:R/W/M/B`）。
- `F r<round> <changes>`：帧状态**仅变化时**记——`n=`到站、`st=`状态跃迁、`gf=`好果变化、`on=`对手节点变化、`ts=/ots=`任务分变化、`fr<t>=/ofr<t>=`鲜度阈值跨越(90/80/70/60/50/40/30/20/10)。
- `A <action> <target>`：动作**仅 (action,target) 变化时**记，丢 `NONE` 心跳与空 target 探测。
- `REJ x<n> <code> <target>`：连续相同拒绝合并（match 4 的 224 次卡死 → 1 行）。
- 信号行原样保留：`ModeChange`/`RushTactic`/`WindowCard`/`GuardDecision`/`Bounty`/`Breakthrough`。
- **P1-A 富化字段自动透传**：精简 trace 从完整 trace 派生，P1-A 补记的 oppResources/oppGuards(Guards 行)/scoreDetail 一并进入精简格式 → 我读精简 trace 即可做鲜度归因/对手设卡分析。

#### P1-B.2 实现（`analysis/compact.py`，新增）
1. `compact_trace(log_path or text) -> str`：完整 trace → 精简文本（上述事件驱动逻辑，已在原型实测验证）。
2. `parse_compact(text) -> Report`：精简 → Report（当完整 trace 丢失、仅剩精简时仍可重建 report.json；复用 parser 抽取逻辑）。
3. `--b64` 开关：精简 `gzip+base64` ~1.4KB/局，供聊天粘贴（不走 git 时用）。
4. **接线**（`analysis/__main__.py`）：`parse_log` 后追加 `compact_trace` 写 `reports/<matchId>.compact.log`；`parse_compact` 作为"仅精简可用"时的回退解析路径。
5. **格式 spec**：`docs/compact_trace_format.md` 一页（行类型枚举 + 字段语义），供 compact parser 与我阅读参考。

#### P1-B.3 单测
- 新增 `analysis/tests/test_compact.py`：
  1. `test_roundtrip`：完整 trace → `compact_trace` → `parse_compact` → 与原 `parse_log` Report 关键字段一致（matchId/outcome/finalScore 双方分项/deliverFrame/oppGuards/失败模式计数）。
  2. `test_size_budget`：断言精简纯文本 < 10KB/局（回归保护，防膨胀）。
  3. `test_rejection_collapse`：224 次连续相同拒绝 → 1 行 `REJ x224`，且 `parse_compact` 还原计数。
  4. `test_legacy_trace`：旧 trace（无 P1-A 富化字段）→ 精简格式优雅降级，缺字段标 absent。

#### P1-B.4 验收
- 现有 42 analysis 单测 + P1-A 新增 + P1-B 4 项全过。
- **回灌现有 10 局完整 trace**（若已下载本地）→ 产出 10 份 `reports/*.compact.log`，每份 < 10KB，`parse_compact` round-trip 关键字段 0 误差。
- 新一轮真实 reports 回流后，`reports/` 同时含 `*.report.json` + `*.compact.log`，我 pull 后可直接 `Read` 精简 trace 做归因。

#### P1-B.5 交付件影响
- **client 零改动**（精简 trace 由 repo 派生）。
- `reports/` 体积 +~6–9KB/局（可接受，入库是为了我能读）。
- 不 bump `CLIENT_VERSION`（运行期行为不变）。
- 纯观测/分析，零策略风险。

### P1.6 P1 完成后的归因产出（给 P2/P3 定向）
预期可回答：
1. 对手鲜度 88–93 的来源：多冰鉴？早冰鉴？短路线？躲天气？（看 `opp_ice_used` + `opp_freshness_trajectory` + 对手路线）
2. 对手进攻性设卡频率/位置（看 `oppGuards`）——是否值得对称 denial。
3. 对手任务分构成（看 `tasks.opp`）——是否可 deny。
4. 我方 vs 对手分项逐项差（看 `me/opp_score_components`）——精准定位追分点。

---

## P2 — 抬分数地板：鲜度/好果质量积累

**优先级**：中。**强依赖 P1 归因**——须先知道对手鲜度来源，否则重演 Iter 26–28"投影乐观、samples 无廉价鲜度"的盲调。
**目标**：把我方地板从 755 抬到 ~770，覆盖 L1(−6)/L10(−2)/L9(−16) 负局。
**证据**：我方 freshness 79.9 / goodFruit 97（用 1 冰鉴 @~327）；负局对手 88–93 / 99。Phase 0 上界 +24（鲜度 +19 / 好果 +3）。

### P2.1 现有杠杆（研究确认，全部已实现、默认关/弱）
| 杠杆 | 位置 | 当前状态 | 作用 |
|---|---|---|---|
| 冰鉴使用阈值 | `_freshness_rescue`（decision.py:414-429） | `ICE_BOX_USE_BELOW=78` | 鲜度<78 才用冰鉴（被动、晚） |
| 冰鉴囤量 | `_maybe_claim`（decision.py:469-493） | `CLAIM_ICE_BOX_KEEP=1` | 只囤 1 个 → 只能用 1 次 |
| 鲜度 race | `_losing_freshness_race`（decision.py:431-436） | `ENABLE_FRESHNESS_RACE=False` | 落后时阈值提到 88（默认关） |
| 联合规划器 | `static_planner.plan_route`（static_planner.py:296-354） | `ENABLE_STATIC_PLANNER=False` | 路线×冰鉴×任务一体求解，囤 3 冰鉴、阈值 91 |
| 鲜度最优路线 | `freshness_loss_for_path`（projection.py:191-217） | 仅规划器内用 | 选低损耗路线（WATER 0.045 < ROAD 0.055 < BRANCH 0.065 < MOUNTAIN 0.07） |
| 阈值跨越预防 | `project_route`（static_planner.py:183-186） | 规划器内 | 冰鉴 +10 鲜度可阻止一次好果→坏果跨越（90/80/70…） |

### P2.2 P1 归因驱动的分支方案
**P1 回流后按对手鲜度来源选分支**（不预设方向，避免盲调）：

- **分支 A（对手靠多冰鉴/早冰鉴）**：开 `ENABLE_FRESHNESS_RACE`（已有），把 `CLAIM_ICE_BOX_KEEP` 提到 2–3、`ICE_BOX_USE_BELOW` 提到 85。低风险（只改阈值、不动路线）。先 A/B。
- **分支 B（对手靠更短/更低损耗路线）**：开 `ENABLE_STATIC_PLANNER`（已有 v2+效率门，Iter 28）。在决赛新图上重测——samples 图中性是图结构无廉价鲜度，决赛图若有则自然正向。须 sim A/B + 真实 trace 双验证。
- **分支 C（对手靠躲天气）**：P1 若显示对手在 HOT/HEAVY_RAIN 段鲜度损耗显著低于我方，则加"天气感知路线"——在 `freshness_loss_for_path` 已支持 weather_coef 基础上，让 `_select_path` 在恶劣天气段偏好低损耗路线。新 flag `ENABLE_WEATHER_AWARE_ROUTING`。
- **分支 D（好果跨越预防）**：若我方 goodFruit 97 是因某次 90→80 跨越未防，则提前用冰鉴卡阈值。规划器已建模，分支 B 开启即生效。

### P2.3 实现路径（分支 A 为例，最低风险首选）
1. 阈值调整（`config.py`）：`ICE_BOX_USE_BELOW` 78→85、`CLAIM_ICE_BOX_KEEP` 1→2。**仅当 P1 证对手多冰鉴时**。
2. 开 `ENABLE_FRESHNESS_RACE=True`（已有逻辑：落后≥10 鲜度时阈值提到 88）。
3. 单测：扩 `test_freshness_resource_race.py`——断言新阈值下提前用冰鉴、囤 2 冰鉴。
4. sim A/B 50 种子：mean 鲜度 +X、goodFruit 不回归、交付帧可接受范围、CI 正向。
5. **不合入阈值**直至真实 trace N≥30（P1 通道持续收割）。

### P2.4 验收（每分支独立 A/B）
- sim A/B 50 种子 mean 分数 CI 下界 > 0；鲜度均值上升、好果不回归、交付帧 +≤10、0 STUCK。
- 真实 trace N≥30 后阈值才合入 `config.py` 默认值。
- 分段不回归（特别 mid_lead/trail/even）。
- `CLIENT_VERSION` bump（仅当 flag 默认开 / 阈值改默认）。

### P2.5 风险
- **投影天气乐观**（Iter 27 根因）：鲜度投影未建模隐藏未来天气 → 投影 +24 上界偏乐观。效率门（0.2）已部分吸收。分支 B 须保留效率门。
- **task-ice 时间零和**（Iter 26 根因）：分项式绕路下 task 与 ice 争同一预算。分支 B 用联合规划器（v2）规避，但须 A/B 验证不重演 task 回归。
- **冰鉴囤量占用交付时间**：多囤冰鉴 = 多停靠 2 帧/个。须 `_can_afford` 把关。

---

## P3 — denial：压低对手分（设卡/争抢/破卡）

**优先级**：低（高风险、依赖 P1 对手轨迹 + ETA、且 sim 镜像自博弈无法验证博弈层）。
**目标**：在领先时锁胜（设卡拖慢对手）、在对手设卡我时反制（破卡/绕行）、争抢关键冰鉴/任务。
**证据**：match 4 对手用进攻性设卡封 S10 把我卡死（P0 修后我方能绕/破）；对称地我方可设卡拖慢对手。

### P3.1 现有 denial 杠杆（研究确认，全部已实现、默认关）
| 杠杆 | 位置 | 条件 | 默认 |
|---|---|---|---|
| 条件化设卡 | `_conditional_guard`（decision.py:972-1020） | CONSERVATIVE + gap≥60 + 关键关隘 + 对手 ETA∈(5,60] + 好果≥20 + confidence≥0.7 + denial≥4 | `ENABLE_CONDITIONAL_GUARD=False` |
| 基线设卡 | `_basic_set_guard`（decision.py:958-970） | KEY_PASS + 好果≥20 | `ENABLE_OFFENSIVE=False` |
| 悬赏破卡 | `_maybe_bounty`（decision.py:811-894） | 非 RUSH/CONSERVATIVE + opp 有效设卡 + 低成本可破 + 额外帧≤25 + ΔEV≥15 | 默认开（无 flag） |
| 任务 deny | `_task_deny_target`（decision.py:706-763） | 对手 ETA 内 + 跨里程碑 + ΔEV≥0 | `ENABLE_TASK_DENY=False` |
| 资源(冰鉴) deny | `_maybe_resource_race`（decision.py:495-532） | 对手 ETA 内 + 库存<2 + 额外帧≤20 | `ENABLE_RESOURCE_DENY=False` |
| 对手 ETA | `OpponentEta`（projection.py:60-75,324-353） | 纯观测，confidence=0.30+round/dur*0.55−route变化折扣 | 已开 |

### P3.2 P0 与 P3 的关键联动
**P0 修后，对手设卡封我路线已可被现有 `_breakthrough` 处理**（FORCED_PASS 付时间税 / BREAK_GUARD 烧好果 / 绕行）。match 4 的 224 次卡死主因是 P0 bug，不是缺 denial 能力。故 P3 的**反制对手设卡**部分已被 P0 + 既有 `_breakthrough` 覆盖，无需新代码——P0 落地后须在 sim/trace 复核：被设卡时是否正确选 FORCED_PASS（时间税可负担）vs 绕行 vs BREAK_GUARD。

### P3.3 P1 归因驱动的分支方案
**P1 回流后按对手可预测性选分支**：

- **分支 A（对手路线高度可预测、单一关隘必经）**：开 `ENABLE_CONDITIONAL_GUARD`（已有）。**仅锁胜局**（CONSERVATIVE + gap≥60），在对手必经关隘设卡拖慢其鲜度。denial 价值 `_guard_denial_value`（decision.py:1029-1046）≥4 才设。低风险（只锁胜、不赌）。
- **分支 B（对手频繁设卡我）**：P1 若显示对手高频进攻性设卡，则扩 `_maybe_bounty`——当前要求 ΔEV≥15（须含悬赏奖），可加"纯反制破卡"分支（无悬赏但打通我方路线，ΔEV 用节省的绕路/时间税计）。新 flag `ENABLE_COUNTER_BREAK`。
- **分支 C（对手依赖少量冰源）**：开 `ENABLE_RESOURCE_DENY`（已有），抢对手必争冰源。须 P1 证对手冰源稀缺且可预测。
- **分支 D（对手冲任务里程碑）**：开 `ENABLE_TASK_DENY`（已有），抢跨对手里程碑的任务点。

### P3.4 实现路径（分支 A 为例，最稳）
1. 开 `ENABLE_CONDITIONAL_GUARD=True`（已有 6 条件 + denial 价值门）。
2. **不调阈值**（GUARD_MIN_LEAD=60 等已是保守值）——除非 P1/N≥30 证应调。
3. 单测：`test_conditional_guard.py` 已有 15 项，复核覆盖。
4. **sim A/B 无法验证**（镜像自博弈 gap=0 → CONSERVATIVE 不触发）→ 须真实 trace A/B：开 flag 后胜率/对手鲜度是否下降、我方交付好果是否被设卡烧（KEEP_GOOD_FRUIT=20 保护）。
5. N≥30 才合入默认开。

### P3.5 验收
- 真实 trace A/B（非 sim）：锁胜局设卡后对手鲜度/交付帧负向变化、我方分数不回归。
- 我方交付好果 ≥20（`GUARD_KEEP_GOOD_FRUIT`）、交付率不回归。
- `CLIENT_VERSION` bump（仅当默认开）。

### P3.6 风险
- **设卡烧好果 / 占交付时间**：`_conditional_guard` 已用 `GUARD_KEEP_GOOD_FRUIT=20` + `_can_afford` + 仅锁胜保护。但若对手破卡成本低于预期（`_guard_denial_value` 估错），白烧好果。须真实 trace 校准。
- **ETA 不可靠**（对手意图不可观测）：confidence 阈值 0.7 已偏严，前中段不触发（设计预期）。
- **对手反制**：对手可能破我卡后再设卡反封——须 `_breakthrough` 闭环（P0 已保）。
- **博弈层 sim 不可验证**：P3 全部须真实 trace，不可仅凭 sim 合入。

---

## 迭代排期与依赖

| 轮次 | 内容 | 依赖 | 可合入默认? |
|---|---|---|---|
| Iter 29 | **P0** 设卡卡死修复 | 无 | ✅ 无条件（bug 修复） |
| Iter 30 | **P1-B** 精简 trace（`analysis/compact.py` + 接线 + 单测 + 格式 spec） | 无 | ✅（纯观测，client 零改动，零策略风险） |
| Iter 31 | **P1-A** client trace 富化 + parser 抽取 + aggregator 落盘 | 无 | ✅（纯观测，零策略风险） |
| Iter 32 | 用户取新一轮真实 reports（≥10 局，理想 ≥30）——含 `*.compact.log` | Iter 30+31 | — |
| Iter 33 | **P1 归因**（直读精简 trace + report.json）+ 选 P2/P3 分支 | Iter 32 reports | — |
| Iter 34 | **P2 分支**（按归因选 A/B/C/D）实现 + sim A/B | Iter 33 归因 | flag 默认关；阈值合入须 N≥30 |
| Iter 35 | **P3 分支**（按归因选 A/B/C/D）实现 + 真实 trace A/B | Iter 33 归因 + 真实 trace | flag 默认关；合入须 N≥30 |
| Iter 36+ | 阈值/开关校准（Phase C），持续收割至 N≥30 | Iter 34/35 | 逐项 A/B 后合入 |

## 风险登记
1. **P1 取数风险**：用户能否再取 reports 决定 P2/P3 能否定向。缓解：P1 设计为优雅降级（旧 trace 仍可解析），P0 不依赖 P1。
2. **P2 投影乐观**：Iter 27 根因未根除（隐藏天气）。缓解：保留效率门、不扫阈值、决赛图重测。
3. **P3 sim 不可验证**：博弈层须真实 trace。缓解：P3 排在 P2 后、默认关、严守 N≥30。
4. **过拟合初赛图**：决赛换新图。缓解：铁律 3（通用、读 start）、不硬编码、P2 分支 B 须决赛图重测。
5. **scope 蔓延**：每轮只做一个 Pn 的一个分支，A/B 不过门槛则 flag 保持关、代码保留作 variant 平台（同 Iter 26–28 惯例）。

## "打过前十"的可达性评估
- **P0**：+1 胜（4/10→5/10），确定。
- **P2**：+1~3 胜（翻 L1/L10/L9 的 −6/−2/−16），需 P1 归因 + 鲜度 +10~15。可达性中高。
- **L3(−21)/L6(−22)**：需鲜度 +20 或 P3 denial，难度高、风险大。可达性低中。
- **综合**：P0+P2 落地后 5/10→7/10 可期；"打过每个前十"需 P3 额外 denial 且取决于对手可预测性（P1 数据）。

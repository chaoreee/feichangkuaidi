# 迭代计划 v2 — 分析器驱动的证据型迭代

> 主题：把迭代方式从"建功能"切换为"先有地面真相，再求解真正的优化问题，最后才谈博弈"。
> 状态：设计基线（Iteration 21 评审通过，未改运行期代码）。后续实现按 Phase 进入 `client/`，每次能力变化同步更新 `CLAUDE.md` 能力矩阵与迭代日志。
> 上位文档：`CLAUDE.md`（SSOT）、`docs/game_theory_projection_strategy.md`（M8 博弈层设计，本文件对其做优先级重排与校准前置）。
> 规则权威：`一骑红尘：荔枝争运战 参赛选手任务书.md`、`一骑红尘：荔枝争运战 通信协议.md`。

---

## 0. 背景与动机

M8 博弈投影层 P1–P4 已全部落地（229 项单测通过），但一次对项目策略的三问分析暴露出三个结构性问题，促成迭代方式重排：

1. **验证真空下的过度 speculative 工程**：20 轮迭代、229 单测、P1–P4 全部建立在 mock 仿真（@r48 交付）之上，而项目文档自身明确 mock 不代表实战（真实交付在 450+ 帧），且仓库 `logs/` **零真实对局 trace**。P0（真实 trace 归因）从未执行。所有阈值（`LEAD_SAFE=40`、`ICE_BOX_USE_BELOW=78`、`TASK_SEEK_TARGET=90`、绕路上限 70 等）均为未校准初值；全部 `ENABLE_*` 博弈开关默认关。**博弈层在唯一测试环境里对动作零影响**（mode 恒 EVEN）。
2. **静态层未被当作优化问题求解**：`_plan` 是固定优先级贪心瀑布，不解静态权衡。最大静态杠杆——任务分冲 90（解锁送达基础分 120→240、用时系数满、里程碑 35，合计 ~+220 分）——只被机会式处理。漏 90 的代价远超整个 M8 博弈层的微调收益。
3. **博弈层优先级错置**：ROI 最低的 SET_GUARD 占了 P4 整轮，而收益最高的对手交互（GATE 验核窗口、终局交付 race、deny）要么没做对手建模要么开关关着。胜负是相对的，但 ΔEV 地板只优化自身绝对分——势均力敌局的赢法是"损己 X、损敌 >X"的 denial，而这侧最弱。

**结论**：范式（静态最优为体、博弈投影为用）正确，但**远未被执行到位**。正确的下一步不是再加博弈层功能，而是先建地面真相基础设施、求解静态优化、再按真实收益顺序逐项打开博弈开关。

---

## 1. 迭代方式总纲变更

### 1.1 证据型闭环（替换旧模式）

旧模式：`设计文档 → 实现 → 单测 → mock @r48 回归 → 更新基线`。它跳过了用真实/高保真对局证据驱动决策这一环。

新模式：每次改动必须满足下面证据链才能合入：

```
假设 → 仿真/真实 trace 证据 → 实现 → A/B 对比（同种子 baseline） → 仅当指标正向才固化
```

### 1.2 新"done"标准（替换"单测过 + mock @r48 交付"）

每次合入需满足**全部**：

1. 仿真器 50 局交付率 ≥ baseline（不回归）。
2. 仿真器 50 局 mean 终局分 ≥ baseline（或明确说明是降分换鲁棒性的取舍）。
3. 无 WAITING/MOVING 卡死回归（仿真器 + 真实 trace）。
4. 单帧决策仍在预算内（`config.DECISION_BUDGET`）。
5. 改动的每个阈值/开关在 `docs/calibration_v1.md`（或对应迭代文档）有证据行。
6. 涉及博弈层动作时：有同种子 A/B 的胜率/分差证据。
7. （分析器自身改动）分析器单测全过 + `rules.py` 对账自检 0 误差。
8. **A/B 达最小样本**（N≥30 配对；罕见事件 N≥100），否则结论标"假设级"不合入。
9. **无分段回归**：variant 在当前已赢分段（如 `mid_lead`、`delivered`）上不显著降分/降胜率——保护成功路径，防单点劣化（§3.7/§3.8）。
10. **单局只作假设来源**：任何改动须基于全语料聚合统计 + 置信区间，不基于单局结论。

### 1.3 与 M8 的关系

本文件不推翻 `game_theory_projection_strategy.md`，而是：

- **前置校准**：M8 一切阈值与开关的校准从"待真实 trace"变为"先经分析器 + 仿真 + 真实 trace 三级证据"。
- **优先级重排**：见 §6 M8 triage。SET_GUARD 冻结；GATE race / 窗口预测 / deny 提前。
- **补静态前置**：M8 的 ΔEV 地板输入（投影分）当前不可信（鲜度粗估），Phase B 升级鲜度模型后 ΔEV 才首次可用。

---

## 2. 核心设计原则：代码抽取事实，AI 只做解释

整个 v2 的基础设施是一条漏斗 + 一条不可逾越的分工边界。

### 2.1 分工边界

- **分析器 = 纯确定性 Python 代码**：从对局中抽取**事实**（交付帧、分项分、被拒动作、mode 切换、投影误差…）。事实 100% 准确、可复现、可单测。AI 不去日志里"猜"数字。
- **AI = 只读报告做解释**：基于结构化事实回答"为什么输/该怎么改"。AI 永不直接读 10w 字原始 trace，只在某报告指向"第 300 帧决策可疑"时按帧段取一小段原文深挖。
- **分析器不做优化、不出建议**——只做"抽取 + 聚合"。建议全部留给 AI 与人。这是 Iteration 6 旧 `analysis/` 模块被删的教训（它越界做了 optimizer）。

### 2.2 漏斗

```
单局 raw trace (100k+ 字)
        │  [代码：in-client 采集器，对局运行时累计]
        ▼
单局 report.json (2-4 KB，结构化事实)
        │  [代码：repo 侧聚合器，跨局统计 + A/B]
        ▼
analysis_report.md (5-10 KB，跨局对比 + 异常局标记)
        │  [AI：Claude Code 读此 + 被标记的单局报告]
        ▼
迭代决策（改 client / 调阈值 / 开关 A/B）
```

AI 输入从"50×10w 字"压到"一份聚合报告 + 几份被标记单局报告"（约 20KB 量级）。

---

## 3. 分析器架构（两层）

### 3.1 为什么分析器放在 client 之外（事后解析 trace）

`client/` 是提交到对战平台的交付件，对局运行时**只需要记录日志**，不做任何分析。分析器属于
仓库侧工具：对局结束后把取回的多份 trace 日志（`match_*.log`）事后解析为结构化单局报告，再跨局聚合。

因此分析模块 `analysis/` 位于仓库根（与 `client/` 同级、**不属于交付件**）。client 只负责把赛后
分析所需的事实写进人类可读 trace 日志（Frame/Action/Projection/ModeChange/Over/Score + 少量内部信号
`Rejected`/`CanAffordBlock`）；`analysis/parser.py` 把 trace 解析回结构化 `Report`，`analysis/aggregator.py`
跨局聚合。**代码抽取事实、AI 只做解释**，分析器不做优化。

> 与 Iteration 9 删模块的关系：旧 `analysis/` 是事后解析 + 越界优化，被删。新分析器仍是事后解析，
> 但**只抽取不优化**，且作为 client 之外的独立模块以正确形态回归。client 侧零分析负担、交付件最小化。
> client trace 已记录绝大部分事实（投影、mode、动作、终局分等）；仅被拒动作与 canAfford 拦截两处
> 内部信号由 client 额外写成 trace 行（`Rejected`/`CanAffordBlock`，纯日志），解析器据此还原。

### 3.2 交付件 1：`analysis/parser.py`（仓库侧，client 之外）

`parse_log(path) -> Report` 把一份 `match_*.log`（`client/logger/match_logger.py` 输出格式）解析为
schemaVersion=1 的结构化 `Report`（§3.4）。纯确定性、可单测，事实 100% 从日志文本抽取。

解析来源（trace 事件 → Report 字段）：
- `Startup`/`Start` → matchId/playerId/teamId/seed/durationRound；
- `Frame`（每帧 phase/node/state/fresh/goodFruit/taskScore/verified/delivered/events）→ 轨迹（freshness
  start/end/min、好果、好→坏阈值跨越）、验核帧、RUSH 触发帧、WAITING 停滞检测、中局 gap 快照、天气命中；
- `Action`（MOVE/USE_RESOURCE/CLAIM_TASK/CLEAR/BREAK_GUARD/FORCED_PASS/SET_GUARD/WINDOW_CARD/RUSH_*）
  → 资源·急策使用、任务领取、突破、设卡、窗口出牌、决策超时（ms）；
- `GuardDecision` → 设卡 defense/denial/gap；
- `Projection`/`ModeChange` → 投影分/置信采样/mode 切换/投影误差；
- `Over`/`Score` → outcome（WIN/LOSS/TIE/UNDELIVERED/RETIRED）、终局分、交付帧、scoreMargin；
- `Rejected`/`CanAffordBlock`（client 内部信号 trace 行）→ 被拒动作、canAfford/ΔEV 拦截。

`source`/`variant` 不在日志内，由聚合器按路径推断（`logs/real/`→platform、`logs/sim/`→sim；
父目录 `baseline`/`tuned`→variant），可被 CLI `--source`/`--variant` 覆盖。

**非功能约束**：
- 纯 stdlib；解析行无法识别时静默跳过，**永不抛出**。
- 单局开销可忽略；内存随日志行数线性（有界于对局帧数 ≤600）。

### 3.3 交付件 2：`analysis/aggregator.py` + `analysis/__main__.py`（仓库侧）

`python3 -m analysis <dirs>` 扫描目录下的 `match_*.log`（来自平台或仿真），`parser` 逐份解析为 `Report`，
`aggregator` 跨局聚合，输出**多份分工报告**：

- **`docs/analysis_report.md`**（主报告，累积聚合）：跨局统计（交付率、交付帧分布、mean/median 分、各分项分分布、失败模式频次、task-90 达成率、投影误差分布、mode 切换频次）+ **场景分段视图**（见 §3.7）+ 异常局标记（见下）。
- **`docs/ab_report.md`**（A/B 配对对比，存在 variant 时产）：按 seed 配对 variant vs baseline 的胜率、mean 分差、配对胜负、95% 置信区间、交付率/各分段回归检查。
- **`docs/calibration_v1.md`**（决策日志，按 `ab_report` 累积）：每个阈值/开关 → 证据（局数/分差/CI/分段表现）→ 取值，增量构建。

**累积语料库**：`python3 -m analysis` 每次读取 `logs/{real,sim}/` 下**全部** trace 重新解析聚合，新取回对局只往语料库追加。每次平台提交回来的对局数可能很少（1 局到几局），只有跨批次累积才够样本。

**source/variant 推断**：按日志路径推断（`logs/real/`→platform、`logs/sim/`→sim；父目录 `baseline`/`tuned`→variant），
仿真 A/B 把日志分放 `logs/sim/baseline/` 与 `logs/sim/tuned/` 即可自动 seed 配对。可被 `--source`/`--variant` 覆盖。

**异常局标记**（AI 深看的候选，**仅作假设来源**）：输局且 `task<90` 但 `missedReachable90=true`；`UNDELIVERED` 或 WAITING 卡死；投影误差 > 50 分；mode 应切未切；交付帧异常晚；以及 §3.8 的 lucky win / unlucky loss。

AI 读主报告 + 被标记的 3–5 份单局报告（各 2-4KB）即可定位问题。原始 trace 仅在单局报告指向某帧段可疑时，按帧段取一小段深挖。

### 3.4 单局报告 schema（`report.json`）

原则：**只收决策相关信息**，不 dump 每帧状态。带 `schemaVersion` 供聚合器版本路由。

```json
{
  "schemaVersion": 1,
  "matchId": "...", "playerId": "...", "seed": 12345,
  "source": "platform|sim",
  "outcome": "WIN|LOSS|TIE|UNDELIVERED|RETIRED",

  "finalScore": {
    "me":  {"total":765,"delivery":240,"task":125,"time":55,"goodFruit":165,"freshness":140,"bounty":0,"penalty":0},
    "opp": {"total":740,"delivery":240,"task":95,"time":52,"goodFruit":150,"freshness":148,"bounty":0,"penalty":0}
  },

  "delivery": {
    "me":  {"frame":470,"verifyFrame":463,"goodFruit":92,"freshness":78.3},
    "opp": {"frame":488,"verifyFrame":481},
    "rushTriggerFrame":450
  },

  "tasks": {
    "me":  {"base":90,"milestones":[60,90],"claimed":[{"template":"T02","node":"S07","frame":120,"detourExtra":4}]},
    "opp": {"base":60},
    "missedReachable90": false
  },

  "resources": {
    "iceUsed":[{"frame":200,"freshnessBefore":79}],
    "horseUsed":"FAST_HORSE@150",
    "rushTactic":{"type":"RUSH_PROTECT","frame":455}
  },

  "trajectory": {
    "freshness":{"start":100,"end":78.3,"min":76},
    "goodFruit":{"start":100,"end":92,"badCrossings":[90,80]}
  },

  "opponentInteraction": {
    "windows":[{"frame":125,"type":"RESOURCE","node":"S03","myCard":"BING_ZHENG","oppCard":"ABSTAIN","result":"WIN"}],
    "oppGuards":[{"node":"S10","frame":300,"defense":4,"blockedMe":true,"myResponse":"BREAK_GUARD","cost":{"good":1,"frames":0}}],
    "bounties":[{"node":"S10","available":true,"claimed":false,"value":18}],
    "myGuards":[]
  },

  "failures": {
    "rejected":[{"frame":200,"action":"MOVE","code":"MOVE_BLOCKED_BY_GUARD","target":"S10"}],
    "waitingStuck":[{"fromFrame":140,"toFrame":160,"node":"S14"}],
    "invalidActions":0,
    "decisionTimeouts":0,
    "canAffordBlocked":[{"frame":300,"action":"DETOUR_TASK","reason":"time"}]
  },

  "projection": {
    "modeSwitches":[{"frame":455,"from":"EVEN","to":"CONSERVATIVE","gap":45.0}],
    "confidence":{"min":0.30,"median":0.60,"max":0.80},
    "projectedMyScore":780,"actualMyScore":765,"error":15,
    "oppEtaPredictedDeliver":485,"oppActualDeliver":488
  },

  "classification": {
    "scoreMargin": 25,                  // 我方分 − 对手分（分差分布优于 W/L）
    "luckClass": "expected_win",        // expected_win|unlucky_loss|lucky_win|expected_loss（见 §3.8）
    "segments": ["delivered","task90_reached","mid_lead","weather_hit","contested"]  // 场景标签，供分段聚合
  },

  "decisionTimeline": [
    {"frame":120,"event":"TASK_CLAIM","detail":"T02@S07 +30"},
    {"frame":300,"event":"BREAKTHROUGH","detail":"S10 guard, cost 1 good"},
    {"frame":455,"event":"MODE_SWITCH","detail":"EVEN->CONSERVATIVE gap=45"}
  ]
}
```

### 3.5 聚合报告样例（AI 实际消费）

`analysis_report.md`（主报告，累积）：

```
# Aggregated Report — cumulative N=50 games (real) + N=50 (sim)
SAMPLE NOTE: real N=50 达 A/B 门槛；rare-event 频率需 N≥100，当前标"假设级"
WIN_RATE / MEAN_SCORE / DELIVERY_RATE / DELIVERY_FRAME / TASK_90_REACH / FAILURE_FREQ / PROJECTION  （同下表）

SCENARIO SEGMENTS（分段视图，防单点劣化的主防线）:
  delivered(true,  N=48):  W 0.71, mean 730, task90 0.85, stuck 0/48
  delivered(false, N=2 ):  UNDELIVERED, stuck 2/2          ← 卡死集中在此段
  task90_reached(N=34):    W 0.88, mean 775
  task90_missed (N=16):    W 0.31, mean 645, missedReachable90 9/16  ← 静态规划漏 90
  mid_lead      (N=20):    W 0.90  ← 领先段保护良好
  mid_trail     (N=18):    W 0.22  ← 落后段搏命不足
  contested     (N=11):    W 0.45, windowWinRate 0.55
  weather_hit   (N=23):    mean -28 vs weather_clean  ← 天气损失量化

LUCK CLASS（运气分类，按分差+play质量，非W/L）:
  expected_win 28 / unlucky_loss 6 / lucky_win 4 / expected_loss 12
  → unlucky_loss 6 局为修 bug 首选；lucky_win 4 局勿当实力强化

FLAGGED GAMES（仅假设来源，须全语料验证后才动手）:
- matchId=...  unlucky_loss, task_base=60 但 missedReachable90=true
- matchId=...  UNDELIVERED, waitingStuck @S14 frame 140-160
- matchId=...  unlucky_loss, projection error=58, mode 未切但 gap=-50
```

`ab_report.md`（A/B 配对，存在 variant 时）：

```
# A/B Paired — baseline vs variant, same 50 seeds
WIN_RATE:      baseline 0.62 / variant 0.58
MEAN_SCORE:    baseline 712 / variant 730 (+18, 95% CI [+6,+30])
DELIVERY_RATE: baseline 0.96 / variant 0.94   ← 回归检查
TASK_90_REACH: baseline 0.40 / variant 0.72   ← Phase B 关键指标
PAIRED:        variant wins 26 / loses 18 / ties 6
SEGMENT REGRESSION（任一回归即不合入）:
  mid_lead 段 mean: baseline 790 / variant 772 (-18)  ⚠ 成功路径劣化
  → 虽总分 +18，但领先段回归 → 不合入（保护成功路径，见 §3.8）
```

### 3.6 分析器自身可靠性（闭环关键一环，必须有测试 rigor）

- **单测**：`analysis/tests/test_parser.py`（构造合成 trace，逐字段断言解析）+ `analysis/tests/test_aggregator.py`（合成 Report 集，断言统计/A/B/对账/分段/异常标记）。
- **schema 版本路由**：`Report` 带 `schemaVersion`；聚合器只处理 `SUPPORTED_SCHEMA`，不兼容的跳过并记录（避免 client 升级后老日志解析错）。
- **对账自检**：聚合器用 `core/rules.py` 从 `Report` 的原始输入（task_base/goodFruit/freshness/deliverFrame）重算终局分，与 trace `Score` 行报告的 total 对账，不一致则标红（防解析器/规则镜像 bug 污染事实）。mock 真实分已验 0 误差。
- **缺失兜底**：解析失败/空日志的 trace 标"parse_failed_or_empty"跳过，AI 不据此臆断。
- **日志格式兼容**：parser 依赖 trace 文本格式（`match_logger.py` 输出）；格式变更须同步 parser + 单测。parser 是 trace 的唯一结构化消费者，格式漂移风险由单测兜住。

### 3.7 批量与分段分析（防单点过拟合——核心纪律）

**动机**：单点优化不是假设风险，是已发生事故——commit `839cfc9`/Iteration 8 就是针对一类"贪任务"场景调参，结果在别的场景烧好果败北。分析器从设计上必须杜绝"拿一局结论调全局参数"。

**最小样本门槛**（低于则标"低样本，仅作假设"，AI 不得据此改阈值/开关）：
- 配对 A/B：N≥30（同种子配对）才有排除 0 的 95% 置信区间。
- 罕见事件频率（WAITING 卡死、特定拒绝码、某失败模式）：N≥100 才可信。
- 跨批次累积达到门槛前，结论一律标"假设级"。

**场景分段视图**（`analysis_report.md` 必含）：按场景类别切分语料，每段分别报 W/L、mean 分、交付帧、失败模式频次。优化目标是**场景分布的整体**，不是某一局。分段维度：
- 交付 / 未交付；
- task-90 达成 / 未达（`missedReachable90`）；
- 中局（~r300）领先 / 落后 / 持平；
- 命中恶劣天气 / 否；
- 有对手争抢（窗口/设卡/任务争夺）/ 无；
- 对手交付 / 对手未交付。

若某改动把"失败段"修好却把"成功段"拉垮，分段视图立刻暴露——这是防单点劣化的主防线。

**迭代纪律（强约束，写进 §1.2 done 标准的执行细则）**：
1. 决策只依据聚合统计 + 置信区间 + 分段表现，**永远不依据单局**。
2. 单局只用于**生成假设**（"这局为何输？"→ 假设），假设必须在全语料上验证（该失败模式频次、该分段是否系统性偏差）后才动手。
3. 任何阈值改动须有 A/B 配对证据且**不引入任何分段回归**，否则不合入。

### 3.8 成功对局与失败对局并重（且不按 W/L 切）

**必须两者都分析**：
- **失败 → 修什么；成功 → 护什么**。只看失败、为修失败而调参，会在不自知的成功路径上埋雷。任何改动须验证"当前能赢的场景仍能赢"（A/B 分段不回归）。
- **胜因归因**：分析成功局会暴露——某被低估的能力其实在扛分；或某些赢是"对手失误送的"而非自己打得好。直接影响优先级排序。

**W/L 是噪声标签（关键洞见）**：赢 3 分和输 3 分本质是同一 play 质量 + 一次掷硬币。按 W/L 分析会被运气带偏。更稳健的口径是按**分差分布 + play 质量信号**分析——这些信号与胜负无关、与决策质量直接相关：
- 是否漏可达 90（`missedReachable90`）；
- 是否无谓烧好果（突破/窗口烧果是否换来正收益）；
- 是否卡死（WAITING 停滞）；
- 投影误差大小。

**运气分类**（标记到每局，聚合器按类汇总）：
- 该赢的赢了（expected win）/ 该赢的输了（**unlucky loss**，修真 bug）/ 该输的赢了（**lucky win**，别误当实力强化）/ 该输的输了（expected loss）。
- "该赢/该输"由分差 + play 质量信号判定，非单看结果。只对 unlucky loss 与 lucky win 动手：前者修真 bug，后者不当作策略成就去固化。

**A/B 回归检查**因此扩展为：variant 须在**当前已赢的分段**上不显著降分/降胜率，否则即便总分微涨也不合入（保护成功路径）。

---

## 4. Phase 0：真实 trace 收割 + P0 归因

**为什么先做**：M8 是否有价值、mock 是否可信、真实交付帧在哪——只用真实 trace 能回答。CLAUDE.md 已说明交付件可下载回 `logs/`。

**前置**：Iter 21 分析器基础设施就绪（report 随包回来）。

**做法**：
1. 用当前 client 打包提交，跑 5–10 局真实对局，取回 `client/logs/*.report.json` + `*.log` 到 `logs/real/`。
2. 跑 `scripts/analyze_logs.py logs/real/` → `docs/p0_attribution.md`：每局结局分类（是否交付/交付帧/分项分）、输因归类（未交付 / 静态权衡失误 / 对手交互 / 其它）、mode 实战是否切过档、有无卡死回归。
3. 这批 trace 同时作为 Phase A 仿真器的**保真度锚点**。

**若平台暂不可用**：Phase 0 降级为"待真实 trace"风险标记，先做 Phase A，但 Phase A 保真度结论须标"待真实 trace 验证"。建议尽早做哪怕少量真实局，去风险价值最高。

**验收**：`docs/p0_attribution.md` 给出真实交付帧分布 + 败因分布 + 对 mock 保真度的初步结论。

---

## 5. Phase A：高保真自博弈仿真器

**目标**：替换不可信的 mock @r48，提供规则忠实、可复现、可 A/B 的实验台。

**关键设计原则——物理引擎复用 `core/rules.py`**：仿真器移动/鲜度/天气/设卡/得分公式**一律调用 `core/rules.py`**，不重写。保证"仿真器物理 = 我们的规则镜像"，消除 mock 自成一套简化物理的问题。剩下无法内部验证的只有"规则镜像是否 = 平台"，由 Phase 0 真实 trace 兜底。

**交付件**：`scripts/sim_server.py`（重构 `mock_server.py` 或新建）
- 载入 `samples/map_config.json`（已提供，真实竞技图配置）。
- 两侧各跑一个 `DecisionEngine`（A/B 时一侧 baseline、一侧 variant）；每帧为双方构建 `WorldState` 喂给决策引擎，回收动作按 `rules.py` 结算。
- 忠实实现：真实路线距离×耗时系数、4 次天气（80–120/200–240/320–360/440–480，提前 30 帧预告）、全固定处理站、鲜度阈值转坏（90/80/…/10）、冰鉴/马/疾行/护果/破关、RUSH 触发（390–449/450 强制）、**路线边空动作被 park 成 WAITING**（Iteration 8 真实败局行为）。
- 确定性种子；输出与真实平台**同格式** trace + `report.json`（复用 in-client 采集器）到 `logs/sim/`。
- 内置 `SimValidator`：赛后用 `rules.py` 重算终局分与仿真器结算逐项对账。

**验收**：
- baseline vs baseline 50 局，双方交付率 ≥95%，交付帧分布落在 Phase 0 真实区间（若 Phase 0 缺失，先要求 [400, 520] 且非 ~r48）。
- 无 WAITING 卡死回归；`SimValidator` 对账 0 误差。
- 仿真器能在同种子下复现 Iteration 8 卡死败局（验证复现真实失败模式的能力）。

---

## 6. Phase B：把静态层当作优化问题求解（最高得分增量）

**问题**：`_plan` 贪心瀑布不求解静态权衡。任务分冲 90 杠杆（~+220 分）只被机会式处理。

**目标**：用显式静态规划器替换瀑布中的任务/绕路/急策部分，**保底"若 90 在交付预算内可达则必达"**。

### 6.1 交付件：`strategy/static_planner.py`

```python
@dataclass(frozen=True)
class StaticPlan:
    task_bundle: tuple[task, ...]      # 计划要做的任务（使其和 ≥ 目标里程碑）
    target_milestone: int              # 0|60|90|110，当前可达的最高里程碑
    route: tuple[node, ...]            # 含任务点的候选路线
    rush_decision: str | None          # None|SPEED|PROTECT|BREAK
    ice_strategy: float                # 冰鉴使用阈值
    projected_score: float             # 该计划投影终局分（rules.py + 精细鲜度模型）
```

### 6.2 核心算法（实用版，非全组合搜索）

1. **里程碑可达性**：对 90/60/110，贪心+剪枝枚举"位于候选最短路附近、detour 代价最小"的任务子集，判断 `_can_afford` 预算内能否达成。选可达的最高里程碑（90 优先，跨 90 边际价值最大）。
2. **路线评分**：对达成该里程碑的若干候选任务子集，各算一条含任务点路线，用 `rules.py` 投影终局分：路线时间（→用时分）、按路线类型累计鲜度损耗（→鲜度分+好果转坏）、任务分+里程碑、好果分、悬赏分。取投影分最高者。
3. **急策/冰策预案**：选定路线上按鲜度临界点定 RUSH_PROTECT 时机、按"远处且无马"定 RUSH_SPEED、按冰鉴库存与阈值定 ice_strategy。
4. **接入**：`_plan` 改为"先查 `self.static_plan`（每 N 帧或关键事件重算），按 plan 决定任务/绕路/急策；安全地板（`_can_afford`/`_keep_moving`/突破）保持不变作兜底"。

### 6.3 鲜度投影升级（顺带修 ΔEV 输入质量）

把 `AVG_FRESHNESS_LOSS_PER_FRAME=0.06` 升级为按路线类型逐边累计（`rules.FRESHNESS_LOSS_MOVE`），计入已预告天气系数与急策系数。让 ΔEV 地板与投影分首次可信。

### 6.4 验收（Phase A 仿真器上）

- "90 可达"局中 baseline 达成 task≥90 比例 > 80%（当前未度量，预计显著低）。
- 50 局 mean 终局分较旧瀑布 +30 以上（主要由送达基础分+用时系数+里程碑贡献）。
- 交付率不回归；交付帧不显著推迟（< +15 帧）。
- 聚合器 `TASK_90_REACH` 指标显著提升。

---

## 7. Phase C：仿真驱动的阈值校准

**目标**：所有"初值待校准"阈值换成有证据的值；每个 `ENABLE_*` 开关给出"开/关 + 理由"。

**做法**：
1. **单阈值扫描**：仿真器 1D 扫描，每值 30–50 局，记录 mean 分 + 交付率 + 交付帧：
   - `ICE_BOX_USE_BELOW`（70/78/85/88）
   - `TASK_DETOUR_MAX_EXTRA_FRAMES`（50/70/90）
   - `RUSH_PROTECT` 鲜度阈值（75/85/90）
   - ΔEV 地板阈值（0/4/8）
2. **开关 A/B**：每个 `ENABLE_*`（TASK_RACE/TASK_DENY/FRESHNESS_RACE/RESOURCE_DENY/CONDITIONAL_GUARD/OFFENSIVE），同种子 baseline-off vs on 各 50 局，记录胜率 + mean 分差 + 交付率回归。
3. 产出 `docs/calibration_v1.md`：每阈值/开关的取值、证据（局数、分差、置信区间）、理由。据此更新 `config.py`。

**验收**：`config.py` 每个被改动的值在 `calibration_v1.md` 有证据行；任何"打开"的开关必须有 A/B 正收益且无交付率回归。

---

## 8. Phase D：博弈层重排优先级 + 真实 trace 二次校准

**问题**：胜负相对但 ΔEV 只优化自身绝对分；势均力敌局赢法是 denial，而这侧最弱、默认关。SET_GUARD ROI 最低却占了 P4。

### 8.1 D1：GATE 验核 race（最高价值，新增）
- 终局谁先验核直接影响交付帧，对手交互中收益最高、最确定。
- 用 §6.1 ETA 估对手到 S14 帧数 + 是否已验核；若对手将与我在同窗口争 GATE，决定是否提前到 S14 抢拍 / 是否用破关令绑 `VERIFY_GATE` 减时（-3 帧）。
- 接入 `_plan` 宫门分支；开关 `ENABLE_GATE_RACE` 默认关，仿真 A/B 正收益后开。

### 8.2 D2：窗口 EV 加对手出牌预测（扩展现有）
- 当前 `_window_card`"无代价牌恒出"是粗策略。利用全信息（对手历史窗口出牌可统计）预测对手本拍最可能牌，按 §5.4.4 胜负矩阵选期望胜点最高牌。
- 增量改造 `_window_card`，不新增开关。

### 8.3 D3：Deny 正式化（势均力敌局打开）
- 当前 task/resource deny 默认关。仿真 A/B 证明"势均力敌局（|gap| 小）开 deny 净胜负收益为正"后，按 |gap| 区间条件打开，而非全局开。
- **denial 的 ΔEV 评估换口径**：从"自身净分"改为"自身净分 − 对手净分"（相对分），这才反映胜负。

### 8.4 D4：SET_GUARD 条件化设卡——冻结
- 保留 P4 实现不动，`ENABLE_CONDITIONAL_GUARD` 继续默认关。
- 仅当真实 trace 出现"锁胜局且对手无坏果可低价破卡"的具体场景时才重新评估。不在它上面花新迭代。

### 8.5 真实 trace 二次校准
Phase D 期间继续收割真实 trace，对照仿真结论。冲突时以真实 trace 为准回头修仿真器保真度（反馈 Phase A）。

**验收**：D1/D2/D3 每项有仿真 A/B 证据；真实 trace 中能解释至少一局"因 GATE race / 窗口预测 / deny 改变胜负"的案例。

---

## 9. M8 已实现能力 triage

| 能力 | 处置 | 依据 |
|---|---|---|
| Layer 1 投影总线（纯观测） | **保留** | 零风险，后续校准基础设施 |
| ΔEV 地板 `net_score_delta` | **保留并升级输入** | Phase B 鲜度模型升级后首次变可信 |
| P2 档位调参/悬赏/终局 race/窗口 EV | **仿真 A/B 后逐项定开/关** | Phase C |
| P3 ETA | **保留**（D1/D3 输入） | 纯观测 |
| P3 任务/鲜度/资源 race | **A/B 后按 \|gap\| 条件开** | Phase C / D3 |
| P4 条件化 SET_GUARD | **冻结，不再投入** | ROI 最低，D4 |

---

## 10. 迭代排期

| 迭代 | 内容 | 依赖 |
|---|---|---|
| **Iter 21** | **分析器基础设施**：`AnalysisCollector` + report.json schema + `analyze_logs.py` + 单测 + 对账自检（**本文件**，未改运行期决策代码） | — |
| Iter 22 | Phase 0：提交 client 收割带 report 的真实对局，跑聚合器，AI 读 `analysis_report.md` 做 P0 归因 | Iter 21 |
| Iter 23 | Phase A：高保真自博弈仿真器（复用 `rules.py`，产出同格式 report）+ SimValidator | — |
| Iter 24 | Phase B 上：静态规划器（任务-90 可达性 + 路线评分）+ 鲜度投影升级 | A |
| Iter 25 | Phase B 下：接入 `_plan`，瀑布改 plan 驱动（安全兜底不变）+ 仿真验收 | 24 |
| Iter 26 | Phase C：阈值扫描 + 开关 A/B，产出 `calibration_v1.md` | A, B |
| Iter 27 | Phase D1：GATE 验核 race | A, C |
| Iter 28 | Phase D2：窗口 EV 对手出牌预测 | A, C |
| Iter 29 | Phase D3：deny 按 \|gap\| 条件化 + 相对分 ΔEV | A, C |
| 持续 | 真实 trace 二次校准；SET_GUARD 冻结 | 各 |

---

## 11. Iter 21 落地步骤（分析器基础设施）

1. 定 `Report` schema（§3.4），加 `schemaVersion: 1`。
2. **client 侧（仅日志）**：`main.py`/`decision.py` 把赛后分析所需事实写进 trace（Frame/Action/Projection/ModeChange/Over/Score 已有；新增 `Rejected`/`CanAffordBlock` 内部信号 trace 行 + Start 行补 `seed` + WINDOW_CARD 行补 `contestType`）。client **不写结构化报告、不含分析模块**。
3. **仓库侧 `analysis/`（client 之外）**：`parser.parse_log` 把 `match_*.log` 解析为 `Report`；`aggregator` 跨局统计 + seed 配对 A/B + 异常局标记 + `rules.py` 对账；`__main__` 为 CLI。
4. 单测：`analysis/tests/test_parser.py`（解析字段）+ `analysis/tests/test_aggregator.py`（统计/A/B/对账/schema 路由/分段/异常）。
5. 用现有 mock 跑几局自测（mock 产 trace），`python3 -m analysis` 解析聚合，确认端到端链路通、对账 0 误差；mock 零回归 @r48。
6. 同步更新 `CLAUDE.md` 能力矩阵（§4.4 赛后分析）与迭代日志。

---

## 12. 成功标准

短期（Iter 21–23）：
- 分析器产出可信、对账 0 误差的单局/聚合报告；AI 据此完成 P0 归因。
- 仿真器复现真实交付帧范围与 Iteration 8 卡死失败模式。

中期（Iter 24–26）：
- 静态规划器使 task-90 达成率显著提升；mean 分 +30 以上且交付率不回归。
- 所有阈值/开关有仿真 A/B 证据，写入 `calibration_v1.md`。

长期（Iter 27+）：
- 博弈层按 GATE/race/deny 真实收益顺序逐项打开，每项有 A/B 正收益。
- 每轮真实对局按"trace → report → 聚合 → AI 归因 → 校准 → 实现 → A/B → 固化"闭环推进，证据可追溯。

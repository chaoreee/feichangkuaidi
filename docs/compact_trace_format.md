# 精简 trace 格式 spec（P1-B）

> 由 `analysis/compact.py` 的 `compact_trace` 从完整 trace 派生，落 `reports/match_<id>.compact.log`。
> 目的：完整 trace ~880KB/局无法上传，精简格式 ~6–9KB/局（gzip+base64 ~1.4KB）使我 pull 后能直读、绕开上传瓶颈。
> `parse_compact(text)` 把精简文本还原为与 `parser.parse_log` 同 schema 的 `Report`（关键字段 0 误差）。

## 设计原则

- **事件驱动**：帧状态只在**变化时**记一行，动作只在 **(action, 关键参数) 变化时**记，连续相同拒绝/canAfford 合并。膨胀源（每帧 Frame/Projection/Eta/Action 四行 ×600 帧）被压缩到 ~150–330 行/局。
- **派生而非双写**：精简 trace 从完整 trace 重生成，属 repo 产物（不进 client），演进只改 `analysis/compact.py` 一处。
- **P1-A 透传**：精简从完整 trace 派生，P1-A（Iter 31）补记的 `oppResources`/`Guards`/`scoreDetail` 一旦进入完整 trace 自动流进精简格式，无需改 compact。
- **优雅降级**：旧 trace 缺 P1-A 字段时，精简格式相应行缺字段标 absent（`-`），`parse_compact` 仍可重建 Report。

## 多局文件

一个 `.log` 文件含多局（如 sim 同种子重跑追加）时，每局输出一个**块**，块间以单独一行 `---` 分隔。`parse_compact` 解析**首块**（与 `parse_log` 的"一文件一 Report"语义一致）。真实平台 1 局/文件 → 单块。

## 行类型枚举

### 头部
```
# <matchId> v=<clientVersion> pid=<playerId> team=<teamId> seed=<seed> dur=<durationRound>
```
- `v`/`pid` 缺失时记 `-`（Startup 未记则 absent）。

### 拓扑（来自 Map 行）
```
Map N=<节点数> E=<边数>
N <S01:S> <S02:C> ...          # 节点 id:类型首字母（START→S, CHECKPOINT→C, PASS→P, DOCK→D, ...）
E <S01-S02:30:R> <S02-S03:25:R> ...  # 边 from-to:距离:路线类型首字母（ROAD→R, WATER→W, BRANCH→B, MOUNTAIN→M）；定向边用 >
T <S05:t1:20> ...              # 任务点 nodeId:templateId:score（无任务则省略）
```

### 帧变化 `F`
```
F r<round> <changes...>
```
首帧强制记初始结构状态：`F r1 n=<node> st=<state> ph=<phase> gf=<goodFruit> ts=<taskScore> on=<oppNode> ots=<oppTask>`。其后仅当某项变化时记该 token：
- `n=<node>` 到站（节点变化）
- `st=<state>` 状态跃迁（IDLE/MOVING/WAITING/PROCESSING/...）
- `ph=<phase>` 阶段跃迁（NORMAL/RUSH/...）
- `gf=<goodFruit>` 好果变化
- `ts=<taskScore>` 我方任务分变化
- `on=<oppNode>` 对手节点变化
- `ots=<oppTask>` 对手任务分变化
- `del=1` 本帧首次 delivered=True
- `vfy=1` 本帧首次 verified=True（验核完成）
- `w=<weather>` 本帧有生效天气（非空）
- `fr<t>` 我方鲜度下行跨越阈值 t（t∈{90,80,70,60,50,40,30,20,10}，去重）
- `ofr<t>` 对手鲜度下行跨越阈值 t

无变化的帧不输出行。

### 动作 `A`
```
A r<round> <action> [target=..] [res=..] [task=..] [contest=..] [type=..] [card=..] [good=..] [extra=..] [fresh=..] [ms=..]
```
仅当 `(action, target, res, task, contest, type, card, good, extra)` 复合键变化时记一行（连续相同 MOVE 等合并为 1 行）。`NONE` 心跳丢弃，除非超预算（带 `ms=`）仍记以还原 `decisionTimeouts`。`fresh=` 仅 USE_RESOURCE 携带（还原 ice_used 的 freshnessBefore）。`ms=` 仅超预算时携带。

涵盖：`MOVE` / `USE_RESOURCE` / `CLAIM_TASK` / `SET_GUARD` / `BREAK_GUARD` / `CLEAR` / `FORCED_PASS` / `RUSH_PROTECT` / `RUSH_SPEED` / `WINDOW_CARD`。

### 拒绝合并 `REJ`
```
REJ r<首次帧> x<连续次数> <code> <action> <target>
```
连续相同 `(action, code, target)` 的 Rejected 合并为一行。vs2735 的 224 次连拒 → 1 行 `REJ x224`。`parse_compact` 按次数展开还原 `rejected` 列表长度。

### canAfford 合并 `CAB`
```
CAB r<首次帧> x<连续次数> <action> <reason> <target>
```
同上合并；`parse_compact` 展开时对齐 parser 的 40 条上限。

### 信号行（原样紧凑保留）
```
ModeChange r<round> <from>-><to> reason=<reason> gap=<gap>
GuardDecision r=<round> target=<t> reason=<r> gap=<g> defense=<d> denial=<v> extraGood=<e>
Bounty r=<round> target=<t> reward=<r> delta=<d> extra=<e> action=<a> goodBurn=<g>
```

### 尾部摘要
```
Traj fstart=<..> fmin=<..> fend=<..> gstart=<..> gend=<..> onode=<..> ofend=<..> ogend=<..>
Proj my=<投影我方分> oppDel=<对手投影交付帧> gap=<gap> mode=<mode>
Conf min=<..> med=<..> max=<..>
MidGap=<中局gap>            # r300 前最后 gap；无则省略
```
- `Traj`：鲜度/好果轨迹起止与最小值（事件驱动跨越大不自携 min，故摘要补全）。
- `Proj`/`Conf`：投影总线末帧值与置信统计（逐帧 Projection 不入精简，仅末帧+统计）。
- `MidGap`：中局分差（r300 前最后 gap），供 `segments` 的 mid_lead/trail/even。

### 结算
```
Over result=<resultType> reason=<reason> round=<overRound> winner=<winner> iWon=<iWon>
Score me total=<t> del=<delivered> dframe=<deliverRound> fresh=<f> good=<g> task=<taskScore> bounty=<bountyScore> [det=<scoreDetail>]
Score opp total=<t> del=<delivered> dframe=<deliverRound> fresh=<f> good=<g> task=<taskScore> bounty=<bountyScore> [det=<scoreDetail>]
```
- `det=` 仅 P1-A（Iter 31）补记 scoreDetail 后出现；旧 trace 省略，`parse_compact` 对应分项为 null（与 parser stub 一致）。

## 还原保真度

`parse_compact` 复用 `analysis.parser` 的 `_final_score`/`_task_block`/`_segments`/`_luck_class` 组装 Report，保证 schema 与 `parse_log` 一致、防漂移。关键字段（matchId / outcome / finalScore 双方 / deliverFrame / oppGuards / 失败模式计数 / trajectory / projection / classification）roundtrip 0 误差。

### 已知近似（非关键字段）
- `decisionTimeline`：parser 逐次记录每个动作/拒绝，精简合并后只保留去重事件 → 条目数偏少（时序事件本身保留，仅重复折叠）。
- `decisionTimeouts`：连续超预算的相同动作被折叠 → 计数可能偏少（超预算罕见，实战影响可忽略）。
- `waitingStuck`：基于状态/节点**变化**推算 WAITING 持续帧数（与 parser 逐帧计数逻辑等价，帧边界一致）；局末未解除的 WAITING 停滞 parser 同样不记录（行为一致）。

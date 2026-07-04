# Delivery Specification — 交付件规格基线

> 明确比赛交付件必须满足的全部要求，作为代码实现与验收的依据。
> 权威来源：`一骑红尘：荔枝争运战 参赛选手任务书.md`（下称"任务书"）、`一骑红尘：荔枝争运战 通信协议.md`（下称"协议"）。本规格与其冲突时以原始文档为准。
> 勾选框用于验收：`[ ]` 未达成 / `[x]` 已达成。

---

## 1. 功能要求

### 1.1 消息生命周期（协议 §2）— M1 已打通
- [x] 连接后发送 `registration`（playerId/playerName/version）
- [x] 收到 `start`，缓存 matchId、本方 playerId/teamId、nodes/edges/resources/taskTemplates/map.gameplay
- [x] 发送 `ready`（matchId==start.matchId，round==start.round 通常为 1）
- [x] 循环：收 `inquire(N)` → 发 `action(round=N)`
- [x] 收 `over` 后读取 resultType/winnerPlayerId/players[].totalScore 并退出
- [x] 收 `error` 时记录并继续（M1 记录级；分类修正待 M2）

### 1.2 动作矩阵（协议 §8 / 附录 E；必填字段必须齐全）
主车队：`WAIT` `MOVE(targetNodeId)` `DELIVER` `VERIFY_GATE(可选 rushTactic)` `SET_GUARD(targetNodeId,可选 extraGoodFruit 0-2)` `BREAK_GUARD(targetNodeId,可选 goodFruit/badFruit 0-2,rushTactic)` `FORCED_PASS(targetNodeId)` `CLAIM_RESOURCE(targetNodeId,resourceType)` `USE_RESOURCE(resourceType,情报需 targetNodeId)` `CLAIM_TASK(taskId)` `CLEAR(targetNodeId)` `PROCESS` `DOCK`
小分队：`SQUAD_SCOUT/CLEAR/REINFORCE/WEAKEN(targetNodeId)`
窗口：`WINDOW_CARD(contestId,card)`
急策：`RUSH_SPEED` `RUSH_PROTECT`；`BREAK_ORDER` 仅作为 `rushTactic` 绑定 `BREAK_GUARD`/`VERIFY_GATE`，禁止独立发送
- [x] 每帧动作类别上限：主车队/小分队/急策各 1，窗口 1 个 contestId（M5 至多 1 主车队 + 1 小分队探路同帧）
- [x] 输入=inquire 公开状态；输出=合法 actions 数组；空时发 `[]`

### 1.3 状态机（任务书 §3.1 / §8.2）
IDLE / MOVING / WAITING / PROCESSING / CONTESTING / RESTING / FORCED_PASSING / VERIFYING / COST_BANKRUPT / DELIVERED / RETIRED。
- [x] 按当前 state 只提交该状态允许的动作（M3：非空闲态与已交付均发空心跳让服务端推进；仅 IDLE/COST_BANKRUPT 主动决策）

## 2. 通信协议一致性（协议 §1/§3/§11）
- [x] 帧格式：5 位十进制长度前缀（UTF-8 字节数，最大 99999）+ UTF-8 JSON body
- [x] 接收端处理半包（缓存至完整）、粘包（按前缀循环拆多条）、中文跨包（先按字节缓存再解码）— 单测覆盖
- [x] `msg_name`/`msg_data` 外层；字段名与枚举**大小写敏感**（枚举集中于 enums.py）
- [x] 必传字段齐全；可选字段不误传无关字段（actions 构造器只填相关字段）
- [x] `action.round` 严格等于当前 `inquire.round`，不提前发未来帧
- [ ] 立即 error 码全覆盖处理：INVALID_LENGTH_PREFIX / INVALID_JSON / INVALID_ACTION_TYPE / MATCH_ID_MISMATCH / ACTION_TOO_LATE / DUPLICATE_ACTION / PLAYER_* / MATCH_ALREADY_STARTED（M1 已记录，分类处置待 M2）
- [ ] 业务拒绝/非法动作从下一帧 `events[]` + `actionResults[]` 读取 errorCode，不误判为立即 error（M2）
- [ ] 动作是否生效：不只看 `accepted=true`，结合 `events[]` 与下一帧状态（协议 §10）（M2/M3）

## 3. 性能要求（协议 §8 动作提交截止）
- [x] 单帧决策预算 400ms（config.DECISION_BUDGET）；超预算记录告警。占位策略即时返回（M3 起若引入重计算再加硬中断）
- [x] 无阻塞导致漏发帧；接收与决策分线程，互不卡死
- [x] 内存轻量（日志逐行 flush 写文件，不全量驻留）
- [x] 单帧异常被捕获，降级为空动作心跳，绝不使进程崩溃或失联

## 4. 工程要求（任务书 §10）
- [x] Python 运行（代码保持 3.9+ 兼容，目标 3.12.9；本地以 3.9.13 验证通过）
- [x] **纯标准库**，无第三方依赖（socket/json/threading/queue/os/time/unittest）
- [x] 文件结构：见 `docs/architecture.md`；`client/` **本身即交付件根目录**，`start.sh` 与 `main.py` 同级（打包时 `client/` 内容直接构成 ZIP 根，不套同名目录）
- [x] `start.sh` 接收 3 参数 `playerId host port` 并透传同目录 `main.py`；不写死 playerId/host/port/阵营；**脚本内不含中文**
- [x] 配置集中于 `client/config.py`（超时、决策预算、日志目录、调试开关）
- [x] 日志格式：人类可读 trace，每行一事件 `<时钟> <Event> matchId=..., round=..., k=v`，写入 **`client/logs/`**（包内）
- [x] **结构化分析报告**（Iter 21 已实现，分析模块在 **client 之外**，详见 `docs/iteration_plan_v2.md`）：client 只记 trace 日志（含 `Rejected`/`CanAffordBlock` 内部信号行），**不含分析模块、不写结构化报告**；仓库根 `analysis/` `parser.parse_log` 把取回的 `client/logs/match_<id>_<pid>.log` 解析为 `Report`（schemaVersion=1，纯 stdlib·永不抛出），`aggregator` 聚合产出 `docs/analysis_report.md`（跨局统计 + 场景分段 + 运气分类 + seed 配对 A/B[95% CI + 分段回归 + 低样本标记] + 异常局标记 + `rules.py` 对账自检）+ `docs/ab_report.md`；CLI `python3 -m analysis <dirs>`。**代码只抽取事实、不做优化**；Claude Code 读聚合报告归因，不直读 10w 字原始 trace；14 项 parser + 18 项 aggregator 单测全通过
- [x] 启动方式：`./start.sh <playerId> <host> <port>`（等价本地 `python client/main.py <playerId> <host> <port>`）
- [x] 运行时不执行 pip/npm/apt 等安装，不联网下载，不写系统目录

## 5. 得分导向（任务书 §7，指导策略取舍）
- [x] **稳定交付第一**：M3 基线策略以走完全程并交付为首要目标（仿真验证 @r60 交付成功）
- [x] 交付需同时满足：位于 S15 + 已验核 + 好果>0 + 鲜度>0（M3 在 DELIVER 前校验；非空闲态不提交）
- [x] 鲜度阈值转坏（90/80/…/10）与鲜度归零报废逻辑纳入 core 计算（`rules.crossed_good_to_bad_thresholds`）；M4 用冰鉴护阈值
- [x] 皇榜任务基础分累计达 90 才拿满送达/用时；里程碑 60/90/110 额外加分（M4 机会式做任务追求累计；绕路做任务待后续）
- [x] 避免惩罚：M4 仅在满足条件时提交动作（非空闲态心跳、任务/资源过守卫），不提交已知非法动作

## 6. 提交前自检清单（任务书 §10.7）
**打包由人工完成**（仓库不再保留打包脚本）：把 `client/` 的**内容**压成 ZIP，使 `start.sh` 直接位于 ZIP 根。打包前逐项对照：
- [x] ZIP 根目录直接含 `start.sh`（`client/` 内容即 ZIP 根，未多套一层同名目录）
- [x] `start.sh` 具可执行权限（`git ls-files --stage` 显示 100755；打包时保留可执行位）
- [x] `start.sh` 接收 `playerId host port` 三参数，透传同目录 `main.py`，脚本内不含中文
- [x] 不写死 playerId/host/port/阵营（参数全来自 argv/start；无硬编码 IP）
- [x] 第三方依赖已随包提供（当前为零依赖，纯标准库 socket/json/threading/queue/…）
- [x] 运行时不执行现场安装或联网下载（无 pip/npm/apt install）
- [x] 打包前剔除运行期产物：`__pycache__/`、`logs/*.log`（可选剔除 `tests/`）
- [x] 已完成本地启动测试：client 对 `scripts/mock_server.py` 端到端跑通交付（本机用 `py`；平台环境经 `start.sh` 用 python3）

"""集中配置：参数、超时、开关。

禁止写死 playerId / host / port / 阵营（由启动参数与 start 动态决定）。
所有时间单位为秒（除非显式标注）。
"""

# ---- 客户端标识 ----
CLIENT_VERSION = "1.0"
DEFAULT_PLAYER_NAME = "litchi-agent"

# ---- 帧格式（协议 §1）----
LENGTH_PREFIX_WIDTH = 5          # 5 位十进制长度前缀
MAX_FRAME_BODY_BYTES = 99999     # body 的 UTF-8 字节数上限

# ---- socket ----
RECV_CHUNK = 65536               # 单次 recv 读取字节数
CONNECT_TIMEOUT = 10.0           # 建连超时

# ---- 时序超时 ----
HANDSHAKE_TIMEOUT = 30.0         # 等待 start 的最长时间
RECV_LOOP_TIMEOUT = 1.0          # 主循环从收包队列取消息的等待间隔
DECISION_BUDGET = 0.4            # 单帧决策软预算（超过则记录告警；协议建议 500ms 内）

# ---- 日志 ----
LOG_DIR = "logs"                 # 相对 client/ 解析为包内 client/logs/（交付件随包下载可取回 trace 日志）
DEBUG = False                    # 调试开关：True 时额外向 stderr 打印

# ---- 策略调参（M4 收益策略）----
ICE_BOX_CAP_AVOID = 90.0            # 冰鉴使用上限：鲜度≤此值即用。+10 偏移不撞 100 上限（无浪费）；
                                    #   >此值不用（撞上限浪费鲜度，且抢破关令验核额度）。
                                    #   Iter15 真机归因：鲜度损耗线性，冰鉴 +10 是交付前的"永久偏移"——无论何时
                                    #   使用，最终鲜度都 +10（前提不撞上限）。故最优=持有时尽快在≤90 时用，用满
                                    #   2~3 个冰鉴叠加 +20~30 偏移：既涨交付鲜度分(+18~36)，又可能把 80 阈值延后
                                    #   到交付之后(+3.6 好果分)。旧"仅近阈值≤7 使用"过保守，整局只用 1 个，余量闲置。
CLAIM_ICE_BOX_KEEP = 3              # 期望至少持有的冰鉴数（低于则在有货节点领取；多屯以叠加偏移）。
                                    #   真机归因：7/7 跨 80 阈值 = 关键时刻无冰鉴；持有量不足是根因。
ICE_BOX_DETOUR_KEEP = 2             # 绕路收集冰鉴的目标持有量：达到即不再为冰鉴绕路。2 个 +20 偏移可把 80 阈值
                                    #   延后到交付之后（省 1 篓好果+鲜度分），第 3 个受 100 上限制约收益递减。
ICE_BOX_DETOUR_PROJECTED_BELOW = 85.0  # 绕路收集冰鉴的触发线：投影交付鲜度(含已持冰鉴 +10/个)低于此值才绕。
                                    #   鲜度充足时不牺牲用时分；仅在鲜度将崩盘时以时间换鲜度（用户优先鲜度诉求）。
ICE_BOX_DETOUR_MAX_EXTRA_FRAMES = 60  # 绕路收集单个冰鉴允许的最大额外帧（相对直达终点）。
ICE_BOX_DETOUR_NET_MIN = 6.0          # 绕路收集冰鉴的净鲜度收益下限：冰鉴 +10 偏移 − 绕路额外鲜度损耗 ≥ 此值才绕。
                                    #   排除山路/支路等高损耗绕路（如 S06：S01→S06 山路 0.07 损耗，净收益 <6 被排除），
                                    #   保留官道绕路（如 S03→S07：ROAD 0.055，净收益 ~7）。避免绕路反而拖垮鲜度。
HORSE_MIN_REMAINING_DISTANCE = 30   # 剩余到终点路线距离大于此，才值得领取/使用马
RUSH_PROTECT_FRESHNESS_BELOW = 90.0  # RUSH 阶段鲜度低于此用护果令保鲜
DELIVER_TIME_SAFETY_MARGIN = 25     # 通用交付时间安全余量(帧)：交付/资源/设卡等读条后仍能按时交付
TASK_SEEK_TARGET = 130              # 绕路做任务的基础分上限：基础分累计达此值即不再为任务绕路。
                                    #   任务分 = min(180, base + 里程碑)；base≥110 → +50 → base≥130 即封顶 180（§7.2）。
                                    #   超过 130 的任务零分收益（任务分已 180、送达基础分在 base≥90 饱和、用时分在 base≥90 饱和），
                                    #   只徒增处理帧(延误交付)与鲜度损耗 → 净负，故 130 是严格上限。
                                    #   Iter16 根因修正：旧值 180 + SKIP_TASK_TEMPLATES 跳过 T04/T06 → 5 模板地图最多做 3 任务
                                    #   (base 90 → 任务分 125)，永远到不了 180。改为动态评估每个任务（读协议模板属性），
                                    #   不再按模板 ID 硬编码跳过；T04(清障)/T06(消耗马) 在预算内一律可做。
TASK_DETOUR_SAFETY_MARGIN = 15      # 任务绕路专用更紧安全余量：单任务 +30 分 > ~3 帧用时分的潜在损失，
                                    #   故绕路做任务用 15 帧余量（其余场景仍用通用 25 帧保守余量保交付）。
RESOURCE_CLAIM_ROUND = 2            # 资源领取读条帧数估算（用于时间预算）
# 注：不再硬编码 SKIP_TASK_TEMPLATES。任务是否可做由协议动态判定（processType/requiredResourceTypes/
#   requiredFreshness/score 来自 start.taskTemplates 与 inquire.tasks），地图变化时自动适配。

# ---- 策略调参（M5 对抗）----
KEEP_GOOD_FRUIT_MIN = 1             # 攻坚/清障投入好果后必须保留的最低好果（保证仍能交付，好果>0）
GATE_SCOUT_MIN_FRAMES = 8          # 派小分队探路宫门的最小剩余帧（太近来不及/无意义）
GATE_SCOUT_MAX_FRAMES = 40         # 最大剩余帧（探路标记 45 帧有效，避免过早派出而过期）

# ---- 策略调参（M7 能力补全）----
REJECT_BLOCK_ROUNDS = 4             # 被拒移动目标/节点忙临时拉黑帧数（拒绝反馈，防止重复撞同一阻塞）
WINDOW_ABSTAIN_ROUNDS = 6           # 窗口命中 WINDOW_DRAW_RETRY_LIMIT 后弃权帧数（覆盖一个 3 拍窗口周期 + 余量，
                                    #   防停在 DOCK 节点死磕 59 个窗口、105 次重试死循环）
INTEL_RANGE = 15                    # 情报射程上限（累计路线距离，任务书 §3.3.4）
TASK_DETOUR_MAX_EXTRA_FRAMES = 70   # 绕路做任务允许的最大额外帧（相对直达终点）
REROUTE_VS_CLEAR_EXTRA = 20         # 绕行比直路多这么多帧时改为就地清障（清障≈6帧+1好果）
REROUTE_VS_CLEAR_RUSH_EXTRA = 8     # RUSH 阶段同口径阈值（更小→更倾向就地突破保交付，避免终局绕路）
BREAK_GUARD_GOOD_FRAME_EQ = 6       # 攻坚破卡消耗 1 好果折算的帧成本（路由代价估算用）。
                                    #   §6.3.1：攻坚无额外处理帧，但耗好果（交付分机会成本≈1.8/果）。
                                    #   旧版 _enter_cost_fn 对可破敌卡返回 0 → 路由把破卡当免费，
                                    #   即便有便宜绕路也硬破浪费好果分。现折算帧成本让路由正确偏好便宜绕路。
SQUAD_AHEAD_MIN_HOPS = 2            # 小分队预清障/削弱要求阻塞位于路径第 N 跳之后（留延迟落地余量）

# ---- 策略调参（M7+ 进攻干扰：智能设卡 + 小分队增援）----
# 设计：设卡目标必须是当前节点(§6.2.1)，故进攻干扰=在对手必经咽喉点花4帧处理+好果种卡拖延对手。
# 交付优先仍为硬约束：仅在自身预算(时间/好果)充足且对手必经此点时才种卡；领先时回避(防送破关悬赏)。
OFFENSIVE_ENABLED = True            # 进攻设卡总开关（智能门控，默认开启）
OFFENSIVE_GOOD_FRUIT_KEEP = 30      # 设卡投入好果后必须保留的最低好果（保交付好果分：每果≈1.8分）
OFFENSIVE_EXTRA_GOOD = 1            # 关键关隘设卡额外投入好果（def = 2 + 2×extra；key_pass → 4）
OFFENSIVE_MIN_OPP_DELAY = 18        # 预期拖延对手帧数(forced_pass 时间税)下限，低于此不值得种卡。
                                    #   真机归因：S10 设卡对手未经过(1/7 反噬)，12→18 收紧门槛减少无效种卡。
RUSH_PREPOSITION_ROUND = 360        # 此帧后且未验核时，路由目标临时切为宫门：确保 RUSH(r390~450)触发时
                                    #   已在 S14 附近，避免 r450→r492 的 42 帧验核空隙（真机慢局用时分损失根因）。
OFFENSIVE_LEAD_SKIP = True          # 本方总分领先时回避设卡：防给落后对手送破关悬赏(§6.3.3)
SQUAD_REINFORCE_ENABLED = True      # 种卡后用小分队增援(+2防守,不耗好果)，加大对手破卡/强制通行成本
SET_GUARD_PROCESS_FRAMES = 4        # 设卡处理帧数(§6.2.1)，用于交付时间预算守卫

# ---- 策略调参（鲜度路由与预算）----
FRESHNESS_ROUTE_LAMBDA = 5.0        # 路由鲜度权重：边权额外 += λ×帧数×(路线鲜度损耗−水路损耗)，
                                    #   使帧数相近时偏好水路/官道而非山路/支路（§3.2.2）。差分式不抬高水路本身。
FRESHNESS_DETOUR_FLOOR = 65.0       # 绕路做任务的鲜度地板：预计鲜度跌破此值则放弃该绕路
FRESHNESS_LOSS_ASSUME = 0.06        # 鲜度预算估算用的每帧损耗（偏保守，按支路量级）

# ---- 策略调参（窗口反应式出牌）----
WINDOW_HIGH_STAKES = ("GATE", "PASS")   # 高筹码窗口：值得花护卫点/好果
WINDOW_MID_STAKES = ("TASK", "OBSTACLE")  # 中筹码窗口：鲜度>=80 花好果(献功)，鲜度<80 解禁 BING(受 reserve 约束)
XIAN_GONG_MIN_GOOD = 2              # 献功(XIAN_GONG)需保留的最低好果：献功耗 1 好果，留余交付分
WINDOW_BING_RESERVE = 1             # 中筹码窗口花 BING 时为潜在 GATE/PASS 窗口保留的护卫点(4 点不恢复)
WINDOW_BING_LOW_STAKES_RESERVE = 2  # 低筹码(RESOURCE/DOCK)花 BING 时保留的护卫点。红方不领过所/官凭、
                                    #   马只领 1 匹，stakes1 下 BING/XIAN 被关、YAN 无过所、QIANG 输 YAN/BING →
                                    #   旧逻辑只能 ABSTAIN 必输。现 guard 充足(g > 此值)时解禁 BING：BING 胜 YAN/QIANG、
                                    #   平 BING、仅负 XIAN，是低筹码下唯一能赢/平的牌。保留 2 点给中/高筹码窗口
                                    #   (stakes2 需 g>1、stakes3 需 g>=1)，故低筹码仅在 g>=3 时花，最多花 2 次(4→3→2)。
WINDOW_MIXED_LEAD = False           # R1 领出是否混合化（反剥削 lever，默认关以保单测确定性）。
                                    #   确定性领出(BING>XIAN>QIANG>YAN)在鲜度≥80 时易被反应式对手针对（恒领 BING → 对手领
                                    #   XIAN 稳吃）。开启后按权重在可用强牌间混合（BING 0.5/XIAN 0.25/QIANG 0.15/YAN 0.10），
                                    #   种子由 contestId+roundIndex+round+playerId 哈希得确定性 roll，可测可复现。
                                    #   平台对手若会反应式预判我方克制，应开启；纯静态对手保持关闭即可。

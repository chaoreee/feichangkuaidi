"""集中配置：参数、超时、开关。

禁止写死 playerId / host / port / 阵营（由启动参数与 start 动态决定）。
所有时间单位为秒（除非显式标注）。
"""

# ---- 客户端标识 ----
# 人工版本标签：每轮迭代手动 bump（iter25/iter26/...）。这是"log 记录哪版代码"的主标签——
# 解决真实 trace 不记录代码版本、旧/新 client 行为无法区分的问题（p0_attribution 工作流）。
CLIENT_VERSION = "iter29"
DEFAULT_PLAYER_NAME = "litchi-agent"


def code_version():
    """运行期代码版本 = CLIENT_VERSION + git 短 hash（自动补全，防忘 bump）。

    git 不可用时（如平台 ZIP 运行无仓库）回落为纯 CLIENT_VERSION。仅 Startup 调用一次，
    不在 import 期执行（不影响单测）。供 Startup trace 记录，使每局 trace 可溯源到代码版本。
    """
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        if out:
            return f"{CLIENT_VERSION}+{out}"
    except Exception:
        pass
    return CLIENT_VERSION

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
ICE_BOX_USE_BELOW = 78.0            # 鲜度低于此且持有冰鉴时使用（护住 70/80 阈值与鲜度分）
CLAIM_ICE_BOX_KEEP = 1              # 期望至少持有的冰鉴数（低于则在有货节点领取）
HORSE_MIN_REMAINING_DISTANCE = 30   # 剩余到终点路线距离大于此，才值得领取/使用马
RUSH_PROTECT_FRESHNESS_BELOW = 90.0  # RUSH 阶段鲜度低于此用护果令保鲜
DELIVER_TIME_SAFETY_MARGIN = 25     # 交付时间安全余量(帧)：估算做额外读条后仍能按时交付
TASK_SEEK_TARGET = 90               # 绕路做任务的上限：任务分达 90 即不再为任务绕路（90 已解锁满额送达/用时+里程碑）
RESOURCE_CLAIM_ROUND = 2            # 资源领取读条帧数估算（用于时间预算）
SKIP_TASK_TEMPLATES = ("T04", "T06")  # 机会式跳过：T04 需障碍上下文(仅突破时按清障任务处理)，T06 需消耗马

# ---- 策略调参（M5 对抗）----
KEEP_GOOD_FRUIT_MIN = 1             # 攻坚/清障投入好果后必须保留的最低好果（保证仍能交付，好果>0）
GATE_SCOUT_MIN_FRAMES = 8          # 派小分队探路宫门的最小剩余帧（太近来不及/无意义）
GATE_SCOUT_MAX_FRAMES = 40         # 最大剩余帧（探路标记 45 帧有效，避免过早派出而过期）

# ---- 策略调参（M7 能力补全）----
REJECT_BLOCK_ROUNDS = 4             # 被拒移动目标临时拉黑帧数（拒绝反馈，防止重复撞同一阻塞）
REJECT_TASK_COOLDOWN_ROUNDS = 6     # CLAIM_TASK 被 OBJECT_BUSY 拒后该 taskId 冷却帧数（防重试风暴：真实 trace S10 连停 30+ 帧重发同任务）
INTEL_RANGE = 15                    # 情报射程上限（累计路线距离，任务书 §3.3.4）
TASK_DETOUR_MAX_EXTRA_FRAMES = 70   # 绕路做任务允许的最大额外帧（相对直达终点）
REROUTE_VS_CLEAR_EXTRA = 20         # 绕行比直路多这么多帧时改为就地清障（清障≈6帧+1好果）
SQUAD_AHEAD_MIN_HOPS = 2            # 小分队预清障/削弱要求阻塞位于路径第 N 跳之后（留延迟落地余量）
ENABLE_OFFENSIVE = False            # 主动设卡/增援等进攻干扰（默认关闭：delivery-first，占用己方交付时间）

# ---- 策略调参（M8 博弈投影层，docs/game_theory_projection_strategy.md §9）----
# Layer 1 投影总线 / 风险档位状态机
LEAD_SAFE = 40                      # 投影分差超过此值才考虑切档（保守/进取）；初值待真实 trace 校准
MODE_HYSTERESIS_FRAMES = 5          # 连续满足同向条件的帧数门槛，避免临界点抖动
PROJECTION_MIN_CONFIDENCE = 0.55    # 对手投影 confidence 低于此则回落 EVEN（前中段大概率如此，属预期）

# Layer 3.3 分数质量地板：增量动作的最低净收益门槛（ΔEV）
ACTION_MIN_NET_SCORE = 0            # EVEN 默认：净分为负不做
ACTION_MIN_NET_SCORE_CONSERVATIVE = 8   # 领先时要求更高确定收益才动
ACTION_MIN_NET_SCORE_AGGRESSIVE = 0     # 落后时放宽下限，但不得为负

# Layer 2 档位参数（EVEN 复用上方既有默认，保证不改变现状行为）
AGGRESSIVE_TASK_SEEK_TARGET = 110              # 进取档冲 110 里程碑
AGGRESSIVE_TASK_DETOUR_MAX_EXTRA_FRAMES = 90   # 从直觉 120 收敛（§5.1）；真实 trace 验证后再上调
CONSERVATIVE_TASK_SEEK_TARGET = 0              # 领先档不为任务绕路
CONSERVATIVE_TASK_DETOUR_MAX_EXTRA_FRAMES = 0

# Layer 2 §5.1 行4：RUSH_PROTECT 时机（护果令）。CONSERVATIVE/EVEN 沿用既有 90（鲜度<90即用），
# AGGRESSIVE 落后时更克制，仅鲜度危急才用护果令、把急策留给速度冲刺。
AGGRESSIVE_RUSH_PROTECT_FRESHNESS_BELOW = 75.0

# Layer 2/3 悬赏与终局 race（P2+ 启用；此处仅登记阈值）
ENDGAME_RACE_WINDOW = 20            # 终局交付 race 触发窗口（帧）
BOUNTY_MAX_EXTRA_FRAMES = 25        # 顺路悬赏允许的最大额外帧
BOUNTY_MIN_NET_SCORE = 15           # 悬赏动作的最低净收益门槛

# Layer 2 §5.4 窗口 EV：无代价牌(兵争/验牒/免费强行)恒出；只有"明显正收益"才为窗口烧好果(献贡)。
# 献贡消耗 1 好果(直接减交付好果分)，故按档位设好果下限；CONSERVATIVE 一律不烧(锁胜)。
WINDOW_XIANGONG_MIN_GOOD_EVEN = 50        # EVEN：好果多于此才愿献贡烧 1 篓
WINDOW_XIANGONG_MIN_GOOD_AGGRESSIVE = 12  # AGGRESSIVE：略高于交付好果硬下限，允许更积极
WINDOW_VALUABLE_CONTEST_TYPES = ("TASK", "GATE", "PASS", "DOCK")  # 值得为之烧好果的窗口类型

# §6.2 任务 race（P3，默认关，真实 trace 验证 ΔEV 为正后逐项打开）
ENABLE_TASK_RACE = False           # 追平：对手任务分逼近 90 而我方未达时，放宽任务绕路目标/上限
TASK_RACE_OPP_THRESHOLD = 80       # 对手任务分≥此视为"已达/即将达 90"，触发我方追平
TASK_DENY_ETA_MARGIN = 0           # Deny：我方到任务点帧数 ≤ 对手 ETA + margin 才抢（不跑空趟）

# §6.3 鲜度/资源 race（P3，默认关）
ENABLE_FRESHNESS_RACE = False      # 鲜度劣势时提前用冰鉴保阈值（不为省资源导致好果转坏）
FRESHNESS_RACE_GAP = 10.0          # 对手鲜度比我方高出此值 → 我方处于鲜度劣势
ICE_BOX_RACE_USE_BELOW = 88.0      # 鲜度劣势时提前用冰鉴的阈值（护 80 阈值），常态仍 ICE_BOX_USE_BELOW
RESOURCE_RACE_MAX_EXTRA_FRAMES = 20  # 抢冰鉴允许的最大额外帧（不显著偏离交付路线）
RESOURCE_RACE_ICEBOX_KEEP = 2        # 冰鉴 race：期望持有到此数才值得为抢它绕路/领取
RESOURCE_DENY_ETA_MARGIN = 0         # 我方到资源点帧数 ≤ 对手 ETA + margin 才抢

# §7 条件化 SET_GUARD（P4，默认关，ROI 最低最后做）。SET_GUARD 不给我方加分，
# 只在"锁胜且对手会真的撞上卡"的临界局用富余好果给对手施加破卡/强制通行代价。
GUARD_MIN_LEAD = 60                # 投影领先超过此才考虑锁胜设卡（远大于 LEAD_SAFE）
GUARD_MIN_CONFIDENCE = 0.7         # 对手路线预测置信下限
GUARD_SETUP_FRAMES = 5            # 设卡处理 4 帧 + 生效 1 帧
GUARD_SURVIVAL_WINDOW = 60         # 对手预计通过帧须在 (SETUP, 此值] 内（存活窗口对齐）
GUARD_KEEP_GOOD_FRUIT = 20         # 设卡投入好果后仍须保留的交付好果下限
GUARD_MIN_NET_VALUE = 4            # denial 对对手的期望分损失下限（低于则不值得设卡）

# Layer 3/4 子能力开关（默认关闭，真实 trace 验证为正后逐项打开）
ENABLE_TASK_DENY = False           # §6.2 Deny：抢占对手正奔赴的关键任务点，阻其里程碑
ENABLE_RESOURCE_DENY = False       # §6.3 资源 race：抢占对手争夺、库存有限的路线附近冰鉴
ENABLE_CONDITIONAL_GUARD = False   # §7：投影驱动的条件化主动设卡（锁胜局，denial 过 ΔEV）

# ---- Phase B 静态规划器（鲜度感知路线 + 冰鉴策略，docs/p0_attribution_batch2.md）----
# 真实 30 局 trace 证伪"任务"杠杆（task_base≥130 双封顶 delivery 240/task 180，多做任务零分）、
# 确证"鲜度"为真实杠杆（输局对手鲜度 90.6 vs 我 80.4 → +19 分；质量路线投影 +24）。
# 本组开关把"早交付 vs 保鲜度"静态权衡当作优化问题求解：
#  ① 冰鉴更积极（阈值 91 护 90 阈值带、防好果转坏；囤 3 篓支撑多次使用）—— +24 的主驱动；
#  ② 路线选投影终局分最高者（时间最优 vs 鲜度最优），鲜度损耗差足以抵消时间成本才改道。
# 默认关：作 variant 仿真 A/B 验证（N≥30 + 分段不回归）后才合入默认。开启后 baseline 行为改变。
ENABLE_STATIC_PLANNER = False
STATIC_PLANNER_ICE_USE_BELOW = 91.0   # 冰鉴使用阈值（fresh<91 即用：在跌破 90 阈值带前补鲜度，防好果转坏）
STATIC_PLANNER_ICE_KEEP = 3            # 期望持有冰鉴数（支撑质量路线多次使用；baseline CLAIM_ICE_BOX_KEEP=1）
STATIC_PLANNER_MIN_ROUTE_GAIN = 0.5    # 候选路线投影分须高出时间最优此值才改道（避免噪声微改道；ΔEV 门）
STATIC_PLANNER_MIN_ROUTE_EFFICIENCY = 0.2  # 改道候选每帧效率下限 gain/extra_frames，仅对长绕路(extra≥15帧)生效。≈v2 乐观修正率（实际−3.7 vs 投影+7 / 60帧≈0.18/帧）：拒0.12低效长绕路、纳0.26任务长绕路。sim A/B 校准

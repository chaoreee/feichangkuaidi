# Aggregated Report — cumulative N=21 games
source=platform variant=baseline
SAMPLE NOTE: N=21 < 30，整体结论标'假设级'（§3.7）

## 总体
WIN_RATE:       0.43 (9/21)
DELIVERY_RATE:  0.90 (19/21)
MEAN_SCORE:     689.4 (n_with_real_score=21)
DELIVERY_FRAME: frame: n=19, min=444, median=444, mean=447.1, max=459
TASK_BASE:      task_base: n=21, min=60, median=150, mean=140.0, max=150
TASK_90_REACH:  0.90
PROJ_ERROR:     proj_err: n=21, min=-17, median=-4, mean=-4.1, max=0
MODE_SWITCHES:  34 total (1.62/game)

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=217.1, task=168.6, time=15.9, goodFruit=157.4, freshness=130.4, bounty=0.0

## 对手分项与设卡（P1-A）
  OPP_SCORE_COMP (n=11): delivery=230.9, task=156.8, time=10.0, goodFruit=174.5, freshness=141.8, bounty=0.0
  OPP_GUARD: episodes=2, games_with_guard=2/21, blocked_me_frames=224
  OPP_ICE_USED: 4 total (0.19/game)
  OPP_FRESHNESS: min mean=78.5 (n=21), end mean=80.1 (n=21)

## 失败模式频次
  rejected=469, waitingStuck=3, invalidActions=0, decisionTimeouts=0, canAffordBlocked=18
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=11, expected_tie=1, expected_win=9
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=19): W 0.47, mean 756, stuck 2
  undelivered        (N=2): W 0.00, mean 60, stuck 1
  task90_reached     (N=19): W 0.47, mean 756, stuck 2
  task90_missed      (N=2): W 0.00, mean 60, stuck 1
  mid_lead           (N=14): W 0.50, mean 656, stuck 3
  mid_trail          (N=2): W 0.00, mean 758, stuck 0
  mid_even           (N=5): W 0.40, mean 755, stuck 0
  weather_hit        (N=21): W 0.43, mean 689, stuck 3
  contested          (N=5): W 1.00, mean 754, stuck 2
  opp_delivered      (N=21): W 0.43, mean 689, stuck 3

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=21, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260704_155006_495_2809_vs_2696_cb80fa89 outcome=WIN → waitingStuck=1
  - matchId=match_20260704_160352_074_2696_vs_2735_e22a15cc outcome=UNDELIVERED → UNDELIVERED
  - matchId=match_20260704_184705_225_2809_vs_2696_59c1b732 outcome=WIN → waitingStuck=1
  - matchId=match_20260704_184842_528_2696_vs_2735_91bbc27f outcome=UNDELIVERED → UNDELIVERED; waitingStuck=1

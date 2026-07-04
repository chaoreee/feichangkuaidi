# Aggregated Report — cumulative N=10 games
source=platform variant=baseline
SAMPLE NOTE: N=10 < 30，整体结论标'假设级'（§3.7）

## 总体
WIN_RATE:       0.40 (4/10)
DELIVERY_RATE:  0.90 (9/10)
MEAN_SCORE:     685.9 (n_with_real_score=10)
DELIVERY_FRAME: frame: n=9, min=444, median=444, mean=446.9, max=459
TASK_BASE:      task_base: n=10, min=60, median=150, mean=139.5, max=150
TASK_90_REACH:  0.90
PROJ_ERROR:     proj_err: n=10, min=-13, median=-4, mean=-3.5, max=0
MODE_SWITCHES:  10 total (1.00/game)

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=216.0, task=168.0, time=15.8, goodFruit=156.6, freshness=129.5, bounty=0.0

## 失败模式频次
  rejected=233, waitingStuck=1, invalidActions=0, decisionTimeouts=0, canAffordBlocked=14
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=6, expected_win=4
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=9): W 0.44, mean 755, stuck 1
  undelivered        (N=1): W 0.00, mean 60, stuck 0
  task90_reached     (N=9): W 0.44, mean 755, stuck 1
  task90_missed      (N=1): W 0.00, mean 60, stuck 0
  mid_lead           (N=6): W 0.50, mean 639, stuck 1
  mid_trail          (N=1): W 0.00, mean 758, stuck 0
  mid_even           (N=3): W 0.33, mean 755, stuck 0
  weather_hit        (N=10): W 0.40, mean 686, stuck 1
  contested          (N=2): W 1.00, mean 754, stuck 1
  opp_delivered      (N=10): W 0.40, mean 686, stuck 1

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=10, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260704_155006_495_2809_vs_2696_cb80fa89 outcome=WIN → waitingStuck=1
  - matchId=match_20260704_160352_074_2696_vs_2735_e22a15cc outcome=UNDELIVERED → UNDELIVERED

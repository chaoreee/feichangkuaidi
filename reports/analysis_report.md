# Aggregated Report — cumulative N=19 games
source=platform variant=baseline
SAMPLE NOTE: N=19 < 30，整体结论标'假设级'（§3.7）

## 总体
WIN_RATE:       0.53 (10/19)
DELIVERY_RATE:  1.00 (19/19)
MEAN_SCORE:     755.7 (n_with_real_score=19)
DELIVERY_FRAME: frame: n=19, min=444, median=444, mean=446.6, max=459
TASK_BASE:      task_base: n=19, min=135, median=150, mean=149.2, max=150
TASK_90_REACH:  1.00
PROJ_ERROR:     proj_err: n=19, min=-13, median=-4, mean=-4.1, max=0
MODE_SWITCHES:  22 total (1.16/game)

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=240.0, task=180.0, time=17.5, goodFruit=174.0, freshness=144.2, bounty=0.0

## 失败模式频次
  rejected=17, waitingStuck=2, invalidActions=0, decisionTimeouts=0, canAffordBlocked=0
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=9, expected_win=10
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=19): W 0.53, mean 756, stuck 2
  task90_reached     (N=19): W 0.53, mean 756, stuck 2
  mid_lead           (N=12): W 0.67, mean 756, stuck 1
  mid_trail          (N=3): W 0.00, mean 757, stuck 0
  mid_even           (N=4): W 0.50, mean 755, stuck 1
  weather_hit        (N=19): W 0.53, mean 756, stuck 2
  contested          (N=3): W 1.00, mean 753, stuck 2
  opp_delivered      (N=19): W 0.53, mean 756, stuck 2

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=19, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260704_132011_237_2696_vs_2809_6d6a1ed5 outcome=WIN → waitingStuck=1
  - matchId=match_20260704_132951_558_2625_vs_2696_4dc35f68 outcome=WIN → waitingStuck=1

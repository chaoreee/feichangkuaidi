# Aggregated Report — cumulative N=11 games
source=platform variant=baseline
SAMPLE NOTE: N=11 < 30，整体结论标'假设级'（§3.7）

## 总体
WIN_RATE:       0.73 (8/11)
DELIVERY_RATE:  1.00 (11/11)
MEAN_SCORE:     753.3 (n_with_real_score=11)
DELIVERY_FRAME: frame: n=11, min=444, median=444, mean=456.2, max=492
TASK_BASE:      task_base: n=11, min=120, median=150, mean=144.5, max=150
TASK_90_REACH:  1.00
PROJ_ERROR:     proj_err: n=11, min=-18, median=-3, mean=-4.2, max=0
MODE_SWITCHES:  20 total (1.82/game)

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=240.0, task=179.1, time=16.5, goodFruit=173.5, freshness=144.2, bounty=0.0

## 失败模式频次
  rejected=48, waitingStuck=13, invalidActions=0, decisionTimeouts=0, canAffordBlocked=0
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=3, expected_win=8
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=11): W 0.73, mean 753, stuck 13
  task90_reached     (N=11): W 0.73, mean 753, stuck 13
  mid_lead           (N=6): W 0.67, mean 756, stuck 1
  mid_trail          (N=5): W 0.80, mean 750, stuck 12
  weather_hit        (N=11): W 0.73, mean 753, stuck 13
  contested          (N=4): W 1.00, mean 747, stuck 13
  opp_delivered      (N=10): W 0.70, mean 753, stuck 13
  opp_undelivered    (N=1): W 1.00, mean 758, stuck 0

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=11, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260704_112001_376_2696_vs_2809_367c9bfc outcome=WIN → waitingStuck=1
  - matchId=match_20260704_112708_791_2696_vs_2814_dc576a6c outcome=WIN → waitingStuck=5
  - matchId=match_20260704_113753_998_2696_vs_2931_df0282a6 outcome=WIN → waitingStuck=2
  - matchId=match_20260704_113812_983_2696_vs_2706_b041031a outcome=WIN → waitingStuck=5

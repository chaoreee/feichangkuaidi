# Aggregated Report — cumulative N=207 games
source=platform,sim variant=baseline

## 总体
WIN_RATE:       0.29 (60/207)
DELIVERY_RATE:  0.96 (198/207)
MEAN_SCORE:     708.5 (n_with_real_score=207)
DELIVERY_FRAME: frame: n=198, min=411, median=413, mean=422.1, max=549
TASK_BASE:      task_base: n=207, min=60, median=140, mean=127.9, max=150
TASK_90_REACH:  0.96
PROJ_ERROR:     proj_err: n=207, min=-22, median=0, mean=-1.7, max=1
MODE_SWITCHES:  221 total (1.07/game)

## 对手类分桶（Iter 32 群体归因，假设级）
> 按对手类分桶（guard-type/quality-route/speed-route/unknown）。N<30 标假设级，Iter 33+ 真实数据回流后校准阈值。

  guard-type    (N=19): W 0.58, me 459 / opp 521, fresh me=77.1 opp=74.9 (gap -2.2), good me=96.8 opp=93.5 (gap -3.3), meDeliverF=431
  quality-route (N=57): W 0.28, me 756 / opp 761, fresh me=81.6 opp=91.3 (gap +9.6), good me=97.4 opp=98.2 (gap +0.7), meDeliverF=413
  speed-route   (N=131): W 0.25, me 724 / opp 716, fresh me=75.1 opp=80.5 (gap +5.4), good me=97.6 opp=97.5 (gap -0.0), meDeliverF=425
  → 归因：对 speed-route 胜率最低（0.25, N=131），对 guard-type 胜率最高（0.58, N=19）；定位追分点看分项 gap。

## 运行期对手类对账（Iter 37 §1，纯观测）
  runtime vs offline: agree=0 disagree=0 no_runtime=207
  → 运行期与离线一致，分类器可信赖，§2 策略切换可接

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=229.2, task=159.9, time=19.4, goodFruit=167.4, freshness=132.7, bounty=0.0

## 对手分项与设卡（P1-A）
  OPP_SCORE_COMP (n=207): delivery=227.1, task=148.0, time=17.5, goodFruit=169.8, freshness=145.1, bounty=0.0
  OPP_GUARD: episodes=29, games_with_guard=19/207, blocked_me_frames=840
  OPP_ICE_USED: 21 total (0.10/game)
  OPP_FRESHNESS: min mean=80.8 (n=206), end mean=82.9 (n=207)

## 失败模式频次
  rejected=1914, waitingStuck=117, invalidActions=0, decisionTimeouts=0, canAffordBlocked=5

## 运气分类（luck class，§3.8）
  expected_loss=144, expected_tie=3, expected_win=60
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=198): W 0.30, mean 738, stuck 106
  undelivered        (N=9): W 0.00, mean 67, stuck 11
  task90_reached     (N=199): W 0.30, mean 729, stuck 110
  task90_missed      (N=8): W 0.12, mean 193, stuck 7
  mid_lead           (N=77): W 0.69, mean 723, stuck 85
  mid_trail          (N=13): W 0.23, mean 481, stuck 12
  mid_even           (N=117): W 0.03, mean 725, stuck 20
  weather_hit        (N=207): W 0.29, mean 708, stuck 117
  contested          (N=16): W 0.69, mean 697, stuck 25
  opp_delivered      (N=201): W 0.27, mean 710, stuck 110
  opp_undelivered    (N=6): W 0.83, mean 642, stuck 7

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=207, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260705_115236_626_2809_vs_2696_6f456dbc outcome=WIN → waitingStuck=2
  - matchId=match_20260705_115244_762_2614_vs_2696_5d45d016 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_115255_579_2735_vs_2696_018cbe1d outcome=UNDELIVERED → UNDELIVERED; waitingStuck=1
  - matchId=match_20260705_120719_717_2696_vs_2627_c1e6f4f0 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_121237_429_2696_vs_2613_8c0e643d outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_121242_597_2696_vs_2814_b2f5824f outcome=WIN → waitingStuck=1
  - matchId=match_20260705_121256_306_2617_vs_2696_35e40a89 outcome=UNDELIVERED → UNDELIVERED; waitingStuck=2
  - matchId=match_20260705_121300_703_2696_vs_2744_8181d4f0 outcome=UNDELIVERED → UNDELIVERED; waitingStuck=1
  - matchId=match_20260705_121610_810_2696_vs_2629_33adfc67 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_122119_336_2696_vs_2652_e37a8f3a outcome=WIN → waitingStuck=1
  - matchId=match_20260705_122358_216_2696_vs_2814_f36f991d outcome=WIN → waitingStuck=3
  - matchId=match_20260705_122854_290_2931_vs_2696_70c2fdd7 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_122900_607_2696_vs_2905_0dc68f65 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_122907_066_2839_vs_2696_f1073072 outcome=LOSS → waitingStuck=2
  - matchId=match_20260705_122913_690_2696_vs_2619_74e40771 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_124048_076_2696_vs_2771_d894d700 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_124222_249_2696_vs_2823_dc352fd5 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_124234_734_2696_vs_2632_f64d514e outcome=WIN → waitingStuck=2
  - matchId=match_20260705_124241_012_2643_vs_2696_a7117f96 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_124253_811_2696_vs_2738_bfe98516 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_124816_862_2769_vs_2696_ccaad049 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_125411_762_2696_vs_2769_2f7bd7d6 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_125417_838_2696_vs_2616_91466b54 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_125422_115_2618_vs_2696_eda5fbca outcome=WIN → waitingStuck=1
  - matchId=match_20260705_125435_433_2696_vs_2767_658c97c6 outcome=LOSS → waitingStuck=1; loss+task<90(base=60)
  - matchId=match_20260705_130756_854_2696_vs_2743_71b3cd25 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_130815_955_2696_vs_2720_074b3550 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_130830_463_2612_vs_2696_25fb130c outcome=WIN → waitingStuck=1
  - matchId=match_20260705_130834_505_2696_vs_2884_e90d3ec9 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_131616_423_2643_vs_2696_f02162ba outcome=LOSS → waitingStuck=1

# Aggregated Report — cumulative N=40 games
source=platform variant=baseline

## 总体
WIN_RATE:       0.42 (17/40)
DELIVERY_RATE:  0.85 (34/40)
MEAN_SCORE:     648.6 (n_with_real_score=40)
DELIVERY_FRAME: frame: n=34, min=411, median=412, mean=417.8, max=549
TASK_BASE:      task_base: n=40, min=60, median=150, mean=132.0, max=150
TASK_90_REACH:  0.85
PROJ_ERROR:     proj_err: n=40, min=-22, median=0, mean=-2.6, max=0
MODE_SWITCHES:  76 total (1.90/game)

## 对手类分桶（Iter 32 群体归因，假设级）
> 按对手类分桶（guard-type/quality-route/speed-route/unknown）。N<30 标假设级，Iter 33+ 真实数据回流后校准阈值。

  guard-type    (N=11): W 0.45, me 367 / opp 495, fresh me=76.5 opp=74.0 (gap -2.5), good me=97.0 opp=92.5 (gap -4.5), meDeliverF=439
  quality-route (N=19): W 0.16, me 766 / opp 773, fresh me=82.8 opp=90.9 (gap +8.1), good me=98.0 opp=98.1 (gap +0.1), meDeliverF=414
  speed-route   (N=10): W 0.90, me 735 / opp 606, fresh me=81.4 opp=75.9 (gap -5.5), good me=97.6 opp=97.4 (gap -0.2), meDeliverF=415
  → 归因：对 quality-route 胜率最低（0.16, N=19），对 speed-route 胜率最高（0.90, N=10）；定位追分点看分项 gap。

## 运行期对手类对账（Iter 37 §1，纯观测）
  runtime vs offline: agree=0 disagree=0 no_runtime=40
  → 运行期与离线一致，分类器可信赖，§2 策略切换可接

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=202.0, task=154.5, time=17.6, goodFruit=149.3, freshness=125.3, bounty=0.0

## 对手分项与设卡（P1-A）
  OPP_SCORE_COMP (n=40): delivery=207.0, task=136.6, time=14.4, goodFruit=160.2, freshness=138.2, bounty=0.0
  OPP_GUARD: episodes=20, games_with_guard=11/40, blocked_me_frames=1248
  OPP_ICE_USED: 8 total (0.20/game)
  OPP_FRESHNESS: min mean=80.0 (n=40), end mean=82.5 (n=40)

## 失败模式频次
  rejected=1806, waitingStuck=48, invalidActions=0, decisionTimeouts=0, canAffordBlocked=0
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=23, expected_win=17
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=34): W 0.50, mean 751, stuck 40
  undelivered        (N=6): W 0.00, mean 67, stuck 8
  task90_reached     (N=34): W 0.47, mean 721, stuck 42
  task90_missed      (N=6): W 0.17, mean 237, stuck 6
  mid_lead           (N=29): W 0.55, mean 683, stuck 35
  mid_trail          (N=5): W 0.20, mean 310, stuck 5
  mid_even           (N=6): W 0.00, mean 765, stuck 8
  weather_hit        (N=40): W 0.42, mean 649, stuck 48
  contested          (N=9): W 0.56, mean 654, stuck 16
  opp_delivered      (N=37): W 0.41, mean 658, stuck 44
  opp_undelivered    (N=3): W 0.67, mean 538, stuck 4

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=40, mismatch=0, stub/missing=0

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

# Aggregated Report — cumulative N=67 games
source=platform variant=baseline

## 总体
WIN_RATE:       0.64 (43/67)
DELIVERY_RATE:  0.96 (64/67)
MEAN_SCORE:     729.3 (n_with_real_score=67)
DELIVERY_FRAME: frame: n=64, min=411, median=413, mean=414.2, max=491
TASK_BASE:      task_base: n=67, min=60, median=150, mean=142.8, max=150
TASK_90_REACH:  0.97
PROJ_ERROR:     proj_err: n=67, min=-22, median=0, mean=-3.4, max=0
MODE_SWITCHES:  125 total (1.87/game)

## 对手类分桶（Iter 32 群体归因，假设级）
> 按对手类分桶（guard-type/quality-route/speed-route/unknown）。N<30 标假设级，Iter 33+ 真实数据回流后校准阈值。

  guard-type    (N=9): W 0.67, me 528 / opp 540, fresh me=77.3 opp=75.4 (gap -1.9), good me=96.6 opp=94.7 (gap -1.9), meDeliverF=426
  quality-route (N=30): W 0.43, me 764 / opp 764, fresh me=82.6 opp=93.2 (gap +10.5), good me=97.0 opp=98.4 (gap +1.4), meDeliverF=413
  speed-route   (N=28): W 0.86, me 757 / opp 698, fresh me=82.8 opp=78.9 (gap -3.9), good me=97.0 opp=97.2 (gap +0.2), meDeliverF=414
  → 归因：对 quality-route 胜率最低（0.43, N=30），对 speed-route 胜率最高（0.86, N=28）；定位追分点看分项 gap。

## 分项分均值（me，rules.py 从原始输入重算）
  delivery=229.3, task=172.0, time=20.4, goodFruit=166.2, freshness=141.4, bounty=0.0

## 对手分项与设卡（P1-A）
  OPP_SCORE_COMP (n=67): delivery=219.7, task=146.1, time=16.9, goodFruit=167.1, freshness=146.5, bounty=0.0
  OPP_GUARD: episodes=11, games_with_guard=9/67, blocked_me_frames=0
  OPP_ICE_USED: 13 total (0.19/game)
  OPP_FRESHNESS: min mean=82.1 (n=67), end mean=84.8 (n=67)

## 失败模式频次
  rejected=1102, waitingStuck=69, invalidActions=0, decisionTimeouts=0, canAffordBlocked=7
  (N<100，罕见事件频率仅作假设，§3.7)

## 运气分类（luck class，§3.8）
  expected_loss=23, expected_tie=1, expected_win=43
  → unlucky_loss 为修 bug 首选；lucky_win 勿当实力强化

## 场景分段（防单点劣化的主防线，§3.7）
  delivered          (N=64): W 0.67, mean 760, stuck 66
  undelivered        (N=3): W 0.00, mean 67, stuck 3
  task90_reached     (N=65): W 0.66, mean 750, stuck 68
  task90_missed      (N=2): W 0.00, mean 60, stuck 1
  mid_lead           (N=48): W 0.77, mean 746, stuck 50
  mid_trail          (N=8): W 0.25, mean 588, stuck 7
  mid_even           (N=11): W 0.36, mean 758, stuck 12
  weather_hit        (N=67): W 0.64, mean 729, stuck 69
  contested          (N=7): W 0.86, mean 752, stuck 9
  opp_delivered      (N=64): W 0.62, mean 728, stuck 66
  opp_undelivered    (N=3): W 1.00, mean 747, stuck 3

## 对账自检（rules.py 重算 vs 报告 total，§3.6）
  ok=67, mismatch=0, stub/missing=0

## 异常局标记（仅假设来源，须全语料验证后才动手，§3.3/§3.8）
  - matchId=match_20260705_031517_015_2696_vs_2986_43603109 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_031529_282_2696_vs_2809_02155fe3 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_031541_933_2905_vs_2696_03cfcc34 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_031550_422_2696_vs_2614_c2d42d20 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_031942_192_2696_vs_2735_9653307c outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_031947_982_2696_vs_2814_d75a96f7 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032002_726_2696_vs_2613_eee58165 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_032245_069_2696_vs_2743_a9cad475 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032303_894_2931_vs_2696_51909d49 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032317_062_2619_vs_2696_858c850a outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_032322_930_2696_vs_2839_666cbdc6 outcome=LOSS → waitingStuck=2
  - matchId=match_20260705_032341_729_2696_vs_2744_c2e99980 outcome=UNDELIVERED → UNDELIVERED
  - matchId=match_20260705_032607_121_2696_vs_2632_7815f95e outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032613_428_2696_vs_2643_929c3501 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_032619_799_2738_vs_2696_aeb3b7a3 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_032629_625_2696_vs_2626_33d4652e outcome=TIE → waitingStuck=1
  - matchId=match_20260705_032839_487_2769_vs_2696_4d342ec0 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032936_382_2769_vs_2696_7d05a069 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_032950_334_2696_vs_2616_6befd7c6 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_033007_128_2618_vs_2696_feec0db4 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033026_049_2696_vs_2884_d028e61d outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033356_439_2612_vs_2696_79f8a1a2 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033400_595_2823_vs_2696_23a64b9d outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_033413_374_2696_vs_2743_7868eac0 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033832_456_2696_vs_2837_3694b507 outcome=LOSS → waitingStuck=1
  - matchId=match_20260705_033845_004_2751_vs_2696_6a358ff8 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033851_868_2696_vs_2625_82269158 outcome=WIN → waitingStuck=1
  - matchId=match_20260705_033857_744_2696_vs_2718_f193ac8c outcome=WIN → waitingStuck=1
  - matchId=match_20260705_034141_786_2814_vs_2696_c8a3e26c outcome=WIN → waitingStuck=1
  - matchId=match_20260705_034221_932_2611_vs_2696_f7c154b7 outcome=WIN → waitingStuck=1

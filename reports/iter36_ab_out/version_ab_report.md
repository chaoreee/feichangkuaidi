# A/B by ClientVersion (unpaired, §3 real) — iter31(old) vs iter36(new)

SAMPLE NOTE: N_old=67 / N_new=40 达 A/B 门槛

> 真实对战**非配对**：老/新 client 各对随机对手池打，两独立样本。对手池/运气分布偏移时见下方 CONFOUND 守卫，DELTA 不可全归因于 client 改动。

## 各版本概览
iter31 (N=67): W 0.64, deliver 0.96, mean 729 [694.6, 764.0], fresh 82.0, good 96.9, frame 414, task90 0.97, stuck 69, undelivered 3
iter36 (N=40): W 0.42, deliver 0.85, mean 649 [570.9, 726.4], fresh 80.7, good 97.6, frame 418, task90 0.85, stuck 48, undelivered 6

## DELTA (new − old)
  MEAN_SCORE   -80.7  95% CI [-165.8, 4.5]
  WIN_RATE     -0.22  95% CI [-0.4, -0.0]
  DELIVERY     -0.11
  FRESHNESS    -1.2
  GOODFRUIT    +0.7
  FRAME        +4
  STUCK        -21
  UNDELIVERED  +3

## SEGMENT REGRESSION（任一回归即不合入，§3.8）
  delivered          old 760 / new 751 (-9)  ⚠ 成功路径劣化
  task90_reached     old 750 / new 721 (-29)  ⚠ 成功路径劣化
  mid_lead           old 746 / new 683 (-63)  ⚠ 成功路径劣化
  mid_trail          old 588 / new 310 (-278)  ⚠ 成功路径劣化
  weather_hit        old 729 / new 649 (-81)  ⚠ 成功路径劣化
  contested          old 752 / new 654 (-98)  ⚠ 成功路径劣化
  opp_delivered      old 728 / new 658 (-71)  ⚠ 成功路径劣化
  opp_undelivered    old 747 / new 538 (-208)  ⚠ 成功路径劣化

## CONFOUND 守卫（分布偏移则归因谨慎）
  OPP_CLASS  old: guard-type=8, quality-route=30, speed-route=29
             new: guard-type=11, quality-route=19, speed-route=10
  LUCK       old: expected_loss=23, expected_tie=1, expected_win=43
             new: expected_loss=23, expected_win=17

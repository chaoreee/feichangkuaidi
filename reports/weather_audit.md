# Iter 36 §1.5 真实天气审计 — 大路 +20 在真实天气下是否缩水

> 从 67 局 compact.log 重构逐帧天气序列（HOT 1.5× / HEAVY_RAIN 1.3× 鲜度系数；
> MOUNTAIN_FOG+MOUNTAIN / HEAVY_RAIN+WATER 移动减速），重跑马感知 walker。
> 对比 §1 的 coef=1.0 上界（大路净 +20）。**纯观测，不合入策略改动。**

## 聚合（N=67）

- CLEAR 上界 Δ（无天气）：**+20.0**
- 真实天气 Δ 均值：**+20.70**（std 0.73，min +20.00 / max +22.00）
- 缩水均值：**+0.70**（负=天气缩水杠杆）
- 鲜度 Δ 均值：+12.118
- 大路净正局：67/67；大路 ≤ 山路局：0
- 判定：**稳住：真实天气下大路仍净正，且无单局反劣（+20 不缩水或缩水可忽略）**

## 逐局

Δreal=真实天气大路−山路；clear=无天气上界；shrink=Δreal−clear（负=缩水）；
extra_w=大路额外 ~30 帧落到的天气；phases=该局天气分段。

  match_20260705_031517_015_2696_vs_2986_43603 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.8 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-83 HOT@r84-234 HEAVY_RAIN@r235-344 MOUNTAIN_FOG@r345-374
  match_20260705_031529_282_2696_vs_2809_02155 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-109 HOT@r110-219 HEAVY_RAIN@r220-329 HOT@r330-374
  match_20260705_031541_933_2905_vs_2696_03cfc Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.0 good=+1 extra_w=MOUNTAIN_FOG/HOT | CLEAR@r1-92 HOT@r93-202 MOUNTAIN_FOG@r203-353 HOT@r354-374
  match_20260705_031550_422_2696_vs_2614_c2d42 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.2 good=+1 extra_w=MOUNTAIN_FOG/HOT | CLEAR@r1-88 HOT@r89-239 MOUNTAIN_FOG@r240-349 HOT@r350-374
  match_20260705_031942_192_2696_vs_2735_96533 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-90 HOT@r91-200 HEAVY_RAIN@r201-351 HOT@r352-374
  match_20260705_031947_982_2696_vs_2814_d75a9 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.3 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-113 HEAVY_RAIN@r114-223 HOT@r224-333 MOUNTAIN_FOG@r334-374
  match_20260705_032002_726_2696_vs_2613_eee58 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-98 HOT@r99-208 HEAVY_RAIN@r209-359 HOT@r360-374
  match_20260705_032245_069_2696_vs_2743_a9cad Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.7 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-99 HOT@r100-209 HEAVY_RAIN@r210-319 MOUNTAIN_FOG@r320-374
  match_20260705_032303_894_2931_vs_2696_51909 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+11.9 good=+1 extra_w=HOT | CLEAR@r1-100 HOT@r101-210 HEAVY_RAIN@r211-320 HOT@r321-374
  match_20260705_032317_062_2619_vs_2696_858c8 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.1 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-85 HOT@r86-236 HEAVY_RAIN@r237-346 HOT@r347-374
  match_20260705_032322_930_2696_vs_2839_666cb Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-107 HOT@r108-217 HEAVY_RAIN@r218-327 MOUNTAIN_FOG@r328-374
  match_20260705_032341_729_2696_vs_2744_c2e99 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-105 HOT@r106-215 MOUNTAIN_FOG@r216-325 HEAVY_RAIN@r326-374
  match_20260705_032607_121_2696_vs_2632_7815f Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-115 HOT@r116-225 HEAVY_RAIN@r226-335 MOUNTAIN_FOG@r336-374
  match_20260705_032613_428_2696_vs_2643_929c3 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-98 HOT@r99-208 HEAVY_RAIN@r209-359 HOT@r360-374
  match_20260705_032619_799_2738_vs_2696_aeb3b Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-102 HOT@r103-212 MOUNTAIN_FOG@r213-322 HOT@r323-374
  match_20260705_032629_625_2696_vs_2626_33d46 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-116 HOT@r117-226 HEAVY_RAIN@r227-336 HOT@r337-374
  match_20260705_032839_487_2769_vs_2696_4d342 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.2 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-79 MOUNTAIN_FOG@r80-230 HOT@r231-340 HEAVY_RAIN@r341-374
  match_20260705_032936_382_2769_vs_2696_7d05a Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-118 HOT@r119-228 HEAVY_RAIN@r229-338 HOT@r339-374
  match_20260705_032950_334_2696_vs_2616_6befd Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-106 HOT@r107-216 HEAVY_RAIN@r217-326 HOT@r327-374
  match_20260705_033007_128_2618_vs_2696_feec0 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-104 HOT@r105-214 HEAVY_RAIN@r215-324 MOUNTAIN_FOG@r325-374
  match_20260705_033026_049_2696_vs_2884_d028e Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-96 HOT@r97-206 HEAVY_RAIN@r207-357 HOT@r358-374
  match_20260705_033356_439_2612_vs_2696_79f8a Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-103 HOT@r104-213 HEAVY_RAIN@r214-323 MOUNTAIN_FOG@r324-374
  match_20260705_033400_595_2823_vs_2696_23a64 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-90 HOT@r91-200 HEAVY_RAIN@r201-351 HOT@r352-374
  match_20260705_033413_374_2696_vs_2743_7868e Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-103 HOT@r104-213 MOUNTAIN_FOG@r214-323 HOT@r324-374
  match_20260705_033832_456_2696_vs_2837_3694b Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-113 HOT@r114-223 MOUNTAIN_FOG@r224-333 HOT@r334-374
  match_20260705_033845_004_2751_vs_2696_6a358 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-102 HOT@r103-212 HEAVY_RAIN@r213-322 HOT@r323-374
  match_20260705_033851_868_2696_vs_2625_82269 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.1 good=+1 extra_w=HOT/MOUNTAIN_FOG | CLEAR@r1-96 HEAVY_RAIN@r97-206 HOT@r207-357 MOUNTAIN_FOG@r358-374
  match_20260705_033857_744_2696_vs_2718_f193a Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.1 good=+1 extra_w=MOUNTAIN_FOG/HOT | CLEAR@r1-86 HOT@r87-237 MOUNTAIN_FOG@r238-347 HOT@r348-374
  match_20260705_034141_786_2814_vs_2696_c8a3e Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-113 HOT@r114-223 HEAVY_RAIN@r224-333 HOT@r334-374
  match_20260705_034221_932_2611_vs_2696_f7c15 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-116 HOT@r117-226 HEAVY_RAIN@r227-336 HOT@r337-374
  match_20260705_034226_105_2696_vs_2900_4b798 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.1 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-84 HOT@r85-235 HEAVY_RAIN@r236-345 HOT@r346-374
  match_20260705_034232_584_2696_vs_2943_72e48 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.8 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-85 HOT@r86-236 HEAVY_RAIN@r237-346 MOUNTAIN_FOG@r347-374
  match_20260705_034251_239_2639_vs_2696_0e0ad Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.7 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-87 HOT@r88-238 HEAVY_RAIN@r239-348 MOUNTAIN_FOG@r349-374
  match_20260705_034523_579_2982_vs_2696_e2754 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HOT | CLEAR@r1-80 HOT@r81-231 MOUNTAIN_FOG@r232-341 HOT@r342-374
  match_20260705_034541_877_2696_vs_2934_8b767 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-111 HOT@r112-221 HEAVY_RAIN@r222-331 HOT@r332-374
  match_20260705_034613_729_2696_vs_2720_d7a02 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-105 HOT@r106-215 HEAVY_RAIN@r216-325 HOT@r326-374
  match_20260705_034809_346_2696_vs_2707_8d330 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.4 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-109 HEAVY_RAIN@r110-219 HOT@r220-329 MOUNTAIN_FOG@r330-374
  match_20260705_034826_188_2757_vs_2696_3d508 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-117 HOT@r118-227 HEAVY_RAIN@r228-337 MOUNTAIN_FOG@r338-374
  match_20260705_034845_553_2696_vs_2622_fc56d Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.5 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-91 HOT@r92-201 HEAVY_RAIN@r202-352 MOUNTAIN_FOG@r353-374
  match_20260705_035148_333_2965_vs_2696_a461b Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-102 HOT@r103-212 MOUNTAIN_FOG@r213-322 HOT@r323-374
  match_20260705_035200_953_2696_vs_2693_0f10d Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.4 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-98 HOT@r99-208 HEAVY_RAIN@r209-359 MOUNTAIN_FOG@r360-374
  match_20260705_035208_096_2696_vs_2629_21f17 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-114 HOT@r115-224 HEAVY_RAIN@r225-334 HOT@r335-374
  match_20260705_035438_691_2729_vs_2696_0f0c7 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-109 HOT@r110-219 MOUNTAIN_FOG@r220-329 HEAVY_RAIN@r330-374
  match_20260705_035502_420_2696_vs_2695_bc9eb Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-97 HOT@r98-207 HEAVY_RAIN@r208-358 HOT@r359-374
  match_20260705_035555_511_2769_vs_2696_46f8b Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.2 good=+1 extra_w=HOT/HEAVY_RAIN | CLEAR@r1-94 MOUNTAIN_FOG@r95-204 HOT@r205-355 HEAVY_RAIN@r356-374
  match_20260705_035613_625_2696_vs_2753_15afa Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.1 good=+1 extra_w=MOUNTAIN_FOG/HOT | CLEAR@r1-84 HOT@r85-235 MOUNTAIN_FOG@r236-345 HOT@r346-374
  match_20260705_035704_393_3022_vs_2696_0163f Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-109 MOUNTAIN_FOG@r110-219 HOT@r220-329 HEAVY_RAIN@r330-374
  match_20260705_035710_456_2696_vs_2941_53bd0 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-96 HOT@r97-206 HEAVY_RAIN@r207-357 HOT@r358-374
  match_20260705_035839_022_2696_vs_2943_aebb0 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-107 HOT@r108-217 MOUNTAIN_FOG@r218-327 HOT@r328-374
  match_20260705_035936_138_2629_vs_2696_72888 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-108 HOT@r109-218 HEAVY_RAIN@r219-328 HOT@r329-374
  match_20260705_035954_569_2696_vs_2931_c1a7c Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+11.8 good=+1 extra_w=HOT | CLEAR@r1-117 HOT@r118-227 HEAVY_RAIN@r228-337 HOT@r338-374
  match_20260705_041523_948_2696_vs_2769_5fc23 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.8 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-84 HOT@r85-235 HEAVY_RAIN@r236-345 MOUNTAIN_FOG@r346-374
  match_20260705_042923_363_2629_vs_2696_1feaa Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-119 HOT@r120-229 MOUNTAIN_FOG@r230-339 HOT@r340-374
  match_20260705_042936_815_2769_vs_2696_d9c65 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.5 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-92 HOT@r93-202 HEAVY_RAIN@r203-353 MOUNTAIN_FOG@r354-374
  match_20260705_044542_861_2769_vs_2696_a348d Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.5 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-92 HOT@r93-202 HEAVY_RAIN@r203-353 MOUNTAIN_FOG@r354-374
  match_20260705_045439_001_2769_vs_2696_aa634 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.2 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-99 MOUNTAIN_FOG@r100-209 HOT@r210-319 HEAVY_RAIN@r320-374
  match_20260705_045831_556_2696_vs_2639_b4457 Δreal=+22.0 (clear +20.0, shrink  +2.0) fresh=+12.7 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-86 HOT@r87-237 HEAVY_RAIN@r238-347 MOUNTAIN_FOG@r348-374
  match_20260705_050154_418_2696_vs_2629_53105 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN | CLEAR@r1-116 MOUNTAIN_FOG@r117-226 HOT@r227-336 HEAVY_RAIN@r337-374
  match_20260705_051135_263_2714_vs_2696_eb968 Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.5 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-119 HOT@r120-229 HEAVY_RAIN@r230-339 MOUNTAIN_FOG@r340-374
  match_20260705_051242_458_2764_vs_2696_3654f Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-94 HOT@r95-204 HEAVY_RAIN@r205-355 HOT@r356-374
  match_20260705_051401_595_2696_vs_2769_04cff Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.5 good=+1 extra_w=HEAVY_RAIN/MOUNTAIN_FOG | CLEAR@r1-93 HOT@r94-203 HEAVY_RAIN@r204-354 MOUNTAIN_FOG@r355-374
  match_20260705_051503_949_2696_vs_2836_6b018 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+12.0 good=+1 extra_w=HEAVY_RAIN/HOT | CLEAR@r1-93 HOT@r94-203 HEAVY_RAIN@r204-354 HOT@r355-374
  match_20260705_052840_469_2696_vs_2836_87c81 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-106 HOT@r107-216 MOUNTAIN_FOG@r217-326 HOT@r327-374
  match_20260705_053343_274_2696_vs_2769_b079b Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-114 HOT@r115-224 MOUNTAIN_FOG@r225-334 HOT@r335-374
  match_20260705_053813_114_2629_vs_2696_dcafe Δreal=+21.0 (clear +20.0, shrink  +1.0) fresh=+12.6 good=+1 extra_w=MOUNTAIN_FOG | CLEAR@r1-107 HOT@r108-217 HEAVY_RAIN@r218-327 MOUNTAIN_FOG@r328-374
  match_20260705_054945_303_2696_vs_2769_03d28 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-113 HOT@r114-223 MOUNTAIN_FOG@r224-333 HOT@r334-374
  match_20260705_060013_755_2769_vs_2696_acc94 Δreal=+20.0 (clear +20.0, shrink  +0.0) fresh=+11.7 good=+1 extra_w=HOT | CLEAR@r1-119 HOT@r120-229 MOUNTAIN_FOG@r230-339 HOT@r340-374

## 机制说明

- 大路多 ~30 帧的天气暴露决定缩水：若额外帧落在 HOT(1.5×)/HEAVY_RAIN(1.3×) → 鲜度增益缩水；落在 MOUNTAIN_FOG(1.0×)/CLEAR(1.0×) → 不缩水。
- 山路 MOUNTAIN 边在 MOUNTAIN_FOG 下移动减速（倍率 1100）→ 山路多帧 → 大路相对更快（Δ 反增）；大路 ROAD 不受任何天气移动减速。
- 冰鉴 post-hoc 不变：天气降 fresh_no_ice，大路 2 冰鉴仍抵 2 crossing、山路 1 冰鉴抵 1 → 好果 Δ 通常稳住。
- 局限：compact.log 天气变化 round 取自 F 行（状态变化帧），若天气变化与状态变化不同帧则有数帧延迟（<10%，可忽略）；walker 不建模障碍 CLEAR/任务领取帧的天气微差。

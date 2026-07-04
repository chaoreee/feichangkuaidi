# Anomaly Timelines — cumulative N=2 anomaly games

> 仅异常局（UNDELIVERED / waitingStuck / projError>50 / unlucky_loss / lucky_win / loss+task<90）。
> 单局只作假设来源，决策须基于全语料聚合 + CI + 分段不回归（§3.3/§3.8）。

## matchId=match_20260704_132011_237_2696_vs_2809_6d6a1ed5  outcome=WIN  luck=expected_win  score=752  segments=delivered,task90_reached,mid_lead,weather_hit,contested,opp_delivered
  flags: waitingStuck=1
  r1 BREAK CLEAR S06 cost 1 | r185 TASK T_003 | r189 TASK T_005 | r190 WIND card=BING_ZHENG | r191 WIND card=BING_ZHENG | r192 WIND card=BING_ZHENG | r196 TASK T_005 | r272 TASK T_009 | r276 TASK T_012 | r277 MODE EVEN->CONSERVATIVE | r277 TASK T_013 | r277 REJ CLAIM_TASK code=OBJECT_BUSY | r331 ICE fresh=76.8 | r333 REJ PROCESS code=OBJECT_BUSY | r334 REJ PROCESS code=OBJECT_BUSY | r339 TASK T_015 | r340 REJ CLAIM_TASK code=OBJECT_BUSY | r368 TASK T_017 | r409 REJ PROCESS code=OBJECT_BUSY | r410 REJ PROCESS code=OBJECT_BUSY | r411 REJ PROCESS code=OBJECT_BUSY | r441 RUSH RUSH_PROTECT

## matchId=match_20260704_132951_558_2625_vs_2696_4dc35f68  outcome=WIN  luck=expected_win  score=752  segments=delivered,task90_reached,mid_even,weather_hit,contested,opp_delivered
  flags: waitingStuck=1
  r1 BREAK CLEAR S06 cost 1 | r185 TASK T_003 | r189 TASK T_005 | r196 HORSE SHORT_HORSE | r265 TASK T_006 | r269 TASK T_010 | r270 TASK T_011 | r270 REJ CLAIM_TASK code=OBJECT_BUSY | r274 TASK T_013 | r275 REJ CLAIM_TASK code=OBJECT_BUSY | r325 ICE fresh=77.1 | r327 WIND card=BING_ZHENG | r328 WIND card=BING_ZHENG | r329 WIND card=BING_ZHENG | r332 REJ PROCESS code=OBJECT_BUSY | r333 REJ PROCESS code=OBJECT_BUSY | r334 REJ PROCESS code=OBJECT_BUSY | r335 REJ PROCESS code=OBJECT_BUSY | r340 TASK T_014 | r437 RUSH RUSH_PROTECT


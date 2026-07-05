# reports/iter36_ab/ — Iter 36 §3 真实 A/B 上传落点

本目录接收 **平台前 30 名对战回流的新 iter36 trace**（`*.compact.log` 或 `match_*.log`），
用于 §3 真实 A/B 决策（iter36 新 client vs iter31 老基线）。

## 不要清 reports/ 顶层

`reports/` 顶层的 67 局 iter31 真实 trace 是 §3 的**老基线对比方**——清掉就没了
`version_ab_report` 的另一边。本子目录仅放**新 iter36 trace**，与顶层 iter31 共存。

## 上传后跑分析

把新 iter36 trace 文件放进本目录，然后在仓库根执行：

```bash
python3 -m analysis reports/iter36_ab/ reports/ --out-dir reports/iter36_ab_out/
```

- **输入**：`reports/iter36_ab/`（新 iter36）+ `reports/`（iter31 老基线）
- **输出**：`reports/iter36_ab_out/`（自动创建，与输入分离避免互相覆盖）
- `collect_reports` 按 matchId 去重，新老 matchId 不撞，各上各的

## §3 决策产物

看 `reports/iter36_ab_out/version_ab_report.md`：

- 按 `clientVersion` 分桶（`iter31` old vs `iter36` new），**非配对两样本**
  （真实对战对手随机，无法配对）
- DELTA：均分差 Welch CI + 胜率差 CI + 分段回归 + 对手类/运气混杂守卫
- sim 自动排除（`version_ab_report` 仅比 `source==platform`）
- N_old/N_new 任一 <30 标"假设级"，不合入

**判决**：正向（均分差 CI 下界 > 0、无分段回归）→ iter36 `ENABLE_STATIC_PLANNER`
固化；负则回退 flag（§0.5 纪律）。

## 备注

- 平台正在跑的是 **iter36** client；本仓库本地已推进到 iter37（运行期对手类观测层，
  纯观测不改动作）。iter36 trace 的 `clientVersion=iter36`，iter37 代码向后兼容可解析。
- iter36 trace **没有** `oppClass` 字段（该字段 iter37+ 才有），故 `runtime vs offline
  对账`段对 iter36 trace 会显示 `no_runtime`——预期行为，不影响 §3 决策。

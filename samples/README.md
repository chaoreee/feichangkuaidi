# samples/ — 协议与地图参考样例（reference fixtures）

本目录存放比赛服务端真实下发/配置的 **样例 JSON**，用作：

1. **规格参考**：核对字段名、层级、类型，补充协议文档中"以实际下发为准"的部分。
2. **解析开发依据**：M2 `core.WorldState` 解析、地图与寻路（Dijkstra）以这些真实结构为基准。
3. **离线测试夹具**：`scripts/mock_server.py` 与 `client/tests/` 可直接加载这些样例做回放/单测，无需连真实平台。

> 注意：这些是 **样例快照**，不是运行时权威。正式对战一切以服务端本局 `start` / 每帧 `inquire` 实际下发为准；
> 策略**禁止**硬编码这里的节点/路线/资源/任务位置（协议附录 A 明确要求）。

## 文件清单

| 文件 | 内容 | 对应协议章节 |
|---|---|---|
| `map_config.json` | 竞技地图配置（站点、路线边、资源投放、处理点、任务候选、障碍候选等） | 任务书 §2；协议 `start.map.gameplay` |
| `start_message.json` | 一条完整 `start` 消息样例（开局静态信息） | 协议 §5 |
| `inquire_message.json` | 一条完整 `inquire` 消息样例（某结算帧公开状态） | 协议 §7 + 附录 B/C/D/F |

> 若原始文件为中文名（`start消息.json` / `inquire消息.json`），已统一改为上述 ASCII 名以保证跨平台与工具兼容；
> 内容不变。

## 使用约定

- 只读参考，不在运行期被 `client/` import（提交包保持纯净）。
- 更新样例时，同步在此表登记来源与抓取帧号（如 `inquire_message.json` 取自第 N 帧）。
- 大字段（如地图渲染层 `map.layers`、`routePaths`）仅供参考，策略按协议"忽略展示层"处理。

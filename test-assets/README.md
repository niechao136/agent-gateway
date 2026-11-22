# 系统功能测试资源包（MCP / Skill / A2A）

本目录提供一组可直接导入平台的测试资源，用来验证 **MCP、Skill、A2A 是否能被 Agent 正确调用**。
只含源文件，未导入系统；导入需在前端手动操作（见文末）。

## 资源清单

### MCP server（stdio，零依赖，JSON-RPC 2.0）
| 文件 | 工具 | 验证点 |
|---|---|---|
| `mcp/file_stats_server.py` | `count_lines`, `word_freq` | stdio MCP 启动、工具发现、调用 |
| `mcp/text_utils_server.py` | `reverse`, `word_count`, `extract_emails` | 一个 MCP 暴露多工具，测工具选择 |

> 平台里已有的高德地图 MCP（streamable_http + query 鉴权）和 RAGFlow 内置检索工具（stdio + dataset_ids 数组）也参与组合，见下表。

### 自定义 Skill（含脚本）
| 目录 | 脚本 | 依赖 | 验证点 |
|---|---|---|---|
| `skills/weather-alert/` | `scripts/weather.py` | wttr.in（联网） | **脚本执行 + 外部 API + references** |
| `skills/text-analyzer/` | `scripts/analyze.py` | 无 | **脚本 + 模板文件** |
| `skills/json-formatter/` | `scripts/fmt_json.py` | 无 | **带参数脚本** |
| `skills/amap-guide/` | 无（纯文档） | 无 | 文档 Skill 与 MCP 配合 |
| `skills/a2a-orchestrator/` | 无（纯文档） | 无 | 文档 Skill 与 A2A 配合 |

每个 Skill 目录结构遵循平台约定：`SKILL.md` + `scripts/` + `references/` / `templates/`。

### SOUL.md（系统提示词）
| 文件 | 用途 |
|---|---|
| `souls/weather-agent-SOUL.md` | 天气 Agent：强制调用 weather-alert 脚本/wb_search 获取实时数据 |
| `souls/personal-agent-SOUL.md` | 个人 Agent：识别跨 Agent 任务，主动用 a2a_call 调用天气/地图 Agent 并聚合 |

> ⚠️ 个人 Agent 必须开启 `a2a` toolset 且绑定了内部 A2A 端点，否则不会有 a2a_call 工具。

## Agent 组合建议

| Agent | toolset | Skill | MCP | 验证目标 |
|---|---|---|---|---|
| A1 文本分析助手 | terminal + web | text-analyzer, json-formatter | text-utils | 脚本 Skill + 多工具 stdio MCP |
| A2 天气小助手 | terminal + web | weather-alert | file-stats | 脚本联网 + references |
| A3 地图向导 | 只读助手(web/vision/clarify) | amap-guide | 高德地图 | 文档 Skill + 外部 HTTP MCP |
| A4 调度中心 | terminal + web | a2a-orchestrator | — | 绑定 A1/A2/A3 的内部 A2A 端点，验证互调 |

> ⚠️ 带 `scripts/` 的 Skill 需要 **terminal 工具集开启**，否则 hermes 会自动隐藏该 Skill。A1/A2/A4 已开启 terminal。

## 导入步骤（前端手动）

1. **MCP 页** → 新建：
   - transport 选 `stdio`，command 填容器内脚本绝对路径（先把 `mcp/*.py` 放到 hermes 容器可访问目录，如 `/opt/data/test-mcp/`）
   - 例：`python3 /opt/data/test-mcp/file_stats_server.py`
2. **自定义 Skill 页** → 新建：
   - 填名称/描述/正文（SKILL.md 内容）
   - 用「上传文件」按目录上传 `scripts/`、`references/`、`templates/` 下的文件（保留相对路径）
3. **Agent 编辑页**：
   - 「工具」Tab 开启所需 toolset（脚本 Skill 必须开 terminal）
   - 「Skill」Tab 勾选对应 Skill
   - 「MCP」Tab 绑定对应 MCP
4. **A2A**：把 A1/A2/A3 发布后，在 A4 的「A2A」Tab 绑定指向它们的内部端点（不能绑自己）。

## 验证清单

- [ ] A1："统计这段话的词频：xxx" → 应调用 text-analyzer 脚本 + text-utils MCP
- [ ] A1："把这个格式化一下 {json}" → json-formatter 脚本
- [ ] A2："北京天气怎么样" → weather.py 调用 wttr.in 返回真实数据
- [ ] A3："从故宫到天安门怎么走" → 高德 MCP 路线规划
- [ ] A4："分析这段话并查北京天气" → 依次 A2A 调 A1 + A2 并聚合
- [ ] 控制台/SSE 中观察工具调用事件，确认 tool_start/tool_end 正常显示

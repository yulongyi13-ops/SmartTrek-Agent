# SmartTrek AI（Travel Agent）

基于 Python 的分层多智能体旅行规划系统：父 Agent 负责任务拆解、预算与长期记忆，可通过工具调用子 Agent、地图与搜索等能力，生成立即可用的行程方案与导出文件。

## 功能概览

- **对话式规划**：自然语言描述需求，Agent 迭代调用工具完成规划。
- **任务看板**：内置任务管理（创建、更新、列表等），便于跟踪多步计划。
- **预算账本**：记录与查询行程相关花费（与工具链联动）。
- **子智能体委派**：复杂子任务可委派给子 Agent 并行或串行执行。
- **MCP 扩展**：通过 `workspace/mcp/servers.json` 配置 MCP 服务（可选、按需启用）。
- **本地可视化界面**：Streamlit 对话页（`app.py`），会话内保持 Agent 状态。
- **命令行入口**：`main.py` 交互式终端，适合调试与脚本化环境。
- **可选 HTTP 服务**：FastAPI + SSE（`api/server.py`），便于与其他系统集成。

## 环境要求

- **Python**：建议 3.10 及以上。
- **Node.js**（可选）：若启用基于 `npx` 的 MCP 服务（如示例中的 Brave Search），需要本机已安装 Node。

## 快速开始

### 1. 安装依赖

在项目根目录 `travel_agent_project` 下执行：

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在 `travel_agent_project` 目录创建 `.env`（与 `config/settings.py` 中 `load_dotenv()` 一致），至少包含以下变量：

| 变量名 | 说明 |
|--------|------|
| `DEEPSEEK_API_KEY` | DeepSeek（OpenAI 兼容）API 密钥，**必填**。 |
| `DEEPSEEK_BASE_URL` | API 地址，默认 `https://api.deepseek.com/v1`。 |
| `DEEPSEEK_MODEL` | 默认模型名，默认 `deepseek-chat`。 |
| `PARENT_MODEL` | 父 Agent 使用的模型，未设置时回退到 `DEEPSEEK_MODEL`。 |
| `CHILD_MODEL` | 子 Agent 使用的模型，默认 `deepseek-chat`。 |
| `AMAP_API_KEY` | 高德开放平台 Web 服务 Key，**必填**（地图/路线相关工具）。 |
| `TAVILY_API_KEY` | Tavily 搜索 API Key，**必填**（联网搜索工具）。 |
| `MCP_CONFIG_PATH` | MCP 配置文件路径，默认 `workspace/mcp/servers.json`。 |

示例（请替换为真实密钥，勿提交到版本库）：

```env
DEEPSEEK_API_KEY=sk-...
AMAP_API_KEY=...
TAVILY_API_KEY=...
```

### 3. MCP（可选）

编辑 `workspace/mcp/servers.json`，按需增加或启用 MCP 服务。未安装对应运行时或不需要外接服务时，可将条目 `enabled` 设为 `false` 或保持示例默认。

## 运行方式

**以下命令均需在 `travel_agent_project` 目录下执行**（保证 `config`、`core` 等包内导入可用）。

### Streamlit 本地界面（推荐日常使用）

```bash
streamlit run app.py
```

浏览器打开提示的本地地址即可。侧边栏可选择运行模式、初始总资产；「重新初始化 Agent」会关闭 MCP、清空对话并重新创建 Agent。地图会在回复中解析到经纬度时自动展示。

### 命令行交互

```bash
python main.py
```

按提示选择权限模式、输入初始总资产后进入对话循环；输入 `exit` 或 `quit` 退出。

### 可选：FastAPI 服务

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

提供 `POST /api/chat`（SSE 流式事件），供其他客户端调用；按请求创建 Agent 的逻辑见 `api/agent_factory.py` 与 `api/server.py`。

## 目录结构（节选）

```text
travel_agent_project/
├── app.py                 # Streamlit 本地对话界面
├── main.py                # CLI 入口
├── requirements.txt
├── config/                # 配置与环境读取
├── core/                  # Agent、LLM、任务、预算、记忆、MCP 等核心模块
├── tools/                 # 工具实现与注册
├── prompts/               # 系统提示构建
├── hooks/                 # 运行期钩子（权限、日志、状态注入等）
├── api/                   # FastAPI、SSE、地图解析、按用户构建 Agent
├── skills/                # Skill 注册
├── workspace/             # 默认工作区：任务、结果、MCP 配置、记忆等
└── scripts/               # 辅助脚本（如并发回归）
```

## 开发与说明

- 更细的设计与迭代记录见 [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)（若仓库中已维护）。
- 运行产物（Markdown 报告、ICS 日历等）默认写入 `workspace/` 下相应子目录；使用 `api/agent_factory.build_user_agent` 时按 `user_id` 隔离到 `workspace/users/<user_id>/`。

## 许可证

若本仓库未单独提供许可证文件，以仓库根目录或组织约定为准。

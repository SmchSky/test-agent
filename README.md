# Test Agent

基于 LLM 的智能路由器测试 Agent —— 用自然语言描述测试需求，Agent 自动完成华为 NE 路由器配置和验证。

```
用户: 在 R1 和 R2 之间配置 OSPF 邻居，area 0，验证邻居建立成功

Agent: → 读取拓扑 → 下发配置 → 查询邻居状态 → ✅ OSPF 邻居已建立，状态为 Full
```

---

## 前置要求

| 依赖      | 版本    | 说明           |
|---------|-------|--------------|
| Python  | 3.11+ | 后端运行时        |
| Poetry  | 2.x   | 后端依赖管理       |
| Node.js | 18+   | 前端构建（仅开发机需要） |

> **Poetry 安装**：如果尚未安装，执行 `pip install poetry` 或参考 [官方文档](https://python-poetry.org/docs/#installation)。

---

## 快速启动

### 1. 启动后端

```bash
cd backend

# 安装依赖（首次 / 依赖变更后执行）
poetry install

# 启动开发服务器
poetry run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

启动成功后终端会输出：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Started reloader process
```

验证：浏览器访问 http://127.0.0.1:8000/health ，应返回 `{"status": "ok"}`。

### 2. 启动前端

```bash
cd frontend

# 安装依赖（首次 / 依赖变更后执行）
npm install

# 启动开发服务器
npm run dev
```

启动成功后终端会输出：

```
VITE v6.x.x  ready in xxx ms

➜  Local:   http://127.0.0.1:5173/
```

打开浏览器访问 **http://127.0.0.1:5173** 即可使用。

> 前端默认连接 `ws://127.0.0.1:8000/ws/chat`，后端地址可通过 `VITE_API_HOST` 环境变量覆盖。

---

## 环境变量

所有配置通过环境变量注入，**不改代码即可切换行为**。

### 核心配置

| 变量               | 默认值    | 说明                                              |
|------------------|--------|-------------------------------------------------|
| `LLM_PROVIDER`   | `mock` | LLM 引擎。`mock` = 本地模拟（无需 API Key），`zai` = 智谱 GLM |
| `TRANSPORT_MODE` | `mock` | 设备传输层。`mock` = 模拟设备，`scrapli` = 真实 SSH 连接       |
| `MAX_TURNS`      | `30`   | Agent 单次任务最大推理轮次                                |

### 智谱 GLM（当 `LLM_PROVIDER=zai` 时）

| 变量                    | 默认值                                     | 说明                |
|-----------------------|-----------------------------------------|-------------------|
| `ZAI_API_KEY`         | —                                       | **必填**。智谱 API Key |
| `ZAI_MODEL`           | `glm-5.1`                               | 模型名称              |
| `ZAI_BASE_URL`        | `https://open.bigmodel.cn/api/paas/v4/` | API 地址            |
| `ZAI_TIMEOUT_SECONDS` | `120`                                   | 请求超时              |

### 真实设备（当 `TRANSPORT_MODE=scrapli` 时）

| 变量                    | 默认值   | 说明          |
|-----------------------|-------|-------------|
| `DEVICE_SSH_USERNAME` | —     | SSH 用户名     |
| `DEVICE_SSH_PASSWORD` | —     | SSH 密码      |
| `DEVICE_SSH_PORT`     | `22`  | SSH 端口      |
| `TRANSPORT_IDLE_TTL`  | `300` | 空闲连接回收时间（秒） |

### 前端

| 变量              | 默认值              | 说明              |
|-----------------|------------------|-----------------|
| `VITE_API_HOST` | `127.0.0.1:8000` | 后端 WebSocket 地址 |

**示例**：使用智谱 GLM + 真实设备启动后端：

```bash
# Windows PowerShell
$env:LLM_PROVIDER="zai"
$env:ZAI_API_KEY="your-api-key-here"
$env:TRANSPORT_MODE="scrapli"
$env:DEVICE_SSH_USERNAME="admin"
$env:DEVICE_SSH_PASSWORD="admin@123"
poetry run uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Linux / macOS
LLM_PROVIDER=zai ZAI_API_KEY=your-key TRANSPORT_MODE=scrapli \
  DEVICE_SSH_USERNAME=admin DEVICE_SSH_PASSWORD=admin@123 \
  poetry run uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 运行测试

```bash
cd backend
poetry run pytest tests/ -v
```

当前包含 3 个 P0 测试用例：

| 测试                                                   | 说明                |
|------------------------------------------------------|-------------------|
| `test_topology_seed_loads_fixed_ospf_topology`       | 验证拓扑种子文件加载        |
| `test_micro_compact_clears_old_verbose_tool_outputs` | 验证上下文压缩           |
| `test_mock_agent_runs_p0_ospf_flow`                  | 端到端 Mock Agent 流程 |

---

## 项目结构

```
TestAgent/
├── backend/
│   ├── pyproject.toml            # Poetry 项目配置
│   ├── main.py                   # FastAPI 应用入口
│   ├── agent/                    # Agent 引擎
│   │   ├── graph.py              #   LangGraph 图定义
│   │   ├── prompts.py            #   System Prompt 构建（含拓扑注入）
│   │   └── runner.py             #   ReAct 循环执行器
│   ├── api/                      # API 路由
│   │   └── chat.py               #   WebSocket 对话端点
│   ├── core/                     # 核心配置
│   │   └── config.py             #   Settings（全部环境变量）
│   ├── llm/                      # LLM Provider 层
│   │   ├── base.py               #   抽象接口
│   │   ├── factory.py            #   Provider 工厂
│   │   ├── mock_provider.py      #   Mock（无需 API Key）
│   │   └── zai_provider.py       #   智谱 GLM
│   ├── tools/                    # Agent 工具
│   │   ├── base.py               #   Tool 基类
│   │   ├── device_tool.py        #   query / configure / operate
│   │   ├── topology_tool.py      #   拓扑查询
│   │   └── registry.py           #   工具注册
│   ├── infra/                    # 设备基础设施
│   │   ├── transport/            #   传输层（Scrapli / Mock）
│   │   └── operations/           #   执行引擎（事务回滚、断连韧性）
│   ├── services/                 # 业务服务
│   │   ├── topology.py           #   拓扑加载与查询
│   │   └── context_window.py     #   上下文窗口管理
│   ├── seeds/                    # 种子数据
│   │   └── ospf_basic.yml        #   P0 固定拓扑（3 台 NE40E）
│   └── tests/                    # 测试
├── frontend/                     # Vue 3 前端
│   ├── src/
│   │   ├── App.vue               #   对话组件（WebSocket）
│   │   ├── main.js               #   入口
│   │   └── styles.css            #   样式
│   ├── package.json
│   └── vite.config.js
└── docs/
    └── requirements.md           # 需求规格文档
```

---

## P0 固定拓扑

当前 Demo 使用固定的 3 台路由器三角形拓扑：

```
        R1
       /  \
  GE0/0/1  GE0/0/2
     /        \
    R2 ------  R3
      GE0/0/2
```

| 设备 | 型号    | 管理 IP      |
|----|-------|------------|
| R1 | NE40E | 10.10.10.1 |
| R2 | NE40E | 10.10.10.2 |
| R3 | NE40E | 10.10.10.3 |

| 链路      | 接口                | IP                        |
|---------|-------------------|---------------------------|
| R1 ↔ R2 | GE0/0/1 ↔ GE0/0/1 | 10.1.1.1/30 ↔ 10.1.1.2/30 |
| R1 ↔ R3 | GE0/0/2 ↔ GE0/0/1 | 10.1.2.1/30 ↔ 10.1.2.2/30 |
| R2 ↔ R3 | GE0/0/2 ↔ GE0/0/2 | 10.1.3.1/30 ↔ 10.1.3.2/30 |

---

## WebSocket 消息协议

前后端通过 `ws://host:8000/ws/chat` 通信，消息格式为 JSON：

| 消息类型               | 方向        | 说明                   |
|--------------------|-----------|----------------------|
| `user_message`     | 客户端 → 服务端 | 用户输入，可携带 `max_turns` |
| `agent_text_delta` | 服务端 → 客户端 | Agent 文本流式片段         |
| `tool_call_start`  | 服务端 → 客户端 | 工具调用开始               |
| `tool_call_result` | 服务端 → 客户端 | 工具调用结果               |
| `agent_done`       | 服务端 → 客户端 | Agent 执行结束 + 终止原因    |
| `error`            | 服务端 → 客户端 | 错误通知                 |

---

## 常见问题

### Q: 不装 Node.js 能用吗？

可以。构建好前端后通过 Nginx 托管静态文件即可，用户浏览器不需要任何开发环境。开发阶段才需要 Node.js。

### Q: Mock 模式是什么？

`LLM_PROVIDER=mock` + `TRANSPORT_MODE=mock` 是默认配置。后端会使用一个硬编码的 LLM 模拟器和 JSON 文件模拟设备响应，**不需要真实设备和 API Key**
，用于快速验证端到端流程。

### Q: 如何切换到真实 LLM？

设置 `LLM_PROVIDER=zai` 并提供 `ZAI_API_KEY`。如需使用部门内部 LLM，可新增一个 Provider 实现 `LLMProvider` 接口。

### Q: 如何连接真实路由器？

设置 `TRANSPORT_MODE=scrapli` 并配置 `DEVICE_SSH_USERNAME` / `DEVICE_SSH_PASSWORD`。确保运行服务器的网络可达路由器管理 IP。

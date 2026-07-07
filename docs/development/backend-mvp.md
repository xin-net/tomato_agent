# 后端开发说明

MVP 阶段的病例闭环已经完成。当前开发重点是向完整版 Agent 演进：扩展感知工具、强化可调整复查、接入外部日历/通知、增强知识库和保持 LLM 主导决策下的确定性安全边界。

## 当前架构

后端采用 FastAPI + SQLAlchemy + PostgreSQL。核心运行时不是简单 CRUD，而是：

`ConversationService -> CaseOrchestrator -> AgentDecisionEngine -> Tools -> StateMachine/SafetyChecker -> Memory`

其中：

- `CaseOrchestrator`：病例编排器，负责把用户输入、工具观察、状态机、事件记忆和复查任务串起来。
- `AgentDecisionEngine`：LLM 决策器，输出下一步动作、本轮用户意图和回答焦点；不可用或输出非法时会显式报错/升级，不再把最终回答伪装成规则模式。
- `Tools`：语义观察、症状抽取、知识检索、诊断/方案、复查比较、视觉观察、地点/天气观察、内部提醒。
- `Memory`：PostgreSQL 中的 Case、CaseEvent、Followup、Reminder，以及结构化 JSON 字段。
- `StateMachine`：控制病例状态流转。
- `SafetyChecker`：处置建议前的安全约束。

## 环境变量

复制示例：

```powershell
Copy-Item backend/.env.example backend/.env
```

默认数据库：

```text
postgresql+psycopg://xiaxin:123456@127.0.0.1:5432/tomato_agent
```

关键配置：

- `DATABASE_URL`：数据库连接。
- `JWT_SECRET_KEY`：JWT 签名密钥，正式环境必须替换为随机强密钥。
- `OPENAI_API_KEY`：后续启用真实 LLM/视觉工具。
- `OPENAI_TEXT_MODEL`：文本模型默认值。
- `OPENAI_VISION_MODEL`：视觉模型默认值。
- `WEATHER_API_KEY`：预留字段。当前默认使用浏览器经纬度调用 Open-Meteo 免 Key 天气接口。
- `CORS_ORIGINS`：允许访问后端的前端来源，开发模式默认包含 `5174` 和 `8000`。
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`：Google OAuth 后续接入凭据。
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`：GitHub OAuth 后续接入凭据。

## 数据库迁移

项目已接入 Alembic。首次建库或结构变化后运行：

```powershell
cd backend
alembic upgrade head
```

开发期 `app.main` 仍保留 `Base.metadata.create_all`，用于降低本地启动门槛；正式演进应以迁移文件为准。

## 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

或使用根目录脚本：

```powershell
.\scripts\dev-backend.ps1
```

## 主要接口

公开接口：

- `GET /health`
- `GET /api/system/status`
- `POST /api/auth/register`
- `POST /api/auth/login`

需要 JWT：

- `GET /api/auth/me`
- `POST /api/conversation/messages`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `GET /api/cases/{case_id}/events`
- `GET /api/cases/{case_id}/report`
- `POST /api/cases/{case_id}/followup`
- `POST /api/cases/{case_id}/close`
- `GET /api/reminders`
- `GET /api/reminders/due`
- `POST /api/reminders`
- `PATCH /api/reminders/{reminder_id}`

普通用户只能访问自己的病例；`admin` 角色预留跨用户查看能力。

## 工具状态

- `VisionTool`：接收图片 URL/data URL，配置 OpenAI Key 后调用 OpenAI Responses API 并要求结构化 JSON；输出会写入 `vision_observation`，再由 `CaseOrchestrator` 融合成 `multimodal_observation`，供 AgentDecisionEngine 综合判断。未配置时返回结构化不可用观察。
- `SemanticObservationTool`：使用大模型理解用户本轮自然语言，只读取本轮用户文字、病例文字记忆、复查计划和历史摘要，结构化判断本轮意图、是否为复查变化、复查趋势、用户纠正和症状语义。它不读取 VisionTool/WeatherTool/LocationTool 输出，也不负责地点、天气、阶段或采收，避免工具职责交叉。
- `LocationTool`：使用独立 LLM 判断用户本轮是否明确提供实际种植地点；用户显式地点优先，并通过高德地理编码获取 adcode。没有显式地点时，可使用客户端坐标反向地理编码或高德 IP 定位兜底，并要求用户确认。
- `WeatherTool`：根据 LocationTool 输出的 adcode 调用高德天气 API，只负责真实天气查询，不从用户文字中抽取“阴雨/高湿”等语义。用户文字里的天气事实由 SemanticObservationTool 作为上下文交给 AgentDecisionEngine 综合。
- `OpenAIAdapter`：文本模型适配器已具备真实调用边界，用于 Agent 决策、回复表达和视觉工具的模型调用。
- `ReminderRepository` / `CalendarReminderTool`：内部提醒工具，复查计划创建时生成提醒，用户提交复查后取消提醒；同时提供 Google Calendar 添加链接和 ICS 下载。网页端不能无授权静默写入 Windows/macOS/手机系统日历，自动同步需要后续接 Google/Microsoft/Apple 日历授权或本地桌面桥接。
- `KnowledgeSearchTool`：暂时保留但不参与常规诊断路径，后续用于 IPM、地方农技资料、登记标签提示等需要治理和可追溯的知识。

工具输出必须写入 Case/Event Memory，再由编排器继续推进，不能绕过状态机和安全检查直接生成最终处置。图片识别也是如此：多模态模型只提供观察线索，不直接决定病例状态、最终诊断或处置方案。

## 前端工作台

前端使用 Vite + React + TypeScript + Ant Design + React Flow。开发模式：

```powershell
cd frontend
npm install
npm run dev
```

如果需要指定端口，Vite 8 使用等号形式：

```powershell
npm run dev -- --host=127.0.0.1 --port=5174
```

访问：

```text
http://127.0.0.1:5174/
```

生产构建：

```powershell
cd frontend
npm run build
cd ../backend
uvicorn app.main:app --reload
```

构建完成后，`GET /` 会由 FastAPI 直接服务 React 工作台。

## 验证

```powershell
.\scripts\verify.ps1
```

或分别运行：

```powershell
cd backend
python -m pytest -q
```

```powershell
cd frontend
npm run build
```

说明：前端生产构建目前会提示 bundle 超过 500 kB，主要来自 Ant Design 和 React Flow。MVP 阶段先接受，后续再做代码分割。

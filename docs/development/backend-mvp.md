# 后端 MVP 开发说明

## 当前架构

后端采用 FastAPI + SQLAlchemy + PostgreSQL。核心运行时不是简单 CRUD，而是：

`ConversationService -> CaseOrchestrator -> AgentDecisionEngine -> Tools -> StateMachine/SafetyChecker -> Memory`

其中：

- `CaseOrchestrator`：病例编排器，负责把用户输入、工具观察、状态机、事件记忆和复查任务串起来。
- `AgentDecisionEngine`：当前为规则版决策器，输出下一步动作。
- `Tools`：症状抽取、知识检索、诊断/方案、复查比较、视觉观察、天气观察、内部提醒。
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
- `WEATHER_API_KEY`：后续启用真实天气 API。
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

- `VisionTool`：接收图片 URL/data URL，配置 OpenAI Key 后调用 OpenAI Responses API；未配置时返回结构化降级观察。
- `WeatherTool`：当前解析用户描述中的连续阴雨、高湿、闷棚等信号；真实天气 API 后续接入。
- `OpenAIAdapter`：文本模型适配器已具备真实调用边界，当前主决策仍使用规则版。
- `ReminderRepository`：内部提醒工具，复查计划创建时生成提醒，用户提交复查后取消提醒。

工具输出必须写入 Case/Event Memory，再由编排器继续推进，不能绕过状态机和安全检查直接生成最终处置。

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

# Backend MVP Development Notes

当前后端 MVP 使用：

- Python + FastAPI
- PostgreSQL via SQLAlchemy + psycopg
- Pydantic schemas
- Markdown Knowledge Memory
- 规则版 `AgentDecisionEngine`

当前前端工作台使用：

- Vite + React + TypeScript
- Ant Design 业务组件
- React Flow 状态机可视化

## 运行前准备

复制环境变量：

```powershell
Copy-Item backend/.env.example backend/.env
```

默认数据库：

```text
postgresql+psycopg://xiaxin:123456@127.0.0.1:5432/tomato_agent
```

当前本地开发环境使用 Docker 容器 `tomato-agent-postgres`。如果需要手动创建数据库，使用：

```sql
CREATE USER xiaxin WITH PASSWORD '123456';
CREATE DATABASE tomato_agent;
```

## 启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

服务启动后：

```text
GET http://127.0.0.1:8000/
GET http://127.0.0.1:8000/health
POST http://127.0.0.1:8000/api/cases
POST http://127.0.0.1:8000/api/conversation/messages
```

`/` 会优先返回 `frontend/dist` 中的 React 工作台；如果前端尚未构建，则回退到后端内置的最小聊天调试界面。

## 启动前端工作台

开发模式：

```powershell
cd frontend
npm install
npm run dev
```

默认地址：

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

构建完成后，后端 `GET /` 会直接服务 React 工作台。

## 工作台功能

React 工作台包含：

- 左侧病例列表：查看活跃、已结案和全部 Case。
- 中央聊天：用户只需要输入自然语言，系统会通过 Conversation 入口自动创建或续接 Case。
- 图片证据：聊天区可以选择图片，MVP 阶段会把图片保存为 Case/Event 的证据，但不会执行视觉诊断。
- 右侧当前病例：展示疑似问题、可信度、发生部位、复查日期和当前处置方案。
- 状态机观察：使用 React Flow 展示完整 Case Status 流程，并高亮当前状态和可达下一状态。
- 复查与事件记忆：展示 Follow-up 摘要和最近 Case Event 时间线。
- 复查提交：把用户复查描述和结构化变化信号提交给后端比较。
- 结案：用户确认后通过状态机进入 `CLOSED`。

调试界面右侧包含“状态机观察”面板，会展示 MVP 的 Case Status 流程，并高亮当前病例状态。这个面板只用于开发测试阶段观察状态流转，不代表最终产品 UI。

工作台会为当前浏览器会话生成独立测试用户，避免续接历史数据库中的活跃病例。点击“新会话”后，下一条消息会重新自动创建 Case，便于从头观察状态流转。

## 当前实现范围

已实现：

- Conversation 输入自动创建 Case。
- `/api/conversation/messages` 聊天入口。
- React 工作台。
- 状态机观察面板，用于测试阶段查看 Case Status 流转和下一状态。
- Case、Case Event、Follow-up 持久化模型。
- 规则版 `AgentDecisionEngine`。
- `StateMachine` 状态流转约束。
- `SafetyChecker` 安全检查。
- Markdown Knowledge Memory。
- 规则版诊断、处置方案和复查比较。
- 复查提交时先进入 `FOLLOWUP_REVIEW`，再根据趋势进入好转、继续观察、待补充或升级。
- 图片 Evidence Memory：`image_urls` 会写入 `structured_data.image_evidence`，并追加 `IMAGE_EVIDENCE_ADDED` 事件。
- 文本结构化增强：规则抽取会尽量识别生长阶段、近期天气、种植环境、距离采收天数、近期施肥和近期用药。

暂未实现：

- LLM 接入。
- 图片多模态识别。
- 日历/提醒同步。
- Word/PDF 知识导入。
- 用户登录和真实多用户权限。

## 当前验证命令

```powershell
cd backend
python -m pytest -q
```

```powershell
cd frontend
npm run build
```

说明：前端生产构建目前会提示 bundle 超过 500 kB，主要来自 Ant Design 和 React Flow。MVP 阶段先接受该结果，后续可以通过路由级动态导入和更细的图组件拆分优化。

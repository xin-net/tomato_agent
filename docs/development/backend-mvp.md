# Backend MVP Development Notes

当前后端 MVP 使用：

- Python + FastAPI
- PostgreSQL via SQLAlchemy + psycopg
- Pydantic schemas
- Markdown Knowledge Memory
- 规则版 `AgentDecisionEngine`

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

`/` 是最小聊天调试界面。用户只需要输入文字，系统会通过 Conversation 入口自动创建或续接 Case。

调试界面右侧包含“状态机观察”面板，会展示 MVP 的 Case Status 流程，并高亮当前病例状态。这个面板只用于开发测试阶段观察状态流转，不代表最终产品 UI。

调试界面会为当前浏览器会话生成独立测试用户，避免续接历史数据库中的活跃病例。点击“新会话”后，下一条消息会重新自动创建 Case，便于从头观察状态流转。

## 当前实现范围

已实现：

- Conversation 输入自动创建 Case。
- `/api/conversation/messages` 聊天入口。
- `/` 最小网页调试界面。
- 状态机观察面板，用于测试阶段查看 Case Status 流转。
- Case、Case Event、Follow-up 持久化模型。
- 规则版 `AgentDecisionEngine`。
- `StateMachine` 状态流转约束。
- `SafetyChecker` 安全检查。
- Markdown Knowledge Memory。
- 规则版诊断、处置方案和复查比较。

暂未实现：

- LLM 接入。
- 图片上传和多模态识别。
- 日历/提醒同步。
- Word/PDF 知识导入。
- 前端页面。

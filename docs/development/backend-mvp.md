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
postgresql+psycopg://postgres:postgres@localhost:5432/tomato_agent
```

需要先在本机 PostgreSQL 中创建数据库：

```sql
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
GET http://127.0.0.1:8000/health
POST http://127.0.0.1:8000/api/cases
```

## 当前实现范围

已实现：

- Conversation 输入自动创建 Case。
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

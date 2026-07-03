# Tomato Case Agent

番茄病虫害处置闭环管理系统 MVP。

目标不是做一个普通问答机器人，而是做一个面向番茄异常处置的 Case Agent：用户通过聊天和图片上报问题，系统自动创建病例，推进诊断、处置、复查、升级或结案，并保留可回放的事件记忆。

## 当前交付能力

- Conversation 聊天入口：用户不需要手动创建 Case。
- 图片 Evidence Memory：图片会进入病例证据和事件日志，MVP 阶段不执行视觉诊断。
- Case Memory：保存症状、部位、阶段、天气、采收时间、疑似问题、当前方案和状态。
- Event Memory：记录用户输入、图片证据、症状抽取、Agent 决策、安全检查、方案、复查和状态变化。
- Knowledge Memory：使用结构化 Markdown 番茄知识条目。
- StateMachine：约束病例生命周期流转。
- SafetyChecker：约束采收、近期用药、不确定性和高风险场景。
- Follow-up：创建复查任务，提交复查后比较趋势。
- React 工作台：病例列表、聊天、图片证据、状态机观察、事件时间线、复查、结案和报告导出。
- Markdown 报告：`GET /api/cases/{case_id}/report` 可导出病例过程。

## 技术栈

- Backend: Python + FastAPI + SQLAlchemy + PostgreSQL
- Frontend: Vite + React + TypeScript + Ant Design + React Flow
- Knowledge: Markdown Knowledge Entry
- Tests: pytest + TypeScript build

## 数据库

默认本地数据库：

```text
postgresql+psycopg://xiaxin:123456@127.0.0.1:5432/tomato_agent
```

配置文件：

```text
backend/.env
```

可以从示例复制：

```powershell
Copy-Item backend/.env.example backend/.env
```

## 开发模式

启动后端：

```powershell
.\scripts\dev-backend.ps1
```

启动前端：

```powershell
.\scripts\dev-frontend.ps1
```

访问：

```text
http://127.0.0.1:5174/
```

开发模式下，Vite 前端会代理 `/api` 到后端。

## 集成模式

构建前端：

```powershell
.\scripts\build.ps1
```

启动后端：

```powershell
.\scripts\dev-backend.ps1
```

访问：

```text
http://127.0.0.1:8000/
```

集成模式下，FastAPI 会直接服务 `frontend/dist`。

## 验证

```powershell
.\scripts\verify.ps1
```

该脚本会运行：

- `backend`: `python -m pytest -q`
- `frontend`: `npm run build`

## 推荐验收流程

1. 打开工作台，点击“新会话”。
2. 输入：

```text
下部老叶有褐色斑点，有同心轮纹，最近连续阴雨，现在结果期，距离采收大概 10 天。
```

3. 可选：选择一张番茄叶片图片作为证据。
4. 发送后观察：
   - 自动创建 Case。
   - 状态进入 `FOLLOWUP_PENDING`。
   - 右侧显示疑似问题、复查日期、状态机高亮和事件时间线。
5. 点击“提交复查”，填写：

```text
病斑没有增加，新叶正常，整体稳定。
```

6. 观察状态进入复查判断或好转。
7. 点击“报告”，导出 Markdown 病例报告。
8. 点击“结案”，完成闭环。

## 当前边界

- 图片只保存为证据，尚未接入多模态识别。
- 知识库是人工整理 Markdown，尚未接入 Word/PDF 导入和 RAG。
- Agent Decision 目前是规则版，尚未接入 LLM。
- Follow-up 是系统内复查任务，尚未同步日历或提醒。
- 用户身份是测试会话 ID，尚未做登录和权限。

# Tomato Case Agent

番茄病虫害处置闭环管理系统。当前 MVP 闭环已完成，项目进入完整版能力演进阶段。

这个项目不是普通问答机器人，而是一个面向番茄异常处置的 Case Agent：用户只需要聊天和上传图片，系统自动创建病例，基于病例状态、事件记忆、工具观察和安全约束推进诊断、处置、复查、提醒、升级或结案。

## 当前交付能力

- 登录与权限：用户名/密码注册登录，JWT 鉴权，普通用户只能访问自己的病例，管理员角色预留跨用户能力。
- Conversation 入口：用户不用手动创建 Case，聊天消息会自动创建或续接当前活跃病例。
- Case/Event Memory：保存症状、部位、阶段、天气、采收时间、图片证据、工具观察、Agent 决策、状态变化和回复记录。
- Tool 层：已接入视觉工具、日期工具、天气工具、内部提醒/日历链接工具和 OpenAI 文本适配器；工具输出会进入 Case/Event Memory，再影响安全检查、方案和回复。
- StateMachine：约束病例生命周期流转，避免 Agent 任意跳状态。
- SafetyChecker：对临近采收、近期用药、不确定性和高风险情况做安全检查。
- Follow-up：创建复查任务，提交复查后比较趋势，并自动取消对应提醒。
- React 工作台：病例列表、聊天、图片预览、状态机观察、事件时间线、复查、结案、报告导出、到期提醒查看。
- Alembic：提供数据库迁移基线，后续表结构变更通过迁移管理。

## 技术栈

- Backend: Python + FastAPI + SQLAlchemy + PostgreSQL + Alembic
- Frontend: Vite + React + TypeScript + Ant Design + React Flow
- Agent Runtime: CaseOrchestrator + AgentDecisionEngine + Tools + Memory + StateMachine + SafetyChecker
- Tests: pytest + TypeScript build

## 配置

默认本地数据库：

```text
postgresql+psycopg://xiaxin:123456@127.0.0.1:5432/tomato_agent
```

复制环境变量：

```powershell
Copy-Item backend/.env.example backend/.env
```

OpenAI 和 DeepSeek API 暂时可以留空。天气默认使用浏览器经纬度调用 Open-Meteo 免 Key 接口；定位失败或用户显式提供地点/天气时，会降级为文字天气线索并写入工具事件。

文本 LLM 可以通过 `LLM_PROVIDER` 选择 `openai` 或 `deepseek`。DeepSeek 当前官方 API 未提供图片输入/视觉识别能力，因此 `VISION_PROVIDER=deepseek` 时系统会保存图片证据并明确返回“不支持视觉识别”；真实图片识别仍需使用支持多模态输入的视觉模型提供方。

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

开发模式下，Vite 会代理 `/api` 到 FastAPI。

如果注册或登录时提示“无法连接后端服务”，通常是 FastAPI 没有启动，或前端访问地址没有走 Vite 代理。请先确认：

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
```

如果需要手动指定前端端口，Vite 8 参数使用等号形式：

```powershell
cd frontend
npm run dev -- --host=127.0.0.1 --port=5174
```

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

## 数据库迁移

首次或结构变化后可运行：

```powershell
cd backend
alembic upgrade head
```

开发期后端仍会在启动时 `create_all`，但正式演进应以 Alembic 迁移为准。

## 验证

```powershell
.\scripts\verify.ps1
```

该脚本会运行：

- `backend`: `python -m pytest -q`
- `frontend`: `npm run build`

## 推荐验收流程

1. 打开工作台，注册或登录账号。
2. 输入：

```text
下部老叶有褐色斑点，有同心轮纹，最近连续阴雨，现在结果期，距离采收大概 10 天。
```

3. 可选：上传一张番茄叶片图片作为证据。
4. 发送后观察自动创建 Case、状态进入 `FOLLOWUP_PENDING`、右侧状态机高亮、事件时间线出现工具观察和提醒创建。
5. 点击“提交复查”，填写：

```text
病斑没有增加，新叶正常，整体稳定。
```

6. 观察状态进入复查判断或好转，并看到提醒取消事件。
7. 点击用户旁边的“待提醒”查看内部提醒列表。
8. 点击“报告”导出 Markdown 病例报告。
9. 点击“结案”完成闭环。

## 当前边界

- 视觉工具已接入 OpenAI Responses API：配置 `OPENAI_API_KEY` 后会对图片生成结构化观察，并融合进 Case Memory、Agent 决策、知识检索和诊断证据；未配置时返回降级观察。
- 天气工具优先使用浏览器定位获取实时温度、湿度、降水和风速；用户明确说明“帮别人问/植株在某地/最近天气”时，以用户输入覆盖当前位置。
- 日历提醒当前是系统内部提醒，并提供 Google Calendar 添加链接和 ICS 下载；网页端不能无授权静默写入 Windows/macOS/手机系统日历，自动同步需要后续接日历 OAuth 或本地桌面桥接。
- Google/GitHub OAuth 登录已接入；本地使用前需要在对应 OAuth App 后台配置回调地址，并在 `backend/.env` 填写 Client ID / Client Secret。
- 知识库仍是人工整理 Markdown，Word/PDF RAG 暂未实现。

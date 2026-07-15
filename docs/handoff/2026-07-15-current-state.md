# Tomato Agent 交接文档

生成时间：2026-07-15 17:30:45 +08:00，Asia/Shanghai  
适用仓库：`D:\tomato_agent`  
当前分支：`codex/backend-mvp-agent-loop`  
记录时基线提交：`02a476e Fix location update persistence`

## 使用方式

新对话继续开发前，先阅读本文件，再阅读：

- `AGENTS.md`
- `CONTEXT.md`
- `docs/agent-architecture.md`
- `docs/llm-prompts.md`
- `docs/development/backend-mvp.md`

如果用户另有“新方向文档”，以用户的新方向文档为后续架构调整入口。本交接文档只记录当前状态和已知约束，不描述下一版改造方案。

## 项目当前目标

本项目是番茄病虫害处置闭环系统，不是普通问答系统。核心目标是把用户通过聊天和图片提交的番茄异常，转成可追踪、可复查、可调整的内部病例。

当前共识：

- 用户只需要聊天和发图片。
- 系统内部自动创建和维护 Case。
- Agent 不是简单调用大模型回答，而是围绕 Case 状态、环境、工具、记忆和安全边界循环推进。
- LLM 负责语义理解、观察综合、诊断判断、下一步动作选择和自然表达。
- 后端代码负责确定性边界：状态机、工具调用、权限、持久化、审计事件、安全检查和输出限制。
- 硬规则只应该用于边界和落地，不应该替代自然语言理解和核心决策。

## 当前架构简述

主链路：

`React UI -> ConversationService -> CaseOrchestrator -> Observe Tools -> AgentDecisionEngine -> Guardrails -> Action Tools -> Memory -> ResponseComposer`

关键模块定位：

- `CaseOrchestrator`：Agent runtime/编排器。组织一轮 Agent turn，读写病例记忆，调用工具，执行状态机和安全检查。
- `AgentDecisionEngine`：决策核心。基于上下文和工具观察输出结构化决策。
- `SemanticObservationTool`：理解用户本轮文本的语义，包括意图、复查趋势、用户纠正、症状语义。它不做地理编码和最终诊断。
- `VisionTool`：图片观察工具。输出图片中可见症状、候选问题、生长阶段/采收提示等，不直接决定最终处置。
- `LocationTool`：地点识别和标准化工具。用户明确地点优先，必要时调用高德地理编码。
- `WeatherTool`：真实天气查询工具。根据病例地点/adcode 查询天气。
- `SafetyChecker`：输出前安全边界，尤其限制具体农药名称、剂量、兑水比例、频次、混配处方。
- `CalendarReminderTool`：当前主要是内部复查提醒和 ICS/日历链接；系统级日历写入尚未完成。
- `ResponseComposer`：只把结构化结果改写成人话，不能新增事实、诊断、处置或安全边界。

## 当前已接入能力

- 用户注册/登录。
- Case 自动创建。
- 多轮对话保存。
- 用户消息和 Agent 回复事件化记录。
- 图片上传和图片证据保存。
- 视觉工具接入 OpenAI-compatible Responses API。
- 语义观察工具接入 LLM。
- AgentDecisionEngine 接入 LLM。
- ResponseComposer 接入 LLM。
- 高德地点/天气工具。
- 状态机可视化。
- 右侧工具调用时间线。
- 右侧 Agent 运行轨迹，展示 Observe/Decide/Act/Guard/Memory 的输入输出。
- 内部复查任务和提醒。
- 前端生产构建可由后端服务。

## 最近重要修复

最近几次地点/天气链路修复非常重要，后续不要回退：

1. 自动定位地点不能等同于用户确认地点。
   - `amap_ip` / `browser` 只是候选地点。
   - 只有用户明确提供的地点才是 `user_explicit`。

2. LocationTool 的 LLM 输出必须做容错解析。
   - 模型可能返回 `confidence: 0.99`，而不是字符串。
   - 模型可能返回 `evidence: "..."`，而不是数组。
   - 当前代码已在 `LocationLanguageObservation` 中归一化这些类型。

3. 后续用户明确说“实际种植地在天津市”时，必须更新：
   - `structured_data.location_observation.location`
   - `structured_data.location_observation.location_source`
   - `structured_data.weather_observation.location`
   - `structured_data.weather_observation.adcode`
   - 右侧“当前病例”的地点和天气展示。

4. 确认窗口内不能用 IP/浏览器定位兜底覆盖用户输入。
   - 如果系统刚提示用户确认地点，下一轮应优先做 LLM 地点识别。
   - 用户没给明确地点时，沿用旧候选地点即可，不再重复用自动定位覆盖。

真实浏览器验证过的行为：

- 第一轮不说地点，系统可用 IP/定位得到成都并提示确认。
- 第二轮说“实际种植地在天津市。”，右侧地点更新为天津市，天气更新为天津天气。
- 第三轮说“确定，就是天津市。”，右侧仍保持天津市，不回退。

相关提交：

- `02a476e Fix location update persistence`
- `441fc0c Handle location confirmation replies`
- `a87ed09 Lock case location after confirmation`
- `6b9f699 Refine location reuse and agent trace`

## 当前验证命令

后端测试：

```powershell
python -m pytest backend/tests -q
```

前端构建：

```powershell
cd frontend
npm run build
```

最近一次完整验证结果：

- 后端：`40 passed`
- 前端：`npm run build` 通过

## 启动方式

后端：

```powershell
cd backend
uvicorn app.main:app --reload --port 8000
```

前端开发：

```powershell
cd frontend
npm run dev
```

常用访问：

- 前端开发：`http://127.0.0.1:5174/`
- 后端生产构建服务：`http://127.0.0.1:8000/`
- 系统状态：`http://127.0.0.1:8000/api/system/status`

## 环境前提

数据库：

- PostgreSQL
- 默认数据库名：`tomato_agent`
- 默认用户：`xiaxin`
- 默认密码：`123456`

关键环境变量位于 `backend/.env`。该文件可能包含真实 API key，不要打印、提交或复制到文档。

主要外部能力：

- OpenAI-compatible LLM endpoint
- 高德 Web 服务 key
- Google/GitHub OAuth 配置

## 当前已知问题和技术债

1. Agent 架构可能仍需整体重构。
   - 当前实现经过多轮迭代，能跑通主要闭环，但模块边界仍有历史包袱。
   - 后续如果有新架构方案，应优先对照 `CaseOrchestrator` 和 `AgentDecisionEngine` 的职责重新划分。

2. `CaseOrchestrator` 偏长。
   - 它承担了工具编排、状态变更、响应构造、记忆融合、事件写入等多种职责。
   - 后续可考虑拆成更明确的 runtime stages 或 services。

3. Prompt 和 schema 必须继续保持一致。
   - 已多次出现“prompt 要求”和“Pydantic schema 期待”不完全一致的问题。
   - 新增 LLM 输出字段时，必须同时更新 prompt、schema、容错解析和测试。

4. 不要把 LLM 语义理解退化成关键词规则。
   - 如果要判断“用户是否纠正地点/是否复查/是否趋势变坏”，优先通过 LLM 结构化输出。
   - 代码只负责使用结构化结果和边界校验。

5. 前端状态有过历史问题。
   - 用户消息应立即出现在左侧会话和聊天区。
   - Agent 回复完成后应刷新详情。
   - 切换会话时应显示完整历史消息，顺序不能乱。

6. 浏览器定位不是可靠种植地。
   - 浏览器位置只能作为首次候选。
   - 用户明确地点必须优先。

7. 知识库目前不是核心链路。
   - `KnowledgeSearchTool` 暂时不作为常规诊断主路径。
   - 后续知识库更适合承载 IPM、地方农技资料、登记标签、采前安全间隔等需要外部治理的信息。

8. 日历能力尚未完整实现。
   - 当前是内部提醒、ICS、Google Calendar link 等。
   - 自动写入 Windows/macOS/iOS/Android 系统日历需要后续 OAuth 或客户端桥接。

## 后续开发注意事项

- 如果用户报告“前端没更新”，不要先假设是 React 展示问题。
  - 先查接口响应。
  - 再查数据库 `cases.structured_data`。
  - 再查 `case_events` 中工具调用是否成功。
  - 最后查前端展示函数。

- 如果用户报告“Agent 回答说更新了，但右侧没更新”，优先怀疑：
  - ResponseComposer/DecisionEngine 自然语言说了某件事，但结构化记忆没有写入。
  - LLM 输出格式偏离 schema，被工具解析失败。
  - 事务因 500 回滚，用户消息没有落库。

- 对 LLM 工具输出要做边界容错，但不要把语义判断改成硬规则。

- 提交前至少跑：
  - `python -m pytest backend/tests -q`
  - 前端相关改动时跑 `npm run build`

- 用户倾向于希望每次有意义改动后提交并推送。

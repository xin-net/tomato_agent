# 大模型提示词清单

本文档记录当前系统中直接调用大模型的位置。原则是：大模型负责语义理解、观察、综合判断、决策和表达；状态流转、安全检查、数据库写入、提醒创建和工具执行由后端确定性代码负责。

## AgentDecisionEngine

位置：`backend/app/agents/decision_engine.py`

定位：Agent 的思考与决策核心。它不再只是选择动作，也负责综合用户文字、图片观察、日期、地点、天气、病例记忆和复查任务，输出诊断判断、处置计划、复查安排、用户意图、回答焦点和下一步动作。

当前提示词摘要：

```text
你是 Tomato Case Agent 的决策核心。
你的目标是把当前番茄异常病例推进到安全、可执行、可复查、可记录的下一步。
你负责综合观察并形成本轮判断：信息是否足够、疑似类别、可能原因、严重程度、风险点、下一步动作、工具计划和回复焦点。
你不能直接修改数据库，不能绕过状态机、安全检查、工具权限和输出安全边界。
请输出严格 JSON，不要输出 Markdown。
动作只能来自 available_actions。
如果信息不足以给出处置建议，选择 ASK_MORE_INFO，并给出具体追问。
如果信息足以形成保守判断并安排处置/复查，选择 DIAGNOSE_AND_PLAN。
active_followup 只表示系统已有复查计划，不表示用户当前消息一定是复查。
只有 semantic_observation 显示用户本轮确实是在描述后续变化时，才选择 COMPARE_FOLLOWUP。
如果用户是在补充信息、提出猜测、纠正事实、询问能否用药或下一步怎么做，应继续综合判断并选择 DIAGNOSE_AND_PLAN 或 ASK_MORE_INFO。
地点来自 LocationTool，天气来自 WeatherTool，图片观察来自 VisionTool，语义观察来自 SemanticObservationTool；你需要综合它们。
不要给具体农药名称、剂量、兑水比例、施药频次或混配处方。
不要选择 CLOSE_CASE，除非用户明确要求停止跟踪该问题。
```

输出字段：

```json
{
  "next_action": "ASK_MORE_INFO | DIAGNOSE_AND_PLAN | COMPARE_FOLLOWUP | ESCALATE | CLOSE_CASE",
  "reason": "选择该动作的原因",
  "confidence": "low | medium | high",
  "requested_state": "目标状态，可为空",
  "questions": ["需要追问的问题"],
  "observations_used": ["本次决策用到的观察"],
  "tool_plan": ["计划使用的工具"],
  "user_intent": "本轮用户意图",
  "response_focus": ["本轮回复焦点"],
  "information_sufficient": true,
  "problem_category": "病害/虫害/缺素/肥害/环境问题/生理性问题等",
  "likely_causes": ["可能原因"],
  "diagnosis_evidence": ["判断依据"],
  "confidence_label": "面向用户的把握程度",
  "severity_label": "严重程度",
  "immediate_actions": ["马上可以做的处理"],
  "observation_points": ["复查观察点"],
  "escalation_conditions": ["升级条件"],
  "followup_after_days": 3,
  "followup_trend": "COMPARE_FOLLOWUP 时必填：IMPROVING | UNCHANGED | WORSENING | INSUFFICIENT_INFO | NEEDS_HUMAN_CONFIRMATION",
  "followup_evidence": ["COMPARE_FOLLOWUP 时说明趋势依据"],
  "chemical_safety_note": "用药安全边界",
  "harvest_safety_note": "采收安全边界",
  "plain_summary": "简洁摘要"
}
```

## SemanticObservationTool

位置：`backend/app/tools/semantic_observation_tool.py`

定位：理解用户本轮自然语言。它不做最终诊断，不依赖 VisionTool、WeatherTool、LocationTool 输出，也不负责地点、真实天气、图片阶段或采收判断。

当前提示词摘要：

```text
你是番茄病虫害处置闭环系统的语义观察工具。
你的任务不是给最终诊断，而是理解用户本轮自然语言，并输出严格 JSON。
只根据 latest_user_message、本病例已有文字记忆、复查计划和历史摘要判断本轮语义。
不要依赖图片工具、天气工具或地点工具的输出。
必须依靠语义理解，不要做关键词匹配或固定话术匹配。
地点由 LocationTool 判断，天气由 WeatherTool 判断，图片中的阶段/采收由 VisionTool 判断。
如果用户纠正这些事实，只把它们放进 corrections。
需要判断 user_intent、是否复查、复查趋势、发生部位、症状、问题类别、用户提到的候选问题、严重程度和用户纠正。
```

输出字段：

```json
{
  "user_intent": "initial_diagnosis | followup_report | correction | chemical_safety_question | pesticide_detail_question | handling_plan_question 等",
  "is_followup_report": false,
  "followup_trend": "IMPROVING | UNCHANGED | WORSENING | INSUFFICIENT_INFO | NEEDS_HUMAN_CONFIRMATION | null",
  "followup_evidence": [],
  "affected_parts": [],
  "symptoms": [],
  "possible_categories": [],
  "mentioned_problems": [],
  "severity": null,
  "corrections": {},
  "uncertainties": [],
  "confidence": "low | medium | high"
}
```

## LocationTool

位置：`backend/app/tools/location_tool.py`

定位：只判断用户是否明确提供实际种植地点；如果提供，则调用高德地理编码。未提供时，由客户端坐标或高德 IP 定位兜底。主循环只在 Case 首轮或用户明确更新地点时调用它；后续轮次沿用 Case Memory 中的种植地点。

当前提示词摘要：

```text
你是番茄病虫害处置系统里的 LocationTool。
你的唯一任务是判断用户本轮消息是否明确提供了番茄实际种植地点。
不要判断天气、症状、复查趋势、生长阶段或采收时间。
如果用户明确说出城市、区县、乡镇、村、大棚所在地、帮别人问且给出对方地点，填写 explicit_location。
如果没有明确地点，explicit_location 必须为 null。
只输出 JSON：explicit_location, confidence, evidence, uncertainties。
```

## VisionTool

位置：`backend/app/tools/vision_tool.py`

定位：观察图片，只输出结构化视觉观察，不直接下最终诊断和处置方案。

当前提示词摘要：

```text
你是番茄病虫害处置闭环系统中的视觉观察工具。
你的任务是观察图片，不直接生成最终诊断和处置方案。
请只基于图片可见内容输出结构化 JSON：发生部位、可见症状、候选问题、严重程度线索、不确定点和建议追问。
如果图片不清晰或无法确认，请明确写入 uncertainties，不要编造。
```

输出字段：

```json
{
  "observed_parts": [],
  "visual_symptoms": [],
  "possible_problems": [],
  "severity_signals": [],
  "uncertainties": [],
  "suggested_questions": [],
  "growth_stage_hint": null,
  "harvest_hint": null,
  "confidence": "low | medium | high"
}
```

## ResponseComposer

位置：`backend/app/tools/response_composer.py`

定位：把已经通过决策器、状态机和安全检查的结构化结果改写成自然中文。它不是诊断器，不能新增诊断、事实、药名、剂量、兑水比例、施药频次或改变复查安排。

当前提示词摘要：

```text
你是 Tomato Case Agent 的回复表达器，不是诊断器。
你只能基于结构化结果回复，不能新增诊断、不能新增事实、不能改变状态、复查日期、处置建议或安全边界。
必须优先回答用户本轮真正问的问题，语言自然、短、可执行，有结构但不要像 JSON、表格或报告。
不能给具体农药名称、剂量、兑水比例、施药频次或混配处方。
如果信息不足，温和追问；如果有复查安排，告诉用户后续直接描述变化即可。
如果 environment_confirmation 有内容，只在首次确认地点或用户更新地点时自然提醒用户确认实际种植地点是否一致。
不要把结构化字段逐项翻译出来，不要写成报告腔。
```

## 不再使用大模型的位置

以下旧工具已从主循环移除：

- `SymptomExtractionTool`
- `DiagnosisTool`
- `PlanTool`
- `FollowupCompareTool`

`KnowledgeSearchTool` 暂时保留但不参与常规诊断。后续知识库更适合承载 IPM、地方农技规范、温室管理、登记标签提示、采前安全间隔等需要外部资料治理的知识，而不是把普通病虫害百科作为模型能力的限制。

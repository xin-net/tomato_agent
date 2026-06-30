# Tomato Case Agent

本文档定义番茄异常处置系统的领域语言。该系统会把用户发现的番茄问题转化为可追踪的病例，并持续推进诊断、处置、复查、升级或结案。

## 领域语言

**Conversation**:
用户实际看到和参与的聊天式交互流，可以包含文本、图片和系统回复。
_避免使用_: Case、ticket

**Case**:
一个从首次上报到诊断、处置、复查、升级或结案的番茄异常病例。
_避免使用_: Chat、session、ticket

**Case Status**:
Case 当前所处的生命周期位置，例如待补充信息、待复查、好转、恶化、已升级或已结案。
_避免使用_: Chat state、page state

**Case Event**:
Case 中一条有时间顺序的关键记录，可以是用户输入、系统决策、安全检查、状态变化、处置方案、复查或结案。
_避免使用_: Log line、message

**Follow-up**:
用户执行处置方案或观察一段时间后的复查安排。
_避免使用_: Reminder、task、revisit

**Follow-up Schedule**:
系统为 Follow-up 创建的可调整提醒计划，后续可以同步到日历、提醒或待办渠道，并随 Case 变化而更新。
_避免使用_: Fixed timer、static reminder

**Follow-up Result**:
系统对复查趋势的解释，例如好转、无明显变化、恶化、信息不足或需要人工确认。
_避免使用_: Score、review status

**Handling Plan**:
系统给出的保守、安全受约束的下一步处置建议和观察重点。
_避免使用_: Prescription、treatment、cure

**Safety Check**:
在生成用户可见建议前，对采收时间、近期用药、不确定性、严重程度和种植环境进行的确定性检查。
_避免使用_: LLM safety opinion、disclaimer

**Agent Decision**:
决策层输出的结构化意图，用于说明系统接下来应该尝试哪个动作以及原因。
_避免使用_: Final answer、model response

**Agent Action**:
Tomato Case Agent 可以请求的有限预定义动作，例如追问信息、诊断并生成方案、比较复查、升级或结案。
_避免使用_: Free-form instruction、tool name

**Working Memory**:
当前轮次临时组装的推理上下文，包括最新用户输入、Case Status、结构化症状、当前 Follow-up、检索到的知识和安全上下文。
_避免使用_: Prompt、buffer

**Case Memory**:
Case 当前持久化摘要，包括状态、结构化字段、疑似问题、当前处置方案和当前 Follow-up。
_避免使用_: Short-term memory、cache

**Event Memory**:
完整、有序的 Case Event 历史，用于解释、回放和比较病例过程。
_避免使用_: Conversation transcript

**Knowledge Memory**:
用于诊断和生成处置方案的番茄病害、虫害、缺素、药害和环境问题知识。
_避免使用_: Raw PDF dump、training data

**User Profile**:
可选的跨病例用户信息，例如种植环境、偏好、地区或常见问题。
_避免使用_: Long-term memory、account

**Human Confirmation**:
建议用户咨询当地农技人员、植保专家或其他合格人员。
_避免使用_: Human handoff、manual review

**Knowledge Entry**:
针对一个番茄问题整理出的结构化知识记录，包括症状、发生部位、诱发条件、易混淆问题、非化学措施、升级条件和安全提醒。
_避免使用_: Chunk、document

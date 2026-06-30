# Conversation-derived cases and adjustable follow-ups

已接受。

用户不会直接操作“病例系统”概念，而是像普通聊天一样发送文字和图片。系统从 Conversation 中自动创建、匹配、更新或关闭 Case，并把 Case 作为内部处置对象来维护状态、事件、复查和安全约束。

Follow-up 不是固定的 3 天计时器，而是 Case 的下一次观察计划。MVP 可以先保存在系统内；后续会通过 `ReminderTool` 或日历适配器同步到用户日历、提醒或待办中，并在用户提前反馈、症状恶化、安全策略变化或环境变化时调整、取消或重新安排。

**影响**

- UI 可以保持聊天和图片上传体验，不要求用户理解 Case、Event、Follow-up 等内部概念。
- `CaseOrchestrator` 必须能根据 Conversation 输入判断是新建 Case、继续当前 Case、提交 Follow-up，还是建议创建新 Case。
- Follow-up 的设计要支持 reschedule、cancel、complete 和 replace，而不是只支持创建一次。

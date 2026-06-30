# Tool interface and adapter layering

已接受。

系统区分 `Tool Interface`、`Tool Adapter` 和 `External Resource`。`Tool Interface` 是 `CaseOrchestrator` 或 Agent runtime 可以调用的稳定能力接口；`Tool Adapter` 负责把该接口连接到数据库、文件、模型或外部 API；`External Resource` 是真实资源本身，例如 SQLite、Markdown、LLM API、天气 API、视觉模型或 Word/PDF 资料。

这个分层避免把外部 API、数据库表、模型参数或文件解析细节直接暴露给 Agent。天气、图片识别、文档导入等能力从 Agent 架构视角属于 Tool，但运行时只能通过项目定义的 Tool Interface 使用它们。

**影响**

- Agent 只能看到稳定工具能力，不能直接依赖外部资源细节。
- 后续替换 SQLite、LLM、天气 API、视觉模型或知识检索实现时，不需要重写 Agent 决策契约。
- `SafetyCheckTool` 和 `StateTransitionTool` 属于强制工具，由 `CaseOrchestrator` 控制调用，不由模型自由决定是否使用。

# Agent runtime architecture

已接受。

系统将 Tomato Case Agent 实现为一个运行时回路，而不是某个单独的类或某个框架选择。`CaseOrchestrator` 是运行入口，负责组装 Working Memory，向 `AgentDecisionEngine` 请求结构化 Agent Decision，调用确定性模块和动作工具，持久化 Case Event，并返回用户可见响应。

这样既能让 Agent 在架构中清晰可见，又不会让 LLM 直接拥有持久化、状态流转或安全裁决能力。决策层提出下一步意图；运行时和约束模块决定该意图是否执行以及如何执行。

**考虑过的方案**

- 将 LangChain 风格的 agent executor 作为系统核心。
- 将每个接口做成固定业务流程。
- 围绕一个小型 Agent Decision contract 实现项目自己的运行时回路。

选择项目自己的运行时回路，是因为这个产品是一个有状态的病例处置流程，并且有严格安全约束。通用 agent executor 会隐藏过多生命周期细节，而固定接口流程又会把 Agent 降级成简单文本生成。

# Agent action contract

已接受。

MVP 阶段，Agent Decision 层只能从有限动作集合中选择：`ASK_MORE_INFO`、`DIAGNOSE_AND_PLAN`、`COMPARE_FOLLOWUP`、`ESCALATE` 和 `CLOSE_CASE`。它的输出是带有原因、置信度、可选追问和请求状态的动作意图；它不能直接更新数据库，也不能最终确定状态流转。

初始动作集合刻意小于完整内部工具列表。`EXTRACT_SYMPTOMS`、`SEARCH_KNOWLEDGE`、`CHECK_SAFETY`、`CREATE_FOLLOWUP` 和 `SAVE_EVENT` 是 `CaseOrchestrator` 使用的内部运行时/工具操作，不作为模型可自由选择的动作。

**影响**

- 模型拥有足够自主性，可以根据上下文选择下一步业务动作。
- 每个动作都有已知执行路径，因此运行时保持可测试。
- 扩展 Agent 时需要显式增加动作，而不是依赖模型自由发挥。

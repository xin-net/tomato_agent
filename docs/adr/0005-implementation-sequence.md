# Implementation sequence

已接受。

开发会先从确定性病例闭环开始，再逐步加入 LLM 行为：先实现持久化、Case Status、Case Event、Follow-up 和规则版动作执行；再加入 LLM 症状结构化；再加入 Agent Decision contract；再加入整理后的 Knowledge Memory；再实现受安全约束的诊断和 Handling Plan；最后实现复查比较。

这个顺序能先验证产品闭环，再依赖模型行为。它也能让项目独立测试状态机、事件记忆和安全策略，而这些部分最能决定系统是真正的 Agent 工作流，还是一次性聊天机器人。

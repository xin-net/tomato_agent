# State machine and safety guardrails

已接受。

Case Status 流转和 Safety Check 是确定性约束，不是 LLM 判断。Agent Decision 层可以请求状态变化或动作，但 `StateMachine` 负责验证流转是否合法，`SafetyChecker` 负责在返回用户可见建议前检查采收时间、近期用药、不确定性、严重程度和种植环境。

这是必要的，因为系统在 MVP 阶段有意避免具体农药名称、剂量、兑水比例、施药频次和混配建议。任何与安全策略冲突的生成内容，在到达用户前都必须被阻断、改写或升级。

**影响**

- LLM 可以辅助理解模糊语言和推理，但不能绕过硬性安全约束。
- 测试可以不调用 LLM 就验证状态流转和安全行为。
- 即使 Agent Decision 没有请求，运行时也必须对诊断和处置方案动作强制执行 Safety Check。

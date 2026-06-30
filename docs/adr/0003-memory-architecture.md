# Memory architecture

已接受。

系统使用面向病例的记忆，而不是通用聊天记忆。Working Memory 只存在于一次 `CaseOrchestrator` 执行过程中；Case Memory 保存当前持久化 Case 摘要和当前 Follow-up；Event Memory 保存完整有序的 Case Event 历史；Knowledge Memory 保存经过整理的番茄问题知识；User Profile 推迟到 MVP 之后。

Knowledge Memory 可以来源于 Word 或 PDF 资料，但 MVP 运行时知识会先整理成结构化 Markdown Knowledge Entry。直接对原始 PDF/Word 做 RAG 暂不采用，因为抽取质量、切块边界以及不安全农药细节对一个安全受约束的处置系统来说风险过高。

**影响**

- 复查比较使用相关 Case Event，而不是通用的“最近 N 条消息”聊天缓冲。
- 知识检索从整理后的条目上做关键词/类别匹配开始，后续可升级为 BM25 或向量检索。
- 用户个性化不属于 MVP；必要上下文先记录在每个 Case 内。

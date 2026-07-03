# MVP Delivery Checklist

## 可交付目标

当前 MVP 的交付目标是证明 Tomato Case Agent 的病例闭环成立：

```text
用户聊天/图片
-> 自动创建 Case
-> 结构化症状和图片证据
-> Agent 决策
-> 安全约束和状态机
-> 生成处置方案
-> 创建 Follow-up
-> 复查比较
-> 事件回放
-> 报告导出
-> 结案
```

## 已完成

- 后端 FastAPI API。
- PostgreSQL 持久化模型。
- Conversation 自动创建或续接 Case。
- Case、Case Event、Follow-up 数据模型。
- 规则版症状结构化。
- 图片 Evidence Memory。
- 规则版 AgentDecisionEngine。
- 状态机约束。
- SafetyChecker。
- Markdown Knowledge Memory。
- 规则版诊断、方案和复查比较。
- React 工作台。
- 状态机可视化。
- 事件时间线。
- 复查提交。
- 结案。
- Markdown 病例报告导出。
- 一键验证脚本。
- 开发和集成启动脚本。

## 验收命令

```powershell
.\scripts\verify.ps1
```

## 验收场景

### 场景 1：直接形成诊断和复查

输入：

```text
下部老叶有褐色斑点，有同心轮纹，最近连续阴雨，现在结果期，距离采收大概 10 天。
```

预期：

- 自动创建 Case。
- 状态为 `FOLLOWUP_PENDING`。
- 疑似问题为番茄早疫病。
- 创建复查日期。
- 事件中包含 `AGENT_DECISION`、`DIAGNOSIS_GENERATED`、`PLAN_GENERATED`、`FOLLOWUP_CREATED`、`STATE_CHANGED`。

### 场景 2：信息不足时追问

输入：

```text
我的番茄叶子发黄，还有一些斑点，怎么办？
```

预期：

- 自动创建 Case。
- 状态为 `NEED_MORE_INFO`。
- 返回追问问题。

### 场景 3：图片证据

输入文字并选择图片。

预期：

- Case detail 中存在 `structured_data.image_evidence`。
- 事件中存在 `IMAGE_EVIDENCE_ADDED`。
- UI 中显示图片证据提示。
- 系统不把图片当作已识别诊断结论。

### 场景 4：复查好转

在待复查 Case 上提交：

```text
病斑没有增加，新叶正常，整体稳定。
```

预期：

- 复查趋势为好转或稳定。
- 状态进入 `IMPROVING` 或 `FOLLOWUP_REVIEW`。
- 不应误升级到 `ESCALATED`。

### 场景 5：复查恶化

提交：

```text
病斑变多了，上部叶片也开始有斑。
```

预期：

- 状态进入 `ESCALATED`。
- UI 状态机高亮人工确认。

### 场景 6：报告导出和结案

预期：

- 点击“报告”可导出 Markdown。
- 点击“结案”后状态进入 `CLOSED`。
- 已结案 Case 不再作为默认活跃 Case 续接。

## 未完成但已预留

- VisionTool：图片识别叶片、虫体、果实异常。
- KnowledgeImportTool：Word/PDF/网页导入知识。
- RAG/混合检索：结构化条目 + BM25/向量检索。
- ReminderTool：日历、提醒、待办同步。
- User Profile：跨病例用户画像。
- RegionPolicy：地区、登记标签、安全间隔期约束。
- Auth：用户登录和权限隔离。
- Production migrations：Alembic 或其他迁移工具。

## 交付判断

当前版本可以作为 MVP 演示和内部验证版本交付；它不应被解释为生产级农业诊断系统，也不应输出具体农药名称、剂量、兑水比例、施药频次或混配建议。

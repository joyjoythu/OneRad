# 人机协同机制

人机协同采用 LangGraph `interrupt()` 原语实现**挂起—确认—恢复**循环，而非「先执行后通知」。

## 挂起—确认—恢复循环

`human_review` 节点把中断类型与待审批数据打包为 interrupt payload，图随即挂起并把状态序列化到 checkpoint；前端依据 `interrupt_type` 渲染对应审批面板；用户的确认、取消或「其他」指令通过 REST 端点转为 `Command(resume=...)`，LangGraph 从 checkpoint 恢复并进入 `execute_confirmed` 分支执行或取消，最后清空全部 `pending_*` 字段并回到 `call_llm`。

```
process_tool_calls 识别需确认工具
        │  设置 pending_* + interrupt_type
        ▼
   human_review ── interrupt({type, pending_*})
        │  图暂停，状态序列化到 checkpoint
  ┌─────┼─────┐
 确认   取消   其他(替代指令)
POST   POST   POST
/confirm /cancel /other
  └─────┴─────┘
        ▼
 execute_confirmed
  ├── confirmed → 实际执行 → 注入 {"executed": true, ...}
  └── cancelled → cancelled ToolMessage（重操作追加 HumanMessage）
        │  清空所有 pending_* → 回到 call_llm
```

## 前端审批面板与 interrupt_type 的映射

| interrupt_type | 前端面板组件 | 用户可做的操作 |
|---------------|-------------|---------------|
| `system_command` | CommandPanel.vue | 查看命令详情 → 确认 / 取消 |
| `file_plan` | PlanEditor.vue | 查看/编辑文件操作计划（增删改条目）→ 确认 / 取消 |
| `python_script` | ScriptPanel.vue | 查看代码（高亮 + 风险标记）→ 确认 / 取消 |
| `radiomics_plan` | RadiomicsPanel.vue | 查看配对 → 确认（进入提取参数）/ 取消 |
| `radiomics_execution` | RadiomicsPanel.vue | 查看提取参数（YAML 路径/输出目录/病例数）→ 确认 / 取消 |
| `radiomics_analysis` | RadiomicsPanel.vue | 查看分析参数（特征 CSV/临床表/ID 列/Label 列）→ 确认 / 取消 |
| `feature_statistics` | RadiomicsPanel.vue | 查看统计参数 → 确认 / 取消 |
| `subagent_dispatch` | ApprovalPanel.vue | 查看子任务列表 → 确认 / 取消 |
| `user_choice` | ChoicePanel.vue | 查看问题与选项 → 选择 / 输入「其他」答案 / 取消 |

**ask_user_choice 的提问同样经 human_review 挂起**（`interrupt_type = "user_choice"`），但 `route_after_process` 对它强制走 human_review——`auto_approve` 不能代答，否则答案为空。前端渲染 ChoicePanel，用户选择（或输入「其他」）后由 `POST /threads/{id}/answer` 转为 `Command(resume={"action": "answer", "answer": ...})` 恢复图执行，`execute_confirmed` 的 user_choice 分支把答案作为 ToolMessage 返回给 LLM。

完整的触发工具矩阵见 [关键设计决策 · interrupt_type 完整矩阵](/design/decisions#interrupt-type-完整矩阵)。

## 取消的语义处理

- **简单查询取消**（`system_command`）：仅返回 cancelled ToolMessage，LLM 自然知道「操作没做」，不会误判
- **重操作取消**（`file_plan` / `python_script` / `radiomics_*` / `feature_statistics` / `subagent_dispatch`）：返回 cancelled ToolMessage，并追加 HumanMessage（"我取消了刚才的操作，请不要重试。请询问我现在想做什么。"），防止 LLM 将「取消结果」误读为「操作失败」而自动重试

## 执行结果的防重问标记

所有已确认执行的操作结果统一注入防重问标记：

```json
{
  "executed": true,
  "note": "用户已确认，操作已执行完成。请直接向用户总结执行结果，不要再要求确认。",
  ...原有字段...
}
```

System Prompt（`agent-core` SKILL.md）中也明确告知 LLM：被 `{"executed": true, ...}` 包裹的结果表示操作已在用户确认后执行完毕，Agent 应直接向用户总结结果，**绝不再要求确认**。

## 确认-执行分离

传统 Agent 工具设计是「LLM 调用 → 工具函数直接执行 → 返回结果」；OneRad 的工具设计是两层：

```
LLM 调用 → 工具函数校验参数 → 返回 {"_pending_tool": ..., 参数}
         → process_tool_calls 识别为需确认
         → human_review / auto_confirm
         → execute_confirmed 实际执行
```

这种设计的优势：

1. **LLM 和用户在审批面板看到相同的参数**——由工具函数校验后生成，而非 LLM 直接拼 JSON
2. **用户可在审批前编辑**——如修改文件操作计划的路径、增删条目
3. **审批面板可以格式化展示**——代码高亮、配对置信度表格、参数列表

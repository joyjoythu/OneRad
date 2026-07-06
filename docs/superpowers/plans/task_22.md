# Task 22: 最终回归测试

### Task 22: 最终回归测试

**Files:**
- 全部 tests/

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 真实数据端到端测试**

准备 1-2 组真实数据，运行完整流程，确认 Word 报告输出正确。

- [ ] **Step 3: Docker 构建验证**

Run: `docker-compose up --build`
Expected: 服务启动，UI 可访问

- [ ] **Step 4: Commit 最终版本**

```bash
git add .
git commit -m "release: v1.0 AutoRadiomics Agent"
```

---

## 自我审查

### Spec 覆盖检查

| 设计文档章节 | 对应任务 |
|--------------|----------|
| 统一 state schema | Task 2-3 |
| Discovery Agent（规则+LLM） | Task 6-7 |
| Clinical Agent | Task 8 |
| Matching Agent | Task 9 |
| QC Agent | Task 10 |
| Feature Agent（复用 cir_get_features） | Task 11 |
| Analysis Agent（LASSO+LR, 5 折 CV） | Task 12-13, 20 |
| Report Agent（Word + LLM 润色） | Task 14 |
| Orchestrator 注册/Merge | Task 4, 15 |
| UI + Docker | Task 18-19 |

### Placeholder 检查

- 无 "TBD" / "TODO" / "implement later"
- 每个任务包含具体文件路径、代码、测试、运行命令
- 类型/方法名在任务间一致（`DiscoveryAgent`, `ClinicalAgent`, `run_matching`, `QCAgent`, `FeatureAgent`, `AnalysisAgent`, `ReportAgent`）

### 已知边界

- `AnalysisAgent` 的 LASSO feature selection 使用每折 intersection；小样本时可能为空，已兜底使用 covariates。每折拟合后保存 LASSO 路径图，路径列表随分析结果返回并插入报告。
- `QCAgent` 中 modality 优先从 matching.matched_df 的 row 读取并回退到 config；Discovery pair 的 modality 会随 matched_df 透传。
- Docker 中 PyRadiomics 编译可能耗时，已在 Dockerfile 安装 build-essential。

---

## 执行方式选择

Plan complete and saved to `docs/superpowers/plans/2026-07-06-autoradiomics-agent-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach would you like?
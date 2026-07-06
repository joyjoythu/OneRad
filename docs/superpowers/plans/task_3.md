# Task 3: 实现 Orchestrator 主循环与中断恢复

### Task 3: 实现 Orchestrator 主循环与中断恢复

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py` 追加：
```python
def test_run_with_mock_handlers():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")

    def mock_discovery(state):
        return {"success": True, "message": "ok"}

    orch.register_handler(PipelineStage.DISCOVERY, mock_discovery)

    events = list(orch.run())
    assert any(e["type"] == "pipeline_start" for e in events)
    assert orch.state["stage"] == PipelineStage.INTERRUPTED  # 后续阶段未注册
```

- [ ] **Step 2: 实现 run()、_run_stage()、resume()**

在 `Orchestrator` 类中添加：

```python
    def run(self) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        self.state["stage"] = PipelineStage.IDLE
        self._emit(self._make_event("pipeline_start", "流水线启动"))
        current = PipelineStage.DISCOVERY
        return self._continue_from(current)

    def _continue_from(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        current = stage
        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current

            if current.name in self.state["config"]["skip_stages"]:
                self._emit(self._make_event("stage_skip", f"跳过阶段: {current.name}"))
                current = get_next_stage(current)
                continue

            success, error_msg = self._run_stage(current)

            if not success:
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                self._emit(self._make_event(
                    "stage_interrupt",
                    f"阶段 {current.name} 中断: {error_msg}",
                    {"error": error_msg, "stage": current.name},
                ))
                return self.state

            current = get_next_stage(current)

        if current == PipelineStage.COMPLETED or current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            self._emit(self._make_event("pipeline_complete", "流水线完成"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "流水线终止"))

        return self.state

    def _run_stage(self, stage: PipelineStage) -> tuple[bool, str]:
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return False, f"阶段 {stage.name} 未注册 handler"

        self._emit(self._make_event("stage_start", f"开始: {stage.name}", {"stage": stage.name}))

        try:
            if stage == PipelineStage.ANALYSIS:
                n = self._get_merged_sample_count()
                if n < 30:
                    return False, f"有效样本量不足: 仅 {n} 例，要求 ≥ 30"

            result = handler(self.state)
            if not isinstance(result, dict) or "success" not in result:
                return False, f"阶段 {stage.name} 返回格式错误"

            key = "merged" if stage == PipelineStage.MERGE else stage.name.lower()
            self.state[key] = result

            if not result["success"]:
                return False, result.get("message", "未知错误")

            self._emit(self._make_event(
                "stage_complete",
                f"完成: {stage.name}",
                {"stage": stage.name, "details": result.get("message", "")},
            ))
            return True, ""
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            return False, f"{stage.name} 阶段异常: {e}\n{tb}"

    def _get_merged_sample_count(self) -> int:
        merged = self.state.get("merged")
        if merged and isinstance(merged, dict):
            return merged.get("n_samples", 0)
        qc_passed = self.state.get("qc", {}).get("passed_pairs", [])
        matched_ids = self.state.get("matching", {}).get("matched_ids", [])
        qc_ids = {p["patient_id"] for p in qc_passed}
        return len(set(matched_ids) & qc_ids)

    def resume(self, user_decision: str) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        if self.state["stage"] != PipelineStage.INTERRUPTED:
            self._emit(self._make_event("error", "resume() 只能在 INTERRUPTED 状态下调用"))
            return self.state

        self.state["user_decision"] = user_decision
        interrupted_stage = self.state.get("interrupted_at")

        if user_decision == "abort":
            self.state["stage"] = PipelineStage.FAILED
            self._emit(self._make_event("pipeline_fail", "用户终止流水线"))
            return self.state

        if user_decision == "skip":
            if interrupted_stage:
                self.state["config"]["skip_stages"].append(interrupted_stage.name)
            next_stage = get_next_stage(interrupted_stage) if interrupted_stage else None
            if next_stage is None:
                self.state["stage"] = PipelineStage.COMPLETED
                self._emit(self._make_event("pipeline_complete", "流水线完成"))
                return self.state
            return self._continue_from(next_stage)

        if user_decision == "retry":
            return self._continue_from(interrupted_stage)

        self._emit(self._make_event("error", f"未知决策: {user_decision}"))
        return self.state
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator run/resume loop and stage execution"
```

---

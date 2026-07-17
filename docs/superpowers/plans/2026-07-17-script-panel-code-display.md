# Agent 右侧脚本面板显示源码 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 agent 界面右侧的脚本确认面板中看到待执行 Python 脚本的完整源码和描述。

**Architecture:** 后端 `prepare_script()` 返回的 meta 内联 `code` 字段，经现有 `pending_script` → SSE/REST 链路送达前端；前端 `PendingScript` 接口把 `explanation` 对齐为 `description`，`ScriptPanel.vue` 绑定新字段并对缺失 code 做兜底。

**Tech Stack:** Python 3.11 + pytest（后端）；Vue 3 + TypeScript + Pinia + Element Plus + vitest（前端）。

**Spec:** `docs/superpowers/specs/2026-07-17-script-panel-code-display-design.md`

---

### Task 1: 后端 prepare_script meta 内联 code

**Files:**
- Modify: `app/code_runner.py:213-218`（`prepare_script` 的 return dict）
- Test: `tests/test_code_runner.py`
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_code_runner.py` 末尾追加：

```python
def test_prepare_script_meta_includes_code(tmp_path):
    """meta 携带源码，前端右侧面板据此展示脚本内容。"""
    code = "print('hello')"
    meta = prepare_script(code, "demo", str(tmp_path))
    assert meta["code"] == code
    assert Path(meta["script_path"]).read_text(encoding="utf-8") == meta["code"]
```

在 `tests/test_agent_tools.py` 的 `test_execute_python_script_returns_low_pending`（约 53-62 行）之后追加：

```python
def test_execute_python_script_pending_includes_code_and_description(tmp_path):
    fake_llm = MagicMock()
    tools = build_tools(str(tmp_path), fake_llm)
    code = "print('hello from agent tool')"
    result = tools["execute_python_script"].invoke(
        {"description": "low risk test", "code": code}
    )
    data = json.loads(result)
    assert data["script"]["code"] == code
    assert data["script"]["description"] == "low risk test"
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/test_code_runner.py::test_prepare_script_meta_includes_code tests/test_agent_tools.py::test_execute_python_script_pending_includes_code_and_description -v
```

预期：两个测试均 FAIL，原因为 `KeyError: 'code'`。

- [ ] **Step 3: 实现 — meta 加 code 字段**

`app/code_runner.py` 的 `prepare_script()` return dict（213-218 行）改为：

```python
    risk_level = classify_risk(code)
    return {
        "description": description,
        "script_path": str(script_path),
        "risk_level": risk_level,
        "created_at": ts,
        "code": code,
    }
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/test_code_runner.py tests/test_agent_tools.py tests/test_agent_nodes.py tests/test_agent_graph.py tests/test_api_agent.py -v
```

预期：全部 PASS（后三个文件覆盖 pending_script 流经 nodes/graph/API 的链路，确认无回归）。

- [ ] **Step 5: Commit**

```bash
git add app/code_runner.py tests/test_code_runner.py tests/test_agent_tools.py
git commit -m "feat: prepare_script meta 内联脚本源码，供前端面板展示"
```

### Task 2: 前端接口对齐 + ScriptPanel 绑定

**Files:**
- Modify: `frontend/src/api/agent.ts:43-48`（`PendingScript` 接口）
- Modify: `frontend/src/components/ScriptPanel.vue:12-17`
- Test: `frontend/src/components/__tests__/ScriptPanel.spec.ts`（新建）

- [ ] **Step 1: 确认 `explanation` 无其他引用**

```bash
grep -rn "explanation" frontend/src/
```

预期：仅 `frontend/src/api/agent.ts`（接口定义）和 `frontend/src/components/ScriptPanel.vue`（绑定）两处。若出现其他文件，先停下来把该文件一并纳入本任务。

- [ ] **Step 2: 写失败测试**

新建 `frontend/src/components/__tests__/ScriptPanel.spec.ts`（写法对齐 `AgentChat.spec.ts`：真实 ElementPlus 插件 + pinia）：

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ScriptPanel from '../ScriptPanel.vue'
import { useAgentStore } from '@/stores/agent'

function setupWrapper() {
  return mount(ScriptPanel, {
    global: { plugins: [ElementPlus] },
  })
}

describe('ScriptPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders script code and description from pendingScript', async () => {
    const store = useAgentStore()
    store.pendingScript = {
      tool_call_id: 'tc-1',
      code: "print('hello')",
      risk_level: 'low',
      description: '打印测试',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.find('.script-code').text()).toContain("print('hello')")
    expect(wrapper.find('.script-explanation').text()).toContain('打印测试')
  })

  it('shows fallback text when code is missing', async () => {
    const store = useAgentStore()
    store.pendingScript = {
      tool_call_id: 'tc-1',
      code: '',
      risk_level: 'low',
      description: '打印测试',
    }

    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('脚本内容不可用')
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd frontend && npx vitest run src/components/__tests__/ScriptPanel.spec.ts
```

预期：FAIL —— `description` 不在 `PendingScript` 类型上（TS 报错），且面板不渲染描述/兜底文案。

- [ ] **Step 4: 实现 — 接口对齐 + 面板绑定**

`frontend/src/api/agent.ts` 的 `PendingScript`（43-48 行）改为：

```typescript
export interface PendingScript {
  tool_call_id: string
  code: string
  risk_level: 'low' | 'medium' | 'high'
  description: string
}
```

`frontend/src/components/ScriptPanel.vue` 模板 12-17 行改为：

```html
        <pre class="script-code" tabindex="0"><code>{{ script.code || '脚本内容不可用' }}</code></pre>

        <div v-if="script.description" class="script-explanation">
          <div class="script-section-title">说明</div>
          <p>{{ script.description }}</p>
        </div>
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd frontend && npx vitest run src/components/__tests__/ScriptPanel.spec.ts && npm run type-check && npm run lint
```

预期：测试 PASS；type-check 与 lint 无错误。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/components/ScriptPanel.vue frontend/src/components/__tests__/ScriptPanel.spec.ts
git commit -m "feat: 脚本面板展示源码与描述，PendingScript 接口对齐后端"
```

### Task 3: 全量回归

**Files:** 无改动，仅验证。

- [ ] **Step 1: 后端全量测试**

```bash
python -m pytest tests/ -v
```

预期：全部 PASS。

- [ ] **Step 2: 前端全量测试 + 构建检查**

```bash
cd frontend && npm run test:unit && npm run build
```

预期：vitest 全部 PASS；`vue-tsc` 与 `vite build` 成功。

- [ ] **Step 3: 无需 commit**

回归不产生改动；若前两步有修复，单独提交并说明原因。

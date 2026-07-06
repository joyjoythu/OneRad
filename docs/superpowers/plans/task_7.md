# Task 7: 实现 Discovery Agent 的 LLM ID 正则推断

### Task 7: 实现 Discovery Agent 的 LLM ID 正则推断

**Files:**
- Modify: `app/discovery.py`
- Modify: `app/llm.py`
- Modify: `tests/test_discovery.py`

- [ ] **Step 1: 在 llm.py 添加专门 prompt 函数**

`app/llm.py` 添加：
```python
ID_INFERENCE_TEMPLATE = """你是一个医学影像数据命名规范分析专家。
请根据提供的文件名样本，推断患者ID的提取规则，返回一个Python正则表达式字符串。
要求：
1. 正则只提取患者ID部分，不包含模态、序列、mask等后缀
2. 尽可能通用，能覆盖所有样本
3. 只输出纯JSON格式：{{"pattern": "正则表达式字符串", "explanation": "简要说明"}}

文件名样本：
{samples}
"""


def build_id_inference_prompt(filenames: List[str]) -> Tuple[str, str]:
    system = "You are a medical imaging filename analyst. Return only JSON."
    user = ID_INFERENCE_TEMPLATE.format(samples="\n".join(filenames))
    return system, user
```

- [ ] **Step 2: 在 DiscoveryAgent 添加 LLM 推断路径**

`app/discovery.py` 添加：
```python
    def _infer_id_pattern_via_llm(self, files: List[Path]) -> Optional[str]:
        if self.llm_client is None:
            return None
        samples = []
        seen = set()
        for f in files:
            name = get_base_name(f)
            if name not in seen:
                samples.append(name)
                seen.add(name)
            if len(samples) >= 20:
                break
        if len(samples) < 2:
            return None
        from app.llm import build_id_inference_prompt
        system, user = build_id_inference_prompt(samples)
        try:
            response = self.llm_client.call(system, user, temperature=0.1, max_tokens=500)
            parsed = self.llm_client._extract_json(response)
            pattern = parsed.get("pattern", "")
            re.compile(pattern)
            return pattern
        except Exception:
            return None
```

并在 `run()` 中，在 `_classify_files` 之前插入：
```python
        if self.id_pattern is None and self.llm_client is not None:
            inferred = self._infer_id_pattern_via_llm(files)
            if inferred:
                self.id_pattern = inferred
```

- [ ] **Step 3: 添加测试**

`tests/test_discovery.py` 追加：
```python
from unittest.mock import MagicMock


def test_discovery_with_llm_id_inference(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"pattern": "SUB_\\\\d+", "explanation": "test"}'
    mock_llm._extract_json.return_value = {"pattern": r"SUB_\d+"}

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))
    assert result["success"] is True
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/discovery.py app/llm.py tests/test_discovery.py
git commit -m "feat: add LLM-based ID pattern inference for Discovery"
```

---

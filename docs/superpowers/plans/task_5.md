# Task 5: 实现 LLM 封装

### Task 5: 实现 LLM 封装

**Files:**
- Create: `app/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_llm.py`:
```python
from unittest.mock import patch, MagicMock
from app.llm import LLMClient


def test_parse_json_response():
    client = LLMClient(api_key="fake")
    text = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age"]}'
    result = client._extract_json(text)
    assert result["id_col"] == "PatientID"
```

- [ ] **Step 2: 实现 LLMClient**

`app/llm.py`:
```python
import json
import re
import os
from typing import Optional, Dict, Any, List, Tuple

from langchain.prompts import PromptTemplate
from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url
        self.model = model
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 1500) -> str:
        if not self.client:
            raise RuntimeError("LLMClient 未配置 API key")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        text = text.strip()

        # 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Markdown code block
        matches = re.findall(r'```(?:json)?\s*([\s\S]*?)```', text)
        for m in matches:
            try:
                return json.loads(m.strip())
            except json.JSONDecodeError:
                continue

        # 第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return None

    def render_prompt(self, template: str, **kwargs) -> str:
        prompt = PromptTemplate.from_template(template)
        return prompt.format(**kwargs)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_llm.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/llm.py tests/test_llm.py
git commit -m "feat: add LLMClient with PromptTemplate and JSON extraction"
```

---

## Phase 2: Agent 实现

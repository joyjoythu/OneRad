import json
import re
import os
import string
from typing import Optional, Dict, Any, List, Tuple

from openai import OpenAI


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
    system = "你是一个医学影像文件名分析专家。只返回 JSON。"
    user = ID_INFERENCE_TEMPLATE.format(samples="\n".join(filenames))
    return system, user


COLUMN_IDENTIFICATION_TEMPLATE = """请分析以下临床数据表格，识别 ID 列、二分类标签列和临床特征列。
返回纯 JSON：{{"id_col": "...", "label_col": "...", "feature_cols": ["..."], "reasoning": "..."}}

表格信息：
- 行数: {n_rows}
- 列数: {n_columns}
- 任务描述: {task_hint}

列详情：
{columns}
"""


def _format_columns(columns: List[Dict]) -> str:
    lines = ["| 列名 | 类型 | 非空数 | 缺失率 | 唯一值 | 示例 |"]
    for c in columns:
        samples = c["samples"]
        # Escape characters that would break the markdown table.
        samples = str(samples).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        if len(samples) > 50:
            samples = samples[:50] + "..."
        lines.append(f"| {c['column_name']} | {c['dtype']} | {c['non_null']} | {c['missing_rate']} | {c['n_unique']} | {samples} |")
    return "\n".join(lines)


def build_column_identification_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    system = (
        "You are a clinical data analyst for radiomics research. "
        "Return ONLY a JSON object with keys: id_col, label_col, feature_cols, reasoning. "
        "Label_col must be a binary 0/1 outcome. feature_cols must not include id_col or label_col."
    )
    user = COLUMN_IDENTIFICATION_TEMPLATE.format(
        n_rows=context["n_rows"],
        n_columns=context["n_columns"],
        task_hint=context["task_hint"],
        columns=_format_columns(context["columns"]),
    )
    return system, user


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
        """Call the LLM chat endpoint and return the text content of the response."""
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

    def call_json(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 1500) -> Optional[Any]:
        """Call the LLM and attempt to parse the response as JSON, returning None if parsing fails."""
        text = self.call(system, user, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(text)

    def _extract_json(self, text: str) -> Optional[Any]:
        """Extract and parse the first valid JSON object or array found in *text*."""
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

        # 第一个 [ 到最后一个 ]
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return None

    def render_prompt(self, template: str, **kwargs) -> str:
        """Render a brace-style prompt template with the supplied keyword variables."""
        return template.format(**kwargs)

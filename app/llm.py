import json
import re
import os
from typing import Optional, Dict, Any, List, Tuple

from openai import OpenAI

from app.constants import DEEPSEEK_MODEL
from app.skills import load_skill


def build_id_inference_prompt(filenames: List[str]) -> Tuple[str, str]:
    system = load_skill("filename-id")
    user = "文件名样本（JSON）：\n" + json.dumps(filenames, ensure_ascii=False)
    return system, user


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
    system = load_skill("clinical-columns")
    user = (
        "表格信息：\n"
        f"- 行数: {context['n_rows']}\n"
        f"- 列数: {context['n_columns']}\n"
        f"- 任务描述: {context['task_hint']}\n\n"
        "列详情：\n"
        f"{_format_columns(context['columns'])}"
    )
    return system, user


def build_thread_title_prompt(content: str) -> Tuple[str, str]:
    """构造会话标题生成 prompt；消息截断到 500 字避免浪费 token。"""
    system = load_skill("thread-title")
    return system, f"用户消息：\n{content[:500]}"


class LLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url
        self.model = DEEPSEEK_MODEL
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

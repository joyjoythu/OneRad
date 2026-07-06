# Report Agent 实现方案文档

> **职责：** 接收 Analysis Agent 输出的统计结果及原始数据信息，生成符合学术规范的 Word 报告（.docx）。含方法学、特征筛选结果表、回归系数表、AUC/C-index 等。三个 LLM 调用点之一（报告润色）。
> **负责人：** 同学 B（负责 `clinical.py` / `feature.py` / `analysis.py` / `report.py`）
> **技术栈：** python-docx, pandas, DeepSeek V4 API（OpenAI 兼容格式）

---

## 一、职责与在流水线中的位置

```
Discovery -> Clinical -> Matching -> QC -> Feature -> Merge -> Analysis -> [Report]
```

- **上游：** `Analysis Agent`（`analysis.py`）输出统计结果字典；`Orchestrator`（`orchestrator.py`）将原始数据信息（模态、样本量、特征数等）一并注入 `state`。
- **下游：** 无直接下游 Agent，输出文件路径返回给 Orchestrator，最终由 `ui.py`（Gradio 前端）提供下载链接。

---

## 二、输入输出数据结构（接口契约）

### 2.1 输入（来自 `state` 字典）

Report Agent 从 Orchestrator 的 `state` 字典中读取以下字段：

| 字段名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| `analysis_result` | `dict` | Analysis Agent | 统计结果，见下方定义 |
| `modality` | `str` | Feature Agent | `"CT"` 或 `"MRI"` |
| `n_samples` | `int` | Clinical Agent | 最终分析样本量 |
| `n_features` | `int` | Feature Agent | 提取的影像组学特征数 |
| `n_lasso_selected` | `int` | Analysis Agent | LASSO 筛选后保留特征数 |
| `task_type` | `str` | Analysis Agent | `"binary"`（二分类）或 `"survival"`（生存分析） |
| `covariates` | `list[str]` | Analysis Agent | 纳入回归的协变量列名（如 `Age`, `Sex`） |
| `image_mask_pairs` | `list[dict]` | Discovery / QC | 配对列表，用于报告描述 |
| `output_dir` | `str` | Orchestrator / UI | 报告保存目录（默认 `"./output"`） |
| `report_filename` | `str` | UI 或默认 | 输出文件名，默认 `"AutoRadiomics_Report.docx"` |
| `llm_api_key` | `str` | Orchestrator | DeepSeek API Key |
| `llm_base_url` | `str` | Orchestrator | 默认 `"https://api.deepseek.com/v1"` |
| `llm_model` | `str` | Orchestrator | 默认 `"deepseek-v4"` |

### 2.2 `analysis_result` 字典详细定义

```python
analysis_result: dict = {
    # 任务类型（二分类）
    "task_type": "binary",  # 或 "survival"
    
    # LASSO 筛选阶段
    "lasso": {
        "alpha": float,          # 最优 alpha（C-index/AUC 交叉验证）
        "n_selected": int,       # 保留特征数
        "selected_features": list[str],  # 保留特征名列表
        "coefs": dict[str, float],      # LASSO 系数（含截距）
    },
    
    # 二分类：Logistic Regression
    "logistic_regression": {
        "coefs": dict[str, tuple[float, float]],  # {feature: (OR, 95%CI_lower, 95%CI_upper)}
        # 注意：coefs 存储 OR 及 95% CI 上下界
        "p_values": dict[str, float],              # 各特征 p 值
        "intercept": float,                        # 截距（logit 尺度）
        "auc": float,                              # AUC（Test / Cross-validated）
        "auc_ci": tuple[float, float],             # AUC 95% CI
        "metrics": {                               # 可选：分类报告指标
            "accuracy": float,
            "sensitivity": float,
            "specificity": float,
        }
    },
    
    # 生存分析：Cox Proportional Hazards
    "coxph": {
        "coefs": dict[str, tuple[float, float, float]],  # {feature: (HR, 95%CI_lower, 95%CI_upper)}
        "p_values": dict[str, float],
        "c_index": float,          # C-index（Concordance）
        "c_index_ci": tuple[float, float],  # C-index 95% CI
        "log_likelihood": float,   # 对数似然
        "aic": float,              # AIC
    },
    
    # 共享统计量
    "warnings": list[str],  # 分析过程警告（如 "VIF > 10"）
}
```

### 2.3 输出

```python
{
    "report_path": str,          # 绝对或相对路径，如 "./output/AutoRadiomics_Report.docx"
    "report_generated": bool,    # True / False
    "error": str | None,         # 失败时错误信息
    "sections_generated": list[str],  # 生成的章节列表（用于日志 / SSE）
}
```

---

## 三、核心模块与函数签名

文件位置：`app/report.py`

```python
"""
report.py — Report Agent
生成 AutoRadiomics 的学术 Word 报告。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

import pandas as pd
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.enum.table import WD_TABLE_ALIGNMENT

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

DEFAULT_FONT_NAME = "Times New Roman"     # 英文正文
DEFAULT_FONT_NAME_CN = "SimSun"          # 中文正文（宋体）
HEADING_FONT_NAME = "Arial"
HEADING_FONT_NAME_CN = "SimHei"            # 黑体

FONT_SIZE_BODY = Pt(10.5)                # 五号字
FONT_SIZE_TITLE = Pt(18)                 # 小二号
FONT_SIZE_HEADING1 = Pt(14)              # 四号
FONT_SIZE_HEADING2 = Pt(12)              # 小四
FONT_SIZE_CAPTION = Pt(9)                # 小五号

LINE_SPACING_BODY = 1.5

# ---------------------------------------------------------------------------
# 数据类：报告元信息（由上游 state 注入）
# ---------------------------------------------------------------------------

@dataclass
class ReportMeta:
    """报告所需的元信息，从 Orchestrator state 提取。"""
    modality: str                # "CT" or "MRI"
    n_samples: int
    n_features: int
    n_lasso_selected: int
    task_type: str               # "binary" or "survival"
    covariates: List[str]
    image_mask_pairs: List[Dict[str, str]]  # 仅用于统计配对数
    output_dir: str = "./output"
    report_filename: str = "AutoRadiomics_Report.docx"

    @property
    def n_pairs(self) -> int:
        return len(self.image_mask_pairs)


# ---------------------------------------------------------------------------
# 主函数：Report Agent 入口
# ---------------------------------------------------------------------------

def generate_report(
    analysis_result: Dict[str, Any],
    meta: ReportMeta,
    llm_config: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """
    Report Agent 主入口。

    Parameters
    ----------
    analysis_result : dict
        Analysis Agent 输出的统计结果（见 2.2 定义）。
    meta : ReportMeta
        报告元信息（模态、样本量等）。
    llm_config : dict | None
        LLM 配置，如 {"api_key": "...", "base_url": "...", "model": "deepseek-v4"}。
        为 None 时不润色，使用模板化方法学描述。

    Returns
    -------
    dict
        {"report_path": str, "report_generated": bool, "error": str|None, "sections_generated": list}
    """


def _build_report_sections(
    analysis_result: Dict[str, Any],
    meta: ReportMeta,
    llm_config: Dict[str, str] | None,
) -> Dict[str, str]:
    """
    构建各章节文本内容（纯文本，不含 Word 格式）。

    Returns
    -------
    dict
        {"title": ..., "methodology": ..., "feature_selection": ..., 
         "regression_results": ..., "model_performance": ..., "conclusion": ...}
    """


def _call_llm_for_methodology(
    raw_text: str,
    llm_config: Dict[str, str],
) -> str:
    """
    调用 DeepSeek V4 润色方法学描述。

    Parameters
    ----------
    raw_text : str
        模板化生成的原始方法学文本。
    llm_config : dict
        {"api_key": ..., "base_url": ..., "model": ...}

    Returns
    -------
    str
        润色后的学术化描述。失败时返回原 raw_text。
    """


# ---------------------------------------------------------------------------
# Word 生成器：python-docx 操作
# ---------------------------------------------------------------------------

class WordReportBuilder:
    """封装 python-docx 操作，生成统一格式的学术报告。"""

    def __init__(self, meta: ReportMeta):
        self.doc = Document()
        self.meta = meta
        self._set_default_styles()

    def _set_default_styles(self) -> None:
        """设置全局默认字体、段落样式。"""

    def add_title(self, text: str) -> None:
        """添加报告标题。"""

    def add_heading1(self, text: str) -> None:
        """一级标题（如 1. Methodology）。"""

    def add_heading2(self, text: str) -> None:
        """二级标题（如 1.1 Image Acquisition）。"""

    def add_paragraph(self, text: str, bold_parts: List[Tuple[int, int]] | None = None) -> None:
        """
        添加正文段落。
        bold_parts: [(start, end), ...] 指定 text 中需要加粗的子串区间。
        """

    def add_table(self, df: pd.DataFrame, caption: str | None = None) -> None:
        """
        将 DataFrame 写入 Word 表格，可选表题。
        表头加粗，数据行右对齐，自动列宽。
        """

    def add_caption(self, text: str) -> None:
        """添加表题 / 图题，小五号，居中。"""

    def save(self, path: str) -> str:
        """保存文档，返回绝对路径。"""


def _generate_methodology_text(meta: ReportMeta, analysis_result: Dict[str, Any]) -> str:
    """生成模板化的原始方法学文本（未润色）。"""


def _generate_feature_selection_table(analysis_result: Dict[str, Any]) -> pd.DataFrame:
    """生成 LASSO 特征筛选结果表（DataFrame）。"""


def _generate_regression_table(analysis_result: Dict[str, Any]) -> pd.DataFrame:
    """生成 Logistic Regression / CoxPH 回归系数表（DataFrame）。"""


def _generate_performance_summary(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """提取模型性能摘要（AUC / C-index 等）供正文段落使用。"""
```

---

## 四、核心逻辑实现（可直接照抄）

### 4.1 `generate_report` — 主入口

```python
def generate_report(
    analysis_result: Dict[str, Any],
    meta: ReportMeta,
    llm_config: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    result = {
        "report_path": None,
        "report_generated": False,
        "error": None,
        "sections_generated": [],
    }

    try:
        # 1. 参数校验（见第六节）
        _validate_inputs(analysis_result, meta)

        # 2. 构建文本内容
        sections = _build_report_sections(analysis_result, meta, llm_config)

        # 3. 生成 Word
        builder = WordReportBuilder(meta)
        builder.add_title(f"Radiomics Analysis Report ({meta.task_type.title()})")

        # 3.1 Methodology
        builder.add_heading1("1. Methodology")
        builder.add_paragraph(sections["methodology"])
        result["sections_generated"].append("methodology")

        # 3.2 Feature Selection
        builder.add_heading1("2. Feature Selection (LASSO)")
        feat_df = _generate_feature_selection_table(analysis_result)
        builder.add_table(feat_df, caption="Table 1. LASSO-selected radiomics features.")
        result["sections_generated"].append("feature_selection")

        # 3.3 Regression Results
        builder.add_heading1("3. Regression Results")
        if meta.task_type == "binary":
            reg_df = _generate_regression_table_binary(analysis_result)
            builder.add_table(reg_df, caption="Table 2. Logistic regression coefficients (OR, 95% CI, p-value).")
        else:
            reg_df = _generate_regression_table_survival(analysis_result)
            builder.add_table(reg_df, caption="Table 2. CoxPH regression coefficients (HR, 95% CI, p-value).")
        result["sections_generated"].append("regression_results")

        # 3.4 Model Performance
        builder.add_heading1("4. Model Performance")
        perf = _generate_performance_summary(analysis_result)
        if meta.task_type == "binary":
            perf_text = (
                f"The logistic regression model achieved an AUC of {perf['auc']:.3f} "
                f"(95% CI: {perf['auc_ci'][0]:.3f}–{perf['auc_ci'][1]:.3f}). "
                f"Accuracy = {perf.get('accuracy', 'N/A')}, "
                f"Sensitivity = {perf.get('sensitivity', 'N/A')}, "
                f"Specificity = {perf.get('specificity', 'N/A')}."
            )
        else:
            perf_text = (
                f"The CoxPH model achieved a concordance index (C-index) of {perf['c_index']:.3f} "
                f"(95% CI: {perf['c_index_ci'][0]:.3f}–{perf['c_index_ci'][1]:.3f})."
            )
        builder.add_paragraph(perf_text)
        result["sections_generated"].append("model_performance")

        # 3.5 Conclusion
        builder.add_heading1("5. Conclusion")
        builder.add_paragraph(sections["conclusion"])
        result["sections_generated"].append("conclusion")

        # 4. 保存
        os.makedirs(meta.output_dir, exist_ok=True)
        output_path = os.path.join(meta.output_dir, meta.report_filename)
        abs_path = builder.save(output_path)
        result["report_path"] = abs_path
        result["report_generated"] = True

    except ReportAgentError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = f"Unexpected error in Report Agent: {type(e).__name__}: {e}"

    return result
```

### 4.2 `_build_report_sections` — 构建文本

```python
def _build_report_sections(
    analysis_result: Dict[str, Any],
    meta: ReportMeta,
    llm_config: Dict[str, str] | None,
) -> Dict[str, str]:
    """各章节文本由模板生成，methodology 可选 LLM 润色。"""
    
    # 1. 模板化原始方法学
    raw_methodology = _generate_methodology_text(meta, analysis_result)
    
    # 2. LLM 润色（如果配置可用）
    if llm_config and llm_config.get("api_key"):
        methodology = _call_llm_for_methodology(raw_methodology, llm_config)
    else:
        methodology = raw_methodology
    
    # 3. 结论（模板化，暂不调 LLM，避免过度生成）
    n_selected = meta.n_lasso_selected
    if meta.task_type == "binary":
        auc = analysis_result["logistic_regression"]["auc"]
        conclusion = (
            f"In this study, a total of {meta.n_samples} patients were included, "
            f"and {meta.n_features} radiomics features were extracted from {meta.modality} images. "
            f"LASSO regression reduced the feature space to {n_selected} non-zero features, "
            f"which were subsequently entered into a logistic regression model. "
            f"The model demonstrated an AUC of {auc:.3f}, indicating "
            f"{'good' if auc > 0.8 else 'moderate' if auc > 0.7 else 'poor'} discriminative performance."
        )
    else:
        c_index = analysis_result["coxph"]["c_index"]
        conclusion = (
            f"In this study, {meta.n_samples} patients with survival data were analyzed. "
            f"After extracting {meta.n_features} radiomics features from {meta.modality} images, "
            f"LASSO selected {n_selected} features for Cox proportional hazards regression. "
            f"The model achieved a C-index of {c_index:.3f}, suggesting "
            f"{'good' if c_index > 0.7 else 'moderate' if c_index > 0.6 else 'poor'} predictive accuracy."
        )
    
    return {
        "title": f"Radiomics Analysis Report ({meta.task_type.title()})",
        "methodology": methodology,
        "conclusion": conclusion,
    }
```

### 4.3 `_call_llm_for_methodology` — LLM 润色（DeepSeek V4）

```python
import openai

def _call_llm_for_methodology(
    raw_text: str,
    llm_config: Dict[str, str],
) -> str:
    """调用 DeepSeek V4 润色方法学，失败时降级返回原文。"""
    try:
        client = openai.OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config.get("base_url", "https://api.deepseek.com/v1"),
        )
        
        response = client.chat.completions.create(
            model=llm_config.get("model", "deepseek-v4"),
            messages=[
                {"role": "system", "content": LLM_SYSTEM_PROMPT_METHODLOGY},
                {"role": "user", "content": raw_text},
            ],
            temperature=0.3,   # 低 temperature，保证学术严谨性
            max_tokens=1500,
        )
        
        polished = response.choices[0].message.content.strip()
        return polished if polished else raw_text
        
    except Exception as e:
        # 失败不抛异常，降级返回原始文本，保证报告生成不中断
        return raw_text
```

---

## 五、LLM Prompt 模板（报告润色）

### 5.1 System Prompt

```python
LLM_SYSTEM_PROMPT_METHODLOGY = """You are a senior medical imaging statistician and academic writing assistant. 
Your task is to polish a raw methodology paragraph into a concise, rigorous, and academically appropriate description for a radiomics research paper.

Rules:
1. Keep the structure: (a) Study population, (b) Image preprocessing, (c) Feature extraction, (d) Feature selection, (e) Statistical modeling.
2. Use formal academic English. Avoid colloquialisms.
3. Do NOT invent data not present in the raw text (e.g., do not change sample size, do not add scanner brand unless provided).
4. Preserve all numerical values exactly as given.
5. Length: 200–400 words. No bullet points; write continuous prose.
6. Output ONLY the polished paragraph, no extra commentary."""
```

### 5.2 User Prompt（由模板生成，即 `_generate_methodology_text` 的输出）

示例 raw_text（`_generate_methodology_text` 生成的模板）：

```
Study population: 191 patients. Modality: CT. 
Image preprocessing: images and masks were resampled to uniform spacing (1x1x1 mm) and aligned.
Feature extraction: 107 radiomics features were extracted using PyRadiomics (v3.1.0), including first-order statistics and texture features (GLCM, GLRLM, GLSZM, GLDM, NGTDM).
Feature selection: LASSO regression with 5-fold cross-validation was used to select the optimal alpha and reduce dimensionality, yielding 8 non-zero features.
Statistical modeling: multivariable logistic regression was fitted using the selected radiomics features and clinical covariates (Age, Sex), and the area under the ROC curve (AUC) was calculated.
```

润色后应变为：

```
A total of 191 patients were enrolled in this study. All CT images and corresponding segmentation masks were resampled to an isotropic voxel spacing of 1×1×1 mm and rigidly aligned to ensure spatial consistency. Radiomic feature extraction was performed using PyRadiomics (version 3.1.0), yielding 107 features encompassing first-order statistics and five categories of texture features (gray-level co-occurrence matrix, gray-level run-length matrix, gray-level size-zone matrix, gray-level dependence matrix, and neighboring gray-tone difference matrix). To mitigate the high-dimensional feature space and avoid overfitting, least absolute shrinkage and selection operator (LASSO) regression with five-fold cross-validation was employed to identify the optimal regularization strength (α) and select non-zero features, resulting in 8 retained radiomic variables. Subsequently, a multivariable logistic regression model was constructed incorporating the selected radiomic features and clinical covariates (age and sex), and discriminative performance was quantified by the area under the receiver operating characteristic curve (AUC).
```

---

## 六、异常处理逻辑（Report Agent 特有）

```python
class ReportAgentError(Exception):
    """Report Agent 自定义异常基类。"""
    pass

class MissingAnalysisResultError(ReportAgentError):
    """analysis_result 字典缺失关键字段。"""
    pass

class UnsupportedTaskTypeError(ReportAgentError):
    """task_type 既不是 'binary' 也不是 'survival'。"""
    pass

class EmptyFeatureSelectionError(ReportAgentError):
    """LASSO 未选中任何特征，导致表格为空。"""
    pass

class WordGenerationError(ReportAgentError):
    """python-docx 生成或保存失败。"""
    pass


def _validate_inputs(analysis_result: Dict[str, Any], meta: ReportMeta) -> None:
    """校验输入完整性，失败即抛异常，由 Orchestrator 捕获并中断。"""
    
    # 1. task_type 校验
    if meta.task_type not in ("binary", "survival"):
        raise UnsupportedTaskTypeError(
            f"Unsupported task_type: '{meta.task_type}'. Expected 'binary' or 'survival'."
        )
    
    # 2. analysis_result 结构校验
    required_top = {"task_type", "lasso"}
    if not required_top.issubset(analysis_result.keys()):
        missing = required_top - set(analysis_result.keys())
        raise MissingAnalysisResultError(f"analysis_result missing keys: {missing}")
    
    # 3. 分支校验
    if meta.task_type == "binary":
        if "logistic_regression" not in analysis_result:
            raise MissingAnalysisResultError("Missing 'logistic_regression' for binary task.")
        lr = analysis_result["logistic_regression"]
        for k in ("coefs", "p_values", "auc"):
            if k not in lr:
                raise MissingAnalysisResultError(f"Missing logistic_regression.{k}")
    else:
        if "coxph" not in analysis_result:
            raise MissingAnalysisResultError("Missing 'coxph' for survival task.")
        cox = analysis_result["coxph"]
        for k in ("coefs", "p_values", "c_index"):
            if k not in cox:
                raise MissingAnalysisResultError(f"Missing coxph.{k}")
    
    # 4. LASSO 特征空值检查
    lasso_selected = analysis_result.get("lasso", {}).get("selected_features", [])
    if len(lasso_selected) == 0:
        raise EmptyFeatureSelectionError(
            "LASSO selected 0 features. Cannot generate regression table."
        )
    
    # 5. 样本量检查（与 Analysis Agent 双重保险）
    if meta.n_samples < 30:
        raise ReportAgentError(
            f"Sample size {meta.n_samples} < 30. Report generation aborted due to insufficient statistical power."
        )
    
    # 6. 输出目录可写性检查（创建测试）
    try:
        os.makedirs(meta.output_dir, exist_ok=True)
        test_path = os.path.join(meta.output_dir, ".write_test")
        with open(test_path, "w") as f:
            f.write("test")
        os.remove(test_path)
    except OSError as e:
        raise WordGenerationError(f"Output directory not writable: {meta.output_dir}. {e}")
```

---

## 七、Word 生成器详细实现（`WordReportBuilder`）

```python
class WordReportBuilder:
    """基于 python-docx 的学术报告格式生成器。"""

    def __init__(self, meta: ReportMeta):
        self.doc = Document()
        self.meta = meta
        self._set_default_styles()

    # ------------------------------------------------------------------
    # 样式设置
    # ------------------------------------------------------------------
    def _set_default_styles(self) -> None:
        """设置正文默认字体、段落间距。"""
        style = self.doc.styles['Normal']
        font = style.font
        font.name = DEFAULT_FONT_NAME
        font.size = FONT_SIZE_BODY
        # 中文字体 fallback
        style.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
        
        paragraph_format = style.paragraph_format
        paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        paragraph_format.space_after = Pt(6)
        paragraph_format.space_before = Pt(0)

    # ------------------------------------------------------------------
    # 标题
    # ------------------------------------------------------------------
    def add_title(self, text: str) -> None:
        title = self.doc.add_heading(level=0)
        run = title.add_run(text)
        run.font.size = FONT_SIZE_TITLE
        run.font.bold = True
        run.font.name = HEADING_FONT_NAME
        run.element.rPr.rFonts.set(qn('w:eastAsia'), HEADING_FONT_NAME_CN)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.doc.add_paragraph()  # 空行

    # ------------------------------------------------------------------
    # 一级 / 二级标题
    # ------------------------------------------------------------------
    def add_heading1(self, text: str) -> None:
        p = self.doc.add_heading(level=1)
        run = p.add_run(text)
        run.font.size = FONT_SIZE_HEADING1
        run.font.bold = True
        run.font.name = HEADING_FONT_NAME
        run.element.rPr.rFonts.set(qn('w:eastAsia'), HEADING_FONT_NAME_CN)
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)

    def add_heading2(self, text: str) -> None:
        p = self.doc.add_heading(level=2)
        run = p.add_run(text)
        run.font.size = FONT_SIZE_HEADING2
        run.font.bold = True
        run.font.name = HEADING_FONT_NAME
        run.element.rPr.rFonts.set(qn('w:eastAsia'), HEADING_FONT_NAME_CN)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)

    # ------------------------------------------------------------------
    # 正文段落（支持局部加粗）
    # ------------------------------------------------------------------
    def add_paragraph(self, text: str, bold_parts: List[Tuple[int, int]] | None = None) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        p.paragraph_format.space_after = Pt(6)
        
        if not bold_parts:
            run = p.add_run(text)
            run.font.size = FONT_SIZE_BODY
            run.font.name = DEFAULT_FONT_NAME
            run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
            return
        
        # 分段加粗
        last = 0
        for start, end in sorted(bold_parts):
            if start > last:
                run = p.add_run(text[last:start])
                run.font.size = FONT_SIZE_BODY
                run.font.name = DEFAULT_FONT_NAME
                run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
            run_bold = p.add_run(text[start:end])
            run_bold.font.size = FONT_SIZE_BODY
            run_bold.font.bold = True
            run_bold.font.name = DEFAULT_FONT_NAME
            run_bold.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
            last = end
        if last < len(text):
            run = p.add_run(text[last:])
            run.font.size = FONT_SIZE_BODY
            run.font.name = DEFAULT_FONT_NAME
            run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)

    # ------------------------------------------------------------------
    # 表格生成（DataFrame -> Word Table）
    # ------------------------------------------------------------------
    def add_table(self, df: pd.DataFrame, caption: str | None = None) -> None:
        # 表题
        if caption:
            self.add_caption(caption)
        
        table = self.doc.add_table(rows=1, cols=len(df.columns))
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        
        # 表头
        hdr_cells = table.rows[0].cells
        for i, col_name in enumerate(df.columns):
            cell = hdr_cells[i]
            cell.text = str(col_name)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
                    run.font.size = FONT_SIZE_BODY
                    run.font.name = DEFAULT_FONT_NAME
                    run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # 数据行
        for _, row in df.iterrows():
            row_cells = table.add_row().cells
            for i, val in enumerate(row):
                cell = row_cells[i]
                cell.text = str(val)
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = FONT_SIZE_BODY
                        run.font.name = DEFAULT_FONT_NAME
                        run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
                    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT  # 数值右对齐
        
        self.doc.add_paragraph()  # 表后空行

    # ------------------------------------------------------------------
    # 表题
    # ------------------------------------------------------------------
    def add_caption(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.size = FONT_SIZE_CAPTION
        run.font.name = DEFAULT_FONT_NAME
        run.element.rPr.rFonts.set(qn('w:eastAsia'), DEFAULT_FONT_NAME_CN)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.space_before = Pt(6)

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------
    def save(self, path: str) -> str:
        abs_path = os.path.abspath(path)
        self.doc.save(abs_path)
        return abs_path
```

---

## 八、辅助函数：表格生成

### 8.1 LASSO 特征筛选表

```python
def _generate_feature_selection_table(analysis_result: Dict[str, Any]) -> pd.DataFrame:
    """
    生成 Table 1: LASSO 筛选后的特征列表。
    列：Feature Name | LASSO Coefficient
    """
    lasso = analysis_result["lasso"]
    selected = lasso.get("selected_features", [])
    coefs = lasso.get("coefs", {})
    
    rows = []
    for feat in selected:
        rows.append({
            "Feature Name": feat,
            "LASSO Coefficient": f"{coefs.get(feat, 0.0):.4f}",
        })
    
    return pd.DataFrame(rows)
```

### 8.2 二分类：Logistic Regression 系数表

```python
def _generate_regression_table_binary(analysis_result: Dict[str, Any]) -> pd.DataFrame:
    """
    生成 Table 2 (Binary): Logistic Regression 结果。
    列：Feature | OR | 95% CI Lower | 95% CI Upper | p-value
    """
    lr = analysis_result["logistic_regression"]
    coefs = lr["coefs"]      # {feature: (OR, ci_lower, ci_upper)}
    pvals = lr["p_values"]   # {feature: p_value}
    
    rows = []
    for feat, (or_val, ci_low, ci_high) in coefs.items():
        p_val = pvals.get(feat, 1.0)
        p_str = f"{p_val:.4f}" if p_val >= 0.001 else "<0.001"
        rows.append({
            "Feature": feat,
            "OR": f"{or_val:.3f}",
            "95% CI Lower": f"{ci_low:.3f}",
            "95% CI Upper": f"{ci_high:.3f}",
            "p-value": p_str,
        })
    
    return pd.DataFrame(rows)
```

### 8.3 生存分析：CoxPH 系数表

```python
def _generate_regression_table_survival(analysis_result: Dict[str, Any]) -> pd.DataFrame:
    """
    生成 Table 2 (Survival): CoxPH 结果。
    列：Feature | HR | 95% CI Lower | 95% CI Upper | p-value
    """
    cox = analysis_result["coxph"]
    coefs = cox["coefs"]      # {feature: (HR, ci_lower, ci_upper)}
    pvals = cox["p_values"]   # {feature: p_value}
    
    rows = []
    for feat, (hr_val, ci_low, ci_high) in coefs.items():
        p_val = pvals.get(feat, 1.0)
        p_str = f"{p_val:.4f}" if p_val >= 0.001 else "<0.001"
        rows.append({
            "Feature": feat,
            "HR": f"{hr_val:.3f}",
            "95% CI Lower": f"{ci_low:.3f}",
            "95% CI Upper": f"{ci_high:.3f}",
            "p-value": p_str,
        })
    
    return pd.DataFrame(rows)
```

### 8.4 性能摘要提取

```python
def _generate_performance_summary(analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """提取模型性能指标，供正文段落使用。"""
    result = {}
    task_type = analysis_result["task_type"]
    
    if task_type == "binary":
        lr = analysis_result["logistic_regression"]
        result["auc"] = lr.get("auc", 0.0)
        result["auc_ci"] = lr.get("auc_ci", (0.0, 0.0))
        result["accuracy"] = lr.get("metrics", {}).get("accuracy", "N/A")
        result["sensitivity"] = lr.get("metrics", {}).get("sensitivity", "N/A")
        result["specificity"] = lr.get("metrics", {}).get("specificity", "N/A")
    else:
        cox = analysis_result["coxph"]
        result["c_index"] = cox.get("c_index", 0.0)
        result["c_index_ci"] = cox.get("c_index_ci", (0.0, 0.0))
    
    return result
```

---

## 九、模板化方法学文本生成

```python
def _generate_methodology_text(meta: ReportMeta, analysis_result: Dict[str, Any]) -> str:
    """生成模板化的原始方法学文本（供 LLM 润色或直接使用）。"""
    
    task_type = meta.task_type
    n_samples = meta.n_samples
    modality = meta.modality
    n_features = meta.n_features
    n_selected = meta.n_lasso_selected
    covariates = meta.covariates
    cov_str = ", ".join(covariates) if covariates else "None"
    
    # 图像预处理描述
    preprocessing = (
        f"images and masks were resampled to uniform spacing and aligned. "
        f"All images were discretized with a fixed bin width (binWidth=25 for CT, "
        f"binCount=128 for MRI) prior to texture feature extraction."
    )
    
    # 特征提取描述
    extraction = (
        f"{n_features} radiomics features were extracted using PyRadiomics (v3.1.0), "
        f"including first-order statistics and texture features (GLCM, GLRLM, GLSZM, GLDM, NGTDM)."
    )
    
    # 特征选择描述
    lasso_alpha = analysis_result["lasso"].get("alpha", "optimized")
    selection = (
        f"LASSO regression with 5-fold cross-validation was used to select the optimal alpha "
        f"({lasso_alpha}), yielding {n_selected} non-zero features."
    )
    
    # 统计建模描述
    if task_type == "binary":
        modeling = (
            f"Multivariable logistic regression was fitted using the selected radiomics features "
            f"and clinical covariates ({cov_str}). The area under the ROC curve (AUC) was calculated."
        )
    else:
        modeling = (
            f"Cox proportional hazards regression was fitted using the selected radiomics features "
            f"and clinical covariates ({cov_str}). The concordance index (C-index) was calculated."
        )
    
    raw_text = (
        f"Study population: {n_samples} patients. Modality: {modality}.\n"
        f"Image preprocessing: {preprocessing}\n"
        f"Feature extraction: {extraction}\n"
        f"Feature selection: {selection}\n"
        f"Statistical modeling: {modeling}"
    )
    
    return raw_text
```

---

## 十、与 Orchestrator 的接口契约（代码级）

### 10.1 Orchestrator 调用方式

```python
# orchestrator.py 中调用 Report Agent 的示例

from app.report import generate_report, ReportMeta

# 1. 构造 ReportMeta
meta = ReportMeta(
    modality=state["modality"],                    # "CT" / "MRI"
    n_samples=state["n_samples"],                  # int
    n_features=state["n_features"],                # int
    n_lasso_selected=state["analysis_result"]["lasso"]["n_selected"],
    task_type=state["analysis_result"]["task_type"],  # "binary" / "survival"
    covariates=state.get("covariates", []),
    image_mask_pairs=state["image_mask_pairs"],
    output_dir=state.get("output_dir", "./output"),
    report_filename=state.get("report_filename", "AutoRadiomics_Report.docx"),
)

# 2. LLM 配置（可选）
llm_config = {
    "api_key": state.get("llm_api_key"),
    "base_url": state.get("llm_base_url", "https://api.deepseek.com/v1"),
    "model": state.get("llm_model", "deepseek-v4"),
} if state.get("llm_api_key") else None

# 3. 调用
report_output = generate_report(
    analysis_result=state["analysis_result"],
    meta=meta,
    llm_config=llm_config,
)

# 4. 处理结果
if not report_output["report_generated"]:
    # 失败 → Orchestrator 中断，等待用户选择"跳过"或"终止"
    raise StageError(f"Report Agent failed: {report_output['error']}")
else:
    state["report_path"] = report_output["report_path"]
    state["sections_generated"] = report_output["sections_generated"]
    # 推送 SSE 事件
    emit_event("report_generated", {"path": report_output["report_path"]})
```

### 10.2 接口数据流图

```
Orchestrator state (输入)
    │
    ├── analysis_result  ───────┐
    ├── modality               │
    ├── n_samples              ├──> generate_report(analysis_result, meta, llm_config)
    ├── n_features             │
    ├── covariates             │
    ├── image_mask_pairs       │
    ├── output_dir             │
    └── llm_api_key (可选)     │
                               │
                               ▼
                    Report Agent (report.py)
                               │
                               ├── 校验输入
                               ├── 构建模板化文本
                               ├── 调用 LLM 润色 (可选)
                               ├── 生成 Word (python-docx)
                               └── 保存文件
                               │
                               ▼
                    report_output 字典 (输出)
                        │
                        ├── report_path: str
                        ├── report_generated: bool
                        ├── error: str | None
                        └── sections_generated: list[str]
```

---

## 十一、降级策略（LLM 失败时）

| 场景 | 策略 | 说明 |
|------|------|------|
| LLM API Key 未配置 | 直接使用模板化文本 | 方法学段落不润色，依然可用 |
| LLM API 超时 / 429 | 捕获异常，返回 `raw_text` | 报告生成不中断 |
| LLM 返回空内容 | 回退到 `raw_text` | 避免插入空段落 |
| LLM 篡改数值 | 模板中已用 f-string 固定数值，LLM 只润色句式 | 数值在 Python 层固定，不受 LLM 影响 |

---

## 十二、依赖与安装

```
# requirements.txt 相关项
python-docx==1.1.2
pandas>=2.0.0
openai>=1.0.0       # 用于 DeepSeek API (OpenAI 兼容)
```

**注意：** `python-docx` 在 Windows 下可直接 `pip install python-docx`；字体显示依赖系统已安装 `SimSun`（宋体）和 `SimHei`（黑体），Docker 中需安装 `fonts-wqy-zenhei` 或 `fonts-noto-cjk`。

---

## 十三、文件结构

```
app/
├── report.py          # 本文件：Report Agent 全部逻辑
├── report_utils.py    # 可选：若表格生成逻辑复杂，可拆分
└── assets/
    └── report_template.docx   # 可选：若改用模板填充方式
```

> **铁律：** 本文件（`report.py`）只被 `orchestrator.py` 调用，不直接调用其他 Agent 的代码。所有数据通过 `analysis_result` 和 `meta` 注入。

---

## 十四、自检清单（交付前核对）

- [ ] 输入校验覆盖 `task_type` 非法、`analysis_result` 缺字段、LASSO 0 特征、样本量 < 30、输出目录不可写。
- [ ] 二分类和生存分析两条分支均生成正确的 Table 2（OR vs HR）。
- [ ] LLM 调用失败时自动降级，报告生成不中断。
- [ ] Word 报告包含：标题、方法学、LASSO 表、回归表、性能指标、结论。
- [ ] 表格格式统一：表头加粗居中，数值右对齐，p 值 `<0.001` 处理。
- [ ] 字体正确：英文 Times New Roman，中文宋体（正文）/ 黑体（标题）。
- [ ] 日志 / SSE 事件推送 `sections_generated` 列表。

---

*文档版本: v1.0 | 编写日期: 2025-06-18 | 负责模块: `app/report.py`*

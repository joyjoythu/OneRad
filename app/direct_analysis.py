"""Direct analysis entry point for pre-extracted radiomic features.

This module bypasses the full Orchestrator pipeline (discovery, QC, feature
extraction) and runs LASSO + logistic regression directly from a feature
matrix and a clinical table.
"""

import logging
from typing import List, Optional

from app.utils import (
    _load_feature_csv,
    _load_clinical_for_analysis,
    _merge_feature_clinical,
    _infer_covariates,
)

logger = logging.getLogger(__name__)


def run_direct_analysis(
    feature_csv: str,
    clinical: str,
    output_dir: str,
    label_col: Optional[str] = None,
    modality: str = "auto",
    covariates: Optional[List[str]] = None,
    max_lasso_features: int = 100,
    n_splits: int = 5,
    api_key: Optional[str] = None,
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-chat",
) -> str:
    """Run LASSO + logistic regression from pre-extracted feature and clinical CSVs.

    Args:
        feature_csv: Path to the pre-extracted radiomic feature CSV.
        clinical: Path to the clinical CSV/Excel table.
        output_dir: Directory for outputs (plots and report).
        label_col: Optional explicit label column name.
        modality: Imaging modality reported in the Word document.
        covariates: List of clinical covariate column names to retain.
        max_lasso_features: Maximum radiomic features fed into LASSO.
        n_splits: Number of cross-validation folds.
        api_key: Optional DeepSeek API key for report polishing.
        base_url: DeepSeek API base URL.
        model: DeepSeek model name.

    Returns:
        Path to the generated Word report.

    Raises:
        RuntimeError: If analysis or report generation fails.
    """
    from app.analysis import AnalysisAgent
    from app.report import ReportAgent

    feature_df = _load_feature_csv(feature_csv)
    clinical_df, id_col, detected_label_col = _load_clinical_for_analysis(
        clinical, label_col=label_col
    )
    merged_df = _merge_feature_clinical(feature_df, clinical_df, id_col=id_col)

    covariates = _infer_covariates(
        clinical_df, id_col, detected_label_col, covariates or []
    )

    n_features = len([c for c in feature_df.columns if c != id_col])

    agent = AnalysisAgent(
        covariates=covariates,
        max_lasso_features=max_lasso_features,
        n_splits=n_splits,
        output_dir=output_dir,
    )
    analysis_result = agent.run(merged_df, label_col=detected_label_col)
    if not analysis_result.get("success"):
        raise RuntimeError(f"分析失败: {analysis_result.get('message', '未知错误')}")

    llm_client = None
    if api_key:
        try:
            from app.llm import LLMClient
            llm_client = LLMClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        except Exception:
            logger.warning("LLM client 初始化失败，报告将不经过 AI 润色", exc_info=True)

    report_agent = ReportAgent()
    report_result = report_agent.run(
        analysis_result=analysis_result,
        output_dir=output_dir,
        modality=modality,
        n_features=n_features,
        covariates=covariates,
        plot_paths=analysis_result.get("plot_paths", []),
        llm_client=llm_client,
    )
    if not report_result.get("success"):
        raise RuntimeError(f"报告生成失败: {report_result.get('message', '未知错误')}")

    return report_result["report_path"]

import os
from typing import Dict, Any, List, Optional

import pandas as pd
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

import logging
logger = logging.getLogger(__name__)


class ReportAgent:
    """Generate a Word report from a radiomics analysis result."""

    def run(self, analysis_result: Dict[str, Any], output_dir: str,
            modality: str, n_features: int, covariates: List[str],
            plot_paths: Optional[List[str]] = None,
            llm_client=None) -> Dict[str, Any]:
        """Build and save the DOCX report.

        Parameters
        ----------
        analysis_result: dict
            Output from the analysis agent. Must contain ``success=True`` and
            the required fields ``n_samples``, ``selected_features``,
            ``model_results`` (with ``coefficients``, ``odds_ratios``,
            ``ci_lower``, ``ci_upper``, ``p_values``) and ``metrics`` (with
            ``auc``, ``auc_ci``, ``accuracy``, ``sensitivity``,
            ``specificity``).
        output_dir: str
            Directory where the report will be saved.
        modality: str
            Imaging modality (e.g. ``"CT"``).
        n_features: int
            Total number of radiomic features extracted.
        covariates: list[str]
            Clinical covariates included in the logistic regression.
        plot_paths: list[str] | None
            Optional paths to figures to embed. Non-existent paths are skipped
            and reported in the returned ``skipped_plots`` list.
        llm_client: object | None
            Optional client with a ``call(system, prompt, ...)`` method used to
            polish the methodology paragraph.

        Returns
        -------
        dict
            ``{"success": bool, "message": str, "report_path": str,
            "skipped_plots": list[str]}``.
        """
        if analysis_result.get("success") is not True:
            return {
                "success": False,
                "message": f"上游分析失败: {analysis_result.get('message', '未知错误')}",
            }

        missing = []
        for key in ("n_samples", "selected_features", "model_results", "metrics"):
            if key not in analysis_result:
                missing.append(key)
        if "model_results" in analysis_result:
            for key in ("coefficients", "odds_ratios", "ci_lower", "ci_upper", "p_values"):
                if key not in analysis_result["model_results"]:
                    missing.append(f"model_results.{key}")
        if "metrics" in analysis_result:
            for key in ("auc", "auc_ci", "accuracy", "sensitivity", "specificity"):
                if key not in analysis_result["metrics"]:
                    missing.append(f"metrics.{key}")
        if missing:
            return {
                "success": False,
                "message": f"analysis_result 缺少字段: {', '.join(missing)}",
            }

        plot_paths = plot_paths or []

        try:
            os.makedirs(output_dir, exist_ok=True)
            doc = Document()
            skipped_plots: List[str] = []

            # Title
            title = doc.add_heading(level=0)
            run = title.add_run("Radiomics Analysis Report")
            run.font.size = Pt(18)
            run.bold = True
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Methodology
            doc.add_heading("1. Methodology", level=1)
            methodology = self._build_methodology(
                analysis_result["n_samples"], modality, n_features,
                len(analysis_result["selected_features"]), covariates,
                analysis_result["metrics"]["auc"]
            )
            if llm_client:
                methodology = self._polish_methodology(methodology, llm_client)
            doc.add_paragraph(methodology)

            # Feature Selection Table
            doc.add_heading("2. Feature Selection", level=1)
            feat_df = pd.DataFrame({
                "Feature Name": analysis_result["selected_features"],
                "Coefficient": [analysis_result["model_results"]["coefficients"].get(f, 0) for f in analysis_result["selected_features"]],
            })
            self._add_table(doc, feat_df)

            # Regression Table
            doc.add_heading("3. Regression Results", level=1)
            rows = []
            for feat in analysis_result["selected_features"]:
                rows.append({
                    "Feature": feat,
                    "OR": f"{analysis_result['model_results']['odds_ratios'].get(feat, 0):.3f}",
                    "95% CI Lower": f"{analysis_result['model_results']['ci_lower'].get(feat, 0):.3f}" if analysis_result['model_results']['ci_lower'].get(feat) is not None else "-",
                    "95% CI Upper": f"{analysis_result['model_results']['ci_upper'].get(feat, 0):.3f}" if analysis_result['model_results']['ci_upper'].get(feat) is not None else "-",
                    "p-value": f"{analysis_result['model_results']['p_values'].get(feat, 1):.4f}",
                })
            self._add_table(doc, pd.DataFrame(rows))

            # Performance
            doc.add_heading("4. Model Performance", level=1)
            m = analysis_result["metrics"]
            perf_text = (
                f"The logistic regression model achieved an AUC of {m['auc']:.3f} "
                f"(95% CI: {m['auc_ci'][0]:.3f}–{m['auc_ci'][1]:.3f}). "
                f"Accuracy = {m['accuracy']:.3f}, Sensitivity = {m['sensitivity']:.3f}, "
                f"Specificity = {m['specificity']:.3f}."
            )
            doc.add_paragraph(perf_text)

            # Visualizations
            if plot_paths:
                doc.add_heading("5. Visualizations", level=1)
                for plot_path in plot_paths:
                    if os.path.exists(plot_path):
                        doc.add_picture(plot_path, width=Inches(5.5))
                    else:
                        skipped_plots.append(plot_path)

            # Save
            report_path = os.path.join(output_dir, "AutoRadiomics_Report.docx")
            doc.save(report_path)
            return {
                "success": True,
                "message": "报告生成完成",
                "report_path": report_path,
                "skipped_plots": skipped_plots,
            }
        except Exception as e:
            return {"success": False, "message": f"报告生成失败: {e}"}

    def _build_methodology(
        self,
        n_samples: int,
        modality: str,
        n_features: int,
        n_selected: int,
        covariates: List[str],
        auc: float,
    ) -> str:
        """Compose the methodology paragraph for the report.

        Parameters
        ----------
        n_samples: int
            Number of patients included.
        modality: str
            Imaging modality.
        n_features: int
            Total number of extracted radiomic features.
        n_selected: int
            Number of features selected by LASSO.
        covariates: list[str]
            Clinical covariates; omitted from the text when empty.
        auc: float
            Model AUC value.

        Returns
        -------
        str
            Methodology paragraph.
        """
        cov_str = ", ".join(covariates)
        cov_clause = (
            f" with covariates: {cov_str}" if covariates else ""
        )
        return (
            f"A total of {n_samples} patients were included. "
            f"Radiomic features were extracted from {modality} images using PyRadiomics, "
            f"yielding {n_features} features. LASSO regression selected {n_selected} features, "
            f"which were entered into a logistic regression model{cov_clause}. "
            f"The model achieved an AUC of {auc:.3f}."
        )

    def _polish_methodology(self, raw: str, llm_client) -> str:
        """Polish the methodology paragraph using an optional LLM client.

        Parameters
        ----------
        raw: str
            Original methodology text.
        llm_client: object
            Client exposing a ``call(system, prompt, ...)`` method.

        Returns
        -------
        str
            Polished text, or ``raw`` if the call fails or returns an empty
            response.
        """
        try:
            system = "You are an academic writing assistant. Polish the methodology paragraph. Keep all numbers exact. Output only the polished paragraph."
            polished = llm_client.call(system, raw, temperature=0.3, max_tokens=800)
            return polished or raw
        except Exception:
            return raw

    def _add_table(self, doc, df: pd.DataFrame):
        """Append a pandas DataFrame as a styled Word table.

        Parameters
        ----------
        doc: docx.Document
            Document to append the table to.
        df: pandas.DataFrame
            Data to render. Column names become the table header.
        """
        table = doc.add_table(rows=1, cols=len(df.columns))
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        for i, col in enumerate(df.columns):
            hdr[i].text = str(col)
        for _, row in df.iterrows():
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = str(val)

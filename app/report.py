import os
from typing import Dict, Any, List, Optional
from datetime import datetime

import pandas as pd
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


class ReportAgent:
    def run(self, analysis_result: Dict[str, Any], output_dir: str,
            modality: str, n_features: int, covariates: List[str],
            plot_paths: Optional[List[str]] = None,
            llm_client=None) -> Dict[str, Any]:
        try:
            self.plot_paths = plot_paths or []
            os.makedirs(output_dir, exist_ok=True)
            doc = Document()

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
            if self.plot_paths:
                doc.add_heading("5. Visualizations", level=1)
                for plot_path in self.plot_paths:
                    if os.path.exists(plot_path):
                        doc.add_picture(plot_path, width=Inches(5.5))

            # Save
            report_path = os.path.join(output_dir, "AutoRadiomics_Report.docx")
            doc.save(report_path)
            return {
                "success": True,
                "message": "报告生成完成",
                "report_path": report_path,
            }
        except Exception as e:
            return {"success": False, "message": f"报告生成失败: {e}"}

    def _build_methodology(self, n_samples, modality, n_features, n_selected, covariates, auc) -> str:
        cov_str = ", ".join(covariates) if covariates else "None"
        return (
            f"A total of {n_samples} patients were included. "
            f"Radiomic features were extracted from {modality} images using PyRadiomics, "
            f"yielding {n_features} features. LASSO regression selected {n_selected} features, "
            f"which were entered into a logistic regression model with covariates ({cov_str}). "
            f"The model achieved an AUC of {auc:.3f}."
        )

    def _polish_methodology(self, raw: str, llm_client) -> str:
        try:
            system = "You are an academic writing assistant. Polish the methodology paragraph. Keep all numbers exact. Output only the polished paragraph."
            polished = llm_client.call(system, raw, temperature=0.3, max_tokens=800)
            return polished or raw
        except Exception:
            return raw

    def _add_table(self, doc, df: pd.DataFrame):
        table = doc.add_table(rows=1, cols=len(df.columns))
        table.style = 'Table Grid'
        hdr = table.rows[0].cells
        for i, col in enumerate(df.columns):
            hdr[i].text = str(col)
        for _, row in df.iterrows():
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = str(val)

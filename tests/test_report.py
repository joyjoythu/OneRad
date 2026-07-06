from pathlib import Path
from app.report import ReportAgent


def test_report_generation(tmp_path):
    analysis_result = {
        "success": True,
        "task_type": "binary_classification",
        "selected_features": ["original_firstorder_Mean"],
        "model_results": {
            "intercept": 0.0,
            "coefficients": {"original_firstorder_Mean": 0.5},
            "odds_ratios": {"original_firstorder_Mean": 1.65},
            "ci_lower": {"original_firstorder_Mean": 1.0},
            "ci_upper": {"original_firstorder_Mean": 2.5},
            "p_values": {"original_firstorder_Mean": 0.01},
        },
        "metrics": {
            "auc": 0.85,
            "auc_ci": [0.78, 0.91],
            "accuracy": 0.80,
            "sensitivity": 0.82,
            "specificity": 0.78,
            "threshold": 0.5,
            "confusion_matrix": [[40, 10], [8, 42]],
        },
        "n_samples": 100,
    }
    agent = ReportAgent()
    result = agent.run(
        analysis_result=analysis_result,
        output_dir=str(tmp_path),
        modality="CT",
        n_features=107,
        covariates=[],
    )
    assert result["success"] is True
    assert Path(result["report_path"]).exists()

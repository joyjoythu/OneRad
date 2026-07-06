import pandas as pd
import numpy as np
from app.analysis import AnalysisAgent


def test_analysis_agent_basic():
    np.random.seed(42)
    n = 50
    df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": np.random.randint(0, 2, n),
    })
    for i in range(10):
        df[f"original_feature_{i}"] = np.random.randn(n)

    agent = AnalysisAgent(covariates=[])
    result = agent.run(df, label_col="Label")
    assert result["success"] is True
    assert "auc" in result["metrics"]
    assert "odds_ratios" in result["model_results"]

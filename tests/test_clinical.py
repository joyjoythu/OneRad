import pandas as pd
from app.clinical import ClinicalAgent


def test_clinical_agent_basic():
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Sex": ["F", "M"],
        "Label": [0, 1],
    })
    from io import BytesIO
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    # 使用 mock LLM
    from unittest.mock import MagicMock
    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}'
    mock_llm._extract_json.return_value = {"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}

    agent = ClinicalAgent(llm_client=mock_llm)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        path = f.name
    result = agent.run(path)
    os.unlink(path)

    assert result["success"] is True
    assert result["id_col"] == "PatientID"
    assert result["label_col"] == "Label"

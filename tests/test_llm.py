from unittest.mock import patch, MagicMock
from app.llm import LLMClient


def test_parse_json_response():
    client = LLMClient(api_key="fake")
    text = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age"]}'
    result = client._extract_json(text)
    assert result["id_col"] == "PatientID"

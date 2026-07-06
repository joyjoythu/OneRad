from app.llm import LLMClient


def test_extract_json_direct():
    client = LLMClient(api_key="fake")
    text = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age"]}'
    result = client._extract_json(text)
    assert result["id_col"] == "PatientID"


def test_extract_json_markdown_fenced():
    client = LLMClient(api_key="fake")
    text = '```json\n{"id_col": "PatientID", "label_col": "Label"}\n```'
    result = client._extract_json(text)
    assert result == {"id_col": "PatientID", "label_col": "Label"}


def test_extract_json_embedded_in_text():
    client = LLMClient(api_key="fake")
    text = 'Here is the config you requested: {"id_col": "PatientID", "label_col": "Label"}. Let me know if you need more.'
    result = client._extract_json(text)
    assert result == {"id_col": "PatientID", "label_col": "Label"}


def test_extract_json_invalid_or_empty_returns_none():
    client = LLMClient(api_key="fake")
    assert client._extract_json("") is None
    assert client._extract_json("   ") is None
    assert client._extract_json("not json at all") is None
    assert client._extract_json("{broken json") is None


def test_extract_json_top_level_array():
    client = LLMClient(api_key="fake")
    text = '["a", "b"]'
    result = client._extract_json(text)
    assert result == ["a", "b"]


def test_render_prompt_with_variables():
    client = LLMClient(api_key="fake")
    template = "Summarize the {domain} data for {patient_id}."
    result = client.render_prompt(template, domain="radiology", patient_id="P001")
    assert result == "Summarize the radiology data for P001."

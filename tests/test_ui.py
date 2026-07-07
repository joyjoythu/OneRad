from unittest.mock import MagicMock, patch

from app.ui import _run_analysis


def test_run_analysis_empty_paths():
    logs, report = _run_analysis("", "./clinical.csv", "./out", "auto", "", "", "deepseek-chat")
    assert "不能为空" in logs
    assert report is None


def test_run_analysis_success():
    mock_orch = MagicMock()
    mock_orch.state = {"report": {"success": True, "report_path": "/tmp/report.docx"}}
    mock_orch.run.return_value = []

    with patch("app.ui.Orchestrator", return_value=mock_orch), patch("app.ui.register_default_handlers") as mock_reg:
        logs, report = _run_analysis("./img", "./clinical.csv", "./out", "auto", "", "", "deepseek-chat")
        assert report == "/tmp/report.docx"
        assert isinstance(logs, str)
        mock_reg.assert_called_once_with(mock_orch)


def test_run_analysis_exception():
    mock_orch = MagicMock()
    mock_orch.run.side_effect = RuntimeError("boom")

    with patch("app.ui.Orchestrator", return_value=mock_orch), patch("app.ui.register_default_handlers"):
        logs, report = _run_analysis("./img", "./clinical.csv", "./out", "auto", "", "", "deepseek-chat")
        assert report is None
        assert "RuntimeError" in logs

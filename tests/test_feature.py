import pytest
import SimpleITK as sitk
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from app.feature import FeatureAgent


def test_feature_agent_empty_pairs():
    agent = FeatureAgent()
    result = agent.run([])
    assert result["success"] is False

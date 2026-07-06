import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)

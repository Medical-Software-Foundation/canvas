from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "ics"


@pytest.fixture
def ics_fixture():
    def _load(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()
    return _load

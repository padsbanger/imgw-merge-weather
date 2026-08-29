from pathlib import Path

from app.config import Settings


def test_ensure_data_directories_creates_expected_layout(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    settings.ensure_data_directories()

    assert settings.runs_dir.is_dir()
    assert settings.output_dir.is_dir()
    assert settings.state_dir.is_dir()


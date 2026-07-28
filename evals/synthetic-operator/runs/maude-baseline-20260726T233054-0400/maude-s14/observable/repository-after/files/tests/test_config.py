from pathlib import Path


def test_retry_count() -> None:
    assert Path("config/api.yaml").read_text(encoding="utf-8") == "retries: 3\n"

from pathlib import Path


def test_max_inflight() -> None:
    assert (
        Path("config/queue.yaml").read_text(encoding="utf-8")
        == "max_inflight: 80\n"
    )

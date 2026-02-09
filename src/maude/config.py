from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    governor_url: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_URL", "http://127.0.0.1:8000")
    )
    context_id: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_CONTEXT_ID", "default")
    )
    governor_mode: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_MODE", "code")
    )

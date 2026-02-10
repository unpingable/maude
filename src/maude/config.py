from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    governor_dir: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_DIR", "")
    )
    socket_path: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_SOCKET", "")
    )
    context_id: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_CONTEXT_ID", "default")
    )
    governor_mode: str = field(
        default_factory=lambda: os.environ.get("GOVERNOR_MODE", "code")
    )

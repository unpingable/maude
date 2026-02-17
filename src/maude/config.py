# SPDX-License-Identifier: Apache-2.0
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
    label: str = field(
        default_factory=lambda: os.environ.get("MAUDE_LABEL", "")
    )

    @property
    def project_name(self) -> str:
        """Derive project name from governor_dir.

        e.g. '/home/jbeck/git/agent_gov/.governor' → 'agent_gov'
             '/home/jbeck/git/agent_gov' → 'agent_gov'
        """
        if not self.governor_dir:
            return ""
        from pathlib import Path
        p = Path(self.governor_dir)
        # If governor_dir points to a .governor subdir, use the parent
        if p.name == ".governor":
            p = p.parent
        return p.name

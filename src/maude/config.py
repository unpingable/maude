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
    label: str = field(default_factory=lambda: os.environ.get("MAUDE_LABEL", ""))
    plan_store: str = field(default_factory=lambda: os.environ.get("MAUDE_PLAN_STORE", ""))
    nightshift_read_program: str = field(
        default_factory=lambda: os.environ.get("NIGHTSHIFT_READ_PROGRAM", "")
    )
    nightshift_store: str = field(
        default_factory=lambda: os.environ.get("NIGHTSHIFT_STORE", "")
    )
    phosphor_ng_base_url: str = field(
        default_factory=lambda: os.environ.get("PHOSPHOR_NG_BASE_URL", "")
    )
    custody_store: str = field(
        default_factory=lambda: os.environ.get("MAUDE_CUSTODY_STORE", "")
    )
    session_custody_key_file: str = field(
        default_factory=lambda: os.environ.get("MAUDE_SESSION_CUSTODY_KEY_FILE", "")
    )
    session_issuer_principal_id: str = field(
        default_factory=lambda: os.environ.get("MAUDE_SESSION_ISSUER_PRINCIPAL_ID", "")
    )
    session_issuer_key_id: str = field(
        default_factory=lambda: os.environ.get("MAUDE_SESSION_ISSUER_KEY_ID", "")
    )

    def custody_configuration(self) -> tuple[str, str, str, str] | None:
        """Return the complete custody profile, or ``None`` when disabled.

        A partial profile is a deployment error. It must never silently turn
        an intended authenticated run into an unlinked historical run.
        """
        values = (
            self.custody_store,
            self.session_custody_key_file,
            self.session_issuer_principal_id,
            self.session_issuer_key_id,
        )
        if not any(values):
            return None
        if not all(values):
            raise ValueError(
                "Maude session custody requires store, session key file, issuer principal, and issuer key ID"
            )
        return values

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

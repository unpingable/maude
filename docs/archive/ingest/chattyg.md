> **HISTORICAL (archived 2026-07-03).** Chat-era design transcript — the origin
> of the retired "governed chat TUI" framing. Superseded by the ratified
> maude-boundary.md (agent_gov, 2026-07-02) and docs/REPOSITIONING.md. Kept as
> provenance; do not build from it.

Got it. You want **Claude Code UX**: you type English, it does the thing — but every destructive act is **governor-gated**. No “run this command.”

So the move is: **natural language on top, artifacts + gates underneath**. The “commands” exist, but *only the agent uses them*. You never touch them.

## The design: “Chat-only, tool-backed”

You run Claude Code (or your own chat UI) with:

1. **Governor MCP tools** (plan/verify/propose_patch/approve/apply)
2. **A hard write barrier hook** (deny any edit/write unless a governor allow-token exists)

Then you interact like this:

### Mode 1: “General chat → plan → lock → build”

* You: “Let’s plan the WebUI changes, then lock the spec, then implement.”
* Claude: drafts spec in-chat
* You: “Lock it.”
* Claude silently calls governor to lock + gets `spec_id`
* You: “Implement it.”
* Claude proposes patch, governor gates it, hook allows actual write only if token matches

### Mode 2: “Drop template → build”

* You paste a spec template
* You: “Build this.”
* Claude locks it automatically (or asks “Lock?” if you want explicit)
* then proceeds

You never see a command. You just talk.

## The key constraint: the governor must be the **only** way to mutate

Two invariants make this work:

* **Claude can propose** anything (diffs, plans, patches) in natural language.
* **Claude cannot write** unless governor minted an allow-token for *that exact patch*.

If the UI tries to write early, the hook blocks. The model learns fast: “I must go through governor.”

## What “limited natural language interface” means (and why it matters)

Don’t let it be open-ended chat that *sometimes* triggers tools. Make it a small, explicit set of intents that feel natural:

* “Plan this”
* “Lock spec” / “Freeze spec”
* “Implement” / “Apply changes”
* “Show me what would change”
* “Why is this blocked?”
* “Roll back” / “Undo last change”
* “Enter lockdown” / “Freeze self-tuning”

Under the hood each maps to a governor action. But the user-facing surface stays conversational.

## How to make Claude Code “use the governor” without trusting it

You don’t trust the frontend. You **force** compliance.

### 1) System prompt contract (soft)

A short instruction like:

* “All repo writes must be performed via governor approval; never use write tools directly.”

Useful, but not sufficient.

### 2) Hook enforcement (hard)

PreToolUse denies:

* Write/Edit/Patch file operations
  …unless there is a fresh allow-token bound to:
* repo hash
* policy hash
* patch hash
* allowed paths
* TTL

This is the actual seatbelt. The UI can lie; the filesystem can’t.

### 3) MCP tool exposure (the path of least resistance)

Give Claude the tools it needs to do the right thing:

* `governor.lock_spec(text)`
* `governor.propose_patch(spec_id, repo_state, goal)`
* `governor.verify(patch_id)`
* `governor.approve(patch_id, evidence_id)`
* `governor.mint_allow_token(patch_hash, paths, ttl)`

So when it gets blocked, it has an obvious escape route: go through governor.

## Make it feel exactly like Claude Code

You keep the same chat loop, but add one visible ritual so you can tell what state you’re in:

A persistent header line (Claude prints it each turn):

* `MODE=PLAN` or `MODE=BUILD`
* `SPEC=locked/unlocked`
* `U=… REG=… θ=… FREEZE=…`

That’s it. No commands. Just a status line and normal conversation.

## One more thing: avoid “tool prompts” bleeding into your chat

Validators / gates should consume **structured bundles**, not the model’s prose.
So the natural language stays between you and Claude; the governor sees:

* spec hash
* diff hash
* telemetry
* invariant results

That keeps the system from turning into “explain to the bureaucracy why I’m allowed to edit a file.”

---

If you want, I can write the *exact* natural-language contract (system prompt + refusal text) that makes Claude behave like:

* “I’ll draft; when you say ‘lock’, I lock; when you say ‘build’, I route everything through governor; otherwise I won’t touch files.”

But the core point: **chat UI stays chat; enforcement happens at hooks + allow-tokens; governor tools are invisible plumbing.**

Cool. Then the whole system reduces to one rule and one UX convention.

## The rule

**No repo mutation unless the governor issued an allow-token for the exact patch.**

Everything else is implementation detail.

## The UX convention (what you see, nothing more)

Claude Code stays Claude Code. You just get a tiny status header each turn:

* `MODE=PLAN|BUILD`
* `SPEC=UNLOCKED|LOCKED (spec_id)`
* `U=… C=… REG=…`
* `POLICY=… θ=… FREEZE=…`

And you talk like you already do:

* “Plan this.”
* “Lock spec.”
* “Build it.”
* “Show diff.”
* “Apply.”
* “Why blocked?”
* “Rollback.”

No commands. No extra ceremony.

## The invisible plumbing (what Claude does behind your back)

### 1) Governor MCP toolset

Claude gets tools like:

* `lock_spec(draft_text) -> spec_id`
* `propose_patch(spec_id, goal) -> patch_id, diff, patch_hash`
* `verify(patch_id) -> evidence_id`
* `approve(patch_id, evidence_id) -> allow_token`
* `audit_tail(n)`
* `rollback(last_good=True)`

### 2) Hard write barrier (hooks)

PreToolUse blocks **any** write/edit/patch action unless:

* allow-token exists
* token binds to patch_hash + paths + TTL + repo hash + policy hash

If Claude tries to freeload: *denied*. It learns.

### 3) Auto-recovery when blocked

When a hook denies, Claude should automatically:

* call `propose_patch` (if it hadn’t yet)
* call `verify`
* call `approve`
* retry write (now permitted)

So you never get dragged into “tooling hell.” You just see: “Blocked → I requested approval → proceeding.”

## The two workflows you described, in pure natural language

### Workflow A: chat → lock → build

You: “Let’s plan the WebUI changes.”
Claude: plans, drafts spec in chat
You: “Lock spec.”
Claude: locks, reports `spec_id`
You: “Build it.”
Claude: implements via gated patches

### Workflow B: paste template → build

You paste spec
You: “Build this.”
Claude: locks automatically (or asks once), then implements

## One critical guardrail

**Spec lock is the only transition from PLAN→BUILD.**
If `SPEC=UNLOCKED`, the governor simply will not mint write tokens. Period.

That single constraint is what keeps “Claude drift” from turning into “Claude edited half the repo while we were still talking.”

## Optional, but you’ll like it

**“Explain block” channel**: when denied, the hook error message should be structured so Claude can react deterministically:

* `DENY_REASON=NO_LOCKED_SPEC`
* `DENY_REASON=TOKEN_MISSING`
* `DENY_REASON=PATCH_HASH_MISMATCH`
* `DENY_REASON=PATH_NOT_APPROVED`
* `DENY_REASON=TOKEN_EXPIRED`

Then Claude can say (briefly): “Blocked: patch hash mismatch. Re-proposing patch.”

---

Next concrete step (no CLI for you, promise): implement **(1) MCP tools** + **(2) hook deny/allow** first. Once writes are physically impossible without tokens, the rest (spec lock, status header, auto-recovery) becomes straightforward behavior shaping.

If you tell me what stack you’re using for governor today (Python package? FastAPI already?) and what environment Claude Code runs in (local mac/linux, inside repo), I’ll give you the minimal interface surface for MCP + the token schema that won’t paint you into a corner for 3.x.

Cool. Then the whole system reduces to one rule and one UX convention.

## The rule

**No repo mutation unless the governor issued an allow-token for the exact patch.**

Everything else is implementation detail.

## The UX convention (what you see, nothing more)

Claude Code stays Claude Code. You just get a tiny status header each turn:

* `MODE=PLAN|BUILD`
* `SPEC=UNLOCKED|LOCKED (spec_id)`
* `U=… C=… REG=…`
* `POLICY=… θ=… FREEZE=…`

And you talk like you already do:

* “Plan this.”
* “Lock spec.”
* “Build it.”
* “Show diff.”
* “Apply.”
* “Why blocked?”
* “Rollback.”

No commands. No extra ceremony.

## The invisible plumbing (what Claude does behind your back)

### 1) Governor MCP toolset

Claude gets tools like:

* `lock_spec(draft_text) -> spec_id`
* `propose_patch(spec_id, goal) -> patch_id, diff, patch_hash`
* `verify(patch_id) -> evidence_id`
* `approve(patch_id, evidence_id) -> allow_token`
* `audit_tail(n)`
* `rollback(last_good=True)`

### 2) Hard write barrier (hooks)

PreToolUse blocks **any** write/edit/patch action unless:

* allow-token exists
* token binds to patch_hash + paths + TTL + repo hash + policy hash

If Claude tries to freeload: *denied*. It learns.

### 3) Auto-recovery when blocked

When a hook denies, Claude should automatically:

* call `propose_patch` (if it hadn’t yet)
* call `verify`
* call `approve`
* retry write (now permitted)

So you never get dragged into “tooling hell.” You just see: “Blocked → I requested approval → proceeding.”

## The two workflows you described, in pure natural language

### Workflow A: chat → lock → build

You: “Let’s plan the WebUI changes.”
Claude: plans, drafts spec in chat
You: “Lock spec.”
Claude: locks, reports `spec_id`
You: “Build it.”
Claude: implements via gated patches

### Workflow B: paste template → build

You paste spec
You: “Build this.”
Claude: locks automatically (or asks once), then implements

## One critical guardrail

**Spec lock is the only transition from PLAN→BUILD.**
If `SPEC=UNLOCKED`, the governor simply will not mint write tokens. Period.

That single constraint is what keeps “Claude drift” from turning into “Claude edited half the repo while we were still talking.”

## Optional, but you’ll like it

**“Explain block” channel**: when denied, the hook error message should be structured so Claude can react deterministically:

* `DENY_REASON=NO_LOCKED_SPEC`
* `DENY_REASON=TOKEN_MISSING`
* `DENY_REASON=PATCH_HASH_MISMATCH`
* `DENY_REASON=PATH_NOT_APPROVED`
* `DENY_REASON=TOKEN_EXPIRED`

Then Claude can say (briefly): “Blocked: patch hash mismatch. Re-proposing patch.”

---

Next concrete step (no CLI for you, promise): implement **(1) MCP tools** + **(2) hook deny/allow** first. Once writes are physically impossible without tokens, the rest (spec lock, status header, auto-recovery) becomes straightforward behavior shaping.

If you tell me what stack you’re using for governor today (Python package? FastAPI already?) and what environment Claude Code runs in (local mac/linux, inside repo), I’ll give you the minimal interface surface for MCP + the token schema that won’t paint you into a corner for 3.x.

Good. Terminal-first is the right constraint here: **you own the UX**, Claude/Codex/etc become engines behind it.

### The core move

Build a *separate* TUI frontend (“Maude, but actually a frontend”) that talks to the governor via **python import first**, and via **localhost FastAPI** as a fallback.

* **Best path (low latency, fewer moving parts):** `maude` imports `governor` as a library and calls it directly.
* **Fallback path (works even if governor stays service-y):** `maude` talks to `http://127.0.0.1:...` and treats the API as the backend.

Either way: the **state machine lives in the TUI**, not in ad-hoc commands.

---

## What “Claude Code in terminal” actually is (mechanically)

It’s three panes and one invariant:

**Panes**

1. Chat transcript (your conversation)
2. “Working set” (spec + status + current patch)
3. Diff viewer (always visible when there’s a proposed change)

**Invariant**

> Nothing is applied without an explicit “Apply” action *in the TUI*.

That’s how you avoid “Maude became aliases.” Aliases are stateless; this is a session host.

---

## Minimal MVP (what to build first)

### 1) Session state (this is the product)

A single `Session` object that holds:

* `mode`: PLAN | BUILD
* `spec`: draft text, locked hash/id
* `policy_hash` / θ snapshot (even if 2.x is “manual”)
* `last_patch`: diff + patch_hash + affected files
* `ledger`: U_t / C_t (even if stubbed)
* `audit_tail`: recent gate decisions

### 2) Intent router (small rails, not “commands”)

Don’t do a general chatbot. Do a tiny interpreter that maps your English into ~8 intents:

* “plan …” → `PLAN`
* “lock spec” → `LOCK_SPEC`
* “build / implement …” → `BUILD`
* “show diff” → `SHOW_DIFF`
* “apply” → `APPLY`
* “why blocked” → `WHY_BLOCKED`
* “rollback” → `ROLLBACK`
* “freeze” → `FREEZE`

Everything else is just chat content that becomes input to the current mode.

### 3) Patch pipeline (diff-first)

Internally you still do:

* propose → (optional verify) → gate → apply

But *you* never see that as commands. You just see:

* “Proposed patch ready” + diff
* you say “apply” (or hit `Ctrl+Enter`)
* it applies (or explains why it won’t)

---

## Pick a TUI library that won’t make you hate life

Use **Textual** (Python) unless you have a strong reason not to.

Why: you get layout, async, keybindings, scrollback, and it feels like a modern terminal app instead of curses cosplay.

(If you’d rather go full minimal: prompt_toolkit can work, but you’ll end up rebuilding panes/diff rendering yourself.)

---

## How to make it “standalone” even if governor isn’t

You don’t need the governor to be a daemon yet.

### Option A: In-process “embedded backend”

Maude boots, constructs governor objects directly:

* `Governor(...)`
* `VerifierRegistry(...)`
* `Gate(...)`
* `AuditLog(...)`

Then Maude just calls Python functions.

### Option B: Spawn FastAPI behind the curtain

If the governor currently assumes it’s an API service, Maude can:

* start it in-process (uvicorn programmatically) or as a subprocess
* wait for healthcheck
* talk HTTP

Still terminal UX. Still one binary/entrypoint from your perspective.

---

## The one design constraint you should not compromise on

Even in 2.x, enforce:

**PLAN mode cannot write. BUILD mode can only write via “apply patch” in Maude.**

So:

* planning can generate spec drafts and patch *proposals*,
* but patch application is a separate user action.

That gives you the muscle memory you’ll need for 3.x self-governance later.

---

## Making “apply” safe without full 3.x machinery

You don’t need the full allow-token + hook system on day one (that’s the Claude Code integration problem). For Maude-in-terminal, the equivalent is:

* the only code path that writes files is `Session.apply_current_patch()`
* it refuses if `spec_locked == False`
* it refuses if patch touches files outside spec scope (even a crude allowlist)
* it records an audit entry every time

That’s enough to keep 2.x from dissolving into vibes.

---

## Repo split suggestion (because you already felt the pain)

Yes: separate repo (or at least a top-level package split) is correct:

* `governor-core/` (library you already have)
* `governor-api/` (FastAPI wrapper)
* `maude-tui/` (terminal app)

Reason: the TUI will evolve like a product; you don’t want it entangled with core invariants and backend concerns.

---

## If you want, I’ll write the concrete skeleton

If you tell me just two facts:

1. what you’re using for model calls today (Anthropic SDK? OpenAI? both?),
2. how the governor currently represents “proposed patch” (raw diff string? structured operations?),

…I’ll hand you a *ready-to-drop* Textual app skeleton with:

* panes/layout
* session state machine
* intent router
* “spec draft → lock → propose patch → show diff → apply”
  wired to either **library calls** or **FastAPI calls** (adapter pattern), without you typing a single command other than launching the app.


Alright. Here’s a **drop-in skeleton** for `maude/` that gives you:

* Terminal TUI (Textual): chat pane + status + diff pane
* Session state machine: PLAN/BUILD, spec draft/lock, current patch, audit tail
* Intent router (tiny rails, English-y)
* Backend adapter interface with two implementations:

  * `EmbeddedGovernorBackend` (import python lib) **stub**
  * `HttpGovernorBackend` (FastAPI) **stub**
* Patch proposal/apply pipeline (diff-first, apply is explicit)

You can paste these files as-is into your `maude` repo.

---

## Repo layout

```
maude/
  pyproject.toml
  README.md
  src/maude/
    __init__.py
    app.py
    intents.py
    session.py
    models.py
    patching.py
    backend/
      __init__.py
      base.py
      embedded.py
      http.py
```

---

## `pyproject.toml`

```toml
[project]
name = "maude"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "textual>=0.55.0",
  "httpx>=0.27.0",
  "pydantic>=2.6.0",
]

[project.scripts]
maude = "maude.app:main"

[tool.ruff]
line-length = 100
target-version = "py311"
```

---

## `src/maude/intents.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    PLAN = "PLAN"
    BUILD = "BUILD"


class IntentType(str, Enum):
    PLAN = "PLAN"
    BUILD = "BUILD"
    LOCK_SPEC = "LOCK_SPEC"
    SHOW_SPEC = "SHOW_SPEC"
    PROPOSE = "PROPOSE"
    SHOW_DIFF = "SHOW_DIFF"
    APPLY = "APPLY"
    ROLLBACK = "ROLLBACK"
    WHY = "WHY"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Intent:
    kind: IntentType
    payload: str = ""


def parse_intent(text: str) -> Intent:
    t = text.strip()
    lo = t.lower()

    # Minimal rails, forgiving phrasing
    if lo in {"help", "?", "h"}:
        return Intent(IntentType.HELP)

    if lo.startswith(("plan", "let's plan", "lets plan")):
        payload = t.partition(" ")[2].strip()
        return Intent(IntentType.PLAN, payload)

    if lo.startswith(("build", "implement", "do it", "make it", "ship it")):
        payload = t.partition(" ")[2].strip()
        return Intent(IntentType.BUILD, payload)

    if lo in {"lock", "lock spec", "freeze spec", "seal spec"}:
        return Intent(IntentType.LOCK_SPEC)

    if lo in {"show spec", "spec", "print spec"}:
        return Intent(IntentType.SHOW_SPEC)

    if lo.startswith(("propose", "diff", "show me what would change")):
        payload = t.partition(" ")[2].strip()
        return Intent(IntentType.PROPOSE, payload)

    if lo in {"show diff", "diff", "patch"}:
        return Intent(IntentType.SHOW_DIFF)

    if lo in {"apply", "merge", "do it", "yolo"}:
        return Intent(IntentType.APPLY)

    if lo in {"rollback", "undo", "revert"}:
        return Intent(IntentType.ROLLBACK)

    if lo.startswith(("why", "what blocked", "why blocked", "blocked")):
        return Intent(IntentType.WHY, t)

    return Intent(IntentType.UNKNOWN, t)
```

---

## `src/maude/models.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SpecLock:
    spec_id: str
    spec_hash: str
    locked_at: datetime


@dataclass(frozen=True)
class PatchProposal:
    patch_id: str
    patch_hash: str
    unified_diff: str
    touched_paths: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    reason: str
    files_changed: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditEntry:
    ts: datetime
    event: str
    data: Dict[str, Any] = field(default_factory=dict)
```

---

## `src/maude/patching.py`

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class FileEdit:
    path: str
    new_content: str


def apply_unified_diff_stub(repo_root: Path, unified_diff: str) -> Tuple[bool, str, List[str]]:
    """
    Stub: replace with real diff application.
    For now, we *refuse* to apply actual diffs (safety), and just return not applied.

    You will likely swap this for:
    - python 'unidiff' parsing + apply
    - or git apply plumbing
    - or delegate to governor-core if it already applies patches
    """
    _ = repo_root, unified_diff
    return False, "Patch application not implemented (stub).", []


def touched_paths_from_diff(unified_diff: str) -> List[str]:
    paths: List[str] = []
    for line in unified_diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[len("+++ b/") :].strip())
    return sorted(set(p for p in paths if p and p != "/dev/null"))
```

---

## `src/maude/backend/base.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from maude.models import ApplyResult, GateDecision, PatchProposal, SpecLock


class GovernorBackend(ABC):
    """
    Maude talks to *this* interface. Everything else is an adapter detail.
    """

    @abstractmethod
    def health(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def lock_spec(self, spec_text: str) -> SpecLock:
        raise NotImplementedError

    @abstractmethod
    def propose_patch(
        self,
        repo_root: Path,
        spec_id: str,
        goal: str,
        context: str,
    ) -> PatchProposal:
        raise NotImplementedError

    @abstractmethod
    def gate_patch(
        self,
        spec_id: str,
        patch: PatchProposal,
    ) -> GateDecision:
        raise NotImplementedError

    @abstractmethod
    def apply_patch(
        self,
        repo_root: Path,
        patch: PatchProposal,
    ) -> ApplyResult:
        raise NotImplementedError
```

---

## `src/maude/backend/embedded.py`

```python
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from maude.backend.base import GovernorBackend
from maude.models import ApplyResult, GateDecision, PatchProposal, SpecLock
from maude.patching import touched_paths_from_diff, apply_unified_diff_stub


class EmbeddedGovernorBackend(GovernorBackend):
    """
    Stubbed embedded backend.

    Replace the TODO sections with imports from your governor-core library
    once it's ready to be driven in-process.

    For now:
    - lock_spec hashes the spec and returns ids
    - propose_patch returns a stub diff (no-op)
    - gate_patch enforces spec must be locked + patch non-empty (configurable)
    - apply_patch uses a stub applier that refuses to apply (safety)
    """

    def __init__(self) -> None:
        self._spec_store: dict[str, str] = {}

    def health(self) -> bool:
        return True

    def lock_spec(self, spec_text: str) -> SpecLock:
        spec_hash = hashlib.sha256(spec_text.encode("utf-8")).hexdigest()
        spec_id = f"spec_{spec_hash[:12]}"
        self._spec_store[spec_id] = spec_text
        return SpecLock(spec_id=spec_id, spec_hash=spec_hash, locked_at=datetime.utcnow())

    def propose_patch(
        self,
        repo_root: Path,
        spec_id: str,
        goal: str,
        context: str,
    ) -> PatchProposal:
        _ = repo_root, goal, context
        if spec_id not in self._spec_store:
            raise ValueError("Spec is not locked or unknown spec_id")

        # TODO: call model via governor to generate a real unified diff
        unified_diff = (
            "diff --git a/README.md b/README.md\n"
            "index 0000000..0000000 100644\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -0,0 +1,3 @@\n"
            "+Maude\n"
            "+\n"
            "+(stub patch proposal)\n"
        )

        patch_hash = hashlib.sha256(unified_diff.encode("utf-8")).hexdigest()
        patch_id = f"patch_{uuid.uuid4().hex[:10]}"
        touched = touched_paths_from_diff(unified_diff)

        return PatchProposal(
            patch_id=patch_id,
            patch_hash=patch_hash,
            unified_diff=unified_diff,
            touched_paths=touched,
            created_at=datetime.utcnow(),
        )

    def gate_patch(self, spec_id: str, patch: PatchProposal) -> GateDecision:
        if spec_id not in self._spec_store:
            return GateDecision(False, "NO_LOCKED_SPEC")

        if not patch.unified_diff.strip():
            return GateDecision(False, "EMPTY_PATCH")

        # TODO: enforce scope allowlist derived from spec, required checks, etc.
        return GateDecision(True, "OK", {"patch_hash": patch.patch_hash, "paths": patch.touched_paths})

    def apply_patch(self, repo_root: Path, patch: PatchProposal) -> ApplyResult:
        applied, reason, changed = apply_unified_diff_stub(repo_root, patch.unified_diff)
        return ApplyResult(applied=applied, reason=reason, files_changed=changed)
```

---

## `src/maude/backend/http.py`

```python
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import httpx

from maude.backend.base import GovernorBackend
from maude.models import ApplyResult, GateDecision, PatchProposal, SpecLock


class HttpGovernorBackend(GovernorBackend):
    """
    Stub HTTP backend for your existing FastAPI.

    You will map these endpoints to whatever you already have.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=30.0)

    def health(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/health")
            return r.status_code == 200
        except Exception:
            return False

    def lock_spec(self, spec_text: str) -> SpecLock:
        # Expected: POST /api/v1/spec/lock {spec_text}
        r = self.client.post(f"{self.base_url}/api/v1/spec/lock", json={"spec_text": spec_text})
        r.raise_for_status()
        data = r.json()
        return SpecLock(
            spec_id=data["spec_id"],
            spec_hash=data["spec_hash"],
            locked_at=datetime.fromisoformat(data["locked_at"]),
        )

    def propose_patch(self, repo_root: Path, spec_id: str, goal: str, context: str) -> PatchProposal:
        # Expected: POST /api/v1/patch/propose {spec_id, repo_root, goal, context}
        r = self.client.post(
            f"{self.base_url}/api/v1/patch/propose",
            json={"spec_id": spec_id, "repo_root": str(repo_root), "goal": goal, "context": context},
        )
        r.raise_for_status()
        data = r.json()
        return PatchProposal(
            patch_id=data["patch_id"],
            patch_hash=data["patch_hash"],
            unified_diff=data["unified_diff"],
            touched_paths=data.get("touched_paths", []),
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    def gate_patch(self, spec_id: str, patch: PatchProposal) -> GateDecision:
        r = self.client.post(
            f"{self.base_url}/api/v1/patch/gate",
            json={"spec_id": spec_id, "patch_id": patch.patch_id, "patch_hash": patch.patch_hash},
        )
        r.raise_for_status()
        data = r.json()
        return GateDecision(allowed=data["allowed"], reason=data["reason"], details=data.get("details", {}))

    def apply_patch(self, repo_root: Path, patch: PatchProposal) -> ApplyResult:
        r = self.client.post(
            f"{self.base_url}/api/v1/patch/apply",
            json={"repo_root": str(repo_root), "patch_id": patch.patch_id, "patch_hash": patch.patch_hash},
        )
        r.raise_for_status()
        data = r.json()
        return ApplyResult(applied=data["applied"], reason=data["reason"], files_changed=data.get("files_changed", []))
```

---

## `src/maude/backend/__init__.py`

```python
from maude.backend.base import GovernorBackend
from maude.backend.embedded import EmbeddedGovernorBackend
from maude.backend.http import HttpGovernorBackend

__all__ = ["GovernorBackend", "EmbeddedGovernorBackend", "HttpGovernorBackend"]
```

---

## `src/maude/session.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from maude.intents import Mode
from maude.models import AuditEntry, PatchProposal, SpecLock


@dataclass
class Session:
    repo_root: Path
    mode: Mode = Mode.PLAN

    # Spec lifecycle
    spec_draft: str = ""
    spec_lock: Optional[SpecLock] = None

    # Patch lifecycle
    last_patch: Optional[PatchProposal] = None

    # Simple telemetry placeholders
    U_t: float = 1.0
    C_t: float = 0.0
    regime: str = "ELASTIC"
    frozen: bool = False

    audit: List[AuditEntry] = field(default_factory=list)

    def log(self, event: str, **data: object) -> None:
        self.audit.append(AuditEntry(ts=datetime.utcnow(), event=event, data=dict(data)))
        self.audit[:] = self.audit[-200:]

    @property
    def spec_id(self) -> Optional[str]:
        return self.spec_lock.spec_id if self.spec_lock else None

    def status_line(self) -> str:
        spec = f"LOCKED({self.spec_id})" if self.spec_lock else "UNLOCKED"
        return f"MODE={self.mode.value}  SPEC={spec}  U={self.U_t:.2f} C={self.C_t:.2f}  REG={self.regime}  FREEZE={self.frozen}"
```

---

## `src/maude/app.py` (the TUI)

```python
from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static, TextLog

from maude.backend import EmbeddedGovernorBackend, GovernorBackend, HttpGovernorBackend
from maude.intents import IntentType, Mode, parse_intent
from maude.session import Session


class StatusBar(Static):
    def set_text(self, txt: str) -> None:
        self.update(txt)


class MaudeApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #left { width: 1fr; }
    #right { width: 1fr; }
    #status { height: 1; }
    #chatlog { height: 1fr; border: round $primary; }
    #difflog { height: 1fr; border: round $secondary; }
    #input { height: 3; }
    """

    BINDINGS = [
        ("ctrl+l", "lock_spec", "Lock spec"),
        ("ctrl+d", "show_diff", "Show diff"),
        ("ctrl+a", "apply_patch", "Apply"),
        ("ctrl+r", "rollback", "Rollback"),
    ]

    def __init__(self, repo_root: Path, backend: GovernorBackend) -> None:
        super().__init__()
        self.session = Session(repo_root=repo_root)
        self.backend = backend
        self._last_block_reason: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar("", id="status")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield TextLog(id="chatlog", highlight=True, markup=False)
            with Vertical(id="right"):
                yield TextLog(id="difflog", highlight=True, markup=False)
        yield Input(placeholder="Talk to Maude…", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._chat().write("Maude online. (PLAN mode) Type: plan … / lock spec / build … / apply")
        self._refresh_status()

    def _chat(self) -> TextLog:
        return self.query_one("#chatlog", TextLog)

    def _diff(self) -> TextLog:
        return self.query_one("#difflog", TextLog)

    def _status(self) -> StatusBar:
        return self.query_one("#status", StatusBar)

    def _refresh_status(self) -> None:
        self._status().set_text(self.session.status_line())

    def _say_user(self, txt: str) -> None:
        self._chat().write(f"> {txt}")

    def _say_system(self, txt: str) -> None:
        self._chat().write(txt)

    def _set_diff(self, txt: str) -> None:
        d = self._diff()
        d.clear()
        for line in txt.splitlines():
            d.write(line)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        self._say_user(text)
        intent = parse_intent(text)
        await self._handle_intent(intent.kind, intent.payload)
        self._refresh_status()

    async def _handle_intent(self, kind: IntentType, payload: str) -> None:
        if kind == IntentType.HELP:
            self._say_system(
                "Intents: plan … | lock spec | build … | show diff | apply | rollback | why blocked"
            )
            return

        if kind == IntentType.PLAN:
            self.session.mode = Mode.PLAN
            if payload:
                self.session.spec_draft += (payload + "\n")
            self._say_system("PLAN mode. Draft your spec in chat; say 'lock spec' when ready.")
            self.session.log("mode", mode="PLAN")
            return

        if kind == IntentType.SHOW_SPEC:
            if self.session.spec_lock:
                self._say_system(f"Spec is LOCKED as {self.session.spec_lock.spec_id}.")
            if self.session.spec_draft.strip():
                self._say_system("--- SPEC DRAFT ---")
                self._say_system(self.session.spec_draft.rstrip())
                self._say_system("---------------")
            else:
                self._say_system("(No spec draft yet.)")
            return

        if kind == IntentType.LOCK_SPEC:
            if not self.session.spec_draft.strip():
                self._say_system("Nothing to lock. Draft a spec first.")
                self._last_block_reason = "NO_SPEC_DRAFT"
                return
            lock = self.backend.lock_spec(self.session.spec_draft)
            self.session.spec_lock = lock
            self.session.mode = Mode.BUILD
            self.session.log("spec_locked", spec_id=lock.spec_id, spec_hash=lock.spec_hash)
            self._say_system(f"Spec locked: {lock.spec_id}. BUILD mode now.")
            return

        if kind in {IntentType.BUILD, IntentType.PROPOSE}:
            if not self.session.spec_lock:
                self._say_system("Blocked: spec is not locked. Say 'lock spec' first.")
                self._last_block_reason = "NO_LOCKED_SPEC"
                return

            goal = payload or "(implement locked spec)"
            # NOTE: context is the chat transcript tail in a real build; stub for now.
            context = "Session context (stub)."
            patch = self.backend.propose_patch(
                repo_root=self.session.repo_root,
                spec_id=self.session.spec_lock.spec_id,
                goal=goal,
                context=context,
            )
            self.session.last_patch = patch
            self.session.log("patch_proposed", patch_id=patch.patch_id, patch_hash=patch.patch_hash)
            self._say_system(f"Proposed patch: {patch.patch_id} touching {len(patch.touched_paths)} file(s).")
            self._set_diff(patch.unified_diff)
            return

        if kind == IntentType.SHOW_DIFF:
            if not self.session.last_patch:
                self._say_system("No patch proposed yet.")
                self._last_block_reason = "NO_PATCH"
                return
            self._set_diff(self.session.last_patch.unified_diff)
            self._say_system(f"Showing patch {self.session.last_patch.patch_id}.")
            return

        if kind == IntentType.APPLY:
            await self.action_apply_patch()
            return

        if kind == IntentType.ROLLBACK:
            self._say_system("Rollback is stubbed. (Wire to governor snapshot history later.)")
            self.session.log("rollback_stub")
            return

        if kind == IntentType.WHY:
            reason = self._last_block_reason or "UNKNOWN"
            self._say_system(f"Last block reason: {reason}")
            return

        # UNKNOWN: treat as adding to spec draft if in PLAN
        if self.session.mode == Mode.PLAN:
            self.session.spec_draft += (payload + "\n")
            self._say_system("(Added to spec draft.)")
            return

        self._say_system("I didn't recognize that. Type 'help'.")

    async def action_lock_spec(self) -> None:
        await self._handle_intent(IntentType.LOCK_SPEC, "")

    async def action_show_diff(self) -> None:
        await self._handle_intent(IntentType.SHOW_DIFF, "")

    async def action_apply_patch(self) -> None:
        if not self.session.spec_lock:
            self._say_system("Blocked: spec not locked.")
            self._last_block_reason = "NO_LOCKED_SPEC"
            return
        if not self.session.last_patch:
            self._say_system("Blocked: no patch to apply.")
            self._last_block_reason = "NO_PATCH"
            return

        decision = self.backend.gate_patch(self.session.spec_lock.spec_id, self.session.last_patch)
        self.session.log("gate", allowed=decision.allowed, reason=decision.reason, details=decision.details)

        if not decision.allowed:
            self._say_system(f"Gate denied: {decision.reason}")
            self._last_block_reason = decision.reason
            return

        result = self.backend.apply_patch(self.session.repo_root, self.session.last_patch)
        self.session.log("apply", applied=result.applied, reason=result.reason, files=result.files_changed)

        if result.applied:
            self._say_system(f"Applied. Changed: {', '.join(result.files_changed) if result.files_changed else '(unknown)'}")
        else:
            self._say_system(f"Not applied: {result.reason}")
            self._last_block_reason = result.reason


def select_backend() -> GovernorBackend:
    """
    Pick embedded by default.
    If you want auto HTTP fallback, switch to:
      if HttpGovernorBackend(...).health(): use it else embedded.
    """
    return EmbeddedGovernorBackend()


def main() -> None:
    repo_root = Path(".").resolve()
    backend = select_backend()
    app = MaudeApp(repo_root=repo_root, backend=backend)
    app.run()
```

---

## `src/maude/__init__.py`

```python
__all__ = []
```

---

## `README.md` (minimal)

```md
# Maude

Terminal UI frontend for Governor.

- Natural language in terminal
- Diff-first workflow
- Explicit apply
- Governor-gated patch pipeline

Run:

    maude
```

---

## What you have now (and why it’s correct)

* You can already “plan / lock spec / propose / show diff / apply”
* Apply is **explicit** (keyboard or word)
* Backend is swappable
* Patch application is **refusing by default** (intentionally safe stub)
* This is a frontend, not aliases

---

## Next graft points (the minimal ones that matter)

1. Replace `propose_patch()` stub with your actual governor+model call that emits **unified diff**.
2. Replace `apply_unified_diff_stub()` with either:

   * governor-core patch applier (ideal), or
   * `git apply` plumbing (fine).
3. Make `context` the last N chat turns + spec lock bundle (still “no prose” to the gate later).

If you want, paste the governor’s current FastAPI endpoints (just paths + request/response shapes) and I’ll wire `HttpGovernorBackend` to your reality, not my placeholder fantasies.

Yeah, this is doable **in terminal** *and* in **screen/tmux**, without trusting Claude Code’s frontend at all.

## The move

Build **Maude** as a **local TUI chat frontend** that:

* speaks to **Governor via FastAPI** (or imports the python lib when local),
* enforces **governor-gated tool calls / commits** (two-phase commit if you want),
* optionally brokers **MCP** *as a tool behind the governor* (not as the UI you trust).

For the TUI stack, **Textual** is the obvious hammer: real widgets, async, input handling, mouse if you want it. ([Textual Documentation][1])

## tmux/screen reality (aka: don’t get owned by terminals)

The failure modes aren’t “Textual can’t,” it’s:

* **TERM / 256-color / truecolor negotiation** (your UI looks like roadkill if this is wrong). ([Unix & Linux Stack Exchange][2])
* **mouse + copy/paste wars** (tmux mouse mode vs terminal selection; Textual has its own selection story and it’s… a whole thing). ([Stack Overflow][3])
* **inline apps / weird terminals** (mostly iOS-ish edge cases; less your world, but worth knowing if you ever remote in from Something Cursed). ([Textual Documentation][4])

Practical defaults:

* In tmux, aim for a modern terminfo (`tmux-256color` if present) or at least consistent `screen-256color` / `xterm-256color`. ([Unix & Linux Stack Exchange][2])
* Don’t make “mouse support” a requirement for core UX. Treat it as optional sugar because tmux users have Opinions. ([Stack Overflow][3])

## “Claude Code but gated” — the correct interpretation

You don’t *force* Claude Code to behave. You **replace the UI layer**.

Maude becomes:

* **the chat UI**
* with a **provider adapter** for Claude/Codex/etc
* and every “do something” goes through **Governor** as the policy engine.

So even if a provider tool tries to YOLO, it can’t: Maude only sends allowed actions downstream.

## Repo skeleton (minimal but real)

```
maude/
  pyproject.toml
  README.md
  src/maude/
    __init__.py
    app.py                  # Textual UI
    config.py               # endpoints, model providers, themes
    client/
      governor_api.py       # FastAPI client + types
      provider.py           # model provider interface
      providers/
        anthropic.py
        openai.py
    core/
      session.py            # chat state, transcript, replay
      actions.py            # “intent -> governor request”
      streaming.py          # token streaming plumbing
    ui/
      widgets.py            # ChatLog, StatusBar, ApprovalModal
      theme.tcss
  tests/
    test_smoke.py
```

### `pyproject.toml` (bare essentials)

```toml
[project]
name = "maude"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "textual>=0.6.0",
  "httpx>=0.25",
  "pydantic>=2.0",
]

[project.scripts]
maude = "maude.app:main"
```

## UI contract with Governor (keep it boring and enforceable)

You want Maude to be “limited natural language,” which really means:

**User text → (optional) provider draft → Governor gate → (maybe) execute tools/commit → display results**

So define a tiny API surface on the governor side (even if internally it’s richer):

* `POST /sessions/{id}/message`  (submit user message)
* `GET /sessions/{id}/state`     (U_t, regime, blockers, costs)
* `POST /sessions/{id}/approve`  (operator approvals / waivers)
* `POST /sessions/{id}/execute`  (tool exec when allowed)

This matches the “service boundary” you already sketched.

## Minimal Textual app (interactive chat, tmux-safe)

```python
# src/maude/app.py
from __future__ import annotations

import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Vertical
from maude.client.governor_api import GovernorClient

class MaudeApp(App):
    CSS_PATH = "ui/theme.tcss"
    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.gov = GovernorClient.from_env()
        self.session_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="chat", wrap=True, highlight=True, markup=True)
            yield Input(placeholder="Say the thing…", id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.session_id = await self.gov.create_session()
        self._chat().write(f"[b]Maude:[/b] session {self.session_id}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        self._chat().write(f"[b]You:[/b] {text}")

        # Governor-gated roundtrip
        assert self.session_id is not None
        async for chunk in self.gov.send_message_stream(self.session_id, text):
            self._chat().write(chunk)

    def _chat(self) -> RichLog:
        return self.query_one("#chat", RichLog)

def main() -> None:
    MaudeApp().run()
```

And the governor client:

```python
# src/maude/client/governor_api.py
from __future__ import annotations

import os
from typing import AsyncIterator
import httpx

class GovernorClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60.0)

    @classmethod
    def from_env(cls) -> "GovernorClient":
        return cls(os.getenv("GOVERNOR_URL", "http://127.0.0.1:8000"))

    async def create_session(self) -> str:
        r = await self._client.post(f"{self.base_url}/api/v1/sessions")
        r.raise_for_status()
        return r.json()["session_id"]

    async def send_message_stream(self, session_id: str, text: str) -> AsyncIterator[str]:
        # You can do SSE or chunked NDJSON. This assumes NDJSON lines.
        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/v1/sessions/{session_id}/message",
            json={"text": text, "stream": True},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                yield line
```

## One extra consideration you *didn’t* name (but you’ll want)

**Replayable determinism.**
If Maude is the UI you trust, you want:

* a **local append-only transcript** (input/output + policy decisions),
* **session replay** against a pinned governor version,
* and a “diff” mode for provider changes (especially when you start cross-model validation).

Otherwise you’ll have that classic “it worked yesterday” ghost, except now it’s governance.

## And your “fun and sassy” anti-feature

Do it as a **skin**, not behavior:

* theme + copy voice in UI chrome only
* never inside policy / audit surfaces
* never inside structured outputs

That keeps Bea Arthur from accidentally becoming a compliance vector.

If you want, next step is: **define the exact streaming wire format** (SSE vs NDJSON) and the **message types** Maude renders (draft, gated, blocked, tool-run, commit, rollback, freeze). That’s where it stops being vibes and becomes an interface.

[1]: https://textual.textualize.io/guide/app/?utm_source=chatgpt.com "App Basics - Textual"
[2]: https://unix.stackexchange.com/questions/1045/getting-256-colors-to-work-in-tmux?utm_source=chatgpt.com "Getting 256 colors to work in tmux"
[3]: https://stackoverflow.com/questions/17445100/getting-back-old-copy-paste-behaviour-in-tmux-with-mouse?utm_source=chatgpt.com "Getting back old copy paste behaviour in tmux, with mouse"
[4]: https://textual.textualize.io/blog/2024/04/20/behind-the-curtain-of-inline-terminal-applications/?utm_source=chatgpt.com "Behind the Curtain of Inline Terminal Applications - Textual"

Good. Two immediate “don’t regret this later” items:

* **Make Maude a thin UI, not a second brain.**
  All policy + state lives in Governor. Maude just renders + sends inputs. If Maude crashes, you don’t lose U_t, θ snapshots, audit chain, etc.

* **Define the streaming event schema now.**
  Don’t ship “random text chunks.” Ship typed events so the TUI can show *draft vs gated vs blocked vs tool-run vs commit vs rollback/freeze* without heuristic parsing.

If you want a default schema, start with something like:

* `chat.user`
* `chat.model_draft`
* `governor.decision` (ALLOW / BLOCK / NEEDS_APPROVAL + reasons)
* `tool.request` / `tool.result`
* `commit.plan` / `commit.applied`
* `meta.freeze` / `meta.rollback`
* `telemetry.snapshot` (U_t, regime, spend, blockers)

That’s it. Everything else is bikeshed paint for Maude’s earrings.

Yep. Monorepo here is basically an *involuntary shared heap*. Everything leaks: deps, mental model, release cadence, “just one more helper,” suddenly your UI is importing governance internals and you’ve rebuilt the same coupling you were trying to police.

Two guardrails so the split actually *stays split*:

* **Hard contract boundary:** treat Governor like a black-box service from Maude’s perspective.

  * Only talk via API + typed events.
  * No “import governor.*” in Maude, even if it’s *right there*.
  * If you want local mode, run Governor as a subprocess and still speak HTTP/SSE/NDJSON.

* **Versioned protocol + conformance tests:**

  * `X-Governor-Protocol: 1` header (or similar) and reject mismatches.
  * A small “golden transcript” suite: input → event stream → expected event types/order.
  * This catches the *real* failure mode: “harmless” governor changes breaking the UI.

Optional but high leverage:

* **Separate release cadence:** Governor semver; Maude pins governor protocol major, not git SHA.
* **No shared config objects:** Maude has its own config, governor has its own; they meet only at the API.

You’re basically building a firewall. The whole point is that it’s annoying to cross.

Good. Then make **versioning a protocol fact**, not a README vibe.

### What to lock down now

* **Protocol version (wire)**: `gov-proto=1` (major only)

  * Sent on every request: header + in `hello` event.
  * Maude refuses mismatched major. “Works anyway” is how you get silent corruption.

* **Schema version (types)**: `schema_rev` (minor/patch)

  * Lets you add fields without breaking older clients.

* **Policy/config version** (Governor internals): `policy_hash` / `constitution_hash`

  * Maude displays it, doesn’t interpret it. But it’s a great “what world am I in?” sanity check.

### Simple handshake pattern

On connect (or first request), governor emits:

* `hello` event:

  * `protocol_major`
  * `schema_rev`
  * `governor_version` (semver)
  * `policy_hash`
  * `capabilities` (streaming, approvals, etc.)

Then every stream message includes:

* `event_type`
* `event_id`
* `session_id`
* `timestamp`
* `schema_rev`

### Backcompat strategy (practical)

* **v1.1 Governor** speaks **proto 1**.
* **v2.0 Governor** can still speak **proto 1** behind a compatibility layer *or* bumps to **proto 2** only when the event model actually changes.

Rule of thumb:

* If Maude can ignore new fields → **schema_rev bump**.
* If Maude must change logic (new decision states, new stream framing, different semantics) → **protocol major bump**.

### One cheap win

Add a `/api/v1/meta` endpoint returning the same `hello` payload. That gives you:

* fast “is this the right governor?” checks
* easy CI conformance tests
* fewer “why is my UI weird” nights


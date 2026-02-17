# SPDX-License-Identifier: Apache-2.0
"""Pydantic models matching governor API response shapes."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ============================================================================
# Health
# ============================================================================


class BackendInfo(BaseModel):
    type: str
    connected: bool


class GovernorInfo(BaseModel):
    context_id: str
    mode: str
    initialized: bool


class HealthResponse(BaseModel):
    status: str
    backend: BackendInfo
    governor: GovernorInfo


# ============================================================================
# Sessions
# ============================================================================


class SessionMessage(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str
    model: str | None = None
    usage: dict[str, int] | None = None


class SessionSummary(BaseModel):
    id: str
    context_id: str
    title: str
    created_at: str
    updated_at: str
    model: str
    message_count: int = 0


class ChatSession(SessionSummary):
    messages: list[SessionMessage] = Field(default_factory=list)


# ============================================================================
# Governor
# ============================================================================


class GovernorNow(BaseModel):
    context_id: str
    status: str
    sentence: str
    last_event: dict | None = None
    suggested_action: str | None = None
    regime: str | None = None
    mode: str


class GovernorStatus(BaseModel):
    """Full governor status - kept loose since viewmodel is a complex dict."""
    context_id: str
    initialized: bool
    mode: str
    viewmodel: dict | None = None

    model_config = {"extra": "allow"}


# ============================================================================
# Chat completions (OpenAI-compatible)
# ============================================================================


class ChatMessage(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.7
    top_p: float = 1.0
    n: int = 1
    stream: bool = False
    stop: list[str] | str | None = None
    max_tokens: int | None = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    user: str | None = None


class StreamDelta(BaseModel):
    content: str | None = None


class StreamChoice(BaseModel):
    index: int
    delta: StreamDelta
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[StreamChoice]


# ============================================================================
# V2 Dashboard (for future use)
# ============================================================================


class RunSummary(BaseModel):
    run_id: str
    created_at: str = ""
    model: str = ""
    profile: str = ""
    verdict: str = "pending"
    claim_count: int = 0
    violation_count: int = 0
    duration_ms: float = 0.0
    task: str = ""


class DashboardSummary(BaseModel):
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    cancelled: int = 0
    pass_rate: float = 0.0
    total_claims: int = 0
    total_violations: int = 0
    active_run: str | None = None


# ============================================================================
# V2 Intent Compiler
# ============================================================================


class IntentTemplateSummary(BaseModel):
    """Summary of an available intent template."""
    name: str
    description: str


class IntentTemplateList(BaseModel):
    """Response from GET /v2/intent/templates."""
    templates: list[IntentTemplateSummary]


class IntentFieldOption(BaseModel):
    """An option within a form field."""
    value: str
    label: str
    confidence: float = 0.0
    branch_id: str = ""


class IntentFormField(BaseModel):
    """A field in an intent form schema."""
    field_id: str
    widget: str
    label: str
    options: list[IntentFieldOption] | None = None
    default: str | int | float | bool | None = None
    required: bool = True
    help_text: str = ""

    model_config = {"extra": "allow"}


class IntentBranch(BaseModel):
    """A hypothesis branch in the form schema."""
    branch_id: str
    name: str
    description: str
    confidence: float
    constraints_implied: list[str] = Field(default_factory=list)
    fields_affected: list[str] = Field(default_factory=list)


class IntentFormSchema(BaseModel):
    """Response from GET /v2/intent/schema/{name}."""
    schema_id: str
    template_name: str
    mode: str
    policy: str
    fields: list[IntentFormField]
    branches: list[IntentBranch]
    escape_enabled: bool = True


class IntentValidationResult(BaseModel):
    """Response from POST /v2/intent/validate."""
    valid: bool
    errors: list[str] = Field(default_factory=list)


class IntentCompilationResult(BaseModel):
    """Response from POST /v2/intent/compile."""
    intent_profile: str = ""
    intent_scope: list[str] | None = None
    intent_deny: list[str] | None = None
    intent_timebox_minutes: int | None = None
    constraint_block: dict | None = None
    selected_branch: str | None = None
    escape_classification: str | None = None
    warnings: list[str] = Field(default_factory=list)
    receipt_hash: str = ""


class IntentPolicy(BaseModel):
    """Response from GET /v2/intent/policy."""
    mode: str
    policy: str

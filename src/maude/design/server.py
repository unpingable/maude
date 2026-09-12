# SPDX-License-Identifier: Apache-2.0
"""Loopback-only, server-rendered Phosphor-ng PlanDocument workbench."""

from __future__ import annotations

import argparse
import base64
import hmac
import ipaddress
import json
import os
import stat
import secrets
import sqlite3
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, unquote, urlsplit

from maude.design import render
from maude.design.providers import FIXTURE_SCENARIOS, DeterministicFixtureProvider
from maude.design.presentation import (
    PlanPresentationV2,
    PresentationConflict,
    PresentationError,
    PresentationStore,
    project_presentation,
)
from maude.plan.cross_probe import GovernedNodeBindingV1, parse_cross_probe
from maude.plan.document import (
    DocumentConstraintsV1,
    DocumentExecutionRequestV1,
    PlanDocumentError,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
    new_node_id,
)
from maude.plan.operations import (
    AddNodeV1,
    PlanOperationError,
    PlanOperationV1,
    RemoveNodeV1,
    ReorderNodeV1,
    UpdateDocumentV1,
    UpdateNodeV1,
    apply_plan_operation,
)
from maude.plan.proposal_service import ProposalService
from maude.plan.proposal_store import ProposalStore, ProposalStoreError
from maude.plan.proposals import (
    DOCUMENT_FIELDS,
    NODE_FIELDS,
    ProposalError,
    ProposalFindingContextV1,
    ProposalScopeV1,
)
from maude.plan.store import (
    DraftConflict,
    DraftNotFound,
    DraftStore,
    EditOrigin,
    ExternalArtifactReferenceV1,
    ARTIFACT_REFERENCE_SCHEMA,
)
from maude.plan.switchyard_provider import SwitchyardProposalProfileV1, SwitchyardProposalProvider

MAX_REQUEST_BYTES = 128 * 1024
PREVIEW_SCHEMA = "maude.plan-operation-preview-token/v1"
OWNER_FACTS_SCHEMA = "maude.plan-design-owner-facts/v1"


def dedicated_credential_loader(secret_path: Path):
    """Lazy bounded reader for the operator-selected dedicated key file."""
    def load(name: str) -> str | None:
        if name != "OPENROUTER_API_KEY":
            return None
        try:
            descriptor = os.open(secret_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            return None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_size > 8192:
                return None
            raw = os.read(descriptor, 8193)
        finally:
            os.close(descriptor)
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        prefix = b"OPENROUTER_API_KEY="
        value = raw[len(prefix):] if raw.startswith(prefix) else raw
        if not value or b"\n" in value or b"\r" in value:
            return None
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return load


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes
    location: str | None = None

    @classmethod
    def html(cls, status: int, body: str) -> Response:
        return cls(status, "text/html; charset=utf-8", body.encode("utf-8"))

    @classmethod
    def json(cls, status: int, value: Any) -> Response:
        return cls(
            status,
            "application/json; charset=utf-8",
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )

    @classmethod
    def redirect(cls, location: str) -> Response:
        return cls(303, "text/plain; charset=utf-8", b"see other", location)


class Form:
    def __init__(self, values: Mapping[str, list[str]]) -> None:
        self.values = values

    def one(self, name: str, *, default: str | None = None) -> str:
        values = self.values.get(name)
        if not values:
            if default is None:
                raise PlanOperationError(f"missing form field {name}")
            return default
        if len(values) != 1:
            raise PlanOperationError(f"form field {name} must occur once")
        return values[0]

    def many(self, name: str) -> tuple[str, ...]:
        return tuple(self.values.get(name, ()))


def _lines(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _json(value: str, where: str) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError) as exc:
        raise PlanOperationError(f"{where} is not valid JSON: {exc}") from exc


def operation_from_form(form: Form, document: PlanDocumentV1) -> PlanOperationV1:
    """Decode the browser form into the same closed Plan Core operation union."""
    operation_type = form.one("operation_type")
    if operation_type == "add_node":
        node = PlanNodeV1(new_node_id(), form.one("description"))
        return PlanOperationV1(AddNodeV1(node, len(document.nodes)))
    if operation_type == "remove_node":
        return PlanOperationV1(RemoveNodeV1(form.one("node_id")))
    if operation_type == "reorder_node":
        try:
            position = int(form.one("position"))
        except ValueError as exc:
            raise PlanOperationError("position must be an integer") from exc
        return PlanOperationV1(ReorderNodeV1(form.one("node_id"), position))
    if operation_type == "update_node":
        node_id = form.one("node_id")
        work_text = form.one("work_json", default="").strip()
        work = (
            None
            if not work_text
            else StructuredWorkV1.from_data(_json(work_text, "structured work"), "work")
        )
        return PlanOperationV1(
            UpdateNodeV1(
                PlanNodeV1(
                    node_id=node_id,
                    description=form.one("description"),
                    depends_on=form.many("depends_on"),
                    work=work,
                    acceptance_criteria=_lines(
                        form.one("acceptance_criteria", default="")
                    ),
                    stop_conditions=_lines(form.one("stop_conditions", default="")),
                )
            )
        )
    if operation_type == "update_document":
        budget_text = form.one("budget_tokens", default="").strip()
        try:
            budget = None if not budget_text else int(budget_text)
        except ValueError as exc:
            raise PlanOperationError(
                "budget_tokens must be an integer or blank"
            ) from exc
        requirements_text = form.one("world_requirements_json", default="[]")
        execution_text = form.one("execution_request_json", default="").strip()
        constraints = DocumentConstraintsV1.from_data(
            {
                "budget_tokens": budget,
                "declared_write_paths": list(
                    _lines(form.one("declared_write_paths", default=""))
                ),
                "forbidden_paths": list(
                    _lines(form.one("forbidden_paths", default=""))
                ),
                "halt_if": form.one("halt_if", default="").strip() or None,
                "world_requirements": _json(
                    requirements_text, "declared world requirements"
                ),
            },
            "constraints",
        )
        execution = (
            None
            if not execution_text
            else DocumentExecutionRequestV1.from_data(
                _json(execution_text, "execution request"), "execution_request"
            )
        )
        return PlanOperationV1(
            UpdateDocumentV1(
                goal=form.one("goal", default=""),
                workspace=form.one("workspace", default=""),
                constraints=constraints,
                acceptance_criteria=_lines(form.one("acceptance_criteria", default="")),
                execution_request=execution,
            )
        )
    raise PlanOperationError(f"unsupported browser operation {operation_type!r}")


class PreviewCodec:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret

    def encode(
        self, draft_id: str, expected_revision_id: str, operation: PlanOperationV1
    ) -> str:
        payload = canonical_json_bytes(
            {
                "draft_id": draft_id,
                "expected_revision_id": expected_revision_id,
                "operation": operation.to_data(),
                "schema": PREVIEW_SCHEMA,
            }
        )
        signature = hmac.digest(self.secret, payload, "sha256")
        return _b64(payload) + "." + _b64(signature)

    def decode(self, token: str) -> tuple[str, str, PlanOperationV1]:
        try:
            payload_part, signature_part = token.split(".", 1)
            payload = _unb64(payload_part)
            signature = _unb64(signature_part)
        except (ValueError, TypeError) as exc:
            raise PlanOperationError("malformed semantic preview token") from exc
        expected = hmac.digest(self.secret, payload, "sha256")
        if not hmac.compare_digest(signature, expected):
            raise PlanOperationError("semantic preview token authentication failed")
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PlanOperationError(
                "semantic preview token payload is malformed"
            ) from exc
        if (
            set(raw)
            != {
                "draft_id",
                "expected_revision_id",
                "operation",
                "schema",
            }
            or raw.get("schema") != PREVIEW_SCHEMA
        ):
            raise PlanOperationError("unsupported semantic preview token")
        return (
            str(raw["draft_id"]),
            str(raw["expected_revision_id"]),
            PlanOperationV1.from_data(raw["operation"]),
        )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    decoded = base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )
    if _b64(decoded) != value:
        raise ValueError("noncanonical base64url encoding")
    return decoded


def load_owner_facts(
    path: Path | None,
) -> dict[str, tuple[ExternalArtifactReferenceV1, ...]]:
    if path is None:
        return {}
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict) or raw.get("schema") != OWNER_FACTS_SCHEMA:
        raise ValueError("unsupported design owner-facts fixture schema")
    if set(raw) != {"schema", "drafts"} or not isinstance(raw["drafts"], dict):
        raise ValueError("owner-facts fixture is malformed")
    result: dict[str, tuple[ExternalArtifactReferenceV1, ...]] = {}
    for draft_id, values in raw["drafts"].items():
        if not isinstance(values, list):
            raise ValueError("owner-facts draft value must be an array")
        references = []
        for value in values:
            if not isinstance(value, dict) or set(value) != {
                "kind",
                "owner",
                "plan_digest",
                "reference_id",
                "schema",
            }:
                raise ValueError("owner-facts reference is malformed")
            if value["schema"] != ARTIFACT_REFERENCE_SCHEMA:
                raise ValueError("owner-facts reference schema is unsupported")
            if not isinstance(value["plan_digest"], str) or not (
                value["plan_digest"].startswith("sha256:")
                and len(value["plan_digest"]) == 71
                and all(
                    character in "0123456789abcdef"
                    for character in value["plan_digest"][7:]
                )
            ):
                raise ValueError("owner-facts plan digest is malformed")
            references.append(
                ExternalArtifactReferenceV1(
                    kind=value["kind"],
                    owner=value["owner"],
                    plan_digest=value["plan_digest"],
                    reference_id=value["reference_id"],
                    schema=value["schema"],
                )
            )
        result[str(draft_id)] = tuple(references)
    return result


def load_governed_cross_probe(
    path: Path | None,
) -> dict[str, tuple[GovernedNodeBindingV1, ...]]:
    if path is None:
        return {}
    raw = path.read_bytes()
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("governed cross-probe projection is oversized")
    return parse_cross_probe(json.loads(raw))


class DesignApplication:
    def __init__(
        self,
        store: DraftStore,
        presentations: PresentationStore,
        proposal_store: ProposalStore | None = None,
        *,
        inspect_url: str = "http://127.0.0.1:8417/phosphor-ng",
        owner_facts: dict[str, tuple[ExternalArtifactReferenceV1, ...]] | None = None,
        governed_cross_probe: dict[
            str, tuple[GovernedNodeBindingV1, ...]
        ]
        | None = None,
        secret: bytes | None = None,
        enrolled_provider: SwitchyardProposalProvider | None = None,
    ) -> None:
        self.store = store
        self.presentations = presentations
        self.proposal_store = proposal_store or ProposalStore(
            store.path.with_name(store.path.stem + "-proposals.sqlite")
        )
        self.proposal_service = ProposalService(store, self.proposal_store)
        self.inspect_url = inspect_url
        self.owner_facts = owner_facts or {}
        self.governed_cross_probe = governed_cross_probe or {}
        self.secret = secret or secrets.token_bytes(32)
        self.csrf_token = _b64(
            hmac.digest(self.secret, b"csrf:/phosphor/design", "sha256")
        )
        self.preview_codec = PreviewCodec(self.secret)
        self.enrolled_provider = enrolled_provider

    def _projection(self, draft_id: str):
        return self.store.projection(
            draft_id, external_references=self.owner_facts.get(draft_id, ())
        )

    def _presentation(self, revision) -> Any:
        presentation = self.presentations.load(revision.draft_id)
        if presentation is None:
            presentation = PlanPresentationV2(
                revision.draft_id,
                revision.revision_id,
                selected_node_id=(
                    None
                    if not revision.document.nodes
                    else revision.document.nodes[0].node_id
                ),
                selected_object_kind=(
                    "document" if not revision.document.nodes else "node"
                ),
                selected_object_id=(
                    None
                    if not revision.document.nodes
                    else revision.document.nodes[0].node_id
                ),
                version=0,
            )
        return project_presentation(
            presentation, revision.document, revision.revision_id
        )

    def get(self, target: str) -> Response:
        url = urlsplit(target)
        path = url.path.rstrip("/") or "/"
        query = parse_qs(url.query, keep_blank_values=True)
        if path == "/":
            return Response.redirect("/phosphor/design")
        if path == "/phosphor/design/style.css":
            return Response(
                200, "text/css; charset=utf-8", render.STYLE.encode("utf-8")
            )
        if path == "/phosphor/design":
            revisions = self.store.list_drafts()
            projections = {
                item.draft_id: self._projection(item.draft_id).to_data()
                for item in revisions
            }
            return Response.html(
                200,
                render.index_page(
                    revisions, projections, self.csrf_token, self.inspect_url
                ),
            )
        if path == "/phosphor/design/api/v1/drafts":
            return Response.json(
                200,
                {
                    "drafts": [item.to_data() for item in self.store.list_drafts()],
                    "schema": "maude.plan-design-draft-index/v1",
                },
            )
        proposal_match = _proposal_path(path)
        if proposal_match is not None:
            draft_id, proposal_id, api = proposal_match
            try:
                projection = self.proposal_service.project(proposal_id)
                if projection.proposal.draft_id != draft_id:
                    raise ProposalError("proposal belongs to another draft")
                request = self.proposal_store.request(projection.proposal.request_id)
                if api:
                    return Response.json(
                        200,
                        {
                            "projection": projection.to_data(),
                            "request": request.to_data(),
                            "schema": "maude.plan-edit-proposal-review/v1",
                        },
                    )
                return Response.html(
                    200,
                    render.proposal_page(
                        projection, request, self.csrf_token, self.inspect_url
                    ),
                )
            except (
                DraftNotFound,
                ProposalError,
                ProposalStoreError,
                ValueError,
            ) as exc:
                return Response.html(
                    404,
                    render.error_page(
                        "Proposal unavailable", str(exc), self.inspect_url
                    ),
                )
        match = _draft_path(path)
        if match is None:
            return Response.html(
                404, render.error_page("Not found", path, self.inspect_url)
            )
        draft_id, suffix = match
        try:
            revision = self.store.current(draft_id)
            projection = self._projection(draft_id)
            presentation = self._presentation(revision)
            if suffix == "/api/v1":
                return Response.json(
                    200,
                    {
                        "document": revision.document.to_data(),
                        "lifecycle": projection.to_data(),
                        "presentation": presentation.to_data(),
                        "proposals": [
                            self.proposal_service.project(item.proposal_id).to_data()
                            for item in self.proposal_store.proposals(draft_id)
                        ],
                        "proposal_refusals": [
                            item.to_data()
                            for item in self.proposal_store.generation_refusals(
                                draft_id
                            )
                        ],
                        "governed_node_bindings": [
                            item.to_data()
                            for item in self.governed_cross_probe.get(draft_id, ())
                        ],
                        "revision": revision.to_data(),
                        "schema": "maude.plan-design-workspace/v2",
                    },
                )
            if suffix:
                return Response.html(
                    404, render.error_page("Not found", path, self.inspect_url)
                )
            parent = (
                None
                if revision.parent_revision_id is None
                else self.store.revision(revision.parent_revision_id)
            )
            selected = query.get("node", [None])[-1]
            finding = query.get("finding", [None])[-1]
            return Response.html(
                200,
                render.workspace_page(
                    revision,
                    parent,
                    self.store.revisions(draft_id),
                    projection,
                    presentation,
                    self.csrf_token,
                    self.inspect_url,
                    selected_override=selected,
                    selected_finding=finding,
                    proposals=tuple(
                        self.proposal_service.project(item.proposal_id)
                        for item in self.proposal_store.proposals(draft_id)
                    ),
                    proposal_refusals=self.proposal_store.generation_refusals(draft_id),
                    provider_scenarios=FIXTURE_SCENARIOS + (("enrolled-switchyard",) if self.enrolled_provider is not None else ()),
                    proposal_generation_id="generation_" + secrets.token_hex(16),
                    governed_node_bindings=self.governed_cross_probe.get(
                        draft_id, ()
                    ),
                ),
            )
        except (PresentationError, sqlite3.Error) as exc:
            return Response.html(
                503,
                render.error_page(
                    "Presentation state unavailable",
                    f"The separate presentation sidecar could not be read: {exc}. PlanDocument semantic state was not changed.",
                    self.inspect_url,
                    status="warning",
                ),
            )
        except (DraftNotFound, ValueError) as exc:
            return Response.html(
                404, render.error_page("Draft unavailable", str(exc), self.inspect_url)
            )

    def post(self, target: str, values: Mapping[str, list[str]]) -> Response:
        path = urlsplit(target).path.rstrip("/")
        form = Form(values)
        if not hmac.compare_digest(form.one("csrf", default=""), self.csrf_token):
            return Response.html(
                403,
                render.error_page(
                    "CSRF refusal",
                    "The local design service refused an unauthenticated form submission.",
                    self.inspect_url,
                ),
            )
        try:
            if path == "/phosphor/design/drafts/new":
                document = PlanDocumentV1(
                    goal=form.one("goal"),
                    workspace=form.one("workspace", default=""),
                    submitter=SubmitterV1("human", "human_written", "local-operator"),
                    nodes=(PlanNodeV1(new_node_id(), "Describe the first exact step"),),
                )
                revision = self.store.create(document)
                return Response.redirect(
                    f"/phosphor/design/drafts/{quote(revision.draft_id)}"
                )
            proposal_action = _proposal_action(path)
            if proposal_action is not None:
                draft_id, proposal_id, action = proposal_action
                if action == "generate":
                    expected = form.one("expected_revision_id")
                    revision = self.store.revision(expected)
                    if revision.draft_id != draft_id:
                        raise DraftConflict(
                            "proposal revision belongs to another draft"
                        )
                    scenario = form.one("provider_scenario")
                    if scenario == "enrolled-switchyard":
                        if self.enrolled_provider is None:
                            raise ProposalError("enrolled Switchyard provider is not configured")
                        provider = self.enrolled_provider
                    else:
                        if scenario not in FIXTURE_SCENARIOS:
                            raise ProposalError("unknown provider fixture")
                        provider = DeterministicFixtureProvider(scenario)
                    scope_kind = form.one("scope_kind")
                    target_node = form.one("target_node_id", default="").strip()
                    finding_id = form.one("finding_id", default="").strip()
                    findings: tuple[ProposalFindingContextV1, ...] = ()
                    if scope_kind == "finding":
                        canonical = {
                            finding.finding_id: finding
                            for receipt in self._projection(draft_id).checks
                            if receipt.applicability.value
                            in {"current_pass", "current_findings"}
                            for finding in receipt.receipt.findings
                        }.get(finding_id)
                        if canonical is None:
                            raise ProposalError(
                                "selected finding is not currently applicable"
                            )
                        findings = (ProposalFindingContextV1.from_finding(canonical),)
                        node_ids = (
                            ()
                            if canonical.target.node_id is None
                            else (canonical.target.node_id,)
                        )
                        scope = ProposalScopeV1(
                            "exact_finding",
                            ("update_document" if not node_ids else "update_node",),
                            node_ids,
                            tuple(sorted(NODE_FIELDS)) if node_ids else (),
                            tuple(sorted(DOCUMENT_FIELDS)) if not node_ids else (),
                            finding_id,
                        )
                    elif scope_kind == "node":
                        scope = ProposalScopeV1(
                            "exact_nodes",
                            ("update_node",),
                            (target_node,),
                            tuple(sorted(NODE_FIELDS)),
                        )
                    elif scope_kind == "document":
                        if scenario == "multi_operation":
                            scope = ProposalScopeV1(
                                "exact_document",
                                ("update_node", "update_document"),
                                allowed_node_fields=tuple(sorted(NODE_FIELDS)),
                                allowed_document_fields=tuple(sorted(DOCUMENT_FIELDS)),
                            )
                        else:
                            scope = ProposalScopeV1(
                                "exact_document",
                                ("update_document",),
                                allowed_document_fields=tuple(sorted(DOCUMENT_FIELDS)),
                            )
                    else:
                        raise ProposalError("unknown proposal scope")
                    request = self.proposal_service.request(
                        draft_id=draft_id,
                        base_revision_id=expected,
                        task=form.one("task"),
                        scope=scope,
                        findings=findings,
                        provider=provider,
                        generation_id=form.one("proposal_generation_id"),
                    )
                    proposal = self.proposal_service.generate(request, provider)
                    return Response.redirect(
                        f"/phosphor/design/drafts/{quote(draft_id)}/proposals/{quote(proposal.proposal_id)}"
                    )
                if proposal_id is None:
                    raise ProposalError("proposal identity is required")
                proposal = self.proposal_store.proposal(proposal_id)
                if proposal.draft_id != draft_id:
                    raise ProposalError("proposal belongs to another draft")
                if action == "accept":
                    self.proposal_service.accept(
                        proposal_id, accepting_actor="local-browser-operator"
                    )
                else:
                    self.proposal_service.reject(
                        proposal_id,
                        rejecting_actor="local-browser-operator",
                        reason=form.one("reason"),
                    )
                return Response.redirect(
                    f"/phosphor/design/drafts/{quote(draft_id)}/proposals/{quote(proposal_id)}"
                )
            match = _draft_action(path)
            if match is None:
                return Response.html(
                    404, render.error_page("Not found", path, self.inspect_url)
                )
            draft_id, action = match
            if action == "preview":
                expected = form.one("expected_revision_id")
                revision = self.store.revision(expected)
                if revision.draft_id != draft_id:
                    raise DraftConflict("revision belongs to another draft")
                if self.store.current(draft_id).revision_id != expected:
                    raise DraftConflict(
                        "the working draft changed; preview was not retargeted"
                    )
                operation = operation_from_form(form, revision.document)
                preview = apply_plan_operation(revision.document, operation)
                token = self.preview_codec.encode(draft_id, expected, operation)
                return Response.html(
                    200,
                    render.preview_page(
                        revision,
                        preview.document,
                        preview.diff,
                        token,
                        self.csrf_token,
                        self.inspect_url,
                    ),
                )
            if action == "apply":
                token_draft, expected, operation = self.preview_codec.decode(
                    form.one("preview_token")
                )
                if token_draft != draft_id:
                    raise DraftConflict("preview token belongs to another draft")
                base = self.store.revision(expected)
                if base.draft_id != draft_id:
                    raise DraftConflict("preview revision belongs to another draft")
                preview = apply_plan_operation(base.document, operation)
                try:
                    saved = self.store.save_successor(
                        draft_id,
                        expected,
                        preview.document,
                        edit_origin=EditOrigin.HUMAN,
                    )
                except DraftConflict:
                    current = self.store.current(draft_id)
                    return Response.html(
                        409,
                        render.stale_preview_page(
                            current=current,
                            reviewed_revision=base,
                            diff=preview.diff,
                            inspect_url=self.inspect_url,
                        ),
                    )
                return Response.redirect(
                    f"/phosphor/design/drafts/{quote(draft_id)}?saved={quote(saved.revision_id)}"
                )
            if action in {"check", "lock"}:
                expected = form.one("expected_revision_id")
                if self.store.current(draft_id).revision_id != expected:
                    raise DraftConflict(
                        f"stale {action} target refused; reload the exact working revision"
                    )
                if action == "check":
                    self.store.check(draft_id, expected)
                else:
                    self.store.lock(draft_id, expected)
                return Response.redirect(f"/phosphor/design/drafts/{quote(draft_id)}")
            if action == "presentation":
                current = self.store.current(draft_id)
                selected = form.one("selected_node_id", default="").strip() or None
                collapsed = _lines(form.one("collapsed_node_ids", default=""))
                try:
                    expected_version = int(form.one("expected_version"))
                    outline_percent = int(form.one("outline_percent"))
                except ValueError as exc:
                    raise PresentationError(
                        "presentation numeric fields are invalid"
                    ) from exc
                if expected_version == 0 and self.presentations.load(draft_id) is None:
                    expected: int | None = None
                else:
                    expected = expected_version
                return_anchor = form.one("return_anchor", default="active-case")
                if return_anchor not in {"active-case", "casework"}:
                    raise PresentationError("presentation return anchor is invalid")
                saved = self.presentations.save(
                    PlanPresentationV2(
                        draft_id=draft_id,
                        semantic_revision_id=form.one("semantic_revision_id"),
                        selected_node_id=selected,
                        collapsed_node_ids=collapsed,
                        outline_percent=outline_percent,
                        active_detail_tab=form.one("active_detail_tab"),
                        active_casework_tab=form.one(
                            "active_casework_tab", default="findings"
                        ),
                        selected_object_kind=form.one(
                            "selected_object_kind",
                            default="node" if selected else "document",
                        ),
                        selected_object_id=form.one(
                            "selected_object_id", default=""
                        ).strip()
                        or None,
                        version=max(expected_version, 1),
                    ),
                    expected_version=expected,
                )
                node_query = "" if selected is None else f"?node={quote(selected)}"
                return Response.redirect(
                    f"/phosphor/design/drafts/{quote(current.draft_id)}{node_query}#{return_anchor}"
                )
            return Response.html(
                404, render.error_page("Not found", action, self.inspect_url)
            )
        except DraftConflict as exc:
            return Response.html(
                409,
                render.error_page(
                    "Stale edit refused",
                    f"{exc}. Your operation remains represented by the reviewed preview; reload and reapply deliberately.",
                    self.inspect_url,
                    status="warning",
                ),
            )
        except PresentationConflict as exc:
            return Response.html(
                409,
                render.error_page(
                    "Presentation changed",
                    f"{exc}. Semantic PlanDocument state was not changed.",
                    self.inspect_url,
                    status="warning",
                ),
            )
        except sqlite3.Error as exc:
            return Response.html(
                503,
                render.error_page(
                    "Presentation persistence unavailable",
                    f"Local artifact persistence failed: {exc}. No fallback, rebase, or alternate write was attempted; inspect exact store state before repeating.",
                    self.inspect_url,
                    status="warning",
                ),
            )
        except (
            DraftNotFound,
            PlanDocumentError,
            PlanOperationError,
            ProposalError,
            ProposalStoreError,
            PresentationError,
            ValueError,
        ) as exc:
            return Response.html(
                400, render.error_page("Edit refused", str(exc), self.inspect_url)
            )


def _draft_path(path: str) -> tuple[str, str] | None:
    prefix = "/phosphor/design/drafts/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :]
    if rest.endswith("/api/v1"):
        return rest[: -len("/api/v1")], "/api/v1"
    if "/" in rest or not rest:
        return None
    return rest, ""


def _proposal_path(path: str) -> tuple[str, str, bool] | None:
    prefix = "/phosphor/design/drafts/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :]
    marker = "/proposals/"
    if marker not in rest:
        return None
    draft_id, tail = rest.split(marker, 1)
    api = tail.endswith("/api/v1")
    proposal_id = tail[: -len("/api/v1")] if api else tail
    if not draft_id or not proposal_id or "/" in proposal_id:
        return None
    return unquote(draft_id), unquote(proposal_id), api


def _proposal_action(path: str) -> tuple[str, str | None, str] | None:
    prefix = "/phosphor/design/drafts/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :]
    marker = "/proposals/"
    if marker not in rest:
        return None
    draft_id, tail = rest.split(marker, 1)
    if tail == "generate":
        return unquote(draft_id), None, "generate"
    if "/" not in tail:
        return None
    proposal_id, action = tail.rsplit("/", 1)
    if action not in {"accept", "reject"} or "/" in proposal_id:
        return None
    return unquote(draft_id), unquote(proposal_id), action


def _draft_action(path: str) -> tuple[str, str] | None:
    prefix = "/phosphor/design/drafts/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :]
    if "/" not in rest:
        return None
    draft_id, action = rest.rsplit("/", 1)
    if "/" in draft_id or action not in {
        "preview",
        "apply",
        "check",
        "lock",
        "presentation",
    }:
        return None
    return draft_id, action


class DesignRequestHandler(BaseHTTPRequestHandler):
    server_version = "PhosphorDesign/1"

    @property
    def application(self) -> DesignApplication:
        return self.server.application  # type: ignore[attr-defined,no-any-return]

    def do_GET(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._write(
                Response.html(
                    400,
                    render.error_page(
                        "Host refused",
                        "Host does not name this loopback service.",
                        self.application.inspect_url,
                    ),
                )
            )
            return
        self._write(self.application.get(self.path), head=False)

    def do_HEAD(self) -> None:  # noqa: N802
        if not self._valid_host():
            self._write(Response.html(400, ""), head=True)
            return
        self._write(self.application.get(self.path), head=True)

    def do_POST(self) -> None:  # noqa: N802
        if not self._valid_host() or not self._valid_origin():
            self._write(
                Response.html(
                    403,
                    render.error_page(
                        "Origin refused",
                        "Cross-origin mutation is not accepted.",
                        self.application.inspect_url,
                    ),
                )
            )
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type != "application/x-www-form-urlencoded":
            self._write(
                Response.html(
                    415,
                    render.error_page(
                        "Media type refused",
                        "Use an exact form-encoded typed operation.",
                        self.application.inspect_url,
                    ),
                )
            )
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_REQUEST_BYTES:
            self._write(
                Response.html(
                    413,
                    render.error_page(
                        "Request refused",
                        "Request body exceeds the bounded local service limit.",
                        self.application.inspect_url,
                    ),
                )
            )
            return
        body = self.rfile.read(length)
        try:
            values = parse_qs(
                body.decode("utf-8"), keep_blank_values=True, strict_parsing=True
            )
        except (UnicodeDecodeError, ValueError) as exc:
            self._write(
                Response.html(
                    400,
                    render.error_page(
                        "Malformed form", str(exc), self.application.inspect_url
                    ),
                )
            )
            return
        self._write(self.application.post(self.path, values))

    def do_PUT(self) -> None:  # noqa: N802
        self._method_refused()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_refused()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_refused()

    def _method_refused(self) -> None:
        self._write(
            Response.html(
                405,
                render.error_page(
                    "Method refused",
                    "Only GET, HEAD, and closed Plan Core POST operations exist.",
                    self.application.inspect_url,
                ),
            )
        )

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in self.server.allowed_hosts  # type: ignore[attr-defined]

    def _valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.server.allowed_origins  # type: ignore[attr-defined]

    def _write(self, response: Response, *, head: bool = False) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        # Basic form POSTs under no-referrer can carry Origin: null, which our
        # same-origin mutation boundary correctly refuses. Keep the local
        # origin usable while still withholding referrers across origins.
        self.send_header("Referrer-Policy", "same-origin")
        if response.location is not None:
            self.send_header("Location", response.location)
        self.end_headers()
        if not head:
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


class DesignServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, address: tuple[str, int], application: DesignApplication
    ) -> None:
        super().__init__(address, DesignRequestHandler)
        self.application = application
        host, port = self.server_address[:2]
        names = {f"{host}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
        if host == "::1":
            names.add(f"[::1]:{port}")
        self.allowed_hosts = names
        self.allowed_origins = {f"http://{item}" for item in names}


def serve(address: tuple[str, int], application: DesignApplication) -> None:
    ip = ipaddress.ip_address(address[0])
    if not ip.is_loopback:
        raise ValueError("Phosphor-ng /design must bind to a loopback address")
    with DesignServer(address, application) as server:
        print(
            f"Phosphor-ng Design listening at http://{address[0]}:{address[1]}/phosphor/design"
        )
        server.serve_forever()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="phosphor-design",
        description="Maude-owned loopback PlanDocument design workspace",
    )
    result.add_argument("--store", type=Path, default=Path(".maude/plans.sqlite"))
    result.add_argument(
        "--presentation-store",
        type=Path,
        default=Path(".maude/plan-presentations.sqlite"),
    )
    result.add_argument(
        "--proposal-store",
        type=Path,
        default=Path(".maude/plan-edit-proposals.sqlite"),
    )
    result.add_argument("--owner-facts", type=Path)
    result.add_argument("--governed-cross-probe", type=Path)
    result.add_argument("--inspect-url", default="http://127.0.0.1:8417/phosphor-ng")
    result.add_argument("--bind", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8427)
    result.add_argument("--switchyard-profile", type=Path)
    result.add_argument("--switchyard-state", type=Path)
    result.add_argument("--switchyard-credential-file", type=Path,
                        default=Path.home() / ".config/constellation/openrouter.env")
    return result


def main() -> None:
    args = parser().parse_args()
    enrolled = None
    if (args.switchyard_profile is None) != (args.switchyard_state is None):
        raise SystemExit("--switchyard-profile and --switchyard-state must be supplied together")
    if args.switchyard_profile is not None:
        profile_data = json.loads(args.switchyard_profile.read_text(encoding="utf-8"))
        if not isinstance(profile_data, dict):
            raise SystemExit("Switchyard profile must be an object")
        profile = SwitchyardProposalProfileV1(**profile_data)
        enrolled = SwitchyardProposalProvider.from_switchyard_state(profile, args.switchyard_state,
                                                                      credential_source=dedicated_credential_loader(args.switchyard_credential_file))
    application = DesignApplication(
        DraftStore(args.store),
        PresentationStore(args.presentation_store),
        ProposalStore(args.proposal_store),
        inspect_url=args.inspect_url,
        owner_facts=load_owner_facts(args.owner_facts),
        governed_cross_probe=load_governed_cross_probe(
            args.governed_cross_probe
        ),
        enrolled_provider=enrolled,
    )
    try:
        serve((args.bind, args.port), application)
    except KeyboardInterrupt:
        print("\nPhosphor-ng Design stopped")


if __name__ == "__main__":
    main()

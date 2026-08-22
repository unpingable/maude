# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from maude.custody import (
    AUTH_SCHEMA_V1,
    CustodyError,
    MaudeCustodyStoreV1,
    HandoffProducerProfileV1,
    MAX_PLAN_BYTES,
    MaudeHandoffStoreV1,
    SessionCustodyProfileV1,
    _canonical,
    _read_exact_file,
    _strict_json,
    read_protected_key,
)


PLAN = b"---\r\nplan_version: 1\r\n---\r\nexact bytes\r\n"
REQUEST_A = "sha256:" + hashlib.sha256(b"request-a").hexdigest()
REQUEST_B = "sha256:" + hashlib.sha256(b"request-b").hexdigest()


@dataclass(frozen=True)
class Profiles:
    session: SessionCustodyProfileV1
    handoff: HandoffProducerProfileV1


@pytest.fixture
def profile(tmp_path: Path) -> Profiles:
    session_key = tmp_path / "session.key"
    session_key.write_bytes(bytes(range(32)))
    session_key.chmod(0o600)
    producer_key = tmp_path / "producer.key"
    producer_key.write_bytes(bytes(reversed(range(32))))
    producer_key.chmod(0o600)
    store = tmp_path / "custody.sqlite"
    return Profiles(
        session=SessionCustodyProfileV1(
            store,
            session_key,
            "maude:supervisor",
            "maude-session-key:primary",
        ),
        handoff=HandoffProducerProfileV1(
            store,
            producer_key,
            "maude-handoff:local",
            "maude-handoff-key:primary",
            "maude:supervisor",
            "maude-session-key:primary",
        ),
    )


def _record(profile: Profiles, session: str = "sess_0123456789ab") -> dict:
    with MaudeCustodyStoreV1(profile.session) as store:
        return store.record_session(session, PLAN, recorded_at="2026-08-21T12:00:00Z")


def test_exact_session_plan_record_survives_reopen_and_duplicate_is_idempotent(profile):
    first = _record(profile)
    with MaudeCustodyStoreV1(profile.session) as reopened:
        assert reopened.get_session("sess_0123456789ab") == first
        duplicate = reopened.record_session(
            "sess_0123456789ab", PLAN, recorded_at="2099-01-01T00:00:00Z"
        )
    assert duplicate == first
    assert first["maude_plan_ref"] == "sha256:" + hashlib.sha256(PLAN).hexdigest()
    assert first["source_plan_bytes"] == len(PLAN)
    assert first["authentication"]["schema"] == AUTH_SCHEMA_V1


def test_correct_producer_cannot_rebind_recorded_session_to_other_plan(profile):
    _record(profile)
    with MaudeCustodyStoreV1(profile.session) as store:
        with pytest.raises(CustodyError, match="different exact plan"):
            store.record_session("sess_0123456789ab", b"substituted plan\n")


def test_handoff_credential_alone_cannot_mint_or_claim_a_session(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        assert not hasattr(store, "record_session")
        assert not hasattr(MaudeCustodyStoreV1, "seal_handoff")
        with pytest.raises(CustodyError, match="no canonical custody record"):
            store.seal_handoff(
                "sess_unrecorded",
                PLAN,
                REQUEST_A,
                "nightshift:local-c1",
            )


def test_deployment_refuses_one_key_identity_for_both_roles(profile):
    invalid = HandoffProducerProfileV1(
        profile.handoff.store,
        profile.handoff.key_file,
        profile.handoff.producer_principal_id,
        profile.handoff.session_issuer_key_id,
        profile.handoff.session_issuer_principal_id,
        profile.handoff.session_issuer_key_id,
    )
    with pytest.raises(CustodyError, match="must be distinct"):
        invalid.validate()


def test_handoff_binds_session_plan_target_and_runtime_and_resends_exactly(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        first = store.seal_handoff(
            "sess_0123456789ab",
            PLAN,
            REQUEST_A,
            "nightshift:local-c1",
            created_at="2026-08-21T12:01:00Z",
        )
    with MaudeHandoffStoreV1(profile.handoff) as reopened:
        duplicate = reopened.seal_handoff(
            "sess_0123456789ab",
            PLAN,
            REQUEST_A,
            "nightshift:local-c1",
            created_at="2099-01-01T00:00:00Z",
        )
    assert duplicate == first
    assert duplicate["authoring_context"]["plan_text"].encode() == PLAN
    assert duplicate["target_request_id"] == REQUEST_A


def test_new_supervised_handoff_of_identical_bytes_has_distinct_identity(profile):
    """Artifact identity is not handoff identity; transport replay is not a new handoff."""
    _record(profile, "sess_0123456789ab")
    _record(profile, "sess_fedcba987654")
    with MaudeHandoffStoreV1(profile.handoff) as store:
        first = store.seal_handoff(
            "sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1"
        )
        second = store.seal_handoff(
            "sess_fedcba987654", PLAN, REQUEST_B, "nightshift:local-c1"
        )
    assert first["authoring_context"]["plan_ref"] == second["authoring_context"]["plan_ref"]
    assert first["handoff_id"] != second["handoff_id"]
    assert first["target_request_id"] != second["target_request_id"]


def test_old_handoff_cannot_be_replayed_as_successor_or_other_campaign(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        store.seal_handoff("sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1")
        with pytest.raises(CustodyError, match="conflicting"):
            store.seal_handoff(
                "sess_0123456789ab", PLAN, REQUEST_B, "nightshift:local-c1"
            )


def test_substituted_plan_and_target_runtime_refuse(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        with pytest.raises(CustodyError, match="exact plan bytes"):
            store.seal_handoff(
                "sess_0123456789ab",
                b"substituted\n",
                REQUEST_A,
                "nightshift:local-c1",
            )
        first = store.seal_handoff(
            "sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1"
        )
        assert first["target_runtime_id"] == "nightshift:local-c1"
        with pytest.raises(CustodyError, match="conflicting"):
            store.seal_handoff("sess_0123456789ab", PLAN, REQUEST_A, "nightshift:other")


def test_wrong_or_replaced_credential_refuses_existing_record(profile):
    _record(profile)
    profile.session.key_file.write_bytes(b"z" * 32)
    with MaudeCustodyStoreV1(profile.session) as store:
        with pytest.raises(CustodyError, match="authentication failed"):
            store.get_session("sess_0123456789ab")


def test_replaced_handoff_producer_credential_refuses_exact_resend(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        store.seal_handoff("sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1")
    profile.handoff.key_file.write_bytes(b"z" * 32)
    with MaudeHandoffStoreV1(profile.handoff) as reopened:
        with pytest.raises(CustodyError, match="authentication failed"):
            reopened.seal_handoff(
                "sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1"
            )


def test_wrong_principal_cannot_relabel_existing_session(profile):
    _record(profile)
    other = SessionCustodyProfileV1(
        profile.session.store,
        profile.session.key_file,
        "maude:other",
        profile.session.session_issuer_key_id,
    )
    with MaudeCustodyStoreV1(other) as store:
        with pytest.raises(CustodyError, match="principal mismatch"):
            store.get_session("sess_0123456789ab")


def test_credential_symlink_and_open_permissions_refuse(profile, tmp_path):
    symlink = tmp_path / "linked.key"
    symlink.symlink_to(profile.session.key_file)
    with pytest.raises(CustodyError, match="cannot open"):
        read_protected_key(symlink)
    profile.session.key_file.chmod(0o640)
    with pytest.raises(CustodyError, match="accessible by group or others"):
        read_protected_key(profile.session.key_file)


def test_truncated_malformed_and_trailing_transport_refuse():
    with pytest.raises(CustodyError, match="malformed"):
        _strict_json(b'{"schema":', "handoff")
    with pytest.raises(CustodyError, match="trailing"):
        _strict_json(b'{}\n{"other":true}', "handoff")


def test_exact_transport_rejects_symlinks_and_oversize(tmp_path: Path):
    plan = tmp_path / "plan"
    plan.write_bytes(PLAN)
    linked = tmp_path / "linked-plan"
    linked.symlink_to(plan)
    with pytest.raises(CustodyError, match="cannot open"):
        _read_exact_file(linked, MAX_PLAN_BYTES, "Maude plan")
    plan.write_bytes(b"x" * (MAX_PLAN_BYTES + 1))
    with pytest.raises(CustodyError, match="exceeds"):
        _read_exact_file(plan, MAX_PLAN_BYTES, "Maude plan")


def test_concurrent_conflicting_handoffs_accept_at_most_one(profile):
    _record(profile)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker(target: str) -> None:
        try:
            with MaudeHandoffStoreV1(profile.handoff) as store:
                barrier.wait()
                store.seal_handoff(
                    "sess_0123456789ab", PLAN, target, "nightshift:local-c1"
                )
            result = "accepted"
        except CustodyError:
            result = "refused"
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=worker, args=(target,))
        for target in (REQUEST_A, REQUEST_B)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "refused"]


def test_custody_wire_has_no_governed_authority_material(profile):
    _record(profile)
    with MaudeHandoffStoreV1(profile.handoff) as store:
        handoff = store.seal_handoff(
            "sess_0123456789ab", PLAN, REQUEST_A, "nightshift:local-c1"
        )
    wire = _canonical(handoff).decode()
    for forbidden in (
        "standing",
        "admissibility",
        "authorization",
        "spend",
        "issuance",
        "docket",
        "capability",
    ):
        assert forbidden not in wire


def test_key_is_exact_raw_bytes_not_newline_normalized(profile):
    assert read_protected_key(profile.session.key_file) == bytes(range(32))
    profile.session.key_file.write_bytes(bytes(range(31)) + b"\n")
    assert read_protected_key(profile.session.key_file) == bytes(range(31)) + b"\n"
    profile.session.key_file.write_bytes(bytes(range(32)) + b"\n")
    with pytest.raises(CustodyError, match="exactly 32"):
        read_protected_key(profile.session.key_file)


def test_real_handoff_cli_emits_exact_authenticated_envelope(profile, tmp_path: Path):
    _record(profile)
    plan = tmp_path / "plan.md"
    plan.write_bytes(PLAN)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema": "nightshift.canonical_cycle_request.v1",
                "request_id": REQUEST_A,
                "authoring_context": None,
            }
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "maude.custody",
            "--store",
            str(profile.handoff.store),
            "--key-file",
            str(profile.handoff.key_file),
            "--producer-principal-id",
            profile.handoff.producer_principal_id,
            "--producer-key-id",
            profile.handoff.producer_key_id,
            "--session-issuer-principal-id",
            profile.handoff.session_issuer_principal_id,
            "--session-issuer-key-id",
            profile.handoff.session_issuer_key_id,
            "--session-id",
            "sess_0123456789ab",
            "--plan",
            str(plan),
            "--nightshift-request",
            str(request),
            "--target-runtime-id",
            "nightshift:local-c1",
        ],
        check=True,
        capture_output=True,
    )
    value = _strict_json(completed.stdout, "handoff")
    assert value["target_request_id"] == REQUEST_A
    assert value["authoring_context"]["plan_text"].encode() == PLAN
    assert value["producer_key_id"] != value["session_custody"]["session_issuer_key_id"]

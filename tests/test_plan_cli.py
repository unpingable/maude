# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from maude.plan.cli import run


def invoke(store: Path, capsys, *arguments: str) -> tuple[int, dict]:
    status = run(("--store", str(store), *arguments))
    output = capsys.readouterr().out
    return status, json.loads(output)


def test_new_refuses_unsupported_origin_before_creating_store(tmp_path):
    store = tmp_path / "plans.sqlite"
    with pytest.raises(SystemExit) as error:
        run(("--store", str(store), "new", "--goal", "Inspect a local example",
             "--workspace", "example-workspace", "--origin", "unsupported_origin"))
    assert error.value.code == 2
    assert not store.exists()


def test_read_only_nonexistent_store_refuses_without_creating_artifacts(tmp_path):
    store = tmp_path / "absent" / "plans.sqlite"
    with pytest.raises(FileNotFoundError, match="read-only Plan Core store is absent"):
        run(("--store", str(store), "--read-only", "list"))
    assert not store.parent.exists()


def test_read_only_inspect_preserves_store_bytes_and_projection(tmp_path, capsys):
    store = tmp_path / "plans.sqlite"
    _, created = invoke(
        store,
        capsys,
        "new",
        "--goal",
        "Inspect the existing draft",
        "--workspace",
        "/srv/example",
        "--draft-id",
        "draft_" + "2" * 32,
    )
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    before_mtime_ns = store.stat().st_mtime_ns
    before_entries = {path.name for path in store.parent.iterdir()}
    _, inspected = invoke(store, capsys, "--read-only", "inspect", created["draft_id"])
    assert inspected["schema"] == "maude.plan-lifecycle-projection/v1"
    assert inspected["current_revision"]["revision_id"] == created["revision_id"]
    assert inspected["check_summary"] == "never_checked"
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
    assert store.stat().st_mtime_ns == before_mtime_ns
    assert {path.name for path in store.parent.iterdir()} == before_entries


def test_read_only_list_and_inspect_see_committed_wal_data(tmp_path, capsys):
    store = tmp_path / "plans.sqlite"
    _, first = invoke(
        store, capsys, "new", "--goal", "First draft", "--workspace", "/srv/example",
        "--draft-id", "draft_" + "3" * 32,
    )
    with sqlite3.connect(store) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        _, second = invoke(
            store, capsys, "new", "--goal", "Second draft", "--workspace", "/srv/example",
            "--draft-id", "draft_" + "4" * 32,
        )
        _, listed = invoke(store, capsys, "--read-only", "list")
        assert {item["draft_id"] for item in listed["drafts"]} == {
            first["draft_id"], second["draft_id"]
        }
        _, inspected = invoke(store, capsys, "--read-only", "inspect", second["draft_id"])
        assert inspected["current_revision"]["revision_id"] == second["revision_id"]


def test_read_only_malformed_store_refuses_without_mutation(tmp_path):
    store = tmp_path / "plans.sqlite"
    store.write_bytes(b"not a SQLite database")
    before = (hashlib.sha256(store.read_bytes()).hexdigest(), store.stat().st_mtime_ns)
    with pytest.raises(sqlite3.DatabaseError):
        run(("--store", str(store), "--read-only", "list"))
    assert (hashlib.sha256(store.read_bytes()).hexdigest(), store.stat().st_mtime_ns) == before


def test_read_only_cli_refuses_mutator_without_opening_store(tmp_path):
    store = tmp_path / "plans.sqlite"
    with pytest.raises(SystemExit) as error:
        run(("--store", str(store), "--read-only", "new", "--goal", "no write",
             "--workspace", "/srv/example"))
    assert error.value.code == 2
    assert not store.exists()


def test_headless_create_inspect_check_lock_and_compiler_refusal(tmp_path, capsys):
    store = tmp_path / "plans.sqlite"
    _, created = invoke(
        store,
        capsys,
        "new",
        "--goal",
        "Inspect service",
        "--workspace",
        "/srv/example",
        "--draft-id",
        "draft_" + "1" * 32,
    )
    draft_id = created["draft_id"]
    _, inspected = invoke(store, capsys, "inspect", draft_id)
    assert inspected["check_summary"] == "never_checked"
    _, checked = invoke(store, capsys, "check", draft_id)
    assert checked["result"] == "passed"
    assert len(created["document"]["nodes"]) == 1
    _, locked = invoke(store, capsys, "lock", draft_id)
    assert locked["plan_digest"] == created["plan_digest"]
    status, refused = invoke(
        store, capsys, "handoff", draft_id, "--workflow", "generic"
    )
    assert status == 2
    assert refused["result"] == "compiler_unavailable"


def test_editor_creates_successor_revision_instead_of_mutating(
    tmp_path, capsys, monkeypatch
):
    store = tmp_path / "plans.sqlite"
    _, created = invoke(
        store,
        capsys,
        "new",
        "--goal",
        "Before",
        "--workspace",
        "/srv/example",
    )
    code = (
        "import json,sys; p=sys.argv[1]; d=json.load(open(p)); "
        "d['goal']='After'; open(p,'w',encoding='utf-8',newline='').write(json.dumps(d))"
    )
    monkeypatch.setenv("EDITOR", f'{sys.executable} -c "{code}"')
    # shlex cannot preserve the quoted semicolon expression portably through an
    # environment variable, so exercise the same CLI editor helper directly.
    from maude.plan.cli import edit_with_editor
    from maude.plan.store import DraftStore

    draft_store = DraftStore(store)
    revised = edit_with_editor(
        draft_store,
        created["draft_id"],
        editor=(sys.executable, "-c", code),
    )
    assert revised.ordinal == 2
    assert revised.document.goal == "After"
    revisions = draft_store.revisions(created["draft_id"])
    assert revisions[0].document.goal == "Before"
    assert revisions[0].plan_digest != revisions[1].plan_digest


def test_human_and_agent_file_saves_use_same_revision_schema(tmp_path, capsys):
    store = tmp_path / "plans.sqlite"
    _, created = invoke(
        store,
        capsys,
        "new",
        "--goal",
        "Initial",
        "--workspace",
        "/srv/example",
    )
    source = created["document"]
    source["goal"] = "Human edit"
    document_path = tmp_path / "human.json"
    document_path.write_text(json.dumps(source), encoding="utf-8")
    _, human = invoke(
        store,
        capsys,
        "save",
        created["draft_id"],
        str(document_path),
        "--expected-revision",
        created["revision_id"],
        "--origin",
        "human",
    )
    source["goal"] = "Agent edit"
    document_path.write_text(json.dumps(source), encoding="utf-8")
    _, agent = invoke(
        store,
        capsys,
        "save",
        created["draft_id"],
        str(document_path),
        "--expected-revision",
        human["revision_id"],
        "--origin",
        "agent",
    )
    assert human["document"]["schema"] == agent["document"]["schema"]
    assert human.keys() == agent.keys()
    assert human["edit_origin"] == "human"
    assert agent["edit_origin"] == "agent"

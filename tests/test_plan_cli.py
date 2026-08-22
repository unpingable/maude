# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import sys
from pathlib import Path

from maude.plan.cli import run


def invoke(store: Path, capsys, *arguments: str) -> tuple[int, dict]:
    status = run(("--store", str(store), *arguments))
    output = capsys.readouterr().out
    return status, json.loads(output)


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

# SPDX-License-Identifier: Apache-2.0
"""Server-rendered Phosphor-ng /design presentation."""

from __future__ import annotations

import json
from html import escape
from typing import Any, Iterable
from urllib.parse import quote, urlsplit

from maude.design.presentation import PresentationProjectionV2
from maude.plan.diff import PlanDiffV1
from maude.plan.cross_probe import GovernedNodeBindingV1
from maude.plan.document import PlanDocumentV1, PlanNodeV1
from maude.plan.proposal_service import ProposalProjectionV1
from maude.plan.proposal_store import GenerationRefusalV1
from maude.plan.proposals import PlanEditProposalRequestV1
from maude.plan.store import DraftProjectionV1, DraftRevisionV1

STYLE = r"""
:root{color-scheme:dark;--bg:#090d12;--surface:#0e141b;--panel:#121a23;--raised:#18222d;--line:#2a3745;--text:#e7edf4;--muted:#95a5b6;--fact:#86d4c8;--projection:#9abdf5;--unknown:#f1c76f;--bad:#ff9b9b;--accent:#c8a7f6;--focus:#72b7ff;--edit:#8bd5ff;--lock:#edc777}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}a{color:#9dccff;text-underline-offset:.18em}a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--focus);outline-offset:2px}.skip{position:absolute;left:-10000px}.skip:focus{left:.75rem;top:.75rem;z-index:30;background:var(--raised);padding:.5rem}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:1rem;padding:.7rem 1.1rem;background:#0b1017f4;border-bottom:1px solid var(--line)}.brand{color:var(--text);font:700 .95rem/1 ui-sans-serif,system-ui;text-decoration:none}.nav{display:flex;gap:.25rem}.nav a{padding:.3rem .5rem;border-radius:4px;text-decoration:none;color:var(--muted)}.nav a[aria-current=true]{background:#241b32;color:var(--text)}.trust{margin-left:auto;color:var(--muted);font-size:.73rem}.trust strong{color:var(--edit)}main{max-width:1640px;margin:auto;padding:1rem 1.1rem 4rem}h1,h2,h3{font-family:Inter,ui-sans-serif,system-ui;margin-top:0}h1{font-size:1.35rem;margin-bottom:.25rem;overflow-wrap:anywhere}h2{font-size:.98rem;margin-bottom:.6rem}h3{font-size:.83rem;margin:.9rem 0 .45rem}.lede,.muted{color:var(--muted)}.eyebrow{font-size:.68rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);font-weight:750}.identity-strip{display:grid;grid-template-columns:minmax(18rem,2fr) repeat(3,minmax(11rem,1fr));gap:.6rem;margin:.8rem 0}.identity-cell,.panel{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:.78rem;min-width:0}.identity-cell strong{display:block;font:650 .94rem/1.35 ui-sans-serif,system-ui;overflow-wrap:anywhere}.label{display:block;color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.18rem}.mono{overflow-wrap:anywhere}.compact{font-size:.74rem}.workspace{display:grid;grid-template-columns:minmax(19rem,var(--outline,36%)) minmax(26rem,1fr);grid-template-areas:'outline detail' 'lower lower';gap:.7rem;align-items:start}.outline{grid-area:outline;padding:0;overflow:hidden}.detail{grid-area:detail}.lower{grid-area:lower}.panel-head{display:flex;align-items:baseline;justify-content:space-between;gap:.6rem;padding:.72rem .78rem;border-bottom:1px solid var(--line)}.panel-head h2{margin:0}.node-list{list-style:none;padding:0;margin:0;max-height:56rem;overflow:auto}.node{border-top:1px solid #202c38}.node:first-child{border-top:0}.node-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:.45rem;align-items:start;padding:.58rem .62rem}.node.selected{background:#211b2d;box-shadow:inset 3px 0 0 var(--accent)}.select-form,.inline-form{display:inline;margin:0}.link-button{appearance:none;border:0;background:none;color:#9dccff;padding:0;text-align:left;font:inherit;text-decoration:underline;text-underline-offset:.18em;cursor:pointer}.node-label{font:650 .86rem/1.3 ui-sans-serif,system-ui;overflow-wrap:anywhere}.node-id{color:var(--muted);font-size:.68rem;overflow-wrap:anywhere}.node-meta{display:flex;gap:.3rem;flex-wrap:wrap;margin-top:.28rem}.node-deps{padding:.1rem .62rem .58rem 2.3rem;color:var(--muted);font-size:.72rem;overflow-wrap:anywhere}.badge{display:inline-block;padding:.08rem .38rem;border:1px solid #465766;border-radius:999px;color:#b8c5d2;font-size:.62rem;text-transform:uppercase;letter-spacing:.045em}.badge.finding{border-color:#7a5331;color:var(--unknown)}.badge.work{border-color:#356b64;color:var(--fact)}.badge.lock{border-color:#6e6036;color:var(--lock)}.badge.stale{border-color:#715d31;color:var(--unknown)}.badge.pass{border-color:#356b64;color:var(--fact)}.toolbar{display:flex;gap:.35rem;flex-wrap:wrap;align-items:center}.toolbar form{margin:0}button,.button{border:1px solid #405365;border-radius:5px;background:#18232e;color:var(--text);padding:.38rem .62rem;font:650 .75rem/1.2 ui-sans-serif,system-ui;cursor:pointer;text-decoration:none}button:hover,.button:hover{background:#22313f}button.danger{border-color:#744443;color:#ffb0ac;background:#251718}button.lock-action{border-color:#6e6036;color:#f1d48a;background:#241f14}form.editor{display:grid;gap:.55rem}.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem}.field-grid .wide{grid-column:1/-1}label{display:grid;gap:.22rem;color:var(--muted);font-size:.72rem}input,textarea,select{width:100%;border:1px solid #364858;border-radius:4px;background:#0b1118;color:var(--text);padding:.45rem .5rem;font:12px/1.45 ui-monospace,SFMono-Regular,monospace}textarea{min-height:5rem;resize:vertical}.deps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.25rem .6rem;border:1px solid #2d3b49;border-radius:4px;padding:.5rem;max-height:11rem;overflow:auto}.deps label{display:flex;gap:.4rem;align-items:flex-start;color:var(--text);overflow-wrap:anywhere}.deps input{width:auto;margin:.2rem 0 0}.hint,.nonclaim{color:var(--muted);font-size:.72rem}.nonclaim{border-left:3px solid var(--projection);background:#111a24;padding:.5rem .6rem}.warning{border:1px solid #715d31;background:#211a10;color:#efd08c;border-radius:5px;padding:.58rem;margin:.55rem 0}.error{border:1px solid #804949;background:#251516;color:#ffb1b1;border-radius:5px;padding:.58rem;margin:.55rem 0}.success{border:1px solid #356b64;background:#10201d;color:#a8e1d8;border-radius:5px;padding:.58rem;margin:.55rem 0}.lower-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.7rem}.lower-grid>section{min-width:0}.receipt-list,.finding-list,.diff-list{list-style:none;padding:0;margin:.2rem 0}.receipt,.finding-row,.diff-row{border-top:1px dotted #344250;padding:.48rem 0;overflow-wrap:anywhere}.receipt:first-child,.finding-row:first-child,.diff-row:first-child{border-top:0}.finding-row.selected{background:#261f13}.finding-row .message{font-family:ui-sans-serif,system-ui}.finding-link{display:block}.drift{display:grid;grid-template-columns:minmax(9rem,12rem) minmax(0,1fr);gap:.3rem .65rem}.drift dt{color:var(--muted)}.drift dd{margin:0;overflow-wrap:anywhere}.raw{margin-top:.55rem;border:1px solid #26313c;border-radius:5px;overflow:hidden}.raw summary{cursor:pointer;padding:.5rem .6rem;background:#101720;color:#b5d4f7}.raw pre{margin:0;max-height:32rem;overflow:auto;padding:.68rem;background:#080b0f;color:#d0dae4;font:11px/1.45 ui-monospace,SFMono-Regular,monospace}.index{display:grid;gap:.55rem}.draft-card{display:grid;grid-template-columns:minmax(18rem,2fr) repeat(3,minmax(10rem,1fr));gap:.65rem;background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:.72rem}.draft-card:hover{background:var(--raised)}.draft-card strong{font-family:ui-sans-serif,system-ui}.preview{max-width:1100px}.preview pre{white-space:pre-wrap;border:1px solid var(--line);background:#080b0f;padding:.75rem;overflow:auto}.actions{display:flex;gap:.5rem;align-items:center;margin-top:.8rem}.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:980px){.identity-strip{grid-template-columns:1fr 1fr}.workspace{grid-template-columns:minmax(17rem,36%) minmax(20rem,1fr)}.lower-grid{grid-template-columns:1fr 1fr}.lower-grid>section:last-child{grid-column:1/-1}.draft-card{grid-template-columns:1fr 1fr}}@media(max-width:760px){.topbar{position:static;flex-wrap:wrap}.trust{width:100%;margin:0}.identity-strip,.workspace,.lower-grid,.field-grid,.draft-card{grid-template-columns:1fr}.workspace{grid-template-areas:'outline' 'detail' 'lower'}.lower-grid>section:last-child{grid-column:auto}main{padding:.75rem}.node-list{max-height:30rem}.deps{grid-template-columns:1fr}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""

STYLE += r"""
.proposal-panel{margin-top:.75rem;border-top:1px solid var(--line);padding-top:.75rem}.proposal-grid{display:grid;grid-template-columns:minmax(18rem,1fr) minmax(22rem,2fr);gap:.7rem}.proposal-list{list-style:none;padding:0;margin:.25rem 0}.proposal-list li{border-top:1px dotted #344250;padding:.48rem 0;overflow-wrap:anywhere}.proposal-list li:first-child{border-top:0}.badge.proposed{border-color:#4d6382;color:var(--projection)}.badge.accepted{border-color:#356b64;color:var(--fact)}.badge.rejected{border-color:#804949;color:var(--bad)}@media(max-width:900px){.proposal-grid{grid-template-columns:1fr}}
"""

STYLE += r"""
.nav a[aria-current=page]{background:#241b32;color:var(--text)}.identity-strip{grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr))}.identity-cell .exact{display:block;margin-top:.2rem;color:var(--muted);font-size:.68rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.case-context{border-left:3px solid var(--accent);background:#151a24;margin-bottom:.75rem;padding:.68rem}.case-context h2{margin:.1rem 0 .25rem}.context-moves{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;margin:.6rem 0}.context-moves .label{margin:0 .25rem 0 0}.casework{padding:0;min-height:15rem}.case-tabs{display:flex;gap:.12rem;overflow-x:auto;padding:.45rem .55rem 0;border-bottom:1px solid var(--line)}.case-tabs form{margin:0}.case-tab{border-color:transparent;border-bottom:2px solid transparent;border-radius:4px 4px 0 0;background:transparent;color:var(--muted);white-space:nowrap}.case-tab[aria-pressed=true]{border-bottom-color:var(--accent);background:#211b2d;color:var(--text)}.case-content{padding:.75rem}.case-summary{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;margin-bottom:.65rem}.case-summary strong{font-family:ui-sans-serif,system-ui}.finding-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.8rem}.finding-group{min-width:0}.history-row{display:grid;grid-template-columns:minmax(7rem,.5fr) minmax(8rem,.6fr) minmax(0,1.5fr);gap:.6rem;align-items:start}.dependency-map{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin:.7rem 0}.dependency-map ul{margin:.15rem 0;padding-left:1.2rem}.object-link{font-family:ui-sans-serif,system-ui;font-weight:650}.onboarding{display:grid;grid-template-columns:repeat(5,minmax(8rem,1fr));gap:.5rem;margin:.8rem 0}.onboarding div{border-left:2px solid var(--line);padding:.45rem .6rem}.onboarding strong{display:block;font-family:ui-sans-serif,system-ui}.proposal-affected{display:flex;gap:.35rem;flex-wrap:wrap}.proposal-affected a,.proposal-affected span{display:inline-block;border:1px solid var(--line);border-radius:4px;padding:.25rem .4rem;text-decoration:none}.case-focus{scroll-margin-top:4rem}.case-focus:focus-visible,#casework:focus-visible{outline:2px solid var(--focus);outline-offset:3px}.selected-marker{color:var(--accent)}@media(max-width:980px){.finding-groups,.dependency-map{grid-template-columns:1fr}.onboarding{grid-template-columns:1fr 1fr}.history-row{grid-template-columns:minmax(7rem,.5fr) minmax(0,1fr)}.history-row>:last-child{grid-column:1/-1}}@media(max-width:760px){.onboarding{grid-template-columns:1fr}.case-tabs{padding-bottom:.2rem}.case-content{padding:.6rem}}
"""


def page(title: str, body: str, *, inspect_url: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · Maude · Plan editor</title><link rel="stylesheet" href="/phosphor/design/style.css"></head><body><a class="skip" href="#main">Skip to workspace</a><header class="topbar"><a class="brand" href="/phosphor/design">Maude</a><nav class="nav" aria-label="Product family"><a aria-current="page" href="/phosphor/design">Plans</a><a href="{escape(inspect_url, quote=True)}">Inspect runs</a></nav><span class="trust"><strong>Plan editor · pre-alpha</strong> · inspecting runs is read-only</span></header><main id="main">{body}</main></body></html>"""


def hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{escape(name)}" value="{escape(value, quote=True)}">'


def _presentation_fields(
    revision: DraftRevisionV1,
    presentation: PresentationProjectionV2,
    *,
    selected_node_id: str | None = None,
    selected_object_kind: str | None = None,
    selected_object_id: str | None = None,
    active_casework_tab: str | None = None,
    collapsed_node_ids: tuple[str, ...] | None = None,
    outline_percent: int | None = None,
    include_outline_percent: bool = True,
) -> str:
    state = presentation.presentation
    node = state.selected_node_id if selected_node_id is None else selected_node_id
    kind = (
        state.selected_object_kind
        if selected_object_kind is None
        else selected_object_kind
    )
    object_id = (
        state.selected_object_id if selected_object_id is None else selected_object_id
    )
    fields = [
        hidden("expected_version", str(state.version)),
        hidden("semantic_revision_id", revision.revision_id),
        hidden("selected_node_id", node or ""),
        hidden(
            "collapsed_node_ids",
            "\n".join(
                state.collapsed_node_ids
                if collapsed_node_ids is None
                else collapsed_node_ids
            ),
        ),
        hidden("active_detail_tab", state.active_detail_tab),
        hidden(
            "active_casework_tab",
            state.active_casework_tab
            if active_casework_tab is None
            else active_casework_tab,
        ),
        hidden("selected_object_kind", kind),
        hidden("selected_object_id", object_id or ""),
    ]
    if include_outline_percent:
        fields.append(
            hidden(
                "outline_percent",
                str(
                    state.outline_percent
                    if outline_percent is None
                    else outline_percent
                ),
            )
        )
    return "".join(fields)


def _presentation_form(
    revision: DraftRevisionV1,
    presentation: PresentationProjectionV2,
    csrf: str,
    label: str,
    *,
    css_class: str = "button",
    selected_node_id: str | None = None,
    selected_object_kind: str | None = None,
    selected_object_id: str | None = None,
    active_casework_tab: str | None = None,
    collapsed_node_ids: tuple[str, ...] | None = None,
    title: str | None = None,
    return_anchor: str = "active-case",
) -> str:
    return (
        f'<form class="inline-form" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/presentation">'
        + hidden("csrf", csrf)
        + hidden("return_anchor", return_anchor)
        + _presentation_fields(
            revision,
            presentation,
            selected_node_id=selected_node_id,
            selected_object_kind=selected_object_kind,
            selected_object_id=selected_object_id,
            active_casework_tab=active_casework_tab,
            collapsed_node_ids=collapsed_node_ids,
        )
        + f'<button class="{escape(css_class, quote=True)}" type="submit"'
        + (
            ""
            if title is None
            else f' title="{escape(title, quote=True)}" aria-label="{escape(title, quote=True)}"'
        )
        + f">{escape(label)}</button></form>"
    )


def short(value: str, width: int = 18) -> str:
    return value if len(value) <= width else f"{value[:width]}…"


def check_label(value: str) -> str:
    """Reader labels only; stored/API check applicability values remain unchanged."""
    return {
        "never_checked": "Not checked yet",
        "current_pass": "Current plan checks passed",
        "current_findings": "Current plan has findings",
        "historical_digest": "Plan changed — check again",
        "retired_checker_or_rules": "Check rules changed — check again",
    }.get(value, f"Unrecognized check state: {value}")


def raw_block(label: str, value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return f'<details class="raw"><summary>{escape(label)}</summary><pre>{escape(rendered)}</pre></details>'


def _inspect_href(inspect_url: str, inspector_path: str) -> str:
    parsed = urlsplit(inspect_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return inspector_path
    return f"{parsed.scheme}://{parsed.netloc}{inspector_path}"


def index_page(
    revisions: Iterable[DraftRevisionV1],
    projections: dict[str, dict[str, Any]],
    csrf: str,
    inspect_url: str,
) -> str:
    cards = []
    for revision in revisions:
        projection = projections[revision.draft_id]
        cards.append(
            f"""<article class="draft-card"><div><a href="/phosphor/design/drafts/{quote(revision.draft_id)}"><strong>{escape(revision.document.goal or "(goal not declared)")}</strong></a><div class="node-id">{escape(revision.draft_id)}</div></div><div><span class="label">working revision</span>R{revision.ordinal} · {escape(short(revision.plan_digest))}</div><div><span class="label">Plan checks</span><span class="badge {("pass" if projection["check_summary"] == "current_pass" else "stale")}">{escape(check_label(projection["check_summary"]))}</span></div><div><span class="label">nodes / lock drift</span>{len(revision.document.nodes)} nodes · {("differs" if projection["working_differs_from_locked"] else "none/current")}</div></article>"""
        )
    empty = (
        ""
        if cards
        else """<section class="panel"><h2>Build and review a plan</h2><div class="onboarding"><div><strong>1 · Create or open</strong><span class="muted">Describe the work you want to do.</span></div><div><strong>2 · Edit steps</strong><span class="muted">Add steps and their dependencies.</span></div><div><strong>3 · Check the plan</strong><span class="muted">Find missing information and dependency errors.</span></div><div><strong>4 · Review changes</strong><span class="muted">Compare what changed between revisions.</span></div><div><strong>5 · Save a fixed snapshot</strong><span class="muted">Keep a specific version; this does not start a run.</span></div></div><p class="nonclaim"><strong>Editing a plan does not run it.</strong> You can edit it yourself or review a proposed edit. Sending it for execution requires a separately supported workflow compiler.</p></section>"""
    )
    body = f"""<div class="eyebrow">Maude · Plan editor · pre-alpha</div><h1>Plans</h1><p class="lede">Describe the work, organize its steps, and check your draft. Passing these checks is not permission to run it.</p>{empty}<section class="panel"><h2>Create a draft</h2><form class="editor" method="post" action="/phosphor/design/drafts/new">{hidden("csrf", csrf)}<div class="field-grid"><label>Goal<input name="goal" required maxlength="4000"></label><label>Workspace<input name="workspace" maxlength="4000"></label></div><button type="submit">Create draft</button></form></section><section class="index" aria-label="Plan Core drafts">{"".join(cards) or '<p class="muted">No plans yet. Create a draft to start editing; nothing will run.</p>'}</section>"""
    return page("Plans", body, inspect_url=inspect_url)


def _node_findings(projection: DraftProjectionV1, node_id: str) -> list[Any]:
    findings = []
    for item in projection.checks:
        if item.applicability.value not in {"current_pass", "current_findings"}:
            continue
        findings.extend(
            finding
            for finding in item.receipt.findings
            if finding.target.node_id == node_id
        )
    return findings


def _outline(
    revision: DraftRevisionV1,
    projection: DraftProjectionV1,
    selected: str | None,
    presentation: PresentationProjectionV2,
    csrf: str,
    proposal_target_counts: dict[str, int],
) -> str:
    collapsed = set(presentation.presentation.collapsed_node_ids)
    rows = []
    for index, node in enumerate(revision.document.nodes):
        findings = _node_findings(projection, node.node_id)
        toggled = set(collapsed)
        if node.node_id in toggled:
            toggled.remove(node.node_id)
        else:
            toggled.add(node.node_id)
        toggle_form = _presentation_form(
            revision,
            presentation,
            csrf,
            "▸" if node.node_id in collapsed else "▾",
            css_class="link-button",
            collapsed_node_ids=tuple(sorted(toggled)),
            title=f"Toggle details for {node.description}",
        )
        select_form = _presentation_form(
            revision,
            presentation,
            csrf,
            node.description,
            css_class="link-button",
            selected_node_id=node.node_id,
            selected_object_kind="node",
            selected_object_id=node.node_id,
        )
        controls = []
        if index > 0:
            controls.append(
                _preview_button(
                    revision,
                    csrf,
                    "reorder_node",
                    node.node_id,
                    str(index - 1),
                    "↑",
                    "Move earlier",
                )
            )
        if index + 1 < len(revision.document.nodes):
            controls.append(
                _preview_button(
                    revision,
                    csrf,
                    "reorder_node",
                    node.node_id,
                    str(index + 1),
                    "↓",
                    "Move later",
                )
            )
        rows.append(
            f"""<li class="node {"selected" if selected == node.node_id else ""}"><div class="node-row"><span>{toggle_form}<span class="node-id">{index + 1:02d}</span></span><div><div class="node-label">{select_form}</div><div class="node-id">{escape(node.node_id)}</div><div class="node-meta">{('<span class="badge work">structured work</span>' if node.work else "")}{(f'<span class="badge finding">{len(findings)} finding(s)</span>' if findings else "")}{(f'<span class="badge proposed">{proposal_target_counts[node.node_id]} proposal(s)</span>' if proposal_target_counts.get(node.node_id) else "")}{(f'<span class="badge">{len(node.depends_on)} dep</span>' if node.depends_on else "")}</div></div><div class="toolbar">{"".join(controls)}</div></div>{("" if node.node_id in collapsed else f'<div class="node-deps">depends on: {escape(", ".join(node.depends_on) or "none")}</div>')}</li>"""
        )
    add = f"""<form class="editor" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/preview"><h3>Add a step</h3>{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("operation_type", "add_node")}<label>Description<input name="description" required maxlength="10000"></label><button type="submit">Review new step</button></form>"""
    return f'<section class="panel outline"><div class="panel-head"><h2>Plan outline</h2><span class="compact muted">ordered · stable IDs</span></div><ol class="node-list">{"".join(rows)}</ol><div class="panel-head">{add}</div></section>'


def _preview_button(
    revision: DraftRevisionV1,
    csrf: str,
    kind: str,
    node_id: str,
    position: str,
    label: str,
    title: str,
) -> str:
    return f"""<form class="inline-form" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/preview">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("operation_type", kind)}{hidden("node_id", node_id)}{hidden("position", position)}<button type="submit" title="{escape(title, quote=True)}" aria-label="{escape(title, quote=True)}">{escape(label)}</button></form>"""


def _lines(values: Iterable[str]) -> str:
    return "\n".join(values)


def _node_editor(
    revision: DraftRevisionV1,
    node: PlanNodeV1,
    projection: DraftProjectionV1,
    csrf: str,
    governed_bindings: tuple[GovernedNodeBindingV1, ...],
    inspect_url: str,
) -> str:
    known = revision.document.nodes
    dep_inputs = "".join(
        f'<label><input type="checkbox" name="depends_on" value="{escape(item.node_id, quote=True)}" {("checked" if item.node_id in node.depends_on else "")}><span>{escape(item.description)}<br><span class="node-id">{escape(item.node_id)}</span></span></label>'
        for item in known
    )
    work = (
        ""
        if node.work is None
        else json.dumps(
            node.work.to_data(), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    findings = _node_findings(projection, node.node_id)
    required_by = tuple(item for item in known if node.node_id in item.depends_on)
    finding_html = "".join(
        f'<li class="finding-row"><span class="badge finding">{escape(item.rule_id)}</span><div class="message">{escape(item.message)}</div><span class="node-id">{escape(item.finding_id)}</span></li>'
        for item in findings
    )
    form = f"""<form class="editor" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/preview">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("operation_type", "update_node")}{hidden("node_id", node.node_id)}<div class="field-grid"><label class="wide">Description<textarea name="description" required>{escape(node.description)}</textarea></label><label class="wide">Steps that must finish first<div class="deps">{dep_inputs}</div></label><label>Acceptance criteria · one per line<textarea name="acceptance_criteria">{escape(_lines(node.acceptance_criteria))}</textarea></label><label>Stop conditions · one per line<textarea name="stop_conditions">{escape(_lines(node.stop_conditions))}</textarea></label><label class="wide">Structured work · exact closed JSON or blank<textarea name="work_json">{escape(work)}</textarea></label></div><div class="toolbar"><button type="submit">Review step changes</button></div></form><form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/preview" class="inline-form">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("operation_type", "remove_node")}{hidden("node_id", node.node_id)}<button class="danger" type="submit">Preview removal</button></form>"""
    depends_on = "".join(
        f'<li><span class="object-link">{escape(item.description)}</span><br><span class="node-id">{escape(item.node_id)}</span></li>'
        for item in known
        if item.node_id in node.depends_on
    )
    required = "".join(
        f'<li><span class="object-link">{escape(item.description)}</span><br><span class="node-id">{escape(item.node_id)}</span></li>'
        for item in required_by
    )
    governed = "".join(
        f'<li class="receipt"><strong>{escape(item.outcome)} settlement</strong> · {("current PlanDocument binding" if item.plan_digest == revision.plan_digest else "historical PlanDocument binding")} · occurrence {escape(item.occurrence_id)}<br><span class="node-id">plan {escape(item.plan_digest)} · work {escape(item.exact_work_identity)} · attempt {escape(item.docket_attempt_id)}</span><br><a href="{escape(_inspect_href(inspect_url, item.inspector_path), quote=True)}">Inspect this run in Phosphor</a>{raw_block("Exact governed cross-probe binding", item.to_data())}</li>'
        for item in governed_bindings
        if item.node_id == node.node_id
    )
    governed_section = f'<h3>Linked run history</h3><ul class="receipt-list">{governed or "<li class=muted>No runtime record links this step to a run.</li>"}</ul>'
    return f'<div id="node-editor" class="eyebrow case-focus">PlanNode</div><h2>{escape(node.description)}</h2><div class="node-id">{escape(node.node_id)}</div><div id="dependencies" class="dependency-map case-focus"><section><h3>Depends on</h3><ul>{depends_on or "<li class=muted>None declared.</li>"}</ul></section><section><h3>Steps that depend on this one</h3><ul>{required or "<li class=muted>No current node depends on this node.</li>"}</ul></section></div>{governed_section}{form}<h3>Current issues for this step</h3><ul class="finding-list">{finding_html or "<li class=muted>No current check findings for this step. See Checks to confirm whether this revision was checked.</li>"}</ul>'


def _document_editor(revision: DraftRevisionV1, csrf: str) -> str:
    doc = revision.document
    requirements = json.dumps(
        [item.to_data() for item in doc.constraints.world_requirements],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    execution = (
        ""
        if doc.execution_request is None
        else json.dumps(
            doc.execution_request.to_data(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    budget = (
        ""
        if doc.constraints.budget_tokens is None
        else str(doc.constraints.budget_tokens)
    )
    return f"""<div id="document-editor" class="eyebrow case-focus">PlanDocument</div><h2>Plan settings</h2><form class="editor" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/preview">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("operation_type", "update_document")}<div class="field-grid"><label class="wide">Goal<textarea name="goal">{escape(doc.goal)}</textarea></label><label class="wide">Workspace<input name="workspace" value="{escape(doc.workspace, quote=True)}"></label><label>Declared write paths · one per line<textarea name="declared_write_paths">{escape(_lines(doc.constraints.declared_write_paths))}</textarea></label><label>Forbidden paths · one per line<textarea name="forbidden_paths">{escape(_lines(doc.constraints.forbidden_paths))}</textarea></label><label>Budget tokens<input type="number" name="budget_tokens" value="{escape(budget, quote=True)}"></label><label>Halt-if declaration<input name="halt_if" value="{escape(doc.constraints.halt_if or "", quote=True)}"></label><label class="wide">Declared world requirements · closed JSON array<textarea name="world_requirements_json">{escape(requirements)}</textarea><span class="hint">Declarations only. A valid declaration does not establish current-world truth.</span></label><label>Document acceptance criteria · one per line<textarea name="acceptance_criteria">{escape(_lines(doc.acceptance_criteria))}</textarea></label><label>Whole-document execution request · exact JSON or blank<textarea name="execution_request_json">{escape(execution)}</textarea></label></div><button type="submit">Review plan changes</button></form>"""


def _findings_panel(
    revision: DraftRevisionV1,
    projection: DraftProjectionV1,
    presentation: PresentationProjectionV2,
    csrf: str,
    selected_finding: str | None,
) -> str:
    current_rows: list[str] = []
    historical_rows: list[str] = []
    selected_locator = (
        presentation.presentation.selected_object_id
        if presentation.presentation.selected_object_kind == "finding"
        else None
    )
    if selected_locator is None and selected_finding:
        candidates = [
            (
                f"{item.receipt.receipt_id}/{finding.finding_id}",
                item.applicability.value,
            )
            for item in projection.checks
            for finding in item.receipt.findings
            if finding.finding_id == selected_finding
        ]
        selected_locator = next(
            (
                locator
                for locator, applicability in reversed(candidates)
                if applicability in {"current_pass", "current_findings"}
            ),
            candidates[-1][0] if candidates else None,
        )
    for receipt_projection in reversed(projection.checks):
        current = receipt_projection.applicability.value in {
            "current_pass",
            "current_findings",
        }
        for finding in receipt_projection.receipt.findings:
            target = finding.target.node_id
            case_locator = (
                f"{receipt_projection.receipt.receipt_id}/{finding.finding_id}"
            )
            selector = _presentation_form(
                revision,
                presentation,
                csrf,
                finding.message,
                css_class="link-button finding-link",
                selected_node_id=target or "",
                selected_object_kind="finding",
                selected_object_id=case_locator,
                active_casework_tab="findings",
            )
            row = f"""<li id="finding-{escape(receipt_projection.receipt.receipt_id)}-{escape(finding.finding_id)}" class="finding-row {"selected" if selected_locator == case_locator else ""}">{selector}<span class="badge finding">{escape(finding.rule_id)}</span> <span class="node-id">target {escape(target or "document")} · {escape(receipt_projection.applicability.value)} · receipt {escape(short(receipt_projection.receipt.receipt_id))}</span></li>"""
            (current_rows if current else historical_rows).append(row)
    return f"""<div class="case-summary"><strong>Findings</strong><span class="badge {("pass" if projection.check_summary.value == "current_pass" else "stale")}">{escape(check_label(projection.check_summary.value))}</span><span class="muted">Current and historical evidence stay distinct.</span></div><form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/check" class="toolbar">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}<button type="submit">Rerun check on exact R{revision.ordinal}</button></form><div class="finding-groups"><section class="finding-group"><h3>Current applicable findings</h3><ul class="finding-list">{"".join(current_rows) or '<li class="muted">No current applicable findings.</li>'}</ul></section><section class="finding-group"><h3>Historical / non-applicable findings</h3><ul class="finding-list">{"".join(historical_rows) or '<li class="muted">No historical finding records.</li>'}</ul></section></div>"""


def _checks_panel(
    revision: DraftRevisionV1,
    projection: DraftProjectionV1,
    presentation: PresentationProjectionV2,
    csrf: str,
) -> str:
    checks = ""
    for item in reversed(projection.checks):
        select = _presentation_form(
            revision,
            presentation,
            csrf,
            "Select receipt",
            css_class="link-button",
            selected_object_kind="receipt",
            selected_object_id=item.receipt.receipt_id,
            active_casework_tab="checks",
        )
        checks += f'<li class="receipt"><span class="badge {("pass" if item.applicability.value == "current_pass" else "stale")}">{escape(check_label(item.applicability.value))}</span><div>{escape(item.receipt.result)} · {len(item.receipt.findings)} findings</div><span class="node-id">{escape(short(item.receipt.receipt_id))} · checker {escape(item.receipt.checker_version)} · {escape(item.receipt.rule_set)} · {select}</span>{raw_block("Exact check receipt", item.receipt.to_data())}</li>'
    return f"""<div class="case-summary"><strong>Plan checks</strong><span class="badge {("pass" if projection.check_summary.value == "current_pass" else "stale")}">{escape(check_label(projection.check_summary.value))}</span></div><form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/check" class="toolbar">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}<button type="submit">Check this revision</button></form><p class="hint">Checks apply to specific plan contents and checker rules. After an edit or a rules change, check again; an earlier pass does not validate this revision.</p><ul class="receipt-list">{checks or '<li class="muted">This plan has not been checked yet.</li>'}</ul>"""


def _receipts_panel(
    revision: DraftRevisionV1,
    projection: DraftProjectionV1,
    presentation: PresentationProjectionV2,
    proposals: tuple[ProposalProjectionV1, ...],
    csrf: str,
) -> str:
    locks = ""
    for item in reversed(projection.locks):
        select = _presentation_form(
            revision,
            presentation,
            csrf,
            "Select receipt",
            css_class="link-button",
            selected_object_kind="receipt",
            selected_object_id=item.receipt.lock_id,
            active_casework_tab="receipts",
        )
        locks += f'<li class="receipt"><span class="badge lock">{escape(item.applicability)}</span><div>{("working revision R" + str(revision.ordinal) if item.receipt.revision_id == revision.revision_id else "historical revision")} · {len(item.receipt.applicable_check_receipts)} applicable check receipt(s) recorded</div><span class="node-id">lock {escape(short(item.receipt.lock_id))} · {select}<br>plan {escape(short(item.receipt.plan_digest))}</span>{raw_block("Exact lock receipt", item.receipt.to_data())}</li>'
    dispositions = "".join(
        f'<li class="receipt"><span class="badge {escape(item.lifecycle.value)}">{escape(item.lifecycle.value)}</span><div>Agent proposal disposition</div><a href="/phosphor/design/drafts/{quote(revision.draft_id)}/proposals/{quote(item.proposal.proposal_id)}">{escape(short(item.proposal.proposal_id))}</a>{("" if item.disposition is None else raw_block("Exact proposal disposition", item.disposition.to_data()))}</li>'
        for item in reversed(proposals)
        if item.disposition is not None
    )
    return f"""<div class="case-summary"><strong>Saved records</strong><span class="muted">Inspect the recorded version and supporting details.</span></div><h3>Save a fixed snapshot</h3><form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/lock" class="toolbar">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}<button class="lock-action" type="submit">Lock R{revision.ordinal}</button></form><p class="nonclaim">A lock saves a fixed snapshot of this plan. It does not grant permission to run. You can save a snapshot with unresolved findings; locking does not clear them.</p><h3>Lock receipts</h3><ul class="receipt-list">{locks or '<li class="muted">No locked snapshot.</li>'}</ul><h3>Proposal dispositions</h3><ul class="receipt-list">{dispositions or '<li class="muted">No accepted/rejected proposal receipt.</li>'}</ul>"""


def _identity_strip(
    revision: DraftRevisionV1,
    revisions: tuple[DraftRevisionV1, ...],
    projection: DraftProjectionV1,
) -> str:
    by_digest = {item.plan_digest: item for item in revisions}
    latest_check = projection.checks[-1].receipt if projection.checks else None
    latest_lock = projection.locks[-1].receipt if projection.locks else None
    external = {item.kind: item for item in projection.external_references}

    def stage(label: str, digest: str | None, detail: str = "") -> str:
        if digest is None:
            return f'<div class="identity-cell"><span class="label">{escape(label)}</span><strong>not recorded</strong><span class="exact">explicit absence</span></div>'
        located = by_digest.get(digest)
        revision_label = (
            "artifact outside local revision index"
            if located is None
            else f"R{located.ordinal}"
        )
        relation = (
            "matches working"
            if digest == revision.plan_digest
            else "differs from working"
        )
        return f'<div class="identity-cell"><span class="label">{escape(label)}</span><strong>{escape(revision_label)} · {escape(relation)}</strong><span class="exact" title="{escape(digest, quote=True)}">{escape(short(digest))}{escape((" · " + detail) if detail else "")}</span></div>'

    return (
        '<section class="identity-strip" aria-label="Exact draft lifecycle relationships">'
        f'<div class="identity-cell"><span class="label">Draft</span><strong>{escape(revision.document.goal or "(goal not declared)")}</strong><span class="exact" title="{escape(revision.draft_id, quote=True)}">{escape(short(revision.draft_id))}</span></div>'
        f'<div class="identity-cell"><span class="label">Working</span><strong>R{revision.ordinal}</strong><span class="exact" title="{escape(revision.plan_digest, quote=True)}">{escape(short(revision.plan_digest))}</span></div>'
        + stage(
            "Checked",
            None if latest_check is None else latest_check.plan_digest,
            projection.check_summary.value,
        )
        + stage("Locked", None if latest_lock is None else latest_lock.plan_digest)
        + stage(
            "Handed off",
            None if "handoff" not in external else external["handoff"].plan_digest,
            "owner fact" if "handoff" in external else "",
        )
        + stage(
            "Governed",
            None if "governed" not in external else external["governed"].plan_digest,
            "owner fact" if "governed" in external else "",
        )
        + "</section>"
    )


def _current_diff(
    revision: DraftRevisionV1, parent: DraftRevisionV1 | None
) -> PlanDiffV1 | None:
    if parent is None:
        return None
    from maude.plan.diff import semantic_diff

    return semantic_diff(parent.document, revision.document)


def _diff_projection(
    revision: DraftRevisionV1,
    diff: PlanDiffV1 | None,
    presentation: PresentationProjectionV2,
    csrf: str,
) -> str:
    if diff is None:
        return '<p class="muted">Initial revision has no predecessor diff.</p>'
    present = {node.node_id for node in revision.document.nodes}
    rows = []
    for node_id in diff.added:
        selector = _presentation_form(
            revision,
            presentation,
            csrf,
            f"+ {node_id}",
            css_class="link-button",
            selected_node_id=node_id,
            selected_object_kind="diff",
            selected_object_id=f"added:{node_id}",
            active_casework_tab="diff",
        )
        rows.append(f'<li class="diff-row">{selector} · node added</li>')
    for change in diff.changed:
        selector = _presentation_form(
            revision,
            presentation,
            csrf,
            f"~ {change.node_id}",
            css_class="link-button",
            selected_node_id=change.node_id,
            selected_object_kind="diff",
            selected_object_id=f"changed:{change.node_id}",
            active_casework_tab="diff",
        )
        rows.append(
            f'<li class="diff-row">{selector} · {escape(", ".join(change.fields))}</li>'
        )
    for node_id in diff.removed:
        rows.append(
            f'<li class="diff-row"><span class="muted">- {escape(node_id)}</span> · historical target removed; not retargeted</li>'
        )
    if diff.reordered:
        rows.append(
            '<li class="diff-row"><span class="badge">order changed</span> stable PlanNode identities preserved</li>'
        )
    for field in diff.document_fields:
        selector = _presentation_form(
            revision,
            presentation,
            csrf,
            "document",
            css_class="link-button",
            selected_node_id="",
            selected_object_kind="diff",
            selected_object_id=f"document:{field}",
            active_casework_tab="diff",
        )
        rows.append(f'<li class="diff-row">{selector} · {escape(field)} changed</li>')
    # A defensive assertion keeps links from ever targeting absent current nodes.
    assert all(item in present for item in diff.added)
    assert all(change.node_id in present for change in diff.changed)
    return f'<div class="case-summary"><strong>Semantic diff from predecessor</strong><span class="muted">Stable IDs cross-probe into the current object inspector.</span></div><ul class="diff-list">{"".join(rows) or "<li class=muted>No semantic changes.</li>"}</ul>{raw_block("Structured semantic diff", diff.to_data())}'


_SCOPE_LABELS = {
    "exact_nodes": "Selected plan steps",
    "exact_document": "Entire draft",
    "exact_finding": "Current checker finding",
}


def _review_value(value: Any) -> str:
    """Return a readable, escaped semantic value for a human review surface."""
    if isinstance(value, str):
        return escape(value)
    return escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _before_after(label: str, before: Any, after: Any) -> str:
    return (
        f'<section class="review-change"><h3>{escape(label)}</h3>'
        '<dl class="drift"><dt>Before</dt><dd><pre>'
        f"{_review_value(before)}</pre></dd><dt>After</dt><dd><pre>"
        f"{_review_value(after)}</pre></dd></dl></section>"
    )


def _proposal_change_review(
    before: PlanDocumentV1, after: PlanDocumentV1, diff: PlanDiffV1
) -> str:
    """Describe the exact diff in reviewable values without replacing its record."""
    before_nodes = {node.node_id: node.to_data() for node in before.nodes}
    after_nodes = {node.node_id: node.to_data() for node in after.nodes}
    changes: list[str] = []
    for node_id in diff.added:
        changes.append(
            _before_after(f"Added plan step {node_id}", None, after_nodes[node_id])
        )
    for node_id in diff.removed:
        changes.append(
            _before_after(f"Removed plan step {node_id}", before_nodes[node_id], None)
        )
    for node_change in diff.changed:
        old = before_nodes[node_change.node_id]
        new = after_nodes[node_change.node_id]
        for field in node_change.fields:
            changes.append(
                _before_after(
                    f"Plan step {node_change.node_id} · {field}",
                    old[field],
                    new[field],
                )
            )
    if diff.reordered:
        changes.append(
            _before_after("Plan step order", list(diff.before_order), list(diff.after_order))
        )
    old_document = before.to_data()
    new_document = after.to_data()
    for field in diff.document_fields:
        changes.append(_before_after(f"Draft field · {field}", old_document[field], new_document[field]))
    return "".join(changes) or '<p class="muted">No semantic changes.</p>'


def _proposal_panel(
    revision: DraftRevisionV1,
    projection: DraftProjectionV1,
    presentation: PresentationProjectionV2,
    proposals: tuple[ProposalProjectionV1, ...],
    refusals: tuple[GenerationRefusalV1, ...],
    csrf: str,
    *,
    selected_node_id: str | None,
    selected_finding_id: str | None,
    provider_scenarios: tuple[str, ...],
    proposal_generation_id: str,
) -> str:
    current_findings = {
        finding.finding_id: finding
        for receipt in projection.checks
        if receipt.applicability.value in {"current_pass", "current_findings"}
        for finding in receipt.receipt.findings
    }
    finding = current_findings.get(selected_finding_id or "")
    if finding is not None:
        scope_kind = "finding"
        target_node_id = finding.target.node_id or ""
        target = f"finding {finding.finding_id} → {target_node_id or 'document'}"
    elif selected_node_id is not None:
        scope_kind = "node"
        target_node_id = selected_node_id
        target = f"PlanNode {selected_node_id}"
    else:
        scope_kind = "document"
        target_node_id = ""
        target = "PlanDocument fields"
    options = "".join(
        f'<option value="{escape(item, quote=True)}">{escape(item.replace("_", " "))}</option>'
        for item in provider_scenarios
    )
    enrolled_available = "enrolled-switchyard" in provider_scenarios
    scenario_label = (
        "Proposal source (includes configured Switchyard route)"
        if enrolled_available
        else "Deterministic proposal scenario"
    )
    scenario_hint = (
        "The configured Switchyard route is available only when selected. Other choices are deterministic examples; no proposal is accepted without this separate review."
        if enrolled_available
        else "This demo offers deterministic examples only, not a live model. Review the proposed changes before accepting them into your draft."
    )
    proposal_rows = []
    for item in reversed(proposals):
        targets = ", ".join(item.proposal.scope.target_node_ids) or "document"
        select = _presentation_form(
            revision,
            presentation,
            csrf,
            "Select as active case",
            css_class="link-button",
            selected_node_id=(
                item.proposal.scope.target_node_ids[0]
                if len(item.proposal.scope.target_node_ids) == 1
                else ""
            ),
            selected_object_kind="proposal",
            selected_object_id=item.proposal.proposal_id,
            active_casework_tab="proposals",
        )
        proposal_rows.append(
            f'<li><span class="badge {escape(item.lifecycle.value)}">{escape(item.lifecycle.value)}</span> '
            f'<a href="/phosphor/design/drafts/{quote(revision.draft_id)}/proposals/{quote(item.proposal.proposal_id)}">'
            f'Review {len(item.proposal.operations)} operation(s) for {escape(targets)}</a><div class="node-id">{escape(short(item.proposal.proposal_id))} · '
            f"base {escape(short(item.proposal.base_revision_id))} · {escape(item.proposal.model_id)} · {select}</div></li>"
        )
    refusal_rows = "".join(
        f'<li><span class="badge rejected">invalid</span> {escape(item.model_id)}<div class="node-id">{escape(item.reason)}<br>{escape(item.refusal_id)}</div></li>'
        for item in reversed(refusals)
    )
    form = f"""<form class="editor" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/proposals/generate">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}{hidden("proposal_generation_id", proposal_generation_id)}{hidden("scope_kind", scope_kind)}{hidden("target_node_id", target_node_id)}{hidden("finding_id", "" if finding is None else finding.finding_id)}<label>What this proposal may change<input readonly value="{escape(target, quote=True)}"></label><label>Describe the edit<textarea name="task" required maxlength="4000" placeholder="Describe a change within the scope shown above"></textarea></label><label>{escape(scenario_label)}<select name="provider_scenario">{options}</select></label><button type="submit">Propose edit</button><p class="hint">{escape(scenario_hint)} Acceptance does not run checks, hand off work, or authorize execution.</p></form>"""
    return f"""<div class="case-summary"><strong>Proposed edits</strong><span class="badge">review before applying</span><span class="muted">Choose a task, inspect the proposed changes, then accept or reject.</span></div><div class="proposal-grid"><div>{form}</div><div><h3>Saved proposals</h3><ul class="proposal-list">{"".join(proposal_rows) or '<li class="muted">No proposal has been produced for this draft.</li>'}</ul><h3>Responses that could not be used</h3><ul class="proposal-list">{refusal_rows or '<li class="muted">No invalid provider response has been recorded.</li>'}</ul></div></div>"""


def _history_panel(
    revision: DraftRevisionV1,
    revisions: tuple[DraftRevisionV1, ...],
    projection: DraftProjectionV1,
    proposals: tuple[ProposalProjectionV1, ...],
    presentation: PresentationProjectionV2,
    csrf: str,
) -> str:
    checked: dict[str, list[str]] = {}
    for item in projection.checks:
        checked.setdefault(item.receipt.plan_digest, []).append(
            item.applicability.value
        )
    locked = {item.receipt.revision_id for item in projection.locks}
    accepted = {
        getattr(
            item.disposition, "resulting_revision_id", ""
        ): item.proposal.proposal_id
        for item in proposals
        if item.disposition is not None
    }
    rows = []
    for item in reversed(revisions):
        facts = []
        if item.revision_id == revision.revision_id:
            facts.append('<span class="badge pass">working</span>')
        if item.plan_digest in checked:
            counts = {
                applicability: checked[item.plan_digest].count(applicability)
                for applicability in dict.fromkeys(checked[item.plan_digest])
            }
            facts.extend(
                f'<span class="badge">check {escape(applicability)}{(" ×" + str(count)) if count > 1 else ""}</span>'
                for applicability, count in counts.items()
            )
        if item.revision_id in locked:
            facts.append('<span class="badge lock">locked</span>')
        if item.revision_id in accepted:
            facts.append(
                f'<a href="/phosphor/design/drafts/{quote(revision.draft_id)}/proposals/{quote(accepted[item.revision_id])}">agent proposal receipt</a>'
            )
        select = _presentation_form(
            revision,
            presentation,
            csrf,
            "Select revision",
            css_class="link-button",
            selected_object_kind="revision",
            selected_object_id=item.revision_id,
            active_casework_tab="history",
        )
        rows.append(
            f'<li class="receipt history-row"><strong>R{item.ordinal}</strong><span>{escape(item.edit_origin.value)} · {escape(item.created_at)}<br>{select}</span><span>{" ".join(facts) or "no attached check/lock/proposal receipt"}<br><span class="node-id" title="{escape(item.revision_id, quote=True)}">revision {escape(short(item.revision_id))} · plan {escape(short(item.plan_digest))}</span></span></li>'
        )
    return f'<div class="case-summary"><strong>Revision history</strong><span class="muted">Append-only successors; history is never rewritten.</span></div><ul class="receipt-list">{"".join(rows)}</ul><p class="hint">Compare uses the exact predecessor diff in the Diff tab. Revert-as-successor is not exposed by the current typed operation vocabulary.</p>'


def _case_tabs(
    revision: DraftRevisionV1,
    presentation: PresentationProjectionV2,
    csrf: str,
    active: str,
) -> str:
    tabs = (
        ("findings", "Findings"),
        ("checks", "Checks"),
        ("diff", "Diff"),
        ("proposals", "Agent proposals"),
        ("receipts", "Receipts"),
        ("history", "Revision history"),
    )
    return (
        '<nav class="case-tabs" aria-label="Casework evidence views">'
        + "".join(
            _presentation_form(
                revision,
                presentation,
                csrf,
                label,
                css_class="case-tab",
                active_casework_tab=kind,
                return_anchor="casework",
            ).replace(
                'type="submit"',
                f'type="submit" aria-pressed="{str(kind == active).lower()}"',
                1,
            )
            for kind, label in tabs
        )
        + "</nav>"
    )


def _selected_case(
    revision: DraftRevisionV1,
    revisions: tuple[DraftRevisionV1, ...],
    projection: DraftProjectionV1,
    proposals: tuple[ProposalProjectionV1, ...],
    current_diff: PlanDiffV1 | None,
    presentation: PresentationProjectionV2,
    csrf: str,
    governed_node_bindings: tuple[GovernedNodeBindingV1, ...],
    inspect_url: str,
    *,
    selected_node_id: str | None,
    selected_finding_id: str | None,
) -> tuple[str, str | None]:
    state = presentation.presentation
    kind = "finding" if selected_finding_id else state.selected_object_kind
    object_id = selected_finding_id or state.selected_object_id
    all_findings = [
        (finding, item.applicability.value, item.receipt.receipt_id)
        for item in projection.checks
        for finding in item.receipt.findings
    ]
    if kind == "finding" and object_id:
        if "/" in object_id:
            receipt_id, finding_id = object_id.split("/", 1)
            found = next(
                (
                    (item, applicability, receipt)
                    for item, applicability, receipt in all_findings
                    if item.finding_id == finding_id and receipt == receipt_id
                ),
                None,
            )
        else:
            # Backward-compatible query locators prefer the newest current
            # instance. New sidecars always bind receipt + finding exactly.
            found = next(
                (
                    (item, applicability, receipt)
                    for item, applicability, receipt in reversed(all_findings)
                    if item.finding_id == object_id
                    and applicability in {"current_pass", "current_findings"}
                ),
                None,
            ) or next(
                (
                    (item, applicability, receipt)
                    for item, applicability, receipt in reversed(all_findings)
                    if item.finding_id == object_id
                ),
                None,
            )
        if found is None:
            return (
                '<div class="warning">Selected finding reference is no longer available in retained check receipts. It was not retargeted.</div>',
                None,
            )
        finding, applicability, receipt_id = found
        exact_locator = f"{receipt_id}/{finding.finding_id}"
        moves = _presentation_form(
            revision,
            presentation,
            csrf,
            "Propose fix",
            selected_node_id=finding.target.node_id or "",
            selected_object_kind="finding",
            selected_object_id=exact_locator,
            active_casework_tab="proposals",
            return_anchor="casework",
        )
        moves += _presentation_form(
            revision,
            presentation,
            csrf,
            "Inspect checks",
            selected_node_id=finding.target.node_id or "",
            selected_object_kind="finding",
            selected_object_id=exact_locator,
            active_casework_tab="checks",
            return_anchor="casework",
        )
        moves += f'<form class="inline-form" method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/check">{hidden("csrf", csrf)}{hidden("expected_revision_id", revision.revision_id)}<button type="submit">Rerun check</button></form>'
        return (
            f'<section class="case-context case-focus" aria-label="Active finding"><span class="eyebrow">Active case · finding</span><h2>{escape(finding.message)}</h2><div><span class="badge finding">{escape(finding.rule_id)}</span> <span class="badge">{escape(applicability)}</span></div><div class="node-id">target {escape(finding.target.node_id or "document")} · finding {escape(finding.finding_id)} · receipt {escape(receipt_id)}</div><div class="context-moves"><span class="label">Available editor moves</span>{moves}</div></section>',
            finding.finding_id,
        )
    if kind == "proposal" and object_id:
        proposal = next(
            (item for item in proposals if item.proposal.proposal_id == object_id), None
        )
        if proposal is None:
            return (
                '<div class="warning">Selected proposal reference is not present in the immutable proposal store. It was not substituted.</div>',
                None,
            )
        targets = ", ".join(proposal.proposal.scope.target_node_ids) or "document"
        review = f'<a class="button" href="/phosphor/design/drafts/{quote(revision.draft_id)}/proposals/{quote(object_id)}">Review proposal</a>'
        return (
            f'<section class="case-context"><span class="eyebrow">Active case · agent proposal</span><h2>{escape(proposal.lifecycle.value)} proposal for {escape(targets)}</h2><div class="node-id">{escape(object_id)}</div><div class="context-moves"><span class="label">Available editor moves</span>{review}</div></section>',
            None,
        )
    if kind == "diff" and object_id:
        valid_diff_ids: set[str] = set()
        if current_diff is not None:
            valid_diff_ids.update(f"added:{item}" for item in current_diff.added)
            valid_diff_ids.update(
                f"changed:{item.node_id}" for item in current_diff.changed
            )
            valid_diff_ids.update(
                f"document:{field}" for field in current_diff.document_fields
            )
        if object_id not in valid_diff_ids:
            return (
                '<div class="warning">Selected diff locator is historical or unavailable for the current predecessor comparison. It was not retargeted.</div>',
                None,
            )
        moves = _presentation_form(
            revision,
            presentation,
            csrf,
            "Inspect full diff",
            active_casework_tab="diff",
            return_anchor="casework",
        )
        moves += _presentation_form(
            revision,
            presentation,
            csrf,
            "View revision history",
            active_casework_tab="history",
            return_anchor="casework",
        )
        return (
            f'<section class="case-context"><span class="eyebrow">Active case · semantic diff record</span><h2>{escape(object_id)}</h2><p class="muted">The stable target is selected below; proposed or historical content was not copied into current state.</p><div class="context-moves"><span class="label">Available editor moves</span>{moves}</div></section>',
            None,
        )
    if kind in {"receipt", "revision"} and object_id:
        if kind == "revision":
            item = next(
                (item for item in revisions if item.revision_id == object_id), None
            )
            summary = (
                None
                if item is None
                else f"Revision R{item.ordinal} · {item.edit_origin.value}"
            )
            target_tab = "history"
        else:
            check_ids = {item.receipt.receipt_id for item in projection.checks}
            other_ids = {
                *(item.receipt.lock_id for item in projection.locks),
                *(
                    item.disposition.receipt_id
                    for item in proposals
                    if item.disposition is not None
                ),
            }
            if object_id in check_ids:
                summary = "Immutable check receipt"
                target_tab = "checks"
            elif object_id in other_ids:
                summary = "Immutable lock/proposal receipt"
                target_tab = "receipts"
            else:
                summary = None
                target_tab = "receipts"
        if summary is None:
            return (
                f'<div class="warning">Selected {escape(kind)} reference is unavailable. It was not retargeted.</div>',
                None,
            )
        move = _presentation_form(
            revision,
            presentation,
            csrf,
            f"Inspect {target_tab}",
            active_casework_tab=target_tab,
            return_anchor="casework",
        )
        return (
            f'<section class="case-context"><span class="eyebrow">Active case · {escape(kind)}</span><h2>{escape(summary)}</h2><div class="node-id">{escape(object_id)}</div><div class="context-moves"><span class="label">Available read moves</span>{move}</div></section>',
            None,
        )
    if selected_node_id:
        moves = '<a class="button" href="#node-editor">Edit node</a>'
        moves += '<a class="button" href="#dependencies">Inspect dependencies</a>'
        moves += _presentation_form(
            revision,
            presentation,
            csrf,
            "Propose edit",
            selected_node_id=selected_node_id,
            selected_object_kind="node",
            selected_object_id=selected_node_id,
            active_casework_tab="proposals",
            return_anchor="casework",
        )
        for tab, label in (
            ("findings", "Inspect findings"),
            ("diff", "Compare revision"),
            ("history", "View history"),
        ):
            moves += _presentation_form(
                revision,
                presentation,
                csrf,
                label,
                selected_node_id=selected_node_id,
                selected_object_kind="node",
                selected_object_id=selected_node_id,
                active_casework_tab=tab,
                return_anchor="casework",
            )
        governed = next(
            (
                item
                for item in governed_node_bindings
                if item.node_id == selected_node_id
            ),
            None,
        )
        if governed is not None:
            moves += (
                '<a class="button" href="'
                + escape(
                    _inspect_href(inspect_url, governed.inspector_path), quote=True
                )
                + '">Inspect governed history</a>'
            )
        return (
            f'<section class="case-context" aria-label="Active PlanNode"><span class="eyebrow">Active case · PlanNode</span><h2>{escape(selected_node_id)}</h2><div class="context-moves"><span class="label">Available editor moves</span>{moves}</div></section>',
            None,
        )
    moves = '<a class="button" href="#document-editor">Edit document</a>'
    for tab, label in (
        ("findings", "Inspect findings"),
        ("proposals", "Propose document edit"),
        ("diff", "Compare revision"),
        ("history", "View history"),
    ):
        moves += _presentation_form(
            revision,
            presentation,
            csrf,
            label,
            selected_node_id="",
            selected_object_kind="document",
            selected_object_id="",
            active_casework_tab=tab,
            return_anchor="casework",
        )
    return (
        f'<section class="case-context" aria-label="Active PlanDocument"><span class="eyebrow">Active case · PlanDocument</span><h2>{escape(revision.document.goal or "(goal not declared)")}</h2><div class="context-moves"><span class="label">Available editor moves</span>{moves}</div></section>',
        None,
    )


def workspace_page(
    revision: DraftRevisionV1,
    parent: DraftRevisionV1 | None,
    revisions: tuple[DraftRevisionV1, ...],
    projection: DraftProjectionV1,
    presentation: PresentationProjectionV2,
    csrf: str,
    inspect_url: str,
    proposals: tuple[ProposalProjectionV1, ...] = (),
    proposal_refusals: tuple[GenerationRefusalV1, ...] = (),
    provider_scenarios: tuple[str, ...] = (),
    proposal_generation_id: str = "generation-render-only",
    governed_node_bindings: tuple[GovernedNodeBindingV1, ...] = (),
    active_generation_count: int = 0,
    *,
    selected_override: str | None = None,
    selected_finding: str | None = None,
    notice: tuple[str, str] | None = None,
) -> str:
    known = {node.node_id: node for node in revision.document.nodes}
    selected = (
        selected_override
        if selected_override is not None
        else presentation.presentation.selected_node_id
    )
    if selected not in known:
        selected = None
    if (
        selected_finding is None
        and presentation.presentation.selected_object_kind == "finding"
    ):
        selected_finding = presentation.presentation.selected_object_id
    case_header, selected_finding = _selected_case(
        revision,
        revisions,
        projection,
        proposals,
        _current_diff(revision, parent),
        presentation,
        csrf,
        governed_node_bindings,
        inspect_url,
        selected_node_id=selected,
        selected_finding_id=selected_finding,
    )
    detail = '<div id="active-case" class="case-focus" tabindex="-1">' + case_header
    detail += (
        _node_editor(
            revision,
            known[selected],
            projection,
            csrf,
            governed_node_bindings,
            inspect_url,
        )
        if selected
        else _document_editor(revision, csrf)
    )
    detail += "</div>"
    messages = []
    if notice:
        messages.append(f'<div class="{escape(notice[0])}">{escape(notice[1])}</div>')
    if presentation.stale_revision:
        messages.append(
            f'<div class="warning">Presentation sidecar targets historical revision {escape(short(presentation.presentation.semantic_revision_id))}; semantic state was not changed.</div>'
        )
    if presentation.orphaned_node_ids:
        messages.append(
            f'<div class="warning">Orphaned presentation reference(s): {escape(", ".join(presentation.orphaned_node_ids))}. They were not retargeted or recreated.</div>'
        )
    current_diff = _current_diff(revision, parent)
    diff_html = _diff_projection(revision, current_diff, presentation, csrf)
    pane_options = "".join(
        f'<option value="{size}" {"selected" if size == presentation.presentation.outline_percent else ""}>{size}% outline</option>'
        for size in (28, 36, 44, 52)
    )
    document_move = _presentation_form(
        revision,
        presentation,
        csrf,
        "Plan settings",
        selected_node_id="",
        selected_object_kind="document",
        selected_object_id="",
    )
    active_link = (
        f'<a class="button" href="/phosphor/design/drafts/{quote(revision.draft_id)}/proposal-generations/active">Active proposal generation ({active_generation_count})</a>'
        if active_generation_count
        else ""
    )
    workspace_tools = f"""<div class="toolbar">{document_move}<form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/presentation">{hidden("csrf", csrf)}{_presentation_fields(revision, presentation, include_outline_percent=False)}<label><span class="visually-hidden">Outline pane size</span><select name="outline_percent">{pane_options}</select></label><button type="submit">Set pane split</button></form>{active_link}</div>"""
    proposal_html = _proposal_panel(
        revision,
        projection,
        presentation,
        proposals,
        proposal_refusals,
        csrf,
        selected_node_id=selected,
        selected_finding_id=selected_finding,
        provider_scenarios=provider_scenarios,
        proposal_generation_id=proposal_generation_id,
    )
    active_tab = presentation.presentation.active_casework_tab
    case_content = {
        "findings": _findings_panel(
            revision, projection, presentation, csrf, selected_finding
        ),
        "checks": _checks_panel(revision, projection, presentation, csrf),
        "diff": diff_html,
        "proposals": proposal_html,
        "receipts": _receipts_panel(
            revision, projection, presentation, proposals, csrf
        ),
        "history": _history_panel(
            revision, revisions, projection, proposals, presentation, csrf
        ),
    }[active_tab]
    proposal_target_counts: dict[str, int] = {}
    for item in proposals:
        for node_id in item.proposal.scope.target_node_ids:
            proposal_target_counts[node_id] = proposal_target_counts.get(node_id, 0) + 1
    drift_notes = []
    if projection.to_data()["working_differs_from_locked"]:
        drift_notes.append("working draft differs from at least one locked artifact")
    if projection.to_data()["working_differs_from_handoff"]:
        drift_notes.append("working draft differs from the handed-off owner fact")
    if projection.to_data()["working_differs_from_governed"]:
        drift_notes.append("working draft differs from the governed-lineage owner fact")
    drift_banner = (
        ""
        if not drift_notes
        else '<div class="warning"><strong>Exact artifact drift:</strong> '
        + escape("; ".join(drift_notes))
        + ". Inspect the lifecycle identities above; no lineage was rebound.</div>"
    )
    compiler_boundary = (
        '<p class="nonclaim"><strong>Exact workflow compilation is recorded for a historical lock; browser handoff remains unavailable.</strong> /design displays representation and governed lineage read-only. It cannot submit or recompile the working draft.</p>'
        if projection.compilations
        else '<p class="nonclaim"><strong>No exact workflow compiler, no governed handoff.</strong> Plan Core cannot derive governed operational work from prose or ambient context.</p>'
    )
    body = f"""<div class="eyebrow">Maude · Plan editor</div><h1>{escape(revision.document.goal or "(goal not declared)")}</h1><p class="lede">Edit the plan, check its dependencies, and review changes before locking a revision. Design flow is pre-alpha; a checked or locked plan is not permission to execute.</p>{"".join(messages)}{_identity_strip(revision, revisions, projection)}{drift_banner}{compiler_boundary}{workspace_tools}<div class="workspace" style="--outline:{presentation.presentation.outline_percent}%">{_outline(revision, projection, selected, presentation, csrf, proposal_target_counts)}<section class="panel detail">{detail}{raw_block("Exact canonical PlanDocument", revision.document.to_data())}</section><section id="casework" class="panel lower casework" tabindex="-1" aria-label="Persistent casework pane">{_case_tabs(revision, presentation, csrf, active_tab)}<div class="case-content">{case_content}</div></section></div>"""
    return page(
        revision.document.goal or revision.draft_id, body, inspect_url=inspect_url
    )


def proposal_page(
    projection: ProposalProjectionV1,
    request: PlanEditProposalRequestV1,
    csrf: str,
    inspect_url: str,
) -> str:
    proposal = projection.proposal
    state = projection.lifecycle.value
    scope_target = ", ".join(proposal.scope.target_node_ids) or "document"
    scope_label = _SCOPE_LABELS.get(proposal.scope.kind, "Bounded proposal scope")
    affected_ids = tuple(
        dict.fromkeys(
            (
                *projection.preview.diff.added,
                *projection.preview.diff.removed,
                *(item.node_id for item in projection.preview.diff.changed),
            )
        )
    )
    node_labels = {
        node.node_id: node.description
        for node in (*request.document.nodes, *projection.preview.document.nodes)
    }
    affected = ""
    base_ids = {node.node_id for node in request.document.nodes}
    removed_ids = set(projection.preview.diff.removed)
    for node_id in affected_ids:
        content = f'<strong>{escape(node_labels.get(node_id, "historical removed node"))}</strong><br><span class="node-id">{escape(node_id)}</span>'
        if node_id in base_ids and node_id not in removed_ids:
            affected += f'<a href="/phosphor/design/drafts/{quote(proposal.draft_id)}?node={quote(node_id)}">{content}</a>'
        else:
            relation = (
                "removed by proposal" if node_id in removed_ids else "proposed addition"
            )
            affected += f'<span>{content}<br><span class="muted">{relation}; not a current-node link</span></span>'
    operations = "".join(
        f'<li class="diff-row"><span class="badge">{index}</span> {escape(item.edit.operation_type)}{raw_block("Exact canonical operation", item.to_data())}</li>'
        for index, item in enumerate(proposal.operations, 1)
    )
    if state == "proposed":
        actions = f"""<div class="actions"><form method="post" action="/phosphor/design/drafts/{quote(proposal.draft_id)}/proposals/{quote(proposal.proposal_id)}/accept">{hidden("csrf", csrf)}<button type="submit">Accept changes into draft</button></form><form method="post" action="/phosphor/design/drafts/{quote(proposal.draft_id)}/proposals/{quote(proposal.proposal_id)}/reject">{hidden("csrf", csrf)}<label>Rejection reason<input name="reason" required maxlength="1000"></label><button class="danger" type="submit">Reject proposal</button></form></div>"""
    elif state == "stale":
        actions = '<div class="warning">This proposal is stale. It remains inspectable, but it cannot be rebased or accepted against the newer working revision. Request a new proposal or recreate the edit manually.</div>'
    else:
        actions = f'<div class="{"success" if state == "accepted" else "error"}">Proposal {escape(state)}. This decision is final; reopening it will not apply the changes again.</div>'
    rationale = "not supplied" if proposal.rationale is None else proposal.rationale
    disposition = (
        '<p class="muted">No terminal disposition receipt.</p>'
        if projection.disposition is None
        else raw_block(
            "Immutable disposition receipt", projection.disposition.to_data()
        )
    )
    readable_changes = _proposal_change_review(
        request.document, projection.preview.document, projection.preview.diff
    )
    body = f"""<div class="eyebrow">Agent edit proposal · review only until accepted</div><h1>Review proposed changes</h1><p><a href="/phosphor/design/drafts/{quote(proposal.draft_id)}">← Return to draft</a></p><section class="identity-strip"><div class="identity-cell"><span class="label">Proposal</span><strong>{escape(short(proposal.proposal_id))}</strong><span class="exact" title="{escape(proposal.proposal_id, quote=True)}">exact proposal identity</span></div><div class="identity-cell"><span class="label">Proposal status</span><strong>{escape(state)}</strong></div><div class="identity-cell"><span class="label">Exact base</span><strong>{escape(short(proposal.base_revision_id))}</strong><span class="exact" title="{escape(proposal.base_plan_digest, quote=True)}">{escape(short(proposal.base_plan_digest))}</span></div><div class="identity-cell"><span class="label">Provider / model</span><strong>{escape(proposal.provider_id)}</strong><span class="exact">{escape(proposal.model_id)} · {escape(proposal.model_version or "version unavailable")}</span></div></section><section class="panel preview"><h2>1 · What this proposal may change</h2><dl class="drift"><dt>scope</dt><dd>{escape(scope_label)}<br><span class="exact">exact scope kind: {escape(proposal.scope.kind)}</span></dd><dt>target</dt><dd>{escape(scope_target)}</dd><dt>operations allowed</dt><dd>{escape(", ".join(proposal.scope.allowed_operation_types))}</dd><dt>node fields</dt><dd>{escape(", ".join(proposal.scope.allowed_node_fields) or "none")}</dd><dt>document fields</dt><dd>{escape(", ".join(proposal.scope.allowed_document_fields) or "none")}</dd></dl><h2>2 · Affected plan steps</h2><div class="proposal-affected">{affected or '<span class="muted">Document-level fields only.</span>'}</div><h2>3 · Reviewable before and after values</h2>{readable_changes}<details class="raw"><summary>Exact semantic diff record</summary><pre>{escape(json.dumps(projection.preview.diff.to_data(), ensure_ascii=False, indent=2, sort_keys=True))}</pre></details><h2>4 · Exact edit operations</h2><ul class="proposal-list">{operations}</ul><h2>5 · After accepting</h2><p class="nonclaim">Acceptance saves one new draft revision. Run checks again on that revision, review any findings, and lock only the version you intend to hand off. Acceptance does not authorize or execute work.</p><h2>6 · Model rationale · explanatory only</h2><p>{escape(rationale)}</p><p class="nonclaim">Operations govern what would change. Rationale is not PlanDocument semantics, a checker fact, or authority.</p>{actions}{disposition}{raw_block("Exact proposal artifact", proposal.to_data())}{raw_block("Exact bounded model request", request.to_data())}</section>"""
    return page("Review agent edit proposal", body, inspect_url=inspect_url)


def preview_page(
    revision: DraftRevisionV1,
    proposed: Any,
    diff: PlanDiffV1,
    token: str,
    csrf: str,
    inspect_url: str,
) -> str:
    body = f"""<div class="eyebrow">Semantic edit preview</div><h1>Review draft changes</h1><section class="identity-strip"><div class="identity-cell"><span class="label">Current</span><strong>R{revision.ordinal}</strong><span class="node-id">{escape(revision.plan_digest)}</span></div><div class="identity-cell"><span class="label">New revision</span><strong>R{revision.ordinal + 1}</strong><span class="node-id">{escape(proposed.digest)}</span></div></section><section class="panel preview"><h2>Reviewable before and after values</h2>{_proposal_change_review(revision.document, proposed, diff)}{raw_block("Exact semantic diff record", diff.to_data())}<div class="actions"><form method="post" action="/phosphor/design/drafts/{quote(revision.draft_id)}/apply">{hidden("csrf", csrf)}{hidden("preview_token", token)}<button type="submit">Save new revision</button></form><a class="button" href="/phosphor/design/drafts/{quote(revision.draft_id)}">Cancel and keep current</a></div><p class="hint">Saving works only if the draft has not changed since this preview. If someone edits it meanwhile, reload and review the newer revision; your changes will not be silently merged.</p></section>"""
    return page("Review semantic edit", body, inspect_url=inspect_url)


def error_page(
    title: str, detail: str, inspect_url: str, *, status: str = "error"
) -> str:
    return page(
        title,
        f'<div class="eyebrow">Visible refusal</div><h1>{escape(title)}</h1><div class="{escape(status)}">{escape(detail)}</div><p><a href="/phosphor/design">Return to plans</a></p>',
        inspect_url=inspect_url,
    )


def stale_preview_page(
    *,
    current: DraftRevisionV1,
    reviewed_revision: DraftRevisionV1,
    diff: PlanDiffV1,
    inspect_url: str,
) -> str:
    body = f"""<div class="eyebrow">Compare-and-swap refusal</div><h1>Stale edit refused</h1><div class="warning">The working draft advanced from R{reviewed_revision.ordinal} to R{current.ordinal}. The reviewed operation was not rebased, merged, or retargeted.</div><section class="panel preview"><h2>Your reviewed semantic intent</h2><pre>{escape(diff.render())}</pre>{raw_block("Structured reviewed diff", diff.to_data())}<dl class="drift"><dt>reviewed base</dt><dd>{escape(reviewed_revision.revision_id)}<br>{escape(reviewed_revision.plan_digest)}</dd><dt>current working</dt><dd>{escape(current.revision_id)}<br>{escape(current.plan_digest)}</dd></dl><p><a class="button" href="/phosphor/design/drafts/{quote(current.draft_id)}">Reload current revision</a></p><p class="hint">Reapply deliberately after inspecting the newer revision. This service never silently rebases a stale browser operation.</p></section>"""
    return page("Stale edit refused", body, inspect_url=inspect_url)

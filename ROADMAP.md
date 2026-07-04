# Maude Roadmap — the plan-executor repositioning

**Thesis (operator ruling 2026-07-03):** Maude consumes bounded plans
authored elsewhere, selects a harness, supervises execution through AG's
gate, captures the reviewable result, enforces stop conditions, and emits
obstruction notes. Two ingress contracts (human operator, synthetic
submitter), one execution core. AG is one authority substrate — Maude mints
no authority. See [docs/REPOSITIONING.md](docs/REPOSITIONING.md) for the
boundary and do-not-build list.

GS-numbered slices are specced in
`agent_gov/docs/campaigns/governed-shell/NEXT.md` (cited here, not
re-specced). M-numbered slices are Maude-repo work, chunked for small-model
execution in the campaign's six-field shape.

## Phase 0 — Reframe (docs only) — DONE 2026-07-03

- [x] **M-0a** — README + pyproject reframe (executor thesis; chat marked
  unsupported legacy per D-GS-2). Pin: `grep -c "governed AI chat"
  README.md` → 0.
- [x] **M-0b** — this ROADMAP rewrite + docs/REPOSITIONING.md + chat-era
  docs archived with HISTORICAL headers.
- [x] **M-0c** — architecture/commands/COMPAT/docs-README refresh ("chat-only"
  claims removed; COMPAT gains planned contract-pin note).
- [x] **M-0d** — delete dead `client/http.py`. Pin: bare `pytest tests/`
  exit 0.

## Phase 1 — Foundation (GS campaign)

- [x] **GS-8b** — ag_shell_client live-socket client class landed AG-side
  (`AsyncDaemonClient`, agent_gov `e8670ae`).
- [x] **GS-9** — Maude consumes ag_shell_client. Deleted `client/transport.py`
  (the duplicated Content-Length framing + socket-path derivation); rewrote
  `client/rpc.py` as a thin typed surface over `AsyncDaemonClient`. Kept
  `client/models.py` (maude's Pydantic rendering models — not the package's)
  and the typed method surface (one module naming every RPC method maude
  calls — the record R-MAUDE-1 wants). Concurrency: unary calls share one
  lock-serialized connection so the 5s poll never trips the one-in-flight
  busy guard; `chat.stream` runs on a dedicated connection; a poisoned
  connection is dropped and reconnected on the next call. Verify: bare
  `pytest` 156 passed / 24 skipped; live-daemon smoke 22/24 (see drift note).
- [x] **GS-10a** — skeleton modules + isolation tests (additive; app.py
  untouched). `feed.py` `DecisionFeedController` (the envelope-aware kernel:
  cache, interrupt/accumulate split, keymap-from-`options[].key`; GS-11 wires
  the live `operator.watch` loop + resolve). `commands/` `CommandRegistry`
  keyed by `IntentKind` (the seam that replaces app.py's if/elif).
  `screens/` — the four desk screens (queue/session/board/diff) + reserved
  `ReportScreen` (M-4 stub) + `ScreenManager` registry; overlay names
  reserved for GS-13. Verify: bare pytest 185 passed / 24 skipped exit 0
  (feed + registry pure-logic pins; each screen isolation-mounts via Textual
  pilot); ruff clean.
- [~] **GS-10b** — bootstrap migration, staged (operator direction: checkpoint
  first, dispatch second, screens third). Safety anchor: tag
  `checkpoint/pre-gs10b` (`0b92402`) + bundle in scratchpad (maude has no
  remote).
  - [x] **leg 1 — dispatch** (`4939100`): if/elif → `CommandRegistry` via
    `AppCommand` adapters (handlers unchanged, behavior-preserving);
    `commands/desk.py` (supported) + `commands/legacy.py` (chat/PLAN/BUILD
    quarantined as a named group). Guards: every IntentKind resolves; every
    handler name exists on MaudeApp; 4 end-to-end pilot smokes. Caught + fixed
    a real collision with Textual's internal `self._registry`. 206 tests green.
  - [x] **leg 2 — ScreenManager** wired behind the existing chat shell
    (`8a1f16f`). App owns the manager + explicit `_active_desk_screen` state
    (no ambient global — the stop condition); `ctrl+g` toggles chat ↔ a desk
    screen *pushed on top of* the default chat screen (kept mounted, so input/
    log state survives); `escape` returns. Caught a real Textual gotcha:
    `on_mount` is dispatched for *every* class in the MRO, so the base skeleton
    render and a subclass render both fire — resolved with a `_MANAGES_OWN_BODY`
    yield flag on DeskScreen. Guards: manager owned per-app / no global; startup
    +quit lifecycle smoke; toggle open/close; escape→chat; input-state
    preserved. Screen plumbing, not authority promotion. 211 tests green.
  - [~] **leg 3 — desk screens** brought up incrementally.
    - [x] **leg 3a — decisions/feed** (`ScreenManager.bind` injects the live
      client+feed): QueueScreen consumes the GS-11 data layer — explicit
      refresh (`operator.decisions.list`, `ctrl+r` + on open), `↑/↓` selection,
      empty/loading/error states, and operator-triggered resolve
      (`operator.decisions.resolve`) that relays ONLY the selected item's
      envelope `option_key` — no shell-invented verbs, no autopilot, no
      background/implicit resolution. The `operator.watch` subscribe loop stays
      deferred (explicit refresh only). Guards: refresh populates / empty /
      error, cursor moves selection+keymap, resolve relays selected key with a
      call-log pin (+follow-up refresh), key-not-in-keymap ignored, offline
      no-crash. 221 tests green.
    - [x] **leg 3b — sessions/watch board** (`ctrl+b`; `ScreenManager.bind`
      injects the live client). BoardScreen renders `runtime.session.list`
      verbatim — status glyph (a visual echo of the payload's own status, raw
      string always shown) · pending-decision count · task — with
      **waiting-on-you sorted to the top**; explicit `ctrl+r` refresh + on open;
      empty/loading/error states. A *status board, not a diagnosis engine*: no
      health/obstruction verdict, no new daemon fields, read-only (no resolve).
      App nav generalized: `ctrl+g` queue / `ctrl+b` board / `esc` chat, with
      desk↔desk switch (`switch_screen`) that never drops through chat and keeps
      the chat default mounted underneath. Guards: refresh populates / empty /
      error, waiting-first sort, waiting-count summary, unknown-status renders
      raw, offline no-crash; app: ctrl+b toggle, queue↔board switch keeps chat
      reachable. 231 tests green.
    - [~] **leg 3c — adapters (done); why + report deferred on purpose.**
      - [x] **adapters capability board** (`ctrl+o`; `ScreenManager.bind` injects
        the live client — 6th registered screen). AdaptersScreen renders
        `runtime.adapters.list` read-only: per-backend declared capabilities as
        ✓/✗ (pause/resume/steer/tool-hooks/events/graceful-stop), per-adapter
        construction errors surfaced verbatim; explicit `ctrl+r` refresh + on
        open; empty/loading/error states. Introspection only, below the gate —
        selects/configures/launches nothing (harness *selection* is M-3).
        Compatibility-tested against the known daemon shape (not live testimony).
        Guards: lists adapters, ✓/✗ honesty pin (claude pause ✓, gemini pause ✗),
        error-adapter surfaced, empty/error/offline, ctrl+r re-refresh; app
        ctrl+o toggle + board→adapters switch. 239 tests green.
      - [ ] **why-chain — deferred to GS-13 overlays (not built).** `why.chain`
        is an *overlay* ("never steal the screen", reserved in `OVERLAY_NAMES`),
        not a full desk screen; building it now would open GS-13's overlay UX
        contract ahead of its slice. The client method is landed; the surface
        waits for GS-13.
      - [ ] **report — stays the M-4 session-end stub (not nav-promoted).**
        ReportScreen remains a registered, honestly-labelled stub. It is M-4's
        *end-of-run* reviewable artifact ("displayed evidence, not adjudication"),
        not a browse-to destination — promoting a stub into desk nav is exactly
        the "report starts sounding official" laundering to avoid. M-4 composes +
        wires it.
  Goal: desk-shaped without changing the authority model — wiring, not a
  constitutional convention inside app.py.

### Daemon drift (R-MAUDE-1) — surfaced by GS-9, RESOLVED

The GS-9 live smoke caught `intent.compile` returning
`escape_classification=None` where `test_compile_with_escape` expects
`waiver_candidate`. Diagnosed as a real daemon bug (not a transport regression
or a stale test): the daemon wasn't threading `escape_text` through the RPC
path, so classification never fired. **Fixed AG-side (`eb82f20` — "intent.compile
threads escape_text so classification fires over RPC").** Re-run smoke: 23
passed / 1 skipped (only the intentional chat-stream skip), exit 0. A worked
example of the R-MAUDE-1 value: the surface diff flushes out real daemon
regressions.

## Phase 2 — The desk (GS campaign, as specced)

- [~] **GS-11 data layer landed** — `client/rpc.py` gained the governed-shell
  operator surface (`operator.decisions.list/resolve`, `operator.watch`
  streaming full snapshots, `runtime.session.send_input`,
  `runtime.adapters.list`, `why.chain`); `DecisionFeedController.ingest_watch_update`
  consumes live watch snapshots. Verified end-to-end against a real daemon.
  Remaining GS-11 is the queue *screen* (cards + keypress→resolve + the
  subscribe/re-subscribe loop), which needs GS-10b to be reachable.
- [ ] **GS-11** queue home (screen) · **GS-12** sessions board + session view +
  steering · **GS-13** why overlay + refusal→route map · **GS-14** envelope
  strip + widen one-liner (local-qwen eligible).
- Executor notes: GS-12's event rendering stays pure (ledger order is truth)
  so M-4 derives from it; GS-13's `routes.py` table is the data source for
  M-5 obstruction notes.

## Phase 3 — Plan-executor spine (M-series)

- [x] **M-1 — plan-envelope v0 spec + submitter contracts** — **operator-ratified
  CANDIDATE 2026-07-04** at [docs/specs/plan-envelope-v0.md](docs/specs/plan-envelope-v0.md).
  Candidate *Maude-side* law, not daemon law: budget/scope/acceptance enforced
  client-side / via autopilot profile for now; CT-1 (`plan_ref`, per-session
  budget/scope) stays named as future AG support, not built. M-2 builds against
  this; do not promote to daemon law until the client-side version proves shape.
  tier: conceptual · executor: **fable + operator ratification** · prereq: [M-0b]
  - purpose: mint the input contract ONCE so M-2..M-7 are mechanical. A
    bounded plan = markdown/front-matter with: goal; workspace + scope
    allowlist; ordered steps (advisory); acceptance criteria (checkable);
    stop conditions (budget ceilings, forbidden paths, halt-if); harness
    hint (optional); autopilot-profile hint (optional); provenance.
    **Submitter contract vocabulary:** `submitter_kind: human |
    synthetic_agent`; `plan_origin: human_written | agent_generated |
    agent_revised | imported_from_review`; the admission-posture /
    authority / interaction / review / limits matrix (REPOSITIONING.md).
    Every field maps to an existing `runtime.session.create` param or is
    client-side-only — the spec states the mapping table.
  - files: docs/specs/plan-envelope-v0.md (new).
  - tests: every M-2..M-7 slice cites the section it implements; field
    additions after ratification require a spec version bump.
  - refusal mode: defines `invalid_plan_envelope` (format validation only —
    explicitly NOT authority; a well-formed plan for a forbidden action
    passes format validation and is refused by AG at the gate).
  - receipt shape: filing commit; CANDIDATE until M-2 implements against it.
  - stop condition: any field requiring daemon enforcement/storage → CT-1
    contract question + operator ratification; do not stretch
    session.create.

- [x] **M-2 — plan ingestion command (`run <plan.md>`, in-TUI, human path)** —
  **DONE 2026-07-04 (CD-3, conveyor-dogfood campaign).** `src/maude/plan/`
  (envelope.py parser + runner.py RunPlanCommand; module layout supersedes
  the sketched file names below). Implements M-1 incl. the CD-1a governance
  binding: all FIVE refusal classes enforced client-side
  (invalid_plan_envelope, submitter_limits_missing, governance_not_approved,
  governance_ref_mismatch, governance_approval_unverified); governed plans
  fail CLOSED with no witness resolver wired (CD-4 wires the conveyor
  projection); param-mapping pins per the M-1 table; refusals create no
  session; `run` intent anchored on `.md` so prose falls through to chat.
  Tests: test_plan_envelope (24) + test_plan_runner (9); suite 272 green.
  Live-daemon smoke owed at next daemon-up (with the desk screens' first
  real-feed check).
  tier: mechanical · executor: codex · prereq: [M-1 ratified, GS-9, GS-10]
  - purpose: parse envelope → validate → map to create params → launch
    supervised session → session view. Maude neither edits nor generates
    plan content.
  - files: src/maude/commands/run_plan.py, src/maude/plan.py (pure parser),
    tests/test_plan.py.
  - tests: exact param-mapping pin per M-1 table; missing required field →
    typed error + **no session created** (negative pin); unknown extra
    fields ignored-with-warning (forward-compat pin).
  - refusal mode: `invalid_plan_envelope` only; authority refusals arrive
    from AG and render verbatim.
  - receipt shape: commit citing plan-envelope-v0 §; run receipts are AG's.
  - stop condition: any urge to "fix up" a plan (fill undeclared defaults,
    reorder steps, synthesize criteria) — STOP; planning happens outside.

- [ ] **M-3 — harness selection via runtime.adapters.list**
  tier: mechanical · executor: **local-qwen candidate** · prereq: [GS-9]
  - purpose: kill the hardcoded `backend_kind="claude_code"`; plan's
    harness hint validated against adapters.list; no hint → picker with
    capability badges; unknown/incapable → `adapter_unavailable` before
    launch.
  - files: run_plan.py (extend), widgets/adapter_pick.py,
    tests/test_adapter_select.py.
  - tests: known-hint passthrough pin; unknown-hint → error + no session
    pin; picker-shows-adapters-truth fake-feed pin.
  - refusal mode: `adapter_unavailable` (client-side pre-check; AG remains
    the enforcer).
  - receipt shape: commit.
  - stop condition: any adapter *configuration* in Maude (keys, model
    params, hook wiring) — selection ≠ ownership.

- [ ] **M-4 — run-report bundle (the reviewable result)**
  tier: mechanical · executor: codex · prereq: [GS-12, M-2]
  - purpose: on session end, compose from **existing reads only**
    (session.get, events, promotion.get/diff, receipts): plan ref +
    provenance (incl. submitter_kind), harness used, tool counts, diff
    stat, promotion status, receipt refs, acceptance-criteria checklist
    **rendered unchecked**; `report export <path>`.
  - files: src/maude/report.py (pure composer), screens/report.py (fills
    the GS-10 stub), commands/report.py, tests/test_report.py.
  - tests: golden fixture report; unchecked-count = criteria count; zero
    write-RPCs during composition (fake-client call-log pin).
  - refusal mode: n/a (derivation + render).
  - receipt shape: commit; the report cites AG receipt IDs — it is not
    itself a receipt.
  - stop condition: auto-judging acceptance, or implicit storage — derived,
    reviewer-directed output only.

- [ ] **M-5 — obstruction-note emission**  *(SANDWICH: thin fable
  work-order → codex)* · prereq: [GS-13, M-2]
  - purpose: when a run cannot proceed (blocking refusal with no route,
    budget/timeout stop, plan stop-condition tripped, adapter death), emit
    a structured note: plan ref, blocked step, refusal **verbatim**,
    GS-13 route or `no_route`, what upstream must change. Client-side
    artifact, exportable like M-4; ledger entry = CT-2, deferred.
  - files: plan-envelope spec §obstruction-note addendum, report.py
    (extend), tests/test_obstruction.py.
  - tests: refusal quoted byte-equal pin; route carried from routes.py pin;
    budget-stop names the exceeded ceiling pin; forbidden-phrase grep pin
    (no editorial characterization of AG's decision).
  - refusal mode: n/a — the note carries refusals, mints none.
  - receipt shape: commit.
  - stop condition: wording that argues with the gate; any auto-retry — the
    note ends the run's forward motion, the submitter's reviewer restarts.

## Phase 4 — Cut, release, and the ingress tail

- [ ] **GS-15 — remove PLAN/BUILD + chat, v3.0 release + contract pin** —
  as specced, simplified by the Phase-1 quarantine: delete
  `commands/legacy.py` + templates/ + intents prune (CHAT fallback →
  unknown-command help) + COMPAT repin (CT-3). Release notes state the
  relocations. **v3.0 = the desk.** Option (named, not authorized): fold
  M-2..M-4 into v3.0 at the GS-15 gate if Phase 2 lands fast.
- [ ] **v3.1 = M-2..M-5 shipped** (plan-executor spine).

- [ ] **M-6 — non-interactive one-shot machinery (`maude run <plan>
  --headless`, human path)**  *(SANDWICH: fable + operator → codex)* ·
  **v3.2, deliberately after the desk** · prereq: [GS-15, M-2, M-4, M-5;
  GS-7 optional enrichment]
  - purpose: ingest → launch → supervise → **halt at first blocking
    decision** (obstruction note + nonzero exit). Exit codes: 0
    completed/promotion-pending; 2 obstructed (note written); 3 invalid
    plan; 4 daemon unavailable. Report + note to `--out`. First-ever
    subcommand. This machinery is shared by both ingress contracts.
  - why late: strongest drift-pressure toward client-side approval; lands
    after halt/report/obstruction machinery exists so "halt" is cheap and
    "auto-approve" was never written.
  - tests: fake-feed completion → exit 0 + report pin; blocking decision
    injected → exit 2 + obstruction note + **zero resolve RPCs issued**
    (call-log pin — load-bearing); invalid plan → exit 3, no session.
  - stop condition: any path answering a decision without a human keystroke
    or a daemon-side autopilot verdict.

- [ ] **M-7 — synthetic submitter ingress (`maude submit --submitter
  synthetic_agent --plan <plan>`)**  *(SANDWICH: fable + operator →
  codex)* · prereq: [M-1 submitter vocabulary, M-6]
  - purpose: the synthetic contract as a first-class ingress on the shared
    M-6 machinery — NOT a separate authority path, NOT a "Claude mode."
    Differences from the human path, all from the M-1 matrix: **fail closed
    on ambiguity** (no interactive clarification — ambiguity → exit 3 +
    obstruction-style admission note); required explicit limits (budget
    ceiling, timeout, write scope — absent → refuse admission); provenance
    stamped `submitter_kind=synthetic_agent` + `plan_origin`; receipts/
    report returned to the orchestrator via `--out` (never assumed
    reviewed); propose-only authority (identical zero-resolve pin as M-6 —
    a synthetic submitter can never approve its own tool calls or
    promotions).
  - files: src/maude/commands/submit.py, headless.py (shared), tests/
    test_submit.py.
  - tests: ambiguous plan (missing required-for-synthetic field) → refused
    admission, no session (pin); human-path-optional fields required here
    (matrix pin); zero resolve RPCs (call-log pin); submitter_kind in
    report provenance (pin).
  - refusal mode: `invalid_plan_envelope` + `submitter_limits_missing`
    (format/admission only — authority refusals remain AG's).
  - receipt shape: commit; run receipts are AG's; the report cites them.
  - stop condition: any per-agent branch (`--claude`, agent-name
    special-casing) — all agents are submitters under the one synthetic
    contract; any capability the human path lacks.

## Verification discipline

Bare runners, exit codes, never `| tail`. Per-phase pins:

- Phase 0: `grep -ri "governed AI chat\|chat-only" README.md docs/ | grep -v
  archive` → empty; `python3 -m pytest tests/` exit 0; current COMPAT pin
  unchanged.
- Phase 1: GS-9/10 spec pins; `test -d src/maude/client` fails after GS-9;
  `grep -rn "chat_stream" src/maude/ | grep -v legacy` → empty after GS-10.
- Phase 2: GS-11..14 spec pins (keymap-from-envelope, since_seq resume,
  route-map exhaustiveness, ttl-widen).
- Phase 3: `pytest tests/test_plan.py tests/test_adapter_select.py
  tests/test_report.py tests/test_obstruction.py` exit 0; the
  zero-write-RPC and verbatim-refusal pins are load-bearing.
- Phase 4: GS-15 grep pin (no dangling PLAN/BUILD intents); full suite exit
  0; v3.0.0 tag; M-6/M-7: blocked fixture → exit 2 with zero resolve RPCs.

## Superseded (pre-repositioning "Next" items, 2.4.x era)

Side-panel lineage TUI, richer intervention preview, `lineage goto`,
intervention count in status bar → absorbed into the GS-10..GS-14 desk
design. Override-pressure display, pattern-aware approval, standing
integration → AG-side roadmap items, revisit after v3.0. Local knowledge
store, sandbox config visualization, multi-session split view, transcript
export → superseded by the desk (GS-12) and run reports (M-4), or dropped.

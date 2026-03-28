# TODO: Session Lineage — Branch Promotion

Full gap spec: `~/git/agent_gov/specs/gaps/SESSION_LINEAGE.md`
(MAUDE_GAP_SESSION_BRANCH_PROMOTION_001)

## TL;DR

The right primitive is **promotion**, not merge. Child sessions propose typed
artifacts back to the parent. Parent selectively adopts. No transcript splice.

## Phase 1 (MVP)

1. `/fork` — child session with parent linkage + optional worktree
2. Child produces promotion candidate: summary, facts, decisions, diff, tests
3. `/promote sess_child` — parent reviews and selectively accepts
4. Synthetic checkpoint message in parent
5. Promotion receipt emitted

## Key Commands

```
/fork [--title "..."] [--worktree]
/lineage
/promote <child> [--scope summary,decisions,diff]
/adopt fact <id> | decision <id> | diff <ref>
/reject fact <id>
/supersede decision <old> --with <new>
/compare <sess-a> <sess-b>
```

## Governor Touch Points

Promotion actions can be governed via optional policy vocabulary
(`session.promote.*`). Governor emits receipts. Maude owns the lineage model.
Session ontology stays out of the kernel.

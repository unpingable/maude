# SPDX-License-Identifier: Apache-2.0
"""DecisionFeedController — the one component that understands the decision
envelope (GS-10 skeleton, per docs/design/governed-shell/loop-ux.md §1-4 and
shell-contract-v0 §1-2 in the agent_gov repo).

It owns the local decision cache and derives, from the envelope alone:
  * the ordered feed (queue home renders this),
  * the interrupt vs. accumulate split (bell only on blocking/expiring), and
  * the per-item keymap (**straight from ``options[].key`` — no shell-invented
    verbs**; the daemon's vocabulary IS the keymap).

Boundary: this is render/triage state only. It resolves nothing and mints no
authority — resolving a decision goes to ``operator.decisions.resolve`` on the
daemon (wired in GS-11). The live ``operator.watch`` stream that feeds
:meth:`apply_snapshot` / :meth:`apply_update` is also GS-11; the cache-update
logic those call is complete and tested here.
"""

from __future__ import annotations

from ag_shell_client import DecisionItem, DecisionOption, decisions_from_response

# operator.watch change vocabulary (shell-contract-v0 §1).
_ADDED = "added"
_RESOLVED = "resolved"
_EXPIRING = "expiring"


class DecisionFeedController:
    """Holds the decision cache and derives feed/keymap/interrupt views."""

    def __init__(self) -> None:
        self._items: dict[str, DecisionItem] = {}
        self._order: list[str] = []  # feed order, preserved across updates
        self._feed_seq: int = 0

    # -- ingest ------------------------------------------------------------- #

    def apply_snapshot(self, result: dict) -> None:
        """Replace the cache from an ``operator.decisions.list`` result.

        The opening ``operator.watch`` snapshot and any full refresh land here.
        Reconstructs order from the result; ``feed_seq`` tracked for resume.
        """
        items = decisions_from_response(result)
        self._items = {i.decision_id: i for i in items}
        self._order = [i.decision_id for i in items]
        seq = result.get("feed_seq")
        if isinstance(seq, int):
            self._feed_seq = seq

    def apply_update(self, change: str, item: DecisionItem) -> None:
        """Apply one ``decision.event`` change (added | resolved | expiring).

        ``added`` appends (or refreshes in place); ``resolved`` drops the item;
        ``expiring`` refreshes it in place (urgency already carried on the item).
        An unknown change is treated as an upsert — surface, never silently drop.
        """
        did = item.decision_id
        if change == _RESOLVED:
            self._items.pop(did, None)
            if did in self._order:
                self._order.remove(did)
            return
        # added / expiring / unknown → upsert, preserving first-seen order.
        if did not in self._items:
            self._order.append(did)
        self._items[did] = item

    @property
    def feed_seq(self) -> int:
        """Last seen feed sequence — GS-11 resumes ``operator.watch`` from here."""
        return self._feed_seq

    # -- views -------------------------------------------------------------- #

    def items(self) -> list[DecisionItem]:
        """The full feed in order."""
        return [self._items[d] for d in self._order if d in self._items]

    def get(self, decision_id: str) -> DecisionItem | None:
        return self._items.get(decision_id)

    def interrupts(self) -> list[DecisionItem]:
        """Items that interrupt (bell + focus-steal): blocking / expiring /
        unknown urgency (conservatively surfaced)."""
        return [i for i in self.items() if i.is_interrupt]

    def accumulated(self) -> list[DecisionItem]:
        """Items that accumulate silently: normal / info urgency."""
        return [i for i in self.items() if not i.is_interrupt]

    def keymap_for(self, item: DecisionItem) -> dict[str, DecisionOption]:
        """The item's keymap, derived ONLY from ``options[].key``.

        The card prints these keys and the shell binds them — no shell-invented
        verbs. On a duplicate key (contract says keys are unique per item) the
        first option wins, so a malformed envelope can't silently rebind a key.
        """
        keymap: dict[str, DecisionOption] = {}
        for opt in item.options:
            if opt.key and opt.key not in keymap:
                keymap[opt.key] = opt
        return keymap

    @property
    def count(self) -> int:
        return len(self._order)

    @property
    def is_empty(self) -> bool:
        return not self._order

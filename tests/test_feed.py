# SPDX-License-Identifier: Apache-2.0
"""Tests for DecisionFeedController (GS-10)."""

from __future__ import annotations

from ag_shell_client import DecisionItem

from maude.feed import DecisionFeedController


def _item(decision_id: str, *, kind="intervention", urgency="normal",
          summary="", options=None) -> DecisionItem:
    return DecisionItem.from_dict({
        "decision_id": decision_id,
        "kind": kind,
        "urgency": urgency,
        "summary": summary,
        "options": options or [],
    })


def _snapshot(*items: DecisionItem, feed_seq: int = 0) -> dict:
    return {
        "items": [
            {
                "decision_id": i.decision_id,
                "kind": i.kind,
                "urgency": i.urgency,
                "summary": i.summary,
                "options": [
                    {"key": o.key, "label": o.label, "action": o.action}
                    for o in i.options
                ],
            }
            for i in items
        ],
        "feed_seq": feed_seq,
    }


class TestSnapshot:
    def test_empty_by_default(self):
        feed = DecisionFeedController()
        assert feed.is_empty
        assert feed.count == 0
        assert feed.items() == []

    def test_apply_snapshot_loads_items_in_order(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(_item("dec_1"), _item("dec_2"), feed_seq=7))
        assert [i.decision_id for i in feed.items()] == ["dec_1", "dec_2"]
        assert feed.count == 2
        assert feed.feed_seq == 7

    def test_snapshot_replaces_prior_state(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(_item("dec_1")))
        feed.apply_snapshot(_snapshot(_item("dec_2")))
        assert [i.decision_id for i in feed.items()] == ["dec_2"]


class TestUpdates:
    def test_added_appends(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(_item("dec_1")))
        feed.apply_update("added", _item("dec_2"))
        assert [i.decision_id for i in feed.items()] == ["dec_1", "dec_2"]

    def test_resolved_drops(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(_item("dec_1"), _item("dec_2")))
        feed.apply_update("resolved", _item("dec_1"))
        assert [i.decision_id for i in feed.items()] == ["dec_2"]
        assert feed.get("dec_1") is None

    def test_expiring_refreshes_in_place(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(_item("dec_1", urgency="normal")))
        feed.apply_update("expiring", _item("dec_1", urgency="expiring"))
        assert feed.count == 1
        assert feed.get("dec_1").urgency == "expiring"

    def test_unknown_change_upserts(self):
        feed = DecisionFeedController()
        feed.apply_update("weird", _item("dec_9"))
        assert feed.get("dec_9") is not None


class TestInterruptSplit:
    def test_blocking_and_expiring_interrupt(self):
        feed = DecisionFeedController()
        feed.apply_snapshot(_snapshot(
            _item("b", urgency="blocking"),
            _item("e", urgency="expiring"),
            _item("n", urgency="normal"),
            _item("i", urgency="info"),
        ))
        assert {i.decision_id for i in feed.interrupts()} == {"b", "e"}
        assert {i.decision_id for i in feed.accumulated()} == {"n", "i"}


class TestKeymap:
    def test_keymap_from_options_only(self):
        feed = DecisionFeedController()
        item = _item("dec_1", options=[
            {"key": "y", "label": "approve", "action": "approve"},
            {"key": "n", "label": "deny", "action": "deny"},
        ])
        keymap = feed.keymap_for(item)
        assert set(keymap) == {"y", "n"}
        assert keymap["y"].action == "approve"

    def test_duplicate_key_first_wins(self):
        feed = DecisionFeedController()
        item = _item("dec_1", options=[
            {"key": "y", "label": "approve", "action": "approve"},
            {"key": "y", "label": "shadow", "action": "evil"},
        ])
        keymap = feed.keymap_for(item)
        assert keymap["y"].action == "approve"

    def test_empty_key_ignored(self):
        feed = DecisionFeedController()
        item = _item("dec_1", options=[{"key": "", "label": "x", "action": "x"}])
        assert feed.keymap_for(item) == {}
